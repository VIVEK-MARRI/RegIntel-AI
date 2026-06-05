"""Module 8.2 — Regulatory Recommendation Engine schemas."""

from __future__ import annotations

import secrets
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ────────────────────────────────────────────────────────────


class RecommendationType(str, Enum):
    COMPLIANCE = "compliance"
    OPERATIONAL = "operational"
    POLICY = "policy"
    REMEDIATION = "remediation"
    STRATEGIC = "strategic"
    TECHNOLOGY = "technology"
    REPORTING = "reporting"
    TRAINING = "training"


class RecommendationPriority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class ActionStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXPIRED = "expired"


class CitationKind(str, Enum):
    REGULATION = "regulation"
    CIRCULAR = "circular"
    AMENDMENT = "amendment"
    IMPACT_REPORT = "impact_report"
    CHANGE_DIFF = "change_diff"
    KNOWLEDGE_GRAPH_NODE = "knowledge_graph_node"
    RESEARCH_REPORT = "research_report"
    EXTERNAL = "external"


# ─── Sub-models ───────────────────────────────────────────────────────


class RecommendationCitation(BaseModel):
    """Source backing a recommendation."""

    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(
        default_factory=lambda: f"rcit-{secrets.token_hex(4)}"
    )
    kind: CitationKind
    reference: str
    title: str = ""
    excerpt: str = ""
    url: Optional[str] = None
    score: float = Field(1.0, ge=0.0, le=1.0)


class ReasoningStep(BaseModel):
    """A single reasoning step that produced a recommendation."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(
        default_factory=lambda: f"rstep-{secrets.token_hex(4)}"
    )
    description: str
    rule: str = ""
    inputs: Dict[str, Any] = Field(default_factory=dict)
    output: str = ""


class ActionPlanStep(BaseModel):
    """A single step in a remediation action plan."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(
        default_factory=lambda: f"apst-{secrets.token_hex(4)}"
    )
    sequence: int = 0
    title: str
    description: str = ""
    owner: str = ""
    estimated_effort_hours: float = 0.0
    depends_on: List[str] = Field(default_factory=list)


class ActionPlan(BaseModel):
    """A sequenced remediation plan attached to a recommendation."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(
        default_factory=lambda: f"plan-{secrets.token_hex(4)}"
    )
    title: str
    summary: str = ""
    steps: List[ActionPlanStep] = Field(default_factory=list)
    total_effort_hours: float = 0.0
    created_at: float = 0.0


# ─── Top-level recommendation ────────────────────────────────────────


class Recommendation(BaseModel):
    """A single recommendation."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(
        default_factory=lambda: f"rec-{secrets.token_hex(6)}"
    )
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1, max_length=4000)
    recommendation_type: RecommendationType
    priority: RecommendationPriority
    status: ActionStatus = ActionStatus.PROPOSED
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    reasoning: List[ReasoningStep] = Field(default_factory=list)
    citations: List[RecommendationCitation] = Field(default_factory=list)
    action_plan: Optional[ActionPlan] = None
    source: str = "manual"
    document_id: Optional[str] = None
    diff_id: Optional[str] = None
    risk_assessment_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = 0.0
    accepted_at: Optional[float] = None
    completed_at: Optional[float] = None
    feedback: str = ""


# ─── Requests / Filters / Stats ─────────────────────────────────────


class RecommendationRequest(BaseModel):
    """Request payload to generate recommendations."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    diff_id: Optional[str] = None
    risk_assessment_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    max_recommendations: int = Field(5, ge=1, le=20)


class RecommendationFeedback(BaseModel):
    """Feedback on a recommendation (accept / reject)."""

    model_config = ConfigDict(extra="forbid")

    status: ActionStatus
    feedback: str = ""


class RecommendationFilter(BaseModel):
    """Query filter for recommendations."""

    model_config = ConfigDict(extra="forbid")

    recommendation_type: Optional[RecommendationType] = None
    priority: Optional[RecommendationPriority] = None
    status: Optional[ActionStatus] = None
    document_id: Optional[str] = None
    after: Optional[float] = None
    before: Optional[float] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedRecommendations(BaseModel):
    """Page of recommendations."""

    model_config = ConfigDict(extra="forbid")

    items: List[Recommendation] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class RecommendationStats(BaseModel):
    """Aggregate recommendation statistics."""

    model_config = ConfigDict(extra="forbid")

    total_recommendations: int = 0
    accepted: int = 0
    rejected: int = 0
    proposed: int = 0
    in_progress: int = 0
    completed: int = 0
    acceptance_rate: float = 0.0
    average_confidence: float = 0.0
    by_priority: Dict[str, int] = Field(default_factory=dict)
    by_type: Dict[str, int] = Field(default_factory=dict)
    by_status: Dict[str, int] = Field(default_factory=dict)
    last_recommendation_at: Optional[float] = None


__all__ = [
    "RecommendationType",
    "RecommendationPriority",
    "ActionStatus",
    "CitationKind",
    "RecommendationCitation",
    "ReasoningStep",
    "ActionPlanStep",
    "ActionPlan",
    "Recommendation",
    "RecommendationRequest",
    "RecommendationFeedback",
    "RecommendationFilter",
    "PaginatedRecommendations",
    "RecommendationStats",
]
