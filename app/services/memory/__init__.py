"""Module 6.3 — Memory Layer.

Provides:

* :class:`MemoryStore` — the abstract interface (Repository pattern).
* :class:`InMemoryMemoryStore` — thread-safe in-process store with
  JSONL persistence.
* :class:`MemoryRepository` — business-rule layer on top of the store
  (expiration, ranking, deduplication).
* :class:`MemoryManager` — orchestrates memory lifecycle (create,
  search, compress, expire).
* :class:`MemoryService` — top-level service exposed via DI.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.core.config import settings
from app.schemas.conversation import Message
from app.schemas.memory import (
    CreateMemoryRequest,
    MemoryContext,
    MemoryEntry,
    MemoryQuery,
    MemoryScope,
    MemorySearchResult,
    MemoryType,
)
from app.services.citation.mapper import token_overlap

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)


# ─── Stopword list (minimal) ──────────────────────────────────────────────


_STOPWORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "in",
    "on", "at", "by", "for", "with", "to", "from", "as", "is", "are", "was",
    "were", "be", "been", "being", "this", "that", "these", "those", "it",
    "its", "i", "you", "he", "she", "we", "they", "them", "us", "me", "my",
    "your", "his", "her", "their", "our", "have", "has", "had", "do", "does",
    "did", "can", "could", "will", "would", "should", "may", "might", "shall",
    "not", "no", "yes", "what", "which", "who", "whom", "how", "when", "where",
    "why", "about", "into", "out", "up", "down", "over", "under", "again",
    "further", "than", "so", "such", "any", "all", "some", "most", "more",
    "less", "much", "many", "few", "each", "every", "other", "another",
}


def _tokenise(text: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "") if t.lower() not in _STOPWORDS]


# ─── Store interface ──────────────────────────────────────────────────────


class MemoryStore:
    """Abstract memory store (Repository pattern)."""

    def add(self, entry: MemoryEntry) -> None: ...
    def get(self, memory_id: str) -> Optional[MemoryEntry]: ...
    def update(self, entry: MemoryEntry) -> None: ...
    def delete(self, memory_id: str) -> bool: ...
    def all(self) -> List[MemoryEntry]: ...
    def reset(self) -> None: ...


# ─── In-memory store ──────────────────────────────────────────────────────


class InMemoryMemoryStore(MemoryStore):
    """Thread-safe in-memory store with optional JSONL persistence."""

    def __init__(self, *, persist_path: Optional[Path] = None) -> None:
        self._entries: Dict[str, MemoryEntry] = {}
        self._lock = threading.RLock()
        self._persist_path = persist_path
        if self._persist_path and self._persist_path.exists():
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        try:
            for line in self._persist_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                entry = MemoryEntry.model_validate(raw)
                self._entries[entry.memory_id] = entry
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load memory store from disk: %s", exc)

    def _persist(self, entry: MemoryEntry) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persist_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.model_dump(mode="json")) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to persist memory entry: %s", exc)

    def add(self, entry: MemoryEntry) -> None:
        with self._lock:
            self._entries[entry.memory_id] = entry
        self._persist(entry)

    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        with self._lock:
            return self._entries.get(memory_id)

    def update(self, entry: MemoryEntry) -> None:
        with self._lock:
            self._entries[entry.memory_id] = entry
        self._persist(entry)

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            return self._entries.pop(memory_id, None) is not None

    def all(self) -> List[MemoryEntry]:
        with self._lock:
            return list(self._entries.values())

    def reset(self) -> None:
        with self._lock:
            self._entries.clear()


# ─── Repository (business rules on top of the store) ─────────────────────


class MemoryRepository:
    """Business-rule layer on top of a :class:`MemoryStore`."""

    def __init__(self, *, store: MemoryStore) -> None:
        self.store = store

    # ── CRUD ────────────────────────────────────────────────────────────

    def create(self, request: CreateMemoryRequest) -> MemoryEntry:
        now = datetime.now(timezone.utc)
        entry = MemoryEntry(
            memory_type=request.memory_type,
            scope=request.scope,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            content=request.content,
            embedding_text=request.content,
            tags=list(request.tags),
            metadata=dict(request.metadata),
            created_at=now,
            updated_at=now,
            ttl_seconds=request.ttl_seconds,
            expires_at=_expiry_from_ttl(now, request.ttl_seconds),
            pinned=request.pinned,
        )
        self.store.add(entry)
        return entry

    def create_raw(
        self,
        *,
        memory_type: MemoryType,
        content: str,
        scope: MemoryScope = MemoryScope.USER,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None,
        pinned: bool = False,
    ) -> MemoryEntry:
        """Lower-level create (used by the manager to record
        retrieval memories derived from orchestrator responses)."""
        request = CreateMemoryRequest(
            memory_type=memory_type,
            content=content,
            scope=scope,
            user_id=user_id,
            conversation_id=conversation_id,
            tags=tags or [],
            metadata=metadata or {},
            ttl_seconds=ttl_seconds,
            pinned=pinned,
        )
        return self.create(request)

    def get(self, memory_id: str) -> Optional[MemoryEntry]:
        return self.store.get(memory_id)

    def update(self, entry: MemoryEntry) -> None:
        entry.updated_at = datetime.now(timezone.utc)
        self.store.update(entry)

    def delete(self, memory_id: str) -> bool:
        return self.store.delete(memory_id)

    def all(self) -> List[MemoryEntry]:
        return self.store.all()

    # ── Queries ─────────────────────────────────────────────────────────

    def search(self, query: MemoryQuery) -> List[MemorySearchResult]:
        now = datetime.now(timezone.utc)
        candidates: List[MemoryEntry] = []
        for entry in self.store.all():
            if not query.include_expired and _is_expired(entry, now):
                continue
            if query.memory_types and entry.memory_type not in query.memory_types:
                continue
            if query.user_id and entry.user_id != query.user_id:
                continue
            if query.conversation_id and entry.conversation_id != query.conversation_id:
                continue
            if query.tags:
                if not all(t in entry.tags for t in query.tags):
                    continue
            candidates.append(entry)
        # Rank.
        query_tokens = _tokenise(query.query or "")
        scored: List[Tuple[MemoryEntry, float, List[str]]] = []
        for entry in candidates:
            score, terms = _score_entry(entry, query_tokens, query.query or "")
            if score < query.min_relevance:
                continue
            scored.append((entry, score, terms))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: query.top_k]
        # Update relevance / access metadata.
        results: List[MemorySearchResult] = []
        for entry, score, terms in top:
            entry.relevance_score = score
            entry.access_count += 1
            entry.last_accessed_at = now
            self.store.update(entry)
            results.append(
                MemorySearchResult(entry=entry, score=score, matched_terms=terms)
            )
        return results

    # ── Maintenance ────────────────────────────────────────────────────

    def purge_expired(self, *, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        purged = 0
        for entry in list(self.store.all()):
            if entry.pinned:
                continue
            if _is_expired(entry, now):
                if self.store.delete(entry.memory_id):
                    purged += 1
        return purged


# ─── Manager ─────────────────────────────────────────────────────────────


class MemoryManager:
    """High-level orchestrator for the memory layer.

    Composes the repository with ranking / compression logic to
    produce :class:`MemoryContext` objects for the copilot.
    """

    def __init__(self, *, repository: MemoryRepository) -> None:
        self.repository = repository

    def record_from_message(
        self, message: Message, *, user_id: Optional[str] = None
    ) -> Optional[MemoryEntry]:
        """Persist a user message as short-term memory (not always
        useful, but useful for the active conversation's history)."""
        if message.role.value == "system":
            return None
        return self.repository.create_raw(
            memory_type=MemoryType.SHORT_TERM,
            content=message.content,
            scope=MemoryScope.CONVERSATION,
            user_id=user_id,
            conversation_id=None,
            tags=["short_term"],
            metadata={"role": message.role.value, "message_id": message.message_id},
            ttl_seconds=60 * 60 * 24,  # 24h
        )

    def record_retrieval(
        self,
        *,
        query: str,
        answer_text: str,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> MemoryEntry:
        """Persist a successful query/answer pair as retrieval memory."""
        content = f"Q: {query}\nA: {answer_text}".strip()
        return self.repository.create_raw(
            memory_type=MemoryType.RETRIEVAL,
            content=content,
            scope=MemoryScope.USER if user_id else MemoryScope.GLOBAL,
            user_id=user_id,
            conversation_id=conversation_id,
            tags=["retrieval"],
            metadata={"query": query},
            ttl_seconds=60 * 60 * 24 * 30,  # 30 days
        )

    def record_long_term(
        self,
        *,
        content: str,
        user_id: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryEntry:
        """Persist long-term user context (preferences, role, etc.)."""
        return self.repository.create_raw(
            memory_type=MemoryType.LONG_TERM,
            content=content,
            scope=MemoryScope.USER,
            user_id=user_id,
            tags=tags or ["long_term"],
            metadata=metadata or {},
            pinned=True,  # long-term memories don't auto-expire
        )

    def build_context(
        self,
        *,
        query: str,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        short_term: Optional[List[Message]] = None,
        top_k: int = 5,
    ) -> MemoryContext:
        """Compose a :class:`MemoryContext` for a copilot request."""
        # 1. Short-term (provided directly by the caller).
        st = list(short_term or [])
        # 2. Long-term: pinned user memories.
        lt_query = MemoryQuery(
            user_id=user_id,
            memory_types=[MemoryType.LONG_TERM],
            top_k=min(top_k, 10),
        )
        lt_hits = self.repository.search(lt_query)
        # 3. Retrieval: ranked by query relevance.
        rt_query = MemoryQuery(
            user_id=user_id,
            conversation_id=conversation_id,
            memory_types=[MemoryType.RETRIEVAL],
            query=query,
            top_k=top_k,
        )
        rt_hits = self.repository.search(rt_query)
        # Compress short-term to last 6 messages to keep context small.
        if len(st) > 6:
            st = st[-6:]
        total = len(st) + len(lt_hits) + len(rt_hits)
        return MemoryContext(
            short_term=st,
            long_term=[h.entry for h in lt_hits],
            retrieval=rt_hits,
            total_count=total,
            memory_used=total > 0,
        )

    def purge_expired(self) -> int:
        return self.repository.purge_expired()

    def reset(self) -> None:
        self.repository.store.reset()


# ─── Top-level service ───────────────────────────────────────────────────


class MemoryService:
    """DI-friendly top-level service."""

    def __init__(
        self,
        *,
        store: Optional[MemoryStore] = None,
        manager: Optional[MemoryManager] = None,
        repository: Optional[MemoryRepository] = None,
    ) -> None:
        if store is None:
            store = InMemoryMemoryStore(
                persist_path=Path(settings.STORAGE_ROOT) / "memory" / "entries.jsonl"
            )
        self.store = store
        if repository is None:
            repository = MemoryRepository(store=store)
        self.repository = repository
        if manager is None:
            manager = MemoryManager(repository=repository)
        self.manager = manager


def build_default_memory_service() -> MemoryService:
    return MemoryService()


# ─── Helpers ─────────────────────────────────────────────────────────────


def _expiry_from_ttl(now: datetime, ttl: Optional[int]) -> Optional[datetime]:
    if ttl is None:
        return None
    return now + timedelta(seconds=int(ttl))


def _is_expired(entry: MemoryEntry, now: datetime) -> bool:
    if entry.expires_at is None:
        return False
    return entry.expires_at <= now


def _score_entry(
    entry: MemoryEntry, query_tokens: Sequence[str], query_text: str
) -> Tuple[float, List[str]]:
    """Score a memory entry against the query.

    The score is a blend of:
    * token overlap (cosine-like) — 0.6 weight
    * exact-phrase match boost — 0.2 weight
    * tag overlap — 0.1 weight
    * recency decay — 0.1 weight
    """
    entry_tokens = _tokenise(entry.embedding_text or entry.content)
    if not query_tokens or not entry_tokens:
        return 0.0, []
    overlap = token_overlap(" ".join(query_tokens), " ".join(entry_tokens))
    matched = [t for t in query_tokens if t in entry_tokens]
    phrase_boost = 0.0
    if query_text and query_text.lower() in (entry.embedding_text or entry.content).lower():
        phrase_boost = 1.0
    elif len(matched) >= 3:
        phrase_boost = len(matched) / max(1, len(query_tokens))
    tag_overlap = 0.0
    if entry.tags and query_tokens:
        tag_set = {t.lower() for t in entry.tags}
        hits = sum(1 for t in query_tokens if t in tag_set)
        tag_overlap = hits / max(1, len(query_tokens))
    age_seconds = max(0.0, (datetime.now(timezone.utc) - entry.created_at).total_seconds())
    # Decay: 1.0 for fresh, ~0.5 after a day, ~0.0 after a month.
    recency = 1.0 / (1.0 + age_seconds / (60 * 60 * 24 * 7))
    score = (
        0.6 * overlap
        + 0.2 * phrase_boost
        + 0.1 * tag_overlap
        + 0.1 * recency
    )
    return min(1.0, score), matched


__all__ = [
    "InMemoryMemoryStore",
    "MemoryManager",
    "MemoryRepository",
    "MemoryService",
    "MemoryStore",
    "build_default_memory_service",
]
