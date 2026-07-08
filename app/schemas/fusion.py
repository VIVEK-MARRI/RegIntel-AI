"""Pydantic schemas for the Retrieval Fusion Engine.

Defines the data models for fusion configuration, individual fused candidates,
and diagnostic reports used for evaluation and observability.
"""

from typing import List, Optional, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field


class FusionMethod(str, Enum):
    """Supported candidate score fusion methods.

    This is the canonical enum. The duplicate in ``app.schemas.hybrid`` is kept
    for backward compatibility and re-exports this definition.
    """

    RRF = "rrf"
    WEIGHTED_SUM = "weighted_sum"
    SCORE_FUSION = "score_fusion"          # Stub – future direct-score averaging
    LEARNING_TO_RANK = "learning_to_rank"  # Stub – future ML re-ranker


class FusionConfig(BaseModel):
    """Parameters that control how two ranked lists are fused."""

    method: FusionMethod = Field(FusionMethod.RRF, description="Fusion algorithm to apply.")
    rrf_k: int = Field(60, ge=1, description="Constant for the RRF formula: 1/(k + rank).")
    dense_weight: float = Field(0.5, ge=0.0, le=1.0, description="Weight for dense retrieval scores.")
    bm25_weight: float = Field(0.5, ge=0.0, le=1.0, description="Weight for BM25 retrieval scores.")


class FusedCandidate(BaseModel):
    """A single chunk result after fusion, preserving full provenance."""

    chunk_id: str = Field(..., description="UUID of the matched chunk.")
    score: float = Field(..., description="Combined retrieval/fusion score.")
    rrf_score: Optional[float] = Field(None, description="RRF-specific score (when RRF is used).")
    dense_score: Optional[float] = Field(None, description="Original dense similarity score.")
    bm25_score: Optional[float] = Field(None, description="Original BM25 relevance score.")
    dense_rank: Optional[int] = Field(None, description="1-indexed rank in the dense result list.")
    bm25_rank: Optional[int] = Field(None, description="1-indexed rank in the BM25 result list.")
    sources: List[str] = Field(default_factory=list, description="Retrieval sources that contributed this chunk (e.g. ['dense', 'bm25']).")
    content: str = Field("", description="Text content of the chunk.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata associated with the chunk.")


class FusionReport(BaseModel):
    """Diagnostic report emitted after each fusion operation for evaluation/observability."""

    method: FusionMethod = Field(..., description="The fusion method that was applied.")
    dense_count: int = Field(0, description="Number of candidates from dense retrieval.")
    bm25_count: int = Field(0, description="Number of candidates from BM25 retrieval.")
    fused_count: int = Field(0, description="Total unique candidates after fusion.")
    overlap_count: int = Field(0, description="Number of chunks that appeared in both lists.")
    overlap_percentage: float = Field(0.0, description="Overlap as a percentage of the union.")
    config: FusionConfig = Field(default_factory=FusionConfig, description="The configuration used for this fusion run.")
