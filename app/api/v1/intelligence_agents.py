"""Module 9.4-9.6 — Intelligence Agent Layer API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.agents import AgentContext
from app.schemas.intelligence_agents import (
    AgentCollaboration,
    ComplianceAgentHealth,
    ComplianceAgentRequest,
    ComplianceAgentResult,
    IntelligenceAgentMetrics,
    ResearchAgentHealth,
    ResearchAgentRequest,
    ResearchAgentResult,
    ResearchMode,
    RiskAgentHealth,
    RiskAgentRequest,
    RiskAgentResult,
)
from app.services.intelligence_agents import IntelligenceAgentService

router = APIRouter(prefix="/agents", tags=["intelligence-agents"])


def _service_dep():
    from app.api.dependencies import get_intelligence_agent_service

    return Depends(get_intelligence_agent_service)


# ─── Health ───────────────────────────────────────────────────


@router.get("/research/health", response_model=ResearchAgentHealth)
async def research_health(
    svc: IntelligenceAgentService = _service_dep(),
) -> ResearchAgentHealth:
    return svc.health_research()


@router.get("/compliance/health", response_model=ComplianceAgentHealth)
async def compliance_health(
    svc: IntelligenceAgentService = _service_dep(),
) -> ComplianceAgentHealth:
    return svc.health_compliance()


@router.get("/risk/health", response_model=RiskAgentHealth)
async def risk_health(
    svc: IntelligenceAgentService = _service_dep(),
) -> RiskAgentHealth:
    return svc.health_risk()


# ─── Run ──────────────────────────────────────────────────────


@router.post("/research/run", response_model=ResearchAgentResult)
async def run_research(
    request: ResearchAgentRequest,
    svc: IntelligenceAgentService = _service_dep(),
) -> ResearchAgentResult:
    try:
        return await svc.run_research(
            request, context=AgentContext(actor="api")
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.post("/compliance/run", response_model=ComplianceAgentResult)
async def run_compliance(
    request: ComplianceAgentRequest,
    svc: IntelligenceAgentService = _service_dep(),
) -> ComplianceAgentResult:
    try:
        return await svc.run_compliance(
            request, context=AgentContext(actor="api")
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.post("/risk/run", response_model=RiskAgentResult)
async def run_risk(
    request: RiskAgentRequest,
    svc: IntelligenceAgentService = _service_dep(),
) -> RiskAgentResult:
    try:
        return await svc.run_risk(
            request, context=AgentContext(actor="api")
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ─── Coordinator (multi-agent pipeline) ──────────────────────


@router.post("/coordinate/pipeline", status_code=status.HTTP_200_OK)
async def coordinate_pipeline(
    payload: Dict[str, Any],
    svc: IntelligenceAgentService = _service_dep(),
) -> Dict[str, Any]:
    """Run the full research → compliance → risk pipeline."""
    query = payload.get("query")
    if not query or not isinstance(query, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`query` is required",
        )
    mode_str = payload.get("mode", ResearchMode.GENERAL.value)
    try:
        mode = ResearchMode(mode_str)
    except ValueError:
        mode = ResearchMode.GENERAL
    return await svc.coordinate(query, mode=mode)


# ─── Metrics + collaborations ────────────────────────────────


@router.get("/metrics", response_model=IntelligenceAgentMetrics)
async def get_metrics(
    svc: IntelligenceAgentService = _service_dep(),
) -> IntelligenceAgentMetrics:
    return svc.metrics()


@router.get("/collaborations", response_model=List[AgentCollaboration])
async def list_collaborations(
    from_agent: Optional[str] = None,
    to_agent: Optional[str] = None,
    svc: IntelligenceAgentService = _service_dep(),
) -> List[AgentCollaboration]:
    return svc.collaborations(
        from_agent=from_agent, to_agent=to_agent
    )


__all__ = ["router"]
