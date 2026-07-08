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
        self.step_latency_ms[step] = self.step_latency_ms.get(step, 0.0) + latency_ms

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
        avg_lat = self.total_delivery_latency_ms / max(
            1, self.alerts_delivered + self.alerts_failed
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


# ─── Milestone 7.6-7.8 — KG / Research / Dashboard Metrics ───────────


@dataclass
class KnowledgeGraphMetrics:
    nodes_added: int = 0
    relationships_added: int = 0
    traversals_executed: int = 0
    dependency_analyses: int = 0
    builds_executed: int = 0
    by_entity_type: Dict[str, int] = field(default_factory=dict)
    last_build_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_node(self, node) -> None:  # type: ignore[no-untyped-def]
        self.nodes_added += 1
        self.by_entity_type[node.entity_type.value] = (
            self.by_entity_type.get(node.entity_type.value, 0) + 1
        )

    def record_relationship(self, rel) -> None:  # type: ignore[no-untyped-def]
        self.relationships_added += 1

    def record_build(self) -> None:
        self.builds_executed += 1
        self.last_build_at = time.time()

    def record_traversal(self) -> None:
        self.traversals_executed += 1

    def record_dependency(self) -> None:
        self.dependency_analyses += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "nodes_added": self.nodes_added,
            "relationships_added": self.relationships_added,
            "traversals_executed": self.traversals_executed,
            "dependency_analyses": self.dependency_analyses,
            "builds_executed": self.builds_executed,
            "by_entity_type": dict(self.by_entity_type),
            "last_build_at": self.last_build_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.nodes_added = 0
        self.relationships_added = 0
        self.traversals_executed = 0
        self.dependency_analyses = 0
        self.builds_executed = 0
        self.by_entity_type.clear()
        self.last_build_at = None
        self.last_reset_at = time.time()


@dataclass
class ResearchMetrics:
    plans_generated: int = 0
    plans_executed: int = 0
    steps_total: int = 0
    reports_generated: int = 0
    comparative_research: int = 0
    timeline_research: int = 0
    cross_document_research: int = 0
    average_steps_per_plan: float = 0.0
    average_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    last_plan_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_plan(self, step_count: int) -> None:
        self.plans_generated += 1
        self.steps_total += step_count
        self.average_steps_per_plan = self.steps_total / self.plans_generated
        self.last_plan_at = time.time()

    def record_execute(
        self,
        *,
        duration_ms: float,
        kind: str = "general",
    ) -> None:
        self.plans_executed += 1
        self.total_duration_ms += duration_ms
        self.average_duration_ms = self.total_duration_ms / self.plans_executed
        if kind == "comparative":
            self.comparative_research += 1
        elif kind == "timeline":
            self.timeline_research += 1
        elif kind == "cross_document":
            self.cross_document_research += 1

    def record_report(self) -> None:
        self.reports_generated += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "plans_generated": self.plans_generated,
            "plans_executed": self.plans_executed,
            "steps_total": self.steps_total,
            "reports_generated": self.reports_generated,
            "comparative_research": self.comparative_research,
            "timeline_research": self.timeline_research,
            "cross_document_research": self.cross_document_research,
            "average_steps_per_plan": round(self.average_steps_per_plan, 3),
            "average_duration_ms": round(self.average_duration_ms, 3),
            "last_plan_at": self.last_plan_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.plans_generated = 0
        self.plans_executed = 0
        self.steps_total = 0
        self.reports_generated = 0
        self.comparative_research = 0
        self.timeline_research = 0
        self.cross_document_research = 0
        self.average_steps_per_plan = 0.0
        self.average_duration_ms = 0.0
        self.total_duration_ms = 0.0
        self.last_plan_at = None
        self.last_reset_at = time.time()


@dataclass
class DashboardMetrics:
    snapshots_generated: int = 0
    trend_analyses: int = 0
    risk_insights_generated: int = 0
    average_risk_score: float = 0.0
    total_risk_score: float = 0.0
    last_snapshot_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_snapshot(self, risk_score: float = 0.0) -> None:
        self.snapshots_generated += 1
        self.total_risk_score += risk_score
        self.average_risk_score = self.total_risk_score / self.snapshots_generated
        self.last_snapshot_at = time.time()

    def record_trend(self) -> None:
        self.trend_analyses += 1

    def record_risk_insight(self) -> None:
        self.risk_insights_generated += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "snapshots_generated": self.snapshots_generated,
            "trend_analyses": self.trend_analyses,
            "risk_insights_generated": self.risk_insights_generated,
            "average_risk_score": round(self.average_risk_score, 3),
            "last_snapshot_at": self.last_snapshot_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.snapshots_generated = 0
        self.trend_analyses = 0
        self.risk_insights_generated = 0
        self.average_risk_score = 0.0
        self.total_risk_score = 0.0
        self.last_snapshot_at = None
        self.last_reset_at = time.time()


@dataclass
class RiskMetrics:
    assessments_generated: int = 0
    historical_lookups: int = 0
    trend_queries: int = 0
    last_assessment_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)
    by_level: Dict[str, int] = field(default_factory=dict)
    by_category: Dict[str, int] = field(default_factory=dict)

    def record_assessment(
        self,
        assessment: Any,
    ) -> None:
        self.assessments_generated += 1
        try:
            level = assessment.risk_level.value
            self.by_level[level] = self.by_level.get(level, 0) + 1
        except Exception:  # pragma: no cover
            pass
        try:
            for cat in getattr(assessment, "risk_categories", []) or []:
                v = cat.value if hasattr(cat, "value") else str(cat)
                self.by_category[v] = self.by_category.get(v, 0) + 1
        except Exception:  # pragma: no cover
            pass
        self.last_assessment_at = time.time()

    def record_history_lookup(self) -> None:
        self.historical_lookups += 1

    def record_trend_query(self) -> None:
        self.trend_queries += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "assessments_generated": self.assessments_generated,
            "historical_lookups": self.historical_lookups,
            "trend_queries": self.trend_queries,
            "by_level": dict(self.by_level),
            "by_category": dict(self.by_category),
            "last_assessment_at": self.last_assessment_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.assessments_generated = 0
        self.historical_lookups = 0
        self.trend_queries = 0
        self.last_assessment_at = None
        self.by_level = {}
        self.by_category = {}
        self.last_reset_at = time.time()


@dataclass
class RecommendationMetrics:
    recommendations_generated: int = 0
    total_recommendations_count: int = 0
    feedback_recorded: int = 0
    accepted_feedback: int = 0
    rejected_feedback: int = 0
    last_generated_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_generated(self, count: int = 1) -> None:
        self.recommendations_generated += 1
        self.total_recommendations_count += count
        self.last_generated_at = time.time()

    def record_feedback(self, status: str = "proposed") -> None:
        self.feedback_recorded += 1
        if status == "accepted":
            self.accepted_feedback += 1
        elif status == "rejected":
            self.rejected_feedback += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "recommendations_generated": self.recommendations_generated,
            "total_recommendations_count": self.total_recommendations_count,
            "feedback_recorded": self.feedback_recorded,
            "accepted_feedback": self.accepted_feedback,
            "rejected_feedback": self.rejected_feedback,
            "last_generated_at": self.last_generated_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.recommendations_generated = 0
        self.total_recommendations_count = 0
        self.feedback_recorded = 0
        self.accepted_feedback = 0
        self.rejected_feedback = 0
        self.last_generated_at = None
        self.last_reset_at = time.time()


@dataclass
class ForecastingMetrics:
    forecasts_generated: int = 0
    scenarios_simulated: int = 0
    trend_predictions: int = 0
    average_horizon_days: float = 0.0
    total_horizon_days: int = 0
    drift_detected: int = 0
    last_forecast_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_forecast(self, horizon_days: int = 30, *, drift: bool = False) -> None:
        self.forecasts_generated += 1
        self.total_horizon_days += horizon_days
        self.average_horizon_days = self.total_horizon_days / self.forecasts_generated
        if drift:
            self.drift_detected += 1
        self.last_forecast_at = time.time()

    def record_scenario(self) -> None:
        self.scenarios_simulated += 1

    def record_trend_prediction(self) -> None:
        self.trend_predictions += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "forecasts_generated": self.forecasts_generated,
            "scenarios_simulated": self.scenarios_simulated,
            "trend_predictions": self.trend_predictions,
            "average_horizon_days": round(self.average_horizon_days, 3),
            "drift_detected": self.drift_detected,
            "last_forecast_at": self.last_forecast_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.forecasts_generated = 0
        self.scenarios_simulated = 0
        self.trend_predictions = 0
        self.average_horizon_days = 0.0
        self.total_horizon_days = 0
        self.drift_detected = 0
        self.last_forecast_at = None
        self.last_reset_at = time.time()


@dataclass
class WorkflowMetrics:
    workflows_created: int = 0
    workflows_started: int = 0
    workflows_completed: int = 0
    workflows_cancelled: int = 0
    workflows_failed: int = 0
    tasks_created: int = 0
    tasks_completed: int = 0
    escalations_triggered: int = 0
    success_rate: float = 0.0
    total_completed: int = 0
    total_terminal: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_escalation_action: Dict[str, int] = field(default_factory=dict)
    by_task_status: Dict[str, int] = field(default_factory=dict)
    last_workflow_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_created(self, workflow_type: str = "unknown") -> None:
        self.workflows_created += 1
        self.by_type[workflow_type] = self.by_type.get(workflow_type, 0) + 1
        self.last_workflow_at = time.time()

    def record_started(self) -> None:
        self.workflows_started += 1

    def record_completed(self) -> None:
        self.workflows_completed += 1
        self.total_completed += 1
        self.total_terminal += 1
        self._recompute_rate()

    def record_cancelled(self) -> None:
        self.workflows_cancelled += 1
        self.total_terminal += 1
        self._recompute_rate()

    def record_failed(self) -> None:
        self.workflows_failed += 1
        self.total_terminal += 1
        self._recompute_rate()

    def record_task_created(self) -> None:
        self.tasks_created += 1

    def record_task_completed(self, status: str = "completed") -> None:
        self.tasks_completed += 1
        self.by_task_status[status] = self.by_task_status.get(status, 0) + 1

    def record_escalation(self, action: str = "escalate") -> None:
        self.escalations_triggered += 1
        self.by_escalation_action[action] = self.by_escalation_action.get(action, 0) + 1

    def _recompute_rate(self) -> None:
        if self.total_terminal > 0:
            self.success_rate = round(self.total_completed / self.total_terminal, 4)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "workflows_created": self.workflows_created,
            "workflows_started": self.workflows_started,
            "workflows_completed": self.workflows_completed,
            "workflows_cancelled": self.workflows_cancelled,
            "workflows_failed": self.workflows_failed,
            "tasks_created": self.tasks_created,
            "tasks_completed": self.tasks_completed,
            "escalations_triggered": self.escalations_triggered,
            "success_rate": self.success_rate,
            "by_type": dict(self.by_type),
            "by_escalation_action": dict(self.by_escalation_action),
            "by_task_status": dict(self.by_task_status),
            "last_workflow_at": self.last_workflow_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.workflows_created = 0
        self.workflows_started = 0
        self.workflows_completed = 0
        self.workflows_cancelled = 0
        self.workflows_failed = 0
        self.tasks_created = 0
        self.tasks_completed = 0
        self.escalations_triggered = 0
        self.success_rate = 0.0
        self.total_completed = 0
        self.total_terminal = 0
        self.by_type = {}
        self.by_escalation_action = {}
        self.by_task_status = {}
        self.last_workflow_at = None
        self.last_reset_at = time.time()


@dataclass
class ReviewMetrics:
    reviews_created: int = 0
    reviews_started: int = 0
    reviews_approved: int = 0
    reviews_rejected: int = 0
    reviews_escalated: int = 0
    corrections_recorded: int = 0
    comments_recorded: int = 0
    total_latency_ms: float = 0.0
    completed_count: int = 0
    average_latency_ms: float = 0.0
    approval_rate: float = 0.0
    total_decided: int = 0
    by_status: Dict[str, int] = field(default_factory=dict)
    by_decision: Dict[str, int] = field(default_factory=dict)
    by_priority: Dict[str, int] = field(default_factory=dict)
    by_role: Dict[str, int] = field(default_factory=dict)
    last_review_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_created(self, priority: str = "medium") -> None:
        self.reviews_created += 1
        self.by_priority[priority] = self.by_priority.get(priority, 0) + 1
        self.last_review_at = time.time()

    def record_started(self) -> None:
        self.reviews_started += 1

    def record_decision(
        self, decision: str = "approved", latency_ms: float = 0.0
    ) -> None:
        self.by_decision[decision] = self.by_decision.get(decision, 0) + 1
        if decision == "approved":
            self.reviews_approved += 1
            self.total_decided += 1
        elif decision == "rejected":
            self.reviews_rejected += 1
            self.total_decided += 1
        elif decision == "escalate":
            self.reviews_escalated += 1
        if latency_ms > 0:
            self.total_latency_ms += latency_ms
            self.completed_count += 1
            self.average_latency_ms = round(
                self.total_latency_ms / self.completed_count, 3
            )
        self._recompute_rate()

    def record_status(self, status: str = "pending") -> None:
        self.by_status[status] = self.by_status.get(status, 0) + 1

    def record_correction(self) -> None:
        self.corrections_recorded += 1

    def record_comment(self, role: str = "reviewer") -> None:
        self.comments_recorded += 1
        self.by_role[role] = self.by_role.get(role, 0) + 1

    def _recompute_rate(self) -> None:
        if self.total_decided > 0:
            self.approval_rate = round(self.reviews_approved / self.total_decided, 4)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "reviews_created": self.reviews_created,
            "reviews_started": self.reviews_started,
            "reviews_approved": self.reviews_approved,
            "reviews_rejected": self.reviews_rejected,
            "reviews_escalated": self.reviews_escalated,
            "corrections_recorded": self.corrections_recorded,
            "comments_recorded": self.comments_recorded,
            "average_latency_ms": self.average_latency_ms,
            "approval_rate": self.approval_rate,
            "by_status": dict(self.by_status),
            "by_decision": dict(self.by_decision),
            "by_priority": dict(self.by_priority),
            "by_role": dict(self.by_role),
            "last_review_at": self.last_review_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.reviews_created = 0
        self.reviews_started = 0
        self.reviews_approved = 0
        self.reviews_rejected = 0
        self.reviews_escalated = 0
        self.corrections_recorded = 0
        self.comments_recorded = 0
        self.total_latency_ms = 0.0
        self.completed_count = 0
        self.average_latency_ms = 0.0
        self.approval_rate = 0.0
        self.total_decided = 0
        self.by_status = {}
        self.by_decision = {}
        self.by_priority = {}
        self.by_role = {}
        self.last_review_at = None
        self.last_reset_at = time.time()


_knowledge_graph_metrics_lock = threading.Lock()
_knowledge_graph_metrics = KnowledgeGraphMetrics()

_research_metrics_lock = threading.Lock()
_research_metrics = ResearchMetrics()

_dashboard_metrics_lock = threading.Lock()
_dashboard_metrics = DashboardMetrics()

_recommendation_metrics_lock = threading.Lock()
_recommendation_metrics = RecommendationMetrics()

_forecasting_metrics_lock = threading.Lock()
_forecasting_metrics = ForecastingMetrics()

_risk_metrics_lock = threading.Lock()
_risk_metrics = RiskMetrics()

_workflow_metrics_lock = threading.Lock()
_workflow_metrics = WorkflowMetrics()

_review_metrics_lock = threading.Lock()
_review_metrics = ReviewMetrics()


def get_knowledge_graph_metrics() -> KnowledgeGraphMetrics:
    return _knowledge_graph_metrics


def get_research_metrics() -> ResearchMetrics:
    return _research_metrics


def get_dashboard_metrics() -> DashboardMetrics:
    return _dashboard_metrics


def get_recommendation_metrics() -> RecommendationMetrics:
    return _recommendation_metrics


def get_forecasting_metrics() -> ForecastingMetrics:
    return _forecasting_metrics


def get_risk_metrics() -> RiskMetrics:
    return _risk_metrics


def get_workflow_metrics() -> WorkflowMetrics:
    return _workflow_metrics


def get_review_metrics() -> ReviewMetrics:
    return _review_metrics


def reset_knowledge_graph_metrics() -> None:
    with _knowledge_graph_metrics_lock:
        _knowledge_graph_metrics.reset()


def reset_research_metrics() -> None:
    with _research_metrics_lock:
        _research_metrics.reset()


def reset_dashboard_metrics() -> None:
    with _dashboard_metrics_lock:
        _dashboard_metrics.reset()


def reset_recommendation_metrics() -> None:
    with _recommendation_metrics_lock:
        _recommendation_metrics.reset()


def reset_forecasting_metrics() -> None:
    with _forecasting_metrics_lock:
        _forecasting_metrics.reset()


def reset_risk_metrics() -> None:
    with _risk_metrics_lock:
        _risk_metrics.reset()


def reset_workflow_metrics() -> None:
    with _workflow_metrics_lock:
        _workflow_metrics.reset()


def reset_review_metrics() -> None:
    with _review_metrics_lock:
        _review_metrics.reset()


# ─── Milestone 8.6-8.8 — Governance / Audit / Admin Metrics ──────────


@dataclass
class GovernanceMetrics:
    """Process-wide counters for the AI governance layer."""

    policies_created: int = 0
    rules_total: int = 0
    decisions_registered: int = 0
    checks_executed: int = 0
    compliant_decisions: int = 0
    non_compliant_decisions: int = 0
    violations_total: int = 0
    blocking_violations: int = 0
    compliance_rate: float = 0.0
    by_decision_type: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_action: Dict[str, int] = field(default_factory=dict)
    by_model: Dict[str, int] = field(default_factory=dict)
    last_check_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_policy_created(self, rule_count: int = 0) -> None:
        self.policies_created += 1
        self.rules_total += rule_count

    def record_decision(self, decision: Any) -> None:
        self.decisions_registered += 1
        try:
            dt = decision.decision_type.value
            self.by_decision_type[dt] = self.by_decision_type.get(dt, 0) + 1
        except Exception:  # pragma: no cover
            pass
        try:
            if decision.model_id:
                self.by_model[decision.model_id] = (
                    self.by_model.get(decision.model_id, 0) + 1
                )
        except Exception:  # pragma: no cover
            pass

    def record_check(self, *, compliant: bool, violation_count: int) -> None:
        self.checks_executed += 1
        if compliant:
            self.compliant_decisions += 1
        else:
            self.non_compliant_decisions += 1
        total = self.compliant_decisions + self.non_compliant_decisions
        self.compliance_rate = (
            round(self.compliant_decisions / total, 4) if total else 0.0
        )
        self.last_check_at = time.time()

    def record_violation(self, *, severity: Any = None, action: Any = None) -> None:
        self.violations_total += 1
        try:
            if severity is not None:
                sv = severity.value if hasattr(severity, "value") else str(severity)
                self.by_severity[sv] = self.by_severity.get(sv, 0) + 1
        except Exception:  # pragma: no cover
            pass
        try:
            if action is not None:
                av = action.value if hasattr(action, "value") else str(action)
                self.by_action[av] = self.by_action.get(av, 0) + 1
                if av == "block":
                    self.blocking_violations += 1
        except Exception:  # pragma: no cover
            pass

    def snapshot(self) -> Dict[str, Any]:
        return {
            "policies_created": self.policies_created,
            "rules_total": self.rules_total,
            "decisions_registered": self.decisions_registered,
            "checks_executed": self.checks_executed,
            "compliant_decisions": self.compliant_decisions,
            "non_compliant_decisions": self.non_compliant_decisions,
            "violations_total": self.violations_total,
            "blocking_violations": self.blocking_violations,
            "compliance_rate": self.compliance_rate,
            "by_decision_type": dict(self.by_decision_type),
            "by_severity": dict(self.by_severity),
            "by_action": dict(self.by_action),
            "by_model": dict(self.by_model),
            "last_check_at": self.last_check_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.policies_created = 0
        self.rules_total = 0
        self.decisions_registered = 0
        self.checks_executed = 0
        self.compliant_decisions = 0
        self.non_compliant_decisions = 0
        self.violations_total = 0
        self.blocking_violations = 0
        self.compliance_rate = 0.0
        self.by_decision_type = {}
        self.by_severity = {}
        self.by_action = {}
        self.by_model = {}
        self.last_check_at = None
        self.last_reset_at = time.time()


@dataclass
class AuditMetrics:
    """Process-wide counters for the audit platform."""

    records_appended: int = 0
    evidence_collected: int = 0
    reports_generated: int = 0
    chain_integrity_checks: int = 0
    chain_integrity_failures: int = 0
    by_action: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_evidence_kind: Dict[str, int] = field(default_factory=dict)
    by_report_kind: Dict[str, int] = field(default_factory=dict)
    last_record_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_record(self, action: Any = None, severity: Any = None) -> None:
        self.records_appended += 1
        try:
            av = action.value if hasattr(action, "value") else str(action)
            self.by_action[av] = self.by_action.get(av, 0) + 1
        except Exception:  # pragma: no cover
            pass
        try:
            sv = severity.value if hasattr(severity, "value") else str(severity)
            self.by_severity[sv] = self.by_severity.get(sv, 0) + 1
        except Exception:  # pragma: no cover
            pass
        self.last_record_at = time.time()

    def record_evidence(self, kind: Any = None) -> None:
        self.evidence_collected += 1
        try:
            kv = kind.value if hasattr(kind, "value") else str(kind)
            self.by_evidence_kind[kv] = self.by_evidence_kind.get(kv, 0) + 1
        except Exception:  # pragma: no cover
            pass

    def record_report(self, kind: Any = None) -> None:
        self.reports_generated += 1
        try:
            kv = kind.value if hasattr(kind, "value") else str(kind)
            self.by_report_kind[kv] = self.by_report_kind.get(kv, 0) + 1
        except Exception:  # pragma: no cover
            pass

    def record_chain_check(self, *, intact: bool) -> None:
        self.chain_integrity_checks += 1
        if not intact:
            self.chain_integrity_failures += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "records_appended": self.records_appended,
            "evidence_collected": self.evidence_collected,
            "reports_generated": self.reports_generated,
            "chain_integrity_checks": self.chain_integrity_checks,
            "chain_integrity_failures": self.chain_integrity_failures,
            "by_action": dict(self.by_action),
            "by_severity": dict(self.by_severity),
            "by_evidence_kind": dict(self.by_evidence_kind),
            "by_report_kind": dict(self.by_report_kind),
            "last_record_at": self.last_record_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.records_appended = 0
        self.evidence_collected = 0
        self.reports_generated = 0
        self.chain_integrity_checks = 0
        self.chain_integrity_failures = 0
        self.by_action = {}
        self.by_severity = {}
        self.by_evidence_kind = {}
        self.by_report_kind = {}
        self.last_record_at = None
        self.last_reset_at = time.time()


@dataclass
class AdminMetrics:
    """Process-wide counters for the admin platform."""

    users_created: int = 0
    users_updated: int = 0
    users_deleted: int = 0
    roles_created: int = 0
    rbac_checks: int = 0
    rbac_denied: int = 0
    settings_changed: int = 0
    dashboard_views: int = 0
    logins_recorded: int = 0
    by_user_status: Dict[str, int] = field(default_factory=dict)
    by_setting_category: Dict[str, int] = field(default_factory=dict)
    last_action_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_user_created(self, status: str = "active") -> None:
        self.users_created += 1
        self.by_user_status[status] = self.by_user_status.get(status, 0) + 1
        self.last_action_at = time.time()

    def record_user_updated(self, status: str = "unchanged") -> None:
        self.users_updated += 1
        if status != "unchanged":
            self.by_user_status[status] = self.by_user_status.get(status, 0) + 1
        self.last_action_at = time.time()

    def record_user_deleted(self) -> None:
        self.users_deleted += 1
        self.last_action_at = time.time()

    def record_role_created(self, permission_count: int = 0) -> None:
        self.roles_created += 1
        self.last_action_at = time.time()

    def record_rbac_check(self, *, allowed: bool) -> None:
        self.rbac_checks += 1
        if not allowed:
            self.rbac_denied += 1
        self.last_action_at = time.time()

    def record_setting_change(self, category: str = "general") -> None:
        self.settings_changed += 1
        self.by_setting_category[category] = (
            self.by_setting_category.get(category, 0) + 1
        )
        self.last_action_at = time.time()

    def record_dashboard_view(self) -> None:
        self.dashboard_views += 1

    def record_login(self) -> None:
        self.logins_recorded += 1
        self.last_action_at = time.time()

    def snapshot(self) -> Dict[str, Any]:
        denial_rate = (
            round(self.rbac_denied / self.rbac_checks, 4) if self.rbac_checks else 0.0
        )
        return {
            "users_created": self.users_created,
            "users_updated": self.users_updated,
            "users_deleted": self.users_deleted,
            "roles_created": self.roles_created,
            "rbac_checks": self.rbac_checks,
            "rbac_denied": self.rbac_denied,
            "rbac_denial_rate": denial_rate,
            "settings_changed": self.settings_changed,
            "dashboard_views": self.dashboard_views,
            "logins_recorded": self.logins_recorded,
            "by_user_status": dict(self.by_user_status),
            "by_setting_category": dict(self.by_setting_category),
            "last_action_at": self.last_action_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.users_created = 0
        self.users_updated = 0
        self.users_deleted = 0
        self.roles_created = 0
        self.rbac_checks = 0
        self.rbac_denied = 0
        self.settings_changed = 0
        self.dashboard_views = 0
        self.logins_recorded = 0
        self.by_user_status = {}
        self.by_setting_category = {}
        self.last_action_at = None
        self.last_reset_at = time.time()


_governance_metrics_lock = threading.Lock()
_governance_metrics = GovernanceMetrics()

_audit_metrics_lock = threading.Lock()
_audit_metrics = AuditMetrics()

_admin_metrics_lock = threading.Lock()
_admin_metrics = AdminMetrics()


def get_governance_metrics() -> GovernanceMetrics:
    return _governance_metrics


def get_audit_metrics() -> AuditMetrics:
    return _audit_metrics


def get_admin_metrics() -> AdminMetrics:
    return _admin_metrics


def reset_governance_metrics() -> None:
    with _governance_metrics_lock:
        _governance_metrics.reset()


def reset_audit_metrics() -> None:
    with _audit_metrics_lock:
        _audit_metrics.reset()


def reset_admin_metrics() -> None:
    with _admin_metrics_lock:
        _admin_metrics.reset()


# ─── Milestone 9 — Agent Framework Metrics ────────────────


@dataclass
class AgentMetrics:
    """Process-wide counters for the multi-agent framework."""

    agents_registered: int = 0
    invocations_total: int = 0
    invocations_succeeded: int = 0
    invocations_failed: int = 0
    invocations_timed_out: int = 0
    retries_total: int = 0
    coordination_runs: int = 0
    coordination_succeeded: int = 0
    coordination_failed: int = 0
    coordination_steps_total: int = 0
    total_duration_ms: float = 0.0
    average_duration_ms: float = 0.0
    by_agent: Dict[str, int] = field(default_factory=dict)
    by_capability: Dict[str, int] = field(default_factory=dict)
    by_status: Dict[str, int] = field(default_factory=dict)
    last_invocation_at: Optional[float] = None
    last_reset_at: float = field(default_factory=time.time)

    def record_registration(self, agent_name: str = "unknown") -> None:
        self.agents_registered += 1
        self.by_agent[agent_name] = self.by_agent.get(agent_name, 0) + 1

    def record_execution(
        self,
        agent_name: str,
        *,
        capability: str = "other",
        status: str = "succeeded",
        duration_ms: float = 0.0,
    ) -> None:
        self.invocations_total += 1
        if status == "succeeded":
            self.invocations_succeeded += 1
        elif status == "timed_out":
            self.invocations_timed_out += 1
        else:
            self.invocations_failed += 1
        self.by_status[status] = self.by_status.get(status, 0) + 1
        self.by_capability[capability] = self.by_capability.get(capability, 0) + 1
        self.total_duration_ms += duration_ms
        self.average_duration_ms = round(
            self.total_duration_ms / self.invocations_total, 3
        )
        self.last_invocation_at = time.time()

    def record_retry(self, agent_name: str = "unknown") -> None:
        self.retries_total += 1
        self.by_agent[agent_name] = self.by_agent.get(agent_name, 0) + 1

    def record_coordination_step(self, duration_ms: float = 0.0) -> None:
        self.coordination_steps_total += 1
        self.total_duration_ms += duration_ms

    def record_coordination(
        self,
        plan: Any = None,
        *,
        final_status: str = "succeeded",
    ) -> None:
        self.coordination_runs += 1
        if final_status == "succeeded":
            self.coordination_succeeded += 1
        else:
            self.coordination_failed += 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "agents_registered": self.agents_registered,
            "invocations_total": self.invocations_total,
            "invocations_succeeded": self.invocations_succeeded,
            "invocations_failed": self.invocations_failed,
            "invocations_timed_out": self.invocations_timed_out,
            "retries_total": self.retries_total,
            "coordination_runs": self.coordination_runs,
            "coordination_succeeded": self.coordination_succeeded,
            "coordination_failed": self.coordination_failed,
            "coordination_steps_total": self.coordination_steps_total,
            "average_duration_ms": self.average_duration_ms,
            "by_agent": dict(self.by_agent),
            "by_capability": dict(self.by_capability),
            "by_status": dict(self.by_status),
            "last_invocation_at": self.last_invocation_at,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.agents_registered = 0
        self.invocations_total = 0
        self.invocations_succeeded = 0
        self.invocations_failed = 0
        self.invocations_timed_out = 0
        self.retries_total = 0
        self.coordination_runs = 0
        self.coordination_succeeded = 0
        self.coordination_failed = 0
        self.coordination_steps_total = 0
        self.total_duration_ms = 0.0
        self.average_duration_ms = 0.0
        self.by_agent = {}
        self.by_capability = {}
        self.by_status = {}
        self.last_invocation_at = None
        self.last_reset_at = time.time()


_agent_metrics_lock = threading.Lock()
_agent_metrics = AgentMetrics()


def get_agent_metrics() -> AgentMetrics:
    return _agent_metrics


def reset_agent_metrics() -> None:
    with _agent_metrics_lock:
        _agent_metrics.reset()


# ─── Milestone 9.4-9.6 — Intelligence Agent Metrics ──────────


@dataclass
class IntelligenceAgentMetrics:
    """Process-wide counters for the Research / Compliance / Risk agents.

    Tracks invocations, success / failure, confidence, latency, scenario
    kinds, modes, collaborations and recommendation acceptance.
    """

    total_invocations: int = 0
    total_successful: int = 0
    total_failed: int = 0
    total_collaborations: int = 0
    # Per-agent tallies
    research_invocations: int = 0
    research_successful: int = 0
    research_failed: int = 0
    research_total_duration_ms: float = 0.0
    research_confidence_total: float = 0.0
    research_last_invocation_at: Optional[float] = None
    research_last_error: str = ""
    compliance_invocations: int = 0
    compliance_successful: int = 0
    compliance_failed: int = 0
    compliance_total_duration_ms: float = 0.0
    compliance_confidence_total: float = 0.0
    compliance_last_invocation_at: Optional[float] = None
    compliance_last_error: str = ""
    risk_invocations: int = 0
    risk_successful: int = 0
    risk_failed: int = 0
    risk_total_duration_ms: float = 0.0
    risk_confidence_total: float = 0.0
    risk_last_invocation_at: Optional[float] = None
    risk_last_error: str = ""
    # Aggregate fields
    by_mode: Dict[str, int] = field(default_factory=dict)
    by_scenario_kind: Dict[str, int] = field(default_factory=dict)
    by_collaboration_pair: Dict[str, int] = field(default_factory=dict)
    recommendations_generated: int = 0
    recommendations_accepted: int = 0
    recommendations_rejected: int = 0
    evidence_items_shared: int = 0
    last_reset_at: float = field(default_factory=time.time)

    # ── per-agent recording helpers ────────────────────────

    def _record_agent(
        self,
        agent: str,
        *,
        duration_ms: float,
        confidence: float,
        success: bool,
        error: str = "",
    ) -> None:
        self.total_invocations += 1
        if success:
            self.total_successful += 1
        else:
            self.total_failed += 1
        if agent == "research":
            self.research_invocations += 1
            self.research_successful += 1 if success else 0
            self.research_failed += 0 if success else 1
            self.research_total_duration_ms += duration_ms
            self.research_confidence_total += confidence
            self.research_last_invocation_at = time.time()
            self.research_last_error = "" if success else error
        elif agent == "compliance":
            self.compliance_invocations += 1
            self.compliance_successful += 1 if success else 0
            self.compliance_failed += 0 if success else 1
            self.compliance_total_duration_ms += duration_ms
            self.compliance_confidence_total += confidence
            self.compliance_last_invocation_at = time.time()
            self.compliance_last_error = "" if success else error
        elif agent == "risk":
            self.risk_invocations += 1
            self.risk_successful += 1 if success else 0
            self.risk_failed += 0 if success else 1
            self.risk_total_duration_ms += duration_ms
            self.risk_confidence_total += confidence
            self.risk_last_invocation_at = time.time()
            self.risk_last_error = "" if success else error

    def record_research(
        self,
        *,
        duration_ms: float,
        confidence: float,
        success: bool = True,
        error: str = "",
        mode: str = "general",
    ) -> None:
        self._record_agent(
            "research",
            duration_ms=duration_ms,
            confidence=confidence,
            success=success,
            error=error,
        )
        self.by_mode[mode] = self.by_mode.get(mode, 0) + 1

    def record_compliance(
        self,
        *,
        duration_ms: float,
        confidence: float,
        success: bool = True,
        error: str = "",
    ) -> None:
        self._record_agent(
            "compliance",
            duration_ms=duration_ms,
            confidence=confidence,
            success=success,
            error=error,
        )

    def record_risk(
        self,
        *,
        duration_ms: float,
        confidence: float,
        success: bool = True,
        error: str = "",
        scenario_kind: str = "",
    ) -> None:
        self._record_agent(
            "risk",
            duration_ms=duration_ms,
            confidence=confidence,
            success=success,
            error=error,
        )
        if scenario_kind:
            self.by_scenario_kind[scenario_kind] = (
                self.by_scenario_kind.get(scenario_kind, 0) + 1
            )

    def record_collaboration(
        self,
        from_agent: str,
        to_agent: str,
        *,
        evidence_items: int = 0,
    ) -> None:
        self.total_collaborations += 1
        self.evidence_items_shared += evidence_items
        key = f"{from_agent}->{to_agent}"
        self.by_collaboration_pair[key] = self.by_collaboration_pair.get(key, 0) + 1

    def record_recommendation_generated(self, count: int = 1) -> None:
        self.recommendations_generated += count

    def record_recommendation_accepted(self, count: int = 1) -> None:
        self.recommendations_accepted += count

    def record_recommendation_rejected(self, count: int = 1) -> None:
        self.recommendations_rejected += count

    def record_scenario_kind(self, kind: str) -> None:
        """Track scenario kinds separately from risk agent invocations."""
        self.by_scenario_kind[kind] = self.by_scenario_kind.get(kind, 0) + 1

    def snapshot(self) -> Dict[str, Any]:
        return {
            "total_invocations": self.total_invocations,
            "total_successful": self.total_successful,
            "total_failed": self.total_failed,
            "total_collaborations": self.total_collaborations,
            "research": {
                "invocations": self.research_invocations,
                "successful": self.research_successful,
                "failed": self.research_failed,
                "average_duration_ms": (
                    round(
                        self.research_total_duration_ms / self.research_invocations,
                        3,
                    )
                    if self.research_invocations
                    else 0.0
                ),
                "average_confidence": (
                    round(
                        self.research_confidence_total / self.research_invocations,
                        3,
                    )
                    if self.research_invocations
                    else 0.0
                ),
                "last_invocation_at": self.research_last_invocation_at,
                "last_error": self.research_last_error,
            },
            "compliance": {
                "invocations": self.compliance_invocations,
                "successful": self.compliance_successful,
                "failed": self.compliance_failed,
                "average_duration_ms": (
                    round(
                        self.compliance_total_duration_ms / self.compliance_invocations,
                        3,
                    )
                    if self.compliance_invocations
                    else 0.0
                ),
                "average_confidence": (
                    round(
                        self.compliance_confidence_total / self.compliance_invocations,
                        3,
                    )
                    if self.compliance_invocations
                    else 0.0
                ),
                "last_invocation_at": self.compliance_last_invocation_at,
                "last_error": self.compliance_last_error,
            },
            "risk": {
                "invocations": self.risk_invocations,
                "successful": self.risk_successful,
                "failed": self.risk_failed,
                "average_duration_ms": (
                    round(
                        self.risk_total_duration_ms / self.risk_invocations,
                        3,
                    )
                    if self.risk_invocations
                    else 0.0
                ),
                "average_confidence": (
                    round(
                        self.risk_confidence_total / self.risk_invocations,
                        3,
                    )
                    if self.risk_invocations
                    else 0.0
                ),
                "last_invocation_at": self.risk_last_invocation_at,
                "last_error": self.risk_last_error,
            },
            "by_mode": dict(self.by_mode),
            "by_scenario_kind": dict(self.by_scenario_kind),
            "by_collaboration_pair": dict(self.by_collaboration_pair),
            "recommendations_generated": self.recommendations_generated,
            "recommendations_accepted": self.recommendations_accepted,
            "recommendations_rejected": self.recommendations_rejected,
            "evidence_items_shared": self.evidence_items_shared,
            "uptime_seconds": time.time() - self.last_reset_at,
        }

    def reset(self) -> None:
        self.total_invocations = 0
        self.total_successful = 0
        self.total_failed = 0
        self.total_collaborations = 0
        self.research_invocations = 0
        self.research_successful = 0
        self.research_failed = 0
        self.research_total_duration_ms = 0.0
        self.research_confidence_total = 0.0
        self.research_last_invocation_at = None
        self.research_last_error = ""
        self.compliance_invocations = 0
        self.compliance_successful = 0
        self.compliance_failed = 0
        self.compliance_total_duration_ms = 0.0
        self.compliance_confidence_total = 0.0
        self.compliance_last_invocation_at = None
        self.compliance_last_error = ""
        self.risk_invocations = 0
        self.risk_successful = 0
        self.risk_failed = 0
        self.risk_total_duration_ms = 0.0
        self.risk_confidence_total = 0.0
        self.risk_last_invocation_at = None
        self.risk_last_error = ""
        self.by_mode = {}
        self.by_scenario_kind = {}
        self.by_collaboration_pair = {}
        self.recommendations_generated = 0
        self.recommendations_accepted = 0
        self.recommendations_rejected = 0
        self.evidence_items_shared = 0
        self.last_reset_at = time.time()


_intel_agent_metrics_lock = threading.Lock()
_intel_agent_metrics = IntelligenceAgentMetrics()


def get_intelligence_agent_metrics() -> IntelligenceAgentMetrics:
    """Return the process-wide intelligence agent metrics singleton."""
    return _intel_agent_metrics


def reset_intelligence_agent_metrics() -> None:
    with _intel_agent_metrics_lock:
        _intel_agent_metrics.reset()
