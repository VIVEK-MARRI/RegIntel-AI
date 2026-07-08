"""Module 6.6 — Feedback Intelligence schemas.

Tracks user feedback on copilot responses and turns it into
operationally useful signals: satisfaction, citation accuracy,
hallucination reports, and corrections.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ──────────────────────────────────────────────────────────────────


class FeedbackType(str, Enum):
    """The kind of feedback the user provided."""

    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    CORRECTION = "correction"
    COMMENT = "comment"
    HALLUCINATION_REPORT = "hallucination_report"
    CITATION_ISSUE = "citation_issue"


class FeedbackCategory(str, Enum):
    """The dimension of quality the feedback addresses."""

    ANSWER_QUALITY = "answer_quality"
    CITATION_ACCURACY = "citation_accuracy"
    HALLUCINATION = "hallucination"
    SPEED = "speed"
    RELEVANCE = "relevance"
    TONE = "tone"
    COMPLETENESS = "completeness"
    OTHER = "other"


class FeedbackSeverity(str, Enum):
    """How serious the reported issue is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ─── Entry / request / response ────────────────────────────────────────────


class FeedbackEntry(BaseModel):
    """A single feedback record."""

    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(default_factory=lambda: f"fb-{uuid.uuid4().hex[:12]}")
    request_id: str = Field(
        ..., description="Copilot request_id this feedback relates to."
    )
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    feedback_type: FeedbackType
    category: FeedbackCategory = FeedbackCategory.ANSWER_QUALITY
    severity: FeedbackSeverity = FeedbackSeverity.LOW
    # Optional user-supplied text.
    comment: Optional[str] = Field(
        None, max_length=4000, description="Free-form user comment."
    )
    # For corrections, the corrected text the user provided.
    corrected_answer: Optional[str] = Field(
        None, max_length=8000, description="User's corrected version of the answer."
    )
    # Optional references to the chunks/sources the user flagged.
    flagged_citations: List[str] = Field(
        default_factory=list,
        description="List of chunk_ids flagged as incorrect / hallucinated.",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedbackRequest(BaseModel):
    """Request to record feedback."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1, max_length=128)
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    feedback_type: FeedbackType
    category: FeedbackCategory = FeedbackCategory.ANSWER_QUALITY
    severity: FeedbackSeverity = FeedbackSeverity.LOW
    comment: Optional[str] = Field(None, max_length=4000)
    corrected_answer: Optional[str] = Field(None, max_length=8000)
    flagged_citations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FeedbackFilter(BaseModel):
    """Filter for listing feedback entries."""

    model_config = ConfigDict(extra="forbid")

    request_id: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    feedback_type: Optional[FeedbackType] = None
    category: Optional[FeedbackCategory] = None
    severity: Optional[FeedbackSeverity] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)
    sort_desc: bool = True


class PaginatedFeedback(BaseModel):
    """Paginated list of feedback entries."""

    model_config = ConfigDict(extra="forbid")

    items: List[FeedbackEntry]
    total: int
    page: int
    page_size: int
    has_more: bool


# ─── Aggregations / stats ─────────────────────────────────────────────────


class FeedbackStats(BaseModel):
    """Aggregated feedback statistics."""

    model_config = ConfigDict(extra="forbid")

    total: int = 0
    by_type: Dict[FeedbackType, int] = Field(default_factory=dict)
    by_category: Dict[FeedbackCategory, int] = Field(default_factory=dict)
    by_severity: Dict[FeedbackSeverity, int] = Field(default_factory=dict)
    thumbs_up: int = 0
    thumbs_down: int = 0
    satisfaction_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="thumbs_up / (thumbs_up + thumbs_down); 0 if no ratings.",
    )
    hallucination_reports: int = 0
    citation_issues: int = 0
    corrections_count: int = 0
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


__all__ = [
    "FeedbackCategory",
    "FeedbackEntry",
    "FeedbackFilter",
    "FeedbackRequest",
    "FeedbackSeverity",
    "FeedbackStats",
    "FeedbackType",
    "PaginatedFeedback",
]
