"""Module 6.5 — Multi-Document Reasoning API.

Endpoints
---------
* ``POST /api/v1/reasoning/run``            — run the coordinator with a
  :class:`ReasoningRequest`.
* ``POST /api/v1/reasoning/compare``        — pairwise comparison only.
* ``POST /api/v1/reasoning/timeline``       — timeline extraction.
* ``POST /api/v1/reasoning/changes``        — change detection.
* ``POST /api/v1/reasoning/contradictions`` — contradiction detection.
* ``POST /api/v1/reasoning/cross-summary``  — cross-document summary.
* ``GET  /api/v1/reasoning/health``         — health probe.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_multi_document_reasoner
from app.schemas.reasoning import (
    ChangeReport,
    ContradictionReport,
    CrossDocumentSummary,
    DocumentDiff,
    ReasoningMode,
    ReasoningRequest,
    ReasoningResponse,
    Timeline,
)
from app.services.reasoning import MultiDocumentReasoner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reasoning", tags=["reasoning"])


# ── Inline request schemas (mode-specific convenience endpoints) ──────────


class _ModeRequest(BaseModel):
    """Request body shared by the mode-specific endpoints."""

    model_config = {"extra": "forbid"}

    query: str = Field(..., min_length=1, max_length=4096)
    chunks: List[Dict[str, Any]] = Field(..., min_length=2, max_length=200)
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.get(
    "/health",
    summary="Health probe for multi-document reasoning",
)
async def health() -> dict:
    return {
        "status": "ok",
        "module": "reasoning",
        "version": "6.5.0",
    }


@router.post(
    "/run",
    response_model=ReasoningResponse,
    summary="Run the full reasoning coordinator on a request",
)
async def run(
    request: ReasoningRequest,
    reasoner: MultiDocumentReasoner = Depends(get_multi_document_reasoner),
) -> ReasoningResponse:
    try:
        return reasoner.reason(request)
    except Exception as exc:  # pragma: no cover
        logger.exception("Reasoning failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"reasoning failed: {exc}",
        ) from exc


@router.post(
    "/compare",
    response_model=ReasoningResponse,
    summary="Compare two documents (first two document_ids in chunks)",
)
async def compare(
    request: _ModeRequest,
    reasoner: MultiDocumentReasoner = Depends(get_multi_document_reasoner),
) -> ReasoningResponse:
    return reasoner.compare(request.query, request.chunks, metadata=request.metadata)


@router.post(
    "/timeline",
    response_model=ReasoningResponse,
    summary="Extract a timeline from a chunk collection",
)
async def extract_timeline(
    request: _ModeRequest,
    reasoner: MultiDocumentReasoner = Depends(get_multi_document_reasoner),
) -> ReasoningResponse:
    return reasoner.timeline(request.query, request.chunks, metadata=request.metadata)


@router.post(
    "/changes",
    response_model=ReasoningResponse,
    summary="Detect regulatory changes between two documents",
)
async def detect_changes(
    request: _ModeRequest,
    reasoner: MultiDocumentReasoner = Depends(get_multi_document_reasoner),
) -> ReasoningResponse:
    return reasoner.changes(request.query, request.chunks, metadata=request.metadata)


@router.post(
    "/contradictions",
    response_model=ReasoningResponse,
    summary="Find contradictions across documents",
)
async def find_contradictions(
    request: _ModeRequest,
    reasoner: MultiDocumentReasoner = Depends(get_multi_document_reasoner),
) -> ReasoningResponse:
    return reasoner.contradictions(request.query, request.chunks, metadata=request.metadata)


@router.post(
    "/cross-summary",
    response_model=ReasoningResponse,
    summary="Produce a unified cross-document summary",
)
async def summarise_cross(
    request: _ModeRequest,
    reasoner: MultiDocumentReasoner = Depends(get_multi_document_reasoner),
) -> ReasoningResponse:
    return reasoner.cross_summary(request.query, request.chunks, metadata=request.metadata)


__all__ = ["router"]
