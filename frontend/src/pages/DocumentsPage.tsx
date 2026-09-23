import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { Tabs } from "@/components/ui/Tabs";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getDocuments,
  uploadDocument,
  getDocument,
  getIngestionJobs,
  getIngestionJob,
  getDocumentChunks,
  getDocumentPages,
} from "@/services/api";
import { useToast } from "@/providers/ToastProvider";
import { formatRelative, truncate } from "@/lib/format";
import { toMillis } from "@/lib/dates";
import { documentsKeys, dashboardKeys } from "@/lib/queryKeys";
import { toRunView } from "@/adapters/documents";
import { ApiClientError } from "@/lib/errors";
import type {
  DocumentDetail,
  DocumentPage as DocumentPageType,
  StoredChunk,
} from "@/types/api/documents";

/**
 * Document library + ingestion monitor. Every number comes from its
 * backend field (see docs/DOCUMENTS_ARCHITECTURE_STAGE08.md):
 * - the list endpoint returns a bare ARRAY (no total) with server-side
 *   source/status filters, uploaded_at-desc sort, and skip/limit paging;
 * - document detail carries authoritative chunk/embedding/indexed state;
 * - ingestion runs carry the 13-state lifecycle; there is NO delete,
 *   retry, or progress-percent endpoint, so none is shown.
 */

const PAGE_SIZE = 25;

/** Backend StatusEnum (app/models/document.py) — the full registry lifecycle. */
const DOC_STATUSES = ["UPLOADED", "PROCESSING", "PARSING", "PARSED", "INDEXED", "FAILED"] as const;
const DOC_SOURCES = ["USER_UPLOAD", "RBI", "SEBI", "IRDAI"] as const;
const TERMINAL_DOC = new Set(["INDEXED", "FAILED"]);

const ALLOWED_EXTS = new Set([".pdf", ".txt"]);
const MAX_BYTES = 100 * 1024 * 1024;

function docStatusTone(s: string): "neutral" | "success" | "warning" | "danger" | "info" | "brand" {
  switch (s) {
    case "INDEXED":
      return "success";
    case "FAILED":
      return "danger";
    case "PARSED":
      return "info";
    case "PROCESSING":
    case "PARSING":
      return "warning";
    default:
      return "neutral";
  }
}

function runStatusTone(s: string): "neutral" | "success" | "warning" | "danger" | "info" | "brand" {
  if (s === "completed") return "success";
  if (s === "failed") return "danger";
  if (s === "skipped") return "neutral";
  return "info";
}

const RUN_STATUS_HELP: Record<string, string> = {
  pending: "Queued — waiting for a worker.",
  downloading: "Fetching the source file.",
  downloaded: "Source fetched, awaiting parse.",
  parsing: "Extracting text and structure.",
  parsed: "Text extracted, awaiting chunks.",
  chunking: "Splitting text into chunks.",
  chunked: "Chunked, awaiting embeddings.",
  embedding: "Creating search embeddings.",
  embedded: "Embedded, awaiting index.",
  indexing: "Writing to the search index.",
  completed: "Finished — output is searchable.",
  failed: "Failed — see the run error.",
  skipped: "Skipped (duplicate or superseded).",
};

export function DocumentsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filterSource, setFilterSource] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [page, setPage] = useState(0);
  const [inspectorTab, setInspectorTab] = useState<"chunks" | "pages">("chunks");

  function resetPage() {
    setPage(0);
  }

  const listParams = useMemo(
    () => ({
      ...(filterSource ? { source: filterSource as (typeof DOC_SOURCES)[number] } : {}),
      ...(filterStatus ? { status: filterStatus as (typeof DOC_STATUSES)[number] } : {}),
      skip: page * PAGE_SIZE,
      limit: PAGE_SIZE,
    }),
    [filterSource, filterStatus, page]
  );

  const { data: documents, isLoading: dLoading, isError: dError, refetch: dRefetch } = useQuery({
    queryKey: documentsKeys.list(listParams),
    queryFn: () => getDocuments(listParams),
  });
  const { data: jobs, isLoading: jLoading, isError: jError, refetch: jRefetch, isFetching: jFetching } = useQuery({
    queryKey: documentsKeys.ingestionJobs(),
    queryFn: getIngestionJobs,
    // Poll only while work is actually in flight; React Query stops the
    // timer on unmount automatically. No setInterval anywhere.
    refetchInterval: (query) => {
      const runs = query.state.data ?? [];
      return runs.some((r) => {
        const s = r.status;
        return s !== "completed" && s !== "failed" && s !== "skipped";
      })
        ? 5000
        : false;
    },
  });
  const { data: detail, isLoading: detLoading, refetch: refetchDetail } = useQuery({
    queryKey: documentsKeys.detail(selectedDoc ?? "none"),
    queryFn: () => getDocument(selectedDoc!),
    enabled: Boolean(selectedDoc),
    refetchInterval: (query) => {
      const d = query.state.data;
      if (!selectedDoc || !d) return 5000;
      return TERMINAL_DOC.has(d.status) ? false : 5000;
    },
  });
  const { data: chunks } = useQuery({
    queryKey: documentsKeys.chunks(selectedDoc ?? "none"),
    queryFn: () => getDocumentChunks(selectedDoc!),
    enabled: Boolean(selectedDoc),
  });
  const { data: pages } = useQuery({
    queryKey: documentsKeys.pages(selectedDoc ?? "none"),
    queryFn: () => getDocumentPages(selectedDoc!),
    enabled: Boolean(selectedDoc),
  });

  const uploadMut = useMutation({ mutationFn: (file: File) => uploadDocument(file) });

  // When the polled jobs list shows the selected document's run reaching a
  // terminal state, refresh the detail + inspectors (chunks/pages grow).
  const selectedRunStatus = (jobs ?? [])
    .filter((j) => j.document_id && j.document_id === selectedDoc)
    .map((j) => j.status)[0];
  useEffect(() => {
    if (!selectedDoc) return;
    if (selectedRunStatus === "completed" || selectedRunStatus === "failed" || selectedRunStatus === "skipped") {
      void qc.invalidateQueries({ queryKey: documentsKeys.detail(selectedDoc) });
      void qc.invalidateQueries({ queryKey: documentsKeys.chunks(selectedDoc) });
      void qc.invalidateQueries({ queryKey: documentsKeys.pages(selectedDoc) });
    }
  }, [selectedRunStatus, selectedDoc, qc]);

  async function handleFile(file: File) {
    const ext = "." + (file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "");
    if (!ALLOWED_EXTS.has(ext)) {
      toast.push({
        title: "Unsupported file type",
        description: `"${ext || "no extension"}" is not accepted. Use PDF or TXT — the parser reads those formats.`,
        tone: "danger",
      });
      return;
    }
    if (file.size > MAX_BYTES) {
      toast.push({
        title: "File too large",
        description: `"${file.name}" exceeds the 100 MB backend limit.`,
        tone: "danger",
      });
      return;
    }
    setUploading(file.name);
    try {
      const result = await uploadMut.mutateAsync(file);
      // Upload ACCEPTED is not ingestion completed: the toast says exactly
      // that, and the new document is selected so its pipeline is visible.
      toast.push({
        title: "Upload accepted",
        description: `${file.name} → ${result.status}. Ingestion continues below.`,
        tone: "success",
      });
      setSelectedDoc(result.document_id);
      // Scoped invalidation: every documents query (all list filter/page
      // variants, detail, inspectors) + ingestion jobs + dashboard summary.
      // No full-cache clear — unrelated domains are untouched.
      await qc.invalidateQueries({ queryKey: documentsKeys.all });
      await qc.invalidateQueries({ queryKey: documentsKeys.ingestionJobs() });
      await qc.invalidateQueries({ queryKey: dashboardKeys.compliance() });
    } catch (err) {
      const status = err instanceof ApiClientError ? err.status : undefined;
      if (status === 409) {
        toast.push({
          title: "Already in the library",
          description: "This document is already in the regulatory library (same file content).",
          tone: "info",
        });
      } else {
        toast.push({
          title: "Upload failed",
          description: err instanceof Error ? err.message : "Upload failed",
          tone: "danger",
        });
      }
    } finally {
      setUploading(null);
    }
  }

  function handleFiles(files: FileList | null | undefined) {
    if (!files || files.length === 0) return;
    if (files.length > 1) {
      toast.push({
        title: "One file at a time",
        description: `Got ${files.length} files — uploading the first. The backend accepts one file per request.`,
        tone: "info",
      });
    }
    void handleFile(files[0]);
  }

  const runViews = useMemo(() => (jobs ?? []).map(toRunView), [jobs]);
  const activeRuns = runViews.filter((j) => !j.terminal);
  const failedRuns = runViews.filter((j) => j.failed);

  // Title search is client-side over the fetched page (the backend exposes
  // source/status filters only). Stated plainly, not hidden.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return documents ?? [];
    return (documents ?? []).filter((d) => d.title.toLowerCase().includes(q));
  }, [documents, search]);

  const indexedOnPage = (documents ?? []).filter((d) => d.status === "INDEXED").length;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h1 className="page-title">Documents</h1>
        <p className="page-description">Regulatory library, upload, and ingestion pipeline.</p>
      </header>

      <section aria-label="Overview" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="On this page" value={dLoading ? <Skeleton lines={1} /> : formatCount(documents?.length)} hint={`Page ${page + 1} · up to ${PAGE_SIZE}`} />
        <Metric label="Indexed on page" value={dLoading ? <Skeleton lines={1} /> : formatCount(indexedOnPage)} hint="status INDEXED" />
        <Metric
          label="Active runs"
          value={jLoading ? <Skeleton lines={1} /> : formatCount(activeRuns.length)}
          hint={jFetching && activeRuns.length > 0 ? "Updating…" : "Ingestion pipeline"}
        />
        <Metric label="Failed runs" value={jLoading ? <Skeleton lines={1} /> : formatCount(failedRuns.length)} hint="Needs attention" />
      </section>

      <Card padding="md">
        <div
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 transition ${
            dragOver ? "border-brand-500 bg-brand-50 dark:bg-brand-950/20" : "border-slate-300 dark:border-slate-700"
          }`}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleFiles(e.dataTransfer.files);
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
        >
          <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {dragOver ? "Drop file here" : "Drag & drop a document here, or"}
          </p>
          <p className="meta-text mt-1">PDF or TXT only · up to 100 MB · one file per upload</p>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.txt"
            className="hidden"
            aria-label="Select a document to upload (PDF or TXT, up to 100 MB)"
            onChange={(e) => {
              handleFiles(e.target.files);
              if (fileRef.current) fileRef.current.value = "";
            }}
          />
          <Button
            variant="primary"
            size="sm"
            className="mt-3"
            onClick={() => fileRef.current?.click()}
            loading={uploading !== null}
            disabled={uploading !== null}
          >
            {uploading !== null ? `Uploading ${truncate(uploading, 28)}…` : "Select File"}
          </Button>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <Card padding="md">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <label htmlFor="doc-search" className="sr-only">Search titles on this page</label>
              <input
                id="doc-search"
                type="text"
                placeholder="Search titles on this page…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="input flex-1"
              />
              <label htmlFor="doc-source" className="sr-only">Filter by source (server)</label>
              <select
                id="doc-source"
                value={filterSource}
                onChange={(e) => {
                  setFilterSource(e.target.value);
                  resetPage();
                }}
                className="input sm:w-auto"
              >
                <option value="">All sources</option>
                {DOC_SOURCES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <label htmlFor="doc-status" className="sr-only">Filter by status (server)</label>
              <select
                id="doc-status"
                value={filterStatus}
                onChange={(e) => {
                  setFilterStatus(e.target.value);
                  resetPage();
                }}
                className="input sm:w-auto"
              >
                <option value="">All statuses</option>
                {DOC_STATUSES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <p className="meta-text mt-2">Source and status filter on the server; title search applies to this page.</p>
          </Card>

          <Card padding="none">
            <CardHeader
              title="Documents"
              description={`Sorted by upload, newest first · page ${page + 1}`}
              actions={
                <div className="flex items-center gap-1">
                  <Button size="sm" variant="secondary" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
                    Prev
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setPage((p) => p + 1)}
                    disabled={!documents || documents.length < PAGE_SIZE}
                  >
                    Next
                  </Button>
                </div>
              }
            />
            <div className="card-body">
              {dLoading ? <Skeleton lines={6} />
              : dError ? <ErrorState title="Documents couldn't be loaded" onRetry={() => void dRefetch()} />
              : !filtered.length ? (
                <EmptyState
                  title={search || filterSource || filterStatus ? "No documents match" : "Your document library is empty"}
                  description={
                    search || filterSource || filterStatus
                      ? "Try a different search or clear the filters."
                      : "Upload a PDF or TXT above to start ingestion."
                  }
                />
              ) : (
                <Table caption="Regulatory documents">
                  <THead>
                    <TR>
                      <TH>Name</TH>
                      <TH>Type</TH>
                      <TH>Source</TH>
                      <TH>Status</TH>
                      <TH>Pages</TH>
                      <TH>Uploaded</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {filtered.map((d) => (
                      <TR
                        key={d.id}
                        tabIndex={0}
                        role="button"
                        aria-label={`Inspect ${d.title}`}
                        onClick={() => setSelectedDoc(d.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setSelectedDoc(d.id);
                          }
                        }}
                        className={`cursor-pointer ${selectedDoc === d.id ? "bg-brand-50 dark:bg-brand-950/20" : ""}`}
                      >
                        <TD className="font-medium">{truncate(d.title, 50)}</TD>
                        <TD className="text-slate-500 text-[10px]">{d.document_type || (d.file_name?.split(".").pop()?.toUpperCase() ?? "—")}</TD>
                        <TD><Badge tone="neutral" size="sm">{d.source}</Badge></TD>
                        <TD><Badge tone={docStatusTone(d.status)} size="sm">{d.status}</Badge></TD>
                        <TD className="text-slate-500">{d.page_count ?? "—"}</TD>
                        <TD className="text-slate-500 text-[10px]">{formatRelative(toMillis(d.uploaded_at))}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </div>
          </Card>
        </div>

        <aside className="space-y-4">
          <DetailPanel
            selectedDoc={selectedDoc}
            detail={detail}
            detLoading={detLoading}
            chunks={chunks}
            pages={pages}
            inspectorTab={inspectorTab}
            onInspectorTab={setInspectorTab}
            onClose={() => setSelectedDoc(null)}
            onRefresh={() => {
              void refetchDetail();
              if (selectedDoc) {
                void qc.invalidateQueries({ queryKey: documentsKeys.chunks(selectedDoc) });
                void qc.invalidateQueries({ queryKey: documentsKeys.pages(selectedDoc) });
              }
            }}
          />

          <Card padding="none">
            <CardHeader
              title="Ingestion runs"
              description={activeRuns.length > 0 ? "Polling every 5s while active" : "Pipeline activity"}
            />
            <div className="card-body max-h-64 overflow-y-auto">
              {jLoading ? <Skeleton lines={3} />
              : jError ? <ErrorState title="Runs couldn't be loaded" onRetry={() => void jRefetch()} />
              : !runViews.length ? <EmptyState title="No runs yet" description="Runs appear here after uploads." />
              : <ul className="space-y-1.5">
                  {runViews.slice(0, 20).map((j) => (
                    <RunRow key={j.id} run={j} onSelectDoc={setSelectedDoc} />
                  ))}
                </ul>
              }
            </div>
          </Card>
        </aside>
      </div>
    </div>
  );
}

function formatCount(n: number | undefined): string {
  return n == null ? "—" : String(n);
}

/**
 * One ingestion run row. The list endpoint never carries failure text, so
 * failed runs offer an expander that lazy-loads the run-detail endpoint
 * (the only honest source of failure_reason).
 */
function RunRow({
  run,
  onSelectDoc,
}: {
  run: ReturnType<typeof toRunView>;
  onSelectDoc: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const { data: runDetail } = useQuery({
    queryKey: documentsKeys.ingestionRun(run.id),
    queryFn: () => getIngestionJob(run.id),
    enabled: expanded && run.failed,
  });
  return (
    <li className="rounded-lg border border-slate-200 px-2.5 py-2 dark:border-slate-800">
      <div className="flex items-center gap-1.5">
        <Badge tone={runStatusTone(run.status)} size="sm">{run.status}</Badge>
        {run.documentId ? (
          <button
            type="button"
            onClick={() => onSelectDoc(run.documentId!)}
            className="truncate text-left text-xs font-medium text-brand-600 hover:underline dark:text-brand-300"
          >
            {truncate(run.documentId, 24)}
          </button>
        ) : (
          <span className="truncate text-xs text-slate-500">{truncate(run.id, 24)}</span>
        )}
      </div>
      <p className="mt-0.5 text-[10px] text-slate-500" title={RUN_STATUS_HELP[run.status]}>
        {RUN_STATUS_HELP[run.status] ?? run.status} · {run.chunksCreated} chunks · {run.embeddingsCreated} embeddings
      </p>
      {run.failed && (
        <div className="mt-1">
          {!expanded ? (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              className="text-[10px] font-medium text-red-600 hover:underline dark:text-red-300"
            >
              View error
            </button>
          ) : runDetail?.failure_reason ? (
            <p className="text-[10px] text-red-600 dark:text-red-300">
              {truncate(runDetail.failure_reason, 200)}
            </p>
          ) : (
            <p className="text-[10px] text-slate-500">No error recorded for this run.</p>
          )}
        </div>
      )}
    </li>
  );
}

function DetailPanel(props: {
  selectedDoc: string | null;
  detail: DocumentDetail | undefined;
  detLoading: boolean;
  chunks: StoredChunk[] | undefined;
  pages: DocumentPageType[] | undefined;
  inspectorTab: "chunks" | "pages";
  onInspectorTab: (t: "chunks" | "pages") => void;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const { selectedDoc, detail, detLoading } = props;
  if (!selectedDoc) return null;
  return (
    <Card padding="md">
      {detLoading || !detail ? (
        <Skeleton lines={6} />
      ) : (
        <>
          <div className="flex items-center justify-between gap-2">
            <h3 className="section-title truncate">{truncate(detail.title, 40)}</h3>
            <button onClick={props.onClose} aria-label="Close document detail" className="rounded p-1 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">×</button>
          </div>
          <dl className="mt-4 space-y-2 text-xs">
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Status</dt><dd><Badge tone={docStatusTone(detail.status)} size="sm">{detail.status}</Badge></dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Pipeline</dt><dd className="text-right">{detail.processing_status}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Indexed</dt><dd>{detail.indexed ? "Yes — searchable" : "No"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Source</dt><dd className="font-medium">{detail.source}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Type</dt><dd>{detail.document_type || "—"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Pages</dt><dd>{detail.page_count ?? "—"}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Chunks</dt><dd>{detail.chunk_count}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Embeddings</dt><dd>{detail.embedding_count}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Uploaded</dt><dd>{formatRelative(toMillis(detail.uploaded_at))}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Checksum</dt><dd className="font-mono text-[10px]">{truncate(detail.checksum, 16)}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">ID</dt><dd className="font-mono text-[10px]">{truncate(detail.id, 16)}</dd></div>
          </dl>
          <div className="mt-4">
            <Tabs
              items={[
                { id: "chunks", label: `Chunks (${detail.chunk_count})` },
                { id: "pages", label: "Pages" },
              ]}
              value={props.inspectorTab}
              onChange={(id) => props.onInspectorTab(id as "chunks" | "pages")}
              label="Document inspector"
              idPrefix="doc-inspector"
            />
            <div role="tabpanel" id={`doc-inspector-panel-${props.inspectorTab}`} aria-labelledby={`doc-inspector-tab-${props.inspectorTab}`} tabIndex={0} className="pt-3">
              {props.inspectorTab === "chunks" ? (
                !(props.chunks ?? []).length ? (
                  <EmptyState title="No chunks yet" description="Chunks appear once parsing completes." />
                ) : (
                  <ChunkList chunks={props.chunks!} />
                )
              ) : !(props.pages ?? []).length ? (
                <EmptyState title="No pages yet" description="Pages appear once parsing completes." />
              ) : (
                <PageList pages={props.pages!} />
              )}
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <Button variant="secondary" size="sm" onClick={props.onRefresh}>Refresh</Button>
          </div>
        </>
      )}
    </Card>
  );
}

function ChunkList({ chunks }: { chunks: StoredChunk[] }) {
  const shown = chunks.slice(0, 20);
  return (
    <div className="space-y-2">
      {chunks.length > 20 ? (
        <p className="meta-text">Showing first 20 of {chunks.length} chunks.</p>
      ) : null}
      <ul className="max-h-72 space-y-2 overflow-y-auto">
        {shown.map((c) => (
          <li key={c.id} className="rounded-lg border border-slate-200 p-2.5 text-xs dark:border-slate-800">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-[10px] text-slate-500">{truncate(c.id, 14)}</span>
              {c.section ? <Badge tone="neutral" size="sm">{c.section}</Badge> : null}
              <span className="ml-auto text-[10px] text-slate-400">p.{c.page_number} · {c.token_count} tok</span>
            </div>
            <p className="mt-1 line-clamp-3 text-slate-600 dark:text-slate-300">{c.content}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PageList({ pages }: { pages: DocumentPageType[] }) {
  const shown = pages.slice(0, 20);
  return (
    <div className="space-y-2">
      {pages.length > 20 ? (
        <p className="meta-text">Showing first 20 of {pages.length} pages.</p>
      ) : null}
      <ul className="max-h-72 space-y-2 overflow-y-auto">
        {shown.map((p) => (
          <li key={p.id} className="rounded-lg border border-slate-200 p-2.5 text-xs dark:border-slate-800">
            <p className="font-mono text-[10px] text-slate-500">Page {p.page_number}</p>
            <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-slate-600 dark:text-slate-300">{p.content}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

