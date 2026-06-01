import uuid
from typing import Optional, Sequence
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.document import Document, SourceEnum, StatusEnum
from app.repositories.base import BaseRepository

class DocumentRepository(BaseRepository[Document]):
    def __init__(self, db_session: AsyncSession):
        super().__init__(Document, db_session)

    async def create_document(self, document_obj: Document) -> Document:
        """Saves a new Document registry entry."""
        return await self.create(document_obj)

    async def get_document(self, document_id: uuid.UUID) -> Optional[Document]:
        """Retrieves a Document registry entry by its ID."""
        return await self.get(document_id)

    async def get_document_by_checksum(self, checksum: str) -> Optional[Document]:
        """Retrieves a Document registry entry by its checksum."""
        query = select(self.model).where(self.model.checksum == checksum)
        result = await self.db_session.execute(query)
        return result.scalars().first()

    async def list_documents(
        self, 
        source: Optional[SourceEnum] = None, 
        status: Optional[StatusEnum] = None, 
        skip: int = 0, 
        limit: int = 100
    ) -> Sequence[Document]:
        """Lists Document entries with optional filters."""
        query = select(self.model)
        if source:
            query = query.where(self.model.source == source)
        if status:
            query = query.where(self.model.status == status)
        query = query.order_by(self.model.uploaded_at.desc()).offset(skip).limit(limit)
        result = await self.db_session.execute(query)
        return result.scalars().all()

    async def update_status(self, document_id: uuid.UUID, new_status: StatusEnum) -> Optional[Document]:
        """Updates the status of a document."""
        # Using UPDATE statement with RETURNING
        query = (
            update(self.model)
            .where(self.model.id == document_id)
            .values(status=new_status)
            .returning(self.model)
        )
        result = await self.db_session.execute(query)
        return result.scalars().first()
