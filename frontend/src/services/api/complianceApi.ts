import { api } from "@/lib/api";
import type { ComplianceAssessment } from "@/types";
import type { PaginatedResponse } from "./copilotApi";

export async function getComplianceAssessments(): Promise<ComplianceAssessment[]> {
  return api.get<PaginatedResponse<ComplianceAssessment>>("/compliance-risk/assessments").then(r => r.items);
}

export async function getComplianceAssessment(id: string): Promise<ComplianceAssessment> {
  return api.get(`/compliance-risk/assessments/${id}`);
}

export async function runCompliance(payload: { scope: string; policies?: string[] }): Promise<ComplianceAssessment> {
  return api.post("/compliance-risk/assess", payload);
}
