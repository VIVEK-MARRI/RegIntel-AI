"""Module 6.7 — Copilot Analytics API.

Endpoints
---------
* ``GET /api/v1/copilot/analytics``         — full CopilotMetrics.
* ``GET /api/v1/copilot/usage``             — lightweight UsageStats.
* ``GET /api/v1/copilot/analytics-health``  — health probe.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_copilot_analytics_service
from app.schemas.copilot_analytics import (
    AnalyticsWindow,
    CopilotMetrics,
    UsageStats,
)
from app.services.copilot_analytics import CopilotAnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/copilot", tags=["copilot-analytics"])


@router.get(
    "/analytics",
    response_model=CopilotMetrics,
    summary="Aggregated copilot metrics for a time window",
)
async def get_analytics(
    window: AnalyticsWindow = Query(
        AnalyticsWindow.ALL, description="Time window to aggregate over."
    ),
    service: CopilotAnalyticsService = Depends(get_copilot_analytics_service),
) -> CopilotMetrics:
    try:
        return service.metrics(window=window)
    except Exception as exc:  # pragma: no cover
        logger.exception("Analytics failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"analytics failed: {exc}",
        ) from exc


@router.get(
    "/usage",
    response_model=UsageStats,
    summary="Lightweight usage snapshot for a time window",
)
async def get_usage(
    window: AnalyticsWindow = Query(AnalyticsWindow.ALL),
    service: CopilotAnalyticsService = Depends(get_copilot_analytics_service),
) -> UsageStats:
    return service.usage(window=window)


@router.get(
    "/analytics-health",
    summary="Health probe for the copilot analytics service",
)
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "module": "copilot_analytics",
        "version": "6.7.0",
    }


__all__ = ["router"]
