from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import BaseRepository
from app.models.bm25 import BM25IndexMetadata


class BM25IndexMetadataRepository(BaseRepository[BM25IndexMetadata]):
    """Repository managing database CRUD operations for BM25IndexMetadata."""

    def __init__(self, db_session: AsyncSession):
        super().__init__(BM25IndexMetadata, db_session)

    async def get_active_metadata(self) -> Optional[BM25IndexMetadata]:
        """Retrieves the active BM25 index metadata if it exists."""
        stmt = (
            select(BM25IndexMetadata)
            .where(BM25IndexMetadata.is_active == True)
            .order_by(BM25IndexMetadata.updated_at.desc())
        )
        result = await self.db_session.execute(stmt)
        return result.scalars().first()

    async def deactivate_all(self) -> None:
        """Deactivates all BM25 index metadata records (setting is_active to False)."""
        stmt = (
            update(BM25IndexMetadata)
            .where(BM25IndexMetadata.is_active == True)
            .values(is_active=False)
        )
        await self.db_session.execute(stmt)
        await self.db_session.flush()
