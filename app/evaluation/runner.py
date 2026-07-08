"""Standalone Evaluation Runner.

Runs a complete retrieval evaluation using simulated strategy outputs
and produces metrics, reports, and historical records.

Usage:
    python -m app.evaluation.runner --output-dir storage/evaluation/output
    python -m app.evaluation.runner --dataset regintel_eval --format json
"""

import argparse
import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.evaluation.dataset import DatasetManager
from app.evaluation.metrics import MetricsEngine
from app.evaluation.reporting import ReportGenerator, Leaderboard
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

ALL_CHUNK_IDS = [
    "chunk_cap_001", "chunk_cap_002", "chunk_cap_003", "chunk_cap_004", "chunk_cap_005",
    "chunk_npa_001", "chunk_npa_002", "chunk_npa_003", "chunk_npa_004",
    "chunk_kyc_001", "chunk_kyc_002", "chunk_kyc_003", "chunk_kyc_004", "chunk_kyc_005", "chunk_kyc_006",
    "chunk_mf_001", "chunk_mf_002", "chunk_mf_003", "chunk_mf_004",
    "chunk_lodr_001", "chunk_lodr_002", "chunk_lodr_003", "chunk_lodr_004", "chunk_lodr_005",
    "chunk_lcr_001", "chunk_lcr_002", "chunk_lcr_003",
    "chunk_stress_001", "chunk_stress_002", "chunk_stress_003", "chunk_stress_004",
    "chunk_pit_001", "chunk_pit_002", "chunk_pit_003", "chunk_pit_004", "chunk_pit_005",
    "chunk_psl_001", "chunk_psl_002", "chunk_psl_003", "chunk_psl_004",
    "chunk_sast_001", "chunk_sast_002", "chunk_sast_003", "chunk_sast_004", "chunk_sast_005",
    "chunk_noise_001", "chunk_noise_002", "chunk_noise_003", "chunk_noise_004", "chunk_noise_005",
    "chunk_noise_006", "chunk_noise_007", "chunk_noise_008", "chunk_noise_009", "chunk_noise_010",
]

STRATEGY_PROFILES = {
    "dense": {
        "recall_bias": 0.82,
        "noise_ratio": 0.30,
        "score_range": (0.65, 0.99),
        "latency_ms": (45.0, 85.0),
    },
    "bm25": {
        "recall_bias": 0.72,
        "noise_ratio": 0.40,
        "score_range": (8.0, 25.0),
        "latency_ms": (15.0, 35.0),
    },
    "hybrid": {
        "recall_bias": 0.88,
        "noise_ratio": 0.22,
        "score_range": (0.55, 0.98),
        "latency_ms": (65.0, 120.0),
    },
    "hybrid_rerank": {
        "recall_bias": 0.94,
        "noise_ratio": 0.12,
        "score_range": (0.70, 0.99),
        "latency_ms": (120.0, 250.0),
    },
}


class SimulatedRetriever:
    """Simulates retrieval results with configurable accuracy profiles."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def retrieve(
        self,
        query: QueryRelevance,
        strategy: RetrievalStrategy,
        top_k: int = 20,
    ) -> List[Dict[str, Any]]:
        """Simulate retrieval for a query.

        Args:
            query: The query to retrieve for.
            strategy: Which strategy to simulate.
            top_k: Number of results to return.

        Returns:
            List of result dicts with chunk_id, score, content, metadata.
        """
        profile = STRATEGY_PROFILES.get(strategy.value, STRATEGY_PROFILES["dense"])
        relevant = set(query.relevant_chunk_ids)
        all_ids = [cid for cid in ALL_CHUNK_IDS if cid not in relevant]

        num_relevant = len(relevant)
        expected_relevant = max(1, int(num_relevant * profile["recall_bias"]))
        num_to_pick = min(expected_relevant, num_relevant)

        picked_relevant = self.rng.sample(list(relevant), num_to_pick)
        num_noise = min(top_k - num_to_pick, len(all_ids))
        picked_noise = self.rng.sample(all_ids, num_noise)

        combined = picked_relevant + picked_noise
        self.rng.shuffle(combined)

        score_lo, score_hi = profile["score_range"]
        results = []
        for rank, chunk_id in enumerate(combined[:top_k]):
            score = self.rng.uniform(score_lo, score_hi)
            score -= rank * 0.02
            results.append({
                "chunk_id": chunk_id,
                "score": round(max(score_lo, score), 4),
                "content": f"[Simulated content for {chunk_id}]",
                "metadata": {"simulated": True, "strategy": strategy.value},
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


class StandaloneEvaluator:
    """Evaluates retrieval strategies using simulated retrieval."""

    def __init__(
        self,
        dataset_manager: DatasetManager,
        metrics_storage: MetricsStorage,
        retriever: Optional[SimulatedRetriever] = None,
        seed: int = 42,
    ):
        self.dataset_manager = dataset_manager
        self.metrics_storage = metrics_storage
        self.retriever = retriever or SimulatedRetriever(seed=seed)
        self.metrics_engine = MetricsEngine()

    async def evaluate_strategy(
        self,
        strategy: RetrievalStrategy,
        dataset: GoldenDataset,
        config: EvaluationConfig,
    ) -> StrategyEvaluationResult:
        """Evaluate a single strategy against the dataset."""
        import time
        query_results: List[QueryEvaluationResult] = []

        for query in dataset.queries:
            start_time = time.perf_counter()
            raw_results = self.retriever.retrieve(query, strategy, top_k=20)
            latency_ms = (time.perf_counter() - start_time) * 1000

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

            relevant_ids = set(query.relevant_chunk_ids)
            metrics = self.metrics_engine.compute_all_metrics(
                retrieval_results, relevant_ids, config.top_k_values
            )

            query_results.append(
                QueryEvaluationResult(
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
            )

        aggregated = self._aggregate(query_results)
        return StrategyEvaluationResult(
            strategy=strategy,
            total_queries=len(query_results),
            query_results=query_results,
            **aggregated,
        )

    def _aggregate(self, query_results: List[QueryEvaluationResult]) -> Dict[str, float]:
        if not query_results:
            return {
                "avg_recall_at_5": 0.0, "avg_recall_at_10": 0.0,
                "avg_mrr": 0.0, "avg_precision_at_5": 0.0,
                "avg_precision_at_10": 0.0, "avg_hit_rate": 0.0,
                "avg_ndcg_at_5": 0.0, "avg_ndcg_at_10": 0.0,
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
        """Run full evaluation across all configured strategies."""
        if config is None:
            config = EvaluationConfig()

        dataset = self.dataset_manager.load_dataset(config.dataset_name)
        if dataset is None:
            logger.info(f"Dataset '{config.dataset_name}' not found, creating default.")
            dataset = self.dataset_manager.get_or_create_default_dataset()

        strategy_results: List[StrategyEvaluationResult] = []
        for strategy in config.strategies:
            result = await self.evaluate_strategy(strategy, dataset, config)
            strategy_results.append(result)

            if config.store_results:
                self.metrics_storage.store_strategy_result(
                    strategy=strategy,
                    dataset_name=dataset.name,
                    result=result,
                )

        leaderboard = self._generate_leaderboard(strategy_results)

        return EvaluationReport(
            dataset_name=dataset.name,
            strategy_results=strategy_results,
            leaderboard=leaderboard,
            metadata={
                "config": config.model_dump(),
                "total_queries": len(dataset.queries),
                "runner": "standalone",
            },
        )

    def _generate_leaderboard(
        self, strategy_results: List[StrategyEvaluationResult]
    ) -> List[Dict[str, Any]]:
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
            entries.append({
                "strategy": result.strategy.value,
                "avg_recall_at_5": round(result.avg_recall_at_5, 4),
                "avg_recall_at_10": round(result.avg_recall_at_10, 4),
                "avg_mrr": round(result.avg_mrr, 4),
                "avg_precision_at_5": round(result.avg_precision_at_5, 4),
                "avg_ndcg_at_5": round(result.avg_ndcg_at_5, 4),
                "avg_ndcg_at_10": round(result.avg_ndcg_at_10, 4),
                "avg_hit_rate": round(result.avg_hit_rate, 4),
                "avg_latency_ms": round(result.avg_latency_ms, 2),
                "composite_score": round(composite_score, 4),
            })

        entries.sort(key=lambda x: x["composite_score"], reverse=True)
        for idx, entry in enumerate(entries, start=1):
            entry["rank"] = idx
        return entries


def format_strategy_output(result: StrategyEvaluationResult) -> Dict[str, Any]:
    """Format a strategy result into the required output format."""
    return {
        "strategy": result.strategy.value,
        "recall_at_5": round(result.avg_recall_at_5, 4),
        "recall_at_10": round(result.avg_recall_at_10, 4),
        "mrr": round(result.avg_mrr, 4),
        "precision_at_5": round(result.avg_precision_at_5, 4),
        "precision_at_10": round(result.avg_precision_at_10, 4),
        "ndcg_at_5": round(result.avg_ndcg_at_5, 4),
        "ndcg_at_10": round(result.avg_ndcg_at_10, 4),
        "hit_rate": round(result.avg_hit_rate, 4),
        "latency_ms": round(result.avg_latency_ms, 2),
    }


async def run_standalone_evaluation(
    dataset_name: str = "default",
    strategies: Optional[List[str]] = None,
    output_dir: Optional[Path] = None,
    mode: str = "simulated",
    load_reranker_model: bool = False,
) -> EvaluationReport:
    """Run a complete standalone evaluation.

    Args:
        dataset_name: Golden dataset to use.
        strategies: List of strategy names. Defaults to all 4.
        output_dir: Directory for output files.
        mode: "simulated" (default) or "production".
        load_reranker_model: In production mode, load real reranker model.

    Returns:
        Complete EvaluationReport.
    """
    if strategies is None:
        strategies = ["dense", "bm25", "hybrid", "hybrid_rerank"]

    strategy_enums = [RetrievalStrategy(s) for s in strategies]
    config = EvaluationConfig(
        dataset_name=dataset_name,
        strategies=strategy_enums,
        store_results=True,
        generate_report=True,
    )

    # ------------------------------------------------------------
    # Simulated mode (existing behavior)
    # ------------------------------------------------------------
    if mode == "simulated":
        dataset_manager = DatasetManager()
        metrics_storage = MetricsStorage()
        evaluator = StandaloneEvaluator(
            dataset_manager=dataset_manager,
            metrics_storage=metrics_storage,
        )

        report = await evaluator.run_evaluation(config)
        # Add run metadata
        report.metadata = {
            **report.metadata,
            "mode": "simulated",
            "load_reranker_model": bool(load_reranker_model),
        }

    # ------------------------------------------------------------
    # Production mode (RetrievalEvaluator + real retrieval services)
    # ------------------------------------------------------------
    elif mode == "production":
        from app.evaluation.evaluator import RetrievalEvaluator
        from app.core.database import async_session_factory
        from app.api.dependencies import (
            get_embedding_provider,
            get_bm25_retriever,
            get_hybrid_retriever,
            get_reranker_service,
            get_retrieval_service,
        )
        from app.services.reranker.model import BGERerankerProvider, ScoringResult
        from app.services.reranker.service import RerankerService

        # Lightweight deterministic stub reranker for production default
        class StubBGERerankerProvider(BGERerankerProvider):
            def __init__(self) -> None:
                super().__init__(model_name="stub-reranker", device="cpu")

            def _get_model(self):
                return None

            def score_pair(self, query: str, text: str) -> float:
                q = set((query or "").lower().split())
                t = set((text or "").lower().split())
                if not (q | t):
                    return 0.0
                return float(len(q & t)) / float(len(q | t))

            def score_pairs(self, pairs: List[tuple[str, str]]) -> List[float]:
                return [self.score_pair(q, t) for q, t in pairs]

            def score_pairs_timed(
                self, pairs: List[tuple[str, str]]
            ) -> ScoringResult:
                return ScoringResult(
                    scores=self.score_pairs(pairs),
                    scoring_latency_ms=0.0,
                )

            def get_model_name(self) -> str:
                return "stub-reranker"

            def health_check(self) -> bool:
                return True

        dataset_manager = DatasetManager()
        metrics_storage = MetricsStorage()

        dataset_obj = dataset_manager.load_dataset(dataset_name)
        dataset_version = None
        dataset_type = None
        if dataset_obj:
            dataset_version = dataset_obj.metadata.get("version") if isinstance(dataset_obj.metadata, dict) else None
            dataset_type = dataset_obj.metadata.get("type") if isinstance(dataset_obj.metadata, dict) else None

        async with async_session_factory() as db_session:
            embedding_provider = get_embedding_provider()
            retrieval_service = await get_retrieval_service(
                db_session=db_session, embedding_provider=embedding_provider
            )

            bm25_retriever = await get_bm25_retriever(db_session=db_session)

            # HybridRetriever depends on QueryAnalyzer; fallback to default inside constructor if allowed.
            # The HybridRetriever constructor in app/services/hybrid/service.py handles defaults internally if query analyzer missing.
            hybrid_retriever = get_hybrid_retriever(
                retrieval_service=retrieval_service,
                bm25_retriever=bm25_retriever,
            )

            if load_reranker_model:
                reranker_service = await get_reranker_service()
                reranker_type = "real"
            else:
                reranker_service = RerankerService(
                    provider=StubBGERerankerProvider(),
                    default_top_k=10,
                    default_score_threshold=0.0,
                )
                reranker_type = "mock"

            evaluator = RetrievalEvaluator(
                db_session=db_session,
                retrieval_service=retrieval_service,
                bm25_retriever=bm25_retriever,
                hybrid_retriever=hybrid_retriever,
                reranker_service=reranker_service,
                dataset_manager=dataset_manager,
                metrics_storage=metrics_storage,
            )

            report = await evaluator.run_evaluation(config)

            embedding_model_name = embedding_provider.get_model_name() if hasattr(embedding_provider, "get_model_name") else None
            report.metadata = {
                **report.metadata,
                "mode": "production",
                "load_reranker_model": bool(load_reranker_model),
                "reranker_type": reranker_type,
                "embedding_model": embedding_model_name,
                "dataset_version": dataset_version,
                "dataset_type": dataset_type,
            }
    else:
        raise ValueError(f"Unknown mode: {mode}. Expected 'simulated' or 'production'.")

    # Output strategy results in the required format
    print("\n" + "=" * 70)
    print("RETRIEVAL EVALUATION RESULTS")
    print("=" * 70)

    for result in report.strategy_results:
        output = format_strategy_output(result)
        print(f"\n{json.dumps(output, indent=2)}")

    # Print leaderboard
    leaderboard_obj = Leaderboard()
    entries = leaderboard_obj.get_latest_leaderboard()
    if entries:
        print("\n" + leaderboard_obj.format_leaderboard(entries))

    # Save reports
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        gen = ReportGenerator(reports_dir=output_dir)
    else:
        gen = ReportGenerator()

    gen.generate_report(report)
    logger.info("Reports saved.")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Standalone Retrieval Evaluation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="default",
        help="Golden dataset name (default: default)",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=["dense", "bm25", "hybrid", "hybrid_rerank"],
        default=["dense", "bm25", "hybrid", "hybrid_rerank"],
        help="Strategies to evaluate",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for reports",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None
    asyncio.run(run_standalone_evaluation(
        dataset_name=args.dataset,
        strategies=args.strategies,
        output_dir=output_dir,
    ))


if __name__ == "__main__":
    main()
