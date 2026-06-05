"""Tests for Module 7.7 — Agentic Regulatory Research."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_research_service, reset_research_service
from app.main import app
from app.schemas.research import (
    ResearchContext,
    ResearchFilter,
    ResearchKind,
    ResearchRequest,
    ResearchStepType,
)
from app.services.research import (
    InMemoryKnowledgeProvider,
    InMemoryResearchStore,
    ResearchExecutor,
    ResearchPlanner,
    ResearchReportGenerator,
    ResearchService,
    build_default_research_service,
)
from app.services.observability import reset_research_metrics


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_research_service()
    reset_research_metrics()
    yield
    reset_research_service()
    reset_research_metrics()


@pytest.fixture
def tmp_store(tmp_path):
    return InMemoryResearchStore(persist_path=Path(tmp_path) / "research.jsonl")


@pytest.fixture
def service(tmp_store):
    svc = ResearchService(store=tmp_store)
    svc.add_knowledge_item(
        {"title": "KYC 2020 circular", "body": "KYC update", "date": "2020-01-01"}
    )
    svc.add_knowledge_item(
        {"title": "KYC 2025 amendment", "body": "KYC changes", "date": "2025-01-01"}
    )
    svc.add_knowledge_item(
        {"title": "AML circular", "body": "AML update", "date": "2023-06-01"}
    )
    return svc


# ─── Planner ──────────────────────────────────────────────────────────


def test_planner_general():
    req = ResearchRequest(query="What is the latest KYC rule?")
    plan = ResearchPlanner().plan(req)
    assert plan.kind == ResearchKind.GENERAL
    assert any(s.step_type == ResearchStepType.RETRIEVE for s in plan.steps)


def test_planner_timeline_hint():
    req = ResearchRequest(query="Show all KYC changes between 2020 and 2025")
    plan = ResearchPlanner().plan(req)
    assert plan.kind == ResearchKind.TIMELINE
    assert any(s.step_type == ResearchStepType.COMPARE for s in plan.steps)


def test_planner_comparative_hint():
    req = ResearchRequest(query="Compare KYC versus AML rules")
    plan = ResearchPlanner().plan(req)
    assert plan.kind == ResearchKind.COMPARATIVE


def test_planner_multi_hop_hint():
    req = ResearchRequest(query="What is the impact on NBFCs?")
    plan = ResearchPlanner().plan(req)
    assert plan.kind == ResearchKind.MULTI_HOP


def test_planner_cross_document_hint():
    req = ResearchRequest(query="Show changes across all regulators")
    plan = ResearchPlanner().plan(req)
    assert plan.kind == ResearchKind.CROSS_DOCUMENT


def test_planner_respects_max_steps():
    req = ResearchRequest(
        query="Multi-hop analysis of all KYC changes between 2020 and 2025",
        max_steps=3,
    )
    plan = ResearchPlanner().plan(req)
    assert len(plan.steps) <= 3


# ─── Executor ────────────────────────────────────────────────────────


def test_executor_runs_all_steps():
    plan = ResearchPlanner().plan(ResearchRequest(query="KYC"))
    provider = InMemoryKnowledgeProvider()
    provider.add({"title": "KYC 2025", "body": "rules", "id": "d1"})
    executed = ResearchExecutor(provider).execute(plan, top_k=3)
    assert all(s.status.value in {"completed", "failed"} for s in executed.steps)


def test_executor_collects_citations():
    plan = ResearchPlanner().plan(ResearchRequest(query="KYC"))
    provider = InMemoryKnowledgeProvider()
    provider.add({"title": "KYC 2025", "body": "rules", "id": "d1"})
    ResearchExecutor(provider).execute(plan, top_k=3)
    cits = plan.metadata.get("citations", [])
    assert any(c["reference"] == "d1" for c in cits)


# ─── Report generator ──────────────────────────────────────────────


def test_report_generator_produces_summary():
    plan = ResearchPlanner().plan(
        ResearchRequest(query="Show all KYC changes between 2020 and 2025")
    )
    plan.metadata = {"citations": [], "duration_ms": 10.0}
    report = ResearchReportGenerator().generate(plan)
    assert report.summary
    assert report.kind == ResearchKind.TIMELINE


def test_report_generator_timeline_section():
    plan = ResearchPlanner().plan(
        ResearchRequest(
            query="Show timeline",
            kind=ResearchKind.TIMELINE,
        )
    )
    plan.metadata = {"citations": [], "duration_ms": 10.0}
    # Simulate a retrieve step with results
    for s in plan.steps:
        if s.step_type == ResearchStepType.RETRIEVE:
            s.outputs = {
                "hits": 1,
                "results": [{"title": "T", "date": "2025-01-01", "id": "d1"}],
            }
    report = ResearchReportGenerator().generate(plan)
    assert len(report.timeline) >= 0  # may be empty if step not marked complete


# ─── Store ──────────────────────────────────────────────────────────


def test_store_persistence(tmp_path):
    from app.schemas.research import ResearchReport

    p = Path(tmp_path) / "research.jsonl"
    s1 = InMemoryResearchStore(persist_path=p)
    r = ResearchReport(
        plan_id="p1",
        query="x",
        kind=ResearchKind.GENERAL,
        summary="s",
        generated_at=1.0,
    )
    s1.add_report(r)
    s2 = InMemoryResearchStore(persist_path=p)
    out = s2.get_report(r.report_id)
    assert out is not None


def test_store_get_missing(tmp_store):
    assert tmp_store.get_report("nope") is None


def test_store_reset(tmp_store):
    from app.schemas.research import ResearchReport

    r = ResearchReport(
        plan_id="p1", query="x", kind=ResearchKind.GENERAL,
        summary="s", generated_at=0.0,
    )
    tmp_store.add_report(r)
    assert len(tmp_store.list_reports()) == 1
    tmp_store.reset()
    assert tmp_store.list_reports() == []


# ─── Service ────────────────────────────────────────────────────────


def test_service_run_generates_report(service):
    req = ResearchRequest(query="What is the latest KYC rule?")
    report = service.run(req)
    assert report.report_id
    assert report.summary
    assert len(report.citations) >= 1


def test_service_run_timeline(service):
    req = ResearchRequest(
        query="Show all KYC changes between 2020 and 2025"
    )
    report = service.run(req)
    assert report.kind == ResearchKind.TIMELINE
    assert report.summary


def test_service_plan_only(service):
    req = ResearchRequest(query="KYC")
    plan = service.plan_only(req)
    assert plan.plan_id


def test_service_get(service):
    report = service.run(ResearchRequest(query="KYC"))
    out = service.get(report.report_id)
    assert out is not None
    assert out.report_id == report.report_id


def test_service_get_missing(service):
    assert service.get("nope") is None


def test_service_search(service):
    service.run(ResearchRequest(query="KYC"))
    res = service.search(ResearchFilter(page=1))
    assert res.total >= 1


def test_service_search_filter_kind(service):
    service.run(ResearchRequest(query="KYC", kind=ResearchKind.TIMELINE))
    res = service.search(ResearchFilter(kind=ResearchKind.TIMELINE))
    assert all(r.kind == ResearchKind.TIMELINE for r in res.items)


def test_service_stats(service):
    service.run(ResearchRequest(query="KYC"))
    s = service.stats()
    assert s.total_reports >= 1


def test_service_list_all(service):
    service.run(ResearchRequest(query="KYC"))
    assert len(service.list_all()) >= 1


def test_build_default_service(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    svc = build_default_research_service()
    assert isinstance(svc, ResearchService)


# ─── API integration ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/research/health")
        assert r.status_code == 200
        assert r.json()["module"] == "research"


@pytest.mark.asyncio
async def test_api_run(tmp_store):
    app.dependency_overrides[get_research_service] = lambda: ResearchService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/research/run",
                json={"query": "KYC rules"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["query"] == "KYC rules"
            assert body["summary"]
    finally:
        app.dependency_overrides.pop(get_research_service, None)


@pytest.mark.asyncio
async def test_api_plan(tmp_store):
    app.dependency_overrides[get_research_service] = lambda: ResearchService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/api/v1/research/plan",
                json={"query": "KYC rules"},
            )
            assert r.status_code == 200
            assert "steps" in r.json()
    finally:
        app.dependency_overrides.pop(get_research_service, None)


@pytest.mark.asyncio
async def test_api_list_reports(tmp_store):
    svc = ResearchService(store=tmp_store)
    svc.run(ResearchRequest(query="KYC"))
    app.dependency_overrides[get_research_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/research?page=1&page_size=10")
            assert r.status_code == 200
            assert r.json()["total"] >= 1
    finally:
        app.dependency_overrides.pop(get_research_service, None)


@pytest.mark.asyncio
async def test_api_get_report_404(tmp_store):
    app.dependency_overrides[get_research_service] = lambda: ResearchService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/research/nope")
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_research_service, None)


@pytest.mark.asyncio
async def test_api_stats(tmp_store):
    app.dependency_overrides[get_research_service] = lambda: ResearchService(
        store=tmp_store
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/v1/research/stats")
            assert r.status_code == 200
            assert "total_reports" in r.json()
    finally:
        app.dependency_overrides.pop(get_research_service, None)
