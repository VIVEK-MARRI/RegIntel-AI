"""Module 9.8 — Multi-Agent Orchestration Platform.

Coordinates multiple agents collaboratively. REUSES the existing M9
framework (agent registry, coordinator, message bus, evidence store) and
the M9.4-9.7 intelligence agents (research / compliance / risk / audit).

Public surface
--------------
* ``AgentMessageBus``             — pub/sub for agent messages
* ``SharedEvidenceStore``         — evidence shared across agents
* ``ExecutionContextManager``     — central context lifecycle
* ``CapabilityBasedRouter``       — capability → agent routing
* ``AgentSelectionPolicy``        — strategy for picking agents
* ``AgentOrchestrator``           — top-level orchestrator
* ``OrchestrationEngine``         — async runtime (parallel/sequential)
* ``TaskCoordinator``             — dispatches steps to agents
* ``ResultSynthesizer``           — merges results, resolves conflicts
* ``ConsensusBuilder``            — weighted consensus on outputs
* ``ConflictResolver``            — picks authoritative values
* ``EvidenceAggregator``          — merges evidence across agents
* ``AgentWorkflowManager``        — re-runnable workflow specs
* ``OrchestrationService``        — DI facade
* ``build_default_orchestration_service``
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.schemas.agents import (
    AgentContext,
    AgentExecutionRequest,
    AgentResult,
    AgentTask,
    CapabilityKind,
    TaskStatus,
)
from app.schemas.orchestration import (
    AgentContribution,
    AgentExecutionGraph,
    AgentExecutionStep,
    AgentMessage,
    AgentWorkflow,
    ExecutionMode,
    MessageKind,
    OrchestrationMetricsSummary,
    OrchestrationRequest,
    OrchestrationResult,
    SharedEvidenceItem,
    SharedExecutionContext,
    WorkflowDefinition,
    WorkflowStatus,
)
from app.services.observability import track_request

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Shared utilities
# ═══════════════════════════════════════════════════════════════════════


def _now() -> float:
    return time.time()


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


# ═══════════════════════════════════════════════════════════════════════
# Message bus + evidence store
# ═══════════════════════════════════════════════════════════════════════


class AgentMessageBus:
    """In-memory pub/sub message bus for agent-to-agent communication.

    Topic routing is by ``to_agent``. Subscribers register a callback
    that receives :class:`AgentMessage`. The bus keeps a bounded history
    of recent messages (default 500) for inspection.
    """

    def __init__(self, max_history: int = 500) -> None:
        self._subs: Dict[str, List[Callable[[AgentMessage], None]]] = (
            defaultdict(list)
        )
        self._lock = threading.RLock()
        self._history: List[AgentMessage] = []
        self._max_history = max_history
        self._metrics_counter = 0

    def subscribe(
        self,
        agent: str,
        callback: Callable[[AgentMessage], None],
    ) -> None:
        with self._lock:
            self._subs[agent].append(callback)

    def unsubscribe(
        self,
        agent: str,
        callback: Callable[[AgentMessage], None],
    ) -> None:
        with self._lock:
            if agent in self._subs and callback in self._subs[agent]:
                self._subs[agent].remove(callback)

    def publish(self, message: AgentMessage) -> int:
        delivered = 0
        with self._lock:
            self._history.append(message)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]
            self._metrics_counter += 1
            cbs = list(
                self._subs.get(message.to_agent, [])
                + self._subs.get("*", [])
            )
        for cb in cbs:
            try:
                cb(message)
                delivered += 1
            except Exception:  # pragma: no cover
                logger.exception("Message bus subscriber raised")
        return delivered

    def history(
        self,
        *,
        from_agent: Optional[str] = None,
        to_agent: Optional[str] = None,
        limit: int = 100,
    ) -> List[AgentMessage]:
        with self._lock:
            items = list(self._history)
        if from_agent:
            items = [m for m in items if m.from_agent == from_agent]
        if to_agent:
            items = [m for m in items if m.to_agent == to_agent]
        return items[-limit:]

    @property
    def message_count(self) -> int:
        with self._lock:
            return self._metrics_counter

    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._metrics_counter = 0


class SharedEvidenceStore:
    """Thread-safe store for evidence shared between agents."""

    def __init__(self) -> None:
        self._items: List[SharedEvidenceItem] = []
        self._lock = threading.RLock()

    def add(self, item: SharedEvidenceItem) -> None:
        with self._lock:
            self._items.append(item)

    def for_consumer(self, consumer: str) -> List[SharedEvidenceItem]:
        with self._lock:
            return [
                it
                for it in self._items
                if it.consumer in ("", "*", consumer)
            ]

    def all(self) -> List[SharedEvidenceItem]:
        with self._lock:
            return list(self._items)

    def by_producer(self, producer: str) -> List[SharedEvidenceItem]:
        with self._lock:
            return [it for it in self._items if it.producer == producer]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class ExecutionContextManager:
    """Manages a single :class:`SharedExecutionContext` for one
    orchestration. Provides ``read`` / ``write`` helpers and a snapshot
    mechanism for downstream agents.
    """

    def __init__(self, context: SharedExecutionContext) -> None:
        self.context = context

    def add_evidence(self, item: SharedEvidenceItem) -> None:
        self.context.evidence.append(item)

    def write_memory(self, key: str, value: Any) -> None:
        self.context.memory[key] = value

    def read_memory(self, key: str, default: Any = None) -> Any:
        return self.context.memory.get(key, default)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "context_id": self.context.context_id,
            "session_id": self.context.session_id,
            "actor": self.context.actor,
            "timeout_ms": self.context.timeout_ms,
            "evidence_keys": [e.evidence_id for e in self.context.evidence],
            "memory_keys": list(self.context.memory.keys()),
        }


# ═══════════════════════════════════════════════════════════════════════
# Routing
# ═══════════════════════════════════════════════════════════════════════


class AgentSelectionPolicy:
    """Pluggable policy for selecting which agent runs a step."""

    def __init__(self, *, prefer_healthy: bool = True) -> None:
        self.prefer_healthy = prefer_healthy

    def select(
        self,
        step: AgentExecutionStep,
        candidates: List[Any],
    ) -> Optional[Any]:
        if not candidates:
            return None
        if step.agent_name and step.agent_name != "*":
            for a in candidates:
                if a.name == step.agent_name:
                    return a
        # Fall back to first healthy
        for a in candidates:
            if (
                self.prefer_healthy
                and hasattr(a, "health")
                and a.health().healthy
            ):
                return a
        return candidates[0]


class CapabilityBasedRouter:
    """Maps a capability string to a list of candidate agents."""

    _CAPABILITY_TO_KIND: Dict[str, CapabilityKind] = {
        "research": CapabilityKind.RETRIEVAL,
        "retrieval": CapabilityKind.RETRIEVAL,
        "compliance": CapabilityKind.COMPLIANCE,
        "risk": CapabilityKind.RISK_ASSESSMENT,
        "audit": CapabilityKind.AUDIT,
        "governance": CapabilityKind.GOVERNANCE,
        "reasoning": CapabilityKind.REASONING,
        "forecasting": CapabilityKind.FORECASTING,
        "recommendation": CapabilityKind.RECOMMENDATION,
        "orchestration": CapabilityKind.ORCHESTRATION,
    }

    def __init__(self, framework_service: Any) -> None:
        self._framework = framework_service

    def candidates_for(self, step: AgentExecutionStep) -> List[Any]:
        agents = list(self._framework.registry.list_instances())
        if step.agent_name and step.agent_name != "*":
            for a in agents:
                if a.name == step.agent_name:
                    return [a]
        kind = self._CAPABILITY_TO_KIND.get(step.capability.lower())
        if kind is None:
            return agents
        matches: List[Any] = []
        for a in agents:
            if a.supports(kind):
                matches.append(a)
        return matches or agents


# ═══════════════════════════════════════════════════════════════════════
# Conflict resolution / consensus / aggregation
# ═══════════════════════════════════════════════════════════════════════


class ConflictResolver:
    """Picks a single authoritative value from many candidate values.

    Strategy: prefer the highest-confidence candidate. Ties are broken
    by lexicographic ordering of the value to keep the result stable.
    """

    @staticmethod
    def resolve(
        values: List[Tuple[str, float]],
    ) -> Tuple[Optional[str], int]:
        if not values:
            return None, 0
        # Sort by (-confidence, value) and pick first
        sorted_v = sorted(
            values, key=lambda x: (-x[1], x[0])
        )
        winner = sorted_v[0]
        conflicts = max(0, len(values) - 1)
        return winner[0], conflicts


class ConsensusBuilder:
    """Computes a 0..1 consensus score from a list of (value, confidence)
    tuples. Higher when the agents agree on the same value.
    """

    @staticmethod
    def score(values: List[Tuple[str, float]]) -> float:
        if not values:
            return 0.0
        from collections import Counter

        counter = Counter([v[0] for v in values])
        top, _ = counter.most_common(1)[0]
        agreements = sum(
            c for v, c in counter.items() if v == top
        )
        return _clamp(agreements / len(values))


class EvidenceAggregator:
    """Merges evidence items from many agents into a deduplicated
    list (keyed by ``evidence_id``).
    """

    @staticmethod
    def merge(
        items_per_agent: Dict[str, List[SharedEvidenceItem]],
    ) -> List[SharedEvidenceItem]:
        merged: Dict[str, SharedEvidenceItem] = {}
        for _agent, items in items_per_agent.items():
            for it in items:
                if it.evidence_id not in merged:
                    merged[it.evidence_id] = it
        return list(merged.values())


# ═══════════════════════════════════════════════════════════════════════
# Result synthesizer
# ═══════════════════════════════════════════════════════════════════════


class ResultSynthesizer:
    """Combines the per-agent :class:`AgentContribution` into a final
    ``final_output`` dict and computes a weighted confidence score.
    """

    def __init__(
        self,
        *,
        consensus_builder: Optional[ConsensusBuilder] = None,
        conflict_resolver: Optional[ConflictResolver] = None,
    ) -> None:
        self.consensus_builder = consensus_builder or ConsensusBuilder
        self.conflict_resolver = conflict_resolver or ConflictResolver

    def synthesize(
        self,
        query: str,
        contributions: List[AgentContribution],
        evidence: List[SharedEvidenceItem],
    ) -> Tuple[Dict[str, Any], float, float, int]:
        if not contributions:
            return {"summary": "no agent produced output"}, 0.0, 0.0, 0
        # 1) Confidence = confidence-weighted average (failures contribute 0)
        weights: List[float] = []
        values: List[float] = []
        for c in contributions:
            if c.status == "succeeded" and c.confidence > 0:
                weights.append(c.confidence)
                values.append(c.confidence)
        avg_conf = sum(values) / max(1, len(values)) if values else 0.0
        # 2) Consensus: look at all summary strings
        summary_pairs = [
            (c.summary or "", c.confidence) for c in contributions
        ]
        consensus = self.consensus_builder.score(summary_pairs)
        # 3) Conflict resolution: pick the most-confident summary
        resolved, conflicts = self.conflict_resolver.resolve(
            summary_pairs
        )
        final_output = {
            "query": query,
            "agent_count": len(contributions),
            "successful_count": sum(
                1 for c in contributions if c.status == "succeeded"
            ),
            "primary_summary": resolved
            or (contributions[0].summary if contributions else ""),
            "primary_output": next(
                (
                    c.output
                    for c in contributions
                    if c.status == "succeeded"
                ),
                {},
            ),
            "evidence_count": len(evidence),
            "evidence_ids": [e.evidence_id for e in evidence],
            "consensus_score": round(consensus, 4),
            "confidence": round(_clamp(avg_conf), 4),
        }
        return final_output, round(avg_conf, 4), round(consensus, 4), conflicts


# ═══════════════════════════════════════════════════════════════════════
# Task coordinator + engine
# ═══════════════════════════════════════════════════════════════════════


class TaskCoordinator:
    """Dispatches :class:`AgentExecutionStep` to a resolved agent."""

    def __init__(
        self,
        *,
        framework_service: Any,
        router: CapabilityBasedRouter,
        policy: Optional[AgentSelectionPolicy] = None,
    ) -> None:
        self._framework = framework_service
        self._router = router
        self._policy = policy or AgentSelectionPolicy()

    async def dispatch(
        self,
        step: AgentExecutionStep,
        query: str,
        context: SharedExecutionContext,
    ) -> Tuple[Optional[Any], AgentExecutionStep]:
        candidates = self._router.candidates_for(step)
        agent = self._policy.select(step, candidates)
        # Ensure the step's target_agent is filled in
        if agent is not None:
            step.agent_name = agent.name
        return agent, step


class OrchestrationEngine:
    """Async runtime that runs an :class:`AgentExecutionGraph`."""

    def __init__(
        self,
        *,
        framework_service: Any,
        coordinator: TaskCoordinator,
    ) -> None:
        self._framework = framework_service
        self._coordinator = coordinator

    async def run_step(
        self,
        agent: Any,
        step: AgentExecutionStep,
        query: str,
        context: SharedExecutionContext,
    ) -> AgentContribution:
        started = _now()
        if agent is None:
            return AgentContribution(
                agent_name=step.agent_name or "unknown",
                status="failed",
                error="no agent available",
                started_at=started,
                completed_at=_now(),
            )
        task = AgentTask(
            capability=self._coerce_capability(step.capability),
            input={
                "query": query,
                "step": step.model_dump(mode="json"),
                "context": context.model_dump(mode="json"),
                **step.input_template,
            },
            context=AgentContext(
                session_id=context.session_id,
                actor=context.actor,
                timeout_ms=step.timeout_ms or context.timeout_ms,
                metadata={"step_id": step.step_id},
            ),
            max_retries=step.max_retries,
            timeout_ms=step.timeout_ms or context.timeout_ms,
            target_agent=agent.name,
        )
        try:
            request = AgentExecutionRequest(
                agent_name=agent.name,
                capability=task.capability,
                input=task.input,
                context=task.context,
                max_retries=task.max_retries,
                timeout_ms=task.timeout_ms,
            )
            result: AgentResult = await self._framework.execute(
                request
            )
            duration = (_now() - started) * 1000.0
            if result.status != TaskStatus.SUCCEEDED:
                return AgentContribution(
                    agent_name=agent.name,
                    status="failed",
                    error=result.error or "agent failed",
                    output=result.output,
                    duration_ms=duration,
                    started_at=started,
                    completed_at=_now(),
                    attempts=result.attempts,
                )
            return AgentContribution(
                agent_name=agent.name,
                status="succeeded",
                output=result.output,
                confidence=self._extract_confidence(result.output),
                duration_ms=duration,
                started_at=started,
                completed_at=_now(),
                attempts=result.attempts,
                summary=self._extract_summary(result.output),
            )
        except Exception as exc:  # pragma: no cover
            duration = (_now() - started) * 1000.0
            return AgentContribution(
                agent_name=agent.name,
                status="failed",
                error=str(exc),
                duration_ms=duration,
                started_at=started,
                completed_at=_now(),
            )

    @staticmethod
    def _coerce_capability(text: str) -> CapabilityKind:
        try:
            return CapabilityKind(text)
        except ValueError:
            mapping = {
                "research": CapabilityKind.RETRIEVAL,
                "compliance": CapabilityKind.COMPLIANCE,
                "risk": CapabilityKind.RISK_ASSESSMENT,
                "audit": CapabilityKind.AUDIT,
                "governance": CapabilityKind.GOVERNANCE,
                "forecasting": CapabilityKind.FORECASTING,
                "recommendation": CapabilityKind.RECOMMENDATION,
            }
            return mapping.get(text.lower(), CapabilityKind.REASONING)

    @staticmethod
    def _extract_confidence(output: Dict[str, Any]) -> float:
        if not isinstance(output, dict):
            return 0.5
        return _clamp(
            output.get("confidence", 0.5)
            or output.get("final_confidence", 0.5)
        )

    @staticmethod
    def _extract_summary(output: Dict[str, Any]) -> str:
        if not isinstance(output, dict):
            return ""
        for key in (
            "summary",
            "final_summary",
            "primary_summary",
        ):
            v = output.get(key)
            if isinstance(v, str) and v:
                return v
        return ""

    async def run_graph(
        self,
        graph: AgentExecutionGraph,
        query: str,
        context: SharedExecutionContext,
        *,
        contributions: List[AgentContribution],
        allow_parallel: bool = True,
    ) -> List[AgentContribution]:
        steps_by_id = {s.step_id: s for s in graph.steps}
        completed: List[AgentContribution] = []
        pending: List[AgentExecutionStep] = list(graph.steps)
        # We run in waves: a step is eligible when all its deps are done
        while pending:
            eligible = [
                s
                for s in pending
                if all(
                    dep in {c.agent_name for c in completed}
                    for dep in s.depends_on
                )
            ]
            if not eligible:
                # Circular or broken deps — run the first one and let
                # the caller see the error
                eligible = pending[:1]
            if graph.mode == ExecutionMode.PARALLEL and allow_parallel:
                tasks = []
                for s in eligible:
                    agent, _ = await self._coordinator.dispatch(
                        s, query, context
                    )
                    tasks.append(
                        self.run_step(agent, s, query, context)
                    )
                wave = await asyncio.gather(*tasks)
            else:
                wave = []
                for s in eligible:
                    agent, _ = await self._coordinator.dispatch(
                        s, query, context
                    )
                    wave.append(
                        await self.run_step(agent, s, query, context)
                    )
            completed.extend(wave)
            contributions.extend(wave)
            for s in eligible:
                pending.remove(s)
            # Avoid infinite loop on circular deps
            if not eligible:
                break
        # Touch steps_by_id to keep linter happy
        _ = steps_by_id
        return completed


# ═══════════════════════════════════════════════════════════════════════
# Workflow manager
# ═══════════════════════════════════════════════════════════════════════


class AgentWorkflowManager:
    """Stores :class:`WorkflowDefinition` objects and tracks their runs."""

    def __init__(self) -> None:
        self._defs: Dict[str, WorkflowDefinition] = {}
        self._runs: Dict[str, AgentWorkflow] = {}
        self._lock = threading.RLock()

    def register(self, definition: WorkflowDefinition) -> None:
        with self._lock:
            self._defs[definition.workflow_id] = definition

    def get(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        with self._lock:
            return self._defs.get(workflow_id)

    def list_definitions(self) -> List[WorkflowDefinition]:
        with self._lock:
            return list(self._defs.values())

    def record_run(self, run: AgentWorkflow) -> None:
        with self._lock:
            self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> Optional[AgentWorkflow]:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self, limit: int = 50) -> List[AgentWorkflow]:
        with self._lock:
            items = list(self._runs.values())
        items.sort(key=lambda r: r.started_at, reverse=True)
        return items[:limit]


# ═══════════════════════════════════════════════════════════════════════
# Orchestrator
# ═══════════════════════════════════════════════════════════════════════


class AgentOrchestrator:
    """Top-level orchestrator that wires everything together."""

    _DEFAULT_AGENT_ORDER = (
        "research-agent",
        "compliance-agent",
        "risk-agent",
        "audit-agent",
    )

    def __init__(
        self,
        *,
        framework_service: Any,
        bus: AgentMessageBus,
        evidence_store: SharedEvidenceStore,
        engine: OrchestrationEngine,
        synthesizer: ResultSynthesizer,
        workflow_manager: AgentWorkflowManager,
    ) -> None:
        self._framework = framework_service
        self._bus = bus
        self._evidence = evidence_store
        self._engine = engine
        self._synthesizer = synthesizer
        self._workflows = workflow_manager

    def build_default_graph(
        self,
        request: OrchestrationRequest,
    ) -> AgentExecutionGraph:
        if request.graph is not None:
            return request.graph
        # Otherwise build a sequential graph from desired_agents
        agents = list(request.desired_agents) or list(
            self._DEFAULT_AGENT_ORDER
        )
        steps: List[AgentExecutionStep] = []
        prev: List[str] = []
        for name in agents:
            capability = name.replace("-agent", "")
            step = AgentExecutionStep(
                agent_name=name,
                capability=capability,
                description=(
                    f"Run {name} on the orchestration query"
                ),
                depends_on=list(prev),
                input_template={"agent": name},
                timeout_ms=request.context.timeout_ms,
            )
            steps.append(step)
            prev = [step.step_id]
        return AgentExecutionGraph(
            steps=steps,
            mode=request.mode,
            metadata={"auto_built": True},
        )

    async def orchestrate(
        self,
        request: OrchestrationRequest,
    ) -> OrchestrationResult:
        with track_request(
            endpoint="/api/v1/agents/orchestrate",
            strategy="orchestrator",
        ):
            started = _now()
            self._evidence.clear()
            graph = self.build_default_graph(request)
            ctx_mgr = ExecutionContextManager(request.context)
            ctx_mgr.write_memory("query", request.query)
            contributions: List[AgentContribution] = []
            messages: List[AgentMessage] = []
            # Publish a "started" message
            start_msg = AgentMessage(
                from_agent="orchestrator",
                to_agent="*",
                kind=MessageKind.STATUS,
                payload={"status": "started", "query": request.query},
            )
            self._bus.publish(start_msg)
            messages.append(start_msg)
            await self._engine.run_graph(
                graph=graph,
                query=request.query,
                context=request.context,
                contributions=contributions,
                allow_parallel=request.allow_parallel,
            )
            # Promote each contribution's output to shared evidence
            for c in contributions:
                if c.output:
                    self._evidence.add(
                        SharedEvidenceItem(
                            producer=c.agent_name,
                            kind="agent_output",
                            title=c.summary or c.agent_name,
                            content=c.output,
                            confidence=c.confidence,
                            consumer="*",
                        )
                    )
            # Build messages between agents
            for c in contributions:
                msg = AgentMessage(
                    from_agent=c.agent_name,
                    to_agent="orchestrator",
                    kind=MessageKind.RESULT,
                    payload={
                        "summary": c.summary,
                        "status": c.status,
                        "confidence": c.confidence,
                    },
                )
                self._bus.publish(msg)
                messages.append(msg)
            evidence = self._evidence.all()
            final_output, conf, consensus, conflicts = (
                self._synthesizer.synthesize(
                    request.query, contributions, evidence
                )
            )
            # Status derivation
            successes = sum(
                1 for c in contributions if c.status == "succeeded"
            )
            if not contributions:
                status_ = WorkflowStatus.FAILED
            elif successes == len(contributions):
                status_ = WorkflowStatus.SUCCEEDED
            elif successes == 0:
                status_ = WorkflowStatus.FAILED
            else:
                status_ = WorkflowStatus.PARTIALLY_SUCCEEDED
            duration = (_now() - started) * 1000.0
            summary = (
                f"Orchestration {status_.value}: {successes}/"
                f"{len(contributions)} agent(s) succeeded; "
                f"confidence={conf:.2f}, consensus={consensus:.2f}."
            )
            result = OrchestrationResult(
                query=request.query,
                status=status_,
                mode=graph.mode,
                agents_used=[s.agent_name for s in graph.steps],
                execution_graph=graph,
                contributions=contributions,
                final_output=final_output,
                summary=summary,
                final_confidence=conf,
                consensus_score=consensus,
                conflicts_resolved=conflicts,
                duration_ms=round(duration, 3),
                started_at=started,
                completed_at=_now(),
                messages=messages,
                shared_evidence=evidence,
                notes=(
                    ""
                    if status_ == WorkflowStatus.SUCCEEDED
                    else f"{len(contributions) - successes} "
                    f"agent(s) failed"
                ),
            )
            return result

    async def run_workflow(
        self,
        definition: WorkflowDefinition,
        *,
        query: str = "",
    ) -> AgentWorkflow:
        run = AgentWorkflow(
            workflow_id=definition.workflow_id,
            workflow_name=definition.name,
            status=WorkflowStatus.RUNNING,
        )
        self._workflows.record_run(run)
        request = OrchestrationRequest(
            query=query or definition.description or definition.name,
            graph=definition.graph,
            mode=definition.graph.mode,
        )
        try:
            result = await self.orchestrate(request)
            run.status = result.status
            run.completed_at = _now()
            run.duration_ms = result.duration_ms
            run.result = result
        except Exception as exc:  # pragma: no cover
            run.status = WorkflowStatus.FAILED
            run.completed_at = _now()
            run.error = str(exc)
        self._workflows.record_run(run)
        return run


# ═══════════════════════════════════════════════════════════════════════
# Service / facade
# ═══════════════════════════════════════════════════════════════════════


class OrchestrationService:
    """DI facade for the multi-agent orchestrator."""

    def __init__(
        self,
        *,
        framework_service: Any,
        bus: AgentMessageBus,
        evidence_store: SharedEvidenceStore,
        engine: OrchestrationEngine,
        orchestrator: AgentOrchestrator,
        workflow_manager: AgentWorkflowManager,
    ) -> None:
        self.framework_service = framework_service
        self.bus = bus
        self.evidence_store = evidence_store
        self.engine = engine
        self.orchestrator = orchestrator
        self.workflow_manager = workflow_manager
        self._lock = threading.RLock()
        self._metrics = OrchestrationMetricsSummary()

    async def orchestrate(
        self, request: OrchestrationRequest
    ) -> OrchestrationResult:
        result = await self.orchestrator.orchestrate(request)
        self._record_metrics(result)
        return result

    async def run_workflow(
        self, definition: WorkflowDefinition, query: str = ""
    ) -> AgentWorkflow:
        return await self.orchestrator.run_workflow(
            definition, query=query
        )

    def list_workflows(self) -> List[WorkflowDefinition]:
        return self.workflow_manager.list_definitions()

    def list_runs(self, limit: int = 50) -> List[AgentWorkflow]:
        return self.workflow_manager.list_runs(limit=limit)

    def messages(
        self,
        *,
        from_agent: Optional[str] = None,
        to_agent: Optional[str] = None,
        limit: int = 100,
    ) -> List[AgentMessage]:
        return self.bus.history(
            from_agent=from_agent, to_agent=to_agent, limit=limit
        )

    def metrics(self) -> OrchestrationMetricsSummary:
        with self._lock:
            return self._metrics.model_copy(deep=True)

    def _record_metrics(self, result: OrchestrationResult) -> None:
        with self._lock:
            self._metrics.total_executions += 1
            if result.status == WorkflowStatus.SUCCEEDED:
                self._metrics.total_successful += 1
            elif result.status == WorkflowStatus.FAILED:
                self._metrics.total_failed += 1
            self._metrics.by_mode[result.mode.value] = (
                self._metrics.by_mode.get(result.mode.value, 0) + 1
            )
            self._metrics.by_status[result.status.value] = (
                self._metrics.by_status.get(result.status.value, 0) + 1
            )
            for a in result.agents_used:
                self._metrics.by_agent[a] = (
                    self._metrics.by_agent.get(a, 0) + 1
                )
            self._metrics.total_messages += len(result.messages)
            self._metrics.total_evidence += len(result.shared_evidence)
            self._metrics.total_conflicts += result.conflicts_resolved
            self._metrics.average_duration_ms = _running_mean(
                self._metrics.average_duration_ms,
                result.duration_ms,
                self._metrics.total_executions,
            )
            self._metrics.average_confidence = _running_mean(
                self._metrics.average_confidence,
                result.final_confidence,
                self._metrics.total_executions,
            )
            self._metrics.average_consensus = _running_mean(
                self._metrics.average_consensus,
                result.consensus_score,
                self._metrics.total_executions,
            )


def _running_mean(prev: float, sample: float, n: int) -> float:
    if n <= 1:
        return float(sample)
    return round(((prev * (n - 1)) + float(sample)) / n, 3)


# ═══════════════════════════════════════════════════════════════════════
# Default factory
# ═══════════════════════════════════════════════════════════════════════


def build_default_orchestration_service(
    *, framework_service: Any = None
) -> OrchestrationService:
    """Build a default :class:`OrchestrationService`."""
    if framework_service is None:
        from app.services.agents import build_default_agent_framework_service

        framework_service = build_default_agent_framework_service()
    bus = AgentMessageBus()
    evidence_store = SharedEvidenceStore()
    router = CapabilityBasedRouter(framework_service)
    policy = AgentSelectionPolicy()
    coordinator = TaskCoordinator(
        framework_service=framework_service,
        router=router,
        policy=policy,
    )
    engine = OrchestrationEngine(
        framework_service=framework_service,
        coordinator=coordinator,
    )
    synthesizer = ResultSynthesizer()
    workflow_manager = AgentWorkflowManager()
    orchestrator = AgentOrchestrator(
        framework_service=framework_service,
        bus=bus,
        evidence_store=evidence_store,
        engine=engine,
        synthesizer=synthesizer,
        workflow_manager=workflow_manager,
    )
    return OrchestrationService(
        framework_service=framework_service,
        bus=bus,
        evidence_store=evidence_store,
        engine=engine,
        orchestrator=orchestrator,
        workflow_manager=workflow_manager,
    )


__all__ = [
    "AgentMessageBus",
    "SharedEvidenceStore",
    "ExecutionContextManager",
    "AgentSelectionPolicy",
    "CapabilityBasedRouter",
    "ConflictResolver",
    "ConsensusBuilder",
    "EvidenceAggregator",
    "ResultSynthesizer",
    "TaskCoordinator",
    "OrchestrationEngine",
    "AgentWorkflowManager",
    "AgentOrchestrator",
    "OrchestrationService",
    "build_default_orchestration_service",
]
