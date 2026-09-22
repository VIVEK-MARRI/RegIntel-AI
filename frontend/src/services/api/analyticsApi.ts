import { api, encodePathSegment } from "@/lib/api";
import type {
  AgentAnalyticsOverview,
  AgentPerformance,
  CostEstimate,
  IntelligenceAgentMetrics,
  LatencyDistribution,
  LeaderboardEntry,
  MonitoringAlert,
  PaginatedAlerts,
  PaginatedDiffs,
  PaginatedRecommendations,
  PaginatedReviews,
  Recommendation,
  ReviewTask,
  AnalyticsHealthSummary,
  DocumentDiff,
} from "@/types/api/analytics";

export async function getAnalyticsOverview(): Promise<AgentAnalyticsOverview> {
  return api.get<AgentAnalyticsOverview>("/agents/analytics/overview");
}

export async function getPerformance(): Promise<AgentPerformance[]> {
  return api.get<AgentPerformance[]>("/agents/analytics/performance");
}

export async function getLeaderboard(topN = 10): Promise<LeaderboardEntry[]> {
  return api.get<LeaderboardEntry[]>("/agents/analytics/leaderboard", {
    query: { top_n: topN },
  });
}

export async function getAnalyticsHealth(): Promise<AnalyticsHealthSummary> {
  return api.get<AnalyticsHealthSummary>("/agents/analytics/health");
}

export async function getCost(): Promise<CostEstimate> {
  return api.get<CostEstimate>("/agents/analytics/cost");
}

export async function getLatency(name: string): Promise<LatencyDistribution> {
  return api.get<LatencyDistribution>(
    `/agents/analytics/performance/${encodePathSegment(name)}/latency`
  );
}

export async function getIntelligenceMetrics(): Promise<IntelligenceAgentMetrics> {
  return api.get<IntelligenceAgentMetrics>("/agents/metrics");
}

export async function getAlerts(): Promise<MonitoringAlert[]> {
  const res = await api.get<PaginatedAlerts>("/alerts");
  return res.items;
}

export async function getChanges(): Promise<DocumentDiff[]> {
  const res = await api.get<PaginatedDiffs>("/changes");
  return res.items;
}

export async function getRecommendations(): Promise<Recommendation[]> {
  const res = await api.get<PaginatedRecommendations>("/recommendations");
  return res.items;
}

export async function getReviewTasks(): Promise<ReviewTask[]> {
  const res = await api.get<PaginatedReviews>("/review/tasks");
  return res.items;
}
