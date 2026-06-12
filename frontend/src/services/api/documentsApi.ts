import { api } from "@/lib/api";
import type { Document, DocumentDetail, DocumentUploadResult, IngestionJob } from "@/types";

export async function getDocuments(): Promise<Document[]> {
  return api.get<Document[]>("/documents");
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  return api.get<DocumentDetail>(`/documents/${id}`);
}

export async function uploadDocument(file: File, title?: string, documentType?: string): Promise<DocumentUploadResult> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  if (documentType) form.append("document_type", documentType);
  return api.post("/documents/upload", form);
}

export async function getIngestionJobs(): Promise<IngestionJob[]> {
  return api.get<{ items: IngestionJob[] }>("/ingestion/runs").then(r => r.items);
}

export async function getIngestionJob(jobId: string): Promise<IngestionJob> {
  return api.get(`/ingestion/runs/${jobId}`);
}

export async function getDocumentChunks(documentId: string): Promise<any[]> {
  return api.get(`/documents/${documentId}/chunks`);
}

export async function getDocumentPages(documentId: string): Promise<any[]> {
  return api.get(`/documents/${documentId}/pages`);
}
