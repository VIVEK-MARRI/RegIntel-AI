"""Module 7.1 — Regulatory Monitoring Engine API.

Endpoints
---------
* ``POST /api/v1/monitoring/run``            — trigger one source
* ``POST /api/v1/monitoring/run-all``        — trigger all enabled sources
* ``GET  /api/v1/monitoring/discoveries``    — paginated discoveries
* ``GET  /api/v1/monitoring/discoveries/{id}`` — single discovery
* ``GET  /api/v1/monitoring/runs``           — recent monitoring runs
* ``GET  /api/v1/monitoring/runs/{id}``      — single run
* ``GET  /api/v1/monitoring/health``         — per-source health
* ``GET  /api/v1/monitoring/scheduler``      — scheduler status
* ``POST /api/v1/monitoring/scheduler/start``
* ``POST /api/v1/monitoring/scheduler/stop``
* ``POST /api/v1/monitoring/scheduler/tick`` — manual scheduler tick
* ``GET  /api/v1/monitoring/sources``        — list registered sources
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_monitoring_service
from app.schemas.monitoring import (
    DiscoveryFilter,
    PaginatedDiscoveries,
    RegulatorySource,
    RunAllResponse,
    RunMonitorRequest,
    RunMonitorResponse,
    SchedulerStatus,
)
from app.services.monitoring import MonitoringService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


# ─── Static routes FIRST (must come before /{id} routes) ───────────────


@router.get(
    "/health",
    summary="Per-source monitoring health snapshot",
)
async def health(
    service: MonitoringService = Depends(get_monitoring_service),
) -> Dict[str, Any]:
    h = service.health().model_dump(mode="json")
    return {"status": "ok", "module": "monitoring", "version": "7.1.0", **h}


@router.get(
    "/sources",
    summary="List registered monitoring sources",
)
async def list_sources(
    service: MonitoringService = Depends(get_monitoring_service),
) -> Dict[str, Any]:
    sources = [s.value for s in service.sources()]
    return {"sources": sources, "count": len(sources)}


@router.get(
    "/scheduler",
    response_model=SchedulerStatus,
    summary="Scheduler status",
)
async def scheduler_status(
    service: MonitoringService = Depends(get_monitoring_service),
) -> SchedulerStatus:
    return service.scheduler_status()


@router.post(
    "/scheduler/start",
    summary="Start the monitoring scheduler",
)
async def scheduler_start(
    service: MonitoringService = Depends(get_monitoring_service),
) -> Dict[str, Any]:
    await service.start_scheduler()
    return {
        "started": True,
        "status": service.scheduler_status().model_dump(mode="json"),
    }


@router.post(
    "/scheduler/stop",
    summary="Stop the monitoring scheduler",
)
async def scheduler_stop(
    service: MonitoringService = Depends(get_monitoring_service),
) -> Dict[str, Any]:
    await service.stop_scheduler()
    return {
        "stopped": True,
        "status": service.scheduler_status().model_dump(mode="json"),
    }


@router.post(
    "/scheduler/tick",
    response_model=RunAllResponse,
    summary="Trigger a single scheduler tick (synchronous)",
)
async def scheduler_tick(
    service: MonitoringService = Depends(get_monitoring_service),
) -> RunAllResponse:
    return await service.scheduler_tick()


@router.post(
    "/run",
    response_model=RunMonitorResponse,
    summary="Run monitoring for a single source",
)
async def run_one(
    request: RunMonitorRequest,
    service: MonitoringService = Depends(get_monitoring_service),
) -> RunMonitorResponse:
    return await service.run_source(request.source, force=request.force)


@router.post(
    "/run-all",
    response_model=RunAllResponse,
    summary="Run monitoring for every enabled source",
)
async def run_all(
    service: MonitoringService = Depends(get_monitoring_service),
) -> RunAllResponse:
    return await service.run_all()


@router.get(
    "/discoveries",
    response_model=PaginatedDiscoveries,
    summary="Paginated discovery list",
)
async def list_discoveries(
    source: Optional[RegulatorySource] = Query(None),
    change_type: Optional[str] = Query(None),
    document_url: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: MonitoringService = Depends(get_monitoring_service),
) -> PaginatedDiscoveries:
    from app.schemas.monitoring import ChangeType as _CT

    flt = DiscoveryFilter(
        source=source,
        change_type=_CT(change_type) if change_type else None,
        document_url=document_url,
        page=page,
        page_size=page_size,
    )
    return service.search(flt)


@router.get(
    "/runs",
    summary="List recent monitoring runs",
)
async def list_runs(
    source: Optional[RegulatorySource] = Query(None),
    service: MonitoringService = Depends(get_monitoring_service),
) -> Dict[str, Any]:
    runs = service.list_runs(source=source)
    return {
        "items": [r.model_dump(mode="json") for r in runs],
        "count": len(runs),
    }


# ─── Dynamic routes last ───────────────────────────────────────────────


@router.get(
    "/discoveries/{discovery_id}",
    summary="Fetch a single discovery",
)
async def get_discovery(
    discovery_id: str,
    service: MonitoringService = Depends(get_monitoring_service),
) -> Dict[str, Any]:
    d = service.get_discovery(discovery_id)
    if d is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"discovery {discovery_id!r} not found",
        )
    return d.model_dump(mode="json")


@router.get(
    "/runs/{run_id}",
    summary="Fetch a single monitoring run",
)
async def get_run(
    run_id: str,
    service: MonitoringService = Depends(get_monitoring_service),
) -> Dict[str, Any]:
    r = service.get_run(run_id)
    if r is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run {run_id!r} not found",
        )
    return r.model_dump(mode="json")


@router.get(
    "/discoveries/{discovery_id}/versions",
    summary="Version history for a discovered document",
)
async def get_versions(
    discovery_id: str,
    service: MonitoringService = Depends(get_monitoring_service),
) -> Dict[str, Any]:
    d = service.get_discovery(discovery_id)
    if d is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"discovery {discovery_id!r} not found",
        )
    versions = service.versions_for(d)
    return {
        "discovery_id": discovery_id,
        "versions": [v.model_dump(mode="json") for v in versions],
        "count": len(versions),
    }


__all__ = ["router"]
