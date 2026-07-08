"""Module 9.8 — Multi-Agent Orchestration Platform API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.orchestration import (
    AgentMessage,
    AgentWorkflow,
    OrchestrationMetricsSummary,
    OrchestrationRequest,
    OrchestrationResult,
    WorkflowDefinition,
)
from app.services.orchestration import OrchestrationService

router = APIRouter(prefix="/agents", tags=["orchestration"])


def _service_dep():
    from app.api.dependencies import get_orchestration_service

    return Depends(get_orchestration_service)


# ─── Orchestrate ──────────────────────────────────────────────


@router.post("/orchestrate", response_model=OrchestrationResult)
async def orchestrate(
    request: OrchestrationRequest,
    svc: OrchestrationService = _service_dep(),
) -> OrchestrationResult:
    try:
        return await svc.orchestrate(request)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ─── Workflows ────────────────────────────────────────────────


@router.post("/workflows", response_model=WorkflowDefinition)
async def register_workflow(
    definition: WorkflowDefinition,
    svc: OrchestrationService = _service_dep(),
) -> WorkflowDefinition:
    svc.workflow_manager.register(definition)
    return definition


@router.get("/workflows", response_model=List[WorkflowDefinition])
async def list_workflows(
    svc: OrchestrationService = _service_dep(),
) -> List[WorkflowDefinition]:
    return svc.list_workflows()


@router.post(
    "/workflows/{workflow_id}/run",
    response_model=AgentWorkflow,
)
async def run_workflow(
    workflow_id: str,
    payload: Dict[str, Any] = {},
    svc: OrchestrationService = _service_dep(),
) -> AgentWorkflow:
    definition = svc.workflow_manager.get(workflow_id)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workflow '{workflow_id}' not found",
        )
    return await svc.run_workflow(
        definition,
        query=str(payload.get("query", definition.name)),
    )


# ─── Executions ───────────────────────────────────────────────


@router.get(
    "/executions/{execution_id}",
    response_model=Dict[str, Any],
)
async def get_execution(
    execution_id: str,
    svc: OrchestrationService = _service_dep(),
) -> Dict[str, Any]:
    # Inspect recent runs
    for r in svc.list_runs(limit=500):
        if r.result and r.result.execution_id == execution_id:
            return r.result.model_dump(mode="json")
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"execution '{execution_id}' not found",
    )


# ─── Health (reuses the underlying framework) ─────────────────


@router.get("/orchestration/health", response_model=Dict[str, Any])
async def orchestration_health(
    svc: OrchestrationService = _service_dep(),
) -> Dict[str, Any]:
    return {
        "status": "healthy",
        "agents": len(svc.framework_service.list_agents()),
        "workflows": len(svc.list_workflows()),
        "messages": svc.bus.message_count,
    }


# ─── Messages + metrics ───────────────────────────────────────


@router.get("/messages", response_model=List[AgentMessage])
async def list_messages(
    from_agent: Optional[str] = None,
    to_agent: Optional[str] = None,
    limit: int = 100,
    svc: OrchestrationService = _service_dep(),
) -> List[AgentMessage]:
    return svc.messages(
        from_agent=from_agent, to_agent=to_agent, limit=limit
    )


@router.get(
    "/orchestration/metrics",
    response_model=OrchestrationMetricsSummary,
)
async def get_metrics(
    svc: OrchestrationService = _service_dep(),
) -> OrchestrationMetricsSummary:
    return svc.metrics()


__all__ = ["router"]
