"""Module 8.2 — Regulatory Recommendation Engine API."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.recommendations import (
    ActionStatus,
    PaginatedRecommendations,
    Recommendation,
    RecommendationFeedback,
    RecommendationFilter,
    RecommendationRequest,
    RecommendationStats,
)
from app.services.observability import get_recommendation_metrics
from app.services.recommendations import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _service_dep():
    from app.api.dependencies import get_recommendation_service

    return Depends(get_recommendation_service)


@router.get("/health")
async def health() -> Dict[str, Any]:
    metrics = get_recommendation_metrics()
    return {"status": "ok", "module": "recommendations", "metrics": metrics.snapshot()}


@router.get("/stats", response_model=RecommendationStats)
async def stats(svc: RecommendationService = _service_dep()) -> RecommendationStats:
    return svc.stats()


@router.get("", response_model=PaginatedRecommendations)
async def list_recommendations(
    document_id: str = "",
    page: int = 1,
    page_size: int = 20,
    svc: RecommendationService = _service_dep(),
) -> PaginatedRecommendations:
    flt = RecommendationFilter(
        document_id=document_id or None,
        page=max(1, page),
        page_size=max(1, min(100, page_size)),
    )
    return svc.search(flt)


@router.get("/{recommendation_id}", response_model=Recommendation)
async def get_recommendation(
    recommendation_id: str, svc: RecommendationService = _service_dep()
) -> Recommendation:
    rec = svc.get(recommendation_id)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation {recommendation_id} not found",
        )
    return rec


@router.post(
    "/generate",
    response_model=List[Recommendation],
    status_code=status.HTTP_201_CREATED,
)
async def generate(
    request: RecommendationRequest,
    svc: RecommendationService = _service_dep(),
) -> List[Recommendation]:
    return svc.generate(request)


@router.post(
    "/{recommendation_id}/feedback",
    response_model=Recommendation,
)
async def feedback(
    recommendation_id: str,
    fb: RecommendationFeedback,
    svc: RecommendationService = _service_dep(),
) -> Recommendation:
    rec = svc.feedback(recommendation_id, fb)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation {recommendation_id} not found",
        )
    return rec


@router.post(
    "/{recommendation_id}/accept",
    response_model=Recommendation,
)
async def accept(
    recommendation_id: str,
    svc: RecommendationService = _service_dep(),
) -> Recommendation:
    rec = svc.feedback(
        recommendation_id,
        RecommendationFeedback(
            status=ActionStatus.ACCEPTED,
            feedback="Accepted via API",
        ),
    )
    if rec is None:
        raise HTTPException(status_code=404, detail="not found")
    return rec


@router.post(
    "/{recommendation_id}/reject",
    response_model=Recommendation,
)
async def reject(
    recommendation_id: str,
    feedback: str = "",
    svc: RecommendationService = _service_dep(),
) -> Recommendation:
    rec = svc.feedback(
        recommendation_id,
        RecommendationFeedback(
            status=ActionStatus.REJECTED,
            feedback=feedback or "Rejected via API",
        ),
    )
    if rec is None:
        raise HTTPException(status_code=404, detail="not found")
    return rec


@router.post(
    "/{recommendation_id}/start",
    response_model=Recommendation,
)
async def start(
    recommendation_id: str,
    svc: RecommendationService = _service_dep(),
) -> Recommendation:
    rec = svc.feedback(
        recommendation_id,
        RecommendationFeedback(
            status=ActionStatus.IN_PROGRESS,
            feedback="Started via API",
        ),
    )
    if rec is None:
        raise HTTPException(status_code=404, detail="not found")
    return rec


@router.post(
    "/{recommendation_id}/complete",
    response_model=Recommendation,
)
async def complete(
    recommendation_id: str,
    svc: RecommendationService = _service_dep(),
) -> Recommendation:
    rec = svc.feedback(
        recommendation_id,
        RecommendationFeedback(
            status=ActionStatus.COMPLETED,
            feedback="Completed via API",
        ),
    )
    if rec is None:
        raise HTTPException(status_code=404, detail="not found")
    return rec
