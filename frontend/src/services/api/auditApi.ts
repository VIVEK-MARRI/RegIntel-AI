import { api, encodePathSegment } from "@/lib/api";
import type {
  AuditEvidence,
  AuditIntegrity,
  AuditRecord,
  ComplianceReport,
  PaginatedAuditRecords,
} from "@/types/api/audit";

export type AuditRecordsQuery = {
  action?: string;
  severity?: string;
  actor?: string;
  subject_type?: string;
  subject_id?: string;
  page?: number;
  page_size?: number;
}

export async function getAuditRecords(
  query?: AuditRecordsQuery
): Promise<AuditRecord[]> {
  const res = await api.get<PaginatedAuditRecords>("/audit/records", { query });
  return res.items;
}

export async function getAuditRecord(id: string): Promise<AuditRecord> {
  return api.get<AuditRecord>(`/audit/records/${encodePathSegment(id)}`);
}

export async function getAuditIntegrity(): Promise<AuditIntegrity> {
  return api.get<AuditIntegrity>("/audit/integrity");
}

export async function getAuditReports(): Promise<ComplianceReport[]> {
  return api.get<ComplianceReport[]>("/audit/reports");
}

export async function getAuditEvidence(): Promise<AuditEvidence[]> {
  return api.get<AuditEvidence[]>("/audit/evidence");
}
