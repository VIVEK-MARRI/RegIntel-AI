"""ConfidenceService — orchestrator (Module 5.3 public API).

Composes the per-factor calculators, the :class:`ConfidenceCalculator`,
and the :class:`ConfidenceMetrics` collector into a single entry
point.  Adds advisory flags (e.g. ``low_citation_coverage``,
``no_rerank_scores``) that downstream consumers can surface to the
user.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.schemas.confidence import (
    DEFAULT_WEIGHTS,
    ConfidenceFactorName,
    ConfidenceFlag,
    ConfidenceRequest,
    ConfidenceResponse,
    level_for,
)
from app.services.confidence.calculator import (
    ConfidenceCalculator,
    FactorCalculator,
)
from app.services.confidence.factors import (
    chunk_coverage_factor,
    citation_coverage_factor,
    retrieval_relevance_factor,
    reranker_confidence_factor,
    source_agreement_factor,
)
from app.services.confidence.metrics import ConfidenceMetrics
from app.services.observability import track_request

logger = logging.getLogger(__name__)


# ─── Service ────────────────────────────────────────────────────────────────


class ConfidenceService:
    """Top-level orchestrator for confidence scoring."""

    def __init__(
        self,
        *,
        calculator: Optional[ConfidenceCalculator] = None,
        metrics: Optional[ConfidenceMetrics] = None,
    ) -> None:
        self.calculator = calculator or ConfidenceCalculator()
        self.metrics = metrics or ConfidenceMetrics()

    # ── Public API ──────────────────────────────────────────────────────────

    def score(self, request: ConfidenceRequest) -> ConfidenceResponse:
        if (
            not request.chunks
            and request.retrieval_scores is None
            and request.reranker_scores is None
        ):
            logger.debug("scoring with no chunks and no scores")

        weights = self._resolve_weights(request.weights)
        request_id = uuid.uuid4().hex
        t0 = time.perf_counter()

        with track_request(
            endpoint="/api/v1/confidence/score",
            strategy="confidence",
        ) as ctx:
            factors = self._build_factors(request, weights)
            confidence, breakdown = self.calculator.aggregate(factors)
            level = level_for(confidence)
            flags = self._compute_flags(request, factors, confidence)

            latency_ms = (time.perf_counter() - t0) * 1000.0
            try:
                ctx.rerank_used = False  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover
                pass

        # Update metrics.
        self.metrics.record(
            confidence=confidence,
            level=level,
            factor_scores={f.name: f.raw_score for f in factors},
            flags=flags,
        )

        response = ConfidenceResponse(
            query=request.query,
            confidence=confidence,
            level=level,
            breakdown=breakdown,
            flags=flags,
            metadata={
                "request_id": request_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "latency_ms": latency_ms,
                "chunks_used": len(request.chunks),
                "rerank_available": request.reranker_scores is not None,
            },
        )
        logger.info(
            "confidence.score query=%s confidence=%.3f level=%s flags=%s",
            request.query[:60],
            confidence,
            level.value,
            [f.value for f in flags],
        )
        return response

    # ── Convenience ────────────────────────────────────────────────────────

    def score_answer(
        self,
        *,
        query: str,
        answer: Mapping[str, Any],
        chunks: Sequence[Mapping[str, Any]],
        retrieval_scores: Optional[Sequence[float]] = None,
        reranker_scores: Optional[Sequence[float]] = None,
        citation_coverage: Optional[float] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> ConfidenceResponse:
        """Single-call wrapper."""
        request = ConfidenceRequest(
            query=query,
            answer=dict(answer),
            chunks=[dict(c) for c in chunks],
            retrieval_scores=list(retrieval_scores)
            if retrieval_scores is not None
            else None,
            reranker_scores=list(reranker_scores)
            if reranker_scores is not None
            else None,
            citation_coverage=citation_coverage,
            weights=weights,
        )
        return self.score(request)

    # ── Internals ──────────────────────────────────────────────────────────

    def _resolve_weights(self, custom: Optional[Dict[str, float]]) -> Dict[str, float]:
        merged: Dict[str, float] = dict(DEFAULT_WEIGHTS)
        if custom:
            for k, v in custom.items():
                if k in {n.value for n in ConfidenceFactorName}:
                    merged[k] = float(v)
        return merged

    def _build_factors(
        self,
        request: ConfidenceRequest,
        weights: Dict[str, float],
    ) -> List[FactorCalculator]:
        # Retrieval relevance.
        rel = retrieval_relevance_factor(
            retrieval_scores=request.retrieval_scores,
            chunk_scores=[c.get("score", 0.0) for c in request.chunks],
        )
        # Reranker.
        rerank = reranker_confidence_factor(request.reranker_scores)
        # Source agreement.
        src = source_agreement_factor(request.chunks)
        # Chunk coverage.
        coverage = chunk_coverage_factor(
            request.chunks,
            min_chunks_for_full_coverage=request.min_chunks_for_full_coverage,
        )
        # Citation coverage.
        cite = citation_coverage_factor(request.citation_coverage, request.answer)

        return [
            FactorCalculator(
                name=ConfidenceFactorName.RETRIEVAL_RELEVANCE,
                score=rel["score"],
                weight=weights[ConfidenceFactorName.RETRIEVAL_RELEVANCE.value],
                available=True,
                details=rel.get("details"),
            ),
            FactorCalculator(
                name=ConfidenceFactorName.RERANKER_CONFIDENCE,
                score=rerank["score"],
                weight=weights[ConfidenceFactorName.RERANKER_CONFIDENCE.value],
                available=rerank.get("available", False),
                details=rerank.get("details"),
            ),
            FactorCalculator(
                name=ConfidenceFactorName.SOURCE_AGREEMENT,
                score=src["score"],
                weight=weights[ConfidenceFactorName.SOURCE_AGREEMENT.value],
                available=True,
                details=src.get("details"),
            ),
            FactorCalculator(
                name=ConfidenceFactorName.CHUNK_COVERAGE,
                score=coverage["score"],
                weight=weights[ConfidenceFactorName.CHUNK_COVERAGE.value],
                available=True,
                details=coverage.get("details"),
            ),
            FactorCalculator(
                name=ConfidenceFactorName.CITATION_COVERAGE,
                # When there are no chunks, the citation factor can't be
                # meaningful — even the heuristic should not save us.
                score=cite["score"] if len(request.chunks) > 0 else 0.0,
                weight=weights[ConfidenceFactorName.CITATION_COVERAGE.value],
                available=len(request.chunks) > 0,
                details=cite.get("details"),
            ),
        ]

    @staticmethod
    def _compute_flags(
        request: ConfidenceRequest,
        factors: List[FactorCalculator],
        confidence: float,
    ) -> List[ConfidenceFlag]:
        flags: List[ConfidenceFlag] = []

        # No chunks.
        if not request.chunks:
            flags.append(ConfidenceFlag.EMPTY_CHUNKS)

        # No answer content.
        answer_text = (request.answer.get("executive_summary", "") or "").strip()
        if (
            not answer_text
            and not (request.answer.get("detailed_explanation", "") or "").strip()
        ):
            flags.append(ConfidenceFlag.NO_ANSWER)

        # Citation coverage.
        cite_factor = next(
            (f for f in factors if f.name == ConfidenceFactorName.CITATION_COVERAGE),
            None,
        )
        if cite_factor is not None and cite_factor.raw_score < 0.7:
            flags.append(ConfidenceFlag.LOW_CITATION_COVERAGE)

        # Reranker.
        if request.reranker_scores is None or len(request.reranker_scores) == 0:
            flags.append(ConfidenceFlag.NO_RERANK_SCORES)

        # Single source.
        sources = {
            c.get("source") for c in request.chunks if c.get("source") is not None
        }
        if len(sources) == 1 and request.chunks:
            flags.append(ConfidenceFlag.SINGLE_SOURCE)

        # Low chunk count.
        if 0 < len(request.chunks) < 3:
            flags.append(ConfidenceFlag.LOW_CHUNK_COUNT)

        # High score variance (using chunk scores).
        scores = [float(c.get("score", 0.0) or 0.0) for c in request.chunks]
        if len(scores) >= 3:
            mean = sum(scores) / len(scores)
            if mean > 0:
                variance = sum((s - mean) ** 2 for s in scores) / len(scores)
                stdev = variance**0.5
                if stdev / mean > 0.4:  # coefficient of variation > 0.4
                    flags.append(ConfidenceFlag.HIGH_SCORE_VARIANCE)

        return flags


# ─── Factory ────────────────────────────────────────────────────────────────


def build_default_confidence_service() -> ConfidenceService:
    return ConfidenceService()


__all__ = ["ConfidenceService", "build_default_confidence_service"]
