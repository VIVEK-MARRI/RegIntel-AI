"""Module 7.2 — Automated Regulatory Ingestion API.

Endpoints
---------
* ``POST /api/v1/ingestion/run``              — trigger one ingestion
* ``POST /api/v1/ingestion/run-discovery``    — ingest a discovery by id
* ``GET  /api/v1/ingestion/runs``             — list / filter runs
* ``GET  /api/v1/ingestion/runs/{run_id}``    — single run
* ``GET  /api/v1/ingestion/runs/{run_id}/audit`` — audit trail for a run
* ``GET  /api/v1/ingestion/audit``            — global audit feed
* ``GET  /api/v1/ingestion/stats``            — aggregated stats
* ``POST /api/v1/ingestion/sync-registry``    — sync discoveries to registry
* ``GET  /api/v1/ingestion/scheduler``        — scheduler status
* ``POST /api/v1/ingestion/scheduler/start``
* ``POST /api/v1/ingestion/scheduler/stop``
* ``POST /api/v1/ingestion/scheduler/tick``
* ``GET  /api/v1/ingestion/health``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_ingestion_service, get_monitoring_service
from app.schemas.ingestion import (
    IngestionFilter,
    IngestionRunResponse,
    IngestionStatus,
    IngestionTriggerRequest,
    PaginatedIngestionRuns,
)
from app.schemas.monitoring import DiscoveryFilter
from app.services.ingestion import AutoIngestionService
from app.services.monitoring import MonitoringService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


# ─── Static routes first ──────────────────────────────────────────────


@router.get(
    "/health",
    summary="Ingestion service health",
)
async def health() -> Dict[str, Any]:
    return {"status": "ok", "module": "ingestion", "version": "7.2.0"}


@router.get(
    "/stats",
    summary="Aggregated ingestion statistics",
)
async def stats(
    service: AutoIngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    return service.stats().model_dump(mode="json")


@router.get(
    "/scheduler",
    summary="Ingestion scheduler status",
)
async def scheduler_status(
    service: AutoIngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    return service.scheduler_status().model_dump(mode="json")


@router.post(
    "/scheduler/start",
    summary="Start the ingestion scheduler",
)
async def scheduler_start(
    service: AutoIngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    await service.start_scheduler()
    return {
        "started": True,
        "status": service.scheduler_status().model_dump(mode="json"),
    }


@router.post(
    "/scheduler/stop",
    summary="Stop the ingestion scheduler",
)
async def scheduler_stop(
    service: AutoIngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    await service.stop_scheduler()
    return {
        "stopped": True,
        "status": service.scheduler_status().model_dump(mode="json"),
    }


@router.post(
    "/scheduler/tick",
    summary="Trigger a single ingestion scheduler tick",
)
async def scheduler_tick(
    service: AutoIngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    runs = await service.scheduler_tick()
    return {
        "ran": len(runs),
        "run_ids": [r.run_id for r in runs],
    }


@router.post(
    "/run",
    response_model=IngestionRunResponse,
    summary="Trigger an ingestion (by URL or discovery id)",
)
async def run_ingestion(
    request: IngestionTriggerRequest,
    service: AutoIngestionService = Depends(get_ingestion_service),
    monitoring: MonitoringService = Depends(get_monitoring_service),
) -> IngestionRunResponse:
    if not request.url and not request.discovery_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="either 'url' or 'discovery_id' must be provided",
        )
    # If only a discovery_id is provided, resolve it.
    if not request.url and request.discovery_id is not None:
        discovery = monitoring.get_discovery(request.discovery_id)
        if discovery is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"discovery {request.discovery_id!r} not found",
            )
        request = IngestionTriggerRequest(
            discovery_id=discovery.discovery_id,
            url=discovery.document_url,
            source=request.source or discovery.source.value,
            title=request.title or discovery.title,
            force=request.force,
        )
    return await service.ingest(request)


@router.post(
    "/run-discovery/{discovery_id}",
    response_model=IngestionRunResponse,
    summary="Trigger ingestion of a single discovery",
)
async def run_discovery(
    discovery_id: str,
    force: bool = Query(False),
    service: AutoIngestionService = Depends(get_ingestion_service),
    monitoring: MonitoringService = Depends(get_monitoring_service),
) -> IngestionRunResponse:
    discovery = monitoring.get_discovery(discovery_id)
    if discovery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"discovery {discovery_id!r} not found",
        )
    return await service.ingest_discovery(discovery, force=force)


@router.post(
    "/sync-registry",
    summary="Synchronise discoveries with the document registry",
)
async def sync_registry(
    source: Optional[str] = Query(None),
    service: AutoIngestionService = Depends(get_ingestion_service),
    monitoring: MonitoringService = Depends(get_monitoring_service),
) -> Dict[str, Any]:
    from app.schemas.monitoring import RegulatorySource

    flt = DiscoveryFilter(
        source=RegulatorySource(source) if source else None, page_size=200
    )
    page = monitoring.search(flt)
    result = await service.sync_registry(page.items)
    return result.model_dump(mode="json")


@router.get(
    "/runs",
    response_model=PaginatedIngestionRuns,
    summary="List / filter ingestion runs",
)
async def list_runs(
    source: Optional[str] = Query(None),
    ingestion_status: Optional[IngestionStatus] = Query(None, alias="status"),
    document_id: Optional[str] = Query(None),
    is_duplicate: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: AutoIngestionService = Depends(get_ingestion_service),
) -> PaginatedIngestionRuns:
    flt = IngestionFilter(
        source=source,
        status=ingestion_status,
        document_id=document_id,
        is_duplicate=is_duplicate,
        page=page,
        page_size=page_size,
    )
    return service.list_runs(flt)


@router.get(
    "/audit",
    summary="Global audit feed",
)
async def list_audits(
    run_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    service: AutoIngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    items = service.list_audits(run_id=run_id, limit=limit)
    return {
        "items": [a.model_dump(mode="json") for a in items],
        "count": len(items),
    }


# ─── Dynamic routes last ────────────────────────────────────────────────


@router.get(
    "/runs/{run_id}",
    response_model=IngestionRunResponse,
    summary="Fetch a single ingestion run",
)
async def get_run(
    run_id: str,
    service: AutoIngestionService = Depends(get_ingestion_service),
) -> IngestionRunResponse:
    run = service.get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"run {run_id!r} not found",
        )
    return IngestionRunResponse.from_run(run)


@router.get(
    "/runs/{run_id}/audit",
    summary="Audit trail for a specific run",
)
async def get_run_audit(
    run_id: str,
    service: AutoIngestionService = Depends(get_ingestion_service),
) -> Dict[str, Any]:
    items = service.list_audits(run_id=run_id, limit=500)
    return {
        "run_id": run_id,
        "items": [a.model_dump(mode="json") for a in items],
        "count": len(items),
    }


__all__ = ["router"]
