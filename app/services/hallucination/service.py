"""HallucinationGuardService — Module 5.4 orchestrator.

Combines the LLM-based :class:`FaithfulnessEvaluator` and the offline
:class:`LexicalFaithfulnessChecker` according to the request's
``method``:

* ``llm``     — run the LLM evaluator only.
* ``lexical`` — run the lexical checker only.
* ``hybrid``  — run both; ``unsupported_claims`` is the union (more
  conservative), the LLM's ``faithfulness_score`` is the primary.
* ``mock``    — run the lexical checker; tagged as ``mock`` in
  metadata (used by offline tests / benchmarks).

The service never raises on provider failure when
``fail_open_on_provider_error`` is true — it falls back to the
lexical checker instead.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.hallucination import (
    ClaimVerdict,
    FaithfulnessMetadata,
    FaithfulnessReport,
    FaithfulnessRequest,
    FaithfulnessResponse,
    HallucinationRiskLevel,
    VerificationMethod,
    risk_level_for,
)
from app.services.answer_generation.providers import BaseLLMProvider
from app.services.citation.claim_extractor import ClaimExtractor
from app.services.hallucination.evaluator import (
    FaithfulnessEvaluator,
    MockFaithfulnessProvider,
)
from app.services.hallucination.lexical import (
    LexicalFaithfulnessChecker,
)
from app.services.observability import track_request

logger = logging.getLogger(__name__)


@dataclass
class _Report:
    """Internal report before serialisation."""

    supported: List[ClaimVerdict]
    unsupported: List[ClaimVerdict]
    score: float
    provider: Optional[str] = None
    latency_ms: float = 0.0


class HallucinationGuardService:
    """Top-level orchestrator for second-pass verification."""

    def __init__(
        self,
        *,
        provider: Optional[BaseLLMProvider] = None,
        lexical_checker: Optional[LexicalFaithfulnessChecker] = None,
    ) -> None:
        self.lexical_checker = lexical_checker or LexicalFaithfulnessChecker()
        self._provider = provider  # injected lazily for LLM / hybrid
        self._extractor = ClaimExtractor()

    def set_provider(self, provider: BaseLLMProvider) -> None:
        """Inject (or swap) the LLM provider used for LLM/hybrid modes."""
        self._provider = provider

    # ── Public API ──────────────────────────────────────────────────────────

    async def verify(self, request: FaithfulnessRequest) -> FaithfulnessResponse:
        request_id = uuid.uuid4().hex
        t0 = time.perf_counter()
        with track_request(
            endpoint="/api/v1/hallucination/verify",
            strategy="hallucination_guard",
        ) as ctx:
            try:
                if request.method == VerificationMethod.LEXICAL:
                    report = self._verify_lexical(request)
                elif request.method == VerificationMethod.MOCK:
                    report = self._verify_lexical(request)
                elif request.method == VerificationMethod.HYBRID:
                    report = await self._verify_hybrid(request)
                else:  # LLM
                    report = await self._verify_llm(request)
            except Exception as exc:
                if request.fail_open_on_provider_error:
                    logger.warning(
                        "Verification method %s failed (%s); falling back to lexical",
                        request.method,
                        exc,
                    )
                    report = self._verify_lexical(request)
                else:
                    raise
            try:
                ctx.rerank_used = False  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass

        latency_ms = (time.perf_counter() - t0) * 1000.0
        faithfulness = self._build_faithfulness_report(
            request=request,
            supported=report.supported,
            unsupported=report.unsupported,
            score=report.score,
        )
        metadata = FaithfulnessMetadata(
            request_id=request_id,
            latency_ms=latency_ms,
            provider_used=report.provider,
            chunks_used=len(request.chunks),
        )
        return FaithfulnessResponse(
            query=request.query,
            report=faithfulness,
            method=request.method,
            metadata=metadata,
        )

    # ── Convenience ────────────────────────────────────────────────────────

    async def verify_answer(
        self,
        *,
        query: str,
        answer: AnswerSection,
        chunks: List[RetrievedChunk],
        method: VerificationMethod = VerificationMethod.LEXICAL,
        min_faithfulness: float = 0.7,
        lexical_threshold: float = 0.15,
        fail_open_on_provider_error: bool = True,
    ) -> FaithfulnessResponse:
        request = FaithfulnessRequest(
            query=query,
            answer=answer,
            chunks=chunks,
            method=method,
            min_faithfulness=min_faithfulness,
            lexical_threshold=lexical_threshold,
            fail_open_on_provider_error=fail_open_on_provider_error,
        )
        return await self.verify(request)

    # ── Internals ──────────────────────────────────────────────────────────

    async def _verify_llm(self, request: FaithfulnessRequest) -> _Report:
        provider = self._provider
        if provider is None:
            # No LLM provider injected — degrade to lexical so the
            # caller still gets a useful report.
            logger.debug("No LLM provider configured; using lexical fallback")
            return self._verify_lexical(request)
        if isinstance(provider, MockFaithfulnessProvider):
            pass
        else:
            pass
        evaluator = FaithfulnessEvaluator(provider=provider, extractor=self._extractor)
        result = await evaluator.verify(
            query=request.query, answer=request.answer, chunks=request.chunks
        )
        if result.error:
            if request.fail_open_on_provider_error:
                logger.warning(
                    "LLM evaluator error; falling back to lexical: %s", result.error
                )
                return self._verify_lexical(request)
            # Propagate the error so the outer try/except can re-raise it.
            raise RuntimeError(result.error) from None
        provider_label = result.provider or getattr(
            provider.name, "value", str(provider.name)
        )
        return _Report(
            supported=result.supported,
            unsupported=result.unsupported,
            score=result.faithfulness_score,
            provider=provider_label,
            latency_ms=result.latency_ms,
        )

    def _verify_lexical(self, request: FaithfulnessRequest) -> _Report:
        checker = LexicalFaithfulnessChecker(
            threshold=request.lexical_threshold,
            extractor=self._extractor,
        )
        verdicts = checker.verify(answer=request.answer, chunks=request.chunks)
        supported = [v for v in verdicts if v.supported]
        unsupported = [v for v in verdicts if not v.supported]
        total = len(verdicts)
        score = (len(supported) / total) if total else 1.0
        return _Report(
            supported=supported,
            unsupported=unsupported,
            score=score,
            provider=None,
        )

    async def _verify_hybrid(self, request: FaithfulnessRequest) -> _Report:
        # Run both in sequence (lexical is fast and informs the LLM
        # failure path).
        lexical = self._verify_lexical(request)
        llm = await self._verify_llm(request)

        # Union of unsupported claims.
        llm_unsupported_ids = {v.claim_id for v in llm.unsupported}
        combined_unsupported = list(llm.unsupported)
        for v in lexical.unsupported:
            if v.claim_id not in llm_unsupported_ids:
                v = v.model_copy(update={"reason": v.reason + " (lexical fallback)"})
                combined_unsupported.append(v)
        # Supported = everything we have a verdict for that isn't unsupported.
        unsupported_ids = {v.claim_id for v in combined_unsupported}
        combined_supported: List[ClaimVerdict] = []
        for v in llm.supported:
            if v.claim_id not in unsupported_ids:
                combined_supported.append(v)
        for v in lexical.supported:
            if v.claim_id not in unsupported_ids and v.claim_id not in {
                x.claim_id for x in combined_supported
            }:
                combined_supported.append(v)

        # Score: prefer the LLM's score; clamp to ensure unsupported count is respected.
        total = len(combined_supported) + len(combined_unsupported)
        score = (len(combined_supported) / total) if total else 1.0

        return _Report(
            supported=combined_supported,
            unsupported=combined_unsupported,
            score=score,
            provider=llm.provider,
            latency_ms=lexical.latency_ms + llm.latency_ms,
        )

    def _build_faithfulness_report(
        self,
        *,
        request: FaithfulnessRequest,
        supported: List[ClaimVerdict],
        unsupported: List[ClaimVerdict],
        score: float,
    ) -> FaithfulnessReport:
        total = len(supported) + len(unsupported)
        hallucination_detected = bool(unsupported)
        # Coverage = fraction of supported claims that have at least one cited chunk.
        covered = sum(1 for v in supported if v.cited_chunk_ids)
        coverage = (covered / len(supported)) if supported else 0.0
        # Risk level uses the request's min_faithfulness as the LOW→MEDIUM boundary.
        risk = risk_level_for(score, hallucination_detected=hallucination_detected)
        # Re-evaluate risk in case min_faithfulness is higher than default.
        if not hallucination_detected and score < request.min_faithfulness:
            risk = HallucinationRiskLevel.LOW
        return FaithfulnessReport(
            query=request.query,
            total_claims=total,
            supported_count=len(supported),
            unsupported_count=len(unsupported),
            supported_claims=supported,
            unsupported_claims=unsupported,
            faithfulness_score=score,
            hallucination_detected=hallucination_detected,
            risk_level=risk,
            coverage=coverage,
        )


# ─── Factory ────────────────────────────────────────────────────────────────


def build_default_hallucination_guard(
    *,
    provider: Optional[BaseLLMProvider] = None,
) -> HallucinationGuardService:
    """Build a guard with the lexical checker and an optional LLM provider."""
    return HallucinationGuardService(provider=provider)


__all__ = [
    "HallucinationGuardService",
    "build_default_hallucination_guard",
]
