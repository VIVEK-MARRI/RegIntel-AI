import uuid
from typing import Optional, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chunk import ChunkEmbedding, EmbeddingStatusEnum, DocumentChunk
from app.repositories.base import BaseRepository

class ChunkEmbeddingRepository(BaseRepository[ChunkEmbedding]):
    """Repository managing database CRUD operations for ChunkEmbedding."""

    def __init__(self, db_session: AsyncSession):
        super().__init__(ChunkEmbedding, db_session)

    async def get_embedding(self, chunk_id: uuid.UUID) -> Optional[ChunkEmbedding]:
        """Retrieves a ChunkEmbedding entry by its associated chunk ID."""
        return await self.get(chunk_id)

    async def upsert_embedding(
        self,
        chunk_id: uuid.UUID,
        status: EmbeddingStatusEnum,
        embedding: Optional[list[float]] = None,
        error_message: Optional[str] = None
    ) -> ChunkEmbedding:
        """Upserts a ChunkEmbedding entry."""
        existing = await self.get_embedding(chunk_id)
        if existing:
            existing.status = status
            existing.embedding = embedding
            existing.error_message = error_message
            self.db_session.add(existing)
            await self.db_session.flush()
            return existing
        
        new_emb = ChunkEmbedding(
            chunk_id=chunk_id,
            embedding=embedding,
            status=status,
            error_message=error_message
        )
        return await self.create(new_emb)

    async def get_document_embeddings_status(self, document_id: uuid.UUID) -> Dict[str, int]:
        """Calculates counts of chunk embeddings group by status for a document."""
        # Query count of embeddings group by status
        query = (
            select(ChunkEmbedding.status, func.count(ChunkEmbedding.chunk_id))
            .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .where(DocumentChunk.document_id == document_id)
            .group_by(ChunkEmbedding.status)
        )
        result = await self.db_session.execute(query)
        
        counts = {
            EmbeddingStatusEnum.PENDING.value: 0,
            EmbeddingStatusEnum.PROCESSING.value: 0,
            EmbeddingStatusEnum.COMPLETED.value: 0,
            EmbeddingStatusEnum.FAILED.value: 0
        }
        
        for row in result.all():
            status_val, count = row
            # status_val could be an enum object, extract string value
            val = status_val.value if hasattr(status_val, "value") else str(status_val)
            counts[val] = count
            
        return counts
