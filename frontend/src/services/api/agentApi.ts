import { api } from "@/lib/api";
import type {
  AgentCollaboration,
  AgentDetail,
  AgentExecutionRequest,
  AgentExecutionResult,
  AgentMessage,
  AgentSummary,
  PaginatedResponse,
  WorkflowDefinition,
} from "@/types";

export async function getAgents(): Promise<PaginatedResponse<AgentSummary>> {
  return api.get<PaginatedResponse<AgentSummary>>("/agents/agents");
}

export async function getAgent(name: string): Promise<AgentDetail> {
  return api.get<AgentDetail>(`/agents/agents/${name}`);
}

export async function getAgentHealth(name: string): Promise<{ health: string; notes: string }> {
  return api.get<{ health: string; notes: string }>(`/agents/agents/${name}/health`);
}

export async function executeAgent(payload: AgentExecutionRequest): Promise<AgentExecutionResult> {
  return api.post<AgentExecutionResult>("/agents/execute", payload);
}

export async function getCollaborations(): Promise<AgentCollaboration[]> {
  return api.get<AgentCollaboration[]>("/agents/collaborations");
}

export async function getAgentMessages(): Promise<AgentMessage[]> {
  return api.get<AgentMessage[]>("/agents/messages");
}

export async function getWorkflows(): Promise<WorkflowDefinition[]> {
  return api.get<WorkflowDefinition[]>("/agents/workflows");
}

export async function createWorkflow(payload: Omit<WorkflowDefinition, "workflow_id" | "created_at">): Promise<WorkflowDefinition> {
  return api.post<WorkflowDefinition>("/agents/workflows", payload);
}

export async function runWorkflow(workflowId: string): Promise<{ execution_id: string; status: string }> {
  return api.post<{ execution_id: string; status: string }>(`/agents/workflows/${workflowId}/run`);
}

export async function getExecution(id: string): Promise<unknown> {
  return api.get(`/agents/executions/${id}`);
}
