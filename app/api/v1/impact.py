"""Module 7.4 — Regulatory Impact Analysis API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_impact_analysis_service
from app.schemas.impact import (
    ImpactAnalysisRequest,
    ImpactAnalysisResult,
    ImpactFilter,
    ImpactLevel,
)
from app.services.impact_analysis import ImpactAnalysisService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/impact", tags=["impact-analysis"])


# ─── Static first ─────────────────────────────────────────────────────


@router.get(
    "/health",
    summary="Impact analysis service health",
)
async def health() -> Dict[str, Any]:
    return {"status": "ok", "module": "impact_analysis", "version": "7.4.0"}


@router.get(
    "/stats",
    summary="Aggregated impact analysis statistics",
)
async def stats(
    service: ImpactAnalysisService = Depends(get_impact_analysis_service),
) -> Dict[str, Any]:
    return service.stats().model_dump(mode="json")


# ─── Analyse ─────────────────────────────────────────────────────────


@router.post(
    "/analyze",
    response_model=ImpactAnalysisResult,
    summary="Run impact analysis for a diff",
)
async def analyze(
    request: ImpactAnalysisRequest,
    service: ImpactAnalysisService = Depends(get_impact_analysis_service),
) -> ImpactAnalysisResult:
    try:
        return service.analyze(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("impact analysis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"impact analysis failed: {exc}",
        ) from exc


# ─── List ─────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="List / filter impact reports",
)
async def list_impacts(
    document_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    min_level: Optional[ImpactLevel] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: ImpactAnalysisService = Depends(get_impact_analysis_service),
) -> Dict[str, Any]:
    flt = ImpactFilter(
        document_id=document_id,
        source=source,
        min_level=min_level,
        page=page,
        page_size=page_size,
    )
    return service.search(flt).model_dump(mode="json")


# ─── Dynamic last ─────────────────────────────────────────────────────


@router.get(
    "/{report_id}",
    summary="Fetch a single impact report",
)
async def get_report(
    report_id: str,
    service: ImpactAnalysisService = Depends(get_impact_analysis_service),
) -> Dict[str, Any]:
    r = service.get(report_id)
    if r is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"report {report_id!r} not found",
        )
    return r.model_dump(mode="json")


__all__ = ["router"]
