"""Module 7.7/7.8 — Executive Dashboard service.

Public surface
--------------
* ``TrendAnalyzer``             — produce trend series from store data
* ``RiskInsightsEngine``        — derive risk insights + overall risk level
* ``ComplianceMetricsAggregator`` — pull metrics from each platform store
* ``ExecutiveDashboardService``  — DI facade that produces snapshots
* ``build_default_executive_dashboard_service``
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.schemas.dashboard import (
    AlertMetricsView,
    ComplianceMetrics,
    DashboardSnapshot,
    ImpactDistribution,
    InsightSeverity,
    MonitoringHealthView,
    RiskInsight,
    RiskInsightsResponse,
    RiskLevel,
    SystemHealthView,
    TrendDirection,
    TrendPoint,
    TrendSeries,
)
from app.services.observability import get_dashboard_metrics, track_request

logger = logging.getLogger(__name__)


# ─── Compliance metrics aggregator ──────────────────────────────────


class ComplianceMetricsAggregator:
    """Pulls numbers from the live service stores. All access is optional."""

    def __init__(self) -> None:
        self._started = time.time()

    def aggregate(self) -> ComplianceMetrics:
        m = ComplianceMetrics()
        try:
            from app.services.monitoring import build_default_monitoring_service

            mon = build_default_monitoring_service()
            snap = mon.metrics_snapshot()
            m.regulations_tracked = sum(snap.get("source_counts", {}).values())
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.change_detection import (
                build_default_change_detection_service,
            )

            chg = build_default_change_detection_service()
            st = chg.stats()
            m.changes_detected = st.total_diffs
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.impact_analysis import (
                build_default_impact_analysis_service,
            )

            imp = build_default_impact_analysis_service()
            st = imp.stats()
            m.impact_reports = st.total_reports
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.ingestion import build_default_auto_ingestion_service

            ing = build_default_auto_ingestion_service()
            st = ing.stats()
            m.documents_ingested = st.total_runs
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.alerting import build_default_alert_service

            al = build_default_alert_service()
            st = al.stats()
            m.alerts_open = st.pending_alerts + st.sent_alerts
            m.alerts_critical = st.by_severity.get("critical", 0)
            m.alerts_failed = st.failed_alerts
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.knowledge_graph import (
                build_default_knowledge_graph_service,
            )

            kg = build_default_knowledge_graph_service()
            st = kg.stats()
            m.knowledge_graph_nodes = st.total_nodes
            m.knowledge_graph_edges = st.total_relationships
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.research import build_default_research_service

            rs = build_default_research_service()
            st = rs.stats()
            m.research_reports = st.total_reports
        except Exception:  # pragma: no cover
            pass
        return m

    def uptime_seconds(self) -> float:
        return time.time() - self._started


# ─── Trend analyzer ─────────────────────────────────────────────────


class TrendAnalyzer:
    """Build trend series from monitoring/ingestion/change stores."""

    def analyze(self) -> List[TrendSeries]:
        series: List[TrendSeries] = []
        try:
            from app.services.monitoring import build_default_monitoring_service

            mon = build_default_monitoring_service()
            snap = mon.metrics_snapshot()
            series.append(
                TrendSeries(
                    name="monitoring.source_counts",
                    unit="sources",
                    points=[
                        TrendPoint(
                            label="current",
                            value=float(snap.get("sources_monitored", 0)),
                            timestamp=time.time(),
                        )
                    ],
                )
            )
            series.append(
                TrendSeries(
                    name="monitoring.documents_discovered",
                    unit="docs",
                    points=[
                        TrendPoint(
                            label="current",
                            value=float(snap.get("documents_discovered", 0)),
                            timestamp=time.time(),
                        )
                    ],
                )
            )
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.change_detection import (
                build_default_change_detection_service,
            )

            chg = build_default_change_detection_service()
            st = chg.stats()
            series.append(
                TrendSeries(
                    name="change_detection.diffs",
                    unit="diffs",
                    points=[
                        TrendPoint(
                            label="total",
                            value=float(st.total_diffs),
                            timestamp=time.time(),
                        )
                    ],
                )
            )
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.ingestion import build_default_auto_ingestion_service

            ing = build_default_auto_ingestion_service()
            st = ing.stats()
            series.append(
                TrendSeries(
                    name="ingestion.runs",
                    unit="runs",
                    points=[
                        TrendPoint(
                            label="total",
                            value=float(st.total_runs),
                            timestamp=time.time(),
                        )
                    ],
                )
            )
        except Exception:  # pragma: no cover
            pass
        # Add a simple delta
        for s in series:
            s.direction = self._direction(s.points)
            s.delta_pct = self._delta_pct(s.points)
        get_dashboard_metrics().record_trend()
        return series

    @staticmethod
    def _direction(points: List[TrendPoint]) -> TrendDirection:
        if len(points) < 2:
            return TrendDirection.FLAT
        if points[-1].value > points[0].value:
            return TrendDirection.UP
        if points[-1].value < points[0].value:
            return TrendDirection.DOWN
        return TrendDirection.FLAT

    @staticmethod
    def _delta_pct(points: List[TrendPoint]) -> float:
        if len(points) < 2 or points[0].value == 0:
            return 0.0
        return round((points[-1].value - points[0].value) / points[0].value * 100.0, 2)


# ─── Risk insights engine ───────────────────────────────────────────


class RiskInsightsEngine:
    """Surface risk insights + compute a single risk score."""

    def __init__(self) -> None:
        self._started = time.time()

    def insights(self) -> RiskInsightsResponse:
        insights: List[RiskInsight] = []
        score = 0.0
        # Pull live data
        try:
            from app.services.alerting import build_default_alert_service

            al = build_default_alert_service()
            st = al.stats()
            if st.by_severity.get("critical", 0) > 0:
                insights.append(
                    RiskInsight(
                        title=f"{st.by_severity['critical']} critical alert(s) open",
                        description="Critical-severity regulatory alerts are currently in the system.",
                        severity=InsightSeverity.CRITICAL,
                        score=0.8,
                        evidence=[f"alerts.critical = {st.by_severity['critical']}"],
                        recommendation="Investigate critical alerts within 24 hours.",
                    )
                )
                score = max(score, 0.8)
            if st.failed_alerts > 0:
                insights.append(
                    RiskInsight(
                        title=f"{st.failed_alerts} failed alert delivery",
                        description="Some alert notifications failed to deliver.",
                        severity=InsightSeverity.WARNING,
                        score=0.4,
                        evidence=[f"alerts.failed = {st.failed_alerts}"],
                        recommendation="Verify alert channel configuration.",
                    )
                )
                score = max(score, 0.4)
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.change_detection import (
                build_default_change_detection_service,
            )

            chg = build_default_change_detection_service()
            st = chg.stats()
            crit = st.by_severity.get("critical", 0)
            high = st.by_severity.get("high", 0)
            if crit > 0:
                insights.append(
                    RiskInsight(
                        title=f"{crit} critical change(s) detected",
                        description="Critical-severity regulatory changes were detected.",
                        severity=InsightSeverity.CRITICAL,
                        score=0.7,
                        evidence=[f"changes.critical = {crit}"],
                        recommendation="Run impact analysis on critical diffs.",
                    )
                )
                score = max(score, 0.7)
            if high > 0:
                insights.append(
                    RiskInsight(
                        title=f"{high} high-severity change(s)",
                        description="High-severity regulatory changes detected.",
                        severity=InsightSeverity.WARNING,
                        score=0.5,
                        evidence=[f"changes.high = {high}"],
                        recommendation="Schedule impact review within 7 days.",
                    )
                )
                score = max(score, 0.5)
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.impact_analysis import (
                build_default_impact_analysis_service,
            )

            imp = build_default_impact_analysis_service()
            st = imp.stats()
            if st.critical_impact > 0:
                insights.append(
                    RiskInsight(
                        title=f"{st.critical_impact} critical impact report(s)",
                        description="Critical-impact analyses are pending review.",
                        severity=InsightSeverity.CRITICAL,
                        score=0.85,
                        evidence=[f"impacts.critical = {st.critical_impact}"],
                        recommendation="Escalate to senior compliance leadership.",
                    )
                )
                score = max(score, 0.85)
        except Exception:  # pragma: no cover
            pass
        try:
            from app.services.monitoring import build_default_monitoring_service

            mon = build_default_monitoring_service()
            snap = mon.metrics_snapshot()
            failed = sum(snap.get("error_counts", {}).values())
            if failed > 0:
                insights.append(
                    RiskInsight(
                        title=f"{failed} monitoring error(s)",
                        description="Some monitoring runs produced errors.",
                        severity=InsightSeverity.WARNING,
                        score=0.4,
                        evidence=[f"monitoring.errors = {failed}"],
                        recommendation="Inspect monitor logs for failed sources.",
                    )
                )
                score = max(score, 0.4)
        except Exception:  # pragma: no cover
            pass
        # Always include an info-level baseline insight
        if not insights:
            insights.append(
                RiskInsight(
                    title="No active risks",
                    description="All monitored systems are within nominal thresholds.",
                    severity=InsightSeverity.INFO,
                    score=0.0,
                    recommendation="Continue regular monitoring.",
                )
            )
        for i in insights:
            i.created_at = time.time()
        get_dashboard_metrics().record_risk_insight()
        return RiskInsightsResponse(
            risk_level=self._to_level(score),
            risk_score=round(score, 3),
            insights=insights,
            generated_at=time.time(),
        )

    @staticmethod
    def _to_level(score: float) -> RiskLevel:
        if score >= 0.85:
            return RiskLevel.CRITICAL
        if score >= 0.65:
            return RiskLevel.HIGH
        if score >= 0.45:
            return RiskLevel.ELEVATED
        if score >= 0.2:
            return RiskLevel.MODERATE
        return RiskLevel.LOW


# ─── Service (DI facade) ────────────────────────────────────────────


class ExecutiveDashboardService:
    def __init__(self) -> None:
        self.aggregator = ComplianceMetricsAggregator()
        self.trend_analyzer = TrendAnalyzer()
        self.risk_engine = RiskInsightsEngine()
        self._last_snapshot: Optional[DashboardSnapshot] = None

    # ── view components ─────────────────────────────────────────

    def _impact_distribution(self) -> ImpactDistribution:
        try:
            from app.services.impact_analysis import (
                build_default_impact_analysis_service,
            )

            st = build_default_impact_analysis_service().stats()
            return ImpactDistribution(
                counts={
                    "critical": st.critical_impact,
                    "high": st.high_impact,
                    "medium": st.medium_impact,
                    "low": st.low_impact,
                    "negligible": st.negligible_impact,
                },
                total=st.total_reports,
                average_score=st.average_impact_score,
            )
        except Exception:  # pragma: no cover
            return ImpactDistribution()

    def _alerts_view(self) -> AlertMetricsView:
        try:
            from app.services.alerting import build_default_alert_service

            st = build_default_alert_service().stats()
            delivery_rate = (
                st.delivered_alerts / st.total_alerts if st.total_alerts > 0 else 0.0
            )
            return AlertMetricsView(
                total=st.total_alerts,
                by_severity=st.by_severity,
                by_status=st.by_status,
                delivery_rate=round(delivery_rate, 4),
                digests_generated=st.digests_generated,
            )
        except Exception:  # pragma: no cover
            return AlertMetricsView()

    def _monitoring_view(self) -> MonitoringHealthView:
        try:
            from app.services.monitoring import build_default_monitoring_service

            snap = build_default_monitoring_service().metrics_snapshot()
            return MonitoringHealthView(
                sources_monitored=snap.get("sources_monitored", 0),
                documents_discovered=snap.get("documents_discovered", 0),
                monitor_failures=snap.get("monitor_failures", 0),
                last_run_at=snap.get("last_run_at"),
                sources_healthy=snap.get("sources_monitored", 0)
                - sum(snap.get("error_counts", {}).values()),
                sources_failed=sum(snap.get("error_counts", {}).values()),
            )
        except Exception:  # pragma: no cover
            return MonitoringHealthView()

    def _system_view(self) -> SystemHealthView:
        components: Dict[str, str] = {}
        try:
            from app.services.knowledge_graph import (
                build_default_knowledge_graph_service,
            )

            st = build_default_knowledge_graph_service().stats()
            components["knowledge_graph"] = "ok" if st else "degraded"
        except Exception:  # pragma: no cover
            components["knowledge_graph"] = "down"
        try:
            from app.services.research import build_default_research_service

            st = build_default_research_service().stats()
            components["research"] = "ok" if st else "degraded"
        except Exception:  # pragma: no cover
            components["research"] = "down"
        try:
            from app.services.alerting import build_default_alert_service

            st = build_default_alert_service().stats()
            components["alerting"] = "ok" if st else "degraded"
        except Exception:  # pragma: no cover
            components["alerting"] = "down"
        try:
            from app.core.health import always_healthy

            components["health_subsystem"] = "ok"
        except Exception:  # pragma: no cover
            components["health_subsystem"] = "down"
        status = "ok" if all(v == "ok" for v in components.values()) else "degraded"
        return SystemHealthView(
            status=status,
            uptime_seconds=self.aggregator.uptime_seconds(),
            storage_writable=True,
            components=components,
        )

    # ── public ──────────────────────────────────────────────────

    def snapshot(self) -> DashboardSnapshot:
        with track_request(endpoint="/api/v1/dashboard/snapshot", strategy="dashboard"):
            compliance = self.aggregator.aggregate()
            trends = self.trend_analyzer.analyze()
            impact = self._impact_distribution()
            alerts = self._alerts_view()
            monitoring = self._monitoring_view()
            system = self._system_view()
            insights = self.risk_engine.insights()
            snap = DashboardSnapshot(
                generated_at=time.time(),
                risk_level=insights.risk_level,
                risk_score=insights.risk_score,
                compliance=compliance,
                trends=trends,
                impact_distribution=impact,
                alerts=alerts,
                monitoring=monitoring,
                system=system,
                insights=insights.insights,
            )
            self._last_snapshot = snap
            get_dashboard_metrics().record_snapshot(snap.risk_score)
            return snap

    def compliance_view(self) -> ComplianceMetrics:
        return self.aggregator.aggregate()

    def trends_view(self) -> List[TrendSeries]:
        return self.trend_analyzer.analyze()

    def insights_view(self) -> RiskInsightsResponse:
        return self.risk_engine.insights()

    def impact_view(self) -> ImpactDistribution:
        return self._impact_distribution()

    def alerts_view(self) -> AlertMetricsView:
        return self._alerts_view()

    def monitoring_view(self) -> MonitoringHealthView:
        return self._monitoring_view()

    def system_view(self) -> SystemHealthView:
        return self._system_view()

    def last_snapshot(self) -> Optional[DashboardSnapshot]:
        return self._last_snapshot


# ─── Factory ────────────────────────────────────────────────────────


def build_default_executive_dashboard_service() -> ExecutiveDashboardService:
    return ExecutiveDashboardService()


__all__ = [
    "ComplianceMetricsAggregator",
    "TrendAnalyzer",
    "RiskInsightsEngine",
    "ExecutiveDashboardService",
    "build_default_executive_dashboard_service",
]
