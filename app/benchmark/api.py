"""FastAPI routes for the M10.5 benchmark platform."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.benchmark.benchmark_service import (
    BenchmarkService,
    get_benchmark_service,
    reset_benchmark_service,
)
from app.benchmark.models import (
    BenchmarkRequest,
    BenchmarkResponse,
    BenchmarkSuite,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


# ─── Helpers ─────────────────────────────────────────────────────────


def _service() -> BenchmarkService:
    return get_benchmark_service()


# ─── Health / readiness ─────────────────────────────────────────────


@router.get("/health", summary="Benchmark platform health")
async def benchmark_health() -> Dict[str, Any]:
    svc = _service()
    return {
        "status": "healthy",
        "module": "benchmark",
        "version": "1.0.0",
        "targets_registered": len(svc._target_registry),  # noqa: SLF001 — diagnostic
    }


# ─── Run a benchmark ───────────────────────────────────────────────


@router.post(
    "/run",
    response_model=BenchmarkResponse,
    summary="Run a benchmark suite",
)
async def run_benchmark(request: BenchmarkRequest) -> BenchmarkResponse:
    try:
        return await _service().run(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Benchmark run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── Convenience GET (synchronous smoke run) ───────────────────────


@router.get(
    "/run",
    response_model=BenchmarkResponse,
    summary="Run a benchmark suite (GET for smoke tests)",
)
async def run_benchmark_get(
    suite: BenchmarkSuite = BenchmarkSuite.SMOKE,
    iterations: Optional[int] = Query(default=None, ge=1, le=1000),
    concurrency: Optional[int] = Query(default=None, ge=1, le=64),
) -> BenchmarkResponse:
    req = BenchmarkRequest(suite=suite, iterations=iterations, concurrency=concurrency)
    try:
        return await _service().run(req)
    except Exception as exc:  # noqa: BLE001
        logger.exception("GET benchmark run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── On-demand reports ─────────────────────────────────────────────


@router.get(
    "/reports/latency",
    summary="Latency report (last run, or run a new smoke benchmark)",
)
async def latency_report(
    suite: BenchmarkSuite = BenchmarkSuite.SMOKE,
) -> Dict[str, Any]:
    response = await _service().run(BenchmarkRequest(suite=suite))
    return _service().latency_report(response)


@router.get(
    "/reports/cost",
    summary="Cost report (last run, or run a new smoke benchmark)",
)
async def cost_report(
    suite: BenchmarkSuite = BenchmarkSuite.SMOKE,
) -> Dict[str, Any]:
    response = await _service().run(BenchmarkRequest(suite=suite))
    return _service().cost_report(response)


@router.get(
    "/reports/agent",
    summary="Agent performance report",
)
async def agent_report(
    suite: BenchmarkSuite = BenchmarkSuite.SMOKE,
) -> Dict[str, Any]:
    response = await _service().run(BenchmarkRequest(suite=suite))
    return _service().agent_performance_report(response)


@router.get(
    "/reports/system",
    summary="System performance report",
)
async def system_report(
    suite: BenchmarkSuite = BenchmarkSuite.SMOKE,
) -> Dict[str, Any]:
    response = await _service().run(BenchmarkRequest(suite=suite))
    return _service().system_performance_report(response)


# ─── Diagnostics ──────────────────────────────────────────────────


@router.post(
    "/reset",
    summary="Reset the benchmark service (test helper)",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reset() -> JSONResponse:
    reset_benchmark_service()
    return JSONResponse(status_code=204, content=None)


@router.get(
    "/suites",
    summary="List available benchmark suites",
)
async def suites() -> Dict[str, Any]:
    return {
        "suites": [
            {"name": s.value, "description": _suite_description(s)}
            for s in BenchmarkSuite
        ]
    }


def _suite_description(suite: BenchmarkSuite) -> str:
    return {
        BenchmarkSuite.SMOKE: "1 op, 1 worker — health check only",
        BenchmarkSuite.QUICK: "5 ops, 1 worker — fast smoke",
        BenchmarkSuite.STANDARD: "25 ops, 4 workers — default suite",
        BenchmarkSuite.FULL: "100 ops, 8 workers — full perf sweep",
    }[suite]
