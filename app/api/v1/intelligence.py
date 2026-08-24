"""Canonical Intelligence Query Endpoint (Module 10).

Provides ``POST /api/v1/intelligence/query`` — a single endpoint that drives
the full regulatory intelligence pipeline:

  Query → Hybrid Retrieval → Evidence → Answer Generation → Citation →
  Confidence Scoring → Hallucination Check → Confidence Routing → Audit

This is the primary entry point for end-users. It internally composes the
M4 retrieval stack, M5 answer generation + confidence + hallucination, M8.6
governance, and M8.7 audit services.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_answer_generator_service,
    get_citation_service,
    get_confidence_service,
    get_governance_service,
    get_audit_service,
    get_hallucination_guard_service,
    get_hybrid_rerank_pipeline,
    get_llm_provider,
)
from app.schemas.intelligence import (
    IntelligenceQueryRequest,
    IntelligenceQueryResponse,
)
from app.services.intelligence.pipeline import build_intelligence_pipeline

logger = logging.getLogger(__name__)

intelligence_router = APIRouter()


@intelligence_router.post(
    "/query",
    response_model=IntelligenceQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="End-to-end regulatory intelligence query",
    description=(
        "Accepts a natural-language regulatory question and runs the full "
        "intelligence pipeline: hybrid retrieval → answer generation → "
        "citation → confidence scoring → hallucination check → "
        "confidence-based routing (abstain | review | return) → audit trail. "
        "\n\nReturns a structured answer with citations, evidence, confidence "
        "score, and governance metadata."
    ),
    response_description="Structured regulatory intelligence response.",
    tags=["Intelligence"],
)
async def query_intelligence(
    request: IntelligenceQueryRequest,
    hybrid_retriever=Depends(get_hybrid_rerank_pipeline),
    answer_generator=Depends(get_answer_generator_service),
    citation_service=Depends(get_citation_service),
    confidence_service=Depends(get_confidence_service),
    hallucination_guard=Depends(get_hallucination_guard_service),
    governance_service=Depends(get_governance_service),
    audit_service=Depends(get_audit_service),
) -> IntelligenceQueryResponse:
    """Run the canonical end-to-end intelligence pipeline."""
    pipeline = build_intelligence_pipeline(
        hybrid_retriever=hybrid_retriever,
        answer_generator=answer_generator,
        citation_service=citation_service,
        confidence_service=confidence_service,
        hallucination_guard=hallucination_guard,
        governance_service=governance_service,
        audit_service=audit_service,
    )
    try:
        return await pipeline.run(request)
    except Exception as exc:
        logger.error(
            "intelligence.query unhandled error: %s", exc, exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Intelligence pipeline error: {type(exc).__name__}: {exc}",
        ) from exc


@intelligence_router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Intelligence pipeline health",
    description="Returns basic health information for the intelligence pipeline services.",
    tags=["Intelligence"],
)
async def intelligence_health(
    hybrid_retriever=Depends(get_hybrid_rerank_pipeline),
    answer_generator=Depends(get_answer_generator_service),
    confidence_service=Depends(get_confidence_service),
) -> dict:
    """Quick health check for the intelligence pipeline dependencies."""
    return {
        "status": "healthy",
        "services": {
            "hybrid_retriever": type(hybrid_retriever).__name__,
            "answer_generator": type(answer_generator).__name__,
            "confidence_service": type(confidence_service).__name__,
        },
    }
