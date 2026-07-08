"""Module 6.7 — Copilot Analytics service.

Public surface
--------------
* :class:`AnalyticsRepository` — pulls raw events from the underlying
  services (conversations, memory, feedback, answer_analytics).
* :class:`ConversationAnalytics` — per-conversation aggregations.
* :class:`CopilotAnalyticsService` — top-level DI service that
  produces :class:`CopilotMetrics` and :class:`UsageStats`.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from app.schemas.copilot_analytics import (
    AnalyticsWindow,
    AnswerQualityMetrics,
    ConversationMetrics,
    CopilotMetrics,
    CostMetrics,
    LatencyMetrics,
    MemoryUsageMetrics,
    QueryCategory,
    QueryCategoryMetrics,
    UsageStats,
)
from app.schemas.planning import QueryType

if TYPE_CHECKING:
    from app.services.answer_analytics import AnswerAnalyticsService
    from app.services.conversation import ConversationService
    from app.services.feedback import FeedbackService
    from app.services.memory import MemoryService

logger = logging.getLogger(__name__)


# ─── Window helpers ────────────────────────────────────────────────────────


_WINDOW_TO_DELTA: Dict[AnalyticsWindow, Optional[timedelta]] = {
    AnalyticsWindow.LAST_HOUR: timedelta(hours=1),
    AnalyticsWindow.LAST_DAY: timedelta(days=1),
    AnalyticsWindow.LAST_WEEK: timedelta(days=7),
    AnalyticsWindow.LAST_MONTH: timedelta(days=30),
    AnalyticsWindow.ALL: None,
}


def _window_start(
    window: AnalyticsWindow, now: Optional[datetime] = None
) -> Optional[datetime]:
    delta = _WINDOW_TO_DELTA.get(window)
    if delta is None:
        return None
    return (now or datetime.now(timezone.utc)) - delta


# ─── Repository ────────────────────────────────────────────────────────────


class AnalyticsRepository:
    """Pulls raw events from the underlying services.

    The repository is intentionally pluggable: it accepts the other
    services as constructor arguments so it can be wired up in DI.
    """

    def __init__(
        self,
        *,
        conversation_service: Optional["ConversationService"] = None,
        memory_service: Optional["MemoryService"] = None,
        feedback_service: Optional["FeedbackService"] = None,
        answer_analytics_service: Optional["AnswerAnalyticsService"] = None,
    ) -> None:
        self.conversation_service = conversation_service
        self.memory_service = memory_service
        self.feedback_service = feedback_service
        self.answer_analytics_service = answer_analytics_service

    def conversations(self) -> List[Any]:
        if self.conversation_service is None:
            return []
        return self.conversation_service.manager.repository.store.all()

    def memories(self) -> List[Any]:
        if self.memory_service is None:
            return []
        return self.memory_service.repository.store.all()

    def feedback(self) -> List[Any]:
        if self.feedback_service is None:
            return []
        return self.feedback_service.manager.repository.all()

    def answer_events(self) -> List[Any]:
        if self.answer_analytics_service is None:
            return []
        try:
            return self.answer_analytics_service.repository.all()
        except Exception:  # pragma: no cover
            return []


# ─── Conversation analytics ───────────────────────────────────────────────


class ConversationAnalytics:
    """Aggregations over conversations."""

    def aggregate(
        self,
        conversations: List[Any],
        *,
        window_start: Optional[datetime] = None,
    ) -> ConversationMetrics:
        if window_start is not None:
            conversations = [c for c in conversations if c.created_at >= window_start]
        total = len(conversations)
        if total == 0:
            return ConversationMetrics()
        active = sum(
            1
            for c in conversations
            if getattr(c, "status", None) and c.status.value == "active"
        )
        archived = sum(
            1
            for c in conversations
            if getattr(c, "status", None) and c.status.value == "archived"
        )
        total_messages = sum(len(c.messages) for c in conversations)
        avg_msgs = total_messages / total
        # Approx token length.
        total_tokens = sum(
            sum(m.token_estimate for m in c.messages) for c in conversations
        )
        avg_len = total_tokens / total if total else 0.0
        # Multi-turn: more than 2 messages (1 user + 1 assistant).
        multi_turn = sum(1 for c in conversations if len(c.messages) > 2)
        multi_turn_ratio = multi_turn / total
        # Follow-up rate: average follow-ups per session
        # (messages beyond the first user turn).
        follow_ups = sum(max(0, len(c.messages) - 2) for c in conversations)
        follow_up_rate = follow_ups / total
        return ConversationMetrics(
            total_conversations=total,
            active_conversations=active,
            archived_conversations=archived,
            avg_messages_per_conversation=avg_msgs,
            avg_conversation_length_tokens=avg_len,
            multi_turn_conversations=multi_turn,
            multi_turn_ratio=multi_turn_ratio,
            follow_up_rate=follow_up_rate,
        )


# ─── Memory analytics ─────────────────────────────────────────────────────


def _classify_memory(entry: Any) -> QueryCategory:
    """Map a memory entry into a coarse query category."""
    text = (entry.content or "").lower()
    tags = " ".join(getattr(entry, "tags", []) or []).lower()
    blob = f"{text} {tags}"
    if "compare" in blob or "vs" in blob or "difference" in blob:
        return QueryCategory.COMPARISON
    if (
        "timeline" in blob
        or "evolution" in blob
        or "history" in blob
        or "effective from" in blob
        or "effective date" in blob
    ):
        return QueryCategory.TIMELINE
    if "change" in blob or "amend" in blob:
        return QueryCategory.CHANGE
    if "cross" in blob or "both" in blob:
        return QueryCategory.CROSS_DOC
    if "step" in blob or "first" in blob or "then" in blob:
        return QueryCategory.MULTI_STEP
    if "how to" in blob or "procedure" in blob or "process" in blob:
        return QueryCategory.PROCEDURAL
    if "what is" in blob or "define" in blob or "definition" in blob or "means" in blob:
        return QueryCategory.DEFINITION
    return QueryCategory.OTHER


# ─── Cost model ───────────────────────────────────────────────────────────


_DEFAULT_COST_PER_1K = 0.002  # USD, mock rate


def _estimate_cost(total_tokens: int) -> float:
    return (total_tokens / 1000.0) * _DEFAULT_COST_PER_1K


# ─── Top-level service ────────────────────────────────────────────────────


class CopilotAnalyticsService:
    """DI-friendly top-level service."""

    def __init__(
        self,
        *,
        repository: Optional[AnalyticsRepository] = None,
        conversation_analytics: Optional[ConversationAnalytics] = None,
    ) -> None:
        self.repository = repository or AnalyticsRepository()
        self.conversation_analytics = conversation_analytics or ConversationAnalytics()

    # ── Public API ──────────────────────────────────────────────────────

    def metrics(
        self, *, window: AnalyticsWindow = AnalyticsWindow.ALL
    ) -> CopilotMetrics:
        ws = _window_start(window)
        conversations = self.repository.conversations()
        memories = self.repository.memories()
        feedback = self.repository.feedback()
        events = self.repository.answer_events()
        # Window filtering.
        if ws is not None:
            conversations = [c for c in conversations if c.created_at >= ws]
            memories = [m for m in memories if m.created_at >= ws]
            feedback = [f for f in feedback if f.created_at >= ws]
            events = [e for e in events if e.timestamp >= ws]
        # Conversations.
        conv_metrics = self.conversation_analytics.aggregate(
            conversations, window_start=None
        )
        # Memory.
        mem_metrics = self._memory_metrics(memories, len(events))
        # Categories.
        cat_metrics = self._category_metrics(events)
        # Latency.
        lat_metrics = self._latency_metrics(events)
        # Cost.
        cost_metrics = self._cost_metrics(events)
        # Quality.
        quality_metrics = self._quality_metrics(events, feedback)
        # Top-level counts.
        total_events = len(events)
        successful = sum(
            1
            for e in events
            if getattr(e, "warnings", None) is not None and not e.warnings
        )
        failed = total_events - successful
        return CopilotMetrics(
            window=window,
            window_start=ws,
            total_requests=total_events,
            successful_requests=successful,
            failed_requests=failed,
            success_rate=(successful / total_events) if total_events else 0.0,
            conversations=conv_metrics,
            memory=mem_metrics,
            categories=cat_metrics,
            latency=lat_metrics,
            cost=cost_metrics,
            quality=quality_metrics,
        )

    def usage(self, *, window: AnalyticsWindow = AnalyticsWindow.ALL) -> UsageStats:
        m = self.metrics(window=window)
        return UsageStats(
            window=window,
            total_requests=m.total_requests,
            total_tokens=m.cost.total_tokens,
            total_conversations=m.conversations.total_conversations,
            total_memories=m.memory.total_memories,
            avg_latency_ms=m.latency.average_ms,
            estimated_cost_usd=m.cost.estimated_cost_usd,
            feedback_total=m.quality.feedback_total,
            satisfaction_ratio=m.quality.satisfaction_ratio,
        )

    # ── Helpers ─────────────────────────────────────────────────────────

    def _memory_metrics(
        self, memories: List[Any], request_count: int
    ) -> MemoryUsageMetrics:
        from app.schemas.memory import MemoryType

        if not memories:
            return MemoryUsageMetrics(memory_used_in_requests=0, memory_used_ratio=0.0)
        short_term = sum(1 for m in memories if m.memory_type == MemoryType.SHORT_TERM)
        long_term = sum(1 for m in memories if m.memory_type == MemoryType.LONG_TERM)
        retrieval = sum(1 for m in memories if m.memory_type == MemoryType.RETRIEVAL)
        pinned = sum(1 for m in memories if getattr(m, "pinned", False))
        avg_rel = sum(getattr(m, "relevance_score", 0.0) for m in memories) / len(
            memories
        )
        # Heuristic: assume 30% of requests used memory (since this is
        # not directly tracked).  When request_count is 0, skip.
        used_in_req = int(request_count * 0.3) if request_count else 0
        return MemoryUsageMetrics(
            total_memories=len(memories),
            short_term=short_term,
            long_term=long_term,
            retrieval=retrieval,
            pinned=pinned,
            avg_relevance_score=avg_rel,
            memory_used_in_requests=used_in_req,
            memory_used_ratio=(used_in_req / request_count) if request_count else 0.0,
        )

    def _category_metrics(self, events: List[Any]) -> QueryCategoryMetrics:
        # We don't currently tag events with a query category, so
        # derive a synthetic distribution from the query text where
        # possible.  When no events exist, return an empty object.
        if not events:
            return QueryCategoryMetrics()
        counts: Counter = Counter()
        for e in events:
            q = (getattr(e, "query", "") or "").lower()
            if "compare" in q or " vs " in q or "difference" in q:
                counts[QueryCategory.COMPARISON] += 1
            elif "timeline" in q or "evolution" in q:
                counts[QueryCategory.TIMELINE] += 1
            elif "change" in q or "amend" in q:
                counts[QueryCategory.CHANGE] += 1
            elif "what is" in q or "define" in q:
                counts[QueryCategory.DEFINITION] += 1
            elif "how to" in q or "procedure" in q:
                counts[QueryCategory.PROCEDURAL] += 1
            else:
                counts[QueryCategory.OTHER] += 1
        top = counts.most_common(1)[0][0] if counts else None
        return QueryCategoryMetrics(by_category=dict(counts), top_category=top)

    def _latency_metrics(self, events: List[Any]) -> LatencyMetrics:
        if not events:
            return LatencyMetrics()
        latencies = sorted(getattr(e, "latency_ms", 0.0) for e in events)
        n = len(latencies)

        def pct(p: float) -> float:
            if n == 0:
                return 0.0
            idx = min(n - 1, int(p * n))
            return latencies[idx]

        return LatencyMetrics(
            count=n,
            average_ms=sum(latencies) / n,
            p50_ms=pct(0.5),
            p95_ms=pct(0.95),
            p99_ms=pct(0.99),
            min_ms=latencies[0] if latencies else 0.0,
            max_ms=latencies[-1] if latencies else 0.0,
        )

    def _cost_metrics(self, events: List[Any]) -> CostMetrics:
        if not events:
            return CostMetrics()
        total = sum(getattr(e, "total_tokens", 0) for e in events)
        # We don't have prompt/completion split here; assume 70/30.
        prompt = int(total * 0.7)
        completion = total - prompt
        avg = total / len(events)
        return CostMetrics(
            total_tokens=total,
            prompt_tokens=prompt,
            completion_tokens=completion,
            estimated_cost_usd=_estimate_cost(total),
            avg_tokens_per_request=avg,
        )

    def _quality_metrics(
        self, events: List[Any], feedback: List[Any]
    ) -> AnswerQualityMetrics:
        if not events and not feedback:
            return AnswerQualityMetrics()
        n = len(events)
        avg_conf = (
            sum(getattr(e, "confidence_score", 0.0) for e in events) / n if n else 0.0
        )
        avg_faith = (
            sum(getattr(e, "faithfulness_score", 0.0) for e in events) / n if n else 0.0
        )
        halluc = (
            sum(1 for e in events if getattr(e, "hallucination_detected", False)) / n
            if n
            else 0.0
        )
        avg_attr = (
            sum(getattr(e, "attribution_coverage_ratio", 0.0) for e in events) / n
            if n
            else 0.0
        )
        thumbs_up = sum(
            1
            for f in feedback
            if getattr(f, "feedback_type", None)
            and f.feedback_type.value == "thumbs_up"
        )
        thumbs_down = sum(
            1
            for f in feedback
            if getattr(f, "feedback_type", None)
            and f.feedback_type.value == "thumbs_down"
        )
        rated = thumbs_up + thumbs_down
        sat = (thumbs_up / rated) if rated else 0.0
        corrections = sum(
            1
            for f in feedback
            if getattr(f, "feedback_type", None)
            and f.feedback_type.value == "correction"
        )
        halluc_reports = sum(
            1
            for f in feedback
            if getattr(f, "feedback_type", None)
            and f.feedback_type.value == "hallucination_report"
        )
        return AnswerQualityMetrics(
            avg_confidence=avg_conf,
            avg_faithfulness=avg_faith,
            hallucination_rate=halluc,
            avg_attribution_coverage=avg_attr,
            thumbs_up=thumbs_up,
            thumbs_down=thumbs_down,
            satisfaction_ratio=sat,
            feedback_total=len(feedback),
            correction_count=corrections,
            hallucination_reports=halluc_reports,
        )


def build_default_copilot_analytics_service() -> CopilotAnalyticsService:
    return CopilotAnalyticsService()


__all__ = [
    "AnalyticsRepository",
    "ConversationAnalytics",
    "CopilotAnalyticsService",
    "build_default_copilot_analytics_service",
]
