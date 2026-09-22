/**
 * Documents + ingestion contracts. Backend: app/api/v1/documents.py +
 * ingestion.py and schemas document.py / chunk.py / ingestion.py
 * (extra="forbid").
 *
 * Verified asymmetries:
 * - GET /documents returns a BARE ARRAY (no envelope); detail adds
 *   chunk_count/embedding_count/indexed/processing_status.
 * - List items have NO chunk_count and NO created_at (uploaded_at ISO).
 * - document_id path params are UUID-gated (non-UUID → 422).
 * - Upload accepts ONLY .pdf/.txt (ext + MIME) ≤100MB; returns 201
 *   {document_id, status: "processing", run_id?}.
 * - Ingestion runs: {run_id (not job_id), 13-value lowercase status enum,
 *   ISO started_at/finished_at}. Terminal success is "completed".
 */
import type { PaginatedResponse } from "./common";

export type DocumentSource = "RBI" | "SEBI" | "IRDAI" | "USER_UPLOAD";
export type DocumentStatus =
  | "UPLOADED" | "PROCESSING" | "PARSING" | "PARSED" | "INDEXED" | "FAILED";

export interface DocumentItem {
  id: string;
  title: string;
  source: DocumentSource;
  file_name: string;
  file_path: string;
  document_type?: string | null;
  publication_date?: string | null;
  checksum: string;
  page_count?: number | null;
  status: DocumentStatus;
  uploaded_at: string;
  updated_at: string;
}

export interface DocumentDetail extends DocumentItem {
  chunk_count: number;
  page_count_actual?: number | null;
  embedding_count: number;
  indexed: boolean;
  processing_status: string;
}

export interface DocumentUploadRequest {
  file: File;
  title?: string;
  document_type?: string;
  source?: DocumentSource;
}

export interface DocumentUploadResult {
  document_id: string;
  status: string;
  run_id?: string | null;
}

export interface StoredChunk {
  id: string;
  document_id: string;
  page_number: number;
  section?: string | null;
  subsection?: string | null;
  content: string;
  token_count: number;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface DocumentPage {
  id: string;
  document_id: string;
  page_number: number;
  content: string;
  created_at: string;
}

export type IngestionStatus =
  | "pending" | "downloading" | "downloaded" | "parsing" | "parsed"
  | "chunking" | "chunked" | "embedding" | "embedded" | "indexing"
  | "completed" | "failed" | "skipped";

export interface IngestionRun {
  run_id: string;
  discovery_id?: string | null;
  document_id?: string | null;
  source?: string | null;
  document_url?: string | null;
  title?: string | null;
  checksum?: string | null;
  status: IngestionStatus;
  steps: unknown[];
  chunks_created: number;
  embeddings_created: number;
  pages_parsed: number;
  is_duplicate: boolean;
  started_at: string;
  finished_at?: string | null;
  duration_ms: number;
}

export type PaginatedIngestionRuns = PaginatedResponse<IngestionRun>;

export interface IngestionRunDetail {
  run_id: string;
  document_id?: string | null;
  ingestion_status: IngestionStatus;
  chunks_created: number;
  embeddings_created: number;
  pages_parsed: number;
  is_duplicate: boolean;
  is_incremental_update: boolean;
  failure_reason?: string | null;
  duration_ms: number;
}

export type DocumentListQuery = {
  source?: DocumentSource;
  status?: DocumentStatus;
  sort_by?: string;
  sort_order?: string;
  skip?: number;
  limit?: number;
}
