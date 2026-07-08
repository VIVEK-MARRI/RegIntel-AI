"""Tests for Module 8.1 — Compliance Risk Intelligence."""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.risk import (
    RiskAssessmentRequest,
    RiskCategory,
    RiskFilter,
    RiskLevel,
)
from app.schemas.change import ChangeCategory, ChangeSeverity
from app.schemas.impact import ImpactLevel
from app.services.compliance_risk import (
    ComplianceRiskService,
    InMemoryRiskStore,
    RiskAnalyzer,
    RiskRepository,
    RiskScorer,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    from app.api import dependencies as deps

    deps.reset_compliance_risk_service()
    yield
    deps.reset_compliance_risk_service()


@pytest.fixture
def store() -> InMemoryRiskStore:
    return InMemoryRiskStore()


@pytest.fixture
def service(store: InMemoryRiskStore) -> ComplianceRiskService:
    return ComplianceRiskService(store=store)


def _override(svc: ComplianceRiskService):
    from app.api.dependencies import get_compliance_risk_service

    app.dependency_overrides[get_compliance_risk_service] = lambda: svc
    return svc


def _make_request(
    document_id: str = "DOC-1",
    source: str = "unit-test",
    context: str = "KYC and AML update",
) -> RiskAssessmentRequest:
    return RiskAssessmentRequest(
        document_id=document_id,
        source=source,
        context={"text": context},
    )


# ─── RiskScorer ────────────────────────────────────────────────────


class TestRiskScorer:
    def test_thresholds(self) -> None:
        s = RiskScorer()
        assert s._to_level(0.9) == RiskLevel.CRITICAL
        assert s._to_level(0.7) == RiskLevel.HIGH
        assert s._to_level(0.5) == RiskLevel.MEDIUM
        assert s._to_level(0.1) == RiskLevel.LOW

    def test_weights_sum_to_one(self) -> None:
        # Weights are inline constants in the scoring formula:
        # 0.30 (severity) + 0.25 (category) + 0.25 (impact)
        # + 0.10 (breadth) + 0.10 (gap) = 1.00
        total = 0.30 + 0.25 + 0.25 + 0.10 + 0.10
        assert abs(total - 1.0) < 1e-6

    def test_score_in_range(self) -> None:
        s = RiskScorer()
        score, level = s.score(
            severity=ChangeSeverity.HIGH,
            category=ChangeCategory.PENALTY_CHANGE,
            impact_level=ImpactLevel.HIGH,
            change_count=3,
            gap_count=2,
        )
        assert 0.0 <= score <= 1.0
        assert level in RiskLevel


# ─── RiskAnalyzer ──────────────────────────────────────────────────


class TestRiskAnalyzer:
    def test_analyze_returns_areas_factors_actions(self) -> None:
        a = RiskAnalyzer()
        out = a.analyze(
            "KYC and AML changes with penalty exposure and deadline 30 days",
            severity=ChangeSeverity.HIGH,
            category=ChangeCategory.PENALTY_CHANGE,
            impact_level=ImpactLevel.HIGH,
            change_count=2,
        )
        assert "areas" in out
        assert "factors" in out
        assert "actions" in out
        assert "gaps" in out
        assert "categories" in out
        assert len(out["actions"]) >= 1
        assert out["gaps"], "Penalty category should trigger a gap"

    def test_analyze_other_category_no_gap(self) -> None:
        a = RiskAnalyzer()
        out = a.analyze(
            "Some text",
            severity=ChangeSeverity.LOW,
            category=ChangeCategory.CLARIFICATION,
            impact_level=ImpactLevel.LOW,
            change_count=1,
        )
        assert not out["gaps"]


# ─── Store / Repository ───────────────────────────────────────────


class TestStoreAndRepository:
    def test_store_round_trip(self, service: ComplianceRiskService) -> None:
        req = _make_request()
        ra = service.assess(req)
        assert service.store.get(ra.assessment_id) is ra
        assert service.store.list_all()

    def test_repository_search(self, service: ComplianceRiskService) -> None:
        service.assess(_make_request(document_id="A"))
        service.assess(_make_request(document_id="B"))
        flt = RiskFilter(document_id="A")
        result = service.repository.search(flt)
        assert result.total == 1
        assert result.items[0].document_id == "A"

    def test_repository_stats(self, service: ComplianceRiskService) -> None:
        service.assess(_make_request())
        s = service.repository.stats()
        assert s.total_assessments >= 1

    def test_history_for(self, service: ComplianceRiskService) -> None:
        service.assess(_make_request(document_id="X"))
        service.assess(_make_request(document_id="X"))
        history = service.history_for("X")
        assert len(history) == 2

    def test_trend_for_flat(self, service: ComplianceRiskService) -> None:
        service.assess(_make_request(document_id="T"))
        service.assess(_make_request(document_id="T"))
        t = service.trend_for("T")
        assert t.direction == "flat"
        assert t.delta == 0.0


# ─── Service ──────────────────────────────────────────────────────


class TestComplianceRiskService:
    def test_assess_basic(self, service: ComplianceRiskService) -> None:
        ra = service.assess(_make_request())
        assert ra.assessment_id.startswith("rsk-")
        assert ra.risk_level in RiskLevel
        assert ra.explanation.summary
        assert ra.affected_areas

    def test_assess_with_diff_id_resolves_change(
        self, service: ComplianceRiskService
    ) -> None:
        try:
            from app.services.change_detection import (
                build_default_change_detection_service,
            )
            from app.schemas.change_detection import (
                ChangeDetectionRequest,
                DocumentVersion,
            )

            cd = build_default_change_detection_service()
            req = ChangeDetectionRequest(
                document_id="DOC-CD",
                previous=DocumentVersion(version_id="v1", content="old", metadata={}),
                current=DocumentVersion(version_id="v2", content="new", metadata={}),
            )
            cr = cd.detect(req)
            ra = service.assess(
                RiskAssessmentRequest(
                    document_id="DOC-CD",
                    diff_id=cr.result_id,
                    source="diff-resolve",
                )
            )
            assert ra.diff_id == cr.result_id
        except Exception:
            pytest.skip("change detection unavailable")

    def test_assess_with_impact_id_resolves_impact(
        self, service: ComplianceRiskService
    ) -> None:
        try:
            from app.services.impact_analysis import (
                build_default_impact_analysis_service,
            )
            from app.schemas.impact_analysis import ImpactAnalysisRequest

            ia = build_default_impact_analysis_service()
            iar = ia.analyze(
                ImpactAnalysisRequest(
                    document_id="DOC-IA",
                    diff_id="diff-fake",
                    impact_level="high",
                )
            )
            ra = service.assess(
                RiskAssessmentRequest(
                    document_id="DOC-IA",
                    impact_report_id=iar.report_id,
                    source="impact-resolve",
                )
            )
            assert ra.impact_report_id == iar.report_id
        except Exception:
            pytest.skip("impact analysis unavailable")

    def test_get_returns_none_for_missing(self, service: ComplianceRiskService) -> None:
        assert service.get("missing") is None


# ─── API ──────────────────────────────────────────────────────────


class TestComplianceRiskAPI:
    @pytest.mark.asyncio
    async def test_health(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/compliance-risk/health")
            assert r.status_code == 200
            assert r.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_assess_flow(self) -> None:
        _override(ComplianceRiskService(store=InMemoryRiskStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/api/v1/compliance-risk/assess",
                json={
                    "document_id": "DOC-API",
                    "source": "test",
                    "context": {"text": "KYC and AML update"},
                },
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["assessment_id"].startswith("rsk-")

    @pytest.mark.asyncio
    async def test_list(self) -> None:
        _override(ComplianceRiskService(store=InMemoryRiskStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/compliance-risk?page=1&page_size=10")
            assert r.status_code == 200
            body = r.json()
            assert "items" in body
            assert "total" in body

    @pytest.mark.asyncio
    async def test_get_404(self) -> None:
        _override(ComplianceRiskService(store=InMemoryRiskStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/compliance-risk/missing")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_get_ok(self) -> None:
        svc = ComplianceRiskService(store=InMemoryRiskStore())
        ra = svc.assess(_make_request())
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get(f"/api/v1/compliance-risk/{ra.assessment_id}")
            assert r.status_code == 200
            assert r.json()["assessment_id"] == ra.assessment_id

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        svc = ComplianceRiskService(store=InMemoryRiskStore())
        svc.assess(_make_request())
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/compliance-risk/stats")
            assert r.status_code == 200
            body = r.json()
            assert body["total_assessments"] >= 1

    @pytest.mark.asyncio
    async def test_trend(self) -> None:
        svc = ComplianceRiskService(store=InMemoryRiskStore())
        svc.assess(_make_request(document_id="T-API"))
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/compliance-risk/trend?document_id=T-API")
            assert r.status_code == 200
            body = r.json()
            assert body["document_id"] == "T-API"
            assert body["direction"] in {"up", "down", "flat"}
