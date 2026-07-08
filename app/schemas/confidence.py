"""Module 5.3 — Confidence Scoring API contracts.

Defines the Pydantic v2 schemas for the confidence engine.  The
engine scores every answer on five weighted factors and returns an
overall confidence in ``[0.0, 1.0]`` plus a band:

================  ==================
confidence        level
================  ==================
``>= 0.9``        ``HIGH``
``>= 0.7``        ``MEDIUM``
``<  0.7``        ``LOW``
================  ==================

Factors
-------

* ``retrieval_relevance``  — average retrieval score of supporting chunks
* ``reranker_confidence``  — average cross-encoder score (if available)
* ``source_agreement``     — how consistent the sources are
* ``chunk_coverage``       — how many chunks back the answer
* ``citation_coverage``    — fraction of claims that received a citation

When the reranker is not available, its weight is redistributed
proportionally across the remaining factors.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enumerations ────────────────────────────────────────────────────────────


class ConfidenceLevel(str, Enum):
    """Discrete confidence bands."""

    HIGH = "high"  # >= 0.9
    MEDIUM = "medium"  # 0.7 - 0.9
    LOW = "low"  # < 0.7


class ConfidenceFactorName(str, Enum):
    """Canonical factor names used throughout the engine."""

    RETRIEVAL_RELEVANCE = "retrieval_relevance"
    RERANKER_CONFIDENCE = "reranker_confidence"
    SOURCE_AGREEMENT = "source_agreement"
    CHUNK_COVERAGE = "chunk_coverage"
    CITATION_COVERAGE = "citation_coverage"


class ConfidenceFlag(str, Enum):
    """Advisory flags attached to a confidence response."""

    LOW_CITATION_COVERAGE = "low_citation_coverage"
    NO_RERANK_SCORES = "no_rerank_scores"
    SINGLE_SOURCE = "single_source"
    LOW_CHUNK_COUNT = "low_chunk_count"
    HIGH_SCORE_VARIANCE = "high_score_variance"
    EMPTY_CHUNKS = "empty_chunks"
    NO_ANSWER = "no_answer"


# ─── Factor / Breakdown ─────────────────────────────────────────────────────


class ConfidenceFactor(BaseModel):
    """A single factor score with its weight and contribution."""

    model_config = ConfigDict(extra="forbid")

    name: ConfidenceFactorName = Field(..., description="Factor identifier.")
    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Raw factor score in [0.0, 1.0].",
    )
    weight: float = Field(
        ...,
        ge=0.0,
        description="Assigned weight (sum of active weights normalises the breakdown).",
    )
    contribution: float = Field(
        ...,
        description="score * weight / total_weight (the share contributed to the overall).",
    )
    available: bool = Field(
        True,
        description="False when the factor could not be computed (e.g. no rerank scores).",
    )
    details: Optional[Dict[str, Any]] = Field(
        None,
        description="Free-form diagnostic payload (averages, counts, etc.).",
    )


class ConfidenceBreakdown(BaseModel):
    """All factors that fed into the final confidence score."""

    model_config = ConfigDict(extra="forbid")

    factors: List[ConfidenceFactor] = Field(default_factory=list)
    weights: Dict[str, float] = Field(
        default_factory=dict,
        description="Effective weights used in the aggregation (normalised).",
    )
    total_weight: float = Field(0.0, ge=0.0)


# ─── Request / Response ─────────────────────────────────────────────────────


class ConfidenceRequest(BaseModel):
    """Request payload for the confidence endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2048)
    answer: Dict[str, Any] = Field(
        ...,
        description="Answer payload (typically Module 5.1's AnswerSection, expressed as a dict).",
    )
    chunks: List[Dict[str, Any]] = Field(
        ...,
        min_length=0,
        max_length=50,
        description="Retrieved chunks (parallel to retrieval scores; the engine reads score / page / source).",
    )
    retrieval_scores: Optional[List[float]] = Field(
        None,
        description="Optional retrieval scores parallel to chunks. If absent, the engine reads each chunk's score field.",
    )
    reranker_scores: Optional[List[float]] = Field(
        None,
        description="Optional reranker scores parallel to chunks. When absent, the reranker factor is unavailable.",
    )
    citation_coverage: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Optional precomputed citation coverage ratio (from Module 5.2).",
    )
    weights: Optional[Dict[str, float]] = Field(
        None,
        description="Custom factor weights. Missing keys fall back to defaults; weights are renormalised.",
    )
    min_chunks_for_full_coverage: int = Field(
        5,
        ge=1,
        le=50,
        description="Chunk count that maps to chunk_coverage = 1.0.",
    )


class ConfidenceResponse(BaseModel):
    """Full response envelope for the confidence endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    level: ConfidenceLevel
    breakdown: ConfidenceBreakdown
    flags: List[ConfidenceFlag] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(
        default_factory=lambda: {
            "request_id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


# ─── Level Helpers ──────────────────────────────────────────────────────────


_HIGH_THRESHOLD = 0.9
_MEDIUM_THRESHOLD = 0.7


def level_for(confidence: float) -> ConfidenceLevel:
    """Map a numeric confidence to a :class:`ConfidenceLevel`."""
    if confidence >= _HIGH_THRESHOLD:
        return ConfidenceLevel.HIGH
    if confidence >= _MEDIUM_THRESHOLD:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


# ─── Default Weights ────────────────────────────────────────────────────────


DEFAULT_WEIGHTS: Dict[str, float] = {
    ConfidenceFactorName.RETRIEVAL_RELEVANCE.value: 0.25,
    ConfidenceFactorName.RERANKER_CONFIDENCE.value: 0.20,
    ConfidenceFactorName.SOURCE_AGREEMENT.value: 0.15,
    ConfidenceFactorName.CHUNK_COVERAGE.value: 0.20,
    ConfidenceFactorName.CITATION_COVERAGE.value: 0.20,
}


__all__ = [
    "ConfidenceLevel",
    "ConfidenceFactorName",
    "ConfidenceFlag",
    "ConfidenceFactor",
    "ConfidenceBreakdown",
    "ConfidenceRequest",
    "ConfidenceResponse",
    "level_for",
    "DEFAULT_WEIGHTS",
]
