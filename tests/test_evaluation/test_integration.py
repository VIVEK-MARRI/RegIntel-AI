"""End-to-end integration tests for the Retrieval Evaluation Suite.

Tests the full pipeline: dataset loading -> evaluation -> metrics -> reporting -> storage.
Uses the StandaloneEvaluator which requires no database connection.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.evaluation.dataset import DatasetManager, create_sample_dataset_with_ids
from app.evaluation.evaluator import RetrievalEvaluator
from app.evaluation.metrics import MetricsEngine
from app.evaluation.reporting import ReportGenerator, Leaderboard
from app.evaluation.runner import StandaloneEvaluator, SimulatedRetriever, STRATEGY_PROFILES
from app.evaluation.schemas import (
    EvaluationConfig,
    EvaluationReport,
    GoldenDataset,
    QueryRelevance,
    RetrievalResult,
    RetrievalStrategy,
)
from app.evaluation.storage import MetricsStorage


# =====================================================================
# Integration: Full Pipeline Tests
# =====================================================================

class TestFullPipeline:
    """End-to-end evaluation pipeline tests."""

    def setup_method(self):
        """Set up test fixtures."""
        self.test_dir = Path("storage/integration_test")
        self.dataset_dir = self.test_dir / "datasets"
        self.reports_dir = self.test_dir / "reports"
        self.metrics_dir = self.test_dir / "metrics"

        for d in [self.dataset_dir, self.reports_dir, self.metrics_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.dataset_manager = DatasetManager(dataset_dir=self.dataset_dir)
        self.metrics_storage = MetricsStorage(storage_dir=self.metrics_dir)
        self.report_generator = ReportGenerator(reports_dir=self.reports_dir)
        self.leaderboard = Leaderboard(reports_dir=self.reports_dir)

    def teardown_method(self):
        """Clean up test files."""
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def _create_test_dataset(self) -> GoldenDataset:
        """Create a test dataset with 10 chunk IDs per query."""
        chunk_ids = [f"chunk_{i:03d}" for i in range(20)]
        return create_sample_dataset_with_ids(chunk_ids[:10])

    @pytest.mark.asyncio
    async def test_standalone_evaluation_all_strategies(self):
        """Test running all 4 strategies end-to-end."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            strategies=[
                RetrievalStrategy.DENSE,
                RetrievalStrategy.BM25,
                RetrievalStrategy.HYBRID,
                RetrievalStrategy.HYBRID_RERANK,
            ],
            store_results=True,
        )

        report = await evaluator.run_evaluation(config)

        # Verify report structure
        assert report.dataset_name == "sample_with_ids"
        assert len(report.strategy_results) == 4
        assert len(report.leaderboard) == 4

        # Verify all strategies are represented
        strategies_in_report = {r.strategy for r in report.strategy_results}
        assert RetrievalStrategy.DENSE in strategies_in_report
        assert RetrievalStrategy.BM25 in strategies_in_report
        assert RetrievalStrategy.HYBRID in strategies_in_report
        assert RetrievalStrategy.HYBRID_RERANK in strategies_in_report

    @pytest.mark.asyncio
    async def test_report_contains_all_metrics(self):
        """Test that reports include all required metrics."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=False,
        )

        report = await evaluator.run_evaluation(config)

        for result in report.strategy_results:
            # All metrics should be present and valid
            assert 0.0 <= result.avg_recall_at_5 <= 1.0
            assert 0.0 <= result.avg_recall_at_10 <= 1.0
            assert 0.0 <= result.avg_mrr <= 1.0
            assert 0.0 <= result.avg_precision_at_5 <= 1.0
            assert 0.0 <= result.avg_precision_at_10 <= 1.0
            assert 0.0 <= result.avg_hit_rate <= 1.0
            assert 0.0 <= result.avg_ndcg_at_5 <= 1.0
            assert 0.0 <= result.avg_ndcg_at_10 <= 1.0
            assert result.avg_latency_ms >= 0.0

    @pytest.mark.asyncio
    async def test_per_strategy_query_results(self):
        """Test that per-query results contain all metrics."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=False,
        )

        report = await evaluator.run_evaluation(config)

        for strategy_result in report.strategy_results:
            assert strategy_result.total_queries == len(dataset.queries)
            assert len(strategy_result.query_results) == len(dataset.queries)

            for qr in strategy_result.query_results:
                assert qr.query_id is not None
                assert qr.query_text is not None
                assert 0.0 <= qr.recall_at_5 <= 1.0
                assert 0.0 <= qr.recall_at_10 <= 1.0
                assert 0.0 <= qr.mrr <= 1.0
                assert 0.0 <= qr.ndcg_at_5 <= 1.0
                assert 0.0 <= qr.ndcg_at_10 <= 1.0
                assert qr.hit_rate in (0.0, 1.0)

    @pytest.mark.asyncio
    async def test_leaderboard_ranking_consistency(self):
        """Test that leaderboard rankings are consistent."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=False,
        )

        report = await evaluator.run_evaluation(config)

        # Leaderboard should be sorted by composite score descending
        scores = [entry["composite_score"] for entry in report.leaderboard]
        assert scores == sorted(scores, reverse=True)

        # Ranks should be sequential starting from 1
        ranks = [entry["rank"] for entry in report.leaderboard]
        assert ranks == list(range(1, len(ranks) + 1))

    @pytest.mark.asyncio
    async def test_hybrid_rerank_outperforms_dense(self):
        """Test that hybrid_rerank generally outperforms dense retrieval."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=False,
        )

        report = await evaluator.run_evaluation(config)

        dense_result = next(r for r in report.strategy_results
                           if r.strategy == RetrievalStrategy.DENSE)
        hybrid_rerank_result = next(r for r in report.strategy_results
                                    if r.strategy == RetrievalStrategy.HYBRID_RERANK)

        # hybrid_rerank should have higher recall@5 (as per simulation profile)
        assert hybrid_rerank_result.avg_recall_at_5 >= dense_result.avg_recall_at_5

    @pytest.mark.asyncio
    async def test_metrics_storage_after_evaluation(self):
        """Test that metrics are properly stored after evaluation."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=True,
        )

        await evaluator.run_evaluation(config)

        # Verify storage for each strategy
        for strategy in RetrievalStrategy:
            history = self.metrics_storage.get_history(strategy)
            assert len(history) == 1
            assert history[0].dataset_name == "sample_with_ids"
            assert history[0].strategy == strategy

            # Verify NDCG fields are stored
            assert 0.0 <= history[0].ndcg_at_5 <= 1.0
            assert 0.0 <= history[0].ndcg_at_10 <= 1.0

    @pytest.mark.asyncio
    async def test_report_generation_after_evaluation(self):
        """Test that reports are correctly generated from evaluation results."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=True,
        )

        report = await evaluator.run_evaluation(config)

        # Generate report files
        report_path = self.report_generator.generate_report(report)
        assert report_path.exists()

        # Verify JSON content
        with open(report_path, "r") as f:
            json_data = json.load(f)
        assert json_data["dataset_name"] == "sample_with_ids"
        assert len(json_data["strategy_results"]) == 4
        assert len(json_data["leaderboard"]) == 4

        # Verify Markdown exists
        md_path = report_path.with_suffix(".md")
        assert md_path.exists()

        with open(md_path, "r") as f:
            md_content = f.read()

        # Check for all required metrics in markdown
        assert "# Retrieval Evaluation Report" in md_content
        assert "## Leaderboard" in md_content
        assert "NDCG@5" in md_content
        assert "NDCG@10" in md_content
        assert "## Detailed Results" in md_content

        for strategy in RetrievalStrategy:
            assert strategy.value in md_content

    @pytest.mark.asyncio
    async def test_leaderboard_persisted_and_retrievable(self):
        """Test that leaderboard data can be read back from saved reports."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=True,
        )

        report = await evaluator.run_evaluation(config)
        self.report_generator.generate_report(report)

        # Retrieve from leaderboard
        lb = self.leaderboard.get_latest_leaderboard()
        assert lb is not None
        assert len(lb) == 4

        # Each entry should have NDCG fields
        for entry in lb:
            assert "avg_ndcg_at_5" in entry
            assert "avg_ndcg_at_10" in entry

    @pytest.mark.asyncio
    async def test_comparison_output_format(self):
        """Test that the output format matches the required specification."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=False,
        )

        report = await evaluator.run_evaluation(config)

        for result in report.strategy_results:
            output = {
                "strategy": result.strategy.value,
                "recall_at_5": round(result.avg_recall_at_5, 4),
            }

            # Must match required output format
            assert "strategy" in output
            assert isinstance(output["strategy"], str)
            assert isinstance(output["recall_at_5"], float)

    @pytest.mark.asyncio
    async def test_multiple_evaluations_accumulate_history(self):
        """Test that running evaluations multiple times accumulates history."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=True,
        )

        # Run evaluation twice
        await evaluator.run_evaluation(config)
        await evaluator.run_evaluation(config)

        # Each strategy should have 2 records
        for strategy in RetrievalStrategy:
            history = self.metrics_storage.get_history(strategy)
            assert len(history) == 2

    @pytest.mark.asyncio
    async def test_historical_metrics_trend(self):
        """Test trend retrieval from historical metrics."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=True,
        )

        # Run 3 times
        for _ in range(3):
            await evaluator.run_evaluation(config)

        for strategy in RetrievalStrategy:
            trend = self.metrics_storage.get_trend(strategy, metric="recall_at_5")
            assert len(trend) == 3

            trend_ndcg = self.metrics_storage.get_trend(strategy, metric="ndcg_at_5")
            assert len(trend_ndcg) == 3

    @pytest.mark.asyncio
    async def test_strategy_comparison(self):
        """Test comparing strategies using stored metrics."""
        dataset = self._create_test_dataset()
        self.dataset_manager.save_dataset(dataset)

        evaluator = StandaloneEvaluator(
            dataset_manager=self.dataset_manager,
            metrics_storage=self.metrics_storage,
            seed=42,
        )

        config = EvaluationConfig(
            dataset_name="sample_with_ids",
            store_results=True,
        )

        await evaluator.run_evaluation(config)

        # Compare on recall@5
        comparison_r5 = self.metrics_storage.compare_strategies(metric="recall_at_5")
        for strategy in RetrievalStrategy:
            assert strategy.value in comparison_r5
            assert comparison_r5[strategy.value] is not None
            assert "value" in comparison_r5[strategy.value]

        # Compare on ndcg
        comparison_ndcg = self.metrics_storage.compare_strategies(metric="ndcg_at_5")
        for strategy in RetrievalStrategy:
            assert strategy.value in comparison_ndcg
            assert comparison_ndcg[strategy.value] is not None


# =====================================================================
# Strategy Simulation Tests
# =====================================================================

class TestSimulatedRetriever:
    """Tests for the simulated retriever."""

    def setup_method(self):
        self.retriever = SimulatedRetriever(seed=42)

    def _make_query(self, relevant_ids):
        return QueryRelevance(
            query_id="q_test",
            query_text="test query",
            relevant_chunk_ids=relevant_ids,
        )

    def test_retrieval_returns_requested_count(self):
        """Test that retrieval returns exactly top_k results."""
        query = self._make_query(["chunk_cap_001", "chunk_cap_002"])
        for strategy in RetrievalStrategy:
            results = self.retriever.retrieve(query, strategy, top_k=10)
            assert len(results) == 10

    def test_retrieval_results_ordered_by_score(self):
        """Test that results are ordered by score descending."""
        query = self._make_query(["chunk_cap_001"])
        for strategy in RetrievalStrategy:
            results = self.retriever.retrieve(query, strategy, top_k=20)
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_different_strategies_produce_different_results(self):
        """Test that different strategies produce different result sets."""
        query = self._make_query(["chunk_cap_001", "chunk_cap_002", "chunk_cap_003"])
        all_results = {}
        for strategy in RetrievalStrategy:
            results = self.retriever.retrieve(query, strategy, top_k=20)
            all_results[strategy.value] = [r["chunk_id"] for r in results]

        # At least some strategies should differ
        result_sets = list(all_results.values())
        assert len(set(tuple(r) for r in result_sets)) > 1

    def test_retrieval_includes_relevant_items(self):
        """Test that relevant items appear in retrieval results."""
        query = self._make_query(["chunk_cap_001", "chunk_cap_002"])
        results = self.retriever.retrieve(query, RetrievalStrategy.DENSE, top_k=20)
        result_ids = {r["chunk_id"] for r in results}
        # At least one relevant should be present (due to recall bias)
        assert len(result_ids.intersection({"chunk_cap_001", "chunk_cap_002"})) > 0

    def test_reproducibility_with_same_seed(self):
        """Test that the same seed produces identical results."""
        retriever1 = SimulatedRetriever(seed=123)
        retriever2 = SimulatedRetriever(seed=123)

        query = self._make_query(["chunk_cap_001"])

        results1 = retriever1.retrieve(query, RetrievalStrategy.HYBRID, top_k=10)
        results2 = retriever2.retrieve(query, RetrievalStrategy.HYBRID, top_k=10)

        assert [r["chunk_id"] for r in results1] == [r["chunk_id"] for r in results2]

    def test_bm25_has_lower_latency_profile(self):
        """Test that BM25 has the lowest latency among all strategies."""
        bm25_profile = STRATEGY_PROFILES["bm25"]
        for name, profile in STRATEGY_PROFILES.items():
            if name != "bm25":
                assert bm25_profile["latency_ms"][1] < profile["latency_ms"][0]

    def test_hybrid_rerank_has_highest_recall_bias(self):
        """Test that hybrid+rerank has the highest recall bias."""
        rr_profile = STRATEGY_PROFILES["hybrid_rerank"]
        for name, profile in STRATEGY_PROFILES.items():
            if name != "hybrid_rerank":
                assert rr_profile["recall_bias"] >= profile["recall_bias"]


# =====================================================================
# Component Integration Tests
# =====================================================================

class TestComponentIntegration:
    """Tests for cross-component integration."""

    def setup_method(self):
        self.engine = MetricsEngine()

    def test_metrics_engine_produces_valid_values(self):
        """Test that MetricsEngine always produces valid [0,1] range values."""
        results = [
            RetrievalResult(chunk_id=f"chunk_{i}", score=1.0 - i * 0.05, rank=i + 1)
            for i in range(20)
        ]

        for k in [1, 3, 5, 10, 20]:
            recall = self.engine.compute_recall_at_k(
                [r.chunk_id for r in results],
                {"chunk_0", "chunk_5", "chunk_10"},
                k=k,
            )
            assert 0.0 <= recall <= 1.0

            precision = self.engine.compute_precision_at_k(
                [r.chunk_id for r in results],
                {"chunk_0", "chunk_5", "chunk_10"},
                k=k,
            )
            assert 0.0 <= precision <= 1.0

            ndcg = self.engine.compute_ndcg_at_k(
                [r.chunk_id for r in results],
                {"chunk_0", "chunk_5", "chunk_10"},
                k=k,
            )
            assert 0.0 <= ndcg <= 1.0

    def test_compute_all_metrics_completeness(self):
        """Test that compute_all_metrics returns all expected keys."""
        results = [
            RetrievalResult(chunk_id=f"chunk_{i}", score=1.0 - i * 0.1, rank=i + 1)
            for i in range(10)
        ]
        relevant = {"chunk_0", "chunk_2", "chunk_4"}

        metrics = self.engine.compute_all_metrics(results, relevant, k_values=[5, 10])

        expected_keys = {
            "recall_at_5", "recall_at_10",
            "precision_at_5", "precision_at_10",
            "ndcg_at_5", "ndcg_at_10",
            "mrr", "hit_rate",
        }
        assert set(metrics.keys()) == expected_keys

    def test_aggregate_metrics_with_ndcg(self):
        """Test that aggregate_metrics handles NDCG fields correctly."""
        query_metrics = [
            {"recall_at_5": 0.8, "recall_at_10": 0.9, "mrr": 0.7,
             "precision_at_5": 0.6, "precision_at_10": 0.65,
             "ndcg_at_5": 0.75, "ndcg_at_10": 0.80,
             "hit_rate": 1.0},
            {"recall_at_5": 0.6, "recall_at_10": 0.7, "mrr": 0.5,
             "precision_at_5": 0.4, "precision_at_10": 0.45,
             "ndcg_at_5": 0.55, "ndcg_at_10": 0.60,
             "hit_rate": 0.8},
        ]

        aggregated = self.engine.aggregate_metrics(query_metrics)

        assert aggregated["avg_recall_at_5"] == pytest.approx(0.7)
        assert aggregated["avg_ndcg_at_5"] == pytest.approx(0.65)
        assert aggregated["avg_ndcg_at_10"] == pytest.approx(0.70)


# =====================================================================
# Regression Tests: Output Format Compliance
# =====================================================================

class TestOutputFormatCompliance:
    """Tests to ensure the output matches the required JSON format."""

    @pytest.mark.asyncio
    async def test_json_output_matches_spec(self):
        """Test that JSON output matches:
        {"strategy": "hybrid_rerank", "recall_at_5": 0.94}
        """
        test_dir = Path("storage/format_test")
        dataset_dir = test_dir / "datasets"
        metrics_dir = test_dir / "metrics"
        for d in [dataset_dir, metrics_dir]:
            d.mkdir(parents=True, exist_ok=True)

        try:
            chunk_ids = [f"chunk_{i:03d}" for i in range(10)]
            dataset = create_sample_dataset_with_ids(chunk_ids)
            dm = DatasetManager(dataset_dir=dataset_dir)
            ms = MetricsStorage(storage_dir=metrics_dir)
            dm.save_dataset(dataset)

            evaluator = StandaloneEvaluator(
                dataset_manager=dm,
                metrics_storage=ms,
                seed=42,
            )

            config = EvaluationConfig(
                dataset_name="sample_with_ids",
                strategies=[RetrievalStrategy.HYBRID_RERANK],
                store_results=False,
            )

            report = await evaluator.run_evaluation(config)

            rr_result = next(r for r in report.strategy_results
                            if r.strategy == RetrievalStrategy.HYBRID_RERANK)

            output = {
                "strategy": rr_result.strategy.value,
                "recall_at_5": round(rr_result.avg_recall_at_5, 2),
            }

            assert output["strategy"] == "hybrid_rerank"
            assert isinstance(output["recall_at_5"], float)
            assert 0.0 <= output["recall_at_5"] <= 1.0
        finally:
            import shutil
            if test_dir.exists():
                shutil.rmtree(test_dir)
