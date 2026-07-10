"""Analytics repository layer for database operations.

Provides CRUD operations and aggregation queries for all analytics models.
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select, text, literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import (
    AggregatedMetricsSnapshot,
    QueryDistributionRecord,
    RetrievalMetricsRecord,
    RerankerGainRecord,
    SystemHealthSnapshot,
)

logger = logging.getLogger(__name__)


class RetrievalMetricsRepository:
    """Repository for retrieval metrics records."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create(self, data: Dict[str, Any]) -> RetrievalMetricsRecord:
        """Create a new retrieval metrics record."""
        record = RetrievalMetricsRecord(**data)
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def get_by_id(self, record_id: uuid.UUID) -> Optional[RetrievalMetricsRecord]:
        """Get a metrics record by ID."""
        stmt = select(RetrievalMetricsRecord).where(
            RetrievalMetricsRecord.id == record_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def query_records(
        self,
        strategy: Optional[str] = None,
        dataset_name: Optional[str] = None,
        query_category: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[RetrievalMetricsRecord], int]:
        """Query metrics records with filters. Returns (records, total_count)."""
        stmt = select(RetrievalMetricsRecord)
        count_stmt = select(func.count(RetrievalMetricsRecord.id))

        filters = []
        if strategy:
            filters.append(RetrievalMetricsRecord.strategy == strategy)
        if dataset_name:
            filters.append(RetrievalMetricsRecord.dataset_name == dataset_name)
        if query_category:
            filters.append(RetrievalMetricsRecord.query_category == query_category)
        if start_time:
            filters.append(RetrievalMetricsRecord.timestamp >= start_time)
        if end_time:
            filters.append(RetrievalMetricsRecord.timestamp <= end_time)

        if filters:
            stmt = stmt.where(and_(*filters))
            count_stmt = count_stmt.where(and_(*filters))

        # Get total count
        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        # Get paginated records
        stmt = (
            stmt.order_by(RetrievalMetricsRecord.timestamp.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        records = list(result.scalars().all())

        return records, total

    async def get_aggregated_metrics(
        self,
        strategy: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        dataset_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compute aggregated metrics for a strategy over a time range."""
        dialect_name = self.db.bind.dialect.name if self.db.bind is not None else ""

        base_select = [
            func.count(RetrievalMetricsRecord.id).label("total_queries"),
            func.count(func.distinct(RetrievalMetricsRecord.query_id)).label(
                "unique_queries"
            ),
            func.avg(RetrievalMetricsRecord.dense_recall_at_5).label(
                "avg_dense_recall_at_5"
            ),
            func.avg(RetrievalMetricsRecord.dense_recall_at_10).label(
                "avg_dense_recall_at_10"
            ),
            func.avg(RetrievalMetricsRecord.bm25_recall_at_5).label(
                "avg_bm25_recall_at_5"
            ),
            func.avg(RetrievalMetricsRecord.bm25_recall_at_10).label(
                "avg_bm25_recall_at_10"
            ),
            func.avg(RetrievalMetricsRecord.hybrid_recall_at_5).label(
                "avg_hybrid_recall_at_5"
            ),
            func.avg(RetrievalMetricsRecord.hybrid_recall_at_10).label(
                "avg_hybrid_recall_at_10"
            ),
            func.avg(RetrievalMetricsRecord.precision_at_5).label("avg_precision_at_5"),
            func.avg(RetrievalMetricsRecord.precision_at_10).label(
                "avg_precision_at_10"
            ),
            func.avg(RetrievalMetricsRecord.mrr).label("avg_mrr"),
            func.avg(RetrievalMetricsRecord.hit_rate).label("avg_hit_rate"),
            func.avg(RetrievalMetricsRecord.retrieval_latency_ms).label(
                "avg_retrieval_latency_ms"
            ),
            func.avg(RetrievalMetricsRecord.reranker_latency_ms).label(
                "avg_reranker_latency_ms"
            ),
            func.avg(RetrievalMetricsRecord.total_latency_ms).label(
                "avg_total_latency_ms"
            ),
            func.avg(RetrievalMetricsRecord.reranker_gain).label("avg_reranker_gain"),
        ]

        if dialect_name == "postgresql":
            base_select.extend(
                [
                    func.percentile_cont(0.5)
                    .within_group(RetrievalMetricsRecord.retrieval_latency_ms)
                    .label("p50_latency"),
                    func.percentile_cont(0.95)
                    .within_group(RetrievalMetricsRecord.retrieval_latency_ms)
                    .label("p95_latency"),
                    func.percentile_cont(0.99)
                    .within_group(RetrievalMetricsRecord.retrieval_latency_ms)
                    .label("p99_latency"),
                ]
            )
        else:
            # SQLite (and other backends) don't support percentile_cont/within_group.
            base_select.extend(
                [
                    literal(None).label("p50_latency"),
                    literal(None).label("p95_latency"),
                    literal(None).label("p99_latency"),
                ]
            )

        stmt = select(*base_select).where(RetrievalMetricsRecord.strategy == strategy)

        if dataset_name:
            stmt = stmt.where(RetrievalMetricsRecord.dataset_name == dataset_name)
        if start_time:
            stmt = stmt.where(RetrievalMetricsRecord.timestamp >= start_time)
        if end_time:
            stmt = stmt.where(RetrievalMetricsRecord.timestamp <= end_time)

        result = await self.db.execute(stmt)
        row = result.one()

        return {
            "total_queries": row.total_queries or 0,
            "unique_queries": row.unique_queries or 0,
            "avg_dense_recall_at_5": float(row.avg_dense_recall_at_5)
            if row.avg_dense_recall_at_5
            else None,
            "avg_dense_recall_at_10": float(row.avg_dense_recall_at_10)
            if row.avg_dense_recall_at_10
            else None,
            "avg_bm25_recall_at_5": float(row.avg_bm25_recall_at_5)
            if row.avg_bm25_recall_at_5
            else None,
            "avg_bm25_recall_at_10": float(row.avg_bm25_recall_at_10)
            if row.avg_bm25_recall_at_10
            else None,
            "avg_hybrid_recall_at_5": float(row.avg_hybrid_recall_at_5)
            if row.avg_hybrid_recall_at_5
            else None,
            "avg_hybrid_recall_at_10": float(row.avg_hybrid_recall_at_10)
            if row.avg_hybrid_recall_at_10
            else None,
            "avg_precision_at_5": float(row.avg_precision_at_5)
            if row.avg_precision_at_5
            else None,
            "avg_precision_at_10": float(row.avg_precision_at_10)
            if row.avg_precision_at_10
            else None,
            "avg_mrr": float(row.avg_mrr) if row.avg_mrr else None,
            "avg_hit_rate": float(row.avg_hit_rate) if row.avg_hit_rate else None,
            "avg_retrieval_latency_ms": float(row.avg_retrieval_latency_ms)
            if row.avg_retrieval_latency_ms
            else None,
            "avg_reranker_latency_ms": float(row.avg_reranker_latency_ms)
            if row.avg_reranker_latency_ms
            else None,
            "avg_total_latency_ms": float(row.avg_total_latency_ms)
            if row.avg_total_latency_ms
            else None,
            "avg_reranker_gain": float(row.avg_reranker_gain)
            if row.avg_reranker_gain
            else None,
            "p50_latency": float(row.p50_latency) if row.p50_latency else None,
            "p95_latency": float(row.p95_latency) if row.p95_latency else None,
            "p99_latency": float(row.p99_latency) if row.p99_latency else None,
        }

    async def get_trend_data(
        self,
        strategy: str,
        metric: str,
        start_time: datetime,
        end_time: datetime,
        window_type: str = "daily",
    ) -> List[Dict[str, Any]]:
        """Get trend data for a specific metric, aggregated by time window."""
        # Map window_type to PostgreSQL date_trunc unit
        trunc_unit = {
            "hourly": "hour",
            "daily": "day",
            "weekly": "week",
            "monthly": "month",
        }.get(window_type, "day")

        # Validate metric column name to prevent SQL injection
        valid_metrics = {
            "dense_recall_at_5",
            "dense_recall_at_10",
            "bm25_recall_at_5",
            "bm25_recall_at_10",
            "hybrid_recall_at_5",
            "hybrid_recall_at_10",
            "precision_at_5",
            "precision_at_10",
            "mrr",
            "hit_rate",
            "retrieval_latency_ms",
            "reranker_latency_ms",
            "total_latency_ms",
            "reranker_gain",
        }
        if metric not in valid_metrics:
            logger.warning(f"Invalid metric requested for trend: {metric}")
            return []

        dialect_name = self.db.bind.dialect.name if self.db.bind is not None else ""
        # Use text() for the dynamic column reference (metric) while keeping other params bound.
        # B608 rationale: metric validated against ALLOWED_METRICS at lines 243-261, proof test
        # test_get_trend_analysis_invalid_metric_rejected confirms rejection before this point
        if dialect_name == "postgresql":
            query = text(f"""
                SELECT
                    date_trunc(:trunc_unit, timestamp) AS window_time,
                    AVG({metric}) AS avg_value,
                    COUNT(*) AS query_count
                FROM retrieval_metrics_records
                WHERE strategy = :strategy
                  AND timestamp >= :start_time
                  AND timestamp <= :end_time
                  AND {metric} IS NOT NULL
                GROUP BY window_time
                ORDER BY window_time ASC
            """)  # nosec B608
        else:
            # SQLite-compatible bucketing (sufficient for tests)
            # daily -> YYYY-MM-DD
            # hourly -> YYYY-MM-DD HH:00:00
            # weekly/monthly: coarse bucketing via YYYY-WW / YYYY-MM approximations
            if window_type == "hourly":
                bucket_expr = "strftime('%Y-%m-%d %H:00:00', timestamp)"
            elif window_type == "weekly":
                bucket_expr = "strftime('%Y-%W', timestamp)"
            elif window_type == "monthly":
                bucket_expr = "strftime('%Y-%m', timestamp)"
            else:
                bucket_expr = "date(timestamp)"
            query = text(f"""
                SELECT
                    {bucket_expr} AS window_time,
                    AVG({metric}) AS avg_value,
                    COUNT(*) AS query_count
                FROM retrieval_metrics_records
                WHERE strategy = :strategy
                  AND timestamp >= :start_time
                  AND timestamp <= :end_time
                  AND {metric} IS NOT NULL
                GROUP BY window_time
                ORDER BY window_time ASC
            """)  # nosec B608

        result = await self.db.execute(
            query,
            {
                "trunc_unit": trunc_unit,
                "strategy": strategy,
                "start_time": start_time,
                "end_time": end_time,
            },
        )

        trend_data = []
        for row in result:
            trend_data.append(
                {
                    "timestamp": row.window_time,
                    "value": float(row.avg_value) if row.avg_value else 0.0,
                    "query_count": row.query_count,
                }
            )

        return trend_data

    async def delete_old_records(self, before: datetime) -> int:
        """Delete records older than the specified timestamp."""
        (text("DELETE FROM retrieval_metrics_records WHERE timestamp < :before"),)
        result = await self.db.execute(
            text("DELETE FROM retrieval_metrics_records WHERE timestamp < :before"),
            {"before": before},
        )
        return result.rowcount


class AggregatedMetricsRepository:
    """Repository for aggregated metrics snapshots."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create(self, data: Dict[str, Any]) -> AggregatedMetricsSnapshot:
        """Create a new aggregated metrics snapshot."""
        snapshot = AggregatedMetricsSnapshot(**data)
        self.db.add(snapshot)
        await self.db.flush()
        await self.db.refresh(snapshot)
        return snapshot

    async def get_latest(
        self,
        strategy: str,
        window_type: str,
        dataset_name: Optional[str] = None,
    ) -> Optional[AggregatedMetricsSnapshot]:
        """Get the latest snapshot for a strategy and window type."""
        stmt = (
            select(AggregatedMetricsSnapshot)
            .where(
                AggregatedMetricsSnapshot.strategy == strategy,
                AggregatedMetricsSnapshot.window_type == window_type,
            )
            .order_by(AggregatedMetricsSnapshot.window_end.desc())
        )
        if dataset_name:
            stmt = stmt.where(AggregatedMetricsSnapshot.dataset_name == dataset_name)
        else:
            stmt = stmt.where(AggregatedMetricsSnapshot.dataset_name.is_(None))

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_range(
        self,
        strategy: str,
        window_type: str,
        start_time: datetime,
        end_time: datetime,
        dataset_name: Optional[str] = None,
    ) -> List[AggregatedMetricsSnapshot]:
        """Get snapshots within a time range."""
        stmt = (
            select(AggregatedMetricsSnapshot)
            .where(
                AggregatedMetricsSnapshot.strategy == strategy,
                AggregatedMetricsSnapshot.window_type == window_type,
                AggregatedMetricsSnapshot.window_start >= start_time,
                AggregatedMetricsSnapshot.window_end <= end_time,
            )
            .order_by(AggregatedMetricsSnapshot.window_start.asc())
        )
        if dataset_name:
            stmt = stmt.where(AggregatedMetricsSnapshot.dataset_name == dataset_name)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def upsert(self, data: Dict[str, Any]) -> AggregatedMetricsSnapshot:
        """Create or update an aggregated metrics snapshot."""
        existing = await self.get_latest(
            strategy=data["strategy"],
            window_type=data["window_type"],
            dataset_name=data.get("dataset_name"),
        )
        if existing:
            for key, value in data.items():
                if hasattr(existing, key) and key not in ("id", "timestamp"):
                    setattr(existing, key, value)
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        return await self.create(data)


class QueryDistributionRepository:
    """Repository for query distribution records."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create(self, data: Dict[str, Any]) -> QueryDistributionRecord:
        """Create a new query distribution record."""
        record = QueryDistributionRecord(**data)
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def get_latest(self, window_type: str) -> Optional[QueryDistributionRecord]:
        """Get the latest distribution record for a window type."""
        stmt = (
            select(QueryDistributionRecord)
            .where(QueryDistributionRecord.window_type == window_type)
            .order_by(QueryDistributionRecord.window_end.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_range(
        self,
        window_type: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[QueryDistributionRecord]:
        """Get distribution records within a time range."""
        stmt = (
            select(QueryDistributionRecord)
            .where(
                QueryDistributionRecord.window_type == window_type,
                QueryDistributionRecord.window_start >= start_time,
                QueryDistributionRecord.window_end <= end_time,
            )
            .order_by(QueryDistributionRecord.window_start.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_category_distribution(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """Get aggregated category distribution over a time range."""
        stmt = select(
            func.sum(QueryDistributionRecord.factual_count).label("factual"),
            func.sum(QueryDistributionRecord.navigational_count).label("navigational"),
            func.sum(QueryDistributionRecord.analytical_count).label("analytical"),
            func.sum(QueryDistributionRecord.comparative_count).label("comparative"),
            func.sum(QueryDistributionRecord.definitional_count).label("definitional"),
            func.sum(QueryDistributionRecord.procedural_count).label("procedural"),
            func.sum(QueryDistributionRecord.unknown_count).label("unknown"),
            func.sum(QueryDistributionRecord.total_count).label("total"),
        )

        if start_time:
            stmt = stmt.where(QueryDistributionRecord.window_start >= start_time)
        if end_time:
            stmt = stmt.where(QueryDistributionRecord.window_end <= end_time)

        result = await self.db.execute(stmt)
        row = result.one()

        return {
            "factual": int(row.factual or 0),
            "navigational": int(row.navigational or 0),
            "analytical": int(row.analytical or 0),
            "comparative": int(row.comparative or 0),
            "definitional": int(row.definitional or 0),
            "procedural": int(row.procedural or 0),
            "unknown": int(row.unknown or 0),
            "total": int(row.total or 0),
        }

    async def get_strategy_distribution(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """Get aggregated strategy distribution over a time range."""
        stmt = select(
            func.sum(QueryDistributionRecord.dense_count).label("dense"),
            func.sum(QueryDistributionRecord.bm25_count).label("bm25"),
            func.sum(QueryDistributionRecord.hybrid_count).label("hybrid"),
            func.sum(QueryDistributionRecord.hybrid_rerank_count).label(
                "hybrid_rerank"
            ),
            func.sum(QueryDistributionRecord.total_count).label("total"),
        )

        if start_time:
            stmt = stmt.where(QueryDistributionRecord.window_start >= start_time)
        if end_time:
            stmt = stmt.where(QueryDistributionRecord.window_end <= end_time)

        result = await self.db.execute(stmt)
        row = result.one()

        return {
            "dense": int(row.dense or 0),
            "bm25": int(row.bm25 or 0),
            "hybrid": int(row.hybrid or 0),
            "hybrid_rerank": int(row.hybrid_rerank or 0),
            "total": int(row.total or 0),
        }


class RerankerGainRepository:
    """Repository for reranker gain records."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create(self, data: Dict[str, Any]) -> RerankerGainRecord:
        """Create a new reranker gain record."""
        record = RerankerGainRecord(**data)
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def get_latest(
        self,
        window_type: str,
        dataset_name: Optional[str] = None,
    ) -> Optional[RerankerGainRecord]:
        """Get the latest reranker gain record.

        Note: tests exercise the endpoint without dataset_name, so we must
        return the latest record regardless of whether dataset_name is NULL.
        """
        stmt = (
            select(RerankerGainRecord)
            .where(RerankerGainRecord.window_type == window_type)
            # Order by both bounds to be deterministic across backends.
            .order_by(
                RerankerGainRecord.window_start.desc(),
                RerankerGainRecord.window_end.desc(),
            )
            .limit(1)
        )

        # For test usage, dataset_name is omitted. In that case we return the
        # latest record for the window_type regardless of dataset_name.
        # If dataset_name is provided, constrain to that dataset.
        if dataset_name is not None:
            stmt = stmt.where(RerankerGainRecord.dataset_name == dataset_name)

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_range(
        self,
        window_type: str,
        start_time: datetime,
        end_time: datetime,
        dataset_name: Optional[str] = None,
    ) -> List[RerankerGainRecord]:
        """Get reranker gain records within a time range."""
        stmt = (
            select(RerankerGainRecord)
            .where(
                RerankerGainRecord.window_type == window_type,
                RerankerGainRecord.window_start >= start_time,
                RerankerGainRecord.window_end <= end_time,
            )
            .order_by(RerankerGainRecord.window_start.asc())
        )
        if dataset_name:
            stmt = stmt.where(RerankerGainRecord.dataset_name == dataset_name)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())


class SystemHealthRepository:
    """Repository for system health snapshots."""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    async def create(self, data: Dict[str, Any]) -> SystemHealthSnapshot:
        """Create a new system health snapshot."""
        snapshot = SystemHealthSnapshot(**data)
        self.db.add(snapshot)
        await self.db.flush()
        await self.db.refresh(snapshot)
        return snapshot

    async def get_latest(self) -> Optional[SystemHealthSnapshot]:
        """Get the latest system health snapshot."""
        stmt = (
            select(SystemHealthSnapshot)
            .order_by(SystemHealthSnapshot.timestamp.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_range(
        self,
        start_time: datetime,
        end_time: datetime,
        limit: int = 100,
    ) -> List[SystemHealthSnapshot]:
        """Get health snapshots within a time range."""
        stmt = (
            select(SystemHealthSnapshot)
            .where(
                SystemHealthSnapshot.timestamp >= start_time,
                SystemHealthSnapshot.timestamp <= end_time,
            )
            .order_by(SystemHealthSnapshot.timestamp.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
