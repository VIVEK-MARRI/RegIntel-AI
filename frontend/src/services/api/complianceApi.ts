import { api, encodePathSegment } from "@/lib/api";
import type {
  PaginatedRiskAssessments,
  RiskAssessment,
  RiskAssessmentRequest,
} from "@/types/api/compliance";

export async function getComplianceAssessments(): Promise<RiskAssessment[]> {
  const res = await api.get<PaginatedRiskAssessments>("/compliance-risk/assessments");
  return res.items;
}

export async function getComplianceAssessment(id: string): Promise<RiskAssessment> {
  // Canonical visible route (the /assessments/{id} alias is hidden from OpenAPI).
  return api.get<RiskAssessment>(
    `/compliance-risk/${encodePathSegment(id)}`
  );
}

/**
 * Backend RiskAssessmentRequest accepts ONLY document_id / diff_id /
 * impact_report_id / source / context (extra=forbid). Never send scope or
 * policies — the backend rejects them with 422.
 */
export async function runCompliance(
  payload: RiskAssessmentRequest
): Promise<RiskAssessment> {
  return api.post<RiskAssessment>("/compliance-risk/assess", payload);
}
