"""Pydantic schemas for the Retrieval Evaluation Suite."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RetrievalStrategy(str, Enum):
    """Supported retrieval strategies for evaluation."""

    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


class QueryRelevance(BaseModel):
    """Represents a single query with its relevant chunk IDs."""

    query_id: str = Field(..., description="Unique identifier for the query.")
    query_text: str = Field(..., description="The search query text.")
    relevant_chunk_ids: List[str] = Field(
        ..., description="List of chunk IDs considered relevant to this query."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata about the query."
    )


class GoldenDataset(BaseModel):
    """Collection of queries with relevance judgments."""

    name: str = Field(..., description="Name of the golden dataset.")
    description: str = Field(default="", description="Description of the dataset.")
    queries: List[QueryRelevance] = Field(
        ..., description="List of queries with relevance judgments."
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Dataset creation timestamp."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional dataset metadata."
    )


class RetrievalResult(BaseModel):
    """Single retrieval result for a query."""

    chunk_id: str = Field(..., description="Retrieved chunk ID.")
    score: float = Field(..., description="Retrieval score.")
    rank: int = Field(..., description="Rank position (1-indexed).")
    content: Optional[str] = Field(None, description="Chunk content snippet.")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Result metadata."
    )


class QueryEvaluationResult(BaseModel):
    """Evaluation results for a single query."""

    query_id: str = Field(..., description="Query identifier.")
    query_text: str = Field(..., description="Query text.")
    strategy: RetrievalStrategy = Field(..., description="Retrieval strategy used.")
    retrieved_results: List[RetrievalResult] = Field(
        default_factory=list, description="List of retrieved results."
    )
    relevant_chunk_ids: List[str] = Field(
        default_factory=list, description="Ground truth relevant chunk IDs."
    )
    recall_at_5: float = Field(0.0, description="Recall@5 score.")
    recall_at_10: float = Field(0.0, description="Recall@10 score.")
    mrr: float = Field(0.0, description="Mean Reciprocal Rank.")
    precision_at_5: float = Field(0.0, description="Precision@5 score.")
    precision_at_10: float = Field(0.0, description="Precision@10 score.")
    hit_rate: float = Field(0.0, description="Hit rate (1 if any relevant found).")
    ndcg_at_5: float = Field(0.0, description="NDCG@5 score.")
    ndcg_at_10: float = Field(0.0, description="NDCG@10 score.")
    latency_ms: float = Field(0.0, description="Query latency in milliseconds.")


class StrategyEvaluationResult(BaseModel):
    """Aggregated evaluation results for a single strategy."""

    strategy: RetrievalStrategy = Field(..., description="Retrieval strategy.")
    total_queries: int = Field(0, description="Total number of queries evaluated.")
    avg_recall_at_5: float = Field(0.0, description="Average Recall@5 across queries.")
    avg_recall_at_10: float = Field(
        0.0, description="Average Recall@10 across queries."
    )
    avg_mrr: float = Field(0.0, description="Average MRR across queries.")
    avg_precision_at_5: float = Field(
        0.0, description="Average Precision@5 across queries."
    )
    avg_precision_at_10: float = Field(
        0.0, description="Average Precision@10 across queries."
    )
    avg_hit_rate: float = Field(0.0, description="Average hit rate across queries.")
    avg_ndcg_at_5: float = Field(0.0, description="Average NDCG@5 across queries.")
    avg_ndcg_at_10: float = Field(0.0, description="Average NDCG@10 across queries.")
    avg_latency_ms: float = Field(0.0, description="Average latency in milliseconds.")
    query_results: List[QueryEvaluationResult] = Field(
        default_factory=list, description="Per-query evaluation results."
    )


class EvaluationReport(BaseModel):
    """Complete evaluation report comparing all strategies."""

    report_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), description="Unique report ID."
    )
    dataset_name: str = Field(..., description="Name of the golden dataset used.")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Report generation time."
    )
    strategy_results: List[StrategyEvaluationResult] = Field(
        default_factory=list, description="Results for each strategy."
    )
    leaderboard: List[Dict[str, Any]] = Field(
        default_factory=list, description="Strategy rankings."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional report metadata."
    )


class LeaderboardEntry(BaseModel):
    """Single entry in the leaderboard."""

    rank: int = Field(..., description="Ranking position.")
    strategy: RetrievalStrategy = Field(..., description="Retrieval strategy.")
    avg_recall_at_5: float = Field(0.0, description="Average Recall@5.")
    avg_recall_at_10: float = Field(0.0, description="Average Recall@10.")
    avg_mrr: float = Field(0.0, description="Average MRR.")
    avg_precision_at_5: float = Field(0.0, description="Average Precision@5.")
    avg_hit_rate: float = Field(0.0, description="Average hit rate.")
    avg_ndcg_at_5: float = Field(0.0, description="Average NDCG@5.")
    avg_ndcg_at_10: float = Field(0.0, description="Average NDCG@10.")
    avg_latency_ms: float = Field(0.0, description="Average latency.")
    composite_score: float = Field(
        0.0, description="Weighted composite score for ranking."
    )


class HistoricalMetrics(BaseModel):
    """Historical metrics record for tracking over time."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Record ID.")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow, description="Record timestamp."
    )
    strategy: RetrievalStrategy = Field(..., description="Retrieval strategy.")
    dataset_name: str = Field(..., description="Dataset used for evaluation.")
    recall_at_5: float = Field(0.0, description="Recall@5 score.")
    recall_at_10: float = Field(0.0, description="Recall@10 score.")
    mrr: float = Field(0.0, description="MRR score.")
    precision_at_5: float = Field(0.0, description="Precision@5 score.")
    precision_at_10: float = Field(0.0, description="Precision@10 score.")
    hit_rate: float = Field(0.0, description="Hit rate.")
    ndcg_at_5: float = Field(0.0, description="NDCG@5 score.")
    ndcg_at_10: float = Field(0.0, description="NDCG@10 score.")
    latency_ms: float = Field(0.0, description="Average latency.")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata."
    )


class EvaluationConfig(BaseModel):
    """Configuration for running evaluations."""

    dataset_name: str = Field(
        "default", description="Name of the golden dataset to use."
    )
    strategies: List[RetrievalStrategy] = Field(
        default_factory=lambda: [
            RetrievalStrategy.DENSE,
            RetrievalStrategy.BM25,
            RetrievalStrategy.HYBRID,
            RetrievalStrategy.HYBRID_RERANK,
        ],
        description="Strategies to evaluate.",
    )
    top_k_values: List[int] = Field(
        default_factory=lambda: [5, 10], description="K values for metrics."
    )
    rerank_top_k: int = Field(10, description="Top-K for reranking stage.")
    hybrid_top_k: int = Field(
        20, description="Top-K for hybrid retrieval before reranking."
    )
    store_results: bool = Field(
        True, description="Whether to store results historically."
    )
    generate_report: bool = Field(
        True, description="Whether to generate comparison report."
    )
