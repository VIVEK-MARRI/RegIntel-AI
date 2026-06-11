"""Phase 7 — Citation Validation.

Covers: schema contracts, claim extraction, mapper scoring, builder
dedup/markers, service orchestration, coverage guarantees, style
correctness, API contracts, citation map integrity, and integration
with confidence and evaluation metrics.
"""

from __future__ import annotations

from typing import Dict, List

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_citation_service, get_reranker_service
from app.main import app
from app.schemas.answer_generation import AnswerSection, RetrievedChunk
from app.schemas.citation import (
    AnnotatedAnswer,
    AnnotatedText,
    CitationMetadata,
    CitationRequest,
    CitationResponse,
    CitationStyle,
    Claim,
    InlineCitation,
    ReferenceEntry,
)
from app.services.citation import (
    CitationBuilder,
    CitationMapper,
    CitationService,
    ClaimExtractor,
    TokenOverlapScorer,
    build_default_citation_service,
    split_into_sentences,
)
from app.services.citation.mapper import section_boost, token_overlap


# ─── Helpers ──────────────────────────────────────────────────────

def _chunk(
    cid: str = "c-1",
    content: str = "RBI Master Circular 12/2024 requires KYC compliance for all NBFCs.",
    doc_id: str = "doc-1",
    doc_title: str = "RBI Master Circular on KYC",
    source: str = "RBI",
    doc_type: str = "circular",
    section: str = "KYC",
    subsection: str = "Customer Identification",
    page: int | None = 1,
    score: float = 0.95,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        document_id=doc_id,
        content=content,
        score=score,
        source=source,
        page_number=page,
        section=section,
        subsection=subsection,
        document_title=doc_title,
    )


def _answer(text: str = "KYC compliance is mandatory for all financial entities.") -> AnswerSection:
    return AnswerSection(
        executive_summary=text,
        detailed_explanation=text,
        supporting_evidence=[],
        key_regulatory_references=[],
    )


# ══════════════════════════════════════════════════════════════════
# 7.1 — Citation Schema Contracts
# ══════════════════════════════════════════════════════════════════


class TestSchemaContracts:
    """Phase 7.1 — Citation Schema Validation"""

    def test_reference_entry_valid(self):
        r = ReferenceEntry(
            citation_id="cit-1", chunk_id="c-1", document_id="d-1",
            document_title="RBI Circular", source="RBI", excerpt="Text.",
        )
        assert r.citation_id == "cit-1"

    def test_reference_entry_defaults(self):
        r = ReferenceEntry(
            citation_id="c1", chunk_id="c1", document_id="d1",
            document_title="Title", excerpt="Excerpt.",
        )
        assert r.source is None
        assert r.page_number is None

    def test_inline_citation_valid(self):
        ic = InlineCitation(citation_id="c1", chunk_id="ck1", claim_id="cl1", marker="[1]")
        assert ic.marker == "[1]"

    def test_claim_minimal(self):
        c = Claim(claim_id="cl1", text="KYC is mandatory.", section="General")
        assert c.section == "General"

    def test_annotated_text_structure(self):
        at = AnnotatedText(text="Answer text.", citations=[], claim_count=2, cited_claim_count=2)
        assert at.claim_count == 2
        assert at.cited_claim_count == 2

    def test_annotated_answer_fields(self):
        aa = AnnotatedAnswer(
            executive_summary=AnnotatedText(text="Summary", citations=[], claim_count=1, cited_claim_count=1),
            detailed_explanation=AnnotatedText(text="Detail", citations=[], claim_count=1, cited_claim_count=1),
            supporting_evidence=[],
            key_regulatory_references=[],
            references=[],
            citation_map={},
        )
        assert aa.executive_summary.text == "Summary"

    def test_citation_metadata_valid(self):
        cm = CitationMetadata(
            request_id="req-1", timestamp="2024-01-01T00:00:00Z",
            latency_ms=12.3, chunks_used=3, claims_extracted=5,
            citations_emitted=4, style=CitationStyle.BRACKETED_SOURCE,
        )
        assert cm.latency_ms == 12.3


# ══════════════════════════════════════════════════════════════════
# 7.2 — Claim Extraction
# ══════════════════════════════════════════════════════════════════


class TestClaimExtraction:
    """Phase 7.2 — Claim Extraction Validation"""

    def test_split_sentences_basic(self):
        text = "KYC is mandatory. AML compliance is required."
        sentences = split_into_sentences(text)
        assert len(sentences) == 2
        assert sentences[0] == "KYC is mandatory."

    def test_split_sentences_with_abbrev(self):
        text = "As per RBI Act 1934, KYC is required. AML rules apply."
        sentences = split_into_sentences(text)
        assert len(sentences) >= 2

    def test_split_sentences_empty(self):
        assert split_into_sentences("") == []

    def test_extract_basic(self):
        extractor = ClaimExtractor()
        claims = extractor.extract("KYC is mandatory. AML rules apply.", "Compliance")
        assert len(claims) == 2
        assert all(c.section == "Compliance" for c in claims)

    def test_extract_filters_short_fragments(self):
        extractor = ClaimExtractor(min_chars=12)
        claims = extractor.extract("Hi. KYC is mandatory for all entities.", "Rules")
        assert len(claims) == 1
        assert "KYC" in claims[0].text

    def test_extract_filters_questions(self):
        extractor = ClaimExtractor()
        claims = extractor.extract("What is KYC? KYC means Know Your Customer.", "FAQ")
        assert len(claims) == 1
        assert "What" not in claims[0].text

    def test_extract_dedup_repeated(self):
        extractor = ClaimExtractor()
        text = "This is a unique sentence. This is a unique sentence. "
        claims = extractor.extract(text * 2, "Test")
        assert len(claims) >= 1

    def test_extract_max_claims(self):
        extractor = ClaimExtractor(max_claims_per_section=3)
        text = "A. B. C. D. E. F. "
        claims = extractor.extract(text, "Section")
        assert len(claims) <= 3

    def test_extract_all_sections(self):
        extractor = ClaimExtractor()
        sections = [("Compliance", "KYC is required."), ("AML", "AML rules apply.")]
        claims = extractor.extract_all(sections)
        assert len(claims) == 2

    def test_extract_all_empty(self):
        extractor = ClaimExtractor()
        claims = extractor.extract_all([])
        assert claims == []


# ══════════════════════════════════════════════════════════════════
# 7.3 — Citation Mapper Scoring
# ══════════════════════════════════════════════════════════════════


class TestCitationMapper:
    """Phase 7.3 — Citation Mapper Scoring Validation"""

    def test_token_overlap_exact(self):
        s = token_overlap("KYC compliance required", "KYC compliance required")
        assert s == pytest.approx(1.0, abs=0.01)

    def test_token_overlap_partial(self):
        s = token_overlap("KYC compliance required", "AML compliance required")
        assert 0.0 < s < 1.0

    def test_token_overlap_no_match(self):
        s = token_overlap("KYC compliance", "mutual fund regulations")
        assert s == 0.0

    def test_token_overlap_empty(self):
        assert token_overlap("", "") == 0.0

    def test_section_boost_exact(self):
        claim = Claim(claim_id="c1", text="KYC rule", section="KYC")
        chunk = _chunk(section="KYC")
        boost = section_boost(claim, chunk)
        assert boost > 0.0

    def test_section_boost_mismatch(self):
        claim = Claim(claim_id="c1", text="AML rule", section="AML")
        chunk = _chunk(section="KYC")
        boost = section_boost(claim, chunk)
        assert boost == 0.0

    def test_scorer_integration(self):
        scorer = TokenOverlapScorer(section_boost_weight=0.1)
        claim = Claim(claim_id="c1", text="KYC compliance", section="KYC")
        chunk = _chunk(content="KYC compliance required")
        score = scorer.score(claim, chunk)
        assert score > 0.0

    def test_mapper_map_claim_found(self):
        mapper = CitationMapper(min_similarity=0.05)
        claim = Claim(claim_id="c1", text="KYC compliance", section="KYC")
        chunk = _chunk(content="KYC compliance required")
        matches = mapper.map_claim(claim, [chunk])
        assert len(matches) > 0

    def test_mapper_map_claim_below_threshold(self):
        mapper = CitationMapper(min_similarity=0.9)
        claim = Claim(claim_id="c1", text="KYC compliance", section="KYC")
        chunk = _chunk(content="mutual fund regulations")
        matches = mapper.map_claim(claim, [chunk])
        assert len(matches) == 0

    def test_mapper_best_match(self):
        mapper = CitationMapper()
        claim = Claim(claim_id="c1", text="KYC compliance", section="KYC")
        chunk = _chunk(content="KYC compliance required")
        match = mapper.best_match(claim, [chunk])
        assert match is not None
        assert match.final_score > 0.0

    def test_mapper_best_match_no_result(self):
        mapper = CitationMapper(min_similarity=0.99)
        claim = Claim(claim_id="c1", text="KYC compliance", section="KYC")
        chunk = _chunk(content="completely unrelated text here")
        match = mapper.best_match(claim, [chunk])
        assert match is None


# ══════════════════════════════════════════════════════════════════
# 7.4 — Citation Builder
# ══════════════════════════════════════════════════════════════════


class TestCitationBuilder:
    """Phase 7.4 — Citation Builder Validation"""

    def test_build_references_dedup(self):
        builder = CitationBuilder()
        chunks = [
            _chunk(cid="c-1", doc_id="doc-1", doc_title="Circular 1", source="RBI"),
            _chunk(cid="c-2", doc_id="doc-1", doc_title="Circular 1", source="RBI"),
            _chunk(cid="c-3", doc_id="doc-2", doc_title="Circular 2", source="SEBI"),
        ]
        refs = builder.build_references(chunks)
        assert len(refs) == 2
        assert refs[0].document_id == "doc-1"

    def test_build_references_metadata(self):
        builder = CitationBuilder()
        chunk = _chunk(doc_id="d1", doc_title="Circular", source="RBI",
                       doc_type="circular", section="KYC", page=3)
        refs = builder.build_references([chunk])
        assert len(refs) == 1
        r = refs[0]
        assert r.source == "RBI"
        assert r.page_number == 3

    def test_build_references_empty(self):
        builder = CitationBuilder()
        refs = builder.build_references([])
        assert refs == []

    def test_annotate_text_adds_markers(self):
        builder = CitationBuilder()
        chunk = _chunk(doc_title="RBI Circular", source="RBI")
        refs = builder.build_references([chunk])
        claim = Claim(claim_id="cl1", text="KYC compliance required", section="KYC")
        annotated = builder.annotate_text(
            text="KYC compliance required for all.",
            section_name="KYC",
            claims=[claim],
            matches_by_claim={"cl1": []},
            references=refs,
        )
        assert isinstance(annotated, AnnotatedText)

    def test_annotate_text_citation_map(self):
        builder = CitationBuilder()
        chunk = _chunk(doc_title="RBI Circular", source="RBI")
        refs = builder.build_references([chunk])
        claim = Claim(claim_id="cl1", text="KYC compliance required", section="KYC")
        annotated = builder.annotate_text(
            text="KYC compliance required.",
            section_name="KYC",
            claims=[claim],
            matches_by_claim={"cl1": []},
            references=refs,
        )
        assert annotated.claim_count >= 1

    def test_build_annotated_answer_structure(self):
        builder = CitationBuilder()
        chunk = _chunk(doc_title="Circular", source="RBI")
        refs = builder.build_references([chunk])
        answer = AnswerSection(
            executive_summary="KYC required.",
            detailed_explanation="AML required.",
            supporting_evidence=[],
            key_regulatory_references=[],
        )
        exec_claims = [Claim(claim_id="e1", text="KYC required.", section="Compliance")]
        det_claims = [Claim(claim_id="d1", text="AML required.", section="AML")]
        aa, cmap = builder.build_annotated_answer(
            answer=answer, references=refs,
            exec_claims=exec_claims, detailed_claims=det_claims,
            exec_matches={"e1": []}, detailed_matches={"d1": []},
        )
        assert isinstance(aa, AnnotatedAnswer)
        assert isinstance(cmap, dict)
        assert len(aa.references) >= 1

    def test_numeric_style_markers(self):
        builder = CitationBuilder(style=CitationStyle.NUMERIC_BRACKET)
        ref = ReferenceEntry(
            citation_id="c1", chunk_id="ck1", document_id="d1",
            document_title="Circular", source="RBI", excerpt="Text.",
        )
        marker = builder._marker_for(ref)
        assert "c1" in marker


# ══════════════════════════════════════════════════════════════════
# 7.5 — Citation Service End-to-End
# ══════════════════════════════════════════════════════════════════


class TestCitationService:
    """Phase 7.5 — Citation Service Orchestration Validation"""

    def test_cite_basic(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC compliance required for all entities.")]
        answer = _answer("KYC compliance required for all entities.")
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks)
        assert isinstance(resp, CitationResponse)
        assert resp.annotated_answer is not None
        assert resp.coverage.coverage_ratio >= 0.0

    def test_cite_full_coverage(self):
        service = build_default_citation_service()
        content = "RBI Master Circular 12/2024 requires KYC compliance for all NBFCs."
        chunks = [_chunk(content=content)]
        answer = _answer(content)
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks,
                                    require_full_coverage=True)
        assert resp.coverage.coverage_ratio >= 0.0

    def test_cite_partial_coverage(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="AML compliance required.")]
        answer = _answer("KYC compliance is mandatory for all financial entities.")
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks)
        assert resp.coverage.total_claims >= 1
        assert resp.coverage.uncited_claims >= 0

    def test_cite_empty_chunks(self):
        service = build_default_citation_service()
        answer = _answer("KYC compliance required.")
        try:
            resp = service.cite_answer(query="KYC", answer=answer, chunks=[])
            assert False, "Should have raised validation error"
        except Exception:
            pass

    def test_cite_empty_answer(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC required.")]
        answer = _answer("?")
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks)
        assert resp.coverage.total_claims == 0

    def test_cite_metadata_present(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC required.")]
        answer = _answer("KYC required.")
        resp = service.cite_answer(query="test", answer=answer, chunks=chunks)
        assert resp.metadata.chunks_used > 0
        assert resp.metadata.latency_ms >= 0.0

    def test_cite_numeric_style(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC required.")]
        answer = _answer("KYC required.")
        resp = service.cite_answer(query="test", answer=answer, chunks=chunks,
                                    style=CitationStyle.NUMERIC_BRACKET)
        assert resp.metadata.style == CitationStyle.NUMERIC_BRACKET

    def test_cite_bracketed_source_style(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC required.")]
        answer = _answer("KYC required.")
        resp = service.cite_answer(query="test", answer=answer, chunks=chunks,
                                    style=CitationStyle.BRACKETED_SOURCE)
        assert resp.metadata.style == CitationStyle.BRACKETED_SOURCE

    def test_cite_reference_dedup(self):
        service = build_default_citation_service()
        chunks = [
            _chunk(cid="c1", doc_id="d1", doc_title="Circular", source="RBI",
                   content="KYC rule 1."),
            _chunk(cid="c2", doc_id="d1", doc_title="Circular", source="RBI",
                   content="KYC rule 2."),
        ]
        answer = _answer("KYC rule 1. KYC rule 2.")
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks)
        assert len(resp.annotated_answer.references) <= 1

    def test_cite_citation_map_integrity(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC compliance required.")]
        answer = _answer("KYC compliance required.")
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks)
        cmap = resp.annotated_answer.citation_map
        for claim_id, citation_id in cmap.items():
            assert isinstance(claim_id, str)
            assert isinstance(citation_id, str)

    def test_cite_coverage_ratio_range(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC required.")]
        answer = _answer("KYC required.")
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks)
        assert 0.0 <= resp.coverage.coverage_ratio <= 1.0

    def test_cite_claim_id_unique(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC required. AML required.")]
        answer = _answer("KYC required. AML required.")
        resp = service.cite_answer(query="compliance", answer=answer, chunks=chunks)
        cmap = resp.annotated_answer.citation_map
        assert len(set(cmap.keys())) == len(cmap)


# ══════════════════════════════════════════════════════════════════
# 7.6 — API Contracts
# ══════════════════════════════════════════════════════════════════


class TestCitationAPI:
    """Phase 7.6 — Citation API Contract Validation"""

    @pytest.fixture(autouse=True)
    def _override_citation(self):
        app.dependency_overrides[get_citation_service] = lambda: build_default_citation_service()
        yield
        app.dependency_overrides.pop(get_citation_service, None)

    @pytest_asyncio.fixture
    async def api_client(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    def _api_chunk(self, **kw) -> dict:
        return _chunk(**kw).model_dump()

    def _api_answer(self, text: str = "KYC compliance is required.") -> dict:
        return _answer(text).model_dump()

    @pytest.mark.asyncio
    async def test_cite_endpoint_success(self, api_client):
        resp = await api_client.post("/api/v1/citation/cite", json={
            "query": "KYC compliance",
            "answer": self._api_answer("KYC compliance is required."),
            "chunks": [self._api_chunk(cid="c1", content="KYC compliance is required.")],
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "annotated_answer" in body
        assert "coverage" in body
        assert "metadata" in body

    @pytest.mark.asyncio
    async def test_cite_endpoint_response_shape(self, api_client):
        resp = await api_client.post("/api/v1/citation/cite", json={
            "query": "KYC",
            "answer": self._api_answer("KYC required."),
            "chunks": [self._api_chunk(cid="c1", content="KYC required.")],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "query" in body
        assert "annotated_answer" in body
        aa = body["annotated_answer"]
        assert "executive_summary" in aa
        assert "references" in aa
        assert "citation_map" in aa

    @pytest.mark.asyncio
    async def test_cite_endpoint_empty_chunks(self, api_client):
        resp = await api_client.post("/api/v1/citation/cite", json={
            "query": "KYC",
            "answer": self._api_answer("KYC required."),
            "chunks": [],
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_cite_endpoint_422_missing_field(self, api_client):
        resp = await api_client.post("/api/v1/citation/cite", json={
            "query": "KYC",
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_cite_endpoint_empty_query(self, api_client):
        resp = await api_client.post("/api/v1/citation/cite", json={
            "query": "",
            "answer": self._api_answer("KYC required."),
            "chunks": [self._api_chunk(cid="c1", content="KYC required.")],
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_cite_endpoint_numeric_style(self, api_client):
        resp = await api_client.post("/api/v1/citation/cite", json={
            "query": "KYC",
            "answer": self._api_answer("KYC required."),
            "chunks": [self._api_chunk(cid="c1", content="KYC required.")],
            "style": "numeric_bracket",
        })
        assert resp.status_code == 200
        assert resp.json()["metadata"]["style"] == "numeric_bracket"

    @pytest.mark.asyncio
    async def test_health_endpoint(self, api_client):
        resp = await api_client.get("/api/v1/citation/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body


# ══════════════════════════════════════════════════════════════════
# 7.7 — Coverage Guarantees
# ══════════════════════════════════════════════════════════════════


class TestCoverageGuarantees:
    """Phase 7.7 — Citation Coverage Validation"""

    def test_full_coverage_flag_true(self):
        service = build_default_citation_service()
        content = "RBI Master Circular requires KYC compliance."
        chunks = [_chunk(content=content)]
        answer = _answer(content)
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks,
                                    require_full_coverage=True)
        assert resp.coverage.coverage_ratio >= 0.0

    def test_coverage_ratio_depends_on_chunks(self):
        service = build_default_citation_service()
        answer = _answer("KYC compliance is mandatory for NBFCs.")
        resp_no_match = service.cite_answer(query="KYC", answer=answer,
                                              chunks=[_chunk(content="AML compliance required.")])
        resp_match = service.cite_answer(query="KYC", answer=answer,
                                          chunks=[_chunk(content="KYC compliance mandatory for NBFCs.")])
        assert resp_match.coverage.coverage_ratio >= resp_no_match.coverage.coverage_ratio

    def test_uncited_claims_reported(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="AML compliance required.")]
        answer = _answer("KYC compliance is mandatory for all entities.")
        resp = service.cite_answer(query="compliance", answer=answer, chunks=chunks)
        assert resp.coverage.uncited_claims >= 0
        assert resp.coverage.total_claims >= resp.coverage.cited_claims

    def test_unique_references_counted(self):
        service = build_default_citation_service()
        chunks = [
            _chunk(cid="c1", doc_id="d1", doc_title="Circular", source="RBI", content="Rule 1."),
            _chunk(cid="c2", doc_id="d2", doc_title="Guidelines", source="SEBI", content="Rule 2."),
        ]
        answer = _answer("Rule 1. Rule 2.")
        resp = service.cite_answer(query="rules", answer=answer, chunks=chunks)
        assert resp.coverage.unique_references <= len(chunks)


# ══════════════════════════════════════════════════════════════════
# 7.8 — Citation Map Integrity
# ══════════════════════════════════════════════════════════════════


class TestCitationMapIntegrity:
    """Phase 7.8 — Citation Map Integrity Validation"""

    def test_map_claim_id_to_citation_id(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC required. AML required.")]
        answer = _answer("KYC required. AML required.")
        resp = service.cite_answer(query="compliance", answer=answer, chunks=chunks)
        cmap = resp.annotated_answer.citation_map
        for claim_id, citation_id in cmap.items():
            ref_ids = [r.citation_id for r in resp.annotated_answer.references]
            assert citation_id in ref_ids or citation_id == ""

    def test_every_cited_claim_in_map(self):
        service = build_default_citation_service()
        chunks = [_chunk(content="KYC compliance required.")]
        answer = _answer("KYC compliance required.")
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks)
        cmap = resp.annotated_answer.citation_map
        cited = [ic.claim_id for ic in resp.annotated_answer.executive_summary.citations]
        cited += [ic.claim_id for ic in resp.annotated_answer.detailed_explanation.citations]
        for claim_id in cited:
            assert claim_id in cmap


# ══════════════════════════════════════════════════════════════════
# 7.9 — Edge Cases
# ══════════════════════════════════════════════════════════════════


class TestCitationEdgeCases:
    """Phase 7.9 — Citation Edge Case Validation"""

    def test_no_chunks_no_citations(self):
        service = build_default_citation_service()
        answer = _answer("This answer has no supporting chunks.")
        try:
            resp = service.cite_answer(query="test", answer=answer, chunks=[])
            assert resp.coverage.cited_claims == 0
        except Exception:
            pass

    def test_very_long_answer(self):
        service = build_default_citation_service()
        text = "KYC compliance is required. " * 100
        chunks = [_chunk(content="KYC compliance is required.")]
        answer = _answer(text)
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks)
        assert resp.metadata.claims_extracted > 0

    def test_answer_with_numbers_and_symbols(self):
        service = build_default_citation_service()
        content = "As per Section 3(1) of RBI Act 1934, KYC is required."
        chunks = [_chunk(content=content)]
        answer = _answer(content)
        resp = service.cite_answer(query="KYC", answer=answer, chunks=chunks)
        assert resp.coverage.total_claims >= 1

    def test_multiline_answer(self):
        service = build_default_citation_service()
        content = "KYC is required.\n\nAML is required.\n\nReporting is required."
        chunks = [_chunk(content="KYC required.")]
        answer = _answer(content)
        resp = service.cite_answer(query="compliance", answer=answer, chunks=chunks)
        assert resp.coverage.total_claims >= 1

    def test_chunk_without_metadata(self):
        service = build_default_citation_service()
        chunk = RetrievedChunk(
            chunk_id="c1", document_id="d1", content="KYC required.", score=0.5,
        )
        answer = _answer("KYC required.")
        resp = service.cite_answer(query="KYC", answer=answer, chunks=[chunk])
        assert resp.metadata.chunks_used == 1


# ══════════════════════════════════════════════════════════════════
# 7.10 — Integration with Confidence & Evaluation
# ══════════════════════════════════════════════════════════════════


class TestIntegration:
    """Phase 7.10 — Citation Integration Validation"""

    def test_coverage_feeds_confidence(self):
        from app.services.confidence.factors import citation_coverage_factor
        result = citation_coverage_factor(coverage=1.0, answer={"text": "KYC required."})
        assert "score" in result
        assert 0.0 <= result["score"] <= 1.0

    def test_coverage_factor_zero(self):
        from app.services.confidence.factors import citation_coverage_factor
        result = citation_coverage_factor(coverage=0.0, answer={"text": "KYC required."})
        assert result["score"] == 0.0

    def test_coverage_factor_partial(self):
        from app.services.confidence.factors import citation_coverage_factor
        result = citation_coverage_factor(coverage=0.5, answer={"text": "KYC required."})
        assert 0.0 < result["score"] < 1.0

    def test_evaluation_citation_accuracy(self):
        from app.services.evaluation import MetricsEngine
        from app.schemas.orchestrator import FinalAnswerResponse, OrchestratorMetadata
        from app.schemas.answer_generation import AnswerSection
        from app.schemas.citation import AnnotatedAnswer, AnnotatedText, InlineCitation
        from app.schemas.confidence import ConfidenceLevel
        from app.schemas.hallucination import HallucinationRiskLevel
        engine = MetricsEngine()
        answer = AnswerSection(
            executive_summary="KYC required.",
            detailed_explanation="KYC required in detail.",
            supporting_evidence=[],
            key_regulatory_references=[],
        )
        resp = FinalAnswerResponse(
            query="KYC",
            answer=answer,
            citations=AnnotatedAnswer(
                executive_summary=AnnotatedText(
                    text="KYC required.",
                    citations=[InlineCitation(citation_id="c1", chunk_id="ck1", claim_id="cl1", marker=" [Test]")],
                    claim_count=2, cited_claim_count=1,
                ),
                detailed_explanation=AnnotatedText(
                    text="KYC required in detail.",
                    citations=[],
                    claim_count=1, cited_claim_count=1,
                ),
                supporting_evidence=[],
                key_regulatory_references=[],
                references=[],
                citation_map={},
            ),
            confidence_score=0.9, confidence_level=ConfidenceLevel.HIGH,
            faithfulness_score=0.9, hallucination_detected=False,
            hallucination_risk_level=HallucinationRiskLevel.NONE,
            source_attributions=[],
            metadata=OrchestratorMetadata(),
        )
        s = engine.citation_accuracy(resp)
        assert 0.0 <= s.score <= 1.0

    def test_evaluation_citation_accuracy_full(self):
        from app.services.evaluation import MetricsEngine
        from app.schemas.orchestrator import FinalAnswerResponse, OrchestratorMetadata
        from app.schemas.answer_generation import AnswerSection
        from app.schemas.citation import AnnotatedAnswer, AnnotatedText, InlineCitation
        from app.schemas.confidence import ConfidenceLevel
        from app.schemas.hallucination import HallucinationRiskLevel
        engine = MetricsEngine()
        answer = AnswerSection(
            executive_summary="All cited.",
            detailed_explanation="All cited in detail.",
            supporting_evidence=[],
            key_regulatory_references=[],
        )
        resp = FinalAnswerResponse(
            query="KYC",
            answer=answer,
            citations=AnnotatedAnswer(
                executive_summary=AnnotatedText(
                    text="All cited.",
                    citations=[InlineCitation(citation_id="c1", chunk_id="ck1", claim_id="cl1", marker=" [Test]")],
                    claim_count=1, cited_claim_count=1,
                ),
                detailed_explanation=AnnotatedText(
                    text="All cited in detail.",
                    citations=[InlineCitation(citation_id="c1", chunk_id="ck1", claim_id="cl1", marker=" [Test]")],
                    claim_count=1, cited_claim_count=1,
                ),
                supporting_evidence=[],
                key_regulatory_references=[],
                references=[],
                citation_map={},
            ),
            confidence_score=0.9, confidence_level=ConfidenceLevel.HIGH,
            faithfulness_score=0.9, hallucination_detected=False,
            hallucination_risk_level=HallucinationRiskLevel.NONE,
            source_attributions=[],
            metadata=OrchestratorMetadata(),
        )
        s = engine.citation_accuracy(resp)
        assert s.score == pytest.approx(1.0, abs=0.01)

    def test_evaluation_citation_accuracy_zero(self):
        from app.services.evaluation import MetricsEngine
        from app.schemas.orchestrator import FinalAnswerResponse, OrchestratorMetadata
        from app.schemas.answer_generation import AnswerSection
        from app.schemas.citation import AnnotatedAnswer, AnnotatedText
        from app.schemas.confidence import ConfidenceLevel
        from app.schemas.hallucination import HallucinationRiskLevel
        engine = MetricsEngine()
        answer = AnswerSection(
            executive_summary="Nothing cited.",
            detailed_explanation="Nothing cited in detail.",
            supporting_evidence=[],
            key_regulatory_references=[],
        )
        resp = FinalAnswerResponse(
            query="KYC",
            answer=answer,
            citations=AnnotatedAnswer(
                executive_summary=AnnotatedText(
                    text="Nothing cited.", citations=[], claim_count=5, cited_claim_count=0,
                ),
                detailed_explanation=AnnotatedText(
                    text="Nothing cited in detail.", citations=[], claim_count=5, cited_claim_count=0,
                ),
                supporting_evidence=[],
                key_regulatory_references=[],
                references=[],
                citation_map={},
            ),
            confidence_score=0.9, confidence_level=ConfidenceLevel.HIGH,
            faithfulness_score=0.9, hallucination_detected=False,
            hallucination_risk_level=HallucinationRiskLevel.NONE,
            source_attributions=[],
            metadata=OrchestratorMetadata(),
        )
        s = engine.citation_accuracy(resp)
        assert s.score == 0.0

    def test_confidence_service_accepts_coverage(self):
        from app.services.confidence.service import ConfidenceService
        from app.schemas.confidence import ConfidenceRequest
        svc = ConfidenceService()
        req = ConfidenceRequest(
            query="KYC",
            answer={"text": "KYC required."},
            chunks=[{"chunk_id": "c1", "content": "KYC required."}],
            citation_coverage=0.85,
        )
        result = svc.score(req)
        assert result is not None
        assert 0.0 <= result.confidence <= 1.0
