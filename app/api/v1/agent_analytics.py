"""Module 9.9 — Agent Analytics Platform API."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.agent_analytics import (
    AgentAnalyticsOverview,
    AgentPerformance,
    CostEstimate,
    HealthSummary,
    LatencyDistribution,
    LeaderboardEntry,
)
from app.services.agent_analytics import AgentAnalyticsService

router = APIRouter(prefix="/agents/analytics", tags=["agent-analytics"])


def _service_dep():
    from app.api.dependencies import get_agent_analytics_service

    return Depends(get_agent_analytics_service)


# ─── Overview ────────────────────────────────────────────────


@router.get("", response_model=AgentAnalyticsOverview)
@router.get("/", response_model=AgentAnalyticsOverview)
@router.get("/overview", response_model=AgentAnalyticsOverview)
async def get_overview(
    svc: AgentAnalyticsService = _service_dep(),
) -> AgentAnalyticsOverview:
    return svc.overview()


# ─── Performance ────────────────────────────────────────────


@router.get("/performance", response_model=List[AgentPerformance])
async def get_performance(
    svc: AgentAnalyticsService = _service_dep(),
) -> List[AgentPerformance]:
    return svc.performance()


@router.get(
    "/performance/{agent_name}",
    response_model=AgentPerformance,
)
async def get_agent_performance(
    agent_name: str,
    svc: AgentAnalyticsService = _service_dep(),
) -> AgentPerformance:
    perf = svc.performance_for(agent_name)
    if perf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no metrics for agent '{agent_name}'",
        )
    return perf


@router.get(
    "/performance/{agent_name}/latency",
    response_model=LatencyDistribution,
)
async def get_agent_latency(
    agent_name: str,
    svc: AgentAnalyticsService = _service_dep(),
) -> LatencyDistribution:
    return svc.analyzer.latency_distribution(agent_name)


# ─── Leaderboard ─────────────────────────────────────────────


@router.get("/leaderboard", response_model=List[LeaderboardEntry])
async def get_leaderboard(
    top_n: int = 10,
    svc: AgentAnalyticsService = _service_dep(),
) -> List[LeaderboardEntry]:
    return svc.leaderboard_view(top_n=top_n)


# ─── Health ─────────────────────────────────────────────────


@router.get("/health", response_model=HealthSummary)
async def get_health(
    svc: AgentAnalyticsService = _service_dep(),
) -> HealthSummary:
    return svc.health()


# ─── Cost ────────────────────────────────────────────────────


@router.get("/cost", response_model=CostEstimate)
async def get_cost(
    svc: AgentAnalyticsService = _service_dep(),
) -> CostEstimate:
    return svc.cost()


# ─── Record / reset helpers (for tests and the engine) ──────


@router.post("/record", status_code=status.HTTP_200_OK)
async def record(
    payload: Dict[str, Any],
    svc: AgentAnalyticsService = _service_dep(),
) -> Dict[str, Any]:
    agent = payload.get("agent_name", "unknown")
    duration = float(payload.get("duration_ms", 0.0))
    status_ = str(payload.get("status", "succeeded"))
    confidence = payload.get("confidence")
    svc.repo.record(agent, duration, status_, confidence=confidence)
    if status_ != "succeeded" and payload.get("error"):
        svc.repo.record_error(agent, str(payload["error"]))
    return {"status": "recorded", "agent_name": agent}


@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset(svc: AgentAnalyticsService = _service_dep()) -> Dict[str, Any]:
    svc.repo.reset()
    return {"status": "reset"}


__all__ = ["router"]
