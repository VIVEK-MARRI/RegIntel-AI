"""Pydantic schemas for the Retrieval Analytics Platform.

Request/response models for analytics APIs, including metrics queries,
trend analysis, performance summaries, and reporting.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─── Metric Record Schemas ───────────────────────────────────────────────────

class RetrievalMetricsCreate(BaseModel):
    """Schema for recording a single query's retrieval metrics."""
    query_id: str = Field(..., description="Unique query identifier.")
    query_text: str = Field(..., description="The search query text.")
    query_category: str = Field(default="unknown", description="Query category.")
    strategy: str = Field(..., description="Retrieval strategy used.")
    dataset_name: Optional[str] = Field(None, description="Dataset name if from evaluation.")
    dense_recall_at_5: Optional[float] = Field(None, ge=0.0, le=1.0)
    dense_recall_at_10: Optional[float] = Field(None, ge=0.0, le=1.0)
    bm25_recall_at_5: Optional[float] = Field(None, ge=0.0, le=1.0)
    bm25_recall_at_10: Optional[float] = Field(None, ge=0.0, le=1.0)
    hybrid_recall_at_5: Optional[float] = Field(None, ge=0.0, le=1.0)
    hybrid_recall_at_10: Optional[float] = Field(None, ge=0.0, le=1.0)
    precision_at_5: Optional[float] = Field(None, ge=0.0, le=1.0)
    precision_at_10: Optional[float] = Field(None, ge=0.0, le=1.0)
    mrr: Optional[float] = Field(None, ge=0.0, le=1.0)
    hit_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    retrieval_latency_ms: Optional[float] = Field(None, ge=0.0)
    reranker_latency_ms: Optional[float] = Field(None, ge=0.0)
    total_latency_ms: Optional[float] = Field(None, ge=0.0)
    reranker_gain: Optional[float] = Field(None)
    results_returned: Optional[int] = Field(None, ge=0)
    relevant_count: Optional[int] = Field(None, ge=0)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class RetrievalMetricsResponse(BaseModel):
    """Response schema for a retrieval metrics record."""
    id: uuid.UUID | str
    timestamp: datetime
    query_id: str
    query_text: str
    query_category: str
    strategy: str
    dataset_name: Optional[str]
    dense_recall_at_5: Optional[float]
    dense_recall_at_10: Optional[float]
    bm25_recall_at_5: Optional[float]
    bm25_recall_at_10: Optional[float]
    hybrid_recall_at_5: Optional[float]
    hybrid_recall_at_10: Optional[float]
    precision_at_5: Optional[float]
    precision_at_10: Optional[float]
    mrr: Optional[float]
    hit_rate: Optional[float]
    retrieval_latency_ms: Optional[float]
    reranker_latency_ms: Optional[float]
    total_latency_ms: Optional[float]
    reranker_gain: Optional[float]
    results_returned: Optional[int]
    relevant_count: Optional[int]
    metadata_json: Dict[str, Any]

    model_config = {"from_attributes": True}


# ─── Aggregated Metrics Schemas ──────────────────────────────────────────────

class AggregatedMetricsResponse(BaseModel):
    """Response schema for aggregated metrics snapshot."""
    id: str
    timestamp: datetime
    window_start: datetime
    window_end: datetime
    window_type: str
    strategy: str
    dataset_name: Optional[str]
    avg_dense_recall_at_5: Optional[float]
    avg_dense_recall_at_10: Optional[float]
    avg_bm25_recall_at_5: Optional[float]
    avg_bm25_recall_at_10: Optional[float]
    avg_hybrid_recall_at_5: Optional[float]
    avg_hybrid_recall_at_10: Optional[float]
    avg_precision_at_5: Optional[float]
    avg_precision_at_10: Optional[float]
    avg_mrr: Optional[float]
    avg_hit_rate: Optional[float]
    avg_retrieval_latency_ms: Optional[float]
    p50_retrieval_latency_ms: Optional[float]
    p95_retrieval_latency_ms: Optional[float]
    p99_retrieval_latency_ms: Optional[float]
    avg_reranker_latency_ms: Optional[float]
    avg_total_latency_ms: Optional[float]
    avg_reranker_gain: Optional[float]
    total_queries: int
    unique_queries: int
    metadata_json: Dict[str, Any]

    model_config = {"from_attributes": True}


# ─── Query Distribution Schemas ──────────────────────────────────────────────

class QueryDistributionResponse(BaseModel):
    """Response schema for query distribution record."""
    id: str
    timestamp: datetime
    window_start: datetime
    window_end: datetime
    window_type: str
    factual_count: int
    navigational_count: int
    analytical_count: int
    comparative_count: int
    definitional_count: int
    procedural_count: int
    unknown_count: int
    total_count: int
    dense_count: int
    bm25_count: int
    hybrid_count: int
    hybrid_rerank_count: int
    avg_query_length: Optional[float]
    avg_result_count: Optional[float]
    metadata_json: Dict[str, Any]

    model_config = {"from_attributes": True}


class QueryDistributionSummary(BaseModel):
    """Summary of query distribution across categories and strategies."""
    window_type: str
    window_start: datetime
    window_end: datetime
    total_queries: int
    category_distribution: Dict[str, int] = Field(
        ..., description="Query counts by category."
    )
    strategy_distribution: Dict[str, int] = Field(
        ..., description="Query counts by strategy."
    )
    category_percentages: Dict[str, float] = Field(
        ..., description="Percentage of queries per category."
    )
    strategy_percentages: Dict[str, float] = Field(
        ..., description="Percentage of queries per strategy."
    )
    avg_query_length: Optional[float] = None
    avg_result_count: Optional[float] = None


# ─── Reranker Gain Schemas ───────────────────────────────────────────────────

class RerankerGainResponse(BaseModel):
    """Response schema for reranker gain record."""
    # Accept UUID (DB) or str (API). We always serialize back to str.
    id: uuid.UUID | str

    timestamp: datetime
    window_start: datetime
    window_end: datetime
    window_type: str
    dataset_name: Optional[str]
    avg_recall_gain_at_5: Optional[float]
    avg_recall_gain_at_10: Optional[float]
    avg_precision_gain_at_5: Optional[float]
    avg_mrr_gain: Optional[float]
    avg_hit_rate_gain: Optional[float]
    avg_reranker_latency_ms: Optional[float]
    reranker_queries_count: int
    improvement_rate: Optional[float]
    metadata_json: Dict[str, Any]

    model_config = {"from_attributes": True}


# ─── System Health Schemas ───────────────────────────────────────────────────

class SystemHealthResponse(BaseModel):
    """Response schema for system health snapshot."""
    # Accept UUID (DB) or str (API). Serialized back to str on output.
    id: uuid.UUID | str
    timestamp: datetime
    status: str
    dense_retrieval_available: bool
    bm25_retrieval_available: bool
    hybrid_retrieval_available: bool
    reranker_available: bool
    index_consistency: bool
    embedding_coverage_pct: Optional[float]
    total_indexed_chunks: Optional[int]
    avg_latency_last_hour_ms: Optional[float]
    queries_last_hour: Optional[int]
    error_rate_last_hour: Optional[float]
    metadata_json: Dict[str, Any]

    model_config = {"from_attributes": True}


# ─── Trend Analysis Schemas ──────────────────────────────────────────────────

class TrendDataPoint(BaseModel):
    """Single data point in a trend series."""
    timestamp: datetime
    value: float
    label: Optional[str] = None


class TrendSeries(BaseModel):
    """A named trend series with data points."""
    metric_name: str
    strategy: Optional[str] = None
    data_points: List[TrendDataPoint]
    trend_direction: Optional[str] = Field(
        None, description="Direction of trend: 'improving', 'degrading', 'stable'."
    )
    trend_slope: Optional[float] = Field(
        None, description="Linear regression slope of the trend."
    )


class TrendAnalysisResponse(BaseModel):
    """Response schema for trend analysis."""
    metric_name: str
    window_type: str
    start_time: datetime
    end_time: datetime
    series: List[TrendSeries]
    summary: Dict[str, Any] = Field(
        default_factory=dict, description="Summary statistics for the trend."
    )


# ─── Performance Summary Schemas ─────────────────────────────────────────────

class StrategyPerformance(BaseModel):
    """Performance summary for a single retrieval strategy."""
    strategy: str
    avg_dense_recall_at_5: Optional[float] = None
    avg_dense_recall_at_10: Optional[float] = None
    avg_bm25_recall_at_5: Optional[float] = None
    avg_bm25_recall_at_10: Optional[float] = None
    avg_hybrid_recall_at_5: Optional[float] = None
    avg_hybrid_recall_at_10: Optional[float] = None
    avg_precision_at_5: Optional[float] = None
    avg_precision_at_10: Optional[float] = None
    avg_mrr: Optional[float] = None
    avg_hit_rate: Optional[float] = None
    avg_retrieval_latency_ms: Optional[float] = None
    p95_retrieval_latency_ms: Optional[float] = None
    avg_reranker_gain: Optional[float] = None
    total_queries: int = 0
    composite_score: Optional[float] = None


class PerformanceSummaryResponse(BaseModel):
    """Comprehensive performance summary across all strategies."""
    window_type: str
    window_start: datetime
    window_end: datetime
    dataset_name: Optional[str]
    strategies: List[StrategyPerformance]
    best_strategy: Optional[str] = Field(
        None, description="Strategy with the highest composite score."
    )
    total_queries: int
    overall_avg_latency_ms: Optional[float] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Query Filter Schemas ────────────────────────────────────────────────────

class MetricsQueryFilter(BaseModel):
    """Filter parameters for querying metrics."""
    strategy: Optional[str] = None
    dataset_name: Optional[str] = None
    query_category: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    window_type: Optional[str] = Field(
        None, description="Aggregation window: 'hourly', 'daily', 'weekly', 'monthly'."
    )
    limit: int = Field(default=100, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""
    total: int
    limit: int
    offset: int
    items: List[Any]


# ─── Comparison Schemas ──────────────────────────────────────────────────────

class StrategyComparisonResponse(BaseModel):
    """Comparison of metrics across strategies."""
    metric_name: str
    window_type: str
    start_time: datetime
    end_time: datetime
    comparisons: Dict[str, Optional[Dict[str, Any]]] = Field(
        ..., description="Strategy name -> {value, change_pct, trend}."
    )
    winner: Optional[str] = Field(
        None, description="Strategy with the best value for the given metric."
    )


# ─── Report Schemas ──────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    """Request schema for generating analytics reports."""
    window_type: str = Field(default="daily", description="Time window for aggregation.")
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    strategies: Optional[List[str]] = Field(None, description="Strategies to include.")
    dataset_name: Optional[str] = None
    include_trends: bool = Field(default=True)
    include_query_distribution: bool = Field(default=True)
    include_reranker_gain: bool = Field(default=True)
    include_system_health: bool = Field(default=True)


class AnalyticsReportResponse(BaseModel):
    """Complete analytics report."""
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    window_type: str
    window_start: datetime
    window_end: datetime
    dataset_name: Optional[str]
    performance_summary: PerformanceSummaryResponse
    trends: Optional[Dict[str, TrendAnalysisResponse]] = None
    query_distribution: Optional[QueryDistributionSummary] = None
    reranker_gain: Optional[RerankerGainResponse] = None
    system_health: Optional[SystemHealthResponse] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)