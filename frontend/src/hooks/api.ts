import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  AdminOverview,
  AdminRole,
  AdminStats,
  AdminUser,
  AgentAnalyticsOverview,
  AgentCollaboration,
  AgentDetail,
  AgentExecutionRequest,
  AgentExecutionResult,
  AgentMessage,
  AgentPerformance,
  AgentSummary,
  AuditEvidence,
  AuditIntegrity,
  AuditRecord,
  ChangeEvent,
  ChatSession,
  ComplianceAssessment,
  ComplianceReport,
  CopilotMessage,
  CopilotRequestPayload,
  CopilotResponsePayload,
  CostEstimate,
  GovernanceDecision,
  GovernancePolicy,
  GraphNode,
  GraphRelationship,
  HealthLevel,
  HealthSummaryResponse,
  ImpactAnalysis,
  IngestionJob,
  IntelligenceAgentMetrics,
  KnowledgeGraphStats,
  LatencyDistribution,
  LeaderboardEntry,
  MonitoringAlert,
  PaginatedResponse,
  Recommendation,
  ResearchReport,
  ReviewTask,
  RiskForecast,
  RiskProjection,
  RiskScenario,
  WorkflowDefinition,
  WorkflowInstance,
  Document,
} from "@/types";

// ─── Copilot ─────────────────────────────────────────────────────────
export const copilotKeys = {
  all: ["copilot"] as const,
  health: () => [...copilotKeys.all, "health"] as const,
  sessions: () => [...copilotKeys.all, "sessions"] as const,
  messages: (id: string) => [...copilotKeys.sessions(), id] as const,
};

export function useCopilotHealth() {
  return useQuery({
    queryKey: copilotKeys.health(),
    queryFn: () => api.get<{ status: string; module: string }>("/copilot/health"),
    staleTime: 60_000,
  });
}

export function useCopilotSessions() {
  return useQuery({
    queryKey: copilotKeys.sessions(),
    queryFn: () => api.get<PaginatedResponse<ChatSession>>("/conversation/sessions"),
  });
}

export function useCopilotMessages(conversationId?: string) {
  return useQuery({
    queryKey: conversationId
      ? copilotKeys.messages(conversationId)
      : copilotKeys.messages("none"),
    queryFn: () =>
      api.get<PaginatedResponse<CopilotMessage>>(
        conversationId
          ? `/conversation/${conversationId}/messages`
          : "/conversation/messages"
      ),
    enabled: Boolean(conversationId),
  });
}

export function useCopilotQuery(): UseMutationResult<
  CopilotResponsePayload,
  Error,
  CopilotRequestPayload
> {
  return useMutation({
    mutationFn: (payload) =>
      api.post<CopilotResponsePayload>("/copilot/query", payload),
  });
}

// ─── Agents (M9) ─────────────────────────────────────────────────────
export const agentKeys = {
  all: ["agents"] as const,
  list: () => [...agentKeys.all, "list"] as const,
  detail: (name: string) => [...agentKeys.all, "detail", name] as const,
  health: (name: string) => [...agentKeys.all, "health", name] as const,
  analytics: () => [...agentKeys.all, "analytics"] as const,
  overview: () => [...agentKeys.all, "analytics", "overview"] as const,
  performance: () => [...agentKeys.all, "analytics", "performance"] as const,
  leaderboard: () => [...agentKeys.all, "analytics", "leaderboard"] as const,
  healthSummary: () => [...agentKeys.all, "analytics", "health"] as const,
  cost: () => [...agentKeys.all, "analytics", "cost"] as const,
  latency: (name: string) => [...agentKeys.all, "analytics", "latency", name] as const,
  collaborations: () => [...agentKeys.all, "collaborations"] as const,
  messages: () => [...agentKeys.all, "messages"] as const,
  workflows: () => [...agentKeys.all, "workflows"] as const,
  workflow: (id: string) => [...agentKeys.all, "workflows", id] as const,
  execution: (id: string) => [...agentKeys.all, "executions", id] as const,
  intelligenceMetrics: () => [...agentKeys.all, "intelligence", "metrics"] as const,
  researchHealth: () => [...agentKeys.all, "research", "health"] as const,
  complianceHealth: () => [...agentKeys.all, "compliance", "health"] as const,
  riskHealth: () => [...agentKeys.all, "risk", "health"] as const,
};

export function useAgents() {
  return useQuery({
    queryKey: agentKeys.list(),
    queryFn: () => api.get<PaginatedResponse<AgentSummary>>("/agents/agents"),
    refetchInterval: 30_000,
  });
}

export function useAgent(name?: string) {
  return useQuery({
    queryKey: name ? agentKeys.detail(name) : agentKeys.detail("none"),
    queryFn: () => api.get<AgentDetail>(`/agents/agents/${name}`),
    enabled: Boolean(name),
  });
}

export function useAgentHealth(name?: string) {
  return useQuery({
    queryKey: name ? agentKeys.health(name) : agentKeys.health("none"),
    queryFn: () =>
      api.get<{ health: HealthLevel; notes: string }>(
        `/agents/agents/${name}/health`
      ),
    enabled: Boolean(name),
    refetchInterval: 15_000,
  });
}

export function useExecuteAgent(): UseMutationResult<
  AgentExecutionResult,
  Error,
  AgentExecutionRequest
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload) =>
      api.post<AgentExecutionResult>("/agents/execute", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: agentKeys.analytics() });
    },
  });
}

export function useAnalyticsOverview() {
  return useQuery({
    queryKey: agentKeys.overview(),
    queryFn: () => api.get<AgentAnalyticsOverview>("/agents/analytics/overview"),
    refetchInterval: 15_000,
  });
}

export function usePerformance() {
  return useQuery({
    queryKey: agentKeys.performance(),
    queryFn: () => api.get<AgentPerformance[]>("/agents/analytics/performance"),
    refetchInterval: 15_000,
  });
}

export function useLeaderboard(topN = 10) {
  return useQuery({
    queryKey: [...agentKeys.leaderboard(), topN],
    queryFn: () =>
      api.get<LeaderboardEntry[]>("/agents/analytics/leaderboard", {
        query: { top_n: topN },
      }),
    refetchInterval: 15_000,
  });
}

export function useAnalyticsHealth() {
  return useQuery({
    queryKey: agentKeys.healthSummary(),
    queryFn: () => api.get<HealthSummaryResponse>("/agents/analytics/health"),
    refetchInterval: 15_000,
  });
}

export function useCost() {
  return useQuery({
    queryKey: agentKeys.cost(),
    queryFn: () => api.get<CostEstimate>("/agents/analytics/cost"),
    refetchInterval: 30_000,
  });
}

export function useLatency(name: string) {
  return useQuery({
    queryKey: agentKeys.latency(name),
    queryFn: () =>
      api.get<LatencyDistribution>(
        `/agents/analytics/performance/${encodeURIComponent(name)}/latency`
      ),
    refetchInterval: 20_000,
    enabled: Boolean(name),
  });
}

export function useCollaborations() {
  return useQuery({
    queryKey: agentKeys.collaborations(),
    queryFn: () => api.get<AgentCollaboration[]>("/agents/collaborations"),
  });
}

export function useAgentMessages() {
  return useQuery({
    queryKey: agentKeys.messages(),
    queryFn: () => api.get<AgentMessage[]>("/agents/messages"),
    refetchInterval: 5_000,
  });
}

export function useWorkflows() {
  return useQuery({
    queryKey: agentKeys.workflows(),
    queryFn: () => api.get<WorkflowDefinition[]>("/agents/workflows"),
  });
}

export function useCreateWorkflow(): UseMutationResult<
  WorkflowDefinition,
  Error,
  Omit<WorkflowDefinition, "workflow_id" | "created_at">
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload) =>
      api.post<WorkflowDefinition>("/agents/workflows", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: agentKeys.workflows() }),
  });
}

export function useRunWorkflow(): UseMutationResult<
  { execution_id: string; status: string },
  Error,
  { workflow_id: string }
> {
  return useMutation({
    mutationFn: ({ workflow_id }) =>
      api.post(`/agents/workflows/${workflow_id}/run`),
  });
}

export function useExecution(id?: string) {
  return useQuery({
    queryKey: id ? agentKeys.execution(id) : agentKeys.execution("none"),
    queryFn: () => api.get(`/agents/executions/${id}`),
    enabled: Boolean(id),
    refetchInterval: (q) => {
      const data = q.state.data as { status?: string } | undefined;
      return data?.status === "running" ? 1500 : false;
    },
  });
}

export function useIntelligenceMetrics() {
  return useQuery({
    queryKey: agentKeys.intelligenceMetrics(),
    queryFn: () => api.get<IntelligenceAgentMetrics>("/agents/metrics"),
    refetchInterval: 10_000,
  });
}

export function useResearchHealth() {
  return useQuery({
    queryKey: agentKeys.researchHealth(),
    queryFn: () => api.get("/agents/research/health"),
    refetchInterval: 30_000,
  });
}

export function useComplianceHealth() {
  return useQuery({
    queryKey: agentKeys.complianceHealth(),
    queryFn: () => api.get("/agents/compliance/health"),
    refetchInterval: 30_000,
  });
}

export function useRiskAgentHealth() {
  return useQuery({
    queryKey: agentKeys.riskHealth(),
    queryFn: () => api.get("/agents/risk/health"),
    refetchInterval: 30_000,
  });
}

// ─── Research ────────────────────────────────────────────────────────
export const researchKeys = {
  all: ["research"] as const,
  reports: () => [...researchKeys.all, "reports"] as const,
  report: (id: string) => [...researchKeys.all, "reports", id] as const,
};

export function useResearchReports() {
  return useQuery({
    queryKey: researchKeys.reports(),
    queryFn: () => api.get<ResearchReport[]>("/research/reports"),
  });
}

export function useResearchReport(id?: string) {
  return useQuery({
    queryKey: id ? researchKeys.report(id) : researchKeys.report("none"),
    queryFn: () => api.get<ResearchReport>(`/research/reports/${id}`),
    enabled: Boolean(id),
  });
}

export function useRunResearch(): UseMutationResult<
  ResearchReport,
  Error,
  { query: string; depth?: number }
> {
  return useMutation({
    mutationFn: (payload) => api.post<ResearchReport>("/research/run", payload),
  });
}

// ─── Compliance Risk ─────────────────────────────────────────────────
export const complianceKeys = {
  all: ["compliance"] as const,
  list: () => [...complianceKeys.all, "list"] as const,
  detail: (id: string) => [...complianceKeys.all, "detail", id] as const,
};

export function useComplianceAssessments() {
  return useQuery({
    queryKey: complianceKeys.list(),
    queryFn: () =>
      api.get<PaginatedResponse<ComplianceAssessment>>(
        "/compliance-risk/assessments"
      ),
    select: (res) => res?.items ?? [],
  });
}

export function useComplianceAssessment(id?: string) {
  return useQuery({
    queryKey: id ? complianceKeys.detail(id) : complianceKeys.detail("none"),
    queryFn: () => api.get<ComplianceAssessment>(`/compliance-risk/assessments/${id}`),
    enabled: Boolean(id),
  });
}

export function useRunCompliance(): UseMutationResult<
  ComplianceAssessment,
  Error,
  { scope: string; policies?: string[] }
> {
  return useMutation({
    mutationFn: (payload) =>
      api.post<ComplianceAssessment>("/compliance-risk/assess", payload),
  });
}

// ─── Risk Forecasting ────────────────────────────────────────────────
export const riskKeys = {
  all: ["risk"] as const,
  forecasts: () => [...riskKeys.all, "forecasts"] as const,
  scenarios: () => [...riskKeys.all, "scenarios"] as const,
  trend: (id: string) => [...riskKeys.all, "trend", id] as const,
  stats: () => [...riskKeys.all, "stats"] as const,
};

export function useRiskForecasts() {
  return useQuery({
    queryKey: riskKeys.forecasts(),
    queryFn: () => api.get<RiskForecast[]>("/forecasting/forecasts"),
  });
}

export function useRiskScenarios() {
  return useQuery({
    queryKey: riskKeys.scenarios(),
    queryFn: () => api.get<RiskScenario[]>("/forecasting/scenarios"),
  });
}

export function useRiskTrend(documentId?: string) {
  return useQuery({
    queryKey: documentId ? riskKeys.trend(documentId) : riskKeys.trend("none"),
    queryFn: () => api.get<RiskProjection[]>(`/forecasting/trend/${documentId}`),
    enabled: Boolean(documentId),
  });
}

export function useForecastRisk(): UseMutationResult<
  RiskForecast,
  Error,
  { horizon_days: number; baseline_score?: number; drivers?: string[] }
> {
  return useMutation({
    mutationFn: (payload) => api.post<RiskForecast>("/forecasting/forecast", payload),
  });
}

// ─── Knowledge Graph ─────────────────────────────────────────────────
export const kgKeys = {
  all: ["kg"] as const,
  stats: () => [...kgKeys.all, "stats"] as const,
  nodes: () => [...kgKeys.all, "nodes"] as const,
  relationships: () => [...kgKeys.all, "relationships"] as const,
  impact: (id: string) => [...kgKeys.all, "impact", id] as const,
};

export function useGraphStats() {
  return useQuery({
    queryKey: kgKeys.stats(),
    queryFn: () => api.get<KnowledgeGraphStats>("/knowledge-graph/stats"),
  });
}

export function useGraphNodes() {
  return useQuery({
    queryKey: kgKeys.nodes(),
    queryFn: () => api.get<GraphNode[]>("/knowledge-graph/nodes"),
  });
}

export function useGraphRelationships() {
  return useQuery({
    queryKey: kgKeys.relationships(),
    queryFn: () => api.get<GraphRelationship[]>("/knowledge-graph/relationships"),
  });
}

export function useGraphImpact(nodeId?: string) {
  return useQuery({
    queryKey: nodeId ? kgKeys.impact(nodeId) : kgKeys.impact("none"),
    queryFn: () =>
      api.get<{ affected: GraphNode[]; total: number }>(
        `/knowledge-graph/impact-traversal/${nodeId}`
      ),
    enabled: Boolean(nodeId),
  });
}

// ─── Governance ──────────────────────────────────────────────────────
export const governanceKeys = {
  all: ["governance"] as const,
  policies: () => [...governanceKeys.all, "policies"] as const,
  policy: (id: string) => [...governanceKeys.all, "policies", id] as const,
  decisions: () => [...governanceKeys.all, "decisions"] as const,
  decision: (id: string) => [...governanceKeys.all, "decisions", id] as const,
  stats: () => [...governanceKeys.all, "stats"] as const,
};

export function usePolicies() {
  return useQuery({
    queryKey: governanceKeys.policies(),
    queryFn: () => api.get<GovernancePolicy[]>("/governance/policies"),
  });
}

export function usePolicy(id?: string) {
  return useQuery({
    queryKey: id ? governanceKeys.policy(id) : governanceKeys.policy("none"),
    queryFn: () => api.get<GovernancePolicy>(`/governance/policies/${id}`),
    enabled: Boolean(id),
  });
}

export function useDecisions() {
  return useQuery({
    queryKey: governanceKeys.decisions(),
    queryFn: () =>
      api.get<PaginatedResponse<GovernanceDecision>>("/governance/decisions"),
  });
}

export function useGovernanceStats() {
  return useQuery({
    queryKey: governanceKeys.stats(),
    queryFn: () =>
      api.get<{ total_policies: number; total_decisions: number; active: number; deprecated: number }>(
        "/governance/stats"
      ),
  });
}

// ─── Audit ───────────────────────────────────────────────────────────
export const auditKeys = {
  all: ["audit"] as const,
  records: () => [...auditKeys.all, "records"] as const,
  record: (id: string) => [...auditKeys.all, "records", id] as const,
  integrity: () => [...auditKeys.all, "integrity"] as const,
  reports: () => [...auditKeys.all, "reports"] as const,
  report: (id: string) => [...auditKeys.all, "reports", id] as const,
  evidence: () => [...auditKeys.all, "evidence"] as const,
};

export function useAuditRecords() {
  return useQuery({
    queryKey: auditKeys.records(),
    queryFn: () => api.get<PaginatedResponse<AuditRecord>>("/audit/records"),
  });
}

export function useAuditRecord(id?: string) {
  return useQuery({
    queryKey: id ? auditKeys.record(id) : auditKeys.record("none"),
    queryFn: () => api.get<AuditRecord>(`/audit/records/${id}`),
    enabled: Boolean(id),
  });
}

export function useAuditIntegrity() {
  return useQuery({
    queryKey: auditKeys.integrity(),
    queryFn: () => api.get<AuditIntegrity>("/audit/integrity"),
    refetchInterval: 60_000,
  });
}

export function useAuditReports() {
  return useQuery({
    queryKey: auditKeys.reports(),
    queryFn: () => api.get<ComplianceReport[]>("/audit/reports"),
  });
}

export function useAuditEvidence() {
  return useQuery({
    queryKey: auditKeys.evidence(),
    queryFn: () => api.get<AuditEvidence[]>("/audit/evidence"),
  });
}

// ─── Admin ───────────────────────────────────────────────────────────
export const adminKeys = {
  all: ["admin"] as const,
  overview: () => [...adminKeys.all, "overview"] as const,
  stats: () => [...adminKeys.all, "stats"] as const,
  users: () => [...adminKeys.all, "users"] as const,
  user: (id: string) => [...adminKeys.all, "users", id] as const,
  roles: () => [...adminKeys.all, "roles"] as const,
};

export function useAdminOverview() {
  return useQuery({
    queryKey: adminKeys.overview(),
    queryFn: () => api.get<AdminOverview>("/admin/overview"),
  });
}

export function useAdminStats() {
  return useQuery({
    queryKey: adminKeys.stats(),
    queryFn: () => api.get<AdminStats>("/admin/stats"),
  });
}

export function useUsers() {
  return useQuery({
    queryKey: adminKeys.users(),
    queryFn: () => api.get<PaginatedResponse<AdminUser>>("/admin/users"),
  });
}

export function useRoles() {
  return useQuery({
    queryKey: adminKeys.roles(),
    queryFn: () => api.get<PaginatedResponse<AdminRole>>("/admin/roles"),
  });
}

// ─── Monitoring / Ingestion / Changes / Impact ───────────────────────
export function useAlerts() {
  return useQuery({
    queryKey: ["alerts"],
    queryFn: () => api.get<PaginatedResponse<MonitoringAlert>>("/alerts"),
    select: (res) => res?.items ?? [],
    refetchInterval: 30_000,
  });
}

export function useIngestionJobs() {
  return useQuery({
    queryKey: ["ingestion", "jobs"],
    queryFn: () => api.get<IngestionJob[]>("/ingestion/jobs"),
  });
}

export function useChanges() {
  return useQuery({
    queryKey: ["changes"],
    queryFn: () => api.get<PaginatedResponse<ChangeEvent>>("/changes"),
    select: (res) => res?.items ?? [],
  });
}

export function useImpact(documentId?: string) {
  return useQuery({
    queryKey: documentId ? ["impact", documentId] : ["impact", "none"],
    queryFn: () => api.get<ImpactAnalysis>(`/impact/${documentId}`),
    enabled: Boolean(documentId),
  });
}

// ─── Workflows / Reviews / Recommendations ───────────────────────────
export function useWorkflowInstances() {
  return useQuery({
    queryKey: ["workflow", "instances"],
    queryFn: () => api.get<WorkflowInstance[]>("/workflow/instances"),
  });
}

export function useReviewTasks() {
  return useQuery({
    queryKey: ["review", "tasks"],
    queryFn: () => api.get<PaginatedResponse<ReviewTask>>("/review/tasks"),
    select: (res) => res?.items ?? [],
  });
}

export function useRecommendations() {
  return useQuery({
    queryKey: ["recommendations"],
    queryFn: () => api.get<PaginatedResponse<Recommendation>>("/recommendations"),
    select: (res) => res?.items ?? [],
  });
}

// ─── Documents ───────────────────────────────────────────────────────
export function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: () => api.get<PaginatedResponse<Document>>("/documents"),
  });
}
