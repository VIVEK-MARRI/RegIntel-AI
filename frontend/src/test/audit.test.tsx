/**
 * Stage 12 audit tests: records with server filters/pagination, tri-state
 * integrity (intact / compromised / unavailable — never default-healthy),
 * evidence on demand with verbatim hashes, report generation + detail, cache
 * isolation, and the no-fake-trust rule. MSW uses backend-shaped payloads
 * (audit schemas: hash-chained records, hand-built integrity dict).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuditPage } from "@/pages/AuditPage";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { ToastViewport } from "@/components/ui/ToastViewport";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const REC1 = {
  audit_id: "aud-1",
  timestamp: 1700000000,
  actor: "analyst",
  actor_role: "analyst",
  action: "approve",
  severity: "warning",
  subject_type: "document",
  subject_id: "d1",
  description: "Approved KYC circular",
  details: { ticket: "T-42", urgent: true },
  ip_address: "10.0.0.1",
  user_agent: "test-agent",
  source_module: "review",
  prev_hash: "prevhashvalue000000000000000000000000000000000000000001",
  record_hash: "recordhashvalue000000000000000000000000000000000000001",
  sequence: 5,
  metadata: {},
};
const REC2 = {
  audit_id: "aud-2",
  timestamp: 1700001000,
  actor: "system",
  actor_role: "",
  action: "login",
  severity: "info",
  subject_type: "user",
  subject_id: "u1",
  description: "login ok",
  details: {},
  source_module: "",
  prev_hash: "p2",
  record_hash: "h2",
  sequence: 6,
  metadata: {},
};
const EV1 = {
  evidence_id: "evd-1",
  record_id: "aud-1",
  kind: "document",
  title: "KYC circular PDF",
  description: "Source document snapshot",
  content: { pages: 12, sealed: true },
  content_hash: "contenthashvalue00000000000000000000000000000000001",
  collected_by: "analyst",
  collected_at: 1700000000,
  source_uri: "https://example.com/kyc.pdf",
  tags: ["kyc"],
};
const REP1 = {
  report_id: "rpt-1",
  title: "Q3 access review",
  description: "Quarterly review of access grants",
  kind: "internal_audit",
  status: "complete",
  regulator: "",
  period_start: 1699000000,
  period_end: 1700000000,
  generated_by: "analyst",
  generated_at: 1700001000,
  completed_at: 1700001100,
  sections: [
    {
      section_id: "sec-1", title: "Access grants", summary: "Two grants reviewed.",
      metrics: {}, evidence_refs: ["evd-1"], findings: ["Grant G-1 lacks expiry"],
      recommendations: ["Add expiry to G-1"], order: 0,
    },
  ],
  record_refs: ["aud-1"],
  evidence_refs: ["evd-1"],
  attestation: "Reviewed and attested.",
  metadata: {},
};

let recordHits: string[] = [];
let records: unknown[] = [REC1, REC2];
let integrityPayload: Record<string, unknown> = {
  intact: true, message: "chain verified", total: 2, valid: 2, invalid: 0,
  chain_length: 2, last_chain_hash: "headhashvalue00000000000000000000000001",
};
let evidenceHits: string[] = [];
let evidenceItems: unknown[] = [EV1];
let reportHits: string[] = [];
let reports: unknown[] = [REP1];
let generateHits: unknown[] = [];
let apiHits: string[] = [];

function track(url: string) {
  apiHits.push(new URL(url).pathname);
}

const server = setupServer(
  http.get("/api/v1/audit/integrity", async ({ request }) => {
    track(request.url);
    if ((integrityPayload as { __error?: boolean }).__error) {
      return HttpResponse.json({ detail: "down" }, { status: 500 });
    }
    return HttpResponse.json(integrityPayload);
  }),
  http.get("/api/v1/audit/stats", async ({ request }) => {
    track(request.url);
    return HttpResponse.json({
      total_records: 2, by_action: { approve: 1 }, by_severity: { warning: 1, info: 1 },
      by_actor: {}, by_module: {}, by_subject_type: {}, chain_length: 2,
      last_chain_hash: "head", chain_integrity: true, last_record_at: 1700001000,
      oldest_record_at: 1700000000,
    });
  }),
  http.get("/api/v1/audit/records", async ({ request }) => {
    track(request.url);
    const url = new URL(request.url);
    recordHits.push(url.search);
    return HttpResponse.json({ items: records, total: records.length, page: 1, page_size: 50, has_more: false });
  }),
  http.get("/api/v1/audit/records/:id", async ({ request, params }) => {
    track(request.url);
    const rec = (records as Record<string, unknown>[]).find((r) => r.audit_id === params.id);
    if (!rec) return HttpResponse.json({ detail: "record not found" }, { status: 404 });
    return HttpResponse.json(rec);
  }),
  http.get("/api/v1/audit/evidence", async ({ request }) => {
    track(request.url);
    const url = new URL(request.url);
    evidenceHits.push(url.search);
    const rid = url.searchParams.get("record_id");
    const items = rid ? (evidenceItems as Record<string, unknown>[]).filter((e) => e.record_id === rid) : evidenceItems;
    return HttpResponse.json(items);
  }),
  http.get("/api/v1/audit/evidence/:id", async ({ request, params }) => {
    track(request.url);
    const ev = (evidenceItems as Record<string, unknown>[]).find((e) => e.evidence_id === params.id);
    if (!ev) return HttpResponse.json({ detail: "evidence not found" }, { status: 404 });
    return HttpResponse.json(ev);
  }),
  http.get("/api/v1/audit/reports", async ({ request }) => {
    track(request.url);
    const url = new URL(request.url);
    reportHits.push(url.search);
    const kind = url.searchParams.get("kind");
    const items = kind ? (reports as Record<string, unknown>[]).filter((r) => r.kind === kind) : reports;
    return HttpResponse.json(items);
  }),
  http.post("/api/v1/audit/reports", async ({ request }) => {
    track(request.url);
    const body = (await request.json()) as Record<string, unknown>;
    generateHits.push(body);
    const created = { ...REP1, report_id: "rpt-9", title: body.title, status: "complete" };
    reports = [created, ...reports];
    return HttpResponse.json(created, { status: 201 });
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
  recordHits = [];
  records = [REC1, REC2];
  integrityPayload = {
    intact: true, message: "chain verified", total: 2, valid: 2, invalid: 0,
    chain_length: 2, last_chain_hash: "headhashvalue00000000000000000000000001",
  };
  evidenceHits = [];
  evidenceItems = [EV1];
  reportHits = [];
  reports = [REP1];
  generateHits = [];
  apiHits = [];
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderAudit() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/audit"]}>
            <AuditPage />
          </MemoryRouter>
          <ToastViewport />
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

async function goTab(label: string) {
  await userEvent.click(screen.getByRole("tab", { name: label }));
}

describe("records", () => {
  it("1+6+9+10+11. renders h1, real fields, subject, actor, no outcome column", async () => {
    renderAudit();
    expect(await screen.findByRole("heading", { level: 1, name: "Audit" })).toBeTruthy();
    expect(await screen.findByText("Approved KYC circular")).toBeTruthy();
    expect(screen.getByText("document:d1")).toBeTruthy();
    expect(screen.getByText("analyst")).toBeTruthy();
    expect(within(screen.getByRole("table")).getByText("warning")).toBeTruthy();
    expect(screen.getByText("5")).toBeTruthy();
    expect(screen.queryByText(/outcome/i)).toBeNull();
  });

  it("7+8. timestamps relative; chain order stated, never recent", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    expect(screen.queryByText("Invalid Date")).toBeNull();
    expect(screen.queryByText("1700000000")).toBeNull();
    expect(screen.getByText(/oldest first/)).toBeTruthy();
    expect(screen.queryByText(/recent/i)).toBeNull();
  });

  it("5. backend error is retryable", async () => {
    server.use(
      http.get("/api/v1/audit/records", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderAudit();
    expect(await screen.findByText("Audit records unavailable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("4. empty is distinct from failure and not a health claim", async () => {
    records = [];
    renderAudit();
    expect(await screen.findByText("No audit records")).toBeTruthy();
    expect(screen.getByText(/not an integrity verdict/)).toBeTruthy();
  });

  it("12+13+14. pagination sends page; filters send server params", async () => {
    const many = Array.from({ length: 50 }, (_, i) => ({ ...REC1, audit_id: `ax${i}`, description: `Event ax${i}` }));
    records = many;
    renderAudit();
    await screen.findByText("Event ax0");
    expect(screen.getByText("Page 1 · 50 shown")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(recordHits.some((h) => h.includes("page=2"))).toBe(true));
    fireEvent.change(screen.getByLabelText(/severity/i), { target: { value: "critical" } });
    await waitFor(() => expect(recordHits.some((h) => h.includes("severity=critical"))).toBe(true));
    fireEvent.change(screen.getByLabelText(/action/i), { target: { value: "login" } });
    await waitFor(() => expect(recordHits.some((h) => h.includes("action=login"))).toBe(true));
  });

  it("text search and after-date send server params", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    fireEvent.change(screen.getByLabelText(/text search/i), { target: { value: "kyc" } });
    await waitFor(() => expect(recordHits.some((h) => h.includes("text_query=kyc"))).toBe(true));
    fireEvent.change(screen.getByLabelText(/^after$/i), { target: { value: "2024-01-01T00:00" } });
    await waitFor(() => expect(recordHits.some((h) => h.includes("after="))).toBe(true));
  });

  it("17. totals come from stats, never from rendered rows", async () => {
    renderAudit();
    expect(await screen.findByText("Stored records")).toBeTruthy();
    expect(screen.getByText("Chain length")).toBeTruthy();
  });
});

describe("integrity", () => {
  it("19+21+25. intact renders counts, message, and head hash", async () => {
    renderAudit();
    expect(await screen.findByText("Audit-chain integrity check: intact.")).toBeTruthy();
    expect(screen.getByText(/2 record\(s\)/)).toBeTruthy();
    expect(screen.getByText(/chain verified/)).toBeTruthy();
    expect(screen.getByText(/Head hash/)).toBeTruthy();
  });

  it("18+20+30. compromised is a prominent failure with the backend reason", async () => {
    integrityPayload = {
      intact: false, message: "break at sequence=5 audit_id=aud-1", total: 2, valid: 0, invalid: 2,
      chain_length: 2, last_chain_hash: "head",
    };
    renderAudit();
    const banner = await screen.findByText("Audit-chain integrity check FAILED.");
    expect(banner).toBeTruthy();
    expect(screen.getByText(/break at sequence=5/)).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
    // Failure sits above the records, not buried.
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(banner.compareDocumentPosition(h1) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
  });

  it("22+48. unavailable check is distinct from compromised", async () => {
    integrityPayload = { __error: true };
    renderAudit();
    expect(await screen.findByText("Integrity status unavailable")).toBeTruthy();
    expect(screen.queryByText(/intact\./)).toBeNull();
    expect(screen.queryByText(/FAILED\./)).toBeNull();
    expect(screen.getByRole("button", { name: "Retry integrity check" })).toBeTruthy();
  });

  it("23+61. missing intact never renders healthy (fail-closed)", async () => {
    integrityPayload = { message: "no data", total: 0, valid: 0, invalid: 0, chain_length: 0, last_chain_hash: "" };
    renderAudit();
    expect(await screen.findByText("Audit-chain integrity check FAILED.")).toBeTruthy();
    expect(screen.queryByText(/intact\./)).toBeNull();
    expect(screen.queryByText(/Healthy/i)).toBeNull();
  });

  it("55. integrity status is announced with text, not color alone", async () => {
    renderAudit();
    const banner = await screen.findByText("Audit-chain integrity check: intact.");
    expect(banner.closest('[role="status"]')).toBeTruthy();
  });
});

describe("detail", () => {
  it("26+27+30+31. selection loads hashes, context, details, and evidence", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    await userEvent.click(screen.getByRole("button", { name: "Inspect record aud-1" }));
    expect(await screen.findByText("Record aud-1")).toBeTruthy();
    expect(screen.getByText(/SHA-256/)).toBeTruthy();
    expect(screen.getByText(/10\.0\.0\.1/)).toBeTruthy();
    expect(screen.getByText("T-42")).toBeTruthy();
    expect(await screen.findByText("KYC circular PDF")).toBeTruthy();
  });

  it("28+29. unknown record errors without substitution", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    server.use(
      http.get("/api/v1/audit/records/:id", async () => HttpResponse.json({ detail: "record not found" }, { status: 404 }))
    );
    await userEvent.click(screen.getByRole("button", { name: "Inspect record aud-1" }));
    expect(await screen.findByText("Record unavailable")).toBeTruthy();
  });

  it("36. hash copy control exposes the full value accessibly", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    await userEvent.click(screen.getByRole("button", { name: "Inspect record aud-1" }));
    await screen.findByText("Record aud-1");
    // Banner head-hash copy exists too: pick the record-hash control by value.
    const copies = screen.getAllByRole("button", { name: /copy full hash/i });
    const recCopy = copies.find((b) => (b.getAttribute("title") ?? "").includes("recordhashvalue"));
    expect(recCopy).toBeTruthy();
    expect(recCopy?.getAttribute("title")).toContain("recordhashvalue000000000000000000000000000000000000001");
  });

  it("58. keyboard record interaction via real buttons", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    const btn = screen.getByRole("button", { name: "Inspect record aud-1" });
    btn.focus();
    expect(document.activeElement).toBe(btn);
  });
});

describe("evidence", () => {
  it("32+33+36. rows, detail with verbatim hash, no invented excerpts", async () => {
    renderAudit();
    await goTab("Evidence");
    expect(await screen.findByText("KYC circular PDF")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Inspect evidence evd-1" }));
    expect(await screen.findByText("Source document snapshot")).toBeTruthy();
    const evCopies = screen.getAllByRole("button", { name: /copy full hash/i });
    const evCopy = evCopies.find((b) => (b.getAttribute("title") ?? "").includes("contenthashvalue"));
    expect(evCopy).toBeTruthy();
    expect(screen.getByRole("link", { name: /kyc\.pdf/ })).toHaveAttribute("href", "https://example.com/kyc.pdf");
    expect(screen.getByText("pages")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.queryByText(/excerpt/i)).toBeNull();
  });

  it("record_id filter narrows server-side; empty is explicit", async () => {
    renderAudit();
    await goTab("Evidence");
    await screen.findByText("KYC circular PDF");
    fireEvent.change(screen.getByLabelText(/filter evidence by record id/i), { target: { value: "aud-9" } });
    await waitFor(() => expect(evidenceHits.some((h) => h.includes("record_id=aud-9"))).toBe(true));
    expect(await screen.findByText("No evidence")).toBeTruthy();
  });

  it("34+50. evidence error is retryable", async () => {
    server.use(
      http.get("/api/v1/audit/evidence", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderAudit();
    await goTab("Evidence");
    expect(await screen.findByText("Evidence unavailable")).toBeTruthy();
  });

  it("evidence links back to its record across tabs", async () => {
    renderAudit();
    await goTab("Evidence");
    await screen.findByText("KYC circular PDF");
    await userEvent.click(screen.getByRole("button", { name: "Inspect evidence evd-1" }));
    await screen.findByText("Source document snapshot");
    await userEvent.click(screen.getByRole("button", { name: /inspect record aud-1/i }));
    expect(await screen.findByText("Record aud-1")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Records" }).getAttribute("aria-selected")).toBe("true");
  });
});

describe("reports", () => {
  it("38+39+40+41. list, sections, periods, and refs render", async () => {
    renderAudit();
    await goTab("Reports");
    expect(await screen.findByText("Q3 access review")).toBeTruthy();
    expect(screen.getByText("complete")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: /Q3 access review/ }));
    expect(await screen.findByText("Access grants")).toBeTruthy();
    expect(screen.getByText("Grant G-1 lacks expiry")).toBeTruthy();
    expect(screen.getByText("Add expiry to G-1")).toBeTruthy();
    expect(screen.getByText("Reviewed and attested.")).toBeTruthy();
  });

  it("report refs jump to the record and evidence tabs", async () => {
    renderAudit();
    await goTab("Reports");
    await screen.findByText("Q3 access review");
    await userEvent.click(screen.getByRole("button", { name: /Q3 access review/ }));
    await screen.findByText("Access grants");
    await userEvent.click(screen.getByRole("button", { name: "aud-1" }));
    expect(await screen.findByText("Record aud-1")).toBeTruthy();
  });

  it("kind filter is server-side", async () => {
    renderAudit();
    await goTab("Reports");
    await screen.findByText("Q3 access review");
    fireEvent.change(screen.getByLabelText(/filter reports by kind/i), { target: { value: "incident_summary" } });
    await waitFor(() => expect(reportHits.some((h) => h.includes("kind=incident_summary"))).toBe(true));
  });

  it("generation posts the real payload, selects the report, refreshes the list", async () => {
    renderAudit();
    await goTab("Reports");
    await screen.findByLabelText(/^title$/i);
    fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "Q4 review" } });
    await userEvent.click(screen.getByRole("button", { name: "Generate report" }));
    await waitFor(() => expect(generateHits.length).toBe(1));
    const body = generateHits[0] as Record<string, unknown>;
    expect(body.title).toBe("Q4 review");
    expect(body.kind).toBe("internal_audit");
    expect(await screen.findByText("Q4 review", { selector: "h3" })).toBeTruthy();
  });

  it("42. no export controls exist without backend support", async () => {
    renderAudit();
    await goTab("Reports");
    await screen.findByText("Q3 access review");
    expect(screen.queryByRole("button", { name: /export pdf/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /download/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /export csv/i })).toBeNull();
  });

  it("generation failure is retryable; short titles stay disabled", async () => {
    server.use(
      http.post("/api/v1/audit/reports", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderAudit();
    await goTab("Reports");
    await screen.findByLabelText(/^title$/i);
    fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "ab" } });
    expect((screen.getByRole("button", { name: "Generate report" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "abc" } });
    await userEvent.click(screen.getByRole("button", { name: "Generate report" }));
    expect(await screen.findByText("Report generation failed")).toBeTruthy();
  });
});

describe("cache", () => {
  it("44+46. filter changes refetch with new keys; audit traffic stays in-domain", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    const hitsBefore = recordHits.length;
    fireEvent.change(screen.getByLabelText(/severity/i), { target: { value: "error" } });
    await waitFor(() => expect(recordHits.length).toBeGreaterThan(hitsBefore));
    expect(apiHits.every((p) => p.startsWith("/api/v1/audit"))).toBe(true);
  });
});

describe("ux/a11y", () => {
  it("54+56+57. h1, table semantics, labelled filters", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    const table = screen.getByRole("table");
    expect(table.querySelector("caption")).toBeTruthy();
    expect(table.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(0);
    expect(screen.getByLabelText(/text search/i)).toBeTruthy();
  });

  it("59. errors use role=alert", async () => {
    server.use(
      http.get("/api/v1/audit/records", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderAudit();
    expect(await screen.findByText("Audit records unavailable")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});

describe("trust", () => {
  it("61+62+63+65+66. no fake trust signals, counts, or hidden failures", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    for (const pat of [/healthy/i, /tamper-proof/i, /100% integrity/i, /verified truth/i, /encrypted/i, /legally valid/i, /forensically/i]) {
      expect(screen.queryByText(pat)).toBeNull();
    }
    expect(screen.queryByText(/page \d+ of \d+/i)).toBeNull();
  });

  it("64. epochs never render raw; no invalid dates", async () => {
    renderAudit();
    await screen.findByText("Approved KYC circular");
    expect(screen.queryByText("1700000000")).toBeNull();
    expect(screen.queryByText("Invalid Date")).toBeNull();
  });
});
