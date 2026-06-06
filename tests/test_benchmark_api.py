"""HTTP-level tests for the M10.5 benchmark router.

Uses FastAPI's TestClient (synchronous) and resets the singleton between
tests so we get a clean BenchmarkService per test.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.benchmark.api import router as benchmark_router
from app.benchmark.benchmark_service import reset_benchmark_service


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI(title="RegIntel AI — Benchmark test")
    app.include_router(benchmark_router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    reset_benchmark_service()
    return TestClient(app)


# ─── /health ────────────────────────────────────────────────────────


def test_health_returns_ok(client: TestClient) -> None:
    res = client.get("/api/v1/benchmark/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert body["module"] == "benchmark"
    assert "targets_registered" in body
    assert body["targets_registered"] >= 4


# ─── POST /run ──────────────────────────────────────────────────────


def test_post_run_smoke(client: TestClient) -> None:
    res = client.post(
        "/api/v1/benchmark/run",
        json={"suite": "smoke", "name": "http-smoke"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["suite"] == "smoke"
    assert body["name"] == "http-smoke"
    assert body["summary"]["total_operations"] >= 4
    assert body["summary"]["successful"] >= 4
    assert "latency" in body["summary"]
    assert "cost" in body["summary"]


def test_post_run_invalid_suite(client: TestClient) -> None:
    res = client.post("/api/v1/benchmark/run", json={"suite": "no-such-suite"})
    assert res.status_code == 422


# ─── GET /run ───────────────────────────────────────────────────────


def test_get_run_smoke(client: TestClient) -> None:
    res = client.get("/api/v1/benchmark/run", params={"suite": "smoke"})
    assert res.status_code == 200
    body = res.json()
    assert body["suite"] == "smoke"


# ─── Reports ────────────────────────────────────────────────────────


def test_latency_report_endpoint(client: TestClient) -> None:
    res = client.get("/api/v1/benchmark/reports/latency", params={"suite": "smoke"})
    assert res.status_code == 200
    body = res.json()
    assert body["report"] == "latency"
    assert "summary" in body
    assert "by_kind" in body


def test_cost_report_endpoint(client: TestClient) -> None:
    res = client.get("/api/v1/benchmark/reports/cost", params={"suite": "smoke"})
    assert res.status_code == 200
    body = res.json()
    assert body["report"] == "cost"
    assert "total_cost_units" in body["summary"]


def test_agent_report_endpoint(client: TestClient) -> None:
    res = client.get("/api/v1/benchmark/reports/agent", params={"suite": "smoke"})
    assert res.status_code == 200
    body = res.json()
    assert body["report"] == "agent_performance"
    assert "leaderboard" in body
    assert "totals" in body


def test_system_report_endpoint(client: TestClient) -> None:
    res = client.get("/api/v1/benchmark/reports/system", params={"suite": "smoke"})
    assert res.status_code == 200
    body = res.json()
    assert body["report"] == "system_performance"
    assert "process" in body
    assert "host" in body
    assert "rss_mb" in body["process"]


# ─── Suite listing ─────────────────────────────────────────────────


def test_suites_listing(client: TestClient) -> None:
    res = client.get("/api/v1/benchmark/suites")
    assert res.status_code == 200
    body = res.json()
    names = [s["name"] for s in body["suites"]]
    assert names == ["smoke", "quick", "standard", "full"]


# ─── Reset endpoint ───────────────────────────────────────────────


def test_reset_endpoint(client: TestClient) -> None:
    res = client.post("/api/v1/benchmark/reset")
    assert res.status_code == 204
