/** Conversation + research + assessment + forecast view models. */
import { toMillis } from "@/lib/dates";
import type { Conversation } from "@/types/api/copilot";
import type { RiskAssessment } from "@/types/api/compliance";
import type { RiskForecast } from "@/types/api/risk";
import type { ResearchReport } from "@/types/api/research";

export interface SessionView {
  id: string;
  title: string;
  status: string;
  updatedMillis: number | null;
  messageCount: number;
  preview: string;
}

export function toSessionView(c: Conversation): SessionView {
  const firstUser = c.messages.find((m) => m.role === "user");
  return {
    id: c.conversation_id,
    title: c.title || "Untitled conversation",
    status: c.status,
    updatedMillis: toMillis(c.updated_at),
    messageCount: c.messages.length,
    preview: firstUser?.content.slice(0, 120) ?? c.summary.slice(0, 120),
  };
}

export interface ResearchReportView {
  id: string;
  query: string;
  kind: string;
  summary: string;
  findings: string[];
  stepCount: number;
  findingCount: number;
  citationsCount: number;
  generatedMillis: number | null;
}

export function toReportView(r: ResearchReport): ResearchReportView {
  return {
    id: r.report_id,
    query: r.query,
    kind: r.kind,
    summary: r.summary,
    findings: r.key_findings,
    stepCount: r.steps.length,
    findingCount: r.key_findings.length,
    citationsCount: r.citations.length,
    generatedMillis: toMillis(r.generated_at),
  };
}

export interface AssessmentView {
  id: string;
  documentId: string | null;
  level: string;
  score: number;
  gapCount: number;
  generatedMillis: number | null;
}

export function toAssessmentView(a: RiskAssessment): AssessmentView {
  return {
    id: a.assessment_id,
    documentId: a.document_id ?? null,
    level: a.risk_level,
    score: a.risk_score,
    gapCount: a.compliance_gaps.length,
    generatedMillis: toMillis(a.generated_at),
  };
}

export interface ForecastView {
  id: string;
  horizonDays: number;
  score: number;
  level: string;
  confidence: number;
  generatedMillis: number | null;
}

export function toForecastView(f: RiskForecast): ForecastView {
  return {
    id: f.forecast_id,
    horizonDays: f.horizon_days,
    score: f.predicted_risk_score,
    level: f.predicted_risk_level,
    confidence: f.confidence,
    generatedMillis: toMillis(f.generated_at),
  };
}
