import { api } from "@/lib/api";
import type { AuditRecord, AuditEvidence, AuditIntegrity, ComplianceReport } from "@/types";
import type { PaginatedResponse } from "./copilotApi";

export async function getAuditRecords(): Promise<AuditRecord[]> {
  return api.get<PaginatedResponse<AuditRecord>>("/audit/records").then(r => r.items);
}

export async function getAuditRecord(id: string): Promise<AuditRecord> {
  return api.get(`/audit/records/${id}`);
}

export async function getAuditIntegrity(): Promise<AuditIntegrity> {
  return api.get("/audit/integrity");
}

export async function getAuditReports(): Promise<ComplianceReport[]> {
  return api.get("/audit/reports");
}

export async function getAuditEvidence(): Promise<AuditEvidence[]> {
  return api.get("/audit/evidence");
}
