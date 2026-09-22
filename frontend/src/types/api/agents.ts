/**
 * Agents contracts. Backend: app/api/v1/agents.py (registry/execute) +
 * app/api/v1/orchestration.py (messages/workflows/executions) +
 * app/api/v1/intelligence_agents.py (collaborations/metrics) and schemas
 * agents.py / orchestration.py / intelligence_agents.py (extra="forbid").
 * Timestamps are epoch SECONDS (float).
 */
import type { PaginatedResponse } from "./common";

export type CapabilityKind =
  | "retrieval" | "reasoning" | "summarization" | "classification"
  | "extraction" | "risk_assessment" | "recommendation" | "forecasting"
  | "knowledge_graph" | "change_detection" | "impact_analysis" | "alerting"
  | "audit" | "governance" | "workflow" | "review" | "compliance"
  | "orchestration" | "other";

export type AgentStatus =
  | "registered" | "active" | "busy" | "paused" | "failed" | "disabled";

export type TaskStatus =
  | "pending" | "running" | "succeeded" | "failed"
  | "timed_out" | "retrying" | "cancelled";

export type WorkflowStatus =
  | "pending" | "running" | "succeeded" | "failed"
  | "partially_succeeded" | "cancelled" | "timed_out";

export type MessageKind =
  | "task" | "result" | "evidence" | "query" | "status"
  | "error" | "ack" | "control";

export interface AgentCapability {
  capability_id: string;
  kind: CapabilityKind;
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
}

export interface AgentMetadata {
  agent_id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  capabilities: AgentCapability[];
  status: AgentStatus;
  default_max_retries: number;
  default_timeout_ms: number;
  priority: number;
  tags: string[];
  registered_at: number;
  updated_at: number;
  metadata: Record<string, unknown>;
}

export type PaginatedAgents = PaginatedResponse<AgentMetadata>;

export interface AgentHealthCheck {
  agent_id: string;
  healthy: boolean;
  last_error: string;
  consecutive_failures: number;
  total_invocations: number;
  successful_invocations: number;
  failed_invocations: number;
  average_duration_ms: number;
  last_invocation_at: number | null;
  last_success_at: number | null;
  last_failure_at: number | null;
}

export interface AgentExecutionRequest {
  agent_name: string;
  capability: CapabilityKind;
  input?: Record<string, unknown>;
  context?: Record<string, unknown>;
  max_retries?: number;
  timeout_ms?: number;
}

export interface AgentResult {
  result_id: string;
  task_id: string;
  agent_id: string;
  agent_name: string;
  status: TaskStatus;
  output: Record<string, unknown>;
  error: string;
  attempts: number;
  duration_ms: number;
  started_at: number | null;
  completed_at: number | null;
  metadata: Record<string, unknown>;
}

export interface AgentExecutionStep {
  step_id: string;
  agent_name: string;
  capability: string;
  description: string;
  depends_on: string[];
  input_template: Record<string, unknown>;
  timeout_ms: number | null;
  max_retries: number;
}

export interface AgentExecutionGraph {
  graph_id: string;
  steps: AgentExecutionStep[];
  mode: string;
  created_at: number;
  metadata: Record<string, unknown>;
}

/** POST /agents/workflows body: the FULL definition MINUS server-set fields. */
export interface WorkflowDefinitionCreate {
  name: string;
  description?: string;
  graph: {
    steps: Array<Partial<AgentExecutionStep> & { agent_name: string }>;
    mode?: string;
    graph_id?: string;
    created_at?: number;
    metadata?: Record<string, unknown>;
  };
  tags?: string[];
  version?: string;
  metadata?: Record<string, unknown>;
}

export interface WorkflowDefinition {
  workflow_id: string;
  name: string;
  description: string;
  graph: AgentExecutionGraph;
  tags: string[];
  version: string;
  created_at: number;
  metadata: Record<string, unknown>;
}

export interface AgentWorkflow {
  run_id: string;
  workflow_id: string;
  workflow_name: string;
  status: WorkflowStatus;
  started_at: number;
  completed_at: number | null;
  duration_ms: number;
  result?: Record<string, unknown> | null;
  error: string;
  metadata: Record<string, unknown>;
}

/** POST /agents/workflows/{id}/run body: ambitious callers pass {query}. */
export interface RunWorkflowRequest {
  query?: string;
}

export interface AgentCollaboration {
  collaboration_id: string;
  from_agent: string;
  to_agent: string;
  request_kind: string;
  evidence_keys: string[];
  result_keys: string[];
  shared_context_keys: string[];
  duration_ms: number;
  created_at: number;
}

export interface AgentBusMessage {
  message_id: string;
  from_agent: string;
  to_agent: string;
  kind: MessageKind;
  payload: Record<string, unknown>;
  correlation_id: string;
  in_reply_to: string;
  created_at: number;
  ttl_ms: number;
}