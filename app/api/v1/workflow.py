"""Module 8.4 — Workflow Automation Platform API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.workflow import (
    AuditEntry,
    EscalationRequest,
    PaginatedWorkflows,
    TaskAssignment,
    TaskAssignmentRequest,
    TaskCompletionRequest,
    TaskCreateRequest,
    TaskStatus,
    Workflow,
    WorkflowCreateRequest,
    WorkflowFilter,
    WorkflowStats,
)
from app.services.observability import get_workflow_metrics
from app.services.workflow import AutomationService

router = APIRouter(prefix="/workflow", tags=["workflow"])


def _service_dep():
    from app.api.dependencies import get_automation_service

    return Depends(get_automation_service)


# ─── Health / Stats ───────────────────────────────────────────────


@router.get("/health")
async def health() -> Dict[str, Any]:
    metrics = get_workflow_metrics()
    return {
        "status": "ok",
        "module": "workflow",
        "metrics": metrics.snapshot(),
    }


@router.get("/stats", response_model=WorkflowStats)
async def stats(svc: AutomationService = _service_dep()) -> WorkflowStats:
    return svc.stats()


# ─── Create / List / Get ──────────────────────────────────────────


@router.post(
    "/create",
    response_model=Workflow,
    status_code=status.HTTP_201_CREATED,
)
async def create(
    request: WorkflowCreateRequest,
    svc: AutomationService = _service_dep(),
) -> Workflow:
    return svc.create(request)


@router.get("", response_model=PaginatedWorkflows)
async def list_workflows(
    workflow_type: Optional[str] = None,
    status_filter: Optional[str] = None,
    document_id: Optional[str] = None,
    created_by: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    svc: AutomationService = _service_dep(),
) -> PaginatedWorkflows:
    from app.schemas.workflow import WorkflowStatus, WorkflowType

    flt = WorkflowFilter(
        workflow_type=WorkflowType(workflow_type) if workflow_type else None,
        status=WorkflowStatus(status_filter) if status_filter else None,
        document_id=document_id or None,
        created_by=created_by or None,
        page=max(1, page),
        page_size=max(1, min(200, page_size)),
    )
    return svc.search(flt)


@router.get("/{workflow_id}", response_model=Workflow)
async def get_workflow(
    workflow_id: str, svc: AutomationService = _service_dep()
) -> Workflow:
    wf = svc.get(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="not found")
    return wf


# ─── Lifecycle ────────────────────────────────────────────────────


@router.post("/{workflow_id}/start", response_model=Workflow)
async def start(
    workflow_id: str,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> Workflow:
    wf = svc.start(workflow_id, actor=actor)
    if wf is None:
        raise HTTPException(status_code=404, detail="not found")
    return wf


@router.post("/{workflow_id}/pause", response_model=Workflow)
async def pause(
    workflow_id: str,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> Workflow:
    wf = svc.pause(workflow_id, actor=actor)
    if wf is None:
        raise HTTPException(status_code=404, detail="not found")
    return wf


@router.post("/{workflow_id}/resume", response_model=Workflow)
async def resume(
    workflow_id: str,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> Workflow:
    wf = svc.resume(workflow_id, actor=actor)
    if wf is None:
        raise HTTPException(status_code=404, detail="not found")
    return wf


@router.post("/{workflow_id}/cancel", response_model=Workflow)
async def cancel(
    workflow_id: str,
    actor: str = "system",
    reason: str = "",
    svc: AutomationService = _service_dep(),
) -> Workflow:
    wf = svc.cancel(workflow_id, actor=actor, reason=reason)
    if wf is None:
        raise HTTPException(status_code=404, detail="not found")
    return wf


@router.post("/{workflow_id}/complete", response_model=Workflow)
async def complete(
    workflow_id: str,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> Workflow:
    wf = svc.complete(workflow_id, actor=actor)
    if wf is None:
        raise HTTPException(status_code=404, detail="not found")
    return wf


@router.post("/{workflow_id}/advance", response_model=Workflow)
async def advance(
    workflow_id: str,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> Workflow:
    wf = svc.advance(workflow_id, actor=actor)
    if wf is None:
        raise HTTPException(status_code=404, detail="not found")
    return wf


# ─── Tasks ────────────────────────────────────────────────────────


@router.post(
    "/{workflow_id}/tasks",
    response_model=TaskAssignment,
    status_code=status.HTTP_201_CREATED,
)
async def add_task(
    workflow_id: str,
    request: TaskCreateRequest,
    svc: AutomationService = _service_dep(),
) -> TaskAssignment:
    task = svc.add_task(workflow_id, request)
    if task is None:
        raise HTTPException(status_code=404, detail="not found")
    return task


@router.post(
    "/{workflow_id}/tasks/{task_id}/assign",
    response_model=TaskAssignment,
)
async def assign_task(
    workflow_id: str,
    task_id: str,
    request: TaskAssignmentRequest,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> TaskAssignment:
    task = svc.assign_task(workflow_id, task_id, request, actor=actor)
    if task is None:
        raise HTTPException(status_code=404, detail="not found")
    return task


@router.post(
    "/{workflow_id}/tasks/{task_id}/start",
    response_model=TaskAssignment,
)
async def start_task(
    workflow_id: str,
    task_id: str,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> TaskAssignment:
    task = svc.start_task(workflow_id, task_id, actor=actor)
    if task is None:
        raise HTTPException(status_code=404, detail="not found")
    return task


@router.post(
    "/{workflow_id}/tasks/{task_id}/complete",
    response_model=TaskAssignment,
)
async def complete_task(
    workflow_id: str,
    task_id: str,
    request: TaskCompletionRequest,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> TaskAssignment:
    task = svc.complete_task(workflow_id, task_id, request, actor=actor)
    if task is None:
        raise HTTPException(status_code=404, detail="not found")
    return task


# ─── Escalation / Audit ───────────────────────────────────────────


@router.post("/{workflow_id}/escalate")
async def escalate(
    workflow_id: str,
    request: EscalationRequest,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> Dict[str, Any]:
    res = svc.escalate(workflow_id, request, actor=actor)
    if res is None:
        raise HTTPException(status_code=404, detail="not found")
    rule, wf = res
    return {
        "rule_id": rule.rule_id,
        "action": rule.action.value,
        "target": request.target or rule.target,
        "reason": request.reason,
        "workflow_id": wf.workflow_id,
        "workflow_status": wf.status.value,
    }


@router.get("/{workflow_id}/audit", response_model=List[AuditEntry])
async def audit(
    workflow_id: str,
    svc: AutomationService = _service_dep(),
) -> List[AuditEntry]:
    wf = svc.get(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="not found")
    return wf.audit_trail


@router.get("/{workflow_id}/progress")
async def progress(
    workflow_id: str,
    svc: AutomationService = _service_dep(),
) -> Dict[str, Any]:
    wf = svc.get(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "workflow_id": workflow_id,
        "progress_percent": svc.progress_percent(workflow_id),
        "current_step_index": wf.current_step_index,
        "total_steps": len(wf.steps),
    }


# ─── Cross-module integration ─────────────────────────────────────


@router.post(
    "/from-recommendation/{recommendation_id}",
    response_model=Workflow,
    status_code=status.HTTP_201_CREATED,
)
async def from_recommendation(
    recommendation_id: str,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> Workflow:
    wf = svc.create_from_recommendation(recommendation_id, actor=actor)
    if wf is None:
        raise HTTPException(
            status_code=404,
            detail=f"Recommendation {recommendation_id} not found",
        )
    return wf


@router.post(
    "/from-risk/{assessment_id}",
    response_model=Workflow,
    status_code=status.HTTP_201_CREATED,
)
async def from_risk(
    assessment_id: str,
    actor: str = "system",
    svc: AutomationService = _service_dep(),
) -> Workflow:
    wf = svc.create_from_risk_assessment(assessment_id, actor=actor)
    if wf is None:
        raise HTTPException(
            status_code=404,
            detail=f"Risk assessment {assessment_id} not found",
        )
    return wf
