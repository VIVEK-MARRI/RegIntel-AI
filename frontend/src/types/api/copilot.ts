/**
 * Copilot + conversations contracts. Backend: app/api/v1/copilot.py,
 * conversation.py and schemas copilot.py / conversation.py / citation.py /
 * attribution.py / memory.py / orchestrator.py / confidence.py /
 * hallucination.py (extra="forbid" throughout).
 *
 * Verified asymmetries (do NOT regress):
 * - citations is an AnnotatedAnswer OBJECT, never an array.
 * - sources are SourceAttribution {attribution_id, section, segment_index,
 *   document_id, document_title, chunk_id, page_number?, chunk_section?,
 *   excerpt, similarity, confidence(enum), metadata}.
 * - memory_context is {short_term: Message[], long_term: MemoryEntry[],
 *   retrieval: MemorySearchResult[], total_count, memory_used}.
 * - Conversation timestamps are ISO strings; Message too.
 * - There is no agent_contributions field anywhere in the response.
 */
import type { PaginatedResponse } from "./common";

export type CopilotMode = "answer" | "summarise" | "search";
export type ConversationStatus = "active" | "paused" | "archived" | "expired";
export type ConversationRole = "user" | "assistant" | "system";
export type ConfidenceLevel = "high" | "medium" | "low";
export type HallucinationRiskLevel = "none" | "low" | "medium" | "high";
export type AttributionSection =
  | "executive_summary" | "detailed_explanation"
  | "supporting_evidence" | "key_regulatory_references";
export type AttributionConfidence = "high" | "medium" | "low" | "none";

export interface CopilotRequest {
  query: string;
  conversation_id?: string | null;
  user_id?: string | null;
  mode?: CopilotMode;
  tone?: string;
  verification_method?: string;
  min_faithfulness?: number;
  use_memory?: boolean;
  memory_top_k?: number;
  chunks?: Array<Record<string, unknown>> | null;
  metadata?: Record<string, unknown>;
}

export interface InlineCitation {
  [key: string]: unknown;
}

export interface AnnotatedText {
  text: string;
  citations: InlineCitation[];
  claim_count: number;
  cited_claim_count: number;
}

export interface EvidenceChunk {
  chunk_id: string;
  document_id?: string | null;
  content: string;
  score: number;
  source?: string | null;
  section?: string | null;
  subsection?: string | null;
  page_number?: number | null;
  metadata: Record<string, unknown>;
}

export interface ReferenceEntry {
  citation_id: string;
  chunk_id: string;
  document_id: string;
  document_title: string;
  source?: string | null;
  document_type?: string | null;
  circular_number?: string | null;
  page_number?: number | null;
  url?: string | null;
  excerpt: string;
}

export interface AnnotatedAnswer {
  executive_summary: AnnotatedText;
  detailed_explanation: AnnotatedText;
  supporting_evidence: EvidenceChunk[];
  key_regulatory_references: string[];
  references: ReferenceEntry[];
  citation_map: Record<string, string>;
}

export interface SourceAttribution {
  attribution_id: string;
  section: AttributionSection;
  segment_index: number;
  document_id: string;
  document_title: string;
  chunk_id: string;
  page_number?: number | null;
  chunk_section?: string | null;
  excerpt: string;
  similarity: number;
  confidence: AttributionConfidence;
  metadata: Record<string, unknown>;
}

export interface ConversationMessage {
  message_id: string;
  role: ConversationRole;
  content: string;
  timestamp: string;
  metadata: Record<string, unknown>;
  references: Record<string, string>;
  token_estimate: number;
}

export interface MemoryEntry {
  memory_id: string;
  memory_type: string;
  scope: string;
  user_id?: string | null;
  conversation_id?: string | null;
  content: string;
  embedding_text: string;
}

export interface MemorySearchResult {
  entry: MemoryEntry;
  score: number;
  matched_terms: string[];
}

export interface MemoryContext {
  short_term: ConversationMessage[];
  long_term: MemoryEntry[];
  retrieval: MemorySearchResult[];
  total_count: number;
  memory_used: boolean;
}

export interface OrchestratorMetadata {
  request_id: string;
  timestamp: string;
  pipeline_version: string;
  model_used?: string | null;
  provider_used?: string | null;
  total_latency_ms: number;
  step_results: unknown[];
  warnings: string[];
  extra: Record<string, unknown>;
}

export interface CopilotResponse {
  request_id: string;
  conversation_id: string;
  user_id?: string | null;
  query: string;
  mode: CopilotMode;
  answer: Record<string, unknown> | null;
  citations: AnnotatedAnswer | null;
  confidence_score: number;
  confidence_level: ConfidenceLevel;
  faithfulness_score: number;
  hallucination_detected: boolean;
  hallucination_risk_level: HallucinationRiskLevel;
  sources: SourceAttribution[];
  attribution_coverage_ratio: number;
  memory_used: boolean;
  memory_context: MemoryContext;
  history: ConversationMessage[];
  latency_ms: number;
  metadata: OrchestratorMetadata;
  created_at: string;
}

export interface Conversation {
  conversation_id: string;
  user_id?: string | null;
  title: string;
  status: ConversationStatus;
  created_at: string;
  updated_at: string;
  expires_at?: string | null;
  ttl_seconds?: number | null;
  messages: ConversationMessage[];
  metadata: Record<string, unknown>;
  tags: string[];
  summary: string;
}

export type ConversationListQuery = {
  user_id?: string;
  status?: ConversationStatus;
  tag?: string;
  query?: string;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_desc?: boolean;
}

export type PaginatedConversations = PaginatedResponse<Conversation>;

export interface CopilotHealth {
  status: string;
  module: string;
  version?: string;
}
