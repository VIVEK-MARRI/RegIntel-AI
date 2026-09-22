import { api, encodePathSegment } from "@/lib/api";
import type {
  GovernanceDecision,
  GovernancePolicy,
  GovernanceStats,
  PaginatedDecisions,
} from "@/types/api/governance";

export async function getPolicies(): Promise<GovernancePolicy[]> {
  // GET /governance/policies returns a BARE ARRAY.
  return api.get<GovernancePolicy[]>("/governance/policies");
}

export async function getPolicy(id: string): Promise<GovernancePolicy> {
  return api.get<GovernancePolicy>(
    `/governance/policies/${encodePathSegment(id)}`
  );
}

export async function getDecisions(): Promise<GovernanceDecision[]> {
  const res = await api.get<PaginatedDecisions>("/governance/decisions");
  return res.items;
}

export async function getGovernanceStats(): Promise<GovernanceStats> {
  return api.get<GovernanceStats>("/governance/stats");
}
