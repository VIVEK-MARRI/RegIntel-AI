"""Module 6.6 — Feedback Intelligence API.

Endpoints
---------
* ``POST /api/v1/copilot/feedback``         — record feedback.
* ``GET  /api/v1/copilot/feedback``         — list / filter feedback.
* ``GET  /api/v1/copilot/feedback/{id}``    — fetch one entry.
* ``GET  /api/v1/copilot/feedback/stats``   — aggregated stats.
* ``GET  /api/v1/copilot/feedback/health``  — health probe.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_feedback_service
from app.schemas.feedback import (
    FeedbackCategory,
    FeedbackEntry,
    FeedbackFilter,
    FeedbackRequest,
    FeedbackSeverity,
    FeedbackStats,
    FeedbackType,
    PaginatedFeedback,
)
from app.services.feedback import FeedbackService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/copilot/feedback", tags=["copilot-feedback"])


# Static routes MUST come before the wildcard /{feedback_id} route.
@router.get(
    "/health",
    summary="Health probe for feedback service",
)
async def health() -> Dict[str, Any]:
    return {"status": "ok", "module": "feedback", "version": "6.6.0"}


@router.get(
    "/stats",
    response_model=FeedbackStats,
    summary="Aggregated feedback statistics",
)
async def stats(
    window_hours: Optional[float] = Query(
        None,
        ge=0,
        description="If set, only include feedback from the last N hours.",
    ),
    user_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
    service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackStats:
    from datetime import timedelta
    window = timedelta(hours=window_hours) if window_hours else None
    return service.manager.stats(
        window=window, user_id=user_id, conversation_id=conversation_id
    )


@router.post(
    "",
    response_model=FeedbackEntry,
    status_code=status.HTTP_201_CREATED,
    summary="Record feedback for a copilot response",
)
async def record_feedback(
    request: FeedbackRequest,
    service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackEntry:
    try:
        return service.manager.record(request)
    except Exception as exc:  # pragma: no cover
        logger.exception("Feedback recording failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"feedback recording failed: {exc}",
        ) from exc


@router.get(
    "",
    response_model=PaginatedFeedback,
    summary="List / filter feedback",
)
async def list_feedback(
    request_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    feedback_type: Optional[FeedbackType] = Query(None),
    category: Optional[FeedbackCategory] = Query(None),
    severity: Optional[FeedbackSeverity] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_desc: bool = Query(True),
    service: FeedbackService = Depends(get_feedback_service),
) -> PaginatedFeedback:
    flt = FeedbackFilter(
        request_id=request_id,
        conversation_id=conversation_id,
        user_id=user_id,
        feedback_type=feedback_type,
        category=category,
        severity=severity,
        page=page,
        page_size=page_size,
        sort_desc=sort_desc,
    )
    return service.manager.search(flt)


@router.get(
    "/{feedback_id}",
    response_model=FeedbackEntry,
    summary="Fetch a single feedback entry",
)
async def get_feedback(
    feedback_id: str,
    service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackEntry:
    entry = service.manager.get(feedback_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feedback {feedback_id!r} not found",
        )
    return entry


__all__ = ["router"]
