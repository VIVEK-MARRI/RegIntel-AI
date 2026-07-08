"""Tests for Module 6.7 — Copilot Analytics."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.api.dependencies import (  # noqa: E402
    get_copilot_analytics_service,
    reset_copilot_analytics_service,
)
from app.api.v1.copilot_analytics import router as analytics_api_router  # noqa: E402
from app.schemas.copilot_analytics import (  # noqa: E402
    AnalyticsWindow,
    AnswerQualityMetrics,
    ConversationMetrics,
    CostMetrics,
    LatencyMetrics,
    MemoryUsageMetrics,
    QueryCategory,
    QueryCategoryMetrics,
    UsageStats,
)
from app.services.copilot_analytics import (  # noqa: E402
    AnalyticsRepository,
    ConversationAnalytics,
    CopilotAnalyticsService,
    _classify_memory,
    _estimate_cost,
    _window_start,
    build_default_copilot_analytics_service,
)


# ─── Window helper ──────────────────────────────────────────────────────


def test_window_start_all_returns_none():
    assert _window_start(AnalyticsWindow.ALL) is None


def test_window_start_last_hour():
    now = datetime.now(timezone.utc)
    s = _window_start(AnalyticsWindow.LAST_HOUR)
    assert s is not None
    delta = (now - s).total_seconds()
    assert 3500 < delta < 3700


def test_window_start_last_day():
    s = _window_start(AnalyticsWindow.LAST_DAY)
    assert s is not None
    delta = (datetime.now(timezone.utc) - s).total_seconds()
    assert 86_000 < delta < 86_500


def test_window_start_last_week_and_month():
    s_week = _window_start(AnalyticsWindow.LAST_WEEK)
    s_month = _window_start(AnalyticsWindow.LAST_MONTH)
    assert s_week is not None
    assert s_month is not None
    # Last week window starts later (more recent) than last month.
    assert s_week > s_month


# ─── Cost + classification helpers ──────────────────────────────────────


def test_estimate_cost_zero_tokens():
    assert _estimate_cost(0) == 0.0


def test_estimate_cost_thousand_tokens():
    cost = _estimate_cost(1000)
    # default rate 0.002 / 1K tokens
    assert 0.001 < cost < 0.003


def _entry(content, tags=None):
    """Build a stub memory entry for classification tests."""
    from types import SimpleNamespace

    return SimpleNamespace(content=content, tags=tags or [])


def test_classify_memory_definition():
    assert (
        _classify_memory(_entry("KYC means Know Your Customer"))
        == QueryCategory.DEFINITION
    )


def test_classify_memory_timeline():
    assert (
        _classify_memory(_entry("Effective from 1 April 2023"))
        == QueryCategory.TIMELINE
    )


def test_classify_memory_change():
    assert (
        _classify_memory(_entry("New amendment to the SEBI regulations"))
        == QueryCategory.CHANGE
    )


def test_classify_memory_comparison():
    assert (
        _classify_memory(_entry("Difference between mutual fund and ETF"))
        == QueryCategory.COMPARISON
    )


def test_classify_memory_other_fallback():
    assert (
        _classify_memory(_entry("Random unrelated chatter about cats"))
        == QueryCategory.OTHER
    )


# ─── Conversation analytics ──────────────────────────────────────────────


def test_conversation_analytics_empty():
    analytics = ConversationAnalytics()
    metrics = analytics.aggregate([])
    assert metrics.total_conversations == 0
    assert metrics.multi_turn_ratio == 0.0
    assert metrics.follow_up_rate == 0.0


def _make_conv(conv_id, user_id, n_msgs, archived=False, with_followup=False):
    from app.schemas.conversation import (
        Conversation,
        ConversationStatus,
        Message,
        Role,
    )

    msgs = []
    for i in range(n_msgs):
        role = Role.USER if i % 2 == 0 else Role.ASSISTANT
        msgs.append(
            Message(
                message_id=f"m{i}",
                role=role,
                content="hello world" * 5,
                timestamp=datetime.now(timezone.utc),
                token_estimate=5,
            )
        )
    return Conversation(
        conversation_id=conv_id,
        user_id=user_id,
        title="t",
        status=ConversationStatus.ARCHIVED if archived else ConversationStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        messages=msgs,
    )


def test_conversation_aggregate_basic_counts():
    convs = [
        _make_conv("c1", "u1", n_msgs=2),
        _make_conv("c2", "u1", n_msgs=4),
        _make_conv("c3", "u2", n_msgs=2, archived=True),
    ]
    analytics = ConversationAnalytics()
    metrics = analytics.aggregate(convs)
    assert metrics.total_conversations == 3
    assert metrics.active_conversations == 2
    assert metrics.archived_conversations == 1
    assert metrics.multi_turn_conversations == 1  # only c2 has >2 messages
    assert metrics.avg_messages_per_conversation >= 2.0


def test_conversation_aggregate_followup_rate():
    convs = [
        _make_conv("c1", "u1", n_msgs=3, with_followup=True),
        _make_conv("c2", "u1", n_msgs=2, with_followup=False),
    ]
    analytics = ConversationAnalytics()
    metrics = analytics.aggregate(convs)
    assert metrics.follow_up_rate == 0.5


# ─── AnalyticsRepository (graceful None) ────────────────────────────────


def test_analytics_repository_handles_missing_services():
    repo = AnalyticsRepository()
    assert repo.conversations() == []
    assert repo.memories() == []
    assert repo.feedback() == []
    assert repo.answer_events() == []


# ─── CopilotAnalyticsService.metrics ────────────────────────────────────


def test_metrics_zero_state():
    repo = AnalyticsRepository()
    svc = CopilotAnalyticsService(repository=repo)
    m = svc.metrics(window=AnalyticsWindow.ALL)
    assert m.conversations.total_conversations == 0
    assert m.memory.total_memories == 0
    assert m.latency.count == 0
    assert m.cost.total_tokens == 0
    assert m.quality.feedback_total == 0


def test_metrics_window_filters():
    repo = AnalyticsRepository()
    svc = CopilotAnalyticsService(repository=repo)
    # Should not raise for any window.
    for w in AnalyticsWindow:
        m = svc.metrics(window=w)
        assert m.window == w


def test_metrics_with_conversations():
    from app.schemas.conversation import (
        Conversation,
        ConversationStatus,
        Message,
        Role,
    )

    conv = Conversation(
        conversation_id="c1",
        user_id="u1",
        title="t",
        status=ConversationStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        messages=[
            Message(
                message_id=f"m{i}",
                role=Role.USER if i % 2 == 0 else Role.ASSISTANT,
                content="hi",
                timestamp=datetime.now(timezone.utc),
                token_estimate=2,
            )
            for i in range(3)
        ],
    )

    class _Stub:
        def conversations(self):
            return [conv]

        def memories(self):
            return []

        def feedback(self):
            return []

        def answer_events(self):
            return []

    svc = CopilotAnalyticsService(repository=_Stub())
    m = svc.metrics(window=AnalyticsWindow.ALL)
    assert m.conversations.total_conversations == 1
    assert m.conversations.multi_turn_conversations == 1


def test_metrics_with_answer_events():
    from app.schemas.analytics_v2 import AnswerAnalyticsEvent

    def _ev(eid, tokens, latency, conf, faith):
        return AnswerAnalyticsEvent(
            event_id=eid,
            request_id=eid,
            query=f"q{eid}",
            confidence_score=conf,
            confidence_level="high",
            faithfulness_score=faith,
            hallucination_detected=False,
            hallucination_risk_level="low",
            attribution_coverage_ratio=0.5,
            citation_coverage_ratio=0.5,
            source_count=2,
            latency_ms=latency,
            total_tokens=tokens,
        )

    class _Stub:
        def conversations(self):
            return []

        def memories(self):
            return []

        def feedback(self):
            return []

        def answer_events(self):
            return [
                _ev("a1", 1000, 200.0, 0.8, 0.9),
                _ev("a2", 2000, 400.0, 0.6, 0.7),
            ]

    svc = CopilotAnalyticsService(repository=_Stub())
    m = svc.metrics(window=AnalyticsWindow.ALL)
    assert m.latency.count == 2
    assert m.latency.average_ms == 300.0
    assert m.cost.total_tokens == 3000
    assert m.quality.avg_confidence > 0.0
    assert m.quality.avg_faithfulness > 0.0


def test_metrics_with_feedback():
    from app.schemas.feedback import (
        FeedbackCategory,
        FeedbackEntry,
        FeedbackSeverity,
        FeedbackType,
    )

    class _Stub:
        def conversations(self):
            return []

        def memories(self):
            return []

        def feedback(self):
            return [
                FeedbackEntry(
                    request_id="r1",
                    feedback_type=FeedbackType.THUMBS_UP,
                    category=FeedbackCategory.ANSWER_QUALITY,
                    severity=FeedbackSeverity.LOW,
                    created_at=datetime.now(timezone.utc),
                ),
                FeedbackEntry(
                    request_id="r2",
                    feedback_type=FeedbackType.HALLUCINATION_REPORT,
                    category=FeedbackCategory.HALLUCINATION,
                    severity=FeedbackSeverity.HIGH,
                    created_at=datetime.now(timezone.utc),
                ),
            ]

        def answer_events(self):
            return []

    svc = CopilotAnalyticsService(repository=_Stub())
    m = svc.metrics(window=AnalyticsWindow.ALL)
    assert m.quality.thumbs_up == 1
    assert m.quality.hallucination_reports == 1
    assert m.quality.feedback_total == 2


def test_metrics_with_memories():
    from app.schemas.memory import MemoryEntry, MemoryType

    class _Stub:
        def conversations(self):
            return []

        def memories(self):
            return [
                MemoryEntry(
                    content="KYC definition",
                    memory_type=MemoryType.LONG_TERM,
                ),
                MemoryEntry(
                    content="short term note",
                    memory_type=MemoryType.SHORT_TERM,
                ),
            ]

        def feedback(self):
            return []

        def answer_events(self):
            return []

    svc = CopilotAnalyticsService(repository=_Stub())
    m = svc.metrics(window=AnalyticsWindow.ALL)
    assert m.memory.total_memories == 2
    assert m.memory.short_term == 1
    assert m.memory.long_term == 1
    cat = m.categories
    assert isinstance(cat, QueryCategoryMetrics)


# ─── Usage (lightweight) ───────────────────────────────────────────────


def test_usage_lightweight():
    repo = AnalyticsRepository()
    svc = CopilotAnalyticsService(repository=repo)
    usage = svc.usage(window=AnalyticsWindow.ALL)
    assert isinstance(usage, UsageStats)
    assert usage.window == AnalyticsWindow.ALL
    assert usage.total_requests == 0


def test_usage_window_filtered():
    from app.schemas.analytics_v2 import AnswerAnalyticsEvent

    def _ev(eid, tokens, latency, ts):
        return AnswerAnalyticsEvent(
            event_id=eid,
            request_id=eid,
            query=f"q{eid}",
            confidence_score=0.5,
            confidence_level="medium",
            faithfulness_score=0.5,
            hallucination_detected=False,
            hallucination_risk_level="low",
            attribution_coverage_ratio=0.5,
            citation_coverage_ratio=0.5,
            source_count=1,
            latency_ms=latency,
            total_tokens=tokens,
            timestamp=ts,
        )

    class _Stub:
        def conversations(self):
            return []

        def memories(self):
            return []

        def feedback(self):
            return []

        def answer_events(self):
            return [
                _ev(
                    "old", 500, 100.0, datetime.now(timezone.utc) - timedelta(days=365)
                ),
                _ev("new", 1500, 200.0, datetime.now(timezone.utc)),
            ]

    svc = CopilotAnalyticsService(repository=_Stub())
    usage_last_day = svc.usage(window=AnalyticsWindow.LAST_DAY)
    usage_all = svc.usage(window=AnalyticsWindow.ALL)
    assert usage_last_day.total_requests == 1
    assert usage_all.total_requests == 2
    assert usage_all.total_tokens == 2000


# ─── Build default service ──────────────────────────────────────────────


def test_build_default_service():
    svc = build_default_copilot_analytics_service()
    assert isinstance(svc, CopilotAnalyticsService)
    # Should not raise
    m = svc.metrics(window=AnalyticsWindow.LAST_WEEK)
    assert m.conversations.total_conversations == 0


# ─── API integration ────────────────────────────────────────────────────


@pytest.fixture
def api_client():
    reset_copilot_analytics_service()
    app = FastAPI()
    app.include_router(analytics_api_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_api_health(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/copilot/analytics-health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["module"] == "copilot_analytics"


@pytest.mark.asyncio
async def test_api_analytics(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/copilot/analytics?window=last_day")
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "last_day"
    assert "conversations" in body
    assert "memory" in body
    assert "latency" in body


@pytest.mark.asyncio
async def test_api_usage(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/copilot/usage?window=all")
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "all"
    assert "total_requests" in body
    assert "estimated_cost_usd" in body


@pytest.mark.asyncio
async def test_api_invalid_window_returns_422(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/copilot/analytics?window=bogus")
    assert r.status_code == 422
