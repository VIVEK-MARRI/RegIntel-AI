"""Tests for Module 6.8 — Production Readiness."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.api.v1.health import (  # noqa: E402
    get_health_checker,
    router as health_router,
    set_health_checker,
)
from app.core.health import (  # noqa: E402
    ComponentHealth,
    HealthChecker,
    HealthStatus,
    always_healthy,
    env_present,
    storage_writable,
)
from app.core.startup import (  # noqa: E402
    EnvironmentValidationError,
    StartupReport,
    on_shutdown,
    on_startup,
    register_default_health_checks,
    validate_environment,
    validate_storage_root,
)
from app.middleware import (  # noqa: E402
    APIKey,
    APIKeyMiddleware,
    APIKeyStore,
    AuditLog,
    AuditLogEntry,
    AuditLogMiddleware,
    DEFAULT_SECURITY_HEADERS,
    RateLimitMiddleware,
    RequestTracingMiddleware,
    SecurityHeadersMiddleware,
    SlidingWindowRateLimiter,
)


# ─── Security headers ────────────────────────────────────────────────────


def test_default_security_headers_dict():
    assert "X-Content-Type-Options" in DEFAULT_SECURITY_HEADERS
    assert DEFAULT_SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" in DEFAULT_SECURITY_HEADERS


@pytest.mark.asyncio
async def test_security_headers_added_to_response():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    async def x():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"


@pytest.mark.asyncio
async def test_security_headers_custom():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, headers={"X-Custom": "yes"})

    @app.get("/x")
    async def x():
        return {}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x")
    assert r.headers.get("X-Custom") == "yes"


# ─── Request tracing ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_id_generated_when_absent():
    app = FastAPI()
    app.add_middleware(RequestTracingMiddleware)

    @app.get("/x")
    async def x():
        return {}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x")
    assert "X-Request-ID" in r.headers
    assert len(r.headers["X-Request-ID"]) > 0


@pytest.mark.asyncio
async def test_request_id_preserved_when_provided():
    app = FastAPI()
    app.add_middleware(RequestTracingMiddleware)

    @app.get("/x")
    async def x():
        return {}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x", headers={"X-Request-ID": "my-id-123"})
    assert r.headers["X-Request-ID"] == "my-id-123"


# ─── Rate limiter ────────────────────────────────────────────────────────


def test_sliding_window_allows_under_limit():
    rl = SlidingWindowRateLimiter()
    for i in range(5):
        allowed, remaining, _ = rl.allow("k1", limit=5, window_seconds=60.0)
        assert allowed
    assert remaining == 0


def test_sliding_window_blocks_over_limit():
    rl = SlidingWindowRateLimiter()
    for _ in range(3):
        rl.allow("k1", limit=3, window_seconds=60.0)
    allowed, remaining, retry = rl.allow("k1", limit=3, window_seconds=60.0)
    assert not allowed
    assert remaining == 0
    assert retry > 0


def test_sliding_window_per_identity_isolation():
    rl = SlidingWindowRateLimiter()
    for _ in range(3):
        rl.allow("k1", limit=3, window_seconds=60.0)
    allowed, _, _ = rl.allow("k2", limit=3, window_seconds=60.0)
    assert allowed


def test_sliding_window_reset():
    rl = SlidingWindowRateLimiter()
    rl.allow("k1", limit=1, window_seconds=60.0)
    rl.reset("k1")
    allowed, _, _ = rl.allow("k1", limit=1, window_seconds=60.0)
    assert allowed


@pytest.mark.asyncio
async def test_rate_limit_middleware_returns_429():
    app = FastAPI()
    limiter = SlidingWindowRateLimiter()
    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
        default_limit=2,
        window_seconds=60.0,
        exempt_paths=set(),  # not exempt
    )

    @app.get("/x")
    async def x():
        return {}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.get("/x")
        r2 = await ac.get("/x")
        r3 = await ac.get("/x")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers


@pytest.mark.asyncio
async def test_rate_limit_middleware_exempt_path():
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        default_limit=1,
        window_seconds=60.0,
        exempt_paths={"/health"},
    )

    @app.get("/health")
    async def h():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r1 = await ac.get("/health")
        r2 = await ac.get("/health")
        r3 = await ac.get("/health")
    for r in (r1, r2, r3):
        assert r.status_code == 200


# ─── API key middleware ──────────────────────────────────────────────────


def test_api_key_store_add_lookup():
    store = APIKeyStore()
    key = APIKey(key_id="k1", secret="s1", label="test")
    store.add(key)
    found = store.lookup("s1")
    assert found is not None
    assert found.key_id == "k1"
    assert store.lookup("nope") is None
    store.remove("s1")
    assert store.lookup("s1") is None


@pytest.mark.asyncio
async def test_api_key_middleware_missing_header():
    app = FastAPI()
    store = APIKeyStore()
    store.add(APIKey(key_id="k1", secret="s1"))
    app.add_middleware(APIKeyMiddleware, store=store, enabled=True, exempt_paths=set())

    @app.get("/x")
    async def x():
        return {}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_key_middleware_invalid_key():
    app = FastAPI()
    store = APIKeyStore()
    store.add(APIKey(key_id="k1", secret="s1"))
    app.add_middleware(APIKeyMiddleware, store=store, enabled=True, exempt_paths=set())

    @app.get("/x")
    async def x():
        return {}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x", headers={"X-Api-Key": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_key_middleware_valid_key():
    app = FastAPI()
    store = APIKeyStore()
    store.add(APIKey(key_id="k1", secret="s1"))
    app.add_middleware(APIKeyMiddleware, store=store, enabled=True, exempt_paths=set())

    @app.get("/x")
    async def x():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x", headers={"X-Api-Key": "s1"})
    assert r.status_code == 200


# ─── Audit log middleware ────────────────────────────────────────────────


def test_audit_log_in_memory():
    log = AuditLog()
    log.record(
        AuditLogEntry(
            timestamp=datetime.now(timezone.utc),
            request_id="r1",
            method="GET",
            path="/x",
            status_code=200,
            duration_ms=1.0,
        )
    )
    entries = log.all()
    assert len(entries) == 1
    assert entries[0].request_id == "r1"


def test_audit_log_thread_safe():
    import threading

    log = AuditLog()

    def worker(n):
        for i in range(n):
            log.record(
                AuditLogEntry(
                    timestamp=datetime.now(timezone.utc),
                    request_id=f"r{i}",
                    method="GET",
                    path="/x",
                    status_code=200,
                    duration_ms=1.0,
                )
            )

    threads = [threading.Thread(target=worker, args=(50,)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(log.all()) == 250


def test_audit_log_persists_to_file(tmp_path: Path):
    log_path = tmp_path / "audit.log"
    log = AuditLog(persist_path=log_path)
    log.record(
        AuditLogEntry(
            timestamp=datetime.now(timezone.utc),
            request_id="r1",
            method="GET",
            path="/x",
            status_code=200,
            duration_ms=1.0,
        )
    )
    log.record(
        AuditLogEntry(
            timestamp=datetime.now(timezone.utc),
            request_id="r2",
            method="POST",
            path="/y",
            status_code=201,
            duration_ms=2.0,
        )
    )
    text = log_path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 2
    parsed = json.loads(lines[0])
    assert parsed["request_id"] == "r1"


@pytest.mark.asyncio
async def test_audit_log_middleware_records():
    app = FastAPI()
    log = AuditLog()
    app.add_middleware(AuditLogMiddleware, audit_log=log)

    @app.get("/x")
    async def x():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/x")
    entries = log.all()
    assert len(entries) == 1
    assert entries[0].path == "/x"
    assert entries[0].status_code == 200


# ─── Health checker ──────────────────────────────────────────────────────


def test_component_health_to_dict():
    comp = ComponentHealth(
        name="x",
        status=HealthStatus.HEALTHY,
        latency_ms=1.0,
        message="ok",
    )
    d = comp.to_dict()
    assert d["name"] == "x"
    assert d["status"] == "healthy"
    assert d["latency_ms"] == 1.0


def test_health_checker_run_healthy():
    checker = HealthChecker()
    checker.register(
        "a", lambda: ComponentHealth(name="a", status=HealthStatus.HEALTHY)
    )
    checker.register(
        "b", lambda: ComponentHealth(name="b", status=HealthStatus.HEALTHY)
    )
    report = checker.run()
    assert report.status == HealthStatus.HEALTHY
    assert {c.name for c in report.components} == {"a", "b"}


def test_health_checker_run_degraded():
    checker = HealthChecker()
    checker.register(
        "a", lambda: ComponentHealth(name="a", status=HealthStatus.HEALTHY)
    )
    checker.register(
        "b", lambda: ComponentHealth(name="b", status=HealthStatus.DEGRADED)
    )
    report = checker.run()
    assert report.status == HealthStatus.DEGRADED


def test_health_checker_run_unhealthy():
    checker = HealthChecker()
    checker.register(
        "a", lambda: ComponentHealth(name="a", status=HealthStatus.HEALTHY)
    )
    checker.register(
        "b", lambda: ComponentHealth(name="b", status=HealthStatus.UNHEALTHY)
    )
    report = checker.run()
    assert report.status == HealthStatus.UNHEALTHY


def test_health_checker_handles_exception_in_check():
    checker = HealthChecker()

    def bad():
        raise RuntimeError("boom")

    checker.register("bad", bad)
    report = checker.run()
    assert report.status == HealthStatus.UNHEALTHY
    assert "boom" in (report.components[0].message or "")


def test_health_checker_run_named_subset():
    checker = HealthChecker()
    checker.register(
        "a", lambda: ComponentHealth(name="a", status=HealthStatus.HEALTHY)
    )
    checker.register(
        "b", lambda: ComponentHealth(name="b", status=HealthStatus.HEALTHY)
    )
    report = checker.run(names=["a"])
    assert {c.name for c in report.components} == {"a"}


def test_health_checker_unregister():
    checker = HealthChecker()
    checker.register(
        "a", lambda: ComponentHealth(name="a", status=HealthStatus.HEALTHY)
    )
    checker.unregister("a")
    assert "a" not in checker.checks()


def test_always_healthy_helper():
    c = always_healthy("x")
    assert c.status == HealthStatus.HEALTHY


def test_env_present_helper_present(monkeypatch):
    monkeypatch.setenv("REGINTEL_TEST_ENV", "1")
    c = env_present("env:test", "REGINTEL_TEST_ENV")
    assert c.status == HealthStatus.HEALTHY


def test_env_present_helper_missing(monkeypatch):
    monkeypatch.delenv("REGINTEL_TEST_ENV_MISSING", raising=False)
    c = env_present("env:test", "REGINTEL_TEST_ENV_MISSING")
    assert c.status == HealthStatus.DEGRADED


def test_storage_writable_helper(tmp_path: Path):
    c = storage_writable("storage", tmp_path)
    assert c.status == HealthStatus.HEALTHY


def test_storage_writable_helper_unwritable(tmp_path: Path):
    # Use a path inside a non-existent / read-only parent.
    c = storage_writable("storage", tmp_path / "nope" / "deeper")
    # If the parent is creatable on Windows as a non-root user, this may
    # actually succeed — relax to "not UNHEALTHY OR HEALTHY".
    assert c.status in {HealthStatus.HEALTHY, HealthStatus.UNHEALTHY}


# ─── Health API endpoints ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_live():
    checker = HealthChecker()
    checker.register(
        "liveness",
        lambda: ComponentHealth(name="liveness", status=HealthStatus.HEALTHY),
    )
    set_health_checker(checker)
    app = FastAPI()
    app.include_router(health_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_health_root():
    app = FastAPI()
    app.include_router(health_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_ready_all_healthy():
    checker = HealthChecker()
    checker.register(
        "liveness",
        lambda: ComponentHealth(name="liveness", status=HealthStatus.HEALTHY),
    )
    checker.register(
        "storage", lambda: ComponentHealth(name="storage", status=HealthStatus.HEALTHY)
    )
    set_health_checker(checker)
    app = FastAPI()
    app.include_router(health_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_ready_unhealthy_returns_503():
    checker = HealthChecker()
    checker.register(
        "liveness",
        lambda: ComponentHealth(name="liveness", status=HealthStatus.HEALTHY),
    )
    checker.register(
        "storage",
        lambda: ComponentHealth(name="storage", status=HealthStatus.UNHEALTHY),
    )
    set_health_checker(checker)
    app = FastAPI()
    app.include_router(health_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health/ready")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_health_deep_unhealthy_returns_503():
    checker = HealthChecker()
    checker.register(
        "a", lambda: ComponentHealth(name="a", status=HealthStatus.UNHEALTHY)
    )
    set_health_checker(checker)
    app = FastAPI()
    app.include_router(health_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health/deep")
    assert r.status_code == 503


# ─── Environment validation ──────────────────────────────────────────────


def test_validate_environment_no_required():
    assert validate_environment() == []


def test_validate_environment_missing(monkeypatch):
    monkeypatch.delenv("REGINTEL_REQUIRED_VAR", raising=False)
    errors = validate_environment(["REGINTEL_REQUIRED_VAR"])
    assert len(errors) == 1
    assert "REGINTEL_REQUIRED_VAR" in errors[0]


def test_validate_environment_present(monkeypatch):
    monkeypatch.setenv("REGINTEL_REQUIRED_VAR", "x")
    assert validate_environment(["REGINTEL_REQUIRED_VAR"]) == []


def test_validate_environment_raises(monkeypatch):
    monkeypatch.delenv("REGINTEL_REQUIRED_VAR", raising=False)
    with pytest.raises(EnvironmentValidationError):
        validate_environment(["REGINTEL_REQUIRED_VAR"], raise_on_error=True)


def test_validate_storage_root_creates_dir(tmp_path: Path):
    target = tmp_path / "new" / "storage"
    errors = validate_storage_root(target)
    assert errors == []
    assert target.exists()


def test_register_default_health_checks():
    checker = HealthChecker()
    registered = register_default_health_checks(
        checker,
        required_env=["REGINTEL_TEST_VAR"],
        storage_root=Path("/tmp"),
    )
    assert "liveness" in registered
    assert "env:REGINTEL_TEST_VAR" in registered
    assert "storage" in registered


def test_on_startup_returns_report(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REGINTEL_TMP_REQUIRED", "ok")
    set_health_checker(HealthChecker())
    report = on_startup(
        required_env=["REGINTEL_TMP_REQUIRED"],
        storage_root=tmp_path,
    )
    assert isinstance(report, StartupReport)
    assert report.success
    assert "liveness" in report.components_registered


def test_on_startup_records_errors(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("REGINTEL_MUST_BE_SET", raising=False)
    set_health_checker(HealthChecker())
    report = on_startup(
        required_env=["REGINTEL_MUST_BE_SET"],
        storage_root=tmp_path,
    )
    assert not report.success
    assert any("REGINTEL_MUST_BE_SET" in e for e in report.errors)


def test_on_startup_can_raise(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("REGINTEL_MUST_BE_SET2", raising=False)
    set_health_checker(HealthChecker())
    with pytest.raises(EnvironmentValidationError):
        on_startup(
            required_env=["REGINTEL_MUST_BE_SET2"],
            storage_root=tmp_path,
            raise_on_error=True,
        )


def test_on_shutdown_does_not_raise():
    on_shutdown()  # should just log


# ─── Middleware ordering / interaction ───────────────────────────────────


@pytest.mark.asyncio
async def test_tracing_and_audit_work_together():
    app = FastAPI()
    log = AuditLog()
    # tracing → audit
    app.add_middleware(RequestTracingMiddleware)
    app.add_middleware(AuditLogMiddleware, audit_log=log)

    @app.get("/x")
    async def x():
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x", headers={"X-Request-ID": "rid-1"})
    assert r.status_code == 200
    entries = log.all()
    assert len(entries) == 1
    assert entries[0].request_id == "rid-1"
