"""
BM25 Retriever - Abstract interface and production implementation.

Designed for regulatory, legal, and compliance document retrieval.
Supports future migration to Elasticsearch/OpenSearch via the abstract interface.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover
    BM25Okapi = None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class IndexStatus(str, Enum):
    """Lifecycle status of a BM25 index."""
    NOT_BUILT = "not_built"
    BUILDING = "building"
    READY = "ready"
    UPDATING = "updating"
    ERROR = "error"


class Source(str, Enum):
    """Supported regulatory sources."""
    RBI = "RBI"
    SEBI = "SEBI"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BM25Document:
    """Represents a single document (chunk) stored in the BM25 index."""
    chunk_id: str
    content: str
    section_title: str = ""
    subsection_title: str = ""
    document_title: str = ""
    source: str = ""
    document_id: str = ""
    page_number: int = 0
    tokenized_content: List[str] = field(default_factory=list, repr=False)

    def to_indexable_text(self) -> str:
        """
        Produce the full text used for BM25 indexing.
        Combines content with section/subsection/document titles so that
        hierarchical metadata contributes to keyword matching.
        """
        parts = [
            self.document_title,
            self.section_title,
            self.subsection_title,
            self.content,
        ]
        return " ".join(p for p in parts if p)


@dataclass
class BM25SearchResult:
    """Single search result returned by the BM25 retriever."""
    chunk_id: str
    bm25_score: float
    section: str = ""
    subsection: str = ""
    document_title: str = ""
    source: str = ""
    document_id: str = ""
    content_preview: str = ""
    rank: int = 0


@dataclass
class BM25SearchResponse:
    """Full search response with results and telemetry."""
    query: str
    results: List[BM25SearchResult]
    total_results: int
    latency_ms: float
    average_score: float = 0.0
    filtered_count: int = 0


@dataclass
class BM25IndexStats:
    """Statistics about the current BM25 index."""
    status: IndexStatus = IndexStatus.NOT_BUILT
    total_documents: int = 0
    total_tokens: int = 0
    avg_doc_length: float = 0.0
    last_built_at: Optional[float] = None
    last_updated_at: Optional[float] = None
    index_version: int = 0


@dataclass
class BM25SearchRequest:
    """Search request with filters and thresholds."""
    query: str
    top_k: int = 10
    source_filter: Optional[List[str]] = None
    document_filter: Optional[List[str]] = None
    score_threshold: float = 0.0


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class BM25Tokenizer:
    """
    Lightweight tokenizer for BM25.
    Keeps it simple (split on whitespace + lowercase) to match rank-bm25
    expectations while being suitable for regulatory text.
    """

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Tokenize text into lowercase word tokens."""
        if not text:
            return []
        # Simple whitespace tokenization with lowercase
        # Remove common punctuation but preserve alphanumeric and hyphens
        cleaned = "".join(
            ch if ch.isalnum() or ch in (" ", "-", "_") else " "
            for ch in text
        )
        return [tok for tok in cleaned.lower().split() if tok]


# ---------------------------------------------------------------------------
# Abstract BM25 Retriever Interface
# ---------------------------------------------------------------------------

class AbstractBM25Retriever(ABC):
    """
    Abstract interface for BM25 retrieval.
    
    Implementations:
    - InMemoryBM25Retriever (rank-bm25 based, for development / small corpora)
    - ElasticsearchBM25Retriever (future migration target)
    - OpenSearchBM25Retriever (future migration target)
    
    This abstraction ensures the service layer remains decoupled from the
    underlying search engine.
    """

    @abstractmethod
    def build_index(self, documents: Sequence[BM25Document]) -> BM25IndexStats:
        """Build the BM25 index from scratch using the provided documents."""
        ...

    @abstractmethod
    def update_index(self, documents: Sequence[BM25Document]) -> BM25IndexStats:
        """Incrementally update the index with new/modified documents."""
        ...

    @abstractmethod
    def rebuild_index(self, documents: Sequence[BM25Document]) -> BM25IndexStats:
        """Rebuild the entire index from scratch."""
        ...

    @abstractmethod
    def search(self, request: BM25SearchRequest) -> BM25SearchResponse:
        """Execute a BM25 search with optional filters and thresholds."""
        ...

    @abstractmethod
    def get_index_stats(self) -> BM25IndexStats:
        """Return current index statistics."""
        ...

    @abstractmethod
    def remove_documents(self, chunk_ids: List[str]) -> BM25IndexStats:
        """Remove documents from the index by chunk ID."""
        ...

    @abstractmethod
    def clear_index(self) -> BM25IndexStats:
        """Clear the entire index."""
        ...


# ---------------------------------------------------------------------------
# In-Memory BM25 Retriever (rank-bm25)
# ---------------------------------------------------------------------------

class InMemoryBM25Retriever(AbstractBM25Retriever):
    """
    Production-grade in-memory BM25 retriever using rank-bm25.
    
    Features:
    - Multi-field indexing (content, section, subsection, document title)
    - Source filtering (RBI/SEBI)
    - Document filtering
    - Score thresholds
    - Retrieval latency tracking
    - Index statistics
    
    Designed to be replaced by Elasticsearch/OpenSearch implementation
    without changing the service layer.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        """
        Initialize the BM25 retriever.
        
        Args:
            k1: BM25 k1 parameter (term frequency saturation). Default 1.5.
            b: BM25 b parameter (length normalization). Default 0.75.
        """
        self._k1 = k1
        self._b = b
        self._tokenizer = BM25Tokenizer()
        self._bm25: Optional[BM25Okapi] = None
        self._documents: Dict[str, BM25Document] = {}
        self._corpus_tokens: List[List[str]] = []
        self._chunk_ids: List[str] = []
        self._stats = BM25IndexStats()
        logger.info(
            "InMemoryBM25Retriever initialized (k1=%.2f, b=%.2f)", k1, b
        )

    # ----- Index Management -----

    def build_index(self, documents: Sequence[BM25Document]) -> BM25IndexStats:
        """Build the BM25 index from scratch."""
        start = time.monotonic()
        self._stats.status = IndexStatus.BUILDING
        logger.info("Building BM25 index for %d documents", len(documents))

        try:
            self._documents.clear()
            self._corpus_tokens.clear()
            self._chunk_ids.clear()

            for doc in documents:
                tokenized = self._tokenizer.tokenize(doc.to_indexable_text())
                doc.tokenized_content = tokenized
                self._documents[doc.chunk_id] = doc
                self._corpus_tokens.append(tokenized)
                self._chunk_ids.append(doc.chunk_id)

            if self._corpus_tokens:
                self._bm25 = BM25Okapi(self._corpus_tokens, k1=self._k1, b=self._b)
            else:
                self._bm25 = None

            elapsed = (time.monotonic() - start) * 1000
            self._stats = BM25IndexStats(
                status=IndexStatus.READY,
                total_documents=len(self._documents),
                total_tokens=sum(len(t) for t in self._corpus_tokens),
                avg_doc_length=(
                    sum(len(t) for t in self._corpus_tokens) / len(self._corpus_tokens)
                    if self._corpus_tokens
                    else 0.0
                ),
                last_built_at=time.time(),
                last_updated_at=time.time(),
                index_version=self._stats.index_version + 1,
            )
            logger.info(
                "BM25 index built: %d docs, %d tokens, %.1f ms",
                self._stats.total_documents,
                self._stats.total_tokens,
                elapsed,
            )
            return self._stats

        except Exception as exc:
            self._stats.status = IndexStatus.ERROR
            logger.exception("Failed to build BM25 index")
            raise BM25IndexError(f"Failed to build BM25 index: {exc}") from exc

    def update_index(self, documents: Sequence[BM25Document]) -> BM25IndexStats:
        """
        Incrementally update the index with new or modified documents.
        
        For the in-memory implementation, we rebuild with the updated set
        since BM25Okapi does not support incremental adds.  The abstract
        interface, however, allows Elasticsearch/OpenSearch implementations
        to do true incremental updates.
        """
        start = time.monotonic()
        self._stats.status = IndexStatus.UPDATING
        logger.info("Updating BM25 index with %d documents", len(documents))

        try:
            for doc in documents:
                tokenized = self._tokenizer.tokenize(doc.to_indexable_text())
                doc.tokenized_content = tokenized
                if doc.chunk_id in self._documents:
                    # Replace existing
                    idx = self._chunk_ids.index(doc.chunk_id)
                    self._documents[doc.chunk_id] = doc
                    self._corpus_tokens[idx] = tokenized
                else:
                    # Add new
                    self._documents[doc.chunk_id] = doc
                    self._corpus_tokens.append(tokenized)
                    self._chunk_ids.append(doc.chunk_id)

            if self._corpus_tokens:
                self._bm25 = BM25Okapi(self._corpus_tokens, k1=self._k1, b=self._b)
            else:
                self._bm25 = None

            elapsed = (time.monotonic() - start) * 1000
            self._stats = BM25IndexStats(
                status=IndexStatus.READY,
                total_documents=len(self._documents),
                total_tokens=sum(len(t) for t in self._corpus_tokens),
                avg_doc_length=(
                    sum(len(t) for t in self._corpus_tokens) / len(self._corpus_tokens)
                    if self._corpus_tokens
                    else 0.0
                ),
                last_built_at=self._stats.last_built_at,
                last_updated_at=time.time(),
                index_version=self._stats.index_version + 1,
            )
            logger.info(
                "BM25 index updated: %d docs, %.1f ms",
                self._stats.total_documents,
                elapsed,
            )
            return self._stats

        except Exception as exc:
            self._stats.status = IndexStatus.ERROR
            logger.exception("Failed to update BM25 index")
            raise BM25IndexError(f"Failed to update BM25 index: {exc}") from exc

    def rebuild_index(self, documents: Sequence[BM25Document]) -> BM25IndexStats:
        """Rebuild the entire index from scratch."""
        logger.info("Rebuilding BM25 index from scratch")
        self._bm25 = None
        return self.build_index(documents)

    def remove_documents(self, chunk_ids: List[str]) -> BM25IndexStats:
        """Remove documents from the index by chunk ID."""
        if not chunk_ids:
            return self._stats

        logger.info("Removing %d documents from BM25 index", len(chunk_ids))
        remove_set = set(chunk_ids)

        new_docs: Dict[str, BM25Document] = {}
        new_tokens: List[List[str]] = []
        new_ids: List[str] = []

        for cid, doc in self._documents.items():
            if cid not in remove_set:
                new_docs[cid] = doc
                idx = self._chunk_ids.index(cid)
                new_tokens.append(self._corpus_tokens[idx])
                new_ids.append(cid)

        self._documents = new_docs
        self._corpus_tokens = new_tokens
        self._chunk_ids = new_ids

        if self._corpus_tokens:
            self._bm25 = BM25Okapi(self._corpus_tokens, k1=self._k1, b=self._b)
        else:
            self._bm25 = None

        self._stats = BM25IndexStats(
            status=IndexStatus.READY if self._documents else IndexStatus.NOT_BUILT,
            total_documents=len(self._documents),
            total_tokens=sum(len(t) for t in self._corpus_tokens),
            avg_doc_length=(
                sum(len(t) for t in self._corpus_tokens) / len(self._corpus_tokens)
                if self._corpus_tokens
                else 0.0
            ),
            last_built_at=self._stats.last_built_at,
            last_updated_at=time.time(),
            index_version=self._stats.index_version + 1,
        )
        return self._stats

    def clear_index(self) -> BM25IndexStats:
        """Clear the entire index."""
        logger.info("Clearing BM25 index")
        self._bm25 = None
        self._documents.clear()
        self._corpus_tokens.clear()
        self._chunk_ids.clear()
        self._stats = BM25IndexStats(status=IndexStatus.NOT_BUILT)
        return self._stats

    # ----- Search -----

    def search(self, request: BM25SearchRequest) -> BM25SearchResponse:
        """
        Execute a BM25 search with optional filters and score thresholds.
        
        Args:
            request: BM25SearchRequest with query, top_k, filters, and threshold.
            
        Returns:
            BM25SearchResponse with results and telemetry.
        """
        start = time.monotonic()

        if self._bm25 is None or not self._documents:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning("BM25 search on empty/unbuilt index")
            return BM25SearchResponse(
                query=request.query,
                results=[],
                total_results=0,
                latency_ms=elapsed,
            )

        # Tokenize query
        query_tokens = self._tokenizer.tokenize(request.query)
        if not query_tokens:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning("BM25 search with empty query tokens")
            return BM25SearchResponse(
                query=request.query,
                results=[],
                total_results=0,
                latency_ms=elapsed,
            )

        # Get raw BM25 scores for all documents
        raw_scores = self._bm25.get_scores(query_tokens)

        # Build scored results with filtering
        scored_results: List[Tuple[int, float]] = []
        filtered_count = 0

        for idx, score in enumerate(raw_scores):
            chunk_id = self._chunk_ids[idx]
            doc = self._documents[chunk_id]

            # Apply source filter
            if request.source_filter and doc.source not in request.source_filter:
                filtered_count += 1
                continue

            # Apply document filter
            if request.document_filter and doc.document_id not in request.document_filter:
                filtered_count += 1
                continue

            # Apply score threshold
            if score < request.score_threshold:
                filtered_count += 1
                continue

            scored_results.append((idx, float(score)))

        # Sort by score descending
        scored_results.sort(key=lambda x: x[1], reverse=True)

        # Take top-k
        top_results = scored_results[: request.top_k]

        # Build response
        results: List[BM25SearchResult] = []
        for rank, (idx, score) in enumerate(top_results, start=1):
            chunk_id = self._chunk_ids[idx]
            doc = self._documents[chunk_id]
            content_preview = doc.content[:200] + ("..." if len(doc.content) > 200 else "")
            results.append(
                BM25SearchResult(
                    chunk_id=chunk_id,
                    bm25_score=round(score, 4),
                    section=doc.section_title,
                    subsection=doc.subsection_title,
                    document_title=doc.document_title,
                    source=doc.source,
                    document_id=doc.document_id,
                    content_preview=content_preview,
                    rank=rank,
                )
            )

        elapsed = (time.monotonic() - start) * 1000
        avg_score = (
            sum(r.bm25_score for r in results) / len(results) if results else 0.0
        )

        logger.info(
            "BM25 search: query=%r, results=%d, filtered=%d, latency=%.1fms, avg_score=%.4f",
            request.query,
            len(results),
            filtered_count,
            elapsed,
            avg_score,
        )

        return BM25SearchResponse(
            query=request.query,
            results=results,
            total_results=len(results),
            latency_ms=round(elapsed, 2),
            average_score=round(avg_score, 4),
            filtered_count=filtered_count,
        )

    def get_index_stats(self) -> BM25IndexStats:
        """Return current index statistics."""
        return self._stats

    # ----- Convenience methods -----

    def get_scores_for_query(self, query: str) -> Dict[str, float]:
        """Get BM25 scores for all documents for a given query (debug utility)."""
        if self._bm25 is None:
            return {}
        tokens = self._tokenizer.tokenize(query)
        if not tokens:
            return {}
        scores = self._bm25.get_scores(tokens)
        return {
            self._chunk_ids[i]: float(scores[i])
            for i in range(len(self._chunk_ids))
        }


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class BM25IndexError(Exception):
    """Raised when BM25 index operations fail."""
    pass


class BM25SearchError(Exception):
    """Raised when BM25 search operations fail."""
    pass