/**
 * Consistent query-key factories. Pages must use these instead of inventing
 * ad-hoc keys, so Stage 06+ invalidation is reliable:
 * same endpoint + same params ⇒ same key, everywhere.
 */
export const healthKeys = {
  all: ["health"] as const,
  ready: () => [...healthKeys.all, "ready"] as const,
};

export const documentsKeys = {
  all: ["documents"] as const,
  list: (params?: { source?: string; status?: string; skip?: number; limit?: number }) =>
    [...documentsKeys.all, "list", params ?? {}] as const,
  detail: (id: string) => [...documentsKeys.all, "detail", id] as const,
  ingestionJobs: () => ["ingestion", "jobs"] as const,
  ingestionRun: (id: string) => ["ingestion", "run", id] as const,
  chunks: (id: string) => [...documentsKeys.all, "chunks", id] as const,
  pages: (id: string) => [...documentsKeys.all, "pages", id] as const,
};

export const copilotKeys = {
  all: ["copilot"] as const,
  sessions: () => [...copilotKeys.all, "sessions"] as const,
  messages: (id: string) => [...copilotKeys.all, "messages", id] as const,
};

export const researchKeys = {
  all: ["research"] as const,
  stats: () => [...researchKeys.all, "stats"] as const,
  reports: (params?: { kind?: string; page?: number; page_size?: number }) =>
    [...researchKeys.all, "reports", params ?? {}] as const,
  report: (id: string) => [...researchKeys.all, "report", id] as const,
};

export const kgKeys = {
  all: ["kg"] as const,
  stats: () => [...kgKeys.all, "stats"] as const,
  nodes: (params?: { entity_type?: string; source?: string; name_contains?: string; tag?: string; page?: number; page_size?: number }) =>
    [...kgKeys.all, "nodes", params ?? {}] as const,
  node: (id: string) => [...kgKeys.all, "node", id] as const,
  relationships: (params?: { source_id?: string; target_id?: string; rel_type?: string }) =>
    [...kgKeys.all, "relationships", params ?? {}] as const,
  impact: (id: string, depth: number, relType?: string) =>
    [...kgKeys.all, "impact", id, depth, relType ?? ""] as const,
  dependency: (id: string, depth: number) =>
    [...kgKeys.all, "dependency", id, depth] as const,
};

export const complianceKeys = {
  all: ["compliance"] as const,
  stats: () => [...complianceKeys.all, "stats"] as const,
  trend: (documentId?: string) => [...complianceKeys.all, "trend", documentId ?? ""] as const,
  // assessments() stays paramless: Dashboard consumes it with a bare queryFn.
  assessments: () => [...complianceKeys.all, "assessments"] as const,
  assessmentsFiltered: (params?: { risk_level?: string; category?: string; document_id?: string; page?: number; page_size?: number }) =>
    [...complianceKeys.all, "assessments", "filtered", params ?? {}] as const,
  assessment: (id: string) => [...complianceKeys.all, "assessment", id] as const,
};

export const riskKeys = {
  all: ["risk"] as const,
  stats: () => [...riskKeys.all, "stats"] as const,
  forecasts: () => [...riskKeys.all, "forecasts"] as const,
  scenarios: () => [...riskKeys.all, "scenarios"] as const,
};

export const governanceKeys = {
  all: ["governance"] as const,
  policies: () => [...governanceKeys.all, "policies"] as const,
  approvalPolicies: () => [...governanceKeys.all, "approval-policies"] as const,
  decisions: (params?: { decision_type?: string; policy_compliant?: boolean }) =>
    [...governanceKeys.all, "decisions", params ?? {}] as const,
  stats: () => [...governanceKeys.all, "stats"] as const,
};

export const auditKeys = {
  all: ["audit"] as const,
  integrity: () => [...auditKeys.all, "integrity"] as const,
  stats: () => [...auditKeys.all, "stats"] as const,
  records: (params?: { action?: string; severity?: string; actor?: string; subject_type?: string; subject_id?: string; source_module?: string; after?: number; before?: number; text_query?: string; page?: number; page_size?: number }) =>
    [...auditKeys.all, "records", params ?? {}] as const,
  record: (id: string) => [...auditKeys.all, "record", id] as const,
  evidence: (params?: { record_id?: string }) =>
    [...auditKeys.all, "evidence", params ?? {}] as const,
  evidenceDetail: (id: string) => [...auditKeys.all, "evidence", "detail", id] as const,
  reports: (params?: { kind?: string }) =>
    [...auditKeys.all, "reports", params ?? {}] as const,
};

export const analyticsKeys = {
  all: ["analytics"] as const,
  overview: () => [...analyticsKeys.all, "overview"] as const,
  performance: () => [...analyticsKeys.all, "performance"] as const,
  intelligence: () => [...analyticsKeys.all, "intelligence"] as const,
  health: () => [...analyticsKeys.all, "health"] as const,
  cost: () => [...analyticsKeys.all, "cost"] as const,
  leaderboard: (topN: number) => [...analyticsKeys.all, "leaderboard", topN] as const,
  latency: (name: string) => [...analyticsKeys.all, "latency", name] as const,
};

export const dashboardKeys = {
  all: ["dashboard"] as const,
  compliance: () => [...dashboardKeys.all, "compliance"] as const,
  trends: () => [...dashboardKeys.all, "trends"] as const,
  impact: () => [...dashboardKeys.all, "impact"] as const,
  alerts: () => [...dashboardKeys.all, "alerts"] as const,
  monitoring: () => [...dashboardKeys.all, "monitoring"] as const,
  system: () => [...dashboardKeys.all, "system"] as const,
  insights: () => [...dashboardKeys.all, "insights"] as const,
};

export const agentsKeys = {
  all: ["agents"] as const,
  list: (params?: { capability?: string; text_query?: string; tag?: string; page?: number; page_size?: number }) =>
    [...agentsKeys.all, "list", params ?? {}] as const,
  agent: (name: string) => [...agentsKeys.all, "agent", name] as const,
  agentHealth: (name: string) => [...agentsKeys.all, "agent-health", name] as const,
  workflows: () => [...agentsKeys.all, "workflows"] as const,
  collaborations: () => [...agentsKeys.all, "collaborations"] as const,
  messages: (params?: { from_agent?: string; to_agent?: string; limit?: number }) =>
    [...agentsKeys.all, "messages", params ?? {}] as const,
};

export const adminKeys = {
  all: ["admin"] as const,
  me: () => [...adminKeys.all, "me"] as const,
  overview: () => [...adminKeys.all, "overview"] as const,
  stats: () => [...adminKeys.all, "stats"] as const,
  users: (params?: { status?: string; role_id?: string; department?: string; text_query?: string; page?: number; page_size?: number }) =>
    [...adminKeys.all, "users", params ?? {}] as const,
  user: (id: string) => [...adminKeys.all, "user", id] as const,
  roles: (params?: { built_in?: boolean; text_query?: string; page?: number; page_size?: number }) =>
    [...adminKeys.all, "roles", params ?? {}] as const,
  role: (id: string) => [...adminKeys.all, "role", id] as const,
  rbac: (userId: string, permission: string) =>
    [...adminKeys.all, "rbac", userId, permission] as const,
  settings: () => [...adminKeys.all, "settings"] as const,
};
