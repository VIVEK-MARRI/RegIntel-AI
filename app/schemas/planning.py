"""Module 6.4 — Query Planning Engine schemas.

The :class:`QueryPlanner` decomposes complex regulatory questions into
executable plans that the system can run against retrieval and
multi-document reasoning.  The schemas here are the public contracts
for that flow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ──────────────────────────────────────────────────────────────────


class QueryType(str, Enum):
    """Top-level classification of a regulatory query."""

    DEFINITION = "definition"  # "What is KYC?"
    FACTUAL = "factual"  # "When was the RBI circular issued?"
    PROCEDURAL = "procedural"  # "How to file a complaint?"
    COMPARISON = "comparison"  # "Compare RBI vs SEBI disclosure rules"
    TIMELINE = "timeline"  # "Evolution of KYC norms"
    REGULATORY_CHANGE = "regulatory_change"  # "What changed in 2023?"
    CROSS_DOCUMENT = "cross_document"  # "What do RBI + SEBI say about X?"
    MULTI_STEP = "multi_step"  # "First, find X, then compare with Y"
    UNKNOWN = "unknown"


class PlanStepType(str, Enum):
    """Types of steps that an :class:`ExecutionPlan` may contain."""

    RETRIEVE = "retrieve"
    SUMMARISE = "summarise"
    COMPARE = "compare"
    EXTRACT_TIMELINE = "extract_timeline"
    DETECT_CHANGE = "detect_change"
    DETECT_CONTRADICTION = "detect_contradiction"
    AGGREGATE = "aggregate"
    ANSWER = "answer"


class PlanStrategy(str, Enum):
    """High-level strategy used to answer the query."""

    SINGLE_DOC = "single_doc"  # All evidence in one document.
    MULTI_DOC = "multi_doc"  # Multiple documents needed.
    ITERATIVE = "iterative"  # Multi-step with sub-queries.
    EVIDENCE_BASED = "evidence_based"  # Pull evidence and synthesise.


class PlanStepStatus(str, Enum):
    """Per-step execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanComplexity(str, Enum):
    """Coarse estimate of how expensive the plan is to execute."""

    SIMPLE = "simple"  # 1–2 steps, single doc.
    MODERATE = "moderate"  # 3–5 steps, multi-doc.
    COMPLEX = "complex"  # Multi-step, multi-doc, with reasoning.


# ─── Plan structure ────────────────────────────────────────────────────────


class PlanStepDefinition(BaseModel):
    """A single step in an :class:`ExecutionPlan`."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(default_factory=lambda: f"step-{uuid.uuid4().hex[:8]}")
    step_type: PlanStepType
    description: str = Field("", description="Human-readable description of the step.")
    depends_on: List[str] = Field(
        default_factory=list,
        description="List of step_ids that must succeed before this step runs.",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form parameters for the step (sub-queries, filters, etc.).",
    )
    expected_output: str = Field(
        "", description="Human-readable description of what the step should produce."
    )
    optional: bool = Field(
        False, description="If true, step failure does not abort the plan."
    )


class ExecutionPlan(BaseModel):
    """The complete plan for answering a query."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:12]}")
    query: str
    query_type: QueryType
    strategy: PlanStrategy
    steps: List[PlanStepDefinition]
    estimated_complexity: PlanComplexity = PlanComplexity.SIMPLE
    expected_documents: int = Field(
        1, ge=1, description="Approximate number of documents needed."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def step_ids(self) -> List[str]:
        return [s.step_id for s in self.steps]

    def get_step(self, step_id: str) -> Optional[PlanStepDefinition]:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    def dependents_of(self, step_id: str) -> List[PlanStepDefinition]:
        return [s for s in self.steps if step_id in s.depends_on]


class PlanStepResult(BaseModel):
    """Result of executing a single :class:`PlanStepDefinition`."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    step_type: PlanStepType
    status: PlanStepStatus = PlanStepStatus.PENDING
    output: Optional[Dict[str, Any]] = None
    citations: List[str] = Field(
        default_factory=list, description="Citation IDs (chunk_ids) used."
    )
    latency_ms: float = Field(0.0, ge=0.0)
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class PlanExecutionResult(BaseModel):
    """The full result of running an :class:`ExecutionPlan`."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    query: str
    query_type: QueryType
    strategy: PlanStrategy
    step_results: List[PlanStepResult]
    status: PlanStepStatus = PlanStepStatus.PENDING
    final_output: Optional[Dict[str, Any]] = None
    total_latency_ms: float = Field(0.0, ge=0.0)
    citations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Validation ────────────────────────────────────────────────────────────


class PlanValidationResult(BaseModel):
    """Result of validating an :class:`ExecutionPlan`."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


# ─── Explanation ───────────────────────────────────────────────────────────


class PlanExplanation(BaseModel):
    """A human-readable explanation of why a plan looks the way it does."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    summary: str = Field(..., description="One-sentence summary.")
    query_type_reason: str = Field("", description="Why this query type was selected.")
    strategy_reason: str = Field("", description="Why this strategy was selected.")
    step_rationale: Dict[str, str] = Field(
        default_factory=dict,
        description="step_id → human-readable rationale.",
    )


# ─── Request / Response ───────────────────────────────────────────────────


class QueryPlanRequest(BaseModel):
    """Request to generate and (optionally) execute a plan."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=4096)
    # Optional hints.
    expected_documents: Optional[int] = Field(None, ge=1, le=20)
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    # Pre-supplied chunks (skips retrieval; useful for unit tests / API callers
    # that already have evidence).
    chunks: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Pre-retrieved chunks; when present, RETRIEVE steps are skipped.",
    )
    # Mode flag: when true, the plan is executed end-to-end.
    execute: bool = Field(
        False, description="If true, execute the plan after generation."
    )
    # Optional time budget for the whole plan in seconds.
    timeout_sec: float = Field(60.0, ge=1.0, le=600.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QueryPlanResponse(BaseModel):
    """Response to a :class:`QueryPlanRequest`."""

    model_config = ConfigDict(extra="forbid")

    plan: ExecutionPlan
    validation: PlanValidationResult
    explanation: PlanExplanation
    execution: Optional[PlanExecutionResult] = Field(
        None, description="Populated only when ``execute=True``."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "ExecutionPlan",
    "PlanComplexity",
    "PlanExecutionResult",
    "PlanExplanation",
    "PlanStepDefinition",
    "PlanStepResult",
    "PlanStepStatus",
    "PlanStepType",
    "PlanStrategy",
    "PlanValidationResult",
    "QueryPlanRequest",
    "QueryPlanResponse",
    "QueryType",
]
