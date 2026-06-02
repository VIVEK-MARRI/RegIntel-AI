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
    score: Optional[float] = Field(None, description="Original retrieval score (dense or fusion).")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata from the retrieval stage.")


class RerankResult(BaseModel):
    """A single reranked chunk with cross-encoder relevance score."""

    chunk_id: str = Field(..., description="UUID of the reranked chunk.")
    rerank_score: float = Field(..., description="Cross-encoder relevance score (higher = more relevant).")
    original_score: Optional[float] = Field(None, description="Score from the initial retrieval stage.")
    original_rank: Optional[int] = Field(None, description="1-indexed rank before reranking.")
    content: str = Field("", description="Text content of the chunk.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata associated with the chunk.")


class RerankRequest(BaseModel):
    """Request schema for the reranking endpoint."""

    query: str = Field(..., description="The user query to score candidates against.")
    candidates: List[RerankCandidate] = Field(
        ..., min_length=1, max_length=500,
        description="Candidate chunks to rerank.",
    )
    top_k: int = Field(5, ge=1, le=100, description="Number of top results to return after reranking.")
    score_threshold: float = Field(0.0, description="Minimum reranker score to include a result.")


class RerankResponse(BaseModel):
    """Response schema for the reranking endpoint."""

    query: str = Field(..., description="The query that candidates were reranked against.")
    results: List[RerankResult] = Field(default_factory=list, description="Top-K reranked results.")
    report: "RerankReport" = Field(..., description="Diagnostic metrics for the reranking operation.")


class RerankReport(BaseModel):
    """Diagnostic report emitted after each reranking operation."""

    model_name: str = Field(..., description="Name of the reranker model used.")
    candidates_received: int = Field(0, description="Number of candidates submitted for reranking.")
    candidates_returned: int = Field(0, description="Number of candidates after top-k and threshold filtering.")
    latency_ms: float = Field(0.0, description="Total wall-clock reranking latency in milliseconds.")
    score_min: Optional[float] = Field(None, description="Minimum reranker score in the result set.")
    score_max: Optional[float] = Field(None, description="Maximum reranker score in the result set.")
    score_mean: Optional[float] = Field(None, description="Mean reranker score in the result set.")
    score_threshold_applied: float = Field(0.0, description="The score threshold that was applied.")
    top_k_applied: int = Field(5, description="The top-k value that was applied.")


# Resolve forward reference
RerankResponse.model_rebuild()
