/** Governance display adapters. */
import { toMillis } from "@/lib/dates";
import type {
  GovernanceDecision,
  GovernancePolicy,
} from "@/types/api/governance";

export interface PolicyView {
  id: string;
  name: string;
  version: string;
  enabled: boolean;
  statusText: string;
  updatedMillis: number | null;
}

export function toPolicyView(p: GovernancePolicy): PolicyView {
  return {
    id: p.policy_id,
    name: p.name,
    version: p.version,
    enabled: p.enabled,
    // Backend semantics are exactly `enabled: bool` — no active/draft/archived.
    statusText: p.enabled ? "Enabled" : "Disabled",
    updatedMillis: toMillis(p.updated_at),
  };
}

export interface DecisionView {
  id: string;
  subject: string;
  outcome: string;
  actor: string;
  timestampMillis: number | null;
}

export function toDecisionView(d: GovernanceDecision): DecisionView {
  return {
    id: d.decision_id,
    subject: `${d.subject_type}:${d.subject_id}`,
    outcome: d.decision,
    actor: d.actor,
    timestampMillis: toMillis(d.timestamp),
  };
}
