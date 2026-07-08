"""Tests for the Metrics Storage."""

import pytest
from pathlib import Path
from app.evaluation.storage import MetricsStorage
from app.evaluation.schemas import (
    HistoricalMetrics,
    RetrievalStrategy,
    StrategyEvaluationResult,
)


class TestMetricsStorage:
    """Test suite for MetricsStorage."""

    def setup_method(self):
        """Set up test fixtures."""
        self.test_dir = Path("storage/evaluation/test_metrics")
        self.storage = MetricsStorage(storage_dir=self.test_dir)

    def teardown_method(self):
        """Clean up test files."""
        if self.test_dir.exists():
            for f in self.test_dir.glob("*"):
                f.unlink()
            self.test_dir.rmdir()

    def test_store_strategy_result(self):
        """Test storing a strategy evaluation result."""
        result = StrategyEvaluationResult(
            strategy=RetrievalStrategy.DENSE,
            total_queries=5,
            avg_recall_at_5=0.8,
            avg_recall_at_10=0.9,
            avg_mrr=0.7,
            avg_precision_at_5=0.6,
            avg_precision_at_10=0.65,
            avg_hit_rate=1.0,
            avg_latency_ms=100.0,
        )

        record = self.storage.store_strategy_result(
            strategy=RetrievalStrategy.DENSE,
            dataset_name="test_dataset",
            result=result,
        )

        assert record.strategy == RetrievalStrategy.DENSE
        assert record.dataset_name == "test_dataset"
        assert record.recall_at_5 == 0.8
        assert record.mrr == 0.7

    def test_get_history(self):
        """Test retrieving historical metrics."""
        # Store multiple results
        for i in range(3):
            result = StrategyEvaluationResult(
                strategy=RetrievalStrategy.HYBRID,
                total_queries=5,
                avg_recall_at_5=0.7 + i * 0.05,
                avg_recall_at_10=0.8,
                avg_mrr=0.6,
                avg_precision_at_5=0.5,
                avg_precision_at_10=0.55,
                avg_hit_rate=1.0,
                avg_latency_ms=150.0,
            )
            self.storage.store_strategy_result(
                strategy=RetrievalStrategy.HYBRID,
                dataset_name="test",
                result=result,
            )

        history = self.storage.get_history(RetrievalStrategy.HYBRID)
        assert len(history) == 3

    def test_get_history_with_limit(self):
        """Test retrieving history with limit."""
        for i in range(5):
            result = StrategyEvaluationResult(
                strategy=RetrievalStrategy.BM25,
                total_queries=5,
                avg_recall_at_5=0.6,
                avg_recall_at_10=0.7,
                avg_mrr=0.5,
                avg_precision_at_5=0.4,
                avg_precision_at_10=0.45,
                avg_hit_rate=0.8,
                avg_latency_ms=80.0,
            )
            self.storage.store_strategy_result(
                strategy=RetrievalStrategy.BM25,
                dataset_name="test",
                result=result,
            )

        history = self.storage.get_history(RetrievalStrategy.BM25, limit=2)
        assert len(history) == 2

    def test_get_latest(self):
        """Test getting the latest metrics for a strategy."""
        # Store results with different values
        for recall in [0.6, 0.7, 0.8]:
            result = StrategyEvaluationResult(
                strategy=RetrievalStrategy.DENSE,
                total_queries=5,
                avg_recall_at_5=recall,
                avg_recall_at_10=0.85,
                avg_mrr=0.65,
                avg_precision_at_5=0.55,
                avg_precision_at_10=0.6,
                avg_hit_rate=1.0,
                avg_latency_ms=100.0,
            )
            self.storage.store_strategy_result(
                strategy=RetrievalStrategy.DENSE,
                dataset_name="test",
                result=result,
            )

        latest = self.storage.get_latest(RetrievalStrategy.DENSE)
        assert latest is not None
        assert latest.recall_at_5 == 0.8  # Last stored value

    def test_get_latest_empty(self):
        """Test getting latest when no history exists."""
        latest = self.storage.get_latest(RetrievalStrategy.HYBRID_RERANK)
        assert latest is None

    def test_get_trend(self):
        """Test getting trend data for a metric."""
        for i in range(5):
            result = StrategyEvaluationResult(
                strategy=RetrievalStrategy.DENSE,
                total_queries=5,
                avg_recall_at_5=0.5 + i * 0.1,
                avg_recall_at_10=0.6,
                avg_mrr=0.4,
                avg_precision_at_5=0.3,
                avg_precision_at_10=0.35,
                avg_hit_rate=0.9,
                avg_latency_ms=100.0,
            )
            self.storage.store_strategy_result(
                strategy=RetrievalStrategy.DENSE,
                dataset_name="test",
                result=result,
            )

        trend = self.storage.get_trend(RetrievalStrategy.DENSE, metric="recall_at_5")
        assert len(trend) == 5
        assert trend[0]["value"] == pytest.approx(0.5)
        assert trend[-1]["value"] == pytest.approx(0.9)

    def test_get_trend_with_window(self):
        """Test getting trend with window limit."""
        for i in range(10):
            result = StrategyEvaluationResult(
                strategy=RetrievalStrategy.BM25,
                total_queries=5,
                avg_recall_at_5=0.5,
                avg_recall_at_10=0.6,
                avg_mrr=0.4,
                avg_precision_at_5=0.3,
                avg_precision_at_10=0.35,
                avg_hit_rate=0.9,
                avg_latency_ms=80.0,
            )
            self.storage.store_strategy_result(
                strategy=RetrievalStrategy.BM25,
                dataset_name="test",
                result=result,
            )

        trend = self.storage.get_trend(RetrievalStrategy.BM25, window=3)
        assert len(trend) == 3

    def test_compare_strategies(self):
        """Test comparing latest metrics across strategies."""
        # Store results for different strategies
        strategies_data = {
            RetrievalStrategy.DENSE: 0.8,
            RetrievalStrategy.BM25: 0.6,
            RetrievalStrategy.HYBRID: 0.9,
        }

        for strategy, recall in strategies_data.items():
            result = StrategyEvaluationResult(
                strategy=strategy,
                total_queries=5,
                avg_recall_at_5=recall,
                avg_recall_at_10=0.85,
                avg_mrr=0.7,
                avg_precision_at_5=0.6,
                avg_precision_at_10=0.65,
                avg_hit_rate=1.0,
                avg_latency_ms=100.0,
            )
            self.storage.store_strategy_result(
                strategy=strategy,
                dataset_name="test",
                result=result,
            )

        comparison = self.storage.compare_strategies(metric="recall_at_5")
        assert comparison["dense"]["value"] == 0.8
        assert comparison["bm25"]["value"] == 0.6
        assert comparison["hybrid"]["value"] == 0.9
        assert comparison["hybrid_rerank"] is None  # No data stored

    def test_clear_history_single_strategy(self):
        """Test clearing history for a single strategy."""
        result = StrategyEvaluationResult(
            strategy=RetrievalStrategy.DENSE,
            total_queries=5,
            avg_recall_at_5=0.8,
            avg_recall_at_10=0.9,
            avg_mrr=0.7,
            avg_precision_at_5=0.6,
            avg_precision_at_10=0.65,
            avg_hit_rate=1.0,
            avg_latency_ms=100.0,
        )
        self.storage.store_strategy_result(
            strategy=RetrievalStrategy.DENSE,
            dataset_name="test",
            result=result,
        )

        assert self.storage.clear_history(RetrievalStrategy.DENSE) is True
        assert len(self.storage.get_history(RetrievalStrategy.DENSE)) == 0

    def test_clear_history_all(self):
        """Test clearing all history."""
        for strategy in [RetrievalStrategy.DENSE, RetrievalStrategy.BM25]:
            result = StrategyEvaluationResult(
                strategy=strategy,
                total_queries=5,
                avg_recall_at_5=0.7,
                avg_recall_at_10=0.8,
                avg_mrr=0.6,
                avg_precision_at_5=0.5,
                avg_precision_at_10=0.55,
                avg_hit_rate=0.9,
                avg_latency_ms=100.0,
            )
            self.storage.store_strategy_result(
                strategy=strategy,
                dataset_name="test",
                result=result,
            )

        assert self.storage.clear_history() is True
        assert len(self.storage.get_history()) == 0

    def test_get_history_all_strategies(self):
        """Test getting history for all strategies."""
        for strategy in [RetrievalStrategy.DENSE, RetrievalStrategy.HYBRID]:
            result = StrategyEvaluationResult(
                strategy=strategy,
                total_queries=5,
                avg_recall_at_5=0.7,
                avg_recall_at_10=0.8,
                avg_mrr=0.6,
                avg_precision_at_5=0.5,
                avg_precision_at_10=0.55,
                avg_hit_rate=0.9,
                avg_latency_ms=100.0,
            )
            self.storage.store_strategy_result(
                strategy=strategy,
                dataset_name="test",
                result=result,
            )

        all_history = self.storage.get_history()
        assert len(all_history) == 2


class TestHistoricalMetrics:
    """Test suite for HistoricalMetrics schema."""

    def test_create_historical_metrics(self):
        """Test creating a HistoricalMetrics record."""
        record = HistoricalMetrics(
            strategy=RetrievalStrategy.DENSE,
            dataset_name="test",
            recall_at_5=0.85,
            recall_at_10=0.90,
            mrr=0.75,
            precision_at_5=0.65,
            precision_at_10=0.70,
            hit_rate=1.0,
            latency_ms=120.5,
        )

        assert record.strategy == RetrievalStrategy.DENSE
        assert record.recall_at_5 == 0.85
        assert record.timestamp is not None

    def test_historical_metrics_with_metadata(self):
        """Test HistoricalMetrics with metadata."""
        record = HistoricalMetrics(
            strategy=RetrievalStrategy.HYBRID,
            dataset_name="test",
            recall_at_5=0.9,
            recall_at_10=0.95,
            mrr=0.8,
            precision_at_5=0.7,
            precision_at_10=0.75,
            hit_rate=1.0,
            latency_ms=150.0,
            metadata={"total_queries": 10, "version": "1.0"},
        )

        assert record.metadata["total_queries"] == 10
