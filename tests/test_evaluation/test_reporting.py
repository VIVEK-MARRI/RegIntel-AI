"""Tests for the Reporting System."""

import json
import pytest
from pathlib import Path
from datetime import datetime
from app.evaluation.reporting import ReportGenerator, Leaderboard
from app.evaluation.schemas import (
    EvaluationReport,
    EvaluationConfig,
    GoldenDataset,
    QueryRelevance,
    QueryEvaluationResult,
    RetrievalResult,
    RetrievalStrategy,
    StrategyEvaluationResult,
)


class TestReportGenerator:
    """Test suite for ReportGenerator."""

    def setup_method(self):
        """Set up test fixtures."""
        self.test_dir = Path("storage/evaluation/test_reports")
        self.generator = ReportGenerator(reports_dir=self.test_dir)

    def teardown_method(self):
        """Clean up test files."""
        if self.test_dir.exists():
            for f in self.test_dir.glob("*"):
                f.unlink()
            self.test_dir.rmdir()

    def _create_sample_report(self) -> EvaluationReport:
        """Create a sample evaluation report for testing."""
        query_results = [
            QueryEvaluationResult(
                query_id="q1",
                query_text="Test query 1",
                strategy=RetrievalStrategy.DENSE,
                retrieved_results=[
                    RetrievalResult(chunk_id="c1", score=0.9, rank=1),
                    RetrievalResult(chunk_id="c2", score=0.8, rank=2),
                ],
                relevant_chunk_ids=["c1", "c3"],
                recall_at_5=0.5,
                recall_at_10=0.5,
                mrr=1.0,
                precision_at_5=0.2,
                precision_at_10=0.1,
                hit_rate=1.0,
                latency_ms=100.0,
            ),
        ]

        strategy_results = [
            StrategyEvaluationResult(
                strategy=RetrievalStrategy.DENSE,
                total_queries=1,
                avg_recall_at_5=0.8,
                avg_recall_at_10=0.9,
                avg_mrr=0.7,
                avg_precision_at_5=0.6,
                avg_precision_at_10=0.65,
                avg_hit_rate=1.0,
                avg_latency_ms=100.0,
                query_results=query_results,
            ),
            StrategyEvaluationResult(
                strategy=RetrievalStrategy.BM25,
                total_queries=1,
                avg_recall_at_5=0.6,
                avg_recall_at_10=0.7,
                avg_mrr=0.5,
                avg_precision_at_5=0.4,
                avg_precision_at_10=0.45,
                avg_hit_rate=0.8,
                avg_latency_ms=80.0,
                query_results=query_results,
            ),
        ]

        leaderboard = [
            {
                "rank": 1,
                "strategy": "dense",
                "avg_recall_at_5": 0.8,
                "avg_recall_at_10": 0.9,
                "avg_mrr": 0.7,
                "avg_precision_at_5": 0.6,
                "avg_hit_rate": 1.0,
                "avg_latency_ms": 100.0,
                "composite_score": 0.75,
            },
            {
                "rank": 2,
                "strategy": "bm25",
                "avg_recall_at_5": 0.6,
                "avg_recall_at_10": 0.7,
                "avg_mrr": 0.5,
                "avg_precision_at_5": 0.4,
                "avg_hit_rate": 0.8,
                "avg_latency_ms": 80.0,
                "composite_score": 0.58,
            },
        ]

        return EvaluationReport(
            dataset_name="test_dataset",
            strategy_results=strategy_results,
            leaderboard=leaderboard,
        )

    def test_generate_report(self):
        """Test generating a report."""
        report = self._create_sample_report()
        report_path = self.generator.generate_report(report)

        assert report_path.exists()
        assert report_path.suffix == ".json"

        # Check markdown was also generated
        md_path = report_path.with_suffix(".md")
        assert md_path.exists()

    def test_report_json_content(self):
        """Test that report JSON contains expected data."""
        report = self._create_sample_report()
        report_path = self.generator.generate_report(report)

        with open(report_path, "r") as f:
            data = json.load(f)

        assert data["dataset_name"] == "test_dataset"
        assert len(data["strategy_results"]) == 2
        assert len(data["leaderboard"]) == 2

    def test_markdown_content(self):
        """Test that markdown report contains expected sections."""
        report = self._create_sample_report()
        report_path = self.generator.generate_report(report)
        md_path = report_path.with_suffix(".md")

        with open(md_path, "r") as f:
            content = f.read()

        assert "# Retrieval Evaluation Report" in content
        assert "## Leaderboard" in content
        assert "## Detailed Results" in content
        assert "dense" in content
        assert "bm25" in content

    def test_generate_comparison_table(self):
        """Test generating comparison table across reports."""
        reports = [self._create_sample_report(), self._create_sample_report()]

        table = self.generator.generate_comparison_table(reports)

        assert "# Strategy Comparison Across Evaluations" in table
        assert "dense" in table
        assert "bm25" in table


class TestLeaderboard:
    """Test suite for Leaderboard."""

    def setup_method(self):
        """Set up test fixtures."""
        self.test_dir = Path("storage/evaluation/test_reports")
        self.leaderboard = Leaderboard(reports_dir=self.test_dir)
        self.generator = ReportGenerator(reports_dir=self.test_dir)

    def teardown_method(self):
        """Clean up test files."""
        if self.test_dir.exists():
            for f in self.test_dir.glob("*"):
                f.unlink()
            self.test_dir.rmdir()

    def _create_and_save_report(self) -> EvaluationReport:
        """Create and save a sample report."""
        report = EvaluationReport(
            dataset_name="test",
            strategy_results=[],
            leaderboard=[
                {
                    "rank": 1,
                    "strategy": "hybrid",
                    "avg_recall_at_5": 0.9,
                    "avg_recall_at_10": 0.95,
                    "avg_mrr": 0.85,
                    "avg_precision_at_5": 0.8,
                    "avg_hit_rate": 1.0,
                    "avg_latency_ms": 150.0,
                    "composite_score": 0.88,
                },
                {
                    "rank": 2,
                    "strategy": "dense",
                    "avg_recall_at_5": 0.8,
                    "avg_recall_at_10": 0.85,
                    "avg_mrr": 0.7,
                    "avg_precision_at_5": 0.6,
                    "avg_hit_rate": 1.0,
                    "avg_latency_ms": 100.0,
                    "composite_score": 0.75,
                },
            ],
        )
        self.generator.generate_report(report)
        return report

    def test_get_latest_leaderboard(self):
        """Test getting the latest leaderboard."""
        self._create_and_save_report()

        leaderboard = self.leaderboard.get_latest_leaderboard()
        assert leaderboard is not None
        assert len(leaderboard) == 2
        assert leaderboard[0]["strategy"] == "hybrid"
        assert leaderboard[0]["rank"] == 1

    def test_get_latest_leaderboard_empty(self):
        """Test getting leaderboard when no reports exist."""
        leaderboard = self.leaderboard.get_latest_leaderboard()
        assert leaderboard is None

    def test_get_strategy_ranking(self):
        """Test getting ranking for a specific strategy."""
        self._create_and_save_report()

        ranking = self.leaderboard.get_strategy_ranking(RetrievalStrategy.HYBRID)
        assert ranking is not None
        assert ranking["rank"] == 1
        assert ranking["composite_score"] == 0.88

    def test_get_strategy_ranking_not_found(self):
        """Test getting ranking for strategy not in leaderboard."""
        self._create_and_save_report()

        ranking = self.leaderboard.get_strategy_ranking(RetrievalStrategy.BM25)
        assert ranking is None

    def test_format_leaderboard(self):
        """Test formatting leaderboard for display."""
        leaderboard = [
            {
                "rank": 1,
                "strategy": "hybrid",
                "avg_recall_at_5": 0.9,
                "avg_mrr": 0.85,
                "avg_latency_ms": 150.0,
                "composite_score": 0.88,
            },
            {
                "rank": 2,
                "strategy": "dense",
                "avg_recall_at_5": 0.8,
                "avg_mrr": 0.7,
                "avg_latency_ms": 100.0,
                "composite_score": 0.75,
            },
        ]

        formatted = self.leaderboard.format_leaderboard(leaderboard)

        assert "RETRIEVAL STRATEGY LEADERBOARD" in formatted
        assert "#1 hybrid" in formatted
        assert "#2 dense" in formatted
        assert "0.88" in formatted


class TestEvaluationReport:
    """Test suite for EvaluationReport schema."""

    def test_create_evaluation_report(self):
        """Test creating an EvaluationReport."""
        report = EvaluationReport(
            dataset_name="test",
            strategy_results=[],
            leaderboard=[],
        )

        assert report.dataset_name == "test"
        assert report.report_id is not None
        assert report.timestamp is not None

    def test_evaluation_report_serialization(self):
        """Test serializing EvaluationReport."""
        report = EvaluationReport(
            dataset_name="test",
            strategy_results=[],
            leaderboard=[{"rank": 1, "strategy": "dense"}],
        )

        data = report.model_dump()
        assert data["dataset_name"] == "test"
        assert len(data["leaderboard"]) == 1


class TestEvaluationConfig:
    """Test suite for EvaluationConfig schema."""

    def test_default_config(self):
        """Test default evaluation configuration."""
        config = EvaluationConfig()

        assert config.dataset_name == "default"
        assert len(config.strategies) == 4
        assert RetrievalStrategy.DENSE in config.strategies
        assert RetrievalStrategy.BM25 in config.strategies
        assert RetrievalStrategy.HYBRID in config.strategies
        assert RetrievalStrategy.HYBRID_RERANK in config.strategies

    def test_custom_config(self):
        """Test custom evaluation configuration."""
        config = EvaluationConfig(
            dataset_name="custom",
            strategies=[RetrievalStrategy.DENSE, RetrievalStrategy.HYBRID],
            top_k_values=[5, 10, 20],
            store_results=False,
        )

        assert config.dataset_name == "custom"
        assert len(config.strategies) == 2
        assert config.top_k_values == [5, 10, 20]
        assert config.store_results is False
