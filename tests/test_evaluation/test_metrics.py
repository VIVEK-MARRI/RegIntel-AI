"""Tests for the Metrics Engine."""

import pytest
from app.evaluation.metrics import MetricsEngine
from app.evaluation.schemas import RetrievalResult


class TestMetricsEngine:
    """Test suite for MetricsEngine."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = MetricsEngine()

    # ------------------------------------------------------------------
    # Recall@K Tests
    # ------------------------------------------------------------------

    def test_recall_at_k_perfect_match(self):
        """Test Recall@K when all relevant items are retrieved."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4", "chunk_5"]
        relevant = {"chunk_1", "chunk_2", "chunk_3"}

        recall = self.engine.compute_recall_at_k(retrieved, relevant, k=5)
        assert recall == 1.0

    def test_recall_at_k_partial_match(self):
        """Test Recall@K when some relevant items are retrieved."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4", "chunk_5"]
        relevant = {"chunk_1", "chunk_6", "chunk_7"}

        recall = self.engine.compute_recall_at_k(retrieved, relevant, k=5)
        assert recall == pytest.approx(1 / 3)

    def test_recall_at_k_no_match(self):
        """Test Recall@K when no relevant items are retrieved."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_4", "chunk_5"}

        recall = self.engine.compute_recall_at_k(retrieved, relevant, k=5)
        assert recall == 0.0

    def test_recall_at_k_empty_relevant(self):
        """Test Recall@K with empty relevant set."""
        retrieved = ["chunk_1", "chunk_2"]
        relevant = set()

        recall = self.engine.compute_recall_at_k(retrieved, relevant, k=5)
        assert recall == 0.0

    def test_recall_at_k_k_smaller_than_retrieved(self):
        """Test Recall@K when K is smaller than retrieved list."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4", "chunk_5"]
        relevant = {"chunk_1", "chunk_2", "chunk_3"}

        recall = self.engine.compute_recall_at_k(retrieved, relevant, k=2)
        assert recall == pytest.approx(2 / 3)

    def test_recall_at_k_capped_at_one(self):
        """Test that Recall@K is capped at 1.0."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_1"}

        recall = self.engine.compute_recall_at_k(retrieved, relevant, k=5)
        assert recall == 1.0

    # ------------------------------------------------------------------
    # Precision@K Tests
    # ------------------------------------------------------------------

    def test_precision_at_k_perfect(self):
        """Test Precision@K when all retrieved are relevant."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_1", "chunk_2", "chunk_3", "chunk_4"}

        precision = self.engine.compute_precision_at_k(retrieved, relevant, k=3)
        assert precision == 1.0

    def test_precision_at_k_partial(self):
        """Test Precision@K when some retrieved are relevant."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4", "chunk_5"]
        relevant = {"chunk_1", "chunk_2"}

        precision = self.engine.compute_precision_at_k(retrieved, relevant, k=5)
        assert precision == pytest.approx(2 / 5)

    def test_precision_at_k_zero(self):
        """Test Precision@K when no retrieved are relevant."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_4", "chunk_5"}

        precision = self.engine.compute_precision_at_k(retrieved, relevant, k=3)
        assert precision == 0.0

    def test_precision_at_k_zero_k(self):
        """Test Precision@K with K=0."""
        retrieved = ["chunk_1"]
        relevant = {"chunk_1"}

        precision = self.engine.compute_precision_at_k(retrieved, relevant, k=0)
        assert precision == 0.0

    # ------------------------------------------------------------------
    # MRR Tests
    # ------------------------------------------------------------------

    def test_mrr_first_position(self):
        """Test MRR when first result is relevant."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_1"}

        mrr = self.engine.compute_mrr(retrieved, relevant)
        assert mrr == 1.0

    def test_mrr_second_position(self):
        """Test MRR when second result is relevant."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_2"}

        mrr = self.engine.compute_mrr(retrieved, relevant)
        assert mrr == pytest.approx(1 / 2)

    def test_mrr_third_position(self):
        """Test MRR when third result is relevant."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_3"}

        mrr = self.engine.compute_mrr(retrieved, relevant)
        assert mrr == pytest.approx(1 / 3)

    def test_mrr_no_match(self):
        """Test MRR when no results are relevant."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_4"}

        mrr = self.engine.compute_mrr(retrieved, relevant)
        assert mrr == 0.0

    def test_mrr_empty_relevant(self):
        """Test MRR with empty relevant set."""
        retrieved = ["chunk_1", "chunk_2"]
        relevant = set()

        mrr = self.engine.compute_mrr(retrieved, relevant)
        assert mrr == 0.0

    def test_mrr_multiple_relevant(self):
        """Test MRR with multiple relevant items (uses first occurrence)."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4"]
        relevant = {"chunk_2", "chunk_3"}

        mrr = self.engine.compute_mrr(retrieved, relevant)
        assert mrr == pytest.approx(1 / 2)

    # ------------------------------------------------------------------
    # Hit Rate Tests
    # ------------------------------------------------------------------

    def test_hit_rate_positive(self):
        """Test Hit Rate when relevant item is in top-K."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4", "chunk_5"]
        relevant = {"chunk_3"}

        hit_rate = self.engine.compute_hit_rate(retrieved, relevant, k=5)
        assert hit_rate == 1.0

    def test_hit_rate_negative(self):
        """Test Hit Rate when no relevant item is in top-K."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_4"}

        hit_rate = self.engine.compute_hit_rate(retrieved, relevant, k=3)
        assert hit_rate == 0.0

    def test_hit_rate_beyond_k(self):
        """Test Hit Rate when relevant item is beyond K."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4", "chunk_5"]
        relevant = {"chunk_5"}

        hit_rate = self.engine.compute_hit_rate(retrieved, relevant, k=3)
        assert hit_rate == 0.0

    def test_hit_rate_empty_relevant(self):
        """Test Hit Rate with empty relevant set."""
        retrieved = ["chunk_1", "chunk_2"]
        relevant = set()

        hit_rate = self.engine.compute_hit_rate(retrieved, relevant, k=5)
        assert hit_rate == 0.0

    # ------------------------------------------------------------------
    # Compute All Metrics Tests
    # ------------------------------------------------------------------

    def test_compute_all_metrics(self):
        """Test computing all metrics at once."""
        results = [
            RetrievalResult(chunk_id="chunk_1", score=0.9, rank=1),
            RetrievalResult(chunk_id="chunk_2", score=0.8, rank=2),
            RetrievalResult(chunk_id="chunk_3", score=0.7, rank=3),
            RetrievalResult(chunk_id="chunk_4", score=0.6, rank=4),
            RetrievalResult(chunk_id="chunk_5", score=0.5, rank=5),
        ]
        relevant = {"chunk_1", "chunk_3", "chunk_6"}

        metrics = self.engine.compute_all_metrics(results, relevant, k_values=[5, 10])

        assert "recall_at_5" in metrics
        assert "recall_at_10" in metrics
        assert "precision_at_5" in metrics
        assert "precision_at_10" in metrics
        assert "mrr" in metrics
        assert "hit_rate" in metrics

        # chunk_1 and chunk_3 are in top-5, out of 3 relevant
        assert metrics["recall_at_5"] == pytest.approx(2 / 3)
        # 2 relevant out of 5 retrieved
        assert metrics["precision_at_5"] == pytest.approx(2 / 5)
        # First relevant at position 1
        assert metrics["mrr"] == 1.0
        # At least one relevant in top-10
        assert metrics["hit_rate"] == 1.0

    def test_compute_all_metrics_empty_results(self):
        """Test computing metrics with empty results."""
        results = []
        relevant = {"chunk_1", "chunk_2"}

        metrics = self.engine.compute_all_metrics(results, relevant, k_values=[5])

        assert metrics["recall_at_5"] == 0.0
        assert metrics["precision_at_5"] == 0.0
        assert metrics["mrr"] == 0.0
        assert metrics["hit_rate"] == 0.0

    # ------------------------------------------------------------------
    # Aggregate Metrics Tests
    # ------------------------------------------------------------------

    def test_aggregate_metrics(self):
        """Test aggregating metrics across queries."""
        query_metrics = [
            {"recall_at_5": 0.8, "mrr": 0.5, "hit_rate": 1.0},
            {"recall_at_5": 0.6, "mrr": 0.3, "hit_rate": 1.0},
            {"recall_at_5": 1.0, "mrr": 1.0, "hit_rate": 1.0},
        ]

        aggregated = self.engine.aggregate_metrics(query_metrics)

        assert aggregated["avg_recall_at_5"] == pytest.approx(0.8)
        assert aggregated["avg_mrr"] == pytest.approx(0.6)
        assert aggregated["avg_hit_rate"] == 1.0

    def test_aggregate_metrics_empty(self):
        """Test aggregating empty metrics list."""
        aggregated = self.engine.aggregate_metrics([])
        assert aggregated == {}

    # ------------------------------------------------------------------
    # Composite Score Tests
    # ------------------------------------------------------------------

    def test_composite_score_default_weights(self):
        """Test composite score with default weights."""
        metrics = {
            "recall_at_5": 0.8,
            "recall_at_10": 0.9,
            "mrr": 0.7,
            "precision_at_5": 0.6,
            "hit_rate": 1.0,
            "ndcg_at_5": 0.85,
            "ndcg_at_10": 0.88,
        }

        score = self.engine.compute_composite_score(metrics)
        expected = (
            0.8 * 0.20
            + 0.9 * 0.15
            + 0.7 * 0.20
            + 0.6 * 0.10
            + 1.0 * 0.10
            + 0.85 * 0.15
            + 0.88 * 0.10
        )
        assert score == pytest.approx(expected)

    def test_composite_score_custom_weights(self):
        """Test composite score with custom weights."""
        metrics = {
            "recall_at_5": 0.8,
            "mrr": 0.6,
        }
        weights = {
            "recall_at_5": 0.7,
            "mrr": 0.3,
        }

        score = self.engine.compute_composite_score(metrics, weights)
        expected = (0.8 * 0.7 + 0.6 * 0.3) / 1.0
        assert score == pytest.approx(expected)

    def test_composite_score_with_avg_prefix(self):
        """Test composite score with avg_ prefixed metric names."""
        metrics = {
            "avg_recall_at_5": 0.8,
            "avg_recall_at_10": 0.9,
            "avg_mrr": 0.7,
            "avg_precision_at_5": 0.6,
            "avg_hit_rate": 1.0,
            "avg_ndcg_at_5": 0.85,
            "avg_ndcg_at_10": 0.88,
        }

        score = self.engine.compute_composite_score(metrics)
        expected = (
            0.8 * 0.20
            + 0.9 * 0.15
            + 0.7 * 0.20
            + 0.6 * 0.10
            + 1.0 * 0.10
            + 0.85 * 0.15
            + 0.88 * 0.10
        )
        assert score == pytest.approx(expected)

    def test_composite_score_perfect(self):
        """Test composite score with perfect metrics."""
        metrics = {
            "recall_at_5": 1.0,
            "recall_at_10": 1.0,
            "mrr": 1.0,
            "precision_at_5": 1.0,
            "hit_rate": 1.0,
            "ndcg_at_5": 1.0,
            "ndcg_at_10": 1.0,
        }

        score = self.engine.compute_composite_score(metrics)
        assert score == 1.0

    def test_composite_score_zero(self):
        """Test composite score with zero metrics."""
        metrics = {
            "recall_at_5": 0.0,
            "recall_at_10": 0.0,
            "mrr": 0.0,
            "precision_at_5": 0.0,
            "hit_rate": 0.0,
            "ndcg_at_5": 0.0,
            "ndcg_at_10": 0.0,
        }

        score = self.engine.compute_composite_score(metrics)
        assert score == 0.0

    # ------------------------------------------------------------------
    # NDCG@K Tests
    # ------------------------------------------------------------------

    def test_ndcg_at_k_perfect_ordering(self):
        """Test NDCG@K with perfect result ordering."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_1", "chunk_2", "chunk_3"}

        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)
        assert ndcg == pytest.approx(1.0, abs=1e-6)

    def test_ndcg_at_k_no_relevant(self):
        """Test NDCG@K when no relevant items are retrieved."""
        retrieved = ["chunk_4", "chunk_5", "chunk_6"]
        relevant = {"chunk_1", "chunk_2", "chunk_3"}

        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)
        assert ndcg == pytest.approx(0.0, abs=1e-6)

    def test_ndcg_at_k_empty_relevant(self):
        """Test NDCG@K with empty relevant set."""
        retrieved = ["chunk_1", "chunk_2"]
        relevant = set()

        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=5)
        assert ndcg == 0.0

    def test_ndcg_at_k_partial_match(self):
        """Test NDCG@K with partial matches at different ranks."""
        retrieved = ["chunk_1", "chunk_4", "chunk_2"]
        relevant = {"chunk_1", "chunk_2", "chunk_3"}

        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)

        # Manually compute expected
        # DCG = (2^1 - 1)/log2(2) + (2^0 - 1)/log2(3) + (2^1 - 1)/log2(4)
        #     = 1/1.0 + 0 + 1/2.0 = 1.5
        import math

        dcg = (
            (math.pow(2, 1) - 1) / math.log2(2)
            + (math.pow(2, 0) - 1) / math.log2(3)
            + (math.pow(2, 1) - 1) / math.log2(4)
        )
        # IDCG = (2^1 - 1)/log2(2) + (2^1 - 1)/log2(3) + (2^1 - 1)/log2(4)
        #      = 1/1.0 + 1/1.585 + 1/2.0 approx 1 + 0.6309 + 0.5 = 2.1309
        idcg = (
            (math.pow(2, 1) - 1) / math.log2(2)
            + (math.pow(2, 1) - 1) / math.log2(3)
            + (math.pow(2, 1) - 1) / math.log2(4)
        )
        expected = dcg / idcg

        assert ndcg == pytest.approx(expected, abs=1e-4)

    def test_ndcg_at_k_beyond_k(self):
        """Test NDCG@K when relevant items are beyond K."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4", "chunk_5"]
        relevant = {"chunk_5"}

        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)
        assert ndcg == pytest.approx(0.0, abs=1e-6)

    def test_ndcg_at_k_at_boundary(self):
        """Test NDCG@K when relevant item is exactly at rank K."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4", "chunk_5"]
        relevant = {"chunk_3"}

        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)
        assert ndcg > 0.0
        assert ndcg < 1.0

    def test_ndcg_at_k_with_graded_relevance(self):
        """Test NDCG@K with graded relevance scores."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_1", "chunk_2", "chunk_3"}
        relevance_scores = {
            "chunk_1": 3.0,
            "chunk_2": 2.0,
            "chunk_3": 1.0,
        }

        ndcg = self.engine.compute_ndcg_at_k(
            retrieved, relevant, k=3, relevance_scores=relevance_scores
        )

        # Perfect ordering of graded relevance should give NDCG = 1.0
        assert ndcg == pytest.approx(1.0, abs=1e-4)

    def test_ndcg_at_k_with_graded_suboptimal(self):
        """Test NDCG@K with suboptimal ordering of graded relevance."""
        retrieved = ["chunk_3", "chunk_2", "chunk_1"]
        relevant = {"chunk_1", "chunk_2", "chunk_3"}
        relevance_scores = {
            "chunk_1": 3.0,
            "chunk_2": 2.0,
            "chunk_3": 1.0,
        }

        ndcg = self.engine.compute_ndcg_at_k(
            retrieved, relevant, k=3, relevance_scores=relevance_scores
        )

        # Suboptimal ordering - NDCG should be < 1.0 but > 0.0
        assert ndcg > 0.0
        assert ndcg < 1.0

    def test_ndcg_at_k_single_relevant(self):
        """Test NDCG@K with a single relevant item retrieved first."""
        retrieved = ["chunk_1", "chunk_2", "chunk_3"]
        relevant = {"chunk_1"}

        ndcg = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)
        assert ndcg == pytest.approx(1.0, abs=1e-6)

    def test_ndcg_at_k_different_k_values(self):
        """Test NDCG with different K values."""
        retrieved = [
            "chunk_1",
            "chunk_2",
            "chunk_3",
            "chunk_4",
            "chunk_5",
            "chunk_6",
            "chunk_7",
            "chunk_8",
            "chunk_9",
            "chunk_10",
        ]
        relevant = {"chunk_1", "chunk_2", "chunk_3"}

        ndcg_3 = self.engine.compute_ndcg_at_k(retrieved, relevant, k=3)
        ndcg_5 = self.engine.compute_ndcg_at_k(retrieved, relevant, k=5)
        ndcg_10 = self.engine.compute_ndcg_at_k(retrieved, relevant, k=10)

        # All relevant items in top-3 should give NDCG@3 = 1.0
        assert ndcg_3 == pytest.approx(1.0, abs=1e-6)
        # NDCG@5 and NDCG@10 should also be 1.0 (all relevant are in top-3)
        assert ndcg_5 == pytest.approx(1.0, abs=1e-6)
        assert ndcg_10 == pytest.approx(1.0, abs=1e-6)

    def test_compute_all_metrics_includes_ndcg(self):
        """Test that compute_all_metrics includes NDCG values."""
        results = [
            RetrievalResult(chunk_id="chunk_1", score=0.9, rank=1),
            RetrievalResult(chunk_id="chunk_2", score=0.8, rank=2),
            RetrievalResult(chunk_id="chunk_3", score=0.7, rank=3),
        ]
        relevant = {"chunk_1", "chunk_2"}

        metrics = self.engine.compute_all_metrics(results, relevant, k_values=[3, 5])

        assert "ndcg_at_3" in metrics
        assert "ndcg_at_5" in metrics
        assert all(v >= 0.0 for k, v in metrics.items() if k.startswith("ndcg"))
        assert all(v <= 1.0 for k, v in metrics.items() if k.startswith("ndcg"))

    def test_composite_score_with_ndcg(self):
        """Test composite score includes NDCG metrics."""
        metrics = {
            "recall_at_5": 0.8,
            "recall_at_10": 0.9,
            "mrr": 0.7,
            "precision_at_5": 0.6,
            "hit_rate": 1.0,
            "ndcg_at_5": 0.85,
            "ndcg_at_10": 0.88,
        }

        score = self.engine.compute_composite_score(metrics)
        assert score > 0.0
        assert score < 1.0
