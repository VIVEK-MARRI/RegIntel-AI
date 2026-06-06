"""Module 8.1 — Compliance Risk Intelligence API."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_compliance_risk_service
from app.schemas.risk import (
    RiskAssessmentRequest,
    RiskCategory,
    RiskFilter,
    RiskLevel,
)
from app.services.compliance_risk import ComplianceRiskService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compliance-risk", tags=["compliance-risk"])


# ─── Static first ─────────────────────────────────────────────────────


@router.get(
    "/health",
    summary="Compliance risk service health",
)
async def health() -> Dict[str, Any]:
    return {"status": "ok", "module": "compliance_risk", "version": "8.1.0"}


@router.get(
    "/stats",
    summary="Aggregate compliance risk statistics",
)
async def stats(
    service: ComplianceRiskService = Depends(get_compliance_risk_service),
) -> Dict[str, Any]:
    return service.stats().model_dump(mode="json")


@router.get(
    "/trend",
    summary="Risk trend for a document or source",
)
async def trend(
    document_id: Optional[str] = Query(None),
    service: ComplianceRiskService = Depends(get_compliance_risk_service),
) -> Dict[str, Any]:
    return service.trend_for(document_id=document_id).model_dump(mode="json")


# ─── Assess ───────────────────────────────────────────────────────────


@router.post(
    "/assess",
    summary="Run a compliance risk assessment",
    status_code=status.HTTP_201_CREATED,
)
async def assess(
    request: RiskAssessmentRequest,
    service: ComplianceRiskService = Depends(get_compliance_risk_service),
) -> Dict[str, Any]:
    return service.assess(request).model_dump(mode="json")


# ─── List ─────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="List / filter risk assessments",
)
async def list_assessments(
    risk_level: Optional[RiskLevel] = Query(None),
    category: Optional[RiskCategory] = Query(None),
    document_id: Optional[str] = Query(None),
    after: Optional[float] = Query(None),
    before: Optional[float] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: ComplianceRiskService = Depends(get_compliance_risk_service),
) -> Dict[str, Any]:
    flt = RiskFilter(
        risk_level=risk_level,
        category=category,
        document_id=document_id,
        after=after,
        before=before,
        page=page,
        page_size=page_size,
    )
    return service.search(flt).model_dump(mode="json")


# RESTful alias used by the web dashboard. Mirrors ``GET /compliance-risk``
# but with the plural-noun path the SPA expects.
@router.get(
    "/assessments",
    summary="List / filter risk assessments (alias)",
    include_in_schema=False,
)
async def list_assessments_plural(
    risk_level: Optional[RiskLevel] = Query(None),
    category: Optional[RiskCategory] = Query(None),
    document_id: Optional[str] = Query(None),
    after: Optional[float] = Query(None),
    before: Optional[float] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    service: ComplianceRiskService = Depends(get_compliance_risk_service),
) -> Dict[str, Any]:
    return await list_assessments(
        risk_level=risk_level,
        category=category,
        document_id=document_id,
        after=after,
        before=before,
        page=page,
        page_size=page_size,
        service=service,
    )


# ─── Dynamic last ─────────────────────────────────────────────────────


@router.get(
    "/{assessment_id}",
    summary="Fetch a single risk assessment",
)
async def get_assessment(
    assessment_id: str,
    service: ComplianceRiskService = Depends(get_compliance_risk_service),
) -> Dict[str, Any]:
    a = service.get(assessment_id)
    if a is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"assessment {assessment_id!r} not found",
        )
    return a.model_dump(mode="json")


__all__ = ["router"]
