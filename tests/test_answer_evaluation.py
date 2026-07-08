"""Tests for Module 5.7 — Answer Evaluation Framework."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_evaluation_service,
    reset_evaluation_service,
)
from app.api.v1.evaluation import router as evaluation_router
from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.attribution import (
    AttributionConfidence,
    AttributionSection,
    SourceAttribution,
)
from app.schemas.citation import (
    AnnotatedAnswer,
    AnnotatedText,
    EvidenceChunk,
    ReferenceEntry,
)
from app.schemas.confidence import ConfidenceLevel
from app.schemas.evaluation import (
    AnswerEvaluationReport,
    AnswerEvaluationResult,
    EvaluationMetric,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationStrategy,
    MetricScore,
)
from app.schemas.hallucination import HallucinationRiskLevel
from app.schemas.orchestrator import (
    FinalAnswerResponse,
    OrchestratorMetadata,
)
from app.services.evaluation import (
    AnswerBenchmarkRunner,
    AnswerEvaluationService,
    AnswerEvaluator,
    MetricsEngine,
    build_default_evaluation_service,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_evaluation_service()
    yield
    reset_evaluation_service()


@pytest.fixture
def sample_chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id="chk-1",
            document_id="doc-1",
            document_title="RBI KYC",
            source="RBI",
            page_number=8,
            section="KYC Norms",
            content=(
                "Banks must perform customer identification at onboarding. "
                "KYC includes identity verification, address proof, and risk "
                "profiling."
            ),
            score=0.92,
        ),
    ]


def _make_response(
    *,
    faithfulness: float = 0.95,
    hallucination_detected: bool = False,
    confidence: float = 0.85,
    attributions: list[SourceAttribution] | None = None,
    citations_count: int = 1,
) -> FinalAnswerResponse:
    answer = AnswerSection(
        executive_summary="Banks perform KYC at onboarding.",
        detailed_explanation=(
            "KYC includes identity verification, address proof, and risk " "profiling."
        ),
        supporting_evidence=[],
        key_regulatory_references=[],
    )
    annotated = AnnotatedAnswer(
        executive_summary=AnnotatedText(
            text=answer.executive_summary,
            citations=[],
            claim_count=1,
            cited_claim_count=1 if citations_count >= 1 else 0,
        ),
        detailed_explanation=AnnotatedText(
            text=answer.detailed_explanation,
            citations=[],
            claim_count=1,
            cited_claim_count=1 if citations_count >= 1 else 0,
        ),
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
                excerpt="Banks must perform customer identification at onboarding.",
            ),
        ],
        citation_map={"clm-1": "cit-1"},
    )
    return FinalAnswerResponse(
        query="What is KYC?",
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
        source_attributions=attributions or [],
        attribution_coverage_ratio=1.0 if attributions else 0.0,
        metadata=OrchestratorMetadata(),
    )


@pytest.fixture
def good_response() -> FinalAnswerResponse:
    return _make_response(
        faithfulness=0.95, hallucination_detected=False, confidence=0.92
    )


@pytest.fixture
def bad_response() -> FinalAnswerResponse:
    return _make_response(faithfulness=0.3, hallucination_detected=True, confidence=0.4)


@pytest.fixture
def app():
    service = build_default_evaluation_service()
    app = FastAPI()
    app.include_router(evaluation_router, prefix="/api/v1")
    app.dependency_overrides[get_evaluation_service] = lambda: service
    yield app
    app.dependency_overrides.clear()


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_evaluation_metric_values(self):
        assert EvaluationMetric.FAITHFULNESS.value == "faithfulness"
        assert EvaluationMetric.HALLUCINATION_RATE.value == "hallucination_rate"

    def test_metric_score_range_validation(self):
        with pytest.raises(Exception):
            MetricScore(metric=EvaluationMetric.FAITHFULNESS, score=1.5)
        with pytest.raises(Exception):
            MetricScore(metric=EvaluationMetric.FAITHFULNESS, score=-0.1)

    def test_evaluation_strategy_values(self):
        assert EvaluationStrategy.BASELINE.value == "baseline"
        assert EvaluationStrategy.CANDIDATE.value == "candidate"


# ─── Metrics engine tests ───────────────────────────────────────────────────


class TestMetricsEngine:
    def test_faithfulness(self, good_response, bad_response):
        engine = MetricsEngine()
        s = engine.faithfulness(good_response)
        assert s.score == 0.95
        assert "no hallucination" in (s.note or "")
        s = engine.faithfulness(bad_response)
        assert s.score == 0.3
        assert "hallucination" in (s.note or "")

    def test_answer_relevance(self, good_response):
        engine = MetricsEngine()
        s = engine.answer_relevance(good_response, "What is KYC?")
        assert 0.0 <= s.score <= 1.0
        assert s.score > 0.0  # overlap with "KYC" word

    def test_answer_relevance_empty(self):
        engine = MetricsEngine()
        empty = _make_response()
        empty.answer.executive_summary = ""
        empty.answer.detailed_explanation = ""
        s = engine.answer_relevance(empty, "q")
        assert s.score == 0.0

    def test_citation_accuracy(self, good_response):
        engine = MetricsEngine()
        s = engine.citation_accuracy(good_response)
        assert s.score == 1.0  # 1 cited out of 1 total in each section

    def test_citation_accuracy_partial(self):
        engine = MetricsEngine()
        resp = _make_response()
        resp.citations.executive_summary.cited_claim_count = 0
        s = engine.citation_accuracy(resp)
        # 1 cited / 2 total = 0.5
        assert 0.0 < s.score < 1.0

    def test_source_attribution_accuracy_no_attributions(self, good_response):
        engine = MetricsEngine()
        s = engine.source_attribution_accuracy(good_response)
        # coverage=0, validity=0 → score=0
        assert s.score == 0.0

    def test_source_attribution_accuracy_with_attributions(self, good_response):
        engine = MetricsEngine()
        good_response.source_attributions = [
            SourceAttribution(
                section=AttributionSection.EXECUTIVE_SUMMARY,
                segment_index=0,
                segment_text="Banks perform KYC at onboarding.",
                document_id="doc-1",
                document_title="RBI KYC",
                chunk_id="chk-1",
                excerpt="KYC includes identity verification",
                similarity=0.8,
                confidence=AttributionConfidence.HIGH,
            ),
        ]
        good_response.attribution_coverage_ratio = 1.0
        s = engine.source_attribution_accuracy(good_response)
        assert s.score > 0.0

    def test_completeness(self, good_response, sample_chunks):
        engine = MetricsEngine()
        s = engine.completeness(good_response, sample_chunks)
        assert s.score > 0.0

    def test_completeness_no_chunks(self, good_response):
        engine = MetricsEngine()
        s = engine.completeness(good_response, [])
        assert s.score == 0.0

    def test_groundedness(self, good_response):
        engine = MetricsEngine()
        s = engine.groundedness(good_response)
        assert 0.0 <= s.score <= 1.0

    def test_hallucination_rate(self, good_response, bad_response):
        engine = MetricsEngine()
        s = engine.hallucination_rate(good_response)
        assert s.score == 1.0  # no hallucination → 1.0
        s = engine.hallucination_rate(bad_response)
        assert s.score == 0.0  # hallucination → 0.0

    def test_evidence_coverage(self, good_response):
        engine = MetricsEngine()
        s = engine.evidence_coverage(good_response)
        assert s.score == good_response.attribution_coverage_ratio

    def test_compute_all(self, good_response, sample_chunks):
        engine = MetricsEngine()
        scores = engine.compute_all(
            response=good_response, query="What is KYC?", chunks=sample_chunks
        )
        assert len(scores) == 8
        metric_names = {s.metric for s in scores}
        assert EvaluationMetric.FAITHFULNESS in metric_names
        assert EvaluationMetric.HALLUCINATION_RATE in metric_names

    def test_compute_subset(self, good_response, sample_chunks):
        engine = MetricsEngine()
        scores = engine.compute_all(
            response=good_response,
            query="q",
            chunks=sample_chunks,
            metrics=[EvaluationMetric.FAITHFULNESS, EvaluationMetric.COMPLETENESS],
        )
        assert len(scores) == 2


# ─── Evaluator tests ────────────────────────────────────────────────────────


class TestAnswerEvaluator:
    def test_evaluate_returns_envelope(self, good_response, sample_chunks):
        evaluator = AnswerEvaluator()
        request = EvaluationRequest(
            response=good_response,
            query="q",
            chunks=[c.model_dump() for c in sample_chunks],
        )
        resp = evaluator.evaluate(request)
        assert isinstance(resp, EvaluationResponse)
        assert resp.query == "q"
        assert isinstance(resp.result, AnswerEvaluationResult)
        assert 0.0 <= resp.result.aggregate_score <= 1.0
        assert resp.result.metadata.get("metrics_count") == 8

    def test_evaluate_with_bad_response(self, bad_response):
        evaluator = AnswerEvaluator()
        request = EvaluationRequest(response=bad_response, query="q", chunks=[])
        resp = evaluator.evaluate(request)
        assert resp.result.aggregate_score < 0.5
        assert resp.result.hallucination_rate == 1.0


# ─── Benchmark runner tests ────────────────────────────────────────────────


class TestAnswerBenchmarkRunner:
    def test_run_benchmark(self, good_response, bad_response, sample_chunks):
        runner = AnswerBenchmarkRunner()
        cases = [
            {
                "response": good_response,
                "query": "q1",
                "chunks": [c.model_dump() for c in sample_chunks],
            },
            {"response": bad_response, "query": "q2", "chunks": []},
        ]
        report = runner.run(cases)
        assert isinstance(report, AnswerEvaluationReport)
        assert report.total_cases == 2
        assert len(report.results) == 2
        assert "faithfulness" in report.aggregate_metrics
        assert "hallucination_rate" in report.aggregate_metrics
        assert 0.0 <= report.average_aggregate_score <= 1.0

    def test_regression_detection(self, good_response, bad_response, sample_chunks):
        runner = AnswerBenchmarkRunner()
        baseline_cases = [
            {
                "response": good_response,
                "query": "q",
                "chunks": [c.model_dump() for c in sample_chunks],
            },
        ]
        candidate_cases = [
            {"response": bad_response, "query": "q", "chunks": []},
        ]
        baseline = runner.run(baseline_cases)
        candidate = runner.run(candidate_cases, baseline_results=baseline.results)
        assert candidate.regression_detected is True
        assert candidate.regression_delta < 0

    def test_no_regression_when_equivalent(self, good_response, sample_chunks):
        runner = AnswerBenchmarkRunner()
        cases = [
            {
                "response": good_response,
                "query": "q",
                "chunks": [c.model_dump() for c in sample_chunks],
            },
        ]
        baseline = runner.run(cases)
        candidate = runner.run(cases, baseline_results=baseline.results)
        assert candidate.regression_detected is False
        assert abs(candidate.regression_delta) < 0.01


# ─── Service tests ─────────────────────────────────────────────────────────


class TestAnswerEvaluationService:
    def test_evaluate_via_service(self, good_response, sample_chunks):
        service = build_default_evaluation_service()
        request = EvaluationRequest(
            response=good_response,
            query="q",
            chunks=[c.model_dump() for c in sample_chunks],
        )
        resp = service.evaluate(request)
        assert resp.result.aggregate_score > 0.0

    def test_benchmark_via_service(self, good_response, bad_response, sample_chunks):
        service = build_default_evaluation_service()
        cases = [
            {
                "response": good_response,
                "query": "q1",
                "chunks": [c.model_dump() for c in sample_chunks],
            },
            {"response": bad_response, "query": "q2", "chunks": []},
        ]
        report = service.benchmark(cases)
        assert report.total_cases == 2


# ─── API tests ──────────────────────────────────────────────────────────────


class TestEvaluationAPI:
    @pytest.mark.asyncio
    async def test_health(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/evaluation/health")
            assert r.status_code == 200
            assert r.json()["module"] == "answer_evaluation"

    @pytest.mark.asyncio
    async def test_evaluate(self, app, good_response, sample_chunks):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            payload = {
                "response": good_response.model_dump(mode="json"),
                "query": "What is KYC?",
                "chunks": [c.model_dump() for c in sample_chunks],
            }
            r = await c.post("/api/v1/evaluation/evaluate", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert "result" in data
            assert "scores" in data["result"]

    @pytest.mark.asyncio
    async def test_evaluate_empty_query_rejected(self, app, good_response):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            payload = {
                "response": good_response.model_dump(mode="json"),
                "query": "  ",
                "chunks": [],
            }
            r = await c.post("/api/v1/evaluation/evaluate", json=payload)
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_benchmark(self, app, good_response, bad_response, sample_chunks):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            payload = {
                "cases": [
                    {
                        "response": good_response.model_dump(mode="json"),
                        "query": "q1",
                        "chunks": [c.model_dump() for c in sample_chunks],
                    },
                    {
                        "response": bad_response.model_dump(mode="json"),
                        "query": "q2",
                        "chunks": [],
                    },
                ],
            }
            r = await c.post("/api/v1/evaluation/benchmark", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["total_cases"] == 2
            assert "regression_detected" in data

    @pytest.mark.asyncio
    async def test_benchmark_empty_cases_rejected(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post("/api/v1/evaluation/benchmark", json={"cases": []})
            assert r.status_code == 422
