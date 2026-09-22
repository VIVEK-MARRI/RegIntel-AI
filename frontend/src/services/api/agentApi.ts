import { LONG_TIMEOUT_MS, api, encodePathSegment } from "@/lib/api";
import type {
  AgentBusMessage,
  AgentCollaboration,
  AgentHealthCheck,
  AgentMetadata,
  AgentResult,
  AgentWorkflow,
  PaginatedAgents,
  RunWorkflowRequest,
  WorkflowDefinition,
  WorkflowDefinitionCreate,
} from "@/types/api/agents";

export async function getAgents(): Promise<PaginatedAgents> {
  return api.get<PaginatedAgents>("/agents/agents");
}

export async function getAgent(name: string): Promise<AgentMetadata> {
  return api.get<AgentMetadata>(`/agents/agents/${encodePathSegment(name)}`);
}

export async function getAgentHealth(name: string): Promise<AgentHealthCheck> {
  return api.get<AgentHealthCheck>(
    `/agents/agents/${encodePathSegment(name)}/health`
  );
}

export interface ExecuteAgentRequest {
  agent_name: string;
  capability: string;
  input?: Record<string, unknown>;
  context?: Record<string, unknown>;
  max_retries?: number;
  timeout_ms?: number;
}

export async function executeAgent(payload: ExecuteAgentRequest): Promise<AgentResult> {
  return api.post<AgentResult>("/agents/execute", payload, {
    timeoutMs: LONG_TIMEOUT_MS,
  });
}

export async function getCollaborations(): Promise<AgentCollaboration[]> {
  return api.get<AgentCollaboration[]>("/agents/collaborations");
}

export async function getAgentMessages(): Promise<AgentBusMessage[]> {
  return api.get<AgentBusMessage[]>("/agents/messages");
}

export async function getWorkflows(): Promise<WorkflowDefinition[]> {
  return api.get<WorkflowDefinition[]>("/agents/workflows");
}

export async function createWorkflow(
  payload: WorkflowDefinitionCreate
): Promise<WorkflowDefinition> {
  return api.post<WorkflowDefinition>("/agents/workflows", payload);
}

export async function runWorkflow(
  workflowId: string,
  payload: RunWorkflowRequest = {}
): Promise<AgentWorkflow> {
  return api.post<AgentWorkflow>(
    `/agents/workflows/${encodePathSegment(workflowId)}/run`,
    payload
  );
}

export async function getExecution(id: string): Promise<unknown> {
  return api.get<unknown>(`/agents/executions/${encodePathSegment(id)}`);
}
