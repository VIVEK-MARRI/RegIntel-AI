/** Audit view models. Integrity derives sustainably from `intact` only. */
import { toMillis } from "@/lib/dates";
import type {
  AuditEvidence,
  AuditIntegrity,
  AuditRecord,
  ComplianceReport,
} from "@/types/api/audit";

export interface AuditRecordView {
  id: string;
  actor: string;
  actorRole: string;
  action: string;
  severity: string;
  subject: string;
  description: string;
  timestampMillis: number | null;
}

export function toRecordView(r: AuditRecord): AuditRecordView {
  return {
    id: r.audit_id,
    actor: r.actor,
    actorRole: r.actor_role,
    action: r.action,
    severity: r.severity,
    subject: `${r.subject_type}:${r.subject_id}`,
    description: r.description,
    timestampMillis: toMillis(r.timestamp),
  };
}

export interface IntegrityView {
  healthy: boolean;
  message: string;
  total: number;
  valid: number;
  invalid: number;
  percent: number;
}

export function toIntegrityView(i: AuditIntegrity): IntegrityView {
  const pct = i.total > 0 ? (i.valid / i.total) * 100 : 0;
  return {
    healthy: i.intact,
    message: i.message,
    total: i.total,
    valid: i.valid,
    invalid: i.invalid,
    percent: pct,
  };
}

export interface EvidenceView {
  id: string;
  recordId: string;
  kind: string;
  title: string;
  collectedMillis: number | null;
}

export function toEvidenceView(e: AuditEvidence): EvidenceView {
  return {
    id: e.evidence_id,
    recordId: e.record_id,
    kind: e.kind,
    title: e.title,
    collectedMillis: toMillis(e.collected_at),
  };
}

export interface ReportView {
  id: string;
  title: string;
  status: string;
  periodStartMillis: number | null;
  periodEndMillis: number | null;
  generatedMillis: number | null;
}

export function toReportView(r: ComplianceReport): ReportView {
  return {
    id: r.report_id,
    title: r.title,
    status: r.status,
    periodStartMillis: toMillis(r.period_start),
    periodEndMillis: toMillis(r.period_end),
    generatedMillis: toMillis(r.generated_at),
  };
}
