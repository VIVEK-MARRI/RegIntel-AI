"""Hybrid Retrieval Service.

Orchestrates dense semantic search and keyword-based BM25 search, delegating
all score fusion to the ``FusionEngine``.
"""

import time
import uuid
import logging
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

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Orchestrates dense semantic search and keyword-based BM25 search.

    Combines results using either Reciprocal Rank Fusion (RRF) or Min-Max
    Normalized Weighted Sum via the ``FusionEngine``.
    """

    def __init__(
        self,
        retrieval_service: RetrievalService,
        bm25_retriever: BM25Retriever,
        fusion_engine: Optional[FusionEngine] = None,
    ):
        self.retrieval_service = retrieval_service
        self.bm25_retriever = bm25_retriever
        self.fusion_engine = fusion_engine or FusionEngine()

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
    ) -> HybridSearchResponse:
        """Coordinates and fuses dense and keyword search queries based on the strategy."""
        start_overall = time.perf_counter()

        dense_results: List[Dict[str, Any]] = []
        bm25_results: List[Dict[str, Any]] = []
        dense_latency = 0.0
        bm25_latency = 0.0

        # Balance / normalise weights
        d_weight, b_weight = RetrievalStrategyManager.balance_weights(dense_weight, bm25_weight)

        # 1. Fetch dense candidates if strategy needs them
        if strategy in (RetrievalStrategy.DENSE, RetrievalStrategy.HYBRID):
            start_dense = time.perf_counter()
            dense_results = await self.retrieve_dense(
                query=query, top_k=dense_top_k, source=source, document_id=document_id,
            )
            dense_latency = (time.perf_counter() - start_dense) * 1000.0

        # 2. Fetch BM25 candidates if strategy needs them
        if strategy in (RetrievalStrategy.KEYWORD, RetrievalStrategy.HYBRID):
            start_bm25 = time.perf_counter()
            bm25_results = await self.retrieve_bm25(
                query=query, top_k=bm25_top_k, source=source, document_id=document_id,
            )
            bm25_latency = (time.perf_counter() - start_bm25) * 1000.0

        # ------------------------------------------------------------------
        # 3. Fuse candidates via the FusionEngine
        # ------------------------------------------------------------------
        if strategy == RetrievalStrategy.DENSE:
            # Dense-only: wrap as-is, no fusion needed
            merged = self._wrap_single_source(dense_results, source_name="dense")
        elif strategy == RetrievalStrategy.KEYWORD:
            # BM25-only: wrap as-is, no fusion needed
            merged = self._wrap_single_source(bm25_results, source_name="bm25")
        else:
            # Hybrid: delegate to the FusionEngine
            config = FusionConfig(
                method=fusion_method,
                rrf_k=rrf_k,
                dense_weight=d_weight,
                bm25_weight=b_weight,
            )
            merged = self.fusion_engine.fuse_results(
                dense_results, bm25_results, config=config,
            )

        # 4. Sort deterministically & slice to top_n
        merged.sort(key=lambda x: (-x["score"], x["chunk_id"]))
        sliced = merged[:top_n]

        # 5. Overlap diagnostics
        dense_ids = {r["chunk_id"] for r in dense_results}
        bm25_ids = {r["chunk_id"] for r in bm25_results}
        overlap_info = compute_overlap(dense_ids, bm25_ids)

        overall_latency = (time.perf_counter() - start_overall) * 1000.0

        metrics = {
            "overall_latency_ms": overall_latency,
            "dense_latency_ms": dense_latency,
            "bm25_latency_ms": bm25_latency,
            "dense_count": len(dense_results),
            "bm25_count": len(bm25_results),
            "overlap_count": overlap_info["overlap_count"],
            "overlap_percentage": overlap_info["overlap_percentage"],
        }

        logger.info(
            "Hybrid search complete. Strategy: %s, Fusion: %s. "
            "Returned %d results in %.2fms. Overlap: %d (%.1f%%).",
            strategy.value,
            fusion_method.value,
            len(sliced),
            overall_latency,
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

            wrapped.append({
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
            })
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
