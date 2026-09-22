/**
 * Research contracts. Backend: app/api/v1/research.py + app/schemas/research.py
 * (extra="forbid"). Timestamps epoch SECONDS.
 *
 * Verified: reports carry steps[] (status completed|...|skipped),
 * key_findings[] (STRINGS), timeline[]/comparisons[]/citations[] — there is
 * NO plan/findings-objects/confidence/created_at/sources concept.
 */
import type { PaginatedResponse } from "./common";

export type ResearchKind =
  | "general" | "multi_hop" | "cross_document" | "timeline" | "comparative";

export type ResearchStepType =
  | "plan" | "retrieve" | "compare" | "reason" | "summarize";

export type ResearchStepStatus =
  | "pending" | "running" | "completed" | "failed" | "skipped";

export type CitationSource =
  | "monitoring" | "ingestion" | "change_detection" | "impact_analysis"
  | "knowledge_graph" | "search" | "copilot";

export interface ResearchStep {
  step_id: string;
  step_type: ResearchStepType;
  description: string;
  status: ResearchStepStatus;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  error: string;
  started_at: number;
  finished_at: number;
  duration_ms: number;
}

export interface ResearchCitation {
  citation_id: string;
  source: CitationSource;
  title: string;
  reference: string;
  url?: string | null;
  score: number;
  metadata: Record<string, unknown>;
}

export interface ResearchReport {
  report_id: string;
  plan_id: string;
  query: string;
  kind: ResearchKind;
  summary: string;
  key_findings: string[];
  timeline: Array<Record<string, unknown>>;
  comparisons: Array<Record<string, unknown>>;
  citations: ResearchCitation[];
  steps: ResearchStep[];
  generated_at: number;
  duration_ms: number;
}

export type PaginatedResearchReports = PaginatedResponse<ResearchReport>;

export interface ResearchRequest {
  query: string;
  kind?: ResearchKind;
  max_steps?: number;
}

export type ResearchListQuery = {
  kind?: ResearchKind;
  page?: number;
  page_size?: number;
}
