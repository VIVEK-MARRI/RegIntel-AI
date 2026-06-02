"""Analytics service layer.

Orchestrates metrics collection, aggregation, trend analysis,
performance summaries, and report generation.
"""

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import (
    AggregatedMetricsSnapshot,
    QueryDistributionRecord,
    RetrievalMetricsRecord,
    RerankerGainRecord,
    SystemHealthSnapshot,
)
from app.repositories.analytics import (
    AggregatedMetricsRepository,
    QueryDistributionRepository,
    RetrievalMetricsRepository,
    RerankerGainRepository,
    SystemHealthRepository,
)
from app.schemas.analytics import (
    AggregatedMetricsResponse,
    AnalyticsReportResponse,
    PerformanceSummaryResponse,
    QueryDistributionSummary,
    RerankerGainResponse,
    RetrievalMetricsCreate,
    RetrievalMetricsResponse,
    StrategyComparisonResponse,
    StrategyPerformance,
    SystemHealthResponse,
    TrendAnalysisResponse,
    TrendDataPoint,
    TrendSeries,
)

logger = logging.getLogger(__name__)

ALL_STRATEGIES = ["dense", "bm25", "hybrid", "hybrid_rerank"]


class AnalyticsService:
    """Main service for retrieval analytics operations."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.metrics_repo = RetrievalMetricsRepository(db_session)
        self.agg_repo = AggregatedMetricsRepository(db_session)
        self.dist_repo = QueryDistributionRepository(db_session)
        self.reranker_repo = RerankerGainRepository(db_session)
        self.health_repo = SystemHealthRepository(db_session)

    # ─── Metrics Recording ────────────────────────────────────────────────

    async def record_metrics(
        self, data: RetrievalMetricsCreate
    ) -> RetrievalMetricsResponse:
        """Record retrieval metrics for a single query."""
        record_data = data.model_dump(exclude_unset=True)
        record = await self.metrics_repo.create(record_data)
        logger.info(
            f"Recorded metrics for query '{record.query_id}' "
            f"strategy='{record.strategy}'"
        )
        return RetrievalMetricsResponse.model_validate(record)

    async def record_metrics_batch(
        self, items: List[RetrievalMetricsCreate]
    ) -> List[RetrievalMetricsResponse]:
        """Record metrics for multiple queries in a batch."""
        responses = []
        for item in items:
            record_data = item.model_dump(exclude_unset=True)
            record = await self.metrics_repo.create(record_data)
            responses.append(RetrievalMetricsResponse.model_validate(record))
        logger.info(f"Recorded batch of {len(responses)} metrics records.")
        return responses

    # ─── Metrics Querying ────────────────────────────────────────────────

    async def query_metrics(
        self,
        strategy: Optional[str] = None,
        dataset_name: Optional[str] = None,
        query_category: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Query metrics records with filters and pagination."""
        records, total = await self.metrics_repo.query_records(
            strategy=strategy,
            dataset_name=dataset_name,
            query_category=query_category,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
        items = [RetrievalMetricsResponse.model_validate(r) for r in records]
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    # ─── Aggregated Metrics ───────────────────────────────────────────────

    async def get_aggregated_metrics(
        self,
        strategy: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        dataset_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregated metrics for a strategy over a time range."""
        return await self.metrics_repo.get_aggregated_metrics(
            strategy=strategy,
            start_time=start_time,
            end_time=end_time,
            dataset_name=dataset_name,
        )

    async def compute_aggregated_snapshot(
        self,
        strategy: str,
        window_type: str,
        window_start: datetime,
        window_end: datetime,
        dataset_name: Optional[str] = None,
    ) -> AggregatedMetricsResponse:
        """Compute and store an aggregated metrics snapshot."""
        agg = await self.metrics_repo.get_aggregated_metrics(
            strategy=strategy,
            start_time=window_start,
            end_time=window_end,
            dataset_name=dataset_name,
        )

        snapshot_data = {
            "window_start": window_start,
            "window_end": window_end,
            "window_type": window_type,
            "strategy": strategy,
            "dataset_name": dataset_name,
            "total_queries": agg["total_queries"],
            "unique_queries": agg["unique_queries"],
            "avg_dense_recall_at_5": agg.get("avg_dense_recall_at_5"),
            "avg_dense_recall_at_10": agg.get("avg_dense_recall_at_10"),
            "avg_bm25_recall_at_5": agg.get("avg_bm25_recall_at_5"),
            "avg_bm25_recall_at_10": agg.get("avg_bm25_recall_at_10"),
            "avg_hybrid_recall_at_5": agg.get("avg_hybrid_recall_at_5"),
            "avg_hybrid_recall_at_10": agg.get("avg_hybrid_recall_at_10"),
            "avg_precision_at_5": agg.get("avg_precision_at_5"),
            "avg_precision_at_10": agg.get("avg_precision_at_10"),
            "avg_mrr": agg.get("avg_mrr"),
            "avg_hit_rate": agg.get("avg_hit_rate"),
            "avg_retrieval_latency_ms": agg.get("avg_retrieval_latency_ms"),
            "p50_retrieval_latency_ms": agg.get("p50_latency"),
            "p95_retrieval_latency_ms": agg.get("p95_latency"),
            "p99_retrieval_latency_ms": agg.get("p99_latency"),
            "avg_reranker_latency_ms": agg.get("avg_reranker_latency_ms"),
            "avg_total_latency_ms": agg.get("avg_total_latency_ms"),
            "avg_reranker_gain": agg.get("avg_reranker_gain"),
        }

        snapshot = await self.agg_repo.upsert(snapshot_data)
        return AggregatedMetricsResponse.model_validate(snapshot)

    # ─── Trend Analysis ──────────────────────────────────────────────────

    async def get_trend_analysis(
        self,
        metric_name: str,
        strategies: Optional[List[str]] = None,
        window_type: str = "daily",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> TrendAnalysisResponse:
        """Get trend analysis for a metric across strategies."""
        if strategies is None:
            strategies = ALL_STRATEGIES

        if not end_time:
            end_time = datetime.now(timezone.utc)
        if not start_time:
            start_time = end_time - timedelta(days=30)

        series_list = []
        for strategy in strategies:
            trend_data = await self.metrics_repo.get_trend_data(
                strategy=strategy,
                metric=metric_name,
                start_time=start_time,
                end_time=end_time,
                window_type=window_type,
            )

            data_points = [
                TrendDataPoint(
                    timestamp=dp["timestamp"],
                    value=dp["value"],
                    label=f"{dp['query_count']} queries",
                )
                for dp in trend_data
            ]

            # Compute trend direction using simple linear regression
            direction, slope = self._compute_trend(data_points)

            series_list.append(
                TrendSeries(
                    metric_name=metric_name,
                    strategy=strategy,
                    data_points=data_points,
                    trend_direction=direction,
                    trend_slope=slope,
                )
            )

        # Build summary
        summary = {}
        for s in series_list:
            if s.data_points:
                values = [dp.value for dp in s.data_points]
                summary[s.strategy] = {
                    "min": min(values),
                    "max": max(values),
                    "mean": sum(values) / len(values),
                    "latest": values[-1] if values else None,
                    "trend": s.trend_direction,
                    "slope": s.trend_slope,
                }

        return TrendAnalysisResponse(
            metric_name=metric_name,
            window_type=window_type,
            start_time=start_time,
            end_time=end_time,
            series=series_list,
            summary=summary,
        )

    def _compute_trend(
        self, data_points: List[TrendDataPoint]
    ) -> tuple[Optional[str], Optional[float]]:
        """Compute trend direction and slope using simple linear regression."""
        if len(data_points) < 2:
            return None, None

        n = len(data_points)
        values = [dp.value for dp in data_points]
        x_values = list(range(n))

        x_mean = sum(x_values) / n
        y_mean = sum(values) / n

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, values))
        denominator = sum((x - x_mean) ** 2 for x in x_values)

        if denominator == 0:
            return "stable", 0.0

        slope = numerator / denominator

        # Determine direction based on slope magnitude
        threshold = 0.001
        if slope > threshold:
            direction = "improving"
        elif slope < -threshold:
            direction = "degrading"
        else:
            direction = "stable"

        return direction, slope

    # ─── Performance Summary ─────────────────────────────────────────────

    async def get_performance_summary(
        self,
        window_type: str = "daily",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        dataset_name: Optional[str] = None,
        strategies: Optional[List[str]] = None,
    ) -> PerformanceSummaryResponse:
        """Generate a comprehensive performance summary across strategies."""
        if strategies is None:
            strategies = ALL_STRATEGIES

        if not end_time:
            end_time = datetime.now(timezone.utc)
        if not start_time:
            # Default window based on type
            delta = {
                "hourly": timedelta(hours=1),
                "daily": timedelta(days=1),
                "weekly": timedelta(weeks=1),
                "monthly": timedelta(days=30),
            }.get(window_type, timedelta(days=1))
            start_time = end_time - delta

        strategy_performances = []
        best_strategy = None
        best_score = -1.0
        total_queries = 0
        all_latencies = []

        for strategy in strategies:
            agg = await self.metrics_repo.get_aggregated_metrics(
                strategy=strategy,
                start_time=start_time,
                end_time=end_time,
                dataset_name=dataset_name,
            )

            perf = StrategyPerformance(
                strategy=strategy,
                avg_dense_recall_at_5=agg.get("avg_dense_recall_at_5"),
                avg_dense_recall_at_10=agg.get("avg_dense_recall_at_10"),
                avg_bm25_recall_at_5=agg.get("avg_bm25_recall_at_5"),
                avg_bm25_recall_at_10=agg.get("avg_bm25_recall_at_10"),
                avg_hybrid_recall_at_5=agg.get("avg_hybrid_recall_at_5"),
                avg_hybrid_recall_at_10=agg.get("avg_hybrid_recall_at_10"),
                avg_precision_at_5=agg.get("avg_precision_at_5"),
                avg_precision_at_10=agg.get("avg_precision_at_10"),
                avg_mrr=agg.get("avg_mrr"),
                avg_hit_rate=agg.get("avg_hit_rate"),
                avg_retrieval_latency_ms=agg.get("avg_retrieval_latency_ms"),
                p95_retrieval_latency_ms=agg.get("p95_latency"),
                avg_reranker_gain=agg.get("avg_reranker_gain"),
                total_queries=agg.get("total_queries", 0),
            )

            # Compute composite score
            score = self._compute_composite_score(perf)
            perf.composite_score = score

            if score > best_score:
                best_score = score
                best_strategy = strategy

            total_queries += agg.get("total_queries", 0)
            if agg.get("avg_retrieval_latency_ms"):
                all_latencies.append(agg["avg_retrieval_latency_ms"])

            strategy_performances.append(perf)

        overall_avg_latency = (
            sum(all_latencies) / len(all_latencies) if all_latencies else None
        )

        return PerformanceSummaryResponse(
            window_type=window_type,
            window_start=start_time,
            window_end=end_time,
            dataset_name=dataset_name,
            strategies=strategy_performances,
            best_strategy=best_strategy,
            total_queries=total_queries,
            overall_avg_latency_ms=overall_avg_latency,
        )

    def _compute_composite_score(self, perf: StrategyPerformance) -> float:
        """Compute a weighted composite score for a strategy."""
        weights = {
            "avg_dense_recall_at_5": 0.15,
            "avg_bm25_recall_at_5": 0.10,
            "avg_hybrid_recall_at_5": 0.15,
            "avg_precision_at_5": 0.15,
            "avg_mrr": 0.20,
            "avg_hit_rate": 0.15,
            "avg_reranker_gain": 0.10,
        }

        score = 0.0
        total_weight = 0.0

        for attr, weight in weights.items():
            value = getattr(perf, attr, None)
            if value is not None:
                score += value * weight
                total_weight += weight

        if total_weight > 0:
            score /= total_weight

        return round(score, 4)

    # ─── Strategy Comparison ─────────────────────────────────────────────

    async def compare_strategies(
        self,
        metric_name: str,
        window_type: str = "daily",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        dataset_name: Optional[str] = None,
    ) -> StrategyComparisonResponse:
        """Compare a specific metric across all strategies."""
        if not end_time:
            end_time = datetime.now(timezone.utc)
        if not start_time:
            start_time = end_time - timedelta(days=1)

        comparisons = {}
        winner = None
        best_value = -float("inf")

        # Also get previous period for change calculation
        period_duration = end_time - start_time
        prev_start = start_time - period_duration
        prev_end = start_time

        for strategy in ALL_STRATEGIES:
            # Current period
            agg_current = await self.metrics_repo.get_aggregated_metrics(
                strategy=strategy,
                start_time=start_time,
                end_time=end_time,
                dataset_name=dataset_name,
            )

            # Previous period
            agg_previous = await self.metrics_repo.get_aggregated_metrics(
                strategy=strategy,
                start_time=prev_start,
                end_time=prev_end,
                dataset_name=dataset_name,
            )

            current_value = agg_current.get(metric_name)
            previous_value = agg_previous.get(metric_name)

            change_pct = None
            if current_value is not None and previous_value is not None and previous_value != 0:
                change_pct = round(
                    ((current_value - previous_value) / previous_value) * 100, 2
                )

            trend = None
            if change_pct is not None:
                if change_pct > 1:
                    trend = "improving"
                elif change_pct < -1:
                    trend = "degrading"
                else:
                    trend = "stable"

            comparisons[strategy] = {
                "value": current_value,
                "previous_value": previous_value,
                "change_pct": change_pct,
                "trend": trend,
                "total_queries": agg_current.get("total_queries", 0),
            }

            if current_value is not None and current_value > best_value:
                best_value = current_value
                winner = strategy

        return StrategyComparisonResponse(
            metric_name=metric_name,
            window_type=window_type,
            start_time=start_time,
            end_time=end_time,
            comparisons=comparisons,
            winner=winner,
        )

    # ─── Query Distribution ──────────────────────────────────────────────

    async def get_query_distribution_summary(
        self,
        window_type: str = "daily",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> QueryDistributionSummary:
        """Get a summary of query distribution."""
        if not end_time:
            end_time = datetime.now(timezone.utc)
        if not start_time:
            start_time = end_time - timedelta(days=1)

        cat_dist = await self.dist_repo.get_category_distribution(start_time, end_time)
        strat_dist = await self.dist_repo.get_strategy_distribution(start_time, end_time)

        total = cat_dist.get("total", 0)

        cat_pct = {}
        for key, value in cat_dist.items():
            if key != "total" and total > 0:
                cat_pct[key] = round((value / total) * 100, 2)
            elif key != "total":
                cat_pct[key] = 0.0

        strat_pct = {}
        for key, value in strat_dist.items():
            if key != "total" and total > 0:
                strat_pct[key] = round((value / total) * 100, 2)
            elif key != "total":
                strat_pct[key] = 0.0

        return QueryDistributionSummary(
            window_type=window_type,
            window_start=start_time,
            window_end=end_time,
            total_queries=total,
            category_distribution={k: v for k, v in cat_dist.items() if k != "total"},
            strategy_distribution={k: v for k, v in strat_dist.items() if k != "total"},
            category_percentages=cat_pct,
            strategy_percentages=strat_pct,
        )

    async def record_query_distribution(
        self,
        window_type: str,
        window_start: datetime,
        window_end: datetime,
        category_counts: Dict[str, int],
        strategy_counts: Dict[str, int],
        avg_query_length: Optional[float] = None,
        avg_result_count: Optional[float] = None,
    ) -> QueryDistributionSummary:
        """Record and return query distribution data."""
        total = sum(category_counts.values())

        record_data = {
            "window_type": window_type,
            "window_start": window_start,
            "window_end": window_end,
            "factual_count": category_counts.get("factual", 0),
            "navigational_count": category_counts.get("navigational", 0),
            "analytical_count": category_counts.get("analytical", 0),
            "comparative_count": category_counts.get("comparative", 0),
            "definitional_count": category_counts.get("definitional", 0),
            "procedural_count": category_counts.get("procedural", 0),
            "unknown_count": category_counts.get("unknown", 0),
            "total_count": total,
            "dense_count": strategy_counts.get("dense", 0),
            "bm25_count": strategy_counts.get("bm25", 0),
            "hybrid_count": strategy_counts.get("hybrid", 0),
            "hybrid_rerank_count": strategy_counts.get("hybrid_rerank", 0),
            "avg_query_length": avg_query_length,
            "avg_result_count": avg_result_count,
        }

        await self.dist_repo.create(record_data)

        cat_pct = {}
        for key, value in category_counts.items():
            cat_pct[key] = round((value / total) * 100, 2) if total > 0 else 0.0

        strat_pct = {}
        for key, value in strategy_counts.items():
            strat_pct[key] = round((value / total) * 100, 2) if total > 0 else 0.0

        return QueryDistributionSummary(
            window_type=window_type,
            window_start=window_start,
            window_end=window_end,
            total_queries=total,
            category_distribution=category_counts,
            strategy_distribution=strategy_counts,
            category_percentages=cat_pct,
            strategy_percentages=strat_pct,
            avg_query_length=avg_query_length,
            avg_result_count=avg_result_count,
        )

    # ─── Reranker Gain ───────────────────────────────────────────────────

    async def get_reranker_gain(
        self,
        window_type: str = "daily",
        dataset_name: Optional[str] = None,
    ) -> Optional[RerankerGainResponse]:
        """Get the latest reranker gain record."""
        record = await self.reranker_repo.get_latest(window_type, dataset_name)
        if record:
            return RerankerGainResponse.model_validate(record)
        return None

    async def record_reranker_gain(
        self,
        window_type: str,
        window_start: datetime,
        window_end: datetime,
        avg_recall_gain_at_5: Optional[float] = None,
        avg_recall_gain_at_10: Optional[float] = None,
        avg_precision_gain_at_5: Optional[float] = None,
        avg_mrr_gain: Optional[float] = None,
        avg_hit_rate_gain: Optional[float] = None,
        avg_reranker_latency_ms: Optional[float] = None,
        reranker_queries_count: int = 0,
        improvement_rate: Optional[float] = None,
        dataset_name: Optional[str] = None,
    ) -> RerankerGainResponse:
        """Record reranker gain metrics."""
        record_data = {
            "window_type": window_type,
            "window_start": window_start,
            "window_end": window_end,
            "dataset_name": dataset_name,
            "avg_recall_gain_at_5": avg_recall_gain_at_5,
            "avg_recall_gain_at_10": avg_recall_gain_at_10,
            "avg_precision_gain_at_5": avg_precision_gain_at_5,
            "avg_mrr_gain": avg_mrr_gain,
            "avg_hit_rate_gain": avg_hit_rate_gain,
            "avg_reranker_latency_ms": avg_reranker_latency_ms,
            "reranker_queries_count": reranker_queries_count,
            "improvement_rate": improvement_rate,
        }

        record = await self.reranker_repo.create(record_data)
        return RerankerGainResponse.model_validate(record)

    # ─── System Health ───────────────────────────────────────────────────

    async def get_system_health(self) -> SystemHealthResponse:
        """Get the latest system health snapshot."""
        record = await self.health_repo.get_latest()
        if record:
            return SystemHealthResponse.model_validate(record)

        # Return default healthy status if no records exist
        return SystemHealthResponse(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            status="healthy",
            dense_retrieval_available=True,
            bm25_retrieval_available=True,
            hybrid_retrieval_available=True,
            reranker_available=True,
            index_consistency=True,
        )

    async def record_system_health(
        self,
        status: str = "healthy",
        dense_available: bool = True,
        bm25_available: bool = True,
        hybrid_available: bool = True,
        reranker_available: bool = True,
        index_consistent: bool = True,
        embedding_coverage: Optional[float] = None,
        total_indexed: Optional[int] = None,
        avg_latency: Optional[float] = None,
        queries_last_hour: Optional[int] = None,
        error_rate: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SystemHealthResponse:
        """Record a system health snapshot."""
        record_data = {
            "status": status,
            "dense_retrieval_available": dense_available,
            "bm25_retrieval_available": bm25_available,
            "hybrid_retrieval_available": hybrid_available,
            "reranker_available": reranker_available,
            "index_consistency": index_consistent,
            "embedding_coverage_pct": embedding_coverage,
            "total_indexed_chunks": total_indexed,
            "avg_latency_last_hour_ms": avg_latency,
            "queries_last_hour": queries_last_hour,
            "error_rate_last_hour": error_rate,
            "metadata_json": metadata or {},
        }

        record = await self.health_repo.create(record_data)
        return SystemHealthResponse.model_validate(record)

    # ─── Report Generation ───────────────────────────────────────────────

    async def generate_report(
        self,
        window_type: str = "daily",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        strategies: Optional[List[str]] = None,
        dataset_name: Optional[str] = None,
        include_trends: bool = True,
        include_query_distribution: bool = True,
        include_reranker_gain: bool = True,
        include_system_health: bool = True,
    ) -> AnalyticsReportResponse:
        """Generate a comprehensive analytics report."""
        if not end_time:
            end_time = datetime.now(timezone.utc)
        if not start_time:
            delta = {
                "hourly": timedelta(hours=1),
                "daily": timedelta(days=1),
                "weekly": timedelta(weeks=1),
                "monthly": timedelta(days=30),
            }.get(window_type, timedelta(days=1))
            start_time = end_time - delta

        # Performance summary
        perf_summary = await self.get_performance_summary(
            window_type=window_type,
            start_time=start_time,
            end_time=end_time,
            dataset_name=dataset_name,
            strategies=strategies,
        )

        # Trends
        trends = None
        if include_trends:
            trend_metrics = [
                "dense_recall_at_5",
                "bm25_recall_at_5",
                "hybrid_recall_at_5",
                "mrr",
                "retrieval_latency_ms",
            ]
            trends = {}
            for metric_name in trend_metrics:
                trend = await self.get_trend_analysis(
                    metric_name=metric_name,
                    strategies=strategies,
                    window_type=window_type,
                    start_time=start_time,
                    end_time=end_time,
                )
                trends[metric_name] = trend

        # Query distribution
        query_dist = None
        if include_query_distribution:
            query_dist = await self.get_query_distribution_summary(
                window_type=window_type,
                start_time=start_time,
                end_time=end_time,
            )

        # Reranker gain
        reranker = None
        if include_reranker_gain:
            reranker = await self.get_reranker_gain(window_type, dataset_name)

        # System health
        health = None
        if include_system_health:
            health = await self.get_system_health()

        return AnalyticsReportResponse(
            window_type=window_type,
            window_start=start_time,
            window_end=end_time,
            dataset_name=dataset_name,
            performance_summary=perf_summary,
            trends=trends,
            query_distribution=query_dist,
            reranker_gain=reranker,
            system_health=health,
        )