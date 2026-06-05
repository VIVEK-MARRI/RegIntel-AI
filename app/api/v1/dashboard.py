"""Module 7.8 — Executive Dashboard API."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.api.dependencies import get_executive_dashboard_service
from app.services.dashboard import ExecutiveDashboardService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ─── Top-level snapshot ──────────────────────────────────────────────


@router.get(
    "/health",
    summary="Dashboard service health",
)
async def health() -> Dict[str, Any]:
    return {"status": "ok", "module": "dashboard", "version": "7.8.0"}


@router.get(
    "/snapshot",
    summary="Full executive dashboard snapshot",
)
async def snapshot(
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> Dict[str, Any]:
    return service.snapshot().model_dump(mode="json")


# ─── Per-view endpoints ─────────────────────────────────────────────


@router.get(
    "/compliance",
    summary="Compliance KPI summary",
)
async def compliance(
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> Dict[str, Any]:
    return service.compliance_view().model_dump(mode="json")


@router.get(
    "/trends",
    summary="Regulatory change trends",
)
async def trends(
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> Dict[str, Any]:
    items = service.trends_view()
    return {
        "items": [s.model_dump(mode="json") for s in items],
        "count": len(items),
    }


@router.get(
    "/impact-distribution",
    summary="Distribution of impact reports by level",
)
async def impact_distribution(
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> Dict[str, Any]:
    return service.impact_view().model_dump(mode="json")


@router.get(
    "/alerts",
    summary="Alert metrics overview",
)
async def alerts(
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> Dict[str, Any]:
    return service.alerts_view().model_dump(mode="json")


@router.get(
    "/monitoring",
    summary="Monitoring health summary",
)
async def monitoring(
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> Dict[str, Any]:
    return service.monitoring_view().model_dump(mode="json")


@router.get(
    "/system",
    summary="System health summary",
)
async def system(
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> Dict[str, Any]:
    return service.system_view().model_dump(mode="json")


@router.get(
    "/insights",
    summary="Risk insights + overall risk level",
)
async def insights(
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> Dict[str, Any]:
    return service.insights_view().model_dump(mode="json")


@router.get(
    "/risk",
    summary="Aggregate risk score and level",
)
async def risk(
    service: ExecutiveDashboardService = Depends(get_executive_dashboard_service),
) -> Dict[str, Any]:
    res = service.insights_view()
    return {
        "risk_level": res.risk_level.value,
        "risk_score": res.risk_score,
        "generated_at": res.generated_at,
    }


__all__ = ["router"]
