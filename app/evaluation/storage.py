"""Metrics Storage for historical tracking.

Stores and retrieves evaluation metrics for tracking performance over time.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.evaluation.schemas import (
    HistoricalMetrics,
    RetrievalStrategy,
    StrategyEvaluationResult,
)

logger = logging.getLogger(__name__)

# Default storage path for historical metrics
DEFAULT_STORAGE_DIR = Path("storage/evaluation/metrics")


class MetricsStorage:
    """Storage for historical evaluation metrics."""

    def __init__(self, storage_dir: Optional[Path] = None):
        """Initialize metrics storage.

        Args:
            storage_dir: Directory to store metrics. Defaults to storage/evaluation/metrics.
        """
        self.storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._cache: List[HistoricalMetrics] = []

    def _get_storage_path(self, strategy: RetrievalStrategy) -> Path:
        """Get the storage file path for a strategy.

        Args:
            strategy: Retrieval strategy.

        Returns:
            Path to the storage file.
        """
        return self.storage_dir / f"{strategy.value}_history.json"

    def store_strategy_result(
        self,
        strategy: RetrievalStrategy,
        dataset_name: str,
        result: StrategyEvaluationResult,
    ) -> HistoricalMetrics:
        """Store evaluation results for a strategy.

        Args:
            strategy: The retrieval strategy.
            dataset_name: Name of the dataset used.
            result: Strategy evaluation result.

        Returns:
            Stored HistoricalMetrics record.
        """
        record = HistoricalMetrics(
            strategy=strategy,
            dataset_name=dataset_name,
            recall_at_5=result.avg_recall_at_5,
            recall_at_10=result.avg_recall_at_10,
            mrr=result.avg_mrr,
            precision_at_5=result.avg_precision_at_5,
            precision_at_10=result.avg_precision_at_10,
            hit_rate=result.avg_hit_rate,
            latency_ms=result.avg_latency_ms,
            metadata={
                "total_queries": result.total_queries,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        # Load existing history
        history = self._load_history(strategy)

        # Append new record
        history.append(record)

        # Save updated history
        self._save_history(strategy, history)

        # Update cache
        self._cache.append(record)

        logger.info(
            f"Stored metrics for strategy '{strategy.value}': "
            f"Recall@5={record.recall_at_5:.4f}, MRR={record.mrr:.4f}"
        )

        return record

    def _load_history(self, strategy: RetrievalStrategy) -> List[HistoricalMetrics]:
        """Load historical metrics for a strategy.

        Args:
            strategy: Retrieval strategy.

        Returns:
            List of historical metrics records.
        """
        file_path = self._get_storage_path(strategy)
        if not file_path.exists():
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [HistoricalMetrics(**item) for item in data]
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Error loading history for {strategy.value}: {e}")
            return []

    def _save_history(
        self, strategy: RetrievalStrategy, history: List[HistoricalMetrics]
    ) -> None:
        """Save historical metrics for a strategy.

        Args:
            strategy: Retrieval strategy.
            history: List of historical metrics records.
        """
        file_path = self._get_storage_path(strategy)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(
                    [item.model_dump() for item in history],
                    f,
                    indent=2,
                    default=str,
                )
        except Exception as e:
            logger.error(f"Error saving history for {strategy.value}: {e}")

    def get_history(
        self,
        strategy: Optional[RetrievalStrategy] = None,
        limit: Optional[int] = None,
    ) -> List[HistoricalMetrics]:
        """Get historical metrics.

        Args:
            strategy: Optional strategy filter. If None, returns all strategies.
            limit: Optional limit on number of records returned.

        Returns:
            List of historical metrics records.
        """
        if strategy:
            history = self._load_history(strategy)
        else:
            history = []
            for s in RetrievalStrategy:
                history.extend(self._load_history(s))

        # Sort by timestamp descending
        history.sort(key=lambda x: x.timestamp, reverse=True)

        if limit:
            history = history[:limit]

        return history

    def get_latest(
        self, strategy: RetrievalStrategy
    ) -> Optional[HistoricalMetrics]:
        """Get the latest metrics for a strategy.

        Args:
            strategy: Retrieval strategy.

        Returns:
            Latest HistoricalMetrics record or None.
        """
        history = self._load_history(strategy)
        if not history:
            return None
        return max(history, key=lambda x: x.timestamp)

    def get_trend(
        self,
        strategy: RetrievalStrategy,
        metric: str = "recall_at_5",
        window: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get trend data for a specific metric.

        Args:
            strategy: Retrieval strategy.
            metric: Metric name to track.
            window: Number of recent records to include.

        Returns:
            List of trend data points.
        """
        history = self._load_history(strategy)
        history.sort(key=lambda x: x.timestamp)

        # Take the last 'window' records
        recent = history[-window:] if len(history) > window else history

        trend = []
        for record in recent:
            value = getattr(record, metric, None)
            if value is not None:
                trend.append({
                    "timestamp": record.timestamp.isoformat(),
                    "value": value,
                    "dataset": record.dataset_name,
                })

        return trend

    def compare_strategies(
        self, metric: str = "recall_at_5"
    ) -> Dict[str, Any]:
        """Compare latest metrics across all strategies.

        Args:
            metric: Metric to compare.

        Returns:
            Comparison dictionary.
        """
        comparison = {}
        for strategy in RetrievalStrategy:
            latest = self.get_latest(strategy)
            if latest:
                comparison[strategy.value] = {
                    "value": getattr(latest, metric, None),
                    "timestamp": latest.timestamp.isoformat(),
                    "dataset": latest.dataset_name,
                }
            else:
                comparison[strategy.value] = None

        return comparison

    def clear_history(self, strategy: Optional[RetrievalStrategy] = None) -> bool:
        """Clear historical metrics.

        Args:
            strategy: Optional strategy to clear. If None, clears all.

        Returns:
            True if cleared successfully.
        """
        try:
            if strategy:
                file_path = self._get_storage_path(strategy)
                if file_path.exists():
                    file_path.unlink()
            else:
                for s in RetrievalStrategy:
                    file_path = self._get_storage_path(s)
                    if file_path.exists():
                        file_path.unlink()
            logger.info(f"Cleared history for {strategy.value if strategy else 'all strategies'}")
            return True
        except Exception as e:
            logger.error(f"Error clearing history: {e}")
            return False