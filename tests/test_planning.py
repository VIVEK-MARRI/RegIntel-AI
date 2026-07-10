"""Tests for Module 6.4 — Query Planning Engine.

Coverage
--------
* Schemas (PlanStepDefinition, ExecutionPlan, PlanStepResult,
  PlanExecutionResult, PlanValidationResult, PlanExplanation,
  QueryPlanRequest, QueryPlanResponse).
* IntentClassifier — keyword-based query type detection.
* TaskDecomposer — per-query-type decomposition.
* StrategySelector — strategy selection.
* PlanValidator — duplicates, missing deps, cycles, sanity checks.
* PlanExplainer — produces human-readable explanations.
* PlanGenerator — composes a complete ExecutionPlan.
* PlanExecutor — runs a plan end-to-end, including topo ordering,
  pre-supplied chunks, dependency failures.
* QueryPlanner — top-level service.
* API integration: /api/v1/planning/* endpoints.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_query_planner,
    reset_query_planner,
)
from app.api.v1.planning import router as planning_router
from app.schemas.planning import (
    ExecutionPlan,
    PlanComplexity,
    PlanStepDefinition,
    PlanStepStatus,
    PlanStepType,
    PlanStrategy,
    QueryPlanRequest,
    QueryType,
)
from app.services.planning import (
    IntentClassifier,
    PlanExecutor,
    PlanExplainer,
    PlanGenerator,
    PlanValidator,
    QueryPlanner,
    StrategySelector,
    TaskDecomposer,
    build_default_query_planner,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_query_planner()
    yield
    reset_query_planner()


@pytest.fixture
def classifier() -> IntentClassifier:
    return IntentClassifier()


@pytest.fixture
def decomposer() -> TaskDecomposer:
    return TaskDecomposer()


@pytest.fixture
def selector() -> StrategySelector:
    return StrategySelector()


@pytest.fixture
def validator() -> PlanValidator:
    return PlanValidator()


@pytest.fixture
def explainer() -> PlanExplainer:
    return PlanExplainer()


@pytest.fixture
def generator() -> PlanGenerator:
    return PlanGenerator()


@pytest.fixture
def executor() -> PlanExecutor:
    return PlanExecutor()


@pytest.fixture
def planner() -> QueryPlanner:
    return build_default_query_planner()


@pytest.fixture
def app():
    reset_query_planner()
    app = FastAPI()
    app.include_router(planning_router, prefix="/api/v1")
    planner = build_default_query_planner()
    app.dependency_overrides[get_query_planner] = lambda: planner
    yield app
    app.dependency_overrides.clear()
    reset_query_planner()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_query_types(self):
        assert QueryType.COMPARISON.value == "comparison"
        assert QueryType.TIMELINE.value == "timeline"
        assert QueryType.REGULATORY_CHANGE.value == "regulatory_change"
        assert QueryType.CROSS_DOCUMENT.value == "cross_document"
        assert QueryType.MULTI_STEP.value == "multi_step"
        assert QueryType.DEFINITION.value == "definition"
        assert QueryType.FACTUAL.value == "factual"
        assert QueryType.PROCEDURAL.value == "procedural"

    def test_plan_step_definition_defaults(self):
        s = PlanStepDefinition(step_type=PlanStepType.RETRIEVE)
        assert s.step_id.startswith("step-")
        assert s.depends_on == []
        assert s.optional is False

    def test_execution_plan_step_lookup(self):
        s1 = PlanStepDefinition(step_type=PlanStepType.RETRIEVE)
        s2 = PlanStepDefinition(step_type=PlanStepType.ANSWER, depends_on=[s1.step_id])
        plan = ExecutionPlan(
            query="x",
            query_type=QueryType.FACTUAL,
            strategy=PlanStrategy.SINGLE_DOC,
            steps=[s1, s2],
        )
        assert plan.get_step(s1.step_id) is s1
        assert plan.get_step("nope") is None
        assert plan.dependents_of(s1.step_id) == [s2]
        assert plan.step_ids() == [s1.step_id, s2.step_id]

    def test_query_plan_request_min_length(self):
        with pytest.raises(Exception):
            QueryPlanRequest(query="")

    def test_query_plan_request_execute_default_false(self):
        req = QueryPlanRequest(query="hi")
        assert req.execute is False
        assert req.timeout_sec == 60.0


# ─── IntentClassifier tests ────────────────────────────────────────────────


class TestIntentClassifier:
    def test_comparison(self, classifier: IntentClassifier):
        assert (
            classifier.classify("Compare RBI vs SEBI KYC rules") == QueryType.COMPARISON
        )
        assert (
            classifier.classify("What is the difference between them?")
            == QueryType.COMPARISON
        )

    def test_timeline(self, classifier: IntentClassifier):
        assert classifier.classify("Timeline of KYC evolution") == QueryType.TIMELINE
        assert (
            classifier.classify("Show the chronology of changes") == QueryType.TIMELINE
        )

    def test_change(self, classifier: IntentClassifier):
        assert (
            classifier.classify("What changed in 2023?") == QueryType.REGULATORY_CHANGE
        )
        assert (
            classifier.classify("Show me the amendment") == QueryType.REGULATORY_CHANGE
        )

    def test_cross_document(self, classifier: IntentClassifier):
        assert (
            classifier.classify("Across both RBI and SEBI") == QueryType.CROSS_DOCUMENT
        )

    def test_multi_step(self, classifier: IntentClassifier):
        assert (
            classifier.classify("First find X, then compare with Y")
            == QueryType.MULTI_STEP
        )

    def test_definition(self, classifier: IntentClassifier):
        assert classifier.classify("What is KYC?") == QueryType.DEFINITION
        assert classifier.classify("Define KYC") == QueryType.DEFINITION

    def test_procedural(self, classifier: IntentClassifier):
        assert classifier.classify("How to file a complaint?") == QueryType.PROCEDURAL

    def test_factual(self, classifier: IntentClassifier):
        assert (
            classifier.classify("When was the RBI circular issued?")
            == QueryType.FACTUAL
        )

    def test_unknown(self, classifier: IntentClassifier):
        assert classifier.classify("zxcvbnm random gibberish") == QueryType.UNKNOWN

    def test_explain(self, classifier: IntentClassifier):
        s = classifier.explain("Compare X vs Y", QueryType.COMPARISON)
        assert "comparison" in s.lower()


# ─── TaskDecomposer tests ──────────────────────────────────────────────────


class TestTaskDecomposer:
    def test_definition_decomposition(self, decomposer: TaskDecomposer):
        steps = decomposer.decompose("What is KYC?", QueryType.DEFINITION)
        types = [s.step_type for s in steps]
        assert PlanStepType.RETRIEVE in types
        assert PlanStepType.ANSWER in types

    def test_comparison_decomposition(self, decomposer: TaskDecomposer):
        steps = decomposer.decompose("Compare A vs B", QueryType.COMPARISON)
        types = [s.step_type for s in steps]
        assert PlanStepType.RETRIEVE in types
        assert PlanStepType.COMPARE in types
        assert PlanStepType.ANSWER in types

    def test_timeline_decomposition(self, decomposer: TaskDecomposer):
        steps = decomposer.decompose("Timeline of X", QueryType.TIMELINE)
        types = [s.step_type for s in steps]
        assert PlanStepType.EXTRACT_TIMELINE in types
        assert PlanStepType.AGGREGATE in types

    def test_change_decomposition(self, decomposer: TaskDecomposer):
        steps = decomposer.decompose(
            "What changed in 2023?", QueryType.REGULATORY_CHANGE
        )
        types = [s.step_type for s in steps]
        assert PlanStepType.DETECT_CHANGE in types

    def test_cross_decomposition(self, decomposer: TaskDecomposer):
        steps = decomposer.decompose("RBI and SEBI both on X", QueryType.CROSS_DOCUMENT)
        types = [s.step_type for s in steps]
        assert PlanStepType.DETECT_CONTRADICTION in types

    def test_multi_step_decomposition(self, decomposer: TaskDecomposer):
        steps = decomposer.decompose(
            "First find X, then compare with Y", QueryType.MULTI_STEP
        )
        # Should produce multiple steps.
        assert len(steps) >= 3


# ─── StrategySelector tests ────────────────────────────────────────────────


class TestStrategySelector:
    def test_single_doc_for_factual(self, selector: StrategySelector):
        assert selector.select(QueryType.FACTUAL, 1) == PlanStrategy.SINGLE_DOC

    def test_multi_doc_for_comparison(self, selector: StrategySelector):
        assert selector.select(QueryType.COMPARISON, 2) == PlanStrategy.MULTI_DOC

    def test_iterative_for_timeline(self, selector: StrategySelector):
        assert selector.select(QueryType.TIMELINE, 3) == PlanStrategy.ITERATIVE

    def test_iterative_for_multi_step(self, selector: StrategySelector):
        assert selector.select(QueryType.MULTI_STEP, 3) == PlanStrategy.ITERATIVE

    def test_evidence_based_default(self, selector: StrategySelector):
        assert selector.select(QueryType.UNKNOWN, 1) == PlanStrategy.EVIDENCE_BASED


# ─── PlanValidator tests ───────────────────────────────────────────────────


class TestPlanValidator:
    def test_valid_plan(self, validator: PlanValidator, generator: PlanGenerator):
        plan = generator.generate(QueryPlanRequest(query="What is KYC?"))
        result = validator.validate(plan)
        assert result.is_valid is True
        assert result.errors == []

    def test_duplicate_step_ids(self, validator: PlanValidator):
        s1 = PlanStepDefinition(step_id="dup", step_type=PlanStepType.RETRIEVE)
        s2 = PlanStepDefinition(step_id="dup", step_type=PlanStepType.ANSWER)
        plan = ExecutionPlan(
            query="x",
            query_type=QueryType.FACTUAL,
            strategy=PlanStrategy.SINGLE_DOC,
            steps=[s1, s2],
        )
        result = validator.validate(plan)
        assert result.is_valid is False
        assert any("Duplicate" in e for e in result.errors)

    def test_missing_dependency(self, validator: PlanValidator):
        s = PlanStepDefinition(
            step_type=PlanStepType.ANSWER,
            depends_on=["nonexistent"],
        )
        plan = ExecutionPlan(
            query="x",
            query_type=QueryType.FACTUAL,
            strategy=PlanStrategy.SINGLE_DOC,
            steps=[s],
        )
        result = validator.validate(plan)
        assert result.is_valid is False
        assert any("missing" in e.lower() for e in result.errors)

    def test_cycle_detected(self, validator: PlanValidator):
        a = PlanStepDefinition(
            step_id="a", step_type=PlanStepType.RETRIEVE, depends_on=["b"]
        )
        b = PlanStepDefinition(
            step_id="b", step_type=PlanStepType.ANSWER, depends_on=["a"]
        )
        plan = ExecutionPlan(
            query="x",
            query_type=QueryType.FACTUAL,
            strategy=PlanStrategy.SINGLE_DOC,
            steps=[a, b],
        )
        result = validator.validate(plan)
        assert result.is_valid is False
        assert any("cycle" in e.lower() for e in result.errors)

    def test_empty_plan(self, validator: PlanValidator):
        plan = ExecutionPlan(
            query="x",
            query_type=QueryType.FACTUAL,
            strategy=PlanStrategy.SINGLE_DOC,
            steps=[],
        )
        result = validator.validate(plan)
        assert result.is_valid is False
        assert any("no steps" in e.lower() for e in result.errors)

    def test_comparison_warning(self, validator: PlanValidator):
        plan = ExecutionPlan(
            query="Compare X vs Y",
            query_type=QueryType.COMPARISON,
            strategy=PlanStrategy.MULTI_DOC,
            steps=[
                PlanStepDefinition(step_type=PlanStepType.RETRIEVE),
                PlanStepDefinition(step_type=PlanStepType.ANSWER),
            ],
            expected_documents=1,  # mismatch → warning
        )
        result = validator.validate(plan)
        assert (
            any(
                "2 expected" in w or "raising" in s
                for w in result.warnings
                for s in [result.suggestions[0] if result.suggestions else ""]
            )
            or len(result.warnings) > 0
        )


# ─── PlanExplainer tests ──────────────────────────────────────────────────


class TestPlanExplainer:
    def test_explain(self, explainer: PlanExplainer, generator: PlanGenerator):
        plan = generator.generate(QueryPlanRequest(query="Compare RBI vs SEBI"))
        explanation = explainer.explain(plan)
        assert explanation.plan_id == plan.plan_id
        assert "comparison" in explanation.summary.lower()
        assert explanation.strategy_reason != ""
        assert len(explanation.step_rationale) == len(plan.steps)


# ─── PlanGenerator tests ──────────────────────────────────────────────────


class TestPlanGenerator:
    def test_generate_factual(self, generator: PlanGenerator):
        plan = generator.generate(QueryPlanRequest(query="When was KYC introduced?"))
        assert plan.query_type == QueryType.FACTUAL
        assert plan.strategy == PlanStrategy.SINGLE_DOC
        assert plan.estimated_complexity in (
            PlanComplexity.SIMPLE,
            PlanComplexity.MODERATE,
        )

    def test_generate_comparison(self, generator: PlanGenerator):
        plan = generator.generate(
            QueryPlanRequest(query="Compare RBI vs SEBI", expected_documents=2)
        )
        assert plan.query_type == QueryType.COMPARISON
        assert plan.strategy == PlanStrategy.MULTI_DOC
        assert plan.expected_documents == 2

    def test_dependencies_filled(self, generator: PlanGenerator):
        plan = generator.generate(QueryPlanRequest(query="What is KYC?"))
        last = plan.steps[-1]
        # Last step should depend on all preceding steps (when it's ANSWER).
        if last.step_type == PlanStepType.ANSWER:
            assert len(last.depends_on) == len(plan.steps) - 1


# ─── PlanExecutor tests ────────────────────────────────────────────────────


class TestPlanExecutor:
    @pytest.mark.asyncio
    async def test_execute_simple(
        self, executor: PlanExecutor, generator: PlanGenerator
    ):
        plan = generator.generate(QueryPlanRequest(query="What is KYC?"))
        result = await executor.execute(plan)
        assert result.plan_id == plan.plan_id
        assert result.status == PlanStepStatus.SUCCESS
        assert len(result.step_results) == len(plan.steps)

    @pytest.mark.asyncio
    async def test_execute_uses_pre_supplied_chunks(self, generator: PlanGenerator):
        executor = PlanExecutor(
            pre_supplied_chunks=[
                {
                    "chunk_id": "pre-1",
                    "document_id": "doc-pre",
                    "content": "pre-supplied content",
                    "score": 0.9,
                }
            ]
        )
        plan = generator.generate(QueryPlanRequest(query="What is KYC?"))
        result = await executor.execute(plan)
        # First step (RETRIEVE) should have a citation to the pre-supplied chunk.
        first_result = result.step_results[0]
        assert "pre-1" in first_result.output.get("citations", [])

    @pytest.mark.asyncio
    async def test_execute_missing_dependency_skipped(self, executor: PlanExecutor):
        # Manually craft a plan with a missing dep.
        s1 = PlanStepDefinition(
            step_id="a",
            step_type=PlanStepType.RETRIEVE,
        )
        s2 = PlanStepDefinition(
            step_id="b",
            step_type=PlanStepType.ANSWER,
            depends_on=["a"],
        )
        s3 = PlanStepDefinition(
            step_id="c",
            step_type=PlanStepType.AGGREGATE,
            depends_on=["nope"],  # missing
        )
        plan = ExecutionPlan(
            query="x",
            query_type=QueryType.FACTUAL,
            strategy=PlanStrategy.SINGLE_DOC,
            steps=[s1, s2, s3],
        )
        result = await executor.execute(plan)
        statuses = {r.step_id: r.status for r in result.step_results}
        assert statuses["a"] == PlanStepStatus.SUCCESS
        assert statuses["b"] == PlanStepStatus.SUCCESS
        assert statuses["c"] == PlanStepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_execute_optional_step_failure_does_not_abort(
        self, executor: PlanExecutor
    ):
        class _BoomReasoner:
            async def reason(self, step_type, *, query, **kwargs):
                if step_type == PlanStepType.COMPARE:
                    raise RuntimeError("boom")
                return {"ok": True}

        executor = PlanExecutor(reasoner=_BoomReasoner())
        s1 = PlanStepDefinition(step_id="r", step_type=PlanStepType.RETRIEVE)
        s2 = PlanStepDefinition(
            step_id="c",
            step_type=PlanStepType.COMPARE,
            depends_on=["r"],
            optional=True,
        )
        s3 = PlanStepDefinition(
            step_id="a",
            step_type=PlanStepType.ANSWER,
            depends_on=["r"],
        )
        plan = ExecutionPlan(
            query="x",
            query_type=QueryType.COMPARISON,
            strategy=PlanStrategy.MULTI_DOC,
            steps=[s1, s2, s3],
        )
        result = await executor.execute(plan)
        statuses = {r.step_id: r.status for r in result.step_results}
        assert statuses["c"] == PlanStepStatus.SKIPPED
        assert statuses["a"] == PlanStepStatus.SUCCESS


# ─── QueryPlanner tests ────────────────────────────────────────────────────


class TestQueryPlanner:
    def test_plan(self, planner: QueryPlanner):
        req = QueryPlanRequest(query="Compare RBI vs SEBI KYC rules")
        plan, validation, explanation = planner.plan(req)
        assert plan.query_type == QueryType.COMPARISON
        assert validation.is_valid is True
        assert explanation.plan_id == plan.plan_id

    @pytest.mark.asyncio
    async def test_plan_and_execute(self, planner: QueryPlanner):
        req = QueryPlanRequest(
            query="What is KYC?",
            chunks=[
                {
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "content": "KYC info",
                    "score": 0.9,
                }
            ],
            execute=True,
        )
        plan, validation, explanation, execution = await planner.plan_and_execute(req)
        assert execution is not None
        assert execution.status == PlanStepStatus.SUCCESS

    def test_default_factory(self):
        planner = build_default_query_planner()
        assert isinstance(planner, QueryPlanner)
        assert isinstance(planner.generator, PlanGenerator)
        assert isinstance(planner.validator, PlanValidator)
        assert isinstance(planner.explainer, PlanExplainer)
        assert isinstance(planner.executor, PlanExecutor)


# ─── API integration tests ─────────────────────────────────────────────────


class TestAPI:
    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient):
        r = await client.get("/api/v1/planning/health")
        assert r.status_code == 200
        assert r.json()["module"] == "planning"

    @pytest.mark.asyncio
    async def test_plan_endpoint(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/planning/plan",
            json={"query": "Compare RBI vs SEBI KYC"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["plan"]["query_type"] == "comparison"
        assert body["validation"]["is_valid"] is True
        assert body["explanation"]["plan_id"] == body["plan"]["plan_id"]

    @pytest.mark.asyncio
    async def test_execute_endpoint(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/planning/execute",
            json={
                "query": "What is KYC?",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": "d1",
                        "content": "KYC",
                        "score": 0.9,
                    }
                ],
                "execute": True,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["execution"] is not None
        assert body["execution"]["status"] in ("success", "failed", "pending")

    @pytest.mark.asyncio
    async def test_validate_endpoint(self, client: AsyncClient):
        plan = {
            "query": "x",
            "query_type": "factual",
            "strategy": "single_doc",
            "steps": [
                {
                    "step_id": "s1",
                    "step_type": "retrieve",
                    "description": "x",
                }
            ],
            "expected_documents": 1,
        }
        r = await client.post("/api/v1/planning/validate", json=plan)
        assert r.status_code == 200
        assert r.json()["is_valid"] is True
