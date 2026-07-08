"""Module 9.8 — Multi-Agent Orchestration Platform schemas.

Contracts for the multi-agent orchestrator. All Pydantic v2 models use
``extra="forbid"``. The orchestrator REUSES the existing M9 framework
(agent registry, coordinator, message bus, evidence store) and the M9.4-9.7
intelligence agents (research / compliance / risk / audit).

Public surface
--------------
* ``ExecutionMode`` / ``WorkflowStatus`` / ``MessageKind`` — enums
* ``AgentMessage``                — message-bus message
* ``SharedExecutionContext``      — context shared across agents
* ``SharedEvidenceItem``          — single piece of shared evidence
* ``AgentExecutionStep``          — one step in a graph
* ``AgentExecutionGraph``         — full execution graph
* ``OrchestrationRequest``        — payload to orchestrate
* ``OrchestrationResult``         — final orchestration outcome
* ``AgentContribution``           — single agent's contribution
* ``WorkflowDefinition``          — re-runnable workflow spec
* ``AgentWorkflow``               — workflow run + status
* ``OrchestrationMetricsSummary`` — aggregate metrics
"""

from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ────────────────────────────────────────────────────────────


class ExecutionMode(str, Enum):
    """How the orchestrator runs agents."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"
    DYNAMIC = "dynamic"


class WorkflowStatus(str, Enum):
    """Lifecycle of an :class:`AgentWorkflow`."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class MessageKind(str, Enum):
    """Kinds of :class:`AgentMessage`."""

    TASK = "task"
    RESULT = "result"
    EVIDENCE = "evidence"
    QUERY = "query"
    STATUS = "status"
    ERROR = "error"
    ACK = "ack"
    CONTROL = "control"


# ─── Messages + context ──────────────────────────────────────────────


class AgentMessage(BaseModel):
    """A single message exchanged between agents / bus / orchestrator."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: f"msg-{secrets.token_hex(4)}")
    from_agent: str  # "research" | "compliance" | "risk" | "audit" | "orchestrator" | "coordinator"
    to_agent: str
    kind: MessageKind
    payload: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = ""
    in_reply_to: str = ""
    created_at: float = Field(default_factory=time.time)
    ttl_ms: int = Field(60_000, ge=0, le=600_000)


class SharedEvidenceItem(BaseModel):
    """An evidence artifact placed in the shared store."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default_factory=lambda: f"sevi-{secrets.token_hex(4)}")
    producer: str  # agent name
    kind: str = "data"  # "data" | "citation" | "violation" | "score" | "summary"
    title: str
    content: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    consumer: str = ""  # "*" or a specific agent
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SharedExecutionContext(BaseModel):
    """Per-orchestration context that all agents can read/write."""

    model_config = ConfigDict(extra="forbid")

    context_id: str = Field(default_factory=lambda: f"octx-{uuid.uuid4().hex[:12]}")
    session_id: str = ""
    actor: str = "system"
    timeout_ms: int = Field(60_000, ge=1_000, le=600_000)
    evidence: List[SharedEvidenceItem] = Field(default_factory=list)
    memory: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


# ─── Execution plan / graph ──────────────────────────────────────────


class AgentExecutionStep(BaseModel):
    """A single step inside an :class:`AgentExecutionGraph`."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(default_factory=lambda: f"stp-{secrets.token_hex(4)}")
    agent_name: str  # "research" | "compliance" | "risk" | "audit" | "*"
    capability: str = "reasoning"  # free-form for routing
    description: str = ""
    depends_on: List[str] = Field(default_factory=list)
    input_template: Dict[str, Any] = Field(default_factory=dict)
    timeout_ms: Optional[int] = Field(None, ge=100, le=600_000)
    max_retries: int = Field(0, ge=0, le=10)


class AgentExecutionGraph(BaseModel):
    """A directed acyclic graph of :class:`AgentExecutionStep`."""

    model_config = ConfigDict(extra="forbid")

    graph_id: str = Field(default_factory=lambda: f"grf-{uuid.uuid4().hex[:12]}")
    steps: List[AgentExecutionStep] = Field(default_factory=list)
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Result + request ────────────────────────────────────────────────


class AgentContribution(BaseModel):
    """A single agent's contribution to the orchestration result."""

    model_config = ConfigDict(extra="forbid")

    agent_name: str
    status: str = "succeeded"
    summary: str = ""
    output: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    duration_ms: float = 0.0
    evidence_ids: List[str] = Field(default_factory=list)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    attempts: int = 1
    error: str = ""


class OrchestrationRequest(BaseModel):
    """Payload to invoke the orchestrator."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=3, max_length=4000)
    desired_agents: List[str] = Field(default_factory=list)
    desired_capabilities: List[str] = Field(default_factory=list)
    mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    context: SharedExecutionContext = Field(default_factory=SharedExecutionContext)
    graph: Optional[AgentExecutionGraph] = None
    allow_parallel: bool = True
    consensus_threshold: float = Field(0.5, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OrchestrationResult(BaseModel):
    """Final result of an orchestration run."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(default_factory=lambda: f"exec-{uuid.uuid4().hex[:12]}")
    query: str
    status: WorkflowStatus = WorkflowStatus.SUCCEEDED
    mode: ExecutionMode
    agents_used: List[str] = Field(default_factory=list)
    execution_graph: AgentExecutionGraph
    contributions: List[AgentContribution] = Field(default_factory=list)
    final_output: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    final_confidence: float = Field(0.5, ge=0.0, le=1.0)
    consensus_score: float = Field(0.0, ge=0.0, le=1.0)
    conflicts_resolved: int = 0
    duration_ms: float = 0.0
    started_at: float = Field(default_factory=time.time)
    completed_at: float = 0.0
    messages: List[AgentMessage] = Field(default_factory=list)
    shared_evidence: List[SharedEvidenceItem] = Field(default_factory=list)
    notes: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Workflows (re-runnable orchestrations) ──────────────────────────


class WorkflowDefinition(BaseModel):
    """A reusable orchestration plan that can be triggered repeatedly."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(default_factory=lambda: f"wf-{secrets.token_hex(6)}")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    graph: AgentExecutionGraph
    tags: List[str] = Field(default_factory=list)
    version: str = "1.0.0"
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentWorkflow(BaseModel):
    """A single run of a :class:`WorkflowDefinition`."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: f"wfrun-{uuid.uuid4().hex[:12]}")
    workflow_id: str
    workflow_name: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    started_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None
    duration_ms: float = 0.0
    result: Optional[OrchestrationResult] = None
    error: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Metrics ─────────────────────────────────────────────────────────


class OrchestrationMetricsSummary(BaseModel):
    """Process-wide orchestration metrics."""

    model_config = ConfigDict(extra="forbid")

    total_executions: int = 0
    total_successful: int = 0
    total_failed: int = 0
    by_mode: Dict[str, int] = Field(default_factory=dict)
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_agent: Dict[str, int] = Field(default_factory=dict)
    total_messages: int = 0
    total_evidence: int = 0
    total_conflicts: int = 0
    average_duration_ms: float = 0.0
    average_confidence: float = 0.0
    average_consensus: float = 0.0
    last_reset_at: float = Field(default_factory=time.time)


__all__ = [
    "ExecutionMode",
    "WorkflowStatus",
    "MessageKind",
    "AgentMessage",
    "SharedEvidenceItem",
    "SharedExecutionContext",
    "AgentExecutionStep",
    "AgentExecutionGraph",
    "AgentContribution",
    "OrchestrationRequest",
    "OrchestrationResult",
    "WorkflowDefinition",
    "AgentWorkflow",
    "OrchestrationMetricsSummary",
]
