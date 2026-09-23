/**
 * Governance contracts. Backend: app/api/v1/governance.py +
 * app/schemas/governance.py (extra="forbid"). Timestamps epoch SECONDS.
 *
 * Verified: policies are versioned STRINGS with an `enabled` boolean (no
 * status enum, no created_by); decisions join on subject_type+subject_id
 * with a `decision` (not outcome) and policy_result object; stats carry
 * compliance/violations counters (no active/deprecated).
 */
import type { PaginatedResponse } from "./common";

export interface PolicyRule {
  rule_id: string;
  name: string;
  description: string;
  kind: string;
  action: string;
  severity: string;
  parameters: Record<string, unknown>;
  enabled: boolean;
}

export interface GovernancePolicy {
  policy_id: string;
  name: string;
  description: string;
  version: string;
  scope: string;
  scope_value?: string | null;
  rules: PolicyRule[];
  enabled: boolean;
  created_at: number;
  updated_at: number;
  tags: string[];
}

export interface GovernanceDecision {
  decision_id: string;
  decision_type: string;
  subject_type: string;
  subject_id: string;
  model_id?: string | null;
  model_version?: string | null;
  decision: string;
  confidence: number;
  risk_level: string;
  categories: string[];
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  actor: string;
  timestamp: number;
  policy_result?: PolicyCheckResult | Record<string, unknown> | null;
  approved_by: string[];
  metadata: Record<string, unknown>;
}

export type PaginatedDecisions = PaginatedResponse<GovernanceDecision>;

export interface GovernanceStats {
  total_policies: number;
  total_rules: number;
  total_decisions: number;
  compliant_decisions: number;
  non_compliant_decisions: number;
  total_violations: number;
  blocking_violations: number;
  average_violations_per_decision: number;
  compliance_rate: number;
  last_decision_at: number | null;
}

/** Backend: PolicyViolation + PolicyCheckResult (POST /decisions/{id}/check). */
export interface PolicyViolation {
  violation_id: string;
  rule_id: string;
  rule_name: string;
  policy_id: string;
  policy_name: string;
  kind: string;
  action: string;
  severity: string;
  message: string;
  details: Record<string, unknown>;
  timestamp: number;
}

export interface PolicyCheckResult {
  result_id: string;
  decision_id: string;
  policy_compliant: boolean;
  violations: PolicyViolation[];
  required_actions: string[];
  evaluated_policies: string[];
  evaluated_rules: number;
  timestamp: number;
  notes: string;
}

/** Backend: ApprovalPolicy (GET /governance/approval-policies). */
export interface ApprovalPolicy {
  policy_id: string;
  name: string;
  description: string;
  decision_types: string[];
  min_risk_level?: string | null;
  required_roles: string[];
  min_approvers: number;
  applies_to: string;
  enabled: boolean;
  created_at: number;
}
