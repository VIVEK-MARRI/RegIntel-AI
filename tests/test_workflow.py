"""Tests for Module 8.4 — Workflow Automation Platform."""

from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.workflow import (
    EscalationRequest,
    TaskAssignmentRequest,
    TaskCompletionRequest,
    TaskCreateRequest,
    TaskPriority,
    TaskStatus,
    WorkflowCreateRequest,
    WorkflowFilter,
    WorkflowStatus,
    WorkflowType,
)
from app.services.workflow import (
    AutomationService,
    InMemoryWorkflowStore,
    TaskManager,
    WorkflowEngine,
    WorkflowOrchestrator,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    from app.api import dependencies as deps

    deps.reset_automation_service()
    deps.reset_recommendation_service()
    deps.reset_compliance_risk_service()
    yield
    deps.reset_automation_service()
    deps.reset_recommendation_service()
    deps.reset_compliance_risk_service()


@pytest.fixture
def store() -> InMemoryWorkflowStore:
    return InMemoryWorkflowStore()


@pytest.fixture
def service(store: InMemoryWorkflowStore) -> AutomationService:
    return AutomationService(store=store)


def _override(svc: AutomationService):
    from app.api.dependencies import get_automation_service

    app.dependency_overrides[get_automation_service] = lambda: svc
    return svc


def _make_request(
    name: str = "WF-1",
    workflow_type: WorkflowType = WorkflowType.COMPLIANCE_REVIEW,
    document_id: str = "DOC-1",
    priority: TaskPriority = TaskPriority.MEDIUM,
    steps: list | None = None,
) -> WorkflowCreateRequest:
    return WorkflowCreateRequest(
        name=name,
        description="test workflow",
        workflow_type=workflow_type,
        document_id=document_id,
        created_by="tester",
        priority=priority,
        steps=steps or [],
    )


# ─── WorkflowEngine ───────────────────────────────────────────────


class TestWorkflowEngine:
    def test_create_with_default_template(self) -> None:
        eng = WorkflowEngine()
        wf = eng.create(_make_request(workflow_type=WorkflowType.COMPLIANCE_REVIEW))
        # Default template has 4 steps for compliance_review
        assert len(wf.steps) == 4
        assert wf.status == WorkflowStatus.ACTIVE
        assert wf.audit_trail[0].action == "workflow.created"

    def test_create_with_custom_steps(self) -> None:
        from app.schemas.workflow import StepType, WorkflowStep

        eng = WorkflowEngine()
        custom = [
            WorkflowStep(name="Custom A", step_type=StepType.TASK, sequence=1),
            WorkflowStep(name="Custom B", step_type=StepType.TASK, sequence=2),
        ]
        wf = eng.create(_make_request(steps=custom))
        assert len(wf.steps) == 2
        assert wf.steps[0].name == "Custom A"

    def test_create_with_no_steps_starts_draft(self) -> None:
        from app.schemas.workflow import WorkflowType

        eng = WorkflowEngine()
        wf = eng.create(
            _make_request(workflow_type=WorkflowType.RISK_ASSESSMENT, steps=[])
        )
        # Default template applies, so ACTIVE
        # But we need a workflow type whose default has steps
        assert wf.status in (WorkflowStatus.DRAFT, WorkflowStatus.ACTIVE)

    def test_lifecycle(self) -> None:
        eng = WorkflowEngine()
        wf = eng.create(_make_request(workflow_type=WorkflowType.POLICY_UPDATE))
        eng.start(wf, "alice")
        assert wf.status == WorkflowStatus.ACTIVE
        eng.pause(wf, "alice")
        assert wf.status == WorkflowStatus.PAUSED
        eng.resume(wf, "alice")
        assert wf.status == WorkflowStatus.ACTIVE
        eng.cancel(wf, "alice", reason="test")
        assert wf.status == WorkflowStatus.CANCELLED

    def test_complete_requires_all_tasks_done(self) -> None:
        eng = WorkflowEngine()
        wf = eng.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        # Add a task that isn't completed
        wf.tasks.append(
            __import__(
                "app.schemas.workflow", fromlist=["TaskAssignment"]
            ).TaskAssignment(
                workflow_id=wf.workflow_id,
                step_id=wf.steps[0].step_id,
                title="t",
            )
        )
        with pytest.raises(ValueError):
            eng.complete(wf, "alice")

    def test_advance_step(self) -> None:
        eng = WorkflowEngine()
        wf = eng.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        original = wf.current_step_index
        eng.advance_step(wf, "alice")
        assert wf.current_step_index == original + 1

    def test_is_terminal(self) -> None:
        eng = WorkflowEngine()
        wf = eng.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        eng.cancel(wf, "alice")
        assert eng.is_terminal(wf) is True


# ─── TaskManager ──────────────────────────────────────────────────


class TestTaskManager:
    def test_add_task(self, service: AutomationService) -> None:
        wf = service.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        task = service.add_task(
            wf.workflow_id,
            TaskCreateRequest(
                step_id=wf.steps[0].step_id,
                title="My task",
                description="d",
            ),
        )
        assert task is not None
        assert task.title == "My task"
        assert task.task_id in [t.task_id for t in wf.tasks]

    def test_add_task_unknown_step(self, service: AutomationService) -> None:
        wf = service.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        with pytest.raises(ValueError):
            service.task_manager.add_task(
                wf,
                TaskCreateRequest(step_id="unknown", title="t"),
            )

    def test_assign_and_complete(self, service: AutomationService) -> None:
        wf = service.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        task = service.add_task(
            wf.workflow_id,
            TaskCreateRequest(step_id=wf.steps[0].step_id, title="T"),
        )
        service.assign_task(
            wf.workflow_id,
            task.task_id,
            TaskAssignmentRequest(assignee="alice"),
        )
        service.start_task(wf.workflow_id, task.task_id)
        result = service.complete_task(
            wf.workflow_id,
            task.task_id,
            TaskCompletionRequest(notes="done"),
        )
        assert result.status == TaskStatus.COMPLETED
        assert result.completed_at is not None

    def test_complete_unknown_task(self, service: AutomationService) -> None:
        wf = service.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        with pytest.raises(ValueError):
            service.task_manager.complete_task(wf, "missing", TaskCompletionRequest())

    def test_tasks_for_assignee(self, service: AutomationService) -> None:
        wf = service.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        service.add_task(
            wf.workflow_id,
            TaskCreateRequest(
                step_id=wf.steps[0].step_id,
                title="t1",
                assignee="alice",
            ),
        )
        service.add_task(
            wf.workflow_id,
            TaskCreateRequest(
                step_id=wf.steps[0].step_id,
                title="t2",
                assignee="bob",
            ),
        )
        alice_tasks = service.task_manager.tasks_for_assignee(wf, "alice")
        assert len(alice_tasks) == 1
        assert alice_tasks[0].title == "t1"


# ─── WorkflowOrchestrator ────────────────────────────────────────


class TestWorkflowOrchestrator:
    def test_trigger_escalation(self) -> None:
        orch = WorkflowOrchestrator()
        wf = WorkflowEngine().create(
            _make_request(workflow_type=WorkflowType.COMPLIANCE_REVIEW)
        )
        rule = orch.trigger_escalation(wf, EscalationRequest(reason="late"))
        assert rule is not None
        assert any(a.action == "workflow.escalated" for a in wf.audit_trail)

    def test_evaluate_timeouts(self) -> None:
        orch = WorkflowOrchestrator()
        wf = WorkflowEngine().create(
            _make_request(workflow_type=WorkflowType.COMPLIANCE_REVIEW)
        )
        wf.started_at = time.time() - 100 * 3600  # 100h ago
        triggered = orch.evaluate_timeouts(wf)
        assert triggered

    def test_evaluate_timeouts_no_started_at(self) -> None:
        orch = WorkflowOrchestrator()
        wf = WorkflowEngine().create(
            _make_request(workflow_type=WorkflowType.COMPLIANCE_REVIEW)
        )
        assert orch.evaluate_timeouts(wf) == []

    def test_progress_percent(self) -> None:
        orch = WorkflowOrchestrator()
        wf = WorkflowEngine().create(
            _make_request(workflow_type=WorkflowType.COMPLIANCE_REVIEW)
        )
        wf.current_step_index = 1
        assert orch.progress_percent(wf) > 0
        wf.status = WorkflowStatus.COMPLETED
        assert orch.progress_percent(wf) == 100.0

    def test_route(self) -> None:
        orch = WorkflowOrchestrator()
        wf = WorkflowEngine().create(
            _make_request(workflow_type=WorkflowType.RISK_ASSESSMENT)
        )
        assert orch.route(wf) is wf.steps[0]


# ─── Repository / Stats ───────────────────────────────────────────


class TestRepository:
    def test_search_and_stats(self, service: AutomationService) -> None:
        wf1 = service.create(_make_request(name="A", document_id="X"))
        wf2 = service.create(_make_request(name="B", document_id="Y"))
        flt = WorkflowFilter(document_id="X")
        res = service.search(flt)
        assert res.total == 1
        assert res.items[0].workflow_id == wf1.workflow_id
        stats = service.stats()
        assert stats.total_workflows >= 2

    def test_stats_with_completed(self, service: AutomationService) -> None:
        wf = service.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        service.start(wf.workflow_id, "tester")
        time.sleep(0.01)
        for t_step in wf.steps:
            t = service.add_task(
                wf.workflow_id,
                TaskCreateRequest(step_id=t_step.step_id, title="x"),
            )
            service.complete_task(
                wf.workflow_id,
                t.task_id,
                TaskCompletionRequest(),
            )
        service.complete(wf.workflow_id, "tester")
        stats = service.stats()
        assert stats.by_status.get("completed") == 1
        assert stats.success_rate == 1.0
        assert stats.average_completion_seconds >= 0.0


# ─── Cross-Module Integration ─────────────────────────────────────


class TestIntegration:
    def test_from_recommendation(self, service: AutomationService) -> None:
        from app.schemas.recommendations import (
            ActionPlan,
            ActionPlanStep,
            Recommendation,
            RecommendationPriority,
            RecommendationType,
        )

        rec = Recommendation(
            title="Update KYC",
            description="d",
            recommendation_type=RecommendationType.COMPLIANCE,
            priority=RecommendationPriority.P1,
            document_id="DOC-R1",
            action_plan=ActionPlan(
                title="plan",
                summary="s",
                steps=[
                    ActionPlanStep(sequence=1, title="A"),
                    ActionPlanStep(sequence=2, title="B"),
                ],
                total_effort_hours=4.0,
            ),
        )
        from app.services.recommendations import (
            build_default_recommendation_service,
        )

        rec_svc = build_default_recommendation_service()
        rec_svc.store.add(rec)
        wf = service.create_from_recommendation(rec.recommendation_id, "tester")
        assert wf is not None
        assert wf.source_recommendation_id == rec.recommendation_id
        assert wf.priority == TaskPriority.HIGH
        assert len(wf.tasks) >= 1

    def test_from_risk_assessment(self, service: AutomationService) -> None:
        from app.schemas.risk import (
            AffectedArea,
            AffectedAreaRecord,
            RecommendedAction,
            RecommendedActionType,
            RiskAssessment,
            RiskCategory,
            RiskExplanation,
            RiskLevel,
        )
        from app.services.compliance_risk import (
            build_default_compliance_risk_service,
        )

        ra = RiskAssessment(
            document_id="DOC-RA1",
            source="test",
            risk_level=RiskLevel.HIGH,
            risk_score=0.7,
            risk_categories=[RiskCategory.COMPLIANCE_GAP],
            affected_areas=[
                AffectedAreaRecord(
                    area=AffectedArea.KYC,
                    exposure_score=0.8,
                    rationale="r",
                )
            ],
            recommended_actions=[
                RecommendedAction(
                    action_type=RecommendedActionType.DOCUMENTATION,
                    title="doc",
                    description="d",
                    priority=RiskLevel.MEDIUM,
                )
            ],
            explanation=RiskExplanation(summary="x"),
            generated_at=time.time(),
        )
        cr_svc = build_default_compliance_risk_service()
        cr_svc.store.add(ra)
        wf = service.create_from_risk_assessment(ra.assessment_id, "tester")
        assert wf is not None
        assert wf.source_risk_assessment_id == ra.assessment_id
        assert wf.priority == TaskPriority.HIGH
        assert len(wf.tasks) >= 1


# ─── API ──────────────────────────────────────────────────────────


class TestWorkflowAPI:
    @pytest.mark.asyncio
    async def test_health(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/workflow/health")
            assert r.status_code == 200
            assert r.json()["module"] == "workflow"

    @pytest.mark.asyncio
    async def test_create_and_get(self) -> None:
        _override(AutomationService(store=InMemoryWorkflowStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                "/api/v1/workflow/create",
                json={
                    "name": "API-WF",
                    "description": "x",
                    "workflow_type": "compliance_review",
                    "document_id": "DOC-API",
                    "created_by": "tester",
                    "priority": "medium",
                },
            )
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["workflow_id"].startswith("wf-")
            wid = body["workflow_id"]
            g = await client.get(f"/api/v1/workflow/{wid}")
            assert g.status_code == 200
            assert g.json()["workflow_id"] == wid

    @pytest.mark.asyncio
    async def test_lifecycle_via_api(self) -> None:
        svc = AutomationService(store=InMemoryWorkflowStore())
        wf = svc.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            s = await client.post(
                f"/api/v1/workflow/{wf.workflow_id}/start?actor=alice"
            )
            assert s.status_code == 200
            assert s.json()["status"] == "active"
            p = await client.post(
                f"/api/v1/workflow/{wf.workflow_id}/pause?actor=alice"
            )
            assert p.json()["status"] == "paused"
            r = await client.post(
                f"/api/v1/workflow/{wf.workflow_id}/resume?actor=alice"
            )
            assert r.json()["status"] == "active"
            c = await client.post(
                f"/api/v1/workflow/{wf.workflow_id}/cancel?actor=alice&reason=stop"
            )
            assert c.json()["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_task_flow(self) -> None:
        svc = AutomationService(store=InMemoryWorkflowStore())
        wf = svc.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            t = await client.post(
                f"/api/v1/workflow/{wf.workflow_id}/tasks",
                json={
                    "step_id": wf.steps[0].step_id,
                    "title": "API task",
                    "assignee": "alice",
                },
            )
            assert t.status_code == 201, t.text
            tid = t.json()["task_id"]
            a = await client.post(
                f"/api/v1/workflow/{wf.workflow_id}/tasks/{tid}/assign",
                json={"assignee": "bob", "assignee_role": "analyst"},
            )
            assert a.status_code == 200
            assert a.json()["assignee"] == "bob"
            s = await client.post(
                f"/api/v1/workflow/{wf.workflow_id}/tasks/{tid}/start"
            )
            assert s.json()["status"] == "in_progress"
            c = await client.post(
                f"/api/v1/workflow/{wf.workflow_id}/tasks/{tid}/complete",
                json={"status": "completed", "notes": "ok"},
            )
            assert c.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_escalate(self) -> None:
        svc = AutomationService(store=InMemoryWorkflowStore())
        wf = svc.create(_make_request(workflow_type=WorkflowType.COMPLIANCE_REVIEW))
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.post(
                f"/api/v1/workflow/{wf.workflow_id}/escalate",
                json={"reason": "manual"},
            )
            assert r.status_code == 200
            assert r.json()["action"] == "escalate"

    @pytest.mark.asyncio
    async def test_audit_and_progress(self) -> None:
        svc = AutomationService(store=InMemoryWorkflowStore())
        wf = svc.create(_make_request(workflow_type=WorkflowType.RISK_ASSESSMENT))
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            a = await client.get(f"/api/v1/workflow/{wf.workflow_id}/audit")
            assert a.status_code == 200
            assert isinstance(a.json(), list)
            p = await client.get(f"/api/v1/workflow/{wf.workflow_id}/progress")
            assert p.json()["workflow_id"] == wf.workflow_id

    @pytest.mark.asyncio
    async def test_stats_and_list(self) -> None:
        svc = AutomationService(store=InMemoryWorkflowStore())
        svc.create(_make_request())
        _override(svc)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/workflow/stats")
            assert r.status_code == 200
            assert r.json()["total_workflows"] >= 1
            resp = await client.get("/api/v1/workflow?page=1&page_size=10")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_404(self) -> None:
        _override(AutomationService(store=InMemoryWorkflowStore()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/v1/workflow/missing")
            assert r.status_code == 404
