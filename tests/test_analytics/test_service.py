"""Tests for the AnalyticsService."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.analytics import RetrievalMetricsCreate
from app.services.analytics.service import AnalyticsService


@pytest.mark.asyncio
class TestMetricsRecording:
    """Tests for metrics recording operations."""

    async def test_record_single_metric(self, db_session):
        """Test recording a single metric."""
        service = AnalyticsService(db_session)
        data = RetrievalMetricsCreate(
            query_id=str(uuid.uuid4()),
            query_text="Test query",
            strategy="dense",
            dense_recall_at_5=0.75,
            mrr=0.80,
            retrieval_latency_ms=45.0,
        )
        result = await service.record_metrics(data)

        assert result.query_text == "Test query"
        assert result.strategy == "dense"
        assert result.dense_recall_at_5 == 0.75
        assert result.mrr == 0.80
        assert result.id is not None

    async def test_record_batch_metrics(self, db_session):
        """Test recording batch metrics."""
        service = AnalyticsService(db_session)
        items = [
            RetrievalMetricsCreate(
                query_id=str(uuid.uuid4()),
                query_text=f"Batch query {i}",
                strategy="dense" if i % 2 == 0 else "bm25",
                dense_recall_at_5=0.5 + (i * 0.1),
            )
            for i in range(5)
        ]
        results = await service.record_metrics_batch(items)

        assert len(results) == 5
        assert results[0].strategy == "dense"
        assert results[1].strategy == "bm25"


@pytest.mark.asyncio
class TestMetricsQuerying:
    """Tests for metrics querying operations."""

    async def test_query_by_strategy(self, db_session):
        """Test querying metrics filtered by strategy."""
        service = AnalyticsService(db_session)

        # Create records for different strategies
        for i in range(3):
            await service.record_metrics(
                RetrievalMetricsCreate(
                    query_id=str(uuid.uuid4()),
                    query_text=f"Dense query {i}",
                    strategy="dense",
                )
            )
        for i in range(2):
            await service.record_metrics(
                RetrievalMetricsCreate(
                    query_id=str(uuid.uuid4()),
                    query_text=f"BM25 query {i}",
                    strategy="bm25",
                )
            )
        await db_session.commit()

        result = await service.query_metrics(strategy="dense")
        assert result["total"] == 3
        for item in result["items"]:
            assert item.strategy == "dense"

    async def test_query_with_pagination(self, db_session):
        """Test querying metrics with pagination."""
        service = AnalyticsService(db_session)

        for i in range(10):
            await service.record_metrics(
                RetrievalMetricsCreate(
                    query_id=str(uuid.uuid4()),
                    query_text=f"Query {i}",
                    strategy="dense",
                )
            )
        await db_session.commit()

        result = await service.query_metrics(limit=5, offset=0)
        assert result["total"] == 10
        assert len(result["items"]) == 5

        result2 = await service.query_metrics(limit=5, offset=5)
        assert len(result2["items"]) == 5


@pytest.mark.asyncio
class TestAggregatedMetrics:
    """Tests for aggregated metrics operations."""

    async def test_get_aggregated_metrics(self, db_session):
        """Test computing aggregated metrics."""
        service = AnalyticsService(db_session)

        for i in range(5):
            await service.record_metrics(
                RetrievalMetricsCreate(
                    query_id=str(uuid.uuid4()),
                    query_text=f"Query {i}",
                    strategy="dense",
                    dense_recall_at_5=0.5 + (i * 0.1),
                    mrr=0.6 + (i * 0.05),
                    retrieval_latency_ms=30.0 + (i * 10),
                )
            )
        await db_session.commit()

        agg = await service.get_aggregated_metrics(strategy="dense")

        assert agg["total_queries"] == 5
        assert agg["avg_dense_recall_at_5"] is not None
        assert agg["avg_mrr"] is not None
        assert agg["avg_retrieval_latency_ms"] is not None

    async def test_aggregated_metrics_with_no_data(self, db_session):
        """Test aggregated metrics with no matching data."""
        service = AnalyticsService(db_session)

        agg = await service.get_aggregated_metrics(strategy="nonexistent")

        assert agg["total_queries"] == 0
        assert agg["avg_dense_recall_at_5"] is None


@pytest.mark.asyncio
class TestTrendAnalysis:
    """Tests for trend analysis operations."""

    async def test_trend_analysis_basic(self, db_session):
        """Test basic trend analysis."""
        service = AnalyticsService(db_session)
        now = datetime.now(timezone.utc)

        # Create records with improving trend
        for i in range(5):
            await service.record_metrics(
                RetrievalMetricsCreate(
                    query_id=str(uuid.uuid4()),
                    query_text=f"Query {i}",
                    strategy="dense",
                    dense_recall_at_5=0.5 + (i * 0.08),
                )
            )
        await db_session.commit()

        trend = await service.get_trend_analysis(
            metric_name="dense_recall_at_5",
            strategies=["dense"],
            window_type="daily",
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )

        assert trend.metric_name == "dense_recall_at_5"
        assert len(trend.series) == 1
        assert trend.series[0].strategy == "dense"

    async def test_trend_analysis_no_data(self, db_session):
        """Test trend analysis with no data."""
        service = AnalyticsService(db_session)
        now = datetime.now(timezone.utc)

        trend = await service.get_trend_analysis(
            metric_name="dense_recall_at_5",
            strategies=["dense"],
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )

        assert len(trend.series) == 1
        assert len(trend.series[0].data_points) == 0

    def test_compute_trend_improving(self):
        """Test trend computation with improving values."""
        from app.schemas.analytics import TrendDataPoint

        service = AnalyticsService.__new__(AnalyticsService)

        points = [
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.5),
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.6),
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.7),
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.8),
        ]

        direction, slope = service._compute_trend(points)
        assert direction == "improving"
        assert slope > 0

    def test_compute_trend_degrading(self):
        """Test trend computation with degrading values."""
        from app.schemas.analytics import TrendDataPoint

        service = AnalyticsService.__new__(AnalyticsService)

        points = [
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.8),
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.7),
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.6),
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.5),
        ]

        direction, slope = service._compute_trend(points)
        assert direction == "degrading"
        assert slope < 0

    def test_compute_trend_stable(self):
        """Test trend computation with stable values."""
        from app.schemas.analytics import TrendDataPoint

        service = AnalyticsService.__new__(AnalyticsService)

        points = [
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.750),
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.751),
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.750),
            TrendDataPoint(timestamp=datetime.now(timezone.utc), value=0.749),
        ]

        direction, slope = service._compute_trend(points)
        assert direction == "stable"


@pytest.mark.asyncio
class TestPerformanceSummary:
    """Tests for performance summary operations."""

    async def test_performance_summary(self, db_session):
        """Test generating performance summary."""
        service = AnalyticsService(db_session)

        for strategy in ["dense", "bm25", "hybrid"]:
            for i in range(3):
                await service.record_metrics(
                    RetrievalMetricsCreate(
                        query_id=str(uuid.uuid4()),
                        query_text=f"{strategy} query {i}",
                        strategy=strategy,
                        dense_recall_at_5=0.6 + (i * 0.05),
                        mrr=0.7 + (i * 0.03),
                    )
                )
        await db_session.commit()

        summary = await service.get_performance_summary(
            window_type="daily",
            start_time=datetime.now(timezone.utc) - timedelta(days=1),
            end_time=datetime.now(timezone.utc) + timedelta(days=1),
        )

        assert len(summary.strategies) == 3
        assert summary.total_queries == 9
        assert summary.best_strategy is not None

        for perf in summary.strategies:
            assert perf.strategy in ["dense", "bm25", "hybrid"]
            assert perf.composite_score is not None

    def test_compute_composite_score(self):
        """Test composite score computation."""
        from app.schemas.analytics import StrategyPerformance

        service = AnalyticsService.__new__(AnalyticsService)

        perf = StrategyPerformance(
            strategy="dense",
            avg_dense_recall_at_5=0.8,
            avg_bm25_recall_at_5=0.7,
            avg_hybrid_recall_at_5=0.75,
            avg_precision_at_5=0.7,
            avg_mrr=0.85,
            avg_hit_rate=0.9,
            avg_reranker_gain=0.05,
        )

        score = service._compute_composite_score(perf)
        assert 0.0 <= score <= 1.0


@pytest.mark.asyncio
class TestStrategyComparison:
    """Tests for strategy comparison operations."""

    async def test_compare_strategies(self, db_session):
        """Test comparing strategies on a metric."""
        service = AnalyticsService(db_session)

        for strategy in ["dense", "bm25"]:
            for i in range(3):
                await service.record_metrics(
                    RetrievalMetricsCreate(
                        query_id=str(uuid.uuid4()),
                        query_text=f"{strategy} query {i}",
                        strategy=strategy,
                        dense_recall_at_5=0.7 if strategy == "dense" else 0.5,
                    )
                )
        await db_session.commit()

        comparison = await service.compare_strategies(
            metric_name="dense_recall_at_5",
            start_time=datetime.now(timezone.utc) - timedelta(days=1),
            end_time=datetime.now(timezone.utc) + timedelta(days=1),
        )

        assert comparison.metric_name == "dense_recall_at_5"
        assert "dense" in comparison.comparisons
        assert "bm25" in comparison.comparisons
        assert comparison.winner == "dense"


@pytest.mark.asyncio
class TestQueryDistribution:
    """Tests for query distribution operations."""

    async def test_record_and_get_distribution(self, db_session):
        """Test recording and retrieving query distribution."""
        service = AnalyticsService(db_session)
        now = datetime.now(timezone.utc)

        cat_counts = {
            "factual": 50,
            "navigational": 20,
            "analytical": 15,
            "comparative": 10,
            "definitional": 5,
            "procedural": 0,
            "unknown": 0,
        }
        strat_counts = {
            "dense": 30,
            "bm25": 25,
            "hybrid": 25,
            "hybrid_rerank": 20,
        }

        result = await service.record_query_distribution(
            window_type="daily",
            window_start=now,
            window_end=now,
            category_counts=cat_counts,
            strategy_counts=strat_counts,
            avg_query_length=12.5,
            avg_result_count=8.0,
        )

        assert result.total_queries == 100
        assert result.category_distribution["factual"] == 50
        assert result.strategy_distribution["dense"] == 30
        assert result.category_percentages["factual"] == 50.0
        assert result.avg_query_length == 12.5


@pytest.mark.asyncio
class TestRerankerGain:
    """Tests for reranker gain operations."""

    async def test_record_and_get_reranker_gain(self, db_session):
        """Test recording and retrieving reranker gain."""
        service = AnalyticsService(db_session)
        now = datetime.now(timezone.utc)

        result = await service.record_reranker_gain(
            window_type="daily",
            window_start=now,
            window_end=now,
            avg_recall_gain_at_5=0.05,
            avg_recall_gain_at_10=0.03,
            avg_mrr_gain=0.06,
            avg_reranker_latency_ms=120.0,
            reranker_queries_count=100,
            improvement_rate=0.75,
        )

        assert result.avg_recall_gain_at_5 == 0.05
        assert result.improvement_rate == 0.75
        assert result.reranker_queries_count == 100

        # Retrieve
        latest = await service.get_reranker_gain("daily")
        assert latest is not None
        assert latest.avg_recall_gain_at_5 == 0.05

    async def test_reranker_gain_not_found(self, db_session):
        """Test retrieving reranker gain when none exists."""
        service = AnalyticsService(db_session)

        result = await service.get_reranker_gain("daily")
        assert result is None


@pytest.mark.asyncio
class TestSystemHealth:
    """Tests for system health operations."""

    async def test_record_and_get_health(self, db_session):
        """Test recording and retrieving system health."""
        service = AnalyticsService(db_session)

        result = await service.record_system_health(
            status="healthy",
            dense_available=True,
            bm25_available=True,
            hybrid_available=True,
            reranker_available=True,
            index_consistent=True,
            embedding_coverage=95.5,
            total_indexed=1000,
            avg_latency=50.0,
            queries_last_hour=500,
            error_rate=0.01,
        )

        assert result.status == "healthy"
        assert result.embedding_coverage_pct == 95.5
        assert result.dense_retrieval_available is True

        # Retrieve
        latest = await service.get_system_health()
        assert latest.status == "healthy"

    async def test_default_health_when_empty(self, db_session):
        """Test default health response when no records exist."""
        service = AnalyticsService(db_session)

        result = await service.get_system_health()
        assert result.status == "healthy"
        assert result.dense_retrieval_available is True


@pytest.mark.asyncio
class TestReportGeneration:
    """Tests for report generation."""

    async def test_generate_report(self, db_session):
        """Test generating a comprehensive analytics report."""
        service = AnalyticsService(db_session)

        # Create some data
        for strategy in ["dense", "bm25"]:
            for i in range(3):
                await service.record_metrics(
                    RetrievalMetricsCreate(
                        query_id=str(uuid.uuid4()),
                        query_text=f"{strategy} query {i}",
                        strategy=strategy,
                        dense_recall_at_5=0.6 + (i * 0.05),
                        mrr=0.7 + (i * 0.03),
                    )
                )
        await db_session.commit()

        now = datetime.now(timezone.utc)
        report = await service.generate_report(
            window_type="daily",
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
        )

        assert report.report_id is not None
        assert report.performance_summary is not None
        assert len(report.performance_summary.strategies) == 2
        assert report.trends is not None
        assert "dense_recall_at_5" in report.trends

    async def test_generate_report_minimal(self, db_session):
        """Test generating a report with minimal data."""
        service = AnalyticsService(db_session)

        now = datetime.now(timezone.utc)
        report = await service.generate_report(
            window_type="daily",
            start_time=now - timedelta(days=1),
            end_time=now + timedelta(days=1),
            include_trends=False,
            include_query_distribution=False,
            include_reranker_gain=False,
            include_system_health=False,
        )

        assert report.report_id is not None
        assert report.trends is None
        assert report.query_distribution is None
        assert report.reranker_gain is None
        assert report.system_health is None
