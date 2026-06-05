import re
import uuid
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.api.dependencies import (
    get_retrieval_service,
    get_embedding_provider,
    get_vector_index_manager,
    get_hybrid_retriever,
    get_reranker_service,
)
from app.models.chunk import ChunkEmbedding, DocumentChunk
from app.services.embedding.retrieval import RetrievalService
from app.services.embedding.index_manager import VectorIndexManager
from app.services.embedding import EmbeddingProvider
from app.schemas.search import (
    SemanticSearchRequest,
    SearchResponse,
    SearchResultItem,
    EmbeddingStatsResponse,
    IndexRebuildRequest,
    IndexRebuildResponse,
    IndexHealthItem,
    SearchHealthResponse
)
from app.schemas.hybrid import HybridSearchRequest, HybridSearchResponse
from app.services.hybrid.service import HybridRetriever
from app.schemas.reranker import RerankRequest, RerankResponse
from app.services.reranker.service import RerankerService

logger = logging.getLogger(__name__)

# Declare three distinct routers for registration
search_router = APIRouter()
embeddings_router = APIRouter()
index_router = APIRouter()

# ----------------------------------------------------
# 1. Search Router
# ----------------------------------------------------

@search_router.post(
    "",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Semantic search over regulatory document chunks",
    description="Performs high-dimensional dense vector similarity search with optional filtering, page-based pagination, and scoring thresholds."
)
async def semantic_search(
    request: SemanticSearchRequest,
    retrieval_service: RetrievalService = Depends(get_retrieval_service)
) -> SearchResponse:
    try:
        # Resolve effective top_k when pagination is requested
        effective_top_k = request.skip + request.limit if request.skip > 0 else request.top_k
        
        search_res = await retrieval_service.retrieve(
            query=request.query,
            top_k=effective_top_k,
            score_threshold=request.score_threshold,
            distance_metric=request.distance_metric,
            source=request.source,
            document_id=request.document_id
        )
        
        # Paginate the retrieved list in memory to support skip/limit slicing safely
        results = search_res.get("results", [])
        if request.skip > 0:
            results = results[request.skip:request.skip + request.limit]
        else:
            results = results[:request.limit]
            
        items = [
            SearchResultItem(
                chunk_id=r["chunk_id"],
                score=r["score"],
                content=r.get("content"),
                metadata=r.get("metadata")
            )
            for r in results
        ]
        
        return SearchResponse(
            query=request.query,
            results=items,
            trace=search_res.get("trace")
        )
    except ValueError as e:
        logger.warning(f"Validation error in semantic search parameters: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error executing semantic search: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while executing the search."
        )


# NOTE: The /hybrid endpoint was removed in Module 4.8.
# It is now provided as the production-grade /api/v1/search/hybrid endpoint
# in app/api/v1/retrieval.py with full diagnostics, optional reranking,
# query classification, and Pydantic v2 contracts.


@search_router.post(
    "/rerank",
    response_model=RerankResponse,
    status_code=status.HTTP_200_OK,
    summary="Rerank retrieval candidates using cross-encoder relevance scoring",
    description="Scores each candidate chunk against the query using BAAI/bge-reranker-base and returns the top-K most relevant results."
)
async def rerank_candidates(
    request: RerankRequest,
    reranker: RerankerService = Depends(get_reranker_service),
) -> RerankResponse:
    try:
        candidates = [
            {
                "chunk_id": c.chunk_id,
                "content": c.content,
                "score": c.score,
                "metadata": c.metadata,
            }
            for c in request.candidates
        ]
        return reranker.rerank(
            query=request.query,
            candidates=candidates,
            top_k=request.top_k,
            score_threshold=request.score_threshold,
        )
    except Exception as e:
        logger.error(f"Unexpected error executing reranking: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while reranking candidates."
        )

@search_router.get(
    "/health",
    response_model=SearchHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Get search indexing health",
    description="Validates relational database pgvector/B-tree index states, computes scanning performance, and checks embedding/chunk registry consistency."
)
async def get_search_health(
    index_manager: VectorIndexManager = Depends(get_vector_index_manager),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider)
) -> SearchHealthResponse:
    try:
        model_name = embedding_provider.get_model_name()
        
        # Gather PG index statistics
        health_metrics = await index_manager.index_health()
        index_health_items = [
            IndexHealthItem(
                index_name=m["index_name"],
                table_name=m["table_name"],
                index_size_bytes=m["index_size_bytes"],
                index_size_pretty=m["index_size_pretty"],
                is_valid=m["is_valid"],
                is_unique=m["is_unique"],
                index_scans=m["index_scans"],
                tuples_read=m["tuples_read"],
                tuples_fetched=m["tuples_fetched"]
            )
            for m in health_metrics
        ]
        
        # Verify index count consistency
        consistency = await index_manager.validate_consistency(model_name)
        
        # Degraded status flag when consistency check reports issues or invalid indexes exist
        any_invalid = any(not item.is_valid for item in index_health_items)
        is_consistent = consistency.get("is_consistent", True)
        
        health_status = "healthy"
        if any_invalid or not is_consistent:
            health_status = "degraded"
            
        return SearchHealthResponse(
            status=health_status,
            is_consistent=is_consistent,
            index_health=index_health_items,
            consistency_details=consistency
        )
    except Exception as e:
        logger.error(f"Error checking search index health: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while inspecting search index health."
        )


# ----------------------------------------------------
# 2. Embeddings Router
# ----------------------------------------------------

@embeddings_router.get(
    "/stats",
    response_model=EmbeddingStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get embedding model and storage stats",
    description="Returns metadata about the active embedding model, dimension parameters, total document chunks, and status distributions of stored embeddings."
)
async def get_embedding_stats(
    db_session: AsyncSession = Depends(get_db_session),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider)
) -> EmbeddingStatsResponse:
    try:
        model_name = embedding_provider.get_model_name()
        dimension = embedding_provider.get_dimension()
        
        # Count total chunks in DB
        chunk_stmt = select(func.count(DocumentChunk.id))
        chunk_res = await db_session.execute(chunk_stmt)
        total_chunks = chunk_res.scalar() or 0
        
        # Count total embeddings for the active model
        emb_stmt = select(func.count(ChunkEmbedding.id)).where(ChunkEmbedding.embedding_model == model_name)
        emb_res = await db_session.execute(emb_stmt)
        total_embeddings = emb_res.scalar() or 0
        
        # Group by status to check completion counts
        status_stmt = (
            select(ChunkEmbedding.status, func.count(ChunkEmbedding.id))
            .where(ChunkEmbedding.embedding_model == model_name)
            .group_by(ChunkEmbedding.status)
        )
        status_res = await db_session.execute(status_stmt)
        status_counts = {
            "PENDING": 0,
            "PROCESSING": 0,
            "COMPLETED": 0,
            "FAILED": 0
        }
        for status_val, count in status_res.all():
            status_str = status_val.value if hasattr(status_val, "value") else str(status_val)
            status_counts[status_str.upper()] = count
            
        completed_count = status_counts.get("COMPLETED", 0)
        coverage = (completed_count / total_chunks * 100.0) if total_chunks > 0 else 100.0
        
        return EmbeddingStatsResponse(
            model_name=model_name,
            dimension=dimension,
            total_chunks=total_chunks,
            total_embeddings=total_embeddings,
            coverage=coverage,
            status_counts=status_counts
        )
    except Exception as e:
        logger.error(f"Error fetching embedding statistics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while gathering embedding statistics."
        )


# ----------------------------------------------------
# 3. Index Router
# ----------------------------------------------------

@index_router.post(
    "/rebuild",
    response_model=IndexRebuildResponse,
    status_code=status.HTTP_200_OK,
    summary="Rebuild vector search indexes",
    description="Performs HNSW vector index recreation. If no index name is provided, resolves and rebuilds all indexes associated with the active embedding model."
)
async def rebuild_indexes(
    request: IndexRebuildRequest,
    index_manager: VectorIndexManager = Depends(get_vector_index_manager),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider)
) -> IndexRebuildResponse:
    try:
        rebuilt_indexes = []
        
        if request.index_name:
            await index_manager.rebuild_index(
                index_name=request.index_name,
                concurrently=request.concurrently
            )
            rebuilt_indexes.append(request.index_name)
        else:
            model_name = embedding_provider.get_model_name()
            health_metrics = await index_manager.index_health()
            
            # Rebuild all indexes corresponding to active model
            clean_model = re.sub(r"[^a-zA-Z0-9_]", "_", model_name).lower()
            matched_indexes = [
                m["index_name"] for m in health_metrics
                if clean_model in m["index_name"].lower()
            ]
            
            if not matched_indexes:
                # Setup default index if none exist
                default_idx = await index_manager.create_index(
                    model_name=model_name,
                    distance_metric="cosine",
                    concurrently=request.concurrently
                )
                rebuilt_indexes.append(default_idx)
            else:
                for idx_name in matched_indexes:
                    await index_manager.rebuild_index(
                        index_name=idx_name,
                        concurrently=request.concurrently
                    )
                    rebuilt_indexes.append(idx_name)
                    
        return IndexRebuildResponse(
            status="success",
            rebuilt_indexes=rebuilt_indexes
        )
    except Exception as e:
        logger.error(f"Error rebuilding vector indexes: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while rebuilding index: {str(e)}"
        )
