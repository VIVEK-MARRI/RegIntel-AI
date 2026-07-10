"""
BM25 Index Manager - Manages the lifecycle of BM25 indices.

Handles building, updating, rebuilding, persisting, and loading BM25 indices.
Coordinates between the retriever, repository, and storage layers.
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from app.services.bm25.retriever import (
    BM25Document,
    BM25IndexStats,
    BM25IndexError,
    InMemoryBM25Retriever,
    AbstractBM25Retriever,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class IndexManagerConfig:
    """Configuration for the BM25 Index Manager."""

    storage_dir: str = "storage/bm25"
    index_filename: str = "bm25_index.pkl"
    metadata_filename: str = "bm25_metadata.json"
    k1: float = 1.5
    b: float = 0.75
    auto_persist: bool = True
    auto_load: bool = True


# ---------------------------------------------------------------------------
# Index Manager
# ---------------------------------------------------------------------------


class BM25IndexManager:
    """
    Manages the full lifecycle of BM25 indices.

    Responsibilities:
    - Build, update, rebuild indices
    - Persist indices to disk
    - Load indices from disk
    - Track index versions and statistics
    - Coordinate between retriever and repository layers

    The manager wraps an AbstractBM25Retriever, so swapping from
    InMemoryBM25Retriever to an Elasticsearch implementation only
    requires changing the retriever instance passed to the manager.
    """

    def __init__(
        self,
        retriever: Optional[AbstractBM25Retriever] = None,
        config: Optional[IndexManagerConfig] = None,
    ) -> None:
        self._config = config or IndexManagerConfig()
        self._retriever = retriever or InMemoryBM25Retriever(
            k1=self._config.k1, b=self._config.b
        )
        self._ensure_storage_dir()

        if self._config.auto_load:
            self._try_load_from_disk()

    @property
    def retriever(self) -> AbstractBM25Retriever:
        """Access the underlying BM25 retriever."""
        return self._retriever

    @property
    def stats(self) -> BM25IndexStats:
        """Get current index statistics."""
        return self._retriever.get_index_stats()

    # ----- Lifecycle Operations -----

    def build_index(self, documents: Sequence[BM25Document]) -> BM25IndexStats:
        """
        Build the BM25 index from scratch.

        Args:
            documents: Sequence of BM25Document instances to index.

        Returns:
            BM25IndexStats after building.
        """
        logger.info("IndexManager: building index with %d documents", len(documents))
        stats = self._retriever.build_index(documents)
        if self._config.auto_persist:
            self._persist_to_disk()
        return stats

    def update_index(self, documents: Sequence[BM25Document]) -> BM25IndexStats:
        """
        Incrementally update the index with new or modified documents.

        Args:
            documents: Sequence of BM25Document instances to add/update.

        Returns:
            BM25IndexStats after updating.
        """
        logger.info("IndexManager: updating index with %d documents", len(documents))
        stats = self._retriever.update_index(documents)
        if self._config.auto_persist:
            self._persist_to_disk()
        return stats

    def rebuild_index(self, documents: Sequence[BM25Document]) -> BM25IndexStats:
        """
        Rebuild the entire index from scratch.

        Args:
            documents: Sequence of BM25Document instances to index.

        Returns:
            BM25IndexStats after rebuilding.
        """
        logger.info("IndexManager: rebuilding index with %d documents", len(documents))
        stats = self._retriever.rebuild_index(documents)
        if self._config.auto_persist:
            self._persist_to_disk()
        return stats

    def remove_documents(self, chunk_ids: List[str]) -> BM25IndexStats:
        """Remove documents from the index by chunk ID."""
        logger.info("IndexManager: removing %d documents", len(chunk_ids))
        stats = self._retriever.remove_documents(chunk_ids)
        if self._config.auto_persist:
            self._persist_to_disk()
        return stats

    def clear_index(self) -> BM25IndexStats:
        """Clear the entire index."""
        logger.info("IndexManager: clearing index")
        stats = self._retriever.clear_index()
        if self._config.auto_persist:
            self._persist_to_disk()
        return stats

    # ----- Persistence -----

    def save_index(self) -> str:
        """
        Persist the current index to disk.

        Returns:
            Path to the saved index file.
        """
        return self._persist_to_disk()

    def load_index(self) -> BM25IndexStats:
        """
        Load a previously saved index from disk.

        Returns:
            BM25IndexStats after loading.
        """
        return self._load_from_disk()

    # ----- Internal -----

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        Path(self._config.storage_dir).mkdir(parents=True, exist_ok=True)

    def _persist_to_disk(self) -> str:
        """Persist the retriever state to disk."""
        if not isinstance(self._retriever, InMemoryBM25Retriever):
            logger.warning("Persistence only supported for InMemoryBM25Retriever")
            return ""

        storage_path = Path(self._config.storage_dir)
        index_path = storage_path / self._config.index_filename
        metadata_path = storage_path / self._config.metadata_filename

        try:
            # Save the retriever state via pickle
            state = {
                "documents": self._retriever._documents,
                "corpus_tokens": self._retriever._corpus_tokens,
                "chunk_ids": self._retriever._chunk_ids,
                "stats": self._retriever._stats,
                "k1": self._retriever._k1,
                "b": self._retriever._b,
            }
            with open(index_path, "wb") as f:
                pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)

            # Save metadata as JSON for human readability
            stats = self._retriever._stats
            metadata = {
                "status": stats.status.value,
                "total_documents": stats.total_documents,
                "total_tokens": stats.total_tokens,
                "avg_doc_length": stats.avg_doc_length,
                "last_built_at": stats.last_built_at,
                "last_updated_at": stats.last_updated_at,
                "index_version": stats.index_version,
                "k1": self._retriever._k1,
                "b": self._retriever._b,
            }
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.info(
                "BM25 index persisted to %s (version %d, %d docs)",
                index_path,
                stats.index_version,
                stats.total_documents,
            )
            return str(index_path)

        except Exception as exc:
            logger.exception("Failed to persist BM25 index")
            raise BM25IndexError(f"Failed to persist index: {exc}") from exc

    def _load_from_disk(self) -> BM25IndexStats:
        """Load the retriever state from disk."""
        if not isinstance(self._retriever, InMemoryBM25Retriever):
            logger.warning("Loading only supported for InMemoryBM25Retriever")
            return self._retriever.get_index_stats()

        storage_path = Path(self._config.storage_dir)
        index_path = storage_path / self._config.index_filename

        if not index_path.exists():
            logger.info("No persisted BM25 index found at %s", index_path)
            return self._retriever.get_index_stats()

        try:
            with open(index_path, "rb") as f:
                # Path is hardcoded storage/bm25/bm25_index.pkl from IndexManagerConfig defaults (lines 37-38); never user-influenced
                state = pickle.load(f)  # nosec B301

            self._retriever._documents = state["documents"]
            self._retriever._corpus_tokens = state["corpus_tokens"]
            self._retriever._chunk_ids = state["chunk_ids"]
            self._retriever._stats = state["stats"]

            # Rebuild the BM25Okapi object from loaded tokens
            if self._retriever._corpus_tokens:
                from rank_bm25 import BM25Okapi

                self._retriever._bm25 = BM25Okapi(
                    self._retriever._corpus_tokens,
                    k1=state.get("k1", 1.5),
                    b=state.get("b", 0.75),
                )
            else:
                self._retriever._bm25 = None

            stats = self._retriever._stats
            logger.info(
                "BM25 index loaded from %s (version %d, %d docs)",
                index_path,
                stats.index_version,
                stats.total_documents,
            )
            return stats

        except Exception as exc:
            logger.exception("Failed to load BM25 index")
            raise BM25IndexError(f"Failed to load index: {exc}") from exc

    def _try_load_from_disk(self) -> None:
        """Attempt to load index from disk on startup."""
        try:
            self._load_from_disk()
        except BM25IndexError:
            logger.info("No valid persisted index found; starting fresh")
        except Exception:
            logger.warning("Could not auto-load index; starting fresh", exc_info=True)
