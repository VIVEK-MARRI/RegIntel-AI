"""Analytics API routes for the Retrieval Analytics Platform.

Provides endpoints for metrics recording, querying, trend analysis,
performance summaries, strategy comparison, query distribution,
reranker gain tracking, system health, and report generation.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.analytics import (
    AggregatedMetricsResponse,
    AnalyticsReportResponse,
    PerformanceSummaryResponse,
    QueryDistributionSummary,
    RerankerGainResponse,
    ReportRequest,
    RetrievalMetricsCreate,
    RetrievalMetricsResponse,
    StrategyComparisonResponse,
    SystemHealthResponse,
    TrendAnalysisResponse,
)
from app.services.analytics.service import AnalyticsService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_analytics_service(
    db_session: AsyncSession = Depends(get_db_session),
) -> AnalyticsService:
    """Dependency injection provider for AnalyticsService."""
    return AnalyticsService(db_session)


# ─── Metrics Recording ───────────────────────────────────────────────────────


@router.post(
    "/metrics",
    response_model=RetrievalMetricsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record retrieval metrics for a single query",
    description="Stores per-query retrieval metrics including recall, precision, MRR, hit rate, and latency.",
)
async def record_metrics(
    data: RetrievalMetricsCreate,
    service: AnalyticsService = Depends(get_analytics_service),
) -> RetrievalMetricsResponse:
    try:
        return await service.record_metrics(data)
    except Exception as e:
        logger.error(f"Error recording metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record metrics: {str(e)}",
        )


@router.post(
    "/metrics/batch",
    response_model=List[RetrievalMetricsResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Record retrieval metrics for multiple queries",
    description="Batch endpoint for storing per-query retrieval metrics.",
)
async def record_metrics_batch(
    items: List[RetrievalMetricsCreate],
    service: AnalyticsService = Depends(get_analytics_service),
) -> List[RetrievalMetricsResponse]:
    try:
        return await service.record_metrics_batch(items)
    except Exception as e:
        logger.error(f"Error recording batch metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record batch metrics: {str(e)}",
        )


# ─── Metrics Querying ────────────────────────────────────────────────────────


@router.get(
    "/metrics",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Query retrieval metrics records",
    description="Query historical metrics with filters for strategy, dataset, category, and time range.",
)
async def query_metrics(
    strategy: Optional[str] = Query(None, description="Filter by retrieval strategy."),
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name."),
    query_category: Optional[str] = Query(
        None, description="Filter by query category."
    ),
    start_time: Optional[datetime] = Query(
        None, description="Start of time range (ISO format)."
    ),
    end_time: Optional[datetime] = Query(
        None, description="End of time range (ISO format)."
    ),
    limit: int = Query(
        default=100, ge=1, le=10000, description="Max records to return."
    ),
    offset: int = Query(default=0, ge=0, description="Number of records to skip."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> Dict[str, Any]:
    try:
        return await service.query_metrics(
            strategy=strategy,
            dataset_name=dataset_name,
            query_category=query_category,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error(f"Error querying metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to query metrics: {str(e)}",
        )


# ─── Aggregated Metrics ──────────────────────────────────────────────────────


@router.get(
    "/metrics/aggregated/{strategy}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get aggregated metrics for a strategy",
    description="Returns aggregated metrics (averages, percentiles) for a retrieval strategy over a time range.",
)
async def get_aggregated_metrics(
    strategy: str,
    start_time: Optional[datetime] = Query(None, description="Start of time range."),
    end_time: Optional[datetime] = Query(None, description="End of time range."),
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> Dict[str, Any]:
    try:
        result = await service.get_aggregated_metrics(
            strategy=strategy,
            start_time=start_time,
            end_time=end_time,
            dataset_name=dataset_name,
        )
        return result
    except Exception as e:
        logger.error(f"Error getting aggregated metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get aggregated metrics: {str(e)}",
        )


@router.post(
    "/metrics/snapshot/{strategy}",
    response_model=AggregatedMetricsResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Compute and store an aggregated metrics snapshot",
    description="Computes aggregated metrics for a strategy over a time window and stores the snapshot.",
)
async def compute_aggregated_snapshot(
    strategy: str,
    window_type: str = Query(
        ..., description="Window type: hourly, daily, weekly, monthly."
    ),
    window_start: datetime = Query(..., description="Start of the aggregation window."),
    window_end: datetime = Query(..., description="End of the aggregation window."),
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> AggregatedMetricsResponse:
    try:
        return await service.compute_aggregated_snapshot(
            strategy=strategy,
            window_type=window_type,
            window_start=window_start,
            window_end=window_end,
            dataset_name=dataset_name,
        )
    except Exception as e:
        logger.error(f"Error computing aggregated snapshot: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute snapshot: {str(e)}",
        )


# ─── Trend Analysis ──────────────────────────────────────────────────────────


@router.get(
    "/trends/{metric_name}",
    response_model=TrendAnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Get trend analysis for a metric",
    description="Returns trend data for a specific metric across strategies, with linear regression analysis.",
)
async def get_trend_analysis(
    metric_name: str,
    strategies: Optional[List[str]] = Query(None, description="Strategies to include."),
    window_type: str = Query(
        default="daily",
        description="Aggregation window: hourly, daily, weekly, monthly.",
    ),
    start_time: Optional[datetime] = Query(None, description="Start of time range."),
    end_time: Optional[datetime] = Query(None, description="End of time range."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> TrendAnalysisResponse:
    try:
        return await service.get_trend_analysis(
            metric_name=metric_name,
            strategies=strategies,
            window_type=window_type,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as e:
        logger.error(f"Error getting trend analysis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get trend analysis: {str(e)}",
        )


# ─── Performance Summary ─────────────────────────────────────────────────────


@router.get(
    "/performance/summary",
    response_model=PerformanceSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get performance summary across strategies",
    description="Returns a comprehensive performance summary comparing all retrieval strategies with composite scores.",
)
async def get_performance_summary(
    window_type: str = Query(
        default="daily", description="Time window: hourly, daily, weekly, monthly."
    ),
    start_time: Optional[datetime] = Query(None, description="Start of time range."),
    end_time: Optional[datetime] = Query(None, description="End of time range."),
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name."),
    strategies: Optional[List[str]] = Query(None, description="Strategies to include."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> PerformanceSummaryResponse:
    try:
        return await service.get_performance_summary(
            window_type=window_type,
            start_time=start_time,
            end_time=end_time,
            dataset_name=dataset_name,
            strategies=strategies,
        )
    except Exception as e:
        logger.error(f"Error getting performance summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get performance summary: {str(e)}",
        )


# ─── Strategy Comparison ─────────────────────────────────────────────────────


@router.get(
    "/performance/compare",
    response_model=StrategyComparisonResponse,
    status_code=status.HTTP_200_OK,
    summary="Compare a metric across strategies",
    description="Compares a specific metric across all strategies with change percentage and trend direction.",
)
async def compare_strategies(
    metric_name: str = Query(
        ..., description="Metric to compare (e.g., dense_recall_at_5, mrr)."
    ),
    window_type: str = Query(default="daily", description="Time window."),
    start_time: Optional[datetime] = Query(None, description="Start of time range."),
    end_time: Optional[datetime] = Query(None, description="End of time range."),
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> StrategyComparisonResponse:
    try:
        return await service.compare_strategies(
            metric_name=metric_name,
            window_type=window_type,
            start_time=start_time,
            end_time=end_time,
            dataset_name=dataset_name,
        )
    except Exception as e:
        logger.error(f"Error comparing strategies: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compare strategies: {str(e)}",
        )


# ─── Query Distribution ───────────────────────────────────────────────────────


@router.get(
    "/distribution/queries",
    response_model=QueryDistributionSummary,
    status_code=status.HTTP_200_OK,
    summary="Get query distribution summary",
    description="Returns query distribution across categories and strategies with percentages.",
)
async def get_query_distribution(
    window_type: str = Query(default="daily", description="Time window."),
    start_time: Optional[datetime] = Query(None, description="Start of time range."),
    end_time: Optional[datetime] = Query(None, description="End of time range."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> QueryDistributionSummary:
    try:
        return await service.get_query_distribution_summary(
            window_type=window_type,
            start_time=start_time,
            end_time=end_time,
        )
    except Exception as e:
        logger.error(f"Error getting query distribution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get query distribution: {str(e)}",
        )


@router.post(
    "/distribution/queries",
    response_model=QueryDistributionSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Record query distribution data",
    description="Records query distribution counts by category and strategy for a time window.",
)
async def record_query_distribution(
    window_type: str = Query(..., description="Time window type."),
    window_start: datetime = Query(..., description="Start of the window."),
    window_end: datetime = Query(..., description="End of the window."),
    category_counts: str = Query(
        ..., description="Query counts by category (JSON string)."
    ),
    strategy_counts: str = Query(
        ..., description="Query counts by strategy (JSON string)."
    ),
    avg_query_length: Optional[float] = Query(
        None, description="Average query length."
    ),
    avg_result_count: Optional[float] = Query(
        None, description="Average result count."
    ),
    service: AnalyticsService = Depends(get_analytics_service),
) -> QueryDistributionSummary:
    try:
        return await service.record_query_distribution(
            window_type=window_type,
            window_start=window_start,
            window_end=window_end,
            category_counts=category_counts,
            strategy_counts=strategy_counts,
            avg_query_length=avg_query_length,
            avg_result_count=avg_result_count,
        )
    except Exception as e:
        logger.error(f"Error recording query distribution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record query distribution: {str(e)}",
        )


# ─── Reranker Gain ────────────────────────────────────────────────────────────


@router.get(
    "/reranker/gain",
    response_model=RerankerGainResponse,
    status_code=status.HTTP_200_OK,
    summary="Get reranker gain metrics",
    description="Returns the latest reranker gain metrics showing improvement over base retrieval.",
)
async def get_reranker_gain(
    window_type: str = Query(default="daily", description="Time window."),
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> RerankerGainResponse:
    # Treat "not found" as 404, but ensure we only return 404 for the actual
    # absence of data (the repo/service returns None).
    result = await service.get_reranker_gain(window_type, dataset_name)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No reranker gain data found for the specified window.",
        )
    return result


@router.post(
    "/reranker/gain",
    response_model=RerankerGainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record reranker gain metrics",
    description="Records reranker improvement metrics for a time window.",
)
async def record_reranker_gain(
    window_type: str = Query(..., description="Time window type."),
    window_start: datetime = Query(..., description="Start of the window."),
    window_end: datetime = Query(..., description="End of the window."),
    avg_recall_gain_at_5: Optional[float] = Query(
        None, description="Average Recall@5 gain."
    ),
    avg_recall_gain_at_10: Optional[float] = Query(
        None, description="Average Recall@10 gain."
    ),
    avg_precision_gain_at_5: Optional[float] = Query(
        None, description="Average Precision@5 gain."
    ),
    avg_mrr_gain: Optional[float] = Query(None, description="Average MRR gain."),
    avg_hit_rate_gain: Optional[float] = Query(
        None, description="Average hit rate gain."
    ),
    avg_reranker_latency_ms: Optional[float] = Query(
        None, description="Average reranker latency."
    ),
    reranker_queries_count: int = Query(
        default=0, description="Number of queries reranked."
    ),
    improvement_rate: Optional[float] = Query(
        None, description="Fraction of queries improved."
    ),
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> RerankerGainResponse:
    try:
        return await service.record_reranker_gain(
            window_type=window_type,
            window_start=window_start,
            window_end=window_end,
            avg_recall_gain_at_5=avg_recall_gain_at_5,
            avg_recall_gain_at_10=avg_recall_gain_at_10,
            avg_precision_gain_at_5=avg_precision_gain_at_5,
            avg_mrr_gain=avg_mrr_gain,
            avg_hit_rate_gain=avg_hit_rate_gain,
            avg_reranker_latency_ms=avg_reranker_latency_ms,
            reranker_queries_count=reranker_queries_count,
            improvement_rate=improvement_rate,
            dataset_name=dataset_name,
        )
    except Exception as e:
        logger.error(f"Error recording reranker gain: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record reranker gain: {str(e)}",
        )


# ─── System Health ────────────────────────────────────────────────────────────


@router.get(
    "/health",
    response_model=SystemHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Get system health snapshot",
    description="Returns the latest system health snapshot including component availability and performance indicators.",
)
async def get_system_health(
    service: AnalyticsService = Depends(get_analytics_service),
) -> SystemHealthResponse:
    try:
        return await service.get_system_health()
    except Exception as e:
        logger.error(f"Error getting system health: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get system health: {str(e)}",
        )


@router.post(
    "/health",
    response_model=SystemHealthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a system health snapshot",
    description="Records a system health snapshot with component availability and performance data.",
)
async def record_system_health(
    status: str = Query(
        default="healthy", description="Overall status: healthy, degraded, unhealthy."
    ),
    dense_available: bool = Query(
        default=True, description="Dense retrieval availability."
    ),
    bm25_available: bool = Query(
        default=True, description="BM25 retrieval availability."
    ),
    hybrid_available: bool = Query(
        default=True, description="Hybrid retrieval availability."
    ),
    reranker_available: bool = Query(
        default=True, description="Reranker availability."
    ),
    index_consistent: bool = Query(
        default=True, description="Index consistency status."
    ),
    embedding_coverage: Optional[float] = Query(
        None, description="Embedding coverage percentage."
    ),
    total_indexed: Optional[int] = Query(None, description="Total indexed chunks."),
    avg_latency: Optional[float] = Query(
        None, description="Average latency last hour (ms)."
    ),
    queries_last_hour: Optional[int] = Query(
        None, description="Queries in the last hour."
    ),
    error_rate: Optional[float] = Query(
        None, description="Error rate in the last hour."
    ),
    service: AnalyticsService = Depends(get_analytics_service),
) -> SystemHealthResponse:
    try:
        return await service.record_system_health(
            status=status,
            dense_available=dense_available,
            bm25_available=bm25_available,
            hybrid_available=hybrid_available,
            reranker_available=reranker_available,
            index_consistent=index_consistent,
            embedding_coverage=embedding_coverage,
            total_indexed=total_indexed,
            avg_latency=avg_latency,
            queries_last_hour=queries_last_hour,
            error_rate=error_rate,
        )
    except Exception as e:
        logger.error(f"Error recording system health: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record system health: {str(e)}",
        )


# ─── Report Generation ────────────────────────────────────────────────────────


@router.post(
    "/reports",
    response_model=AnalyticsReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a comprehensive analytics report",
    description="Generates a full analytics report including performance summary, trends, query distribution, reranker gain, and system health.",
)
async def generate_report(
    request: ReportRequest,
    service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsReportResponse:
    try:
        return await service.generate_report(
            window_type=request.window_type,
            start_time=request.start_time,
            end_time=request.end_time,
            strategies=request.strategies,
            dataset_name=request.dataset_name,
            include_trends=request.include_trends,
            include_query_distribution=request.include_query_distribution,
            include_reranker_gain=request.include_reranker_gain,
            include_system_health=request.include_system_health,
        )
    except Exception as e:
        logger.error(f"Error generating report: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}",
        )


@router.get(
    "/reports/summary",
    response_model=AnalyticsReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a quick analytics report",
    description="Generates a report using query parameters for quick access.",
)
async def generate_quick_report(
    window_type: str = Query(default="daily", description="Time window."),
    start_time: Optional[datetime] = Query(None, description="Start of time range."),
    end_time: Optional[datetime] = Query(None, description="End of time range."),
    strategies: Optional[List[str]] = Query(None, description="Strategies to include."),
    dataset_name: Optional[str] = Query(None, description="Filter by dataset name."),
    service: AnalyticsService = Depends(get_analytics_service),
) -> AnalyticsReportResponse:
    try:
        return await service.generate_report(
            window_type=window_type,
            start_time=start_time,
            end_time=end_time,
            strategies=strategies,
            dataset_name=dataset_name,
        )
    except Exception as e:
        logger.error(f"Error generating quick report: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate report: {str(e)}",
        )
