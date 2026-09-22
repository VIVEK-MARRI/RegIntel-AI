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
import type { FeedbackEntry, FeedbackRequest } from "@/types/api/feedback";

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

export interface DeleteConversationResult {
  conversation_id: string;
  deleted: boolean;
  mode: string;
}

/**
 * DELETE /conversations/:id. Default is a hard delete; the backend also
 * supports soft archive (?hard=false), which the UI does not use — deleted
 * means gone, honestly.
 */
export async function deleteConversation(
  conversationId: string
): Promise<DeleteConversationResult> {
  return api.del<DeleteConversationResult>(
    `/conversations/${encodePathSegment(conversationId)}?hard=true`
  );
}

export async function queryCopilot(
  payload: CopilotRequest,
  options?: { signal?: AbortSignal }
): Promise<CopilotResponse> {
  return api.post<CopilotResponse>("/copilot/query", payload, {
    timeoutMs: LONG_TIMEOUT_MS,
    signal: options?.signal,
  });
}

export async function submitFeedback(
  payload: FeedbackRequest
): Promise<FeedbackEntry> {
  return api.post<FeedbackEntry>("/copilot/feedback", payload);
}
