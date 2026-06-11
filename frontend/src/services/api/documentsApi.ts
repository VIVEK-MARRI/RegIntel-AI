import { api } from "@/lib/api";
import type { Document, IngestionJob } from "@/types";
import type { PaginatedResponse } from "./copilotApi";

export interface UploadResult {
  document_id: string;
  status: string;
  checksum?: string;
}

export async function getDocuments(): Promise<Document[]> {
  return api.get<PaginatedResponse<Document>>("/documents").then(r => r.items);
}

export async function uploadDocument(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  return api.post("/documents/upload", form);
}

export async function getIngestionJobs(): Promise<IngestionJob[]> {
  return api.get("/ingestion/jobs");
}

export async function getIngestionJob(jobId: string): Promise<IngestionJob> {
  return api.get(`/ingestion/jobs/${jobId}`);
}
