"""Tests for Module 7.3 — Regulatory Change Detection Engine."""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import List

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_change_detection_service,
    reset_change_detection_service,
)
from app.main import app
from app.schemas.change import (
    ChangeCategory,
    ChangeDetectionRequest,
    ChangeFilter,
    ChangeSeverity,
    ChangeType,
    ClauseChange,
    DocumentDiff,
    SectionRef,
)
from app.services.change_detection import (
    ChangeClassifier,
    ChangeDetectionService,
    ChangeRepository,
    ChangeStore,
    ClauseComparator,
    DocumentDiffEngine,
    InMemoryChangeStore,
    VersionComparator,
    _classify_category,
    _classify_severity,
    _generate_summary,
    _overall_category,
    _overall_severity,
    _rationale,
    _split_clauses,
    _split_sections,
    _token_overlap,
    _tokenise,
    build_default_change_detection_service,
)
from app.services.observability import (
    reset_change_detection_metrics,
)


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_change_detection_service()
    reset_change_detection_metrics()
    yield
    reset_change_detection_service()
    reset_change_detection_metrics()


@pytest.fixture
def tmp_store(tmp_path):
    """Return an InMemoryChangeStore that persists to a tmp JSONL file."""
    persist = tmp_path / "diffs.jsonl"
    return InMemoryChangeStore(persist_path=persist)


@pytest.fixture
def service(tmp_store: ChangeStore) -> ChangeDetectionService:
    return ChangeDetectionService(store=tmp_store)


# ─── Token / overlap helpers ───────────────────────────────────────────


def test_tokenise_basic():
    toks = _tokenise("Hello, World! Hello.")
    assert toks == ["hello", "world", "hello"]


def test_token_overlap_jaccard():
    assert _token_overlap(["a", "b", "c"], ["a", "b", "c"]) == 1.0
    assert _token_overlap(["a", "b"], ["c", "d"]) == 0.0
    overlap = _token_overlap(["a", "b", "c"], ["b", "c", "d"])
    assert 0.0 < overlap < 1.0


# ─── Section / clause splitting ───────────────────────────────────────


def test_split_sections_numbered():
    text = (
        "1. Introduction\nThis is the intro.\n\n"
        "2. Definitions\nA term means a word.\n\n"
        "3. Compliance\nFollow the rules."
    )
    secs = _split_sections(text)
    assert [s[0] for s in secs] == [
        "1. Introduction",
        "2. Definitions",
        "3. Compliance",
    ]
    assert "This is the intro" in secs[0][1]
    assert "Follow the rules" in secs[2][1]


def test_split_sections_chapter_and_article():
    text = (
        "Chapter 1 — General Provisions\nbody A\n\n"
        "Article 5 — Duties\nbody B\n\n"
        "Section 12 — Penalties\nbody C"
    )
    secs = _split_sections(text)
    headers = [s[0] for s in secs]
    assert any("Chapter 1" in h for h in headers)
    assert any("Article 5" in h for h in headers)
    assert any("Section 12" in h for h in headers)


def test_split_clauses_basic():
    text = "First sentence. Second sentence. Third one too."
    clauses = _split_clauses(text)
    assert len(clauses) >= 2
    assert "First sentence" in clauses[0]


def test_split_clauses_lettered():
    text = "\n".join(
        [
            "(a) First clause.",
            "(b) Second clause.",
            "(c) Third clause.",
        ]
    )
    clauses = _split_clauses(text)
    assert len(clauses) == 3
    assert "First" in clauses[0]
    assert "Third" in clauses[2]


# ─── Severity / category classification ───────────────────────────────


def test_classify_severity_added_with_high_keywords():
    text = "The licensee shall not violate this clause; penalty applies."
    sev = _classify_severity(text, ChangeType.ADDED)
    assert sev in (ChangeSeverity.HIGH, ChangeSeverity.CRITICAL)


def test_classify_severity_removed_with_high_keywords():
    text = "Mandatory disclosure requirements are revoked."
    sev = _classify_severity(text, ChangeType.REMOVED)
    assert sev in (ChangeSeverity.HIGH, ChangeSeverity.CRITICAL)


def test_classify_severity_modified_mild():
    text = "Clarified the format of the report."
    sev = _classify_severity(text, ChangeType.MODIFIED)
    assert sev in (ChangeSeverity.LOW, ChangeSeverity.MEDIUM)


def test_classify_severity_unchanged():
    assert _classify_severity("foo", ChangeType.UNCHANGED) == ChangeSeverity.LOW


def test_classify_category_penalty():
    cat = _classify_category("A new penalty of INR 10,000 is imposed.")
    assert cat == ChangeCategory.PENALTY_CHANGE


def test_classify_category_deadline():
    cat = _classify_category("Compliance deadline is 30 days from notice.")
    assert cat == ChangeCategory.COMPLIANCE_DEADLINE


def test_classify_category_other():
    cat = _classify_category("Definitions updated for consistency.")
    assert cat == ChangeCategory.OTHER


def test_classify_category_clarification():
    cat = _classify_category("This is a clarification of the previous wording.")
    assert cat == ChangeCategory.CLARIFICATION


def test_rationale_includes_keyword():
    r = _rationale(
        ChangeType.ADDED,
        ChangeSeverity.HIGH,
        "",
        "Mandatory disclosure shall apply.",
    )
    assert "mandatory" in r.lower() or "shall" in r.lower() or "high" in r.lower()


# ─── Overall severity / category aggregation ─────────────────────────


def test_overall_severity_takes_max():
    from app.schemas.change import ClauseChange

    changes = [
        ClauseChange(
            change_type=ChangeType.MODIFIED,
            location=SectionRef(section="1"),
            severity=ChangeSeverity.LOW,
            category=ChangeCategory.OTHER,
        ),
        ClauseChange(
            change_type=ChangeType.ADDED,
            location=SectionRef(section="2"),
            severity=ChangeSeverity.CRITICAL,
            category=ChangeCategory.PENALTY_CHANGE,
        ),
    ]
    assert _overall_severity(changes) == ChangeSeverity.CRITICAL


def test_overall_category_takes_max_count():
    from app.schemas.change import ClauseChange

    changes = [
        ClauseChange(
            change_type=ChangeType.MODIFIED,
            location=SectionRef(section="1"),
            severity=ChangeSeverity.MEDIUM,
            category=ChangeCategory.POLICY_UPDATE,
        ),
        ClauseChange(
            change_type=ChangeType.MODIFIED,
            location=SectionRef(section="1"),
            severity=ChangeSeverity.MEDIUM,
            category=ChangeCategory.POLICY_UPDATE,
        ),
        ClauseChange(
            change_type=ChangeType.ADDED,
            location=SectionRef(section="2"),
            severity=ChangeSeverity.HIGH,
            category=ChangeCategory.PENALTY_CHANGE,
        ),
    ]
    assert _overall_category(changes) == ChangeCategory.POLICY_UPDATE


def test_generate_summary_text():
    from app.schemas.change import ClauseChange, DocumentDiff

    changes = [
        ClauseChange(
            change_type=ChangeType.ADDED,
            location=SectionRef(section="1"),
            severity=ChangeSeverity.HIGH,
            category=ChangeCategory.PENALTY_CHANGE,
        ),
        ClauseChange(
            change_type=ChangeType.REMOVED,
            location=SectionRef(section="2"),
            severity=ChangeSeverity.MEDIUM,
            category=ChangeCategory.POLICY_UPDATE,
        ),
    ]
    diff = DocumentDiff(
        document_id="d1",
        old_version="1.0",
        new_version="2.0",
        added_count=1,
        removed_count=1,
        modified_count=0,
        unchanged_count=0,
        overall_severity=ChangeSeverity.HIGH,
        overall_category=ChangeCategory.PENALTY_CHANGE,
    )
    diff.changes = changes
    s = _generate_summary(diff)
    assert "1 addition" in s
    assert "1 removal" in s
    assert "high" in s.lower()


# ─── VersionComparator ────────────────────────────────────────────────


def test_version_comparator_equal_texts():
    text = "The licensee shall comply with all applicable rules."
    pairs = VersionComparator().compare_texts(text, text)
    assert pairs == [] or all(p.change_type == ChangeType.UNCHANGED for p in pairs)


def test_version_comparator_detects_addition():
    old = "The licensee shall file quarterly returns."
    new = old + " A new penalty of INR 5,000 shall apply for late filings."
    pairs = VersionComparator().compare_texts(old, new)
    assert any(p.change_type == ChangeType.ADDED for p in pairs)


def test_version_comparator_detects_removal():
    old = "Mandatory disclosure required. A penalty of INR 1,000 applies."
    new = "Disclosure required."
    pairs = VersionComparator().compare_texts(old, new)
    assert any(p.change_type == ChangeType.REMOVED for p in pairs)


def test_version_comparator_detects_modification():
    old = "The deadline is 30 days."
    new = "The deadline is 60 days."
    pairs = VersionComparator().compare_texts(old, new)
    assert any(
        p.change_type in (ChangeType.MODIFIED, ChangeType.REMOVED, ChangeType.ADDED)
        for p in pairs
    )


# ─── ClauseComparator ─────────────────────────────────────────────────


def test_clause_comparator_added_section():
    old_secs = [{"section": "1. Intro", "text": "A."}]
    new_secs = [
        {"section": "1. Intro", "text": "A."},
        {"section": "2. New", "text": "B."},
    ]
    diffs = ClauseComparator().compare_sections(old_secs, new_secs)
    added = [d for d in diffs if d.change_type == ChangeType.ADDED]
    assert any("2. New" in (d.location.section or "") for d in added)


def test_clause_comparator_removed_section():
    old_secs = [
        {"section": "1. Intro", "text": "A."},
        {"section": "2. Old", "text": "B."},
    ]
    new_secs = [{"section": "1. Intro", "text": "A."}]
    diffs = ClauseComparator().compare_sections(old_secs, new_secs)
    removed = [d for d in diffs if d.change_type == ChangeType.REMOVED]
    assert any("2. Old" in (d.location.section or "") for d in removed)


def test_clause_comparator_modified_clause_within_section():
    old_secs = [
        {
            "section": "1. Duties",
            "text": "\n".join(
                ["(a) Comply with rules.", "(b) Submit reports quarterly."]
            ),
        }
    ]
    new_secs = [
        {
            "section": "1. Duties",
            "text": "\n".join(
                ["(a) Comply with rules.", "(b) Submit reports monthly."]
            ),
        }
    ]
    diffs = ClauseComparator().compare_sections(old_secs, new_secs)
    assert any(
        d.change_type in (ChangeType.MODIFIED, ChangeType.REMOVED, ChangeType.ADDED)
        for d in diffs
    )


# ─── ChangeClassifier ─────────────────────────────────────────────────


def test_change_classifier_unchanged_shortcut():
    from app.services.change_detection import _ClausePair

    p = _ClausePair(
        old_text="x",
        new_text="x",
        location=SectionRef(section="1"),
        change_type=ChangeType.UNCHANGED,
        similarity=1.0,
    )
    out = ChangeClassifier().classify(p)
    assert out.severity == ChangeSeverity.LOW


def test_change_classifier_severity_floor_penalty_change():
    from app.services.change_detection import _ClausePair

    p = _ClausePair(
        old_text=None,
        new_text="A new penalty of INR 5,000 shall apply.",
        location=SectionRef(section="1"),
        change_type=ChangeType.ADDED,
        similarity=0.0,
    )
    out = ChangeClassifier().classify(p)
    assert out.severity in (ChangeSeverity.MEDIUM, ChangeSeverity.HIGH, ChangeSeverity.CRITICAL)
    assert out.category == ChangeCategory.PENALTY_CHANGE


def test_change_classifier_assigns_rationale():
    from app.services.change_detection import _ClausePair

    p = _ClausePair(
        old_text=None,
        new_text="Mandatory penalty clause added.",
        location=SectionRef(section="1"),
        change_type=ChangeType.ADDED,
        similarity=0.0,
    )
    out = ChangeClassifier().classify(p)
    assert out.rationale is not None
    assert out.rationale != ""


# ─── DocumentDiffEngine ───────────────────────────────────────────────


def test_diff_engine_text_only_no_changes():
    text = "Identical text."
    req = ChangeDetectionRequest(
        old_text=text, new_text=text, old_version="1.0", new_version="1.0"
    )
    diff = DocumentDiffEngine().detect(req)
    assert all(
        c.change_type == ChangeType.UNCHANGED for c in diff.changes
    ) or diff.changes == []


def test_diff_engine_text_only_with_changes():
    req = ChangeDetectionRequest(
        old_text="Old rule.",
        new_text="New mandatory penalty of INR 5,000 applies.",
        old_version="1.0",
        new_version="2.0",
    )
    diff = DocumentDiffEngine().detect(req)
    assert any(
        c.change_type in (ChangeType.ADDED, ChangeType.MODIFIED)
        and c.severity
        in (ChangeSeverity.MEDIUM, ChangeSeverity.HIGH, ChangeSeverity.CRITICAL)
        for c in diff.changes
    )
    assert diff.overall_severity in (
        ChangeSeverity.MEDIUM,
        ChangeSeverity.HIGH,
        ChangeSeverity.CRITICAL,
    )
    assert diff.duration_ms >= 0


def test_diff_engine_sections_input():
    req = ChangeDetectionRequest(
        old_sections=[
            {"section": "1. Intro", "text": "Original body."},
        ],
        new_sections=[
            {"section": "1. Intro", "text": "Original body."},
            {"section": "2. New", "text": "New section about penalty."},
        ],
        old_version="1.0",
        new_version="2.0",
    )
    diff = DocumentDiffEngine().detect(req)
    assert any(c.change_type == ChangeType.ADDED for c in diff.changes)


def test_diff_engine_summary_populated():
    req = ChangeDetectionRequest(
        old_text="The old rule says X.",
        new_text="The new rule says X and adds a penalty of INR 1,000.",
        old_version="1.0",
        new_version="2.0",
    )
    diff = DocumentDiffEngine().detect(req)
    assert diff.summary is not None and diff.summary != ""


def test_diff_engine_records_metrics():
    from app.services.observability import get_change_detection_metrics

    reset_change_detection_metrics()
    req = ChangeDetectionRequest(
        old_text="A",
        new_text="A. New mandatory penalty applies.",
        old_version="1.0",
        new_version="2.0",
    )
    DocumentDiffEngine().detect(req)
    snap = get_change_detection_metrics().snapshot()
    assert snap["diffs_computed"] >= 1


# ─── Store + Repository ───────────────────────────────────────────────


def test_store_persists_to_jsonl(tmp_path):
    from pathlib import Path

    p = Path(tmp_path) / "diffs.jsonl"
    s1 = InMemoryChangeStore(persist_path=p)
    diff = DocumentDiff(
        document_id="doc-1",
        old_version="1.0",
        new_version="2.0",
        added_count=1,
        removed_count=0,
        modified_count=0,
        unchanged_count=0,
        overall_severity=ChangeSeverity.HIGH,
        overall_category=ChangeCategory.PENALTY_CHANGE,
        summary="added 1 high penalty",
                duration_ms=2.0,
    )
    s1.add_diff(diff)
    s2 = InMemoryChangeStore(persist_path=p)
    out = s2.get_diff(diff.diff_id)
    assert out is not None
    assert out.document_id == "doc-1"


def test_store_get_missing_returns_none(tmp_store):
    assert tmp_store.get_diff("nope") is None


def test_store_list_empty(tmp_store):
    assert tmp_store.list_diffs() == []


def test_store_reset_clears_memory(tmp_store):
    diff = DocumentDiff(
        document_id="x",
        old_version="1",
        new_version="2",
        added_count=0,
        removed_count=0,
        modified_count=0,
        unchanged_count=0,
        overall_severity=ChangeSeverity.LOW,
        overall_category=ChangeCategory.OTHER,
        summary="",
                duration_ms=0.0,
    )
    tmp_store.add_diff(diff)
    assert len(tmp_store.list_diffs()) == 1
    tmp_store.reset()
    assert tmp_store.list_diffs() == []


def test_repository_search_pagination(tmp_store):
    from app.services.change_detection import ChangeRepository

    repo = ChangeRepository(tmp_store)
    for i in range(5):
        d = DocumentDiff(
            document_id=f"d{i}",
            old_version="1.0",
            new_version="2.0",
            added_count=0,
            removed_count=0,
            modified_count=1,
            unchanged_count=0,
            overall_severity=ChangeSeverity.MEDIUM,
            overall_category=ChangeCategory.POLICY_UPDATE,
            summary="mod",
            computed_at=float(i),
            duration_ms=1.0,
        )
        tmp_store.add_diff(d)
    page1 = repo.search(ChangeFilter(page=1, page_size=2))
    assert page1.page == 1
    assert page1.page_size == 2
    assert page1.total >= 5
    assert page1.has_more is True
    assert len(page1.items) == 2


def test_repository_search_filter_by_severity(tmp_store):
    from app.services.change_detection import ChangeRepository

    repo = ChangeRepository(tmp_store)
    for sev in [ChangeSeverity.LOW, ChangeSeverity.CRITICAL, ChangeSeverity.LOW]:
        d = DocumentDiff(
            document_id="x",
            old_version="1.0",
            new_version="2.0",
            added_count=0,
            removed_count=0,
            modified_count=1,
            unchanged_count=0,
            overall_severity=sev,
            overall_category=ChangeCategory.OTHER,
            summary="",
                        duration_ms=0.0,
        )
        tmp_store.add_diff(d)
    res = repo.search(ChangeFilter(min_severity=ChangeSeverity.CRITICAL))
    assert all(d.overall_severity == ChangeSeverity.CRITICAL for d in res.items)


def test_repository_search_filter_by_category(tmp_store):
    from app.services.change_detection import ChangeRepository

    repo = ChangeRepository(tmp_store)
    for cat in [ChangeCategory.PENALTY_CHANGE, ChangeCategory.OTHER]:
        d = DocumentDiff(
            document_id="x",
            old_version="1.0",
            new_version="2.0",
            added_count=0,
            removed_count=0,
            modified_count=1,
            unchanged_count=0,
            overall_severity=ChangeSeverity.MEDIUM,
            overall_category=cat,
            summary="",
                        duration_ms=0.0,
        )
        tmp_store.add_diff(d)
    res = repo.search(ChangeFilter(category=ChangeCategory.PENALTY_CHANGE))
    assert all(d.overall_category == ChangeCategory.PENALTY_CHANGE for d in res.items)


def test_repository_stats(tmp_store):
    from app.services.change_detection import ChangeRepository

    repo = ChangeRepository(tmp_store)
    for sev in [ChangeSeverity.LOW, ChangeSeverity.HIGH, ChangeSeverity.CRITICAL]:
        d = DocumentDiff(
            document_id="x",
            old_version="1.0",
            new_version="2.0",
            added_count=1 if sev == ChangeSeverity.CRITICAL else 0,
            removed_count=0,
            modified_count=1,
            unchanged_count=0,
            overall_severity=sev,
            overall_category=ChangeCategory.OTHER,
            summary="",
            duration_ms=0.0,
        )
        tmp_store.add_diff(d)
    s = repo.stats()
    assert s.total_diffs == 3
    assert s.by_severity.get(ChangeSeverity.LOW) == 1
    assert s.by_severity.get(ChangeSeverity.HIGH) == 1
    assert s.by_severity.get(ChangeSeverity.CRITICAL) == 1


def test_repository_filter_validates_page():
    from app.services.change_detection import ChangeRepository

    repo = ChangeRepository(InMemoryChangeStore())
    with pytest.raises(Exception):
        ChangeFilter(page=0)


# ─── ChangeDetectionService ──────────────────────────────────────────


def test_service_detect_rejects_empty(tmp_store):
    from app.schemas.change import ChangeDetectionRequest

    svc = ChangeDetectionService(store=tmp_store)
    req = ChangeDetectionRequest(old_text=None, new_text=None, old_version="1.0", new_version="2.0")
    with pytest.raises(ValueError):
        svc.detect(req)


def test_service_detect_returns_result(service):
    req = ChangeDetectionRequest(
        old_text="Old text. No penalty here.",
        new_text="New text. Mandatory penalty of INR 1,000 applies.",
        old_version="1.0",
        new_version="2.0",
    )
    result = service.detect(req)
    assert hasattr(result, "diff")
    assert result.has_changes is True


def test_service_get_stored(service):
    req = ChangeDetectionRequest(
        old_text="A",
        new_text="B. New mandatory penalty.",
        old_version="1.0",
        new_version="2.0",
    )
    result = service.detect(req)
    fetched = service.get(result.diff.diff_id)
    assert fetched is not None
    assert fetched.diff_id == result.diff.diff_id


def test_service_get_missing(service):
    assert service.get("nope") is None


def test_service_search(service):
    req = ChangeDetectionRequest(
        old_text="A", new_text="B. New penalty.", old_version="1.0", new_version="2.0"
    )
    service.detect(req)
    res = service.search(ChangeFilter(page=1))
    assert res.total >= 1


def test_service_stats(service):
    req = ChangeDetectionRequest(
        old_text="A", new_text="B. New penalty.", old_version="1.0", new_version="2.0"
    )
    service.detect(req)
    s = service.stats()
    assert s.total_diffs >= 1


def test_build_default_service_uses_persistent_store(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    svc = build_default_change_detection_service()
    assert isinstance(svc, ChangeDetectionService)
    assert svc.store is not None


# ─── API integration ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/changes/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["module"] == "change_detection"


@pytest.mark.asyncio
async def test_api_detect_success(tmp_store):
    app.dependency_overrides[get_change_detection_service] = lambda: ChangeDetectionService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/changes/detect",
                json={
                    "old_text": "Old clause.",
                    "new_text": "New clause with mandatory penalty.",
                    "old_version": "1.0",
                    "new_version": "2.0",
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert "diff" in body
            assert body["has_changes"] is True
    finally:
        app.dependency_overrides.pop(get_change_detection_service, None)


@pytest.mark.asyncio
async def test_api_detect_validation_error(tmp_store):
    app.dependency_overrides[get_change_detection_service] = lambda: ChangeDetectionService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/changes/detect",
                json={"old_version": "1.0", "new_version": "2.0"},
            )
            assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(get_change_detection_service, None)


@pytest.mark.asyncio
async def test_api_list_diffs(tmp_store):
    svc = ChangeDetectionService(store=tmp_store)
    svc.detect(
        ChangeDetectionRequest(
            old_text="A", new_text="B. Penalty.", old_version="1.0", new_version="2.0"
        )
    )
    app.dependency_overrides[get_change_detection_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/changes?page=1&page_size=10")
            assert r.status_code == 200
            body = r.json()
            assert "items" in body
            assert body["total"] >= 1
    finally:
        app.dependency_overrides.pop(get_change_detection_service, None)


@pytest.mark.asyncio
async def test_api_get_diff_404(tmp_store):
    app.dependency_overrides[get_change_detection_service] = lambda: ChangeDetectionService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/changes/nope")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_change_detection_service, None)


@pytest.mark.asyncio
async def test_api_stats(tmp_store):
    app.dependency_overrides[get_change_detection_service] = lambda: ChangeDetectionService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/changes/stats")
            assert r.status_code == 200
            body = r.json()
            assert "total_diffs" in body
    finally:
        app.dependency_overrides.pop(get_change_detection_service, None)
