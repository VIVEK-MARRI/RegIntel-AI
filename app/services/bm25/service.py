import os
import re
import time
import pickle
import uuid
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover
    BM25Okapi = None

from app.core.config import settings
from app.models.document import Document, SourceEnum
from app.models.chunk import DocumentChunk
from app.models.bm25 import BM25IndexMetadata
from app.repositories.bm25 import BM25IndexMetadataRepository
from app.services.bm25.base import BM25Retriever

logger = logging.getLogger(__name__)

# Stopwords set for regulatory tokenization
STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "aren",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can",
    "couldn",
    "did",
    "didn",
    "do",
    "does",
    "doesn",
    "doing",
    "don",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "hadn",
    "has",
    "hasn",
    "have",
    "haven",
    "having",
    "he",
    "her",
    "here",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "isn",
    "it",
    "its",
    "itself",
    "just",
    "me",
    "more",
    "most",
    "mustn",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "now",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "re",
    "s",
    "same",
    "shan",
    "she",
    "should",
    "shouldn",
    "so",
    "some",
    "such",
    "t",
    "than",
    "that",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "wasn",
    "we",
    "were",
    "weren",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "will",
    "with",
    "won",
    "wouldn",
    "y",
    "you",
    "your",
    "yours",
    "yourself",
    "yourselves",
}


def clean_tokenize(text: str) -> List[str]:
    """Applies lowercase normalization, matches word tokens, and filters stopwords."""
    if not text:
        return []
    # Match alphanumeric sequences (words)
    tokens = re.findall(r"\w+", text.lower(), re.UNICODE)
    return [t for t in tokens if t not in STOPWORDS]


class BM25IndexManager:
    """Manages creation, serialization, updates, and rebuild operations for BM25 indexes."""

    def __init__(self, db_session: AsyncSession, storage_dir: Optional[str] = None):
        self.db_session = db_session
        self.metadata_repo = BM25IndexMetadataRepository(db_session)
        self.storage_dir = storage_dir or os.path.join(settings.STORAGE_ROOT, "bm25")
        os.makedirs(self.storage_dir, exist_ok=True)

    def _get_corpus_document(self, chunk: DocumentChunk) -> str:
        """Concatenates chunk text and title/section metadata for keyword search indexing."""
        title = chunk.document.title if chunk.document else ""
        return f"{title} {chunk.section} {chunk.subsection} {chunk.content}"

    async def build_index(self, index_name: str = "default_bm25") -> str:
        """Fetches all registered chunks, builds the BM25 index, and serializes it to disk."""
        logger.info("Initializing BM25 index build...")

        # Query all chunks including document titles
        stmt = select(DocumentChunk).options(selectinload(DocumentChunk.document))
        res = await self.db_session.execute(stmt)
        chunks = res.scalars().all()

        if not chunks:
            logger.warning("No chunks found in database. BM25 index will be empty.")
            return ""

        corpus_texts = [self._get_corpus_document(c) for c in chunks]
        tokenized_corpus = [clean_tokenize(doc) for doc in corpus_texts]

        # Initialize rank-bm25 engine
        bm25_engine = BM25Okapi(tokenized_corpus)
        chunk_ids = [str(c.id) for c in chunks]

        # Serialize index and mapping metadata
        filepath = os.path.join(self.storage_dir, f"{index_name}.pkl")
        payload = {"bm25": bm25_engine, "chunk_ids": chunk_ids}
        with open(filepath, "wb") as f:
            pickle.dump(payload, f)

        # Calculate statistics
        vocab = set()
        for doc in tokenized_corpus:
            vocab.update(doc)

        corpus_size = len(chunks)
        avg_doc_len = bm25_engine.avgdl
        vocab_size = len(vocab)

        # Persist index metadata details in DB (upsert based on index_name)
        stmt_exist = select(BM25IndexMetadata).where(
            BM25IndexMetadata.index_name == index_name
        )
        existing_res = await self.db_session.execute(stmt_exist)
        meta = existing_res.scalars().first()

        if meta:
            meta.corpus_size = corpus_size
            meta.avg_doc_len = avg_doc_len
            meta.vocab_size = vocab_size
            meta.file_path = filepath
            meta.is_active = True
            self.db_session.add(meta)
        else:
            await self.metadata_repo.deactivate_all()
            meta = BM25IndexMetadata(
                index_name=index_name,
                corpus_size=corpus_size,
                avg_doc_len=avg_doc_len,
                vocab_size=vocab_size,
                file_path=filepath,
                is_active=True,
            )
            await self.metadata_repo.create(meta)
        await self.db_session.commit()

        logger.info(
            f"Successfully built and saved BM25 index to {filepath}. "
            f"Corpus size: {corpus_size}, Avg doc len: {avg_doc_len:.2f}, Vocab size: {vocab_size}"
        )
        return filepath

    async def update_index(self) -> bool:
        """Updates the active BM25 index if new un-indexed chunks are found in the database."""
        active_meta = await self.metadata_repo.get_active_metadata()
        if not active_meta:
            await self.build_index()
            return True

        # Check total chunk count in DB
        chunk_count_stmt = select(func.count(DocumentChunk.id))
        count_res = await self.db_session.execute(chunk_count_stmt)
        total_chunks = count_res.scalar() or 0

        # If DB count equals corpus size, index is already up-to-date
        if total_chunks == active_meta.corpus_size:
            logger.info("BM25 index is up to date. No updates needed.")
            return False

        # Rebuild index to recalculate globals (IDF/averages) correctly
        logger.info(
            f"New chunks detected ({total_chunks} vs {active_meta.corpus_size}). Rebuilding index..."
        )
        await self.build_index(active_meta.index_name)
        return True

    async def rebuild_index(self) -> None:
        """Cleans and reconstructs the active BM25 index from database records."""
        active_meta = await self.metadata_repo.get_active_metadata()
        index_name = active_meta.index_name if active_meta else "default_bm25"
        await self.build_index(index_name)


class BM25RetrieverService(BM25Retriever):
    """Provides keyword-based document chunk search scoring and metadata filtering using rank-bm25."""

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self.metadata_repo = BM25IndexMetadataRepository(db_session)

        # In-memory index cache
        self._cached_metadata_id: Optional[uuid.UUID] = None
        self._cached_bm25: Optional[BM25Okapi] = None
        self._cached_chunk_ids: List[str] = []
        self._cached_chunk_id_to_idx: Dict[str, int] = {}

    async def _refresh_cache_if_needed(self) -> bool:
        """Reloads serialized index file if index metadata changes in database."""
        active_meta = await self.metadata_repo.get_active_metadata()
        if not active_meta:
            self._cached_bm25 = None
            self._cached_chunk_ids = []
            self._cached_chunk_id_to_idx = {}
            self._cached_metadata_id = None
            return False

        if self._cached_metadata_id == active_meta.id and self._cached_bm25 is not None:
            return True

        # Load serialized index payload
        filepath = active_meta.file_path
        if not os.path.exists(filepath):
            logger.warning(f"BM25 index file not found at {filepath}")
            return False

        try:
            with open(filepath, "rb") as f:
                payload = pickle.load(f)

            self._cached_bm25 = payload["bm25"]
            self._cached_chunk_ids = payload["chunk_ids"]
            self._cached_chunk_id_to_idx = {
                cid: idx for idx, cid in enumerate(self._cached_chunk_ids)
            }
            self._cached_metadata_id = active_meta.id
            logger.info(
                f"Loaded BM25 index '{active_meta.index_name}' successfully into memory cache."
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to load BM25 index file {filepath}: {e}", exc_info=True
            )
            return False

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
        source: Optional[SourceEnum] = None,
        document_id: Optional[uuid.UUID] = None,
    ) -> List[Dict[str, Any]]:
        """Scores documents matching query and filters candidates by metadata constraints and score threshold."""
        start_time = time.perf_counter()

        if not query or not query.strip():
            return []

        # Refresh index cache
        has_index = await self._refresh_cache_if_needed()
        if not has_index or self._cached_bm25 is None:
            logger.warning("Retrieval requested but no active BM25 index is available.")
            return []

        # 1. Fetch matching candidate chunks from database to apply filters efficiently
        candidate_stmt = select(DocumentChunk).options(
            selectinload(DocumentChunk.document)
        )

        # Apply filters in database query
        if source or document_id:
            candidate_stmt = candidate_stmt.join(
                Document, Document.id == DocumentChunk.document_id
            )
            if source:
                candidate_stmt = candidate_stmt.where(Document.source == source)
            if document_id:
                candidate_stmt = candidate_stmt.where(
                    DocumentChunk.document_id == document_id
                )

        candidate_res = await self.db_session.execute(candidate_stmt)
        candidates = candidate_res.scalars().all()

        if not candidates:
            return []

        # 2. Tokenize search query and compute document scores
        tokenized_query = clean_tokenize(query)
        all_scores = self._cached_bm25.get_scores(tokenized_query)

        scored_results = []
        for chunk in candidates:
            chunk_str = str(chunk.id)
            if chunk_str not in self._cached_chunk_id_to_idx:
                # Chunk exists in DB but not in the active index (rebuild/update needed)
                continue

            idx = self._cached_chunk_id_to_idx[chunk_str]
            score = float(all_scores[idx])

            if score >= score_threshold:
                scored_results.append((chunk, score))

        # 3. Deterministic Sorting: score desc, chunk id asc secondary
        scored_results.sort(key=lambda x: (-x[1], x[0].id))
        top_results = scored_results[:top_k]

        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"BM25 Retrieval completed in {duration_ms:.2f}ms. "
            f"Query: '{query}'. Scanned {len(scored_results)} candidates. Top-K: {len(top_results)}."
        )

        # 4. Serialize matching items
        serialized = []
        for chunk, score in top_results:
            serialized.append(
                {
                    "chunk_id": str(chunk.id),
                    "score": score,
                    "section": chunk.section,
                    "subsection": chunk.subsection,
                    "content": chunk.content,
                    "metadata": {
                        "document_id": str(chunk.document_id),
                        "document_title": chunk.document.title
                        if chunk.document
                        else "",
                        "page_number": chunk.page_number,
                        "token_count": chunk.token_count,
                    },
                }
            )
        return serialized
