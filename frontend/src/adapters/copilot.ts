/**
 * Copilot UI models. The backend shapes (AnnotatedAnswer object, source
 * attributions, memory context) are NOT directly renderable as the old
 * frontend assumed — these explicit transforms bridge DTO → view.
 */
import type {
  Conversation,
  ConversationMessage,
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

export interface UIMessage {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  answer?: UIAnswer | null;
  citations?: ReferenceEntry[];
  sources?: SourceAttribution[];
  confidence_score?: number;
  faithfulness_score?: number;
  hallucination_detected?: boolean;
  hallucination_risk_level?: string;
  latency_ms?: number;
  memory_context?: MemoryContext | null;
}

export function toAssistantMessage(r: CopilotResponse): UIMessage {
  const c = r.citations;
  const answer: UIAnswer | null = c
    ? {
        executiveSummary: c.executive_summary.text,
        detailedExplanation: c.detailed_explanation.text,
        evidence: c.supporting_evidence,
        references: c.key_regulatory_references,
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
    answer,
    citations: c?.references ?? [],
    sources: r.sources ?? [],
    confidence_score: r.confidence_score,
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
  };
}
