"""Module 5.1 — Answer Generation tests.

Covers:

* Pydantic schema validation
* PromptBuilder formatting / truncation
* Section parser edge cases
* Provider factory and mock provider behaviour
* Service-level generate() and stream()
* API integration tests against ``/api/v1/answer/generate`` and ``/api/v1/answer/stream``
  using a stubbed provider via FastAPI ``dependency_overrides``.

The mock provider is the only LLM backend used in tests; no network calls
are made.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator, Dict, List

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_answer_generator_service,
    get_llm_provider,
    get_prompt_builder,
)
from app.main import app
from app.schemas.answer_generation import (
    AnswerGenerationRequest,
    AnswerGenerationResponse,
    AnswerStreamChunk,
    AnswerTone,
    EvidenceChunk,
    LLMProviderName,
    RetrievedChunk,
)
from app.services.answer_generation import (
    AnswerGeneratorService,
    MockLLMProvider,
    PromptBuilder,
    build_default_service,
)
from app.services.answer_generation.providers import (
    BaseLLMProvider,
    GeminiProvider,
    LLMResponse,
    LiteLLMProvider,
    OpenAIProvider,
    get_provider,
)
from app.services.answer_generation.service import (
    _extract_evidence_ids,
    _extract_references,
    parse_sections,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _make_chunk(
    *,
    cid: str = "c-1",
    doc: str = "d-1",
    content: str = "Sample regulatory text for testing.",
    score: float = 0.9,
    source=None,
    page: int = 1,
    section: str = "Section A",
    title: str = "Doc Title",
) -> RetrievedChunk:
    from app.models.document import SourceEnum

    return RetrievedChunk(
        chunk_id=cid,
        document_id=doc,
        content=content,
        score=score,
        source=source or SourceEnum.RBI,
        page_number=page,
        section=section,
        document_title=title,
    )


@pytest.fixture
def two_chunks() -> List[RetrievedChunk]:
    return [
        _make_chunk(cid="c-1", doc="d-1", content="RBI KYC obligations apply to all banks." * 5,
                    source="RBI", page=12, section="KYC", title="Master Direction 2016"),
        _make_chunk(cid="c-2", doc="d-2", content="SEBI mandates portfolio disclosure of holdings." * 5,
                    source="SEBI", page=4, section="Disclosure", title="SEBI Circular 2020"),
    ]


@pytest.fixture
def mock_service() -> AnswerGeneratorService:
    return build_default_service(
        provider=LLMProviderName.MOCK, model="mock-default"
    )


# ─── Schema validation ──────────────────────────────────────────────────────


class TestSchemas:
    def test_chunk_min_fields(self):
        c = _make_chunk()
        assert c.chunk_id == "c-1"
        assert c.document_id == "d-1"
        assert c.score == 0.9
        assert c.source.value == "RBI"

    def test_chunk_rejects_extra_fields(self):
        with pytest.raises(Exception):
            RetrievedChunk.model_validate(
                {"chunk_id": "x", "document_id": "y", "content": "z", "score": 0.1, "unknown": 1}
            )

    def test_request_requires_chunks(self):
        with pytest.raises(Exception):
            AnswerGenerationRequest(query="hi", chunks=[])

    def test_request_default_provider(self):
        req = AnswerGenerationRequest(
            query="hi", chunks=[_make_chunk()]
        )
        assert req.provider == LLMProviderName.MOCK
        assert req.tone == AnswerTone.REGULATORY
        assert req.stream is False
        assert req.max_tokens == 1200

    def test_request_bounds(self):
        with pytest.raises(Exception):
            AnswerGenerationRequest(
                query="hi", chunks=[_make_chunk()], max_tokens=10
            )
        with pytest.raises(Exception):
            AnswerGenerationRequest(
                query="hi", chunks=[_make_chunk()], temperature=3.0
            )
        with pytest.raises(Exception):
            AnswerGenerationRequest(query="", chunks=[_make_chunk()])

    def test_response_envelope(self):
        resp = AnswerGenerationResponse(
            query="q",
            answer={
                "executive_summary": "s",
                "detailed_explanation": "d",
                "supporting_evidence": [],
                "key_regulatory_references": [],
            },
            metadata={
                "provider": "mock",
                "model": "m",
                "chunks_used": 1,
            },
        )
        assert resp.metadata.provider == "mock"
        assert resp.answer.executive_summary == "s"


# ─── PromptBuilder ──────────────────────────────────────────────────────────


class TestPromptBuilder:
    def test_build_basic(self, two_chunks):
        builder = PromptBuilder(tone=AnswerTone.REGULATORY)
        bundle = builder.build("What are KYC obligations?", two_chunks)
        assert "What are KYC obligations?" in bundle.user_prompt
        assert "c-1" in bundle.user_prompt
        assert "c-2" in bundle.user_prompt
        assert "Executive Summary" in bundle.system_prompt
        assert "RBI" in bundle.user_prompt
        assert bundle.truncated == 0
        assert bundle.chunk_ids == ["c-1", "c-2"]

    def test_build_truncates_excerpt(self, two_chunks):
        builder = PromptBuilder(
            tone=AnswerTone.REGULATORY, max_excerpt_chars=20
        )
        bundle = builder.build("q?", two_chunks)
        for cid in bundle.chunk_ids:
            assert any(
                cid in line for line in bundle.user_prompt.splitlines()
            )

    def test_build_respects_token_budget(self):
        huge = [
            _make_chunk(
                cid=f"c-{i}",
                content="X " * 5000,  # very long content
            )
            for i in range(20)
        ]
        builder = PromptBuilder(
            tone=AnswerTone.REGULATORY,
            context_token_budget=200,
            max_excerpt_chars=4000,
        )
        bundle = builder.build("q?", huge)
        assert len(bundle.chunk_ids) < 20
        assert bundle.truncated > 0

    def test_build_rejects_empty_query(self, two_chunks):
        with pytest.raises(ValueError):
            PromptBuilder().build("", two_chunks)
        with pytest.raises(ValueError):
            PromptBuilder().build("   ", two_chunks)

    def test_build_rejects_empty_chunks(self):
        with pytest.raises(ValueError):
            PromptBuilder().build("q?", [])

    def test_tone_changes_system_prompt(self, two_chunks):
        for tone in AnswerTone:
            builder = PromptBuilder(tone=tone)
            bundle = builder.build("q?", two_chunks)
            assert bundle.system_prompt


# ─── Section parser ─────────────────────────────────────────────────────────


class TestSectionParser:
    def test_parses_all_four_sections(self):
        raw = (
            "Executive Summary: a summary.\n\n"
            "Detailed Explanation: long text.\n\n"
            "Supporting Evidence: [c-1, c-2]\n\n"
            "Key Regulatory References: RBI Act, SEBI LODR"
        )
        out = parse_sections(raw)
        assert out["executive_summary"].strip() == "a summary."
        assert out["detailed_explanation"].strip() == "long text."
        assert "[c-1, c-2]" in out["supporting_evidence"]
        assert "RBI Act" in out["key_regulatory_references"]

    def test_fallback_when_no_headers(self):
        out = parse_sections("Just one paragraph. " * 5)
        assert out["executive_summary"]
        assert "Just one paragraph" in out["executive_summary"]

    def test_handles_empty_input(self):
        out = parse_sections("")
        for v in out.values():
            assert v == ""

    def test_handles_partial_headers(self):
        raw = "Executive Summary: only header provided"
        out = parse_sections(raw)
        assert "only header" in out["executive_summary"]
        assert out["detailed_explanation"] == ""

    def test_extract_evidence_brackets(self):
        assert _extract_evidence_ids("[c-1, c-2]") == ["c-1", "c-2"]

    def test_extract_evidence_plain(self):
        assert _extract_evidence_ids("c-1, c-2") == ["c-1", "c-2"]

    def test_extract_references(self):
        assert _extract_references("Act A, Act B, Act C") == ["Act A", "Act B", "Act C"]


# ─── Provider factory + mock ────────────────────────────────────────────────


class TestProviders:
    def test_factory_returns_mock_by_default(self):
        p = get_provider(LLMProviderName.MOCK, model="m")
        assert isinstance(p, MockLLMProvider)
        assert p.model == "m"

    def test_factory_returns_openai_provider(self):
        p = get_provider(LLMProviderName.OPENAI, model="gpt-x", api_key="x")
        assert isinstance(p, OpenAIProvider)
        # No key in env -> _init_error set
        assert p._init_error is not None  # type: ignore[attr-defined]

    def test_factory_returns_gemini_provider(self):
        p = get_provider(LLMProviderName.GEMINI, model="g-1", api_key="x")
        assert isinstance(p, GeminiProvider)
        # Either: SDK missing → _init_error populated, or SDK present → client built.
        sdk_present = p._client is not None  # type: ignore[attr-defined]
        assert sdk_present or p._init_error is not None  # type: ignore[attr-defined]

    def test_factory_returns_litellm_provider(self):
        p = get_provider(LLMProviderName.LITELLM, model="gpt-4o-mini", api_key="x")
        assert isinstance(p, LiteLLMProvider)
        # litellm is now a hard dependency (requirements.txt). When the SDK is
        # importable the provider must initialise cleanly (mirrors the gemini
        # test's SDK-present guard).
        sdk_present = p._acompletion is not None  # type: ignore[attr-defined]
        assert sdk_present or p._init_error is not None  # type: ignore[attr-defined]

    def test_factory_returns_mock_for_unknown(self):
        # Defensive: any unknown enum should fall back to mock
        class _Fake:
            value = "mystery"

        p = get_provider(_Fake(), model="m")  # type: ignore[arg-type]
        assert isinstance(p, MockLLMProvider)

    @pytest.mark.asyncio
    async def test_mock_provider_records_prompts(self):
        mock = MockLLMProvider()
        out = await mock.generate(
            system_prompt="sys", user_prompt="Question:\nWhat is KYC?\n\n[1] Chunk ID: abc-1\nContent: text",
            max_tokens=200,
            temperature=0.1,
        )
        assert out.provider == "mock"
        assert "Executive Summary" in out.text
        assert "abc-1" in out.text
        assert mock.call_count == 1
        assert "Question" in mock.last_user_prompt

    @pytest.mark.asyncio
    async def test_mock_stream_yields_text(self):
        mock = MockLLMProvider()
        chunks: List[str] = []
        async for piece in mock.stream(
            system_prompt="s",
            user_prompt="Question:\nQ?\n\n[1] Chunk ID: cid-1\nContent: x",
            max_tokens=100,
            temperature=0.0,
        ):
            chunks.append(piece)
        assert "".join(chunks)
        assert any("Executive Summary" in c for c in chunks)


# ─── Service ────────────────────────────────────────────────────────────────


class TestAnswerGeneratorService:
    @pytest.mark.asyncio
    async def test_generate_returns_structured_answer(
        self, mock_service, two_chunks
    ):
        req = AnswerGenerationRequest(
            query="What are KYC obligations?", chunks=two_chunks
        )
        res = await mock_service.generate(req)
        assert isinstance(res, AnswerGenerationResponse)
        assert res.query == req.query
        assert res.answer.executive_summary
        assert res.answer.detailed_explanation
        # Mock enumerates both chunk ids as evidence.
        assert {e.chunk_id for e in res.answer.supporting_evidence} == {"c-1", "c-2"}
        assert res.answer.key_regulatory_references
        assert res.metadata.provider == "mock"
        assert res.metadata.chunks_used == 2
        assert res.metadata.latency_ms >= 0
        assert res.metadata.timestamp is not None
        assert res.metadata.request_id

    @pytest.mark.asyncio
    async def test_generate_includes_raw_when_requested(
        self, mock_service, two_chunks
    ):
        req = AnswerGenerationRequest(
            query="q", chunks=two_chunks, include_raw=True
        )
        res = await mock_service.generate(req)
        assert res.raw_response is not None
        assert "Executive Summary" in res.raw_response

    @pytest.mark.asyncio
    async def test_generate_rejects_empty_chunks(self, mock_service):
        # Pydantic-level constraint; service-level guard for safety.
        with pytest.raises(ValueError):
            await mock_service.generate_from_chunks(query="q", chunks=[])

    @pytest.mark.asyncio
    async def test_stream_emits_event_sequence(
        self, mock_service, two_chunks
    ):
        req = AnswerGenerationRequest(
            query="q", chunks=two_chunks, stream=True
        )
        events: List[AnswerStreamChunk] = []
        async for ev in mock_service.stream(req):
            events.append(ev)

        kinds = [e.event for e in events]
        assert kinds[0] == "start"
        assert "token" in kinds
        assert "section" in kinds
        assert kinds[-1] == "end"
        # Final 'end' event carries metadata.
        end = events[-1]
        assert end.metadata is not None
        assert end.metadata.chunks_used == 2
        # The 'section' event carries the parsed answer.
        section_evt = next(e for e in events if e.event == "section")
        assert section_evt.section is not None
        assert section_evt.section.executive_summary

    @pytest.mark.asyncio
    async def test_generate_from_chunks_convenience(
        self, mock_service, two_chunks
    ):
        res = await mock_service.generate_from_chunks(
            query="q?", chunks=two_chunks
        )
        assert res.answer.executive_summary

    @pytest.mark.asyncio
    async def test_provider_error_propagates(
        self, two_chunks
    ):
        class FailingProvider(BaseLLMProvider):
            name = LLMProviderName.MOCK

            async def generate(self, **kwargs) -> LLMResponse:
                raise RuntimeError("simulated provider failure")

        svc = AnswerGeneratorService(provider=FailingProvider())
        req = AnswerGenerationRequest(query="q", chunks=two_chunks)
        with pytest.raises(RuntimeError, match="simulated provider failure"):
            await svc.generate(req)


# ─── API integration tests ─────────────────────────────────────────────────


class TestAnswerGenerationAPI:
    @pytest_asyncio.fixture
    async def api_client(self):
        # Override the DI factories with deterministic stubs.
        mock = MockLLMProvider()
        builder = PromptBuilder(tone=AnswerTone.REGULATORY)
        service = AnswerGeneratorService(provider=mock, prompt_builder=builder)

        app.dependency_overrides[get_llm_provider] = lambda: mock
        app.dependency_overrides[get_prompt_builder] = lambda: builder
        app.dependency_overrides[get_answer_generator_service] = lambda: service

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_generate_endpoint_success(self, api_client, two_chunks):
        payload = {
            "query": "What are KYC obligations?",
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "content": c.content,
                    "score": c.score,
                    "source": c.source.value,
                    "page_number": c.page_number,
                    "section": c.section,
                    "document_title": c.document_title,
                }
                for c in two_chunks
            ],
        }
        r = await api_client.post("/api/v1/answer/generate", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["query"] == payload["query"]
        assert body["answer"]["executive_summary"]
        assert body["metadata"]["provider"] == "mock"
        assert body["metadata"]["chunks_used"] == 2

    @pytest.mark.asyncio
    async def test_generate_endpoint_validation_error(self, api_client):
        # Missing chunks
        r = await api_client.post(
            "/api/v1/answer/generate", json={"query": "hi"}
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_generate_endpoint_empty_chunks_400(self, api_client):
        # Bypass pydantic by sending an empty list and relying on the handler check.
        r = await api_client.post(
            "/api/v1/answer/generate",
            json={"query": "hi", "chunks": []},
        )
        # Either 422 (pydantic) or 400 (handler) is acceptable.
        assert r.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_stream_endpoint_emits_sse(self, api_client, two_chunks):
        payload = {
            "query": "q?",
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "content": c.content,
                    "score": c.score,
                    "source": c.source.value,
                    "page_number": c.page_number,
                    "section": c.section,
                    "document_title": c.document_title,
                }
                for c in two_chunks
            ],
        }
        r = await api_client.post("/api/v1/answer/stream", json=payload)
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

        events: List[Dict[str, Any]] = []
        async for line in r.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                continue
            events.append(json.loads(data))

        kinds = [e["event"] for e in events]
        assert "start" in kinds
        assert "token" in kinds
        assert "section" in kinds
        assert "end" in kinds

    @pytest.mark.asyncio
    async def test_default_provider_is_mock(self, api_client, two_chunks):
        # No provider field => mock default.
        payload = {
            "query": "q?",
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "content": c.content,
                    "score": c.score,
                    "source": c.source.value,
                }
                for c in two_chunks
            ],
        }
        r = await api_client.post("/api/v1/answer/generate", json=payload)
        assert r.status_code == 200
        assert r.json()["metadata"]["provider"] == "mock"
