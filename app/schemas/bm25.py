"""
BM25 Search Schemas - Request/Response models for BM25 API endpoints.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class BM25SearchRequestSchema(BaseModel):
    """Request schema for BM25 search."""
    query: str = Field(..., min_length=1, description="Search query string")
    top_k: int = Field(10, ge=1, le=100, description="Maximum number of results")
    source_filter: Optional[List[str]] = Field(
        None,
        description="Filter by source (e.g., ['RBI', 'SEBI'])",
    )
    document_filter: Optional[List[str]] = Field(
        None,
        description="Filter by document ID",
    )
    score_threshold: float = Field(
        0.0,
        ge=0.0,
        description="Minimum BM25 score threshold",
    )


class BM25SearchResultSchema(BaseModel):
    """Single BM25 search result."""
    chunk_id: str
    bm25_score: float
    section: str = ""
    subsection: str = ""
    document_title: str = ""
    source: str = ""
    document_id: str = ""
    content_preview: str = ""
    rank: int = 0

    model_config = {
        "json_schema_extra": {
            "example": {
                "chunk_id": "abc-123",
                "bm25_score": 12.3,
                "section": "KYC Guidelines",
                "subsection": "Customer Identification",
                "document_title": "RBI Master Direction on KYC",
                "source": "RBI",
                "document_id": "doc-456",
                "content_preview": "Banks shall verify the identity of customers...",
                "rank": 1,
            }
        }
    }


class BM25SearchResponseSchema(BaseModel):
    """BM25 search response with results and telemetry."""
    query: str
    results: List[BM25SearchResultSchema]
    total_results: int
    latency_ms: float
    average_score: float = 0.0
    filtered_count: int = 0


class BM25IndexStatsSchema(BaseModel):
    """BM25 index statistics."""
    status: str
    total_documents: int
    total_tokens: int
    avg_doc_length: float
    last_built_at: Optional[float] = None
    last_updated_at: Optional[float] = None
    index_version: int = 0


class BM25IndexActionResponse(BaseModel):
    """Response for index management actions (build, update, rebuild)."""
    success: bool
    message: str
    stats: BM25IndexStatsSchema