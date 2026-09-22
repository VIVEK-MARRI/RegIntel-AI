/**
 * Compliance (risk assessment) contracts. Backend: app/api/v1/compliance_risk.py
 * + app/schemas/risk.py (extra="forbid"). Timestamps epoch SECONDS.
 *
 * Verified: the model is RiskAssessment keyed by document/diff/impact — there
 * is NO scope/obligations concept. POST /assess REQUIRES none of the old
 * frontend keys; {scope, policies} are rejected (422).
 */
import type { PaginatedResponse } from "./common";

export interface RiskAssessmentRequest {
  document_id?: string;
  diff_id?: string;
  impact_report_id?: string;
  source?: string;
  context?: Record<string, unknown>;
}

export interface AffectedArea {
  area: string;
  exposure_score: number;
  [key: string]: unknown;
}

export interface RecommendedAction {
  action_id: string;
  action_type: string;
  title: string;
  [key: string]: unknown;
}

export interface ComplianceGap {
  gap_id: string;
  area: string;
  severity: string;
  description: string;
  regulatory_basis: string;
  [key: string]: unknown;
}

export interface RiskAssessment {
  assessment_id: string;
  document_id?: string | null;
  diff_id?: string | null;
  impact_report_id?: string | null;
  source: string;
  risk_level: string;
  risk_score: number;
  risk_categories: string[];
  affected_areas: AffectedArea[];
  recommended_actions: RecommendedAction[];
  compliance_gaps: ComplianceGap[];
  explanation: string;
  regulatory_exposure: number;
  generated_at: number;
}

export type PaginatedRiskAssessments = PaginatedResponse<RiskAssessment>;
