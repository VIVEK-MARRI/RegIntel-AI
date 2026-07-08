"""Hybrid + Rerank Pipeline Service.

End-to-end retrieval pipeline that chains:
  Query Understanding -> Dense Retrieval -> BM25 Retrieval ->
  RRF Fusion -> Cross-Encoder Reranking

This is the primary service for production search, providing the highest
retrieval quality by combining all retrieval and ranking stages.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.models.document import SourceEnum
from app.schemas.hybrid import (
    FusionMethod,
    RetrievalStrategy,
)
from app.services.hybrid.service import HybridRetriever

logger = logging.getLogger(__name__)


@dataclass
class HybridRerankTelemetry:
    """Full-pipeline telemetry for a hybrid retrieval + reranking operation."""
    # Query analysis
    query: str = ""
    query_type: str = "unknown"
    query_confidence: float = 0.0
    recommended_strategy: str = "hybrid"

    # Retrieval
    dense_latency_ms: float = 0.0
    bm25_latency_ms: float = 0.0
    fusion_latency_ms: float = 0.0
    dense_count: int = 0
    bm25_count: int = 0
    fused_count: int = 0
    overlap_count: int = 0
    overlap_pct: float = 0.0

    # Reranking
    rerank_latency_ms: float = 0.0
    rerank_candidates: int = 0
    rerank_results: int = 0
    rerank_model: str = ""

    # Overall
    total_latency_ms: float = 0.0
    results_returned: int = 0

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "query_type": self.query_type,
            "query_confidence": self.query_confidence,
            "recommended_strategy": self.recommended_strategy,
            "dense_latency_ms": self.dense_latency_ms,
            "bm25_latency_ms": self.bm25_latency_ms,
            "fusion_latency_ms": self.fusion_latency_ms,
            "dense_count": self.dense_count,
            "bm25_count": self.bm25_count,
            "fused_count": self.fused_count,
            "overlap_count": self.overlap_count,
            "overlap_pct": self.overlap_pct,
            "rerank_latency_ms": self.rerank_latency_ms,
            "rerank_candidates": self.rerank_candidates,
            "rerank_results": self.rerank_results,
            "rerank_model": self.rerank_model,
            "total_latency_ms": self.total_latency_ms,
            "results_returned": self.results_returned,
        }


class HybridRerankPipeline:
    """End-to-end hybrid retrieval + reranking pipeline.

    Orchestrates the full retrieval flow:
    1. (optional) Query understanding via ``QueryAnalyzer``
    2. Concurrent dense + BM25 retrieval
    3. RRF fusion of candidate lists
    4. Cross-encoder reranking for precision

    Usage:
        pipeline = HybridRerankPipeline(hybrid_retriever, reranker_service)
        response = await pipeline.search("RBI KYC requirements", top_k=5)
    """

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        reranker_service: "RerankerService",
    ):
        self.hybrid_retriever = hybrid_retriever
        self.reranker = reranker_service

    async def search(
        self,
        query: str,
        top_k: int = 5,
        rerank_top_k: Optional[int] = None,
        rerank_score_threshold: float = 0.0,
        fusion_candidate_k: int = 20,
        dense_top_k: int = 20,
        bm25_top_k: int = 20,
        dense_weight: float = 0.5,
        bm25_weight: float = 0.5,
        fusion_method: FusionMethod = FusionMethod.RRF,
        rrf_k: int = 60,
        source: Optional[SourceEnum] = None,
        document_id: Optional[uuid.UUID] = None,
        use_query_analysis: bool = True,
    ) -> "HybridRerankResponse":
        """Execute the full hybrid retrieval + reranking pipeline.

        Args:
            query: User search query.
            top_k: Number of final results to return after reranking.
            rerank_top_k: Max candidates to pass to the reranker
                (defaults to ``fusion_candidate_k``).
            rerank_score_threshold: Minimum cross-encoder score to keep.
            fusion_candidate_k: Number of fused candidates before reranking.
            dense_top_k: Dense candidates to fetch per query.
            bm25_top_k: BM25 candidates to fetch per query.
            dense_weight: Dense fusion weight.
            bm25_weight: BM25 fusion weight.
            fusion_method: RRF or weighted_sum.
            rrf_k: RRF smoothing constant.
            source: Optional source filter (RBI/SEBI).
            document_id: Optional document filter.
            use_query_analysis: Whether to use QueryAnalyzer for strategy selection.

        Returns:
            HybridRerankResponse with reranked results and full telemetry.
        """
        start_total = time.perf_counter()
        telemetry = HybridRerankTelemetry(query=query)

        # ------------------------------------------------------------------
        # Stage 1: Hybrid retrieval (concurrent dense + BM25 + fusion)
        # ------------------------------------------------------------------
        hybrid_response = await self.hybrid_retriever.retrieve_hybrid(
            query=query,
            top_n=fusion_candidate_k,
            dense_top_k=dense_top_k,
            bm25_top_k=bm25_top_k,
            dense_weight=dense_weight,
            bm25_weight=bm25_weight,
            strategy=RetrievalStrategy.HYBRID,
            fusion_method=fusion_method,
            rrf_k=rrf_k,
            source=source,
            document_id=document_id,
            use_query_analysis=use_query_analysis,
        )

        # Extract telemetry from hybrid response metrics
        metrics = hybrid_response.metrics
        telemetry.query_type = metrics.get("query_type", "unknown")
        telemetry.query_confidence = metrics.get("query_confidence", 0.0)
        telemetry.recommended_strategy = metrics.get("recommended_strategy", "hybrid")
        telemetry.dense_latency_ms = metrics.get("dense_latency_ms", 0.0)
        telemetry.bm25_latency_ms = metrics.get("bm25_latency_ms", 0.0)
        telemetry.fusion_latency_ms = metrics.get("fusion_latency_ms", 0.0)
        telemetry.dense_count = metrics.get("dense_count", 0)
        telemetry.bm25_count = metrics.get("bm25_count", 0)
        telemetry.overlap_count = metrics.get("overlap_count", 0)
        telemetry.overlap_pct = metrics.get("overlap_percentage", 0.0)

        # ------------------------------------------------------------------
        # Stage 2: Cross-encoder reranking
        # ------------------------------------------------------------------
        candidates = [
            {
                "chunk_id": r.chunk_id,
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
                "dense_score": r.dense_score,
                "bm25_score": r.bm25_score,
                "dense_rank": r.dense_rank,
                "bm25_rank": r.bm25_rank,
            }
            for r in hybrid_response.results
        ]

        effective_top_k = rerank_top_k if rerank_top_k is not None else top_k

        rerank_response = self.reranker.rerank(
            query=query,
            candidates=candidates,
            top_k=effective_top_k,
            score_threshold=rerank_score_threshold,
        )

        telemetry.rerank_latency_ms = rerank_response.report.latency_ms
        telemetry.rerank_candidates = len(candidates)
        telemetry.rerank_results = len(rerank_response.results)
        telemetry.rerank_model = rerank_response.report.model_name

        # ------------------------------------------------------------------
        # Build final response
        # ------------------------------------------------------------------
        total_latency = (time.perf_counter() - start_total) * 1000.0
        telemetry.total_latency_ms = total_latency
        telemetry.fused_count = len(candidates)
        telemetry.results_returned = len(rerank_response.results)

        logger.info(
            "Hybrid+Rerank pipeline complete. Query='%s', Type=%s, "
            "Dense=%d, BM25=%d, Fused=%d, Reranked=%d, "
            "Total=%.2fms (retrieval=%.2fms, rerank=%.2fms).",
            query[:80],
            telemetry.query_type,
            telemetry.dense_count,
            telemetry.bm25_count,
            telemetry.fused_count,
            telemetry.results_returned,
            total_latency,
            total_latency - telemetry.rerank_latency_ms,
            telemetry.rerank_latency_ms,
        )

        rerank_report_dict = None
        if rerank_response.report:
            rerank_report_dict = rerank_response.report.model_dump()

        return HybridRerankResponse(
            query=query,
            results=rerank_response.results,
            rerank_report=rerank_report_dict,
            telemetry=telemetry.to_dict(),
            hybrid_metrics=metrics,
        )


# ---------------------------------------------------------------------------
# Response schema (defined here to avoid circular imports)
# ---------------------------------------------------------------------------

from pydantic import BaseModel as PydanticBaseModel


class HybridRerankResponse(PydanticBaseModel):
    """Full response from the hybrid retrieval + reranking pipeline."""
    query: str
    results: List  # List[RerankResult]
    rerank_report: Optional[Dict[str, Any]] = None
    telemetry: Dict[str, Any] = {}
    hybrid_metrics: Dict[str, Any] = {}
