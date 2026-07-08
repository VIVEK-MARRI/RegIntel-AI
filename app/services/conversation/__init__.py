"""Module 6.2 — Conversation Management.

Provides:

* :class:`ConversationStore` — abstract store.
* :class:`InMemoryConversationStore` — thread-safe store with JSONL
  persistence.
* :class:`ConversationRepository` — business-rule layer (pagination,
  filtering, search).
* :class:`SessionManager` — token-budget-aware context window
  management.
* :class:`ConversationHistoryManager` — replay, summarise, trim.
* :class:`ConversationManager` — high-level orchestrator.
* :class:`ConversationService` — top-level service exposed via DI.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.config import settings
from app.schemas.conversation import (
    AppendMessageRequest,
    Conversation,
    ConversationContext,
    ConversationFilter,
    ConversationStatus,
    CreateConversationRequest,
    Message,
    PaginatedConversations,
    Role,
)
from app.services.observability import track_request

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)
_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "in",
    "on",
    "at",
    "by",
    "for",
    "to",
    "from",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "this",
    "that",
    "it",
    "i",
    "you",
    "he",
    "she",
    "we",
    "they",
    "us",
    "my",
    "your",
    "their",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "what",
    "which",
    "who",
    "when",
    "where",
    "how",
    "why",
    "as",
    "but",
    "or",
    "not",
    "no",
    "yes",
    "can",
    "could",
    "will",
    "would",
    "should",
    "may",
    "might",
    "shall",
    "with",
    "without",
    "into",
    "out",
    "up",
    "down",
    "over",
    "under",
}


# ─── Token estimation ────────────────────────────────────────────────────


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


# ─── Store interface ─────────────────────────────────────────────────────


class ConversationStore:
    """Abstract conversation store (Repository pattern)."""

    def add(self, conversation: Conversation) -> None: ...
    def get(self, conversation_id: str) -> Optional[Conversation]: ...
    def update(self, conversation: Conversation) -> None: ...
    def delete(self, conversation_id: str) -> bool: ...
    def all(self) -> List[Conversation]: ...
    def reset(self) -> None: ...


class InMemoryConversationStore(ConversationStore):
    """Thread-safe in-memory store with optional JSONL persistence."""

    def __init__(self, *, persist_path: Optional[Path] = None) -> None:
        self._items: Dict[str, Conversation] = {}
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
                conv = Conversation.model_validate(raw)
                self._items[conv.conversation_id] = conv
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load conversation store: %s", exc)

    def _persist(self, conv: Conversation) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persist_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(conv.model_dump(mode="json")) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to persist conversation: %s", exc)

    def add(self, conversation: Conversation) -> None:
        with self._lock:
            self._items[conversation.conversation_id] = conversation
        self._persist(conversation)

    def get(self, conversation_id: str) -> Optional[Conversation]:
        with self._lock:
            return self._items.get(conversation_id)

    def update(self, conversation: Conversation) -> None:
        conversation.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._items[conversation.conversation_id] = conversation
        self._persist(conversation)

    def delete(self, conversation_id: str) -> bool:
        with self._lock:
            return self._items.pop(conversation_id, None) is not None

    def all(self) -> List[Conversation]:
        with self._lock:
            return list(self._items.values())

    def reset(self) -> None:
        with self._lock:
            self._items.clear()


# ─── Repository (business rules) ─────────────────────────────────────────


class ConversationRepository:
    """Business-rule layer on top of the store."""

    def __init__(self, *, store: ConversationStore) -> None:
        self.store = store

    def create(self, request: CreateConversationRequest) -> Conversation:
        now = datetime.now(timezone.utc)
        ttl = request.ttl_seconds
        expires_at = now + timedelta(seconds=ttl) if ttl else None
        conv = Conversation(
            user_id=request.user_id,
            title=request.title or "",
            status=ConversationStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            ttl_seconds=ttl,
            expires_at=expires_at,
            metadata=dict(request.metadata),
            tags=list(request.tags),
        )
        self.store.add(conv)
        return conv

    def get(self, conversation_id: str) -> Optional[Conversation]:
        return self.store.get(conversation_id)

    def update(self, conversation: Conversation) -> None:
        self.store.update(conversation)

    def delete(self, conversation_id: str) -> bool:
        return self.store.delete(conversation_id)

    def all(self) -> List[Conversation]:
        return self.store.all()

    def append_message(
        self, conversation_id: str, request: AppendMessageRequest
    ) -> Conversation:
        conv = self.get(conversation_id)
        if conv is None:
            raise KeyError(f"conversation {conversation_id!r} not found")
        now = datetime.now(timezone.utc)
        msg = Message(
            role=request.role,
            content=request.content,
            timestamp=now,
            metadata=dict(request.metadata),
            references=dict(request.references),
            token_estimate=estimate_tokens(request.content),
        )
        conv.messages.append(msg)
        # Update title lazily from the first user message.
        if not conv.title and request.role == Role.USER:
            conv.title = request.content[:80].strip()
        self.store.update(conv)
        return conv

    def search(self, flt: ConversationFilter) -> PaginatedConversations:
        items = list(self.store.all())
        now = datetime.now(timezone.utc)
        # Filter.
        filtered: List[Conversation] = []
        for c in items:
            # Exclude expired by default.
            if (
                c.expires_at
                and c.expires_at <= now
                and c.status != ConversationStatus.EXPIRED
            ):
                continue
            if flt.user_id and c.user_id != flt.user_id:
                continue
            if flt.status and c.status != flt.status:
                continue
            if flt.tag and flt.tag not in c.tags:
                continue
            if flt.query:
                if not _conversation_matches_query(c, flt.query):
                    continue
            filtered.append(c)
        # Sort.
        sort_key = (
            flt.sort_by
            if flt.sort_by in {"created_at", "updated_at", "title"}
            else "updated_at"
        )
        filtered.sort(key=lambda c: getattr(c, sort_key), reverse=flt.sort_desc)
        # Paginate.
        total = len(filtered)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        page_items = filtered[start:end]
        return PaginatedConversations(
            items=page_items,
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def purge_expired(self, *, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        purged = 0
        for c in list(self.store.all()):
            if (
                c.expires_at
                and c.expires_at <= now
                and c.status != ConversationStatus.ARCHIVED
            ):
                if self.store.delete(c.conversation_id):
                    purged += 1
        return purged


def _conversation_matches_query(conv: Conversation, query: str) -> bool:
    q = query.lower()
    if q in (conv.title or "").lower():
        return True
    if q in (conv.summary or "").lower():
        return True
    for m in conv.messages:
        if q in m.content.lower():
            return True
    for tag in conv.tags:
        if q in tag.lower():
            return True
    return False


# ─── Session manager (context window) ───────────────────────────────────


class SessionManager:
    """Builds a :class:`ConversationContext` within a token budget."""

    DEFAULT_TOKEN_BUDGET = 2000

    def __init__(self, *, default_token_budget: int = DEFAULT_TOKEN_BUDGET) -> None:
        self.default_token_budget = default_token_budget

    def build_context(
        self,
        conversation: Conversation,
        *,
        token_budget: Optional[int] = None,
    ) -> ConversationContext:
        budget = token_budget or self.default_token_budget
        # Start with the most recent messages; walk backwards until the
        # budget is exhausted.  Compress older messages into the
        # conversation's summary.
        messages: List[Message] = []
        used = 0
        compressed = False
        for msg in reversed(conversation.messages):
            cost = msg.token_estimate or estimate_tokens(msg.content)
            if used + cost > budget and messages:
                compressed = True
                break
            messages.insert(0, msg)
            used += cost
        return ConversationContext(
            conversation_id=conversation.conversation_id,
            user_id=conversation.user_id,
            summary=conversation.summary or "",
            recent_messages=messages,
            token_budget=budget,
            compressed=compressed,
            extra={
                "message_count": len(conversation.messages),
                "included_count": len(messages),
            },
        )


# ─── History manager (replay, summarise, trim) ──────────────────────────


class ConversationHistoryManager:
    """Operations on the message history: replay, summarise, trim."""

    MAX_SUMMARY_LENGTH = 500

    def replay(self, conversation: Conversation) -> List[Message]:
        return list(conversation.messages)

    def summarise(self, conversation: Conversation) -> str:
        """Produce a short extractive summary of the conversation.

        Strategy: pick the first N most relevant sentences from all
        user/assistant messages, dedup, and concatenate.
        """
        all_text: List[str] = []
        for m in conversation.messages:
            if m.role in (Role.USER, Role.ASSISTANT):
                # Take the first sentence only.
                first = re.split(r"(?<=[.!?])\s+", m.content.strip(), maxsplit=1)[0]
                if first:
                    all_text.append(first)
        # Dedup while preserving order.
        seen: set = set()
        unique: List[str] = []
        for t in all_text:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)
        summary = " ".join(unique)
        if len(summary) > self.MAX_SUMMARY_LENGTH:
            summary = summary[: self.MAX_SUMMARY_LENGTH - 1].rstrip() + "…"
        return summary

    def trim(
        self,
        conversation: Conversation,
        *,
        keep_last: int = 20,
    ) -> Conversation:
        """Trim the message history to the last ``keep_last`` messages
        and update the summary with the dropped portion."""
        if len(conversation.messages) <= keep_last:
            return conversation
        dropped = conversation.messages[:-keep_last]
        kept = conversation.messages[-keep_last:]
        # Append dropped messages to the summary.
        chunk_summaries = []
        for m in dropped:
            first = re.split(r"(?<=[.!?])\s+", m.content.strip(), maxsplit=1)[0]
            if first:
                chunk_summaries.append(f"{m.role.value}: {first}")
        if chunk_summaries:
            extra = " ".join(chunk_summaries)
            if conversation.summary:
                conversation.summary = f"{conversation.summary} | {extra}"
            else:
                conversation.summary = extra
            if len(conversation.summary) > self.MAX_SUMMARY_LENGTH:
                conversation.summary = (
                    conversation.summary[: self.MAX_SUMMARY_LENGTH - 1].rstrip() + "…"
                )
        conversation.messages = kept
        return conversation


# ─── Manager (orchestrator) ─────────────────────────────────────────────


class ConversationManager:
    """High-level orchestrator for conversation operations."""

    def __init__(
        self,
        *,
        repository: ConversationRepository,
        session: SessionManager,
        history: ConversationHistoryManager,
    ) -> None:
        self.repository = repository
        self.session = session
        self.history = history

    # ── Lifecycle ──────────────────────────────────────────────────────

    def create(self, request: CreateConversationRequest) -> Conversation:
        return self.repository.create(request)

    def get(self, conversation_id: str) -> Optional[Conversation]:
        return self.repository.get(conversation_id)

    def get_or_create(
        self,
        conversation_id: Optional[str],
        *,
        user_id: Optional[str] = None,
    ) -> Conversation:
        if conversation_id:
            conv = self.repository.get(conversation_id)
            if conv is not None:
                return conv
        return self.repository.create(CreateConversationRequest(user_id=user_id))

    def delete(self, conversation_id: str) -> bool:
        return self.repository.delete(conversation_id)

    def append(
        self, conversation_id: str, request: AppendMessageRequest
    ) -> Conversation:
        return self.repository.append_message(conversation_id, request)

    def append_user(
        self, conversation_id: str, content: str, **metadata: Any
    ) -> Conversation:
        return self.append(
            conversation_id,
            AppendMessageRequest(role=Role.USER, content=content, metadata=metadata),
        )

    def append_assistant(
        self,
        conversation_id: str,
        content: str,
        *,
        references: Optional[Dict[str, str]] = None,
        **metadata: Any,
    ) -> Conversation:
        return self.append(
            conversation_id,
            AppendMessageRequest(
                role=Role.ASSISTANT,
                content=content,
                metadata=metadata,
                references=references or {},
            ),
        )

    # ── Search / listing ─────────────────────────────────────────────

    def search(self, flt: ConversationFilter) -> PaginatedConversations:
        return self.repository.search(flt)

    # ── Context ───────────────────────────────────────────────────────

    def build_context(
        self,
        conversation_id: str,
        *,
        token_budget: Optional[int] = None,
    ) -> ConversationContext:
        conv = self.get(conversation_id)
        if conv is None:
            raise KeyError(f"conversation {conversation_id!r} not found")
        return self.session.build_context(conv, token_budget=token_budget)

    # ── Maintenance ──────────────────────────────────────────────────

    def refresh_summary(self, conversation_id: str) -> Conversation:
        conv = self.get(conversation_id)
        if conv is None:
            raise KeyError(f"conversation {conversation_id!r} not found")
        conv.summary = self.history.summarise(conv)
        self.repository.update(conv)
        return conv

    def trim(self, conversation_id: str, *, keep_last: int = 20) -> Conversation:
        conv = self.get(conversation_id)
        if conv is None:
            raise KeyError(f"conversation {conversation_id!r} not found")
        conv = self.history.trim(conv, keep_last=keep_last)
        self.repository.update(conv)
        return conv

    def replay(self, conversation_id: str) -> List[Message]:
        conv = self.get(conversation_id)
        if conv is None:
            raise KeyError(f"conversation {conversation_id!r} not found")
        return self.history.replay(conv)

    def purge_expired(self) -> int:
        return self.repository.purge_expired()

    def reset(self) -> None:
        self.repository.store.reset()


# ─── Top-level service ───────────────────────────────────────────────────


class ConversationService:
    """DI-friendly top-level service."""

    def __init__(
        self,
        *,
        store: Optional[ConversationStore] = None,
        manager: Optional[ConversationManager] = None,
        repository: Optional[ConversationRepository] = None,
        session: Optional[SessionManager] = None,
        history: Optional[ConversationHistoryManager] = None,
    ) -> None:
        if store is None:
            store = InMemoryConversationStore(
                persist_path=Path(settings.STORAGE_ROOT)
                / "conversations"
                / "entries.jsonl"
            )
        self.store = store
        if repository is None:
            repository = ConversationRepository(store=store)
        self.repository = repository
        if session is None:
            session = SessionManager()
        self.session = session
        if history is None:
            history = ConversationHistoryManager()
        self.history = history
        if manager is None:
            manager = ConversationManager(
                repository=repository, session=session, history=history
            )
        self.manager = manager


def build_default_conversation_service() -> ConversationService:
    return ConversationService()


__all__ = [
    "ConversationHistoryManager",
    "ConversationManager",
    "ConversationRepository",
    "ConversationService",
    "ConversationStore",
    "InMemoryConversationStore",
    "SessionManager",
    "build_default_conversation_service",
    "estimate_tokens",
]
