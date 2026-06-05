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


# ─── Milestone 7.3-7.5 — Change / Impact / Alert Metrics ───────────────


@dataclass
class ChangeDetectionMetrics:
    """Process-wide counters for the change detection engine."""

    diffs_computed: int = 0
    changes_detected: int = 0
    critical_diffs: int = 0
    high_diffs: int = 0
    medium_diffs: int = 0
    low_diffs: int = 0
    total_latency_ms: float = 0.0
    last_diff_at: Optional[float] = None
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_category: Dict[str, int] = field(default_factory=dict)
    last_reset_at: float = field(default_factory=time.time)

    def record_diff(self, diff) -> None:  # type: ignore[no-untyped-def]
        self.diffs_computed += 1
        self.changes_detected += len(diff.changes)
        self.total_latency_ms += diff.duration_ms
        self.last_diff_at = time.time()
        sev = diff.overall_severity.value
        self.by_severity[sev] = self.by_severity.get(sev, 0) + 1
        cat = diff.overall_category.value
        self.by_category[cat] = self.by_category.get(cat, 0) + 1
        if sev == "critical":
            self.critical_diffs += 1
        elif sev == "high":
            self.high_diffs += 1
        elif sev == "medium":
            self.medium_diffs += 1
        else:
            self.low_diffs += 1

    def snapshot(self) -> Dict[str, Any]:
        avg_lat = (
            self.total_latency_ms / self.diffs_computed
            if self.diffs_computed > 0
            else 0.0
        )
        return {
            "diffs_computed": self.diffs_computed,
            "changes_detected": self.changes_detected,
            "critical_diffs": self.critical_diffs,
            "high_diffs": self.high_diffs,
            "medium_diffs": self.medium_diffs,
            "low_diffs": self.low_diffs,
            "average_latency_ms": round(avg_lat, 3),
            "last_diff_at": self.last_diff_at,
            "by_severity": dict(self.by_severity),
            "by_category": dict(self.by_category),
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.diffs_computed = 0
        self.changes_detected = 0
        self.critical_diffs = 0
        self.high_diffs = 0
        self.medium_diffs = 0
        self.low_diffs = 0
        self.total_latency_ms = 0.0
        self.last_diff_at = None
        self.by_severity.clear()
        self.by_category.clear()
        self.last_reset_at = time.time()


@dataclass
class ImpactAnalysisMetrics:
    """Process-wide counters for the impact analysis engine."""

    reports_generated: int = 0
    critical_impact: int = 0
    high_impact: int = 0
    medium_impact: int = 0
    low_impact: int = 0
    total_impact_score: float = 0.0
    affected_entities_total: int = 0
    actions_recommended_total: int = 0
    last_report_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_report(self, report) -> None:  # type: ignore[no-untyped-def]
        self.reports_generated += 1
        self.total_impact_score += report.impact_score
        self.affected_entities_total += len(report.affected_entities)
        self.actions_recommended_total += len(report.required_actions)
        self.last_report_at = time.time()
        lvl = report.impact_level.value
        if lvl == "critical":
            self.critical_impact += 1
        elif lvl == "high":
            self.high_impact += 1
        elif lvl == "medium":
            self.medium_impact += 1
        else:
            self.low_impact += 1

    def snapshot(self) -> Dict[str, Any]:
        avg = (
            self.total_impact_score / self.reports_generated
            if self.reports_generated > 0
            else 0.0
        )
        return {
            "reports_generated": self.reports_generated,
            "critical_impact": self.critical_impact,
            "high_impact": self.high_impact,
            "medium_impact": self.medium_impact,
            "low_impact": self.low_impact,
            "average_impact_score": round(avg, 3),
            "affected_entities_total": self.affected_entities_total,
            "actions_recommended_total": self.actions_recommended_total,
            "last_report_at": self.last_report_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.reports_generated = 0
        self.critical_impact = 0
        self.high_impact = 0
        self.medium_impact = 0
        self.low_impact = 0
        self.total_impact_score = 0.0
        self.affected_entities_total = 0
        self.actions_recommended_total = 0
        self.last_report_at = None
        self.last_reset_at = time.time()


@dataclass
class AlertMetrics:
    """Process-wide counters for the alerting system."""

    alerts_raised: int = 0
    alerts_delivered: int = 0
    alerts_failed: int = 0
    digests_generated: int = 0
    total_delivery_latency_ms: float = 0.0
    by_channel: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    last_alert_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_alert(self, alert) -> None:  # type: ignore[no-untyped-def]
        self.alerts_raised += 1
        self.by_severity[alert.severity.value] = (
            self.by_severity.get(alert.severity.value, 0) + 1
        )
        self.last_alert_at = time.time()

    def record_delivery(
        self,
        channel: str,
        *,
        success: bool,
        latency_ms: float = 0.0,
    ) -> None:
        if success:
            self.alerts_delivered += 1
        else:
            self.alerts_failed += 1
        self.total_delivery_latency_ms += latency_ms
        self.by_channel[channel] = self.by_channel.get(channel, 0) + 1

    def record_digest(self) -> None:
        self.digests_generated += 1

    def snapshot(self) -> Dict[str, Any]:
        avg_lat = (
            self.total_delivery_latency_ms
            / max(1, self.alerts_delivered + self.alerts_failed)
        )
        delivery_rate = (
            self.alerts_delivered / self.alerts_raised
            if self.alerts_raised > 0
            else 0.0
        )
        return {
            "alerts_raised": self.alerts_raised,
            "alerts_delivered": self.alerts_delivered,
            "alerts_failed": self.alerts_failed,
            "delivery_rate": round(delivery_rate, 4),
            "digests_generated": self.digests_generated,
            "average_delivery_latency_ms": round(avg_lat, 3),
            "by_channel": dict(self.by_channel),
            "by_severity": dict(self.by_severity),
            "last_alert_at": self.last_alert_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.alerts_raised = 0
        self.alerts_delivered = 0
        self.alerts_failed = 0
        self.digests_generated = 0
        self.total_delivery_latency_ms = 0.0
        self.by_channel.clear()
        self.by_severity.clear()
        self.last_alert_at = None
        self.last_reset_at = time.time()


_change_detection_metrics_lock = threading.Lock()
_change_detection_metrics = ChangeDetectionMetrics()

_impact_analysis_metrics_lock = threading.Lock()
_impact_analysis_metrics = ImpactAnalysisMetrics()

_alert_metrics_lock = threading.Lock()
_alert_metrics = AlertMetrics()


def get_change_detection_metrics() -> ChangeDetectionMetrics:
    return _change_detection_metrics


def get_impact_analysis_metrics() -> ImpactAnalysisMetrics:
    return _impact_analysis_metrics


def get_alert_metrics() -> AlertMetrics:
    return _alert_metrics


def reset_change_detection_metrics() -> None:
    with _change_detection_metrics_lock:
        _change_detection_metrics.reset()


def reset_impact_analysis_metrics() -> None:
    with _impact_analysis_metrics_lock:
        _impact_analysis_metrics.reset()


def reset_alert_metrics() -> None:
    with _alert_metrics_lock:
        _alert_metrics.reset()
