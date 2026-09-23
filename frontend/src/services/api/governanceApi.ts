import { api, encodePathSegment } from "@/lib/api";
import type {
  ApprovalPolicy,
  GovernanceDecision,
  GovernancePolicy,
  GovernanceStats,
  PaginatedDecisions,
  PolicyCheckResult,
} from "@/types/api/governance";

export async function getApprovalPolicies(): Promise<ApprovalPolicy[]> {
  return api.get<ApprovalPolicy[]>("/governance/approval-policies");
}

export async function updatePolicy(
  id: string,
  patch: { enabled?: boolean }
): Promise<GovernancePolicy> {
  return api.patch<GovernancePolicy>(
    `/governance/policies/${encodePathSegment(id)}`,
    patch
  );
}

export async function recheckDecision(id: string): Promise<PolicyCheckResult> {
  return api.post<PolicyCheckResult>(
    `/governance/decisions/${encodePathSegment(id)}/check`
  );
}

export async function getPolicies(query?: {
  scope?: string;
  enabled_only?: boolean;
}): Promise<GovernancePolicy[]> {
  // GET /governance/policies returns a BARE ARRAY.
  return api.get<GovernancePolicy[]>("/governance/policies", { query });
}

export async function getPolicy(id: string): Promise<GovernancePolicy> {
  return api.get<GovernancePolicy>(
    `/governance/policies/${encodePathSegment(id)}`
  );
}

export async function getDecisions(query?: {
  decision_type?: string;
  model_id?: string;
  subject_type?: string;
  subject_id?: string;
  risk_level?: string;
  policy_compliant?: boolean;
  actor?: string;
  page?: number;
  page_size?: number;
}): Promise<GovernanceDecision[]> {
  const res = await api.get<PaginatedDecisions>("/governance/decisions", { query });
  return res.items;
}

export async function getGovernanceStats(): Promise<GovernanceStats> {
  return api.get<GovernanceStats>("/governance/stats");
}
