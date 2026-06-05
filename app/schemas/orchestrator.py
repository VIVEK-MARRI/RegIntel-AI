"""Module 5.6 — Response Orchestrator schemas.

The orchestrator is the single entry point for "I have a query and a
set of retrieved chunks; produce the full intelligence-enriched
response."  It composes:

* Module 5.1 — Answer Generation
* Module 5.2 — Citation Engine
* Module 5.3 — Confidence Scoring
* Module 5.4 — Hallucination Guard
* Module 5.5 — Source Attribution Engine

Final response shape (matches the spec):

::

    {
      "query": "...",
      "answer": {...},                  # AnswerSection
      "citations": {...},               # AnnotatedAnswer
      "confidence_score": 0.92,
      "faithfulness_score": 0.95,
      "hallucination_detected": false,
      "source_attributions": [...],
      "latency_ms": 0,
      "metadata": {...}
    }
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
from app.schemas.attribution import SourceAttribution
from app.schemas.citation import AnnotatedAnswer
from app.schemas.confidence import ConfidenceLevel
from app.schemas.hallucination import HallucinationRiskLevel, VerificationMethod


# ─── Enums ──────────────────────────────────────────────────────────────────


class PipelineStep(str, Enum):
    """The ordered steps of the orchestrator pipeline."""

    ANSWER_GENERATION = "answer_generation"
    CITATION = "citation"
    CONFIDENCE = "confidence"
    HALLUCINATION = "hallucination"
    ATTRIBUTION = "attribution"


class PipelineStatus(str, Enum):
    """Per-step execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    DEGRADED = "degraded"


# ─── Pipeline control ──────────────────────────────────────────────────────


class OrchestratorRequest(BaseModel):
    """Top-level orchestrator request."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2048)
    chunks: List[RetrievedChunk] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Retrieved chunks that ground the answer.",
    )
    tone: str = Field(
        "regulatory",
        description="Answer tone (regulatory / explanatory / concise).",
    )
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(700, ge=50, le=4000)
    # Verification method for Module 5.4.
    verification_method: VerificationMethod = VerificationMethod.LEXICAL
    min_faithfulness: float = Field(0.7, ge=0.0, le=1.0)
    # Disable any of these to skip steps (e.g. for unit tests).
    enable_answer_generation: bool = Field(True)
    enable_citation: bool = Field(True)
    enable_confidence: bool = Field(True)
    enable_hallucination_guard: bool = Field(True)
    enable_attribution: bool = Field(True)
    # Per-step timeout in seconds.
    step_timeout_sec: float = Field(60.0, ge=1.0, le=600.0)
    # Fail-open: if a step fails, the pipeline continues with whatever
    # succeeded and the failure is recorded in the response.
    fail_open: bool = Field(
        True,
        description="If true, a step failure degrades the pipeline; if false, the request raises.",
    )


# ─── Pipeline telemetry ────────────────────────────────────────────────────


class StepResult(BaseModel):
    """Per-step execution record."""

    model_config = ConfigDict(extra="forbid")

    step: PipelineStep
    status: PipelineStatus = PipelineStatus.PENDING
    latency_ms: float = Field(0.0, ge=0.0)
    error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class OrchestratorMetadata(BaseModel):
    """Telemetry attached to the final response."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pipeline_version: str = Field("5.6.0")
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    total_latency_ms: float = Field(0.0, ge=0.0)
    step_results: List[StepResult] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


# ─── Final response ────────────────────────────────────────────────────────


class FinalAnswerResponse(BaseModel):
    """The full intelligence-enriched response.

    This is the contract for the orchestrator endpoint and is also the
    canonical record stored by Module 5.8 (Answer Analytics).
    """

    model_config = ConfigDict(extra="forbid")

    query: str
    answer: AnswerSection = Field(..., description="The generated answer (Module 5.1).")
    citations: AnnotatedAnswer = Field(
        ..., description="Annotated answer with inline citations (Module 5.2)."
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregate confidence from Module 5.3.",
    )
    confidence_level: ConfidenceLevel = Field(
        ..., description="Bucketed confidence (HIGH / MEDIUM / LOW)."
    )
    faithfulness_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Faithfulness from Module 5.4.",
    )
    hallucination_detected: bool = Field(
        ..., description="True if any claim is unsupported (Module 5.4)."
    )
    hallucination_risk_level: HallucinationRiskLevel = Field(
        ..., description="Risk bucketing for the faithfulness verdict."
    )
    source_attributions: List[SourceAttribution] = Field(
        default_factory=list,
        description="Segment-level attributions (Module 5.5).",
    )
    attribution_coverage_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of segments that have an attribution.",
    )
    latency_ms: float = Field(0.0, ge=0.0)
    metadata: OrchestratorMetadata = Field(default_factory=OrchestratorMetadata)


# ─── Internal context (pipeline state) ────────────────────────────────────


class ResponseContext(BaseModel):
    """Mutable pipeline context passed between steps.

    The :class:`PipelineCoordinator` owns one of these per request and
    updates it as each step runs.  Not part of the public API.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    query: str
    chunks: List[RetrievedChunk] = Field(default_factory=list)
    answer: Optional[AnswerSection] = None
    citations: Optional[AnnotatedAnswer] = None
    confidence_score: Optional[float] = None
    confidence_level: Optional[ConfidenceLevel] = None
    faithfulness_score: Optional[float] = None
    hallucination_detected: Optional[bool] = None
    hallucination_risk_level: Optional[HallucinationRiskLevel] = None
    source_attributions: List[SourceAttribution] = Field(default_factory=list)
    attribution_coverage_ratio: float = 0.0
    step_results: List[StepResult] = Field(default_factory=list)
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Pipeline knobs (set from the orchestrator request, not validated
    # in the schema to keep the context light).
    options: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "FinalAnswerResponse",
    "OrchestratorMetadata",
    "OrchestratorRequest",
    "PipelineStatus",
    "PipelineStep",
    "ResponseContext",
    "StepResult",
]
