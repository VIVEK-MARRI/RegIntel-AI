"""Module 7.8 — Executive Dashboard schemas."""

from __future__ import annotations

import secrets
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ────────────────────────────────────────────────────────────


class TrendDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


class InsightSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ─── Sub-models ───────────────────────────────────────────────────────


class ComplianceMetrics(BaseModel):
    """High-level compliance KPIs."""

    model_config = ConfigDict(extra="forbid")

    regulations_tracked: int = 0
    changes_detected: int = 0
    impact_reports: int = 0
    alerts_open: int = 0
    alerts_critical: int = 0
    alerts_failed: int = 0
    documents_ingested: int = 0
    knowledge_graph_nodes: int = 0
    knowledge_graph_edges: int = 0
    research_reports: int = 0


class TrendPoint(BaseModel):
    """A point on a time series."""

    model_config = ConfigDict(extra="forbid")

    label: str
    value: float
    timestamp: float


class TrendSeries(BaseModel):
    """A named time series of values."""

    model_config = ConfigDict(extra="forbid")

    name: str
    unit: str = ""
    direction: TrendDirection = TrendDirection.FLAT
    delta_pct: float = 0.0
    points: List[TrendPoint] = Field(default_factory=list)


class ImpactDistribution(BaseModel):
    """Distribution of impact reports by impact level."""

    model_config = ConfigDict(extra="forbid")

    counts: Dict[str, int] = Field(default_factory=dict)
    total: int = 0
    average_score: float = 0.0


class AlertMetricsView(BaseModel):
    """Alert distribution for the dashboard."""

    model_config = ConfigDict(extra="forbid")

    total: int = 0
    by_severity: Dict[str, int] = Field(default_factory=dict)
    by_status: Dict[str, int] = Field(default_factory=dict)
    delivery_rate: float = 0.0
    digests_generated: int = 0


class MonitoringHealthView(BaseModel):
    """Monitoring engine health summary."""

    model_config = ConfigDict(extra="forbid")

    sources_monitored: int = 0
    documents_discovered: int = 0
    monitor_failures: int = 0
    last_run_at: Optional[float] = None
    sources_healthy: int = 0
    sources_failed: int = 0


class SystemHealthView(BaseModel):
    """System-level health summary."""

    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    uptime_seconds: float = 0.0
    storage_writable: bool = True
    components: Dict[str, str] = Field(default_factory=dict)


class RiskInsight(BaseModel):
    """A single risk insight surfaced by the RiskInsightsEngine."""

    model_config = ConfigDict(extra="forbid")

    insight_id: str = Field(default_factory=lambda: f"ins-{secrets.token_hex(6)}")
    title: str
    description: str
    severity: InsightSeverity
    score: float = Field(0.0, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list, max_length=20)
    recommendation: str = ""
    created_at: float = 0.0


# ─── Dashboard payload ───────────────────────────────────────────────


class DashboardSnapshot(BaseModel):
    """The full executive dashboard payload."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(default_factory=lambda: f"dash-{secrets.token_hex(6)}")
    title: str = "RegIntel Executive Dashboard"
    generated_at: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    compliance: ComplianceMetrics = Field(default_factory=ComplianceMetrics)
    trends: List[TrendSeries] = Field(default_factory=list)
    impact_distribution: ImpactDistribution = Field(default_factory=ImpactDistribution)
    alerts: AlertMetricsView = Field(default_factory=AlertMetricsView)
    monitoring: MonitoringHealthView = Field(default_factory=MonitoringHealthView)
    system: SystemHealthView = Field(default_factory=SystemHealthView)
    insights: List[RiskInsight] = Field(default_factory=list)


class RiskInsightsResponse(BaseModel):
    """Response payload for /dashboard/insights."""

    model_config = ConfigDict(extra="forbid")

    risk_level: RiskLevel
    risk_score: float
    insights: List[RiskInsight] = Field(default_factory=list)
    generated_at: float = 0.0


__all__ = [
    "TrendDirection",
    "RiskLevel",
    "InsightSeverity",
    "ComplianceMetrics",
    "TrendPoint",
    "TrendSeries",
    "ImpactDistribution",
    "AlertMetricsView",
    "MonitoringHealthView",
    "SystemHealthView",
    "RiskInsight",
    "DashboardSnapshot",
    "RiskInsightsResponse",
]
