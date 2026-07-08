"""Pydantic schemas for the BGE Reranking Engine.

Defines request/response models and diagnostic reporting for cross-encoder
reranking of retrieval candidates.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RerankCandidate(BaseModel):
    """A single candidate chunk to be reranked."""

    chunk_id: str = Field(..., description="UUID of the candidate chunk.")
    content: str = Field(..., description="Text content of the candidate chunk.")
    score: Optional[float] = Field(
        None, description="Original retrieval score (dense or fusion)."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Metadata from the retrieval stage."
    )


class RerankResult(BaseModel):
    """A single reranked chunk with cross-encoder relevance score."""

    chunk_id: str = Field(..., description="UUID of the reranked chunk.")
    rerank_score: float = Field(
        ..., description="Cross-encoder relevance score (higher = more relevant)."
    )
    original_score: Optional[float] = Field(
        None, description="Score from the initial retrieval stage."
    )
    original_rank: Optional[int] = Field(
        None, description="1-indexed rank before reranking."
    )
    new_rank: Optional[int] = Field(None, description="1-indexed rank after reranking.")
    content: str = Field("", description="Text content of the chunk.")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Metadata associated with the chunk."
    )


class RerankRequest(BaseModel):
    """Request schema for the reranking endpoint."""

    query: str = Field(..., description="The user query to score candidates against.")
    candidates: List[RerankCandidate] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Candidate chunks to rerank.",
    )
    top_k: int = Field(
        5, ge=1, le=100, description="Number of top results to return after reranking."
    )
    score_threshold: float = Field(
        0.0, description="Minimum reranker score to include a result."
    )


class RerankResponse(BaseModel):
    """Response schema for the reranking endpoint."""

    query: str = Field(
        ..., description="The query that candidates were reranked against."
    )
    results: List[RerankResult] = Field(
        default_factory=list, description="Top-K reranked results."
    )
    report: "RerankReport" = Field(
        ..., description="Diagnostic metrics for the reranking operation."
    )


class ScoreDistribution(BaseModel):
    """Histogram-style score distribution for reranking diagnostics."""

    bins: List[float] = Field(
        default_factory=list, description="Score bin edges [0.0, 0.1, 0.2, ...]."
    )
    counts: List[int] = Field(
        default_factory=list, description="Count of scores falling in each bin."
    )
    median: Optional[float] = Field(None, description="Median reranker score.")
    std_dev: Optional[float] = Field(
        None, description="Standard deviation of reranker scores."
    )
    p25: Optional[float] = Field(None, description="25th percentile score.")
    p75: Optional[float] = Field(None, description="75th percentile score.")


class PrecisionMetrics(BaseModel):
    """Precision improvement metrics comparing pre- and post-reranking."""

    rank_correlation: Optional[float] = Field(
        None,
        description="Spearman rank correlation between original and rerank scores.",
    )
    avg_score_lift: Optional[float] = Field(
        None, description="Average score increase for top-k results vs candidates."
    )
    top1_improvement: Optional[float] = Field(
        None, description="Score improvement of the #1 result vs the original #1."
    )
    rank_changes: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of chunks whose rank changed: {'improved': N, 'declined': N, 'unchanged': N}.",
    )


class RerankReport(BaseModel):
    """Diagnostic report emitted after each reranking operation."""

    model_name: str = Field(..., description="Name of the reranker model used.")
    candidates_received: int = Field(
        0, description="Number of candidates submitted for reranking."
    )
    candidates_returned: int = Field(
        0, description="Number of candidates after top-k and threshold filtering."
    )
    candidates_filtered: int = Field(
        0, description="Number of candidates removed by score threshold."
    )
    latency_ms: float = Field(
        0.0, description="Total wall-clock reranking latency in milliseconds."
    )
    scoring_latency_ms: float = Field(
        0.0, description="Time spent in model inference only."
    )
    score_min: Optional[float] = Field(
        None, description="Minimum reranker score in the result set."
    )
    score_max: Optional[float] = Field(
        None, description="Maximum reranker score in the result set."
    )
    score_mean: Optional[float] = Field(
        None, description="Mean reranker score in the result set."
    )
    score_threshold_applied: float = Field(
        0.0, description="The score threshold that was applied."
    )
    top_k_applied: int = Field(5, description="The top-k value that was applied.")
    score_distribution: Optional[ScoreDistribution] = Field(
        None, description="Histogram-style score distribution."
    )
    precision_metrics: Optional[PrecisionMetrics] = Field(
        None, description="Precision improvement metrics."
    )


class BenchmarkResult(BaseModel):
    """Result of a single benchmark run."""

    query: str = Field(..., description="The query used in the benchmark.")
    num_candidates: int = Field(..., description="Number of candidates reranked.")
    latency_ms: float = Field(..., description="Total latency in milliseconds.")
    scoring_latency_ms: float = Field(
        ..., description="Model inference latency in milliseconds."
    )
    top_k: int = Field(..., description="Top-k value used.")
    score_threshold: float = Field(..., description="Score threshold used.")
    top_score: float = Field(..., description="Highest reranker score.")
    candidates_returned: int = Field(..., description="Number of results returned.")


class BenchmarkReport(BaseModel):
    """Comprehensive benchmark report for the reranking engine."""

    model_name: str = Field(..., description="Name of the reranker model used.")
    total_queries: int = Field(0, description="Total number of queries benchmarked.")
    total_candidates: int = Field(
        0, description="Total number of candidates processed."
    )
    avg_latency_ms: float = Field(
        0.0, description="Average total latency per query in milliseconds."
    )
    p50_latency_ms: float = Field(
        0.0, description="50th percentile latency in milliseconds."
    )
    p95_latency_ms: float = Field(
        0.0, description="95th percentile latency in milliseconds."
    )
    p99_latency_ms: float = Field(
        0.0, description="99th percentile latency in milliseconds."
    )
    avg_scoring_latency_ms: float = Field(
        0.0, description="Average model inference latency."
    )
    throughput_qps: float = Field(0.0, description="Queries per second throughput.")
    avg_candidates_per_query: float = Field(
        0.0, description="Average number of candidates per query."
    )
    avg_top_score: float = Field(
        0.0, description="Average top reranker score across all queries."
    )
    results: List[BenchmarkResult] = Field(
        default_factory=list, description="Individual benchmark results."
    )


# Resolve forward reference
RerankResponse.model_rebuild()
