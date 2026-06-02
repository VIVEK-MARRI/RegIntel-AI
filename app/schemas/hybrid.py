import uuid
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from app.models.document import SourceEnum
from enum import Enum

class RetrievalStrategy(str, Enum):
    """Supported retrieval strategy modes."""
    DENSE = "dense"
    KEYWORD = "keyword"
    HYBRID = "hybrid"

# Canonical enum lives in app.schemas.fusion; re-export for backward compat.
from app.schemas.fusion import FusionMethod  # noqa: E402, F401


class RetrievalResult(BaseModel):
    """Schema representing a single merged candidate chunk result."""
    chunk_id: str = Field(..., description="UUID of the matched chunk.")
    score: float = Field(..., description="Combined retrieval/fusion score.")
    dense_score: Optional[float] = Field(None, description="Original dense score if retrieved via dense.")
    bm25_score: Optional[float] = Field(None, description="Original BM25 score if retrieved via BM25.")
    dense_rank: Optional[int] = Field(None, description="Rank in dense retrieval list (1-indexed).")
    bm25_rank: Optional[int] = Field(None, description="Rank in BM25 retrieval list (1-indexed).")
    content: str = Field(..., description="Text content of the chunk.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata associated with the chunk.")

class HybridSearchRequest(BaseModel):
    """Schema for validating incoming hybrid search requests."""
    query: str = Field(..., description="Search query text.")
    top_n: int = Field(5, ge=1, le=100, description="Number of final results to return.")
    dense_top_k: int = Field(10, ge=1, le=100, description="Number of intermediate candidates to fetch from dense retrieval.")
    bm25_top_k: int = Field(10, ge=1, le=100, description="Number of intermediate candidates to fetch from BM25 retrieval.")
    dense_weight: float = Field(0.5, ge=0.0, le=1.0, description="Weight factor for dense retrieval results.")
    bm25_weight: float = Field(0.5, ge=0.0, le=1.0, description="Weight factor for BM25 keyword retrieval results.")
    strategy: RetrievalStrategy = Field(RetrievalStrategy.HYBRID, description="Retrieval strategy mode.")
    fusion_method: FusionMethod = Field(FusionMethod.RRF, description="Fusion method to combine scores (rrf or weighted_sum).")
    rrf_k: int = Field(60, ge=1, description="Constant parameter for Reciprocal Rank Fusion ranking formula.")
    source: Optional[SourceEnum] = Field(None, description="Filter by document source (e.g. RBI, SEBI).")
    document_id: Optional[uuid.UUID] = Field(None, description="Filter by specific document UUID.")

class HybridSearchResponse(BaseModel):
    """Schema representing the unified hybrid search result list and telemetry diagnostics."""
    query: str = Field(..., description="The query string that was searched.")
    results: List[RetrievalResult] = Field(default_factory=list, description="Unified list of merged search results.")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Telemetry metrics tracking latency and candidate overlap.")
