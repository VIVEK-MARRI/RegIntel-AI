/** Document + ingestion view models. */
import { toMillis } from "@/lib/dates";
import type {
  DocumentDetail,
  DocumentItem,
  IngestionRun,
  IngestionRunDetail,
} from "@/types/api/documents";

export interface DocumentView {
  id: string;
  title: string;
  source: string;
  status: string;
  fileName: string;
  pageCount: number | null;
  uploadedMillis: number | null;
}

export function toDocumentView(d: DocumentItem): DocumentView {
  return {
    id: d.id,
    title: d.title,
    source: d.source,
    status: d.status,
    fileName: d.file_name,
    pageCount: d.page_count ?? null,
    uploadedMillis: toMillis(d.uploaded_at),
  };
}

export interface DocumentDetailView extends DocumentView {
  chunkCount: number;
  embeddingCount: number;
  indexed: boolean;
  processingStatus: string;
}

export function toDocumentDetailView(d: DocumentDetail): DocumentDetailView {
  return {
    ...toDocumentView(d),
    chunkCount: d.chunk_count,
    embeddingCount: d.embedding_count,
    indexed: d.indexed,
    processingStatus: d.processing_status,
  };
}

export interface IngestionRunView {
  id: string;
  documentId: string | null;
  status: string;
  terminal: boolean;
  failed: boolean;
  chunksCreated: number;
  embeddingsCreated: number;
  startedMillis: number | null;
  finishedMillis: number | null;
  failureReason: string | null;
}

const TERMINAL = new Set(["completed", "failed", "skipped"]);

export function toRunView(r: IngestionRun): IngestionRunView {
  return {
    id: r.run_id,
    documentId: r.document_id ?? null,
    status: r.status,
    terminal: TERMINAL.has(r.status),
    failed: r.status === "failed",
    chunksCreated: r.chunks_created,
    embeddingsCreated: r.embeddings_created,
    startedMillis: toMillis(r.started_at),
    finishedMillis: toMillis(r.finished_at),
    failureReason: null,
  };
}

export function toRunDetailView(r: IngestionRunDetail): IngestionRunView {
  return {
    id: r.run_id,
    documentId: r.document_id ?? null,
    status: r.ingestion_status,
    terminal: TERMINAL.has(r.ingestion_status),
    failed: r.ingestion_status === "failed",
    chunksCreated: r.chunks_created,
    embeddingsCreated: r.embeddings_created,
    startedMillis: null,
    finishedMillis: null,
    failureReason: r.failure_reason ?? null,
  };
}
