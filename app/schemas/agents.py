"""Module 9 — Multi-Agent Framework contracts.

Pydantic v2 with ``extra="forbid"`` for all models. This module
defines the contracts for the agent framework, the agent registry and
the coordinator agent.

Public surface
--------------
* ``AgentStatus`` / ``TaskStatus`` / ``CapabilityKind`` — enums
* ``AgentCapability``           — a single capability an agent offers
* ``AgentTask``                 — input to an agent
* ``AgentResult``               — output of an agent
* ``AgentContext``              — per-execution context
* ``AgentMetadata``             — registry-level metadata
* ``AgentHealthCheck``          — health snapshot
* ``AgentRegistrationRequest``  — payload to register an agent
* ``CoordinatorPlan``           — execution plan produced by coordinator
* ``CoordinatorResult``         — coordinator outcome
* ``CoordinatorRequest``        — payload to invoke the coordinator
"""

from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ─────────────────────────────────────────────────────


class AgentStatus(str, Enum):
    """Lifecycle status of a registered agent."""

    REGISTERED = "registered"
    ACTIVE = "active"
    BUSY = "busy"
    PAUSED = "paused"
    FAILED = "failed"
    DISABLED = "disabled"


class TaskStatus(str, Enum):
    """Status of a single :class:`AgentTask` execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class CapabilityKind(str, Enum):
    """Kinds of capabilities an agent can declare.

    The enum is deliberately broad so that the same registry can host
    any future specialised agent (retrieval, reasoning, summarisation,
    KG traversal, change-detection, risk, forecast, etc.).
    """

    RETRIEVAL = "retrieval"
    REASONING = "reasoning"
    SUMMARIZATION = "summarization"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    RISK_ASSESSMENT = "risk_assessment"
    RECOMMENDATION = "recommendation"
    FORECASTING = "forecasting"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    CHANGE_DETECTION = "change_detection"
    IMPACT_ANALYSIS = "impact_analysis"
    ALERTING = "alerting"
    AUDIT = "audit"
    GOVERNANCE = "governance"
    WORKFLOW = "workflow"
    REVIEW = "review"
    COMPLIANCE = "compliance"
    ORCHESTRATION = "orchestration"
    OTHER = "other"


# ─── Atomic building blocks ─────────────────────────────────


class AgentCapability(BaseModel):
    """A single capability an agent offers."""

    model_config = ConfigDict(extra="forbid")

    capability_id: str = Field(
        default_factory=lambda: f"cap-{secrets.token_hex(4)}"
    )
    kind: CapabilityKind
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    # Free-form parameters describing what the agent accepts/produces
    # for this capability. Examples:
    #   {"accepts": ["query"], "produces": ["answer"], "languages": ["en"]}
    parameters: Dict[str, Any] = Field(default_factory=dict)


class AgentContext(BaseModel):
    """Per-execution context shared with the agent."""

    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(
        default_factory=lambda: f"ctx-{uuid.uuid4().hex[:12]}"
    )
    session_id: str = ""
    actor: str = "system"
    timeout_ms: int = Field(30_000, ge=100, le=600_000)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Free-form "memory" the agent may use to remember things
    memory: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class AgentTask(BaseModel):
    """Input to an agent's ``execute`` method."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(
        default_factory=lambda: f"tsk-{uuid.uuid4().hex[:12]}"
    )
    capability: CapabilityKind
    input: Dict[str, Any] = Field(default_factory=dict)
    context: AgentContext = Field(default_factory=AgentContext)
    # Dependencies: other task_ids that must succeed first
    depends_on: List[str] = Field(default_factory=list)
    # Retry config — overrides per-agent default
    max_retries: int = Field(0, ge=0, le=10)
    timeout_ms: Optional[int] = Field(None, ge=100, le=600_000)
    # Optional target hint (agent name) for the distributor
    target_agent: str = ""
    created_at: float = Field(default_factory=time.time)


class AgentResult(BaseModel):
    """Output of an agent's ``execute`` method."""

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(
        default_factory=lambda: f"res-{uuid.uuid4().hex[:12]}"
    )
    task_id: str = ""
    agent_id: str = ""
    agent_name: str = ""
    status: TaskStatus = TaskStatus.SUCCEEDED
    output: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    attempts: int = 1
    duration_ms: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == TaskStatus.SUCCEEDED


class AgentHealthCheck(BaseModel):
    """A point-in-time health snapshot for an agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    healthy: bool = True
    last_error: str = ""
    consecutive_failures: int = 0
    total_invocations: int = 0
    successful_invocations: int = 0
    failed_invocations: int = 0
    average_duration_ms: float = 0.0
    last_invocation_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_failure_at: Optional[float] = None


class AgentMetadata(BaseModel):
    """Registry-level metadata for a registered agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(
        default_factory=lambda: f"agt-{uuid.uuid4().hex[:12]}"
    )
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    version: str = "1.0.0"
    author: str = "system"
    capabilities: List[AgentCapability] = Field(default_factory=list)
    status: AgentStatus = AgentStatus.REGISTERED
    # Default retry/timeout applied when the caller does not override
    default_max_retries: int = Field(0, ge=0, le=10)
    default_timeout_ms: int = Field(30_000, ge=100, le=600_000)
    # Concurrency / selection hints
    priority: int = 0  # higher = preferred when multiple agents match
    tags: List[str] = Field(default_factory=list)
    registered_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Coordinator contracts ─────────────────────────────────


class PlanStep(BaseModel):
    """A single step in a :class:`CoordinatorPlan`."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(
        default_factory=lambda: f"step-{secrets.token_hex(4)}"
    )
    capability: CapabilityKind
    description: str = ""
    input: Dict[str, Any] = Field(default_factory=dict)
    target_agent: str = ""  # optional preferred agent name
    depends_on: List[str] = Field(default_factory=list)
    max_retries: int = Field(0, ge=0, le=10)
    timeout_ms: Optional[int] = Field(None, ge=100, le=600_000)


class CoordinatorPlan(BaseModel):
    """A multi-step execution plan produced by the coordinator."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(
        default_factory=lambda: f"plan-{uuid.uuid4().hex[:12]}"
    )
    query: str = ""
    steps: List[PlanStep] = Field(default_factory=list)
    selected_agents: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    rationale: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CoordinatorResult(BaseModel):
    """The final aggregated output of the coordinator."""

    model_config = ConfigDict(extra="forbid")

    result_id: str = Field(
        default_factory=lambda: f"cres-{uuid.uuid4().hex[:12]}"
    )
    plan_id: str = ""
    query: str = ""
    selected_agents: List[str] = Field(default_factory=list)
    step_results: List[AgentResult] = Field(default_factory=list)
    final_output: Dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.SUCCEEDED
    duration_ms: float = 0.0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    conflicts_resolved: int = 0
    notes: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Request payloads ─────────────────────────────────────


class AgentRegistrationRequest(BaseModel):
    """Payload to register a new agent (without an executable).

    The actual :class:`BaseAgent` instance is supplied separately to
    :class:`AgentRegistry`; this payload only carries the metadata.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    version: str = "1.0.0"
    author: str = "system"
    capabilities: List[AgentCapability] = Field(default_factory=list)
    default_max_retries: int = Field(0, ge=0, le=10)
    default_timeout_ms: int = Field(30_000, ge=100, le=600_000)
    priority: int = 0
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentExecutionRequest(BaseModel):
    """Request to invoke a specific agent directly."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str = Field(..., min_length=1, max_length=200)
    capability: CapabilityKind
    input: Dict[str, Any] = Field(default_factory=dict)
    context: AgentContext = Field(default_factory=AgentContext)
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    timeout_ms: Optional[int] = Field(None, ge=100, le=600_000)


class CoordinatorRequest(BaseModel):
    """Request to invoke the coordinator with a free-form query."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=4000)
    desired_capabilities: List[CapabilityKind] = Field(default_factory=list)
    context: AgentContext = Field(default_factory=AgentContext)
    max_steps: int = Field(8, ge=1, le=32)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentDiscoveryQuery(BaseModel):
    """Query payload for the agent discovery service."""

    model_config = ConfigDict(extra="forbid")

    capability: Optional[CapabilityKind] = None
    text_query: Optional[str] = None
    tag: Optional[str] = None
    healthy_only: bool = False
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedAgents(BaseModel):
    """A page of agent metadata."""

    model_config = ConfigDict(extra="forbid")

    items: List[AgentMetadata] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


__all__ = [
    "AgentStatus",
    "TaskStatus",
    "CapabilityKind",
    "AgentCapability",
    "AgentContext",
    "AgentTask",
    "AgentResult",
    "AgentHealthCheck",
    "AgentMetadata",
    "PlanStep",
    "CoordinatorPlan",
    "CoordinatorResult",
    "AgentRegistrationRequest",
    "AgentExecutionRequest",
    "CoordinatorRequest",
    "AgentDiscoveryQuery",
    "PaginatedAgents",
]
