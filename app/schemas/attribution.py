"""Module 5.5 — Source Attribution Engine schemas.

Module 5.5 is distinct from Module 5.2 (Citation Engine):

* **Module 5.2** attaches inline ``[citation]`` markers to claim text and
  builds a references list.
* **Module 5.5** (this file) produces a *segment-level* map that shows
  exactly which source document, page, and section every segment of
  the answer originated from, with a confidence score and a
  short evidence excerpt.

The output is consumed by Module 5.6 (Response Orchestrator) to
build the final ``source_attributions`` array of the response.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)


# ─── Enums ──────────────────────────────────────────────────────────────────


class AttributionSection(str, Enum):
    """Which answer section the attribution refers to."""

    EXECUTIVE_SUMMARY = "executive_summary"
    DETAILED_EXPLANATION = "detailed_explanation"
    SUPPORTING_EVIDENCE = "supporting_evidence"
    KEY_REGULATORY_REFERENCES = "key_regulatory_references"


class AttributionConfidence(str, Enum):
    """Bucketed attribution confidence."""

    HIGH = "high"        # score >= 0.7 and at least one cited chunk
    MEDIUM = "medium"    # 0.4 <= score < 0.7 OR multiple weak chunks
    LOW = "low"          # 0.15 <= score < 0.4
    NONE = "none"        # score < 0.15 (or no matching chunk)


# ─── Core models ────────────────────────────────────────────────────────────


class SourceAttribution(BaseModel):
    """Attribution record for a single answer segment.

    The segment is identified by ``section`` + ``segment_index``; the
    source is identified by ``document_id`` / ``page_number`` /
    ``section`` (chunk section) and a short ``excerpt`` of the
    matching chunk content.
    """

    model_config = ConfigDict(extra="forbid")

    attribution_id: str = Field(
        default_factory=lambda: f"att-{uuid.uuid4().hex[:8]}",
        description="Unique attribution id.",
    )
    section: AttributionSection = Field(
        ..., description="Which answer section the segment belongs to."
    )
    segment_index: int = Field(
        0,
        ge=0,
        description="0-indexed position of the segment within its section.",
    )
    segment_text: str = Field(
        ...,
        min_length=1,
        description="The actual text of the answer segment being attributed.",
    )
    document_id: str = Field(..., description="Source document UUID.")
    document_title: str = Field(..., description="Source document title.")
    chunk_id: str = Field(..., description="Source chunk UUID.")
    page_number: Optional[int] = Field(
        None, ge=0, description="Page the chunk was extracted from."
    )
    chunk_section: Optional[str] = Field(
        None, description="Section title inside the source document."
    )
    source: Optional[str] = Field(
        None, description="Regulator source (RBI / SEBI / ...)."
    )
    excerpt: str = Field(
        "", description="Short excerpt of the matching chunk (may be empty when no chunk was matched)."
    )
    similarity: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Token-overlap similarity between segment and chunk.",
    )
    confidence: AttributionConfidence = Field(
        ..., description="Bucketed confidence for this attribution."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional additional metadata (rank, score, etc).",
    )


class AttributionCoverage(BaseModel):
    """Coverage statistics for the attribution run."""

    model_config = ConfigDict(extra="forbid")

    total_segments: int = Field(0, ge=0)
    attributed_segments: int = Field(0, ge=0)
    unattributed_segments: int = Field(0, ge=0)
    coverage_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="attributed_segments / total_segments (1.0 = full coverage).",
    )
    unattributed_segment_ids: List[str] = Field(default_factory=list)
    average_similarity: float = Field(0.0, ge=0.0, le=1.0)
    high_confidence_count: int = Field(0, ge=0)
    medium_confidence_count: int = Field(0, ge=0)
    low_confidence_count: int = Field(0, ge=0)


class AttributionValidation(BaseModel):
    """Result of the :class:`AttributionValidator`."""

    model_config = ConfigDict(extra="forbid")

    valid: bool = Field(..., description="True if every segment has evidence.")
    issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class AttributionRequest(BaseModel):
    """Request payload for the attribution endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2048)
    answer: AnswerSection = Field(..., description="Structured answer (Module 5.1).")
    chunks: List[RetrievedChunk] = Field(
        ...,
        min_length=0,
        max_length=50,
        description="Retrieved chunks that grounded the answer.",
    )
    min_similarity: float = Field(
        0.10,
        ge=0.0,
        le=1.0,
        description="Minimum similarity to accept an attribution; below this the segment is unattributed.",
    )
    require_full_coverage: bool = Field(
        False,
        description="If true, validation issues include a 'partial-coverage' warning when coverage < 1.0.",
    )
    max_excerpt_length: int = Field(
        200,
        ge=20,
        le=2000,
        description="Maximum length of the chunk excerpt included in the attribution.",
    )


class AttributionMetadata(BaseModel):
    """Telemetry attached to every attribution response."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = Field(0.0, ge=0.0)
    chunks_used: int = Field(0, ge=0)
    segments_extracted: int = Field(0, ge=0)
    attributions_emitted: int = Field(0, ge=0)


class AttributionResponse(BaseModel):
    """Full response envelope for the attribution endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str
    attributions: List[SourceAttribution] = Field(default_factory=list)
    coverage: AttributionCoverage = Field(default_factory=AttributionCoverage)
    validation: AttributionValidation = Field(
        default_factory=lambda: AttributionValidation(valid=True)
    )
    metadata: AttributionMetadata = Field(default_factory=AttributionMetadata)


# ─── Helpers ────────────────────────────────────────────────────────────────


def bucket_confidence(similarity: float) -> AttributionConfidence:
    """Bucket a similarity score into an :class:`AttributionConfidence`."""
    if similarity >= 0.70:
        return AttributionConfidence.HIGH
    if similarity >= 0.40:
        return AttributionConfidence.MEDIUM
    if similarity >= 0.15:
        return AttributionConfidence.LOW
    return AttributionConfidence.NONE


def build_excerpt(text: str, *, max_length: int = 200) -> str:
    """Build a short excerpt from chunk text (trimmed to ``max_length``)."""
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 1].rstrip() + "…"


__all__ = [
    "AttributionConfidence",
    "AttributionCoverage",
    "AttributionMetadata",
    "AttributionRequest",
    "AttributionResponse",
    "AttributionSection",
    "AttributionValidation",
    "SourceAttribution",
    "bucket_confidence",
    "build_excerpt",
]
