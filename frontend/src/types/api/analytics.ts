/**
 * Analytics + monitoring contracts. Backend: app/api/v1/agent_analytics.py
 * (prefix /agents/analytics) + intelligence_agents.py (/agents/metrics) +
 * alerts.py / changes.py / recommendations.py / review.py (bare prefixes).
 * Timestamps epoch SECONDS unless noted.
 */
import type { PaginatedResponse } from "./common";

export interface AnalyticsAgentHealthItem {
  agent_name: string;
  total_invocations: number;
  successful_invocations: number;
  failed_invocations: number;
  success_rate: number;
  average_duration_ms: number;
  average_confidence: number;
  last_invocation_at: number | null;
  last_error: string;
  health: string;
}

export interface AnalyticsHealthSummary {
  total_agents: number;
  healthy_agents: number;
  degraded_agents: number;
  unhealthy_agents: number;
  unknown_agents: number;
  overall_health: string;
  agents: AnalyticsAgentHealthItem[];
  notes?: string;
}

export interface AgentAnalyticsOverview {
  total_agents: number;
  total_invocations: number;
  success_rate: number;
  average_duration_ms: number;
  average_confidence: number;
  total_collaborations: number;
  total_cost_units: number;
  health: AnalyticsHealthSummary;
  leaderboard: LeaderboardEntry[];
  collaborations: unknown[];
  recent_executions: unknown[];
  forecast_accuracy: unknown[];
  recommendation_accuracy: unknown[];
  cost: CostEstimate | null;
  generated_at: number;
}

export interface AgentPerformance {
  agent_name: string;
  total_invocations: number;
  successful_invocations: number;
  failed_invocations: number;
  success_rate: number;
  average_duration_ms: number;
  p95_duration_ms: number;
  average_confidence: number;
  total_evidence_shared: number;
  last_invocation_at: number | null;
  last_error: string;
  health: string;
}

export interface LeaderboardEntry {
  rank: number;
  agent_name: string;
  score: number;
  success_rate: number;
  average_confidence: number;
  total_invocations: number;
  average_duration_ms: number;
}

export interface CostEstimate {
  agent_name: string;
  invocations: number;
  tokens_used: number;
  cost_units: number;
  currency: string;
  cost_per_invocation: number;
  notes: string;
}

export interface LatencyDistribution {
  agent_name: string;
  count: number;
  average_ms: number;
  min_ms: number;
  max_ms: number;
  p50_ms: number;
  p90_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export interface IntelligenceAgentMetrics {
  total_invocations: number;
  total_successful: number;
  total_failed: number;
  total_collaborations: number;
  research: Record<string, unknown>;
  compliance: Record<string, unknown>;
  risk: Record<string, unknown>;
  by_mode: Record<string, number>;
  by_scenario_kind: Record<string, number>;
  average_confidence: number;
  last_reset_at: number;
}

/* ---------------- monitoring: alerts / changes / recommendations / review */

export type AlertSeverity = "info" | "low" | "medium" | "high" | "critical";
export type AlertStatus = "pending" | "sent" | "delivered" | "failed" | "skipped";

export interface MonitoringAlert {
  alert_id: string;
  title: string;
  message: string;
  source: string;
  severity: AlertSeverity;
  channels: string[];
  status: AlertStatus;
  priority: number;
  created_at: number;
  sent_at?: number | null;
  delivered_at?: number | null;
  document_id?: string | null;
  diff_id?: string | null;
}

export type PaginatedAlerts = PaginatedResponse<MonitoringAlert>;

export type DiffChangeType =
  | "added" | "removed" | "modified" | "unchanged" | "renumbered";

export interface ClauseChange {
  change_id: string;
  change_type: DiffChangeType;
  [key: string]: unknown;
}

export interface DocumentDiff {
  diff_id: string;
  document_id: string;
  old_version: string;
  new_version: string;
  source: string;
  changes: ClauseChange[];
  added_count: number;
  removed_count: number;
  modified_count: number;
  unchanged_count: number;
  overall_severity: string;
  overall_category: string;
  summary: string;
  computed_at: string;
  duration_ms: number;
  metadata: Record<string, unknown>;
}

export type PaginatedDiffs = PaginatedResponse<DocumentDiff>;

export interface Recommendation {
  recommendation_id: string;
  title: string;
  description: string;
  recommendation_type: string;
  priority: string;
  status: string;
  confidence: number;
  reasoning: unknown[];
  citations: unknown[];
  action_plan?: Record<string, unknown> | null;
  source: string;
  document_id?: string | null;
  created_at: number;
}

export type PaginatedRecommendations = PaginatedResponse<Recommendation>;

export interface ReviewTask {
  review_id: string;
  title: string;
  description: string;
  subject_type: string;
  subject_id: string;
  workflow_id?: string | null;
  task_id?: string | null;
  status: string;
  priority: string;
  decision?: string | null;
  assigned_to?: string | null;
  assigned_role?: string | null;
  due_at?: number | null;
  created_at: number;
}

export type PaginatedReviews = PaginatedResponse<ReviewTask>;
