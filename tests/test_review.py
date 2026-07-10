"""Tests for Module 8.5 — Human-in-the-Loop Review."""

from __future__ import annotations


import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.review import (
    ApprovalRequirement,
    ReviewCreateRequest,
    ReviewDecision,
    ReviewDecisionRequest,
    ReviewFilter,
    ReviewPriority,
    ReviewStatus,
)
from app.services.review import (
    ApprovalCoordinator,
    InMemoryReviewStore,
    ReviewEngine,
    ReviewManager,
    ReviewService,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    from app.api import dependencies as deps

    deps.reset_review_service()
    deps.reset_automation_service()
    yield
    deps.reset_review_service()
    deps.reset_automation_service()


@pytest.fixture
def store() -> InMemoryReviewStore:
    return InMemoryReviewStore()


@pytest.fixture
def service(store: InMemoryReviewStore) -> ReviewService:
    return ReviewService(store=store)


def _override(svc: ReviewService):
    from app.api.dependencies import get_review_service

    app.dependency_overrides[get_review_service] = lambda: svc
    return svc


def _make_request(
    title: str = "Review-1",
    subject_type: str = "document",
    subject_id: str = "DOC-1",
    assigned_to: str = "alice",
    assigned_role: str = "reviewer",
    priority: ReviewPriority = ReviewPriority.MEDIUM,
    required_approvers: list | None = None,
) -> ReviewCreateRequest:
    return ReviewCreateRequest(
        title=title,
        description="test review",
        subject_type=subject_type,
        subject_id=subject_id,
        assigned_to=assigned_to,
        assigned_role=assigned_role,
        priority=priority,
        required_approvers=required_approvers or [],
    )


# ─── ReviewEngine ────────────────────────────────────────────────


class TestReviewEngine:
    def test_create_with_default_requirement(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        assert review.status == ReviewStatus.PENDING
        assert review.review_id.startswith("rev-")
        assert len(review.required_approvers) == 1
        assert review.required_approvers[0].min_approvals == 1

    def test_create_with_explicit_requirements(self) -> None:
        eng = ReviewEngine()
        reqs = [
            ApprovalRequirement(approver_role="risk_manager", min_approvals=2),
            ApprovalRequirement(approver_role="compliance_head", min_approvals=1),
        ]
        review = eng.create(_make_request(required_approvers=reqs))
        assert len(review.required_approvers) == 2

    def test_start(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        eng.start(review, "alice")
        assert review.status == ReviewStatus.IN_REVIEW
        assert review.started_at is not None

    def test_complete_approved(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        eng.start(review, "alice")
        eng.complete(review, ReviewDecision.APPROVED, "alice")
        assert review.status == ReviewStatus.APPROVED

    def test_complete_rejected(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        eng.start(review, "alice")
        eng.complete(review, ReviewDecision.REJECTED, "alice")
        assert review.status == ReviewStatus.REJECTED

    def test_escalate(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        eng.start(review, "alice")
        eng.escalate(review, "alice", reason="timeout")
        assert review.status == ReviewStatus.ESCALATED

    def test_withdraw(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        eng.withdraw(review, "alice")
        assert review.status == ReviewStatus.WITHDRAWN

    def test_is_terminal(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        eng.start(review)
        eng.complete(review, ReviewDecision.APPROVED, "alice")
        assert eng.is_terminal(review) is True


# ─── ReviewManager ──────────────────────────────────────────────


class TestReviewManager:
    def test_assign(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        mgr = ReviewManager()
        mgr.assign(review, "bob", "compliance_officer", "system")
        assert review.assigned_to == "bob"
        assert review.assigned_role == "compliance_officer"
        assert review.assigned_at is not None

    def test_add_comment(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        mgr = ReviewManager()
        c = mgr.add_comment(review, "alice", "Looks good", "reviewer")
        assert c in review.comments
        assert c.author == "alice"

    def test_add_comment_empty(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        mgr = ReviewManager()
        with pytest.raises(ValueError):
            mgr.add_comment(review, "alice", "", "reviewer")

    def test_add_correction(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        mgr = ReviewManager()
        c = mgr.add_correction(
            review,
            field="policy_id",
            original_value="P-1",
            corrected_value="P-2",
            reason="wrong reference",
            corrected_by="alice",
        )
        assert c in review.corrections
        assert c.corrected_by == "alice"


# ─── ApprovalCoordinator ────────────────────────────────────────


class TestApprovalCoordinator:
    def test_single_approver_full_approval(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        coord = ApprovalCoordinator()
        coord.record_approval(review, "alice", "reviewer")
        state = coord.evaluate(review)
        assert state["fully_approved"] is True
        assert state["pending_approvals"] == 0

    def test_multi_approver_need_all(self) -> None:
        eng = ReviewEngine()
        review = eng.create(
            _make_request(
                required_approvers=[
                    ApprovalRequirement(approver_role="risk_manager", min_approvals=1),
                    ApprovalRequirement(
                        approver_role="compliance_head", min_approvals=1
                    ),
                ]
            )
        )
        coord = ApprovalCoordinator()
        coord.record_approval(review, "alice", "risk_manager")
        state = coord.evaluate(review)
        assert state["fully_approved"] is False
        assert state["pending_approvals"] == 1
        coord.record_approval(review, "bob", "compliance_head")
        state = coord.evaluate(review)
        assert state["fully_approved"] is True

    def test_rejection_blocks(self) -> None:
        eng = ReviewEngine()
        review = eng.create(_make_request())
        coord = ApprovalCoordinator()
        coord.record_rejection(review, "alice", "no", "reviewer")
        state = coord.evaluate(review)
        assert state["rejected"] is True
        assert state["fully_approved"] is False

    def test_min_approvals(self) -> None:
        eng = ReviewEngine()
        review = eng.create(
            _make_request(
                required_approvers=[
                    ApprovalRequirement(approver_role="risk_manager", min_approvals=2)
                ]
            )
        )
        coord = ApprovalCoordinator()
        coord.record_approval(review, "alice", "risk_manager")
        state = coord.evaluate(review)
        assert state["fully_approved"] is False
        coord.record_approval(review, "bob", "risk_manager")
        state = coord.evaluate(review)
        assert state["fully_approved"] is True


# ─── Repository / Stats ─────────────────────────────────────────


class TestRepository:
    def test_search(self, service: ReviewService) -> None:
        service.create(_make_request(title="A", assigned_to="alice"))
        service.create(_make_request(title="B", assigned_to="bob"))
        flt = ReviewFilter(assigned_to="alice")
        res = service.search(flt)
        assert res.total == 1
        assert res.items[0].title == "A"

    def test_stats(self, service: ReviewService) -> None:
        r1 = service.create(_make_request())
        r2 = service.create(_make_request())
        service.start(r1.review_id, "alice")
        service.engine.complete(r1, ReviewDecision.APPROVED, "alice")
        service.start(r2.review_id, "alice")
        service.engine.complete(r2, ReviewDecision.REJECTED, "alice")
        stats = service.stats()
        assert stats.approved == 1
        assert stats.rejected == 1
        assert stats.approval_rate == 0.5

    def test_queue_for(self, service: ReviewService) -> None:
        service.create(_make_request(assigned_to="alice"))
        service.create(_make_request(assigned_to="bob"))
        q = service.queue_for("alice")
        assert len(q) == 1
        assert q[0].status in (ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)


# ─── Service ────────────────────────────────────────────────────


class TestReviewService:
    def test_decide_approve_consensus(self, service: ReviewService) -> None:
        r = service.create(_make_request())
        service.start(r.review_id, "alice")
        result = service.decide(
            r.review_id,
            ReviewDecisionRequest(
                decision=ReviewDecision.APPROVED,
                approver_role="reviewer",
                comment_text="LGTM",
            ),
            actor="alice",
        )
        assert result is not None
        assert result.status == ReviewStatus.APPROVED
        assert result.comments

    def test_decide_reject(self, service: ReviewService) -> None:
        r = service.create(_make_request())
        service.start(r.review_id, "alice")
        result = service.decide(
            r.review_id,
            ReviewDecisionRequest(
                decision=ReviewDecision.REJECTED,
                approver_role="reviewer",
                reason="Bad",
            ),
            actor="alice",
        )
        assert result.status == ReviewStatus.REJECTED

    def test_decide_needs_changes(self, service: ReviewService) -> None:
        r = service.create(_make_request())
        service.start(r.review_id, "alice")
        result = service.decide(
            r.review_id,
            ReviewDecisionRequest(
                decision=ReviewDecision.NEEDS_CHANGES,
                reason="fix typos",
            ),
            actor="alice",
        )
        assert result.decision == ReviewDecision.NEEDS_CHANGES

    def test_decide_with_corrections(self, service: ReviewService) -> None:
        r = service.create(_make_request())
        service.start(r.review_id, "alice")
        result = service.decide(
            r.review_id,
            ReviewDecisionRequest(
                decision=ReviewDecision.APPROVED,
                approver_role="reviewer",
                corrections=[
                    {
                        "field": "x",
                        "original_value": "a",
                        "corrected_value": "b",
                        "reason": "typo",
                    }
                ],
            ),
            actor="alice",
        )
        assert len(result.corrections) == 1

    def test_decide_unknown(self, service: ReviewService) -> None:
        assert (
            service.decide(
                "missing",
                ReviewDecisionRequest(
                    decision=ReviewDecision.APPROVED,
                ),
            )
            is None
        )

    def test_get_missing(self, service: ReviewService) -> None:
        assert service.get("missing") is None

    def test_create_for_workflow(self, service: ReviewService) -> None:
        # The review service's cross-module integration uses
        # build_default_automation_service(). We override that
        # builder via module-level monkey-patch so it returns
        # our test's workflow service (sharing the same store).
        from app.services import workflow as wf_mod
        from app.services.workflow import (
            AutomationService,
            InMemoryWorkflowStore,
        )
        from app.schemas.workflow import (
            WorkflowCreateRequest,
            WorkflowType,
        )

        wf_store = InMemoryWorkflowStore()
        wf_svc = AutomationService(store=wf_store)
        wf = wf_svc.create(
            WorkflowCreateRequest(
                name="x",
                description="y",
                workflow_type=WorkflowType.COMPLIANCE_REVIEW,
                created_by="t",
            )
        )
        original = wf_mod.build_default_automation_service
        wf_mod.build_default_automation_service = lambda: wf_svc
        try:
            r = service.create_for_workflow(wf.workflow_id, "tester")
        finally:
            wf_mod.build_default_automation_service = original
        assert r is not None
        assert r.workflow_id == wf.workflow_id

    def test_create_for_workflow_missing(self, service: ReviewService) -> None:
        r = service.create_for_workflow("missing-id", "tester")
        assert r is None


# ─── API ────────────────────────────────────────────────────────


class TestReviewAPI:
    @pytest.mark.asyncio
    async def test_health(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/review/health")
            assert r.status_code == 200
            assert r.json()["module"] == "review"

    @pytest.mark.asyncio
    async def test_create_and_get(self) -> None:
        _override(ReviewService(store=InMemoryReviewStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/api/v1/review/create",
                json={
                    "title": "API review",
                    "description": "x",
                    "subject_type": "document",
                    "subject_id": "DOC-1",
                    "assigned_to": "alice",
                    "assigned_role": "reviewer",
                },
            )
            assert r.status_code == 201, r.text
            rid = r.json()["review_id"]
            g = await client.get(f"/api/v1/review/{rid}")
            assert g.status_code == 200
            assert g.json()["review_id"] == rid

    @pytest.mark.asyncio
    async def test_lifecycle(self) -> None:
        svc = ReviewService(store=InMemoryReviewStore())
        r = svc.create(_make_request())
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            s = await client.post(f"/api/v1/review/{r.review_id}/start?actor=alice")
            assert s.json()["status"] == "in_review"
            a = await client.post(f"/api/v1/review/{r.review_id}/approve?actor=alice")
            assert a.json()["status"] == "approved"
            w = await client.get(f"/api/v1/review/{r.review_id}")
            assert w.json()["status"] == "approved"

    @pytest.mark.asyncio
    async def test_reject(self) -> None:
        svc = ReviewService(store=InMemoryReviewStore())
        r = svc.create(_make_request())
        svc.start(r.review_id, "alice")
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.post(
                f"/api/v1/review/{r.review_id}/reject?actor=alice&reason=bad"
            )
            assert res.status_code == 200
            assert res.json()["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_comment_and_correction(self) -> None:
        svc = ReviewService(store=InMemoryReviewStore())
        r = svc.create(_make_request())
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            c = await client.post(
                f"/api/v1/review/{r.review_id}/comment",
                json={"author": "alice", "text": "hi", "role": "reviewer"},
            )
            assert c.status_code == 201
            cid = c.json()["comment_id"]
            cr = await client.post(
                f"/api/v1/review/{r.review_id}/correction",
                json={
                    "field": "x",
                    "original_value": "a",
                    "corrected_value": "b",
                    "reason": "typo",
                    "corrected_by": "alice",
                },
            )
            assert cr.status_code == 201
            assert cr.json()["field"] == "x"

    @pytest.mark.asyncio
    async def test_audit_and_history(self) -> None:
        svc = ReviewService(store=InMemoryReviewStore())
        r = svc.create(_make_request())
        svc.add_comment(r.review_id, "hi", "alice", "reviewer")
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            a = await client.get(f"/api/v1/review/{r.review_id}/audit")
            assert a.status_code == 200
            assert isinstance(a.json(), list)
            h = await client.get(f"/api/v1/review/{r.review_id}/history")
            assert h.json()["review_id"] == r.review_id
            assert h.json()["comments"]

    @pytest.mark.asyncio
    async def test_queue(self) -> None:
        svc = ReviewService(store=InMemoryReviewStore())
        svc.create(_make_request(assigned_to="alice"))
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/review/queue/alice")
            assert r.status_code == 200
            assert len(r.json()) == 1

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        svc = ReviewService(store=InMemoryReviewStore())
        svc.create(_make_request())
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/review/stats")
            assert r.status_code == 200
            assert r.json()["total_reviews"] >= 1

    @pytest.mark.asyncio
    async def test_list_and_get_404(self) -> None:
        _override(ReviewService(store=InMemoryReviewStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/review?page=1&page_size=10")
            assert r.status_code == 200
            assert "items" in r.json()
            r2 = await client.get("/api/v1/review/missing")
            assert r2.status_code == 404

    @pytest.mark.asyncio
    async def test_approval_consensus(self) -> None:
        svc = ReviewService(store=InMemoryReviewStore())
        r = svc.create(
            _make_request(
                required_approvers=[
                    ApprovalRequirement(approver_role="risk_manager", min_approvals=1),
                    ApprovalRequirement(
                        approver_role="compliance_head", min_approvals=1
                    ),
                ]
            )
        )
        svc.start(r.review_id, "alice")
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            a1 = await client.post(
                f"/api/v1/review/{r.review_id}/approvals/alice/approve?role=risk_manager"
            )
            assert a1.json()["status"] == "in_review"
            a2 = await client.post(
                f"/api/v1/review/{r.review_id}/approvals/bob/approve?role=compliance_head"
            )
            assert a2.json()["status"] == "approved"

    @pytest.mark.asyncio
    async def test_assign_endpoint(self) -> None:
        svc = ReviewService(store=InMemoryReviewStore())
        r = svc.create(_make_request())
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.post(
                f"/api/v1/review/{r.review_id}/assign",
                json={"assigned_to": "bob", "assigned_role": "compliance"},
            )
            assert res.status_code == 200
            assert res.json()["assigned_to"] == "bob"

    @pytest.mark.asyncio
    async def test_from_workflow(self) -> None:
        from app.services import workflow as wf_mod
        from app.services.workflow import (
            AutomationService,
            InMemoryWorkflowStore,
        )
        from app.schemas.workflow import (
            WorkflowCreateRequest,
            WorkflowType,
        )

        wf_store = InMemoryWorkflowStore()
        wf_svc = AutomationService(store=wf_store)
        wf = wf_svc.create(
            WorkflowCreateRequest(
                name="x",
                description="y",
                workflow_type=WorkflowType.COMPLIANCE_REVIEW,
                created_by="t",
            )
        )
        original = wf_mod.build_default_automation_service
        wf_mod.build_default_automation_service = lambda: wf_svc
        try:
            _override(ReviewService(store=InMemoryReviewStore()))
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                res = await client.post(
                    f"/api/v1/review/from-workflow/{wf.workflow_id}"
                )
                assert res.status_code == 201, res.text
                assert res.json()["workflow_id"] == wf.workflow_id
        finally:
            wf_mod.build_default_automation_service = original

    @pytest.mark.asyncio
    async def test_from_workflow_404(self) -> None:
        _override(ReviewService(store=InMemoryReviewStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            res = await client.post("/api/v1/review/from-workflow/missing")
            assert res.status_code == 404
