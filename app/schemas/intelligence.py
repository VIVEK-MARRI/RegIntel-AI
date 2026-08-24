"""Schemas for the canonical Intelligence Query endpoint (Module 10).

The canonical endpoint ``POST /api/v1/intelligence/query`` drives the full
regulatory intelligence pipeline in a single call:

  Query → Retrieval → Evidence → Generation → Citation →
  Confidence → Hallucination → Governance routing → Audit

These schemas are intentionally separate from the lower-level M5.6
``OrchestratorRequest`` / ``OrchestratorResponse`` so the two APIs can
evolve independently.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ─── Request ──────────────────────────────────────────────────────────────────


class IntelligenceQueryRequest(BaseModel):
    """Request for the canonical end-to-end intelligence query."""

    query: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="The regulatory question to answer.",
        examples=["What are the KYC requirements under RBI guidelines?"],
    )
    source_filter: Optional[List[str]] = Field(
        default=None,
        description=(
            "Restrict retrieval to documents from these regulatory bodies "
            "(e.g. ['RBI', 'SEBI', 'IRDAI']). None = search all sources."
        ),
        examples=[["RBI", "SEBI"]],
    )
    top_k: Optional[int] = Field(
        default=None,
        ge=1,
        le=50,
        description=(
            "Maximum number of evidence chunks to retrieve. "
            "Defaults to INTELLIGENCE_TOP_K from settings."
        ),
    )
    workflow: Optional[str] = Field(
        default=None,
        description=(
            "Optional agent workflow to activate: "
            "'research' | 'compliance' | 'risk'. "
            "When omitted the lightweight pipeline coordinator is used."
        ),
        examples=["research"],
    )
    score_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum retrieval score for evidence chunks (0 = no filter).",
    )
    active_only: bool = Field(
        default=True,
        description="Whether to retrieve only active (non-superseded) documents.",
    )

    model_config = {"extra": "forbid"}


# ─── Supporting models ────────────────────────────────────────────────────────


class EvidenceChunk(BaseModel):
    """A single evidence chunk returned alongside the answer."""

    chunk_id: str
    document_id: Optional[str] = None
    content: str
    score: float
    source: Optional[str] = None
    section: Optional[str] = None
    subsection: Optional[str] = None
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AnswerSection(BaseModel):
    """Structured answer produced by the LLM."""

    executive_summary: str = ""
    detailed_explanation: str = ""
    supporting_evidence: List[str] = Field(default_factory=list)
    key_regulatory_references: List[str] = Field(default_factory=list)
    compliance_implications: str = ""
    recommended_actions: str = ""
    caveats: str = ""


class CitationItem(BaseModel):
    """A single citation attached to the answer."""

    citation_id: str
    document_title: Optional[str] = None
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    source: Optional[str] = None
    section: Optional[str] = None
    page_number: Optional[int] = None
    excerpt: Optional[str] = None
    relevance_score: Optional[float] = None


class ConfidenceBreakdown(BaseModel):
    """Per-factor confidence breakdown."""

    retrieval_relevance: Optional[float] = None
    reranker_confidence: Optional[float] = None
    source_agreement: Optional[float] = None
    chunk_coverage: Optional[float] = None
    citation_coverage: Optional[float] = None


# ─── Response ─────────────────────────────────────────────────────────────────


class IntelligenceQueryResponse(BaseModel):
    """Response from the canonical end-to-end intelligence query endpoint."""

    run_id: str = Field(description="Unique identifier for this pipeline run.")
    query: str = Field(description="The original query.")

    # ── Answer ──────────────────────────────────────────────────────────────
    answer: AnswerSection = Field(description="Structured regulatory answer.")
    citations: List[CitationItem] = Field(
        default_factory=list,
        description="Citations backing the answer.",
    )

    # ── Evidence (retrieved chunks) ─────────────────────────────────────────
    evidence: List[EvidenceChunk] = Field(
        default_factory=list,
        description="Retrieved evidence chunks used to generate the answer.",
    )

    # ── Confidence ──────────────────────────────────────────────────────────
    confidence: float = Field(
        description="Aggregate confidence score [0, 1].",
        ge=0.0,
        le=1.0,
    )
    confidence_level: str = Field(
        description="Human-readable confidence level: LOW | MEDIUM | HIGH | VERY_HIGH."
    )
    confidence_breakdown: Optional[ConfidenceBreakdown] = Field(
        default=None,
        description="Per-factor confidence breakdown.",
    )
    confidence_flags: List[str] = Field(
        default_factory=list,
        description="Advisory flags (e.g. 'low_citation_coverage', 'single_source').",
    )

    # ── Routing decisions ───────────────────────────────────────────────────
    abstained: bool = Field(
        default=False,
        description=(
            "True when confidence is below the abstention threshold and there "
            "is insufficient evidence to produce a reliable answer. "
            "The answer field will contain an explanation, not a substantive response."
        ),
    )
    requires_review: bool = Field(
        default=False,
        description=(
            "True when confidence is between the abstention threshold and the "
            "low-confidence threshold. A governance review task has been created."
        ),
    )
    governance_task_id: Optional[str] = Field(
        default=None,
        description="ID of the governance review task created (when requires_review=True).",
    )

    # ── Hallucination check ─────────────────────────────────────────────────
    hallucination_detected: Optional[bool] = Field(
        default=None,
        description="Whether the hallucination checker flagged the answer.",
    )
    faithfulness_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Faithfulness score from the hallucination checker [0, 1].",
    )

    # ── Audit ───────────────────────────────────────────────────────────────
    audit_record_id: Optional[str] = Field(
        default=None,
        description="ID of the audit record created for this query.",
    )

    # ── Performance metadata ─────────────────────────────────────────────────
    latency_ms: float = Field(
        default=0.0,
        description="End-to-end pipeline latency in milliseconds.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional diagnostic metadata.",
    )
