import { api } from "@/lib/api";
import type { GovernancePolicy, GovernanceDecision } from "@/types";
import type { PaginatedResponse } from "./copilotApi";

export interface GovernanceStats {
  total_policies: number;
  total_decisions: number;
  active: number;
  deprecated: number;
}

export async function getPolicies(): Promise<GovernancePolicy[]> {
  return api.get("/governance/policies");
}

export async function getPolicy(id: string): Promise<GovernancePolicy> {
  return api.get(`/governance/policies/${id}`);
}

export async function getDecisions(): Promise<GovernanceDecision[]> {
  return api.get<PaginatedResponse<GovernanceDecision>>("/governance/decisions").then(r => r.items);
}

export async function getGovernanceStats(): Promise<GovernanceStats> {
  return api.get("/governance/stats");
}
