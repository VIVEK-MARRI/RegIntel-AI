/**
 * Copilot feedback contracts. Backend: app/api/v1/feedback.py
 * (prefix /copilot/feedback) + app/schemas/feedback.py (extra="forbid").
 *
 * Thumbs up/down per assistant message needs only {request_id,
 * feedback_type} — both available on every CopilotResponse.
 */
export type FeedbackType =
  | "thumbs_up"
  | "thumbs_down"
  | "correction"
  | "comment"
  | "hallucination_report"
  | "citation_issue";

export interface FeedbackRequest {
  request_id: string;
  conversation_id?: string | null;
  user_id?: string | null;
  feedback_type: FeedbackType;
  category?: string;
  severity?: string;
  comment?: string | null;
  corrected_answer?: string | null;
  flagged_citations?: string[];
  metadata?: Record<string, unknown>;
}

export interface FeedbackEntry {
  feedback_id: string;
  request_id: string;
  conversation_id?: string | null;
  user_id?: string | null;
  feedback_type: FeedbackType;
  comment?: string | null;
}
