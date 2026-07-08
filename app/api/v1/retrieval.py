"""Module 4.8 — Production-Grade Hybrid Search API Layer.

Endpoints (mounted under ``/api/v1``):

* ``POST /search/dense``        — dense semantic search.
* ``POST /search/bm25``         — BM25 keyword search.
* ``POST /search/hybrid``       — flagship hybrid + optional BGE rerank.
* ``GET  /retrieval/metrics``   — aggregated retrieval metrics.
* ``GET  /retrieval/health``    — dependency health check.

All endpoints:

* Are async-first.
* Validate request bodies with the Pydantic v2 contracts in
  ``app.schemas.hybrid_search``.
* Wrap their work in the ``track_request`` observability context manager so
  per-request latency / error / strategy counters are always recorded.
* Emit structured ``logger.info`` events that downstream log aggregators
  can correlate via ``request_id``.
* Reuse the existing service layer (``RetrievalService``, ``BM25Service``,
  ``HybridRetriever``, ``HybridRerankPipeline``, ``RerankerService``,
  ``QueryAnalyzer``, ``AnalyticsService``) — no duplicated business logic.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_bm25_service,
    get_hybrid_retriever,
    get_query_analyzer,
    get_reranker_service,
    get_retrieval_service,
)
from app.core.database import get_db_session
from app.schemas.hybrid_search import (
    BM25SearchRequest,
    DenseSearchRequest,
    HealthCheck,
    HybridSearchDiagnostics,
    HybridSearchRequest,
    HybridSearchResponse,
    RetrievalHealthResponse,
    RetrievalMetricsResponse,
    SearchResultItem,
    SearchResponse,
    SearchStrategy,
)
from app.services.analytics.service import AnalyticsService
from app.services.bm25.bm25_service import BM25Service
from app.services.bm25.retriever import IndexStatus
from app.services.embedding.retrieval import RetrievalService
from app.services.hybrid.service import HybridRetriever
from app.services.observability import (
    get_metrics,
    log_search_event,
    track_request,
)
from app.services.query_analysis.service import QueryAnalyzer
from app.services.reranker.service import RerankerService

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _to_search_result_item(
    *,
    chunk_id: str,
    score: float,
    document_id: Optional[str] = None,
    page_number: Optional[int] = None,
    content: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    rank: Optional[int] = None,
) -> SearchResultItem:
    """Normalize an internal result dict into the public API schema."""
    meta = dict(metadata or {})
    if document_id is None and isinstance(meta.get("document_id"), str):
        document_id = meta["document_id"]
    if page_number is None and isinstance(meta.get("page_number"), int):
        page_number = meta["page_number"]
    return SearchResultItem(
        chunk_id=str(chunk_id),
        document_id=str(document_id) if document_id else None,
        score=float(score),
        page_number=page_number,
        content=content,
        metadata=meta,
        rank=rank,
    )


def _build_strategy_distribution() -> Dict[str, int]:
    """Return a snapshot of the in-process API metrics counters."""
    metrics = get_metrics()
    return {
        "dense": metrics.counters.get("dense", 0),
        "bm25": metrics.counters.get("bm25", 0),
        "hybrid": metrics.counters.get("hybrid", 0),
        "hybrid_rerank": metrics.counters.get("hybrid_rerank", 0),
        "errors": metrics.counters.get("errors", 0),
    }


# ─── Dense Search ─────────────────────────────────────────────────────────────


@router.post(
    "/search/dense",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Dense (semantic) vector search over regulatory chunks",
    description=(
        "Encodes the query with the configured embedding model and runs a "
        "vector similarity search. Supports optional source / document / "
        "min-score filters and the standard distance metrics "
        "(cosine, inner_product, l2)."
    ),
    tags=["search"],
)
async def dense_search(
    request: DenseSearchRequest,
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
) -> SearchResponse:
    request_id = uuid.uuid4().hex
    endpoint_path = "/api/v1/search/dense"
    started = time.perf_counter()

    with track_request(endpoint=endpoint_path, strategy="dense") as ctx:
        ctx.request_id = request_id
        try:
            response = await retrieval_service.retrieve(
                query=request.query,
                top_k=request.top_k,
                score_threshold=request.filters.min_score or 0.0,
                distance_metric=request.distance_metric,
                source=request.filters.source,
                document_id=request.filters.document_id,
            )
        except Exception as exc:  # noqa: BLE001 - surface as 500
            logger.exception("Dense search failed (request_id=%s)", request_id)
            log_search_event(
                "dense_search_failed",
                ctx,
                extra={"error": str(exc), "query": request.query},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Dense search failed: {exc}",
            ) from exc

        raw_results = response.get("results", []) or []
        items: List[SearchResultItem] = []
        for idx, hit in enumerate(raw_results, start=1):
            meta = hit.get("metadata") or {}
            items.append(
                _to_search_result_item(
                    chunk_id=hit.get("chunk_id"),
                    score=hit.get("score", 0.0),
                    document_id=meta.get("document_id"),
                    page_number=meta.get("page_number"),
                    content=hit.get("content"),
                    metadata=meta,
                    rank=idx,
                )
            )

        latency_ms = (time.perf_counter() - started) * 1000.0

        log_search_event(
            "dense_search_completed",
            ctx,
            extra={
                "query": request.query,
                "latency_ms": round(latency_ms, 3),
                "total_results": len(items),
            },
        )

        return SearchResponse(
            query=request.query,
            strategy=SearchStrategy.DENSE.value,
            latency_ms=round(latency_ms, 3),
            total_results=len(items),
            results=items,
            request_id=request_id,
        )


# ─── BM25 Search ──────────────────────────────────────────────────────────────


@router.post(
    "/search/bm25",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="BM25 keyword search over the in-memory lexical index",
    description=(
        "Runs BM25 ranking against the in-memory lexical index. Supports "
        "source / document / min-score filters and a configurable "
        "score threshold."
    ),
    tags=["search"],
)
async def bm25_search(
    request: BM25SearchRequest,
    bm25_service: BM25Service = Depends(get_bm25_service),
) -> SearchResponse:
    request_id = uuid.uuid4().hex
    endpoint_path = "/api/v1/search/bm25"
    started = time.perf_counter()

    with track_request(endpoint=endpoint_path, strategy="bm25") as ctx:
        ctx.request_id = request_id
        try:
            source_filter = (
                [request.filters.source.value]
                if request.filters.source is not None
                else None
            )
            document_filter = (
                [str(request.filters.document_id)]
                if request.filters.document_id is not None
                else None
            )

            response = bm25_service.search(
                query=request.query,
                top_k=request.top_k,
                source_filter=source_filter,
                document_filter=document_filter,
                score_threshold=request.score_threshold,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("BM25 search failed (request_id=%s)", request_id)
            log_search_event(
                "bm25_search_failed",
                ctx,
                extra={"error": str(exc), "query": request.query},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"BM25 search failed: {exc}",
            ) from exc

        items: List[SearchResultItem] = []
        for hit in response.results:
            items.append(
                _to_search_result_item(
                    chunk_id=hit.chunk_id,
                    score=hit.bm25_score,
                    document_id=hit.document_id or None,
                    page_number=None,
                    content=hit.content_preview or None,
                    metadata={
                        "section": hit.section,
                        "subsection": hit.subsection,
                        "document_title": hit.document_title,
                        "source": hit.source,
                        "rank": hit.rank,
                    },
                    rank=hit.rank or None,
                )
            )

        latency_ms = (time.perf_counter() - started) * 1000.0

        log_search_event(
            "bm25_search_completed",
            ctx,
            extra={
                "query": request.query,
                "latency_ms": round(latency_ms, 3),
                "total_results": len(items),
            },
        )

        return SearchResponse(
            query=request.query,
            strategy=SearchStrategy.BM25.value,
            latency_ms=round(latency_ms, 3),
            total_results=len(items),
            results=items,
            request_id=request_id,
        )


# ─── Hybrid Search ────────────────────────────────────────────────────────────


@router.post(
    "/search/hybrid",
    response_model=HybridSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Hybrid dense + BM25 search with optional BGE reranking",
    description=(
        "Flagship endpoint. Runs query classification, then concurrent "
        "dense + BM25 retrieval, fuses with the requested fusion method "
        "(RRF or weighted sum), and optionally reranks with the BGE "
        "cross-encoder. Returns classified query type, full pipeline "
        "diagnostics, and the top-K fused results."
    ),
    tags=["search"],
)
async def hybrid_search(
    request: HybridSearchRequest,
    hybrid_retriever: HybridRetriever = Depends(get_hybrid_retriever),
    reranker: RerankerService = Depends(get_reranker_service),
    query_analyzer: QueryAnalyzer = Depends(get_query_analyzer),
) -> HybridSearchResponse:
    request_id = uuid.uuid4().hex
    endpoint_path = "/api/v1/search/hybrid"
    started = time.perf_counter()

    strategy_label = (
        SearchStrategy.HYBRID_RERANK.value
        if request.enable_reranking
        else SearchStrategy.HYBRID.value
    )

    with track_request(endpoint=endpoint_path, strategy=strategy_label) as ctx:
        ctx.request_id = request_id
        # ── 1. Query classification ───────────────────────────────────────
        query_type = "unknown"
        query_confidence = 0.0
        recommended_strategy = "hybrid"
        try:
            analysis = query_analyzer.analyze(request.query)
            query_type = analysis.query_type
            query_confidence = analysis.confidence
            recommended_strategy = analysis.optimal_strategy
        except Exception as exc:  # noqa: BLE001
            logger.warning("Query analysis failed (request_id=%s): %s", request_id, exc)

        # ── 2. Hybrid retrieval ──────────────────────────────────────────
        try:
            hybrid_response = await hybrid_retriever.retrieve_hybrid(
                query=request.query,
                top_n=request.fusion_candidate_k,
                dense_top_k=request.dense_top_k,
                bm25_top_k=request.bm25_top_k,
                dense_weight=request.dense_weight,
                bm25_weight=request.bm25_weight,
                fusion_method=request.fusion_method,
                rrf_k=request.rrf_k,
                source=request.filters.source,
                document_id=request.filters.document_id,
                use_query_analysis=request.use_query_analysis,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Hybrid retrieval failed (request_id=%s)", request_id)
            log_search_event(
                "hybrid_search_failed",
                ctx,
                extra={"error": str(exc), "query": request.query},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Hybrid retrieval failed: {exc}",
            ) from exc

        # ── 3. Optional reranking ────────────────────────────────────────
        candidates: List[Dict[str, Any]] = []
        for r in hybrid_response.results:
            candidates.append(
                {
                    "chunk_id": r.chunk_id,
                    "score": r.score,
                    "dense_score": r.dense_score,
                    "bm25_score": r.bm25_score,
                    "dense_rank": r.dense_rank,
                    "bm25_rank": r.bm25_rank,
                    "content": r.content,
                    "metadata": r.metadata,
                }
            )

        rerank_used = False
        rerank_model: Optional[str] = None
        rerank_latency_ms = 0.0
        final_items: List[SearchResultItem] = []
        diagnostics_metrics = dict(hybrid_response.metrics or {})

        if request.enable_reranking and candidates:
            rerank_start = time.perf_counter()
            try:
                rerank_response = reranker.rerank(
                    query=request.query,
                    candidates=candidates,
                    top_k=request.top_k,
                    score_threshold=0.0,
                )
                rerank_latency_ms = (time.perf_counter() - rerank_start) * 1000.0
                rerank_used = True
                ctx.rerank_used = True
                rerank_model = rerank_response.report.model_name
                for idx, r in enumerate(rerank_response.results, start=1):
                    final_items.append(
                        _to_search_result_item(
                            chunk_id=r.chunk_id,
                            score=r.rerank_score,
                            document_id=(r.metadata or {}).get("document_id"),
                            page_number=(r.metadata or {}).get("page_number"),
                            content=r.content,
                            metadata=r.metadata,
                            rank=idx,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Reranking failed (request_id=%s); falling back to fusion order: %s",
                    request_id,
                    exc,
                )
                rerank_latency_ms = (time.perf_counter() - rerank_start) * 1000.0
                final_items = [
                    _to_search_result_item(
                        chunk_id=c["chunk_id"],
                        score=c["score"],
                        document_id=(c.get("metadata") or {}).get("document_id"),
                        page_number=(c.get("metadata") or {}).get("page_number"),
                        content=c.get("content"),
                        metadata=c.get("metadata"),
                        rank=idx,
                    )
                    for idx, c in enumerate(candidates[: request.top_k], start=1)
                ]
        else:
            final_items = [
                _to_search_result_item(
                    chunk_id=c["chunk_id"],
                    score=c["score"],
                    document_id=(c.get("metadata") or {}).get("document_id"),
                    page_number=(c.get("metadata") or {}).get("page_number"),
                    content=c.get("content"),
                    metadata=c.get("metadata"),
                    rank=idx,
                )
                for idx, c in enumerate(candidates[: request.top_k], start=1)
            ]

        latency_ms = (time.perf_counter() - started) * 1000.0

        diagnostics = HybridSearchDiagnostics(
            query_type=query_type,
            query_confidence=query_confidence,
            recommended_strategy=recommended_strategy,
            dense_count=diagnostics_metrics.get("dense_count", 0),
            bm25_count=diagnostics_metrics.get("bm25_count", 0),
            fused_count=diagnostics_metrics.get("fused_count", len(candidates)),
            overlap_count=diagnostics_metrics.get("overlap_count", 0),
            overlap_pct=diagnostics_metrics.get("overlap_percentage", 0.0),
            dense_latency_ms=diagnostics_metrics.get("dense_latency_ms", 0.0),
            bm25_latency_ms=diagnostics_metrics.get("bm25_latency_ms", 0.0),
            fusion_latency_ms=diagnostics_metrics.get("fusion_latency_ms", 0.0),
            rerank_latency_ms=round(rerank_latency_ms, 3),
            rerank_used=rerank_used,
            rerank_model=rerank_model,
            fusion_method=str(
                diagnostics_metrics.get("fusion_method", request.fusion_method.value)
            ),
        )

        log_search_event(
            "hybrid_search_completed",
            ctx,
            extra={
                "query": request.query,
                "latency_ms": round(latency_ms, 3),
                "total_results": len(final_items),
                "query_type": query_type,
                "rerank_used": rerank_used,
            },
        )

        return HybridSearchResponse(
            query=request.query,
            query_type=query_type,
            strategy=strategy_label,
            latency_ms=round(latency_ms, 3),
            total_results=len(final_items),
            results=final_items,
            request_id=request_id,
            diagnostics=diagnostics,
        )


# ─── Retrieval Metrics ────────────────────────────────────────────────────────


@router.get(
    "/retrieval/metrics",
    response_model=RetrievalMetricsResponse,
    status_code=status.HTTP_200_OK,
    summary="Aggregated retrieval metrics (reuses the analytics platform)",
    description=(
        "Returns dense/BM25/hybrid recall, reranker gain, retrieval success "
        "rate, and average latency over a recent window. Pulled from the "
        "existing AnalyticsService — no metric is recomputed here."
    ),
    tags=["retrieval"],
)
async def retrieval_metrics(
    window: str = Query(
        "daily",
        pattern="^(hourly|daily|weekly|monthly)$",
        description="Aggregation window type.",
    ),
    dataset_name: Optional[str] = Query(None, description="Optional dataset filter."),
    db_session: AsyncSession = Depends(get_db_session),
) -> RetrievalMetricsResponse:
    analytics = AnalyticsService(db_session)
    now = datetime.now(timezone.utc)
    delta_map = {
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "monthly": timedelta(days=30),
    }
    window_start = now - delta_map[window]

    per_strategy: Dict[str, Dict[str, Any]] = {}
    total_queries = 0
    avg_latencies: List[float] = []
    reranker_gains: List[float] = []
    hit_rates: List[float] = []

    try:
        for strategy in ("dense", "bm25", "hybrid", "hybrid_rerank"):
            agg = await analytics.get_aggregated_metrics(
                strategy=strategy,
                start_time=window_start,
                end_time=now,
                dataset_name=dataset_name,
            )
            if not agg:
                continue
            per_strategy[strategy] = agg
            total_queries += int(agg.get("total_queries", 0) or 0)
            if agg.get("avg_retrieval_latency_ms") is not None:
                avg_latencies.append(float(agg["avg_retrieval_latency_ms"]))
            if agg.get("avg_reranker_gain") is not None:
                reranker_gains.append(float(agg["avg_reranker_gain"]))
            if agg.get("avg_hit_rate") is not None:
                hit_rates.append(float(agg["avg_hit_rate"]))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to read aggregated metrics: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Analytics layer unavailable: {exc}",
        ) from exc

    dense = per_strategy.get("dense", {})
    bm25 = per_strategy.get("bm25", {})
    hybrid = per_strategy.get("hybrid", {})
    rerank = per_strategy.get("hybrid_rerank", {})

    return RetrievalMetricsResponse(
        dense_recall=dense.get("avg_dense_recall_at_10"),
        bm25_recall=bm25.get("avg_bm25_recall_at_10"),
        hybrid_recall=hybrid.get("avg_hybrid_recall_at_10"),
        reranker_gain=(
            rerank.get("avg_reranker_gain")
            if rerank
            else (sum(reranker_gains) / len(reranker_gains) if reranker_gains else None)
        ),
        retrieval_success_rate=(sum(hit_rates) / len(hit_rates) if hit_rates else None),
        average_latency=(
            sum(avg_latencies) / len(avg_latencies) if avg_latencies else None
        ),
        total_queries=total_queries,
        window_start=window_start,
        window_end=now,
    )


# ─── Retrieval Health ─────────────────────────────────────────────────────────


@router.get(
    "/retrieval/health",
    response_model=RetrievalHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Comprehensive retrieval subsystem health check",
    description=(
        "Probes database, BM25 service, hybrid retriever, analytics layer, "
        "and the reranker. Returns per-component status plus a rollup of "
        "healthy / degraded / unhealthy."
    ),
    tags=["retrieval"],
)
async def retrieval_health(
    db_session: AsyncSession = Depends(get_db_session),
    bm25_service: BM25Service = Depends(get_bm25_service),
    hybrid_retriever: HybridRetriever = Depends(get_hybrid_retriever),
    reranker: RerankerService = Depends(get_reranker_service),
) -> RetrievalHealthResponse:
    components: List[HealthCheck] = []
    checks: Dict[str, bool] = {}
    overall = "healthy"

    # ── Database ────────────────────────────────────────────────────────
    db_start = time.perf_counter()
    try:
        result = await db_session.execute(text("SELECT 1"))
        result.scalar_one()
        latency = round((time.perf_counter() - db_start) * 1000.0, 3)
        components.append(
            HealthCheck(name="database", healthy=True, latency_ms=latency)
        )
        checks["database"] = True
    except Exception as exc:  # noqa: BLE001
        components.append(
            HealthCheck(name="database", healthy=False, details={"error": str(exc)})
        )
        checks["database"] = False
        overall = "unhealthy"

    # ── BM25 ─────────────────────────────────────────────────────────────
    try:
        stats = bm25_service.stats
        is_ready = stats.status == IndexStatus.READY
        components.append(
            HealthCheck(
                name="bm25_service",
                healthy=is_ready,
                details={
                    "status": stats.status.value,
                    "total_documents": stats.total_documents,
                    "index_version": stats.index_version,
                },
            )
        )
        checks["bm25_service"] = is_ready
        if not is_ready and overall == "healthy":
            overall = "degraded"
    except Exception as exc:  # noqa: BLE001
        components.append(
            HealthCheck(name="bm25_service", healthy=False, details={"error": str(exc)})
        )
        checks["bm25_service"] = False
        overall = "unhealthy"

    # ── Hybrid retriever ────────────────────────────────────────────────
    try:
        components.append(
            HealthCheck(
                name="hybrid_retriever",
                healthy=True,
                details={
                    "has_dense_backend": hybrid_retriever.retrieval_service is not None,
                    "has_bm25_backend": hybrid_retriever.bm25_retriever is not None,
                    "query_analyzer_attached": hybrid_retriever.query_analyzer
                    is not None,
                },
            )
        )
        checks["hybrid_retriever"] = True
    except Exception as exc:  # noqa: BLE001
        components.append(
            HealthCheck(
                name="hybrid_retriever",
                healthy=False,
                details={"error": str(exc)},
            )
        )
        checks["hybrid_retriever"] = False
        overall = "unhealthy"

    # ── Analytics layer ──────────────────────────────────────────────────
    try:
        analytics = AnalyticsService(db_session)
        agg = await analytics.get_aggregated_metrics(strategy="hybrid")
        components.append(
            HealthCheck(
                name="analytics_layer",
                healthy=True,
                details={
                    "queryable": True,
                    "hybrid_total_queries": int(agg.get("total_queries", 0) or 0),
                },
            )
        )
        checks["analytics_layer"] = True
    except Exception as exc:  # noqa: BLE001
        components.append(
            HealthCheck(
                name="analytics_layer",
                healthy=False,
                details={"error": str(exc)},
            )
        )
        checks["analytics_layer"] = False
        if overall == "healthy":
            overall = "degraded"

    # ── Reranker ─────────────────────────────────────────────────────────
    try:
        provider = getattr(reranker, "provider", None)
        model_name = provider.get_model_name() if provider is not None else "unknown"
        components.append(
            HealthCheck(
                name="reranker",
                healthy=True,
                details={
                    "model": model_name,
                    "default_top_k": reranker.default_top_k,
                },
            )
        )
        checks["reranker"] = True
    except Exception as exc:  # noqa: BLE001
        components.append(
            HealthCheck(name="reranker", healthy=False, details={"error": str(exc)})
        )
        checks["reranker"] = False
        if overall == "healthy":
            overall = "degraded"

    return RetrievalHealthResponse(
        status=overall,
        checks=checks,
        components=components,
    )
