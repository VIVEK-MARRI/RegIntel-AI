"""Tests for the Retrieval Evaluator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.evaluation.evaluator import RetrievalEvaluator
from app.evaluation.schemas import (
    EvaluationConfig,
    GoldenDataset,
    QueryRelevance,
    RetrievalStrategy,
    StrategyEvaluationResult,
)


class TestRetrievalEvaluator:
    """Test suite for RetrievalEvaluator."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_db_session = AsyncMock()
        self.mock_retrieval_service = AsyncMock()
        self.mock_bm25_retriever = AsyncMock()
        self.mock_hybrid_retriever = AsyncMock()
        self.mock_reranker_service = MagicMock()

        self.evaluator = RetrievalEvaluator(
            db_session=self.mock_db_session,
            retrieval_service=self.mock_retrieval_service,
            bm25_retriever=self.mock_bm25_retriever,
            hybrid_retriever=self.mock_hybrid_retriever,
            reranker_service=self.mock_reranker_service,
        )

    def _create_sample_dataset(self) -> GoldenDataset:
        """Create a sample dataset for testing."""
        return GoldenDataset(
            name="test",
            queries=[
                QueryRelevance(
                    query_id="q1",
                    query_text="Test query 1",
                    relevant_chunk_ids=["chunk_1", "chunk_2"],
                ),
                QueryRelevance(
                    query_id="q2",
                    query_text="Test query 2",
                    relevant_chunk_ids=["chunk_3"],
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_evaluate_strategy_dense(self):
        """Test evaluating dense retrieval strategy."""
        # Mock dense retrieval results
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {"chunk_id": "chunk_1", "score": 0.9, "content": "test"},
                {"chunk_id": "chunk_3", "score": 0.8, "content": "test"},
                {"chunk_id": "chunk_5", "score": 0.7, "content": "test"},
            ]
        }

        dataset = self._create_sample_dataset()
        config = EvaluationConfig(
            strategies=[RetrievalStrategy.DENSE],
            store_results=False,
        )

        result = await self.evaluator.evaluate_strategy(
            RetrievalStrategy.DENSE, dataset, config
        )

        assert result.strategy == RetrievalStrategy.DENSE
        assert result.total_queries == 2
        assert len(result.query_results) == 2

        # First query has chunk_1 in relevant, which is retrieved at rank 1
        assert result.query_results[0].recall_at_5 > 0
        assert result.query_results[0].mrr > 0

    @pytest.mark.asyncio
    async def test_evaluate_strategy_bm25(self):
        """Test evaluating BM25 retrieval strategy."""
        # Mock BM25 retrieval results
        self.mock_bm25_retriever.retrieve.return_value = [
            {"chunk_id": "chunk_2", "score": 1.5, "content": "test"},
            {"chunk_id": "chunk_4", "score": 1.2, "content": "test"},
        ]

        dataset = self._create_sample_dataset()
        config = EvaluationConfig(
            strategies=[RetrievalStrategy.BM25],
            store_results=False,
        )

        result = await self.evaluator.evaluate_strategy(
            RetrievalStrategy.BM25, dataset, config
        )

        assert result.strategy == RetrievalStrategy.BM25
        assert result.total_queries == 2

    @pytest.mark.asyncio
    async def test_evaluate_strategy_hybrid(self):
        """Test evaluating hybrid retrieval strategy."""
        # Mock hybrid retrieval results
        mock_hybrid_response = MagicMock()
        mock_hybrid_response.results = [
            MagicMock(chunk_id="chunk_1", score=0.95, content="test", metadata={}),
            MagicMock(chunk_id="chunk_2", score=0.85, content="test", metadata={}),
        ]
        self.mock_hybrid_retriever.retrieve_hybrid.return_value = mock_hybrid_response

        dataset = self._create_sample_dataset()
        config = EvaluationConfig(
            strategies=[RetrievalStrategy.HYBRID],
            store_results=False,
        )

        result = await self.evaluator.evaluate_strategy(
            RetrievalStrategy.HYBRID, dataset, config
        )

        assert result.strategy == RetrievalStrategy.HYBRID
        assert result.total_queries == 2

    @pytest.mark.asyncio
    async def test_evaluate_strategy_hybrid_rerank(self):
        """Test evaluating hybrid + rerank strategy."""
        # Mock hybrid retrieval results
        mock_hybrid_response = MagicMock()
        mock_hybrid_response.results = [
            MagicMock(chunk_id="chunk_1", score=0.9, content="test", metadata={}),
            MagicMock(chunk_id="chunk_2", score=0.8, content="test", metadata={}),
        ]
        self.mock_hybrid_retriever.retrieve_hybrid.return_value = mock_hybrid_response

        # Mock reranker results
        mock_rerank_response = MagicMock()
        mock_rerank_response.results = [
            MagicMock(
                chunk_id="chunk_1", rerank_score=0.95, content="test", metadata={}
            ),
            MagicMock(
                chunk_id="chunk_2", rerank_score=0.85, content="test", metadata={}
            ),
        ]
        self.mock_reranker_service.rerank.return_value = mock_rerank_response

        dataset = self._create_sample_dataset()
        config = EvaluationConfig(
            strategies=[RetrievalStrategy.HYBRID_RERANK],
            store_results=False,
        )

        result = await self.evaluator.evaluate_strategy(
            RetrievalStrategy.HYBRID_RERANK, dataset, config
        )

        assert result.strategy == RetrievalStrategy.HYBRID_RERANK
        assert result.total_queries == 2

    def test_aggregate_query_results(self):
        """Test aggregating query results."""
        from app.evaluation.schemas import QueryEvaluationResult, RetrievalResult

        query_results = [
            QueryEvaluationResult(
                query_id="q1",
                query_text="test",
                strategy=RetrievalStrategy.DENSE,
                recall_at_5=0.8,
                recall_at_10=0.9,
                mrr=0.7,
                precision_at_5=0.6,
                precision_at_10=0.65,
                hit_rate=1.0,
                latency_ms=100.0,
            ),
            QueryEvaluationResult(
                query_id="q2",
                query_text="test",
                strategy=RetrievalStrategy.DENSE,
                recall_at_5=0.6,
                recall_at_10=0.7,
                mrr=0.5,
                precision_at_5=0.4,
                precision_at_10=0.45,
                hit_rate=0.8,
                latency_ms=120.0,
            ),
        ]

        aggregated = self.evaluator._aggregate_query_results(query_results)

        assert aggregated["avg_recall_at_5"] == pytest.approx(0.7)
        assert aggregated["avg_recall_at_10"] == pytest.approx(0.8)
        assert aggregated["avg_mrr"] == pytest.approx(0.6)
        assert aggregated["avg_latency_ms"] == pytest.approx(110.0)

    def test_aggregate_query_results_empty(self):
        """Test aggregating empty query results."""
        aggregated = self.evaluator._aggregate_query_results([])

        assert aggregated["avg_recall_at_5"] == 0.0
        assert aggregated["avg_mrr"] == 0.0

    def test_generate_leaderboard(self):
        """Test generating leaderboard from strategy results."""
        from app.evaluation.schemas import StrategyEvaluationResult

        results = [
            StrategyEvaluationResult(
                strategy=RetrievalStrategy.DENSE,
                total_queries=5,
                avg_recall_at_5=0.8,
                avg_recall_at_10=0.9,
                avg_mrr=0.7,
                avg_precision_at_5=0.6,
                avg_precision_at_10=0.65,
                avg_hit_rate=1.0,
                avg_latency_ms=100.0,
            ),
            StrategyEvaluationResult(
                strategy=RetrievalStrategy.BM25,
                total_queries=5,
                avg_recall_at_5=0.6,
                avg_recall_at_10=0.7,
                avg_mrr=0.5,
                avg_precision_at_5=0.4,
                avg_precision_at_10=0.45,
                avg_hit_rate=0.8,
                avg_latency_ms=80.0,
            ),
        ]

        leaderboard = self.evaluator._generate_leaderboard(results)

        assert len(leaderboard) == 2
        # Dense should be ranked higher due to better metrics
        assert leaderboard[0]["strategy"] == "dense"
        assert leaderboard[0]["rank"] == 1
        assert leaderboard[1]["strategy"] == "bm25"
        assert leaderboard[1]["rank"] == 2

    @pytest.mark.asyncio
    async def test_run_evaluation(self):
        """Test running full evaluation."""
        # Mock all retrieval methods
        self.mock_retrieval_service.retrieve.return_value = {
            "results": [
                {"chunk_id": "chunk_1", "score": 0.9, "content": "test"},
            ]
        }
        self.mock_bm25_retriever.retrieve.return_value = [
            {"chunk_id": "chunk_1", "score": 1.5, "content": "test"},
        ]

        mock_hybrid_response = MagicMock()
        mock_hybrid_response.results = [
            MagicMock(chunk_id="chunk_1", score=0.95, content="test", metadata={}),
        ]
        self.mock_hybrid_retriever.retrieve_hybrid.return_value = mock_hybrid_response

        mock_rerank_response = MagicMock()
        mock_rerank_response.results = [
            MagicMock(
                chunk_id="chunk_1", rerank_score=0.98, content="test", metadata={}
            ),
        ]
        self.mock_reranker_service.rerank.return_value = mock_rerank_response

        config = EvaluationConfig(
            dataset_name="default",
            strategies=[RetrievalStrategy.DENSE, RetrievalStrategy.BM25],
            store_results=False,
            generate_report=False,
        )

        report = await self.evaluator.run_evaluation(config)

        assert report.dataset_name is not None
        assert len(report.strategy_results) == 2
        assert len(report.leaderboard) == 2


class TestRetrievalStrategy:
    """Test suite for RetrievalStrategy enum."""

    def test_strategy_values(self):
        """Test strategy enum values."""
        assert RetrievalStrategy.DENSE.value == "dense"
        assert RetrievalStrategy.BM25.value == "bm25"
        assert RetrievalStrategy.HYBRID.value == "hybrid"
        assert RetrievalStrategy.HYBRID_RERANK.value == "hybrid_rerank"

    def test_strategy_from_string(self):
        """Test creating strategy from string."""
        assert RetrievalStrategy("dense") == RetrievalStrategy.DENSE
        assert RetrievalStrategy("bm25") == RetrievalStrategy.BM25
        assert RetrievalStrategy("hybrid") == RetrievalStrategy.HYBRID
        assert RetrievalStrategy("hybrid_rerank") == RetrievalStrategy.HYBRID_RERANK
