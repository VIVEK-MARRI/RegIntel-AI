import uuid
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from app.models.document import SourceEnum


class SemanticSearchRequest(BaseModel):
    """Schema for validating semantic search requests."""

    query: str = Field(..., description="Semantic search query text.")
    top_k: int = Field(
        5, ge=1, le=100, description="Number of top candidates to retrieve."
    )
    score_threshold: float = Field(
        0.0, ge=0.0, le=1.0, description="Similarity score threshold filter."
    )
    distance_metric: str = Field(
        "cosine",
        description="Distance metric (cosine, inner_product, ip, l2, euclidean).",
    )
    source: Optional[SourceEnum] = Field(None, description="Filter by document source.")
    document_id: Optional[uuid.UUID] = Field(None, description="Filter by document ID.")
    skip: int = Field(0, ge=0, description="Offset for paginating search results.")
    limit: int = Field(
        5,
        ge=1,
        le=100,
        description="Limit for paginating search results (defaults to top_k).",
    )


class SearchResultItem(BaseModel):
    """Schema for a single search result match."""

    chunk_id: str = Field(..., description="UUID of the matched chunk.")
    score: float = Field(..., description="Similarity score.")
    content: Optional[str] = Field(None, description="Text content of the chunk.")
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Metadata associated with the chunk."
    )


class SearchResponse(BaseModel):
    """Schema for a semantic search response."""

    query: str = Field(..., description="The query string that was searched.")
    results: List[SearchResultItem] = Field(
        default_factory=list, description="List of matched chunks."
    )
    trace: Optional[Dict[str, Any]] = Field(
        None, description="Diagnostic search trace."
    )


class EmbeddingStatsResponse(BaseModel):
    """Schema for embedding stats response."""

    model_name: str = Field(..., description="Name of the active embedding model.")
    dimension: int = Field(..., description="Vector dimensions.")
    total_chunks: int = Field(..., description="Total count of chunks in the database.")
    total_embeddings: int = Field(
        ..., description="Total count of embeddings stored in the database."
    )
    coverage: float = Field(
        ..., description="Percentage of chunks with computed embeddings."
    )
    status_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Counts of embeddings grouped by processing status.",
    )


class IndexRebuildRequest(BaseModel):
    """Schema for index rebuild parameters."""

    index_name: Optional[str] = Field(
        None,
        description="Optional index name to rebuild. If omitted, the index for the active model is rebuilt.",
    )
    concurrently: bool = Field(
        False, description="Rebuild concurrently (online index rebuild)."
    )


class IndexRebuildResponse(BaseModel):
    """Schema for index rebuild response."""

    status: str = Field(..., description="Result status.")
    rebuilt_indexes: List[str] = Field(
        default_factory=list, description="Names of indexes rebuilt."
    )


class IndexHealthItem(BaseModel):
    """Schema for a single index health metric record."""

    index_name: str = Field(..., description="Name of the index.")
    table_name: str = Field(..., description="Name of the table.")
    index_size_bytes: int = Field(..., description="Size of the index in bytes.")
    index_size_pretty: str = Field(..., description="Human-readable size of the index.")
    is_valid: bool = Field(..., description="Whether the index is valid and usable.")
    is_unique: bool = Field(
        ..., description="Whether the index has a uniqueness constraint."
    )
    index_scans: int = Field(
        ..., description="Number of scans performed using this index."
    )
    tuples_read: int = Field(..., description="Number of tuples read by index scans.")
    tuples_fetched: int = Field(
        ..., description="Number of table rows fetched by index scans."
    )


class SearchHealthResponse(BaseModel):
    """Schema for search health response."""

    status: str = Field(
        ..., description="Overall indexing health status (healthy/degraded)."
    )
    is_consistent: bool = Field(
        ...,
        description="Whether embedding records and registered chunks are consistent.",
    )
    index_health: List[IndexHealthItem] = Field(
        default_factory=list, description="List of index health metrics."
    )
    consistency_details: Dict[str, Any] = Field(
        ..., description="Details of consistency check."
    )
