"""Module 8.5 — Human-in-the-Loop Review API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.review import (
    AuditEntry,
    PaginatedReviews,
    Review,
    ReviewAssignmentRequest,
    ReviewComment,
    ReviewCommentRequest,
    ReviewCorrection,
    ReviewCorrectionRequest,
    ReviewCreateRequest,
    ReviewDecisionRequest,
    ReviewFilter,
    ReviewStats,
)
from app.services.observability import get_review_metrics
from app.services.review import ReviewService

router = APIRouter(prefix="/review", tags=["review"])


def _service_dep():
    from app.api.dependencies import get_review_service

    return Depends(get_review_service)


# ─── Health / Stats ──────────────────────────────────────────────


@router.get("/health")
async def health() -> Dict[str, Any]:
    metrics = get_review_metrics()
    return {
        "status": "ok",
        "module": "review",
        "metrics": metrics.snapshot(),
    }


@router.get("/stats", response_model=ReviewStats)
async def stats(svc: ReviewService = _service_dep()) -> ReviewStats:
    return svc.stats()


# ─── Create / List / Get ──────────────────────────────────────────


@router.post(
    "/create",
    response_model=Review,
    status_code=status.HTTP_201_CREATED,
)
async def create(
    request: ReviewCreateRequest,
    actor: str = "system",
    svc: ReviewService = _service_dep(),
) -> Review:
    return svc.create(request, actor=actor)


@router.get("", response_model=PaginatedReviews)
async def list_reviews(
    status_filter: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    workflow_id: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    svc: ReviewService = _service_dep(),
) -> PaginatedReviews:
    from app.schemas.review import ReviewPriority, ReviewStatus

    flt = ReviewFilter(
        status=ReviewStatus(status_filter) if status_filter else None,
        priority=ReviewPriority(priority) if priority else None,
        assigned_to=assigned_to or None,
        workflow_id=workflow_id or None,
        subject_type=subject_type or None,
        subject_id=subject_id or None,
        page=max(1, page),
        page_size=max(1, min(200, page_size)),
    )
    return svc.search(flt)


# RESTful alias used by the web dashboard. Mirrors ``GET /review`` but
# with the plural-noun path the SPA expects.
@router.get("/tasks", response_model=PaginatedReviews, include_in_schema=False)
async def list_review_tasks(
    status_filter: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    workflow_id: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    svc: ReviewService = _service_dep(),
) -> PaginatedReviews:
    return await list_reviews(
        status_filter=status_filter,
        priority=priority,
        assigned_to=assigned_to,
        workflow_id=workflow_id,
        subject_type=subject_type,
        subject_id=subject_id,
        page=page,
        page_size=page_size,
        svc=svc,
    )


@router.get("/{review_id}", response_model=Review)
async def get_review(review_id: str, svc: ReviewService = _service_dep()) -> Review:
    r = svc.get(review_id)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


# ─── Lifecycle ────────────────────────────────────────────────────


@router.post("/{review_id}/start", response_model=Review)
async def start(
    review_id: str,
    actor: str = "system",
    svc: ReviewService = _service_dep(),
) -> Review:
    r = svc.start(review_id, actor=actor)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


@router.post("/{review_id}/decide", response_model=Review)
async def decide(
    review_id: str,
    request: ReviewDecisionRequest,
    actor: str = "system",
    svc: ReviewService = _service_dep(),
) -> Review:
    r = svc.decide(review_id, request, actor=actor)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


@router.post("/{review_id}/approve", response_model=Review)
async def approve(
    review_id: str,
    actor: str = "system",
    approver_role: str = "",
    comment: str = "",
    svc: ReviewService = _service_dep(),
) -> Review:
    request = ReviewDecisionRequest(
        decision=__import__(
            "app.schemas.review", fromlist=["ReviewDecision"]
        ).ReviewDecision.APPROVED,
        approver_role=approver_role,
        comment_text=comment,
    )
    r = svc.decide(review_id, request, actor=actor)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


@router.post("/{review_id}/reject", response_model=Review)
async def reject(
    review_id: str,
    actor: str = "system",
    approver_role: str = "",
    reason: str = "",
    comment: str = "",
    svc: ReviewService = _service_dep(),
) -> Review:
    request = ReviewDecisionRequest(
        decision=__import__(
            "app.schemas.review", fromlist=["ReviewDecision"]
        ).ReviewDecision.REJECTED,
        approver_role=approver_role,
        reason=reason,
        comment_text=comment,
    )
    r = svc.decide(review_id, request, actor=actor)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


@router.post("/{review_id}/escalate", response_model=Review)
async def escalate(
    review_id: str,
    reason: str = "",
    actor: str = "system",
    svc: ReviewService = _service_dep(),
) -> Review:
    r = svc.escalate(review_id, reason=reason, actor=actor)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


@router.post("/{review_id}/withdraw", response_model=Review)
async def withdraw(
    review_id: str,
    reason: str = "",
    actor: str = "system",
    svc: ReviewService = _service_dep(),
) -> Review:
    r = svc.withdraw(review_id, reason=reason, actor=actor)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


# ─── Assignment / Comments / Corrections ─────────────────────────


@router.post("/{review_id}/assign", response_model=Review)
async def assign(
    review_id: str,
    request: ReviewAssignmentRequest,
    actor: str = "system",
    svc: ReviewService = _service_dep(),
) -> Review:
    r = svc.get(review_id)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    svc.manager.assign(r, request.assigned_to, request.assigned_role, actor=actor)
    svc.store.add(r)
    return r


@router.post(
    "/{review_id}/comment",
    response_model=ReviewComment,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    review_id: str,
    request: ReviewCommentRequest,
    svc: ReviewService = _service_dep(),
) -> ReviewComment:
    c = svc.add_comment(review_id, request.text, request.author, role=request.role)
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    return c


@router.post(
    "/{review_id}/correction",
    response_model=ReviewCorrection,
    status_code=status.HTTP_201_CREATED,
)
async def add_correction(
    review_id: str,
    request: ReviewCorrectionRequest,
    svc: ReviewService = _service_dep(),
) -> ReviewCorrection:
    c = svc.add_correction(
        review_id,
        field=request.field,
        original_value=request.original_value,
        corrected_value=request.corrected_value,
        reason=request.reason,
        corrected_by=request.corrected_by or "system",
    )
    if c is None:
        raise HTTPException(status_code=404, detail="not found")
    return c


# ─── Approval coordination ───────────────────────────────────────


@router.get("/{review_id}/approvals")
async def approvals(
    review_id: str, svc: ReviewService = _service_dep()
) -> Dict[str, Any]:
    state = svc.evaluate_approvals(review_id)
    if state is None:
        raise HTTPException(status_code=404, detail="not found")
    return state


@router.post("/{review_id}/approvals/{approver}/approve", response_model=Review)
async def record_approval(
    review_id: str,
    approver: str,
    role: str = "",
    actor: str = "system",
    svc: ReviewService = _service_dep(),
) -> Review:
    r = svc.record_approval(review_id, approver, role, actor=actor)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


@router.post("/{review_id}/approvals/{approver}/reject", response_model=Review)
async def record_rejection(
    review_id: str,
    approver: str,
    reason: str = "",
    role: str = "",
    actor: str = "system",
    svc: ReviewService = _service_dep(),
) -> Review:
    r = svc.record_rejection(review_id, approver, reason, role, actor=actor)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r


# ─── Audit / History / Queue ─────────────────────────────────────


@router.get("/{review_id}/audit", response_model=List[AuditEntry])
async def audit(
    review_id: str, svc: ReviewService = _service_dep()
) -> List[AuditEntry]:
    r = svc.get(review_id)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return r.audit_trail


@router.get("/{review_id}/history")
async def history(
    review_id: str, svc: ReviewService = _service_dep()
) -> Dict[str, Any]:
    r = svc.get(review_id)
    if r is None:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "review_id": review_id,
        "comments": r.comments,
        "corrections": r.corrections,
        "audit_count": len(r.audit_trail),
    }


@router.get("/queue/{assignee}", response_model=List[Review])
async def queue(assignee: str, svc: ReviewService = _service_dep()) -> List[Review]:
    return svc.queue_for(assignee)


# ─── Cross-module integration ────────────────────────────────────


@router.post(
    "/from-workflow/{workflow_id}",
    response_model=Review,
    status_code=status.HTTP_201_CREATED,
)
async def from_workflow(
    workflow_id: str,
    assigned_to: str = "compliance_head",
    actor: str = "system",
    svc: ReviewService = _service_dep(),
) -> Review:
    r = svc.create_for_workflow(workflow_id, assigned_to=assigned_to, actor=actor)
    if r is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow {workflow_id} not found",
        )
    return r
