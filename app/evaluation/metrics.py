"""Metrics Engine for Retrieval Evaluation.

Calculates standard IR metrics:
- Recall@K
- Precision@K
- MRR (Mean Reciprocal Rank)
- Hit Rate
- NDCG@K (Normalized Discounted Cumulative Gain)
"""

import logging
import math
from typing import Dict, List, Set, Optional

from app.evaluation.schemas import RetrievalResult

logger = logging.getLogger(__name__)


class MetricsEngine:
    """Engine for computing retrieval evaluation metrics."""

    @staticmethod
    def compute_recall_at_k(
        retrieved_ids: List[str],
        relevant_ids: Set[str],
        k: int,
    ) -> float:
        """Compute Recall@K.

        Recall@K = |{relevant items} ∩ {retrieved top-K items}| / |{relevant items}|

        Args:
            retrieved_ids: Ordered list of retrieved chunk IDs.
            relevant_ids: Set of relevant chunk IDs.
            k: Number of top results to consider.

        Returns:
            Recall@K score between 0.0 and 1.0.
        """
        if not relevant_ids:
            logger.warning("No relevant IDs provided for recall calculation.")
            return 0.0

        top_k_retrieved = set(retrieved_ids[:k])
        relevant_retrieved = top_k_retrieved.intersection(relevant_ids)
        recall = len(relevant_retrieved) / len(relevant_ids)
        return min(recall, 1.0)

    @staticmethod
    def compute_precision_at_k(
        retrieved_ids: List[str],
        relevant_ids: Set[str],
        k: int,
    ) -> float:
        """Compute Precision@K.

        Precision@K = |{relevant items} ∩ {retrieved top-K items}| / K

        Args:
            retrieved_ids: Ordered list of retrieved chunk IDs.
            relevant_ids: Set of relevant chunk IDs.
            k: Number of top results to consider.

        Returns:
            Precision@K score between 0.0 and 1.0.
        """
        if k == 0:
            return 0.0

        top_k_retrieved = set(retrieved_ids[:k])
        relevant_retrieved = top_k_retrieved.intersection(relevant_ids)
        precision = len(relevant_retrieved) / k
        return precision

    @staticmethod
    def compute_mrr(
        retrieved_ids: List[str],
        relevant_ids: Set[str],
    ) -> float:
        """Compute Mean Reciprocal Rank (MRR).

        MRR = 1 / rank_of_first_relevant_item

        Args:
            retrieved_ids: Ordered list of retrieved chunk IDs.
            relevant_ids: Set of relevant chunk IDs.

        Returns:
            MRR score between 0.0 and 1.0.
        """
        if not relevant_ids:
            logger.warning("No relevant IDs provided for MRR calculation.")
            return 0.0

        for rank, chunk_id in enumerate(retrieved_ids, start=1):
            if chunk_id in relevant_ids:
                return 1.0 / rank

        return 0.0

    @staticmethod
    def compute_hit_rate(
        retrieved_ids: List[str],
        relevant_ids: Set[str],
        k: int = 10,
    ) -> float:
        """Compute Hit Rate@K.

        Hit Rate = 1 if any relevant item is in top-K, else 0.

        Args:
            retrieved_ids: Ordered list of retrieved chunk IDs.
            relevant_ids: Set of relevant chunk IDs.
            k: Number of top results to consider.

        Returns:
            Hit rate (0.0 or 1.0).
        """
        if not relevant_ids:
            return 0.0

        top_k_retrieved = set(retrieved_ids[:k])
        if top_k_retrieved.intersection(relevant_ids):
            return 1.0
        return 0.0

    @staticmethod
    def compute_ndcg_at_k(
        retrieved_ids: List[str],
        relevant_ids: Set[str],
        k: int,
        relevance_scores: Optional[Dict[str, float]] = None,
    ) -> float:
        """Compute NDCG@K (Normalized Discounted Cumulative Gain).

        NDCG@K = DCG@K / IDCG@K

        DCG@K = sum_{i=1}^{K} (2^rel_i - 1) / log2(i + 1)

        If no relevance_scores are provided, uses binary relevance
        (1 if the retrieved item is in relevant_ids, 0 otherwise).

        Args:
            retrieved_ids: Ordered list of retrieved chunk IDs.
            relevant_ids: Set of relevant chunk IDs.
            k: Number of top results to consider.
            relevance_scores: Optional mapping of chunk_id to graded
                relevance score. Defaults to binary (0 or 1).

        Returns:
            NDCG@K score between 0.0 and 1.0.
        """
        if not relevant_ids:
            return 0.0

        def _gain(chunk_id: str) -> float:
            if relevance_scores and chunk_id in relevance_scores:
                return relevance_scores[chunk_id]
            return 1.0 if chunk_id in relevant_ids else 0.0

        # Compute DCG@K
        dcg = 0.0
        for i, chunk_id in enumerate(retrieved_ids[:k]):
            rank = i + 1
            rel = _gain(chunk_id)
            dcg += (math.pow(2, rel) - 1.0) / math.log2(rank + 1)

        # Compute IDCG@K: ideal ordering puts all relevant items first
        ideal_gains = sorted(
            [_gain(cid) for cid in relevant_ids],
            reverse=True,
        )
        idcg = 0.0
        for i in range(min(k, len(ideal_gains))):
            rank = i + 1
            rel = ideal_gains[i]
            idcg += (math.pow(2, rel) - 1.0) / math.log2(rank + 1)

        if idcg == 0.0:
            return 0.0

        return dcg / idcg

    @staticmethod
    def compute_all_metrics(
        retrieved_results: List[RetrievalResult],
        relevant_ids: Set[str],
        k_values: List[int] = None,
    ) -> Dict[str, float]:
        """Compute all metrics for a single query evaluation.

        Args:
            retrieved_results: List of retrieval results ordered by rank.
            relevant_ids: Set of relevant chunk IDs.
            k_values: List of K values for Recall@K and Precision@K.

        Returns:
            Dictionary containing all computed metrics.
        """
        if k_values is None:
            k_values = [5, 10]

        retrieved_ids = [r.chunk_id for r in retrieved_results]

        metrics = {}

        # Compute Recall@K and Precision@K for each K value
        for k in k_values:
            metrics[f"recall_at_{k}"] = MetricsEngine.compute_recall_at_k(
                retrieved_ids, relevant_ids, k
            )
            metrics[f"precision_at_{k}"] = MetricsEngine.compute_precision_at_k(
                retrieved_ids, relevant_ids, k
            )

        # Compute MRR
        metrics["mrr"] = MetricsEngine.compute_mrr(retrieved_ids, relevant_ids)

        # Compute Hit Rate (using max K)
        max_k = max(k_values) if k_values else 10
        metrics["hit_rate"] = MetricsEngine.compute_hit_rate(
            retrieved_ids, relevant_ids, max_k
        )

        # Compute NDCG for each K value
        for k in k_values:
            metrics[f"ndcg_at_{k}"] = MetricsEngine.compute_ndcg_at_k(
                retrieved_ids, relevant_ids, k
            )

        return metrics

    @staticmethod
    def aggregate_metrics(
        query_metrics: List[Dict[str, float]],
    ) -> Dict[str, float]:
        """Aggregate metrics across multiple queries.

        Args:
            query_metrics: List of metric dictionaries from individual queries.

        Returns:
            Dictionary with averaged metrics.
        """
        if not query_metrics:
            return {}

        aggregated = {}
        keys = query_metrics[0].keys()

        for key in keys:
            values = [m[key] for m in query_metrics if key in m]
            if values:
                aggregated[f"avg_{key}"] = sum(values) / len(values)
            else:
                aggregated[f"avg_{key}"] = 0.0

        return aggregated

    @staticmethod
    def compute_composite_score(
        metrics: Dict[str, float],
        weights: Dict[str, float] = None,
    ) -> float:
        """Compute a weighted composite score for ranking strategies.

        Default weights:
            - recall_at_5: 0.20
            - recall_at_10: 0.15
            - mrr: 0.20
            - precision_at_5: 0.10
            - hit_rate: 0.10
            - ndcg_at_5: 0.15
            - ndcg_at_10: 0.10

        Args:
            metrics: Dictionary of metric values.
            weights: Optional custom weights for each metric.

        Returns:
            Composite score between 0.0 and 1.0.
        """
        if weights is None:
            weights = {
                "recall_at_5": 0.20,
                "recall_at_10": 0.15,
                "mrr": 0.20,
                "precision_at_5": 0.10,
                "hit_rate": 0.10,
                "ndcg_at_5": 0.15,
                "ndcg_at_10": 0.10,
            }

        score = 0.0
        total_weight = 0.0

        for metric_name, weight in weights.items():
            # Try both raw and averaged metric names
            value = metrics.get(metric_name) or metrics.get(f"avg_{metric_name}", 0.0)
            score += value * weight
            total_weight += weight

        if total_weight > 0:
            score /= total_weight

        return score