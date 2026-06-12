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
  return api.get("/conversations");
}

export async function getMessages(conversationId?: string): Promise<{ items: CopilotMessage[] }> {
  if (conversationId) {
    const conv = await api.get<{ messages: CopilotMessage[] }>(`/conversations/${conversationId}`);
    return { items: conv.messages ?? [] };
  }
  return { items: [] };
}

export async function queryCopilot(payload: CopilotRequestPayload): Promise<CopilotResponsePayload> {
  return api.post("/copilot/query", payload);
}
