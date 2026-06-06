"""Module 9 — Multi-Agent Framework.

This module is intentionally self-contained: it defines the agent
abstraction, a registry with capability lookup and health tracking, and
a coordinator agent that decomposes a query into a multi-step plan,
distributes steps to the best agents, and aggregates the results.

Public surface
--------------
* ``BaseAgent``                — abstract base every agent inherits
* ``AgentExecutionEngine``     — async runtime: retries, timeouts, lifecycle
* ``AgentRegistry``            — CRUD + lookup
* ``CapabilityRegistry``       — capability → agents index
* ``AgentDiscoveryService``    — search / health-aware selection
* ``AgentMetadataStore``       — persistence (in-memory + JSONL)
* ``TaskPlanner``              — query → plan
* ``TaskDistributor``          — plan → per-step tasks
* ``ResultAggregator``         — results → final output
* ``CoordinatorAgent``         — top-level entry point
* ``AgentFrameworkService``    — DI facade
* ``build_default_agent_framework_service``
* Two ready-to-use agents:
  * ``EchoAgent`` — used by tests; returns a deterministic output
  * ``CapabilityAgent`` — generic agent driven by ``input`` mapping
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.core.config import settings
from app.schemas.agents import (
    AgentCapability,
    AgentContext,
    AgentDiscoveryQuery,
    AgentExecutionRequest,
    AgentHealthCheck,
    AgentMetadata,
    AgentRegistrationRequest,
    AgentResult,
    AgentStatus,
    AgentTask,
    CapabilityKind,
    CoordinatorPlan,
    CoordinatorRequest,
    CoordinatorResult,
    PaginatedAgents,
    PlanStep,
    TaskStatus,
)
from app.services.observability import (
    get_agent_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── BaseAgent ─────────────────────────────────────────────


class BaseAgent(ABC):
    """Abstract base for every agent in the framework.

    Concrete agents override :meth:`execute` (async) and may override
    :meth:`health` for custom probes. The framework handles retries,
    timeouts, status transitions and health tracking.
    """

    def __init__(self, metadata: AgentMetadata) -> None:
        self.metadata = metadata
        self._status: AgentStatus = AgentStatus.REGISTERED
        self._lock = threading.RLock()
        # Health bookkeeping
        self._consecutive_failures = 0
        self._total = 0
        self._successful = 0
        self._failed = 0
        self._total_duration_ms = 0.0
        self._last_invocation_at: Optional[float] = None
        self._last_success_at: Optional[float] = None
        self._last_failure_at: Optional[float] = None
        self._last_error: str = ""

    # ─── lifecycle ────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            self._status = AgentStatus.ACTIVE
            self.metadata.status = AgentStatus.ACTIVE
            self.metadata.updated_at = time.time()

    def pause(self) -> None:
        with self._lock:
            self._status = AgentStatus.PAUSED
            self.metadata.status = AgentStatus.PAUSED
            self.metadata.updated_at = time.time()

    def disable(self) -> None:
        with self._lock:
            self._status = AgentStatus.DISABLED
            self.metadata.status = AgentStatus.DISABLED
            self.metadata.updated_at = time.time()

    @property
    def status(self) -> AgentStatus:
        with self._lock:
            return self._status

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def agent_id(self) -> str:
        return self.metadata.agent_id

    # ─── capabilities ─────────────────────────────────────

    def supports(self, capability: CapabilityKind) -> bool:
        return any(c.kind == capability for c in self.metadata.capabilities)

    # ─── execution ────────────────────────────────────────

    @abstractmethod
    async def execute(self, task: AgentTask) -> AgentResult:
        """Run the agent on ``task`` and return a result."""

    # ─── health ───────────────────────────────────────────

    def health(self) -> AgentHealthCheck:
        with self._lock:
            avg = (
                self._total_duration_ms / self._total
                if self._total
                else 0.0
            )
            healthy = self._status in (
                AgentStatus.ACTIVE,
                AgentStatus.REGISTERED,
                AgentStatus.BUSY,
            ) and self._consecutive_failures < 5
            return AgentHealthCheck(
                agent_id=self.agent_id,
                healthy=healthy,
                last_error=self._last_error,
                consecutive_failures=self._consecutive_failures,
                total_invocations=self._total,
                successful_invocations=self._successful,
                failed_invocations=self._failed,
                average_duration_ms=round(avg, 3),
                last_invocation_at=self._last_invocation_at,
                last_success_at=self._last_success_at,
                last_failure_at=self._last_failure_at,
            )

    # ─── bookkeeping hooks (called by the engine) ────────

    def _record_success(self, duration_ms: float) -> None:
        with self._lock:
            self._total += 1
            self._successful += 1
            self._total_duration_ms += duration_ms
            self._consecutive_failures = 0
            self._last_success_at = time.time()
            self._last_invocation_at = self._last_success_at
            self._last_error = ""

    def _record_failure(
        self, error: str, duration_ms: float = 0.0
    ) -> None:
        with self._lock:
            self._total += 1
            self._failed += 1
            self._total_duration_ms += duration_ms
            self._consecutive_failures += 1
            self._last_failure_at = time.time()
            self._last_invocation_at = self._last_failure_at
            self._last_error = error

    def set_busy(self, busy: bool) -> None:
        with self._lock:
            if busy:
                self._status = AgentStatus.BUSY
            elif self._status == AgentStatus.BUSY:
                self._status = AgentStatus.ACTIVE
            self.metadata.status = self._status


# ─── Ready-to-use agents (used by tests and as fallbacks) ────


class EchoAgent(BaseAgent):
    """An agent that echoes ``input`` back inside ``output``."""

    async def execute(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            agent_name=self.name,
            status=TaskStatus.SUCCEEDED,
            output={
                "echo": task.input,
                "capability": task.capability.value,
            },
        )


class CapabilityAgent(BaseAgent):
    """An agent driven by a ``callable`` registered at construction.

    The callable receives the :class:`AgentTask` and returns either a
    :class:`AgentResult` (sync or async) or a plain ``dict`` (which is
    wrapped into a successful :class:`AgentResult`).
    """

    def __init__(
        self,
        metadata: AgentMetadata,
        handler: Callable[
            [AgentTask], Any
        ],
    ) -> None:
        super().__init__(metadata)
        self._handler = handler

    async def execute(self, task: AgentTask) -> AgentResult:
        ret = self._handler(task)
        if inspect.iscoroutine(ret):
            ret = await ret
        if isinstance(ret, AgentResult):
            ret.task_id = task.task_id
            ret.agent_id = self.agent_id
            ret.agent_name = self.name
            if ret.status == TaskStatus.SUCCEEDED:
                return ret
            return ret
        # dict / other → wrap
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            agent_name=self.name,
            status=TaskStatus.SUCCEEDED,
            output=ret if isinstance(ret, dict) else {"value": ret},
        )


# ─── AgentExecutionEngine ──────────────────────────────────


class AgentExecutionEngine:
    """Async runtime that wraps an agent with retries, timeouts, lifecycle."""

    async def run(
        self, agent: BaseAgent, task: AgentTask
    ) -> AgentResult:
        with track_request(
            endpoint="/api/v1/agents/execute",
            strategy="agent_execute",
        ):
            max_retries = max(
                task.max_retries,
                agent.metadata.default_max_retries,
            )
            timeout_ms = (
                task.timeout_ms
                if task.timeout_ms is not None
                else agent.metadata.default_timeout_ms
            )
            # Apply the smaller of the task/agent default
            timeout_s = max(0.1, timeout_ms / 1000.0)

            last_error = ""
            attempts = 0
            started = time.time()
            agent.set_busy(True)
            try:
                for attempt in range(max_retries + 1):
                    attempts = attempt + 1
                    attempt_started = time.time()
                    try:
                        result = await asyncio.wait_for(
                            agent.execute(task),
                            timeout=timeout_s,
                        )
                        duration_ms = (
                            time.time() - attempt_started
                        ) * 1000.0
                        agent._record_success(duration_ms)
                        result.attempts = attempts
                        result.started_at = attempt_started
                        result.completed_at = time.time()
                        result.duration_ms = round(duration_ms, 3)
                        if attempts > 1:
                            get_agent_metrics().record_retry(
                                agent.metadata.name
                            )
                        get_agent_metrics().record_execution(
                            agent.metadata.name,
                            capability=task.capability.value,
                            status="succeeded",
                            duration_ms=result.duration_ms,
                        )
                        return result
                    except asyncio.TimeoutError:
                        last_error = f"timeout after {timeout_ms}ms"
                        duration_ms = timeout_ms
                        agent._record_failure(last_error, duration_ms)
                        get_agent_metrics().record_execution(
                            agent.metadata.name,
                            capability=task.capability.value,
                            status="timed_out",
                            duration_ms=duration_ms,
                        )
                        # Retryable
                        if attempt < max_retries:
                            get_agent_metrics().record_retry(
                                agent.metadata.name
                            )
                            continue
                        return AgentResult(
                            task_id=task.task_id,
                            agent_id=agent.agent_id,
                            agent_name=agent.metadata.name,
                            status=TaskStatus.TIMED_OUT,
                            error=last_error,
                            attempts=attempts,
                            started_at=attempt_started,
                            completed_at=time.time(),
                            duration_ms=round(duration_ms, 3),
                        )
                    except Exception as exc:  # noqa: BLE001
                        last_error = str(exc)
                        duration_ms = (
                            time.time() - attempt_started
                        ) * 1000.0
                        agent._record_failure(last_error, duration_ms)
                        get_agent_metrics().record_execution(
                            agent.metadata.name,
                            capability=task.capability.value,
                            status="failed",
                            duration_ms=duration_ms,
                        )
                        if attempt < max_retries:
                            get_agent_metrics().record_retry(
                                agent.metadata.name
                            )
                            continue
                        return AgentResult(
                            task_id=task.task_id,
                            agent_id=agent.agent_id,
                            agent_name=agent.metadata.name,
                            status=TaskStatus.FAILED,
                            error=last_error,
                            attempts=attempts,
                            started_at=attempt_started,
                            completed_at=time.time(),
                            duration_ms=round(duration_ms, 3),
                        )
                # Should not reach here
                return AgentResult(
                    task_id=task.task_id,
                    agent_id=agent.agent_id,
                    agent_name=agent.metadata.name,
                    status=TaskStatus.FAILED,
                    error=last_error or "unknown",
                    attempts=attempts,
                )
            finally:
                agent.set_busy(False)
                get_agent_metrics().record_coordination_step(
                    duration_ms=(time.time() - started) * 1000.0
                )


# ─── Metadata store (in-memory + JSONL) ────────────────────


class AgentMetadataStore:
    """Thread-safe metadata persistence."""

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._agents: Dict[str, AgentMetadata] = {}
        self._by_name: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def upsert(self, meta: AgentMetadata) -> None:
        with self._lock:
            self._agents[meta.agent_id] = meta
            self._by_name[meta.name] = meta.agent_id
            self._persist()

    def get(self, agent_id: str) -> Optional[AgentMetadata]:
        with self._lock:
            return self._agents.get(agent_id)

    def get_by_name(self, name: str) -> Optional[AgentMetadata]:
        with self._lock:
            aid = self._by_name.get(name)
            return self._agents.get(aid) if aid else None

    def list(self) -> List[AgentMetadata]:
        with self._lock:
            return sorted(
                self._agents.values(),
                key=lambda m: (-m.priority, m.name),
            )

    def delete(self, agent_id: str) -> bool:
        with self._lock:
            meta = self._agents.pop(agent_id, None)
            if meta is None:
                return False
            self._by_name.pop(meta.name, None)
            self._persist()
            return True

    # ─── persistence ──────────────────────────────────────

    def _persist(self) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(
                os.path.dirname(self._persist_path), exist_ok=True
            )
            payload = {
                "agents": [
                    json.loads(m.model_dump_json())
                    for m in self._agents.values()
                ],
            }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        except Exception:  # pragma: no cover
            logger.exception("Failed to persist agent metadata")

    def _load(self) -> None:
        if not self._persist_path or not os.path.exists(
            self._persist_path
        ):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            for raw in payload.get("agents", []):
                m = AgentMetadata(**raw)
                self._agents[m.agent_id] = m
                self._by_name[m.name] = m.agent_id
        except Exception:  # pragma: no cover
            logger.exception("Failed to load agent metadata")


# ─── AgentRegistry ────────────────────────────────────────


class AgentRegistry:
    """In-memory registry of :class:`BaseAgent` + their metadata."""

    def __init__(self, store: AgentMetadataStore) -> None:
        self._instances: Dict[str, BaseAgent] = {}
        self._instances_by_name: Dict[str, str] = {}
        self._store = store

    # ─── registration ────────────────────────────────────

    def register(
        self,
        request: AgentRegistrationRequest,
        agent: BaseAgent,
    ) -> AgentMetadata:
        # If an agent with the same name already exists, replace
        # the instance but keep the agent_id stable
        existing = self._store.get_by_name(request.name)
        if existing is not None:
            agent.metadata = existing.model_copy(
                update={
                    "description": request.description
                    or existing.description,
                    "version": request.version or existing.version,
                    "author": request.author or existing.author,
                    "capabilities": request.capabilities
                    or existing.capabilities,
                    "default_max_retries": request.default_max_retries,
                    "default_timeout_ms": request.default_timeout_ms,
                    "priority": request.priority,
                    "tags": request.tags or existing.tags,
                    "updated_at": time.time(),
                }
            )
            meta = agent.metadata
        else:
            agent.metadata = AgentMetadata(
                name=request.name,
                description=request.description,
                version=request.version,
                author=request.author,
                capabilities=request.capabilities,
                default_max_retries=request.default_max_retries,
                default_timeout_ms=request.default_timeout_ms,
                priority=request.priority,
                tags=request.tags,
                metadata=request.metadata,
            )
            meta = agent.metadata
        self._store.upsert(meta)
        self._instances[meta.agent_id] = agent
        self._instances_by_name[meta.name] = meta.agent_id
        get_agent_metrics().record_registration(meta.name)
        return meta

    def unregister(self, name: str) -> bool:
        meta = self._store.get_by_name(name)
        if meta is None:
            return False
        self._instances.pop(meta.agent_id, None)
        self._instances_by_name.pop(meta.name, None)
        return self._store.delete(meta.agent_id)

    # ─── lookup ──────────────────────────────────────────

    def get(self, name: str) -> Optional[BaseAgent]:
        meta = self._store.get_by_name(name)
        if meta is None:
            return None
        return self._instances.get(meta.agent_id)

    def get_metadata(self, name: str) -> Optional[AgentMetadata]:
        return self._store.get_by_name(name)

    def list_all(self) -> List[AgentMetadata]:
        return self._store.list()

    def list_instances(self) -> List[BaseAgent]:
        return [
            self._instances[m.agent_id]
            for m in self._store.list()
            if m.agent_id in self._instances
        ]

    def count(self) -> int:
        return len(self._instances)


# ─── CapabilityRegistry ──────────────────────────────────


class CapabilityRegistry:
    """Capability → list of agent names (sorted by priority)."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def by_capability(
        self, capability: CapabilityKind
    ) -> List[AgentMetadata]:
        out: List[AgentMetadata] = []
        for m in self._registry.list_all():
            if any(c.kind == capability for c in m.capabilities):
                out.append(m)
        out.sort(key=lambda m: (-m.priority, m.name))
        return out

    def best_match(
        self, capability: CapabilityKind
    ) -> Optional[AgentMetadata]:
        matches = self.by_capability(capability)
        return matches[0] if matches else None

    def all_capabilities(self) -> Dict[CapabilityKind, List[str]]:
        out: Dict[CapabilityKind, List[str]] = {}
        for m in self._registry.list_all():
            for c in m.capabilities:
                out.setdefault(c.kind, []).append(m.name)
        return out


# ─── AgentDiscoveryService ────────────────────────────────


class AgentDiscoveryService:
    """Search agents by capability / text / tag / health."""

    def __init__(
        self,
        registry: AgentRegistry,
        capability_registry: CapabilityRegistry,
    ) -> None:
        self._registry = registry
        self._capability_registry = capability_registry

    def search(self, query: AgentDiscoveryQuery) -> PaginatedAgents:
        items: List[AgentMetadata] = []
        for meta in self._registry.list_all():
            if query.capability is not None:
                if not any(
                    c.kind == query.capability for c in meta.capabilities
                ):
                    continue
            if query.tag:
                if query.tag not in meta.tags:
                    continue
            if query.text_query:
                q = query.text_query.lower()
                haystack = " ".join(
                    [meta.name, meta.description, " ".join(meta.tags)]
                ).lower()
                if q not in haystack:
                    continue
            if query.healthy_only:
                agent = self._registry.get(meta.name)
                if agent is None or not agent.health().healthy:
                    continue
            items.append(meta)
        total = len(items)
        start = (query.page - 1) * query.page_size
        end = start + query.page_size
        return PaginatedAgents(
            items=items[start:end],
            total=total,
            page=query.page,
            page_size=query.page_size,
            has_more=end < total,
        )

    def select(
        self,
        capability: CapabilityKind,
        *,
        prefer_healthy: bool = True,
    ) -> Optional[BaseAgent]:
        candidates = self._capability_registry.by_capability(capability)
        if not candidates:
            return None
        if prefer_healthy:
            for meta in candidates:
                agent = self._registry.get(meta.name)
                if agent is not None and agent.health().healthy:
                    return agent
        # Fallback to the highest-priority agent
        return self._registry.get(candidates[0].name)


# ─── TaskPlanner ──────────────────────────────────────────


class TaskPlanner:
    """Translate a free-form query into a multi-step plan.

    The planner is intentionally deterministic and dependency-free: it
    maps the requested capabilities to ordered steps and records
    per-step retry/timeout hints.
    """

    def plan(
        self,
        request: CoordinatorRequest,
    ) -> CoordinatorPlan:
        caps = list(request.desired_capabilities) or self._infer_caps(
            request.query
        )
        steps: List[PlanStep] = []
        for i, cap in enumerate(caps[: request.max_steps]):
            steps.append(
                PlanStep(
                    capability=cap,
                    description=f"step {i+1}: {cap.value}",
                    input={"query": request.query, "step_index": i},
                    depends_on=(
                        [steps[-1].step_id] if steps else []
                    ),
                )
            )
        selected_agents: List[str] = []
        for s in steps:
            # We can't actually pick agents here (no registry access),
            # but we annotate with a hint
            s.target_agent = s.target_agent or ""
        return CoordinatorPlan(
            query=request.query,
            steps=steps,
            selected_agents=selected_agents,
            rationale=(
                f"planned {len(steps)} step(s) for capabilities "
                f"{[c.value for c in caps]}"
            ),
            metadata={"max_steps": request.max_steps},
        )

    @staticmethod
    def _infer_caps(query: str) -> List[CapabilityKind]:
        """Map common keywords to capabilities.

        This is a deliberately small heuristic; richer planning can
        be added later without changing the planner's contract.
        """
        q = query.lower()
        caps: List[CapabilityKind] = []
        if any(
            w in q for w in ["search", "find", "retrieve", "document"]
        ):
            caps.append(CapabilityKind.RETRIEVAL)
        if any(w in q for w in ["reason", "analyze", "compare"]):
            caps.append(CapabilityKind.REASONING)
        if any(
            w in q for w in ["risk", "compliance", "regulatory"]
        ):
            caps.append(CapabilityKind.RISK_ASSESSMENT)
        if any(w in q for w in ["recommend", "suggest"]):
            caps.append(CapabilityKind.RECOMMENDATION)
        if any(w in q for w in ["forecast", "predict", "trend"]):
            caps.append(CapabilityKind.FORECASTING)
        if any(w in q for w in ["graph", "entity", "relationship"]):
            caps.append(CapabilityKind.KNOWLEDGE_GRAPH)
        if any(w in q for w in ["change", "diff"]):
            caps.append(CapabilityKind.CHANGE_DETECTION)
        if any(w in q for w in ["impact"]):
            caps.append(CapabilityKind.IMPACT_ANALYSIS)
        if any(w in q for w in ["summarize", "summary"]):
            caps.append(CapabilityKind.SUMMARIZATION)
        if not caps:
            caps.append(CapabilityKind.REASONING)
        return caps


# ─── TaskDistributor ──────────────────────────────────────


class TaskDistributor:
    """Turn a :class:`CoordinatorPlan` into a list of :class:`AgentTask`."""

    def __init__(self, discovery: AgentDiscoveryService) -> None:
        self._discovery = discovery

    def distribute(
        self,
        plan: CoordinatorPlan,
        context: AgentContext,
    ) -> List[AgentTask]:
        tasks: List[AgentTask] = []
        for step in plan.steps:
            agent = self._discovery.select(
                step.capability, prefer_healthy=True
            )
            target = step.target_agent or (agent.name if agent else "")
            tasks.append(
                AgentTask(
                    capability=step.capability,
                    input=step.input,
                    context=context,
                    depends_on=step.depends_on,
                    max_retries=step.max_retries,
                    timeout_ms=step.timeout_ms,
                    target_agent=target,
                )
            )
            if target and target not in plan.selected_agents:
                plan.selected_agents.append(target)
        return tasks


# ─── ResultAggregator ─────────────────────────────────────


class ResultAggregator:
    """Aggregate per-step :class:`AgentResult` into a final output."""

    def aggregate(
        self,
        plan: CoordinatorPlan,
        results: List[AgentResult],
    ) -> CoordinatorResult:
        successful = [
            r for r in results if r.status == TaskStatus.SUCCEEDED
        ]
        failed = [r for r in results if r.status != TaskStatus.SUCCEEDED]
        # Conflict resolution: prefer the most-recent successful result
        # per (capability, key) tuple. Here we just collect outputs.
        merged: Dict[str, Any] = {
            "query": plan.query,
            "plan_id": plan.plan_id,
            "step_count": len(results),
            "successful_count": len(successful),
            "failed_count": len(failed),
            "outputs": [r.output for r in successful],
            "errors": [
                {"agent": r.agent_name, "error": r.error}
                for r in failed
            ],
        }
        # If there is exactly one successful result, hoist its output
        if len(successful) == 1:
            merged["primary_output"] = successful[0].output
        status = (
            TaskStatus.SUCCEEDED
            if not failed
            else (TaskStatus.SUCCEEDED if successful else TaskStatus.FAILED)
        )
        duration_ms = sum(r.duration_ms for r in results)
        return CoordinatorResult(
            plan_id=plan.plan_id,
            query=plan.query,
            selected_agents=list(plan.selected_agents),
            step_results=results,
            final_output=merged,
            status=status,
            duration_ms=round(duration_ms, 3),
            conflicts_resolved=max(0, len(successful) - 1),
            notes=(
                ""
                if not failed
                else f"{len(failed)} of {len(results)} step(s) failed"
            ),
        )


# ─── CoordinatorAgent ────────────────────────────────────


class CoordinatorAgent:
    """Top-level entry point that ties planner, distributor, engine and
    aggregator together.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        discovery: AgentDiscoveryService,
        engine: AgentExecutionEngine,
    ) -> None:
        self._registry = registry
        self._discovery = discovery
        self._engine = engine
        self._planner = TaskPlanner()
        self._distributor = TaskDistributor(discovery)
        self._aggregator = ResultAggregator()

    async def coordinate(
        self, request: CoordinatorRequest
    ) -> CoordinatorResult:
        with track_request(
            endpoint="/api/v1/agents/coordinate",
            strategy="coordinator",
        ):
            started = time.time()
            plan = self._planner.plan(request)
            tasks = self._distributor.distribute(plan, request.context)
            # Run the steps sequentially respecting depends_on.
            # We keep it simple: run all eligible steps in order,
            # skipping those whose target_agent cannot be found.
            results: List[AgentResult] = []
            for task in tasks:
                agent = (
                    self._registry.get(task.target_agent)
                    if task.target_agent
                    else self._discovery.select(
                        task.capability, prefer_healthy=True
                    )
                )
                if agent is None:
                    results.append(
                        AgentResult(
                            task_id=task.task_id,
                            agent_id="",
                            agent_name=task.target_agent,
                            status=TaskStatus.FAILED,
                            error=(
                                f"no agent available for capability "
                                f"{task.capability.value}"
                            ),
                        )
                    )
                    continue
                result = await self._engine.run(agent, task)
                results.append(result)
                if (
                    result.status
                    == TaskStatus.FAILED
                    and task.max_retries == 0
                ):
                    # Continue executing the rest of the plan so that
                    # the caller gets a complete picture.
                    continue
            final = self._aggregator.aggregate(plan, results)
            final.started_at = started
            final.completed_at = time.time()
            final.duration_ms = round(
                (final.completed_at - started) * 1000.0, 3
            )
            get_agent_metrics().record_coordination(
                plan=plan,
                final_status=final.status.value,
            )
            return final


# ─── AgentFrameworkService (DI facade) ────────────────────


class AgentFrameworkService:
    """Single point of entry for the agent framework."""

    def __init__(
        self,
        store: AgentMetadataStore,
    ) -> None:
        self.store = store
        self.engine = AgentExecutionEngine()
        self.registry = AgentRegistry(store)
        self.capability_registry = CapabilityRegistry(self.registry)
        self.discovery = AgentDiscoveryService(
            self.registry, self.capability_registry
        )
        self.coordinator = CoordinatorAgent(
            self.registry, self.discovery, self.engine
        )
        # Seed a single EchoAgent so the framework is usable out of
        # the box for demos and tests.
        self._seed_default_agents()

    # ─── seeding ────────────────────────────────────────

    def _seed_default_agents(self) -> None:
        try:
            existing = self.registry.get_metadata("echo-agent")
            if existing is not None:
                # Ensure the in-process instance exists too. The
                # metadata store is persisted to disk but the
                # in-process instance map is empty after a restart.
                if self.registry.get("echo-agent") is None:
                    instance = EchoAgent(existing)
                    self.registry._instances[existing.agent_id] = (
                        instance
                    )
                    self.registry._instances_by_name[existing.name] = (
                        existing.agent_id
                    )
                return
            self.register(
                AgentRegistrationRequest(
                    name="echo-agent",
                    description=(
                        "Trivial agent that echoes its input back. "
                        "Useful for testing."
                    ),
                    capabilities=[
                        AgentCapability(
                            kind=CapabilityKind.OTHER,
                            name="echo",
                            description="echoes task.input",
                        )
                    ],
                    tags=["built-in", "test"],
                ),
                EchoAgent(
                    AgentMetadata(
                        name="echo-agent",
                        capabilities=[
                            AgentCapability(
                                kind=CapabilityKind.OTHER,
                                name="echo",
                            )
                        ],
                    )
                ),
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to seed echo agent")

    # ─── registration helpers ───────────────────────────

    def register(
        self,
        request: AgentRegistrationRequest,
        agent: BaseAgent,
    ) -> AgentMetadata:
        return self.registry.register(request, agent)

    def unregister(self, name: str) -> bool:
        return self.registry.unregister(name)

    # ─── discovery ──────────────────────────────────────

    def list_agents(self) -> List[AgentMetadata]:
        return self.registry.list_all()

    def get_agent(self, name: str) -> Optional[AgentMetadata]:
        return self.registry.get_metadata(name)

    def get_agent_instance(self, name: str) -> Optional[BaseAgent]:
        return self.registry.get(name)

    def search_agents(
        self, query: AgentDiscoveryQuery
    ) -> PaginatedAgents:
        return self.discovery.search(query)

    def health(self, name: str) -> Optional[AgentHealthCheck]:
        agent = self.registry.get(name)
        return agent.health() if agent else None

    # ─── execution ─────────────────────────────────────

    async def execute(
        self, request: AgentExecutionRequest
    ) -> AgentResult:
        agent = self.registry.get(request.agent_name)
        if agent is None:
            return AgentResult(
                task_id="",
                agent_id="",
                agent_name=request.agent_name,
                status=TaskStatus.FAILED,
                error=f"agent '{request.agent_name}' not found",
            )
        task = AgentTask(
            capability=request.capability,
            input=request.input,
            context=request.context,
            max_retries=request.max_retries or 0,
            timeout_ms=request.timeout_ms,
            target_agent=request.agent_name,
        )
        return await self.engine.run(agent, task)

    async def coordinate(
        self, request: CoordinatorRequest
    ) -> CoordinatorResult:
        return await self.coordinator.coordinate(request)


# ─── Default factory ─────────────────────────────────────


def build_default_agent_framework_service() -> AgentFrameworkService:
    """Build a default :class:`AgentFrameworkService` with JSONL persistence."""
    persist_path = os.path.join(
        settings.STORAGE_ROOT, "agents", "agents.jsonl"
    )
    store = AgentMetadataStore(persist_path=persist_path)
    return AgentFrameworkService(store)


__all__ = [
    "BaseAgent",
    "EchoAgent",
    "CapabilityAgent",
    "AgentExecutionEngine",
    "AgentMetadataStore",
    "AgentRegistry",
    "CapabilityRegistry",
    "AgentDiscoveryService",
    "TaskPlanner",
    "TaskDistributor",
    "ResultAggregator",
    "CoordinatorAgent",
    "AgentFrameworkService",
    "build_default_agent_framework_service",
]
