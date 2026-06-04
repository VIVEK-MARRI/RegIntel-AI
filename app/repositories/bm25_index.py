"""
BM25 Index Repository - Database layer for BM25 index metadata.

Stores and retrieves BM25 index metadata from the database.
The actual index data (tokenized corpus) is managed by the Index Manager
and persisted to disk separately.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bm25 import BM25IndexMetadata
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class BM25IndexRepository(BaseRepository[BM25IndexMetadata]):
    """
    Repository for BM25 index metadata.
    
    Stores index metadata (corpus size, avg doc length, vocab size,
    file path, active status) in the database for tracking and auditing.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, BM25IndexMetadata)

    async def get_active_index(self) -> Optional[BM25IndexMetadata]:
        """Get the currently active BM25 index metadata."""
        stmt = select(BM25IndexMetadata).where(
            BM25IndexMetadata.is_active == True  # noqa: E712
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, index_name: str) -> Optional[BM25IndexMetadata]:
        """Get BM25 index metadata by name."""
        stmt = select(BM25IndexMetadata).where(
            BM25IndexMetadata.index_name == index_name
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def deactivate_all(self) -> None:
        """Deactivate all BM25 indices."""
        stmt = select(BM25IndexMetadata).where(
            BM25IndexMetadata.is_active == True  # noqa: E712
        )
        result = await self._session.execute(stmt)
        active_indices = result.scalars().all()
        for idx in active_indices:
            idx.is_active = False
        await self._session.flush()
        logger.info("Deactivated %d BM25 indices", len(active_indices))

    async def create_index_record(
        self,
        index_name: str,
        corpus_size: int,
        avg_doc_len: float,
        vocab_size: int,
        file_path: str,
    ) -> BM25IndexMetadata:
        """
        Create a new BM25 index metadata record.
        
        Deactivates all existing indices before creating the new one.
        """
        await self.deactivate_all()
        record = BM25IndexMetadata(
            index_name=index_name,
            corpus_size=corpus_size,
            avg_doc_len=avg_doc_len,
            vocab_size=vocab_size,
            file_path=file_path,
            is_active=True,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        logger.info(
            "Created BM25 index record: %s (corpus=%d, avg_len=%.1f, vocab=%d)",
            index_name,
            corpus_size,
            avg_doc_len,
            vocab_size,
        )
        return record