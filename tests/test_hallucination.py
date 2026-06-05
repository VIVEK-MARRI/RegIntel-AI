"""Tests for Module 5.4 — Hallucination Guard.

Coverage
--------
* Schema validation (FaithfulnessRequest, FaithfulnessResponse,
  ClaimVerdict, FaithfulnessMetadata, risk_level_for).
* Prompt builder (system/user prompt shape, JSON-fenced responses).
* Response parser (valid JSON, fenced JSON, malformed, missing
  verdicts).
* LexicalFaithfulnessChecker (overlap threshold, no chunks, multi
  claim verdict).
* FaithfulnessEvaluator with MockFaithfulnessProvider.
* HallucinationGuardService for each method (LLM, lexical, hybrid,
  mock), including fail-open fallback to lexical when the LLM
  raises.
* API integration: /api/v1/hallucination/verify + /health, with
  dependency_overrides for the LLM provider so no external SDK is
  loaded.
"""

from __future__ import annotations

import json
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_hallucination_guard_service,
    reset_hallucination_guard,
)
from app.api.v1.hallucination import router as hallucination_router
from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.hallucination import (
    ClaimVerdict,
    FaithfulnessMetadata,
    FaithfulnessReport,
    FaithfulnessRequest,
    FaithfulnessResponse,
    HallucinationRiskLevel,
    VerificationMethod,
    risk_level_for,
)
from app.services.hallucination import (
    FaithfulnessEvaluator,
    HallucinationGuardService,
    LexicalFaithfulnessChecker,
    MockFaithfulnessProvider,
    VerificationResult,
    build_default_hallucination_guard,
    build_verification_prompts,
    parse_verification_response,
)
from app.services.hallucination.evaluator import (
    _extract_chunks_from_prompt,
    _extract_claims_from_prompt,
    _parse_header_meta,
)
from app.services.hallucination.prompts import VerificationPrompts


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Ensure no module-level singletons leak between tests."""
    reset_hallucination_guard()
    yield
    reset_hallucination_guard()


@pytest.fixture
def sample_chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id="chk-1",
            document_id="doc-1",
            document_title="RBI Master Direction on KYC",
            source="RBI",
            page_number=8,
            section="KYC Norms",
            content=(
                "Banks must perform customer identification at onboarding. "
                "The KYC process includes identity verification, address proof, "
                "and risk profiling."
            ),
            score=0.92,
        ),
        RetrievedChunk(
            chunk_id="chk-2",
            document_id="doc-1",
            document_title="RBI Master Direction on KYC",
            source="RBI",
            page_number=9,
            section="Ongoing Monitoring",
            content=(
                "Ongoing monitoring must be conducted periodically. "
                "Suspicious activity must be reported to the Financial Intelligence Unit."
            ),
            score=0.78,
        ),
    ]


@pytest.fixture
def good_answer() -> AnswerSection:
    return AnswerSection(
        executive_summary="Banks perform KYC at onboarding.",
        detailed_explanation=(
            "The KYC process includes identity verification, address proof, "
            "and risk profiling for every customer."
        ),
        supporting_evidence=[],
        key_regulatory_references=[],
    )


@pytest.fixture
def bad_answer() -> AnswerSection:
    return AnswerSection(
        executive_summary="Banks perform KYC at onboarding.",
        detailed_explanation=(
            "The KYC process includes identity verification, address proof, "
            "and risk profiling for every customer. "
            "Banks must also file monthly tax returns for every account holder."
        ),
        supporting_evidence=[],
        key_regulatory_references=[],
    )


@pytest.fixture
def app(monkeypatch):
    """Build a test FastAPI app with the hallucination router mounted and a
    fresh guard singleton injected via dependency_overrides."""
    reset_hallucination_guard()
    app = FastAPI()
    app.include_router(hallucination_router, prefix="/api/v1")
    # Default guard with no LLM provider (uses lexical).
    guard = build_default_hallucination_guard()
    app.dependency_overrides[get_hallucination_guard_service] = lambda: guard
    yield app
    app.dependency_overrides.clear()
    reset_hallucination_guard()


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_risk_level_for_high_score(self):
        assert risk_level_for(0.95, hallucination_detected=False) == HallucinationRiskLevel.NONE
        assert risk_level_for(1.0, hallucination_detected=False) == HallucinationRiskLevel.NONE

    def test_risk_level_for_medium_score(self):
        assert risk_level_for(0.8, hallucination_detected=False) == HallucinationRiskLevel.LOW
        assert risk_level_for(0.7, hallucination_detected=False) == HallucinationRiskLevel.LOW

    def test_risk_level_for_low_score(self):
        assert risk_level_for(0.5, hallucination_detected=False) == HallucinationRiskLevel.MEDIUM
        assert risk_level_for(0.4, hallucination_detected=False) == HallucinationRiskLevel.MEDIUM

    def test_risk_level_for_very_low(self):
        assert risk_level_for(0.3, hallucination_detected=False) == HallucinationRiskLevel.HIGH
        assert risk_level_for(0.0, hallucination_detected=False) == HallucinationRiskLevel.HIGH

    def test_hallucination_bumps_risk(self):
        # Single unsupported claim bumps NONE→LOW at minimum.
        assert risk_level_for(0.99, hallucination_detected=True) == HallucinationRiskLevel.LOW
        # Already-LOW stays LOW.
        assert risk_level_for(0.8, hallucination_detected=True) == HallucinationRiskLevel.LOW

    def test_verification_method_values(self):
        assert VerificationMethod.LLM.value == "llm"
        assert VerificationMethod.LEXICAL.value == "lexical"
        assert VerificationMethod.HYBRID.value == "hybrid"
        assert VerificationMethod.MOCK.value == "mock"

    def test_claim_verdict_default_id(self):
        v = ClaimVerdict(claim="hello", section="x", supported=True)
        assert v.claim_id.startswith("clm-")
        assert len(v.claim_id) == 12  # "clm-" + 8 hex

    def test_faithfulness_request_rejects_unknown_method(self):
        with pytest.raises(Exception):
            FaithfulnessRequest(
                query="q",
                answer=AnswerSection(
                    executive_summary="s",
                    detailed_explanation="d",
                    supporting_evidence=[],
                    key_regulatory_references=[],
                ),
                chunks=[],
                method="bogus",  # type: ignore[arg-type]
            )

    def test_faithfulness_request_allows_empty_chunks(self):
        req = FaithfulnessRequest(
            query="q",
            answer=AnswerSection(
                executive_summary="s",
                detailed_explanation="d",
                supporting_evidence=[],
                key_regulatory_references=[],
            ),
            chunks=[],
            method=VerificationMethod.LEXICAL,
        )
        assert req.chunks == []
        assert req.lexical_threshold == 0.15

    def test_faithfulness_metadata_fields(self):
        meta = FaithfulnessMetadata(
            request_id="abc",
            latency_ms=12.5,
            provider_used="openai",
            chunks_used=3,
        )
        assert meta.latency_ms == 12.5
        assert meta.chunks_used == 3


# ─── Prompt builder tests ───────────────────────────────────────────────────


class TestPromptBuilder:
    def test_builds_prompts(self, sample_chunks, good_answer):
        from app.schemas.citation import Claim

        claims = [
            Claim(claim_id="clm-aaa", text="Banks perform KYC.", section="executive_summary"),
        ]
        bundle = build_verification_prompts(
            query="What is KYC?",
            answer=good_answer,
            chunks=sample_chunks,
            claims=claims,
        )
        assert isinstance(bundle, VerificationPrompts)
        assert "JSON" in bundle.system_prompt
        assert "claim_id=clm-aaa" in bundle.user_prompt
        assert "chk-1" in bundle.user_prompt
        assert bundle.claim_count == 1

    def test_chunk_and_claim_round_trip(self, sample_chunks, good_answer):
        from app.schemas.citation import Claim

        claims = [
            Claim(claim_id="clm-a", text="Banks perform KYC at onboarding.", section="executive_summary"),
            Claim(claim_id="clm-b", text="KYC includes identity verification.", section="detailed_explanation"),
        ]
        bundle = build_verification_prompts(
            query="q", answer=good_answer, chunks=sample_chunks, claims=claims
        )
        parsed_chunks = _extract_chunks_from_prompt(bundle.user_prompt)
        parsed_claims = _extract_claims_from_prompt(bundle.user_prompt)
        assert len(parsed_chunks) == 2
        assert len(parsed_claims) == 2
        assert parsed_claims[0][0] == "clm-a"
        assert parsed_chunks[0][0] == "chk-1"

    def test_parse_header_meta(self):
        meta = _parse_header_meta("[1] claim_id=clm-abc section=executive_summary")
        assert meta["claim_id"] == "clm-abc"
        assert meta["section"] == "executive_summary"


# ─── Response parser tests ──────────────────────────────────────────────────


class TestResponseParser:
    def _claims(self):
        from app.schemas.citation import Claim
        return [
            Claim(claim_id="clm-1", text="Banks perform KYC at onboarding.", section="executive_summary"),
            Claim(claim_id="clm-2", text="Identity verification is required.", section="detailed_explanation"),
        ]

    def test_parse_valid_json(self):
        raw = json.dumps({
            "supported_claims": [
                {"claim_id": "clm-1", "claim": "Banks perform KYC at onboarding.", "cited_chunk_ids": ["chk-1"]},
            ],
            "unsupported_claims": [
                {"claim_id": "clm-2", "claim": "Identity verification is required.", "reason": "no evidence"},
            ],
            "overall_faithfulness": 0.5,
        })
        sup, unsup, score = parse_verification_response(raw, self._claims())
        assert len(sup) == 1 and sup[0].claim_id == "clm-1"
        assert len(unsup) == 1 and unsup[0].claim_id == "clm-2"
        assert score == 0.5

    def test_parse_fenced_json(self):
        raw = "```json\n" + json.dumps({
            "supported_claims": [],
            "unsupported_claims": [
                {"claim_id": "clm-1", "claim": "x", "reason": "y"},
                {"claim_id": "clm-2", "claim": "z", "reason": "w"},
            ],
            "overall_faithfulness": 0.0,
        }) + "\n```"
        sup, unsup, score = parse_verification_response(raw, self._claims())
        assert sup == []
        assert len(unsup) == 2
        assert score == 0.0

    def test_parse_malformed_returns_all_unsupported(self):
        sup, unsup, score = parse_verification_response("not json at all", self._claims())
        assert sup == []
        assert len(unsup) == 2
        assert score == 0.0
        assert all("LLM did not return" in v.reason or "could not" in v.reason.lower() for v in unsup)

    def test_missing_verdict_marked_unsupported(self):
        raw = json.dumps({
            "supported_claims": [
                {"claim_id": "clm-1", "claim": "Banks perform KYC at onboarding."},
            ],
            "unsupported_claims": [],
            "overall_faithfulness": 1.0,
        })
        sup, unsup, score = parse_verification_response(raw, self._claims())
        # clm-1 is supported, but clm-2 is missing — must be marked unsupported.
        assert len(sup) == 1
        assert len(unsup) == 1
        assert unsup[0].claim_id == "clm-2"
        assert "LLM did not return" in unsup[0].reason
        # score recalculated from counts
        assert score == 0.5

    def test_brace_balanced_extraction(self):
        raw = "noise before " + json.dumps({
            "supported_claims": [
                {"claim_id": "clm-1", "claim": "x", "cited_chunk_ids": ["c1"]},
                {"claim_id": "clm-2", "claim": "y", "cited_chunk_ids": ["c1"]},
            ],
            "unsupported_claims": [],
            "overall_faithfulness": 1.0,
        }) + " noise after"
        sup, unsup, _ = parse_verification_response(raw, self._claims())
        assert len(sup) == 2
        assert unsup == []


# ─── Lexical checker tests ──────────────────────────────────────────────────


class TestLexicalChecker:
    def test_no_chunks_all_unsupported(self, good_answer):
        checker = LexicalFaithfulnessChecker()
        verdicts = checker.verify(answer=good_answer, chunks=[])
        assert len(verdicts) >= 1
        assert all(not v.supported for v in verdicts)
        assert all("no source documents" in v.reason for v in verdicts)

    def test_supported_claims(self, sample_chunks, good_answer):
        checker = LexicalFaithfulnessChecker(threshold=0.15)
        verdicts = checker.verify(answer=good_answer, chunks=sample_chunks)
        assert len(verdicts) >= 1
        # All good-answer claims should be supported (text is in chunks).
        assert all(v.supported for v in verdicts)
        assert all(v.cited_chunk_ids for v in verdicts)

    def test_unsupported_claim_detected(self, sample_chunks, bad_answer):
        checker = LexicalFaithfulnessChecker(threshold=0.15)
        verdicts = checker.verify(answer=bad_answer, chunks=sample_chunks)
        # The "monthly tax returns" claim is not in the chunks.
        assert any(not v.supported for v in verdicts)

    def test_threshold_controls_support(self, sample_chunks, good_answer):
        # With a very high threshold, even good claims fail.
        checker = LexicalFaithfulnessChecker(threshold=0.99)
        verdicts = checker.verify(answer=good_answer, chunks=sample_chunks)
        assert all(not v.supported for v in verdicts)


# ─── LLM evaluator tests ───────────────────────────────────────────────────


class TestLLMEvaluator:
    @pytest.mark.asyncio
    async def test_evaluator_with_mock_provider(self, sample_chunks, good_answer, bad_answer):
        provider = MockFaithfulnessProvider()
        evaluator = FaithfulnessEvaluator(provider=provider)
        result = await evaluator.verify(
            query="What is KYC?", answer=good_answer, chunks=sample_chunks
        )
        assert isinstance(result, VerificationResult)
        assert result.error is None
        assert result.provider == "mock-faithfulness"
        assert result.total_tokens > 0
        # At least one claim supported.
        assert len(result.supported) >= 1
        assert result.faithfulness_score > 0.0

    @pytest.mark.asyncio
    async def test_evaluator_detects_unsupported(self, sample_chunks, bad_answer):
        provider = MockFaithfulnessProvider()
        evaluator = FaithfulnessEvaluator(provider=provider)
        result = await evaluator.verify(
            query="What is KYC?", answer=bad_answer, chunks=sample_chunks
        )
        assert any("monthly tax" in v.claim for v in result.unsupported)

    @pytest.mark.asyncio
    async def test_evaluator_handles_provider_error(self, sample_chunks, good_answer):
        class BrokenProvider(MockFaithfulnessProvider):
            async def generate(self, **kwargs):
                raise RuntimeError("simulated SDK failure")

        evaluator = FaithfulnessEvaluator(provider=BrokenProvider())
        result = await evaluator.verify(
            query="q", answer=good_answer, chunks=sample_chunks
        )
        assert result.error is not None
        assert "simulated SDK failure" in result.error
        assert result.supported == []
        assert result.unsupported == []

    @pytest.mark.asyncio
    async def test_evaluator_no_claims(self, good_answer, sample_chunks):
        from app.schemas.answer_generation import AnswerSection

        empty_answer = AnswerSection(
            executive_summary=".",
            detailed_explanation=".",
            supporting_evidence=[],
            key_regulatory_references=[],
        )
        provider = MockFaithfulnessProvider()
        evaluator = FaithfulnessEvaluator(provider=provider)
        result = await evaluator.verify(
            query="q", answer=empty_answer, chunks=sample_chunks
        )
        assert result.faithfulness_score == 1.0
        assert result.supported == []
        assert result.unsupported == []


# ─── HallucinationGuardService tests ────────────────────────────────────────


class TestHallucinationGuardService:
    @pytest.mark.asyncio
    async def test_lexical_method(self, sample_chunks, good_answer, bad_answer):
        guard = HallucinationGuardService()
        request = FaithfulnessRequest(
            query="q", answer=bad_answer, chunks=sample_chunks,
            method=VerificationMethod.LEXICAL,
        )
        resp = await guard.verify(request)
        assert isinstance(resp, FaithfulnessResponse)
        assert resp.method == VerificationMethod.LEXICAL
        assert resp.report.hallucination_detected is True
        assert resp.report.unsupported_count >= 1
        assert resp.report.faithfulness_score < 1.0
        assert resp.metadata.provider_used is None  # no LLM
        assert resp.metadata.chunks_used == 2

    @pytest.mark.asyncio
    async def test_lexical_method_all_supported(self, sample_chunks, good_answer):
        guard = HallucinationGuardService()
        request = FaithfulnessRequest(
            query="q", answer=good_answer, chunks=sample_chunks,
            method=VerificationMethod.LEXICAL,
        )
        resp = await guard.verify(request)
        assert resp.report.hallucination_detected is False
        assert resp.report.faithfulness_score == 1.0
        assert resp.report.risk_level == HallucinationRiskLevel.NONE

    @pytest.mark.asyncio
    async def test_mock_method(self, sample_chunks, bad_answer):
        guard = HallucinationGuardService()
        request = FaithfulnessRequest(
            query="q", answer=bad_answer, chunks=sample_chunks,
            method=VerificationMethod.MOCK,
        )
        resp = await guard.verify(request)
        assert resp.method == VerificationMethod.MOCK
        assert resp.report.hallucination_detected is True

    @pytest.mark.asyncio
    async def test_llm_method(self, sample_chunks, good_answer):
        guard = HallucinationGuardService(provider=MockFaithfulnessProvider())
        request = FaithfulnessRequest(
            query="q", answer=good_answer, chunks=sample_chunks,
            method=VerificationMethod.LLM,
        )
        resp = await guard.verify(request)
        assert resp.metadata.provider_used == "mock-faithfulness"
        assert resp.report.faithfulness_score > 0.0

    @pytest.mark.asyncio
    async def test_llm_fails_open_to_lexical(self, sample_chunks, good_answer):
        class BrokenProvider(MockFaithfulnessProvider):
            async def generate(self, **kwargs):
                raise RuntimeError("boom")

        guard = HallucinationGuardService(provider=BrokenProvider())
        request = FaithfulnessRequest(
            query="q", answer=good_answer, chunks=sample_chunks,
            method=VerificationMethod.LLM,
            fail_open_on_provider_error=True,
        )
        resp = await guard.verify(request)
        # Fell back to lexical — still produces a report.
        assert resp.report.faithfulness_score == 1.0
        assert resp.report.hallucination_detected is False
        assert resp.metadata.provider_used is None  # lexical has no provider

    @pytest.mark.asyncio
    async def test_llm_fails_closed_propagates(self, sample_chunks, good_answer):
        class BrokenProvider(MockFaithfulnessProvider):
            async def generate(self, **kwargs):
                raise RuntimeError("boom")

        guard = HallucinationGuardService(provider=BrokenProvider())
        request = FaithfulnessRequest(
            query="q", answer=good_answer, chunks=sample_chunks,
            method=VerificationMethod.LLM,
            fail_open_on_provider_error=False,
        )
        with pytest.raises(RuntimeError, match="boom"):
            await guard.verify(request)

    @pytest.mark.asyncio
    async def test_hybrid_method(self, sample_chunks, bad_answer):
        guard = HallucinationGuardService(provider=MockFaithfulnessProvider())
        request = FaithfulnessRequest(
            query="q", answer=bad_answer, chunks=sample_chunks,
            method=VerificationMethod.HYBRID,
        )
        resp = await guard.verify(request)
        assert resp.metadata.provider_used == "mock-faithfulness"
        assert resp.report.hallucination_detected is True
        # Both LLM and lexical ran; total_claims reflects union.
        assert resp.report.total_claims >= 2

    @pytest.mark.asyncio
    async def test_no_provider_falls_back_to_lexical(self, sample_chunks, good_answer):
        guard = HallucinationGuardService(provider=None)
        request = FaithfulnessRequest(
            query="q", answer=good_answer, chunks=sample_chunks,
            method=VerificationMethod.LLM,
        )
        resp = await guard.verify(request)
        assert resp.report.faithfulness_score == 1.0
        assert resp.report.hallucination_detected is False

    @pytest.mark.asyncio
    async def test_set_provider_swaps(self, sample_chunks, good_answer):
        guard = HallucinationGuardService(provider=None)
        guard.set_provider(MockFaithfulnessProvider())
        request = FaithfulnessRequest(
            query="q", answer=good_answer, chunks=sample_chunks,
            method=VerificationMethod.LLM,
        )
        resp = await guard.verify(request)
        assert resp.metadata.provider_used == "mock-faithfulness"

    @pytest.mark.asyncio
    async def test_verify_answer_convenience(self, sample_chunks, good_answer):
        guard = HallucinationGuardService()
        resp = await guard.verify_answer(
            query="q", answer=good_answer, chunks=sample_chunks,
            method=VerificationMethod.LEXICAL,
        )
        assert resp.report.faithfulness_score == 1.0

    @pytest.mark.asyncio
    async def test_risk_level_for_low_score(self, sample_chunks, bad_answer):
        guard = HallucinationGuardService()
        request = FaithfulnessRequest(
            query="q", answer=bad_answer, chunks=sample_chunks,
            method=VerificationMethod.LEXICAL,
        )
        resp = await guard.verify(request)
        # hallucination_detected=True bumps to at least LOW.
        assert resp.report.risk_level in (
            HallucinationRiskLevel.LOW,
            HallucinationRiskLevel.MEDIUM,
            HallucinationRiskLevel.HIGH,
        )

    @pytest.mark.asyncio
    async def test_min_faithfulness_triggers_low_risk(self, sample_chunks, good_answer):
        # No chunks → all claims unsupported → score=0.0 → risk HIGH.
        guard = HallucinationGuardService()
        request = FaithfulnessRequest(
            query="q", answer=good_answer, chunks=[],
            method=VerificationMethod.LEXICAL,
            min_faithfulness=0.9,
        )
        resp = await guard.verify(request)
        assert resp.report.hallucination_detected is True
        assert resp.report.faithfulness_score == 0.0
        assert resp.report.risk_level == HallucinationRiskLevel.HIGH

    @pytest.mark.asyncio
    async def test_min_faithfulness_bumps_risk_with_mock_provider(
        self, sample_chunks, good_answer
    ):
        # Mock provider returns all-supported and 0.5 overall.  With
        # min_faithfulness=0.9 the guard should clamp risk to LOW.
        class _SoftMock(MockFaithfulnessProvider):
            async def generate(self, **kwargs):
                from app.services.answer_generation.providers import LLMResponse
                # Mark every claim as supported with overall 0.5 — score
                # is MEDIUM but min_faithfulness should clamp risk to LOW.
                sup, unsup = _extract_claims_from_prompt(kwargs["user_prompt"]), []
                supported_payload = [
                    {"claim_id": cid, "claim": ctext, "cited_chunk_ids": ["chk-1"]}
                    for cid, ctext, _ in sup
                ]
                payload = {
                    "supported_claims": supported_payload,
                    "unsupported_claims": [],
                    "overall_faithfulness": 0.5,
                }
                return LLMResponse(
                    text=json.dumps(payload),
                    prompt_tokens=10,
                    completion_tokens=10,
                    total_tokens=20,
                    model=self.model,
                    provider="mock-faithfulness",
                )

        guard = HallucinationGuardService(provider=_SoftMock())
        request = FaithfulnessRequest(
            query="q", answer=good_answer, chunks=sample_chunks,
            method=VerificationMethod.LLM,
            min_faithfulness=0.9,
        )
        resp = await guard.verify(request)
        assert resp.report.hallucination_detected is False
        assert resp.report.faithfulness_score == 0.5
        # min_faithfulness clamps the risk to LOW even though score is MEDIUM
        assert resp.report.risk_level == HallucinationRiskLevel.LOW


# ─── API integration tests ──────────────────────────────────────────────────


class TestHallucinationAPI:
    @pytest.mark.asyncio
    async def test_health(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/hallucination/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"
            assert data["module"] == "hallucination_guard"
            assert data["version"] == "5.4.0"

    @pytest.mark.asyncio
    async def test_verify_lexical_supported(self, app, sample_chunks, good_answer):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {
                "query": "What is KYC?",
                "answer": good_answer.model_dump(),
                "chunks": [c.model_dump() for c in sample_chunks],
                "method": "lexical",
            }
            r = await c.post("/api/v1/hallucination/verify", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["method"] == "lexical"
            assert data["report"]["hallucination_detected"] is False
            assert data["report"]["faithfulness_score"] == 1.0
            assert data["report"]["risk_level"] == "none"

    @pytest.mark.asyncio
    async def test_verify_lexical_unsupported(self, app, sample_chunks, bad_answer):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {
                "query": "What is KYC?",
                "answer": bad_answer.model_dump(),
                "chunks": [c.model_dump() for c in sample_chunks],
                "method": "lexical",
            }
            r = await c.post("/api/v1/hallucination/verify", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["report"]["hallucination_detected"] is True
            assert data["report"]["unsupported_count"] >= 1
            assert any("monthly tax" in c["claim"] for c in data["report"]["unsupported_claims"])

    @pytest.mark.asyncio
    async def test_verify_empty_query_rejected(self, app, good_answer):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {
                "query": "   ",
                "answer": good_answer.model_dump(),
                "chunks": [],
                "method": "lexical",
            }
            r = await c.post("/api/v1/hallucination/verify", json=payload)
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_verify_empty_summary_rejected(self, app, good_answer):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {
                "query": "q",
                "answer": {
                    "executive_summary": "   ",
                    "detailed_explanation": "details",
                    "supporting_evidence": [],
                    "key_regulatory_references": [],
                },
                "chunks": [],
                "method": "lexical",
            }
            r = await c.post("/api/v1/hallucination/verify", json=payload)
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_verify_empty_chunks(self, app, good_answer):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {
                "query": "q",
                "answer": good_answer.model_dump(),
                "chunks": [],
                "method": "lexical",
            }
            r = await c.post("/api/v1/hallucination/verify", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["report"]["hallucination_detected"] is True
            assert data["report"]["unsupported_count"] >= 1

    @pytest.mark.asyncio
    async def test_verify_metadata_populated(self, app, sample_chunks, good_answer):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {
                "query": "q",
                "answer": good_answer.model_dump(),
                "chunks": [c.model_dump() for c in sample_chunks],
                "method": "lexical",
            }
            r = await c.post("/api/v1/hallucination/verify", json=payload)
            data = r.json()
            assert "metadata" in data
            assert "request_id" in data["metadata"]
            assert data["metadata"]["chunks_used"] == 2
            assert data["metadata"]["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_dependency_overrides_inject_mock_provider(
        self, app, sample_chunks, bad_answer
    ):
        # Build a custom app with a guard wired to a mock provider, then
        # exercise the LLM endpoint.
        from app.api.dependencies import get_hallucination_guard_service

        guard = build_default_hallucination_guard(provider=MockFaithfulnessProvider())
        app.dependency_overrides[get_hallucination_guard_service] = lambda: guard
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            payload = {
                "query": "q",
                "answer": bad_answer.model_dump(),
                "chunks": [c.model_dump() for c in sample_chunks],
                "method": "llm",
            }
            r = await c.post("/api/v1/hallucination/verify", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["metadata"]["provider_used"] == "mock-faithfulness"
            assert data["report"]["hallucination_detected"] is True
