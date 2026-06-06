"""RegIntel AI — Benchmark & Performance Platform (M10.5).

Public surface:

* :class:`BenchmarkService` — orchestrator
* :class:`PerformanceRunner` — single-shot performance measurement
* :class:`LoadTester` — concurrent synthetic load generation
* :class:`MetricsCollector` — low-level metrics (latency, memory, tokens, cost)
* :class:`Reporter` — latency / cost / agent / system reports
* :func:`register_routes` — FastAPI mount point
"""

from app.benchmark.benchmark_service import (
    BenchmarkService,
    get_benchmark_service,
    reset_benchmark_service,
)
from app.benchmark.load_tester import LoadTestConfig, LoadTester, LoadTestResult
from app.benchmark.metrics_collector import (
    LatencyMetric,
    MemoryMetric,
    MetricsCollector,
    TokenUsage,
)
from app.benchmark.models import (
    BenchmarkRequest,
    BenchmarkResponse,
    BenchmarkSuite,
    OperationKind,
    OperationResult,
    SystemSnapshot,
)
from app.benchmark.performance_runner import (
    PerformanceRunner,
    PerformanceScenario,
    ScenarioResult,
)
from app.benchmark.reporter import Reporter

__all__ = [
    "BenchmarkRequest",
    "BenchmarkResponse",
    "BenchmarkService",
    "BenchmarkSuite",
    "LatencyMetric",
    "LoadTestConfig",
    "LoadTester",
    "LoadTestResult",
    "MemoryMetric",
    "MetricsCollector",
    "OperationKind",
    "OperationResult",
    "PerformanceRunner",
    "PerformanceScenario",
    "Reporter",
    "ScenarioResult",
    "SystemSnapshot",
    "TokenUsage",
    "get_benchmark_service",
    "reset_benchmark_service",
]
