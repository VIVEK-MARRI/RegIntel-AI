"""Module 7.3 — Regulatory Change Detection Engine API.

Endpoints
---------
* ``POST /api/v1/changes/detect``   — run change detection
* ``GET  /api/v1/changes``          — list / filter stored diffs
* ``GET  /api/v1/changes/{diff_id}`` — single diff
* ``GET  /api/v1/changes/stats``    — aggregate stats
* ``GET  /api/v1/changes/health``
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_change_detection_service
from app.schemas.change import (
    ChangeCategory,
    ChangeDetectionRequest,
    ChangeDetectionResult,
    ChangeFilter,
    ChangeSeverity,
)
from app.services.change_detection import ChangeDetectionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/changes", tags=["change-detection"])


# ─── Static first ─────────────────────────────────────────────────────


@router.get(
    "/health",
    summary="Change detection service health",
)
async def health() -> Dict[str, Any]:
    return {"status": "ok", "module": "change_detection", "version": "7.3.0"}


@router.get(
    "/stats",
    summary="Aggregated change detection statistics",
)
async def stats(
    service: ChangeDetectionService = Depends(get_change_detection_service),
) -> Dict[str, Any]:
    return service.stats().model_dump(mode="json")


# ─── Detect ───────────────────────────────────────────────────────────


@router.post(
    "/detect",
    response_model=ChangeDetectionResult,
    summary="Detect changes between two document versions",
)
async def detect(
    request: ChangeDetectionRequest,
    service: ChangeDetectionService = Depends(get_change_detection_service),
) -> ChangeDetectionResult:
    try:
        return service.detect(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("change detection failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"change detection failed: {exc}",
        ) from exc


# ─── List ─────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="List / filter stored diffs",
)
async def list_diffs(
    document_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    min_severity: Optional[ChangeSeverity] = Query(None),
    category: Optional[ChangeCategory] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: ChangeDetectionService = Depends(get_change_detection_service),
) -> Dict[str, Any]:
    flt = ChangeFilter(
        document_id=document_id,
        source=source,
        min_severity=min_severity,
        category=category,
        page=page,
        page_size=page_size,
    )
    res = service.search(flt)
    return res.model_dump(mode="json")


# ─── Dynamic last ─────────────────────────────────────────────────────


@router.get(
    "/{diff_id}",
    summary="Fetch a single diff",
)
async def get_diff(
    diff_id: str,
    service: ChangeDetectionService = Depends(get_change_detection_service),
) -> Dict[str, Any]:
    d = service.get(diff_id)
    if d is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"diff {diff_id!r} not found",
        )
    return d.model_dump(mode="json")


__all__ = ["router"]
