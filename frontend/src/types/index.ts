/**
 * Generic shared types used across the UI. These are derived from the
 * RegIntel AI backend Pydantic schemas but kept loose (strings + numbers)
 * to remain resilient to API evolution.
 */

export type Dict<T = unknown> = Record<string, T>;

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApiError {
  status: number;
  message: string;
  detail?: unknown;
}

export type HealthLevel = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface HealthSummaryResponse {
  total_agents: number;
  healthy_agents: number;
  degraded_agents: number;
  unhealthy_agents: number;
  unknown_agents: number;
  overall_health: HealthLevel;
  agents: AgentHealthItem[];
  notes: string;
}

export interface AgentHealthItem {
  agent_name: string;
  total_invocations: number;
  success_count: number;
  failure_count: number;
  success_rate: number;
  average_duration_ms: number;
  average_confidence: number;
  last_invocation_at: number;
  last_error: string;
  health: HealthLevel;
}

export interface CopilotRequestPayload {
  query: string;
  conversation_id?: string | null;
  user_id?: string | null;
  mode?: "answer" | "summarise" | "search";
  use_memory?: boolean;
  memory_top_k?: number;
  metadata?: Dict;
}

export interface CopilotCitation {
  citation_id: string;
  chunk_id?: string;
  document_id?: string;
  page?: number | null;
  start_char?: number | null;
  end_char?: number | null;
  text: string;
  confidence: number;
  source_label?: string;
}

export interface CopilotAttribution {
  source_id: string;
  document_id: string;
  document_title?: string;
  chunk_id?: string;
  relevance: number;
  excerpt?: string;
}

export interface CopilotMessage {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: string;
  agent_contributions?: AgentContributionItem[];
  citations?: CopilotCitation[];
  sources?: CopilotAttribution[];
  confidence_score?: number;
  confidence_level?: string;
  faithfulness_score?: number;
  hallucination_detected?: boolean;
  hallucination_risk_level?: string;
  memory_context?: MemoryContext;
  latency_ms?: number;
}

export interface MemoryContext {
  short_term: Array<{ content: string; relevance: number; created_at?: string }>;
  long_term: Array<{ content: string; relevance: number; created_at?: string }>;
  entities: string[];
}

export interface AgentContributionItem {
  agent_name: string;
  capability: string;
  output: string;
  confidence: number;
  duration_ms: number;
  status: string;
  depends_on?: string[];
}

export interface CopilotResponsePayload {
  request_id: string;
  conversation_id: string;
  query: string;
  answer: string | null;
  citations: CopilotCitation[];
  sources: CopilotAttribution[];
  confidence_score: number;
  confidence_level: string;
  faithfulness_score: number;
  hallucination_detected: boolean;
  hallucination_risk_level: string;
  memory_used: boolean;
  memory_context: MemoryContext;
  history: CopilotMessage[];
  latency_ms: number;
  agent_contributions: AgentContributionItem[];
  attribution_coverage_ratio: number;
}

export interface AgentSummary {
  agent_id: string;
  name: string;
  description?: string;
  capabilities: string[];
  tags?: string[];
  status?: string;
  registered_at?: string;
}

export interface AgentDetail extends AgentSummary {
  config: Dict;
  metadata: Dict;
  statistics: Dict;
}

export interface AgentPerformance {
  agent_name: string;
  total_invocations: number;
  success_count: number;
  failure_count: number;
  success_rate: number;
  average_duration_ms: number;
  average_confidence: number;
  p50_duration_ms?: number;
  p90_duration_ms?: number;
  p95_duration_ms?: number;
  p99_duration_ms?: number;
  health: HealthLevel;
  last_invocation_at: number;
  last_error: string;
}

export interface LeaderboardEntry {
  rank: number;
  agent_name: string;
  score: number;
  success_rate: number;
  average_confidence: number;
  average_duration_ms: number;
  invocations: number;
}

export interface LatencyDistribution {
  agent_name: string;
  p50: number;
  p90: number;
  p95: number;
  p99: number;
  min: number;
  max: number;
  average: number;
  count: number;
  buckets: Array<{ range: string; count: number }>;
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

export interface AgentAnalyticsOverview {
  total_agents: number;
  total_invocations: number;
  success_rate: number;
  average_duration_ms: number;
  average_confidence: number;
  health: HealthSummaryResponse;
  cost: CostEstimate;
  leaderboard: LeaderboardEntry[];
  generated_at: number;
  notes: string;
}

export interface AgentExecutionRequest {
  agent_name: string;
  input: string | Dict;
  context?: Dict;
  metadata?: Dict;
}

export interface AgentExecutionResult {
  execution_id: string;
  agent_name: string;
  output: string | Dict;
  confidence: number;
  duration_ms: number;
  status: "succeeded" | "failed" | "running";
  error?: string;
  metadata: Dict;
  citations?: CopilotCitation[];
  started_at: number;
  completed_at: number;
}

export interface WorkflowDefinition {
  workflow_id: string;
  name: string;
  description?: string;
  steps: Array<{
    step_id: string;
    agent_name: string;
    capability: string;
    depends_on: string[];
    timeout_ms?: number;
    max_retries?: number;
  }>;
  created_at?: string;
}

export interface AgentMessage {
  message_id: string;
  from_agent: string;
  to_agent?: string;
  channel: string;
  kind: string;
  payload: Dict;
  created_at: number;
}

export interface IntelligenceAgentMetrics {
  total_invocations: number;
  succeeded: number;
  failed: number;
  average_confidence: number;
  average_duration_ms: number;
  per_agent: Array<{
    agent_name: string;
    invocations: number;
    succeeded: number;
    failed: number;
    average_confidence: number;
    average_duration_ms: number;
  }>;
  collaborations: number;
}

export interface AgentCollaboration {
  collaboration_id: string;
  topic: string;
  participants: string[];
  messages: AgentMessage[];
  consensus: number;
  result_summary: string;
  created_at: number;
}

export interface ResearchPlanStep {
  step_id: string;
  description: string;
  tools: string[];
  estimated_duration_ms: number;
  status: "pending" | "running" | "done" | "failed";
}

export interface ResearchFinding {
  finding_id: string;
  title: string;
  content: string;
  source_ids: string[];
  confidence: number;
  relevance: number;
}

export interface ResearchReport {
  report_id: string;
  query: string;
  plan: ResearchPlanStep[];
  findings: ResearchFinding[];
  summary: string;
  confidence: number;
  created_at: number;
  sources: CopilotAttribution[];
}

export interface ComplianceObligation {
  obligation_id: string;
  title: string;
  description: string;
  policy_id: string;
  severity: "low" | "medium" | "high" | "critical";
  due_date?: string;
  status: "open" | "in_progress" | "met" | "breached";
}

export interface ComplianceGap {
  gap_id: string;
  obligation_id: string;
  description: string;
  severity: "low" | "medium" | "high" | "critical";
  recommended_actions: string[];
  detected_at: number;
}

export interface ComplianceAssessment {
  assessment_id: string;
  scope: string;
  obligations: ComplianceObligation[];
  gaps: ComplianceGap[];
  overall_score: number;
  risk_level: "low" | "medium" | "high" | "critical";
  generated_at: number;
}

export interface RiskScenario {
  scenario_id: string;
  name: string;
  description: string;
  probability: number;
  impact: "low" | "medium" | "high" | "critical";
  drivers: string[];
}

export interface RiskProjection {
  projection_id: string;
  horizon_days: number;
  baseline_score: number;
  projected_score: number;
  confidence: number;
  drivers: string[];
  scenario_id?: string;
  created_at: number;
}

export interface GraphNode {
  node_id: string;
  label: string;
  type: string;
  properties: Dict;
}

export interface GraphRelationship {
  rel_id: string;
  source: string;
  target: string;
  type: string;
  properties: Dict;
}

export interface KnowledgeGraphStats {
  node_count: number;
  relationship_count: number;
  nodes_by_type: Record<string, number>;
  relationships_by_type: Record<string, number>;
  generated_at: number;
}

export interface GovernancePolicy {
  policy_id: string;
  name: string;
  description: string;
  scope: string;
  rules: Array<{ rule_id: string; description: string; severity: string }>;
  status: "draft" | "active" | "deprecated";
  version: number;
  updated_at: number;
  created_by?: string;
}

export interface GovernanceDecision {
  decision_id: string;
  decision_type: string;
  subject: string;
  outcome: string;
  confidence: number;
  policy_ids: string[];
  rationale: string;
  approver?: string;
  created_at: number;
}

export interface AuditRecord {
  audit_id: string;
  actor: string;
  action: string;
  subject: string;
  outcome: string;
  timestamp: number;
  evidence_ids: string[];
  metadata: Dict;
}

export interface AuditEvidence {
  evidence_id: string;
  audit_id: string;
  kind: string;
  payload: Dict;
  signature: string;
  created_at: number;
}

export interface AuditIntegrity {
  total: number;
  valid: number;
  invalid: number;
  broken_chains: string[];
  checked_at: number;
}

export interface ComplianceReport {
  report_id: string;
  title: string;
  scope: string;
  period_start: string;
  period_end: string;
  status: "draft" | "published";
  sections: Array<{ heading: string; body: string }>;
  generated_at: number;
}

export interface AdminUser {
  user_id: string;
  name: string;
  email: string;
  roles: string[];
  status: "active" | "suspended" | "pending";
  created_at: number;
  last_login_at?: number;
}

export interface AdminRole {
  role_id: string;
  name: string;
  description: string;
  permissions: string[];
  member_count: number;
}

export interface AdminStats {
  total_users: number;
  active_users: number;
  total_roles: number;
  total_policies: number;
  total_audit_records: number;
  total_decisions: number;
  system_health: HealthLevel;
  generated_at: number;
}

export interface AdminOverview {
  users: { total: number; active: number; suspended: number };
  policies: { total: number; active: number; draft: number };
  audit: { total: number; last_24h: number };
  compliance_score: number;
  notes: string;
  generated_at: number;
}

export interface MonitoringAlert {
  alert_id: string;
  severity: "info" | "warning" | "critical";
  title: string;
  description: string;
  source: string;
  detected_at: number;
  status: "open" | "acknowledged" | "resolved";
}

export interface IngestionJob {
  job_id: string;
  source: string;
  status: "queued" | "running" | "succeeded" | "failed";
  documents_total: number;
  documents_processed: number;
  started_at: number;
  completed_at?: number;
  error?: string;
}

export interface ChangeEvent {
  change_id: string;
  document_id: string;
  change_type: "added" | "modified" | "removed";
  summary: string;
  impact_score: number;
  detected_at: number;
}

export interface ImpactAnalysis {
  analysis_id: string;
  root_document_id: string;
  affected_documents: Array<{ document_id: string; impact_score: number }>;
  total_impact: number;
  generated_at: number;
}

export interface WorkflowInstance {
  workflow_id: string;
  name: string;
  status: "pending" | "running" | "paused" | "completed" | "failed";
  tasks: Array<{
    task_id: string;
    name: string;
    status: string;
    assignee?: string;
    completed_at?: number;
  }>;
  created_at: number;
  updated_at: number;
}

export interface ReviewTask {
  task_id: string;
  subject: string;
  description: string;
  reviewer: string;
  status: "pending" | "approved" | "rejected" | "needs_changes";
  due_at?: number;
  created_at: number;
}

export interface Recommendation {
  recommendation_id: string;
  title: string;
  description: string;
  type: string;
  priority: "P0" | "P1" | "P2" | "P3" | "P4";
  rationale: string;
  actions: string[];
  confidence: number;
  created_at: number;
  status: "open" | "accepted" | "rejected";
}

export interface RiskForecast {
  forecast_id: string;
  horizon_days: number;
  baseline_score: number;
  projected_score: number;
  confidence: number;
  drivers: string[];
  created_at: number;
}

export interface Document {
  document_id: string;
  title: string;
  source: string;
  jurisdiction?: string;
  status: string;
  created_at: number;
  chunk_count: number;
}

export interface ChatSession {
  conversation_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
  preview: string;
}
