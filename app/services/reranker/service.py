"""BGE Reranker Service.

Orchestrates cross-encoder reranking of retrieval candidates.  Accepts raw
candidate dicts (from ``FusionEngine`` or ``RetrievalService``), scores every
(query, chunk) pair using the BGE cross-encoder, and returns the top-K
results sorted by relevance.

Public API
----------
* ``RerankerService.rerank()``  – full pipeline (score → filter → sort → report).
* ``RerankerService.score_candidates()``  – raw scoring only.
* ``RerankerService.benchmark()``  – run benchmark suite.
"""

from __future__ import annotations

import logging
import math
import statistics
import time
from typing import Any, Dict, List, Optional

from app.schemas.reranker import (
    BenchmarkReport,
    BenchmarkResult,
    PrecisionMetrics,
    RerankReport,
    RerankResponse,
    RerankResult,
    ScoreDistribution,
)
from app.services.reranker.model import BGERerankerProvider

logger = logging.getLogger(__name__)


class RerankerService:
    """Service layer for cross-encoder reranking.

    Parameters
    ----------
    provider : BGERerankerProvider
        The underlying model provider that performs inference.
    default_top_k : int
        Fallback top-k when the caller doesn't specify one.
    default_score_threshold : float
        Fallback minimum score threshold.
    """

    def __init__(
        self,
        provider: BGERerankerProvider,
        default_top_k: int = 5,
        default_score_threshold: float = 0.0,
    ) -> None:
        self.provider = provider
        self.default_top_k = default_top_k
        self.default_score_threshold = default_score_threshold

    # ------------------------------------------------------------------
    # Strict output contract (minimal) helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _minimal_result(chunk_id: str, rerank_score: float) -> RerankResult:
        """Create a minimal RerankResult that matches the strict output contract.

        The "strict contract" requirement is:
            {"chunk_id":"...", "rerank_score":0.95}

        Since API responses use `RerankResult`, we keep required fields and
        blank optional diagnostics/content/metadata.
        """
        return RerankResult(
            chunk_id=chunk_id,
            rerank_score=rerank_score,
            content="",
            metadata={},
        )

    # ------------------------------------------------------------------
    # Core scoring
    # ------------------------------------------------------------------

    def score_candidates(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Score each candidate against the query using the cross-encoder.

        Parameters
        ----------
        query : str
            The user query.
        candidates : list[dict]
            Candidate dicts — each must have at least ``chunk_id`` and ``content``.

        Returns
        -------
        list[dict]
            The same candidates augmented with ``rerank_score`` and ``original_rank``.
        """
        if not candidates:
            return []

        pairs = [(query, c["content"]) for c in candidates]
        scoring_result = self.provider.score_pairs_timed(pairs)

        scored: List[Dict[str, Any]] = []
        for idx, candidate in enumerate(candidates):
            scored.append(
                {
                    **candidate,
                    "rerank_score": scoring_result.scores[idx],
                    "original_rank": idx + 1,
                    "scoring_latency_ms": scoring_result.scoring_latency_ms,
                }
            )
        return scored

    def score_candidates_minimal(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Strict scoring output contract.

        Returns list of:
            {"chunk_id": "...", "rerank_score": 0.95}

        Notes
        -----
        - Does not apply threshold filtering.
        - Does not truncate to top_k.
        - Does not include diagnostics fields.
        """
        if not candidates:
            return []

        scored = self.score_candidates(query, candidates)
        return [
            {"chunk_id": s["chunk_id"], "rerank_score": s["rerank_score"]}
            for s in scored
        ]

    # ------------------------------------------------------------------
    # Full reranking pipeline
    # ------------------------------------------------------------------

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        *,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> RerankResponse:
        """Full reranking pipeline.

        1. Score all candidates via the cross-encoder.
        2. Filter by ``score_threshold``.
        3. Sort descending by ``rerank_score`` (tiebreak: ``chunk_id``).
        4. Slice to ``top_k``.
        5. Build diagnostic report with score distribution and precision metrics.

        Parameters
        ----------
        query : str
            The user query.
        candidates : list[dict]
            Candidate dicts with at least ``chunk_id`` and ``content``.
        top_k : int, optional
            Number of top results to return.  Falls back to ``default_top_k``.
        score_threshold : float, optional
            Minimum score to include.  Falls back to ``default_score_threshold``.

        Returns
        -------
        RerankResponse
            Contains the reranked results and a diagnostic report.
        """
        effective_top_k = top_k if top_k is not None else self.default_top_k
        effective_threshold = (
            score_threshold
            if score_threshold is not None
            else self.default_score_threshold
        )

        start = time.perf_counter()

        # 1. Score
        scored = self.score_candidates(query, candidates)
        scoring_latency_ms = scored[0].get("scoring_latency_ms", 0.0) if scored else 0.0

        # 2. Filter by threshold
        filtered = [s for s in scored if s["rerank_score"] >= effective_threshold]

        # 3. Deterministic sort (desc score, asc chunk_id)
        filtered.sort(key=lambda x: (-x["rerank_score"], x["chunk_id"]))

        # 4. Slice
        top_results = filtered[:effective_top_k]

        latency_ms = (time.perf_counter() - start) * 1000

        # 5. Build result objects with new_rank
        results = [
            RerankResult(
                chunk_id=r["chunk_id"],
                rerank_score=r["rerank_score"],
                original_score=r.get("score"),
                original_rank=r.get("original_rank"),
                new_rank=idx + 1,
                content=r.get("content", ""),
                metadata=r.get("metadata", {}),
            )
            for idx, r in enumerate(top_results)
        ]

        # 6. Score distribution metrics
        all_scores = [s["rerank_score"] for s in scored]
        score_distribution = self._compute_score_distribution(all_scores)

        # 7. Precision improvement metrics
        precision_metrics = self._compute_precision_metrics(scored, top_results)

        report = RerankReport(
            model_name=self.provider.get_model_name(),
            candidates_received=len(candidates),
            candidates_returned=len(results),
            candidates_filtered=len(scored) - len(filtered),
            latency_ms=latency_ms,
            scoring_latency_ms=scoring_latency_ms,
            score_min=min(all_scores) if all_scores else None,
            score_max=max(all_scores) if all_scores else None,
            score_mean=statistics.mean(all_scores) if all_scores else None,
            score_threshold_applied=effective_threshold,
            top_k_applied=effective_top_k,
            score_distribution=score_distribution,
            precision_metrics=precision_metrics,
        )

        logger.info(
            "Reranking complete. Model=%s, Received=%d, Returned=%d, "
            "Latency=%.2fms (scoring=%.2fms), ScoreRange=[%.4f, %.4f].",
            report.model_name,
            report.candidates_received,
            report.candidates_returned,
            report.latency_ms,
            report.scoring_latency_ms,
            report.score_min or 0.0,
            report.score_max or 0.0,
        )

        return RerankResponse(query=query, results=results, report=report)

    def rerank_minimal(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        *,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> RerankResponse:
        """Rerank with strict minimal output contract for each result.

        Output contract (per result):
            {"chunk_id": "...", "rerank_score": 0.95}
        """
        effective_top_k = top_k if top_k is not None else self.default_top_k
        effective_threshold = (
            score_threshold
            if score_threshold is not None
            else self.default_score_threshold
        )

        start = time.perf_counter()

        scored = self.score_candidates(query, candidates)
        scoring_latency_ms = scored[0].get("scoring_latency_ms", 0.0) if scored else 0.0

        filtered = [s for s in scored if s["rerank_score"] >= effective_threshold]
        filtered.sort(key=lambda x: (-x["rerank_score"], x["chunk_id"]))
        top_results = filtered[:effective_top_k]

        latency_ms = (time.perf_counter() - start) * 1000

        # Build minimal results; keep rerank diagnostics in report.
        results = [
            self._minimal_result(chunk_id=r["chunk_id"], rerank_score=r["rerank_score"])
            for r in top_results
        ]

        all_scores = [s["rerank_score"] for s in scored]
        score_distribution = self._compute_score_distribution(all_scores)
        precision_metrics = self._compute_precision_metrics(scored, top_results)

        report = RerankReport(
            model_name=self.provider.get_model_name(),
            candidates_received=len(candidates),
            candidates_returned=len(results),
            candidates_filtered=len(scored) - len(filtered),
            latency_ms=latency_ms,
            scoring_latency_ms=scoring_latency_ms,
            score_min=min(all_scores) if all_scores else None,
            score_max=max(all_scores) if all_scores else None,
            score_mean=statistics.mean(all_scores) if all_scores else None,
            score_threshold_applied=effective_threshold,
            top_k_applied=effective_top_k,
            score_distribution=score_distribution,
            precision_metrics=precision_metrics,
        )

        return RerankResponse(query=query, results=results, report=report)

    # ------------------------------------------------------------------
    # Batch reranking
    # ------------------------------------------------------------------

    def rerank_batch(
        self,
        queries: List[str],
        candidates_per_query: List[List[Dict[str, Any]]],
        *,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[RerankResponse]:
        """Rerank candidates for multiple queries in batch.

        Parameters
        ----------
        queries : list[str]
            List of user queries.
        candidates_per_query : list[list[dict]]
            Candidate lists, one per query.
        top_k : int, optional
            Number of top results per query.
        score_threshold : float, optional
            Minimum score threshold.

        Returns
        -------
        list[RerankResponse]
            One response per query.
        """
        if len(queries) != len(candidates_per_query):
            raise ValueError(
                f"queries ({len(queries)}) and candidates_per_query "
                f"({len(candidates_per_query)}) must have the same length."
            )

        return [
            self.rerank(q, c, top_k=top_k, score_threshold=score_threshold)
            for q, c in zip(queries, candidates_per_query)
        ]

    def rerank_batch_minimal(
        self,
        queries: List[str],
        candidates_per_query: List[List[Dict[str, Any]]],
        *,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> List[RerankResponse]:
        """Batch rerank with strict minimal per-result output contract."""
        if len(queries) != len(candidates_per_query):
            raise ValueError(
                f"queries ({len(queries)}) and candidates_per_query "
                f"({len(candidates_per_query)}) must have the same length."
            )

        return [
            self.rerank_minimal(q, c, top_k=top_k, score_threshold=score_threshold)
            for q, c in zip(queries, candidates_per_query)
        ]

    # ------------------------------------------------------------------
    # Benchmark
    # ------------------------------------------------------------------

    def benchmark(
        self,
        queries: List[str],
        candidates_per_query: List[List[Dict[str, Any]]],
        *,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> BenchmarkReport:
        """Run a benchmark suite across multiple queries.

        Measures latency, throughput, and score statistics across all queries.

        Parameters
        ----------
        queries : list[str]
            List of user queries.
        candidates_per_query : list[list[dict]]
            Candidate lists, one per query.
        top_k : int, optional
            Number of top results per query.
        score_threshold : float, optional
            Minimum score threshold.

        Returns
        -------
        BenchmarkReport
            Comprehensive benchmark results.
        """
        effective_top_k = top_k if top_k is not None else self.default_top_k
        effective_threshold = (
            score_threshold
            if score_threshold is not None
            else self.default_score_threshold
        )

        results: List[BenchmarkResult] = []
        total_start = time.perf_counter()

        for query, candidates in zip(queries, candidates_per_query):
            resp = self.rerank(
                query,
                candidates,
                top_k=effective_top_k,
                score_threshold=effective_threshold,
            )
            top_score = resp.results[0].rerank_score if resp.results else 0.0
            results.append(
                BenchmarkResult(
                    query=query,
                    num_candidates=len(candidates),
                    latency_ms=resp.report.latency_ms,
                    scoring_latency_ms=resp.report.scoring_latency_ms,
                    top_k=effective_top_k,
                    score_threshold=effective_threshold,
                    top_score=top_score,
                    candidates_returned=resp.report.candidates_returned,
                )
            )

        total_elapsed_ms = (time.perf_counter() - total_start) * 1000
        latencies = [r.latency_ms for r in results]
        scoring_latencies = [r.scoring_latency_ms for r in results]
        total_candidates = sum(r.num_candidates for r in results)

        report = BenchmarkReport(
            model_name=self.provider.get_model_name(),
            total_queries=len(queries),
            total_candidates=total_candidates,
            avg_latency_ms=statistics.mean(latencies) if latencies else 0.0,
            p50_latency_ms=self._percentile(latencies, 50) if latencies else 0.0,
            p95_latency_ms=self._percentile(latencies, 95) if latencies else 0.0,
            p99_latency_ms=self._percentile(latencies, 99) if latencies else 0.0,
            avg_scoring_latency_ms=statistics.mean(scoring_latencies)
            if scoring_latencies
            else 0.0,
            throughput_qps=(len(queries) / total_elapsed_ms * 1000)
            if total_elapsed_ms > 0
            else 0.0,
            avg_candidates_per_query=total_candidates / len(queries)
            if queries
            else 0.0,
            avg_top_score=statistics.mean([r.top_score for r in results])
            if results
            else 0.0,
            results=results,
        )

        logger.info(
            "Benchmark complete. Queries=%d, AvgLatency=%.2fms, P95=%.2fms, "
            "Throughput=%.2f qps.",
            report.total_queries,
            report.avg_latency_ms,
            report.p95_latency_ms,
            report.throughput_qps,
        )

        return report

    # ------------------------------------------------------------------
    # Convenience: rerank from dicts (fusion engine output)
    # ------------------------------------------------------------------

    def rerank_fusion_results(
        self,
        query: str,
        fusion_results: List[Dict[str, Any]],
        *,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> RerankResponse:
        """Rerank results that came directly from ``FusionEngine.fuse_results()``.

        This is a convenience wrapper that maps the fusion dict keys to the
        fields expected by ``rerank()``.
        """
        candidates = [
            {
                "chunk_id": r["chunk_id"],
                "content": r.get("content", ""),
                "score": r.get("score"),
                "metadata": r.get("metadata", {}),
            }
            for r in fusion_results
        ]
        return self.rerank(
            query,
            candidates,
            top_k=top_k,
            score_threshold=score_threshold,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_score_distribution(scores: List[float]) -> ScoreDistribution:
        """Compute histogram-style score distribution with percentiles."""
        if not scores:
            return ScoreDistribution()

        sorted_scores = sorted(scores)
        n = len(sorted_scores)

        # 10-bin histogram: [0.0-0.1), [0.1-0.2), ..., [0.9-1.0]
        bin_edges = [round(i * 0.1, 1) for i in range(11)]
        counts = [0] * 10
        for s in scores:
            bin_idx = min(int(s / 0.1), 9)
            counts[bin_idx] += 1

        return ScoreDistribution(
            bins=bin_edges,
            counts=counts,
            median=RerankerService._percentile(sorted_scores, 50),
            std_dev=statistics.stdev(sorted_scores) if n > 1 else 0.0,
            p25=RerankerService._percentile(sorted_scores, 25),
            p75=RerankerService._percentile(sorted_scores, 75),
        )

    @staticmethod
    def _compute_precision_metrics(
        all_scored: List[Dict[str, Any]],
        top_results: List[Dict[str, Any]],
    ) -> PrecisionMetrics:
        """Compute precision improvement metrics."""
        if not all_scored or not top_results:
            return PrecisionMetrics()

        # Rank changes
        rank_changes: Dict[str, int] = {"improved": 0, "declined": 0, "unchanged": 0}
        for r in top_results:
            orig_rank = r.get("original_rank", 0)
            # new_rank is position in top_results + 1
            new_rank = top_results.index(r) + 1
            if new_rank < orig_rank:
                rank_changes["improved"] += 1
            elif new_rank > orig_rank:
                rank_changes["declined"] += 1
            else:
                rank_changes["unchanged"] += 1

        # Average score lift: mean of top-k rerank scores vs mean of all candidates
        top_mean = statistics.mean([r["rerank_score"] for r in top_results])
        all_mean = statistics.mean([s["rerank_score"] for s in all_scored])
        avg_score_lift = top_mean - all_mean

        # Top-1 improvement: score of new #1 vs score of original #1
        original_1_score = all_scored[0].get("rerank_score", 0.0) if all_scored else 0.0
        new_1_score = top_results[0]["rerank_score"] if top_results else 0.0
        top1_improvement = new_1_score - original_1_score

        # Spearman rank correlation between original scores and rerank scores
        rank_correlation = None
        if len(all_scored) >= 3:
            try:
                original_scores = [s.get("score", 0.0) or 0.0 for s in all_scored]
                rerank_scores = [s["rerank_score"] for s in all_scored]
                rank_correlation = RerankerService._spearman_correlation(
                    original_scores, rerank_scores
                )
            except Exception:
                rank_correlation = None

        return PrecisionMetrics(
            rank_correlation=rank_correlation,
            avg_score_lift=avg_score_lift,
            top1_improvement=top1_improvement,
            rank_changes=rank_changes,
        )

    @staticmethod
    def _percentile(sorted_data: List[float], p: float) -> float:
        """Compute the p-th percentile from sorted data."""
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return d0 + d1

    @staticmethod
    def _spearman_correlation(x: List[float], y: List[float]) -> Optional[float]:
        """Compute Spearman rank correlation between two lists."""
        n = len(x)
        if n < 3:
            return None

        def _ranks(values: List[float]) -> List[float]:
            indexed = list(enumerate(values))
            indexed.sort(key=lambda t: (t[1], t[0]))
            ranks = [0.0] * len(values)
            i = 0
            while i < len(indexed):
                j = i
                while j < len(indexed) and indexed[j][1] == indexed[i][1]:
                    j += 1
                avg_rank = (i + j - 1) / 2.0 + 1.0
                for k in range(i, j):
                    ranks[indexed[k][0]] = avg_rank
                i = j
            return ranks

        rank_x = _ranks(x)
        rank_y = _ranks(y)

        d_squared = sum((rx - ry) ** 2 for rx, ry in zip(rank_x, rank_y))
        denominator = n * (n**2 - 1)
        if denominator == 0:
            return 0.0
        return 1.0 - (6.0 * d_squared) / denominator
