"""Tests for Module 8.3 — Risk Forecasting Engine."""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.forecasting import (
    ForecastRequest,
    ForecastScenario,
    HistoryPoint,
    RiskForecast,
    ScenarioRequest,
    ScenarioType,
)
from app.services.forecasting import (
    ExponentialSmoothingForecastModel,
    ForecastingService,
    InMemoryForecastingStore,
    LinearRegressionForecastModel,
    RiskForecastingEngine,
    ScenarioAnalyzer,
    TrendPredictor,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    from app.api import dependencies as deps

    deps.reset_forecasting_service()
    deps.reset_compliance_risk_service()
    yield
    deps.reset_forecasting_service()
    deps.reset_compliance_risk_service()


@pytest.fixture
def store() -> InMemoryForecastingStore:
    return InMemoryForecastingStore()


@pytest.fixture
def service(store: InMemoryForecastingStore) -> ForecastingService:
    return ForecastingService(store=store)


def _override(svc: ForecastingService):
    from app.api.dependencies import get_forecasting_service

    app.dependency_overrides[get_forecasting_service] = lambda: svc
    return svc


# ─── Models ────────────────────────────────────────────────────────


class TestLinearRegressionModel:
    def test_fit_and_predict_constant(self) -> None:
        m = LinearRegressionForecastModel()
        m.fit([0.5, 0.5, 0.5, 0.5])
        pts = m.predict(3)
        assert len(pts) == 3
        for p in pts:
            assert 0.0 <= p.predicted_score <= 1.0
            assert p.lower_bound <= p.predicted_score <= p.upper_bound

    def test_fit_and_predict_increasing(self) -> None:
        m = LinearRegressionForecastModel()
        m.fit([0.1, 0.3, 0.5, 0.7, 0.9])
        pts = m.predict(5)
        # Increasing series should give a forecast near the trend
        for p in pts:
            assert p.predicted_score >= 0.5

    def test_fit_empty(self) -> None:
        m = LinearRegressionForecastModel()
        m.fit([])
        assert m.predict(3) == []


class TestExponentialSmoothingModel:
    def test_fit_and_predict(self) -> None:
        m = ExponentialSmoothingForecastModel()
        m.fit([0.3, 0.4, 0.5, 0.6])
        pts = m.predict(2)
        assert len(pts) == 2
        for p in pts:
            assert 0.0 <= p.predicted_score <= 1.0

    def test_fit_empty(self) -> None:
        m = ExponentialSmoothingForecastModel()
        m.fit([])
        assert m.predict(3) == []


# ─── Trend / Scenario ──────────────────────────────────────────────


class TestTrendPredictor:
    def test_flat(self) -> None:
        tp = TrendPredictor()
        score, direction = tp.predict([0.5, 0.5, 0.5])
        assert direction == "flat"
        assert score == 0.5

    def test_up(self) -> None:
        tp = TrendPredictor()
        score, direction = tp.predict([0.1, 0.3, 0.5, 0.7])
        assert direction == "up"

    def test_down(self) -> None:
        tp = TrendPredictor()
        score, direction = tp.predict([0.9, 0.7, 0.5, 0.3])
        assert direction == "down"

    def test_empty(self) -> None:
        tp = TrendPredictor()
        score, direction = tp.predict([])
        assert score == 0.0
        assert direction == "flat"


class TestScenarioAnalyzer:
    def test_three_scenarios(self) -> None:
        sa = ScenarioAnalyzer()
        out = sa.analyze(
            0.5,
            [ScenarioType.BEST_CASE, ScenarioType.BASELINE, ScenarioType.WORST_CASE],
        )
        assert len(out) == 3
        # BEST_CASE is lower
        best = next(o for o in out if o.name == "best_case")
        base = next(o for o in out if o.name == "baseline")
        worst = next(o for o in out if o.name == "worst_case")
        assert best.predicted_score < base.predicted_score
        assert worst.predicted_score > base.predicted_score


# ─── Engine ────────────────────────────────────────────────────────


class TestRiskForecastingEngine:
    def test_forecast_basic(self) -> None:
        eng = RiskForecastingEngine()
        req = ForecastRequest(
            document_id="DOC1",
            horizon_days=7,
            history=[
                HistoryPoint(value=0.4),
                HistoryPoint(value=0.5),
                HistoryPoint(value=0.6),
            ],
        )
        f = eng.forecast(req)
        assert f.horizon_days == 7
        assert len(f.points) == 7
        assert 0.0 <= f.predicted_risk_score <= 1.0

    def test_forecast_drift_detected(self) -> None:
        eng = RiskForecastingEngine()
        req1 = ForecastRequest(
            horizon_days=3,
            history=[HistoryPoint(value=0.2)],
        )
        eng.forecast(req1)
        req2 = ForecastRequest(
            horizon_days=3,
            history=[HistoryPoint(value=0.9)],
        )
        f2 = eng.forecast(req2)
        assert f2.drift_detected is True

    def test_scenario_simulation(self) -> None:
        eng = RiskForecastingEngine()
        req = ScenarioRequest(
            baseline_score=0.5,
            scenario_types=[
                ScenarioType.BEST_CASE,
                ScenarioType.WORST_CASE,
            ],
        )
        out = eng.scenario_simulation(req)
        assert len(out) == 2

    def test_trend_prediction_empty(self) -> None:
        eng = RiskForecastingEngine()
        score, direction = eng.trend_prediction("DOC-NONE")
        assert score == 0.0
        assert direction == "flat"


# ─── Store / Service ───────────────────────────────────────────────


class TestStoreAndService:
    def test_store_add_get_list(self, service: ForecastingService) -> None:
        eng = RiskForecastingEngine()
        f = eng.forecast(
            ForecastRequest(
                horizon_days=3,
                history=[HistoryPoint(value=0.4)],
            )
        )
        service.store.add(f)
        assert service.store.get(f.forecast_id) is f
        assert service.store.list_all()

    def test_service_forecast(self, service: ForecastingService) -> None:
        f = service.forecast(
            ForecastRequest(
                document_id="DOC1",
                horizon_days=5,
                history=[HistoryPoint(value=0.5)],
            )
        )
        assert f.forecast_id.startswith("fcast-")
        assert service.get(f.forecast_id) is f

    def test_service_scenario_simulation(self, service: ForecastingService) -> None:
        out = service.scenario_simulation(ScenarioRequest(baseline_score=0.5))
        assert len(out) == 3

    def test_service_accuracy(self, service: ForecastingService) -> None:
        service.forecast(
            ForecastRequest(horizon_days=3, history=[HistoryPoint(value=0.4)])
        )
        m = service.accuracy_metrics()
        assert m["total_forecasts"] == 1
        assert m["average_horizon_days"] == 3.0

    def test_get_missing(self, service: ForecastingService) -> None:
        assert service.get("missing") is None


# ─── API ──────────────────────────────────────────────────────────


class TestForecastingAPI:
    @pytest.mark.asyncio
    async def test_health(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/forecasting/health")
            assert r.status_code == 200
            assert r.json()["module"] == "forecasting"

    @pytest.mark.asyncio
    async def test_forecast(self) -> None:
        _override(ForecastingService(store=InMemoryForecastingStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/api/v1/forecasting/forecast",
                json={
                    "document_id": "DOC-API",
                    "horizon_days": 5,
                    "history": [{"value": 0.4}, {"value": 0.5}],
                },
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["horizon_days"] == 5
            assert len(body["points"]) == 5

    @pytest.mark.asyncio
    async def test_scenario(self) -> None:
        _override(ForecastingService(store=InMemoryForecastingStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/api/v1/forecasting/scenario",
                json={"baseline_score": 0.5},
            )
            assert r.status_code == 200
            body = r.json()
            assert len(body) == 3

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        svc = ForecastingService(store=InMemoryForecastingStore())
        svc.forecast(ForecastRequest(horizon_days=5, history=[HistoryPoint(value=0.5)]))
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/forecasting/stats")
            assert r.status_code == 200
            body = r.json()
            assert body["total_forecasts"] == 1

    @pytest.mark.asyncio
    async def test_accuracy(self) -> None:
        _override(ForecastingService(store=InMemoryForecastingStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/forecasting/accuracy")
            assert r.status_code == 200
            assert "total_forecasts" in r.json()

    @pytest.mark.asyncio
    async def test_list(self) -> None:
        svc = ForecastingService(store=InMemoryForecastingStore())
        svc.forecast(ForecastRequest(horizon_days=3, history=[HistoryPoint(value=0.4)]))
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/forecasting")
            assert r.status_code == 200
            body = r.json()
            assert isinstance(body, list)
            assert len(body) >= 1

    @pytest.mark.asyncio
    async def test_get_ok_and_404(self) -> None:
        svc = ForecastingService(store=InMemoryForecastingStore())
        f = svc.forecast(
            ForecastRequest(horizon_days=3, history=[HistoryPoint(value=0.4)])
        )
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.get(f"/api/v1/forecasting/{f.forecast_id}")
            assert r1.status_code == 200
            r2 = await client.get("/api/v1/forecasting/missing")
            assert r2.status_code == 404

    @pytest.mark.asyncio
    async def test_trend(self) -> None:
        _override(ForecastingService(store=InMemoryForecastingStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/forecasting/trend/DOC-NONE")
            assert r.status_code == 200
            body = r.json()
            assert body["direction"] in {"up", "down", "flat"}
