"""Module 5.6 — Response Orchestrator.

Composes the full Milestone 5 intelligence stack into a single
pipeline:

::

    Query + Chunks
         │
         ▼
    ┌──────────────────┐
    │  AnswerGenerator │  (Module 5.1)
    └─────────┬────────┘
              ▼
    ┌──────────────────┐
    │  Citation        │  (Module 5.2)
    └─────────┬────────┘
              ▼
    ┌──────────────────┐
    │  Confidence      │  (Module 5.3)
    └─────────┬────────┘
              ▼
    ┌──────────────────┐
    │  Hallucination   │  (Module 5.4)
    └─────────┬────────┘
              ▼
    ┌──────────────────┐
    │  Attribution     │  (Module 5.5)
    └─────────┬────────┘
              ▼
    FinalAnswerResponse

The :class:`PipelineCoordinator` runs each step with a per-step
timeout and graceful degradation: any single step failure is
recorded in :class:`StepResult` and the pipeline continues with
fallback values (per ``fail_open=True``).  When
``fail_open=False`` the request raises.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

from app.schemas.answer_generation import (
    AnswerGenerationRequest,
    AnswerSection,
    RetrievedChunk,
    AnswerTone,
    LLMProviderName,
)
from app.schemas.attribution import SourceAttribution
from app.schemas.citation import (
    AnnotatedAnswer,
    CitationRequest,
    CitationStyle,
    Claim,
    EvidenceChunk,
)
from app.schemas.confidence import (
    ConfidenceRequest,
    ConfidenceResponse,
    ConfidenceLevel,
)
from app.schemas.hallucination import (
    FaithfulnessRequest,
    HallucinationRiskLevel,
    VerificationMethod,
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
from app.services.answer_generation import AnswerGeneratorService
from app.services.attribution import SourceAttributionService
from app.services.citation import CitationService
from app.services.confidence import ConfidenceService
from app.services.hallucination import HallucinationGuardService
from app.services.observability import track_request

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ─── Fallback factories ────────────────────────────────────────────────────


def _fallback_evidence(chunks: List[RetrievedChunk]) -> List[EvidenceChunk]:
    """Build minimal evidence chunks from raw retrieved chunks."""
    out: List[EvidenceChunk] = []
    for c in chunks:
        out.append(
            EvidenceChunk(
                claim_id=f"clm-fallback-{c.chunk_id[:6]}",
                content=c.content[:300],
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.document_title or "(untitled)",
                page_number=c.page_number,
                section=c.section,
                score=c.score or 0.0,
            )
        )
    return out


def _empty_annotations(answer: AnswerSection) -> AnnotatedAnswer:
    from app.schemas.citation import AnnotatedText

    return AnnotatedAnswer(
        executive_summary=AnnotatedText(text=answer.executive_summary, citations=[]),
        detailed_explanation=AnnotatedText(
            text=answer.detailed_explanation, citations=[]
        ),
        supporting_evidence=[],
        key_regulatory_references=list(answer.key_regulatory_references),
        references=[],
        citation_map={},
    )


def _neutral_confidence(answer: AnswerSection, chunks: List[RetrievedChunk]) -> float:
    """Conservative fallback: average retrieval score, clamped."""
    if not chunks:
        return 0.0
    return max(0.0, min(1.0, sum(c.score or 0.0 for c in chunks) / len(chunks)))


def _neutral_faithfulness() -> float:
    return 0.5


# ─── Pipeline step base ────────────────────────────────────────────────────


class AnswerPipeline:
    """A single executable step in the orchestrator.

    Subclasses override :meth:`run` (async) and may produce partial
    updates to the context.  :meth:`run_with_timeout` is what the
    coordinator calls.
    """

    step: PipelineStep = PipelineStep.ANSWER_GENERATION

    def __init__(self, *, step_timeout_sec: float = 60.0) -> None:
        self.step_timeout_sec = step_timeout_sec

    async def run(
        self, context: ResponseContext
    ) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    async def run_with_timeout(self, context: ResponseContext) -> StepResult:
        result = StepResult(step=self.step, status=PipelineStatus.RUNNING)
        t0 = time.perf_counter()
        try:
            await asyncio.wait_for(self.run(context), timeout=self.step_timeout_sec)
            result.status = PipelineStatus.SUCCESS
        except asyncio.TimeoutError:
            result.status = PipelineStatus.FAILED
            result.error = f"step timed out after {self.step_timeout_sec:.1f}s"
            logger.warning("Pipeline step %s timed out", self.step)
        except Exception as exc:
            result.status = PipelineStatus.FAILED
            result.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Pipeline step %s failed", self.step)
        result.latency_ms = (time.perf_counter() - t0) * 1000.0
        return result


# ─── Concrete steps ────────────────────────────────────────────────────────


class AnswerGenerationStep(AnswerPipeline):
    step = PipelineStep.ANSWER_GENERATION

    def __init__(self, *, service: AnswerGeneratorService, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = service

    async def run(self, context: ResponseContext) -> None:
        tone_str = context.options.get("tone", "regulatory")
        temperature = context.options.get("temperature", 0.2)
        max_tokens = context.options.get("max_tokens", 3072)
        try:
            tone = AnswerTone(tone_str)
        except ValueError:
            tone = AnswerTone.REGULATORY
        request = AnswerGenerationRequest(
            query=context.query,
            chunks=context.chunks,
            tone=tone,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response = await self.service.generate(request)
        context.answer = response.answer
        context.model_used = response.metadata.model
        context.provider_used = response.metadata.provider


class CitationStep(AnswerPipeline):
    step = PipelineStep.CITATION

    def __init__(self, *, service: CitationService, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = service

    async def run(self, context: ResponseContext) -> None:
        if context.answer is None:
            raise RuntimeError(
                "Citation step requires answer; run answer-generation first"
            )
        request = CitationRequest(
            query=context.query,
            answer=context.answer,
            chunks=context.chunks,
            style=CitationStyle.BRACKETED_SOURCE,
        )
        response = self.service.cite(request)
        context.citations = response.annotated_answer


class ConfidenceStep(AnswerPipeline):
    step = PipelineStep.CONFIDENCE

    def __init__(self, *, service: ConfidenceService, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = service

    async def run(self, context: ResponseContext) -> None:
        if context.answer is None:
            raise RuntimeError("Confidence step requires answer")

        request = ConfidenceRequest(
            query=context.query,
            answer=context.answer.model_dump(),
            chunks=[c.model_dump() for c in context.chunks],
        )
        response = self.service.score(request)
        context.confidence_score = response.confidence
        context.confidence_level = response.level


class HallucinationStep(AnswerPipeline):
    step = PipelineStep.HALLUCINATION

    def __init__(self, *, service: HallucinationGuardService, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = service

    async def run(self, context: ResponseContext) -> None:
        if context.answer is None:
            raise RuntimeError("Hallucination step requires answer")
        method = context.options.get("verification_method", VerificationMethod.LEXICAL)
        min_faith = context.options.get("min_faithfulness", 0.7)
        request = FaithfulnessRequest(
            query=context.query,
            answer=context.answer,
            chunks=context.chunks,
            method=method,
            min_faithfulness=min_faith,
            fail_open_on_provider_error=True,
        )
        response = await self.service.verify(request)
        context.faithfulness_score = response.report.faithfulness_score
        context.hallucination_detected = response.report.hallucination_detected
        context.hallucination_risk_level = response.report.risk_level
        if response.metadata.provider_used:
            context.provider_used = response.metadata.provider_used


class AttributionStep(AnswerPipeline):
    step = PipelineStep.ATTRIBUTION

    def __init__(self, *, service: SourceAttributionService, **kwargs) -> None:
        super().__init__(**kwargs)
        self.service = service

    async def run(self, context: ResponseContext) -> None:
        if context.answer is None:
            raise RuntimeError("Attribution step requires answer")
        response = self.service.attribute_segments(
            query=context.query,
            answer=context.answer,
            chunks=context.chunks,
        )
        context.source_attributions = response.attributions
        context.attribution_coverage_ratio = response.coverage.coverage_ratio


# ─── Coordinator ───────────────────────────────────────────────────────────


class PipelineCoordinator:
    """Runs the full pipeline for a request.

    A coordinator is constructed with all five services and is
    responsible for executing the steps in order, recording
    :class:`StepResult` objects, and assembling the final
    :class:`FinalAnswerResponse`.
    """

    def __init__(
        self,
        *,
        answer_generator: AnswerGeneratorService,
        citation: CitationService,
        confidence: ConfidenceService,
        hallucination_guard: HallucinationGuardService,
        attribution: SourceAttributionService,
    ) -> None:
        self.answer_generator = answer_generator
        self.citation = citation
        self.confidence = confidence
        self.hallucination_guard = hallucination_guard
        self.attribution = attribution

    def _build_steps(self, request: OrchestratorRequest) -> List[AnswerPipeline]:
        steps: List[AnswerPipeline] = []
        if request.enable_answer_generation:
            steps.append(
                AnswerGenerationStep(
                    service=self.answer_generator,
                    step_timeout_sec=request.step_timeout_sec,
                )
            )
        if request.enable_citation:
            steps.append(
                CitationStep(
                    service=self.citation,
                    step_timeout_sec=request.step_timeout_sec,
                )
            )
        if request.enable_confidence:
            steps.append(
                ConfidenceStep(
                    service=self.confidence,
                    step_timeout_sec=request.step_timeout_sec,
                )
            )
        if request.enable_hallucination_guard:
            steps.append(
                HallucinationStep(
                    service=self.hallucination_guard,
                    step_timeout_sec=request.step_timeout_sec,
                )
            )
        if request.enable_attribution:
            steps.append(
                AttributionStep(
                    service=self.attribution,
                    step_timeout_sec=request.step_timeout_sec,
                )
            )
        return steps

    async def run(self, request: OrchestratorRequest) -> FinalAnswerResponse:
        t0 = time.perf_counter()
        with track_request(
            endpoint="/api/v1/orchestrator/answer",
            strategy="response_orchestrator",
        ):
            context = ResponseContext(
                query=request.query,
                chunks=request.chunks,
                options={
                    "tone": request.tone,
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens,
                    "verification_method": request.verification_method,
                    "min_faithfulness": request.min_faithfulness,
                },
            )

            steps = self._build_steps(request)
            for step in steps:
                result = await step.run_with_timeout(context)
                context.step_results.append(result)
                if result.status == PipelineStatus.FAILED and not request.fail_open:
                    raise RuntimeError(
                        f"Pipeline step {step.step} failed: {result.error}"
                    )

            response = self._build_response(context)
        response.latency_ms = (time.perf_counter() - t0) * 1000.0
        response.metadata.total_latency_ms = response.latency_ms
        return response

    # ── Assembly ──────────────────────────────────────────────────────────

    def _build_response(self, context: ResponseContext) -> FinalAnswerResponse:
        # Required: answer must exist (even if from a fallback).
        if context.answer is None:
            # Synthesise a minimal answer from the first chunk.
            first = context.chunks[0] if context.chunks else None
            if first is None:
                raise RuntimeError(
                    "Pipeline produced no answer and no chunks were supplied"
                )
            context.answer = AnswerSection(
                executive_summary="Information retrieved.",
                detailed_explanation=first.content[:500]
                or "No additional detail available.",
                supporting_evidence=[],
                key_regulatory_references=[],
            )
            context.warnings.append(
                "answer_generation step produced no output; synthesised a stub"
            )

        # Citations: default to empty annotations if missing.
        if context.citations is None:
            context.citations = _empty_annotations(context.answer)
            context.warnings.append(
                "citation step produced no output; using empty annotations"
            )

        # Confidence: default to neutral.
        if context.confidence_score is None:
            context.confidence_score = _neutral_confidence(
                context.answer, context.chunks
            )
            context.confidence_level = ConfidenceLevel.MEDIUM
            context.warnings.append(
                "confidence step produced no output; using neutral fallback"
            )

        # Faithfulness: default to 0.5.
        if context.faithfulness_score is None:
            context.faithfulness_score = _neutral_faithfulness()
            context.hallucination_detected = True
            context.hallucination_risk_level = HallucinationRiskLevel.MEDIUM
            context.warnings.append(
                "hallucination step produced no output; using fallback"
            )

        if context.hallucination_detected is None:
            context.hallucination_detected = False
        if context.hallucination_risk_level is None:
            context.hallucination_risk_level = (
                HallucinationRiskLevel.HIGH
                if context.hallucination_detected
                else HallucinationRiskLevel.NONE
            )
        if context.confidence_level is None:
            if context.confidence_score >= 0.9:
                context.confidence_level = ConfidenceLevel.HIGH
            elif context.confidence_score >= 0.7:
                context.confidence_level = ConfidenceLevel.MEDIUM
            else:
                context.confidence_level = ConfidenceLevel.LOW

        metadata = OrchestratorMetadata(
            request_id=context.request_id,
            model_used=context.model_used,
            provider_used=context.provider_used,
            step_results=context.step_results,
            warnings=list(context.warnings),
        )
        return FinalAnswerResponse(
            query=context.query,
            answer=context.answer,
            citations=context.citations,
            confidence_score=context.confidence_score,
            confidence_level=context.confidence_level,
            faithfulness_score=context.faithfulness_score,
            hallucination_detected=context.hallucination_detected,
            hallucination_risk_level=context.hallucination_risk_level,
            source_attributions=context.source_attributions,
            attribution_coverage_ratio=context.attribution_coverage_ratio,
            metadata=metadata,
        )


# ─── Top-level orchestrator + response builder ─────────────────────────────


class ResponseBuilder:
    """Builds the final :class:`FinalAnswerResponse` payload."""

    @staticmethod
    def to_dict(response: FinalAnswerResponse) -> Dict[str, Any]:
        """Serialise to the dict shape shown in the spec."""
        return {
            "query": response.query,
            "answer": response.answer.model_dump(),
            "citations": response.citations.model_dump(),
            "confidence_score": response.confidence_score,
            "confidence_level": response.confidence_level.value,
            "faithfulness_score": response.faithfulness_score,
            "hallucination_detected": response.hallucination_detected,
            "hallucination_risk_level": response.hallucination_risk_level.value,
            "source_attributions": [
                a.model_dump() for a in response.source_attributions
            ],
            "attribution_coverage_ratio": response.attribution_coverage_ratio,
            "latency_ms": response.latency_ms,
            "metadata": response.metadata.model_dump(mode="json"),
        }


class ResponseOrchestrator:
    """Top-level orchestrator. Wraps a :class:`PipelineCoordinator`."""

    def __init__(self, *, coordinator: PipelineCoordinator) -> None:
        self.coordinator = coordinator

    async def answer(self, request: OrchestratorRequest) -> FinalAnswerResponse:
        return await self.coordinator.run(request)


# ─── Default factory ──────────────────────────────────────────────────────


def build_default_orchestrator(
    *,
    answer_generator: AnswerGeneratorService,
    citation: CitationService,
    confidence: ConfidenceService,
    hallucination_guard: HallucinationGuardService,
    attribution: SourceAttributionService,
) -> ResponseOrchestrator:
    coordinator = PipelineCoordinator(
        answer_generator=answer_generator,
        citation=citation,
        confidence=confidence,
        hallucination_guard=hallucination_guard,
        attribution=attribution,
    )
    return ResponseOrchestrator(coordinator=coordinator)


__all__ = [
    "AnswerGenerationStep",
    "AnswerPipeline",
    "AttributionStep",
    "CitationStep",
    "ConfidenceStep",
    "HallucinationStep",
    "PipelineCoordinator",
    "ResponseBuilder",
    "ResponseOrchestrator",
    "build_default_orchestrator",
]
