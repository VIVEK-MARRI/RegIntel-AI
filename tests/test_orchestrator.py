"""Tests for Module 5.6 — Response Orchestrator.

Coverage
--------
* Schema validation (OrchestratorRequest, FinalAnswerResponse,
  ResponseContext, StepResult, pipeline status enums).
* PipelineCoordinator step ordering and graceful degradation.
* Per-step failure handling (fail_open True/False).
* Step timeout enforcement.
* Disabling individual steps via request flags.
* ResponseBuilder shape.
* API integration: /api/v1/orchestrator/answer + /health, with all
  five services injected via dependency_overrides so no real LLM
  SDK is required.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_attribution_service,
    get_citation_service,
    get_confidence_service,
    get_hallucination_guard_service,
    get_response_orchestrator,
    reset_attribution_service,
    reset_confidence_service,
    reset_hallucination_guard,
    reset_response_orchestrator,
)
from app.api.v1.orchestrator import router as orchestrator_router
from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.orchestrator import (
    FinalAnswerResponse,
    OrchestratorMetadata,
    OrchestratorRequest,
    PipelineStatus,
    PipelineStep,
    ResponseContext,
    StepResult,
)
from app.services.orchestrator import (
    AnswerGenerationStep,
    AnswerPipeline,
    AttributionStep,
    CitationStep,
    ConfidenceStep,
    HallucinationStep,
    PipelineCoordinator,
    ResponseBuilder,
    ResponseOrchestrator,
    build_default_orchestrator,
)
from app.services.answer_generation import AnswerGeneratorService
from app.services.answer_generation.providers import MockLLMProvider
from app.services.citation import CitationService
from app.services.confidence import ConfidenceService
from app.services.hallucination import HallucinationGuardService
from app.services.attribution import SourceAttributionService


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    for fn in (
        reset_attribution_service,
        reset_confidence_service,
        reset_hallucination_guard,
        reset_response_orchestrator,
    ):
        fn()
    yield
    for fn in (
        reset_attribution_service,
        reset_confidence_service,
        reset_hallucination_guard,
        reset_response_orchestrator,
    ):
        fn()


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
                "KYC includes identity verification, address proof, and "
                "risk profiling."
            ),
            score=0.92,
        ),
    ]


@pytest.fixture
def coordinator():
    return PipelineCoordinator(
        answer_generator=AnswerGeneratorService(
            provider=MockLLMProvider(),
            prompt_builder=None,  # type: ignore[arg-type]
        )
        if False
        else _build_generator(),
        citation=_build_citation(),
        confidence=_build_confidence(),
        hallucination_guard=_build_hallucination(),
        attribution=_build_attribution(),
    )


def _build_generator():
    from app.services.answer_generation import PromptBuilder

    return AnswerGeneratorService(
        provider=MockLLMProvider(),
        prompt_builder=PromptBuilder(),
    )


def _build_citation():
    from app.services.citation import build_default_citation_service
    return build_default_citation_service()


def _build_confidence():
    from app.services.confidence import build_default_confidence_service
    return build_default_confidence_service()


def _build_hallucination():
    from app.services.hallucination import build_default_hallucination_guard
    return build_default_hallucination_guard()


def _build_attribution():
    from app.services.attribution import build_default_attribution_service
    return build_default_attribution_service()


@pytest.fixture
def app():
    orchestrator = build_default_orchestrator(
        answer_generator=_build_generator(),
        citation=_build_citation(),
        confidence=_build_confidence(),
        hallucination_guard=_build_hallucination(),
        attribution=_build_attribution(),
    )
    app = FastAPI()
    app.include_router(orchestrator_router, prefix="/api/v1")
    app.dependency_overrides[get_response_orchestrator] = lambda: orchestrator
    yield app
    app.dependency_overrides.clear()


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_step_enum_values(self):
        assert PipelineStep.ANSWER_GENERATION.value == "answer_generation"
        assert PipelineStep.CITATION.value == "citation"
        assert PipelineStep.CONFIDENCE.value == "confidence"
        assert PipelineStep.HALLUCINATION.value == "hallucination"
        assert PipelineStep.ATTRIBUTION.value == "attribution"

    def test_status_enum_values(self):
        assert PipelineStatus.SUCCESS.value == "success"
        assert PipelineStatus.FAILED.value == "failed"
        assert PipelineStatus.DEGRADED.value == "degraded"
        assert PipelineStatus.SKIPPED.value == "skipped"

    def test_orchestrator_request_defaults(self, sample_chunks):
        req = OrchestratorRequest(query="q", chunks=sample_chunks)
        assert req.tone == "regulatory"
        assert req.temperature == 0.2
        assert req.max_tokens == 700
        assert req.fail_open is True
        assert req.enable_answer_generation is True
        assert req.enable_citation is True
        assert req.enable_confidence is True
        assert req.enable_hallucination_guard is True
        assert req.enable_attribution is True

    def test_orchestrator_request_rejects_empty_chunks(self):
        with pytest.raises(Exception):
            OrchestratorRequest(query="q", chunks=[])

    def test_step_result_defaults(self):
        sr = StepResult(step=PipelineStep.CITATION)
        assert sr.status == PipelineStatus.PENDING
        assert sr.latency_ms == 0.0
        assert sr.error is None
        assert sr.warnings == []


# ─── Pipeline step base tests ───────────────────────────────────────────────


class TestAnswerPipelineBase:
    @pytest.mark.asyncio
    async def test_run_with_timeout_records_failure(self):
        class _Slow(AnswerPipeline):
            step = PipelineStep.CITATION

            async def run(self, context):
                await asyncio.sleep(2.0)

        step = _Slow(step_timeout_sec=0.05)
        ctx = ResponseContext(query="q", chunks=[])
        result = await step.run_with_timeout(ctx)
        assert result.status == PipelineStatus.FAILED
        assert "timed out" in (result.error or "")

    @pytest.mark.asyncio
    async def test_run_with_timeout_records_exception(self):
        class _Boom(AnswerPipeline):
            step = PipelineStep.CITATION

            async def run(self, context):
                raise RuntimeError("kaboom")

        step = _Boom()
        ctx = ResponseContext(query="q", chunks=[])
        result = await step.run_with_timeout(ctx)
        assert result.status == PipelineStatus.FAILED
        assert "kaboom" in (result.error or "")

    @pytest.mark.asyncio
    async def test_run_with_timeout_success(self):
        class _OK(AnswerPipeline):
            step = PipelineStep.CITATION

            async def run(self, context):
                context.warnings.append("ran")

        step = _OK()
        ctx = ResponseContext(query="q", chunks=[])
        result = await step.run_with_timeout(ctx)
        assert result.status == PipelineStatus.SUCCESS
        assert "ran" in ctx.warnings


# ─── Coordinator tests ─────────────────────────────────────────────────────


class TestPipelineCoordinator:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, coordinator, sample_chunks):
        req = OrchestratorRequest(
            query="What is KYC?", chunks=sample_chunks, fail_open=True
        )
        resp = await coordinator.run(req)
        assert isinstance(resp, FinalAnswerResponse)
        assert resp.query == "What is KYC?"
        assert resp.answer is not None
        # Every step succeeded.
        statuses = {s.step: s.status for s in resp.metadata.step_results}
        assert statuses[PipelineStep.ANSWER_GENERATION] == PipelineStatus.SUCCESS
        assert statuses[PipelineStep.CITATION] == PipelineStatus.SUCCESS
        assert statuses[PipelineStep.CONFIDENCE] == PipelineStatus.SUCCESS
        assert statuses[PipelineStep.HALLUCINATION] == PipelineStatus.SUCCESS
        assert statuses[PipelineStep.ATTRIBUTION] == PipelineStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_disabled_steps_are_skipped(self, coordinator, sample_chunks):
        req = OrchestratorRequest(
            query="q",
            chunks=sample_chunks,
            enable_attribution=False,
            enable_citation=False,
        )
        resp = await coordinator.run(req)
        steps = {s.step for s in resp.metadata.step_results}
        assert PipelineStep.ATTRIBUTION not in steps
        assert PipelineStep.CITATION not in steps

    @pytest.mark.asyncio
    async def test_step_failure_records_status(self, sample_chunks):
        # Build a citation service whose cite() raises.
        from app.services.citation import CitationService

        class _BrokenCitation(CitationService):
            def cite(self, request):
                raise RuntimeError("citation down")

        coord = PipelineCoordinator(
            answer_generator=_build_generator(),
            citation=_BrokenCitation(),
            confidence=_build_confidence(),
            hallucination_guard=_build_hallucination(),
            attribution=_build_attribution(),
        )
        req = OrchestratorRequest(
            query="q", chunks=sample_chunks, fail_open=True
        )
        resp = await coord.run(req)
        citation_step = next(
            s for s in resp.metadata.step_results if s.step == PipelineStep.CITATION
        )
        assert citation_step.status == PipelineStatus.FAILED
        assert "citation down" in (citation_step.error or "")

    @pytest.mark.asyncio
    async def test_fail_closed_propagates(self, sample_chunks):
        from app.services.citation import CitationService

        class _BrokenCitation(CitationService):
            def cite(self, request):
                raise RuntimeError("boom")

        coord = PipelineCoordinator(
            answer_generator=_build_generator(),
            citation=_BrokenCitation(),
            confidence=_build_confidence(),
            hallucination_guard=_build_hallucination(),
            attribution=_build_attribution(),
        )
        req = OrchestratorRequest(
            query="q", chunks=sample_chunks, fail_open=False
        )
        with pytest.raises(RuntimeError, match="boom"):
            await coord.run(req)

    @pytest.mark.asyncio
    async def test_step_timeout_enforced(self, sample_chunks):
        from app.services.citation import CitationService

        class _SlowCitation(CitationService):
            async def cite_async(self, request):  # not used; we patch the step directly
                await asyncio.sleep(3.0)
                return super().cite(request)

            def cite(self, request):
                return super().cite(request)

        # Patch the step itself by replacing the citation step's run
        # method to await asyncio.sleep — this is the path that
        # asyncio.wait_for can actually interrupt.
        class _SlowCitationStep(AnswerPipeline):
            step = PipelineStep.CITATION

            async def run(self, context):
                await asyncio.sleep(3.0)

        coord = PipelineCoordinator(
            answer_generator=_build_generator(),
            citation=_SlowCitation(),
            confidence=_build_confidence(),
            hallucination_guard=_build_hallucination(),
            attribution=_build_attribution(),
        )
        # Replace the citation step in the build_steps output.
        coord._build_steps = lambda req: [
            AnswerGenerationStep(
                service=coord.answer_generator,
                step_timeout_sec=req.step_timeout_sec,
            ),
            _SlowCitationStep(step_timeout_sec=req.step_timeout_sec),
            ConfidenceStep(
                service=coord.confidence,
                step_timeout_sec=req.step_timeout_sec,
            ),
            HallucinationStep(
                service=coord.hallucination_guard,
                step_timeout_sec=req.step_timeout_sec,
            ),
            AttributionStep(
                service=coord.attribution,
                step_timeout_sec=req.step_timeout_sec,
            ),
        ]
        req = OrchestratorRequest(
            query="q",
            chunks=sample_chunks,
            fail_open=True,
            step_timeout_sec=1.0,  # schema minimum
        )
        resp = await coord.run(req)
        citation_step = next(
            s for s in resp.metadata.step_results if s.step == PipelineStep.CITATION
        )
        assert citation_step.status == PipelineStatus.FAILED
        assert "timed out" in (citation_step.error or "")

    @pytest.mark.asyncio
    async def test_response_envelope_shape(self, coordinator, sample_chunks):
        req = OrchestratorRequest(query="q", chunks=sample_chunks)
        resp = await coordinator.run(req)
        assert 0.0 <= resp.confidence_score <= 1.0
        assert 0.0 <= resp.faithfulness_score <= 1.0
        assert isinstance(resp.hallucination_detected, bool)
        assert resp.latency_ms > 0

    @pytest.mark.asyncio
    async def test_all_steps_disabled_uses_synthesised_answer(self, coordinator, sample_chunks):
        req = OrchestratorRequest(
            query="q",
            chunks=sample_chunks,
            enable_answer_generation=False,
            enable_citation=False,
            enable_confidence=False,
            enable_hallucination_guard=False,
            enable_attribution=False,
        )
        resp = await coordinator.run(req)
        # Synthesised answer from first chunk.
        assert resp.answer.executive_summary == "Information retrieved."
        # Faithfulness gets the neutral fallback (0.5) and hallucination=True.
        assert resp.hallucination_detected is True
        assert resp.faithfulness_score == 0.5


# ─── Response builder tests ────────────────────────────────────────────────


class TestResponseBuilder:
    def test_to_dict_has_all_keys(self, coordinator, sample_chunks):
        async def _run():
            return await coordinator.run(
                OrchestratorRequest(query="q", chunks=sample_chunks)
            )
        resp = asyncio.run(_run())
        d = ResponseBuilder.to_dict(resp)
        for k in (
            "query",
            "answer",
            "citations",
            "confidence_score",
            "faithfulness_score",
            "hallucination_detected",
            "source_attributions",
            "latency_ms",
            "metadata",
        ):
            assert k in d
        assert "confidence_level" in d
        assert "hallucination_risk_level" in d
        assert "attribution_coverage_ratio" in d


# ─── API tests ─────────────────────────────────────────────────────────────


class TestOrchestratorAPI:
    @pytest.mark.asyncio
    async def test_health(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/orchestrator/health")
            assert r.status_code == 200
            assert r.json()["module"] == "response_orchestrator"

    @pytest.mark.asyncio
    async def test_answer(self, app, sample_chunks):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {
                "query": "What is KYC?",
                "chunks": [c.model_dump() for c in sample_chunks],
                "tone": "regulatory",
                "verification_method": "lexical",
            }
            r = await c.post("/api/v1/orchestrator/answer", json=payload)
            assert r.status_code == 200
            data = r.json()
            for k in (
                "query",
                "answer",
                "citations",
                "confidence_score",
                "faithfulness_score",
                "hallucination_detected",
                "source_attributions",
                "latency_ms",
                "metadata",
            ):
                assert k in data

    @pytest.mark.asyncio
    async def test_answer_empty_query_rejected(self, app, sample_chunks):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {
                "query": "  ",
                "chunks": [c.model_dump() for c in sample_chunks],
            }
            r = await c.post("/api/v1/orchestrator/answer", json=payload)
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_answer_no_chunks_rejected(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {"query": "q", "chunks": []}
            r = await c.post("/api/v1/orchestrator/answer", json=payload)
            assert r.status_code == 422
