"""Tests for Module 7.1 — Regulatory Monitoring Engine."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.api.dependencies import (  # noqa: E402
    get_monitoring_service,
    reset_monitoring_service,
)
from app.api.v1.monitoring import router as monitoring_router  # noqa: E402
from app.core.http_client import HTTPClient, HTTPClientConfig  # noqa: E402
from app.schemas.monitoring import (  # noqa: E402
    ChangeType,
    DiscoveryFilter,
    DiscoveryType,
    DiscoveredDocument,
    DocumentVersion,
    MonitoringHealth,
    MonitoringRun,
    MonitoringStatus,
    RegulatorySource,
    RunMonitorRequest,
    RunMonitorResponse,
    SchedulerStatus,
    SourceConfig,
)
from app.services.monitoring import (  # noqa: E402
    DocumentDiscoveryEngine,
    InMemoryMonitoringStore,
    IRDAISourceAdapter,
    MoFSourceAdapter,
    MonitoringHealthChecker,
    MonitoringRepository,
    MonitoringScheduler,
    MonitoringService,
    PFRDASourceAdapter,
    RBISourceAdapter,
    SEBISourceAdapter,
    SourceAdapter,
    SourceRegistry,
    build_default_monitoring_service,
)
from app.services.observability import reset_monitoring_metrics  # noqa: E402


# ─── Schemas ─────────────────────────────────────────────────────────────


def test_discovered_document_generates_id():
    d = DiscoveredDocument(source=RegulatorySource.RBI, title="x", document_url="u")
    assert d.discovery_id.startswith("disc-")
    assert d.document_found is True
    assert d.change_type == ChangeType.NEW


def test_discovered_document_brief_dict():
    d = DiscoveredDocument(
        source=RegulatorySource.SEBI,
        title="x",
        document_url="u",
        version="v1",
    )
    brief = d.to_brief_dict()
    assert brief["source"] == "SEBI"
    assert brief["document_found"] is True
    assert brief["document_url"] == "u"
    assert brief["version"] == "v1"


def test_monitoring_run_finish_records_duration():
    run = MonitoringRun(source=RegulatorySource.RBI)
    run.finish(MonitoringStatus.HEALTHY, discovered_count=3, new_count=2, updated_count=1)
    assert run.finished_at is not None
    assert run.status == MonitoringStatus.HEALTHY
    assert run.discovered_count == 3
    assert run.duration_ms >= 0


def test_source_config_validates_interval():
    with pytest.raises(Exception):
        SourceConfig(source=RegulatorySource.RBI, base_url="x", poll_interval_seconds=10)


def test_discovery_filter_validates_page():
    with pytest.raises(Exception):
        DiscoveryFilter(page=0)


# ─── Adapters ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rbi_adapter_emits_documents():
    cfg = SourceConfig(source=RegulatorySource.RBI, base_url="x")
    adapter = RBISourceAdapter(cfg)
    docs = await adapter.discover()
    assert len(docs) >= 1
    assert all(d.source == RegulatorySource.RBI for d in docs)


@pytest.mark.asyncio
async def test_sebi_adapter_emits_documents():
    docs = await SEBISourceAdapter(
        SourceConfig(source=RegulatorySource.SEBI, base_url="x")
    ).discover()
    assert all(d.source == RegulatorySource.SEBI for d in docs)


@pytest.mark.asyncio
async def test_irdai_adapter_emits_documents():
    docs = await IRDAISourceAdapter(
        SourceConfig(source=RegulatorySource.IRDAI, base_url="x")
    ).discover()
    assert all(d.source == RegulatorySource.IRDAI for d in docs)


@pytest.mark.asyncio
async def test_pfrda_adapter_emits_documents():
    docs = await PFRDASourceAdapter(
        SourceConfig(source=RegulatorySource.PFRDA, base_url="x")
    ).discover()
    assert all(d.source == RegulatorySource.PFRDA for d in docs)


@pytest.mark.asyncio
async def test_mof_adapter_emits_documents():
    docs = await MoFSourceAdapter(
        SourceConfig(source=RegulatorySource.MINISTRY_OF_FINANCE, base_url="x")
    ).discover()
    assert all(d.source == RegulatorySource.MINISTRY_OF_FINANCE for d in docs)


# ─── Source registry ─────────────────────────────────────────────────────


def test_registry_lists_built_in_sources():
    r = SourceRegistry()
    sources = r.list_sources()
    assert RegulatorySource.RBI in sources
    assert RegulatorySource.SEBI in sources
    assert RegulatorySource.IRDAI in sources
    assert RegulatorySource.PFRDA in sources
    assert RegulatorySource.MINISTRY_OF_FINANCE in sources


def test_registry_register_custom_source():
    r = SourceRegistry()
    cfg = SourceConfig(source=RegulatorySource.CUSTOM, base_url="x")
    r.register(RegulatorySource.CUSTOM, lambda c: _StubAdapter(c), cfg)
    assert RegulatorySource.CUSTOM in r.list_sources()
    adapter = r.build(RegulatorySource.CUSTOM)
    assert adapter.source == RegulatorySource.CUSTOM


def test_registry_unregister():
    r = SourceRegistry()
    r.unregister(RegulatorySource.RBI)
    assert RegulatorySource.RBI not in r.list_sources()


def test_registry_build_missing_raises():
    r = SourceRegistry()
    with pytest.raises(KeyError):
        r.build(RegulatorySource.CUSTOM)


def test_registry_set_config():
    r = SourceRegistry()
    cfg = SourceConfig(source=RegulatorySource.RBI, base_url="https://rbi.gov.in")
    r.set_config(RegulatorySource.RBI, cfg)
    assert r.get_config(RegulatorySource.RBI) == cfg


def test_registry_list_enabled_filters_disabled():
    r = SourceRegistry()
    r.set_config(
        RegulatorySource.RBI,
        SourceConfig(source=RegulatorySource.RBI, base_url="x", enabled=True),
    )
    r.set_config(
        RegulatorySource.SEBI,
        SourceConfig(source=RegulatorySource.SEBI, base_url="x", enabled=False),
    )
    enabled = r.list_enabled_sources()
    assert RegulatorySource.RBI in enabled
    assert RegulatorySource.SEBI not in enabled


class _StubAdapter(SourceAdapter):
    source = RegulatorySource.CUSTOM

    async def discover(self):
        return []


# ─── Store / repository ──────────────────────────────────────────────────


def test_store_add_and_list_discovery():
    s = InMemoryMonitoringStore()
    d = DiscoveredDocument(source=RegulatorySource.RBI, title="x", document_url="u")
    s.add_discovery(d)
    assert s.get_discovery(d.discovery_id) is not None
    assert len(s.list_discoveries()) == 1


def test_store_persists_to_disk(tmp_path):
    p = tmp_path / "monitoring.jsonl"
    s = InMemoryMonitoringStore(persist_path=p)
    d = DiscoveredDocument(source=RegulatorySource.RBI, title="x", document_url="u")
    s.add_discovery(d)
    text = p.read_text(encoding="utf-8")
    assert "disc-" in text
    # Reload
    s2 = InMemoryMonitoringStore(persist_path=p)
    assert len(s2.list_discoveries()) == 1


def test_store_versions():
    s = InMemoryMonitoringStore()
    s.upsert_version(
        DocumentVersion(document_key="RBI:x", version="v1", document_url="u")
    )
    s.upsert_version(
        DocumentVersion(document_key="RBI:x", version="v2", document_url="u")
    )
    assert len(s.list_versions("RBI:x")) == 2
    assert s.latest_version("RBI:x").version == "v2"


def test_repository_marks_duplicate():
    s = InMemoryMonitoringStore()
    repo = MonitoringRepository(s)
    d1 = DiscoveredDocument(
        source=RegulatorySource.RBI, title="x", document_url="u", version="v1"
    )
    d2 = DiscoveredDocument(
        source=RegulatorySource.RBI, title="x", document_url="u", version="v1"
    )
    repo.add_discovery(d1)
    out = repo.add_discovery(d2)
    assert out.already_known is True
    assert out.change_type == ChangeType.UNCHANGED


def test_repository_search_filter():
    s = InMemoryMonitoringStore()
    repo = MonitoringRepository(s)
    repo.add_discovery(
        DiscoveredDocument(source=RegulatorySource.RBI, title="r", document_url="r1")
    )
    repo.add_discovery(
        DiscoveredDocument(source=RegulatorySource.SEBI, title="s", document_url="s1")
    )
    flt = DiscoveryFilter(source=RegulatorySource.RBI)
    res = repo.search(flt)
    assert res.total == 1


def test_repository_search_pagination():
    s = InMemoryMonitoringStore()
    repo = MonitoringRepository(s)
    for i in range(7):
        repo.add_discovery(
            DiscoveredDocument(
                source=RegulatorySource.RBI, title=f"t{i}", document_url=f"u{i}"
            )
        )
    res = repo.search(DiscoveryFilter(page=2, page_size=3))
    assert res.page == 2
    assert len(res.items) == 3
    assert res.has_more is True


# ─── Discovery engine ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discovery_engine_uses_registry():
    registry = SourceRegistry()
    repository = MonitoringRepository(InMemoryMonitoringStore())
    engine = DocumentDiscoveryEngine(registry, repository)
    docs = await engine.discover(RegulatorySource.RBI)
    assert len(docs) >= 1
    for d in docs:
        assert d.source == RegulatorySource.RBI


# ─── Monitor / health ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_monitor_run_source_succeeds():
    reset_monitoring_metrics()
    svc = MonitoringService()
    response = await svc.run_source(RegulatorySource.RBI)
    assert response.run.status == MonitoringStatus.HEALTHY
    assert response.run.discovered_count >= 1


@pytest.mark.asyncio
async def test_monitor_run_source_disabled():
    reset_monitoring_metrics()
    svc = MonitoringService()
    svc.set_source_config(
        RegulatorySource.SEBI,
        SourceConfig(source=RegulatorySource.SEBI, base_url="x", enabled=False),
    )
    response = await svc.run_source(RegulatorySource.SEBI)
    assert response.run.status == MonitoringStatus.UNHEALTHY
    assert "disabled" in (response.run.error_message or "")


@pytest.mark.asyncio
async def test_monitor_run_source_force():
    svc = MonitoringService()
    svc.set_source_config(
        RegulatorySource.SEBI,
        SourceConfig(source=RegulatorySource.SEBI, base_url="x", enabled=False),
    )
    response = await svc.run_source(RegulatorySource.SEBI, force=True)
    assert response.run.status == MonitoringStatus.HEALTHY


@pytest.mark.asyncio
async def test_monitor_run_all():
    reset_monitoring_metrics()
    svc = MonitoringService()
    response = await svc.run_all()
    assert response.total_discoveries >= len(svc.sources())


@pytest.mark.asyncio
async def test_monitor_handles_adapter_exception(monkeypatch):
    svc = MonitoringService()
    # Force registry.build to raise
    from app.services.monitoring import SourceRegistry as _SR

    def boom(self, source):
        raise RuntimeError("adapter boom")

    monkeypatch.setattr(_SR, "build", boom)
    response = await svc.run_source(RegulatorySource.RBI)
    assert response.run.status == MonitoringStatus.UNHEALTHY
    assert "boom" in (response.run.error_message or "")


def test_health_checker_reports_overall():
    svc = MonitoringService()
    h = svc.health()
    assert isinstance(h, MonitoringHealth)
    assert h.overall_status in {
        MonitoringStatus.HEALTHY,
        MonitoringStatus.UNKNOWN,
        MonitoringStatus.DEGRADED,
        MonitoringStatus.UNHEALTHY,
    }
    sources = {s.source for s in h.sources}
    assert RegulatorySource.RBI in sources


# ─── Scheduler ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduler_start_stop():
    svc = MonitoringService()
    scheduler = MonitoringScheduler(svc.monitor, svc.registry, interval_seconds=60)
    assert scheduler.running is False
    await scheduler.start()
    assert scheduler.running is True
    await scheduler.stop()
    assert scheduler.running is False


@pytest.mark.asyncio
async def test_scheduler_tick():
    reset_monitoring_metrics()
    svc = MonitoringService()
    scheduler = MonitoringScheduler(svc.monitor, svc.registry)
    response = await scheduler.tick()
    assert response.total_discoveries >= 1
    assert scheduler.status().last_tick_at is not None


@pytest.mark.asyncio
async def test_scheduler_status_running():
    svc = MonitoringService()
    scheduler = MonitoringScheduler(svc.monitor, svc.registry, interval_seconds=120)
    assert scheduler.status().running is False
    await scheduler.start()
    try:
        st = scheduler.status()
        assert st.running is True
        assert st.interval_seconds == 120
    finally:
        await scheduler.stop()


# ─── Service helpers ─────────────────────────────────────────────────────


def test_service_list_runs():
    svc = MonitoringService(store=InMemoryMonitoringStore())
    # No runs yet
    assert svc.list_runs() == []


def test_service_get_run_missing():
    svc = MonitoringService()
    assert svc.get_run("nope") is None


def test_service_versions_for_unknown_discovery():
    svc = MonitoringService()
    d = DiscoveredDocument(
        source=RegulatorySource.RBI, title="x", document_url="u"
    )
    assert svc.versions_for(d) == []


@pytest.mark.asyncio
async def test_register_custom_source_runtime():
    svc = MonitoringService()
    cfg = SourceConfig(source=RegulatorySource.CUSTOM, base_url="https://x")
    svc.register_custom_source(RegulatorySource.CUSTOM, _StubAdapter, cfg)
    assert RegulatorySource.CUSTOM in svc.sources()


# ─── HTTP client ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_client_get_with_mocked_transport():
    """Verify HTTPClient wraps httpx and applies retries on HTTPError."""
    import httpx

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            return httpx.Response(500, request=request)
        return httpx.Response(200, request=request, content=b"ok")

    transport = httpx.MockTransport(handler)
    client = HTTPClient(
        config=HTTPClientConfig(max_retries=3, backoff_factor=0.0),
        client=httpx.AsyncClient(transport=transport),
    )
    response = await client.get("https://x.invalid/y")
    assert response.status_code == 200
    assert call_count["n"] == 2
    await client.aclose()


# ─── API integration ────────────────────────────────────────────────────


@pytest.fixture
def fresh_service():
    return MonitoringService()


@pytest.fixture
def api_client(fresh_service):
    app = FastAPI()
    app.include_router(monitoring_router, prefix="/api/v1")
    app.dependency_overrides[get_monitoring_service] = lambda: fresh_service
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_api_health(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/monitoring/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "sources" in body


@pytest.mark.asyncio
async def test_api_sources(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/monitoring/sources")
    assert r.status_code == 200
    body = r.json()
    assert "RBI" in body["sources"]
    assert "SEBI" in body["sources"]


@pytest.mark.asyncio
async def test_api_run_source(api_client):
    async with api_client as ac:
        r = await ac.post(
            "/api/v1/monitoring/run",
            json={"source": "RBI", "force": False},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["run"]["status"] == "healthy"
    assert len(body["discoveries"]) >= 1


@pytest.mark.asyncio
async def test_api_run_all(api_client):
    async with api_client as ac:
        r = await ac.post("/api/v1/monitoring/run-all")
    assert r.status_code == 200
    body = r.json()
    assert body["total_discoveries"] >= 1


@pytest.mark.asyncio
async def test_api_run_invalid_source(api_client):
    async with api_client as ac:
        r = await ac.post(
            "/api/v1/monitoring/run",
            json={"source": "BOGUS"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_api_list_discoveries(api_client):
    async with api_client as ac:
        await ac.post("/api/v1/monitoring/run", json={"source": "RBI"})
        r = await ac.get("/api/v1/monitoring/discoveries")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1


@pytest.mark.asyncio
async def test_api_list_runs(api_client):
    async with api_client as ac:
        await ac.post("/api/v1/monitoring/run", json={"source": "RBI"})
        r = await ac.get("/api/v1/monitoring/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1


@pytest.mark.asyncio
async def test_api_get_discovery_404(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/monitoring/discoveries/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_get_run_404(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/monitoring/runs/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_scheduler_start_stop(api_client):
    async with api_client as ac:
        s1 = await ac.post("/api/v1/monitoring/scheduler/start")
        assert s1.status_code == 200
        s2 = await ac.post("/api/v1/monitoring/scheduler/stop")
        assert s2.status_code == 200


@pytest.mark.asyncio
async def test_api_scheduler_tick(api_client):
    async with api_client as ac:
        r = await ac.post("/api/v1/monitoring/scheduler/tick")
    assert r.status_code == 200
    body = r.json()
    assert body["total_discoveries"] >= 1


@pytest.mark.asyncio
async def test_api_scheduler_status(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/monitoring/scheduler")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is False
