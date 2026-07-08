import uuid
from typing import Sequence, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.page import DocumentPage
from app.repositories.base import BaseRepository


class PageRepository(BaseRepository[DocumentPage]):
    """Repository class managing database queries for DocumentPage ORM instances."""

    def __init__(self, db_session: AsyncSession):
        super().__init__(DocumentPage, db_session)

    async def bulk_insert_pages(self, pages: List[DocumentPage]) -> None:
        """Inserts multiple DocumentPage entries in a single transaction block."""
        self.db_session.add_all(pages)
        await self.db_session.flush()

    async def get_pages_by_document(
        self, document_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> Sequence[DocumentPage]:
        """Retrieves page-level content for a document sorted by page_number, with pagination support."""
        query = (
            select(self.model)
            .where(self.model.document_id == document_id)
            .order_by(self.model.page_number.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db_session.execute(query)
        return result.scalars().all()
