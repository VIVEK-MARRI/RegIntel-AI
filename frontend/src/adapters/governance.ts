/** Governance + admin display adapters. */
import { toMillis } from "@/lib/dates";
import type { AdminRole, AdminUser } from "@/types/api/admin";
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
    statusText: p.enabled ? "active" : "disabled",
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

export interface AdminUserView {
  id: string;
  displayName: string;
  email: string;
  roleCount: number;
  status: string;
  lastLoginMillis: number | null;
}

export function toAdminUserView(u: AdminUser): AdminUserView {
  return {
    id: u.user_id,
    displayName: u.full_name || u.username,
    email: u.email,
    roleCount: u.role_ids.length,
    status: u.status,
    lastLoginMillis: toMillis(u.last_login_at),
  };
}

export interface AdminRoleView {
  id: string;
  name: string;
  memberCount: number;
  permissionCount: number;
}

export function toAdminRoleView(r: AdminRole): AdminRoleView {
  return {
    id: r.role_id,
    name: r.name,
    memberCount: r.user_count,
    permissionCount: r.permissions.length,
  };
}
