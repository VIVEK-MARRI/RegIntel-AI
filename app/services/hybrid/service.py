"""Hybrid Retrieval Service.

Orchestrates dense semantic search and keyword-based BM25 search, delegating
all score fusion to the ``FusionEngine``.

Milestone 4 enhancements:
- Concurrent dense + BM25 retrieval via asyncio.gather for lower latency.
- Query analysis integration: the ``QueryAnalyzer`` is invoked before retrieval
  to classify the query and recommend an optimal retrieval strategy.
- Structured telemetry: every call produces a ``RetrievalTelemetry`` snapshot
  that can be persisted by the analytics layer.
"""

import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from app.models.document import SourceEnum
from app.schemas.hybrid import (
    RetrievalStrategy,
    FusionMethod,
    RetrievalResult,
    HybridSearchResponse,
)
from app.services.embedding.retrieval import RetrievalService
from app.services.bm25.base import BM25Retriever
from app.services.hybrid.strategy import RetrievalStrategyManager
from app.services.fusion.engine import FusionEngine
from app.schemas.fusion import FusionConfig
from app.services.fusion.ranking import compute_overlap
from app.services.query_analysis.service import QueryAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class RetrievalTelemetry:
    """Structured telemetry for a single hybrid retrieval operation.

    Captured by the analytics layer for observability and performance tracking.
    """

    query: str
    query_type: str = "unknown"
    query_confidence: float = 0.0
    recommended_strategy: str = "hybrid"
    effective_strategy: str = "hybrid"
    fusion_method: str = "rrf"
    dense_latency_ms: float = 0.0
    bm25_latency_ms: float = 0.0
    fusion_latency_ms: float = 0.0
    overall_latency_ms: float = 0.0
    dense_count: int = 0
    bm25_count: int = 0
    fused_count: int = 0
    overlap_count: int = 0
    overlap_pct: float = 0.0
    results_returned: int = 0
    dense_weight: float = 0.5
    bm25_weight: float = 0.5
    strategy_source: str = "explicit"  # "explicit" or "query_analyzer"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "query_type": self.query_type,
            "query_confidence": self.query_confidence,
            "recommended_strategy": self.recommended_strategy,
            "effective_strategy": self.effective_strategy,
            "fusion_method": self.fusion_method,
            "dense_latency_ms": self.dense_latency_ms,
            "bm25_latency_ms": self.bm25_latency_ms,
            "fusion_latency_ms": self.fusion_latency_ms,
            "overall_latency_ms": self.overall_latency_ms,
            "dense_count": self.dense_count,
            "bm25_count": self.bm25_count,
            "fused_count": self.fused_count,
            "overlap_count": self.overlap_count,
            "overlap_pct": self.overlap_pct,
            "results_returned": self.results_returned,
            "dense_weight": self.dense_weight,
            "bm25_weight": self.bm25_weight,
            "strategy_source": self.strategy_source,
        }


class HybridRetriever:
    """Orchestrates dense semantic search and keyword-based BM25 search.

    Combines results using either Reciprocal Rank Fusion (RRF) or Min-Max
    Normalized Weighted Sum via the ``FusionEngine``.

    Milestone 4 features:
    - Concurrent dense + BM25 via ``asyncio.gather`` for lower p95 latency.
    - Optional ``QueryAnalyzer`` integration for automatic strategy selection.
    - Structured ``RetrievalTelemetry`` for analytics persistence.
    """

    def __init__(
        self,
        retrieval_service: RetrievalService,
        bm25_retriever: BM25Retriever,
        fusion_engine: Optional[FusionEngine] = None,
        query_analyzer: Optional[QueryAnalyzer] = None,
    ):
        self.retrieval_service = retrieval_service
        self.bm25_retriever = bm25_retriever
        self.fusion_engine = fusion_engine or FusionEngine()
        self.query_analyzer = query_analyzer

    async def retrieve_dense(
        self,
        query: str,
        top_k: int = 5,
        source: Optional[SourceEnum] = None,
        document_id: Optional[uuid.UUID] = None,
    ) -> List[Dict[str, Any]]:
        """Wraps semantic retrieval service."""
        dense_response = await self.retrieval_service.retrieve(
            query=query,
            top_k=top_k,
            source=source,
            document_id=document_id,
        )
        return dense_response.get("results", [])

    async def retrieve_bm25(
        self,
        query: str,
        top_k: int = 5,
        source: Optional[SourceEnum] = None,
        document_id: Optional[uuid.UUID] = None,
    ) -> List[Dict[str, Any]]:
        """Wraps BM25 keyword search."""
        return await self.bm25_retriever.retrieve(
            query=query,
            top_k=top_k,
            source=source,
            document_id=document_id,
        )

    async def retrieve_hybrid(
        self,
        query: str,
        top_n: int = 5,
        dense_top_k: int = 10,
        bm25_top_k: int = 10,
        dense_weight: float = 0.5,
        bm25_weight: float = 0.5,
        strategy: RetrievalStrategy = RetrievalStrategy.HYBRID,
        fusion_method: FusionMethod = FusionMethod.RRF,
        rrf_k: int = 60,
        source: Optional[SourceEnum] = None,
        document_id: Optional[uuid.UUID] = None,
        use_query_analysis: bool = True,
    ) -> HybridSearchResponse:
        """Coordinates and fuses dense and keyword search queries.

        Milestone 4: dense and BM25 retrieval run concurrently via
        ``asyncio.gather`` for lower end-to-end latency.

        When *use_query_analysis* is True and a ``QueryAnalyzer`` is
        configured, the query is classified before retrieval and the
        recommended strategy / weights may override the caller defaults.
        """
        start_overall = time.perf_counter()

        # ------------------------------------------------------------------
        # 0. Query understanding (optional)
        # ------------------------------------------------------------------
        query_type = "unknown"
        query_confidence = 0.0
        recommended_strategy = strategy.value
        strategy_source = "explicit"

        if use_query_analysis and self.query_analyzer:
            try:
                analysis = self.query_analyzer.analyze(query)
                query_type = analysis.query_type
                query_confidence = analysis.confidence
                recommended_strategy = analysis.optimal_strategy
                strategy_source = "query_analyzer"

                # Override strategy when analyzer confidence is high
                if analysis.confidence >= 0.7:
                    strategy_map = {
                        "bm25": RetrievalStrategy.KEYWORD,
                        "dense": RetrievalStrategy.DENSE,
                        "hybrid": RetrievalStrategy.HYBRID,
                    }
                    strategy = strategy_map.get(analysis.optimal_strategy, strategy)
                    logger.info(
                        "Query analyzer override: type=%s, strategy=%s (confidence=%.2f)",
                        query_type,
                        strategy.value,
                        query_confidence,
                    )
            except Exception as exc:
                logger.warning("Query analysis failed, using defaults: %s", exc)

        # Balance / normalise weights
        d_weight, b_weight = RetrievalStrategyManager.balance_weights(
            dense_weight, bm25_weight
        )

        # ------------------------------------------------------------------
        # 1. Concurrent retrieval
        # ------------------------------------------------------------------
        dense_results: List[Dict[str, Any]] = []
        bm25_results: List[Dict[str, Any]] = []
        dense_latency = 0.0
        bm25_latency = 0.0

        # Build coroutine lists for concurrent execution
        coros = []
        dense_idx = None
        bm25_idx = None

        if strategy in (RetrievalStrategy.DENSE, RetrievalStrategy.HYBRID):
            dense_idx = len(coros)
            coros.append(self.retrieve_dense(query, dense_top_k, source, document_id))
        if strategy in (RetrievalStrategy.KEYWORD, RetrievalStrategy.HYBRID):
            bm25_idx = len(coros)
            coros.append(self.retrieve_bm25(query, bm25_top_k, source, document_id))

        if len(coros) > 1:
            # Run dense and BM25 concurrently
            start_concurrent = time.perf_counter()
            results = await asyncio.gather(*coros, return_exceptions=True)
            concurrent_latency = (time.perf_counter() - start_concurrent) * 1000.0

            if dense_idx is not None:
                d_result = results[dense_idx]
                if isinstance(d_result, Exception):
                    logger.error("Dense retrieval failed: %s", d_result)
                else:
                    dense_results = d_result
                    dense_latency = concurrent_latency
            if bm25_idx is not None:
                b_result = results[bm25_idx]
                if isinstance(b_result, Exception):
                    logger.error("BM25 retrieval failed: %s", b_result)
                else:
                    bm25_results = b_result
                    bm25_latency = concurrent_latency
        elif len(coros) == 1:
            # Single-source strategy
            start_single = time.perf_counter()
            result = await coros[0]
            single_latency = (time.perf_counter() - start_single) * 1000.0
            if dense_idx is not None:
                if not isinstance(result, Exception):
                    dense_results = result
                    dense_latency = single_latency
            elif bm25_idx is not None:
                if not isinstance(result, Exception):
                    bm25_results = result
                    bm25_latency = single_latency

        # ------------------------------------------------------------------
        # 2. Fuse candidates via the FusionEngine
        # ------------------------------------------------------------------
        start_fusion = time.perf_counter()

        if strategy == RetrievalStrategy.DENSE:
            merged = self._wrap_single_source(dense_results, source_name="dense")
        elif strategy == RetrievalStrategy.KEYWORD:
            merged = self._wrap_single_source(bm25_results, source_name="bm25")
        else:
            config = FusionConfig(
                method=fusion_method,
                rrf_k=rrf_k,
                dense_weight=d_weight,
                bm25_weight=b_weight,
            )
            merged = self.fusion_engine.fuse_results(
                dense_results,
                bm25_results,
                config=config,
            )

        # Sort deterministically & slice to top_n
        merged.sort(key=lambda x: (-x["score"], x["chunk_id"]))
        sliced = merged[:top_n]

        fusion_latency = (time.perf_counter() - start_fusion) * 1000.0

        # Overlap diagnostics
        dense_ids = {r["chunk_id"] for r in dense_results}
        bm25_ids = {r["chunk_id"] for r in bm25_results}
        overlap_info = compute_overlap(dense_ids, bm25_ids)

        overall_latency = (time.perf_counter() - start_overall) * 1000.0

        RetrievalTelemetry(
            query=query,
            query_type=query_type,
            query_confidence=query_confidence,
            recommended_strategy=recommended_strategy,
            effective_strategy=strategy.value,
            fusion_method=fusion_method.value,
            dense_latency_ms=dense_latency,
            bm25_latency_ms=bm25_latency,
            fusion_latency_ms=fusion_latency,
            overall_latency_ms=overall_latency,
            dense_count=len(dense_results),
            bm25_count=len(bm25_results),
            fused_count=len(merged),
            overlap_count=overlap_info["overlap_count"],
            overlap_pct=overlap_info["overlap_percentage"],
            results_returned=len(sliced),
            dense_weight=d_weight,
            bm25_weight=b_weight,
            strategy_source=strategy_source,
        )

        metrics = {
            "overall_latency_ms": overall_latency,
            "dense_latency_ms": dense_latency,
            "bm25_latency_ms": bm25_latency,
            "fusion_latency_ms": fusion_latency,
            "dense_count": len(dense_results),
            "bm25_count": len(bm25_results),
            "overlap_count": overlap_info["overlap_count"],
            "overlap_percentage": overlap_info["overlap_percentage"],
            "query_type": query_type,
            "query_confidence": query_confidence,
            "recommended_strategy": recommended_strategy,
            "strategy_source": strategy_source,
        }

        logger.info(
            "Hybrid search complete. Strategy: %s (source=%s), Fusion: %s. "
            "Returned %d results in %.2fms (dense=%.2fms, bm25=%.2fms, fusion=%.2fms). "
            "Overlap: %d (%.1f%%).",
            strategy.value,
            strategy_source,
            fusion_method.value,
            len(sliced),
            overall_latency,
            dense_latency,
            bm25_latency,
            fusion_latency,
            overlap_info["overlap_count"],
            overlap_info["overlap_percentage"],
        )

        return HybridSearchResponse(
            query=query,
            results=[RetrievalResult(**self._to_retrieval_dict(r)) for r in sliced],
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap_single_source(
        results: List[Dict[str, Any]],
        source_name: str,
    ) -> List[Dict[str, Any]]:
        """Wrap single-source results into the unified candidate format."""
        wrapped: List[Dict[str, Any]] = []
        for idx, r in enumerate(results):
            meta = r.get("metadata") or {}
            # Promote BM25 top-level keys into metadata
            for key in ("section", "subsection"):
                if key not in meta and key in r:
                    meta[key] = r[key]

            wrapped.append(
                {
                    "chunk_id": r["chunk_id"],
                    "score": r["score"],
                    "rrf_score": None,
                    "dense_score": r["score"] if source_name == "dense" else None,
                    "bm25_score": r["score"] if source_name == "bm25" else None,
                    "dense_rank": (idx + 1) if source_name == "dense" else None,
                    "bm25_rank": (idx + 1) if source_name == "bm25" else None,
                    "sources": [source_name],
                    "content": r["content"],
                    "metadata": meta,
                }
            )
        return wrapped

    @staticmethod
    def _to_retrieval_dict(candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Project a fused candidate into the ``RetrievalResult`` field set.

        Drops keys like ``rrf_score`` and ``sources`` that are not part of
        the legacy ``RetrievalResult`` schema.
        """
        return {
            "chunk_id": candidate["chunk_id"],
            "score": candidate["score"],
            "dense_score": candidate.get("dense_score"),
            "bm25_score": candidate.get("bm25_score"),
            "dense_rank": candidate.get("dense_rank"),
            "bm25_rank": candidate.get("bm25_rank"),
            "content": candidate.get("content", ""),
            "metadata": candidate.get("metadata", {}),
        }
