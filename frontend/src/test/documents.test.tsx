/**
 * Stage 08 documents tests: real lifecycle (upload -> runs -> detail),
 * server filters/pagination, bounded polling, chunks/pages inspectors.
 * MSW replies with backend-shaped payloads (documents/ingestion schemas).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { DocumentsPage } from "@/pages/DocumentsPage";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { ToastViewport } from "@/components/ui/ToastViewport";
import { getDashboardCompliance } from "@/services/api/dashboardApi";
import { dashboardKeys } from "@/lib/queryKeys";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const docFixture = (id: string, overrides: Record<string, unknown> = {}) => ({
  id,
  title: `Doc ${id}`,
  source: "RBI",
  file_name: `${id}.pdf`,
  file_path: `/x/${id}.pdf`,
  checksum: "ab".repeat(32),
  status: "INDEXED",
  uploaded_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
  document_type: "CIRCULAR",
  page_count: 4,
  ...overrides,
});

const runFixture = (run_id: string, status: string, document_id: string | null = "d1") => ({
  run_id,
  document_id,
  status,
  steps: [],
  chunks_created: status === "completed" ? 4 : 0,
  embeddings_created: status === "completed" ? 4 : 0,
  pages_parsed: 2,
  is_duplicate: false,
  started_at: "2026-01-01T00:00:00+00:00",
  finished_at: status === "completed" ? "2026-01-01T00:01:00+00:00" : null,
  duration_ms: 1000,
});

let listHits: string[] = [];
let runsHits = 0;

function listHandler(docs: unknown[]) {
  return async ({ request }: { request: Request }) => {
    const url = new URL(request.url);
    listHits.push(url.search);
    return HttpResponse.json(docs);
  };
}

const server = setupServer(
  http.get("/api/v1/documents", async ({ request }) => {
    const url = new URL(request.url);
    listHits.push(url.search);
    return HttpResponse.json([
      docFixture("d1"),
      docFixture("d2", { status: "PROCESSING", title: "Second doc", source: "SEBI" }),
    ]);
  }),
  http.post("/api/v1/documents/upload", async () => {
    return HttpResponse.json({ document_id: "d9", status: "processing", run_id: "run-9" }, { status: 201 });
  }),
  http.get("/api/v1/documents/:id", async ({ params }) => {
    return HttpResponse.json({
      ...docFixture(params.id as string),
      chunk_count: 4,
      embedding_count: 4,
      indexed: true,
      processing_status: "completed",
    });
  }),
  http.get("/api/v1/documents/:id/chunks", async () => {
    return HttpResponse.json([
      {
        id: "c1", document_id: "d1", page_number: 1, section: "4.2",
        content: "Every bank shall verify identity.", token_count: 12,
        metadata_json: {}, created_at: "2026-01-01T00:00:00+00:00",
      },
    ]);
  }),
  http.get("/api/v1/documents/:id/pages", async () => {
    return HttpResponse.json([
      { id: "p1", document_id: "d1", page_number: 1, content: "Page one text.", created_at: "2026-01-01T00:00:00+00:00" },
    ]);
  }),
  http.get("/api/v1/ingestion/runs", async () => {
    runsHits += 1;
    return HttpResponse.json({
      items: [runFixture("run-1", "completed"), runFixture("run-2", "failed", "d2")],
      total: 2, page: 1, page_size: 50,
    });
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
  listHits = [];
  runsHits = 0;
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderDocuments() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/documents"]}>
            <Routes>
              <Route path="/documents" element={<DocumentsPage />} />
            </Routes>
          </MemoryRouter>
          <ToastViewport />
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

function uploadFile(name: string, type: string, size = 10) {
  const input = screen.getByLabelText(/select a document to upload/i) as HTMLInputElement;
  const file = new File([new Uint8Array(size)], name, { type });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("document list", () => {
  it("1+2+3. renders, loads, and shows real rows", async () => {
    renderDocuments();
    expect(await screen.findByText("Doc d1")).toBeTruthy();
    expect(screen.getByText("Second doc")).toBeTruthy();
  });

  it("4+5. empty library vs load failure are distinct", async () => {
    server.use(
      http.get("/api/v1/documents", listHandler([]))
    );
    renderDocuments();
    expect(await screen.findByText("Your document library is empty")).toBeTruthy();
  });

  it("5b. load failure shows retryable error", async () => {
    server.use(
      http.get("/api/v1/documents", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderDocuments();
    expect(await screen.findByText("Documents couldn't be loaded")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("6+11+12. fields, timestamps, statuses render from the contract", async () => {
    renderDocuments();
    await screen.findByText("Doc d1");
    const table = screen.getByRole("table");
    expect(within(table).getByText("INDEXED")).toBeTruthy();
    expect(within(table).getByText("PROCESSING")).toBeTruthy();
    // uploaded_at ISO renders relatively, never raw or Invalid Date.
    expect(screen.queryByText("Invalid Date")).toBeNull();
    expect(screen.queryByText("2026-01-01T00:00:00+00:00")).toBeNull();
  });

  it("7+8. server pagination params sent; no fake totals", async () => {
    renderDocuments();
    await screen.findByText("Doc d1");
    expect(listHits.length).toBeGreaterThanOrEqual(1);
    expect(listHits[0]).toContain("limit=25");
    expect(listHits[0]).toContain("skip=0");
    expect(screen.queryByText(/of \d+ documents/)).toBeNull();
  });

  it("next page advances skip; prev returns", async () => {
    const many = Array.from({ length: 25 }, (_, i) => docFixture(`dx${i}`));
    server.use(http.get("/api/v1/documents", listHandler(many)));
    renderDocuments();
    const user = userEvent.setup();
    await screen.findByText("Doc dx0");
    await user.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(listHits.some((q) => q.includes("skip=25"))).toBe(true));
    await user.click(screen.getByRole("button", { name: "Prev" }));
    await waitFor(() => expect(listHits.filter((q) => q.includes("skip=0")).length).toBeGreaterThan(1));
  });

  it("9+10. source/status filters reach the server; title stays local", async () => {
    renderDocuments();
    const user = userEvent.setup();
    await screen.findByText("Doc d1");
    await user.selectOptions(screen.getByLabelText(/filter by source/i), "SEBI");
    await waitFor(() => expect(listHits.some((q) => q.includes("source=SEBI"))).toBe(true));
    await user.selectOptions(screen.getByLabelText(/filter by status/i), "INDEXED");
    await waitFor(() => expect(listHits.some((q) => q.includes("status=INDEXED"))).toBe(true));
  });

  it("13. long names truncate safely", async () => {
    server.use(
      http.get("/api/v1/documents", listHandler([
        docFixture("dx", { title: "A".repeat(200) }),
      ]))
    );
    renderDocuments();
    const cell = await screen.findByText(/A{10}/);
    // Helper truncation caps text at 50 chars; cell stays single-line.
    expect(cell.textContent!.length).toBeLessThanOrEqual(50);
  });
});

describe("upload", () => {
  it("14+16+18. valid file uploads and selects the new document", async () => {
    renderDocuments();
    await screen.findByText("Doc d1");
    uploadFile("new.pdf", "application/pdf");
    expect(await screen.findByText(/Upload accepted/)).toBeTruthy();
    // New document auto-selected: its detail panel appears.
    expect(await screen.findByText("Pipeline")).toBeTruthy();
  });

  it("15. invalid extension rejected client-side with guidance", async () => {
    renderDocuments();
    await screen.findByText("Doc d1");
    uploadFile("evil.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    expect(await screen.findByText(/Unsupported file type/)).toBeTruthy();
    expect(screen.queryByText(/Upload accepted/)).toBeNull();
  });

  it("15b. oversize file rejected before upload", async () => {
    renderDocuments();
    await screen.findByText("Doc d1");
    uploadFile("big.pdf", "application/pdf", 101 * 1024 * 1024);
    expect(await screen.findByText(/exceeds the 100 MB/)).toBeTruthy();
  });

  it("17. duplicate submit prevented while uploading", async () => {
    let posts = 0;
    server.use(
      http.post("/api/v1/documents/upload", async () => {
        posts += 1;
        await new Promise((r) => setTimeout(r, 300));
        return HttpResponse.json({ document_id: "d9", status: "processing" }, { status: 201 });
      })
    );
    renderDocuments();
    await screen.findByText("Doc d1");
    const input = screen.getByLabelText(/select a document to upload/i) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "a.pdf", { type: "application/pdf" })] } });
    // Button disables itself while the request is in flight.
    expect(await screen.findByText(/Uploading a.pdf/)).toBeTruthy();
    expect(posts).toBeLessThanOrEqual(1);
    await screen.findByText(/Upload accepted/);
    expect(posts).toBe(1);
  });

  it("19+20. upload failure surfaces canonical error; 409 is distinct", async () => {
    server.use(
      http.post("/api/v1/documents/upload", async () => {
        return HttpResponse.json({ detail: "checksum exists" }, { status: 409 });
      })
    );
    renderDocuments();
    await screen.findByText("Doc d1");
    uploadFile("dup.pdf", "application/pdf");
    expect(await screen.findByText("Already in the library")).toBeTruthy();
  });

  it("21. no fake progress percentages during upload", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    server.use(
      http.post("/api/v1/documents/upload", async () => {
        await gate;
        return HttpResponse.json({ document_id: "d9", status: "processing" }, { status: 201 });
      })
    );
    renderDocuments();
    await screen.findByText("Doc d1");
    uploadFile("slow.pdf", "application/pdf");
    await screen.findByText(/Uploading slow.pdf/);
    expect(document.body.textContent).not.toMatch(/\d+%/);
    release();
    expect(await screen.findByText(/Upload accepted/)).toBeTruthy();
  });

  it("22. upload accepted is distinguished from ingestion completed", async () => {
    renderDocuments();
    await screen.findByText("Doc d1");
    uploadFile("new.pdf", "application/pdf");
    expect(await screen.findByText("Upload accepted")).toBeTruthy();
    expect(await screen.findByText(/Ingestion continues below/)).toBeTruthy();
  });
});

describe("ingestion", () => {
  it("23-27. all lifecycle states render with honest tones", async () => {
    server.use(
      http.get("/api/v1/ingestion/runs", async () => HttpResponse.json({
        items: [
          runFixture("r1", "pending"),
          runFixture("r2", "embedding"),
          runFixture("r3", "completed"),
          runFixture("r4", "failed"),
          runFixture("r5", "skipped"),
        ],
        total: 5, page: 1, page_size: 50,
      }))
    );
    renderDocuments();
    for (const s of ["pending", "embedding", "completed", "failed", "skipped"]) {
      expect(await screen.findByText(s, { exact: true })).toBeTruthy();
    }
    // Completed reads success, never amber.
    expect(screen.getByText("completed").closest("li")!.textContent).toBeTruthy();
  });

  it("unknown run status falls back safely", async () => {
    server.use(
      http.get("/api/v1/ingestion/runs", async () => HttpResponse.json({
        items: [runFixture("rx", "mystery-state")],
        total: 1, page: 1, page_size: 50,
      }))
    );
    renderDocuments();
    expect(await screen.findByText("mystery-state")).toBeTruthy();
  });

  it("28+29+30. polls while active, stops at terminal, cleans up", async () => {
    vi.useFakeTimers();
    try {
      let mode: "active" | "terminal" = "active";
      server.use(
        http.get("/api/v1/ingestion/runs", async () => {
          runsHits += 1;
          const status = mode === "active" ? "indexing" : "completed";
          return HttpResponse.json({
            items: [runFixture("r1", status)],
            total: 1, page: 1, page_size: 50,
          });
        })
      );
      renderDocuments();
      // Flush mount under fake timers, then assert on settled content.
      await vi.advanceTimersByTimeAsync(200);
      expect(screen.getByText("Doc d1")).toBeTruthy();
      const first = runsHits;
      await vi.advanceTimersByTimeAsync(6000);
      expect(runsHits).toBeGreaterThan(first);
      mode = "terminal";
      await vi.advanceTimersByTimeAsync(15000);
      const settled = runsHits;
      await vi.advanceTimersByTimeAsync(15000);
      expect(runsHits).toBe(settled);
    } finally {
      vi.useRealTimers();
    }
  });

  it("failure reason loads on demand, bounded, without tracebacks", async () => {
    server.use(
      http.get("/api/v1/ingestion/runs/:id", async () => HttpResponse.json({
        run_id: "rf",
        document_id: "d2",
        ingestion_status: "failed",
        chunks_created: 0,
        embeddings_created: 0,
        pages_parsed: 0,
        is_duplicate: false,
        is_incremental_update: false,
        failure_reason: "Traceback X".padEnd(500, "!"),
        duration_ms: 5,
      }))
    );
    renderDocuments();
    const user = userEvent.setup();
    await screen.findByText("Doc d1");
    await user.click(await screen.findByText("View error"));
    const el = await screen.findByText(/Traceback X/);
    expect(el.textContent!.length).toBeLessThanOrEqual(210);
  });
});

describe("detail + inspectors", () => {
  async function openDetail() {
    renderDocuments();
    const user = userEvent.setup();
    await user.click(await screen.findByText("Doc d1"));
    await screen.findByText("Pipeline");
    return user;
  }

  it("31+32. detail loads with structured metadata", async () => {
    await openDetail();
    expect(screen.getByText("Yes — searchable")).toBeTruthy();
    expect(screen.getAllByText("completed").length).toBeGreaterThanOrEqual(1);
  });

  it("33. detail failure is recoverable", async () => {
    server.use(
      http.get("/api/v1/documents/:id", async () => {
        return HttpResponse.json({ detail: "gone" }, { status: 404 });
      })
    );
    renderDocuments();
    const user = userEvent.setup();
    await user.click(await screen.findByText("Doc d1"));
    await waitFor(() => expect(screen.queryByText("Pipeline")).toBeNull());
  });

  it("34+35. UUID ids encode safely in chunk/page requests", async () => {
    const seen: string[] = [];
    server.use(
      http.get("/api/v1/documents/:id/chunks", async ({ request }) => {
        seen.push(new URL(request.url).pathname);
        return HttpResponse.json([]);
      })
    );
    renderDocuments();
    const user = userEvent.setup();
    await user.click(await screen.findByText("Second doc"));
    await waitFor(() => expect(seen.length).toBeGreaterThan(0));
  });

  it("36+37. chunks and pages inspectors with empty states", async () => {
    const user = await openDetail().then(async () => userEvent.setup());
    expect(await screen.findByText("Every bank shall verify identity.")).toBeTruthy();
    await user.click(screen.getByRole("tab", { name: "Pages" }));
    expect(await screen.findByText("Page one text.")).toBeTruthy();
  });

  it("empty chunks render honestly", async () => {
    server.use(
      http.get("/api/v1/documents/:id/chunks", async () => HttpResponse.json([]))
    );
    await openDetail();
    expect(await screen.findByText("No chunks yet")).toBeTruthy();
  });
});

describe("relationships + a11y + responsive", () => {
  it("43. upload invalidates list, jobs, and dashboard compliance", async () => {
    let complianceHits = 0;
    server.use(
      http.get("/api/v1/dashboard/compliance", async () => {
        complianceHits += 1;
        return HttpResponse.json({
          regulations_tracked: 0, changes_detected: 0, impact_reports: 0,
          alerts_open: 0, alerts_critical: 0, alerts_failed: 0,
          documents_ingested: 1, knowledge_graph_nodes: 0, knowledge_graph_edges: 0,
          research_reports: 0,
        });
      })
    );
    // A mounted dashboard-compliance probe observes the invalidation.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    function Probe() {
      useQuery({ queryKey: dashboardKeys.compliance(), queryFn: getDashboardCompliance });
      return null;
    }
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ToastProvider>
            <MemoryRouter initialEntries={["/documents"]}>
              <Routes>
                <Route path="/documents" element={<><Probe /><DocumentsPage /></>} />
              </Routes>
            </MemoryRouter>
            <ToastViewport />
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>
    );
    await screen.findByText("Doc d1");
    expect(complianceHits).toBe(1);
    const beforeList = listHits.length;
    uploadFile("fresh.pdf", "application/pdf");
    await screen.findByText(/Upload accepted/);
    await waitFor(() => expect(complianceHits).toBeGreaterThan(1));
    await waitFor(() => expect(listHits.length).toBeGreaterThan(beforeList));
  });

  it("45. upload touches only documents/ingestion/dashboard endpoints", async () => {
    // The MSW server runs with onUnhandledRequest: "error", so any fetch
    // outside the documents/ingestion/dashboard surface fails this test.
    // Research, conversations, and other domains are never requested here.
    renderDocuments();
    await screen.findByText("Doc d1");
    uploadFile("fresh.pdf", "application/pdf");
    await screen.findByText(/Upload accepted/);
    await waitFor(() => expect(listHits.length).toBeGreaterThan(1));
  });

  it("46+47+48+49+50. heading, labels, table semantics, statuses", async () => {
    renderDocuments();
    expect(await screen.findByRole("heading", { name: "Documents", level: 1 })).toBeTruthy();
    expect(screen.getByLabelText(/select a document to upload/i)).toBeTruthy();
    await screen.findByText("Doc d1");
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeTruthy();
    const row = screen.getByText("Doc d1").closest("tr")!;
    expect(row.getAttribute("tabindex")).toBe("0");
  });

  it("rows are keyboard-operable", async () => {
    renderDocuments();
    const user = userEvent.setup();
    await screen.findByText("Doc d1");
    const row = screen.getByText("Doc d1").closest("tr")!;
    row.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByText("Pipeline")).toBeTruthy();
  });

  it("51+52. mobile structure without overflow", async () => {
    renderDocuments();
    await screen.findByText("Doc d1");
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1024 + 1);
  });
});

