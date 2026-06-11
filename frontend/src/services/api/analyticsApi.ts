import { api } from "@/lib/api";
import type {
  AgentAnalyticsOverview,
  AgentPerformance,
  ChangeEvent,
  CostEstimate,
  HealthSummaryResponse,
  IntelligenceAgentMetrics,
  LatencyDistribution,
  LeaderboardEntry,
  MonitoringAlert,
  Recommendation,
  ReviewTask,
} from "@/types";
import type { PaginatedResponse } from "./copilotApi";

export async function getAnalyticsOverview(): Promise<AgentAnalyticsOverview> {
  return api.get("/agents/analytics/overview");
}

export async function getPerformance(): Promise<AgentPerformance[]> {
  return api.get("/agents/analytics/performance");
}

export async function getLeaderboard(topN = 10): Promise<LeaderboardEntry[]> {
  return api.get("/agents/analytics/leaderboard", { query: { top_n: topN } });
}

export async function getAnalyticsHealth(): Promise<HealthSummaryResponse> {
  return api.get("/agents/analytics/health");
}

export async function getCost(): Promise<CostEstimate> {
  return api.get("/agents/analytics/cost");
}

export async function getLatency(name: string): Promise<LatencyDistribution> {
  return api.get(`/agents/analytics/performance/${encodeURIComponent(name)}/latency`);
}

export async function getIntelligenceMetrics(): Promise<IntelligenceAgentMetrics> {
  return api.get("/agents/metrics");
}

export async function getAlerts(): Promise<MonitoringAlert[]> {
  return api.get<PaginatedResponse<MonitoringAlert>>("/alerts").then(r => r.items);
}

export async function getChanges(): Promise<ChangeEvent[]> {
  return api.get<PaginatedResponse<ChangeEvent>>("/changes").then(r => r.items);
}

export async function getRecommendations(): Promise<Recommendation[]> {
  return api.get<PaginatedResponse<Recommendation>>("/recommendations").then(r => r.items);
}

export async function getReviewTasks(): Promise<ReviewTask[]> {
  return api.get<PaginatedResponse<ReviewTask>>("/review/tasks").then(r => r.items);
}
