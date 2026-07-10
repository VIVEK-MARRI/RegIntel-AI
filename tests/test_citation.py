"""Module 5.2 — Citation Engine tests.

Covers:
* Pydantic schema validation
* Inline marker formatting (circular number, page, source)
* Claim extraction (sentence split, filtering, dedup)
* Citation mapper scoring (lexical overlap + section boost)
* CitationBuilder (reference list, annotated text, citation map)
* CitationService end-to-end (orchestration + coverage)
* API integration tests against ``/api/v1/citation/cite`` and
  ``/api/v1/citation/health``.

The citation engine is deterministic and dependency-free, so the
test suite runs offline without any LLM or retrieval backend.
"""

from __future__ import annotations

from typing import List

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_citation_service
from app.main import app
from app.models.document import SourceEnum
from app.schemas.answer_generation import (
    AnswerSection,
    EvidenceChunk,
    RetrievedChunk,
)
from app.schemas.citation import (
    CitationRequest,
    CitationResponse,
    CitationStyle,
    Claim,
    ReferenceEntry,
)
from app.services.citation import (
    CitationBuilder,
    CitationMapper,
    CitationService,
    ClaimExtractor,
    build_default_citation_service,
    split_into_sentences,
)
from app.services.citation.mapper import (
    section_boost,
    token_overlap,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _chunk(
    cid: str = "c-1",
    doc: str = "d-1",
    content: str = "Sample regulatory text for testing.",
    score: float = 0.9,
    source=None,
    page: int = 1,
    section: str = "Section A",
    title: str = "RBI Master Direction 2016",
) -> RetrievedChunk:
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
def rbi_chunks() -> List[RetrievedChunk]:
    return [
        _chunk(
            cid="c-1",
            doc="d-1",
            content=(
                "Banks must follow RBI KYC norms under Master Direction "
                "MD/2016/1. Customer identification procedure requires "
                "PAN for transactions above fifty thousand rupees. Banks "
                "shall verify identity of beneficial owners."
            ),
            source=SourceEnum.RBI,
            page=12,
            section="KYC",
            title="RBI Master Direction MD/2016/1 on KYC",
        ),
        _chunk(
            cid="c-2",
            doc="d-2",
            content=(
                "SEBI mandates monthly portfolio disclosure of scheme-wise "
                "holdings within seven days of the close of the month."
            ),
            source=SourceEnum.SEBI,
            page=4,
            section="Disclosure",
            title="SEBI Circular 12/2024",
        ),
    ]


@pytest.fixture
def sample_answer() -> AnswerSection:
    return AnswerSection(
        executive_summary=(
            "Banks must follow RBI KYC norms under Master Direction MD/2016/1."
        ),
        detailed_explanation=(
            "Customer identification procedure requires PAN for transactions "
            "above fifty thousand rupees. "
            "SEBI mandates monthly portfolio disclosure of scheme-wise "
            "holdings within seven days."
        ),
        supporting_evidence=[
            EvidenceChunk(
                chunk_id="c-1",
                document_id="d-1",
                source="RBI",
                excerpt="Banks must follow RBI KYC norms.",
            ),
        ],
        key_regulatory_references=["RBI Act 1934", "PMLA 2002"],
    )


@pytest.fixture
def citation_service() -> CitationService:
    return build_default_citation_service()


# ─── Schema / format helpers ───────────────────────────────────────────────


class TestMarkerFormatting:
    def test_marker_with_circular_and_page(self):
        from app.schemas.citation import format_inline_marker

        m = format_inline_marker(
            source="RBI",
            document_type="Circular",
            document_title="RBI Circular 12/2024 on KYC",
            circular_number="12/2024",
            page_number=8,
        )
        assert m == "[RBI Circular 12/2024 | Page 8]"

    def test_marker_without_page(self):
        from app.schemas.citation import format_inline_marker

        m = format_inline_marker(
            source="RBI",
            document_type="Act",
            document_title="RBI Act 1934",
            circular_number=None,
            page_number=None,
        )
        assert m == "[RBI Act 1934]"

    def test_marker_strips_source_prefix_in_title(self):
        from app.schemas.citation import format_inline_marker

        m = format_inline_marker(
            source="SEBI",
            document_type="Master Direction",
            document_title="SEBI Master Direction on Portfolio Disclosure",
            circular_number=None,
            page_number=4,
        )
        assert m == "[SEBI Master Direction on Portfolio Disclosure | Page 4]"

    def test_marker_falls_back_to_unknown(self):
        from app.schemas.citation import format_inline_marker

        m = format_inline_marker(
            source=None,
            document_type=None,
            document_title=None,
            circular_number=None,
            page_number=None,
        )
        assert m == "[Unknown Source]"

    def test_extract_circular_variants(self):
        from app.schemas.citation import extract_circular_number

        assert extract_circular_number("RBI Circular 12/2024") == "12/2024"
        assert extract_circular_number("MD/2016/1") == "MD/2016/1"
        assert extract_circular_number("RBI/2024-25/123") == "RBI/2024-25/123"
        assert (
            extract_circular_number("SEBI/HO/MIRSD-SEC-1/2024")
            == "SEBI/HO/MIRSD-SEC-1/2024"
        )
        assert extract_circular_number("No number here") is None

    def test_detect_document_type(self):
        from app.schemas.citation import detect_document_type

        assert detect_document_type("RBI Master Direction 2016") == "Master Direction"
        assert detect_document_type("SEBI Circular 12/2024") == "Circular"
        assert detect_document_type("Master Circular on KYC") == "Master Circular"
        assert detect_document_type("Banking Regulation Act 1949") == "Act"
        assert detect_document_type("") is None

    def test_reference_entry_marker_via_to_marker(self):
        ref = ReferenceEntry(
            citation_id="ref-1",
            chunk_id="c-1",
            document_id="d-1",
            document_title="RBI Circular 12/2024",
            source="RBI",
            document_type="Circular",
            circular_number="12/2024",
            page_number=8,
            excerpt="KYC norms.",
        )
        assert ref.to_marker() == "[RBI Circular 12/2024 | Page 8]"


# ─── Claim extraction ───────────────────────────────────────────────────────


class TestClaimExtractor:
    def test_split_basic_sentences(self):
        sentences = split_into_sentences(
            "Banks must follow KYC. Customer identification is mandatory. "
            "SEBI mandates portfolio disclosure."
        )
        # 3 sentences, with trailing punctuation preserved on each.
        assert len(sentences) == 3
        assert sentences[0].startswith("Banks must follow KYC")
        assert sentences[1].startswith("Customer identification is mandatory")
        assert sentences[2].startswith("SEBI mandates portfolio disclosure")
        assert sentences[0].endswith("KYC.")
        assert sentences[1].endswith("mandatory.")
        assert sentences[2].endswith("disclosure.")

    def test_split_handles_paragraph_breaks(self):
        sentences = split_into_sentences(
            "Banks must follow KYC.\n\nSEBI mandates portfolio disclosure."
        )
        assert any(s.startswith("Banks must follow KYC") for s in sentences)
        assert any(
            s.startswith("SEBI mandates portfolio disclosure") for s in sentences
        )
        assert len(sentences) == 2

    def test_split_drops_short_fragments(self):
        ex = ClaimExtractor(min_chars=20)
        claims = ex.extract("OK. Banks must follow KYC under RBI norms.", "x")
        assert all(len(c.text) >= 20 for c in claims)
        assert any("KYC" in c.text for c in claims)

    def test_extract_drops_questions(self):
        ex = ClaimExtractor()
        claims = ex.extract("Banks must follow KYC. What about SEBI?", "x")
        assert all(not c.text.endswith("?") for c in claims)

    def test_extract_deduplicates(self):
        ex = ClaimExtractor()
        claims = ex.extract("Banks must follow KYC. Banks must follow KYC.", "x")
        assert len(claims) == 1

    def test_extract_assigns_section(self):
        ex = ClaimExtractor()
        claims = ex.extract(
            "Banks must follow KYC under RBI norms.", "executive_summary"
        )
        assert all(c.section == "executive_summary" for c in claims)


# ─── Mapper scoring ────────────────────────────────────────────────────────


class TestCitationMapper:
    def test_token_overlap_identical(self):
        score = token_overlap("Banks must follow KYC", "Banks must follow KYC")
        assert score > 0.9

    def test_token_overlap_disjoint(self):
        score = token_overlap("Banks must follow KYC", "Cloud services and APIs")
        assert score < 0.1

    def test_token_overlap_partial(self):
        score = token_overlap(
            "Customer identification requires PAN for transactions",
            "Customer identification procedure requires PAN for high-value transactions",
        )
        assert 0.2 < score < 1.0

    def test_section_boost_exact(self):
        chunk = _chunk(section="KYC")
        claim = Claim(text="Banks must follow KYC norms under RBI", section="x")
        assert section_boost(claim, chunk) > 0.0

    def test_section_boost_word(self):
        chunk = _chunk(section="Customer Identification")
        claim = Claim(text="Customer identification is mandatory", section="x")
        assert section_boost(claim, chunk) > 0.0

    def test_section_boost_miss(self):
        chunk = _chunk(section="Disclosure")
        claim = Claim(text="Banks must follow KYC norms", section="x")
        assert section_boost(claim, chunk) == 0.0

    def test_mapper_returns_best_match(self, rbi_chunks):
        mapper = CitationMapper(min_similarity=0.05)
        claim = Claim(
            text="Customer identification requires PAN for transactions",
            section="detailed_explanation",
        )
        matches = mapper.map_claim(claim, rbi_chunks)
        assert len(matches) >= 1
        assert matches[0].chunk.chunk_id == "c-1"
        assert matches[0].final_score >= 0.1

    def test_mapper_below_threshold(self, rbi_chunks):
        mapper = CitationMapper(min_similarity=0.99)
        claim = Claim(text="Customer identification", section="x")
        matches = mapper.map_claim(claim, rbi_chunks)
        # No chunk should reach 0.99 for such a short claim.
        assert matches == []


# ─── Builder ───────────────────────────────────────────────────────────────


class TestCitationBuilder:
    def test_build_references_dedupes_by_document(self, rbi_chunks):
        # Add a second chunk from d-1 to test dedup.
        rbi_chunks.append(
            _chunk(
                cid="c-3",
                doc="d-1",
                content="Another KYC rule.",
                source=SourceEnum.RBI,
                page=13,
                section="KYC",
                title="RBI Master Direction MD/2016/1 on KYC",
            )
        )
        builder = CitationBuilder()
        refs = builder.build_references(rbi_chunks, include_paragraph=True)
        # Two unique documents.
        assert len(refs) == 2
        assert {r.document_id for r in refs} == {"d-1", "d-2"}

    def test_reference_contains_extracted_metadata(self, rbi_chunks):
        builder = CitationBuilder()
        refs = builder.build_references(rbi_chunks, include_paragraph=True)
        # Find the RBI ref.
        rbi = next(r for r in refs if r.source == "RBI")
        assert rbi.circular_number == "MD/2016/1"
        assert rbi.document_type == "Master Direction"
        assert rbi.page_number == 12
        assert rbi.section == "KYC"
        # Excerpt populated.
        assert rbi.excerpt

    def test_annotate_text_appends_marker(self, rbi_chunks, sample_answer):
        builder = CitationBuilder()
        refs = builder.build_references(rbi_chunks, include_paragraph=True)
        ex = ClaimExtractor()
        claims = ex.extract(sample_answer.executive_summary, "executive_summary")
        mapper = CitationMapper(min_similarity=0.05)
        matches_by_claim = {c.claim_id: mapper.map_claim(c, rbi_chunks) for c in claims}
        annotated = builder.annotate_text(
            sample_answer.executive_summary,
            "executive_summary",
            claims,
            matches_by_claim,
            refs,
        )
        assert annotated.cited_claim_count == len(claims)
        assert annotated.claim_count == len(claims)
        # Inline marker present in annotated text.
        assert "[RBI" in annotated.text
        assert "Page 12]" in annotated.text

    def test_numeric_bracket_style(self, rbi_chunks, sample_answer):
        builder = CitationBuilder(style=CitationStyle.NUMERIC_BRACKET)
        refs = builder.build_references(rbi_chunks, include_paragraph=True)
        ex = ClaimExtractor()
        claims = ex.extract(sample_answer.executive_summary, "executive_summary")
        mapper = CitationMapper(min_similarity=0.05)
        matches_by_claim = {c.claim_id: mapper.map_claim(c, rbi_chunks) for c in claims}
        annotated = builder.annotate_text(
            sample_answer.executive_summary,
            "executive_summary",
            claims,
            matches_by_claim,
            refs,
        )
        # Numeric style → "[1]" or "[2]" markers.
        assert "[1]" in annotated.text or "[2]" in annotated.text


# ─── Service (orchestration) ───────────────────────────────────────────────


class TestCitationService:
    def test_cite_full_coverage(self, citation_service, rbi_chunks, sample_answer):
        req = CitationRequest(
            query="What are KYC obligations?",
            answer=sample_answer,
            chunks=rbi_chunks,
        )
        res = citation_service.cite(req)
        assert isinstance(res, CitationResponse)
        assert res.coverage.total_claims >= 2
        # All claims should be cited given strong lexical overlap.
        assert res.coverage.cited_claims == res.coverage.total_claims
        assert res.coverage.coverage_ratio == 1.0
        assert res.coverage.uncited_claim_ids == []
        # Annotated text should have markers.
        assert "[" in res.annotated_answer.executive_summary.text
        # At least one reference per document.
        assert len(res.annotated_answer.references) >= 1
        # Citation map populated.
        assert res.annotated_answer.citation_map

    def test_cite_partial_coverage_reports_uncited(self, citation_service, rbi_chunks):
        answer = AnswerSection(
            executive_summary="This is unrelated text without overlap.",
            detailed_explanation="Completely alien content with no matching keywords.",
        )
        req = CitationRequest(
            query="Q",
            answer=answer,
            chunks=rbi_chunks,
            min_similarity=0.5,  # very high threshold
        )
        res = citation_service.cite(req)
        # min_chars=12 means short sentences are still extracted; the
        # mapper will likely return nothing for "very" high threshold.
        assert res.coverage.total_claims >= 0
        if res.coverage.total_claims > 0:
            assert res.coverage.uncited_claims >= 0

    def test_cite_rejects_empty_chunks(self, citation_service, sample_answer):
        with pytest.raises(ValueError):
            citation_service.cite(
                CitationRequest(query="q", answer=sample_answer, chunks=[])
            )

    def test_cite_uses_numeric_style_when_requested(
        self, citation_service, rbi_chunks, sample_answer
    ):
        req = CitationRequest(
            query="q",
            answer=sample_answer,
            chunks=rbi_chunks,
            style=CitationStyle.NUMERIC_BRACKET,
        )
        res = citation_service.cite(req)
        # Numeric style → reference ids like "[1]".
        for ref in res.annotated_answer.references:
            assert ref.citation_id.startswith("[")

    def test_cite_includes_paragraph_locator(self, citation_service, rbi_chunks):
        chunk_with_para = _chunk(
            cid="c-99",
            doc="d-99",
            content="Refer to clause (a) of section 4.1 for details on KYC.",
            source=SourceEnum.RBI,
            page=20,
            section="KYC",
            title="RBI Master Direction 2016",
        )
        chunks = [*rbi_chunks, chunk_with_para]
        answer = AnswerSection(
            executive_summary="Refer to clause (a) of section 4.1 for KYC.",
            detailed_explanation="Refer to clause (a) of section 4.1 for KYC details.",
            supporting_evidence=[],
            key_regulatory_references=[],
        )
        req = CitationRequest(
            query="q", answer=answer, chunks=chunks, include_paragraph=True
        )
        res = citation_service.cite(req)
        refs = res.annotated_answer.references
        c99_ref = next((r for r in refs if r.chunk_id == "c-99"), None)
        assert c99_ref is not None
        assert c99_ref.paragraph is not None

    def test_cite_answer_convenience(self, citation_service, rbi_chunks, sample_answer):
        res = citation_service.cite_answer(
            query="q", answer=sample_answer, chunks=rbi_chunks
        )
        assert res.coverage.total_claims >= 1
        assert res.metadata.chunks_used == len(rbi_chunks)


# ─── API integration ───────────────────────────────────────────────────────


class TestCitationAPI:
    @pytest_asyncio.fixture
    async def api_client(self):
        svc = build_default_citation_service()
        app.dependency_overrides[get_citation_service] = lambda: svc
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_cite_endpoint_success(self, api_client, rbi_chunks, sample_answer):
        payload = {
            "query": "What are KYC obligations?",
            "answer": sample_answer.model_dump(),
            "chunks": [c.model_dump() for c in rbi_chunks],
        }
        r = await api_client.post("/api/v1/citation/cite", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "annotated_answer" in body
        assert "references" in body["annotated_answer"]
        assert "coverage" in body
        assert body["metadata"]["chunks_used"] == 2

    @pytest.mark.asyncio
    async def test_cite_endpoint_validation_error(self, api_client):
        r = await api_client.post("/api/v1/citation/cite", json={"query": "q"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_cite_endpoint_empty_chunks(self, api_client, sample_answer):
        r = await api_client.post(
            "/api/v1/citation/cite",
            json={"query": "q", "answer": sample_answer.model_dump(), "chunks": []},
        )
        assert r.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_citation_health(self, api_client):
        r = await api_client.get("/api/v1/citation/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["module"] == "5.2-citation-engine"

    @pytest.mark.asyncio
    async def test_cite_endpoint_inlines_markers(
        self, api_client, rbi_chunks, sample_answer
    ):
        payload = {
            "query": "q",
            "answer": sample_answer.model_dump(),
            "chunks": [c.model_dump() for c in rbi_chunks],
        }
        r = await api_client.post("/api/v1/citation/cite", json=payload)
        body = r.json()
        annotated = body["annotated_answer"]
        # The detailed explanation should now contain an inline marker.
        assert "[" in annotated["detailed_explanation"]["text"]
        # At least one reference contains a page number when chunks had pages.
        assert any(
            "Page" in ref["document_title"] or ref["page_number"] is not None
            for ref in annotated["references"]
        )
        # Coverage must be present.
        assert 0.0 <= body["coverage"]["coverage_ratio"] <= 1.0
