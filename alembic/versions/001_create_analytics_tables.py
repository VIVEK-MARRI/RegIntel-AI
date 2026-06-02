"""Create analytics tables for Retrieval Analytics Platform.

Revision ID: 001_create_analytics_tables
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_create_analytics_tables"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create retrieval_metrics_records table
    op.create_table(
        "retrieval_metrics_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("query_id", sa.String(255), nullable=False, index=True),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("query_category", sa.String(50), nullable=False, server_default="unknown"),
        sa.Column("strategy", sa.String(50), nullable=False, index=True),
        sa.Column("dataset_name", sa.String(255), nullable=True, index=True),
        sa.Column("dense_recall_at_5", sa.Float, nullable=True),
        sa.Column("dense_recall_at_10", sa.Float, nullable=True),
        sa.Column("bm25_recall_at_5", sa.Float, nullable=True),
        sa.Column("bm25_recall_at_10", sa.Float, nullable=True),
        sa.Column("hybrid_recall_at_5", sa.Float, nullable=True),
        sa.Column("hybrid_recall_at_10", sa.Float, nullable=True),
        sa.Column("precision_at_5", sa.Float, nullable=True),
        sa.Column("precision_at_10", sa.Float, nullable=True),
        sa.Column("mrr", sa.Float, nullable=True),
        sa.Column("hit_rate", sa.Float, nullable=True),
        sa.Column("retrieval_latency_ms", sa.Float, nullable=True),
        sa.Column("reranker_latency_ms", sa.Float, nullable=True),
        sa.Column("total_latency_ms", sa.Float, nullable=True),
        sa.Column("reranker_gain", sa.Float, nullable=True),
        sa.Column("results_returned", sa.Integer, nullable=True),
        sa.Column("relevant_count", sa.Integer, nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_rmr_strategy_timestamp", "retrieval_metrics_records", ["strategy", "timestamp"])
    op.create_index("idx_rmr_dataset_strategy", "retrieval_metrics_records", ["dataset_name", "strategy"])
    op.create_index("idx_rmr_query_category", "retrieval_metrics_records", ["query_category"])

    # Create aggregated_metrics_snapshots table
    op.create_table(
        "aggregated_metrics_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("window_type", sa.String(20), nullable=False, index=True),
        sa.Column("strategy", sa.String(50), nullable=False, index=True),
        sa.Column("dataset_name", sa.String(255), nullable=True),
        sa.Column("avg_dense_recall_at_5", sa.Float, nullable=True),
        sa.Column("avg_dense_recall_at_10", sa.Float, nullable=True),
        sa.Column("avg_bm25_recall_at_5", sa.Float, nullable=True),
        sa.Column("avg_bm25_recall_at_10", sa.Float, nullable=True),
        sa.Column("avg_hybrid_recall_at_5", sa.Float, nullable=True),
        sa.Column("avg_hybrid_recall_at_10", sa.Float, nullable=True),
        sa.Column("avg_precision_at_5", sa.Float, nullable=True),
        sa.Column("avg_precision_at_10", sa.Float, nullable=True),
        sa.Column("avg_mrr", sa.Float, nullable=True),
        sa.Column("avg_hit_rate", sa.Float, nullable=True),
        sa.Column("avg_retrieval_latency_ms", sa.Float, nullable=True),
        sa.Column("p50_retrieval_latency_ms", sa.Float, nullable=True),
        sa.Column("p95_retrieval_latency_ms", sa.Float, nullable=True),
        sa.Column("p99_retrieval_latency_ms", sa.Float, nullable=True),
        sa.Column("avg_reranker_latency_ms", sa.Float, nullable=True),
        sa.Column("avg_total_latency_ms", sa.Float, nullable=True),
        sa.Column("avg_reranker_gain", sa.Float, nullable=True),
        sa.Column("total_queries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unique_queries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_ams_window_strategy", "aggregated_metrics_snapshots", ["window_type", "strategy"])
    op.create_index("idx_ams_window_range", "aggregated_metrics_snapshots", ["window_start", "window_end"])
    op.create_unique_constraint(
        "uq_ams_window_strategy_dataset",
        "aggregated_metrics_snapshots",
        ["window_type", "strategy", "window_start", "dataset_name"],
    )

    # Create query_distribution_records table
    op.create_table(
        "query_distribution_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_type", sa.String(20), nullable=False, index=True),
        sa.Column("factual_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("navigational_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("analytical_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("comparative_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("definitional_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("procedural_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unknown_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dense_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bm25_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("hybrid_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("hybrid_rerank_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_query_length", sa.Float, nullable=True),
        sa.Column("avg_result_count", sa.Float, nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_qdr_window_type_timestamp", "query_distribution_records", ["window_type", "timestamp"])
    op.create_unique_constraint(
        "uq_qdr_window",
        "query_distribution_records",
        ["window_type", "window_start"],
    )

    # Create reranker_gain_records table
    op.create_table(
        "reranker_gain_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_type", sa.String(20), nullable=False, index=True),
        sa.Column("dataset_name", sa.String(255), nullable=True),
        sa.Column("avg_recall_gain_at_5", sa.Float, nullable=True),
        sa.Column("avg_recall_gain_at_10", sa.Float, nullable=True),
        sa.Column("avg_precision_gain_at_5", sa.Float, nullable=True),
        sa.Column("avg_mrr_gain", sa.Float, nullable=True),
        sa.Column("avg_hit_rate_gain", sa.Float, nullable=True),
        sa.Column("avg_reranker_latency_ms", sa.Float, nullable=True),
        sa.Column("reranker_queries_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("improvement_rate", sa.Float, nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_rgr_window_type_timestamp", "reranker_gain_records", ["window_type", "timestamp"])
    op.create_unique_constraint(
        "uq_rgr_window_dataset",
        "reranker_gain_records",
        ["window_type", "window_start", "dataset_name"],
    )

    # Create system_health_snapshots table
    op.create_table(
        "system_health_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="healthy", index=True),
        sa.Column("dense_retrieval_available", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("bm25_retrieval_available", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("hybrid_retrieval_available", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("reranker_available", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("index_consistency", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("embedding_coverage_pct", sa.Float, nullable=True),
        sa.Column("total_indexed_chunks", sa.Integer, nullable=True),
        sa.Column("avg_latency_last_hour_ms", sa.Float, nullable=True),
        sa.Column("queries_last_hour", sa.Integer, nullable=True),
        sa.Column("error_rate_last_hour", sa.Float, nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("idx_shs_status_timestamp", "system_health_snapshots", ["status", "timestamp"])


def downgrade() -> None:
    op.drop_table("system_health_snapshots")
    op.drop_table("reranker_gain_records")
    op.drop_table("query_distribution_records")
    op.drop_table("aggregated_metrics_snapshots")
    op.drop_table("retrieval_metrics_records")