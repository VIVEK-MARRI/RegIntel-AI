"""Tests for Module 7.4 — Regulatory Impact Analysis Engine."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import (
    get_impact_analysis_service,
    reset_impact_analysis_service,
)
from app.main import app
from app.schemas.change import (
    ChangeCategory,
    ChangeDetectionRequest,
    ChangeSeverity,
    ChangeType,
    ClauseChange,
    DocumentDiff,
    SectionRef,
)
from app.schemas.impact import (
    ActionPriority,
    AffectedEntity,
    BusinessImpact,
    ComplianceImpact,
    ExecutiveSummary,
    ImpactAnalysisRequest,
    ImpactAnalysisResult,
    ImpactAnalysisStats,
    ImpactDimension,
    ImpactFilter,
    ImpactLevel,
    ImpactReport,
    RequiredAction,
)
from app.services.impact_analysis import (
    AffectedEntityAnalyzer,
    ImpactAnalysisService,
    ImpactAnalysisRepository,
    ImpactReportStore,
    ImpactScorer,
    InMemoryImpactStore,
    RegulatorySummaryGenerator,
    _action_for_category,
    _business_impacts_for,
    _compliance_impact_for,
    _priority_for_severity,
    build_default_impact_analysis_service,
)
from app.services.observability import reset_impact_analysis_metrics


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_impact_analysis_service()
    reset_impact_analysis_metrics()
    yield
    reset_impact_analysis_service()
    reset_impact_analysis_metrics()


@pytest.fixture
def tmp_store(tmp_path):
    return InMemoryImpactStore(persist_path=Path(tmp_path) / "impact.jsonl")


@pytest.fixture
def service(tmp_store):
    return ImpactAnalysisService(store=tmp_store)


def _make_diff(
    *,
    severity: ChangeSeverity = ChangeSeverity.HIGH,
    category: ChangeCategory = ChangeCategory.PENALTY_CHANGE,
    change_type: ChangeType = ChangeType.ADDED,
    before_text: str = "",
    after_text: str = "Mandatory penalty of INR 5,000 applies.",
) -> DocumentDiff:
    return DocumentDiff(
        document_id="doc-1",
        old_version="1.0",
        new_version="2.0",
        overall_severity=severity,
        overall_category=category,
        summary="change",
        changes=[
            ClauseChange(
                change_type=change_type,
                location=SectionRef(section="1"),
                old_text=before_text,
                new_text=after_text,
                severity=severity,
                category=category,
            )
        ],
    )


# ─── Scoring ──────────────────────────────────────────────────────────


def test_impact_scorer_critical():
    score, level = ImpactScorer().score(
        severity=ChangeSeverity.CRITICAL,
        category=ChangeCategory.PENALTY_CHANGE,
        change_type=ChangeType.ADDED,
        change_count=5,
    )
    assert level == ImpactLevel.CRITICAL
    assert score >= 0.85


def test_impact_scorer_low():
    score, level = ImpactScorer().score(
        severity=ChangeSeverity.LOW,
        category=ChangeCategory.CLARIFICATION,
        change_type=ChangeType.MODIFIED,
        change_count=1,
    )
    assert level in (ImpactLevel.NEGLIGIBLE, ImpactLevel.LOW)
    assert score <= 0.35


def test_impact_scorer_to_level_thresholds():
    s = ImpactScorer()
    assert s._to_level(0.0) == ImpactLevel.NEGLIGIBLE
    assert s._to_level(0.25) == ImpactLevel.LOW
    assert s._to_level(0.55) == ImpactLevel.MEDIUM
    assert s._to_level(0.7) == ImpactLevel.HIGH
    assert s._to_level(0.9) == ImpactLevel.CRITICAL


# ─── AffectedEntityAnalyzer ──────────────────────────────────────────


def test_entity_analyzer_detects_bank():
    changes = [
        ClauseChange(
            change_type=ChangeType.ADDED,
            location=SectionRef(section="1"),
            new_text="All scheduled banks must comply.",
            severity=ChangeSeverity.HIGH,
            category=ChangeCategory.POLICY_UPDATE,
        )
    ]
    entities = AffectedEntityAnalyzer().analyze(changes)
    bank = next((e for e in entities if e.entity_type.value == "bank"), None)
    assert bank is not None
    assert bank.exposure_score > 0


def test_entity_analyzer_detects_nbfc():
    changes = [
        ClauseChange(
            change_type=ChangeType.ADDED,
            location=SectionRef(section="1"),
            new_text="NBFC and HFC entities must report quarterly.",
            severity=ChangeSeverity.HIGH,
            category=ChangeCategory.REPORTING_REQUIREMENT,
        )
    ]
    entities = AffectedEntityAnalyzer().analyze(changes)
    types = {e.entity_type.value for e in entities}
    assert "nbfc" in types


def test_entity_analyzer_fallback_other():
    changes = [
        ClauseChange(
            change_type=ChangeType.MODIFIED,
            location=SectionRef(section="1"),
            new_text="Generic update.",
            severity=ChangeSeverity.LOW,
            category=ChangeCategory.OTHER,
        )
    ]
    entities = AffectedEntityAnalyzer().analyze(changes)
    assert any(e.entity_type.value == "other" for e in entities)


# ─── Priority / Action generation ────────────────────────────────────


def test_priority_for_severity():
    assert _priority_for_severity(ChangeSeverity.CRITICAL) == ActionPriority.P0
    assert _priority_for_severity(ChangeSeverity.HIGH) == ActionPriority.P1
    assert _priority_for_severity(ChangeSeverity.MEDIUM) == ActionPriority.P2
    assert _priority_for_severity(ChangeSeverity.LOW) == ActionPriority.P3


def test_action_for_category_penalty():
    a = _action_for_category(ChangeCategory.PENALTY_CHANGE, ChangeSeverity.HIGH)
    assert a.priority == ActionPriority.P1
    assert "penalty" in a.action.lower() or "review" in a.action.lower()


def test_action_for_category_deadline():
    a = _action_for_category(ChangeCategory.COMPLIANCE_DEADLINE, ChangeSeverity.MEDIUM)
    assert a.priority == ActionPriority.P2
    assert "deadline" in a.action.lower() or "calendar" in a.action.lower()


def test_action_for_category_other():
    a = _action_for_category(ChangeCategory.OTHER, ChangeSeverity.LOW)
    assert a.priority == ActionPriority.P3


# ─── Business / compliance impacts ───────────────────────────────────


def test_business_impacts_for_penalty():
    diff = _make_diff(category=ChangeCategory.PENALTY_CHANGE)
    impacts = _business_impacts_for(diff)
    dims = {i.dimension for i in impacts}
    assert ImpactDimension.FINANCIAL in dims


def test_business_impacts_for_capital():
    diff = _make_diff(category=ChangeCategory.CAPITAL_REQUIREMENT)
    impacts = _business_impacts_for(diff)
    dims = {i.dimension for i in impacts}
    assert ImpactDimension.FINANCIAL in dims


def test_compliance_impact_for_penalty():
    diff = _make_diff(category=ChangeCategory.PENALTY_CHANGE)
    c = _compliance_impact_for(diff)
    assert "Penalty assessment" in c.obligations_affected


def test_compliance_impact_default():
    diff = _make_diff(category=ChangeCategory.OTHER)
    c = _compliance_impact_for(diff)
    assert c.obligations_affected == ["General compliance review"]


# ─── Executive summary ──────────────────────────────────────────────


def test_summary_generator_high():
    diff = _make_diff(severity=ChangeSeverity.HIGH)
    entities = [
        AffectedEntity(
            entity_type="bank",  # type: ignore[arg-type]
            name="Bank",
            rationale="x",
            exposure_score=0.8,
        )
    ]
    s = RegulatorySummaryGenerator().generate(diff, entities, ImpactLevel.HIGH)
    assert s.headline
    assert len(s.key_points) > 0
    assert "escalate" in s.recommendation.lower() or "review" in s.recommendation.lower()


def test_summary_generator_low():
    diff = _make_diff(severity=ChangeSeverity.LOW)
    s = RegulatorySummaryGenerator().generate(diff, [], ImpactLevel.LOW)
    assert "record" in s.recommendation.lower() or "file" in s.recommendation.lower()


# ─── Store + Repository ──────────────────────────────────────────────


def test_store_persistence(tmp_path):
    p = Path(tmp_path) / "impact.jsonl"
    s1 = InMemoryImpactStore(persist_path=p)
    r = ImpactReport(
        diff_id="d1",
        document_id="doc-1",
        impact_level=ImpactLevel.HIGH,
        impact_score=0.8,
        generated_at=1.0,
    )
    s1.add_report(r)
    s2 = InMemoryImpactStore(persist_path=p)
    out = s2.get_report(r.report_id)
    assert out is not None
    assert out.document_id == "doc-1"


def test_store_get_missing(tmp_store):
    assert tmp_store.get_report("nope") is None


def test_store_list_empty(tmp_store):
    assert tmp_store.list_reports() == []


def test_store_reset_clears(tmp_store):
    r = ImpactReport(
        diff_id="d1",
        impact_level=ImpactLevel.LOW,
        impact_score=0.1,
        generated_at=0.0,
    )
    tmp_store.add_report(r)
    assert len(tmp_store.list_reports()) == 1
    tmp_store.reset()
    assert tmp_store.list_reports() == []


def test_repository_search_pagination(tmp_store):
    repo = ImpactAnalysisRepository(tmp_store)
    for i in range(5):
        r = ImpactReport(
            diff_id=f"d{i}",
            impact_level=ImpactLevel.MEDIUM,
            impact_score=0.5,
            generated_at=float(i),
        )
        tmp_store.add_report(r)
    res = repo.search(ImpactFilter(page=1, page_size=2))
    assert res.total == 5
    assert res.has_more is True
    assert len(res.items) == 2


def test_repository_search_filter_by_level(tmp_store):
    repo = ImpactAnalysisRepository(tmp_store)
    for lvl in [ImpactLevel.LOW, ImpactLevel.CRITICAL, ImpactLevel.LOW]:
        r = ImpactReport(
            diff_id="d",
            impact_level=lvl,
            impact_score=0.5,
            generated_at=0.0,
        )
        tmp_store.add_report(r)
    res = repo.search(ImpactFilter(min_level=ImpactLevel.HIGH))
    assert all(r.impact_level == ImpactLevel.CRITICAL for r in res.items)


def test_repository_stats(tmp_store):
    repo = ImpactAnalysisRepository(tmp_store)
    for lvl, score in [
        (ImpactLevel.LOW, 0.2),
        (ImpactLevel.HIGH, 0.7),
        (ImpactLevel.CRITICAL, 0.95),
    ]:
        r = ImpactReport(
            diff_id="d",
            impact_level=lvl,
            impact_score=score,
            generated_at=0.0,
        )
        tmp_store.add_report(r)
    s = repo.stats()
    assert s.total_reports == 3
    assert s.critical_impact == 1
    assert s.high_impact == 1
    assert s.low_impact == 1
    assert 0.0 < s.average_impact_score < 1.0


# ─── Service ─────────────────────────────────────────────────────────


def test_service_analyze_rejects_empty(tmp_store):
    svc = ImpactAnalysisService(store=tmp_store)
    with pytest.raises(ValueError):
        svc.analyze(ImpactAnalysisRequest())


def test_service_analyze_with_inline_diff(service):
    diff = _make_diff()
    req = ImpactAnalysisRequest(diff=diff.model_dump(mode="json"))
    result = service.analyze(req)
    assert isinstance(result, ImpactAnalysisResult)
    assert result.report.impact_level in (
        ImpactLevel.HIGH,
        ImpactLevel.CRITICAL,
    )


def test_service_analyze_with_diff_object(service):
    diff = _make_diff(
        severity=ChangeSeverity.LOW,
        category=ChangeCategory.CLARIFICATION,
    )
    result = service.analyze(ImpactAnalysisRequest(), diff=diff)
    assert result.report.impact_level in (
        ImpactLevel.LOW,
        ImpactLevel.NEGLIGIBLE,
    )


def test_service_analyze_records_metrics(service):
    from app.services.observability import get_impact_analysis_metrics

    reset_impact_analysis_metrics()
    diff = _make_diff()
    service.analyze(ImpactAnalysisRequest(), diff=diff)
    snap = get_impact_analysis_metrics().snapshot()
    assert snap["reports_generated"] >= 1


def test_service_get_stored(service):
    diff = _make_diff()
    result = service.analyze(ImpactAnalysisRequest(), diff=diff)
    r = service.get(result.report.report_id)
    assert r is not None
    assert r.diff_id == diff.diff_id


def test_service_get_missing(service):
    assert service.get("nope") is None


def test_service_search(service):
    diff = _make_diff()
    service.analyze(ImpactAnalysisRequest(), diff=diff)
    res = service.search(ImpactFilter(page=1))
    assert res.total >= 1


def test_service_stats(service):
    diff = _make_diff()
    service.analyze(ImpactAnalysisRequest(), diff=diff)
    s = service.stats()
    assert s.total_reports >= 1


def test_service_list_all(service):
    diff = _make_diff()
    service.analyze(ImpactAnalysisRequest(), diff=diff)
    assert len(service.list_all()) >= 1


def test_build_default_service(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    svc = build_default_impact_analysis_service()
    assert isinstance(svc, ImpactAnalysisService)


# ─── API integration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/impact/health")
        assert r.status_code == 200
        assert r.json()["module"] == "impact_analysis"


@pytest.mark.asyncio
async def test_api_analyze_success(tmp_store):
    app.dependency_overrides[get_impact_analysis_service] = lambda: ImpactAnalysisService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            diff = _make_diff()
            r = await c.post(
                "/api/v1/impact/analyze",
                json={"diff": diff.model_dump(mode="json")},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert "report" in body
    finally:
        app.dependency_overrides.pop(get_impact_analysis_service, None)


@pytest.mark.asyncio
async def test_api_analyze_validation_error(tmp_store):
    app.dependency_overrides[get_impact_analysis_service] = lambda: ImpactAnalysisService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/v1/impact/analyze", json={})
            assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(get_impact_analysis_service, None)


@pytest.mark.asyncio
async def test_api_list_reports(tmp_store):
    svc = ImpactAnalysisService(store=tmp_store)
    diff = _make_diff()
    svc.analyze(ImpactAnalysisRequest(), diff=diff)
    app.dependency_overrides[get_impact_analysis_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/impact?page=1&page_size=10")
            assert r.status_code == 200
            body = r.json()
            assert "items" in body
    finally:
        app.dependency_overrides.pop(get_impact_analysis_service, None)


@pytest.mark.asyncio
async def test_api_get_report_404(tmp_store):
    app.dependency_overrides[get_impact_analysis_service] = lambda: ImpactAnalysisService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/impact/nope")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_impact_analysis_service, None)


@pytest.mark.asyncio
async def test_api_stats(tmp_store):
    app.dependency_overrides[get_impact_analysis_service] = lambda: ImpactAnalysisService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/impact/stats")
            assert r.status_code == 200
            body = r.json()
            assert "total_reports" in body
    finally:
        app.dependency_overrides.pop(get_impact_analysis_service, None)
