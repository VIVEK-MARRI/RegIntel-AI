"""Pydantic schemas for Milestone 4 Hybrid Retrieval API endpoints.

Request/response models for query analysis, hybrid+rerank search,
and retrieval telemetry.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.document import SourceEnum
from app.schemas.fusion import FusionMethod


# ─── Query Analysis Schemas ──────────────────────────────────────────────────

class QueryAnalysisRequest(BaseModel):
    """Request schema for query analysis."""
    query: str = Field(..., description="The user query to analyze.", min_length=1)


class QueryAnalysisResponse(BaseModel):
    """Response schema for query analysis."""
    query: str = Field(..., description="The original query.")
    query_type: str = Field(..., description="Classified query type (keyword, circular, regulation, semantic, comparison, definition).")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence.")
    optimal_strategy: str = Field(..., description="Recommended retrieval strategy (bm25, dense, hybrid).")
    processing_time_ms: float = Field(0.0, description="Time taken for analysis.")


# ─── Hybrid + Rerank Request / Response ──────────────────────────────────────

class HybridRerankSearchRequest(BaseModel):
    """Request schema for the combined hybrid + reranking search endpoint."""
    query: str = Field(..., description="Search query text.", min_length=1)
    top_k: int = Field(5, ge=1, le=100, description="Final number of results after reranking.")
    rerank_top_k: Optional[int] = Field(None, ge=1, le=100, description="Candidates to pass to reranker (defaults to fusion_candidate_k).")
    rerank_score_threshold: float = Field(0.0, ge=0.0, le=1.0, description="Minimum reranker score to include.")
    fusion_candidate_k: int = Field(20, ge=1, le=200, description="Number of fused candidates before reranking.")
    dense_top_k: int = Field(20, ge=1, le=200, description="Dense candidates to fetch.")
    bm25_top_k: int = Field(20, ge=1, le=200, description="BM25 candidates to fetch.")
    dense_weight: float = Field(0.5, ge=0.0, le=1.0, description="Dense fusion weight.")
    bm25_weight: float = Field(0.5, ge=0.0, le=1.0, description="BM25 fusion weight.")
    fusion_method: FusionMethod = Field(FusionMethod.RRF, description="Fusion method (rrf or weighted_sum).")
    rrf_k: int = Field(60, ge=1, description="RRF smoothing constant.")
    source: Optional[SourceEnum] = Field(None, description="Filter by document source (RBI/SEBI).")
    document_id: Optional[uuid.UUID] = Field(None, description="Filter by document ID.")
    use_query_analysis: bool = Field(True, description="Use query analyzer for automatic strategy selection.")


class RerankedSearchResult(BaseModel):
    """A single reranked search result."""
    chunk_id: str
    rerank_score: float
    original_score: Optional[float] = None
    dense_score: Optional[float] = None
    bm25_score: Optional[float] = None
    dense_rank: Optional[int] = None
    bm25_rank: Optional[int] = None
    new_rank: Optional[int] = None
    content: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalDiagnostics(BaseModel):
    """Diagnostic metrics for the retrieval pipeline."""
    query_type: str = "unknown"
    query_confidence: float = 0.0
    recommended_strategy: str = "hybrid"
    strategy_source: str = "explicit"
    dense_count: int = 0
    bm25_count: int = 0
    fused_count: int = 0
    overlap_count: int = 0
    overlap_pct: float = 0.0
    dense_latency_ms: float = 0.0
    bm25_latency_ms: float = 0.0
    fusion_latency_ms: float = 0.0
    rerank_latency_ms: float = 0.0
    total_latency_ms: float = 0.0


class HybridRerankSearchResponse(BaseModel):
    """Response schema for the combined hybrid + reranking search endpoint."""
    query: str
    results: List[RerankedSearchResult]
    diagnostics: RetrievalDiagnostics
    rerank_model: str = ""
    rerank_candidates: int = 0


# ─── Retrieval Metrics Schemas ───────────────────────────────────────────────

class RetrievalMetricsEntry(BaseModel):
    """Per-query retrieval metrics summary."""
    query_id: str
    query_text: str
    strategy: str
    query_type: str
    total_latency_ms: float
    dense_count: int
    bm25_count: int
    overlap_pct: float
    results_returned: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ─── Retrieval Health Schemas ────────────────────────────────────────────────

class RetrievalHealthComponent(BaseModel):
    """Health status of a single retrieval component."""
    name: str
    status: str  # "healthy", "degraded", "unhealthy"
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class RetrievalHealthResponse(BaseModel):
    """Response schema for retrieval system health."""
    status: str  # "healthy", "degraded", "unhealthy"
    components: List[RetrievalHealthComponent]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
