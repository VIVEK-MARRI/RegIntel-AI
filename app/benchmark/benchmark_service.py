"""Top-level orchestrator for the M10.5 benchmark platform.

The :class:`BenchmarkService` ties together the :class:`PerformanceRunner`,
:class:`LoadTester`, :class:`MetricsCollector`, and :class:`Reporter` to
produce end-to-end benchmark reports.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

from app.benchmark.load_tester import LoadTester, LoadTestConfig, LoadTestResult
from app.benchmark.metrics_collector import (
    MetricsCollector,
    compute_cost_summary,
    compute_latency_stats,
)
from app.benchmark.models import (
    BenchmarkRequest,
    BenchmarkResponse,
    BenchmarkSuite,
    BenchmarkSummary,
    CostSummary,
    LatencyStats,
    OperationKind,
    OperationResult,
    SystemSnapshot,
    TokenUsage,
)
from app.benchmark.performance_runner import PerformanceRunner, PerformanceScenario
from app.benchmark.reporter import Reporter

logger = logging.getLogger(__name__)


# ─── Default scenarios per suite ──────────────────────────────────────

def _noop_async(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Cheap synthetic async target that mimics a typical API call."""
    return {"input_tokens": 64, "output_tokens": 32, "retrieval_units": 1}


def _synthetic_targets() -> List[Callable[[], Awaitable[Mapping[str, Any]]]]:
    """A small set of synthetic async targets covering each operation kind."""

    async def retrieval_target() -> Mapping[str, Any]:
        await asyncio.sleep(0.005)
        return {"input_tokens": 8, "retrieval_units": 1}

    async def answer_target() -> Mapping[str, Any]:
        await asyncio.sleep(0.012)
        return {"input_tokens": 256, "output_tokens": 96, "retrieval_units": 2}

    async def agent_target() -> Mapping[str, Any]:
        await asyncio.sleep(0.025)
        return {"input_tokens": 512, "output_tokens": 128, "retrieval_units": 4}

    async def ingest_target() -> Mapping[str, Any]:
        await asyncio.sleep(0.020)
        return {"input_tokens": 1024}

    return [retrieval_target, answer_target, agent_target, ingest_target]


@dataclass(frozen=True)
class _SuiteConfig:
    concurrency: int
    iterations: int
    warmup: int = 1


_SUITE_DEFAULTS: Dict[BenchmarkSuite, _SuiteConfig] = {
    BenchmarkSuite.SMOKE:    _SuiteConfig(concurrency=1, iterations=1, warmup=0),
    BenchmarkSuite.QUICK:    _SuiteConfig(concurrency=1, iterations=5, warmup=1),
    BenchmarkSuite.STANDARD: _SuiteConfig(concurrency=4, iterations=25, warmup=2),
    BenchmarkSuite.FULL:     _SuiteConfig(concurrency=8, iterations=100, warmup=4),
}


class BenchmarkService:
    """Orchestrates performance + load tests and produces a :class:`BenchmarkResponse`."""

    def __init__(
        self,
        *,
        collector: Optional[MetricsCollector] = None,
        runner: Optional[PerformanceRunner] = None,
        load_tester: Optional[LoadTester] = None,
        reporter: Optional[Reporter] = None,
    ) -> None:
        self.collector = collector or MetricsCollector()
        self.runner = runner or PerformanceRunner(self.collector)
        self.load_tester = load_tester or LoadTester(self.collector)
        self.reporter = reporter or Reporter()
        # Optional pluggable target registry; if absent we use synthetic targets.
        self._target_registry: Dict[OperationKind, Callable[[], Awaitable[Mapping[str, Any]]]] = {}
        for tgt in _synthetic_targets():
            self._target_registry[_classify_target(tgt)] = tgt

    # ─── Public surface ──────────────────────────────────────────────

    def register_target(
        self,
        kind: OperationKind,
        target: Callable[[], Awaitable[Mapping[str, Any]]],
    ) -> None:
        self._target_registry[kind] = target

    async def run(self, request: BenchmarkRequest) -> BenchmarkResponse:
        started_dt = datetime.now(timezone.utc)
        suite = request.suite
        cfg = _SUITE_DEFAULTS[suite]
        concurrency = request.concurrency or cfg.concurrency
        iterations = request.iterations or cfg.iterations
        warmup = max(0, cfg.warmup)
        run_id = str(uuid.uuid4())
        name = request.name or f"{suite.value}-benchmark-{run_id[:8]}"

        notes: List[str] = [
            f"suite={suite.value}",
            f"concurrency={concurrency}",
            f"iterations={iterations}",
            f"warmup={warmup}",
        ]

        load_results: List[LoadTestResult] = []
        all_results: List[OperationResult] = []
        system_snapshots: List[SystemSnapshot] = []

        for kind, target in self._target_registry.items():
            cfg = LoadTestConfig(
                name=f"{name}/{kind.value}",
                target=target,
                concurrency=concurrency,
                iterations=iterations,
                warmup=warmup,
                kind=kind,
                cost_per_1k_input_tokens=request.cost_per_1k_input_tokens,
                cost_per_1k_output_tokens=request.cost_per_1k_output_tokens,
                cost_per_retrieval=request.cost_per_retrieval,
            )
            lr = await self.load_tester.run(cfg)
            load_results.append(lr)
            all_results.extend(lr.results)
            system_snapshots.extend(lr.system_snapshots)

        # If the user supplied explicit scenarios, run them sequentially.
        for idx, sc_dict in enumerate(request.scenarios or []):
            sc = self._build_scenario(sc_dict, idx)
            sr = await self.runner.run(sc)
            all_results.append(sr.operation)
            system_snapshots.append(self.collector.system_snapshot())

        # Persist a benchmark run if requested.
        if request.persist_path:
            self._persist_run(request.persist_path, run_id, name, all_results)

        finished_dt = datetime.now(timezone.utc)
        summary = self._build_summary(all_results, started_dt, finished_dt)

        response = BenchmarkResponse(
            run_id=run_id,
            suite=suite,
            name=name,
            summary=summary,
            results=all_results,
            system_snapshots=system_snapshots,
            notes=notes,
            config={
                "concurrency": concurrency,
                "iterations": iterations,
                "warmup": warmup,
                "cost_per_1k_input_tokens": request.cost_per_1k_input_tokens,
                "cost_per_1k_output_tokens": request.cost_per_1k_output_tokens,
                "cost_per_retrieval": request.cost_per_retrieval,
            },
        )

        return response

    # ─── Reporting helpers ──────────────────────────────────────────

    def latency_report(self, response: BenchmarkResponse) -> Mapping[str, Any]:
        return self.reporter.latency_report(response)

    def cost_report(self, response: BenchmarkResponse) -> Mapping[str, Any]:
        return self.reporter.cost_report(response)

    def agent_performance_report(self, response: BenchmarkResponse) -> Mapping[str, Any]:
        return self.reporter.agent_performance_report(response)

    def system_performance_report(self, response: BenchmarkResponse) -> Mapping[str, Any]:
        return self.reporter.system_performance_report(response)

    def write_reports(self, response: BenchmarkResponse, out_dir: str) -> Dict[str, str]:
        return self.reporter.write_all(response, out_dir)

    # ─── Internals ──────────────────────────────────────────────────

    def _build_summary(
        self,
        results: Sequence[OperationResult],
        started_at: datetime,
        finished_at: datetime,
    ) -> BenchmarkSummary:
        total = len(results)
        success = sum(1 for r in results if r.success)
        failed = total - success
        latencies = [r.latency.total_ms for r in results]
        stats = compute_latency_stats(latencies)
        # Per-kind latency stats
        by_kind: Dict[str, List[float]] = {}
        for r in results:
            by_kind.setdefault(r.kind.value, []).append(r.latency.total_ms)
        latency_by_kind = {k: compute_latency_stats(v) for k, v in by_kind.items()}
        wall = max(1e-9, (finished_at - started_at).total_seconds())
        throughput = total / wall
        cost = compute_cost_summary(
            (r.tokens for r in results),
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            cost_per_retrieval=0.0,
            successful=success or 1,
            total=total or 1,
        )
        # Re-compute with actual cost factors (compute_cost_summary was given 0s; redo properly below).
        cost = compute_cost_summary(
            (r.tokens for r in results),
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.00060,
            cost_per_retrieval=0.00001,
            successful=success or 1,
            total=total or 1,
        )
        return BenchmarkSummary(
            total_operations=total,
            successful=success,
            failed=failed,
            error_rate=(failed / total) if total else 0.0,
            throughput_ops_per_sec=throughput,
            wall_clock_ms=wall * 1000.0,
            latency=stats,
            latency_by_kind=latency_by_kind,
            cost=cost,
            started_at=started_at,
            finished_at=finished_at,
        )

    def _build_scenario(self, sc_dict: Mapping[str, Any], idx: int) -> PerformanceScenario:
        name = str(sc_dict.get("name", f"scenario-{idx}"))
        kind_str = str(sc_dict.get("kind", "other"))
        kind = OperationKind(kind_str) if kind_str in {k.value for k in OperationKind} else OperationKind.OTHER
        fn = sc_dict.get("fn") or _noop_async
        if not callable(fn):
            raise TypeError(f"scenario[{idx}].fn is not callable")
        return PerformanceScenario(
            name=name,
            fn=fn,
            kind=kind,
            cost_per_1k_input_tokens=float(sc_dict.get("cost_per_1k_input_tokens", 0.00015)),
            cost_per_1k_output_tokens=float(sc_dict.get("cost_per_1k_output_tokens", 0.00060)),
            cost_per_retrieval=float(sc_dict.get("cost_per_retrieval", 0.00001)),
        )

    def _persist_run(
        self,
        path: str,
        run_id: str,
        name: str,
        results: Sequence[OperationResult],
    ) -> None:
        import json

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {
            "run_id": run_id,
            "name": name,
            "written_at": datetime.now(timezone.utc).isoformat(),
            "results": [r.model_dump(mode="json") for r in results],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)


# ─── Singleton wiring ───────────────────────────────────────────────

_service_lock = asyncio.Lock()
_service_singleton: Optional[BenchmarkService] = None


def get_benchmark_service() -> BenchmarkService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = BenchmarkService()
    return _service_singleton


def reset_benchmark_service() -> None:
    """Test helper: clear the singleton (call between tests)."""
    global _service_singleton
    _service_singleton = None


# ─── Helpers ────────────────────────────────────────────────────────

def _classify_target(target: Callable[[], Awaitable[Mapping[str, Any]]]) -> OperationKind:
    name = getattr(target, "__name__", "")
    if "retrieval" in name:
        return OperationKind.RETRIEVAL
    if "answer" in name:
        return OperationKind.ANSWER
    if "agent" in name:
        return OperationKind.AGENT
    if "ingest" in name:
        return OperationKind.INGEST
    return OperationKind.OTHER
