"""Module 6.5 — Multi-Document Reasoning schemas.

The :class:`MultiDocumentReasoner` analyses collections of regulatory
chunks / documents to produce structured insights:

* :class:`DocumentDiff` / :class:`DiffItem` — pairwise differences.
* :class:`Timeline` / :class:`TimelineEvent` — chronological view.
* :class:`RegulatoryChange` / :class:`ChangeReport` — what changed.
* :class:`Contradiction` / :class:`ContradictionReport` — conflicting
  claims.
* :class:`CrossDocumentSummary` — unified cross-doc summary.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ──────────────────────────────────────────────────────────────────


class DiffType(str, Enum):
    """Type of difference between two chunks / documents."""

    ADDED = "added"  # Present in B, missing in A.
    REMOVED = "removed"  # Present in A, missing in B.
    CHANGED = "changed"  # Present in both, materially different.
    UNCHANGED = "unchanged"  # Cosine-similar enough to skip.
    CONTRADICTS = "contradicts"  # Same topic, opposite claim.


class ChangeType(str, Enum):
    """Type of regulatory change detected."""

    NEW = "new"  # Net new rule.
    AMENDED = "amended"  # Modified rule.
    REPEALED = "repealed"  # Removed rule.
    SUPERSEDED = "superseded"  # Replaced by another rule.
    CLARIFIED = "clarified"  # Language clarifications only.


class ContradictionSeverity(str, Enum):
    """How serious a contradiction is."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReasoningMode(str, Enum):
    """What kind of reasoning to run."""

    COMPARE = "compare"
    TIMELINE = "timeline"
    CHANGES = "changes"
    CONTRADICTIONS = "contradictions"
    CROSS_SUMMARY = "cross_summary"
    FULL = "full"  # run all of the above in one pass


# ─── Differences ───────────────────────────────────────────────────────────


class DiffItem(BaseModel):
    """A single difference between two chunks / documents."""

    model_config = ConfigDict(extra="forbid")

    diff_id: str = Field(default_factory=lambda: f"diff-{uuid.uuid4().hex[:10]}")
    diff_type: DiffType
    section: str = Field("", description="Section title where the diff lives.")
    before: Optional[str] = Field(None, description="Text from document A (or None).")
    after: Optional[str] = Field(None, description="Text from document B (or None).")
    similarity: float = Field(
        0.0, ge=0.0, le=1.0, description="Token overlap (0=distinct, 1=identical)."
    )
    severity: ContradictionSeverity = ContradictionSeverity.LOW
    citation_a: Optional[str] = Field(
        None, description="Citation (chunk_id) for side A."
    )
    citation_b: Optional[str] = Field(
        None, description="Citation (chunk_id) for side B."
    )
    explanation: str = Field("", description="Human-readable explanation.")


class DocumentDiff(BaseModel):
    """Pairwise diff between two documents / chunk collections."""

    model_config = ConfigDict(extra="forbid")

    document_a_id: str
    document_a_title: str = ""
    document_b_id: str
    document_b_title: str = ""
    similarity_score: float = Field(0.0, ge=0.0, le=1.0)
    differences: List[DiffItem] = Field(default_factory=list)
    summary: str = Field("", description="A brief narrative summary of the diff.")


# ─── Timeline ──────────────────────────────────────────────────────────────


class TimelineEvent(BaseModel):
    """A single point on a regulatory timeline."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:10]}")
    event_date: Optional[date] = None
    event_year: Optional[int] = Field(None, ge=1900, le=2100)
    document_id: Optional[str] = None
    document_title: str = ""
    section: str = ""
    description: str
    category: str = Field(
        "general",
        description="e.g. 'circular', 'amendment', 'master_direction', 'general'.",
    )
    citation: Optional[str] = None


class Timeline(BaseModel):
    """An ordered list of :class:`TimelineEvent`."""

    model_config = ConfigDict(extra="forbid")

    events: List[TimelineEvent] = Field(default_factory=list)
    span_start: Optional[date] = None
    span_end: Optional[date] = None
    grouped_by_period: Dict[str, List[TimelineEvent]] = Field(default_factory=dict)
    summary: str = ""


# ─── Changes ───────────────────────────────────────────────────────────────


class RegulatoryChange(BaseModel):
    """A detected regulatory change between two versions / documents."""

    model_config = ConfigDict(extra="forbid")

    change_id: str = Field(default_factory=lambda: f"chg-{uuid.uuid4().hex[:10]}")
    change_type: ChangeType
    document_a_id: Optional[str] = None
    document_b_id: Optional[str] = None
    section: str = ""
    before: Optional[str] = None
    after: Optional[str] = None
    effective_date: Optional[date] = None
    significance: ContradictionSeverity = ContradictionSeverity.MEDIUM
    citation_a: Optional[str] = None
    citation_b: Optional[str] = None
    explanation: str = ""


class ChangeReport(BaseModel):
    """All detected changes plus a summary."""

    model_config = ConfigDict(extra="forbid")

    changes: List[RegulatoryChange] = Field(default_factory=list)
    by_type: Dict[ChangeType, int] = Field(default_factory=dict)
    summary: str = ""


# ─── Contradictions ────────────────────────────────────────────────────────


class Contradiction(BaseModel):
    """Two claims that disagree with each other."""

    model_config = ConfigDict(extra="forbid")

    contradiction_id: str = Field(
        default_factory=lambda: f"ctr-{uuid.uuid4().hex[:10]}"
    )
    claim_a: str
    source_a: str
    citation_a: Optional[str] = None
    claim_b: str
    source_b: str
    citation_b: Optional[str] = None
    severity: ContradictionSeverity = ContradictionSeverity.MEDIUM
    explanation: str = ""


class ContradictionReport(BaseModel):
    """All contradictions plus a summary."""

    model_config = ConfigDict(extra="forbid")

    contradictions: List[Contradiction] = Field(default_factory=list)
    summary: str = ""


# ─── Cross-document summary ───────────────────────────────────────────────


class CrossDocumentSummary(BaseModel):
    """A unified summary of a topic across multiple documents."""

    model_config = ConfigDict(extra="forbid")

    topic: str
    document_ids: List[str] = Field(default_factory=list)
    document_titles: List[str] = Field(default_factory=list)
    key_points: List[str] = Field(default_factory=list)
    summary_text: str = ""
    citations: List[str] = Field(default_factory=list)


# ─── Request / Response ───────────────────────────────────────────────────


class ReasoningRequest(BaseModel):
    """Request to run multi-document reasoning."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=4096)
    mode: ReasoningMode = ReasoningMode.FULL
    # Chunks to reason over.  At least one chunk is required.
    chunks: List[Dict[str, Any]] = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Chunks to reason over.  Each must have at least chunk_id, document_id, content.",
    )
    # Optional: pre-group chunks by document.
    document_groups: Optional[Dict[str, List[str]]] = Field(
        None,
        description="Optional document_id → list[chunk_id] grouping.",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReasoningResponse(BaseModel):
    """Response from multi-document reasoning."""

    model_config = ConfigDict(extra="forbid")

    query: str
    mode: ReasoningMode
    diff: Optional[DocumentDiff] = None
    timeline: Optional[Timeline] = None
    changes: Optional[ChangeReport] = None
    contradictions: Optional[ContradictionReport] = None
    cross_summary: Optional[CrossDocumentSummary] = None
    citations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "ChangeReport",
    "ChangeType",
    "Contradiction",
    "ContradictionReport",
    "ContradictionSeverity",
    "CrossDocumentSummary",
    "DiffItem",
    "DiffType",
    "DocumentDiff",
    "ReasoningMode",
    "ReasoningRequest",
    "ReasoningResponse",
    "RegulatoryChange",
    "Timeline",
    "TimelineEvent",
]
