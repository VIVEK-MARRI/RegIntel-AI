"""
BM25 Search API Endpoints.

Provides REST API for BM25 search and index management.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_db_session
from app.schemas.bm25 import (
    BM25SearchRequestSchema,
    BM25SearchResponseSchema,
    BM25IndexStatsSchema,
    BM25IndexActionResponse,
)
from app.services.bm25.bm25_service import BM25Service
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton BM25 service instance
_bm25_service: Optional[BM25Service] = None


def get_bm25_service() -> BM25Service:
    """Get or create the singleton BM25 service."""
    global _bm25_service
    if _bm25_service is None:
        _bm25_service = BM25Service()
    return _bm25_service


def set_bm25_service(service: BM25Service) -> None:
    """Set the BM25 service instance (for testing/dependency injection)."""
    global _bm25_service
    _bm25_service = service


# ----- Search Endpoints -----

@router.post("/search", response_model=BM25SearchResponseSchema)
async def bm25_search(
    request: BM25SearchRequestSchema,
    service: BM25Service = Depends(get_bm25_service),
) -> BM25SearchResponseSchema:
    """
    Execute a BM25 keyword search.
    
    Supports:
    - Top-K retrieval
    - Source filtering (RBI/SEBI)
    - Document filtering
    - Score thresholds
    """
    if not service.is_index_ready():
        raise HTTPException(
            status_code=503,
            detail="BM25 index is not ready. Build the index first.",
        )

    response = service.search(
        query=request.query,
        top_k=request.top_k,
        source_filter=request.source_filter,
        document_filter=request.document_filter,
        score_threshold=request.score_threshold,
    )

    return BM25SearchResponseSchema(
        query=response.query,
        results=[
            {
                "chunk_id": r.chunk_id,
                "bm25_score": r.bm25_score,
                "section": r.section,
                "subsection": r.subsection,
                "document_title": r.document_title,
                "source": r.source,
                "document_id": r.document_id,
                "content_preview": r.content_preview,
                "rank": r.rank,
            }
            for r in response.results
        ],
        total_results=response.total_results,
        latency_ms=response.latency_ms,
        average_score=response.average_score,
        filtered_count=response.filtered_count,
    )


@router.get("/search", response_model=BM25SearchResponseSchema)
async def bm25_search_get(
    query: str = Query(..., min_length=1, description="Search query"),
    top_k: int = Query(10, ge=1, le=100),
    source: Optional[str] = Query(None, description="Filter by source (RBI/SEBI)"),
    service: BM25Service = Depends(get_bm25_service),
) -> BM25SearchResponseSchema:
    """GET endpoint for BM25 search (convenience)."""
    source_filter = [source] if source else None
    return await bm25_search(
        request=BM25SearchRequestSchema(
            query=query, top_k=top_k, source_filter=source_filter
        ),
        service=service,
    )


# ----- Index Management Endpoints -----

@router.post("/index/build", response_model=BM25IndexActionResponse)
async def bm25_build_index(
    session: AsyncSession = Depends(get_db_session),
    service: BM25Service = Depends(get_bm25_service),
) -> BM25IndexActionResponse:
    """Build the BM25 index from all chunks in the database."""
    try:
        stats = await service.build_index_from_db(session)
        return BM25IndexActionResponse(
            success=True,
            message=f"BM25 index built successfully (version {stats.index_version})",
            stats=_stats_to_schema(stats),
        )
    except Exception as exc:
        logger.exception("Failed to build BM25 index")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/index/update", response_model=BM25IndexActionResponse)
async def bm25_update_index(
    session: AsyncSession = Depends(get_db_session),
    service: BM25Service = Depends(get_bm25_service),
) -> BM25IndexActionResponse:
    """Update the BM25 index with new/modified chunks."""
    try:
        stats = await service.update_index_from_db(session)
        return BM25IndexActionResponse(
            success=True,
            message=f"BM25 index updated successfully (version {stats.index_version})",
            stats=_stats_to_schema(stats),
        )
    except Exception as exc:
        logger.exception("Failed to update BM25 index")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/index/rebuild", response_model=BM25IndexActionResponse)
async def bm25_rebuild_index(
    session: AsyncSession = Depends(get_db_session),
    service: BM25Service = Depends(get_bm25_service),
) -> BM25IndexActionResponse:
    """Rebuild the entire BM25 index from scratch."""
    try:
        stats = await service.rebuild_index_from_db(session)
        return BM25IndexActionResponse(
            success=True,
            message=f"BM25 index rebuilt successfully (version {stats.index_version})",
            stats=_stats_to_schema(stats),
        )
    except Exception as exc:
        logger.exception("Failed to rebuild BM25 index")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/index/stats", response_model=BM25IndexStatsSchema)
async def bm25_index_stats(
    service: BM25Service = Depends(get_bm25_service),
) -> BM25IndexStatsSchema:
    """Get current BM25 index statistics."""
    stats = service.get_index_stats()
    return _stats_to_schema(stats)


@router.delete("/index", response_model=BM25IndexActionResponse)
async def bm25_clear_index(
    service: BM25Service = Depends(get_bm25_service),
) -> BM25IndexActionResponse:
    """Clear the entire BM25 index."""
    stats = service.clear_index()
    return BM25IndexActionResponse(
        success=True,
        message="BM25 index cleared",
        stats=_stats_to_schema(stats),
    )


# ----- Helpers -----

def _stats_to_schema(stats) -> BM25IndexStatsSchema:
    """Convert BM25IndexStats to BM25IndexStatsSchema."""
    return BM25IndexStatsSchema(
        status=stats.status.value,
        total_documents=stats.total_documents,
        total_tokens=stats.total_tokens,
        avg_doc_length=stats.avg_doc_length,
        last_built_at=stats.last_built_at,
        last_updated_at=stats.last_updated_at,
        index_version=stats.index_version,
    )