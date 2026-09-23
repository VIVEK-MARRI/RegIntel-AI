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

export interface RiskFactor {
  factor_id: string;
  name: string;
  category: string;
  weight: number;
  raw_value: number;
  contribution: number;
  explanation: string;
  source: string;
  [key: string]: unknown;
}

/** Backend: RiskExplanation OBJECT (not a string). confidence is a backend constant. */
export interface RiskExplanation {
  summary: string;
  top_factors: RiskFactor[];
  scoring_method: string;
  confidence: number;
  [key: string]: unknown;
}

export interface AffectedArea {
  area: string;
  exposure_score: number;
  rationale: string;
  related_changes: number;
  [key: string]: unknown;
}

export interface RecommendedAction {
  action_id: string;
  action_type: string;
  title: string;
  description: string;
  priority: string;
  rationale: string;
  confidence: number;
  estimated_effort_hours: number;
  [key: string]: unknown;
}

export interface ComplianceGap {
  gap_id: string;
  area: string;
  severity: string;
  description: string;
  regulatory_basis: string;
  remediation_action_id?: string | null;
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
  explanation: RiskExplanation | string;
  regulatory_exposure: number;
  historical_risk_score?: number | null;
  trend: string;
  generated_at: number;
  duration_ms: number;
  metadata: Record<string, unknown>;
}

export type PaginatedRiskAssessments = PaginatedResponse<RiskAssessment>;

export type AssessmentListQuery = {
  risk_level?: string;
  category?: string;
  document_id?: string;
  page?: number;
  page_size?: number;
};

/** Backend: RiskStats (GET /compliance-risk/stats). */
export interface RiskStats {
  total_assessments: number;
  critical_risks: number;
  high_risks: number;
  medium_risks: number;
  low_risks: number;
  average_risk_score: number;
  by_category: Record<string, number>;
  by_source: Record<string, number>;
  by_affected_area: Record<string, number>;
  total_recommended_actions: number;
  total_compliance_gaps: number;
  last_assessment_at: number | null;
}

export interface RiskTrendPoint {
  timestamp: number;
  risk_score: number;
  risk_level: string;
}

/** Backend: RiskTrend (GET /compliance-risk/trend). Points ascend by time. */
export interface ComplianceRiskTrend {
  document_id?: string | null;
  source?: string | null;
  points: RiskTrendPoint[];
  direction: string;
  delta: number;
}
