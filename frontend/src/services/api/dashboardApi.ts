import { api } from "@/lib/api";
import type {
  AlertMetricsView,
  ComplianceMetrics,
  DashboardRiskResponse,
  DashboardSnapshot,
  ImpactDistribution,
  MonitoringHealthView,
  RiskInsightsResponse,
  SystemHealthView,
  TrendListResponse,
} from "@/types/api/dashboard";

/**
 * Executive dashboard views (app/api/v1/dashboard.py). Each view is an
 * independent endpoint so widgets fail independently. No request params.
 */
export async function getDashboardSnapshot(): Promise<DashboardSnapshot> {
  return api.get<DashboardSnapshot>("/dashboard/snapshot");
}

export async function getDashboardCompliance(): Promise<ComplianceMetrics> {
  return api.get<ComplianceMetrics>("/dashboard/compliance");
}

export async function getDashboardTrends(): Promise<TrendListResponse> {
  return api.get<TrendListResponse>("/dashboard/trends");
}

export async function getDashboardImpact(): Promise<ImpactDistribution> {
  return api.get<ImpactDistribution>("/dashboard/impact-distribution");
}

export async function getDashboardAlerts(): Promise<AlertMetricsView> {
  return api.get<AlertMetricsView>("/dashboard/alerts");
}

export async function getDashboardMonitoring(): Promise<MonitoringHealthView> {
  return api.get<MonitoringHealthView>("/dashboard/monitoring");
}

export async function getDashboardSystem(): Promise<SystemHealthView> {
  return api.get<SystemHealthView>("/dashboard/system");
}

export async function getDashboardInsights(): Promise<RiskInsightsResponse> {
  return api.get<RiskInsightsResponse>("/dashboard/insights");
}

export async function getDashboardRisk(): Promise<DashboardRiskResponse> {
  return api.get<DashboardRiskResponse>("/dashboard/risk");
}
