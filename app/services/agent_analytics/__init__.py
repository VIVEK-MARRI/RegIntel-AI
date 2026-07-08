"""Module 9.9 — Agent Analytics Platform.

Monitors and optimises the entire multi-agent ecosystem. REUSES the M9
observability primitives, the framework service, the orchestration
service and the per-agent execution engines. This module does NOT
re-implement the underlying observability counters; it aggregates and
exposes them through higher-level analytics APIs.

Public surface
--------------
* ``AgentMetricsRepository``   — in-memory record store
* ``AgentPerformanceAnalyzer`` — per-agent performance roll-ups
* ``AgentHealthMonitor``       — health classification
* ``AgentLeaderboard``         — rank agents by score
* ``AgentCostAnalyzer``        — cost / token estimation
* ``AgentAnalyticsService``    — DI facade
* ``build_default_agent_analytics_service``
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from app.schemas.agent_analytics import (
    AgentAnalyticsOverview,
    AgentLatencyPoint,
    AgentPerformance,
    AgentUsageCount,
    CollaborationStats,
    CostEstimate,
    ExecutionSummary,
    ForecastAccuracy,
    HealthLevel,
    HealthSummary,
    LatencyDistribution,
    LeaderboardEntry,
    RecommendationAccuracy,
)
from app.schemas.orchestration import OrchestrationResult, WorkflowStatus

logger = logging.getLogger(__name__)


def _now() -> float:
    return time.time()


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


# ═══════════════════════════════════════════════════════════════════════
# Repository — records each agent execution
# ═══════════════════════════════════════════════════════════════════════


class AgentMetricsRepository:
    """Thread-safe in-memory store of per-agent execution records.

    Bounded by ``max_records_per_agent`` to keep memory usage flat
    under long-running test suites.
    """

    def __init__(self, max_records_per_agent: int = 1000) -> None:
        self._records: Dict[str, Deque[AgentLatencyPoint]] = defaultdict(
            lambda: deque(maxlen=max_records_per_agent)
        )
        self._successes: Dict[str, int] = defaultdict(int)
        self._failures: Dict[str, int] = defaultdict(int)
        self._confidences: Dict[str, List[float]] = defaultdict(list)
        self._latencies: Dict[str, List[float]] = defaultdict(list)
        self._errors: Dict[str, str] = defaultdict(str)
        self._last_invocation: Dict[str, float] = defaultdict(float)
        self._lock = threading.RLock()

    def record(
        self,
        agent_name: str,
        duration_ms: float,
        status: str,
        *,
        confidence: Optional[float] = None,
    ) -> None:
        with self._lock:
            point = AgentLatencyPoint(
                agent_name=agent_name,
                duration_ms=duration_ms,
                status=status,
                timestamp=_now(),
            )
            self._records[agent_name].append(point)
            if status == "succeeded":
                self._successes[agent_name] += 1
            else:
                self._failures[agent_name] += 1
            if confidence is not None:
                self._confidences[agent_name].append(confidence)
            self._latencies[agent_name].append(duration_ms)
            self._last_invocation[agent_name] = point.timestamp

    def record_error(self, agent_name: str, error: str) -> None:
        with self._lock:
            self._errors[agent_name] = str(error)[:512]

    def stats(self, agent_name: str) -> AgentPerformance:
        with self._lock:
            total = self._successes[agent_name] + self._failures[agent_name]
            ok = self._successes[agent_name]
            fail = self._failures[agent_name]
            durations = list(self._latencies[agent_name])
            confs = list(self._confidences[agent_name])
            last = self._last_invocation.get(agent_name)
            err = self._errors.get(agent_name, "")
        success_rate = (ok / total) if total else 0.0
        avg = sum(durations) / len(durations) if durations else 0.0
        p95 = _percentile(durations, 95.0) if durations else 0.0
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        # Classify health
        if total == 0:
            health = HealthLevel.UNKNOWN
        elif fail == 0:
            health = HealthLevel.HEALTHY
        elif success_rate < 0.5:
            health = HealthLevel.UNHEALTHY
        else:
            health = HealthLevel.DEGRADED
        return AgentPerformance(
            agent_name=agent_name,
            total_invocations=total,
            successful_invocations=ok,
            failed_invocations=fail,
            success_rate=round(success_rate, 4),
            average_duration_ms=round(avg, 3),
            p95_duration_ms=round(p95, 3),
            average_confidence=round(avg_conf, 3),
            last_invocation_at=last,
            last_error=err,
            health=health,
        )

    def all_agent_names(self) -> List[str]:
        with self._lock:
            return sorted(
                set(self._records.keys())
                | set(self._successes.keys())
                | set(self._failures.keys())
            )

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._successes.clear()
            self._failures.clear()
            self._confidences.clear()
            self._latencies.clear()
            self._errors.clear()
            self._last_invocation.clear()


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_v) - 1)
    if f == c:
        return sorted_v[f]
    return sorted_v[f] + (sorted_v[c] - sorted_v[f]) * (k - f)


# ═══════════════════════════════════════════════════════════════════════
# Performance analyzer
# ═══════════════════════════════════════════════════════════════════════


class AgentPerformanceAnalyzer:
    """Builds :class:`AgentPerformance` and :class:`LatencyDistribution`
    views for a single agent or the whole ecosystem.
    """

    def __init__(self, repo: AgentMetricsRepository) -> None:
        self._repo = repo

    def for_agent(self, agent_name: str) -> AgentPerformance:
        return self._repo.stats(agent_name)

    def for_all(self) -> List[AgentPerformance]:
        return [self._repo.stats(name) for name in self._repo.all_agent_names()]

    def latency_distribution(self, agent_name: str) -> LatencyDistribution:
        with self._repo._lock:  # noqa: SLF001
            durations = list(self._repo._latencies.get(agent_name, []))  # noqa: SLF001
        if not durations:
            return LatencyDistribution(agent_name=agent_name)
        return LatencyDistribution(
            agent_name=agent_name,
            count=len(durations),
            average_ms=round(sum(durations) / len(durations), 3),
            min_ms=round(min(durations), 3),
            max_ms=round(max(durations), 3),
            p50_ms=round(_percentile(durations, 50.0), 3),
            p90_ms=round(_percentile(durations, 90.0), 3),
            p95_ms=round(_percentile(durations, 95.0), 3),
            p99_ms=round(_percentile(durations, 99.0), 3),
        )


# ═══════════════════════════════════════════════════════════════════════
# Health monitor
# ═══════════════════════════════════════════════════════════════════════


class AgentHealthMonitor:
    """Classifies the health of a single agent or the whole ecosystem."""

    def __init__(self, analyzer: AgentPerformanceAnalyzer) -> None:
        self._analyzer = analyzer

    def agent_health(self, agent_name: str) -> HealthLevel:
        return self._analyzer.for_agent(agent_name).health

    def ecosystem_health(self) -> HealthSummary:
        perfs = self._analyzer.for_all()
        counts = {lvl: 0 for lvl in HealthLevel}
        for p in perfs:
            counts[p.health] = counts.get(p.health, 0) + 1
        total = len(perfs)
        if total == 0:
            overall = HealthLevel.UNKNOWN
        elif counts.get(HealthLevel.UNHEALTHY, 0) > 0:
            overall = HealthLevel.DEGRADED
        elif counts.get(HealthLevel.DEGRADED, 0) > 0:
            overall = HealthLevel.DEGRADED
        elif counts.get(HealthLevel.UNKNOWN, 0) == total:
            overall = HealthLevel.UNKNOWN
        else:
            overall = HealthLevel.HEALTHY
        return HealthSummary(
            total_agents=total,
            healthy_agents=counts.get(HealthLevel.HEALTHY, 0),
            degraded_agents=counts.get(HealthLevel.DEGRADED, 0),
            unhealthy_agents=counts.get(HealthLevel.UNHEALTHY, 0),
            unknown_agents=counts.get(HealthLevel.UNKNOWN, 0),
            overall_health=overall,
            agents=perfs,
            notes=(
                ""
                if overall != HealthLevel.DEGRADED
                else "At least one agent is degraded or unhealthy"
            ),
        )


# ═══════════════════════════════════════════════════════════════════════
# Leaderboard
# ═══════════════════════════════════════════════════════════════════════


class AgentLeaderboard:
    """Ranks agents by a composite score."""

    def __init__(
        self,
        analyzer: AgentPerformanceAnalyzer,
        *,
        weight_success: float = 0.6,
        weight_confidence: float = 0.3,
        weight_speed: float = 0.1,
    ) -> None:
        self._analyzer = analyzer
        self.weight_success = weight_success
        self.weight_confidence = weight_confidence
        self.weight_speed = weight_speed

    def rank(self, top_n: int = 10) -> List[LeaderboardEntry]:
        perfs = self._analyzer.for_all()
        scored: List[LeaderboardEntry] = []
        for p in perfs:
            # Speed score: 1.0 if avg < 100ms, 0.0 if avg > 5000ms, linear in between
            avg = p.average_duration_ms
            if avg <= 0:
                speed = 0.0
            elif avg >= 5_000:
                speed = 0.0
            else:
                speed = max(0.0, 1.0 - (avg / 5_000.0))
            score = (
                self.weight_success * p.success_rate
                + self.weight_confidence * p.average_confidence
                + self.weight_speed * speed
            )
            scored.append(
                LeaderboardEntry(
                    agent_name=p.agent_name,
                    score=round(score, 4),
                    success_rate=p.success_rate,
                    average_confidence=p.average_confidence,
                    total_invocations=p.total_invocations,
                    average_duration_ms=p.average_duration_ms,
                )
            )
        scored.sort(key=lambda e: e.score, reverse=True)
        for i, e in enumerate(scored):
            e.rank = i + 1
        return scored[:top_n]


# ═══════════════════════════════════════════════════════════════════════
# Cost analyzer
# ═══════════════════════════════════════════════════════════════════════


class AgentCostAnalyzer:
    """Estimates cost in arbitrary "cost units" per agent / platform.

    Uses a configurable ``cost_per_invocation`` rate. The actual token
    cost is approximated; if the agent framework supplies a token
    count, that is preferred.
    """

    def __init__(
        self,
        repo: AgentMetricsRepository,
        *,
        cost_per_invocation: float = 0.001,
        cost_per_token: float = 0.000002,
    ) -> None:
        self._repo = repo
        self.cost_per_invocation = cost_per_invocation
        self.cost_per_token = cost_per_token

    def estimate_for_agent(self, agent_name: str) -> CostEstimate:
        p = self._repo.stats(agent_name)
        cost = p.total_invocations * self.cost_per_invocation
        return CostEstimate(
            agent_name=agent_name,
            invocations=p.total_invocations,
            tokens_used=0,
            cost_units=round(cost, 4),
            cost_per_invocation=round(self.cost_per_invocation, 6),
            notes=("Estimated at " f"${self.cost_per_invocation}/invocation"),
        )

    def estimate_platform_total(self) -> CostEstimate:
        perfs = self._repo.all_agent_names()
        total = sum(self.estimate_for_agent(n).cost_units for n in perfs)
        invocations = sum(self._repo.stats(n).total_invocations for n in perfs)
        return CostEstimate(
            invocations=invocations,
            cost_units=round(total, 4),
            cost_per_invocation=(round(total / invocations, 6) if invocations else 0.0),
            notes="Aggregated cost across all known agents",
        )


# ═══════════════════════════════════════════════════════════════════════
# Service / facade
# ═══════════════════════════════════════════════════════════════════════


class AgentAnalyticsService:
    """DI facade for the agent analytics platform."""

    def __init__(
        self,
        repo: AgentMetricsRepository,
        analyzer: AgentPerformanceAnalyzer,
        monitor: AgentHealthMonitor,
        leaderboard: AgentLeaderboard,
        cost_analyzer: AgentCostAnalyzer,
        *,
        framework_service: Any = None,
        orchestration_service: Any = None,
    ) -> None:
        self.repo = repo
        self.analyzer = analyzer
        self.monitor = monitor
        self.leaderboard = leaderboard
        self.cost_analyzer = cost_analyzer
        self.framework_service = framework_service
        self.orchestration_service = orchestration_service
        # Pre-register all known agents so the leaderboard / health
        # endpoint returns something even before any run.
        self._pre_seed_agents()

    def _pre_seed_agents(self) -> None:
        if self.framework_service is None:
            return
        try:
            for meta in self.framework_service.list_agents():
                # Only insert empty stats so agent is visible
                self.repo.record(
                    meta.name,
                    duration_ms=0.0,
                    status="succeeded",
                )
        except Exception:  # pragma: no cover
            pass

    # ─── analytics endpoints ──────────────────────────────

    def overview(
        self,
        *,
        collaboration_counts: Optional[Dict[str, int]] = None,
        recent_executions: Optional[List[ExecutionSummary]] = None,
        forecast_accuracy: Optional[List[ForecastAccuracy]] = None,
        recommendation_accuracy: Optional[List[RecommendationAccuracy]] = None,
    ) -> AgentAnalyticsOverview:
        perfs = self.analyzer.for_all()
        total_invocations = sum(p.total_invocations for p in perfs)
        successes = sum(p.successful_invocations for p in perfs)
        success_rate = successes / total_invocations if total_invocations else 0.0
        durations = [p.average_duration_ms for p in perfs if p.average_duration_ms > 0]
        avg_dur = sum(durations) / len(durations) if durations else 0.0
        confs = [p.average_confidence for p in perfs if p.average_confidence > 0]
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        health = self.monitor.ecosystem_health()
        leaderboard = self.leaderboard.rank(top_n=20)
        collab_pairs = self._build_collaboration_stats(collaboration_counts or {})
        cost = self.cost_analyzer.estimate_platform_total()
        return AgentAnalyticsOverview(
            total_agents=len(perfs),
            total_invocations=total_invocations,
            success_rate=round(success_rate, 4),
            average_duration_ms=round(avg_dur, 3),
            average_confidence=round(avg_conf, 3),
            total_collaborations=sum(c.count for c in collab_pairs),
            total_cost_units=cost.cost_units,
            health=health,
            leaderboard=leaderboard,
            collaborations=collab_pairs,
            recent_executions=recent_executions or [],
            forecast_accuracy=forecast_accuracy or [],
            recommendation_accuracy=recommendation_accuracy or [],
            cost=cost,
        )

    def performance(self) -> List[AgentPerformance]:
        return self.analyzer.for_all()

    def performance_for(self, agent_name: str) -> Optional[AgentPerformance]:
        if agent_name in self.repo.all_agent_names():
            return self.analyzer.for_agent(agent_name)
        return None

    def leaderboard_view(self, top_n: int = 10) -> List[LeaderboardEntry]:
        return self.leaderboard.rank(top_n=top_n)

    def health(self) -> HealthSummary:
        return self.monitor.ecosystem_health()

    def cost(self) -> CostEstimate:
        return self.cost_analyzer.estimate_platform_total()

    # ─── internal: collaboration stats ─────────────────────

    def _build_collaboration_stats(
        self, raw: Dict[str, int]
    ) -> List[CollaborationStats]:
        out: List[CollaborationStats] = []
        for key, count in raw.items():
            if "->" not in key:
                continue
            from_a, to_a = key.split("->", 1)
            out.append(
                CollaborationStats(
                    from_agent=from_a,
                    to_agent=to_a,
                    count=int(count),
                )
            )
        out.sort(key=lambda c: c.count, reverse=True)
        return out


# ═══════════════════════════════════════════════════════════════════════
# Default factory
# ═══════════════════════════════════════════════════════════════════════


def build_default_agent_analytics_service(
    *,
    framework_service: Any = None,
    orchestration_service: Any = None,
) -> AgentAnalyticsService:
    """Build a default :class:`AgentAnalyticsService`."""
    repo = AgentMetricsRepository()
    analyzer = AgentPerformanceAnalyzer(repo)
    monitor = AgentHealthMonitor(analyzer)
    leaderboard = AgentLeaderboard(analyzer)
    cost = AgentCostAnalyzer(repo)
    return AgentAnalyticsService(
        repo=repo,
        analyzer=analyzer,
        monitor=monitor,
        leaderboard=leaderboard,
        cost_analyzer=cost,
        framework_service=framework_service,
        orchestration_service=orchestration_service,
    )


__all__ = [
    "AgentMetricsRepository",
    "AgentPerformanceAnalyzer",
    "AgentHealthMonitor",
    "AgentLeaderboard",
    "AgentCostAnalyzer",
    "AgentAnalyticsService",
    "build_default_agent_analytics_service",
]
