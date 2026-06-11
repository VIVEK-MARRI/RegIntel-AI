import { api } from "@/lib/api";
import type { CopilotRequestPayload, CopilotResponsePayload, ChatSession, CopilotMessage } from "@/types";

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export async function getCopilotHealth(): Promise<{ status: string; module: string }> {
  return api.get("/copilot/health");
}

export async function getSessions(): Promise<PaginatedResponse<ChatSession>> {
  return api.get("/conversation/sessions");
}

export async function getMessages(conversationId?: string): Promise<PaginatedResponse<CopilotMessage>> {
  const path = conversationId ? `/conversation/${conversationId}/messages` : "/conversation/messages";
  return api.get(path);
}

export async function queryCopilot(payload: CopilotRequestPayload): Promise<CopilotResponsePayload> {
  return api.post("/copilot/query", payload);
}
