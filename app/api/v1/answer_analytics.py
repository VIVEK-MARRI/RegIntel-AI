"""Module 5.8 — Answer Analytics Platform API.

Endpoints
---------
* ``GET  /api/v1/answers/analytics``   — overall snapshot.
* ``GET  /api/v1/answers/quality``     — quality-focused snapshot.
* ``GET  /api/v1/answers/hallucinations`` — hallucination breakdown.
* ``GET  /api/v1/answers/citations``   — citation coverage.
* ``GET  /api/v1/answers/health``      — health probe.
* ``POST /api/v1/answers/record``      — record a response (used by
  the orchestrator when wiring analytics into the request path).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    get_answer_analytics_service,
    get_answer_health_monitor,
)
from app.schemas.analytics_v2 import (
    AnalyticsWindow,
    AnswerAnalyticsEvent,
    AnswerAnalyticsSnapshot,
    AnswerHealthReport,
)
from app.schemas.orchestrator import FinalAnswerResponse
from app.services.answer_analytics import (
    AnswerAnalyticsService,
    AnswerHealthMonitor,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/answers", tags=["answer-analytics"])


def _parse_window(window: str) -> AnalyticsWindow:
    try:
        return AnalyticsWindow(window)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid window: {window!r}",
        )


@router.get(
    "/analytics",
    response_model=AnswerAnalyticsSnapshot,
    summary="Overall analytics snapshot",
)
async def analytics(
    window: str = Query("all", description="Time window (hour/day/week/month/all)."),
    service: AnswerAnalyticsService = Depends(get_answer_analytics_service),
) -> AnswerAnalyticsSnapshot:
    return service.snapshot(_parse_window(window))


@router.get(
    "/quality",
    response_model=AnswerAnalyticsSnapshot,
    summary="Quality-focused snapshot (same payload; tag for dashboards)",
)
async def quality(
    window: str = Query("all"),
    service: AnswerAnalyticsService = Depends(get_answer_analytics_service),
) -> AnswerAnalyticsSnapshot:
    return service.snapshot(_parse_window(window))


@router.get(
    "/hallucinations",
    response_model=AnswerAnalyticsSnapshot,
    summary="Hallucination-focused snapshot",
)
async def hallucinations(
    window: str = Query("all"),
    service: AnswerAnalyticsService = Depends(get_answer_analytics_service),
) -> AnswerAnalyticsSnapshot:
    return service.snapshot(_parse_window(window))


@router.get(
    "/citations",
    response_model=AnswerAnalyticsSnapshot,
    summary="Citation-coverage-focused snapshot",
)
async def citations(
    window: str = Query("all"),
    service: AnswerAnalyticsService = Depends(get_answer_analytics_service),
) -> AnswerAnalyticsSnapshot:
    return service.snapshot(_parse_window(window))


@router.get(
    "/health",
    response_model=AnswerHealthReport,
    summary="Health probe for the answer analytics platform",
)
async def health(
    monitor: AnswerHealthMonitor = Depends(get_answer_health_monitor),
) -> AnswerHealthReport:
    return monitor.check()


@router.post(
    "/record",
    response_model=AnswerAnalyticsEvent,
    summary="Record a final response for analytics",
)
async def record(
    payload: dict,
    service: AnswerAnalyticsService = Depends(get_answer_analytics_service),
) -> AnswerAnalyticsEvent:
    if "response" not in payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`response` is required",
        )
    try:
        response = FinalAnswerResponse.model_validate(payload["response"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid response: {exc}",
        ) from exc
    return service.record(response, total_tokens=int(payload.get("total_tokens", 0)))


__all__ = ["router"]
