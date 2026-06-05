"""Module 5.7 — Answer Evaluation Framework.

Provides:

* :class:`MetricsEngine` — computes each :class:`EvaluationMetric` from
  a :class:`FinalAnswerResponse` plus the original query / chunks.
* :class:`AnswerEvaluator` — orchestrator that runs the metrics and
  returns an :class:`AnswerEvaluationResult`.
* :class:`AnswerBenchmarkRunner` — runs an evaluator over a golden
  dataset and produces an :class:`AnswerEvaluationReport`, with
  baseline-vs-candidate regression detection.
* :class:`AnswerEvaluationService` — top-level service exposed via DI
  to the API.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.schemas.answer_generation import AnswerSection, RetrievedChunk
from app.schemas.attribution import SourceAttribution
from app.schemas.evaluation import (
    AnswerEvaluationReport,
    AnswerEvaluationResult,
    EvaluationMetric,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationStrategy,
    MetricScore,
)
from app.schemas.orchestrator import FinalAnswerResponse
from app.services.citation.mapper import token_overlap
from app.services.observability import track_request

logger = logging.getLogger(__name__)


# ─── Metrics engine ──────────────────────────────────────────────────────


class MetricsEngine:
    """Stateless, dependency-free metrics computations.

    Each method is a pure function: input → score.  The class is
    thread-safe by construction (no shared state).
    """

    # ── Faithfulness ──────────────────────────────────────────────────────

    def faithfulness(self, response: FinalAnswerResponse) -> MetricScore:
        score = response.faithfulness_score
        note = (
            "no hallucination"
            if not response.hallucination_detected
            else "hallucination detected"
        )
        return MetricScore(
            metric=EvaluationMetric.FAITHFULNESS,
            score=score,
            note=note,
            raw={
                "faithfulness_score": score,
                "hallucination_detected": response.hallucination_detected,
            },
        )

    # ── Answer relevance ────────────────────────────────────────────────

    def answer_relevance(
        self, response: FinalAnswerResponse, query: str
    ) -> MetricScore:
        answer_text = " ".join(
            [
                response.answer.executive_summary or "",
                response.answer.detailed_explanation or "",
            ]
        )
        if not answer_text.strip():
            return MetricScore(
                metric=EvaluationMetric.ANSWER_RELEVANCE,
                score=0.0,
                note="empty answer",
                raw={"query": query, "answer_length": 0},
            )
        score = token_overlap(query, answer_text)
        return MetricScore(
            metric=EvaluationMetric.ANSWER_RELEVANCE,
            score=score,
            note=f"query/answer token overlap = {score:.2f}",
            raw={"query": query, "answer_length": len(answer_text)},
        )

    # ── Citation accuracy ──────────────────────────────────────────────

    def citation_accuracy(self, response: FinalAnswerResponse) -> MetricScore:
        # Coverage ratio = cited_claim_count / claim_count (Module 5.2
        # fills these on the AnnotatedText).
        executive = response.citations.executive_summary
        detailed = response.citations.detailed_explanation
        total_claims = executive.claim_count + detailed.claim_count
        cited_claims = executive.cited_claim_count + detailed.cited_claim_count
        if total_claims == 0:
            return MetricScore(
                metric=EvaluationMetric.CITATION_ACCURACY,
                score=0.0,
                note="no claims extracted",
                raw={"total_claims": 0, "cited_claims": 0},
            )
        score = cited_claims / total_claims
        return MetricScore(
            metric=EvaluationMetric.CITATION_ACCURACY,
            score=score,
            note=f"{cited_claims}/{total_claims} claims cited",
            raw={"total_claims": total_claims, "cited_claims": cited_claims},
        )

    # ── Source attribution accuracy ─────────────────────────────────────

    def source_attribution_accuracy(
        self, response: FinalAnswerResponse
    ) -> MetricScore:
        attributions = response.source_attributions
        if not attributions:
            return MetricScore(
                metric=EvaluationMetric.SOURCE_ATTRIBUTION_ACCURACY,
                score=0.0,
                note="no attributions emitted",
                raw={"attribution_count": 0},
            )
        # Accuracy = coverage ratio of attributions (high/medium/low
        # count weighted by their confidence bucket).
        coverage = response.attribution_coverage_ratio
        # Count attributions with valid chunk_id + document_id.
        valid = sum(
            1
            for a in attributions
            if a.chunk_id and a.document_id
        )
        validity = valid / len(attributions)
        score = 0.5 * coverage + 0.5 * validity
        return MetricScore(
            metric=EvaluationMetric.SOURCE_ATTRIBUTION_ACCURACY,
            score=score,
            note=f"coverage={coverage:.2f}, validity={validity:.2f}",
            raw={
                "coverage_ratio": coverage,
                "valid_attributions": valid,
                "total_attributions": len(attributions),
            },
        )

    # ── Completeness ────────────────────────────────────────────────────

    def completeness(
        self,
        response: FinalAnswerResponse,
        chunks: List[RetrievedChunk],
    ) -> MetricScore:
        # Completeness = did the answer cover the major concepts in the
        # chunks.  Score is the max token-overlap between the answer
        # and the most-similar chunk.
        answer_text = " ".join(
            [
                response.answer.executive_summary or "",
                response.answer.detailed_explanation or "",
            ]
        )
        if not chunks or not answer_text.strip():
            return MetricScore(
                metric=EvaluationMetric.COMPLETENESS,
                score=0.0,
                note="no chunks or empty answer",
                raw={"chunks": len(chunks), "answer_length": 0},
            )
        scores = [token_overlap(answer_text, c.content) for c in chunks]
        score = max(scores) if scores else 0.0
        return MetricScore(
            metric=EvaluationMetric.COMPLETENESS,
            score=score,
            note=f"max chunk overlap = {score:.2f}",
            raw={"chunks": len(chunks), "max_overlap": score, "scores": scores},
        )

    # ── Groundedness ────────────────────────────────────────────────────

    def groundedness(self, response: FinalAnswerResponse) -> MetricScore:
        # Groundedness = average similarity of supported claims to
        # their cited chunks.  We reuse citation accuracy as a proxy
        # when claim-level grounding info isn't available.
        ca = self.citation_accuracy(response).score
        # Weighted: 60% citation accuracy + 40% faithfulness.
        score = 0.6 * ca + 0.4 * response.faithfulness_score
        return MetricScore(
            metric=EvaluationMetric.GROUNDEDNESS,
            score=score,
            note=f"0.6*citation_accuracy + 0.4*faithfulness = {score:.2f}",
            raw={"citation_accuracy": ca, "faithfulness": response.faithfulness_score},
        )

    # ── Hallucination rate ─────────────────────────────────────────────

    def hallucination_rate(self, response: FinalAnswerResponse) -> MetricScore:
        rate = 1.0 if response.hallucination_detected else 0.0
        return MetricScore(
            metric=EvaluationMetric.HALLUCINATION_RATE,
            score=1.0 - rate,  # higher is better
            note=(
                "no hallucination"
                if not response.hallucination_detected
                else "hallucination detected"
            ),
            raw={"hallucination_detected": response.hallucination_detected},
        )

    # ── Evidence coverage ─────────────────────────────────────────────

    def evidence_coverage(self, response: FinalAnswerResponse) -> MetricScore:
        # Evidence coverage = fraction of attribution slots that have
        # an actual chunk reference.  Uses Module 5.5's coverage.
        return MetricScore(
            metric=EvaluationMetric.EVIDENCE_COVERAGE,
            score=response.attribution_coverage_ratio,
            note=f"attribution coverage = {response.attribution_coverage_ratio:.2f}",
            raw={"coverage_ratio": response.attribution_coverage_ratio},
        )

    # ── Orchestration ──────────────────────────────────────────────────

    def compute_all(
        self,
        *,
        response: FinalAnswerResponse,
        query: str,
        chunks: List[RetrievedChunk],
        metrics: Optional[Sequence[EvaluationMetric]] = None,
    ) -> List[MetricScore]:
        all_metrics: List[Tuple[EvaluationMetric, Any]] = [
            (EvaluationMetric.FAITHFULNESS, lambda: self.faithfulness(response)),
            (EvaluationMetric.ANSWER_RELEVANCE, lambda: self.answer_relevance(response, query)),
            (EvaluationMetric.CITATION_ACCURACY, lambda: self.citation_accuracy(response)),
            (
                EvaluationMetric.SOURCE_ATTRIBUTION_ACCURACY,
                lambda: self.source_attribution_accuracy(response),
            ),
            (EvaluationMetric.COMPLETENESS, lambda: self.completeness(response, chunks)),
            (EvaluationMetric.GROUNDEDNESS, lambda: self.groundedness(response)),
            (EvaluationMetric.HALLUCINATION_RATE, lambda: self.hallucination_rate(response)),
            (EvaluationMetric.EVIDENCE_COVERAGE, lambda: self.evidence_coverage(response)),
        ]
        selected = metrics or [m for m, _ in all_metrics]
        out: List[MetricScore] = []
        for m, fn in all_metrics:
            if m in selected:
                out.append(fn())
        return out


# ─── Answer evaluator ─────────────────────────────────────────────────────


class AnswerEvaluator:
    """Single-response evaluator."""

    def __init__(self, *, engine: Optional[MetricsEngine] = None) -> None:
        self.engine = engine or MetricsEngine()

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        # Re-hydrate chunks from dicts.
        chunks: List[RetrievedChunk] = []
        for raw in request.chunks:
            try:
                chunks.append(RetrievedChunk.model_validate(raw))
            except Exception:
                continue
        t0 = time.perf_counter()
        scores = self.engine.compute_all(
            response=request.response,
            query=request.query,
            chunks=chunks,
            metrics=request.metrics,
        )
        aggregate = (
            sum(s.score for s in scores) / len(scores) if scores else 0.0
        )
        hr = next(
            (
                1.0 - s.score
                for s in scores
                if s.metric == EvaluationMetric.HALLUCINATION_RATE
            ),
            0.0,
        )
        result = AnswerEvaluationResult(
            strategy=request.strategy,
            scores=scores,
            aggregate_score=aggregate,
            hallucination_rate=hr,
            notes=[],
            metadata={
                "latency_ms": (time.perf_counter() - t0) * 1000.0,
                "metrics_count": len(scores),
            },
        )
        return EvaluationResponse(query=request.query, result=result)


# ─── Benchmark runner ─────────────────────────────────────────────────────


class AnswerBenchmarkRunner:
    """Runs an evaluator over a golden dataset and produces a report."""

    def __init__(self, *, evaluator: Optional[AnswerEvaluator] = None) -> None:
        self.evaluator = evaluator or AnswerEvaluator()

    def run(
        self,
        cases: Iterable[Dict[str, Any]],
        *,
        baseline_results: Optional[List[AnswerEvaluationResult]] = None,
    ) -> AnswerEvaluationReport:
        results: List[AnswerEvaluationResult] = []
        for case in cases:
            request = EvaluationRequest(
                response=case["response"],
                query=case["query"],
                chunks=case.get("chunks", []),
                strategy=EvaluationStrategy(case.get("strategy", "candidate")),
                metrics=case.get("metrics"),
            )
            resp = self.evaluator.evaluate(request)
            results.append(resp.result)

        # Aggregate per-metric.
        agg: Dict[EvaluationMetric, List[float]] = {}
        for r in results:
            for s in r.scores:
                agg.setdefault(s.metric, []).append(s.score)
        agg_metrics = {m.value: statistics.mean(v) for m, v in agg.items() if v}

        avg_agg = (
            statistics.mean([r.aggregate_score for r in results]) if results else 0.0
        )
        avg_hr = (
            statistics.mean([r.hallucination_rate for r in results]) if results else 0.0
        )

        # Regression detection.
        regression_detected = False
        regression_delta = 0.0
        if baseline_results:
            baseline_avg = (
                statistics.mean([r.aggregate_score for r in baseline_results])
                if baseline_results
                else 0.0
            )
            regression_delta = avg_agg - baseline_avg
            regression_detected = regression_delta < -0.02  # 2% threshold

        return AnswerEvaluationReport(
            total_cases=len(results),
            results=results,
            aggregate_metrics=agg_metrics,
            average_aggregate_score=avg_agg,
            average_hallucination_rate=avg_hr,
            regression_detected=regression_detected,
            regression_delta=regression_delta,
        )


# ─── Top-level service ─────────────────────────────────────────────────────


class AnswerEvaluationService:
    """DI-friendly service that wraps the evaluator and the runner."""

    def __init__(
        self,
        *,
        evaluator: Optional[AnswerEvaluator] = None,
        runner: Optional[AnswerBenchmarkRunner] = None,
    ) -> None:
        self.evaluator = evaluator or AnswerEvaluator()
        self.runner = runner or AnswerBenchmarkRunner(evaluator=self.evaluator)

    def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        with track_request(
            endpoint="/api/v1/evaluation/evaluate",
            strategy="answer_evaluation",
        ) as ctx:
            return self.evaluator.evaluate(request)

    def benchmark(
        self,
        cases: List[Dict[str, Any]],
        *,
        baseline_results: Optional[List[AnswerEvaluationResult]] = None,
    ) -> AnswerEvaluationReport:
        with track_request(
            endpoint="/api/v1/evaluation/benchmark",
            strategy="answer_evaluation",
        ) as ctx:
            return self.runner.run(cases, baseline_results=baseline_results)


def build_default_evaluation_service() -> AnswerEvaluationService:
    return AnswerEvaluationService()


__all__ = [
    "AnswerBenchmarkRunner",
    "AnswerEvaluationService",
    "AnswerEvaluator",
    "MetricsEngine",
    "build_default_evaluation_service",
]
