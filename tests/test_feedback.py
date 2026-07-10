"""Tests for Module 6.6 — Feedback Intelligence."""

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

from app.api.dependencies import get_feedback_service  # noqa: E402
from app.api.v1.feedback import router as feedback_router  # noqa: E402
from app.schemas.feedback import (  # noqa: E402
    FeedbackCategory,
    FeedbackEntry,
    FeedbackFilter,
    FeedbackRequest,
    FeedbackSeverity,
    FeedbackStats,
    FeedbackType,
    PaginatedFeedback,
)
from app.services.feedback import (  # noqa: E402
    FeedbackAnalytics,
    FeedbackManager,
    FeedbackRepository,
    FeedbackService,
    InMemoryFeedbackStore,
    build_default_feedback_service,
)


# ─── Schemas ────────────────────────────────────────────────────────────


def test_feedback_entry_generates_id():
    e = FeedbackEntry(request_id="r1", feedback_type=FeedbackType.THUMBS_UP)
    assert e.feedback_id.startswith("fb-")
    assert len(e.feedback_id) > 5


def test_feedback_request_minimal():
    r = FeedbackRequest(request_id="r1", feedback_type=FeedbackType.THUMBS_UP)
    assert r.category == FeedbackCategory.ANSWER_QUALITY
    assert r.severity == FeedbackSeverity.LOW
    assert r.flagged_citations == []


def test_feedback_request_validates_request_id():
    with pytest.raises(Exception):
        FeedbackRequest(request_id="", feedback_type=FeedbackType.THUMBS_UP)


def test_feedback_filter_defaults():
    f = FeedbackFilter()
    assert f.page == 1
    assert f.page_size == 50
    assert f.sort_desc is True


def test_feedback_filter_validates_page():
    with pytest.raises(Exception):
        FeedbackFilter(page=0)


def test_paginated_feedback_model():
    p = PaginatedFeedback(items=[], total=0, page=1, page_size=10, has_more=False)
    assert p.total == 0


def test_feedback_stats_defaults():
    s = FeedbackStats()
    assert s.total == 0
    assert s.satisfaction_ratio == 0.0


# ─── Store ──────────────────────────────────────────────────────────────


def test_in_memory_store_add_and_all():
    store = InMemoryFeedbackStore()
    e = FeedbackEntry(request_id="r1", feedback_type=FeedbackType.THUMBS_UP)
    store.add(e)
    items = store.all()
    assert len(items) == 1
    assert items[0].feedback_id == e.feedback_id


def test_in_memory_store_reset():
    store = InMemoryFeedbackStore()
    e = FeedbackEntry(request_id="r1", feedback_type=FeedbackType.THUMBS_UP)
    store.add(e)
    store.reset()
    assert store.all() == []


def test_in_memory_store_persists_to_disk(tmp_path):
    p = tmp_path / "feedback.jsonl"
    store = InMemoryFeedbackStore(persist_path=p)
    e = FeedbackEntry(request_id="r1", feedback_type=FeedbackType.THUMBS_UP)
    store.add(e)
    text = p.read_text(encoding="utf-8")
    assert "r1" in text


# ─── Repository ─────────────────────────────────────────────────────────


def test_repository_add_creates_entry():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    req = FeedbackRequest(request_id="r1", feedback_type=FeedbackType.THUMBS_UP)
    e = repo.add(req)
    assert e.request_id == "r1"


def test_repository_get_by_id():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    e = repo.add(FeedbackRequest(request_id="r1", feedback_type=FeedbackType.THUMBS_UP))
    assert repo.get(e.feedback_id) is not None
    assert repo.get("nope") is None


def test_repository_all():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    repo.add(FeedbackRequest(request_id="r1", feedback_type=FeedbackType.THUMBS_UP))
    repo.add(FeedbackRequest(request_id="r2", feedback_type=FeedbackType.THUMBS_DOWN))
    assert len(repo.all()) == 2


def test_repository_search_by_type():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    repo.add(FeedbackRequest(request_id="r1", feedback_type=FeedbackType.THUMBS_UP))
    repo.add(FeedbackRequest(request_id="r2", feedback_type=FeedbackType.THUMBS_DOWN))
    flt = FeedbackFilter(feedback_type=FeedbackType.THUMBS_UP)
    res = repo.search(flt)
    assert res.total == 1
    assert res.items[0].feedback_type == FeedbackType.THUMBS_UP


def test_repository_search_by_category():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    repo.add(
        FeedbackRequest(
            request_id="r1",
            feedback_type=FeedbackType.COMMENT,
            category=FeedbackCategory.HALLUCINATION,
        )
    )
    flt = FeedbackFilter(category=FeedbackCategory.HALLUCINATION)
    res = repo.search(flt)
    assert res.total == 1


def test_repository_search_pagination():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    for i in range(7):
        repo.add(
            FeedbackRequest(
                request_id=f"r{i}",
                feedback_type=FeedbackType.COMMENT,
            )
        )
    flt = FeedbackFilter(page=2, page_size=3, sort_desc=False)
    res = repo.search(flt)
    assert res.page == 2
    assert len(res.items) == 3
    assert res.has_more is True


# ─── Analytics ──────────────────────────────────────────────────────────


def test_analytics_aggregate_empty():
    a = FeedbackAnalytics()
    s = a.aggregate([])
    assert s.total == 0
    assert s.satisfaction_ratio == 0.0


def test_analytics_aggregate_counts():
    a = FeedbackAnalytics()
    entries = [
        FeedbackEntry(request_id="r1", feedback_type=FeedbackType.THUMBS_UP),
        FeedbackEntry(request_id="r2", feedback_type=FeedbackType.THUMBS_UP),
        FeedbackEntry(request_id="r3", feedback_type=FeedbackType.THUMBS_DOWN),
        FeedbackEntry(
            request_id="r4",
            feedback_type=FeedbackType.HALLUCINATION_REPORT,
        ),
    ]
    s = a.aggregate(entries)
    assert s.total == 4
    assert s.thumbs_up == 2
    assert s.thumbs_down == 1
    assert s.hallucination_reports == 1
    assert 0.6 < s.satisfaction_ratio < 0.7


def test_analytics_window_filters_old():
    a = FeedbackAnalytics()
    now = datetime.now(timezone.utc)
    entries = [
        FeedbackEntry(
            request_id="new",
            feedback_type=FeedbackType.THUMBS_UP,
            created_at=now,
        ),
        FeedbackEntry(
            request_id="old",
            feedback_type=FeedbackType.THUMBS_UP,
            created_at=now - timedelta(days=365),
        ),
    ]
    s = a.aggregate(entries, window=timedelta(days=1), now=now)
    assert s.total == 1
    assert s.window_start is not None
    assert s.window_end == now


# ─── Manager ────────────────────────────────────────────────────────────


def test_manager_record():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    mgr = FeedbackManager(repository=repo, analytics=FeedbackAnalytics())
    e = mgr.record(
        FeedbackRequest(request_id="r1", feedback_type=FeedbackType.THUMBS_UP)
    )
    assert e.request_id == "r1"


def test_manager_get():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    mgr = FeedbackManager(repository=repo, analytics=FeedbackAnalytics())
    e = mgr.record(
        FeedbackRequest(request_id="r1", feedback_type=FeedbackType.THUMBS_UP)
    )
    assert mgr.get(e.feedback_id) is not None
    assert mgr.get("nope") is None


def test_manager_search():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    mgr = FeedbackManager(repository=repo, analytics=FeedbackAnalytics())
    mgr.record(FeedbackRequest(request_id="r1", feedback_type=FeedbackType.THUMBS_UP))
    res = mgr.search(FeedbackFilter())
    assert res.total == 1


def test_manager_stats_with_filters():
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    mgr = FeedbackManager(repository=repo, analytics=FeedbackAnalytics())
    mgr.record(
        FeedbackRequest(
            request_id="r1",
            user_id="u1",
            feedback_type=FeedbackType.THUMBS_UP,
        )
    )
    mgr.record(
        FeedbackRequest(
            request_id="r2",
            user_id="u2",
            feedback_type=FeedbackType.THUMBS_DOWN,
        )
    )
    s = mgr.stats(user_id="u1")
    assert s.total == 1
    assert s.thumbs_up == 1


# ─── Service / factory ─────────────────────────────────────────────────


def test_feedback_service_defaults():
    svc = FeedbackService()
    assert isinstance(svc.store, InMemoryFeedbackStore)
    assert isinstance(svc.repository, FeedbackRepository)
    assert isinstance(svc.analytics, FeedbackAnalytics)
    assert isinstance(svc.manager, FeedbackManager)


def test_build_default_feedback_service():
    svc = build_default_feedback_service()
    assert isinstance(svc, FeedbackService)


# ─── API integration ────────────────────────────────────────────────────


@pytest.fixture
def fresh_service():
    """Per-test feedback service backed by a fresh in-memory store (no disk)."""
    store = InMemoryFeedbackStore()
    repo = FeedbackRepository(store=store)
    mgr = FeedbackManager(repository=repo, analytics=FeedbackAnalytics())
    return FeedbackService(
        store=store, repository=repo, manager=mgr, analytics=FeedbackAnalytics()
    )


@pytest.fixture
def api_client(fresh_service):
    app = FastAPI()
    app.include_router(feedback_router, prefix="/api/v1")
    app.dependency_overrides[get_feedback_service] = lambda: fresh_service
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_api_health(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/copilot/feedback/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_api_record_feedback(api_client):
    async with api_client as ac:
        r = await ac.post(
            "/api/v1/copilot/feedback",
            json={
                "request_id": "r1",
                "feedback_type": "thumbs_up",
                "category": "answer_quality",
            },
        )
    assert r.status_code == 201
    body = r.json()
    assert body["request_id"] == "r1"
    assert body["feedback_type"] == "thumbs_up"


@pytest.mark.asyncio
async def test_api_list_feedback(api_client):
    async with api_client as ac:
        await ac.post(
            "/api/v1/copilot/feedback",
            json={"request_id": "r1", "feedback_type": "thumbs_up"},
        )
        await ac.post(
            "/api/v1/copilot/feedback",
            json={"request_id": "r2", "feedback_type": "thumbs_down"},
        )
        r = await ac.get("/api/v1/copilot/feedback")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2


@pytest.mark.asyncio
async def test_api_get_feedback_by_id(api_client):
    async with api_client as ac:
        post = await ac.post(
            "/api/v1/copilot/feedback",
            json={"request_id": "r1", "feedback_type": "thumbs_up"},
        )
        eid = post.json()["feedback_id"]
        r = await ac.get(f"/api/v1/copilot/feedback/{eid}")
    assert r.status_code == 200
    assert r.json()["feedback_id"] == eid


@pytest.mark.asyncio
async def test_api_get_feedback_404(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/copilot/feedback/fb-doesnotexist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_stats(api_client):
    async with api_client as ac:
        await ac.post(
            "/api/v1/copilot/feedback",
            json={"request_id": "r1", "feedback_type": "thumbs_up"},
        )
        await ac.post(
            "/api/v1/copilot/feedback",
            json={"request_id": "r2", "feedback_type": "hallucination_report"},
        )
        r = await ac.get("/api/v1/copilot/feedback/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["thumbs_up"] == 1
    assert body["hallucination_reports"] == 1
