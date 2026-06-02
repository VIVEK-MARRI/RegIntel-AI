"""Tests for analytics database models."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.analytics import (
    AggregatedMetricsSnapshot,
    QueryDistributionRecord,
    RetrievalMetricsRecord,
    RerankerGainRecord,
    SystemHealthSnapshot,
)


@pytest.mark.asyncio
class TestRetrievalMetricsRecord:
    """Tests for RetrievalMetricsRecord model."""

    async def test_create_record(self, db_session):
        """Test creating a retrieval metrics record."""
        record = RetrievalMetricsRecord(
            query_id=str(uuid.uuid4()),
            query_text="Test query",
            query_category="factual",
            strategy="dense",
            dataset_name="test_dataset",
            dense_recall_at_5=0.75,
            dense_recall_at_10=0.85,
            precision_at_5=0.70,
            mrr=0.80,
            hit_rate=1.0,
            retrieval_latency_ms=45.0,
            reranker_gain=0.05,
            results_returned=10,
            relevant_count=8,
        )
        db_session.add(record)
        await db_session.flush()
        await db_session.refresh(record)

        assert record.id is not None
        assert record.query_text == "Test query"
        assert record.strategy == "dense"
        assert record.dense_recall_at_5 == 0.75
        assert record.retrieval_latency_ms == 45.0

    async def test_nullable_fields(self, db_session):
        """Test that nullable fields can be None."""
        record = RetrievalMetricsRecord(
            query_id=str(uuid.uuid4()),
            query_text="Minimal query",
            strategy="bm25",
        )
        db_session.add(record)
        await db_session.flush()
        await db_session.refresh(record)

        assert record.dense_recall_at_5 is None
        assert record.reranker_gain is None
        assert record.metadata_json == {}

    async def test_default_values(self, db_session):
        """Test default values are set correctly."""
        record = RetrievalMetricsRecord(
            query_id=str(uuid.uuid4()),
            query_text="Default test",
            strategy="hybrid",
        )
        db_session.add(record)
        await db_session.flush()
        await db_session.refresh(record)

        assert record.query_category == "unknown"
        assert record.metadata_json == {}
        assert record.timestamp is not None

    async def test_query_by_strategy(self, db_session):
        """Test querying records by strategy."""
        for strategy in ["dense", "bm25", "dense"]:
            record = RetrievalMetricsRecord(
                query_id=str(uuid.uuid4()),
                query_text=f"Query for {strategy}",
                strategy=strategy,
            )
            db_session.add(record)
        await db_session.flush()

        stmt = select(RetrievalMetricsRecord).where(
            RetrievalMetricsRecord.strategy == "dense"
        )
        result = await db_session.execute(stmt)
        records = list(result.scalars().all())

        assert len(records) == 2


@pytest.mark.asyncio
class TestAggregatedMetricsSnapshot:
    """Tests for AggregatedMetricsSnapshot model."""

    async def test_create_snapshot(self, db_session):
        """Test creating an aggregated metrics snapshot."""
        now = datetime.now(timezone.utc)
        snapshot = AggregatedMetricsSnapshot(
            window_start=now,
            window_end=now,
            window_type="daily",
            strategy="dense",
            dataset_name="test_dataset",
            avg_dense_recall_at_5=0.75,
            avg_mrr=0.80,
            avg_retrieval_latency_ms=45.0,
            total_queries=100,
            unique_queries=95,
        )
        db_session.add(snapshot)
        await db_session.flush()
        await db_session.refresh(snapshot)

        assert snapshot.id is not None
        assert snapshot.window_type == "daily"
        assert snapshot.total_queries == 100

    async def test_unique_constraint(self, db_session):
        """Test unique constraint on window_type, strategy, window_start, dataset_name."""
        now = datetime.now(timezone.utc)
        snapshot1 = AggregatedMetricsSnapshot(
            window_start=now,
            window_end=now,
            window_type="daily",
            strategy="dense",
            dataset_name="test_dataset",
            total_queries=10,
        )
        db_session.add(snapshot1)
        await db_session.flush()

        # Same constraint values should fail
        snapshot2 = AggregatedMetricsSnapshot(
            window_start=now,
            window_end=now,
            window_type="daily",
            strategy="dense",
            dataset_name="test_dataset",
            total_queries=20,
        )
        db_session.add(snapshot2)
        with pytest.raises(Exception):
            await db_session.flush()


@pytest.mark.asyncio
class TestQueryDistributionRecord:
    """Tests for QueryDistributionRecord model."""

    async def test_create_distribution_record(self, db_session):
        """Test creating a query distribution record."""
        now = datetime.now(timezone.utc)
        record = QueryDistributionRecord(
            window_start=now,
            window_end=now,
            window_type="daily",
            factual_count=50,
            navigational_count=20,
            analytical_count=15,
            comparative_count=10,
            definitional_count=5,
            procedural_count=0,
            unknown_count=0,
            total_count=100,
            dense_count=30,
            bm25_count=25,
            hybrid_count=25,
            hybrid_rerank_count=20,
            avg_query_length=12.5,
            avg_result_count=8.0,
        )
        db_session.add(record)
        await db_session.flush()
        await db_session.refresh(record)

        assert record.id is not None
        assert record.total_count == 100
        assert record.factual_count == 50
        assert record.avg_query_length == 12.5


@pytest.mark.asyncio
class TestRerankerGainRecord:
    """Tests for RerankerGainRecord model."""

    async def test_create_reranker_gain_record(self, db_session):
        """Test creating a reranker gain record."""
        now = datetime.now(timezone.utc)
        record = RerankerGainRecord(
            window_start=now,
            window_end=now,
            window_type="daily",
            dataset_name="test_dataset",
            avg_recall_gain_at_5=0.05,
            avg_recall_gain_at_10=0.03,
            avg_precision_gain_at_5=0.04,
            avg_mrr_gain=0.06,
            avg_hit_rate_gain=0.02,
            avg_reranker_latency_ms=120.0,
            reranker_queries_count=100,
            improvement_rate=0.75,
        )
        db_session.add(record)
        await db_session.flush()
        await db_session.refresh(record)

        assert record.id is not None
        assert record.avg_recall_gain_at_5 == 0.05
        assert record.improvement_rate == 0.75
        assert record.reranker_queries_count == 100


@pytest.mark.asyncio
class TestSystemHealthSnapshot:
    """Tests for SystemHealthSnapshot model."""

    async def test_create_health_snapshot(self, db_session):
        """Test creating a system health snapshot."""
        snapshot = SystemHealthSnapshot(
            status="healthy",
            dense_retrieval_available=True,
            bm25_retrieval_available=True,
            hybrid_retrieval_available=True,
            reranker_available=True,
            index_consistency=True,
            embedding_coverage_pct=95.5,
            total_indexed_chunks=1000,
            avg_latency_last_hour_ms=50.0,
            queries_last_hour=500,
            error_rate_last_hour=0.01,
        )
        db_session.add(snapshot)
        await db_session.flush()
        await db_session.refresh(snapshot)

        assert snapshot.id is not None
        assert snapshot.status == "healthy"
        assert snapshot.embedding_coverage_pct == 95.5
        assert snapshot.dense_retrieval_available is True

    async def test_default_status(self, db_session):
        """Test default status is 'healthy'."""
        snapshot = SystemHealthSnapshot()
        db_session.add(snapshot)
        await db_session.flush()
        await db_session.refresh(snapshot)

        assert snapshot.status == "healthy"
        assert snapshot.dense_retrieval_available is True
        assert snapshot.index_consistency is True