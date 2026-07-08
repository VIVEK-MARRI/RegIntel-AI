import time
import math
import uuid
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.chunk import ChunkEmbedding, DocumentChunk, EmbeddingStatusEnum
from app.models.document import Document, SourceEnum
from app.services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


def dot_product(v1: List[float], v2: List[float]) -> float:
    return sum(x * y for x, y in zip(v1, v2))


def norm(v: List[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    d = dot_product(v1, v2)
    n1 = norm(v1)
    n2 = norm(v2)
    if n1 > 0.0 and n2 > 0.0:
        return d / (n1 * n2)
    return 0.0


def l2_similarity(v1: List[float], v2: List[float]) -> float:
    dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(v1, v2)))
    return 1.0 / (1.0 + dist)


class RetrievalService:
    """Service responsible for dense vector semantic search over regulatory document chunks."""

    def __init__(self, db_session: AsyncSession, embedding_provider: EmbeddingProvider):
        self.db_session = db_session
        self.embedding_provider = embedding_provider

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
        distance_metric: str = "cosine",
        source: Optional[SourceEnum] = None,
        document_id: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Performs semantic search over chunk embeddings and returns top-K results with traces."""
        start_time = time.perf_counter()
        metric = distance_metric.lower()

        if metric not in ["cosine", "inner_product", "ip", "l2", "euclidean"]:
            raise ValueError(
                f"Unsupported distance metric '{distance_metric}'. Supported: cosine, inner_product, ip, l2, euclidean"
            )

        if not query or not query.strip():
            duration_ms = (time.perf_counter() - start_time) * 1000
            return {
                "results": [],
                "trace": {
                    "query": query,
                    "metric": metric,
                    "top_k": top_k,
                    "score_threshold": score_threshold,
                    "duration_ms": duration_ms,
                    "candidates_scanned": 0,
                },
            }

        # 1. Generate query embedding
        query_vector = self.embedding_provider.encode_query(query)
        model_name = self.embedding_provider.get_model_name()

        results = []
        candidates_scanned = 0

        # 2. Fallback Mode (Python-based calculations on database-filtered rows)
        if settings.USE_PGVECTOR_FALLBACK:
            # Query candidate embeddings & chunks from database using standard filtering
            stmt = (
                select(DocumentChunk, ChunkEmbedding)
                .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    and_(
                        ChunkEmbedding.embedding_model == model_name,
                        ChunkEmbedding.status == EmbeddingStatusEnum.COMPLETED,
                    )
                )
            )

            if source:
                stmt = stmt.where(Document.source == source)
            if document_id:
                stmt = stmt.where(DocumentChunk.document_id == document_id)

            db_results = await self.db_session.execute(stmt)
            rows = db_results.all()
            candidates_scanned = len(rows)

            scored_candidates = []
            for chunk, emb_record in rows:
                if not emb_record.embedding:
                    continue

                # Compute similarity based on requested metric
                if metric == "cosine":
                    score = cosine_similarity(query_vector, emb_record.embedding)
                elif metric in ["inner_product", "ip"]:
                    score = dot_product(query_vector, emb_record.embedding)
                else:  # L2
                    score = l2_similarity(query_vector, emb_record.embedding)

                if score >= score_threshold:
                    scored_candidates.append((chunk, score))

            # 3. Deterministic Sorting: sort descending by score, secondary ascending by chunk ID
            scored_candidates.sort(key=lambda x: (-x[1], x[0].id))
            top_candidates = scored_candidates[:top_k]

            for chunk, score in top_candidates:
                results.append(
                    {
                        "chunk_id": str(chunk.id),
                        "score": score,
                        "content": chunk.content,
                        "metadata": {
                            "document_id": str(chunk.document_id),
                            "page_number": chunk.page_number,
                            "section": chunk.section,
                            "subsection": chunk.subsection,
                            "token_count": chunk.token_count,
                            "metadata_json": chunk.metadata_json,
                        },
                    }
                )

        # 4. Native pgvector Mode
        else:
            # Build database-level pgvector similarity query
            # We map metric to pgvector distance operator:
            # - cosine_distance: ChunkEmbedding.embedding.cosine_distance(query_vector)
            # - negative inner product: ChunkEmbedding.embedding.max_inner_product(query_vector)
            # - l2_distance: ChunkEmbedding.embedding.l2_distance(query_vector)

            # To perform filtering, sorting, and score threshold, we select from subquery:
            if metric == "cosine":
                distance_expr = ChunkEmbedding.embedding.cosine_distance(query_vector)
                score_expr = (1.0 - distance_expr).label("score")
            elif metric in ["inner_product", "ip"]:
                distance_expr = ChunkEmbedding.embedding.max_inner_product(query_vector)
                score_expr = (-distance_expr).label("score")
            else:  # L2
                distance_expr = ChunkEmbedding.embedding.l2_distance(query_vector)
                score_expr = (1.0 / (1.0 + distance_expr)).label("score")

            subq_stmt = (
                select(
                    DocumentChunk.id.label("chunk_id"),
                    DocumentChunk.content.label("content"),
                    DocumentChunk.document_id.label("document_id"),
                    DocumentChunk.page_number.label("page_number"),
                    DocumentChunk.section.label("section"),
                    DocumentChunk.subsection.label("subsection"),
                    DocumentChunk.token_count.label("token_count"),
                    DocumentChunk.metadata_json.label("metadata_json"),
                    score_expr,
                )
                .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    and_(
                        ChunkEmbedding.embedding_model == model_name,
                        ChunkEmbedding.status == EmbeddingStatusEnum.COMPLETED,
                    )
                )
            )

            if source:
                subq_stmt = subq_stmt.where(Document.source == source)
            if document_id:
                subq_stmt = subq_stmt.where(DocumentChunk.document_id == document_id)

            subq = subq_stmt.subquery()

            # Final statement filtering by score threshold and sorting deterministically
            final_stmt = (
                select(subq)
                .where(subq.c.score >= score_threshold)
                .order_by(subq.c.score.desc(), subq.c.chunk_id.asc())
                .limit(top_k)
            )

            db_results = await self.db_session.execute(final_stmt)
            rows = db_results.all()
            candidates_scanned = len(
                rows
            )  # In native mode, scanned matches returning row count

            for row in rows:
                results.append(
                    {
                        "chunk_id": str(row.chunk_id),
                        "score": float(row.score),
                        "content": row.content,
                        "metadata": {
                            "document_id": str(row.document_id),
                            "page_number": row.page_number,
                            "section": row.section,
                            "subsection": row.subsection,
                            "token_count": row.token_count,
                            "metadata_json": row.metadata_json,
                        },
                    }
                )

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Retrieval complete. Found {len(results)} matches for query '{query}' "
            f"in {duration_ms:.2f}ms (metric: {metric})"
        )

        return {
            "results": results,
            "trace": {
                "query": query,
                "metric": metric,
                "top_k": top_k,
                "score_threshold": score_threshold,
                "duration_ms": duration_ms,
                "candidates_scanned": candidates_scanned,
                "filters": {
                    "source": source.value if source else None,
                    "document_id": str(document_id) if document_id else None,
                },
            },
        }
