"""Database models for the Retrieval Analytics Platform.

Stores historical retrieval metrics, query distribution data,
reranker gain measurements, and system health snapshots.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.document import Base
from app.models.types import PortableJSON


class RetrievalStrategyEnum(str, PyEnum):
    """Retrieval strategy types tracked by analytics."""

    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


class QueryCategoryEnum(str, PyEnum):
    """Categories for query distribution tracking."""

    FACTUAL = "factual"
    NAVIGATIONAL = "navigational"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    DEFINITIONAL = "definitional"
    PROCEDURAL = "procedural"
    UNKNOWN = "unknown"


class RetrievalMetricsRecord(Base):
    """Stores per-query retrieval metrics for historical analysis.

    Each row represents a single query evaluation against a specific
    retrieval strategy, capturing recall, precision, MRR, hit rate,
    and latency measurements.
    """

    __tablename__ = "retrieval_metrics_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    query_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_category: Mapped[str] = mapped_column(
        String(50), default=QueryCategoryEnum.UNKNOWN.value, nullable=False
    )
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    dataset_name: Mapped[str] = mapped_column(String(255), nullable=True, index=True)

    # Recall metrics
    dense_recall_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    dense_recall_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    bm25_recall_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    bm25_recall_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    hybrid_recall_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    hybrid_recall_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Precision metrics
    precision_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Ranking metrics
    mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Latency
    retrieval_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    reranker_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Reranker gain
    reranker_gain: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Result counts
    results_returned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relevant_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Metadata
    metadata_json: Mapped[dict] = mapped_column(
        PortableJSON(), nullable=False, default=dict
    )

    __table_args__ = (
        Index("idx_rmr_strategy_timestamp", "strategy", "timestamp"),
        Index("idx_rmr_dataset_strategy", "dataset_name", "strategy"),
        Index("idx_rmr_query_category", "query_category"),
    )


class AggregatedMetricsSnapshot(Base):
    """Pre-computed aggregated metrics over time windows.

    Used for fast dashboard queries and trend analysis without
    computing aggregates on-the-fly from raw records.
    """

    __tablename__ = "aggregated_metrics_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    window_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # "hourly", "daily", "weekly", "monthly"
    strategy: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    dataset_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Aggregated recall
    avg_dense_recall_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_dense_recall_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_bm25_recall_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_bm25_recall_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hybrid_recall_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hybrid_recall_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Aggregated precision
    avg_precision_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_precision_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Aggregated ranking
    avg_mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Aggregated latency
    avg_retrieval_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50_retrieval_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p95_retrieval_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p99_retrieval_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_reranker_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_total_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Reranker gain
    avg_reranker_gain: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Query counts
    total_queries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unique_queries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Metadata
    metadata_json: Mapped[dict] = mapped_column(
        PortableJSON(), nullable=False, default=dict
    )

    __table_args__ = (
        UniqueConstraint(
            "window_type",
            "strategy",
            "window_start",
            "dataset_name",
            name="uq_ams_window_strategy_dataset",
        ),
        Index("idx_ams_window_strategy", "window_type", "strategy"),
        Index("idx_ams_window_range", "window_start", "window_end"),
    )


class QueryDistributionRecord(Base):
    """Tracks query distribution patterns over time.

    Captures the volume and categorization of queries to identify
    usage patterns and optimize retrieval strategies accordingly.
    """

    __tablename__ = "query_distribution_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Query counts by category
    factual_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    navigational_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    analytical_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comparative_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    definitional_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    procedural_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Query counts by strategy
    dense_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bm25_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hybrid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hybrid_rerank_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Average query characteristics
    avg_query_length: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_result_count: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Metadata
    metadata_json: Mapped[dict] = mapped_column(
        PortableJSON(), nullable=False, default=dict
    )

    __table_args__ = (
        UniqueConstraint(
            "window_type",
            "window_start",
            name="uq_qdr_window",
        ),
        Index("idx_qdr_window_type_timestamp", "window_type", "timestamp"),
    )


class RerankerGainRecord(Base):
    """Tracks reranker improvement metrics over time.

    Measures how much the reranker improves retrieval quality
    compared to the base retrieval strategy.
    """

    __tablename__ = "reranker_gain_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    dataset_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Gain metrics (reranker vs base)
    avg_recall_gain_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_recall_gain_at_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_precision_gain_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_mrr_gain: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hit_rate_gain: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Reranker performance
    avg_reranker_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    reranker_queries_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    # Improvement rate
    improvement_rate: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        help_text="Fraction of queries where reranker improved results",
    )

    # Metadata
    metadata_json: Mapped[dict] = mapped_column(
        PortableJSON(), nullable=False, default=dict
    )

    __table_args__ = (
        UniqueConstraint(
            "window_type",
            "window_start",
            "dataset_name",
            name="uq_rgr_window_dataset",
        ),
        Index("idx_rgr_window_type_timestamp", "window_type", "timestamp"),
    )


class SystemHealthSnapshot(Base):
    """System health and performance snapshots for monitoring.

    Captures overall system health indicators at regular intervals.
    """

    __tablename__ = "system_health_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Overall system status
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="healthy", index=True
    )  # "healthy", "degraded", "unhealthy"

    # Retrieval system health
    dense_retrieval_available: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    bm25_retrieval_available: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    hybrid_retrieval_available: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    reranker_available: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    # Index health
    index_consistency: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    embedding_coverage_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_indexed_chunks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Performance summary
    avg_latency_last_hour_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    queries_last_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_rate_last_hour: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Metadata
    metadata_json: Mapped[dict] = mapped_column(
        PortableJSON(), nullable=False, default=dict
    )

    __table_args__ = (Index("idx_shs_status_timestamp", "status", "timestamp"),)
