import { useState, useRef } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/Table";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getDocuments, uploadDocument, getIngestionJobs } from "@/services/api";
import { useToast } from "@/providers/ToastProvider";
import { formatRelative, truncate } from "@/lib/format";

export function DocumentsPage() {
  const qc = useQueryClient();
  const { data: documents, isLoading: dLoading, isError: dError, refetch: dRefetch } = useQuery({
    queryKey: ["documents"], queryFn: getDocuments,
  });
  const { data: jobs, isLoading: jLoading, isError: jError, refetch: jRefetch } = useQuery({
    queryKey: ["ingestion", "jobs"], queryFn: getIngestionJobs,
  });
  const uploadMut = useMutation({ mutationFn: uploadDocument });
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const result = await uploadMut.mutateAsync(file);
      toast.push({ title: "Uploaded", description: `${file.name} → ${result.status}`, tone: "success" });
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["ingestion", "jobs"] });
    } catch (err) {
      toast.push({ title: "Upload failed", description: err instanceof Error ? err.message : "Error", tone: "danger" });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const jobStatusTone = (s: string) =>
    s === "succeeded" ? "success" : s === "failed" ? "danger" : s === "running" ? "warning" : "neutral";

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Documents</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Regulatory document library and ingestion pipeline.</p>
      </header>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Metric label="Total Documents" value={documents?.length ?? "—"} />
        {jobs && <Metric label="Active jobs" value={jobs.filter((j) => j.status === "running" || j.status === "queued").length} />}
        <Metric label="Ingestion jobs" value={jobs?.length ?? "—"} />
      </section>

      <Card padding="md">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Upload Document</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400">PDF, DOCX, or HTML regulatory filings</p>
          </div>
          <div>
            <input ref={fileRef} type="file" accept=".pdf,.docx,.html,.xml" className="hidden" onChange={handleUpload} />
            <Button variant="primary" onClick={() => fileRef.current?.click()} loading={uploading}>Upload</Button>
          </div>
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Documents" />
        <div className="card-body">
          {dLoading ? <Skeleton lines={5} />
          : dError ? <ErrorState onRetry={dRefetch} />
          : !documents?.length ? <EmptyState title="No documents" description="Upload a document to get started." />
          : <Table>
              <THead><TR><TH>Title</TH><TH>Source</TH><TH>Jurisdiction</TH><TH>Status</TH><TH>Chunks</TH><TH>Created</TH></TR></THead>
              <TBody>
                {documents.map((d) => (
                  <TR key={d.document_id}>
                    <TD className="font-medium">{truncate(d.title, 60)}</TD>
                    <TD className="text-slate-500">{truncate(d.source, 30)}</TD>
                    <TD><Badge tone="neutral" size="sm">{d.jurisdiction ?? "—"}</Badge></TD>
                    <TD><Badge tone={d.status === "ready" ? "success" : "warning"} size="sm">{d.status}</Badge></TD>
                    <TD>{d.chunk_count}</TD>
                    <TD className="text-slate-500">{formatRelative(d.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          }
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Ingestion Jobs" description="Document ingestion pipeline status" />
        <div className="card-body">
          {jLoading ? <Skeleton lines={3} />
          : jError ? <ErrorState onRetry={jRefetch} />
          : !jobs?.length ? <EmptyState title="No ingestion jobs" />
          : <ul className="space-y-2">
              {jobs.map((j) => (
                <li key={j.job_id} className="rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-800">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{truncate(j.source, 60)}</span>
                    <Badge tone={jobStatusTone(j.status)} size="sm">{j.status}</Badge>
                    {(j.status === "running" || j.status === "queued") && (
                      <span className="ml-auto text-[10px] text-slate-500">{j.documents_processed} / {j.documents_total}</span>
                    )}
                  </div>
                  {(j.status === "running" || j.status === "queued") && (
                    <ProgressBar value={j.documents_processed} max={j.documents_total} className="mt-2" />
                  )}
                  {j.error && <p className="mt-1 text-xs text-red-600">{j.error}</p>}
                </li>
              ))}
            </ul>
          }
        </div>
      </Card>
    </div>
  );
}
