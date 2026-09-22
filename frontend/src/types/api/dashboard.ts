/**
 * Executive dashboard contracts. Backend: app/api/v1/dashboard.py +
 * app/schemas/dashboard.py (extra="forbid"). Timestamps epoch SECONDS.
 *
 * Verified live (/api/v1/dashboard/snapshot): aggregates REAL subsystem
 * state (documents_ingested, KG nodes/edges, research count, ingestion
 * trends, component health). Empty stores yield honest zeros — never
 * synthetic demo data. TrendSeries carry "current"/"total" points, NOT
 * time series: render deltas as text, not line charts.
 */
export type TrendDirection = "up" | "down" | "flat";
export type DashboardRiskLevel = "low" | "moderate" | "elevated" | "high" | "critical";
export type InsightSeverity = "info" | "warning" | "critical";

export interface ComplianceMetrics {
  regulations_tracked: number;
  changes_detected: number;
  impact_reports: number;
  alerts_open: number;
  alerts_critical: number;
  alerts_failed: number;
  documents_ingested: number;
  knowledge_graph_nodes: number;
  knowledge_graph_edges: number;
  research_reports: number;
}

export interface TrendPoint {
  label: string;
  value: number;
  timestamp: number;
}

export interface TrendSeries {
  name: string;
  unit: string;
  direction: TrendDirection;
  delta_pct: number;
  points: TrendPoint[];
}

export interface ImpactDistribution {
  counts: Record<string, number>;
  total: number;
  average_score: number;
}

export interface AlertMetricsView {
  total: number;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
  delivery_rate: number;
  digests_generated: number;
}

export interface MonitoringHealthView {
  sources_monitored: number;
  documents_discovered: number;
  monitor_failures: number;
  last_run_at: number | null;
  sources_healthy: number;
  sources_failed: number;
}

export interface SystemHealthView {
  status: string;
  uptime_seconds: number;
  storage_writable: boolean;
  components: Record<string, string>;
}

export interface RiskInsight {
  insight_id: string;
  title: string;
  description: string;
  severity: InsightSeverity;
  score: number;
  evidence: string[];
  recommendation: string;
  created_at: number;
}

export interface DashboardSnapshot {
  snapshot_id: string;
  title: string;
  generated_at: number;
  risk_level: DashboardRiskLevel;
  risk_score: number;
  compliance: ComplianceMetrics;
  trends: TrendSeries[];
  impact_distribution: ImpactDistribution;
  alerts: AlertMetricsView;
  monitoring: MonitoringHealthView;
  system: SystemHealthView;
  insights: RiskInsight[];
}

export interface RiskInsightsResponse {
  risk_level: DashboardRiskLevel;
  risk_score: number;
  insights: RiskInsight[];
  generated_at: number;
}

export interface TrendListResponse {
  items: TrendSeries[];
  count: number;
}

export interface DashboardRiskResponse {
  risk_level: DashboardRiskLevel;
  risk_score: number;
  generated_at: number;
}
