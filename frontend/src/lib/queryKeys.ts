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
  list: () => [...documentsKeys.all, "list"] as const,
  detail: (id: string) => [...documentsKeys.all, "detail", id] as const,
  ingestionJobs: () => ["ingestion", "jobs"] as const,
};

export const copilotKeys = {
  all: ["copilot"] as const,
  sessions: () => [...copilotKeys.all, "sessions"] as const,
  messages: (id: string) => [...copilotKeys.all, "messages", id] as const,
};

export const researchKeys = {
  all: ["research"] as const,
  reports: () => [...researchKeys.all, "reports"] as const,
  report: (id: string) => [...researchKeys.all, "report", id] as const,
};

export const kgKeys = {
  all: ["kg"] as const,
  stats: () => [...kgKeys.all, "stats"] as const,
  nodes: () => [...kgKeys.all, "nodes"] as const,
  impact: (id: string) => [...kgKeys.all, "impact", id] as const,
};

export const complianceKeys = {
  all: ["compliance"] as const,
  assessments: () => [...complianceKeys.all, "assessments"] as const,
  assessment: (id: string) => [...complianceKeys.all, "assessment", id] as const,
};

export const riskKeys = {
  all: ["risk"] as const,
  forecasts: () => [...riskKeys.all, "forecasts"] as const,
  scenarios: () => [...riskKeys.all, "scenarios"] as const,
};

export const governanceKeys = {
  all: ["governance"] as const,
  policies: () => [...governanceKeys.all, "policies"] as const,
  decisions: () => [...governanceKeys.all, "decisions"] as const,
  stats: () => [...governanceKeys.all, "stats"] as const,
};

export const auditKeys = {
  all: ["audit"] as const,
  records: () => [...auditKeys.all, "records"] as const,
  integrity: () => [...auditKeys.all, "integrity"] as const,
  reports: () => [...auditKeys.all, "reports"] as const,
  evidence: () => [...auditKeys.all, "evidence"] as const,
};

export const analyticsKeys = {
  all: ["analytics"] as const,
  overview: () => [...analyticsKeys.all, "overview"] as const,
  performance: () => [...analyticsKeys.all, "performance"] as const,
  intelligence: () => [...analyticsKeys.all, "intelligence"] as const,
  changes: () => [...analyticsKeys.all, "changes"] as const,
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
  list: () => [...agentsKeys.all, "list"] as const,
  health: () => [...agentsKeys.all, "health"] as const,
  workflows: () => [...agentsKeys.all, "workflows"] as const,
  collaborations: () => [...agentsKeys.all, "collaborations"] as const,
  messages: () => [...agentsKeys.all, "messages"] as const,
};

export const adminKeys = {
  all: ["admin"] as const,
  overview: () => [...adminKeys.all, "overview"] as const,
  stats: () => [...adminKeys.all, "stats"] as const,
  users: () => [...adminKeys.all, "users"] as const,
  roles: () => [...adminKeys.all, "roles"] as const,
};
