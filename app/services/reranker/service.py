"""BGE Reranker Service.

Orchestrates cross-encoder reranking of retrieval candidates.  Accepts raw
candidate dicts (from ``FusionEngine`` or ``RetrievalService``), scores every
(query, chunk) pair using the BGE cross-encoder, and returns the top-K
results sorted by relevance.

Public API
----------
* ``RerankerService.rerank()``  – full pipeline (score → filter → sort → report).
* ``RerankerService.score_candidates()``  – raw scoring only.
"""

from __future__ import annotations

import logging
import statistics
import time
from typing import Any, Dict, List, Optional

from app.schemas.reranker import (
    RerankCandidate,
    RerankReport,
    RerankResponse,
    RerankResult,
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
            The same candidates augmented with ``rerank_score``.
        """
        if not candidates:
            return []

        pairs = [(query, c["content"]) for c in candidates]
        scores = self.provider.score_pairs(pairs)

        scored: List[Dict[str, Any]] = []
        for idx, candidate in enumerate(candidates):
            scored.append({
                **candidate,
                "rerank_score": scores[idx],
                "original_rank": idx + 1,
            })
        return scored

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
        5. Build diagnostic report.

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
            score_threshold if score_threshold is not None else self.default_score_threshold
        )

        start = time.perf_counter()

        # 1. Score
        scored = self.score_candidates(query, candidates)

        # 2. Filter by threshold
        filtered = [s for s in scored if s["rerank_score"] >= effective_threshold]

        # 3. Deterministic sort (desc score, asc chunk_id)
        filtered.sort(key=lambda x: (-x["rerank_score"], x["chunk_id"]))

        # 4. Slice
        top_results = filtered[:effective_top_k]

        latency_ms = (time.perf_counter() - start) * 1000

        # 5. Build result objects
        results = [
            RerankResult(
                chunk_id=r["chunk_id"],
                rerank_score=r["rerank_score"],
                original_score=r.get("score"),
                original_rank=r.get("original_rank"),
                content=r.get("content", ""),
                metadata=r.get("metadata", {}),
            )
            for r in top_results
        ]

        # 6. Score distribution metrics
        all_scores = [s["rerank_score"] for s in scored]
        report = RerankReport(
            model_name=self.provider.get_model_name(),
            candidates_received=len(candidates),
            candidates_returned=len(results),
            latency_ms=latency_ms,
            score_min=min(all_scores) if all_scores else None,
            score_max=max(all_scores) if all_scores else None,
            score_mean=statistics.mean(all_scores) if all_scores else None,
            score_threshold_applied=effective_threshold,
            top_k_applied=effective_top_k,
        )

        logger.info(
            "Reranking complete. Model=%s, Received=%d, Returned=%d, "
            "Latency=%.2fms, ScoreRange=[%.4f, %.4f].",
            report.model_name,
            report.candidates_received,
            report.candidates_returned,
            report.latency_ms,
            report.score_min or 0.0,
            report.score_max or 0.0,
        )

        return RerankResponse(query=query, results=results, report=report)

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
            query, candidates, top_k=top_k, score_threshold=score_threshold,
        )
