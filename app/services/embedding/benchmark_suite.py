import os
import time
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import List, Optional
from app.core.config import settings
from app.schemas.evaluation import (
    GoldenEvaluationItem,
    QueryEvaluationResult,
    BenchmarkSummaryMetrics,
    BenchmarkReport
)
from app.services.embedding.retrieval import RetrievalService

logger = logging.getLogger(__name__)

class RetrievalBenchmarkRunner:
    """Runs automated retrieval benchmark evaluations over a Golden Dataset, logging history and metrics."""

    def __init__(self, retrieval_service: RetrievalService, history_dir: Optional[str] = None):
        self.retrieval_service = retrieval_service
        self.history_dir = history_dir or os.path.join(settings.STORAGE_ROOT, "benchmarks", "history")
        # Ensure directories exist
        os.makedirs(self.history_dir, exist_ok=True)

    def _is_match(self, retrieved: dict, item: GoldenEvaluationItem) -> bool:
        """Determines if a retrieved chunk matches ground truth expected IDs or sections."""
        # Match by chunk ID
        if retrieved["chunk_id"] in item.expected_chunk_ids:
            return True
        # Match by section title fallback (case-insensitive check)
        section = retrieved.get("metadata", {}).get("section", "")
        for sec in item.expected_sections:
            if sec.lower() in section.lower():
                return True
        return False

    async def run_benchmark(
        self,
        golden_dataset: List[GoldenEvaluationItem],
        top_k: int = 10,
        distance_metric: str = "cosine"
    ) -> BenchmarkReport:
        """Executes retrieval queries, calculates precision, recall, MRR, and persists metrics."""
        start_time = time.perf_counter()
        query_results: List[QueryEvaluationResult] = []

        if not golden_dataset:
            raise ValueError("Golden dataset is empty. Cannot run benchmark.")

        for item in golden_dataset:
            # Execute retrieval
            response = await self.retrieval_service.retrieve(
                query=item.query,
                top_k=top_k,
                distance_metric=distance_metric
            )
            retrieved_list = response.get("results", [])
            retrieved_ids = [r["chunk_id"] for r in retrieved_list]

            # 1. Match detection
            matches = [self._is_match(r, item) for r in retrieved_list]

            # 2. expected count for recall denominator
            expected_count = max(len(item.expected_chunk_ids), len(item.expected_sections), 1)

            # 3. Precision@5 and Precision@10
            matches_5 = matches[:5]
            matches_10 = matches[:10]
            
            p_5 = sum(matches_5) / 5.0
            p_10 = sum(matches_10) / 10.0

            # 4. Recall@5 and Recall@10
            r_5 = sum(matches_5) / expected_count
            r_10 = sum(matches_10) / expected_count

            # 5. Hit Rate
            hit_5 = any(matches_5)
            hit_10 = any(matches_10)

            # 6. Reciprocal Rank (MRR)
            mrr_score = 0.0
            for rank, matched in enumerate(matches, 1):
                if matched:
                    mrr_score = 1.0 / rank
                    break

            query_results.append(
                QueryEvaluationResult(
                    query=item.query,
                    retrieved_ids=retrieved_ids,
                    precision_at_5=p_5,
                    precision_at_10=p_10,
                    recall_at_5=r_5,
                    recall_at_10=r_10,
                    mrr=mrr_score,
                    hit_at_5=hit_5,
                    hit_at_10=hit_10
                )
            )

        # Aggregations
        num_queries = len(golden_dataset)
        mean_p5 = sum(q.precision_at_5 for q in query_results) / num_queries
        mean_p10 = sum(q.precision_at_10 for q in query_results) / num_queries
        mean_r5 = sum(q.recall_at_5 for q in query_results) / num_queries
        mean_r10 = sum(q.recall_at_10 for q in query_results) / num_queries
        mean_mrr = sum(q.mrr for q in query_results) / num_queries
        hit_rate5 = sum(1.0 if q.hit_at_5 else 0.0 for q in query_results) / num_queries
        hit_rate10 = sum(1.0 if q.hit_at_10 else 0.0 for q in query_results) / num_queries

        summary_metrics = BenchmarkSummaryMetrics(
            mean_precision_at_5=mean_p5,
            mean_precision_at_10=mean_p10,
            mean_recall_at_5=mean_r5,
            mean_recall_at_10=mean_r10,
            mrr=mean_mrr,
            hit_rate_at_5=hit_rate5,
            hit_rate_at_10=hit_rate10
        )

        duration_ms = (time.perf_counter() - start_time) * 1000
        provider = self.retrieval_service.embedding_provider
        
        report = BenchmarkReport(
            benchmark_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            embedding_model=provider.get_model_name(),
            embedding_dimension=provider.get_dimension(),
            distance_metric=distance_metric,
            fallback_mode_active=settings.USE_PGVECTOR_FALLBACK,
            metrics=summary_metrics,
            query_results=query_results,
            duration_ms=duration_ms
        )

        # Persist report as JSON file in history directory
        model_safe = re_sub_name = "".join(c if c.isalnum() else "_" for c in report.embedding_model)
        filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{model_safe}.json"
        filepath = os.path.join(self.history_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))

        logger.info(f"Saved benchmark report to {filepath}")
        return report

    def get_history(self) -> List[BenchmarkReport]:
        """Loads and returns all historical benchmark reports in the history directory."""
        history = []
        if not os.path.exists(self.history_dir):
            return history
        
        for file in sorted(os.listdir(self.history_dir)):
            if file.endswith(".json"):
                path = os.path.join(self.history_dir, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        history.append(BenchmarkReport.model_validate(data))
                except Exception as e:
                    logger.error(f"Failed to load historical report {path}: {e}")
        return history

    def generate_comparison_report(self, reports: List[BenchmarkReport]) -> str:
        """Compiles a Markdown table comparing metrics across benchmark reports."""
        if not reports:
            return "No benchmark reports available for comparison."

        md = "# Retrieval Benchmark Comparison Report\n\n"
        md += "| Run Timestamp | Embedding Model | Metric | Recall@5 | Recall@10 | MRR | Hit Rate@5 | Hit Rate@10 | Precision@5 | Precision@10 | Fallback |\n"
        md += "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        
        for r in reports:
            dt = datetime.fromisoformat(r.timestamp).strftime("%Y-%m-%d %H:%M:%S")
            md += (
                f"| {dt} | {r.embedding_model} ({r.embedding_dimension}D) | {r.distance_metric} "
                f"| {r.metrics.mean_recall_at_5:.3f} | {r.metrics.mean_recall_at_10:.3f} | {r.metrics.mrr:.3f} "
                f"| {r.metrics.hit_rate_at_5:.1%} | {r.metrics.hit_rate_at_10:.1%} "
                f"| {r.metrics.mean_precision_at_5:.3f} | {r.metrics.mean_precision_at_10:.3f} "
                f"| {'Yes' if r.fallback_mode_active else 'No'} |\n"
            )
        return md
