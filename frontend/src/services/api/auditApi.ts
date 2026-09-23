import { api, encodePathSegment } from "@/lib/api";
import type {
  AuditEvidence,
  AuditIntegrity,
  AuditRecord,
  AuditStats,
  ComplianceReport,
  EvidenceQuery,
  PaginatedAuditRecords,
  ReportCreateRequest,
  ReportListQuery,
} from "@/types/api/audit";

export type AuditRecordsQuery = {
  action?: string;
  severity?: string;
  actor?: string;
  subject_type?: string;
  subject_id?: string;
  source_module?: string;
  after?: number;
  before?: number;
  text_query?: string;
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

export async function getAuditStats(): Promise<AuditStats> {
  return api.get<AuditStats>("/audit/stats");
}

export async function getAuditReports(query?: ReportListQuery): Promise<ComplianceReport[]> {
  return api.get<ComplianceReport[]>("/audit/reports", { query });
}

export async function getAuditReport(id: string): Promise<ComplianceReport> {
  return api.get<ComplianceReport>(`/audit/reports/${encodePathSegment(id)}`);
}

export async function generateAuditReport(payload: ReportCreateRequest): Promise<ComplianceReport> {
  return api.post<ComplianceReport>("/audit/reports", payload);
}

export async function getAuditEvidence(query?: EvidenceQuery): Promise<AuditEvidence[]> {
  return api.get<AuditEvidence[]>("/audit/evidence", { query });
}

export async function getAuditEvidenceById(id: string): Promise<AuditEvidence> {
  return api.get<AuditEvidence>(`/audit/evidence/${encodePathSegment(id)}`);
}
