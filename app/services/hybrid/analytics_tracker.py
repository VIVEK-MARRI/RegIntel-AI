"""Retrieval Analytics Tracker.

Bridges the retrieval pipeline (hybrid retriever, reranker) to the
analytics database layer.  Records per-query telemetry for observability,
performance monitoring, and retrieval evaluation.

Designed as a lightweight, async-aware tracker that can be called from
any pipeline stage without blocking the critical path.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import (
    RetrievalMetricsRecord,
    QueryDistributionRecord,
    RerankerGainRecord,
    SystemHealthSnapshot,
    QueryCategoryEnum,
)

logger = logging.getLogger(__name__)


class RetrievalAnalyticsTracker:
    """Tracks retrieval pipeline telemetry to the analytics database.

    Usage:
        tracker = RetrievalAnalyticsTracker(db_session)
        await tracker.record_retrieval(telemetry_dict)
        await tracker.record_reranker_gain(telemetry_dict)
    """

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def record_retrieval(
        self,
        query_text: str,
        query_id: Optional[str] = None,
        strategy: str = "hybrid",
        query_type: str = "unknown",
        query_category: str = QueryCategoryEnum.UNKNOWN.value,
        dataset_name: Optional[str] = None,
        dense_recall_at_5: Optional[float] = None,
        dense_recall_at_10: Optional[float] = None,
        bm25_recall_at_5: Optional[float] = None,
        bm25_recall_at_10: Optional[float] = None,
        hybrid_recall_at_5: Optional[float] = None,
        hybrid_recall_at_10: Optional[float] = None,
        precision_at_5: Optional[float] = None,
        precision_at_10: Optional[float] = None,
        mrr: Optional[float] = None,
        hit_rate: Optional[float] = None,
        retrieval_latency_ms: Optional[float] = None,
        total_latency_ms: Optional[float] = None,
        results_returned: int = 0,
        relevant_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RetrievalMetricsRecord:
        """Record a single retrieval operation's metrics."""
        record = RetrievalMetricsRecord(
            query_id=query_id or str(uuid.uuid4()),
            query_text=query_text[:2000],
            query_category=self._map_query_type_to_category(query_type),
            strategy=strategy,
            dataset_name=dataset_name,
            dense_recall_at_5=dense_recall_at_5,
            dense_recall_at_10=dense_recall_at_10,
            bm25_recall_at_5=bm25_recall_at_5,
            bm25_recall_at_10=bm25_recall_at_10,
            hybrid_recall_at_5=hybrid_recall_at_5,
            hybrid_recall_at_10=hybrid_recall_at_10,
            precision_at_5=precision_at_5,
            precision_at_10=precision_at_10,
            mrr=mrr,
            hit_rate=hit_rate,
            retrieval_latency_ms=retrieval_latency_ms,
            total_latency_ms=total_latency_ms,
            results_returned=results_returned,
            relevant_count=relevant_count,
            metadata_json=metadata or {},
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def record_reranker_gain(
        self,
        window_type: str,
        window_start: datetime,
        window_end: datetime,
        avg_recall_gain_at_5: Optional[float] = None,
        avg_recall_gain_at_10: Optional[float] = None,
        avg_precision_gain_at_5: Optional[float] = None,
        avg_mrr_gain: Optional[float] = None,
        avg_hit_rate_gain: Optional[float] = None,
        avg_reranker_latency_ms: Optional[float] = None,
        reranker_queries_count: int = 0,
        improvement_rate: Optional[float] = None,
        dataset_name: Optional[str] = None,
    ) -> RerankerGainRecord:
        """Record reranker improvement metrics."""
        record = RerankerGainRecord(
            window_type=window_type,
            window_start=window_start,
            window_end=window_end,
            dataset_name=dataset_name,
            avg_recall_gain_at_5=avg_recall_gain_at_5,
            avg_recall_gain_at_10=avg_recall_gain_at_10,
            avg_precision_gain_at_5=avg_precision_gain_at_5,
            avg_mrr_gain=avg_mrr_gain,
            avg_hit_rate_gain=avg_hit_rate_gain,
            avg_reranker_latency_ms=avg_reranker_latency_ms,
            reranker_queries_count=reranker_queries_count,
            improvement_rate=improvement_rate,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def record_system_health(
        self,
        status: str = "healthy",
        dense_available: bool = True,
        bm25_available: bool = True,
        hybrid_available: bool = True,
        reranker_available: bool = True,
        index_consistent: bool = True,
        embedding_coverage: Optional[float] = None,
        total_indexed_chunks: Optional[int] = None,
        avg_latency: Optional[float] = None,
        queries_last_hour: Optional[int] = None,
        error_rate: Optional[float] = None,
    ) -> SystemHealthSnapshot:
        """Record a system health snapshot."""
        record = SystemHealthSnapshot(
            status=status,
            dense_retrieval_available=dense_available,
            bm25_retrieval_available=bm25_available,
            hybrid_retrieval_available=hybrid_available,
            reranker_available=reranker_available,
            index_consistency=index_consistent,
            embedding_coverage_pct=embedding_coverage,
            total_indexed_chunks=total_indexed_chunks,
            avg_latency_last_hour_ms=avg_latency,
            queries_last_hour=queries_last_hour,
            error_rate_last_hour=error_rate,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def record_query_distribution(
        self,
        window_type: str,
        window_start: datetime,
        window_end: datetime,
        category_counts: Dict[str, int],
        strategy_counts: Dict[str, int],
        avg_query_length: Optional[float] = None,
        avg_result_count: Optional[float] = None,
    ) -> QueryDistributionRecord:
        """Record query distribution data."""
        total = sum(category_counts.values())
        record = QueryDistributionRecord(
            window_type=window_type,
            window_start=window_start,
            window_end=window_end,
            factual_count=category_counts.get("factual", 0),
            navigational_count=category_counts.get("navigational", 0),
            analytical_count=category_counts.get("analytical", 0),
            comparative_count=category_counts.get("comparative", 0),
            definitional_count=category_counts.get("definitional", 0),
            procedural_count=category_counts.get("procedural", 0),
            unknown_count=category_counts.get("unknown", 0),
            total_count=total,
            dense_count=strategy_counts.get("dense", 0),
            bm25_count=strategy_counts.get("bm25", 0),
            hybrid_count=strategy_counts.get("hybrid", 0),
            hybrid_rerank_count=strategy_counts.get("hybrid_rerank", 0),
            avg_query_length=avg_query_length,
            avg_result_count=avg_result_count,
        )
        self.db.add(record)
        await self.db.flush()
        return record

    @staticmethod
    def _map_query_type_to_category(query_type: str) -> str:
        """Map query analysis type to analytics category."""
        mapping = {
            "keyword": QueryCategoryEnum.NAVIGATIONAL.value,
            "circular": QueryCategoryEnum.NAVIGATIONAL.value,
            "regulation": QueryCategoryEnum.FACTUAL.value,
            "semantic": QueryCategoryEnum.ANALYTICAL.value,
            "comparison": QueryCategoryEnum.COMPARATIVE.value,
            "comparative": QueryCategoryEnum.COMPARATIVE.value,
            "definition": QueryCategoryEnum.DEFINITIONAL.value,
        }
        return mapping.get(query_type, QueryCategoryEnum.UNKNOWN.value)
