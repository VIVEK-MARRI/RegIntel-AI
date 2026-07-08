"""Module 5.8 — Answer Analytics Platform.

Provides:

* :class:`AnswerMetricsRepository` — thread-safe in-memory store with
  optional JSONL persistence (reuses the same storage pattern as
  Module 4's analytics).
* :class:`AnswerAnalyticsService` — high-level API for recording
  events, computing snapshots, and serving dashboard data.
* :class:`AnswerHealthMonitor` — derives a :class:`AnswerHealthReport`
  from the latest snapshot.

The repository is process-singleton and lives in DI; tests use
``reset_answer_analytics_service()`` to clear it between runs.
"""

from __future__ import annotations

import json
import logging
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.config import settings
from app.schemas.orchestrator import FinalAnswerResponse
from app.schemas.analytics_v2 import (
    AnalyticsWindow,
    AnswerAnalyticsEvent,
    AnswerAnalyticsSnapshot,
    AnswerHealthReport,
    ConfidenceDistribution,
    FaithfulnessDistribution,
    HallucinationBuckets,
    HealthStatus,
    LatencyStats,
    TokenUsageStats,
)
from app.services.observability import track_request

logger = logging.getLogger(__name__)


# ─── Repository ───────────────────────────────────────────────────────────


class AnswerMetricsRepository:
    """Thread-safe in-memory event store with optional JSONL persistence."""

    def __init__(self, *, persist_path: Optional[Path] = None) -> None:
        self._events: List[AnswerAnalyticsEvent] = []
        self._lock = threading.RLock()
        self._persist_path = persist_path

    def add(self, event: AnswerAnalyticsEvent) -> None:
        with self._lock:
            self._events.append(event)
        if self._persist_path is not None:
            try:
                self._persist_path.parent.mkdir(parents=True, exist_ok=True)
                with self._persist_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event.model_dump(mode="json")) + "\n")
            except Exception as exc:  # pragma: no cover
                logger.warning("Failed to persist analytics event: %s", exc)

    def all(self) -> List[AnswerAnalyticsEvent]:
        with self._lock:
            return list(self._events)

    def window(self, w: AnalyticsWindow) -> List[AnswerAnalyticsEvent]:
        if w == AnalyticsWindow.ALL:
            return self.all()
        now = datetime.now(timezone.utc)
        if w == AnalyticsWindow.HOUR:
            cutoff = now - timedelta(hours=1)
        elif w == AnalyticsWindow.DAY:
            cutoff = now - timedelta(days=1)
        elif w == AnalyticsWindow.WEEK:
            cutoff = now - timedelta(weeks=1)
        elif w == AnalyticsWindow.MONTH:
            cutoff = now - timedelta(days=30)
        else:
            return self.all()
        with self._lock:
            return [e for e in self._events if e.timestamp >= cutoff]

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


# ─── Service ──────────────────────────────────────────────────────────────


class AnswerAnalyticsService:
    """Top-level service used by the API."""

    def __init__(
        self,
        *,
        repository: Optional[AnswerMetricsRepository] = None,
        persist_path: Optional[Path] = None,
    ) -> None:
        self.repository = repository or AnswerMetricsRepository(
            persist_path=persist_path
            or Path(settings.STORAGE_ROOT) / "analytics" / "answer_events.jsonl"
        )

    # ── Recording ────────────────────────────────────────────────────────

    def record(
        self, response: FinalAnswerResponse, *, total_tokens: int = 0
    ) -> AnswerAnalyticsEvent:
        # Citation coverage = cited_claim_count / claim_count across both sections.
        executive = response.citations.executive_summary
        detailed = response.citations.detailed_explanation
        total_claims = executive.claim_count + detailed.claim_count
        cited_claims = executive.cited_claim_count + detailed.cited_claim_count
        citation_coverage = (cited_claims / total_claims) if total_claims else 0.0

        # Source count: unique document_ids across attributions.
        source_ids = {
            a.document_id for a in response.source_attributions if a.document_id
        }

        event = AnswerAnalyticsEvent(
            request_id=response.metadata.request_id,
            query=response.query,
            confidence_score=response.confidence_score,
            confidence_level=response.confidence_level.value,
            faithfulness_score=response.faithfulness_score,
            hallucination_detected=response.hallucination_detected,
            hallucination_risk_level=response.hallucination_risk_level.value,
            attribution_coverage_ratio=response.attribution_coverage_ratio,
            citation_coverage_ratio=citation_coverage,
            source_count=len(source_ids),
            latency_ms=response.latency_ms,
            total_tokens=total_tokens,
            model_used=response.metadata.model_used,
            provider_used=response.metadata.provider_used,
            step_results=[
                s.model_dump(mode="json") for s in response.metadata.step_results
            ],
            warnings=list(response.metadata.warnings),
        )
        self.repository.add(event)
        return event

    # ── Aggregations ─────────────────────────────────────────────────────

    def snapshot(
        self, window: AnalyticsWindow = AnalyticsWindow.ALL
    ) -> AnswerAnalyticsSnapshot:
        events = self.repository.window(window)
        with track_request(
            endpoint=f"/api/v1/answers/analytics?window={window.value}",
            strategy="answer_analytics",
        ):
            snap = self._compute_snapshot(events, window)
        return snap

    def _compute_snapshot(
        self, events: List[AnswerAnalyticsEvent], window: AnalyticsWindow
    ) -> AnswerAnalyticsSnapshot:
        n = len(events)
        if n == 0:
            return AnswerAnalyticsSnapshot(window=window)
        faiths = [e.faithfulness_score for e in events]
        confs = [e.confidence_score for e in events]
        attr_covs = [e.attribution_coverage_ratio for e in events]
        cit_covs = [e.citation_coverage_ratio for e in events]
        latencies = [e.latency_ms for e in events]
        tokens = [e.total_tokens for e in events]
        models: Dict[str, int] = {}
        providers: Dict[str, int] = {}
        for e in events:
            if e.model_used:
                models[e.model_used] = models.get(e.model_used, 0) + 1
            if e.provider_used:
                providers[e.provider_used] = providers.get(e.provider_used, 0) + 1

        confid_dist = ConfidenceDistribution(high=0, medium=0, low=0)
        for c in confs:
            if c >= 0.9:
                confid_dist.high += 1
            elif c >= 0.7:
                confid_dist.medium += 1
            else:
                confid_dist.low += 1

        faith_dist = FaithfulnessDistribution(
            bucket_0_25=0, bucket_25_50=0, bucket_50_75=0, bucket_75_100=0
        )
        for f in faiths:
            if f < 0.25:
                faith_dist.bucket_0_25 += 1
            elif f < 0.5:
                faith_dist.bucket_25_50 += 1
            elif f < 0.75:
                faith_dist.bucket_50_75 += 1
            else:
                faith_dist.bucket_75_100 += 1

        hallu = HallucinationBuckets(detected=0, not_detected=0)
        for e in events:
            if e.hallucination_detected:
                hallu.detected += 1
            else:
                hallu.not_detected += 1

        lat = _percentile_stats(latencies)
        tok = TokenUsageStats(
            total_tokens=sum(tokens),
            average_tokens=sum(tokens) / n if n else 0.0,
            models=models,
            providers=providers,
        )
        hallucination_rate = hallu.detected / n
        # Answer quality = mean of (faithfulness, confidence, attribution coverage, citation coverage).
        answer_quality = (
            statistics.mean(faiths)
            + statistics.mean(confs)
            + statistics.mean(attr_covs)
            + statistics.mean(cit_covs)
        ) / 4.0

        return AnswerAnalyticsSnapshot(
            window=window,
            total_responses=n,
            average_faithfulness=statistics.mean(faiths),
            average_confidence=statistics.mean(confs),
            average_attribution_coverage=statistics.mean(attr_covs),
            average_citation_coverage=statistics.mean(cit_covs),
            hallucination_rate=hallucination_rate,
            answer_quality=answer_quality,
            confidence_distribution=confid_dist,
            faithfulness_distribution=faith_dist,
            hallucination_buckets=hallu,
            latency=lat,
            token_usage=tok,
        )

    # ── Health ──────────────────────────────────────────────────────────

    def health(self) -> AnswerHealthReport:
        snap = self.snapshot(AnalyticsWindow.ALL)
        reasons: List[str] = []
        if snap.total_responses == 0:
            return AnswerHealthReport(
                status=HealthStatus.HEALTHY,
                total_responses=0,
                degraded_reasons=["no responses recorded yet"],
            )
        if snap.hallucination_rate > 0.20:
            reasons.append(
                f"hallucination rate {snap.hallucination_rate:.2%} exceeds 20% threshold"
            )
        if snap.average_faithfulness < 0.60:
            reasons.append(
                f"average faithfulness {snap.average_faithfulness:.2f} below 0.60"
            )
        if snap.average_citation_coverage < 0.50:
            reasons.append(
                f"citation coverage {snap.average_citation_coverage:.2%} below 50%"
            )
        if snap.latency.p95_ms > 5000:
            reasons.append(
                f"p95 latency {snap.latency.p95_ms:.0f}ms exceeds 5s threshold"
            )
        status = (
            HealthStatus.HEALTHY
            if not reasons
            else (
                HealthStatus.DEGRADED if len(reasons) <= 2 else HealthStatus.UNHEALTHY
            )
        )
        return AnswerHealthReport(
            status=status,
            total_responses=snap.total_responses,
            average_faithfulness=snap.average_faithfulness,
            hallucination_rate=snap.hallucination_rate,
            citation_coverage=snap.average_citation_coverage,
            average_latency_ms=snap.latency.average_ms,
            degraded_reasons=reasons,
        )

    # ── Test helpers ────────────────────────────────────────────────────

    def reset(self) -> None:
        self.repository.reset()


# ─── Health monitor ──────────────────────────────────────────────────────


class AnswerHealthMonitor:
    """Wraps the analytics service for dedicated health probes."""

    def __init__(self, *, service: AnswerAnalyticsService) -> None:
        self.service = service

    def check(self) -> AnswerHealthReport:
        return self.service.health()


# ─── Helpers ────────────────────────────────────────────────────────────


def _percentile_stats(values: List[float]) -> LatencyStats:
    n = len(values)
    if n == 0:
        return LatencyStats()
    sorted_vals = sorted(values)
    p50 = sorted_vals[n // 2]
    p95_idx = max(0, int(n * 0.95) - 1)
    p99_idx = max(0, int(n * 0.99) - 1)
    return LatencyStats(
        count=n,
        average_ms=sum(values) / n,
        p50_ms=p50,
        p95_ms=sorted_vals[p95_idx],
        p99_ms=sorted_vals[p99_idx],
        min_ms=min(values),
        max_ms=max(values),
    )


def build_default_answer_analytics_service() -> AnswerAnalyticsService:
    return AnswerAnalyticsService()


__all__ = [
    "AnswerAnalyticsService",
    "AnswerHealthMonitor",
    "AnswerMetricsRepository",
    "build_default_answer_analytics_service",
]
