"""Module 5.3 — Confidence Scoring API Layer.

Endpoints (mounted under ``/api/v1``):

* ``POST /confidence/score``  — score an answer and return the
  overall confidence + per-factor breakdown + advisory flags.
* ``GET  /confidence/metrics``  — read the in-process metrics
  snapshot (per-factor distribution, level distribution, flags).
* ``POST /confidence/metrics/reset``  — reset the in-process
  metrics (mainly for tests).
* ``GET  /confidence/health``  — liveness probe.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_confidence_service
from app.schemas.confidence import (
    ConfidenceRequest,
    ConfidenceResponse,
)
from app.services.confidence import ConfidenceService
from app.services.observability import track_request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["confidence"])


# ─── POST /confidence/score ──────────────────────────────────────────────────


@router.post(
    "/confidence/score",
    response_model=ConfidenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Score an answer with confidence + per-factor breakdown",
)
async def score_confidence(
    request: ConfidenceRequest,
    service: ConfidenceService = Depends(get_confidence_service),
) -> ConfidenceResponse:
    """Compute the overall confidence and return a full breakdown.

    The handler:
      1. Validates the request (Pydantic).
      2. Wraps the call in ``track_request`` for observability.
      3. Delegates to :meth:`ConfidenceService.score`.
      4. Returns the structured :class:`ConfidenceResponse`.
    """
    with track_request(
        endpoint="/api/v1/confidence/score",
        strategy="confidence",
    ) as ctx:
        try:
            response = service.score(request)
        except ValueError as exc:
            logger.warning("Validation error in confidence scoring: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except Exception as exc:
            logger.exception("Confidence scoring failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Confidence scoring failed: {exc}",
            ) from exc
        try:
            ctx.rerank_used = False  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass

    logger.info(
        "confidence.score query=%s confidence=%.3f level=%s",
        request.query[:60],
        response.confidence,
        response.level.value,
    )
    return response


# ─── GET /confidence/metrics ─────────────────────────────────────────────────


@router.get(
    "/confidence/metrics",
    status_code=status.HTTP_200_OK,
    summary="Read the in-process confidence metrics snapshot",
)
async def read_metrics(
    service: ConfidenceService = Depends(get_confidence_service),
) -> Dict[str, Any]:
    return service.metrics.snapshot()


# ─── POST /confidence/metrics/reset ──────────────────────────────────────────


@router.post(
    "/confidence/metrics/reset",
    status_code=status.HTTP_200_OK,
    summary="Reset the in-process confidence metrics",
)
async def reset_metrics(
    service: ConfidenceService = Depends(get_confidence_service),
) -> Dict[str, Any]:
    service.metrics.reset()
    return {"status": "ok", "reset": True}


# ─── GET /confidence/health ──────────────────────────────────────────────────


@router.get(
    "/confidence/health",
    status_code=status.HTTP_200_OK,
    summary="Health check for the confidence engine",
)
async def confidence_health() -> dict:
    return {"status": "ok", "module": "5.3-confidence-engine"}


__all__ = ["router"]
