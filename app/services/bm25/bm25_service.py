"""
BM25 Service - High-level service for BM25 retrieval operations.

Coordinates between the retriever, index manager, and repository layers.
Provides the main API for the rest of the application to interact with BM25.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.bm25_index import BM25IndexRepository
from app.repositories.chunk import ChunkRepository
from app.services.bm25.retriever import (
    BM25Document,
    BM25SearchRequest,
    BM25SearchResponse,
    BM25SearchResult,
    BM25IndexStats,
    IndexStatus,
    InMemoryBM25Retriever,
)
from app.services.bm25.index_manager import BM25IndexManager, IndexManagerConfig

logger = logging.getLogger(__name__)


class BM25Service:
    """
    High-level BM25 service for RegIntel AI.
    
    Provides:
    - Index building from database chunks
    - Search with filtering and thresholds
    - Index lifecycle management
    - Telemetry and metrics
    
    This is the primary interface that API endpoints and other services
    should use for BM25 operations.
    """

    def __init__(
        self,
        index_manager: Optional[BM25IndexManager] = None,
        config: Optional[IndexManagerConfig] = None,
    ) -> None:
        self._config = config or IndexManagerConfig()
        self._index_manager = index_manager or BM25IndexManager(config=self._config)
        self._retriever = self._index_manager.retriever

    @property
    def index_manager(self) -> BM25IndexManager:
        """Access the index manager."""
        return self._index_manager

    @property
    def stats(self) -> BM25IndexStats:
        """Get current index statistics."""
        return self._retriever.get_index_stats()

    # ----- Index Lifecycle -----

    async def build_index_from_db(self, session: AsyncSession) -> BM25IndexStats:
        """
        Build the BM25 index from all chunks in the database.
        
        Args:
            session: Async SQLAlchemy session.
            
        Returns:
            BM25IndexStats after building.
        """
        logger.info("BM25Service: building index from database")
        chunk_repo = ChunkRepository(session)
        chunks = await chunk_repo.get_all()
        
        if not chunks:
            logger.warning("No chunks found in database to index")
            return self._retriever.get_index_stats()

        documents = self._chunks_to_documents(chunks)
        stats = self._index_manager.build_index(documents)

        # Persist metadata to database
        bm25_repo = BM25IndexRepository(session)
        vocab_size = self._compute_vocab_size(documents)
        file_path = f"{self._config.storage_dir}/{self._config.index_filename}"
        await bm25_repo.create_index_record(
            index_name=f"bm25_v{stats.index_version}",
            corpus_size=stats.total_documents,
            avg_doc_len=stats.avg_doc_length,
            vocab_size=vocab_size,
            file_path=file_path,
        )
        await session.commit()

        return stats

    async def update_index_from_db(
        self, session: AsyncSession, chunk_ids: Optional[List[str]] = None
    ) -> BM25IndexStats:
        """
        Update the BM25 index with new or modified chunks from the database.
        
        Args:
            session: Async SQLAlchemy session.
            chunk_ids: Optional list of specific chunk IDs to update.
                      If None, updates all chunks.
            
        Returns:
            BM25IndexStats after updating.
        """
        logger.info("BM25Service: updating index from database")
        chunk_repo = ChunkRepository(session)
        
        if chunk_ids:
            chunks = []
            for cid in chunk_ids:
                chunk = await chunk_repo.get_by_id(cid)
                if chunk:
                    chunks.append(chunk)
        else:
            chunks = await chunk_repo.get_all()

        if not chunks:
            logger.warning("No chunks found to update")
            return self._retriever.get_index_stats()

        documents = self._chunks_to_documents(chunks)
        stats = self._index_manager.update_index(documents)
        await session.commit()

        return stats

    async def rebuild_index_from_db(self, session: AsyncSession) -> BM25IndexStats:
        """
        Rebuild the entire BM25 index from the database.
        
        Args:
            session: Async SQLAlchemy session.
            
        Returns:
            BM25IndexStats after rebuilding.
        """
        logger.info("BM25Service: rebuilding index from database")
        self._index_manager.clear_index()
        return await self.build_index_from_db(session)

    # ----- Search -----

    def search(
        self,
        query: str,
        top_k: int = 10,
        source_filter: Optional[List[str]] = None,
        document_filter: Optional[List[str]] = None,
        score_threshold: float = 0.0,
    ) -> BM25SearchResponse:
        """
        Execute a BM25 search.
        
        Args:
            query: Search query string.
            top_k: Maximum number of results to return.
            source_filter: Optional list of sources to filter by (e.g., ["RBI", "SEBI"]).
            document_filter: Optional list of document IDs to filter by.
            score_threshold: Minimum BM25 score threshold.
            
        Returns:
            BM25SearchResponse with results and telemetry.
        """
        request = BM25SearchRequest(
            query=query,
            top_k=top_k,
            source_filter=source_filter,
            document_filter=document_filter,
            score_threshold=score_threshold,
        )
        return self._retriever.search(request)

    def search_with_defaults(self, query: str) -> BM25SearchResponse:
        """Execute a BM25 search with default parameters."""
        return self.search(query=query)

    # ----- Index Management -----

    def get_index_stats(self) -> BM25IndexStats:
        """Get current index statistics."""
        return self._retriever.get_index_stats()

    def is_index_ready(self) -> bool:
        """Check if the index is built and ready for search."""
        return self._retriever.get_index_stats().status == IndexStatus.READY

    def clear_index(self) -> BM25IndexStats:
        """Clear the entire index."""
        return self._index_manager.clear_index()

    def save_index(self) -> str:
        """Persist the current index to disk."""
        return self._index_manager.save_index()

    def load_index(self) -> BM25IndexStats:
        """Load a previously saved index from disk."""
        return self._index_manager.load_index()

    # ----- Internal Helpers -----

    @staticmethod
    def _chunks_to_documents(chunks: Sequence[Any]) -> List[BM25Document]:
        """
        Convert database chunk models to BM25Document instances.
        
        Maps the chunk hierarchy (document -> section -> subsection -> chunk)
        into BM25Document fields for multi-field indexing.
        """
        documents: List[BM25Document] = []
        for chunk in chunks:
            # Extract hierarchy information from the chunk
            section_title = ""
            subsection_title = ""
            document_title = ""
            source = ""
            document_id = ""

            # Navigate the chunk hierarchy
            if hasattr(chunk, "document") and chunk.document:
                document_title = getattr(chunk.document, "title", "") or ""
                source = getattr(chunk.document, "source", "") or ""
                document_id = str(getattr(chunk.document, "id", ""))

            if hasattr(chunk, "section") and chunk.section:
                section_title = getattr(chunk.section, "title", "") or ""
                if hasattr(chunk.section, "parent") and chunk.section.parent:
                    subsection_title = section_title
                    section_title = getattr(chunk.section.parent, "title", "") or ""

            doc = BM25Document(
                chunk_id=str(getattr(chunk, "id", "")),
                content=getattr(chunk, "content", "") or "",
                section_title=section_title,
                subsection_title=subsection_title,
                document_title=document_title,
                source=source,
                document_id=document_id,
                page_number=getattr(chunk, "page_number", 0) or 0,
            )
            documents.append(doc)

        return documents

    @staticmethod
    def _compute_vocab_size(documents: List[BM25Document]) -> int:
        """Compute the vocabulary size from a list of BM25Documents."""
        vocab = set()
        for doc in documents:
            vocab.update(doc.tokenized_content)
        return len(vocab)