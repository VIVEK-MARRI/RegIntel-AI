"""Module 5.4 — Hallucination Guard API contracts.

Defines the Pydantic v2 schemas for the second-pass verification
engine.  Given an :class:`AnswerSection` (from Module 5.1) and the
:class:`RetrievedChunk` list that grounded it, the guard returns a
:class:`FaithfulnessReport` that flags every claim as either
``supported`` or ``unsupported`` and emits a single
``faithfulness_score`` in ``[0.0, 1.0]``.

Output shape (excerpt)::

    {
      "faithfulness_score": 0.96,
      "hallucination_detected": false,
      "supported_claims":   [ ... ],
      "unsupported_claims": [ ... ]
    }
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)


# ─── Enumerations ────────────────────────────────────────────────────────────


class HallucinationRiskLevel(str, Enum):
    """Discrete risk bands derived from the faithfulness score."""

    NONE = "none"        # >= 0.9
    LOW = "low"          # 0.7 - 0.9
    MEDIUM = "medium"    # 0.4 - 0.7
    HIGH = "high"        # < 0.4


class VerificationMethod(str, Enum):
    """How the verdicts were produced."""

    LLM = "llm"          # LLM-based evaluator (primary)
    LEXICAL = "lexical"  # Token-overlap fallback (offline)
    HYBRID = "hybrid"    # Both — union of unsupported claims
    MOCK = "mock"        # Deterministic offline evaluator


# ─── Claim verdict ──────────────────────────────────────────────────────────


class ClaimVerdict(BaseModel):
    """Verdict on a single claim."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(default_factory=lambda: f"clm-{uuid.uuid4().hex[:8]}")
    claim: str = Field(..., min_length=1, description="The claim text.")
    section: str = Field(
        ..., description="Which answer section the claim came from."
    )
    supported: bool = Field(..., description="True if the claim is grounded in the sources.")
    confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="LLM's confidence in the verdict (1.0 for lexical / mock).",
    )
    cited_chunk_ids: List[str] = Field(
        default_factory=list,
        description="Chunks that support the claim (empty when unsupported).",
    )
    reason: str = Field(
        "",
        description="Short justification, e.g. 'cited chunk c-1' or 'no overlap with sources'.",
    )


# ─── Report ─────────────────────────────────────────────────────────────────


class FaithfulnessReport(BaseModel):
    """Aggregated faithfulness report for one verification request."""

    model_config = ConfigDict(extra="forbid")

    query: str
    total_claims: int = Field(0, ge=0)
    supported_count: int = Field(0, ge=0)
    unsupported_count: int = Field(0, ge=0)
    supported_claims: List[ClaimVerdict] = Field(default_factory=list)
    unsupported_claims: List[ClaimVerdict] = Field(default_factory=list)
    faithfulness_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of supported claims (0 when there are no claims).",
    )
    hallucination_detected: bool = Field(
        False,
        description="True when any claim is unsupported.",
    )
    risk_level: HallucinationRiskLevel = Field(HallucinationRiskLevel.NONE)
    coverage: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of supported claims that have at least one cited chunk.",
    )


# ─── Request / Response ─────────────────────────────────────────────────────


class FaithfulnessRequest(BaseModel):
    """Request payload for the hallucination-guard endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2048)
    answer: AnswerSection = Field(..., description="Structured answer (from Module 5.1).")
    chunks: List[RetrievedChunk] = Field(
        ...,
        min_length=0,
        max_length=50,
        description="Retrieved chunks that grounded the answer.",
    )
    method: VerificationMethod = Field(
        VerificationMethod.LLM,
        description="Verification strategy. ``hybrid`` runs LLM + lexical and unions unsupported claims.",
    )
    min_faithfulness: float = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description="Faithfulness score below this triggers ``HIGH`` risk in the report.",
    )
    lexical_threshold: float = Field(
        0.15,
        ge=0.0,
        le=1.0,
        description="Token-overlap threshold for the lexical fallback.",
    )
    fail_open_on_provider_error: bool = Field(
        True,
        description="If true, an LLM provider error falls back to lexical instead of raising.",
    )


class FaithfulnessMetadata(BaseModel):
    """Telemetry attached to every response."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = Field(0.0, ge=0.0)
    provider_used: Optional[str] = Field(
        None, description="Provider that produced the LLM verdicts (None if lexical-only)."
    )
    chunks_used: int = Field(0, ge=0)


class FaithfulnessResponse(BaseModel):
    """Full response envelope for the verification endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str
    report: FaithfulnessReport
    method: VerificationMethod
    metadata: FaithfulnessMetadata


# ─── Helpers ────────────────────────────────────────────────────────────────


_NONE_THRESHOLD = 0.9
_LOW_THRESHOLD = 0.7
_MEDIUM_THRESHOLD = 0.4


def risk_level_for(
    faithfulness_score: float,
    *,
    hallucination_detected: bool = False,
) -> HallucinationRiskLevel:
    """Map a numeric faithfulness score to a :class:`HallucinationRiskLevel`.

    Score is the primary signal.  A single unsupported claim is enough
    to bump the risk level to at least ``LOW`` even when the score is
    high.
    """
    if hallucination_detected:
        if faithfulness_score >= _LOW_THRESHOLD:
            return HallucinationRiskLevel.LOW
        if faithfulness_score >= _MEDIUM_THRESHOLD:
            return HallucinationRiskLevel.MEDIUM
        return HallucinationRiskLevel.HIGH

    if faithfulness_score >= _NONE_THRESHOLD:
        return HallucinationRiskLevel.NONE
    if faithfulness_score >= _LOW_THRESHOLD:
        return HallucinationRiskLevel.LOW
    if faithfulness_score >= _MEDIUM_THRESHOLD:
        return HallucinationRiskLevel.MEDIUM
    return HallucinationRiskLevel.HIGH


__all__ = [
    "HallucinationRiskLevel",
    "VerificationMethod",
    "ClaimVerdict",
    "FaithfulnessReport",
    "FaithfulnessRequest",
    "FaithfulnessMetadata",
    "FaithfulnessResponse",
    "risk_level_for",
]
