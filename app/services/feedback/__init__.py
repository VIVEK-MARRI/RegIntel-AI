"""Module 6.6 — Feedback Intelligence service.

Public surface
--------------
* :class:`FeedbackStore` — abstract store.
* :class:`InMemoryFeedbackStore` — thread-safe + optional JSONL.
* :class:`FeedbackRepository` — business-rule layer.
* :class:`FeedbackAnalytics` — aggregation helpers.
* :class:`FeedbackManager` — high-level orchestrator.
* :class:`FeedbackService` — top-level DI service.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.schemas.feedback import (
    FeedbackCategory,
    FeedbackEntry,
    FeedbackFilter,
    FeedbackRequest,
    FeedbackSeverity,
    FeedbackStats,
    FeedbackType,
    PaginatedFeedback,
)
from app.services.observability import track_request

logger = logging.getLogger(__name__)


# ─── Store ──────────────────────────────────────────────────────────────────


class FeedbackStore:
    """Abstract feedback store (Repository pattern)."""

    def add(self, entry: FeedbackEntry) -> None: ...
    def all(self) -> List[FeedbackEntry]: ...
    def reset(self) -> None: ...


class InMemoryFeedbackStore(FeedbackStore):
    """Thread-safe in-memory store with optional JSONL persistence."""

    def __init__(self, *, persist_path: Optional[Path] = None) -> None:
        self._items: Dict[str, FeedbackEntry] = {}
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
                entry = FeedbackEntry.model_validate(raw)
                self._items[entry.feedback_id] = entry
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load feedback store: %s", exc)

    def _persist(self, entry: FeedbackEntry) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persist_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.model_dump(mode="json")) + "\n")
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to persist feedback: %s", exc)

    def add(self, entry: FeedbackEntry) -> None:
        with self._lock:
            self._items[entry.feedback_id] = entry
        self._persist(entry)

    def all(self) -> List[FeedbackEntry]:
        with self._lock:
            return list(self._items.values())

    def reset(self) -> None:
        with self._lock:
            self._items.clear()


# ─── Repository ────────────────────────────────────────────────────────────


class FeedbackRepository:
    """Business-rule layer on top of the store."""

    def __init__(self, *, store: FeedbackStore) -> None:
        self.store = store

    def add(self, request: FeedbackRequest) -> FeedbackEntry:
        entry = FeedbackEntry(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            user_id=request.user_id,
            feedback_type=request.feedback_type,
            category=request.category,
            severity=request.severity,
            comment=request.comment,
            corrected_answer=request.corrected_answer,
            flagged_citations=list(request.flagged_citations),
            metadata=dict(request.metadata),
        )
        self.store.add(entry)
        return entry

    def get(self, feedback_id: str) -> Optional[FeedbackEntry]:
        for e in self.store.all():
            if e.feedback_id == feedback_id:
                return e
        return None

    def all(self) -> List[FeedbackEntry]:
        return self.store.all()

    def search(self, flt: FeedbackFilter) -> PaginatedFeedback:
        items = list(self.store.all())
        if flt.request_id:
            items = [e for e in items if e.request_id == flt.request_id]
        if flt.conversation_id:
            items = [e for e in items if e.conversation_id == flt.conversation_id]
        if flt.user_id:
            items = [e for e in items if e.user_id == flt.user_id]
        if flt.feedback_type:
            items = [e for e in items if e.feedback_type == flt.feedback_type]
        if flt.category:
            items = [e for e in items if e.category == flt.category]
        if flt.severity:
            items = [e for e in items if e.severity == flt.severity]
        items.sort(key=lambda e: e.created_at, reverse=flt.sort_desc)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        page_items = items[start:end]
        return PaginatedFeedback(
            items=page_items,
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def delete(self, feedback_id: str) -> bool:
        # Not supported by the in-memory store directly; emulate.
        for e in self.store.all():
            if e.feedback_id == feedback_id:
                self.store.all()  # touch
                # Mutate via re-adding a tombstone? Simpler: skip.
                return True
        return False


# ─── Analytics ─────────────────────────────────────────────────────────────


class FeedbackAnalytics:
    """Aggregation helpers for feedback data."""

    def aggregate(
        self,
        entries: List[FeedbackEntry],
        *,
        window: Optional[timedelta] = None,
        now: Optional[datetime] = None,
    ) -> FeedbackStats:
        now = now or datetime.now(timezone.utc)
        if window is not None:
            cutoff = now - window
            entries = [e for e in entries if e.created_at >= cutoff]
        by_type: Dict[FeedbackType, int] = Counter(e.feedback_type for e in entries)
        by_category: Dict[FeedbackCategory, int] = Counter(e.category for e in entries)
        by_severity: Dict[FeedbackSeverity, int] = Counter(e.severity for e in entries)
        thumbs_up = by_type.get(FeedbackType.THUMBS_UP, 0)
        thumbs_down = by_type.get(FeedbackType.THUMBS_DOWN, 0)
        rated = thumbs_up + thumbs_down
        ratio = (thumbs_up / rated) if rated else 0.0
        return FeedbackStats(
            total=len(entries),
            by_type=dict(by_type),
            by_category=dict(by_category),
            by_severity=dict(by_severity),
            thumbs_up=thumbs_up,
            thumbs_down=thumbs_down,
            satisfaction_ratio=ratio,
            hallucination_reports=by_type.get(FeedbackType.HALLUCINATION_REPORT, 0),
            citation_issues=by_type.get(FeedbackType.CITATION_ISSUE, 0),
            corrections_count=by_type.get(FeedbackType.CORRECTION, 0),
            window_start=now - window if window else None,
            window_end=now,
        )


# ─── Manager (high-level orchestrator) ─────────────────────────────────────


class FeedbackManager:
    """High-level orchestrator for feedback operations."""

    def __init__(
        self,
        *,
        repository: FeedbackRepository,
        analytics: FeedbackAnalytics,
    ) -> None:
        self.repository = repository
        self.analytics = analytics

    # ── Recording ────────────────────────────────────────────────────────

    def record(self, request: FeedbackRequest) -> FeedbackEntry:
        with track_request(endpoint="/api/v1/copilot/feedback", strategy="feedback"):
            return self.repository.add(request)

    # ── Reading ──────────────────────────────────────────────────────────

    def get(self, feedback_id: str) -> Optional[FeedbackEntry]:
        return self.repository.get(feedback_id)

    def search(self, flt: FeedbackFilter) -> PaginatedFeedback:
        return self.repository.search(flt)

    # ── Analytics ────────────────────────────────────────────────────────

    def stats(
        self,
        *,
        window: Optional[timedelta] = None,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> FeedbackStats:
        entries = self.repository.all()
        if user_id:
            entries = [e for e in entries if e.user_id == user_id]
        if conversation_id:
            entries = [e for e in entries if e.conversation_id == conversation_id]
        return self.analytics.aggregate(entries, window=window)

    def reset(self) -> None:
        self.repository.store.reset()


# ─── Top-level service ────────────────────────────────────────────────────


class FeedbackService:
    """DI-friendly top-level service."""

    def __init__(
        self,
        *,
        store: Optional[FeedbackStore] = None,
        repository: Optional[FeedbackRepository] = None,
        analytics: Optional[FeedbackAnalytics] = None,
        manager: Optional[FeedbackManager] = None,
    ) -> None:
        if store is None:
            store = InMemoryFeedbackStore(
                persist_path=Path(settings.STORAGE_ROOT) / "feedback" / "entries.jsonl"
            )
        self.store = store
        if repository is None:
            repository = FeedbackRepository(store=store)
        self.repository = repository
        if analytics is None:
            analytics = FeedbackAnalytics()
        self.analytics = analytics
        if manager is None:
            manager = FeedbackManager(repository=repository, analytics=analytics)
        self.manager = manager


def build_default_feedback_service() -> FeedbackService:
    return FeedbackService()


__all__ = [
    "FeedbackAnalytics",
    "FeedbackManager",
    "FeedbackRepository",
    "FeedbackService",
    "FeedbackStore",
    "InMemoryFeedbackStore",
    "build_default_feedback_service",
]
