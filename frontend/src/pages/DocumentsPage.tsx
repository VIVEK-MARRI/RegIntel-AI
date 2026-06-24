import { useState, useRef, useCallback } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getDocuments, uploadDocument, getDocument, getIngestionJobs } from "@/services/api";
import { useToast } from "@/providers/ToastProvider";
import { formatRelative, truncate } from "@/lib/format";


const STATUS_TONE: Record<string, string> = {
  UPLOADED: "neutral",
  PROCESSING: "warning",
  PARSING: "warning",
  PARSED: "info",
  INDEXED: "success",
  FAILED: "danger",
};

const ALLOWED_TYPES = ".pdf,.docx,.txt,.html,.htm";

function statusTone(s: string) {
  return STATUS_TONE[s] ?? "neutral";
}

export function DocumentsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filterSource, setFilterSource] = useState("");

  const { data: documents, isLoading: dLoading, isError: dError, refetch: dRefetch } = useQuery({
    queryKey: ["documents"], queryFn: getDocuments,
  });
  const { data: jobs, isLoading: jLoading, isError: jError, refetch: jRefetch } = useQuery({
    queryKey: ["ingestion", "jobs"], queryFn: getIngestionJobs,
  });
  const { data: detail, refetch: refetchDetail } = useQuery({
    queryKey: ["document", selectedDoc],
    queryFn: () => getDocument(selectedDoc!),
    enabled: Boolean(selectedDoc),
  });

  const uploadMut = useMutation({ mutationFn: (file: File) => uploadDocument(file) });

  async function handleFile(file: File) {
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED_TYPES.includes(ext)) {
      toast.push({ title: "Unsupported file type", description: `${ext} not allowed. Use PDF, DOCX, TXT, or HTML.`, tone: "danger" });
      return;
    }
    setUploading(true);
    try {
      const result = await uploadMut.mutateAsync(file);
      toast.push({ title: "Uploaded", description: `${file.name} → ${result.status}`, tone: "success" });
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["ingestion", "jobs"] });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed";
      toast.push({ title: "Upload failed", description: msg, tone: "danger" });
    } finally {
      setUploading(false);
    }
  }

  const handleInputChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await handleFile(file);
    if (fileRef.current) fileRef.current.value = "";
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    await handleFile(file);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => setDragOver(false), []);

  const activeJobs = jobs?.filter((j) => j.status === "running" || j.status === "queued") ?? [];
  const userUploads = documents?.filter((d) => d.source === "USER_UPLOAD") ?? [];

  const filtered = (documents ?? []).filter((d) => {
    if (search && !d.title.toLowerCase().includes(search.toLowerCase())) return false;
    if (filterSource && d.source !== filterSource) return false;
    return true;
  });

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Documents</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Enterprise document upload, ingestion pipeline, and search.</p>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Metric label="Total Documents" value={documents?.length ?? "—"} hint="All registered documents" />
        <Metric label="User Uploads" value={userUploads.length} hint="Enterprise documents" />
        <Metric label="Active Jobs" value={activeJobs.length} hint="Running / queued" />
        <Metric label="Indexed" value={documents?.filter((d) => d.status === "INDEXED").length ?? "—"} hint="Ready for search" />
      </section>

      <Card padding="md">
        <div
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition ${
            dragOver ? "border-brand-500 bg-brand-50 dark:bg-brand-950/20" : "border-slate-300 dark:border-slate-700"
          }`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {dragOver ? "Drop file here" : "Drag & drop a document here, or"}
          </p>
          <p className="mt-1 text-[10px] text-slate-500 dark:text-slate-400">PDF, DOCX, TXT, HTML — up to 100 MB</p>
          <input ref={fileRef} type="file" accept={ALLOWED_TYPES} className="hidden" onChange={handleInputChange} />
          <Button variant="primary" size="sm" className="mt-3" onClick={() => fileRef.current?.click()} loading={uploading}>
            Select File
          </Button>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <Card padding="md">
            <div className="flex items-center gap-3">
              <input
                type="text"
                placeholder="Search documents..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              />
              <select
                value={filterSource}
                onChange={(e) => setFilterSource(e.target.value)}
                className="rounded-lg border border-slate-300 px-2 py-1.5 text-xs dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                <option value="">All sources</option>
                <option value="USER_UPLOAD">User Upload</option>
                <option value="RBI">RBI</option>
                <option value="SEBI">SEBI</option>
                <option value="IRDAI">IRDAI</option>
              </select>
            </div>
          </Card>

          <Card padding="none">
            <CardHeader
              title="Documents"
              actions={filtered.length > 0 ? <Badge tone="neutral" size="sm">{filtered.length}</Badge> : undefined}
            />
            <div className="card-body">
              {dLoading ? <Skeleton lines={6} />
              : dError ? <ErrorState onRetry={dRefetch} />
              : !filtered.length ? <EmptyState title="No documents" description={search ? "Try a different search." : "Upload a document to get started."} />
              : <Table>
                  <THead>
                    <TR>
                      <TH>Name</TH>
                      <TH>Type</TH>
                      <TH>Source</TH>
                      <TH>Status</TH>
                      <TH>Pages</TH>
                      <TH>Chunks</TH>
                      <TH>Uploaded</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {filtered.map((d) => (
                      <TR
                        key={d.id}
                        onClick={() => setSelectedDoc(d.id)}
                        className={`cursor-pointer ${selectedDoc === d.id ? "bg-brand-50 dark:bg-brand-950/20" : ""}`}
                      >
                        <TD className="font-medium">{truncate(d.title, 50)}</TD>
                        <TD className="text-slate-500 text-[10px]">{d.document_type || (d.file_name?.split(".").pop()?.toUpperCase() ?? "—")}</TD>
                        <TD><Badge tone="neutral" size="sm">{d.source}</Badge></TD>
                        <TD><Badge tone={statusTone(d.status) as any} size="sm">{d.status}</Badge></TD>
                        <TD className="text-slate-500">{d.page_count ?? "—"}</TD>
                        <TD className="text-slate-500">{d.chunk_count ?? "—"}</TD>
                        <TD className="text-slate-500 text-[10px]">{formatRelative(d.created_at)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              }
            </div>
          </Card>
        </div>

        <aside className="space-y-4">
          {selectedDoc && detail ? (
            <Card padding="md">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{truncate(detail.title, 40)}</h3>
                <button onClick={() => setSelectedDoc(null)} className="text-xs text-slate-400 hover:text-slate-600">&times;</button>
              </div>
              <dl className="mt-4 space-y-2 text-xs">
                <div className="flex justify-between"><dt className="text-slate-500">Status</dt><dd><Badge tone={statusTone(detail.status) as any} size="sm">{detail.status}</Badge></dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Source</dt><dd className="font-medium">{detail.source}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Type</dt><dd>{detail.document_type || "—"}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Pages</dt><dd>{detail.page_count ?? "—"}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Chunks</dt><dd>{detail.chunk_count ?? "—"}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Embeddings</dt><dd>{detail.embedding_count ?? "—"}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Indexed</dt><dd>{detail.indexed ? "Yes" : "No"}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Processing</dt><dd>{detail.processing_status}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-500">Uploaded</dt><dd>{formatRelative(detail.created_at)}</dd></div>
              </dl>
              <div className="mt-4 flex gap-2">
                <Button variant="secondary" size="sm" onClick={() => refetchDetail()}>Refresh</Button>
              </div>
            </Card>
          ) : null}

          <Card padding="none">
            <CardHeader title="Ingestion Jobs" description="Pipeline activity" />
            <div className="card-body max-h-64 overflow-y-auto">
              {jLoading ? <Skeleton lines={3} />
              : jError ? <ErrorState onRetry={jRefetch} />
              : !jobs?.length ? <EmptyState title="No jobs" />
              : <ul className="space-y-1.5">
                  {jobs.slice(0, 20).map((j) => (
                    <li key={j.job_id} className="rounded-lg border border-slate-200 px-2.5 py-2 dark:border-slate-800">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-xs font-medium text-slate-900 dark:text-slate-100">{truncate(j.source || j.document_id || j.job_id, 35)}  // eslint-disable-line</span>
                        <Badge tone={j.status === "succeeded" ? "success" : j.status === "failed" ? "danger" : "warning"} size="sm">{j.ingestion_status || j.status}</Badge>
                      </div>
                      {j.chunks_created != null && (
                        <p className="mt-0.5 text-[10px] text-slate-500">{j.chunks_created} chunks · {j.embeddings_created} embeddings</p>
                      )}
                      {j.failure_reason && <p className="mt-0.5 text-[10px] text-red-600">{j.failure_reason}</p>}
                    </li>
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
