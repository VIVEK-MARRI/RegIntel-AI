"""Concurrent load tester for the M10.5 benchmark platform.

Generates synthetic traffic against an async function, records latency /
throughput / error rates, and exposes a structured :class:`LoadTestResult`.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, List, Mapping, Optional

from app.benchmark.metrics_collector import (
    MetricsCollector,
    compute_latency_stats,
)
from app.benchmark.models import (
    LatencyMetric,
    LatencyStats,
    OperationKind,
    OperationResult,
    SystemSnapshot,
    TokenUsage,
)


@dataclass
class LoadTestConfig:
    """Configuration for a load test run."""

    name: str
    target: Callable[..., Awaitable[Any]]
    concurrency: int = 4
    iterations: int = 25
    kind: OperationKind = OperationKind.OTHER
    timeout_seconds: float = 60.0
    warmup: int = 0
    # Optional token / cost parameters
    cost_per_1k_input_tokens: float = 0.00015
    cost_per_1k_output_tokens: float = 0.00060
    cost_per_retrieval: float = 0.00001
    # Per-iteration arguments
    arg_provider: Optional[Callable[[int], Iterable[Any]]] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class LoadTestResult:
    """Outcome of a load test run."""

    config: LoadTestConfig
    results: List[OperationResult]
    started_at: float
    finished_at: float
    latency: LatencyStats
    errors: int
    success: int
    system_snapshots: List[SystemSnapshot]
    notes: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def throughput_ops_per_sec(self) -> float:
        wall = max(1e-9, self.finished_at - self.started_at)
        return self.total / wall

    @property
    def error_rate(self) -> float:
        return (self.errors / self.total) if self.total else 0.0


class LoadTester:
    """Runs a callable concurrently and records per-iteration metrics."""

    def __init__(self, collector: Optional[MetricsCollector] = None) -> None:
        self._collector = collector or MetricsCollector()

    @property
    def collector(self) -> MetricsCollector:
        return self._collector

    async def run(self, config: LoadTestConfig) -> LoadTestResult:
        if config.concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if config.iterations < 1:
            raise ValueError("iterations must be >= 1")
        if not inspect.iscoroutinefunction(config.target):
            raise TypeError("LoadTester requires an async target")

        # Warmup (not measured).
        for i in range(config.warmup):
            args = self._args_for(config, i)
            try:
                await asyncio.wait_for(config.target(*args), timeout=config.timeout_seconds)
            except Exception:
                pass

        semaphore = asyncio.Semaphore(config.concurrency)
        results: List[OperationResult] = []
        system_snapshots: List[SystemSnapshot] = []
        started = time.perf_counter()
        lock = asyncio.Lock()

        async def _one(idx: int) -> None:
            async with semaphore:
                if not results:
                    system_snapshots.append(self._collector.system_snapshot())
                args = self._args_for(config, idx)
                t0 = time.perf_counter()
                success = True
                error: Optional[str] = None
                result: Any = None
                try:
                    result = await asyncio.wait_for(
                        config.target(*args), timeout=config.timeout_seconds
                    )
                except Exception as exc:  # noqa: BLE001
                    success = False
                    error = f"{type(exc).__name__}: {exc}"
                t1 = time.perf_counter()
                op = OperationResult(
                    id=str(uuid.uuid4()),
                    name=f"{config.name}#{idx}",
                    kind=config.kind,
                    success=success,
                    error=error,
                    latency=LatencyMetric(total_ms=(t1 - t0) * 1000.0),
                    memory=self._collector.memory_snapshot(),
                    tokens=self._extract_tokens(result),
                    cost_units=self._collector.compute_cost(
                        self._extract_tokens(result),
                        config.cost_per_1k_input_tokens,
                        config.cost_per_1k_output_tokens,
                        config.cost_per_retrieval,
                    ),
                    metadata={"config": dict(config.metadata), "iteration": idx},
                )
                async with lock:
                    results.append(op)
                if idx == config.iterations - 1:
                    system_snapshots.append(self._collector.system_snapshot())

        await asyncio.gather(*(_one(i) for i in range(config.iterations)))
        finished = time.perf_counter()

        latencies = [op.latency.total_ms for op in results]
        stats = compute_latency_stats(latencies)
        errors = sum(1 for r in results if not r.success)
        return LoadTestResult(
            config=config,
            results=results,
            started_at=started,
            finished_at=finished,
            latency=stats,
            errors=errors,
            success=len(results) - errors,
            system_snapshots=system_snapshots,
        )

    def _args_for(self, config: LoadTestConfig, idx: int) -> tuple:
        if config.arg_provider is None:
            return ()
        try:
            return tuple(config.arg_provider(idx))
        except Exception:
            return ()

    def _extract_tokens(self, result: Any) -> TokenUsage:
        if isinstance(result, Mapping):  # type: ignore[arg-type]
            return self._collector.compute_tokens(
                input_tokens=int(result.get("input_tokens", 0)),
                output_tokens=int(result.get("output_tokens", 0)),
                embedding_tokens=int(result.get("embedding_tokens", 0)),
                retrieval_units=int(result.get("retrieval_units", 0)),
            )
        return self._collector.compute_tokens()
