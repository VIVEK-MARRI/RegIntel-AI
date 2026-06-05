"""Module 7.5 — Regulatory Alerting System API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_alert_service
from app.schemas.alerts import (
    AlertCreateRequest,
    AlertFilter,
    AlertSeverity,
    AlertStatus,
    DigestPeriod,
    DigestRequest,
    SubscriptionCreateRequest,
)
from app.services.alerting import AlertService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerting"])


# ─── Static first ─────────────────────────────────────────────────────


@router.get(
    "/health",
    summary="Alerting service health",
)
async def health() -> Dict[str, Any]:
    return {"status": "ok", "module": "alerting", "version": "7.5.0"}


@router.get(
    "/stats",
    summary="Aggregated alert statistics",
)
async def stats(
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    return service.stats().model_dump(mode="json")


# ─── Digests ─────────────────────────────────────────────────────────


@router.get(
    "/digest/daily",
    summary="Generate a daily digest",
)
async def daily_digest(
    source: Optional[str] = Query(None),
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    req = DigestRequest(period=DigestPeriod.DAILY, source=source)
    return service.generate_digest(req).model_dump(mode="json")


@router.get(
    "/digest/weekly",
    summary="Generate a weekly digest",
)
async def weekly_digest(
    source: Optional[str] = Query(None),
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    req = DigestRequest(period=DigestPeriod.WEEKLY, source=source)
    return service.generate_digest(req).model_dump(mode="json")


# ─── Subscriptions ──────────────────────────────────────────────────


@router.post(
    "/subscriptions",
    summary="Create a subscription",
)
async def create_subscription(
    request: SubscriptionCreateRequest,
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    try:
        sub = service.create_subscription(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return sub.model_dump(mode="json")


@router.get(
    "/subscriptions",
    summary="List subscriptions",
)
async def list_subscriptions(
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    return {"items": [s.model_dump(mode="json") for s in service.list_subscriptions()]}


@router.delete(
    "/subscriptions/{sub_id}",
    summary="Remove a subscription",
)
async def delete_subscription(
    sub_id: str,
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    ok = service.remove_subscription(sub_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"subscription {sub_id!r} not found",
        )
    return {"removed": True, "subscription_id": sub_id}


# ─── Alerts (create / list / process) ──────────────────────────────


@router.post(
    "",
    summary="Create an alert",
)
async def create_alert(
    request: AlertCreateRequest,
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    return service.create_alert(request).model_dump(mode="json")


@router.post(
    "/process",
    summary="Process all pending alerts",
)
async def process_pending(
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    processed = await service.process_pending()
    return {
        "processed_count": len(processed),
        "items": [a.model_dump(mode="json") for a in processed],
    }


@router.get(
    "",
    summary="List / filter alerts",
)
async def list_alerts(
    source: Optional[str] = Query(None),
    severity: Optional[AlertSeverity] = Query(None),
    alert_status: Optional[AlertStatus] = Query(None, alias="status"),
    after: Optional[float] = Query(None),
    before: Optional[float] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    flt = AlertFilter(
        source=source,
        severity=severity,
        status=alert_status,
        after=after,
        before=before,
        page=page,
        page_size=page_size,
    )
    return service.search(flt).model_dump(mode="json")


# ─── Dynamic last ─────────────────────────────────────────────────────


@router.get(
    "/subscriptions/{sub_id}",
    summary="Fetch a single subscription",
)
async def get_subscription(
    sub_id: str,
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    s = service.get_subscription(sub_id)
    if s is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"subscription {sub_id!r} not found",
        )
    return s.model_dump(mode="json")


@router.get(
    "/{alert_id}",
    summary="Fetch a single alert",
)
async def get_alert(
    alert_id: str,
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    a = service.get(alert_id)
    if a is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"alert {alert_id!r} not found",
        )
    return a.model_dump(mode="json")


@router.get(
    "/{alert_id}/deliveries",
    summary="List delivery attempts for an alert",
)
async def list_deliveries(
    alert_id: str,
    service: AlertService = Depends(get_alert_service),
) -> Dict[str, Any]:
    items = service.deliveries_for(alert_id)
    return {"items": [d.model_dump(mode="json") for d in items]}


__all__ = ["router"]
