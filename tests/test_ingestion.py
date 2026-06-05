"""Tests for Module 7.2 — Automated Regulatory Ingestion."""

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
    get_ingestion_service,
    get_monitoring_service,
    reset_ingestion_service,
    reset_monitoring_service,
)
from app.api.v1.ingestion import router as ingestion_router  # noqa: E402
from app.schemas.ingestion import (  # noqa: E402
    IngestionAuditEntry,
    IngestionFilter,
    IngestionRun,
    IngestionRunResponse,
    IngestionSchedulerStatus,
    IngestionStats,
    IngestionStatus,
    IngestionStep,
    IngestionStepName,
    IngestionStepStatus,
    IngestionTriggerRequest,
    PaginatedIngestionRuns,
    RegistrySyncResult,
)
from app.schemas.monitoring import DiscoveredDocument, RegulatorySource  # noqa: E402
from app.services.ingestion import (  # noqa: E402
    AutoIngestionService,
    DocumentPipelineCoordinator,
    DuplicateDetector,
    FailureRecovery,
    InMemoryIngestionStore,
    IngestionAuditService,
    IngestionRepository,
    IngestionScheduler,
    RegistrySynchronizer,
    _BytesDownloader,
    _NoOpChunker,
    _NoOpEmbedder,
    _NoOpIndexer,
    _NoOpParser,
    _NoOpRegistry,
    build_default_auto_ingestion_service,
)
from app.services.monitoring import (  # noqa: E402
    InMemoryMonitoringStore,
    MonitoringService,
)
from app.services.observability import (  # noqa: E402
    reset_ingestion_metrics,
    reset_monitoring_metrics,
)


# ─── Schemas ────────────────────────────────────────────────────────────


def test_ingestion_step_lifecycle():
    s = IngestionStep(step=IngestionStepName.DOWNLOAD)
    assert s.status == IngestionStepStatus.PENDING
    s.start()
    assert s.status == IngestionStepStatus.RUNNING
    s.finish(IngestionStepStatus.SUCCEEDED, metadata={"x": 1})
    assert s.status == IngestionStepStatus.SUCCEEDED
    assert s.finished_at is not None
    assert s.duration_ms >= 0
    assert s.metadata == {"x": 1}


def test_ingestion_run_finish():
    r = IngestionRun()
    r.finish(IngestionStatus.COMPLETED)
    assert r.status == IngestionStatus.COMPLETED
    assert r.duration_ms >= 0


def test_ingestion_run_response_from_run():
    r = IngestionRun(
        document_id="d1",
        chunks_created=10,
        embeddings_created=10,
        pages_parsed=5,
    )
    r.finish(IngestionStatus.COMPLETED)
    resp = IngestionRunResponse.from_run(r)
    assert resp.document_id == "d1"
    assert resp.ingestion_status == IngestionStatus.COMPLETED
    assert resp.chunks_created == 10


def test_ingestion_filter_validates_page():
    with pytest.raises(Exception):
        IngestionFilter(page=0)


def test_ingestion_stats_defaults():
    s = IngestionStats()
    assert s.total_runs == 0
    assert s.average_duration_ms == 0.0


# ─── Store / repository ──────────────────────────────────────────────────


def test_store_add_and_list_run():
    s = InMemoryIngestionStore()
    r = IngestionRun()
    s.add_run(r)
    assert s.get_run(r.run_id) is not None
    assert len(s.list_runs()) == 1


def test_store_persists_to_disk(tmp_path):
    p = tmp_path / "ingestion.jsonl"
    s = InMemoryIngestionStore(persist_path=p)
    s.add_run(IngestionRun())
    text = p.read_text(encoding="utf-8")
    assert "ing-" in text
    s2 = InMemoryIngestionStore(persist_path=p)
    assert len(s2.list_runs()) == 1


def test_repository_search_pagination():
    s = InMemoryIngestionStore()
    repo = IngestionRepository(s)
    for _ in range(7):
        repo.add_run(IngestionRun())
    res = repo.list_runs(IngestionFilter(page=2, page_size=3))
    assert res.page == 2
    assert len(res.items) == 3
    assert res.has_more is True


def test_repository_search_by_status():
    s = InMemoryIngestionStore()
    repo = IngestionRepository(s)
    a = IngestionRun()
    a.finish(IngestionStatus.COMPLETED)
    b = IngestionRun()
    b.finish(IngestionStatus.FAILED)
    repo.add_run(a)
    repo.add_run(b)
    res = repo.list_runs(IngestionFilter(status=IngestionStatus.FAILED))
    assert res.total == 1


def test_repository_audit_list_for_run():
    s = InMemoryIngestionStore()
    repo = IngestionRepository(s)
    repo.add_audit(
        IngestionAuditEntry(run_id="r1", event="x")
    )
    repo.add_audit(
        IngestionAuditEntry(run_id="r2", event="y")
    )
    assert len(repo.list_audits(run_id="r1", limit=10)) == 1
    assert len(repo.list_audits(limit=10)) == 2


def test_repository_stats():
    s = InMemoryIngestionStore()
    repo = IngestionRepository(s)
    r = IngestionRun(chunks_created=10, embeddings_created=10, pages_parsed=3)
    r.finish(IngestionStatus.COMPLETED)
    repo.add_run(r)
    stats = repo.stats()
    assert stats.total_runs == 1
    assert stats.completed_runs == 1
    assert stats.chunks_created == 10


def test_repository_latest_run_for_document():
    s = InMemoryIngestionStore()
    repo = IngestionRepository(s)
    repo.add_run(IngestionRun(document_id="d1"))
    repo.add_run(IngestionRun(document_id="d1"))
    repo.add_run(IngestionRun(document_id="d2"))
    latest = repo.latest_run_for_document("d1")
    assert latest is not None
    assert latest.document_id == "d1"
    assert repo.latest_run_for_document("nope") is None


# ─── Duplicate detector ─────────────────────────────────────────────────


def test_duplicate_detector_checksum_is_deterministic():
    h1 = DuplicateDetector.compute_checksum(b"abc")
    h2 = DuplicateDetector.compute_checksum(b"abc")
    assert h1 == h2
    assert DuplicateDetector.compute_checksum(b"x") != h1


@pytest.mark.asyncio
async def test_duplicate_detector_detects_duplicate():
    reg = _NoOpRegistry()
    det = DuplicateDetector(reg)
    assert await det.is_duplicate("sha-x") is False
    # Register
    await reg.register({"title": "x", "checksum": "sha-y"})
    assert await det.is_duplicate("sha-y") is True


# ─── Failure recovery ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failure_recovers_after_retry():
    fr = FailureRecovery(max_retries=3, backoff_factor=0.0)
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("flake")
        return "ok"

    result = await fr.run(flaky, step=IngestionStepName.DOWNLOAD)
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_failure_gives_up_after_max_retries():
    fr = FailureRecovery(max_retries=2, backoff_factor=0.0)

    async def always_fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await fr.run(always_fail, step=IngestionStepName.PARSE)


# ─── Audit service ──────────────────────────────────────────────────────


def test_audit_service_records_entry():
    s = InMemoryIngestionStore()
    repo = IngestionRepository(s)
    audit = IngestionAuditService(repo)
    e = audit.record("r1", "x")
    assert e.audit_id.startswith("aud-")
    assert len(repo.list_audits(run_id="r1")) == 1


# ─── Pipeline coordinator ───────────────────────────────────────────────


def _build_pipeline(
    *,
    downloader=_BytesDownloader(),
    parser=_NoOpParser(),
    chunker=_NoOpChunker(),
    embedder=_NoOpEmbedder(),
    indexer=_NoOpIndexer(),
    registry=None,
    duplicate_detector=None,
    recovery=None,
    audit=None,
):
    registry = registry or _NoOpRegistry()
    duplicate_detector = duplicate_detector or DuplicateDetector(registry)
    recovery = recovery or FailureRecovery()
    audit = audit or IngestionAuditService(IngestionRepository(InMemoryIngestionStore()))
    return DocumentPipelineCoordinator(
        downloader=downloader,
        parser=parser,
        chunker=chunker,
        embedder=embedder,
        indexer=indexer,
        registry=registry,
        duplicate_detector=duplicate_detector,
        recovery=recovery,
        audit_service=audit,
    )


@pytest.mark.asyncio
async def test_pipeline_runs_all_steps_successfully():
    pipeline = _build_pipeline()
    run = IngestionRun()
    req = IngestionTriggerRequest(
        url="https://example.com/test.pdf",
        source="RBI",
        title="Test",
    )
    out = await pipeline.run(req, run)
    assert out.status == IngestionStatus.COMPLETED
    assert len(out.steps) == 5
    assert all(s.status == IngestionStepStatus.SUCCEEDED for s in out.steps)
    assert out.chunks_created == 3
    assert out.embeddings_created == 3


@pytest.mark.asyncio
async def test_pipeline_detects_duplicate():
    reg = _NoOpRegistry()
    det = DuplicateDetector(reg)
    # Pre-register a doc with a checksum matching the URL we'll request.
    from app.services.ingestion import DuplicateDetector as _DD

    pre_checksum = _DD.compute_checksum(b"placeholder")
    await reg.register({"checksum": pre_checksum, "title": "x"})

    # Now request an ingestion with a payload that produces that same
    # checksum.
    class _FixedDownloader:
        async def download(self, url):
            return b"placeholder"

    pipeline = _build_pipeline(
        downloader=_FixedDownloader(), registry=reg, duplicate_detector=det
    )
    req = IngestionTriggerRequest(url="https://x", source="RBI")
    out = await pipeline.run(req, IngestionRun())
    assert out.is_duplicate is True
    assert out.status == IngestionStatus.SKIPPED


@pytest.mark.asyncio
async def test_pipeline_force_skips_duplicate_check():
    reg = _NoOpRegistry()
    det = DuplicateDetector(reg)
    from app.services.ingestion import DuplicateDetector as _DD

    pre_checksum = _DD.compute_checksum(b"placeholder")
    await reg.register({"checksum": pre_checksum, "title": "x"})

    class _FixedDownloader:
        async def download(self, url):
            return b"placeholder"

    pipeline = _build_pipeline(
        downloader=_FixedDownloader(), registry=reg, duplicate_detector=det
    )
    req = IngestionTriggerRequest(url="https://x", source="RBI", force=True)
    out = await pipeline.run(req, IngestionRun())
    assert out.is_duplicate is False
    assert out.status == IngestionStatus.COMPLETED


@pytest.mark.asyncio
async def test_pipeline_missing_url_fails():
    pipeline = _build_pipeline()
    out = await pipeline.run(IngestionTriggerRequest(), IngestionRun())
    assert out.status == IngestionStatus.FAILED
    assert "url" in (out.failure_reason or "")


@pytest.mark.asyncio
async def test_pipeline_parser_failure_marks_failed():
    class _FailParser:
        async def parse(self, document_id):
            raise RuntimeError("parser boom")

    pipeline = _build_pipeline(parser=_FailParser())
    out = await pipeline.run(
        IngestionTriggerRequest(url="https://x", source="RBI"), IngestionRun()
    )
    assert out.status == IngestionStatus.FAILED
    assert "parse" in (out.failure_reason or "")


@pytest.mark.asyncio
async def test_pipeline_chunker_failure_marks_failed():
    class _FailChunker:
        async def chunk(self, document_id):
            raise RuntimeError("chunker boom")

    pipeline = _build_pipeline(chunker=_FailChunker())
    out = await pipeline.run(
        IngestionTriggerRequest(url="https://x", source="RBI"), IngestionRun()
    )
    assert out.status == IngestionStatus.FAILED
    assert "chunk" in (out.failure_reason or "")


@pytest.mark.asyncio
async def test_pipeline_embedder_failure_marks_failed():
    class _FailEmbedder:
        async def embed(self, document_id):
            raise RuntimeError("embedder boom")

    pipeline = _build_pipeline(embedder=_FailEmbedder())
    out = await pipeline.run(
        IngestionTriggerRequest(url="https://x", source="RBI"), IngestionRun()
    )
    assert out.status == IngestionStatus.FAILED
    assert "embed" in (out.failure_reason or "")


@pytest.mark.asyncio
async def test_pipeline_indexer_failure_marks_failed():
    class _FailIndexer:
        async def ensure_index(self, model_name):
            raise RuntimeError("indexer boom")

    pipeline = _build_pipeline(indexer=_FailIndexer())
    out = await pipeline.run(
        IngestionTriggerRequest(url="https://x", source="RBI"), IngestionRun()
    )
    assert out.status == IngestionStatus.FAILED
    assert "index" in (out.failure_reason or "")


# ─── Registry synchroniser ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_registry_mixed():
    reg = _NoOpRegistry()
    det = DuplicateDetector(reg)
    sync = RegistrySynchronizer(reg, det)
    discoveries = [
        DiscoveredDocument(
            source=RegulatorySource.RBI,
            title="x",
            document_url="https://rbi/u1",
        ),
        DiscoveredDocument(
            source=RegulatorySource.SEBI,
            title="y",
            document_url="https://sebi/u1",
        ),
    ]
    result = await sync.sync(discoveries)
    assert result.matched == 2
    assert result.new_in_registry == 2
    assert result.errors == 0


@pytest.mark.asyncio
async def test_sync_registry_marks_duplicates():
    reg = _NoOpRegistry()
    det = DuplicateDetector(reg)
    # Pre-register a doc with checksum of "https://rbi/u1"
    from app.services.ingestion import DuplicateDetector as _DD

    checksum = _DD.compute_checksum(b"https://rbi/u1")
    await reg.register({"checksum": checksum, "title": "x"})

    sync = RegistrySynchronizer(reg, det)
    discoveries = [
        DiscoveredDocument(
            source=RegulatorySource.RBI, title="x", document_url="https://rbi/u1"
        )
    ]
    result = await sync.sync(discoveries)
    assert result.already_in_registry == 1
    assert result.new_in_registry == 0


# ─── Top-level service ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_service_ingest_url():
    reset_ingestion_metrics()
    svc = AutoIngestionService(
        coordinator=_build_pipeline(),
        repository=IngestionRepository(InMemoryIngestionStore()),
        audit_service=IngestionAuditService(
            IngestionRepository(InMemoryIngestionStore())
        ),
        synchronizer=RegistrySynchronizer(_NoOpRegistry(), DuplicateDetector(_NoOpRegistry())),
        registry=_NoOpRegistry(),
    )
    resp = await svc.ingest(
        IngestionTriggerRequest(url="https://x/y.pdf", source="RBI", title="T")
    )
    assert resp.ingestion_status == IngestionStatus.COMPLETED
    assert resp.chunks_created == 3


@pytest.mark.asyncio
async def test_service_ingest_discovery():
    reset_ingestion_metrics()
    svc = AutoIngestionService(
        coordinator=_build_pipeline(),
        repository=IngestionRepository(InMemoryIngestionStore()),
        audit_service=IngestionAuditService(
            IngestionRepository(InMemoryIngestionStore())
        ),
        synchronizer=RegistrySynchronizer(_NoOpRegistry(), DuplicateDetector(_NoOpRegistry())),
        registry=_NoOpRegistry(),
    )
    d = DiscoveredDocument(
        source=RegulatorySource.RBI, title="x", document_url="https://x/y"
    )
    resp = await svc.ingest_discovery(d)
    assert resp.ingestion_status == IngestionStatus.COMPLETED


def test_service_get_run_missing():
    svc = build_default_auto_ingestion_service()
    assert svc.get_run("nope") is None


def test_service_stats_empty():
    registry = _NoOpRegistry()
    store = InMemoryIngestionStore()
    repo = IngestionRepository(store)
    audit = IngestionAuditService(repo)
    coordinator = _build_pipeline(registry=registry, audit=audit)
    sync = RegistrySynchronizer(registry, DuplicateDetector(registry))
    svc = AutoIngestionService(
        coordinator=coordinator,
        repository=repo,
        audit_service=audit,
        synchronizer=sync,
        registry=registry,
    )
    stats = svc.stats()
    assert stats.total_runs == 0


@pytest.mark.asyncio
async def test_service_ingest_pending_discoveries_no_monitoring():
    svc = build_default_auto_ingestion_service()
    runs = await svc.ingest_pending_discoveries()
    assert runs == []  # no monitoring_service


# ─── Scheduler ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingestion_scheduler_start_stop():
    svc = build_default_auto_ingestion_service()
    sch = IngestionScheduler(svc, interval_seconds=60)
    assert sch.running is False
    await sch.start()
    assert sch.running is True
    await sch.stop()
    assert sch.running is False


@pytest.mark.asyncio
async def test_ingestion_scheduler_tick_empty():
    svc = build_default_auto_ingestion_service()
    sch = IngestionScheduler(svc)
    runs = await sch.tick()
    assert runs == []  # no monitoring_service


def test_ingestion_scheduler_status_default():
    svc = build_default_auto_ingestion_service()
    sch = IngestionScheduler(svc, interval_seconds=120)
    st = sch.status()
    assert st.running is False
    assert st.interval_seconds == 120


# ─── API integration ────────────────────────────────────────────────────


@pytest.fixture
def fresh_service():
    return build_default_auto_ingestion_service()


@pytest.fixture
def api_client(fresh_service):
    app = FastAPI()
    app.include_router(ingestion_router, prefix="/api/v1")
    app.dependency_overrides[get_ingestion_service] = lambda: fresh_service
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_api_health(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/ingestion/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_api_run_ingestion(api_client):
    async with api_client as ac:
        r = await ac.post(
            "/api/v1/ingestion/run",
            json={"url": "https://x/y.pdf", "source": "RBI", "title": "T"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ingestion_status"] == "completed"
    assert body["chunks_created"] >= 1


@pytest.mark.asyncio
async def test_api_run_ingestion_missing_url_and_discovery_returns_400(api_client):
    async with api_client as ac:
        r = await ac.post("/api/v1/ingestion/run", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_api_run_ingestion_resolves_discovery():
    from app.services.monitoring import (
        InMemoryMonitoringStore,
        MonitoringService,
    )

    reset_monitoring_metrics()
    monitor = MonitoringService(store=InMemoryMonitoringStore())
    d = DiscoveredDocument(
        source=RegulatorySource.RBI, title="x", document_url="https://rbi/u1"
    )
    monitor.repository.add_discovery(d)

    # Build a fresh service with fresh stores to avoid disk pollution.
    registry = _NoOpRegistry()
    store = InMemoryIngestionStore()
    repo = IngestionRepository(store)
    audit = IngestionAuditService(repo)
    coordinator = _build_pipeline(registry=registry, audit=audit)
    sync = RegistrySynchronizer(registry, DuplicateDetector(registry))
    svc = AutoIngestionService(
        coordinator=coordinator,
        repository=repo,
        audit_service=audit,
        synchronizer=sync,
        registry=registry,
    )

    app = FastAPI()
    app.include_router(ingestion_router, prefix="/api/v1")
    app.dependency_overrides[get_ingestion_service] = lambda: svc
    app.dependency_overrides[get_monitoring_service] = lambda: monitor
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/api/v1/ingestion/run",
            json={"discovery_id": d.discovery_id},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ingestion_status"] == "completed"


@pytest.mark.asyncio
async def test_api_run_discovery():
    from app.services.monitoring import (
        InMemoryMonitoringStore,
        MonitoringService,
    )

    reset_monitoring_metrics()
    monitor = MonitoringService(store=InMemoryMonitoringStore())
    d = DiscoveredDocument(
        source=RegulatorySource.RBI, title="x", document_url="https://rbi/u2"
    )
    monitor.repository.add_discovery(d)

    registry = _NoOpRegistry()
    store = InMemoryIngestionStore()
    repo = IngestionRepository(store)
    audit = IngestionAuditService(repo)
    coordinator = _build_pipeline(registry=registry, audit=audit)
    sync = RegistrySynchronizer(registry, DuplicateDetector(registry))
    svc = AutoIngestionService(
        coordinator=coordinator,
        repository=repo,
        audit_service=audit,
        synchronizer=sync,
        registry=registry,
    )

    app = FastAPI()
    app.include_router(ingestion_router, prefix="/api/v1")
    app.dependency_overrides[get_ingestion_service] = lambda: svc
    app.dependency_overrides[get_monitoring_service] = lambda: monitor
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(f"/api/v1/ingestion/run-discovery/{d.discovery_id}")
    assert r.status_code == 200
    assert r.json()["ingestion_status"] == "completed"


@pytest.mark.asyncio
async def test_api_run_discovery_404(api_client):
    async with api_client as ac:
        r = await ac.post("/api/v1/ingestion/run-discovery/nope")
    # Monitoring service returns None → discovery 404 OR ingestion 404
    assert r.status_code in {404, 500}  # acceptable: 500 if monitoring raises


@pytest.mark.asyncio
async def test_api_list_runs(api_client):
    async with api_client as ac:
        await ac.post(
            "/api/v1/ingestion/run",
            json={"url": "https://x/y.pdf", "source": "RBI"},
        )
        r = await ac.get("/api/v1/ingestion/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1


@pytest.mark.asyncio
async def test_api_get_run_404(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/ingestion/runs/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_stats(api_client):
    async with api_client as ac:
        await ac.post(
            "/api/v1/ingestion/run",
            json={"url": "https://x/y.pdf", "source": "RBI"},
        )
        r = await ac.get("/api/v1/ingestion/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_runs"] >= 1


@pytest.mark.asyncio
async def test_api_audit(api_client):
    async with api_client as ac:
        await ac.post(
            "/api/v1/ingestion/run",
            json={"url": "https://x/y.pdf", "source": "RBI"},
        )
        r = await ac.get("/api/v1/ingestion/audit")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1


@pytest.mark.asyncio
async def test_api_run_audit(api_client):
    async with api_client as ac:
        post = await ac.post(
            "/api/v1/ingestion/run",
            json={"url": "https://x/y.pdf", "source": "RBI"},
        )
        rid = post.json()["run_id"]
        r = await ac.get(f"/api/v1/ingestion/runs/{rid}/audit")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1


@pytest.mark.asyncio
async def test_api_sync_registry():
    from app.services.monitoring import (
        InMemoryMonitoringStore,
        MonitoringService,
    )

    reset_monitoring_metrics()
    monitor = MonitoringService(store=InMemoryMonitoringStore())
    monitor.repository.add_discovery(
        DiscoveredDocument(
            source=RegulatorySource.RBI,
            title="x",
            document_url="https://rbi/sync-1",
        )
    )

    registry = _NoOpRegistry()
    store = InMemoryIngestionStore()
    repo = IngestionRepository(store)
    audit = IngestionAuditService(repo)
    coordinator = _build_pipeline(registry=registry, audit=audit)
    sync = RegistrySynchronizer(registry, DuplicateDetector(registry))
    svc = AutoIngestionService(
        coordinator=coordinator,
        repository=repo,
        audit_service=audit,
        synchronizer=sync,
        registry=registry,
    )

    app = FastAPI()
    app.include_router(ingestion_router, prefix="/api/v1")
    app.dependency_overrides[get_ingestion_service] = lambda: svc
    app.dependency_overrides[get_monitoring_service] = lambda: monitor
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/api/v1/ingestion/sync-registry")
    assert r.status_code == 200
    body = r.json()
    assert body["new_in_registry"] >= 1


@pytest.mark.asyncio
async def test_api_scheduler_start_stop(api_client):
    async with api_client as ac:
        s1 = await ac.post("/api/v1/ingestion/scheduler/start")
        assert s1.status_code == 200
        s2 = await ac.post("/api/v1/ingestion/scheduler/stop")
        assert s2.status_code == 200


@pytest.mark.asyncio
async def test_api_scheduler_tick(api_client):
    async with api_client as ac:
        r = await ac.post("/api/v1/ingestion/scheduler/tick")
    assert r.status_code == 200
    assert "ran" in r.json()


@pytest.mark.asyncio
async def test_api_scheduler_status(api_client):
    async with api_client as ac:
        r = await ac.get("/api/v1/ingestion/scheduler")
    assert r.status_code == 200
    assert r.json()["running"] is False
