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
