"""Observability primitives for the Hybrid Search API Layer.

Provides lightweight, dependency-free helpers for:

* API latency tracking (per-request timer with context manager support).
* In-process counters for request volume, error rate, strategy usage and
  reranker usage. These are exposed through ``/api/v1/retrieval/metrics``
  and the OpenAPI documentation.
* Structured-logging enrichment (request_id correlation, latency fields).

The design intentionally avoids pulling in an external metrics dependency
(Prometheus client, OpenTelemetry, etc.) so the platform remains deployable
in any environment. Counters are process-local and reset on restart, which
is acceptable for a single-instance deployment and as a baseline for
production observability that the analytics layer already provides.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)


# ─── Request Context ─────────────────────────────────────────────────────────


@dataclass
class RequestContext:
    """Per-request observability context."""

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    endpoint: str = ""
    strategy: str = ""
    started_at: float = field(default_factory=time.perf_counter)
    finished_at: Optional[float] = None
    error: Optional[str] = None
    rerank_used: bool = False

    @property
    def latency_ms(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.perf_counter()
        return (end - self.started_at) * 1000.0

    def finish(self, error: Optional[str] = None) -> None:
        self.finished_at = time.perf_counter()
        self.error = error

    def to_log_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "endpoint": self.endpoint,
            "strategy": self.strategy,
            "latency_ms": round(self.latency_ms, 3),
            "error": self.error,
            "rerank_used": self.rerank_used,
        }


# ─── Metric Counters ─────────────────────────────────────────────────────────


@dataclass
class APIMetrics:
    """Process-wide counters for the hybrid search API."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    strategy_counts: Dict[str, int] = field(default_factory=dict)
    reranker_used: int = 0
    reranker_skipped: int = 0
    endpoint_counts: Dict[str, int] = field(default_factory=dict)
    error_counts: Dict[str, int] = field(default_factory=dict)
    last_reset_at: float = field(default_factory=time.time)

    def record_request(
        self,
        endpoint: str,
        strategy: str,
        latency_ms: float,
        success: bool,
        rerank_used: bool = False,
    ) -> None:
        self.total_requests += 1
        self.total_latency_ms += latency_ms
        self.endpoint_counts[endpoint] = self.endpoint_counts.get(endpoint, 0) + 1
        self.strategy_counts[strategy] = self.strategy_counts.get(strategy, 0) + 1
        if rerank_used:
            self.reranker_used += 1
        else:
            self.reranker_skipped += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1

    def record_error(self, error_type: str) -> None:
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1

    def snapshot(self) -> Dict[str, Any]:
        avg_latency = (
            self.total_latency_ms / self.total_requests
            if self.total_requests > 0
            else 0.0
        )
        error_rate = (
            self.failed_requests / self.total_requests
            if self.total_requests > 0
            else 0.0
        )
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "average_latency_ms": round(avg_latency, 3),
            "error_rate": round(error_rate, 4),
            "strategy_counts": dict(self.strategy_counts),
            "reranker_used": self.reranker_used,
            "reranker_skipped": self.reranker_skipped,
            "endpoint_counts": dict(self.endpoint_counts),
            "error_counts": dict(self.error_counts),
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_latency_ms = 0.0
        self.strategy_counts.clear()
        self.reranker_used = 0
        self.reranker_skipped = 0
        self.endpoint_counts.clear()
        self.error_counts.clear()
        self.last_reset_at = time.time()


# ─── Module-level Singleton ──────────────────────────────────────────────────

_metrics_lock = threading.Lock()
_metrics = APIMetrics()


def get_metrics() -> APIMetrics:
    """Return the process-wide metrics singleton (thread-safe)."""
    return _metrics


# ─── Timing Helper ───────────────────────────────────────────────────────────


@contextmanager
def track_request(
    endpoint: str,
    strategy: str = "unknown",
    rerank_used: bool = False,
) -> Iterator[RequestContext]:
    """Context manager that records timing, error, and counts for a request.

    Usage::

        with track_request("/api/v1/search/dense", strategy="dense") as ctx:
            ... do work ...
            ctx.strategy = "dense"
            ctx.rerank_used = True   # may be flipped dynamically
    """
    ctx = RequestContext(endpoint=endpoint, strategy=strategy, rerank_used=rerank_used)
    try:
        yield ctx
        ctx.finish()
    except Exception as exc:  # noqa: BLE001 - we want to record all failures
        ctx.finish(error=str(exc))
        raise
    finally:
        with _metrics_lock:
            _metrics.record_request(
                endpoint=ctx.endpoint,
                strategy=ctx.strategy or "unknown",
                latency_ms=ctx.latency_ms,
                success=ctx.error is None,
                rerank_used=ctx.rerank_used,
            )
        logger.info(
            "request_completed",
            extra=ctx.to_log_dict(),
        )


# ─── Structured-log enrichment ───────────────────────────────────────────────


def log_search_event(
    event: str,
    ctx: RequestContext,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit a structured log line tagged with the request context."""
    payload = ctx.to_log_dict()
    if extra:
        payload.update(extra)
    logger.info(event, extra=payload)


# ─── Milestone 7 — Monitoring & Ingestion Metrics ──────────────────────────


@dataclass
class MonitoringMetrics:
    """Process-wide counters for the regulatory monitoring engine."""

    sources_monitored: int = 0
    documents_discovered: int = 0
    documents_failed: int = 0
    monitor_runs: int = 0
    monitor_failures: int = 0
    last_run_at: Optional[float] = None
    last_discovery_at: Optional[float] = None
    source_counts: Dict[str, int] = field(default_factory=dict)
    source_availability: Dict[str, bool] = field(default_factory=dict)
    error_counts: Dict[str, int] = field(default_factory=dict)
    last_reset_at: float = field(default_factory=time.time)

    def record_monitor_run(self, source: str, success: bool) -> None:
        self.monitor_runs += 1
        self.sources_monitored += 1
        self.source_counts[source] = self.source_counts.get(source, 0) + 1
        self.source_availability[source] = success
        self.last_run_at = time.time()
        if not success:
            self.monitor_failures += 1

    def record_discovery(self, source: str, n: int = 1) -> None:
        self.documents_discovered += n
        self.last_discovery_at = time.time()

    def record_discovery_failure(self, source: str, reason: str) -> None:
        self.documents_failed += 1
        key = f"{source}:{reason}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "sources_monitored": self.sources_monitored,
            "documents_discovered": self.documents_discovered,
            "documents_failed": self.documents_failed,
            "monitor_runs": self.monitor_runs,
            "monitor_failures": self.monitor_failures,
            "last_run_at": self.last_run_at,
            "last_discovery_at": self.last_discovery_at,
            "source_counts": dict(self.source_counts),
            "source_availability": dict(self.source_availability),
            "error_counts": dict(self.error_counts),
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.sources_monitored = 0
        self.documents_discovered = 0
        self.documents_failed = 0
        self.monitor_runs = 0
        self.monitor_failures = 0
        self.last_run_at = None
        self.last_discovery_at = None
        self.source_counts.clear()
        self.source_availability.clear()
        self.error_counts.clear()
        self.last_reset_at = time.time()


@dataclass
class IngestionMetrics:
    """Process-wide counters for the automated ingestion pipeline."""

    documents_ingested: int = 0
    documents_failed: int = 0
    chunks_created: int = 0
    embeddings_created: int = 0
    total_processing_latency_ms: float = 0.0
    runs_total: int = 0
    runs_succeeded: int = 0
    runs_failed: int = 0
    last_run_at: Optional[float] = None
    source_counts: Dict[str, int] = field(default_factory=dict)
    step_latency_ms: Dict[str, float] = field(default_factory=dict)
    last_reset_at: float = field(default_factory=time.time)

    def record_run(
        self,
        source: str,
        *,
        success: bool,
        chunks: int = 0,
        embeddings: int = 0,
        latency_ms: float = 0.0,
    ) -> None:
        self.runs_total += 1
        if success:
            self.runs_succeeded += 1
            self.documents_ingested += 1
            self.chunks_created += chunks
            self.embeddings_created += embeddings
        else:
            self.runs_failed += 1
            self.documents_failed += 1
        self.total_processing_latency_ms += latency_ms
        self.source_counts[source] = self.source_counts.get(source, 0) + 1
        self.last_run_at = time.time()

    def record_step_latency(self, step: str, latency_ms: float) -> None:
        self.step_latency_ms[step] = (
            self.step_latency_ms.get(step, 0.0) + latency_ms
        )

    def snapshot(self) -> Dict[str, Any]:
        avg_latency = (
            self.total_processing_latency_ms / self.runs_total
            if self.runs_total > 0
            else 0.0
        )
        return {
            "documents_ingested": self.documents_ingested,
            "documents_failed": self.documents_failed,
            "chunks_created": self.chunks_created,
            "embeddings_created": self.embeddings_created,
            "runs_total": self.runs_total,
            "runs_succeeded": self.runs_succeeded,
            "runs_failed": self.runs_failed,
            "average_processing_latency_ms": round(avg_latency, 3),
            "last_run_at": self.last_run_at,
            "source_counts": dict(self.source_counts),
            "step_latency_ms": dict(self.step_latency_ms),
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.documents_ingested = 0
        self.documents_failed = 0
        self.chunks_created = 0
        self.embeddings_created = 0
        self.total_processing_latency_ms = 0.0
        self.runs_total = 0
        self.runs_succeeded = 0
        self.runs_failed = 0
        self.last_run_at = None
        self.source_counts.clear()
        self.step_latency_ms.clear()
        self.last_reset_at = time.time()


_monitoring_metrics_lock = threading.Lock()
_monitoring_metrics = MonitoringMetrics()

_ingestion_metrics_lock = threading.Lock()
_ingestion_metrics = IngestionMetrics()


def get_monitoring_metrics() -> MonitoringMetrics:
    """Return the process-wide monitoring metrics singleton."""
    return _monitoring_metrics


def get_ingestion_metrics() -> IngestionMetrics:
    """Return the process-wide ingestion metrics singleton."""
    return _ingestion_metrics


def reset_monitoring_metrics() -> None:
    with _monitoring_metrics_lock:
        _monitoring_metrics.reset()


def reset_ingestion_metrics() -> None:
    with _ingestion_metrics_lock:
        _ingestion_metrics.reset()
