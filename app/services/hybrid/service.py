import time
import uuid
import logging
from typing import List, Dict, Any, Optional

from app.models.document import SourceEnum
from app.schemas.hybrid import (
    RetrievalStrategy,
    FusionMethod,
    RetrievalResult,
    HybridSearchResponse
)
from app.services.embedding.retrieval import RetrievalService
from app.services.bm25.base import BM25Retriever
from app.services.hybrid.strategy import min_max_normalize, RetrievalStrategyManager

logger = logging.getLogger(__name__)

class HybridRetriever:
    """Orchestrates dense semantic search and keyword-based BM25 search.
    
    Combines results using either Reciprocal Rank Fusion (RRF) or Min-Max Normalized Weighted Sum.
    """

    def __init__(self, retrieval_service: RetrievalService, bm25_retriever: BM25Retriever):
        self.retrieval_service = retrieval_service
        self.bm25_retriever = bm25_retriever

    async def retrieve_dense(
        self,
        query: str,
        top_k: int = 5,
        source: Optional[SourceEnum] = None,
        document_id: Optional[uuid.UUID] = None
    ) -> List[Dict[str, Any]]:
        """Wraps semantic retrieval service."""
        dense_response = await self.retrieval_service.retrieve(
            query=query,
            top_k=top_k,
            source=source,
            document_id=document_id
        )
        return dense_response.get("results", [])

    async def retrieve_bm25(
        self,
        query: str,
        top_k: int = 5,
        source: Optional[SourceEnum] = None,
        document_id: Optional[uuid.UUID] = None
    ) -> List[Dict[str, Any]]:
        """Wraps BM25 keyword search."""
        return await self.bm25_retriever.retrieve(
            query=query,
            top_k=top_k,
            source=source,
            document_id=document_id
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
        document_id: Optional[uuid.UUID] = None
    ) -> HybridSearchResponse:
        """Coordinates and fuses dense and keyword search queries based on the strategy."""
        start_overall = time.perf_counter()
        
        dense_results: List[Dict[str, Any]] = []
        bm25_results: List[Dict[str, Any]] = []
        dense_latency = 0.0
        bm25_latency = 0.0
        
        # Balance/Normalize weights
        d_weight, b_weight = RetrievalStrategyManager.balance_weights(dense_weight, bm25_weight)
        
        # 1. Fetch dense candidates if strategy needs them
        if strategy in [RetrievalStrategy.DENSE, RetrievalStrategy.HYBRID]:
            start_dense = time.perf_counter()
            dense_results = await self.retrieve_dense(
                query=query,
                top_k=dense_top_k,
                source=source,
                document_id=document_id
            )
            dense_latency = (time.perf_counter() - start_dense) * 1000.0

        # 2. Fetch BM25 candidates if strategy needs them
        if strategy in [RetrievalStrategy.KEYWORD, RetrievalStrategy.HYBRID]:
            start_bm25 = time.perf_counter()
            bm25_results = await self.retrieve_bm25(
                query=query,
                top_k=bm25_top_k,
                source=source,
                document_id=document_id
            )
            bm25_latency = (time.perf_counter() - start_bm25) * 1000.0

        # Create dictionaries of chunk details
        dense_map = {r["chunk_id"]: r for r in dense_results}
        bm25_map = {r["chunk_id"]: r for r in bm25_results}
        
        merged_candidates: Dict[str, Dict[str, Any]] = {}
        
        # 3. Fuse Candidates
        if strategy == RetrievalStrategy.DENSE:
            # Dense Only
            for idx, cid in enumerate(dense_map.keys()):
                r = dense_map[cid]
                merged_candidates[cid] = {
                    "chunk_id": cid,
                    "score": r["score"],
                    "dense_score": r["score"],
                    "dense_rank": idx + 1,
                    "bm25_score": None,
                    "bm25_rank": None,
                    "content": r["content"],
                    "metadata": r.get("metadata") or {}
                }
        elif strategy == RetrievalStrategy.KEYWORD:
            # BM25 Only
            for idx, cid in enumerate(bm25_map.keys()):
                r = bm25_map[cid]
                # Synthesize standard metadata dict
                meta = r.get("metadata") or {}
                if "section" not in meta and "section" in r:
                    meta["section"] = r["section"]
                if "subsection" not in meta and "subsection" in r:
                    meta["subsection"] = r["subsection"]
                merged_candidates[cid] = {
                    "chunk_id": cid,
                    "score": r["score"],
                    "dense_score": None,
                    "dense_rank": None,
                    "bm25_score": r["score"],
                    "bm25_rank": idx + 1,
                    "content": r["content"],
                    "metadata": meta
                }
        else:
            # Hybrid fusion (RRF or Weighted Sum)
            if fusion_method == FusionMethod.RRF:
                # Reciprocal Rank Fusion
                all_ids = set(dense_map.keys()).union(bm25_map.keys())
                for cid in all_ids:
                    score = 0.0
                    dense_rank = None
                    bm25_rank = None
                    dense_score = None
                    bm25_score = None
                    content = ""
                    meta = {}

                    if cid in dense_map:
                        dense_idx = list(dense_map.keys()).index(cid)
                        dense_rank = dense_idx + 1
                        dense_score = dense_map[cid]["score"]
                        content = dense_map[cid]["content"]
                        meta.update(dense_map[cid].get("metadata") or {})
                        score += d_weight * (1.0 / (rrf_k + dense_rank))
                        
                    if cid in bm25_map:
                        bm25_idx = list(bm25_map.keys()).index(cid)
                        bm25_rank = bm25_idx + 1
                        bm25_score = bm25_map[cid]["score"]
                        if not content:
                            content = bm25_map[cid]["content"]
                        meta.update(bm25_map[cid].get("metadata") or {})
                        if "section" not in meta and "section" in bm25_map[cid]:
                            meta["section"] = bm25_map[cid]["section"]
                        if "subsection" not in meta and "subsection" in bm25_map[cid]:
                            meta["subsection"] = bm25_map[cid]["subsection"]
                        score += b_weight * (1.0 / (rrf_k + bm25_rank))

                    merged_candidates[cid] = {
                        "chunk_id": cid,
                        "score": score,
                        "dense_score": dense_score,
                        "dense_rank": dense_rank,
                        "bm25_score": bm25_score,
                        "bm25_rank": bm25_rank,
                        "content": content,
                        "metadata": meta
                    }
            else:
                # Min-Max Normalized Weighted Sum
                dense_ids = list(dense_map.keys())
                bm25_ids = list(bm25_map.keys())
                
                raw_dense_scores = [dense_map[cid]["score"] for cid in dense_ids]
                raw_bm25_scores = [bm25_map[cid]["score"] for cid in bm25_ids]
                
                norm_dense_scores = min_max_normalize(raw_dense_scores)
                norm_bm25_scores = min_max_normalize(raw_bm25_scores)
                
                dense_norm_map = {cid: norm_dense_scores[idx] for idx, cid in enumerate(dense_ids)}
                bm25_norm_map = {cid: norm_bm25_scores[idx] for idx, cid in enumerate(bm25_ids)}
                
                all_ids = set(dense_map.keys()).union(bm25_map.keys())
                for cid in all_ids:
                    dense_rank = None
                    bm25_rank = None
                    dense_score = None
                    bm25_score = None
                    content = ""
                    meta = {}
                    
                    norm_dense = 0.0
                    norm_bm25 = 0.0
                    
                    if cid in dense_map:
                        dense_idx = dense_ids.index(cid)
                        dense_rank = dense_idx + 1
                        dense_score = dense_map[cid]["score"]
                        norm_dense = dense_norm_map[cid]
                        content = dense_map[cid]["content"]
                        meta.update(dense_map[cid].get("metadata") or {})
                        
                    if cid in bm25_map:
                        bm25_idx = bm25_ids.index(cid)
                        bm25_rank = bm25_idx + 1
                        bm25_score = bm25_map[cid]["score"]
                        norm_bm25 = bm25_norm_map[cid]
                        if not content:
                            content = bm25_map[cid]["content"]
                        meta.update(bm25_map[cid].get("metadata") or {})
                        if "section" not in meta and "section" in bm25_map[cid]:
                            meta["section"] = bm25_map[cid]["section"]
                        if "subsection" not in meta and "subsection" in bm25_map[cid]:
                            meta["subsection"] = bm25_map[cid]["subsection"]

                    score = d_weight * norm_dense + b_weight * norm_bm25
                    
                    merged_candidates[cid] = {
                        "chunk_id": cid,
                        "score": score,
                        "dense_score": dense_score,
                        "dense_rank": dense_rank,
                        "bm25_score": bm25_score,
                        "bm25_rank": bm25_rank,
                        "content": content,
                        "metadata": meta
                    }

        # 4. Sort deterministically (score descending, chunk id ascending) and slice
        sorted_results = list(merged_candidates.values())
        sorted_results.sort(key=lambda x: (-x["score"], x["chunk_id"]))
        sliced_results = sorted_results[:top_n]
        
        # 5. Calculate overlap diagnostics
        dense_ids = set(dense_map.keys())
        bm25_ids = set(bm25_map.keys())
        overlap_ids = dense_ids.intersection(bm25_ids)
        union_ids = dense_ids.union(bm25_ids)
        
        overlap_count = len(overlap_ids)
        overlap_percentage = (overlap_count / len(union_ids) * 100.0) if union_ids else 0.0
        
        overall_latency = (time.perf_counter() - start_overall) * 1000.0
        
        metrics = {
            "overall_latency_ms": overall_latency,
            "dense_latency_ms": dense_latency,
            "bm25_latency_ms": bm25_latency,
            "dense_count": len(dense_results),
            "bm25_count": len(bm25_results),
            "overlap_count": overlap_count,
            "overlap_percentage": overlap_percentage
        }
        
        logger.info(
            f"Hybrid search complete. Strategy: {strategy.value}, Fusion: {fusion_method.value}. "
            f"Returned {len(sliced_results)} results in {overall_latency:.2f}ms. Overlap: {overlap_count} ({overlap_percentage:.1f}%)."
        )
        
        return HybridSearchResponse(
            query=query,
            results=[RetrievalResult(**r) for r in sliced_results],
            metrics=metrics
        )
