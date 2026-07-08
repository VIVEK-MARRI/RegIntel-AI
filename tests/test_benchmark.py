"""Tests for the M10.5 benchmark platform.

Covers:
* MetricsCollector: stats, memory snapshots, cost computation
* PerformanceRunner: timing, success + failure paths, tokens
* LoadTester: concurrency, throughput, error rate, async targets
* BenchmarkService: end-to-end run + report generation
* Reporter: latency, cost, agent, system reports + markdown / html
* CLI: `run` and `report` subcommands, `--quick` shortcut
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from typing import Any, AsyncIterator, Dict, List, Mapping

import pytest

from app.benchmark import (
    BenchmarkRequest,
    BenchmarkResponse,
    BenchmarkService,
    BenchmarkSuite,
    LatencyMetric,
    LoadTestConfig,
    LoadTestResult,
    LoadTester,
    MemoryMetric,
    MetricsCollector,
    OperationKind,
    OperationResult,
    PerformanceRunner,
    PerformanceScenario,
    Reporter,
    TokenUsage,
    get_benchmark_service,
    reset_benchmark_service,
)
from app.benchmark.benchmark_service import _classify_target
from app.benchmark.cli import main as cli_main
from app.benchmark.metrics_collector import (
    compute_cost_summary,
    compute_latency_stats,
)
from app.benchmark.reporter import Reporter as _Reporter


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_service_singleton() -> None:
    reset_benchmark_service()
    yield
    reset_benchmark_service()


@pytest.fixture
def collector() -> MetricsCollector:
    return MetricsCollector()


# ─── MetricsCollector ──────────────────────────────────────────────


class TestMetricsCollector:
    def test_compute_latency_stats_empty(self) -> None:
        stats = compute_latency_stats([])
        assert stats.count == 0
        assert stats.min_ms == stats.max_ms == 0.0

    def test_compute_latency_stats_distribution(self) -> None:
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        stats = compute_latency_stats(values)
        assert stats.count == 10
        assert stats.min_ms == 10
        assert stats.max_ms == 100
        assert stats.median_ms == 55
        assert stats.p50_ms == 55
        assert 30 <= stats.p90_ms <= 100
        assert stats.stddev_ms > 0

    def test_compute_cost_summary(self) -> None:
        usages = [
            TokenUsage(input_tokens=1000, output_tokens=500, retrieval_units=10),
            TokenUsage(input_tokens=2000, output_tokens=0, retrieval_units=5),
        ]
        cost = compute_cost_summary(
            usages,
            cost_per_1k_input=0.001,
            cost_per_1k_output=0.002,
            cost_per_retrieval=0.0001,
            successful=2,
            total=2,
        )
        # 3k in = 0.003, 0.5k out = 0.001, 15 retrieval = 0.0015 => 0.0055
        assert cost.total_cost_units == pytest.approx(0.0055, rel=1e-6)
        assert cost.cost_per_operation == pytest.approx(0.00275, rel=1e-6)
        assert cost.total_input_tokens == 3000
        assert cost.total_output_tokens == 500

    def test_compute_tokens_clamps_to_zero(self, collector: MetricsCollector) -> None:
        t = collector.compute_tokens(input_tokens=-5, output_tokens=10)
        assert t.input_tokens == 0
        assert t.output_tokens == 10

    def test_memory_snapshot(self, collector: MetricsCollector) -> None:
        snap = collector.memory_snapshot()
        assert isinstance(snap, MemoryMetric)
        assert snap.rss_mb >= 0

    def test_system_snapshot(self, collector: MetricsCollector) -> None:
        snap = collector.system_snapshot()
        assert snap.process_rss_mb >= 0
        assert snap.process_threads >= 0

    def test_time_context_manager_measures(self, collector: MetricsCollector) -> None:
        with collector.time() as finalise:
            pass
        metric = finalise()
        assert metric.total_ms >= 0

    def test_time_context_manager_with_work(self, collector: MetricsCollector) -> None:
        with collector.time() as finalise:
            total = 0
            for i in range(1000):
                total += i
            assert total > 0
        metric = finalise()
        assert metric.total_ms >= 0  # measured even on clean exit


# ─── PerformanceRunner ─────────────────────────────────────────────


class TestPerformanceRunner:
    @pytest.mark.asyncio
    async def test_run_synchronous_function(self) -> None:
        runner = PerformanceRunner()

        def add(a: int, b: int) -> int:
            return a + b

        sc = PerformanceScenario(name="add", fn=add, kind=OperationKind.OTHER)
        result = await runner.run(sc, 2, 3)
        assert result.operation.success is True
        assert result.operation.latency.total_ms >= 0
        assert result.operation.tokens.input_tokens == 0
        assert result.operation.cost_units == 0

    @pytest.mark.asyncio
    async def test_run_async_function(self) -> None:
        runner = PerformanceRunner()

        async def fetch() -> Dict[str, int]:
            await asyncio.sleep(0.001)
            return {"input_tokens": 100, "output_tokens": 50, "retrieval_units": 1}

        sc = PerformanceScenario(
            name="fetch",
            fn=fetch,
            kind=OperationKind.RETRIEVAL,
            token_provider=lambda r: r,
        )
        result = await runner.run(sc)
        assert result.operation.success is True
        assert result.operation.tokens.input_tokens == 100
        assert result.operation.cost_units > 0
        assert result.operation.memory is not None

    @pytest.mark.asyncio
    async def test_run_records_errors(self) -> None:
        runner = PerformanceRunner()

        def boom() -> None:
            raise RuntimeError("kaboom")

        sc = PerformanceScenario(name="boom", fn=boom)
        result = await runner.run(sc)
        assert result.operation.success is False
        assert "kaboom" in (result.operation.error or "")

    @pytest.mark.asyncio
    async def test_metadata_provider_receives_result(self) -> None:
        runner = PerformanceRunner()

        def double(x: int) -> int:
            return x * 2

        captured: List[Dict[str, Any]] = []

        def provider(result: Any, op: OperationResult) -> None:
            captured.append({"result": result, "id": op.id})

        sc = PerformanceScenario(
            name="double",
            fn=double,
            metadata_provider=provider,
        )
        await runner.run(sc, 21)
        assert captured and captured[0]["result"] == 42


# ─── LoadTester ────────────────────────────────────────────────────


class TestLoadTester:
    @pytest.mark.asyncio
    async def test_runs_all_iterations(self) -> None:
        async def target() -> Dict[str, int]:
            await asyncio.sleep(0.001)
            return {"input_tokens": 5, "output_tokens": 5}

        cfg = LoadTestConfig(
            name="t",
            target=target,
            concurrency=2,
            iterations=10,
        )
        result = await LoadTester().run(cfg)
        assert result.total == 10
        assert result.success == 10
        assert result.errors == 0
        assert result.throughput_ops_per_sec > 0
        assert result.latency.count == 10
        assert result.latency.p99_ms >= result.latency.p50_ms

    @pytest.mark.asyncio
    async def test_records_failures(self) -> None:
        async def target(i: int) -> int:
            await asyncio.sleep(0.001)
            if i % 2 == 0:
                raise ValueError("bad")
            return i

        cfg = LoadTestConfig(
            name="t",
            target=target,
            concurrency=2,
            iterations=10,
            arg_provider=lambda i: (i,),
        )
        result = await LoadTester().run(cfg)
        assert result.total == 10
        assert result.errors == 5
        assert result.success == 5
        assert result.error_rate == 0.5

    @pytest.mark.asyncio
    async def test_warmup_runs_unmeasured(self) -> None:
        async def target() -> int:
            return 1

        cfg = LoadTestConfig(
            name="t", target=target, concurrency=1, iterations=3, warmup=2
        )
        result = await LoadTester().run(cfg)
        assert result.total == 3  # warmup not counted

    @pytest.mark.asyncio
    async def test_rejects_sync_target(self) -> None:
        def target() -> int:
            return 1

        cfg = LoadTestConfig(name="t", target=target, concurrency=1, iterations=1)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            await LoadTester().run(cfg)

    @pytest.mark.asyncio
    async def test_timeout_marks_failure(self) -> None:
        async def target() -> int:
            await asyncio.sleep(1.0)
            return 1

        cfg = LoadTestConfig(
            name="t", target=target, concurrency=1, iterations=1, timeout_seconds=0.05
        )
        result = await LoadTester().run(cfg)
        assert result.errors == 1
        assert result.results[0].error is not None


# ─── BenchmarkService ──────────────────────────────────────────────


class TestBenchmarkService:
    @pytest.mark.asyncio
    async def test_runs_smoke_suite(self) -> None:
        svc = BenchmarkService()
        req = BenchmarkRequest(suite=BenchmarkSuite.SMOKE, name="smoke")
        response = await svc.run(req)
        assert response.summary.total_operations >= 4  # one per kind
        assert response.summary.error_rate == 0.0
        assert response.run_id
        assert response.summary.latency.count >= 4
        # Latency by kind should cover all four synthetic kinds.
        assert set(response.summary.latency_by_kind.keys()) >= {
            OperationKind.RETRIEVAL.value,
            OperationKind.ANSWER.value,
            OperationKind.AGENT.value,
            OperationKind.INGEST.value,
        }

    @pytest.mark.asyncio
    async def test_writes_reports_to_disk(self) -> None:
        svc = BenchmarkService()
        req = BenchmarkRequest(suite=BenchmarkSuite.SMOKE, name="smoke")
        response = await svc.run(req)
        with tempfile.TemporaryDirectory() as d:
            written = svc.write_reports(response, d)
            assert set(written.keys()) == {
                "latency_report.json",
                "cost_report.json",
                "agent_performance_report.json",
                "system_performance_report.json",
                "run.json",
                "summary.md",
                "summary.html",
            }
            for name, path in written.items():
                assert os.path.exists(path)
                if name.endswith(".json"):
                    with open(path) as fh:
                        data = json.load(fh)
                    assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_custom_target_registry(self) -> None:
        svc = BenchmarkService()

        async def custom() -> Dict[str, int]:
            await asyncio.sleep(0.002)
            return {"input_tokens": 50, "output_tokens": 25, "retrieval_units": 1}

        # Replace one of the defaults.
        svc.register_target(OperationKind.AGENT, custom)
        req = BenchmarkRequest(suite=BenchmarkSuite.QUICK, name="custom")
        response = await svc.run(req)
        agent_results = [r for r in response.results if r.kind == OperationKind.AGENT]
        assert agent_results
        assert all(r.tokens.input_tokens == 50 for r in agent_results)

    @pytest.mark.asyncio
    async def test_singleton_returns_same_instance(self) -> None:
        a = get_benchmark_service()
        b = get_benchmark_service()
        assert a is b


# ─── Reporter ──────────────────────────────────────────────────────


class TestReporter:
    @pytest.mark.asyncio
    async def test_all_reports(self) -> None:
        svc = BenchmarkService()
        response = await svc.run(BenchmarkRequest(suite=BenchmarkSuite.SMOKE, name="r"))
        reporter = Reporter()

        latency = reporter.latency_report(response)
        assert latency["report"] == "latency"
        assert "by_kind" in latency
        assert latency["summary"]["count"] >= 4

        cost = reporter.cost_report(response)
        assert cost["report"] == "cost"
        assert "total_cost_units" in cost["summary"]

        agent = reporter.agent_performance_report(response)
        assert agent["report"] == "agent_performance"
        assert isinstance(agent["leaderboard"], list)
        # Leaderboard is sorted descending by composite_score
        scores = [p.get("composite_score", 0.0) for p in agent["leaderboard"]]
        assert scores == sorted(scores, reverse=True)

        system = reporter.system_performance_report(response)
        assert system["report"] == "system_performance"
        assert "process" in system
        assert "host" in system
        assert "rss_mb" in system["process"]
        assert "snapshots" in system["process"]

    def test_markdown_summary(self) -> None:
        response = BenchmarkResponse.model_validate(_sample_run())
        md = Reporter().render_markdown_summary(response)
        assert "Benchmark" in md
        assert "Latency by kind" in md
        assert "p99" in md

    def test_html_summary(self) -> None:
        response = BenchmarkResponse.model_validate(_sample_run())
        html = Reporter().render_html_summary(response)
        assert "<table" in html
        assert "Latency by kind" in html


# ─── CLI ───────────────────────────────────────────────────────────


class TestCli:
    def test_quick_run(self, tmp_path, capsys) -> None:
        out = tmp_path / "bench.json"
        rc = cli_main(["--quick", "--output", str(out)])
        captured = capsys.readouterr()
        assert rc == 0
        assert out.exists()
        with open(out) as fh:
            data = json.load(fh)
        assert data["suite"] == "quick"
        assert "suite=quick" in captured.out

    def test_report_subcommand(self, tmp_path) -> None:
        run = tmp_path / "run.json"
        rc = cli_main(["--quick", "--output", str(run)])
        assert rc == 0
        out_dir = tmp_path / "reports"
        rc = cli_main(["report", "--input", str(run), "--out-dir", str(out_dir)])
        assert rc == 0
        for f in [
            "latency_report.json",
            "cost_report.json",
            "agent_performance_report.json",
            "system_performance_report.json",
            "summary.md",
            "summary.html",
        ]:
            assert (out_dir / f).exists()


# ─── Helpers ────────────────────────────────────────────────────────


def _sample_run() -> Dict[str, Any]:
    """A minimal BenchmarkResponse-shaped payload for the report tests."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return {
        "run_id": "abc",
        "suite": "smoke",
        "name": "sample",
        "summary": {
            "total_operations": 2,
            "successful": 2,
            "failed": 0,
            "error_rate": 0.0,
            "throughput_ops_per_sec": 100.0,
            "wall_clock_ms": 20.0,
            "latency": {
                "count": 2,
                "min_ms": 1.0,
                "max_ms": 5.0,
                "mean_ms": 3.0,
                "median_ms": 3.0,
                "p50_ms": 3.0,
                "p90_ms": 4.5,
                "p95_ms": 4.75,
                "p99_ms": 4.95,
                "stddev_ms": 2.0,
            },
            "latency_by_kind": {
                "retrieval": {
                    "count": 1,
                    "min_ms": 1.0,
                    "max_ms": 1.0,
                    "mean_ms": 1.0,
                    "median_ms": 1.0,
                    "p50_ms": 1.0,
                    "p90_ms": 1.0,
                    "p95_ms": 1.0,
                    "p99_ms": 1.0,
                    "stddev_ms": 0.0,
                },
                "answer": {
                    "count": 1,
                    "min_ms": 5.0,
                    "max_ms": 5.0,
                    "mean_ms": 5.0,
                    "median_ms": 5.0,
                    "p50_ms": 5.0,
                    "p90_ms": 5.0,
                    "p95_ms": 5.0,
                    "p99_ms": 5.0,
                    "stddev_ms": 0.0,
                },
            },
            "cost": {
                "total_cost_units": 0.001,
                "total_input_tokens": 1000,
                "total_output_tokens": 500,
                "total_retrieval_units": 5,
                "cost_per_operation": 0.0005,
                "cost_per_success": 0.0005,
                "currency": "USD",
            },
            "started_at": now,
            "finished_at": now,
        },
        "results": [
            {
                "id": "1",
                "name": "retrieval",
                "kind": "retrieval",
                "success": True,
                "error": None,
                "latency": {
                    "total_ms": 1.0,
                    "server_ms": None,
                    "queue_ms": None,
                    "timestamp": now,
                },
                "memory": {
                    "rss_mb": 100,
                    "heap_mb": None,
                    "traced_mb": None,
                    "timestamp": now,
                },
                "tokens": {
                    "input_tokens": 100,
                    "output_tokens": 0,
                    "embedding_tokens": 0,
                    "retrieval_units": 1,
                },
                "cost_units": 0.0001,
                "metadata": {},
                "timestamp": now,
            },
            {
                "id": "2",
                "name": "answer",
                "kind": "answer",
                "success": True,
                "error": None,
                "latency": {
                    "total_ms": 5.0,
                    "server_ms": None,
                    "queue_ms": None,
                    "timestamp": now,
                },
                "memory": {
                    "rss_mb": 110,
                    "heap_mb": None,
                    "traced_mb": None,
                    "timestamp": now,
                },
                "tokens": {
                    "input_tokens": 200,
                    "output_tokens": 100,
                    "embedding_tokens": 0,
                    "retrieval_units": 2,
                },
                "cost_units": 0.0005,
                "metadata": {},
                "timestamp": now,
            },
        ],
        "system_snapshots": [],
        "notes": [],
        "config": {},
    }
