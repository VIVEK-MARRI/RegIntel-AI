"""Module 8.5 — Human-in-the-Loop Review System contracts.

Pydantic v2 with ``extra="forbid"`` for all models. Designed to integrate
with Module 8.4 (Workflow Automation) via workflow_id/task_id and
Module 8.1-8.3 (Risk, Recommendations, Forecasting) via subject_id.
"""

from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ─────────────────────────────────────────────────────────


class ReviewStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class ReviewPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ReviewDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"
    ESCALATE = "escalate"


# ─── Audit entry (re-used shape) ──────────────────────────────────


class AuditEntry(BaseModel):
    """A single timestamped action in a review audit trail."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(default_factory=lambda: f"aud-{secrets.token_hex(6)}")
    action: str
    actor: str
    timestamp: float = Field(default_factory=time.time)
    details: Dict[str, Any] = Field(default_factory=dict)
    source: str = "review_engine"


# ─── Review building blocks ──────────────────────────────────────


class ReviewComment(BaseModel):
    """A single comment on a review."""

    model_config = ConfigDict(extra="forbid")

    comment_id: str = Field(default_factory=lambda: f"cmt-{secrets.token_hex(4)}")
    author: str
    role: str = "reviewer"
    text: str = Field(..., min_length=1, max_length=4000)
    timestamp: float = Field(default_factory=time.time)
    attachments: List[str] = Field(default_factory=list)


class ReviewCorrection(BaseModel):
    """A single correction captured during review."""

    model_config = ConfigDict(extra="forbid")

    correction_id: str = Field(default_factory=lambda: f"cor-{secrets.token_hex(4)}")
    field: str
    original_value: str
    corrected_value: str
    reason: str = ""
    corrected_by: str = ""
    timestamp: float = Field(default_factory=time.time)


class ApprovalRequirement(BaseModel):
    """A single approver-role requirement on a review."""

    model_config = ConfigDict(extra="forbid")

    approver_role: str
    required: bool = True
    min_approvals: int = Field(1, ge=1, le=10)
    approved_by: List[str] = Field(default_factory=list)
    rejected_by: List[str] = Field(default_factory=list)


# ─── Review ───────────────────────────────────────────────────────


class Review(BaseModel):
    """A human-in-the-loop review instance."""

    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: f"rev-{uuid.uuid4().hex[:12]}")
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    subject_type: str = "document"  # "workflow" | "task" | "recommendation" | "risk_assessment" | "document" | "policy"
    subject_id: str = ""
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None
    status: ReviewStatus = ReviewStatus.PENDING
    priority: ReviewPriority = ReviewPriority.MEDIUM
    decision: ReviewDecision = ReviewDecision.PENDING
    assigned_to: str = ""
    assigned_role: str = ""
    required_approvers: List[ApprovalRequirement] = Field(default_factory=list)
    comments: List[ReviewComment] = Field(default_factory=list)
    corrections: List[ReviewCorrection] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    assigned_at: Optional[float] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    due_at: Optional[float] = None
    created_by: str = "system"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    audit_trail: List[AuditEntry] = Field(default_factory=list)


# ─── Requests / Filters / Stats ───────────────────────────────────


class ReviewCreateRequest(BaseModel):
    """Request to create a new review."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    subject_type: str = "document"
    subject_id: str = ""
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None
    assigned_to: str = ""
    assigned_role: str = ""
    required_approvers: List[ApprovalRequirement] = Field(default_factory=list)
    priority: ReviewPriority = ReviewPriority.MEDIUM
    due_at: Optional[float] = None
    created_by: str = "system"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReviewCorrectionPayload(BaseModel):
    """Inline correction submitted with a decision."""

    model_config = ConfigDict(extra="forbid")

    field: str
    original_value: str
    corrected_value: str
    reason: str = ""


class ReviewDecisionRequest(BaseModel):
    """Request to record a review decision."""

    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecision
    approver_role: str = ""
    comment_text: str = ""
    reason: str = ""
    corrections: List[ReviewCorrectionPayload] = Field(default_factory=list)


class ReviewAssignmentRequest(BaseModel):
    """Request to (re)assign a review."""

    model_config = ConfigDict(extra="forbid")

    assigned_to: str
    assigned_role: str = ""


class ReviewCommentRequest(BaseModel):
    """Request to add a comment."""

    model_config = ConfigDict(extra="forbid")

    author: str
    text: str = Field(..., min_length=1, max_length=4000)
    role: str = "reviewer"


class ReviewCorrectionRequest(BaseModel):
    """Request to add a correction."""

    model_config = ConfigDict(extra="forbid")

    field: str
    original_value: str
    corrected_value: str
    reason: str = ""
    corrected_by: str = ""


class ReviewFilter(BaseModel):
    """Query filter for reviews."""

    model_config = ConfigDict(extra="forbid")

    status: Optional[ReviewStatus] = None
    priority: Optional[ReviewPriority] = None
    assigned_to: Optional[str] = None
    workflow_id: Optional[str] = None
    subject_type: Optional[str] = None
    subject_id: Optional[str] = None
    after: Optional[float] = None
    before: Optional[float] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedReviews(BaseModel):
    """Page of reviews."""

    model_config = ConfigDict(extra="forbid")

    items: List[Review] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class ReviewStats(BaseModel):
    """Aggregated review statistics."""

    model_config = ConfigDict(extra="forbid")

    total_reviews: int = 0
    approved: int = 0
    rejected: int = 0
    pending: int = 0
    escalated: int = 0
    approval_rate: float = 0.0
    average_latency_ms: float = 0.0
    total_comments: int = 0
    total_corrections: int = 0
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_decision: Dict[str, int] = Field(default_factory=dict)
    by_priority: Dict[str, int] = Field(default_factory=dict)
    last_review_at: Optional[float] = None


__all__ = [
    "ReviewStatus",
    "ReviewPriority",
    "ReviewDecision",
    "AuditEntry",
    "ReviewComment",
    "ReviewCorrection",
    "ApprovalRequirement",
    "Review",
    "ReviewCreateRequest",
    "ReviewCorrectionPayload",
    "ReviewDecisionRequest",
    "ReviewAssignmentRequest",
    "ReviewCommentRequest",
    "ReviewCorrectionRequest",
    "ReviewFilter",
    "PaginatedReviews",
    "ReviewStats",
]
