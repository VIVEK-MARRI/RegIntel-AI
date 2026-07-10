"""Tests for Module 8.2 — Regulatory Recommendation Engine."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.recommendations import (
    ActionStatus,
    RecommendationFilter,
    RecommendationPriority,
    RecommendationRequest,
    RecommendationType,
)
from app.services.recommendations import (
    ActionPlanner,
    InMemoryRecommendationStore,
    RecommendationGenerator,
    RecommendationService,
)


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    from app.api import dependencies as deps

    deps.reset_recommendation_service()
    deps.reset_compliance_risk_service()
    yield
    deps.reset_recommendation_service()
    deps.reset_compliance_risk_service()


@pytest.fixture
def store() -> InMemoryRecommendationStore:
    return InMemoryRecommendationStore()


@pytest.fixture
def service(store: InMemoryRecommendationStore) -> RecommendationService:
    return RecommendationService(store=store)


def _override(svc: RecommendationService):
    from app.api.dependencies import get_recommendation_service

    app.dependency_overrides[get_recommendation_service] = lambda: svc
    return svc


# ─── ActionPlanner ────────────────────────────────────────────────


class TestActionPlanner:
    def test_plan_with_steps(self) -> None:
        planner = ActionPlanner()
        plan = planner.plan(
            "T",
            [
                {
                    "title": "A",
                    "description": "do a",
                    "owner": "X",
                    "estimated_effort_hours": 2.0,
                },
                {
                    "title": "B",
                    "owner": "Y",
                    "estimated_effort_hours": 3.0,
                    "depends_on": ["1"],
                },
            ],
        )
        assert plan.steps[0].sequence == 1
        assert plan.steps[1].sequence == 2
        assert plan.total_effort_hours == 5.0
        assert plan.steps[1].depends_on == ["1"]

    def test_plan_defaults(self) -> None:
        planner = ActionPlanner()
        plan = planner.plan("T", [{"title": "A"}], total_effort_hours=8.0)
        assert plan.total_effort_hours == 8.0
        assert plan.steps[0].description == ""


# ─── RecommendationGenerator ──────────────────────────────────────


class TestRecommendationGenerator:
    def test_priority_for_risk_levels(self) -> None:
        gen = RecommendationGenerator()
        from app.schemas.risk import RiskLevel

        assert gen._priority_for(RiskLevel.CRITICAL) == RecommendationPriority.P0
        assert gen._priority_for(RiskLevel.HIGH) == RecommendationPriority.P1
        assert gen._priority_for(RiskLevel.MEDIUM) == RecommendationPriority.P2
        assert gen._priority_for(RiskLevel.LOW) == RecommendationPriority.P3

    def test_generate_from_risk_assessment(self) -> None:
        from app.schemas.risk import (
            AffectedArea,
            AffectedAreaRecord,
            RiskAssessment,
            RiskCategory,
            RiskExplanation,
            RiskLevel,
        )

        gen = RecommendationGenerator()
        ra = RiskAssessment(
            document_id="DOC1",
            source="test",
            risk_level=RiskLevel.HIGH,
            risk_score=0.7,
            risk_categories=[RiskCategory.COMPLIANCE_GAP],
            affected_areas=[
                AffectedAreaRecord(
                    area=AffectedArea.KYC,
                    exposure_score=0.8,
                    rationale="kyc exposure",
                )
            ],
            explanation=RiskExplanation(summary="KYC"),
            generated_at=0,
        )
        req = RecommendationRequest(
            document_id="DOC1",
            risk_assessment_id=ra.assessment_id,
        )
        recs = gen.generate(req, risk_assessment=ra, max_recommendations=3)
        assert recs
        assert recs[0].risk_assessment_id == ra.assessment_id
        assert recs[0].priority == RecommendationPriority.P1
        assert recs[0].document_id == "DOC1"

    def test_generate_falls_back_to_general_remediation(self) -> None:
        from app.schemas.risk import (
            AffectedArea,
            AffectedAreaRecord,
            RiskAssessment,
            RiskCategory,
            RiskExplanation,
            RiskLevel,
        )

        gen = RecommendationGenerator()
        ra = RiskAssessment(
            document_id="DOC1",
            source="test",
            risk_level=RiskLevel.LOW,
            risk_score=0.2,
            risk_categories=[RiskCategory.OPERATIONAL],
            affected_areas=[
                AffectedAreaRecord(
                    area=AffectedArea.OTHER,
                    exposure_score=0.1,
                    rationale="unknown",
                )
            ],
            explanation=RiskExplanation(summary="n/a"),
            generated_at=0,
        )
        req = RecommendationRequest(document_id="DOC1")
        recs = gen.generate(req, risk_assessment=ra, max_recommendations=3)
        assert recs
        assert recs[0].recommendation_type == RecommendationType.REMEDIATION


# ─── Store / Repository ───────────────────────────────────────────


class TestStoreAndRepository:
    def test_store_add_get_list(self, service: RecommendationService) -> None:
        from app.schemas.recommendations import Recommendation

        rec = Recommendation(
            title="t",
            description="d",
            recommendation_type=RecommendationType.COMPLIANCE,
            priority=RecommendationPriority.P2,
        )
        service.store.add(rec)
        assert service.store.get(rec.recommendation_id) is rec
        assert rec in service.store.list_all()

    def test_repository_search_pagination(self, service: RecommendationService) -> None:
        from app.schemas.recommendations import Recommendation

        for i in range(5):
            service.store.add(
                Recommendation(
                    title=f"t{i}",
                    description="d",
                    recommendation_type=RecommendationType.COMPLIANCE,
                    priority=RecommendationPriority.P2,
                )
            )
        flt = RecommendationFilter(page=1, page_size=2)
        res = service.search(flt)
        assert res.total == 5
        assert res.has_more is True
        assert len(res.items) == 2

    def test_repository_search_by_filters(self, service: RecommendationService) -> None:
        from app.schemas.recommendations import Recommendation

        service.store.add(
            Recommendation(
                title="a",
                description="d",
                recommendation_type=RecommendationType.POLICY,
                priority=RecommendationPriority.P0,
                document_id="D1",
            )
        )
        service.store.add(
            Recommendation(
                title="b",
                description="d",
                recommendation_type=RecommendationType.OPERATIONAL,
                priority=RecommendationPriority.P3,
                document_id="D2",
            )
        )
        flt = RecommendationFilter(
            document_id="D1",
            recommendation_type=RecommendationType.POLICY,
        )
        res = service.search(flt)
        assert res.total == 1
        assert res.items[0].document_id == "D1"

    def test_repository_stats(self, service: RecommendationService) -> None:
        from app.schemas.recommendations import Recommendation

        for _ in range(3):
            service.store.add(
                Recommendation(
                    title="t",
                    description="d",
                    recommendation_type=RecommendationType.COMPLIANCE,
                    priority=RecommendationPriority.P2,
                )
            )
        stats = service.stats()
        assert stats.total_recommendations == 3
        assert stats.average_confidence > 0
        assert stats.by_type.get("compliance") == 3


# ─── Service ──────────────────────────────────────────────────────


class TestRecommendationService:
    def test_generate_persists_recs(self, service: RecommendationService) -> None:
        req = RecommendationRequest(
            document_id="DOC9",
            max_recommendations=2,
        )
        recs = service.generate(req)
        assert recs
        for r in recs:
            assert service.store.get(r.recommendation_id) is r

    def test_feedback_updates_status(self, service: RecommendationService) -> None:
        recs = service.generate(
            RecommendationRequest(document_id="D1", max_recommendations=1)
        )
        rid = recs[0].recommendation_id
        rec = (
            service.feedback(
                rid,
                type(recs[0]).__fields_set__
                and type(recs[0])(
                    **{**recs[0].model_dump(), "status": ActionStatus.ACCEPTED}
                ),
            )
            if False
            else None
        )
        # Simpler:
        from app.schemas.recommendations import RecommendationFeedback

        rec = service.feedback(
            rid,
            RecommendationFeedback(status=ActionStatus.ACCEPTED, feedback="ok"),
        )
        assert rec is not None
        assert rec.status == ActionStatus.ACCEPTED
        assert rec.accepted_at is not None

    def test_feedback_returns_none_for_missing(
        self, service: RecommendationService
    ) -> None:
        from app.schemas.recommendations import RecommendationFeedback

        rec = service.feedback(
            "missing",
            RecommendationFeedback(status=ActionStatus.REJECTED, feedback=""),
        )
        assert rec is None

    def test_get_returns_none_for_missing(self, service: RecommendationService) -> None:
        assert service.get("missing") is None


# ─── API ──────────────────────────────────────────────────────────


class TestRecommendationAPI:
    @pytest.mark.asyncio
    async def test_health(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/recommendations/health")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "ok"
            assert "metrics" in body

    @pytest.mark.asyncio
    async def test_generate_then_get(self) -> None:
        from app.services.recommendations import (
            InMemoryRecommendationStore,
            RecommendationService,
        )

        svc = RecommendationService(store=InMemoryRecommendationStore())
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/api/v1/recommendations/generate",
                json={"document_id": "DOC-API", "max_recommendations": 2},
            )
            assert r.status_code == 201, r.text
            recs = r.json()
            assert len(recs) >= 1
            rid = recs[0]["recommendation_id"]
            g = await client.get(f"/api/v1/recommendations/{rid}")
            assert g.status_code == 200
            assert g.json()["recommendation_id"] == rid

    @pytest.mark.asyncio
    async def test_get_missing_404(self) -> None:
        _override(RecommendationService(store=InMemoryRecommendationStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/recommendations/nope")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_list_pagination(self) -> None:
        _override(RecommendationService(store=InMemoryRecommendationStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/recommendations?page=1&page_size=5")
            assert r.status_code == 200
            body = r.json()
            assert "items" in body
            assert "total" in body

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        _override(RecommendationService(store=InMemoryRecommendationStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/recommendations/stats")
            assert r.status_code == 200
            body = r.json()
            assert "total_recommendations" in body

    @pytest.mark.asyncio
    async def test_accept_reject_complete(self) -> None:
        from app.schemas.recommendations import Recommendation

        store = InMemoryRecommendationStore()
        svc = RecommendationService(store=store)
        rec = Recommendation(
            title="t",
            description="d",
            recommendation_type=RecommendationType.COMPLIANCE,
            priority=RecommendationPriority.P2,
        )
        store.add(rec)
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            a = await client.post(
                f"/api/v1/recommendations/{rec.recommendation_id}/accept"
            )
            assert a.status_code == 200
            assert a.json()["status"] == ActionStatus.ACCEPTED.value
            s = await client.post(
                f"/api/v1/recommendations/{rec.recommendation_id}/start"
            )
            assert s.status_code == 200
            assert s.json()["status"] == ActionStatus.IN_PROGRESS.value
            c = await client.post(
                f"/api/v1/recommendations/{rec.recommendation_id}/complete"
            )
            assert c.status_code == 200
            assert c.json()["status"] == ActionStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_reject(self) -> None:
        from app.schemas.recommendations import Recommendation

        store = InMemoryRecommendationStore()
        svc = RecommendationService(store=store)
        rec = Recommendation(
            title="t",
            description="d",
            recommendation_type=RecommendationType.COMPLIANCE,
            priority=RecommendationPriority.P2,
        )
        store.add(rec)
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/api/v1/recommendations/{rec.recommendation_id}/reject?feedback=not+useful"
            )
            assert r.status_code == 200
            assert r.json()["status"] == ActionStatus.REJECTED.value

    @pytest.mark.asyncio
    async def test_feedback_endpoint(self) -> None:
        from app.schemas.recommendations import Recommendation

        store = InMemoryRecommendationStore()
        svc = RecommendationService(store=store)
        rec = Recommendation(
            title="t",
            description="d",
            recommendation_type=RecommendationType.COMPLIANCE,
            priority=RecommendationPriority.P2,
        )
        store.add(rec)
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/api/v1/recommendations/{rec.recommendation_id}/feedback",
                json={"status": "accepted", "feedback": "ok"},
            )
            assert r.status_code == 200
            assert r.json()["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_feedback_missing_404(self) -> None:
        _override(RecommendationService(store=InMemoryRecommendationStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/api/v1/recommendations/missing/feedback",
                json={"status": "accepted", "feedback": "x"},
            )
            assert r.status_code == 404
