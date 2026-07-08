"""Pydantic schemas for the M10.5 benchmark platform."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field


class OperationKind(str, Enum):
    """What kind of operation a measurement represents."""

    RETRIEVAL = "retrieval"
    ANSWER = "answer"
    AGENT = "agent"
    INGEST = "ingest"
    OTHER = "other"


class BenchmarkSuite(str, Enum):
    """Pre-defined benchmark suites with sensible default scenarios."""

    SMOKE = "smoke"  # 1 op, no concurrency
    QUICK = "quick"  # 5 ops, 1 worker
    STANDARD = "standard"  # 25 ops, 4 workers
    FULL = "full"  # 100 ops, 8 workers


# ─── Single-operation measurement ──────────────────────────────────────


class LatencyMetric(BaseModel):
    """A single latency measurement in milliseconds."""

    model_config = ConfigDict(extra="forbid")
    total_ms: float = Field(..., ge=0)
    server_ms: Optional[float] = Field(default=None, ge=0)
    queue_ms: Optional[float] = Field(default=None, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TokenUsage(BaseModel):
    """Token accounting for a single operation."""

    model_config = ConfigDict(extra="forbid")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    embedding_tokens: int = Field(default=0, ge=0)
    retrieval_units: int = Field(default=0, ge=0)


class MemoryMetric(BaseModel):
    """Resident-set / heap snapshot."""

    model_config = ConfigDict(extra="forbid")
    rss_mb: float = Field(..., ge=0)
    heap_mb: Optional[float] = Field(default=None, ge=0)
    traced_mb: Optional[float] = Field(default=None, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OperationResult(BaseModel):
    """A single benchmarked operation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    kind: OperationKind
    success: bool
    error: Optional[str] = None
    latency: LatencyMetric
    memory: Optional[MemoryMetric] = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    cost_units: float = Field(default=0.0, ge=0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── System snapshot ──────────────────────────────────────────────────


class SystemSnapshot(BaseModel):
    """Process- and host-level resource snapshot."""

    model_config = ConfigDict(extra="forbid")

    process_rss_mb: float = Field(..., ge=0)
    process_vms_mb: float = Field(..., ge=0)
    process_cpu_percent: float = Field(default=0.0, ge=0)
    process_threads: int = Field(default=0, ge=0)
    host_cpu_percent: Optional[float] = Field(default=None, ge=0)
    host_memory_percent: Optional[float] = Field(default=None, ge=0)
    host_loadavg: Optional[List[float]] = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Aggregate statistics ─────────────────────────────────────────────


class LatencyStats(BaseModel):
    """Latency distribution statistics for a set of operations."""

    model_config = ConfigDict(extra="forbid")
    count: int = Field(..., ge=0)
    min_ms: float = Field(..., ge=0)
    max_ms: float = Field(..., ge=0)
    mean_ms: float = Field(..., ge=0)
    median_ms: float = Field(..., ge=0)
    p50_ms: float = Field(..., ge=0)
    p90_ms: float = Field(..., ge=0)
    p95_ms: float = Field(..., ge=0)
    p99_ms: float = Field(..., ge=0)
    stddev_ms: float = Field(default=0.0, ge=0)


class CostSummary(BaseModel):
    """Aggregate cost analysis for a benchmark run."""

    model_config = ConfigDict(extra="forbid")
    total_cost_units: float = Field(default=0.0, ge=0)
    total_input_tokens: int = Field(default=0, ge=0)
    total_output_tokens: int = Field(default=0, ge=0)
    total_retrieval_units: int = Field(default=0, ge=0)
    cost_per_operation: float = Field(default=0.0, ge=0)
    cost_per_success: float = Field(default=0.0, ge=0)
    currency: str = "USD"


# ─── Request / response shapes ────────────────────────────────────────


class BenchmarkRequest(BaseModel):
    """Run a benchmark."""

    model_config = ConfigDict(extra="forbid")

    suite: BenchmarkSuite = BenchmarkSuite.STANDARD
    name: Optional[str] = None
    # If empty, the suite defaults are used.
    scenarios: List[Dict[str, Any]] = Field(default_factory=list)
    concurrency: Optional[int] = Field(default=None, ge=1, le=128)
    iterations: Optional[int] = Field(default=None, ge=1, le=10_000)
    cost_per_1k_input_tokens: float = Field(default=0.00015, ge=0)
    cost_per_1k_output_tokens: float = Field(default=0.00060, ge=0)
    cost_per_retrieval: float = Field(default=0.00001, ge=0)
    persist_path: Optional[str] = None


class BenchmarkSummary(BaseModel):
    """Top-level aggregate stats for a benchmark run."""

    model_config = ConfigDict(extra="forbid")

    total_operations: int = Field(..., ge=0)
    successful: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    error_rate: float = Field(..., ge=0, le=1)
    throughput_ops_per_sec: float = Field(..., ge=0)
    wall_clock_ms: float = Field(..., ge=0)
    latency: LatencyStats
    latency_by_kind: Dict[str, LatencyStats] = Field(default_factory=dict)
    cost: CostSummary
    started_at: datetime
    finished_at: datetime


class BenchmarkResponse(BaseModel):
    """Full benchmark response including per-operation results."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    suite: BenchmarkSuite
    name: str
    summary: BenchmarkSummary
    results: List[OperationResult]
    system_snapshots: List[SystemSnapshot] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    config: Mapping[str, Any] = Field(default_factory=dict)
