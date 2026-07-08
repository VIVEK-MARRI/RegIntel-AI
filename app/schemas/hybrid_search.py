"""Pydantic v2 API contracts for the Hybrid Search API Layer (Module 4.8).

These schemas define the wire format for the production-grade dense / BM25 /
hybrid search endpoints. They are intentionally separate from the
``app/schemas/search.py`` and ``app/schemas/hybrid.py`` internal contracts
so the public API surface can evolve independently from the service layer.

All request/response models follow the spec defined in Module 4.8:

* ``query`` is the canonical raw user query string.
* ``top_k`` is the final number of results to return.
* ``filters`` is an optional generic filter object (document_id / source /
  section / score_threshold).
* Responses always expose ``query``, ``strategy``, ``latency_ms`` and a
  ``results`` list of ``SearchResultItem``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import SourceEnum
from app.schemas.fusion import FusionMethod


# ─── Enums ───────────────────────────────────────────────────────────────────


class SearchStrategy(str, Enum):
    """Strategy used to satisfy a search request."""

    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


# ─── Filter Models ───────────────────────────────────────────────────────────


class SearchFilters(BaseModel):
    """Generic filter object accepted by all search endpoints.

    All fields are optional. A ``None`` value means "no filter on this field".
    The endpoint will apply filters to the underlying retrieval call.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[uuid.UUID] = Field(
        None, description="Restrict results to chunks belonging to this document."
    )
    source: Optional[SourceEnum] = Field(
        None, description="Restrict results to a regulator source (RBI / SEBI)."
    )
    section: Optional[str] = Field(
        None, description="Restrict results to chunks whose section contains this text."
    )
    min_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Minimum score required for a result to be included.",
    )


# ─── Request Models ──────────────────────────────────────────────────────────


class DenseSearchRequest(BaseModel):
    """Request payload for the dense (semantic) search endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ..., min_length=1, max_length=2048, description="User search query."
    )
    top_k: int = Field(5, ge=1, le=100, description="Number of results to return.")
    filters: SearchFilters = Field(
        default_factory=SearchFilters, description="Optional result filters."
    )
    distance_metric: str = Field(
        "cosine",
        description="Distance metric: cosine, inner_product, ip, l2, euclidean.",
    )


class BM25SearchRequest(BaseModel):
    """Request payload for the BM25 keyword search endpoint."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ..., min_length=1, max_length=2048, description="User search query."
    )
    top_k: int = Field(5, ge=1, le=100, description="Number of results to return.")
    filters: SearchFilters = Field(
        default_factory=SearchFilters, description="Optional result filters."
    )
    score_threshold: float = Field(
        0.0,
        ge=0.0,
        description="Minimum BM25 score to include a result.",
    )


class HybridSearchRequest(BaseModel):
    """Request payload for the hybrid (dense + BM25) search endpoint.

    The flagship endpoint of Module 4.8. Runs the full pipeline:
    query understanding → dense + BM25 → RRF fusion → optional BGE rerank.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ..., min_length=1, max_length=2048, description="User search query."
    )
    top_k: int = Field(
        5, ge=1, le=100, description="Final number of results to return."
    )
    filters: SearchFilters = Field(
        default_factory=SearchFilters, description="Optional result filters."
    )
    enable_reranking: bool = Field(
        True,
        description="When true the fused candidates are passed through the BGE cross-encoder.",
    )
    fusion_method: FusionMethod = Field(
        FusionMethod.RRF, description="Score fusion method: rrf or weighted_sum."
    )
    dense_weight: float = Field(
        0.5, ge=0.0, le=1.0, description="Weight of dense scores during fusion."
    )
    bm25_weight: float = Field(
        0.5, ge=0.0, le=1.0, description="Weight of BM25 scores during fusion."
    )
    rrf_k: int = Field(60, ge=1, description="Smoothing constant for RRF fusion.")
    dense_top_k: int = Field(20, ge=1, le=200, description="Dense candidates to fetch.")
    bm25_top_k: int = Field(20, ge=1, le=200, description="BM25 candidates to fetch.")
    fusion_candidate_k: int = Field(
        20, ge=1, le=200, description="Fused candidates to feed into the reranker."
    )
    use_query_analysis: bool = Field(
        True, description="If true the QueryAnalyzer is used to refine the strategy."
    )


# ─── Response Models ─────────────────────────────────────────────────────────


class SearchResultItem(BaseModel):
    """A single ranked search result returned by the API."""

    chunk_id: str = Field(..., description="UUID of the matched chunk.")
    document_id: Optional[str] = Field(
        None, description="UUID of the parent document (when known)."
    )
    score: float = Field(..., description="Final score for this result.")
    page_number: Optional[int] = Field(
        None, description="Page number the chunk was extracted from."
    )
    content: Optional[str] = Field(
        None, description="Optional text content of the chunk (included by default)."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Optional metadata about the chunk."
    )
    rank: Optional[int] = Field(None, description="1-indexed rank of the result.")


class SearchResponse(BaseModel):
    """Generic response envelope for a search request.

    The same envelope is used by dense, BM25, and hybrid endpoints so that
    downstream clients can parse the response shape uniformly.
    """

    query: str = Field(..., description="The original query string.")
    strategy: str = Field(..., description="The strategy that produced these results.")
    latency_ms: float = Field(
        ..., description="End-to-end request latency in milliseconds."
    )
    total_results: int = Field(..., ge=0, description="Number of results returned.")
    results: List[SearchResultItem] = Field(
        default_factory=list, description="Ranked list of result items."
    )
    request_id: Optional[str] = Field(
        None,
        description="Server-generated ID correlating logs and metrics for this request.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Server timestamp at response time.",
    )


class HybridSearchDiagnostics(BaseModel):
    """Telemetry for the hybrid search endpoint."""

    query_type: str = Field("unknown", description="Classified query type.")
    query_confidence: float = Field(0.0, description="Query classification confidence.")
    recommended_strategy: str = Field(
        "hybrid", description="Strategy recommended by analyzer."
    )
    dense_count: int = Field(0, description="Dense candidates fetched.")
    bm25_count: int = Field(0, description="BM25 candidates fetched.")
    fused_count: int = Field(0, description="Fused candidates produced.")
    overlap_count: int = Field(0, description="Chunks returned by both dense and BM25.")
    overlap_pct: float = Field(
        0.0, description="Overlap as percentage of total candidates."
    )
    dense_latency_ms: float = Field(0.0, description="Dense retrieval latency in ms.")
    bm25_latency_ms: float = Field(0.0, description="BM25 retrieval latency in ms.")
    fusion_latency_ms: float = Field(0.0, description="Score fusion latency in ms.")
    rerank_latency_ms: float = Field(
        0.0, description="Cross-encoder rerank latency in ms."
    )
    rerank_used: bool = Field(
        False, description="True if reranking was actually applied."
    )
    rerank_model: Optional[str] = Field(None, description="Reranker model name.")
    fusion_method: str = Field("rrf", description="Fusion method that was used.")


class HybridSearchResponse(SearchResponse):
    """Extended response for the hybrid search endpoint.

    Includes query classification and full-pipeline diagnostics. Inherits
    the standard envelope from :class:`SearchResponse`.
    """

    query_type: str = Field(..., description="Classified query type.")
    strategy: str = Field("hybrid", description="Always 'hybrid' for this endpoint.")
    diagnostics: HybridSearchDiagnostics = Field(
        default_factory=HybridSearchDiagnostics, description="Pipeline telemetry."
    )


# ─── Metrics & Health Models ─────────────────────────────────────────────────


class RetrievalMetricsResponse(BaseModel):
    """Aggregated retrieval metrics sourced from the analytics platform."""

    dense_recall: Optional[float] = Field(
        None, description="Recall@10 for dense retrieval (averaged over recent window)."
    )
    bm25_recall: Optional[float] = Field(
        None, description="Recall@10 for BM25 retrieval (averaged over recent window)."
    )
    hybrid_recall: Optional[float] = Field(
        None,
        description="Recall@10 for hybrid retrieval (averaged over recent window).",
    )
    reranker_gain: Optional[float] = Field(
        None, description="Average recall improvement after BGE reranking."
    )
    retrieval_success_rate: Optional[float] = Field(
        None,
        description="Fraction of queries that returned at least one relevant chunk.",
    )
    average_latency: Optional[float] = Field(
        None, description="Average end-to-end retrieval latency in ms."
    )
    total_queries: int = Field(0, description="Total queries recorded.")
    window_start: Optional[datetime] = Field(
        None, description="Start of the metrics window."
    )
    window_end: Optional[datetime] = Field(
        None, description="End of the metrics window."
    )


class HealthCheck(BaseModel):
    """A single health probe result."""

    name: str = Field(..., description="Component name being checked.")
    healthy: bool = Field(..., description="True when the component is operational.")
    latency_ms: Optional[float] = Field(None, description="Probe latency in ms.")
    details: Dict[str, Any] = Field(
        default_factory=dict, description="Component-specific diagnostic data."
    )


class RetrievalHealthResponse(BaseModel):
    """Response model for the retrieval system health endpoint."""

    status: str = Field(
        ..., description="Overall status: healthy | degraded | unhealthy."
    )
    checks: Dict[str, bool] = Field(
        ..., description="Map of component name to boolean health flag."
    )
    components: List[HealthCheck] = Field(
        default_factory=list, description="Detailed per-component health information."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Server timestamp at response time.",
    )
