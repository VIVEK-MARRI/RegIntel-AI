"""Tests for Module 6.1 — Regulatory Copilot Service & API.

Coverage
--------
* Schema validation (CopilotRequest, CopilotResponse, CopilotMessage,
  CopilotMode).
* CopilotService — ASK flow with mocked orchestrator, memory recording,
  conversation history.
* CopilotController — input validation.
* Copilot modes: ANSWER, SUMMARISE, SEARCH.
* Multi-turn flow (same conversation_id).
* ``use_memory=False`` path.
* ``chunks`` parameter honoured / memory-synthesised fallback.
* No-chunks degraded path.
* API integration: /api/v1/copilot/query + /health.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_conversation_service,
    get_memory_service,
    get_response_orchestrator,
    reset_conversation_service,
    reset_memory_service,
    reset_response_orchestrator,
)
from app.api.v1.copilot import (
    get_copilot_service,
    reset_copilot_service,
    router as copilot_router,
)
from app.schemas.answer_generation import AnswerSection
from app.schemas.citation import AnnotatedAnswer, AnnotatedText
from app.schemas.confidence import ConfidenceLevel
from app.schemas.copilot import (
    CopilotMessage,
    CopilotMode,
    CopilotRequest,
)
from app.schemas.hallucination import HallucinationRiskLevel
from app.schemas.orchestrator import (
    FinalAnswerResponse,
    OrchestratorMetadata,
    OrchestratorRequest,
    StepResult,
    PipelineStep,
    PipelineStatus,
)
from app.services.copilot import (
    CopilotController,
    CopilotService,
    build_default_copilot_service,
)
from app.services.conversation import (
    ConversationService,
    InMemoryConversationStore,
)
from app.services.hybrid.pipeline import HybridRerankResponse
from app.services.memory import (
    InMemoryMemoryStore,
    MemoryService,
)
from app.schemas.reranker import RerankResult


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_copilot_service()
    reset_conversation_service()
    reset_memory_service()
    reset_response_orchestrator()
    yield
    reset_copilot_service()
    reset_conversation_service()
    reset_memory_service()
    reset_response_orchestrator()


class _FakeOrchestrator:
    """Records calls and returns a deterministic FinalAnswerResponse."""

    def __init__(self) -> None:
        self.calls: List[OrchestratorRequest] = []  # type: ignore[name-defined]

    async def answer(self, request):  # type: ignore[no-untyped-def]
        self.calls.append(request)
        return FinalAnswerResponse(
            query=request.query,
            answer=AnswerSection(
                executive_summary=f"Answer to {request.query!r}.",
                detailed_explanation="This is the detailed explanation.",
            ),
            citations=AnnotatedAnswer(
                executive_summary=AnnotatedText(text="hi"),
                detailed_explanation=AnnotatedText(text="hello"),
            ),
            confidence_score=0.85,
            confidence_level=ConfidenceLevel.HIGH,
            faithfulness_score=0.92,
            hallucination_detected=False,
            hallucination_risk_level=HallucinationRiskLevel.NONE,
            source_attributions=[],
            attribution_coverage_ratio=0.5,
            latency_ms=12.3,
            metadata=OrchestratorMetadata(
                request_id=request.request_id
                if hasattr(request, "request_id")
                else "test",
                model_used="mock",
                provider_used="mock",
                step_results=[
                    StepResult(
                        step=PipelineStep.ANSWER_GENERATION,
                        status=PipelineStatus.SUCCESS,
                    )
                ],
            ),
        )


@pytest.fixture
def fake_orchestrator() -> _FakeOrchestrator:
    return _FakeOrchestrator()


class _FakeHybridPipeline:
    """Records calls and returns a deterministic hybrid rerank response.

    Stands in for the real HybridRerankPipeline so the regression test can
    assert the copilot actually reaches retrieval instead of the degraded
    empty-answer path.
    """

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def search(self, query: str, **kwargs: Any) -> HybridRerankResponse:
        self.calls.append({"query": query, **kwargs})
        return HybridRerankResponse(
            query=query,
            results=[
                RerankResult(
                    chunk_id="chunk-abc",
                    rerank_score=0.91,
                    original_score=0.8,
                    original_rank=1,
                    new_rank=1,
                    content="KYC means Know Your Customer; banks must verify identity.",
                    metadata={
                        "document_id": "doc-1",
                        "source": "RBI",
                        "page_number": 3,
                        "section": "Customer Due Diligence",
                        "subsection": "Identification",
                        "document_title": "KYC Master Direction",
                    },
                )
            ],
        )


@pytest.fixture
def memory_service() -> MemoryService:
    return MemoryService(store=InMemoryMemoryStore())


@pytest.fixture
def conversation_service() -> ConversationService:
    return ConversationService(store=InMemoryConversationStore())


@pytest.fixture
def copilot_service(
    fake_orchestrator: _FakeOrchestrator,
    memory_service: MemoryService,
    conversation_service: ConversationService,
) -> CopilotService:
    return build_default_copilot_service(
        orchestrator=fake_orchestrator,
        memory=memory_service,
        conversation=conversation_service,
    )


@pytest.fixture
def controller(
    copilot_service: CopilotService,
) -> CopilotController:
    return CopilotController(service=copilot_service)


@pytest.fixture
def copilot_service_with_hybrid(
    fake_orchestrator: _FakeOrchestrator,
    memory_service: MemoryService,
    conversation_service: ConversationService,
) -> CopilotService:
    """Service wired to a fake hybrid pipeline (P0.0 regression fixture)."""
    fake_pipeline = _FakeHybridPipeline()
    svc = build_default_copilot_service(
        orchestrator=fake_orchestrator,
        memory=memory_service,
        conversation=conversation_service,
        hybrid_pipeline=fake_pipeline,
    )
    # expose the spy for assertions
    svc._fake_pipeline = fake_pipeline  # type: ignore[attr-defined]
    return svc


@pytest.fixture
def controller_with_hybrid(
    copilot_service_with_hybrid: CopilotService,
) -> CopilotController:
    return CopilotController(service=copilot_service_with_hybrid)


@pytest.fixture
def app(
    fake_orchestrator: _FakeOrchestrator,
    memory_service: MemoryService,
    conversation_service: ConversationService,
):
    app = FastAPI()
    app.include_router(copilot_router, prefix="/api/v1")
    service = build_default_copilot_service(
        orchestrator=fake_orchestrator,
        memory=memory_service,
        conversation=conversation_service,
    )
    app.dependency_overrides[get_copilot_service] = lambda: service
    app.dependency_overrides[get_memory_service] = lambda: memory_service
    app.dependency_overrides[get_conversation_service] = lambda: conversation_service
    app.dependency_overrides[get_response_orchestrator] = lambda: fake_orchestrator
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def app_with_hybrid(
    fake_orchestrator: _FakeOrchestrator,
    memory_service: MemoryService,
    conversation_service: ConversationService,
):
    """App whose copilot service is wired to a fake hybrid pipeline (P0.0)."""
    app = FastAPI()
    app.include_router(copilot_router, prefix="/api/v1")
    fake_pipeline = _FakeHybridPipeline()
    service = build_default_copilot_service(
        orchestrator=fake_orchestrator,
        memory=memory_service,
        conversation=conversation_service,
        hybrid_pipeline=fake_pipeline,
    )
    app.dependency_overrides[get_copilot_service] = lambda: service
    app.dependency_overrides[get_memory_service] = lambda: memory_service
    app.dependency_overrides[get_conversation_service] = lambda: conversation_service
    app.dependency_overrides[get_response_orchestrator] = lambda: fake_orchestrator
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_copilot_mode_values(self):
        assert CopilotMode.ANSWER.value == "answer"
        assert CopilotMode.SUMMARISE.value == "summarise"
        assert CopilotMode.SEARCH.value == "search"

    def test_copilot_request_defaults(self):
        r = CopilotRequest(query="hello")
        assert r.mode == CopilotMode.ANSWER
        assert r.use_memory is True
        assert r.memory_top_k == 5
        assert r.tone == "regulatory"
        assert r.min_faithfulness == 0.7
        assert r.conversation_id is None
        assert r.request_id  # auto-generated

    def test_copilot_request_forbids_extra(self):
        with pytest.raises(Exception):
            CopilotRequest(query="hi", bad_field="oops")

    def test_copilot_request_min_query(self):
        with pytest.raises(Exception):
            CopilotRequest(query="")

    def test_copilot_request_max_query(self):
        with pytest.raises(Exception):
            CopilotRequest(query="x" * 5000)

    def test_copilot_request_memory_top_k_bounds(self):
        with pytest.raises(Exception):
            CopilotRequest(query="hi", memory_top_k=0)
        with pytest.raises(Exception):
            CopilotRequest(query="hi", memory_top_k=100)

    def test_copilot_message_defaults(self):
        m = CopilotMessage(role="user", content="hi")
        assert m.role == "user"
        assert m.timestamp is not None


# ─── Service tests ──────────────────────────────────────────────────────────


class TestService:
    @pytest.mark.asyncio
    async def test_ask_creates_conversation(self, controller: CopilotController):
        req = CopilotRequest(query="What is KYC?")
        resp = await controller.handle(req)
        assert resp.conversation_id.startswith("conv-")
        assert resp.mode == CopilotMode.ANSWER

    @pytest.mark.asyncio
    async def test_ask_records_messages(
        self, controller: CopilotController, conversation_service: ConversationService
    ):
        req = CopilotRequest(query="What is KYC?")
        resp = await controller.handle(req)
        conv = conversation_service.manager.get(resp.conversation_id)
        assert conv is not None
        # 2 messages: user + assistant.
        assert len(conv.messages) == 2
        assert conv.messages[0].role.value == "user"
        assert conv.messages[1].role.value == "assistant"

    @pytest.mark.asyncio
    async def test_ask_calls_orchestrator(
        self, controller: CopilotController, fake_orchestrator: _FakeOrchestrator
    ):
        req = CopilotRequest(
            query="What is KYC?",
            chunks=[
                {
                    "chunk_id": "chk-1",
                    "document_id": "doc-1",
                    "content": "KYC means Know Your Customer.",
                    "score": 0.9,
                }
            ],
        )
        resp = await controller.handle(req)
        assert len(fake_orchestrator.calls) == 1
        assert fake_orchestrator.calls[0].query == "What is KYC?"
        assert resp.confidence_score == 0.85
        assert resp.faithfulness_score == 0.92

    @pytest.mark.asyncio
    async def test_ask_records_retrieval_memory(
        self,
        controller: CopilotController,
        memory_service: MemoryService,
    ):
        req = CopilotRequest(
            query="What is KYC?",
            user_id="u-1",
            chunks=[
                {
                    "chunk_id": "chk-1",
                    "document_id": "doc-1",
                    "content": "KYC is Know Your Customer.",
                    "score": 0.9,
                }
            ],
        )
        await controller.handle(req)
        # Retrieval memory should be recorded for user u-1.
        all_mem = memory_service.repository.all()
        retrieval = [e for e in all_mem if e.memory_type.value == "retrieval"]
        assert len(retrieval) >= 1
        assert retrieval[0].user_id == "u-1"

    @pytest.mark.asyncio
    async def test_multi_turn_shares_conversation(
        self, controller: CopilotController, conversation_service: ConversationService
    ):
        req1 = CopilotRequest(
            query="What is KYC?",
            chunks=[
                {
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "content": "KYC info",
                    "score": 0.9,
                }
            ],
        )
        r1 = await controller.handle(req1)
        # Second turn: use the same conversation.
        req2 = CopilotRequest(
            query="Tell me more",
            conversation_id=r1.conversation_id,
            chunks=[
                {
                    "chunk_id": "c2",
                    "document_id": "d2",
                    "content": "more KYC",
                    "score": 0.9,
                }
            ],
        )
        r2 = await controller.handle(req2)
        assert r1.conversation_id == r2.conversation_id
        conv = conversation_service.manager.get(r1.conversation_id)
        # 4 messages: 2 user + 2 assistant.
        assert len(conv.messages) == 4

    @pytest.mark.asyncio
    async def test_use_memory_false_skips_memory(
        self, controller: CopilotController, memory_service: MemoryService
    ):
        req = CopilotRequest(
            query="What is KYC?",
            use_memory=False,
            chunks=[
                {
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "content": "KYC info",
                    "score": 0.9,
                }
            ],
        )
        resp = await controller.handle(req)
        assert resp.memory_used is False

    @pytest.mark.asyncio
    async def test_no_chunks_returns_degraded_answer(
        self, controller: CopilotController, fake_orchestrator: _FakeOrchestrator
    ):
        req = CopilotRequest(query="What is KYC?")
        resp = await controller.handle(req)
        # Orchestrator NOT invoked (degraded path).
        assert len(fake_orchestrator.calls) == 0
        assert resp.answer is not None
        assert "No grounded information" in resp.answer["executive_summary"]

    @pytest.mark.asyncio
    async def test_summarise_mode_skips_orchestrator(
        self, controller: CopilotController, fake_orchestrator: _FakeOrchestrator
    ):
        req = CopilotRequest(
            query="Summarise the KYC history",
            mode=CopilotMode.SUMMARISE,
        )
        resp = await controller.handle(req)
        assert resp.mode == CopilotMode.SUMMARISE
        assert len(fake_orchestrator.calls) == 0
        assert resp.answer is not None
        assert "summary" in resp.answer

    @pytest.mark.asyncio
    async def test_search_mode_returns_sources(
        self, controller: CopilotController, fake_orchestrator: _FakeOrchestrator
    ):
        req = CopilotRequest(
            query="Find KYC info",
            mode=CopilotMode.SEARCH,
        )
        resp = await controller.handle(req)
        assert resp.mode == CopilotMode.SEARCH
        assert len(fake_orchestrator.calls) == 0
        assert resp.answer is not None
        assert "sources" in resp.answer

    @pytest.mark.asyncio
    async def test_history_echo(self, controller: CopilotController):
        req1 = CopilotRequest(
            query="first",
            chunks=[
                {"chunk_id": "c1", "document_id": "d1", "content": "x", "score": 0.5}
            ],
        )
        r1 = await controller.handle(req1)
        assert len(r1.history) == 2
        # history should be the 2 messages from this turn.
        assert r1.history[0].role == "user"
        assert r1.history[0].content == "first"


# ─── Controller tests ───────────────────────────────────────────────────────


class TestController:
    @pytest.mark.asyncio
    async def test_rejects_whitespace_query(self, controller: CopilotController):
        req = CopilotRequest(query="   ")
        with pytest.raises(ValueError):
            await controller.handle(req)


# ─── API integration tests ─────────────────────────────────────────────────


class TestAPI:
    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient):
        r = await client.get("/api/v1/copilot/health")
        assert r.status_code == 200
        assert r.json()["module"] == "copilot"

    @pytest.mark.asyncio
    async def test_query_end_to_end(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/copilot/query",
            json={
                "query": "What is KYC?",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": "d1",
                        "content": "KYC info",
                        "score": 0.9,
                    }
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["query"] == "What is KYC?"
        assert body["conversation_id"].startswith("conv-")
        assert body["answer"] is not None
        assert body["confidence_score"] == 0.85

    @pytest.mark.asyncio
    async def test_query_with_empty_query_returns_422(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/copilot/query",
            json={"query": ""},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_query_summarise_mode(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/copilot/query",
            json={"query": "summary please", "mode": "summarise"},
        )
        assert r.status_code == 200
        assert r.json()["mode"] == "summarise"

    @pytest.mark.asyncio
    async def test_query_search_mode(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/copilot/query",
            json={"query": "find something", "mode": "search"},
        )
        assert r.status_code == 200
        assert r.json()["mode"] == "search"


# ─── P0.0 regression: copilot must reach real retrieval ────────────────────


@pytest_asyncio.fixture
async def client_with_hybrid(app_with_hybrid):
    transport = ASGITransport(app=app_with_hybrid)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestP00HybridRetrieval:
    """Regression tests for P0.0 — the copilot must invoke the real hybrid
    retrieval pipeline for a new question instead of the degraded
    empty-answer path."""

    @pytest.mark.asyncio
    async def test_new_question_invokes_hybrid_pipeline(
        self,
        controller_with_hybrid: CopilotController,
        fake_orchestrator: _FakeOrchestrator,
    ):
        req = CopilotRequest(query="What is KYC?", use_memory=True)
        resp = await controller_with_hybrid.handle(req)

        svc = controller_with_hybrid.service
        # (a) hybrid pipeline was actually invoked
        assert getattr(svc, "_fake_pipeline").calls, "hybrid pipeline was never invoked"
        assert svc._fake_pipeline.calls[0]["query"] == "What is KYC?"

        # (b) orchestrator received real chunks from retrieval
        assert len(fake_orchestrator.calls) == 1
        chunks = fake_orchestrator.calls[0].chunks
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "chunk-abc"

        # (b) answer is real, not the degraded empty-answer path
        assert resp.answer is not None
        assert "No grounded information" not in resp.answer["executive_summary"]
        assert resp.confidence_score > 0

        # (a) retrieval_invoked flag is set in response metadata
        assert resp.metadata.extra.get("retrieval_invoked") is True

    @pytest.mark.asyncio
    async def test_query_without_chunks_invokes_hybrid_pipeline(
        self, client_with_hybrid: AsyncClient
    ):
        r = await client_with_hybrid.post(
            "/api/v1/copilot/query",
            json={"query": "What is KYC?", "use_memory": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["answer"] is not None
        assert "No grounded information" not in body["answer"]["executive_summary"]
        assert body["metadata"]["extra"]["retrieval_invoked"] is True
