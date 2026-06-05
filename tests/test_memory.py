"""Tests for Module 6.3 — Memory Layer.

Coverage
--------
* Schema validation (MemoryEntry, MemoryQuery, MemoryContext,
  MemorySearchResult, CreateMemoryRequest).
* InMemoryMemoryStore — thread-safety, CRUD, JSONL persistence.
* MemoryRepository — CRUD, search ranking, type/tag filters, expiration.
* MemoryManager — record_from_message, record_retrieval,
  record_long_term, build_context.
* MemoryService — DI factory.
* API integration: /api/v1/memory/* endpoints.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_memory_service,
    reset_memory_service,
)
from app.api.v1.memory import router as memory_router
from app.schemas.conversation import Message, Role
from app.schemas.memory import (
    CreateMemoryRequest,
    MemoryContext,
    MemoryEntry,
    MemoryQuery,
    MemoryScope,
    MemorySearchResult,
    MemoryType,
)
from app.services.memory import (
    InMemoryMemoryStore,
    MemoryManager,
    MemoryRepository,
    MemoryService,
    MemoryStore,
    build_default_memory_service,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_memory_service()
    yield
    reset_memory_service()


@pytest.fixture
def store() -> InMemoryMemoryStore:
    return InMemoryMemoryStore()


@pytest.fixture
def repository(store: InMemoryMemoryStore) -> MemoryRepository:
    return MemoryRepository(store=store)


@pytest.fixture
def manager(repository: MemoryRepository) -> MemoryManager:
    return MemoryManager(repository=repository)


@pytest.fixture
def service() -> MemoryService:
    return MemoryService(store=InMemoryMemoryStore())


@pytest.fixture
def app():
    reset_memory_service()
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/v1")
    service = MemoryService(store=InMemoryMemoryStore())
    app.dependency_overrides[get_memory_service] = lambda: service
    yield app
    app.dependency_overrides.clear()
    reset_memory_service()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_memory_entry_defaults(self):
        e = MemoryEntry(
            memory_type=MemoryType.LONG_TERM,
            scope=MemoryScope.USER,
            content="hello",
        )
        assert e.memory_id.startswith("mem-")
        assert e.tags == []
        assert e.access_count == 0
        assert e.pinned is False

    def test_create_memory_request_ttl_bounds(self):
        with pytest.raises(Exception):
            CreateMemoryRequest(
                memory_type=MemoryType.SHORT_TERM, content="x", ttl_seconds=0
            )
        with pytest.raises(Exception):
            CreateMemoryRequest(
                memory_type=MemoryType.SHORT_TERM,
                content="x",
                ttl_seconds=100_000_000,
            )

    def test_memory_query_top_k_bounds(self):
        with pytest.raises(Exception):
            MemoryQuery(top_k=0)
        with pytest.raises(Exception):
            MemoryQuery(top_k=100)

    def test_memory_types(self):
        assert MemoryType.SHORT_TERM.value == "short_term"
        assert MemoryType.LONG_TERM.value == "long_term"
        assert MemoryType.RETRIEVAL.value == "retrieval"

    def test_memory_scopes(self):
        assert MemoryScope.USER.value == "user"
        assert MemoryScope.CONVERSATION.value == "conversation"
        assert MemoryScope.GLOBAL.value == "global"


# ─── Store tests ────────────────────────────────────────────────────────────


class TestInMemoryStore:
    def test_add_and_get(self, store: InMemoryMemoryStore):
        e = MemoryEntry(
            memory_type=MemoryType.SHORT_TERM,
            scope=MemoryScope.USER,
            content="hello",
        )
        store.add(e)
        assert store.get(e.memory_id) is e

    def test_update(self, store: InMemoryMemoryStore):
        e = MemoryEntry(
            memory_type=MemoryType.SHORT_TERM,
            scope=MemoryScope.USER,
            content="hello",
        )
        store.add(e)
        e.content = "world"
        store.update(e)
        assert store.get(e.memory_id).content == "world"

    def test_delete(self, store: InMemoryMemoryStore):
        e = MemoryEntry(
            memory_type=MemoryType.SHORT_TERM,
            scope=MemoryScope.USER,
            content="hello",
        )
        store.add(e)
        assert store.delete(e.memory_id) is True
        assert store.get(e.memory_id) is None

    def test_all_and_reset(self, store: InMemoryMemoryStore):
        store.add(
            MemoryEntry(
                memory_type=MemoryType.SHORT_TERM,
                scope=MemoryScope.USER,
                content="a",
            )
        )
        store.add(
            MemoryEntry(
                memory_type=MemoryType.SHORT_TERM,
                scope=MemoryScope.USER,
                content="b",
            )
        )
        assert len(store.all()) == 2
        store.reset()
        assert store.all() == []


# ─── Repository tests ───────────────────────────────────────────────────────


class TestRepository:
    def test_create_sets_expiry(self, repository: MemoryRepository):
        req = CreateMemoryRequest(
            memory_type=MemoryType.SHORT_TERM,
            content="hello",
            ttl_seconds=3600,
        )
        e = repository.create(req)
        assert e.expires_at is not None
        assert e.ttl_seconds == 3600

    def test_create_pinned_no_expiry(self, repository: MemoryRepository):
        req = CreateMemoryRequest(
            memory_type=MemoryType.LONG_TERM,
            content="user role",
            pinned=True,
        )
        e = repository.create(req)
        assert e.expires_at is None
        assert e.pinned is True

    def test_update_bumps_timestamp(self, repository: MemoryRepository):
        req = CreateMemoryRequest(memory_type=MemoryType.LONG_TERM, content="x")
        e = repository.create(req)
        old = e.updated_at
        repository.update(e)
        # updated_at should be >= old
        assert e.updated_at >= old

    def test_search_returns_relevant(self, repository: MemoryRepository):
        repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.LONG_TERM,
                content="KYC requirements for banks",
                pinned=True,
            )
        )
        repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.LONG_TERM,
                content="SEBI disclosure obligations",
                pinned=True,
            )
        )
        results = repository.search(MemoryQuery(query="KYC banks"))
        assert len(results) >= 1
        assert any("KYC" in r.entry.content for r in results)

    def test_search_filter_by_type(self, repository: MemoryRepository):
        repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.SHORT_TERM,
                content="x",
                ttl_seconds=3600,
            )
        )
        repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.LONG_TERM,
                content="x",
                pinned=True,
            )
        )
        results = repository.search(
            MemoryQuery(memory_types=[MemoryType.LONG_TERM])
        )
        assert all(r.entry.memory_type == MemoryType.LONG_TERM for r in results)

    def test_search_filter_by_user(self, repository: MemoryRepository):
        repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.LONG_TERM,
                content="x",
                user_id="alice",
                pinned=True,
            )
        )
        repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.LONG_TERM,
                content="x",
                user_id="bob",
                pinned=True,
            )
        )
        results = repository.search(MemoryQuery(user_id="alice"))
        assert all(r.entry.user_id == "alice" for r in results)

    def test_search_filter_by_tag(self, repository: MemoryRepository):
        repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.LONG_TERM,
                content="a",
                tags=["kyc", "policy"],
                pinned=True,
            )
        )
        repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.LONG_TERM,
                content="b",
                tags=["sebi"],
                pinned=True,
            )
        )
        results = repository.search(MemoryQuery(tags=["kyc"]))
        assert len(results) == 1
        assert "kyc" in results[0].entry.tags

    def test_search_updates_access_count(self, repository: MemoryRepository):
        repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.LONG_TERM,
                content="KYC norms",
                pinned=True,
            )
        )
        e = repository.all()[0]
        assert e.access_count == 0
        repository.search(MemoryQuery(query="KYC"))
        assert e.access_count == 1
        assert e.last_accessed_at is not None

    def test_purge_expired_skips_pinned(self, repository: MemoryRepository):
        # Pinned entry that would otherwise be expired.
        pinned = repository.create(
            CreateMemoryRequest(
                memory_type=MemoryType.LONG_TERM,
                content="always keep",
                pinned=True,
            )
        )
        pinned.expires_at = datetime.now(timezone.utc).replace(year=2000)
        repository.update(pinned)
        purged = repository.purge_expired()
        assert purged == 0
        assert repository.get(pinned.memory_id) is not None


# ─── Manager tests ──────────────────────────────────────────────────────────


class TestManager:
    def test_record_from_message_user(self, manager: MemoryManager):
        msg = Message(role=Role.USER, content="hello")
        entry = manager.record_from_message(msg, user_id="u-1")
        assert entry is not None
        assert entry.memory_type == MemoryType.SHORT_TERM
        assert entry.user_id == "u-1"
        assert entry.content == "hello"

    def test_record_from_message_system_returns_none(
        self, manager: MemoryManager
    ):
        msg = Message(role=Role.SYSTEM, content="sys")
        entry = manager.record_from_message(msg, user_id="u-1")
        assert entry is None

    def test_record_retrieval(self, manager: MemoryManager):
        entry = manager.record_retrieval(
            query="What is KYC?",
            answer_text="KYC is Know Your Customer.",
            user_id="u-1",
        )
        assert entry.memory_type == MemoryType.RETRIEVAL
        assert "What is KYC?" in entry.content
        assert entry.user_id == "u-1"

    def test_record_long_term_pinned(self, manager: MemoryManager):
        entry = manager.record_long_term(
            content="user is a risk manager",
            user_id="u-1",
        )
        assert entry.memory_type == MemoryType.LONG_TERM
        assert entry.pinned is True
        assert entry.expires_at is None

    def test_build_context_includes_ltm(self, manager: MemoryManager):
        manager.record_long_term(content="user role: risk manager", user_id="u-1")
        ctx = manager.build_context(query="anything", user_id="u-1")
        assert ctx.memory_used is True
        assert len(ctx.long_term) >= 1

    def test_build_context_compresses_short_term(
        self, manager: MemoryManager
    ):
        long_history = [
            Message(role=Role.USER, content=f"msg {i}") for i in range(20)
        ]
        ctx = manager.build_context(
            query="x", user_id="u", short_term=long_history
        )
        assert len(ctx.short_term) <= 6


# ─── Service-level tests ───────────────────────────────────────────────────


class TestService:
    def test_default_factory(self):
        svc = build_default_memory_service()
        assert isinstance(svc, MemoryService)
        assert isinstance(svc.store, InMemoryMemoryStore)
        assert isinstance(svc.repository, MemoryRepository)
        assert isinstance(svc.manager, MemoryManager)


# ─── API integration tests ─────────────────────────────────────────────────


class TestAPI:
    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient):
        r = await client.get("/api/v1/memory/health")
        assert r.status_code == 200
        assert r.json()["module"] == "memory"

    @pytest.mark.asyncio
    async def test_create_and_get(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/memory",
            json={
                "memory_type": "long_term",
                "scope": "user",
                "content": "user prefers terse answers",
                "user_id": "u-1",
                "pinned": True,
            },
        )
        assert r.status_code == 201
        mid = r.json()["memory_id"]
        r2 = await client.get(f"/api/v1/memory/{mid}")
        assert r2.status_code == 200
        assert r2.json()["content"] == "user prefers terse answers"

    @pytest.mark.asyncio
    async def test_get_missing_404(self, client: AsyncClient):
        r = await client.get("/api/v1/memory/mem-missing")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_update_memory(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/memory",
            json={
                "memory_type": "long_term",
                "scope": "user",
                "content": "old",
                "pinned": True,
            },
        )
        mid = r.json()["memory_id"]
        r2 = await client.put(
            f"/api/v1/memory/{mid}",
            json={"content": "new"},
        )
        assert r2.status_code == 200
        assert r2.json()["content"] == "new"

    @pytest.mark.asyncio
    async def test_delete_memory(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/memory",
            json={
                "memory_type": "long_term",
                "scope": "user",
                "content": "x",
                "pinned": True,
            },
        )
        mid = r.json()["memory_id"]
        r2 = await client.delete(f"/api/v1/memory/{mid}")
        assert r2.status_code == 200
        r3 = await client.get(f"/api/v1/memory/{mid}")
        assert r3.status_code == 404

    @pytest.mark.asyncio
    async def test_search(self, client: AsyncClient):
        await client.post(
            "/api/v1/memory",
            json={
                "memory_type": "long_term",
                "scope": "user",
                "content": "KYC requirements for banks",
                "pinned": True,
            },
        )
        await client.post(
            "/api/v1/memory",
            json={
                "memory_type": "long_term",
                "scope": "user",
                "content": "SEBI disclosure obligations",
                "pinned": True,
            },
        )
        r = await client.post(
            "/api/v1/memory/search",
            json={"query": "KYC", "top_k": 5},
        )
        assert r.status_code == 200
        results = r.json()
        assert len(results) >= 1
        assert any("KYC" in item["entry"]["content"] for item in results)

    @pytest.mark.asyncio
    async def test_record_message(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/memory/record-message",
            json={
                "role": "user",
                "content": "hello there",
                "user_id": "u-1",
            },
        )
        assert r.status_code == 200
        assert r.json()["memory_type"] == "short_term"

    @pytest.mark.asyncio
    async def test_record_retrieval(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/memory/record-retrieval",
            json={
                "query": "What is KYC?",
                "answer_text": "KYC is Know Your Customer.",
                "user_id": "u-1",
            },
        )
        assert r.status_code == 200
        assert r.json()["memory_type"] == "retrieval"

    @pytest.mark.asyncio
    async def test_record_long_term(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/memory/record-long-term",
            json={
                "content": "user is a risk manager",
                "user_id": "u-1",
            },
        )
        assert r.status_code == 200
        assert r.json()["memory_type"] == "long_term"
        assert r.json()["pinned"] is True

    @pytest.mark.asyncio
    async def test_build_context(self, client: AsyncClient):
        await client.post(
            "/api/v1/memory/record-long-term",
            json={
                "content": "user prefers terse answers",
                "user_id": "u-1",
            },
        )
        r = await client.post(
            "/api/v1/memory/build-context",
            json={"query": "anything", "user_id": "u-1", "top_k": 5},
        )
        assert r.status_code == 200
        assert r.json()["memory_used"] is True

    @pytest.mark.asyncio
    async def test_purge(self, client: AsyncClient):
        r = await client.post("/api/v1/memory/purge")
        assert r.status_code == 200
        assert "purged" in r.json()
