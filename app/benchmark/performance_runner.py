"""Single-shot performance runner for the M10.5 benchmark platform.

A "scenario" describes a function to time and a way to count tokens. The
runner times the function, records memory and tokens, computes a cost,
and returns a structured :class:`ScenarioResult`.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from app.benchmark.metrics_collector import MetricsCollector
from app.benchmark.models import (
    OperationKind,
    OperationResult,
)


@dataclass(frozen=True)
class PerformanceScenario:
    """A named operation with optional token accounting and metadata."""

    name: str
    fn: Callable[..., Any]
    kind: OperationKind = OperationKind.OTHER
    # Optional async hook returning TokenUsage-shaped data.
    token_provider: Optional[Callable[[Any], Mapping[str, int]]] = None
    metadata_provider: Optional[Callable[[Any, OperationResult], None]] = None
    cost_per_1k_input_tokens: float = 0.00015
    cost_per_1k_output_tokens: float = 0.00060
    cost_per_retrieval: float = 0.00001

    def __post_init__(self) -> None:
        if not callable(self.fn):
            raise TypeError(
                f"PerformanceScenario.fn must be callable, got {type(self.fn)!r}"
            )


@dataclass
class ScenarioResult:
    """A single timed scenario run, plus its :class:`OperationResult`."""

    scenario: PerformanceScenario
    operation: OperationResult
    duration_ms: float


class PerformanceRunner:
    """Run :class:`PerformanceScenario` instances and capture metrics."""

    def __init__(self, collector: Optional[MetricsCollector] = None) -> None:
        self._collector = collector or MetricsCollector()

    @property
    def collector(self) -> MetricsCollector:
        return self._collector

    async def run(
        self, scenario: PerformanceScenario, *args: Any, **kwargs: Any
    ) -> ScenarioResult:
        """Execute the scenario, measuring latency, memory, tokens, cost."""
        if not callable(scenario.fn):
            raise TypeError("scenario.fn is not callable")
        start = time.perf_counter()
        result: Any = None
        error: Optional[str] = None
        success = True
        try:
            if inspect.iscoroutinefunction(scenario.fn):
                result = await scenario.fn(*args, **kwargs)
            else:
                result = await asyncio.to_thread(scenario.fn, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            success = False
            error = f"{type(exc).__name__}: {exc}"
        end = time.perf_counter()
        total_ms = (end - start) * 1000.0

        tokens = self._extract_tokens(scenario, result)
        cost = self._collector.compute_cost(
            tokens,
            scenario.cost_per_1k_input_tokens,
            scenario.cost_per_1k_output_tokens,
            scenario.cost_per_retrieval,
        )
        memory = self._collector.memory_snapshot()

        op = OperationResult(
            id=str(uuid.uuid4()),
            name=scenario.name,
            kind=scenario.kind,
            success=success,
            error=error,
            latency=__import__(
                "app.benchmark.models", fromlist=["LatencyMetric"]
            ).LatencyMetric(total_ms=total_ms),
            memory=memory,
            tokens=tokens,
            cost_units=cost,
        )

        if scenario.metadata_provider is not None:
            try:
                scenario.metadata_provider(result, op)
            except Exception:  # pragma: no cover - non-fatal
                pass

        return ScenarioResult(scenario=scenario, operation=op, duration_ms=total_ms)

    def _extract_tokens(self, scenario: PerformanceScenario, result: Any) -> Any:
        if scenario.token_provider is None:
            return self._collector.compute_tokens()
        try:
            raw = scenario.token_provider(result) or {}
            return self._collector.compute_tokens(
                input_tokens=int(raw.get("input_tokens", 0)),
                output_tokens=int(raw.get("output_tokens", 0)),
                embedding_tokens=int(raw.get("embedding_tokens", 0)),
                retrieval_units=int(raw.get("retrieval_units", 0)),
            )
        except Exception:
            return self._collector.compute_tokens()
