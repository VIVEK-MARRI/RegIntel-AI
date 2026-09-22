import { LONG_TIMEOUT_MS, api, encodePathSegment } from "@/lib/api";
import type {
  Conversation,
  ConversationListQuery,
  CopilotHealth,
  ConversationMessage,
  CopilotRequest,
  CopilotResponse,
  PaginatedConversations,
} from "@/types/api/copilot";

export async function getCopilotHealth(): Promise<CopilotHealth> {
  return api.get<CopilotHealth>("/copilot/health");
}

export async function getSessions(
  query?: ConversationListQuery
): Promise<PaginatedConversations> {
  return api.get<PaginatedConversations>("/conversations", { query });
}

export interface ConversationMessages {
  items: ConversationMessage[];
}

/**
 * GET /conversations/:id returns the full Conversation (with messages[]).
 * This helper preserves the historical {items} shape for the message list.
 */
export async function getMessages(
  conversationId?: string
): Promise<ConversationMessages> {
  if (!conversationId) return { items: [] };
  const conv = await api.get<Conversation>(
    `/conversations/${encodePathSegment(conversationId)}`
  );
  return { items: conv.messages ?? [] };
}

export async function queryCopilot(payload: CopilotRequest): Promise<CopilotResponse> {
  return api.post<CopilotResponse>("/copilot/query", payload, {
    timeoutMs: LONG_TIMEOUT_MS,
  });
}
