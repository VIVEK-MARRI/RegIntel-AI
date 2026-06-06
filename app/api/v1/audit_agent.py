"""Module 9.7 — Audit Agent API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.agents import AgentContext
from app.schemas.audit_agent import (
    AuditAgentHealth,
    AuditAgentRequest,
    AuditAgentResult,
    AuditMetricsSummary,
)
from app.schemas.audit_agent import AuditTaskKind
from app.services.audit_agent import AuditAgentService

router = APIRouter(prefix="/agents", tags=["audit-agent"])


def _service_dep():
    from app.api.dependencies import get_audit_agent_service

    return Depends(get_audit_agent_service)


# ─── Run ──────────────────────────────────────────────────────


@router.post("/audit/run", response_model=AuditAgentResult)
async def run_audit(
    request: AuditAgentRequest,
    svc: AuditAgentService = _service_dep(),
) -> AuditAgentResult:
    try:
        return await svc.run(
            request, context=AgentContext(actor="api")
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ─── Health + metrics ────────────────────────────────────────


@router.get("/audit/health", response_model=AuditAgentHealth)
async def audit_health(
    svc: AuditAgentService = _service_dep(),
) -> AuditAgentHealth:
    return svc.health()


@router.get("/audit/metrics", response_model=AuditMetricsSummary)
async def audit_metrics(
    svc: AuditAgentService = _service_dep(),
) -> AuditMetricsSummary:
    return svc.metrics()


# ─── Convenience: list supported task kinds ──────────────────


@router.get("/audit/task-kinds", response_model=List[str])
async def list_task_kinds() -> List[str]:
    return [k.value for k in AuditTaskKind]


# ─── Convenience: register with framework (idempotent) ──────


@router.post("/audit/register", status_code=status.HTTP_200_OK)
async def register_with_framework(
    svc: AuditAgentService = _service_dep(),
) -> Dict[str, Any]:
    from app.api.dependencies import get_agent_framework_service

    framework = get_agent_framework_service()
    svc.register(framework)
    return {"status": "registered", "agent": svc.agent.name}


__all__ = ["router"]
