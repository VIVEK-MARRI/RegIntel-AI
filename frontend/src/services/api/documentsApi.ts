import { api, encodePathSegment } from "@/lib/api";
import type {
  DocumentDetail,
  DocumentItem,
  DocumentListQuery,
  DocumentPage,
  DocumentUploadRequest,
  DocumentUploadResult,
  IngestionRun,
  IngestionRunDetail,
  PaginatedIngestionRuns,
  StoredChunk,
} from "@/types/api/documents";

export async function getDocuments(
  query?: DocumentListQuery
): Promise<DocumentItem[]> {
  // GET /documents returns a BARE ARRAY (no envelope).
  return api.get<DocumentItem[]>("/documents", { query });
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  return api.get<DocumentDetail>(`/documents/${encodePathSegment(id)}`);
}

export async function uploadDocument(
  file: File,
  title?: string,
  documentType?: string,
  source?: DocumentUploadRequest["source"]
): Promise<DocumentUploadResult> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  if (documentType) form.append("document_type", documentType);
  if (source) form.append("source", source);
  return api.post<DocumentUploadResult>("/documents/upload", form, {
    timeoutMs: 120_000,
  });
}

export async function getIngestionJobs(): Promise<IngestionRun[]> {
  const res = await api.get<PaginatedIngestionRuns>("/ingestion/runs");
  return res.items;
}

export async function getIngestionJob(runId: string): Promise<IngestionRunDetail> {
  return api.get<IngestionRunDetail>(
    `/ingestion/runs/${encodePathSegment(runId)}`
  );
}

export async function getDocumentChunks(documentId: string): Promise<StoredChunk[]> {
  return api.get<StoredChunk[]>(
    `/documents/${encodePathSegment(documentId)}/chunks`
  );
}

export async function getDocumentPages(documentId: string): Promise<DocumentPage[]> {
  return api.get<DocumentPage[]>(
    `/documents/${encodePathSegment(documentId)}/pages`
  );
}
