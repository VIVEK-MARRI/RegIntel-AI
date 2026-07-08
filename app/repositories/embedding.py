import uuid
from typing import Optional, Dict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chunk import ChunkEmbedding, EmbeddingStatusEnum, DocumentChunk
from app.repositories.base import BaseRepository

class ChunkEmbeddingRepository(BaseRepository[ChunkEmbedding]):
    """Repository managing database CRUD operations for ChunkEmbedding."""

    def __init__(self, db_session: AsyncSession):
        super().__init__(ChunkEmbedding, db_session)

    async def get_embedding(self, chunk_id: uuid.UUID, embedding_model: str) -> Optional[ChunkEmbedding]:
        """Retrieves a ChunkEmbedding entry by its associated chunk ID and model name."""
        stmt = select(ChunkEmbedding).where(
            ChunkEmbedding.chunk_id == chunk_id,
            ChunkEmbedding.embedding_model == embedding_model
        )
        result = await self.db_session.execute(stmt)
        return result.scalars().first()

    async def save_embedding(
        self,
        chunk_id: uuid.UUID,
        embedding: list[float],
        embedding_model: str,
        embedding_dimension: int
    ) -> ChunkEmbedding:
        """Saves a single embedding (upserting if one already exists for the chunk and model)."""
        existing = await self.get_embedding(chunk_id, embedding_model)
        if existing:
            existing.embedding = embedding
            existing.embedding_dimension = embedding_dimension
            existing.status = EmbeddingStatusEnum.COMPLETED
            existing.error_message = None
            self.db_session.add(existing)
            await self.db_session.flush()
            return existing

        new_emb = ChunkEmbedding(
            chunk_id=chunk_id,
            embedding=embedding,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            status=EmbeddingStatusEnum.COMPLETED
        )
        return await self.create(new_emb)

    async def save_embeddings_bulk(self, embeddings_data: list[dict]) -> None:
        """Bulk inserts or updates (upserts) embeddings."""
        if not embeddings_data:
            return

        from sqlalchemy.dialects.postgresql import insert
        from sqlalchemy import func

        stmt = insert(ChunkEmbedding).values(embeddings_data)
        update_dict = {
            "embedding": stmt.excluded.embedding,
            "embedding_dimension": stmt.excluded.embedding_dimension,
            "status": stmt.excluded.status,
            "error_message": stmt.excluded.error_message,
            "updated_at": func.now()
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["chunk_id", "embedding_model"],
            set_=update_dict
        )
        await self.db_session.execute(stmt)
        await self.db_session.flush()

    async def delete_embeddings(self, chunk_id: uuid.UUID, embedding_model: Optional[str] = None) -> None:
        """Deletes embeddings for a chunk, optionally filtered by model."""
        from sqlalchemy import delete
        stmt = delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id == chunk_id)
        if embedding_model:
            stmt = stmt.where(ChunkEmbedding.embedding_model == embedding_model)
        await self.db_session.execute(stmt)
        await self.db_session.flush()

    async def upsert_embedding(
        self,
        chunk_id: uuid.UUID,
        status: EmbeddingStatusEnum,
        embedding_model: str,
        embedding_dimension: int,
        embedding: Optional[list[float]] = None,
        error_message: Optional[str] = None
    ) -> ChunkEmbedding:
        """Upserts a ChunkEmbedding entry."""
        existing = await self.get_embedding(chunk_id, embedding_model)
        if existing:
            existing.status = status
            existing.embedding = embedding
            existing.embedding_dimension = embedding_dimension
            existing.error_message = error_message
            self.db_session.add(existing)
            await self.db_session.flush()
            return existing
        
        new_emb = ChunkEmbedding(
            chunk_id=chunk_id,
            embedding=embedding,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            status=status,
            error_message=error_message
        )
        return await self.create(new_emb)

    async def get_document_embeddings_status(self, document_id: uuid.UUID, embedding_model: Optional[str] = None) -> Dict[str, int]:
        """Calculates counts of chunk embeddings group by status for a document."""
        # Query count of embeddings group by status
        query = (
            select(ChunkEmbedding.status, func.count(ChunkEmbedding.chunk_id))
            .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .where(DocumentChunk.document_id == document_id)
        )
        if embedding_model:
            query = query.where(ChunkEmbedding.embedding_model == embedding_model)
        query = query.group_by(ChunkEmbedding.status)
        
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

    async def get_embeddings_by_document(
        self, document_id: uuid.UUID, embedding_model: Optional[str] = None
    ) -> list[ChunkEmbedding]:
        """Retrieves all ChunkEmbedding records for chunks belonging to a document."""
        query = (
            select(ChunkEmbedding)
            .join(DocumentChunk, DocumentChunk.id == ChunkEmbedding.chunk_id)
            .where(DocumentChunk.document_id == document_id)
        )
        if embedding_model:
            query = query.where(ChunkEmbedding.embedding_model == embedding_model)
        result = await self.db_session.execute(query)
        return list(result.scalars().all())
