import uuid
from typing import Optional, Sequence, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.chunk import DocumentChunk
from app.repositories.base import BaseRepository

class ChunkRepository(BaseRepository[DocumentChunk]):
    """Repository managing database CRUD operations for DocumentChunk."""

    def __init__(self, db_session: AsyncSession):
        super().__init__(DocumentChunk, db_session)

    async def create_chunk(self, chunk: DocumentChunk) -> DocumentChunk:
        """Saves a single DocumentChunk record to the database."""
        return await self.create(chunk)

    async def create_chunks_bulk(self, chunks: List[DocumentChunk]) -> None:
        """Inserts multiple DocumentChunk entries in a single transaction block."""
        self.db_session.add_all(chunks)
        await self.db_session.flush()

    async def get_chunk(self, chunk_id: uuid.UUID) -> Optional[DocumentChunk]:
        """Retrieves a single chunk by its ID."""
        return await self.get(chunk_id)

    async def get_document_chunks(
        self, 
        document_id: uuid.UUID, 
        skip: int = 0, 
        limit: int = 100
    ) -> Sequence[DocumentChunk]:
        """Retrieves a paginated sequence of chunks belonging to a document, sorted by page_number."""
        query = (
            select(self.model)
            .where(self.model.document_id == document_id)
            .order_by(self.model.page_number.asc(), self.model.id.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(query)
        return result.scalars().all()
