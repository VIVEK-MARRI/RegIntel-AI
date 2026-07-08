"""Module 7.3 — Regulatory Change Detection Engine schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ────────────────────────────────────────────────────────────────


class ChangeType(str, Enum):
    """The type of change between two versions of a document."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    RENUMBERED = "renumbered"  # re-labelled, same content


class ChangeSeverity(str, Enum):
    """Severity scoring of a detected change.

    * LOW      — cosmetic / formatting change, no compliance impact
    * MEDIUM   — minor policy change, clarification
    * HIGH     — substantive policy change, new compliance obligation
    * CRITICAL — fundamental regulatory change, immediate action required
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ChangeScope(str, Enum):
    """What part of the document the change touches."""

    SECTION = "section"  # entire section added/removed
    SUBSECTION = "subsection"  # entire subsection added/removed
    CLAUSE = "clause"  # individual clause / paragraph
    DEFINITION = "definition"  # change to a defined term
    METADATA = "metadata"  # title, publication date, etc.
    GLOBAL = "global"  # document-level (e.g. withdrawal)


class ChangeCategory(str, Enum):
    """Categorisation of a regulatory change.

    Used both by the change classifier and downstream impact analysis.
    """

    POLICY_UPDATE = "policy_update"
    REGULATORY_AMENDMENT = "regulatory_amendment"
    NEW_GUIDANCE = "new_guidance"
    CLARIFICATION = "clarification"
    COMPLIANCE_DEADLINE = "compliance_deadline"
    PENALTY_CHANGE = "penalty_change"
    REPORTING_REQUIREMENT = "reporting_requirement"
    CAPITAL_REQUIREMENT = "capital_requirement"
    SCOPE_CHANGE = "scope_change"
    OTHER = "other"


# ─── Atomic change records ──────────────────────────────────────────────


class SectionRef(BaseModel):
    """A reference to a specific section/subsection of a document."""

    model_config = ConfigDict(extra="forbid")

    section: Optional[str] = None
    subsection: Optional[str] = None
    clause: Optional[str] = None
    page: Optional[int] = None


class ClauseChange(BaseModel):
    """The atomic unit of change: a single clause (paragraph)."""

    model_config = ConfigDict(extra="forbid")

    change_id: str = Field(default_factory=lambda: f"chg-{uuid4().hex[:12]}")
    change_type: ChangeType
    location: SectionRef
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    severity: ChangeSeverity = ChangeSeverity.LOW
    category: ChangeCategory = ChangeCategory.OTHER
    rationale: Optional[str] = Field(
        None, description="Human-readable explanation of the change."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DocumentDiff(BaseModel):
    """Structured diff between two versions of a document."""

    model_config = ConfigDict(extra="forbid")

    diff_id: str = Field(default_factory=lambda: f"diff-{uuid4().hex[:12]}")
    document_id: Optional[str] = None
    old_version: Optional[str] = None
    new_version: Optional[str] = None
    source: Optional[str] = None
    old_publication_date: Optional[datetime] = None
    new_publication_date: Optional[datetime] = None
    changes: List[ClauseChange] = Field(default_factory=list)
    added_count: int = 0
    removed_count: int = 0
    modified_count: int = 0
    unchanged_count: int = 0
    overall_severity: ChangeSeverity = ChangeSeverity.LOW
    overall_category: ChangeCategory = ChangeCategory.OTHER
    summary: Optional[str] = None
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ─── Compare requests / responses ──────────────────────────────────────


class ChangeDetectionRequest(BaseModel):
    """Request to detect changes between two document versions."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    source: Optional[str] = None
    old_text: Optional[str] = Field(
        None, description="Plain text of the previous version."
    )
    new_text: Optional[str] = Field(None, description="Plain text of the new version.")
    old_version: Optional[str] = None
    new_version: Optional[str] = None
    old_publication_date: Optional[datetime] = None
    new_publication_date: Optional[datetime] = None
    # Section breakdown (optional): a list of {section, subsection, text}
    # pairs. When supplied, the diff is computed at the section level
    # which yields higher-quality results.
    old_sections: Optional[List[Dict[str, Any]]] = None
    new_sections: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChangeDetectionResult(BaseModel):
    """Result of a single change-detection invocation."""

    model_config = ConfigDict(extra="forbid")

    diff: DocumentDiff
    affected_sections: List[str] = Field(default_factory=list)
    has_changes: bool = False


# ─── Filter / list ──────────────────────────────────────────────────────


class ChangeFilter(BaseModel):
    """Filter for listing stored diffs."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    source: Optional[str] = None
    min_severity: Optional[ChangeSeverity] = None
    category: Optional[ChangeCategory] = None
    after: Optional[datetime] = None
    before: Optional[datetime] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedDiffs(BaseModel):
    """Paginated list of stored diffs."""

    model_config = ConfigDict(extra="forbid")

    items: List[DocumentDiff]
    total: int
    page: int
    page_size: int
    has_more: bool


# ─── Stats ──────────────────────────────────────────────────────────────


class ChangeDetectionStats(BaseModel):
    """Aggregate statistics for the change detection engine."""

    model_config = ConfigDict(extra="forbid")

    total_diffs: int = 0
    total_changes: int = 0
    added: int = 0
    removed: int = 0
    modified: int = 0
    by_severity: Dict[ChangeSeverity, int] = Field(default_factory=dict)
    by_category: Dict[ChangeCategory, int] = Field(default_factory=dict)
    by_source: Dict[str, int] = Field(default_factory=dict)
    average_duration_ms: float = 0.0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "ChangeCategory",
    "ChangeDetectionRequest",
    "ChangeDetectionResult",
    "ChangeDetectionStats",
    "ChangeFilter",
    "ChangeScope",
    "ChangeSeverity",
    "ChangeType",
    "ClauseChange",
    "DocumentDiff",
    "PaginatedDiffs",
    "SectionRef",
]
