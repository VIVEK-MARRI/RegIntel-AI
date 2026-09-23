import { LONG_TIMEOUT_MS, api, encodePathSegment } from "@/lib/api";
import type {
  AgentBusMessage,
  AgentCollaboration,
  AgentExecutionRequest,
  AgentHealthCheck,
  AgentMetadata,
  AgentRegistrationRequest,
  AgentResult,
  AgentWorkflow,
  CoordinatorRequest,
  CoordinatorResult,
  MessagesQuery,
  PaginatedAgents,
  RunWorkflowRequest,
  WorkflowDefinition,
  WorkflowDefinitionCreate,
} from "@/types/api/agents";
import type { AgentListQuery } from "@/types/api/agents";

export async function getAgents(query?: AgentListQuery): Promise<PaginatedAgents> {
  return api.get<PaginatedAgents>("/agents/agents", { query });
}

export async function getAgent(name: string): Promise<AgentMetadata> {
  return api.get<AgentMetadata>(`/agents/agents/${encodePathSegment(name)}`);
}

export async function getAgentHealth(name: string): Promise<AgentHealthCheck> {
  return api.get<AgentHealthCheck>(
    `/agents/agents/${encodePathSegment(name)}/health`
  );
}

export async function registerAgent(payload: AgentRegistrationRequest): Promise<AgentMetadata> {
  // Note: the backend registers a metadata/echo agent over HTTP (see the
  // route docstring); programmatic BaseAgent registration is service-side.
  return api.post<AgentMetadata>("/agents/agents", payload);
}

export async function unregisterAgent(name: string): Promise<{ unregistered: string }> {
  return api.del<{ unregistered: string }>(`/agents/agents/${encodePathSegment(name)}`);
}

export async function executeAgent(payload: AgentExecutionRequest): Promise<AgentResult> {
  // Blocking: the backend awaits handler completion and returns AgentResult.
  return api.post<AgentResult>("/agents/execute", payload, {
    timeoutMs: LONG_TIMEOUT_MS,
  });
}

export async function coordinate(payload: CoordinatorRequest): Promise<CoordinatorResult> {
  // Blocking: deterministic keyword planner + distributor, full result returned.
  return api.post<CoordinatorResult>("/agents/coordinate", payload, {
    timeoutMs: LONG_TIMEOUT_MS,
  });
}

export async function getCollaborations(): Promise<AgentCollaboration[]> {
  return api.get<AgentCollaboration[]>("/agents/collaborations");
}

export async function getAgentMessages(query?: MessagesQuery): Promise<AgentBusMessage[]> {
  return api.get<AgentBusMessage[]>("/agents/messages", { query });
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
