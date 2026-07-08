"""Tests for Module 7.8 — Executive Dashboard."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_executive_dashboard_service,
    reset_executive_dashboard_service,
)
from app.main import app
from app.schemas.dashboard import (
    AlertMetricsView,
    ComplianceMetrics,
    DashboardSnapshot,
    ImpactDistribution,
    InsightSeverity,
    MonitoringHealthView,
    RiskInsight,
    RiskInsightsResponse,
    RiskLevel,
    SystemHealthView,
    TrendDirection,
    TrendPoint,
    TrendSeries,
)
from app.services.dashboard import (
    ComplianceMetricsAggregator,
    ExecutiveDashboardService,
    RiskInsightsEngine,
    TrendAnalyzer,
    build_default_executive_dashboard_service,
)
from app.services.observability import reset_dashboard_metrics


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_executive_dashboard_service()
    reset_dashboard_metrics()
    yield
    reset_executive_dashboard_service()
    reset_dashboard_metrics()


@pytest.fixture
def service():
    return ExecutiveDashboardService()


# ─── ComplianceMetricsAggregator ─────────────────────────────────────


def test_compliance_aggregator_returns_metrics():
    m = ComplianceMetricsAggregator().aggregate()
    assert isinstance(m, ComplianceMetrics)
    # Defaults are zero
    assert m.regulations_tracked >= 0


def test_compliance_aggregator_uptime():
    agg = ComplianceMetricsAggregator()
    assert agg.uptime_seconds() >= 0


# ─── TrendAnalyzer ───────────────────────────────────────────────────


def test_trend_analyzer_runs():
    series = TrendAnalyzer().analyze()
    assert isinstance(series, list)


def test_trend_analyzer_direction_flat():
    a = TrendAnalyzer()
    assert a._direction([]) == TrendDirection.FLAT
    assert (
        a._direction([TrendPoint(label="a", value=1.0, timestamp=0.0)])
        == TrendDirection.FLAT
    )


def test_trend_analyzer_direction_up():
    a = TrendAnalyzer()
    pts = [
        TrendPoint(label="a", value=1.0, timestamp=0.0),
        TrendPoint(label="b", value=2.0, timestamp=1.0),
    ]
    assert a._direction(pts) == TrendDirection.UP


def test_trend_analyzer_direction_down():
    a = TrendAnalyzer()
    pts = [
        TrendPoint(label="a", value=5.0, timestamp=0.0),
        TrendPoint(label="b", value=2.0, timestamp=1.0),
    ]
    assert a._direction(pts) == TrendDirection.DOWN


def test_trend_analyzer_delta_pct():
    a = TrendAnalyzer()
    assert (
        a._delta_pct(
            [
                TrendPoint(label="a", value=100.0, timestamp=0.0),
                TrendPoint(label="b", value=150.0, timestamp=1.0),
            ]
        )
        == 50.0
    )


# ─── RiskInsightsEngine ─────────────────────────────────────────────


def test_risk_engine_returns_response():
    res = RiskInsightsEngine().insights()
    assert isinstance(res, RiskInsightsResponse)
    assert res.risk_level in (e for e in RiskLevel)
    assert res.insights


def test_risk_engine_to_level():
    e = RiskInsightsEngine()
    assert e._to_level(0.9) == RiskLevel.CRITICAL
    assert e._to_level(0.7) == RiskLevel.HIGH
    assert e._to_level(0.5) == RiskLevel.ELEVATED
    assert e._to_level(0.3) == RiskLevel.MODERATE
    assert e._to_level(0.1) == RiskLevel.LOW


# ─── ExecutiveDashboardService ──────────────────────────────────────


def test_service_snapshot(service):
    snap = service.snapshot()
    assert isinstance(snap, DashboardSnapshot)
    assert snap.risk_level in (e for e in RiskLevel)


def test_service_compliance_view(service):
    m = service.compliance_view()
    assert isinstance(m, ComplianceMetrics)


def test_service_trends_view(service):
    s = service.trends_view()
    assert isinstance(s, list)


def test_service_insights_view(service):
    res = service.insights_view()
    assert isinstance(res, RiskInsightsResponse)


def test_service_impact_view(service):
    v = service.impact_view()
    assert isinstance(v, ImpactDistribution)


def test_service_alerts_view(service):
    v = service.alerts_view()
    assert isinstance(v, AlertMetricsView)


def test_service_monitoring_view(service):
    v = service.monitoring_view()
    assert isinstance(v, MonitoringHealthView)


def test_service_system_view(service):
    v = service.system_view()
    assert isinstance(v, SystemHealthView)
    assert v.status in ("ok", "degraded")


def test_service_last_snapshot(service):
    assert service.last_snapshot() is None
    service.snapshot()
    assert service.last_snapshot() is not None


def test_build_default_service():
    svc = build_default_executive_dashboard_service()
    assert isinstance(svc, ExecutiveDashboardService)


# ─── API integration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_health():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/health")
        assert r.status_code == 200
        assert r.json()["module"] == "dashboard"


@pytest.mark.asyncio
async def test_api_snapshot():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert "compliance" in body
        assert "trends" in body
        assert "impact_distribution" in body
        assert "alerts" in body
        assert "monitoring" in body
        assert "system" in body
        assert "insights" in body


@pytest.mark.asyncio
async def test_api_compliance():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/compliance")
        assert r.status_code == 200
        assert "regulations_tracked" in r.json()


@pytest.mark.asyncio
async def test_api_trends():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/trends")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body


@pytest.mark.asyncio
async def test_api_impact_distribution():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/impact-distribution")
        assert r.status_code == 200
        assert "counts" in r.json()


@pytest.mark.asyncio
async def test_api_alerts():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/alerts")
        assert r.status_code == 200
        assert "total" in r.json()


@pytest.mark.asyncio
async def test_api_monitoring():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/monitoring")
        assert r.status_code == 200
        assert "sources_monitored" in r.json()


@pytest.mark.asyncio
async def test_api_system():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/system")
        assert r.status_code == 200
        body = r.json()
        assert "status" in body
        assert "components" in body


@pytest.mark.asyncio
async def test_api_insights():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/insights")
        assert r.status_code == 200
        body = r.json()
        assert "risk_level" in body
        assert "insights" in body


@pytest.mark.asyncio
async def test_api_risk():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/v1/dashboard/risk")
        assert r.status_code == 200
        body = r.json()
        assert "risk_level" in body
        assert "risk_score" in body
