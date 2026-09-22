/**
 * Copilot UI models. The backend shapes (AnnotatedAnswer object, source
 * attributions, memory context) are NOT directly renderable as the old
 * frontend assumed — these explicit transforms bridge DTO → view.
 */
import type {
  Conversation,
  ConversationMessage,
  CopilotMode,
  CopilotResponse,
  EvidenceChunk,
  MemoryContext,
  ReferenceEntry,
  SourceAttribution,
} from "@/types/api/copilot";

export interface UIAnswer {
  executiveSummary: string;
  detailedExplanation: string;
  evidence: EvidenceChunk[];
  references: string[];
}

export interface SearchHit {
  memory_id: string;
  content: string;
  score: number;
  tags: string[];
  memory_type: string;
}

export interface UIMessage {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  /** Present only on freshly answered assistant messages (never persisted). */
  requestId?: string;
  conversationId?: string;
  mode?: CopilotMode;
  answer?: UIAnswer | null;
  /** summarise mode: backend returns {summary} instead of an answer. */
  summaryText?: string | null;
  /** search mode: backend returns {sources: memory hits}. */
  searchHits?: SearchHit[];
  citations?: ReferenceEntry[];
  sources?: SourceAttribution[];
  confidence_score?: number;
  confidence_level?: string;
  faithfulness_score?: number;
  hallucination_detected?: boolean;
  hallucination_risk_level?: string;
  latency_ms?: number;
  memory_context?: MemoryContext | null;
}

function toSearchHits(raw: unknown): SearchHit[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((h): h is Record<string, unknown> => typeof h === "object" && h !== null)
    .map((h) => ({
      memory_id: typeof h.memory_id === "string" ? h.memory_id : "",
      content: typeof h.content === "string" ? h.content : "",
      score: typeof h.score === "number" ? h.score : 0,
      tags: Array.isArray(h.tags) ? h.tags.filter((t): t is string => typeof t === "string") : [],
      memory_type: typeof h.memory_type === "string" ? h.memory_type : "",
    }));
}

export function toAssistantMessage(r: CopilotResponse): UIMessage {
  const mode = r.mode ?? "answer";
  const rawAnswer: unknown = r.answer;
  const asRecord =
    typeof rawAnswer === "object" && rawAnswer !== null
      ? (rawAnswer as Record<string, unknown>)
      : null;

  if (mode === "summarise") {
    const summaryText =
      asRecord && typeof asRecord.summary === "string" ? asRecord.summary : "";
    return {
      role: "assistant",
      content: summaryText,
      timestamp: r.created_at,
      requestId: r.request_id,
      conversationId: r.conversation_id,
      mode,
      summaryText,
      citations: [],
      sources: r.sources ?? [],
      confidence_score: r.confidence_score,
      confidence_level: r.confidence_level,
      faithfulness_score: r.faithfulness_score,
      hallucination_detected: r.hallucination_detected,
      hallucination_risk_level: r.hallucination_risk_level,
      latency_ms: r.latency_ms,
      memory_context: r.memory_used ? r.memory_context : null,
    };
  }

  if (mode === "search") {
    const searchHits = toSearchHits(asRecord?.sources);
    return {
      role: "assistant",
      content: "",
      timestamp: r.created_at,
      requestId: r.request_id,
      conversationId: r.conversation_id,
      mode,
      searchHits,
      citations: [],
      sources: [],
      confidence_score: r.confidence_score,
      latency_ms: r.latency_ms,
      memory_context: r.memory_used ? r.memory_context : null,
    };
  }

  const c = r.citations;
  const flatExec =
    asRecord && typeof asRecord.executive_summary === "string"
      ? asRecord.executive_summary
      : "";
  const flatDetail =
    asRecord && typeof asRecord.detailed_explanation === "string"
      ? asRecord.detailed_explanation
      : "";
  // Primary: structured citations object. Fallback: flat string fields the
  // backend emits when no citations were produced (e.g. mock/demo backends
  // answering without retrieval). Never invent text either way.
  const answer: UIAnswer | null = c
    ? {
        executiveSummary: c.executive_summary.text,
        detailedExplanation: c.detailed_explanation.text,
        evidence: c.supporting_evidence,
        references: c.key_regulatory_references,
      }
    : flatExec || flatDetail
      ? {
          executiveSummary: flatExec,
          detailedExplanation: flatDetail,
          evidence: [],
          references: [],
        }
      : null;
  const content = answer
    ? [answer.executiveSummary, answer.detailedExplanation]
        .filter(Boolean)
        .join("\n\n")
    : "";
  return {
    role: "assistant",
    content,
    timestamp: r.created_at,
    requestId: r.request_id,
    conversationId: r.conversation_id,
    mode,
    answer,
    citations: c?.references ?? [],
    sources: r.sources ?? [],
    confidence_score: r.confidence_score,
    confidence_level: r.confidence_level,
    faithfulness_score: r.faithfulness_score,
    hallucination_detected: r.hallucination_detected,
    hallucination_risk_level: r.hallucination_risk_level,
    latency_ms: r.latency_ms,
    memory_context: r.memory_used ? r.memory_context : null,
  };
}

export function toHistoryMessage(m: ConversationMessage): UIMessage {
  return { role: m.role, content: m.content, timestamp: m.timestamp };
}

export interface SessionListItem {
  id: string;
  title: string;
  preview: string;
  updatedMillis: number | null;
  messageCount: number;
}

export function toSessionItem(c: Conversation): SessionListItem {
  const firstUser = c.messages.find((m) => m.role === "user");
  return {
    id: c.conversation_id,
    title: c.title || "Untitled conversation",
    preview: firstUser?.content.slice(0, 120) ?? c.summary.slice(0, 120),
    updatedMillis:
      c.updated_at && !Number.isNaN(Date.parse(c.updated_at))
        ? Date.parse(c.updated_at)
        : null,
    messageCount: c.messages.length,
  };
}
