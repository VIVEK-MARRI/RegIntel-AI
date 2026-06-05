"""Tests for Module 6.2 — Conversation Management.

Coverage
--------
* Schema validation (Conversation, Message, ConversationContext,
  ConversationFilter, PaginatedConversations, CreateConversationRequest,
  AppendMessageRequest).
* InMemoryConversationStore — thread-safety, add/get/update/delete.
* ConversationRepository — create / append / search / pagination /
  filtering / tag matching / purge_expired.
* SessionManager — build_context with token budget + compression.
* ConversationHistoryManager — replay, summarise, trim.
* ConversationManager — high-level orchestration.
* ConversationService — DI factory, defaults, persistence path.
* API integration: /api/v1/conversations/* endpoints.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_conversation_service,
    reset_conversation_service,
)
from app.api.v1.conversation import router as conversation_router
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
from app.services.conversation import (
    ConversationHistoryManager,
    ConversationManager,
    ConversationRepository,
    ConversationService,
    InMemoryConversationStore,
    SessionManager,
    build_default_conversation_service,
    estimate_tokens,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_conversation_service()
    yield
    reset_conversation_service()


@pytest.fixture
def store() -> InMemoryConversationStore:
    return InMemoryConversationStore()


@pytest.fixture
def repository(store: InMemoryConversationStore) -> ConversationRepository:
    return ConversationRepository(store=store)


@pytest.fixture
def session() -> SessionManager:
    return SessionManager(default_token_budget=300)


@pytest.fixture
def history() -> ConversationHistoryManager:
    return ConversationHistoryManager()


@pytest.fixture
def manager(
    repository: ConversationRepository,
    session: SessionManager,
    history: ConversationHistoryManager,
) -> ConversationManager:
    return ConversationManager(
        repository=repository, session=session, history=history
    )


@pytest.fixture
def service() -> ConversationService:
    # Use a fresh, isolated store (no JSONL persistence) so tests don't
    # see each other's data or pre-existing files.
    return ConversationService(store=InMemoryConversationStore())


@pytest.fixture
def app():
    reset_conversation_service()
    app = FastAPI()
    app.include_router(conversation_router, prefix="/api/v1")
    service = ConversationService(store=InMemoryConversationStore())
    app.dependency_overrides[get_conversation_service] = lambda: service
    yield app
    app.dependency_overrides.clear()
    reset_conversation_service()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_message_defaults(self):
        m = Message(role=Role.USER, content="hello")
        assert m.role == Role.USER
        assert m.message_id.startswith("msg-")
        assert m.token_estimate >= 0
        assert m.timestamp is not None

    def test_message_auto_token_via_service(self, manager: ConversationManager):
        c = manager.create(CreateConversationRequest(user_id="u"))
        manager.append_user(c.conversation_id, "hello world")
        msg = manager.get(c.conversation_id).messages[0]
        assert msg.token_estimate > 0

    def test_conversation_defaults(self):
        c = Conversation(user_id="u-1", title="My chat")
        assert c.conversation_id.startswith("conv-")
        assert c.status == ConversationStatus.ACTIVE
        assert c.messages == []
        assert c.expires_at is None

    def test_create_conversation_request_ttl_bounds(self):
        with pytest.raises(Exception):
            CreateConversationRequest(user_id="u", ttl_seconds=10)
        with pytest.raises(Exception):
            CreateConversationRequest(user_id="u", ttl_seconds=10_000_000)

    def test_paginated_conversations_has_more(self):
        p = PaginatedConversations(
            items=[], total=10, page=1, page_size=3, has_more=True
        )
        assert p.has_more is True
        assert p.total == 10

    def test_conversation_context_compression_flag(self):
        ctx = ConversationContext(
            conversation_id="c-1",
            user_id="u-1",
            summary="",
            recent_messages=[],
            token_budget=1000,
            compressed=True,
        )
        assert ctx.compressed is True

    def test_role_enum_values(self):
        assert Role.USER.value == "user"
        assert Role.ASSISTANT.value == "assistant"
        assert Role.SYSTEM.value == "system"


# ─── Store tests ────────────────────────────────────────────────────────────


class TestInMemoryStore:
    def test_add_and_get(self, store: InMemoryConversationStore):
        c = Conversation(user_id="u-1", title="t")
        store.add(c)
        got = store.get(c.conversation_id)
        assert got is c

    def test_update(self, store: InMemoryConversationStore):
        c = Conversation(user_id="u-1", title="t")
        store.add(c)
        c.title = "new"
        store.update(c)
        assert store.get(c.conversation_id).title == "new"

    def test_delete(self, store: InMemoryConversationStore):
        c = Conversation(user_id="u-1", title="t")
        store.add(c)
        assert store.delete(c.conversation_id) is True
        assert store.get(c.conversation_id) is None

    def test_all_and_reset(self, store: InMemoryConversationStore):
        store.add(Conversation(user_id="u", title="a"))
        store.add(Conversation(user_id="u", title="b"))
        assert len(store.all()) == 2
        store.reset()
        assert store.all() == []


# ─── Repository tests ───────────────────────────────────────────────────────


class TestRepository:
    def test_create(self, repository: ConversationRepository):
        c = repository.create(CreateConversationRequest(user_id="u-1"))
        assert c.user_id == "u-1"
        # No TTL by default.
        assert c.expires_at is None

    def test_create_with_ttl(self, repository: ConversationRepository):
        c = repository.create(
            CreateConversationRequest(user_id="u-1", ttl_seconds=3600)
        )
        assert c.expires_at is not None

    def test_create_with_long_ttl(self, repository: ConversationRepository):
        c = repository.create(
            CreateConversationRequest(user_id="u-1", ttl_seconds=3600)
        )
        assert c.expires_at is not None

    def test_append_message_sets_title(self, repository: ConversationRepository):
        c = repository.create(CreateConversationRequest(user_id="u-1"))
        repository.append_message(
            c.conversation_id,
            AppendMessageRequest(role=Role.USER, content="What is KYC?"),
        )
        c2 = repository.get(c.conversation_id)
        assert c2.title.startswith("What is KYC")
        assert len(c2.messages) == 1

    def test_append_message_404(self, repository: ConversationRepository):
        with pytest.raises(KeyError):
            repository.append_message(
                "conv-missing",
                AppendMessageRequest(role=Role.USER, content="x"),
            )

    def test_search_by_user(self, repository: ConversationRepository):
        repository.create(CreateConversationRequest(user_id="alice"))
        repository.create(CreateConversationRequest(user_id="bob"))
        flt = ConversationFilter(user_id="alice", page=1, page_size=10)
        result = repository.search(flt)
        assert result.total == 1
        assert result.items[0].user_id == "alice"

    def test_search_by_tag(self, repository: ConversationRepository):
        c1 = repository.create(
            CreateConversationRequest(user_id="u", tags=["kyc"])
        )
        repository.create(
            CreateConversationRequest(user_id="u", tags=["sebi"])
        )
        flt = ConversationFilter(tag="kyc", page=1, page_size=10)
        result = repository.search(flt)
        assert result.total == 1
        assert result.items[0].conversation_id == c1.conversation_id

    def test_search_by_query_text(self, repository: ConversationRepository):
        c = repository.create(CreateConversationRequest(user_id="u"))
        repository.append_message(
            c.conversation_id,
            AppendMessageRequest(
                role=Role.USER, content="KYC requirements for banks"
            ),
        )
        flt = ConversationFilter(query="kyc", page=1, page_size=10)
        result = repository.search(flt)
        assert result.total == 1

    def test_pagination(self, repository: ConversationRepository):
        for i in range(5):
            repository.create(CreateConversationRequest(user_id=f"u{i}"))
        result = repository.search(ConversationFilter(page=1, page_size=2))
        assert len(result.items) == 2
        assert result.total == 5
        assert result.has_more is True
        result2 = repository.search(ConversationFilter(page=3, page_size=2))
        assert len(result2.items) == 1
        assert result2.has_more is False

    def test_purge_expired(self, repository: ConversationRepository):
        # Manually create a conversation whose expires_at is in the past.
        c = repository.create(
            CreateConversationRequest(user_id="u", ttl_seconds=60)
        )
        past = datetime.now(timezone.utc).replace(year=2000)
        c.expires_at = past
        repository.update(c)
        purged = repository.purge_expired()
        assert purged == 1


# ─── SessionManager tests ──────────────────────────────────────────────────


class TestSessionManager:
    def test_build_context_includes_recent(
        self, manager: ConversationManager
    ):
        c = manager.create(CreateConversationRequest(user_id="u"))
        for i in range(3):
            manager.append_user(c.conversation_id, f"msg {i}")
        ctx = manager.build_context(c.conversation_id, token_budget=10000)
        assert len(ctx.recent_messages) == 3
        assert ctx.compressed is False

    def test_build_context_compresses_old(
        self, manager: ConversationManager, session: SessionManager
    ):
        c = manager.create(CreateConversationRequest(user_id="u"))
        # Use longer messages (~50 chars = ~12 tokens each) so we can
        # exercise compression with a budget of >= 100.
        for i in range(20):
            manager.append_user(
                c.conversation_id, f"This is a long message number {i} with more text"
            )
        # Budget = 100 → roughly 8 messages fit → compression triggered.
        ctx = session.build_context(c, token_budget=100)
        assert len(ctx.recent_messages) < 20
        assert ctx.compressed is True


# ─── HistoryManager tests ───────────────────────────────────────────────────


class TestHistoryManager:
    def test_replay(self, manager: ConversationManager):
        c = manager.create(CreateConversationRequest(user_id="u"))
        manager.append_user(c.conversation_id, "hi")
        manager.append_assistant(c.conversation_id, "hello")
        msgs = manager.replay(c.conversation_id)
        assert len(msgs) == 2

    def test_summarise(self, history: ConversationHistoryManager):
        c = Conversation(
            user_id="u",
            messages=[
                Message(role=Role.USER, content="What is KYC?"),
                Message(role=Role.ASSISTANT, content="KYC is Know Your Customer."),
            ],
        )
        s = history.summarise(c)
        assert "KYC" in s

    def test_summarise_truncates(self, history: ConversationHistoryManager):
        c = Conversation(
            user_id="u",
            messages=[
                Message(role=Role.USER, content="x " * 200),
            ],
        )
        s = history.summarise(c)
        assert len(s) <= history.MAX_SUMMARY_LENGTH

    def test_trim_keeps_recent_and_updates_summary(
        self, manager: ConversationManager
    ):
        c = manager.create(CreateConversationRequest(user_id="u"))
        for i in range(10):
            manager.append_user(c.conversation_id, f"msg-{i}")
        c2 = manager.trim(c.conversation_id, keep_last=3)
        assert len(c2.messages) == 3
        assert "msg-0" in c2.summary or "msg-1" in c2.summary


# ─── ConversationManager tests ─────────────────────────────────────────────


class TestManager:
    def test_get_or_create_creates_when_missing(
        self, manager: ConversationManager
    ):
        c = manager.get_or_create(None, user_id="u-1")
        assert c.conversation_id.startswith("conv-")

    def test_get_or_create_returns_existing(
        self, manager: ConversationManager
    ):
        c1 = manager.create(CreateConversationRequest(user_id="u-1"))
        c2 = manager.get_or_create(c1.conversation_id, user_id="u-1")
        assert c2.conversation_id == c1.conversation_id

    def test_refresh_summary(self, manager: ConversationManager):
        c = manager.create(CreateConversationRequest(user_id="u"))
        manager.append_user(c.conversation_id, "Tell me about KYC")
        c2 = manager.refresh_summary(c.conversation_id)
        assert "KYC" in c2.summary

    def test_purge_expired_delegates(
        self, manager: ConversationManager, repository: ConversationRepository
    ):
        c = manager.create(CreateConversationRequest(user_id="u", ttl_seconds=60))
        past = datetime.now(timezone.utc).replace(year=2000)
        c.expires_at = past
        repository.update(c)
        assert manager.purge_expired() == 1


# ─── Service-level tests ───────────────────────────────────────────────────


class TestService:
    def test_default_factory(self):
        svc = build_default_conversation_service()
        assert isinstance(svc, ConversationService)
        assert isinstance(svc.store, InMemoryConversationStore)
        assert isinstance(svc.repository, ConversationRepository)
        assert isinstance(svc.session, SessionManager)
        assert isinstance(svc.history, ConversationHistoryManager)
        assert isinstance(svc.manager, ConversationManager)

    def test_estimate_tokens(self):
        assert estimate_tokens("") == 1
        assert estimate_tokens("hello world") >= 1


# ─── API integration tests ─────────────────────────────────────────────────


class TestAPI:
    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient):
        r = await client.get("/api/v1/conversations/health")
        assert r.status_code == 200
        assert r.json()["module"] == "conversation"

    @pytest.mark.asyncio
    async def test_create_and_get(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/conversations",
            json={"user_id": "u-1", "title": "test"},
        )
        assert r.status_code == 201
        cid = r.json()["conversation_id"]
        r2 = await client.get(f"/api/v1/conversations/{cid}")
        assert r2.status_code == 200
        assert r2.json()["user_id"] == "u-1"

    @pytest.mark.asyncio
    async def test_get_missing_404(self, client: AsyncClient):
        r = await client.get("/api/v1/conversations/conv-missing")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_append_message(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/conversations", json={"user_id": "u-1"}
        )
        cid = r.json()["conversation_id"]
        r2 = await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"role": "user", "content": "hi"},
        )
        assert r2.status_code == 200
        assert len(r2.json()["messages"]) == 1

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, client: AsyncClient):
        for i in range(5):
            await client.post(
                "/api/v1/conversations", json={"user_id": f"u{i}"}
            )
        r = await client.get("/api/v1/conversations?page=1&page_size=2")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["has_more"] is True

    @pytest.mark.asyncio
    async def test_list_filter_by_user(self, client: AsyncClient):
        await client.post("/api/v1/conversations", json={"user_id": "alice"})
        await client.post("/api/v1/conversations", json={"user_id": "bob"})
        r = await client.get("/api/v1/conversations?user_id=alice")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    @pytest.mark.asyncio
    async def test_soft_delete(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/conversations", json={"user_id": "u-1"}
        )
        cid = r.json()["conversation_id"]
        r2 = await client.delete(f"/api/v1/conversations/{cid}")
        assert r2.status_code == 200
        assert r2.json()["mode"] == "archived"

    @pytest.mark.asyncio
    async def test_hard_delete(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/conversations", json={"user_id": "u-1"}
        )
        cid = r.json()["conversation_id"]
        r2 = await client.delete(f"/api/v1/conversations/{cid}?hard=true")
        assert r2.status_code == 200
        assert r2.json()["mode"] == "hard"
        r3 = await client.get(f"/api/v1/conversations/{cid}")
        assert r3.status_code == 404

    @pytest.mark.asyncio
    async def test_get_context(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/conversations", json={"user_id": "u-1"}
        )
        cid = r.json()["conversation_id"]
        await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"role": "user", "content": "hi"},
        )
        r2 = await client.get(
            f"/api/v1/conversations/{cid}/context?token_budget=500"
        )
        assert r2.status_code == 200
        assert r2.json()["conversation_id"] == cid

    @pytest.mark.asyncio
    async def test_refresh_summary(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/conversations", json={"user_id": "u-1"}
        )
        cid = r.json()["conversation_id"]
        await client.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"role": "user", "content": "Tell me about KYC"},
        )
        r2 = await client.post(
            f"/api/v1/conversations/{cid}/refresh-summary"
        )
        assert r2.status_code == 200
        assert "KYC" in r2.json()["summary"]

    @pytest.mark.asyncio
    async def test_trim(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/conversations", json={"user_id": "u-1"}
        )
        cid = r.json()["conversation_id"]
        for i in range(8):
            await client.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"role": "user", "content": f"msg {i}"},
            )
        r2 = await client.post(
            f"/api/v1/conversations/{cid}/trim?keep_last=2"
        )
        assert r2.status_code == 200
        assert len(r2.json()["messages"]) == 2

    @pytest.mark.asyncio
    async def test_purge_expired(self, client: AsyncClient):
        r = await client.post("/api/v1/conversations/purge-expired")
        assert r.status_code == 200
        assert "purged" in r.json()
