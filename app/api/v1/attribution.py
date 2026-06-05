"""Module 5.5 — Source Attribution API.

Endpoints
---------
* ``POST /api/v1/attribution/attribute`` — produce segment-level
  source attributions for an answer.
* ``GET  /api/v1/attribution/health`` — health probe.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_attribution_service
from app.schemas.attribution import (
    AttributionRequest,
    AttributionResponse,
)
from app.services.attribution import SourceAttributionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attribution", tags=["attribution"])


@router.post(
    "/attribute",
    response_model=AttributionResponse,
    summary="Produce segment-level source attributions for an answer",
)
async def attribute(
    request: AttributionRequest,
    service: SourceAttributionService = Depends(get_attribution_service),
) -> AttributionResponse:
    if not request.query.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`query` must be a non-empty string",
        )
    if not request.answer.executive_summary.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`answer.executive_summary` must be a non-empty string",
        )
    if not request.answer.detailed_explanation.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`answer.detailed_explanation` must be a non-empty string",
        )
    try:
        return service.attribute(request)
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("Source attribution failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"source attribution failed: {exc}",
        ) from exc


@router.get(
    "/health",
    summary="Health probe for the source attribution engine",
)
async def health(
    service: SourceAttributionService = Depends(get_attribution_service),
) -> dict:
    return {
        "status": "ok",
        "module": "source_attribution",
        "version": "5.5.0",
    }


__all__ = ["router"]
