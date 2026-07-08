"""Retrieval Evaluator - Main evaluation orchestrator.

Coordinates evaluation of retrieval strategies against golden datasets.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.dataset import DatasetManager
from app.evaluation.metrics import MetricsEngine
from app.evaluation.schemas import (
    EvaluationConfig,
    EvaluationReport,
    GoldenDataset,
    QueryEvaluationResult,
    QueryRelevance,
    RetrievalResult,
    RetrievalStrategy,
    StrategyEvaluationResult,
)
from app.evaluation.storage import MetricsStorage
from app.services.embedding.retrieval import RetrievalService
from app.services.bm25.base import BM25Retriever
from app.services.hybrid.service import HybridRetriever
from app.services.reranker.service import RerankerService

logger = logging.getLogger(__name__)


class RetrievalEvaluator:
    """Main evaluator for retrieval strategies."""

    def __init__(
        self,
        db_session: AsyncSession,
        retrieval_service: RetrievalService,
        bm25_retriever: BM25Retriever,
        hybrid_retriever: HybridRetriever,
        reranker_service: RerankerService,
        dataset_manager: Optional[DatasetManager] = None,
        metrics_storage: Optional[MetricsStorage] = None,
    ):
        """Initialize the evaluator.

        Args:
            db_session: Database session.
            retrieval_service: Dense retrieval service.
            bm25_retriever: BM25 retriever.
            hybrid_retriever: Hybrid retriever.
            reranker_service: Reranker service.
            dataset_manager: Optional dataset manager.
            metrics_storage: Optional metrics storage.
        """
        self.db_session = db_session
        self.retrieval_service = retrieval_service
        self.bm25_retriever = bm25_retriever
        self.hybrid_retriever = hybrid_retriever
        self.reranker_service = reranker_service
        self.dataset_manager = dataset_manager or DatasetManager()
        self.metrics_storage = metrics_storage or MetricsStorage()
        self.metrics_engine = MetricsEngine()

    async def evaluate_strategy(
        self,
        strategy: RetrievalStrategy,
        dataset: GoldenDataset,
        config: EvaluationConfig,
    ) -> StrategyEvaluationResult:
        """Evaluate a single retrieval strategy against the dataset.

        Args:
            strategy: The retrieval strategy to evaluate.
            dataset: The golden dataset.
            config: Evaluation configuration.

        Returns:
            StrategyEvaluationResult with aggregated metrics.
        """
        logger.info(f"Evaluating strategy: {strategy.value}")
        query_results: List[QueryEvaluationResult] = []

        for query in dataset.queries:
            result = await self._evaluate_query(strategy, query, config)
            query_results.append(result)

        # Aggregate metrics
        aggregated = self._aggregate_query_results(query_results)

        return StrategyEvaluationResult(
            strategy=strategy,
            total_queries=len(query_results),
            query_results=query_results,
            **aggregated,
        )

    async def _evaluate_query(
        self,
        strategy: RetrievalStrategy,
        query: QueryRelevance,
        config: EvaluationConfig,
    ) -> QueryEvaluationResult:
        """Evaluate a single query with the given strategy.

        Args:
            strategy: Retrieval strategy.
            query: Query with relevance judgments.
            config: Evaluation configuration.

        Returns:
            QueryEvaluationResult with metrics.
        """
        start_time = time.perf_counter()

        # Execute retrieval based on strategy
        if strategy == RetrievalStrategy.DENSE:
            raw_results = await self._retrieve_dense(query)
        elif strategy == RetrievalStrategy.BM25:
            raw_results = await self._retrieve_bm25(query)
        elif strategy == RetrievalStrategy.HYBRID:
            raw_results = await self._retrieve_hybrid(query, config)
        elif strategy == RetrievalStrategy.HYBRID_RERANK:
            raw_results = await self._retrieve_hybrid_rerank(query, config)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Convert to RetrievalResult objects
        retrieval_results = [
            RetrievalResult(
                chunk_id=r["chunk_id"],
                score=r["score"],
                rank=idx + 1,
                content=r.get("content"),
                metadata=r.get("metadata", {}),
            )
            for idx, r in enumerate(raw_results)
        ]

        # Compute metrics
        relevant_ids = set(query.relevant_chunk_ids)
        metrics = self.metrics_engine.compute_all_metrics(
            retrieval_results, relevant_ids, config.top_k_values
        )

        return QueryEvaluationResult(
            query_id=query.query_id,
            query_text=query.query_text,
            strategy=strategy,
            retrieved_results=retrieval_results,
            relevant_chunk_ids=list(relevant_ids),
            recall_at_5=metrics.get("recall_at_5", 0.0),
            recall_at_10=metrics.get("recall_at_10", 0.0),
            mrr=metrics.get("mrr", 0.0),
            precision_at_5=metrics.get("precision_at_5", 0.0),
            precision_at_10=metrics.get("precision_at_10", 0.0),
            hit_rate=metrics.get("hit_rate", 0.0),
            ndcg_at_5=metrics.get("ndcg_at_5", 0.0),
            ndcg_at_10=metrics.get("ndcg_at_10", 0.0),
            latency_ms=latency_ms,
        )

    async def _retrieve_dense(self, query: QueryRelevance) -> List[Dict[str, Any]]:
        """Retrieve using dense strategy."""
        response = await self.retrieval_service.retrieve(
            query=query.query_text,
            top_k=20,
        )
        return response.get("results", [])

    async def _retrieve_bm25(self, query: QueryRelevance) -> List[Dict[str, Any]]:
        """Retrieve using BM25 strategy."""
        return await self.bm25_retriever.retrieve(
            query=query.query_text,
            top_k=20,
        )

    async def _retrieve_hybrid(
        self, query: QueryRelevance, config: EvaluationConfig
    ) -> List[Dict[str, Any]]:
        """Retrieve using hybrid strategy."""
        response = await self.hybrid_retriever.retrieve_hybrid(
            query=query.query_text,
            top_n=20,
            dense_top_k=config.hybrid_top_k,
            bm25_top_k=config.hybrid_top_k,
        )
        results = []
        for r in response.results:
            results.append(
                {
                    "chunk_id": r.chunk_id,
                    "score": r.score,
                    "content": r.content,
                    "metadata": r.metadata,
                }
            )
        return results

    async def _retrieve_hybrid_rerank(
        self, query: QueryRelevance, config: EvaluationConfig
    ) -> List[Dict[str, Any]]:
        """Retrieve using hybrid + rerank strategy."""
        # First get hybrid results
        hybrid_response = await self.hybrid_retriever.retrieve_hybrid(
            query=query.query_text,
            top_n=config.hybrid_top_k,
            dense_top_k=config.hybrid_top_k,
            bm25_top_k=config.hybrid_top_k,
        )

        # Convert to candidate format for reranker
        candidates = [
            {
                "chunk_id": r.chunk_id,
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in hybrid_response.results
        ]

        # Rerank
        rerank_response = self.reranker_service.rerank(
            query=query.query_text,
            candidates=candidates,
            top_k=config.rerank_top_k,
        )

        results = []
        for r in rerank_response.results:
            results.append(
                {
                    "chunk_id": r.chunk_id,
                    "score": r.rerank_score,
                    "content": r.content,
                    "metadata": r.metadata,
                }
            )
        return results

    def _aggregate_query_results(
        self, query_results: List[QueryEvaluationResult]
    ) -> Dict[str, float]:
        """Aggregate metrics across query results.

        Args:
            query_results: List of per-query results.

        Returns:
            Dictionary of averaged metrics.
        """
        if not query_results:
            return {
                "avg_recall_at_5": 0.0,
                "avg_recall_at_10": 0.0,
                "avg_mrr": 0.0,
                "avg_precision_at_5": 0.0,
                "avg_precision_at_10": 0.0,
                "avg_hit_rate": 0.0,
                "avg_ndcg_at_5": 0.0,
                "avg_ndcg_at_10": 0.0,
                "avg_latency_ms": 0.0,
            }

        n = len(query_results)
        return {
            "avg_recall_at_5": sum(q.recall_at_5 for q in query_results) / n,
            "avg_recall_at_10": sum(q.recall_at_10 for q in query_results) / n,
            "avg_mrr": sum(q.mrr for q in query_results) / n,
            "avg_precision_at_5": sum(q.precision_at_5 for q in query_results) / n,
            "avg_precision_at_10": sum(q.precision_at_10 for q in query_results) / n,
            "avg_hit_rate": sum(q.hit_rate for q in query_results) / n,
            "avg_ndcg_at_5": sum(q.ndcg_at_5 for q in query_results) / n,
            "avg_ndcg_at_10": sum(q.ndcg_at_10 for q in query_results) / n,
            "avg_latency_ms": sum(q.latency_ms for q in query_results) / n,
        }

    async def run_evaluation(
        self,
        config: Optional[EvaluationConfig] = None,
    ) -> EvaluationReport:
        """Run full evaluation across all configured strategies.

        Args:
            config: Evaluation configuration. Uses defaults if not provided.

        Returns:
            Complete evaluation report.
        """
        if config is None:
            config = EvaluationConfig()

        # Load dataset
        dataset = self.dataset_manager.load_dataset(config.dataset_name)
        if dataset is None:
            logger.info(f"Dataset '{config.dataset_name}' not found, creating default.")
            dataset = self.dataset_manager.get_or_create_default_dataset()

        logger.info(
            f"Starting evaluation with dataset '{dataset.name}' "
            f"({len(dataset.queries)} queries) "
            f"for strategies: {[s.value for s in config.strategies]}"
        )

        # Evaluate each strategy
        strategy_results: List[StrategyEvaluationResult] = []
        for strategy in config.strategies:
            result = await self.evaluate_strategy(strategy, dataset, config)
            strategy_results.append(result)

            # Store metrics if configured
            if config.store_results:
                self.metrics_storage.store_strategy_result(
                    strategy=strategy,
                    dataset_name=dataset.name,
                    result=result,
                )

        # Generate leaderboard
        leaderboard = self._generate_leaderboard(strategy_results)

        # Create report
        report = EvaluationReport(
            dataset_name=dataset.name,
            strategy_results=strategy_results,
            leaderboard=leaderboard,
            metadata={
                "config": config.model_dump(),
                "total_queries": len(dataset.queries),
            },
        )

        logger.info("Evaluation complete.")
        return report

    def _generate_leaderboard(
        self, strategy_results: List[StrategyEvaluationResult]
    ) -> List[Dict[str, Any]]:
        """Generate leaderboard rankings from strategy results.

        Args:
            strategy_results: Results for each strategy.

        Returns:
            Sorted leaderboard entries.
        """
        entries = []
        for result in strategy_results:
            composite_score = self.metrics_engine.compute_composite_score(
                {
                    "recall_at_5": result.avg_recall_at_5,
                    "recall_at_10": result.avg_recall_at_10,
                    "mrr": result.avg_mrr,
                    "precision_at_5": result.avg_precision_at_5,
                    "hit_rate": result.avg_hit_rate,
                    "ndcg_at_5": result.avg_ndcg_at_5,
                    "ndcg_at_10": result.avg_ndcg_at_10,
                }
            )
            entries.append(
                {
                    "strategy": result.strategy.value,
                    "avg_recall_at_5": result.avg_recall_at_5,
                    "avg_recall_at_10": result.avg_recall_at_10,
                    "avg_mrr": result.avg_mrr,
                    "avg_precision_at_5": result.avg_precision_at_5,
                    "avg_ndcg_at_5": result.avg_ndcg_at_5,
                    "avg_ndcg_at_10": result.avg_ndcg_at_10,
                    "avg_hit_rate": result.avg_hit_rate,
                    "avg_latency_ms": result.avg_latency_ms,
                    "composite_score": composite_score,
                }
            )

        # Sort by composite score descending
        entries.sort(key=lambda x: x["composite_score"], reverse=True)

        # Add ranks
        for idx, entry in enumerate(entries, start=1):
            entry["rank"] = idx

        return entries
