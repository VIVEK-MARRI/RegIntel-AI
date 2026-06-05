"""Module 5.6 — Response Orchestrator API.

Endpoints
---------
* ``POST /api/v1/orchestrator/answer`` — full intelligence pipeline.
* ``GET  /api/v1/orchestrator/health`` — health probe.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_response_orchestrator
from app.schemas.orchestrator import FinalAnswerResponse, OrchestratorRequest
from app.services.orchestrator import ResponseOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


@router.post(
    "/answer",
    response_model=FinalAnswerResponse,
    summary="Run the full intelligence pipeline",
)
async def answer(
    request: OrchestratorRequest,
    orchestrator: ResponseOrchestrator = Depends(get_response_orchestrator),
) -> FinalAnswerResponse:
    if not request.query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`query` must be a non-empty string",
        )
    if not request.chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`chunks` must contain at least one chunk",
        )
    try:
        return await orchestrator.answer(request)
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("Orchestrator pipeline failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"orchestrator pipeline failed: {exc}",
        ) from exc


@router.get(
    "/health",
    summary="Health probe for the response orchestrator",
)
async def health() -> dict:
    return {
        "status": "ok",
        "module": "response_orchestrator",
        "version": "5.6.0",
    }


__all__ = ["router"]
