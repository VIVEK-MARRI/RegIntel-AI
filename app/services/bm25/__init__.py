"""
BM25 Retrieval Engine for RegIntel AI.

Provides keyword-based retrieval optimized for regulatory, legal,
and compliance documents.
"""

from app.services.bm25.retriever import (
    AbstractBM25Retriever,
    BM25Document,
    BM25IndexError,
    BM25IndexStats,
    BM25SearchError,
    BM25SearchRequest,
    BM25SearchResponse,
    BM25SearchResult,
    BM25Tokenizer,
    InMemoryBM25Retriever,
    IndexStatus,
    Source,
)
from app.services.bm25.index_manager import BM25IndexManager, IndexManagerConfig
from app.services.bm25.bm25_service import BM25Service

__all__ = [
    "AbstractBM25Retriever",
    "BM25Document",
    "BM25IndexError",
    "BM25IndexManager",
    "BM25IndexStats",
    "BM25SearchError",
    "BM25SearchRequest",
    "BM25SearchResponse",
    "BM25SearchResult",
    "BM25Service",
    "BM25Tokenizer",
    "InMemoryBM25Retriever",
    "IndexManagerConfig",
    "IndexStatus",
    "Source",
]
