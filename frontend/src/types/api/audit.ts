/**
 * Audit contracts. Backend: app/api/v1/audit.py + app/schemas/audit.py
 * (extra="forbid"). Timestamps epoch SECONDS (float).
 *
 * Verified asymmetries:
 * - /integrity returns a HAND-BUILT dict {intact, message, ...} — there is
 *   no broken_chains[] / checked_at. Derive UI state from `intact`.
 * - Evidence joins on record_id (not audit_id); signatures are content_hash.
 * - Report periods are epoch floats; sections are ReportSection objects.
 */
import type { PaginatedResponse } from "./common";

export type AuditAction =
  | "create" | "update" | "delete" | "read" | "login" | "logout"
  | "export" | "approve" | "reject" | "escalate" | "policy_check"
  | "workflow_start" | "workflow_complete" | "report_generate"
  | "config_change" | "rbac_grant" | "rbac_revoke" | "other";

export type AuditSeverity = "info" | "notice" | "warning" | "error" | "critical";

export interface AuditRecord {
  audit_id: string;
  timestamp: number;
  actor: string;
  actor_role: string;
  action: AuditAction | string;
  severity: AuditSeverity;
  subject_type: string;
  subject_id: string;
  description: string;
  details: Record<string, unknown>;
  ip_address?: string | null;
  user_agent?: string | null;
  source_module?: string | null;
  prev_hash: string;
  record_hash: string;
  sequence: number;
  metadata: Record<string, unknown>;
}

export type PaginatedAuditRecords = PaginatedResponse<AuditRecord>;

export interface AuditIntegrity {
  intact: boolean;
  message: string;
  total: number;
  valid: number;
  invalid: number;
  chain_length: number;
  last_chain_hash: string;
}

export type ReportStatus =
  | "draft" | "generating" | "complete" | "failed" | "archived";

export interface ReportSection {
  section_id: string;
  title: string;
  summary: string;
  metrics: Record<string, unknown>;
  evidence_refs: string[];
  findings: string[];
  recommendations: string[];
  order: number;
}

export interface ComplianceReport {
  report_id: string;
  title: string;
  description: string;
  kind: string;
  status: ReportStatus;
  regulator?: string | null;
  period_start: number;
  period_end: number;
  generated_by?: string | null;
  generated_at: number;
  completed_at?: number | null;
  sections: ReportSection[];
  record_refs: string[];
  evidence_refs: string[];
}

export type EvidenceKind =
  | "document" | "screenshot" | "log" | "citation" | "decision"
  | "approval" | "policy" | "config" | "other";

export interface AuditEvidence {
  evidence_id: string;
  record_id: string;
  kind: EvidenceKind;
  title: string;
  description: string;
  content: Record<string, unknown>;
  content_hash: string;
  collected_by?: string | null;
  collected_at: number;
  source_uri?: string | null;
  tags: string[];
}
