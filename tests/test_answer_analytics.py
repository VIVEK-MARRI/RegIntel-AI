"""Tests for Module 5.8 — Answer Analytics Platform."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_answer_analytics_service,
    get_answer_health_monitor,
    reset_answer_analytics_service,
)
from app.api.v1.answer_analytics import router as answer_analytics_router
from app.schemas.answer_generation import AnswerSection
from app.schemas.analytics_v2 import (
    AnalyticsWindow,
    AnswerAnalyticsEvent,
    AnswerAnalyticsSnapshot,
    HealthStatus,
)
from app.schemas.attribution import AttributionSection
from app.schemas.citation import (
    AnnotatedAnswer,
    AnnotatedText,
    ReferenceEntry,
)
from app.schemas.confidence import ConfidenceLevel
from app.schemas.hallucination import HallucinationRiskLevel
from app.schemas.orchestrator import (
    FinalAnswerResponse,
    OrchestratorMetadata,
)
from app.services.answer_analytics import (
    AnswerHealthMonitor,
    AnswerMetricsRepository,
    build_default_answer_analytics_service,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_answer_analytics_service()
    yield
    reset_answer_analytics_service()


def _make_response(
    *,
    query: str = "What is KYC?",
    faithfulness: float = 0.95,
    hallucination_detected: bool = False,
    confidence: float = 0.85,
    attribution_coverage: float = 1.0,
    citation_coverage: float = 1.0,
    latency_ms: float = 50.0,
    model_used: str | None = "gpt-4o-mini",
    provider_used: str | None = "openai",
) -> FinalAnswerResponse:
    answer = AnswerSection(
        executive_summary="Banks perform KYC at onboarding.",
        detailed_explanation="KYC includes identity verification and address proof.",
        supporting_evidence=[],
        key_regulatory_references=[],
    )
    exec_text = AnnotatedText(
        text=answer.executive_summary,
        citations=[],
        claim_count=1,
        cited_claim_count=1,
    )
    detailed_text = AnnotatedText(
        text=answer.detailed_explanation,
        citations=[],
        claim_count=1,
        cited_claim_count=1 if citation_coverage >= 1.0 else 0,
    )
    annotated = AnnotatedAnswer(
        executive_summary=exec_text,
        detailed_explanation=detailed_text,
        supporting_evidence=[],
        key_regulatory_references=[],
        references=[
            ReferenceEntry(
                citation_id="cit-1",
                document_id="doc-1",
                document_title="RBI KYC",
                page_number=8,
                section="KYC Norms",
                chunk_id="chk-1",
                excerpt="KYC includes identity verification",
            )
        ],
        citation_map={"clm-1": "cit-1"},
    )
    from app.schemas.attribution import SourceAttribution, AttributionConfidence

    attributions = []
    if attribution_coverage > 0:
        attributions = [
            SourceAttribution(
                section=AttributionSection.EXECUTIVE_SUMMARY,
                segment_index=0,
                segment_text=answer.executive_summary,
                document_id="doc-1",
                document_title="RBI KYC",
                chunk_id="chk-1",
                excerpt="KYC includes identity verification",
                similarity=0.8,
                confidence=AttributionConfidence.HIGH,
            )
        ]
    return FinalAnswerResponse(
        query=query,
        answer=answer,
        citations=annotated,
        confidence_score=confidence,
        confidence_level=(
            ConfidenceLevel.HIGH
            if confidence >= 0.9
            else (ConfidenceLevel.MEDIUM if confidence >= 0.7 else ConfidenceLevel.LOW)
        ),
        faithfulness_score=faithfulness,
        hallucination_detected=hallucination_detected,
        hallucination_risk_level=(
            HallucinationRiskLevel.NONE
            if not hallucination_detected and faithfulness >= 0.9
            else HallucinationRiskLevel.MEDIUM
        ),
        source_attributions=attributions,
        attribution_coverage_ratio=attribution_coverage,
        metadata=OrchestratorMetadata(
            model_used=model_used, provider_used=provider_used
        ),
        latency_ms=latency_ms,
    )


@pytest.fixture
def app():
    service = build_default_answer_analytics_service()
    app = FastAPI()
    app.include_router(answer_analytics_router, prefix="/api/v1")
    app.dependency_overrides[get_answer_analytics_service] = lambda: service
    app.dependency_overrides[get_answer_health_monitor] = lambda: AnswerHealthMonitor(
        service=service
    )
    yield app
    app.dependency_overrides.clear()


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_analytics_window_values(self):
        assert AnalyticsWindow.ALL.value == "all"
        assert AnalyticsWindow.DAY.value == "day"
        assert AnalyticsWindow.HOUR.value == "hour"

    def test_health_status_values(self):
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"

    def test_snapshot_defaults(self):
        s = AnswerAnalyticsSnapshot()
        assert s.total_responses == 0
        assert s.average_faithfulness == 0.0
        assert s.hallucination_rate == 0.0
        assert s.confidence_distribution.high == 0


# ─── Repository tests ──────────────────────────────────────────────────────


class TestAnswerMetricsRepository:
    def test_add_and_retrieve(self):
        repo = AnswerMetricsRepository()
        event = AnswerAnalyticsEvent(
            request_id="r1",
            query="q",
            confidence_score=0.5,
            confidence_level="medium",
            faithfulness_score=0.7,
            hallucination_detected=False,
            hallucination_risk_level="low",
            attribution_coverage_ratio=0.5,
            citation_coverage_ratio=0.5,
            source_count=1,
            latency_ms=10.0,
        )
        repo.add(event)
        assert len(repo.all()) == 1
        assert repo.all()[0].request_id == "r1"

    def test_window_all(self):
        repo = AnswerMetricsRepository()
        for i in range(3):
            repo.add(
                AnswerAnalyticsEvent(
                    request_id=f"r{i}",
                    query=f"q{i}",
                    confidence_score=0.5,
                    confidence_level="medium",
                    faithfulness_score=0.7,
                    hallucination_detected=False,
                    hallucination_risk_level="low",
                    attribution_coverage_ratio=0.5,
                    citation_coverage_ratio=0.5,
                    source_count=1,
                    latency_ms=10.0,
                )
            )
        assert len(repo.window(AnalyticsWindow.ALL)) == 3

    def test_window_hour(self):
        repo = AnswerMetricsRepository()
        repo.add(
            AnswerAnalyticsEvent(
                request_id="r1",
                query="q",
                confidence_score=0.5,
                confidence_level="medium",
                faithfulness_score=0.7,
                hallucination_detected=False,
                hallucination_risk_level="low",
                attribution_coverage_ratio=0.5,
                citation_coverage_ratio=0.5,
                source_count=1,
                latency_ms=10.0,
            )
        )
        # Hour window should still contain a fresh event.
        assert len(repo.window(AnalyticsWindow.HOUR)) == 1

    def test_reset(self):
        repo = AnswerMetricsRepository()
        repo.add(
            AnswerAnalyticsEvent(
                request_id="r1",
                query="q",
                confidence_score=0.5,
                confidence_level="medium",
                faithfulness_score=0.7,
                hallucination_detected=False,
                hallucination_risk_level="low",
                attribution_coverage_ratio=0.5,
                citation_coverage_ratio=0.5,
                source_count=1,
                latency_ms=10.0,
            )
        )
        repo.reset()
        assert len(repo.all()) == 0

    def test_persistence(self, tmp_path):
        persist = tmp_path / "events.jsonl"
        repo = AnswerMetricsRepository(persist_path=persist)
        repo.add(
            AnswerAnalyticsEvent(
                request_id="r1",
                query="q",
                confidence_score=0.5,
                confidence_level="medium",
                faithfulness_score=0.7,
                hallucination_detected=False,
                hallucination_risk_level="low",
                attribution_coverage_ratio=0.5,
                citation_coverage_ratio=0.5,
                source_count=1,
                latency_ms=10.0,
            )
        )
        assert persist.exists()
        contents = persist.read_text()
        assert "r1" in contents


# ─── Service tests ────────────────────────────────────────────────────────


class TestAnswerAnalyticsService:
    def test_record_event(self):
        service = build_default_answer_analytics_service()
        response = _make_response()
        event = service.record(response, total_tokens=100)
        assert isinstance(event, AnswerAnalyticsEvent)
        assert event.total_tokens == 100
        assert event.model_used == "gpt-4o-mini"
        assert event.provider_used == "openai"
        assert event.source_count == 1

    def test_record_calculates_citation_coverage(self):
        service = build_default_answer_analytics_service()
        response = _make_response(citation_coverage=0.5)
        event = service.record(response)
        assert event.citation_coverage_ratio == 0.5

    def test_snapshot_empty(self):
        service = build_default_answer_analytics_service()
        snap = service.snapshot()
        assert snap.total_responses == 0

    def test_snapshot_with_data(self):
        service = build_default_answer_analytics_service()
        service.record(
            _make_response(faithfulness=0.9, confidence=0.85), total_tokens=50
        )
        service.record(
            _make_response(
                faithfulness=0.6, confidence=0.6, hallucination_detected=True
            ),
            total_tokens=80,
        )
        snap = service.snapshot()
        assert snap.total_responses == 2
        assert 0.0 < snap.average_faithfulness < 1.0
        assert snap.hallucination_rate == 0.5  # 1/2
        assert snap.confidence_distribution.medium == 1
        assert snap.confidence_distribution.low == 1
        assert snap.faithfulness_distribution.bucket_75_100 == 1
        assert snap.faithfulness_distribution.bucket_50_75 == 1
        assert snap.hallucination_buckets.detected == 1
        assert snap.hallucination_buckets.not_detected == 1
        assert snap.token_usage.total_tokens == 130
        assert snap.token_usage.models["gpt-4o-mini"] == 2

    def test_snapshot_window(self):
        service = build_default_answer_analytics_service()
        service.record(_make_response())
        snap_all = service.snapshot(AnalyticsWindow.ALL)
        snap_day = service.snapshot(AnalyticsWindow.DAY)
        assert snap_all.total_responses == 1
        assert snap_day.total_responses == 1

    def test_health_no_data(self):
        service = build_default_answer_analytics_service()
        h = service.health()
        assert h.status == HealthStatus.HEALTHY
        assert h.total_responses == 0

    def test_health_healthy(self):
        service = build_default_answer_analytics_service()
        for _ in range(3):
            service.record(_make_response(faithfulness=0.95, confidence=0.95))
        h = service.health()
        assert h.status == HealthStatus.HEALTHY
        assert h.hallucination_rate == 0.0

    def test_health_degraded_high_hallucination(self):
        service = build_default_answer_analytics_service()
        # 50% hallucination rate
        for _ in range(2):
            service.record(
                _make_response(hallucination_detected=True, faithfulness=0.3)
            )
        for _ in range(2):
            service.record(
                _make_response(hallucination_detected=False, faithfulness=0.9)
            )
        h = service.health()
        assert h.hallucination_rate == 0.5
        assert h.status in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY)
        assert any("hallucination" in r for r in h.degraded_reasons)

    def test_health_unhealthy_high_latency(self):
        service = build_default_answer_analytics_service()
        service.record(_make_response(latency_ms=10000.0))
        h = service.health()
        assert h.status in (HealthStatus.DEGRADED, HealthStatus.UNHEALTHY)

    def test_reset(self):
        service = build_default_answer_analytics_service()
        service.record(_make_response())
        service.reset()
        snap = service.snapshot()
        assert snap.total_responses == 0


class TestAnswerHealthMonitor:
    def test_check_delegates(self):
        service = build_default_answer_analytics_service()
        service.record(_make_response())
        monitor = AnswerHealthMonitor(service=service)
        h = monitor.check()
        assert h.total_responses == 1


# ─── API tests ─────────────────────────────────────────────────────────────


class TestAnswerAnalyticsAPI:
    @pytest.mark.asyncio
    async def test_analytics_empty(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/answers/analytics")
            assert r.status_code == 200
            data = r.json()
            assert data["total_responses"] == 0

    @pytest.mark.asyncio
    async def test_analytics_invalid_window(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/answers/analytics?window=bogus")
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_quality_hallucinations_citations(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            for path in ("/quality", "/hallucinations", "/citations"):
                r = await c.get(f"/api/v1/answers{path}")
                assert r.status_code == 200
                assert "total_responses" in r.json()

    @pytest.mark.asyncio
    async def test_health(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/answers/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "healthy"
            assert "degraded_reasons" in data

    @pytest.mark.asyncio
    async def test_record(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            payload = {
                "response": _make_response().model_dump(mode="json"),
                "total_tokens": 100,
            }
            r = await c.post("/api/v1/answers/record", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["total_tokens"] == 100

    @pytest.mark.asyncio
    async def test_record_missing_response(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post("/api/v1/answers/record", json={})
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_end_to_end_flow(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            # 1. Record a good response.
            payload = {
                "response": _make_response(
                    faithfulness=0.95, confidence=0.92, attribution_coverage=1.0
                ).model_dump(mode="json"),
                "total_tokens": 200,
            }
            r = await c.post("/api/v1/answers/record", json=payload)
            assert r.status_code == 200
            # 2. Record a bad response.
            payload = {
                "response": _make_response(
                    faithfulness=0.2, hallucination_detected=True, confidence=0.3
                ).model_dump(mode="json"),
                "total_tokens": 50,
            }
            r = await c.post("/api/v1/answers/record", json=payload)
            assert r.status_code == 200
            # 3. Read analytics.
            r = await c.get("/api/v1/answers/analytics")
            data = r.json()
            assert data["total_responses"] == 2
            assert data["hallucination_rate"] == 0.5
            assert data["token_usage"]["total_tokens"] == 250
            # 4. Read health.
            r = await c.get("/api/v1/answers/health")
            assert r.status_code == 200
            h = r.json()
            assert h["total_responses"] == 2
            # Should be degraded (hallucination rate too high).
            assert h["status"] in ("degraded", "unhealthy")
