"""Tests for Module 9.9 — Agent Analytics Platform."""

from __future__ import annotations

import os

# Lift rate-limit ceiling
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.agent_analytics import (
    AgentAnalyticsOverview,
    AgentPerformance,
    HealthLevel,
)
from app.schemas.agents import AgentMetadata
from app.services.agent_analytics import (
    AgentAnalyticsService,
    AgentCostAnalyzer,
    AgentHealthMonitor,
    AgentLeaderboard,
    AgentMetricsRepository,
    AgentPerformanceAnalyzer,
    build_default_agent_analytics_service,
)


def _build_service() -> AgentAnalyticsService:
    return build_default_agent_analytics_service()


# ─── Repository tests ───────────────────────────────────────


def test_repo_records_success():
    repo = AgentMetricsRepository()
    repo.record("a", 100.0, "succeeded", confidence=0.8)
    s = repo.stats("a")
    assert s.total_invocations == 1
    assert s.successful_invocations == 1
    assert s.success_rate == 1.0
    assert s.average_confidence == 0.8
    assert s.health == HealthLevel.HEALTHY


def test_repo_records_failure():
    repo = AgentMetricsRepository()
    repo.record("a", 100.0, "failed")
    repo.record("a", 200.0, "succeeded")
    s = repo.stats("a")
    assert s.total_invocations == 2
    assert s.successful_invocations == 1
    assert s.failed_invocations == 1
    assert s.health == HealthLevel.DEGRADED


def test_repo_unhealthy_when_more_fails_than_oks():
    repo = AgentMetricsRepository()
    for _ in range(3):
        repo.record("a", 50.0, "failed")
    s = repo.stats("a")
    assert s.health == HealthLevel.UNHEALTHY


def test_repo_unknown_when_no_records():
    repo = AgentMetricsRepository()
    s = repo.stats("nope")
    assert s.total_invocations == 0
    assert s.health == HealthLevel.UNKNOWN


def test_repo_records_error():
    repo = AgentMetricsRepository()
    repo.record("a", 10.0, "failed")
    repo.record_error("a", "boom")
    s = repo.stats("a")
    assert "boom" in s.last_error


def test_repo_all_agent_names_sorted():
    repo = AgentMetricsRepository()
    repo.record("z", 1, "succeeded")
    repo.record("a", 1, "succeeded")
    assert repo.all_agent_names() == ["a", "z"]


def test_repo_reset_clears():
    repo = AgentMetricsRepository()
    repo.record("a", 1, "succeeded")
    repo.reset()
    assert repo.all_agent_names() == []


# ─── Percentile helper ──────────────────────────────────────


def test_percentile_basic():
    from app.services.agent_analytics import _percentile
    assert _percentile([], 50) == 0.0
    assert _percentile([10], 50) == 10
    assert abs(_percentile([1, 2, 3, 4, 5], 50) - 3) < 0.01
    assert abs(_percentile([1, 2, 3, 4, 5], 95) - 4.8) < 0.01


# ─── Performance analyzer ───────────────────────────────────


def test_performance_analyzer_returns_for_all():
    repo = AgentMetricsRepository()
    repo.record("a", 100, "succeeded", confidence=0.7)
    repo.record("b", 200, "failed")
    a = AgentPerformanceAnalyzer(repo)
    perfs = a.for_all()
    names = sorted(p.agent_name for p in perfs)
    assert names == ["a", "b"]


def test_performance_analyzer_latency_distribution():
    repo = AgentMetricsRepository()
    for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]:
        repo.record("a", v, "succeeded")
    a = AgentPerformanceAnalyzer(repo)
    dist = a.latency_distribution("a")
    assert dist.count == 10
    assert dist.min_ms == 10
    assert dist.max_ms == 100
    assert 50 <= dist.p50_ms <= 60
    assert dist.p99_ms >= dist.p95_ms


def test_performance_analyzer_latency_empty():
    a = AgentPerformanceAnalyzer(AgentMetricsRepository())
    dist = a.latency_distribution("nope")
    assert dist.count == 0


# ─── Health monitor ──────────────────────────────────────────


def test_health_monitor_healthy():
    repo = AgentMetricsRepository()
    repo.record("a", 1, "succeeded")
    repo.record("b", 1, "succeeded")
    m = AgentHealthMonitor(AgentPerformanceAnalyzer(repo))
    h = m.ecosystem_health()
    assert h.healthy_agents == 2
    assert h.overall_health == HealthLevel.HEALTHY


def test_health_monitor_degraded():
    repo = AgentMetricsRepository()
    # 3 successes + 2 fails for the same agent: 60% success rate
    # → DEGRADED
    for _ in range(3):
        repo.record("a", 1, "succeeded")
    for _ in range(2):
        repo.record("a", 1, "failed")
    m = AgentHealthMonitor(AgentPerformanceAnalyzer(repo))
    h = m.ecosystem_health()
    assert h.degraded_agents == 1
    assert h.healthy_agents == 0
    assert h.overall_health == HealthLevel.DEGRADED


def test_health_monitor_mixed_overall_degraded():
    repo = AgentMetricsRepository()
    repo.record("a", 1, "succeeded")
    repo.record("b", 1, "failed")
    m = AgentHealthMonitor(AgentPerformanceAnalyzer(repo))
    h = m.ecosystem_health()
    # 1 healthy + 1 unhealthy → overall degraded
    assert h.healthy_agents == 1
    assert h.unhealthy_agents == 1
    assert h.overall_health == HealthLevel.DEGRADED


def test_health_monitor_empty():
    m = AgentHealthMonitor(
        AgentPerformanceAnalyzer(AgentMetricsRepository())
    )
    h = m.ecosystem_health()
    assert h.total_agents == 0
    assert h.overall_health == HealthLevel.UNKNOWN


# ─── Leaderboard ────────────────────────────────────────────


def test_leaderboard_ranks_by_score():
    repo = AgentMetricsRepository()
    for _ in range(5):
        repo.record("a", 100, "succeeded", confidence=0.9)
    for _ in range(3):
        repo.record("b", 100, "succeeded", confidence=0.5)
    repo.record("c", 100, "failed")
    lb = AgentLeaderboard(AgentPerformanceAnalyzer(repo))
    board = lb.rank(top_n=10)
    assert board[0].agent_name == "a"
    assert board[1].agent_name == "b"
    assert board[2].agent_name == "c"
    assert board[0].rank == 1


def test_leaderboard_top_n_truncates():
    repo = AgentMetricsRepository()
    for name in ["a", "b", "c", "d", "e"]:
        repo.record(name, 100, "succeeded", confidence=0.5)
    lb = AgentLeaderboard(AgentPerformanceAnalyzer(repo))
    board = lb.rank(top_n=3)
    assert len(board) == 3


def test_leaderboard_empty():
    lb = AgentLeaderboard(
        AgentPerformanceAnalyzer(AgentMetricsRepository())
    )
    assert lb.rank(top_n=5) == []


# ─── Cost analyzer ──────────────────────────────────────────


def test_cost_estimate_for_agent():
    repo = AgentMetricsRepository()
    for _ in range(10):
        repo.record("a", 100, "succeeded")
    ca = AgentCostAnalyzer(repo, cost_per_invocation=0.01)
    c = ca.estimate_for_agent("a")
    assert c.invocations == 10
    assert c.cost_units == 0.1


def test_cost_estimate_platform_total():
    repo = AgentMetricsRepository()
    for _ in range(5):
        repo.record("a", 100, "succeeded")
    for _ in range(5):
        repo.record("b", 100, "succeeded")
    ca = AgentCostAnalyzer(repo, cost_per_invocation=0.01)
    c = ca.estimate_platform_total()
    assert c.invocations == 10
    assert c.cost_units == 0.1
    assert c.cost_per_invocation == 0.01


# ─── Service facade ────────────────────────────────────────


def test_service_overview_empty():
    svc = _build_service()
    o = svc.overview()
    assert o.total_agents == 0
    assert o.health.overall_health == HealthLevel.UNKNOWN
    assert o.cost.invocations == 0


def test_service_overview_after_records():
    svc = _build_service()
    for _ in range(3):
        svc.repo.record("a", 100, "succeeded", confidence=0.8)
    for _ in range(2):
        svc.repo.record("b", 200, "failed")
    o = svc.overview()
    assert o.total_invocations == 5
    assert o.success_rate == 0.6
    # Agent a: 100% → healthy. Agent b: 0% → unhealthy.
    assert o.health.healthy_agents == 1
    assert o.health.unhealthy_agents == 1
    assert o.health.overall_health == HealthLevel.DEGRADED
    assert o.health.healthy_agents == 1


def test_service_performance_for():
    svc = _build_service()
    svc.repo.record("a", 50, "succeeded")
    assert svc.performance_for("a") is not None
    assert svc.performance_for("nope") is None


def test_service_leaderboard_top_n():
    svc = _build_service()
    svc.repo.record("a", 50, "succeeded", confidence=0.9)
    board = svc.leaderboard_view(top_n=5)
    assert len(board) >= 1
    assert board[0].agent_name == "a"


def test_service_health():
    svc = _build_service()
    h = svc.health()
    assert h.overall_health == HealthLevel.UNKNOWN


def test_service_cost():
    svc = _build_service()
    c = svc.cost()
    assert c.invocations == 0


def test_service_overview_with_collaboration_data():
    svc = _build_service()
    o = svc.overview(
        collaboration_counts={
            "research->compliance": 5,
            "compliance->risk": 3,
        },
        recent_executions=[],
        forecast_accuracy=[],
        recommendation_accuracy=[],
    )
    assert o.total_collaborations == 8
    keys = {(c.from_agent, c.to_agent) for c in o.collaborations}
    assert ("research", "compliance") in keys
    assert ("compliance", "risk") in keys


def test_service_pre_seed_agents():
    class _FW:
        def list_agents(self):
            return [
                AgentMetadata(name="echo-agent"),
                AgentMetadata(name="audit-agent"),
            ]

    svc = build_default_agent_analytics_service(
        framework_service=_FW()
    )
    assert "echo-agent" in svc.repo.all_agent_names()
    assert "audit-agent" in svc.repo.all_agent_names()


# ─── API integration ───────────────────────────────────────


@pytest.mark.asyncio
async def test_api_overview_and_health():
    from app.api.dependencies import (
        get_agent_analytics_service,
        reset_agent_analytics_service,
    )
    reset_agent_analytics_service()
    svc = _build_service()
    app.dependency_overrides[
        get_agent_analytics_service
    ] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get(
                "/api/v1/agents/analytics/overview"
            )
            assert r.status_code == 200
            assert "total_agents" in r.json()
            r2 = await ac.get("/api/v1/agents/analytics/health")
            assert r2.status_code == 200
            assert "overall_health" in r2.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_record_and_performance():
    from app.api.dependencies import (
        get_agent_analytics_service,
        reset_agent_analytics_service,
    )
    reset_agent_analytics_service()
    svc = _build_service()
    app.dependency_overrides[
        get_agent_analytics_service
    ] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.post(
                "/api/v1/agents/analytics/record",
                json={
                    "agent_name": "test-agent",
                    "duration_ms": 100.0,
                    "status": "succeeded",
                    "confidence": 0.8,
                },
            )
            assert r.status_code == 200
            r2 = await ac.get(
                "/api/v1/agents/analytics/performance"
            )
            assert r2.status_code == 200
            assert any(
                p["agent_name"] == "test-agent"
                for p in r2.json()
            )
            r3 = await ac.get(
                "/api/v1/agents/analytics/performance/test-agent"
            )
            assert r3.status_code == 200
            assert r3.json()["agent_name"] == "test-agent"
            r4 = await ac.get(
                "/api/v1/agents/analytics/performance/test-agent/latency"
            )
            assert r4.status_code == 200
            r5 = await ac.get(
                "/api/v1/agents/analytics/performance/nope-agent"
            )
            assert r5.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_leaderboard_and_cost():
    from app.api.dependencies import (
        get_agent_analytics_service,
        reset_agent_analytics_service,
    )
    reset_agent_analytics_service()
    svc = _build_service()
    app.dependency_overrides[
        get_agent_analytics_service
    ] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get(
                "/api/v1/agents/analytics/leaderboard?top_n=5"
            )
            assert r.status_code == 200
            assert isinstance(r.json(), list)
            r2 = await ac.get("/api/v1/agents/analytics/cost")
            assert r2.status_code == 200
            assert "cost_units" in r2.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_reset():
    from app.api.dependencies import (
        get_agent_analytics_service,
        reset_agent_analytics_service,
    )
    reset_agent_analytics_service()
    svc = _build_service()
    app.dependency_overrides[
        get_agent_analytics_service
    ] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            await ac.post(
                "/api/v1/agents/analytics/record",
                json={
                    "agent_name": "x",
                    "duration_ms": 10,
                    "status": "succeeded",
                },
            )
            r = await ac.post(
                "/api/v1/agents/analytics/reset"
            )
            assert r.status_code == 200
            assert "x" not in svc.repo.all_agent_names()
    finally:
        app.dependency_overrides.clear()
