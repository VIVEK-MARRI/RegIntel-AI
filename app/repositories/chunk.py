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

    async def get_all(self) -> Sequence[DocumentChunk]:
        """Fetch all DocumentChunk entries."""
        query = select(self.model)
        result = await self.db_session.execute(query)
        return result.scalars().all()

    async def list_chunks(
        self,
        document_id: Optional[uuid.UUID] = None,
        section: Optional[str] = None,
        subsection: Optional[str] = None,
        sort_by: str = "page_number",
        sort_order: str = "asc",
        skip: int = 0,
        limit: int = 100
    ) -> Sequence[DocumentChunk]:
        """Lists DocumentChunk entries with optional filters, search, and dynamic sorting."""
        query = select(self.model)
        
        if document_id:
            query = query.where(self.model.document_id == document_id)
        if section:
            query = query.where(self.model.section.ilike(f"%{section}%"))
        if subsection:
            query = query.where(self.model.subsection.ilike(f"%{subsection}%"))
            
        # Apply sorting dynamically
        sort_col = getattr(self.model, sort_by, self.model.page_number)
        if sort_order == "desc":
            query = query.order_by(sort_col.desc(), self.model.id.desc())
        else:
            query = query.order_by(sort_col.asc(), self.model.id.asc())
            
        query = query.offset(skip).limit(limit)
        result = await self.db_session.execute(query)
        return result.scalars().all()

    async def get_document_chunks(
        self, 
        document_id: uuid.UUID, 
        section: Optional[str] = None,
        subsection: Optional[str] = None,
        sort_by: str = "page_number",
        sort_order: str = "asc",
        skip: int = 0, 
        limit: int = 100
    ) -> Sequence[DocumentChunk]:
        """Retrieves a paginated sequence of chunks belonging to a document, with optional filters and sorting."""
        return await self.list_chunks(
            document_id=document_id,
            section=section,
            subsection=subsection,
            sort_by=sort_by,
            sort_order=sort_order,
            skip=skip,
            limit=limit
        )
