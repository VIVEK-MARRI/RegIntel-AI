"""Tests for Module 6.5 — Multi-Document Reasoning.

Coverage
--------
* Schemas (DiffItem, DocumentDiff, TimelineEvent, Timeline,
  RegulatoryChange, ChangeReport, Contradiction, ContradictionReport,
  CrossDocumentSummary, ReasoningRequest, ReasoningResponse).
* DocumentComparator — added/removed/changed/unchanged/contradicts.
* TimelineAnalyzer — date extraction, year-only fallback, categorisation.
* ChangeDetector — maps diffs to change types.
* ContradictionDetector — overlap gate, severity bucketing.
* CrossDocumentSummariser — query-relevant key points.
* ReasoningCoordinator — multi-mode orchestration.
* MultiDocumentReasoner — top-level service.
* API integration: /api/v1/reasoning/* endpoints.
"""

from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_multi_document_reasoner,
    reset_multi_document_reasoner,
)
from app.api.v1.reasoning import router as reasoning_router
from app.schemas.reasoning import (
    ChangeType,
    Contradiction,
    ContradictionSeverity,
    DiffItem,
    DiffType,
    ReasoningMode,
    ReasoningRequest,
    RegulatoryChange,
    TimelineEvent,
)
from app.services.reasoning import (
    ChangeDetector,
    ContradictionDetector,
    CrossDocumentSummariser,
    DocumentComparator,
    MultiDocumentReasoner,
    ReasoningCoordinator,
    TimelineAnalyzer,
    build_default_multi_document_reasoner,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_multi_document_reasoner()
    yield
    reset_multi_document_reasoner()


@pytest.fixture
def comparator() -> DocumentComparator:
    return DocumentComparator()


@pytest.fixture
def timeline_analyzer() -> TimelineAnalyzer:
    return TimelineAnalyzer()


@pytest.fixture
def change_detector() -> ChangeDetector:
    return ChangeDetector()


@pytest.fixture
def contradiction_detector() -> ContradictionDetector:
    return ContradictionDetector()


@pytest.fixture
def summariser() -> CrossDocumentSummariser:
    return CrossDocumentSummariser()


@pytest.fixture
def coordinator() -> ReasoningCoordinator:
    return ReasoningCoordinator()


@pytest.fixture
def reasoner() -> MultiDocumentReasoner:
    return build_default_multi_document_reasoner()


@pytest.fixture
def app():
    reset_multi_document_reasoner()
    app = FastAPI()
    app.include_router(reasoning_router, prefix="/api/v1")
    service = build_default_multi_document_reasoner()
    app.dependency_overrides[get_multi_document_reasoner] = lambda: service
    yield app
    app.dependency_overrides.clear()
    reset_multi_document_reasoner()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _chunk(cid, did, content, *, section="S1", title="Doc"):
    return {
        "chunk_id": cid,
        "document_id": did,
        "document_title": title,
        "section": section,
        "content": content,
        "score": 0.9,
    }


# ─── Schema tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_diff_types(self):
        assert DiffType.ADDED.value == "added"
        assert DiffType.REMOVED.value == "removed"
        assert DiffType.CHANGED.value == "changed"
        assert DiffType.UNCHANGED.value == "unchanged"
        assert DiffType.CONTRADICTS.value == "contradicts"

    def test_change_types(self):
        assert ChangeType.NEW.value == "new"
        assert ChangeType.AMENDED.value == "amended"
        assert ChangeType.REPEALED.value == "repealed"

    def test_contradiction_severities(self):
        assert ContradictionSeverity.LOW.value == "low"
        assert ContradictionSeverity.MEDIUM.value == "medium"
        assert ContradictionSeverity.HIGH.value == "high"

    def test_reasoning_modes(self):
        assert ReasoningMode.COMPARE.value == "compare"
        assert ReasoningMode.TIMELINE.value == "timeline"
        assert ReasoningMode.CHANGES.value == "changes"
        assert ReasoningMode.CONTRADICTIONS.value == "contradictions"
        assert ReasoningMode.CROSS_SUMMARY.value == "cross_summary"
        assert ReasoningMode.FULL.value == "full"

    def test_diff_item_defaults(self):
        d = DiffItem(diff_type=DiffType.ADDED)
        assert d.diff_id.startswith("diff-")
        assert d.severity == ContradictionSeverity.LOW

    def test_timeline_event_defaults(self):
        e = TimelineEvent(description="x", event_year=2023)
        assert e.event_id.startswith("evt-")
        assert e.category == "general"

    def test_regulatory_change_defaults(self):
        c = RegulatoryChange(change_type=ChangeType.NEW)
        assert c.change_id.startswith("chg-")
        assert c.significance == ContradictionSeverity.MEDIUM

    def test_contradiction_defaults(self):
        c = Contradiction(claim_a="x", source_a="a", claim_b="y", source_b="b")
        assert c.contradiction_id.startswith("ctr-")

    def test_reasoning_request_min_chunks(self):
        with pytest.raises(Exception):
            ReasoningRequest(
                query="x",
                chunks=[{"chunk_id": "1", "document_id": "d", "content": "c"}],
            )

    def test_reasoning_request_forbids_extra(self):
        with pytest.raises(Exception):
            ReasoningRequest(
                query="x",
                chunks=[
                    {"chunk_id": "1", "document_id": "d", "content": "c"},
                    {"chunk_id": "2", "document_id": "d", "content": "c"},
                ],
                bad="x",
            )


# ─── DocumentComparator tests ──────────────────────────────────────────────


class TestDocumentComparator:
    def test_changed_or_added_removed(self, comparator: DocumentComparator):
        a = [_chunk("a1", "docA", "KYC content here")]
        b = [_chunk("b1", "docB", "completely different topic entirely")]
        diff = comparator.compare(a, b, document_a_id="docA", document_b_id="docB")
        # Either CHANGED (low-similarity match) or REMOVED+ADDED
        # (no match) is acceptable depending on the threshold.
        types = [d.diff_type for d in diff.differences]
        assert DiffType.CHANGED in types or (
            DiffType.REMOVED in types and DiffType.ADDED in types
        )

    def test_added_when_b_has_no_match(self, comparator: DocumentComparator):
        # Two A chunks that both match to the SAME B chunk — second A
        # has no available match, second B has no available match.
        a = [
            _chunk("a1", "docA", "topic 1 content here"),
            _chunk("a2", "docA", "topic 2 content here"),
        ]
        b = [
            _chunk("b1", "docB", "topic 1 content here"),
            _chunk("b2", "docB", "totally unrelated material"),
        ]
        diff = comparator.compare(a, b, document_a_id="docA", document_b_id="docB")
        types = [d.diff_type for d in diff.differences]
        # At least one ADDED or CHANGED should appear.
        assert DiffType.ADDED in types or DiffType.CHANGED in types

    def test_unchanged(self, comparator: DocumentComparator):
        a = [_chunk("a1", "docA", "the KYC process requires ID verification")]
        b = [_chunk("b1", "docB", "the KYC process requires ID verification")]
        diff = comparator.compare(a, b, document_a_id="docA", document_b_id="docB")
        assert any(d.diff_type == DiffType.UNCHANGED for d in diff.differences)

    def test_changed(self, comparator: DocumentComparator):
        a = [
            _chunk(
                "a1",
                "docA",
                "KYC process requires Aadhaar and PAN for verification of identity",
            )
        ]
        b = [
            _chunk(
                "b1",
                "docB",
                "KYC process requires Aadhaar and voter ID for identity verification of customers",
            )
        ]
        diff = comparator.compare(a, b, document_a_id="docA", document_b_id="docB")
        # Either CHANGED (low-similarity match) or UNCHANGED (high-similarity)
        # depending on token overlap.
        types = [d.diff_type for d in diff.differences]
        assert DiffType.CHANGED in types or DiffType.UNCHANGED in types

    def test_contradicts_detected(self, comparator: DocumentComparator):
        a = [_chunk("a1", "docA", "Insider trading is prohibited by SEBI regulations.")]
        b = [
            _chunk(
                "b1", "docB", "Insider trading is permitted under the new SEBI rules."
            )
        ]
        diff = comparator.compare(a, b, document_a_id="docA", document_b_id="docB")
        assert any(d.diff_type == DiffType.CONTRADICTS for d in diff.differences)

    def test_summary(self, comparator: DocumentComparator):
        a = [_chunk("a1", "docA", "x")]
        b = [_chunk("b1", "docB", "y")]
        diff = comparator.compare(a, b)
        assert "added" in diff.summary.lower()
        assert "removed" in diff.summary.lower()


# ─── TimelineAnalyzer tests ────────────────────────────────────────────────


class TestTimelineAnalyzer:
    def test_extract_full_date(self, timeline_analyzer: TimelineAnalyzer):
        chunks = [
            _chunk("c1", "d1", "RBI issued a circular on 15/03/2023."),
            _chunk("c2", "d1", "SEBI issued a circular on 22-06-2022."),
        ]
        t = timeline_analyzer.analyze(chunks)
        assert len(t.events) == 2
        assert t.events[0].event_year == 2022
        assert t.events[1].event_year == 2023

    def test_extract_year_only(self, timeline_analyzer: TimelineAnalyzer):
        chunks = [_chunk("c1", "d1", "The master direction was issued in 2016.")]
        t = timeline_analyzer.analyze(chunks)
        assert len(t.events) == 1
        assert t.events[0].event_year == 2016

    def test_extract_month_name(self, timeline_analyzer: TimelineAnalyzer):
        chunks = [_chunk("c1", "d1", "On March 15, 2023 a new circular was issued.")]
        t = timeline_analyzer.analyze(chunks)
        assert len(t.events) == 1
        assert t.events[0].event_year == 2023
        assert t.events[0].event_date == date(2023, 3, 15)

    def test_no_date_skipped(self, timeline_analyzer: TimelineAnalyzer):
        chunks = [_chunk("c1", "d1", "Some text without any date.")]
        t = timeline_analyzer.analyze(chunks)
        assert t.events == []

    def test_categorisation(self, timeline_analyzer: TimelineAnalyzer):
        chunks = [_chunk("c1", "d1", "An amendment was made in 2023.")]
        t = timeline_analyzer.analyze(chunks)
        assert t.events[0].category == "amendment"

    def test_grouped_by_year(self, timeline_analyzer: TimelineAnalyzer):
        chunks = [
            _chunk("c1", "d1", "On 1/1/2022, the rule was made."),
            _chunk("c2", "d1", "On 1/1/2023, the rule was amended."),
            _chunk("c3", "d1", "On 1/1/2022, another rule was made."),
        ]
        t = timeline_analyzer.analyze(chunks)
        assert "2022" in t.grouped_by_period
        assert "2023" in t.grouped_by_period
        assert len(t.grouped_by_period["2022"]) == 2
        assert len(t.grouped_by_period["2023"]) == 1


# ─── ChangeDetector tests ──────────────────────────────────────────────────


class TestChangeDetector:
    def test_detect_new(self, change_detector: ChangeDetector):
        a: list = []
        b = [_chunk("b1", "docB", "Brand new regulation.")]
        report = change_detector.detect(a, b)
        assert any(c.change_type == ChangeType.NEW for c in report.changes)
        assert report.by_type.get(ChangeType.NEW, 0) >= 1

    def test_detect_repealed(self, change_detector: ChangeDetector):
        a = [_chunk("a1", "docA", "Old rule that is no longer valid.")]
        b: list = []
        report = change_detector.detect(a, b)
        assert any(c.change_type == ChangeType.REPEALED for c in report.changes)

    def test_detect_amended_or_new(self, change_detector: ChangeDetector):
        a = [
            _chunk(
                "a1",
                "docA",
                "KYC requires identity verification for onboarding of new customers only.",
            )
        ]
        b = [
            _chunk(
                "b1",
                "docB",
                "KYC requires identity verification plus address proof plus annual review for all existing customers.",
            )
        ]
        report = change_detector.detect(a, b)
        # Either AMENDED (low-similarity match) or NEW (no match) is fine.
        types = [c.change_type for c in report.changes]
        assert ChangeType.AMENDED in types or ChangeType.NEW in types


# ─── ContradictionDetector tests ──────────────────────────────────────────


class TestContradictionDetector:
    def test_detect_shall_vs_shall_not(
        self, contradiction_detector: ContradictionDetector
    ):
        chunks = [
            _chunk("c1", "d1", "Banks shall maintain KYC records for 5 years."),
            _chunk("c2", "d2", "Banks shall not maintain KYC records."),
        ]
        report = contradiction_detector.detect(chunks)
        assert len(report.contradictions) >= 1
        assert report.contradictions[0].severity in (
            ContradictionSeverity.MEDIUM,
            ContradictionSeverity.HIGH,
        )

    def test_skip_within_document(self, contradiction_detector: ContradictionDetector):
        chunks = [
            _chunk("c1", "d1", "Banks shall maintain records."),
            _chunk("c2", "d1", "Banks shall not maintain records."),
        ]
        report = contradiction_detector.detect(chunks)
        assert report.contradictions == []

    def test_no_contradiction_for_aligned(
        self, contradiction_detector: ContradictionDetector
    ):
        chunks = [
            _chunk("c1", "d1", "Banks must verify customer identity."),
            _chunk(
                "c2", "d2", "Customer identity verification is required for all banks."
            ),
        ]
        report = contradiction_detector.detect(chunks)
        # Same direction → no contradiction flagged.
        assert report.contradictions == []


# ─── CrossDocumentSummariser tests ────────────────────────────────────────


class TestCrossDocumentSummariser:
    def test_summarise(self, summariser: CrossDocumentSummariser):
        chunks = [
            _chunk("c1", "d1", "KYC is required for all banks operating in India."),
            _chunk(
                "c2", "d2", "SEBI also requires KYC for capital market participants."
            ),
        ]
        s = summariser.summarise("KYC requirements", chunks)
        assert s.topic == "KYC requirements"
        assert "d1" in s.document_ids
        assert "d2" in s.document_ids
        assert len(s.key_points) >= 1
        assert len(s.summary_text) > 0


# ─── ReasoningCoordinator tests ────────────────────────────────────────────


class TestReasoningCoordinator:
    def test_full_mode(self, coordinator: ReasoningCoordinator):
        chunks = [
            _chunk("c1", "d1", "RBI circular on KYC was issued on 1/1/2023."),
            _chunk("c2", "d2", "SEBI circular on KYC was issued on 1/1/2022."),
        ]
        req = ReasoningRequest(query="KYC", chunks=chunks, mode=ReasoningMode.FULL)
        resp = coordinator.run(req)
        assert resp.timeline is not None
        assert resp.cross_summary is not None
        assert len(resp.timeline.events) >= 2

    def test_compare_mode(self, coordinator: ReasoningCoordinator):
        chunks = [
            _chunk("c1", "d1", "Rule A."),
            _chunk("c2", "d2", "Rule B."),
        ]
        req = ReasoningRequest(query="x", chunks=chunks, mode=ReasoningMode.COMPARE)
        resp = coordinator.run(req)
        assert resp.diff is not None

    def test_changes_mode(self, coordinator: ReasoningCoordinator):
        chunks = [
            _chunk("c1", "d1", "Old rule."),
            _chunk("c2", "d2", "New rule."),
        ]
        req = ReasoningRequest(query="x", chunks=chunks, mode=ReasoningMode.CHANGES)
        resp = coordinator.run(req)
        assert resp.changes is not None
        assert len(resp.changes.changes) >= 1


# ─── MultiDocumentReasoner tests ──────────────────────────────────────────


class TestMultiDocumentReasoner:
    def test_default_factory(self):
        r = build_default_multi_document_reasoner()
        assert isinstance(r, MultiDocumentReasoner)
        assert isinstance(r.comparator, DocumentComparator)
        assert isinstance(r._timeline, TimelineAnalyzer)
        assert isinstance(r._changes, ChangeDetector)
        # Internal: _contradictions is the detector instance.
        assert isinstance(r._contradictions, ContradictionDetector)
        assert isinstance(r.summariser, CrossDocumentSummariser)

    def test_compare_convenience(self, reasoner: MultiDocumentReasoner):
        chunks = [_chunk("c1", "d1", "x"), _chunk("c2", "d2", "y")]
        resp = reasoner.compare("test", chunks)
        assert resp.mode == ReasoningMode.COMPARE

    def test_timeline_convenience(self, reasoner: MultiDocumentReasoner):
        chunks = [
            _chunk("c1", "d1", "In 2023 a rule was made."),
            _chunk("c2", "d2", "In 2024 another rule was made."),
        ]
        resp = reasoner.timeline("test", chunks)
        assert resp.timeline is not None
        assert len(resp.timeline.events) == 2


# ─── API integration tests ─────────────────────────────────────────────────


class TestAPI:
    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient):
        r = await client.get("/api/v1/reasoning/health")
        assert r.status_code == 200
        assert r.json()["module"] == "reasoning"

    @pytest.mark.asyncio
    async def test_compare_endpoint(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/reasoning/compare",
            json={
                "query": "Compare KYC",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": "d1",
                        "content": "KYC requires ID",
                        "score": 0.9,
                    },
                    {
                        "chunk_id": "c2",
                        "document_id": "d2",
                        "content": "KYC requires ID",
                        "score": 0.9,
                    },
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "compare"
        assert body["diff"] is not None

    @pytest.mark.asyncio
    async def test_timeline_endpoint(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/reasoning/timeline",
            json={
                "query": "Timeline",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": "d1",
                        "content": "In 2023 a rule was made.",
                        "score": 0.9,
                    },
                    {
                        "chunk_id": "c2",
                        "document_id": "d1",
                        "content": "In 2024 another rule was made.",
                        "score": 0.9,
                    },
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["timeline"] is not None
        assert len(body["timeline"]["events"]) == 2

    @pytest.mark.asyncio
    async def test_changes_endpoint(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/reasoning/changes",
            json={
                "query": "What changed?",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": "d1",
                        "content": "Old rule",
                        "score": 0.9,
                    },
                    {
                        "chunk_id": "c2",
                        "document_id": "d2",
                        "content": "New rule",
                        "score": 0.9,
                    },
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["changes"] is not None

    @pytest.mark.asyncio
    async def test_contradictions_endpoint(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/reasoning/contradictions",
            json={
                "query": "find conflicts",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": "d1",
                        "content": "Banks shall maintain records.",
                        "score": 0.9,
                    },
                    {
                        "chunk_id": "c2",
                        "document_id": "d2",
                        "content": "Banks shall not maintain records.",
                        "score": 0.9,
                    },
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["contradictions"] is not None
        assert len(body["contradictions"]["contradictions"]) >= 1

    @pytest.mark.asyncio
    async def test_cross_summary_endpoint(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/reasoning/cross-summary",
            json={
                "query": "KYC",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": "d1",
                        "content": "KYC is mandatory for all banks.",
                        "score": 0.9,
                    },
                    {
                        "chunk_id": "c2",
                        "document_id": "d2",
                        "content": "SEBI also mandates KYC for brokers.",
                        "score": 0.9,
                    },
                ],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["cross_summary"] is not None

    @pytest.mark.asyncio
    async def test_run_endpoint(self, client: AsyncClient):
        r = await client.post(
            "/api/v1/reasoning/run",
            json={
                "query": "KYC",
                "chunks": [
                    {
                        "chunk_id": "c1",
                        "document_id": "d1",
                        "content": "KYC in 2023",
                        "score": 0.9,
                    },
                    {
                        "chunk_id": "c2",
                        "document_id": "d2",
                        "content": "KYC in 2024",
                        "score": 0.9,
                    },
                ],
                "mode": "full",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["timeline"] is not None
        assert body["cross_summary"] is not None
