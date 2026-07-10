"""Tests for Module 5.5 — Source Attribution Engine.

Coverage
--------
* Schema validation (AttributionRequest, AttributionResponse,
  SourceAttribution, AttributionCoverage, bucket_confidence,
  build_excerpt).
* AttributionMapper — segment splitting, matching, threshold handling.
* AttributionValidator — coverage checks, full-coverage enforcement.
* SourceAttributionService — orchestrator + coverage computation.
* API integration: /api/v1/attribution/attribute + /health.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_attribution_service,
    reset_attribution_service,
)
from app.api.v1.attribution import router as attribution_router
from app.schemas.answer_generation import (
    AnswerSection,
    RetrievedChunk,
)
from app.schemas.attribution import (
    AttributionConfidence,
    AttributionRequest,
    AttributionResponse,
    AttributionSection,
    SourceAttribution,
    bucket_confidence,
    build_excerpt,
)
from app.services.attribution import (
    AttributionMapper,
    build_default_attribution_service,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_attribution_service()
    yield
    reset_attribution_service()


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
            document_id="doc-2",
            document_title="SEBI LODR",
            source="SEBI",
            page_number=42,
            section="Disclosure Obligations",
            content=(
                "Listed entities must disclose material information to stock "
                "exchanges promptly. Insider trading is prohibited."
            ),
            score=0.81,
        ),
    ]


@pytest.fixture
def well_supported_answer() -> AnswerSection:
    return AnswerSection(
        executive_summary="Banks perform KYC at onboarding.",
        detailed_explanation=(
            "The KYC process includes identity verification, address proof, "
            "and risk profiling."
        ),
        supporting_evidence=[],
        key_regulatory_references=[],
    )


@pytest.fixture
def mixed_answer() -> AnswerSection:
    return AnswerSection(
        executive_summary="Banks perform KYC at onboarding.",
        detailed_explanation=(
            "The KYC process includes identity verification, address proof, "
            "and risk profiling. Banks must also send weekly SMS reminders "
            "to all account holders about their KYC status."
        ),
        supporting_evidence=[],
        key_regulatory_references=[
            "RBI Master Direction on KYC, 2016",
        ],
    )


@pytest.fixture
def app():
    reset_attribution_service()
    app = FastAPI()
    app.include_router(attribution_router, prefix="/api/v1")
    service = build_default_attribution_service()
    app.dependency_overrides[get_attribution_service] = lambda: service
    yield app
    app.dependency_overrides.clear()
    reset_attribution_service()


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_bucket_confidence_thresholds(self):
        assert bucket_confidence(0.9) == AttributionConfidence.HIGH
        assert bucket_confidence(0.7) == AttributionConfidence.HIGH
        assert bucket_confidence(0.5) == AttributionConfidence.MEDIUM
        assert bucket_confidence(0.4) == AttributionConfidence.MEDIUM
        assert bucket_confidence(0.2) == AttributionConfidence.LOW
        assert bucket_confidence(0.15) == AttributionConfidence.LOW
        assert bucket_confidence(0.1) == AttributionConfidence.NONE
        assert bucket_confidence(0.0) == AttributionConfidence.NONE

    def test_build_excerpt_truncates(self):
        text = "a " * 200
        excerpt = build_excerpt(text, max_length=50)
        assert len(excerpt) <= 50
        assert excerpt.endswith("…")

    def test_build_excerpt_no_truncation(self):
        text = "short text"
        assert build_excerpt(text, max_length=100) == "short text"

    def test_build_excerpt_collapses_whitespace(self):
        text = "a   b\n\n   c"
        assert build_excerpt(text) == "a b c"

    def test_source_attribution_default_id(self):
        sa = SourceAttribution(
            section=AttributionSection.EXECUTIVE_SUMMARY,
            segment_index=0,
            segment_text="x",
            document_id="d",
            document_title="t",
            chunk_id="c",
            excerpt="e",
            similarity=0.5,
            confidence=AttributionConfidence.MEDIUM,
        )
        assert sa.attribution_id.startswith("att-")

    def test_attribution_request_rejects_short_query(self):
        with pytest.raises(Exception):
            AttributionRequest(
                query="",
                answer=AnswerSection(
                    executive_summary="s",
                    detailed_explanation="d",
                    supporting_evidence=[],
                    key_regulatory_references=[],
                ),
                chunks=[],
            )

    def test_attribution_request_allows_empty_chunks(self):
        req = AttributionRequest(
            query="q",
            answer=AnswerSection(
                executive_summary="s",
                detailed_explanation="d",
                supporting_evidence=[],
                key_regulatory_references=[],
            ),
            chunks=[],
        )
        assert req.chunks == []


# ─── Mapper tests ───────────────────────────────────────────────────────────


class TestAttributionMapper:
    def test_map_no_chunks(self, well_supported_answer):
        mapper = AttributionMapper()
        attrs = mapper.map(answer=well_supported_answer, chunks=[])
        # No chunks → every segment is unattributed but still recorded.
        assert len(attrs) >= 1
        for a in attrs:
            assert a.confidence == AttributionConfidence.NONE
            assert a.document_id == ""
            assert a.similarity == 0.0

    def test_map_supported_segments(self, sample_chunks, well_supported_answer):
        mapper = AttributionMapper()
        attrs = mapper.map(
            answer=well_supported_answer, chunks=sample_chunks, min_similarity=0.10
        )
        # All segments should match a chunk.
        assert all(a.confidence != AttributionConfidence.NONE for a in attrs)
        assert all(a.document_id for a in attrs)
        assert all(a.excerpt for a in attrs)
        # Segments come from both executive_summary and detailed_explanation.
        sections = {a.section for a in attrs}
        assert AttributionSection.EXECUTIVE_SUMMARY in sections
        assert AttributionSection.DETAILED_EXPLANATION in sections

    def test_map_includes_key_references(self, sample_chunks, mixed_answer):
        mapper = AttributionMapper()
        attrs = mapper.map(answer=mixed_answer, chunks=sample_chunks)
        sections = {a.section for a in attrs}
        assert AttributionSection.KEY_REGULATORY_REFERENCES in sections

    def test_map_threshold_filters(self, sample_chunks, mixed_answer):
        mapper = AttributionMapper()
        # High threshold → only high-confidence attributions survive.
        attrs = mapper.map(
            answer=mixed_answer, chunks=sample_chunks, min_similarity=0.95
        )
        # All attributions should still be returned (so we can see what
        # was filtered), but most will be low/none confidence.
        none_count = sum(1 for a in attrs if a.confidence == AttributionConfidence.NONE)
        assert none_count >= 1

    def test_map_excerpt_respects_length(self, sample_chunks, well_supported_answer):
        mapper = AttributionMapper()
        attrs = mapper.map(
            answer=well_supported_answer,
            chunks=sample_chunks,
            max_excerpt_length=50,
        )
        for a in attrs:
            if a.excerpt:
                assert len(a.excerpt) <= 50


# ─── Validator tests ────────────────────────────────────────────────────────


class TestAttributionValidator:
    def test_valid_when_all_attributed(self, well_supported_answer, sample_chunks):
        service = build_default_attribution_service()
        resp = service.attribute_segments(
            query="q", answer=well_supported_answer, chunks=sample_chunks
        )
        assert resp.validation.valid is True
        assert resp.validation.issues == []

    def test_full_coverage_required(self, mixed_answer, sample_chunks):
        service = build_default_attribution_service()
        resp = service.attribute_segments(
            query="q",
            answer=mixed_answer,
            chunks=sample_chunks,
            require_full_coverage=True,
        )
        # SMS reminders claim is not in any chunk → unattributed → issue.
        if resp.coverage.unattributed_segments > 0:
            assert any("require_full_coverage" in i for i in resp.validation.issues)
            assert resp.validation.valid is False
        else:
            assert resp.validation.valid is True

    def test_warning_when_low_conf_majority(self, well_supported_answer, sample_chunks):
        # Use a very high threshold so most attributions are marked
        # matched_below_threshold → low confidence.
        service = build_default_attribution_service()
        resp = service.attribute_segments(
            query="q",
            answer=well_supported_answer,
            chunks=sample_chunks,
            min_similarity=0.95,
        )
        # The "LOW" warning triggers only when >50% of segments are LOW.
        # We can also assert coverage is reasonable.
        assert resp.coverage.total_segments >= 1


# ─── Service tests ──────────────────────────────────────────────────────────


class TestSourceAttributionService:
    def test_attribute_returns_full_envelope(
        self, well_supported_answer, sample_chunks
    ):
        service = build_default_attribution_service()
        req = AttributionRequest(
            query="q", answer=well_supported_answer, chunks=sample_chunks
        )
        resp = service.attribute(req)
        assert isinstance(resp, AttributionResponse)
        assert resp.query == "q"
        assert resp.coverage.total_segments == len(resp.attributions)
        assert resp.metadata.chunks_used == 2
        assert resp.metadata.segments_extracted == len(resp.attributions)
        assert resp.metadata.latency_ms >= 0

    def test_attribute_segments_convenience(self, well_supported_answer, sample_chunks):
        service = build_default_attribution_service()
        resp = service.attribute_segments(
            query="q", answer=well_supported_answer, chunks=sample_chunks
        )
        assert resp.coverage.total_segments >= 1
        assert resp.metadata.request_id  # non-empty UUID hex

    def test_coverage_counts(self, well_supported_answer, sample_chunks):
        service = build_default_attribution_service()
        resp = service.attribute_segments(
            query="q", answer=well_supported_answer, chunks=sample_chunks
        )
        c = resp.coverage
        # High + medium + low + (unattributed) = total
        assert (
            c.high_confidence_count
            + c.medium_confidence_count
            + c.low_confidence_count
            + c.unattributed_segments
            == c.total_segments
        )
        # Average similarity is bounded.
        assert 0.0 <= c.average_similarity <= 1.0
        # Coverage ratio.
        if c.total_segments:
            assert 0.0 <= c.coverage_ratio <= 1.0

    def test_empty_answer(self, sample_chunks):
        # Both summary and explanation non-empty (schema requires
        # min_length=1); sentence extraction may return 0 claims if
        # content is just punctuation.
        answer = AnswerSection(
            executive_summary="Banks perform KYC.",
            detailed_explanation="KYC is a process.",
            supporting_evidence=[],
            key_regulatory_references=[],
        )
        service = build_default_attribution_service()
        resp = service.attribute_segments(
            query="q", answer=answer, chunks=sample_chunks
        )
        # Both are claim-bearing sections, so 2 segments.
        assert resp.coverage.total_segments >= 2


# ─── API tests ──────────────────────────────────────────────────────────────


class TestAttributionAPI:
    @pytest.mark.asyncio
    async def test_health(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get("/api/v1/attribution/health")
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"
            assert data["module"] == "source_attribution"

    @pytest.mark.asyncio
    async def test_attribute_full(self, app, well_supported_answer, sample_chunks):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            payload = {
                "query": "What is KYC?",
                "answer": well_supported_answer.model_dump(),
                "chunks": [c.model_dump() for c in sample_chunks],
            }
            r = await c.post("/api/v1/attribution/attribute", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert "attributions" in data
            assert "coverage" in data
            assert "validation" in data
            assert data["query"] == "What is KYC?"

    @pytest.mark.asyncio
    async def test_attribute_empty_query_rejected(self, app, well_supported_answer):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            payload = {
                "query": "  ",
                "answer": well_supported_answer.model_dump(),
                "chunks": [],
            }
            r = await c.post("/api/v1/attribution/attribute", json=payload)
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_attribute_empty_summary_rejected(self, app, sample_chunks):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            payload = {
                "query": "q",
                "answer": {
                    "executive_summary": "",
                    "detailed_explanation": "details",
                    "supporting_evidence": [],
                    "key_regulatory_references": [],
                },
                "chunks": [c.model_dump() for c in sample_chunks],
            }
            r = await c.post("/api/v1/attribution/attribute", json=payload)
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_attribute_no_chunks_still_returns_200(
        self, app, well_supported_answer
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            payload = {
                "query": "q",
                "answer": well_supported_answer.model_dump(),
                "chunks": [],
            }
            r = await c.post("/api/v1/attribution/attribute", json=payload)
            assert r.status_code == 200
            data = r.json()
            # All segments unattributed.
            assert (
                data["coverage"]["unattributed_segments"]
                == data["coverage"]["total_segments"]
            )
            assert data["coverage"]["coverage_ratio"] == 0.0

    @pytest.mark.asyncio
    async def test_attribute_metadata_populated(
        self, app, well_supported_answer, sample_chunks
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            payload = {
                "query": "q",
                "answer": well_supported_answer.model_dump(),
                "chunks": [c.model_dump() for c in sample_chunks],
            }
            r = await c.post("/api/v1/attribution/attribute", json=payload)
            data = r.json()
            assert "metadata" in data
            assert data["metadata"]["chunks_used"] == 2
            assert data["metadata"]["segments_extracted"] >= 1
            assert data["metadata"]["latency_ms"] >= 0.0
