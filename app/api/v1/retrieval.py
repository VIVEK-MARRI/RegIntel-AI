"""Enhanced Search API — Milestone 4 endpoints.

Adds:
* Query analysis endpoint (POST /api/v1/search/analyze)
* Hybrid + Rerank endpoint (POST /api/v1/search/hybrid-rerank)
* Retrieval metrics endpoint (GET /api/v1/retrieval/metrics)
* Enhanced retrieval health endpoint (GET /api/v1/retrieval/health)
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_query_analyzer,
    get_hybrid_retriever,
    get_reranker_service,
    get_bm25_retriever,
    get_retrieval_service,
    get_embedding_provider,
)
from app.schemas.retrieval import (
    HybridRerankSearchRequest,
    HybridRerankSearchResponse,
    QueryAnalysisRequest,
    QueryAnalysisResponse,
    RetrievalDiagnostics,
    RetrievalHealthComponent,
    RetrievalHealthResponse,
    RerankedSearchResult,
)
from app.schemas.hybrid import FusionMethod
from app.services.query_analysis.service import QueryAnalyzer
from app.services.hybrid.service import HybridRetriever
from app.services.hybrid.pipeline import HybridRerankPipeline
from app.services.reranker.service import RerankerService
from app.services.embedding.retrieval import RetrievalService
from app.services.bm25.base import BM25Retriever
from app.services.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Query Analysis ───────────────────────────────────────────────────────────


@router.post(
    "/analyze",
    response_model=QueryAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze query intent and recommend retrieval strategy",
    description="Classifies the query into one of: keyword, circular, regulation, semantic, comparison, definition. Returns the confidence score and recommended retrieval strategy (bm25, dense, hybrid).",
)
async def analyze_query(
    request: QueryAnalysisRequest,
    analyzer: QueryAnalyzer = Depends(get_query_analyzer),
) -> QueryAnalysisResponse:
    try:
        start = time.perf_counter()
        result = analyzer.analyze(request.query)
        elapsed = (time.perf_counter() - start) * 1000.0
        return QueryAnalysisResponse(
            query=result.query,
            query_type=result.query_type,
            confidence=result.confidence,
            optimal_strategy=result.optimal_strategy,
            processing_time_ms=round(elapsed, 2),
        )
    except Exception as e:
        logger.error("Query analysis failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query analysis failed: {str(e)}",
        )


# ─── Hybrid + Rerank Search ─────────────────────────────────────────────────


@router.post(
    "/hybrid-rerank",
    response_model=HybridRerankSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Hybrid retrieval with cross-encoder reranking",
    description=(
        "Full pipeline: query understanding → concurrent dense + BM25 retrieval → "
        "RRF fusion → BGE cross-encoder reranking. "
        "Returns top-K reranked chunks with full diagnostic telemetry."
    ),
)
async def hybrid_rerank_search(
    request: HybridRerankSearchRequest,
    hybrid_retriever: HybridRetriever = Depends(get_hybrid_retriever),
    reranker: RerankerService = Depends(get_reranker_service),
) -> HybridRerankSearchResponse:
    try:
        pipeline = HybridRerankPipeline(hybrid_retriever, reranker)

        effective_rerank_top_k = (
            request.rerank_top_k if request.rerank_top_k else request.fusion_candidate_k
        )

        response = await pipeline.search(
            query=request.query,
            top_k=request.top_k,
            rerank_top_k=effective_rerank_top_k,
            rerank_score_threshold=request.rerank_score_threshold,
            fusion_candidate_k=request.fusion_candidate_k,
            dense_top_k=request.dense_top_k,
            bm25_top_k=request.bm25_top_k,
            dense_weight=request.dense_weight,
            bm25_weight=request.bm25_weight,
            fusion_method=request.fusion_method,
            rrf_k=request.rrf_k,
            source=request.source,
            document_id=request.document_id,
            use_query_analysis=request.use_query_analysis,
        )

        # Map internal response to API schema
        rerank_results = []
        for r in response.results:
            rerank_results.append(
                RerankedSearchResult(
                    chunk_id=r.chunk_id,
                    rerank_score=r.rerank_score,
                    original_score=r.original_score,
                    content=r.content,
                    metadata=r.metadata,
                )
            )

        tel = response.telemetry
        return HybridRerankSearchResponse(
            query=request.query,
            results=rerank_results,
            diagnostics=RetrievalDiagnostics(
                query_type=tel.get("query_type", "unknown"),
                query_confidence=tel.get("query_confidence", 0.0),
                recommended_strategy=tel.get("recommended_strategy", "hybrid"),
                dense_count=tel.get("dense_count", 0),
                bm25_count=tel.get("bm25_count", 0),
                fused_count=tel.get("fused_count", 0),
                overlap_count=tel.get("overlap_count", 0),
                overlap_pct=tel.get("overlap_pct", 0.0),
                dense_latency_ms=tel.get("dense_latency_ms", 0.0),
                bm25_latency_ms=tel.get("bm25_latency_ms", 0.0),
                fusion_latency_ms=tel.get("fusion_latency_ms", 0.0),
                rerank_latency_ms=tel.get("rerank_latency_ms", 0.0),
                total_latency_ms=tel.get("total_latency_ms", 0.0),
            ),
            rerank_model=tel.get("rerank_model", ""),
            rerank_candidates=tel.get("rerank_candidates", 0),
        )
    except Exception as e:
        logger.error("Hybrid+rerank search failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Hybrid+rerank search failed: {str(e)}",
        )


# ─── Retrieval Health ────────────────────────────────────────────────────────


@router.get(
    "/health",
    response_model=RetrievalHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Comprehensive retrieval system health check",
    description="Checks health of all retrieval components: dense, BM25, hybrid, reranker.",
)
async def retrieval_health(
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    bm25_retriever: BM25Retriever = Depends(get_bm25_retriever),
    hybrid_retriever: HybridRetriever = Depends(get_hybrid_retriever),
    reranker: RerankerService = Depends(get_reranker_service),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> RetrievalHealthResponse:
    components: list[RetrievalHealthComponent] = []
    overall_status = "healthy"

    # Check dense retrieval
    try:
        start = time.perf_counter()
        model_name = embedding_provider.get_model_name()
        dim = embedding_provider.get_dimension()
        dense_latency = (time.perf_counter() - start) * 1000.0
        components.append(RetrievalHealthComponent(
            name="dense_retrieval",
            status="healthy",
            latency_ms=round(dense_latency, 2),
            details={"model": model_name, "dimension": dim},
        ))
    except Exception as e:
        components.append(RetrievalHealthComponent(
            name="dense_retrieval",
            status="unhealthy",
            details={"error": str(e)},
        ))
        overall_status = "degraded"

    # Check BM25
    try:
        bm25_ready = hasattr(bm25_retriever, 'is_ready') and bm25_retriever.is_ready()
        bm25_status = "healthy" if bm25_ready else "degraded"
        components.append(RetrievalHealthComponent(
            name="bm25_retrieval",
            status=bm25_status,
            details={"index_ready": bm25_ready},
        ))
        if not bm25_ready and overall_status == "healthy":
            overall_status = "degraded"
    except Exception as e:
        components.append(RetrievalHealthComponent(
            name="bm25_retrieval",
            status="unhealthy",
            details={"error": str(e)},
        ))
        overall_status = "degraded"

    # Check hybrid retriever (wired if its dependencies work)
    try:
        hybrid_ok = (
            hybrid_retriever.retrieval_service is not None
            and hybrid_retriever.bm25_retriever is not None
            and hybrid_retriever.fusion_engine is not None
        )
        components.append(RetrievalHealthComponent(
            name="hybrid_retriever",
            status="healthy" if hybrid_ok else "degraded",
            details={"configured": hybrid_ok},
        ))
        if not hybrid_ok and overall_status == "healthy":
            overall_status = "degraded"
    except Exception as e:
        components.append(RetrievalHealthComponent(
            name="hybrid_retriever",
            status="unhealthy",
            details={"error": str(e)},
        ))
        overall_status = "degraded"

    # Check reranker
    try:
        reranker_healthy = reranker.provider.health_check()
        components.append(RetrievalHealthComponent(
            name="reranker",
            status="healthy" if reranker_healthy else "degraded",
            details={"model": reranker.provider.get_model_name()},
        ))
        if not reranker_healthy and overall_status == "healthy":
            overall_status = "degraded"
    except Exception as e:
        components.append(RetrievalHealthComponent(
            name="reranker",
            status="degraded",
            details={"error": str(e)},
        ))
        if overall_status == "healthy":
            overall_status = "degraded"

    any_unhealthy = any(c.status == "unhealthy" for c in components)
    if any_unhealthy:
        overall_status = "unhealthy"

    return RetrievalHealthResponse(
        status=overall_status,
        components=components,
        timestamp=datetime.now(timezone.utc),
    )
