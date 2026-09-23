/**
 * Stage 10 research tests: synchronous run lifecycle, report history,
 * deep-linked report detail (steps/findings/citations/timeline/comparisons),
 * cache behavior, and the no-fabrication rule (no confidence, no progress %,
 * no fake sources). MSW replies with backend-shaped payloads (research schemas).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ResearchPage } from "@/pages/ResearchPage";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { ToastViewport } from "@/components/ui/ToastViewport";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const stepFixture = (id: string, overrides: Record<string, unknown> = {}) => ({
  step_id: id,
  step_type: "retrieve",
  description: `Retrieve for ${id}`,
  status: "completed",
  inputs: {},
  outputs: {},
  error: "",
  started_at: 1700000000,
  finished_at: 1700000005,
  duration_ms: 5000,
  ...overrides,
});

const citFixture = (id: string, overrides: Record<string, unknown> = {}) => ({
  citation_id: id,
  source: "ingestion",
  title: `Source ${id}`,
  reference: `RBI/2024/${id}`,
  url: null,
  score: 0.9,
  metadata: {},
  ...overrides,
});

const R1 = {
  report_id: "r1",
  plan_id: "plan-1",
  query: "KYC updation rules 2024",
  kind: "general",
  summary: "Research report for KYC: 1 citation drawn from 2 plan steps.",
  key_findings: ["Referenced: Source c1"],
  timeline: [],
  comparisons: [],
  citations: [citFixture("c1", { url: "https://example.com/kyc" })],
  steps: [stepFixture("s1"), stepFixture("s2", { step_type: "summarize", description: "Summarize findings" })],
  generated_at: 1700000000,
  duration_ms: 4200,
  metadata: {},
};

const R2 = {
  report_id: "r2",
  plan_id: "plan-2",
  query: "Compare FEMA vs RBI thresholds",
  kind: "comparative",
  summary: "Comparative analysis: 0 references compared across 1 step.",
  key_findings: ["No citations found in this run."],
  timeline: [],
  comparisons: [{ items_compared: 3, step: "Compare thresholds" }],
  citations: [],
  steps: [stepFixture("s3", { step_type: "compare", description: "Compare thresholds" })],
  generated_at: 1700001000,
  duration_ms: 2500,
  metadata: {},
};

const R3 = {
  report_id: "r3",
  plan_id: "plan-3",
  query: "KYC circular timeline",
  kind: "timeline",
  summary: "Timeline analysis: 0 sources consulted across 1 step.",
  key_findings: [],
  timeline: [
    { title: "Circular issued", date: "2024-03-01", id: "e1" },
    { title: "Enforcement begins", date: 1700000000, id: "e2" },
  ],
  comparisons: [],
  citations: [],
  steps: [stepFixture("s4")],
  generated_at: 1700002000,
  duration_ms: 1800,
  metadata: {},
};

const REPORTS: Record<string, unknown> = { r1: R1, r2: R2, r3: R3 };

let listHits: string[] = [];
let listItems: unknown[] = [R1, R2];
let runHits: unknown[] = [];
let runDelayMs = 0;

const server = setupServer(
  http.get("/api/v1/research/stats", async () => {
    return HttpResponse.json({
      total_reports: 2,
      plans_generated: 2,
      steps_total: 3,
      average_steps_per_plan: 1.5,
      average_duration_ms: 3350,
      by_kind: { general: 1, comparative: 1 },
      last_report_at: 1700001000,
    });
  }),
  http.get("/api/v1/research", async ({ request }) => {
    const url = new URL(request.url);
    listHits.push(url.search);
    return HttpResponse.json({ items: listItems, total: listItems.length, page: 1, page_size: 20, has_more: false });
  }),
  http.get("/api/v1/research/:id", async ({ params }) => {
    const r = REPORTS[params.id as string];
    if (!r) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    return HttpResponse.json(r);
  }),
  http.post("/api/v1/research/run", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    runHits.push(body);
    if (runDelayMs > 0) await new Promise((r) => setTimeout(r, runDelayMs));
    // The backend persists the report: later GET /research/:id must resolve it.
    const created = { ...R1, report_id: "r9", query: body.query };
    REPORTS["r9"] = created;
    return HttpResponse.json(created);
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
  listHits = [];
  listItems = [R1, R2];
  delete REPORTS["r9"];
  runHits = [];
  runDelayMs = 0;
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderResearch(initialRoute = "/research") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[initialRoute]}>
            <Routes>
              <Route path="/research" element={<ResearchPage />} />
              <Route path="/research/:reportId" element={<ResearchPage />} />
            </Routes>
          </MemoryRouter>
          <ToastViewport />
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

async function fillQuestion(q: string) {
  await screen.findByLabelText(/research question/i);
  fireEvent.change(screen.getByLabelText(/research question/i), { target: { value: q } });
}

describe("request", () => {
  it("1. page renders with h1, labelled input, kind and steps controls", async () => {
    renderResearch();
    expect(await screen.findByRole("heading", { level: 1, name: "Research" })).toBeTruthy();
    expect(screen.getByLabelText(/research question/i)).toBeTruthy();
    expect(screen.getByLabelText(/^kind/i)).toBeTruthy();
    expect(screen.getByLabelText(/max steps/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run research" })).toBeTruthy();
  });

  it("2. run is disabled until the question reaches 3 characters", async () => {
    renderResearch();
    const btn = await screen.findByRole("button", { name: "Run research" });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    await fillQuestion("ab");
    expect((screen.getByRole("button", { name: "Run research" }) as HTMLButtonElement).disabled).toBe(true);
    await fillQuestion("abc");
    expect((screen.getByRole("button", { name: "Run research" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("3+4. submit sends the real request payload and navigates to the report", async () => {
    renderResearch();
    await fillQuestion("KYC updation rules 2024");
    fireEvent.change(screen.getByLabelText(/^kind/i), { target: { value: "comparative" } });
    fireEvent.change(screen.getByLabelText(/max steps/i), { target: { value: "5" } });
    await userEvent.click(screen.getByRole("button", { name: "Run research" }));
    await waitFor(() => expect(runHits.length).toBe(1));
    expect(runHits[0]).toMatchObject({ query: "KYC updation rules 2024", kind: "comparative", max_steps: 5 });
    // Navigated to the REAL report id from the response, detail loaded.
    expect(await screen.findByText("KYC updation rules 2024", { selector: "h2" })).toBeTruthy();
  });

  it("5. duplicate submission is prevented while a run is pending", async () => {
    runDelayMs = 400;
    renderResearch();
    await fillQuestion("duplicate guard question");
    const btn = screen.getByRole("button", { name: "Run research" });
    await userEvent.click(btn);
    await userEvent.click(btn);
    await waitFor(() => expect(screen.queryByText("Research is running…")).toBeTruthy());
    await waitFor(() => expect(runHits.length).toBe(1), { timeout: 3000 });
    expect(runHits.length).toBe(1);
  });

  it("21. no fake progress: pending state shows no percentages", async () => {
    runDelayMs = 400;
    renderResearch();
    await fillQuestion("progress honesty question");
    await userEvent.click(screen.getByRole("button", { name: "Run research" }));
    await screen.findByText("Research is running…");
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.queryByText(/streaming/i)).toBeNull();
  });

  it("18. run failure shows a retryable error, retry resends once", async () => {
    server.use(
      http.post("/api/v1/research/run", async () => HttpResponse.json({ detail: "boom" }, { status: 500 }))
    );
    renderResearch();
    await fillQuestion("failing question here");
    await userEvent.click(screen.getByRole("button", { name: "Run research" }));
    expect(await screen.findByText("Research run failed")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
    server.use(
      http.post("/api/v1/research/run", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        runHits.push(body);
        const created = { ...R1, report_id: "r9", query: body.query };
        REPORTS["r9"] = created;
        return HttpResponse.json(created);
      })
    );
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(runHits.length).toBe(1));
  });
});

describe("list", () => {
  it("6+7. loading then real rows with kind, counts, timestamps", async () => {
    renderResearch();
    expect(await screen.findByText("KYC updation rules 2024")).toBeTruthy();
    expect(screen.getByText("Compare FEMA vs RBI thresholds")).toBeTruthy();
    expect(screen.getByText("2 step(s) · 1 finding(s) · 1 citation(s)")).toBeTruthy();
    expect(screen.queryByText("Invalid Date")).toBeNull();
  });

  it("8. empty library is distinct from failure", async () => {
    listItems = [];
    renderResearch();
    expect(await screen.findByText("No reports yet")).toBeTruthy();
  });

  it("9. list failure shows retryable error", async () => {
    server.use(
      http.get("/api/v1/research", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderResearch();
    expect(await screen.findByText("Reports unavailable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("10. kind filter is server-side; next page sends page=2", async () => {
    const many = Array.from({ length: 20 }, (_, i) => ({ ...R1, report_id: `rx${i}`, query: `Report rx${i}` }));
    listItems = many;
    renderResearch();
    await screen.findByText("Report rx0");
    fireEvent.change(screen.getByLabelText(/filter reports by kind/i), { target: { value: "general" } });
    await waitFor(() => expect(listHits.some((h) => h.includes("kind=general"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(listHits.some((h) => h.includes("page=2"))).toBe(true));
  });

  it("stats render from /stats; stats failure is isolated", async () => {
    renderResearch();
    expect(await screen.findByText("Stored reports")).toBeTruthy();
    expect(await screen.findByText("KYC updation rules 2024")).toBeTruthy();
    server.use(
      http.get("/api/v1/research/stats", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    const second = renderResearch();
    expect(await screen.findByText("Research statistics unavailable")).toBeTruthy();
    second.unmount();
  });
});

describe("run lifecycle", () => {
  it("14+17. synchronous success seeds detail and lands on the report", async () => {
    renderResearch();
    await fillQuestion("KYC updation rules 2024");
    await userEvent.click(screen.getByRole("button", { name: "Run research" }));
    // Report sections render from the response without a second click.
    expect(await screen.findByText("Steps (2)")).toBeTruthy();
    expect(screen.getByText("Key findings (1)")).toBeTruthy();
    expect(screen.getByText("Sources & citations (1)")).toBeTruthy();
  });

  it("37. completing a run refreshes the list with the new report", async () => {
    renderResearch();
    await fillQuestion("brand new question here");
    await userEvent.click(screen.getByRole("button", { name: "Run research" }));
    await screen.findByText("Steps (2)");
    listItems = [{ ...R1, report_id: "r9", query: "brand new question here" }, R1, R2];
    await userEvent.click(screen.getByRole("button", { name: "Back to reports" }));
    expect(await screen.findByText("brand new question here")).toBeTruthy();
  });

  it("run-again is explicit: it fills the form, it does not rerun silently", async () => {
    renderResearch("/research/r1");
    expect(await screen.findByText("KYC updation rules 2024", { selector: "h2" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Run again with this question" }));
    expect(runHits.length).toBe(0);
    expect((screen.getByLabelText(/research question/i) as HTMLTextAreaElement).value).toBe(
      "KYC updation rules 2024"
    );
  });
});

describe("deep link", () => {
  it("22+23+28. report route loads that exact report", async () => {
    renderResearch("/research/r2");
    expect(await screen.findByText("Compare FEMA vs RBI thresholds", { selector: "h2" })).toBeTruthy();
    expect(screen.getByText("Comparisons (1)")).toBeTruthy();
    // Timeline section belongs to timeline-kind reports only.
    expect(screen.queryByText(/Timeline \(/)).toBeNull();
  });

  it("24+26+40. unknown id errors without falling back to another report", async () => {
    renderResearch("/research/nope");
    expect(await screen.findByText("Report unavailable")).toBeTruthy();
    expect(screen.queryByText("KYC updation rules 2024")).toBeNull();
    expect(screen.queryByText("Compare FEMA vs RBI thresholds")).toBeNull();
  });

  it("27. back navigation returns to the list", async () => {
    renderResearch("/research/r1");
    await screen.findByText("KYC updation rules 2024", { selector: "h2" });
    await userEvent.click(screen.getByRole("button", { name: "Back to reports" }));
    expect(await screen.findByText("Compare FEMA vs RBI thresholds")).toBeTruthy();
  });
});

describe("report", () => {
  it("30+31+32+33. steps, findings, citations, summary render from data", async () => {
    renderResearch("/research/r1");
    await screen.findByText("KYC updation rules 2024", { selector: "h2" });
    expect(screen.getByText("Retrieve for s1")).toBeTruthy();
    expect(screen.getAllByText("completed").length).toBe(2);
    expect(screen.getAllByText(/took 5\.0s/).length).toBe(2);
    expect(screen.getByText("Referenced: Source c1")).toBeTruthy();
    expect(screen.getByText("Source c1")).toBeTruthy();
    expect(screen.getByText("RBI/2024/c1")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open reference: Source c1" })).toHaveAttribute(
      "href",
      "https://example.com/kyc"
    );
    expect(screen.getByText(/Two citations|1 citation drawn/)).toBeTruthy();
    expect(screen.getByText("Completed in 4.2s")).toBeTruthy();
  });

  it("failed step shows its backend error text", async () => {
    // Exact report path: a ":id" pattern here would also match /stats and
    // poison the overview query with report-shaped data.
    server.use(
      http.get("/api/v1/research/r1", async () =>
        HttpResponse.json({
          ...R1,
          steps: [stepFixture("sx", { status: "failed", error: "LLM timeout" })],
        })
      )
    );
    renderResearch("/research/r1");
    expect(await screen.findByText("LLM timeout")).toBeTruthy();
    expect(screen.getByText("failed")).toBeTruthy();
  });

  it("timeline entries render for timeline-kind reports", async () => {
    renderResearch("/research/r3");
    expect(await screen.findByText("Timeline (2)")).toBeTruthy();
    expect(screen.getByText("Circular issued")).toBeTruthy();
    expect(screen.getByText(/2024-03-01/)).toBeTruthy();
    expect(screen.getByText("Enforcement begins")).toBeTruthy();
  });

  it("34+35. confidence is never fabricated", async () => {
    renderResearch("/research/r1");
    await screen.findByText("KYC updation rules 2024", { selector: "h2" });
    expect(screen.queryByText(/confidence/i)).toBeNull();
    expect(screen.queryByText(/reliability/i)).toBeNull();
  });

  it("36+42+43+44. malformed and empty collections render safely", async () => {
    server.use(
      http.get("/api/v1/research/r1", async () =>
        HttpResponse.json({ ...R1, steps: undefined, key_findings: [], citations: undefined })
      )
    );
    renderResearch("/research/r1");
    expect(await screen.findByText("Steps (0)")).toBeTruthy();
    expect(screen.getByText("No steps recorded for this report.")).toBeTruthy();
    expect(screen.getByText(/contains no findings/)).toBeTruthy();
    expect(screen.getByText(/No citations in this report/)).toBeTruthy();
  });

  it("backend finding text renders verbatim; empty results are not failure", async () => {
    renderResearch("/research/r2");
    await screen.findByText("Comparisons (1)");
    // The backend's own empty-run sentence renders as content, not as an error.
    expect(screen.getByText("No citations found in this run.")).toBeTruthy();
    expect(screen.queryByText("Report unavailable")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("ux/a11y", () => {
  it("45+46+47. h1, labelled controls, text status", async () => {
    renderResearch("/research/r1");
    expect(await screen.findByRole("heading", { level: 1, name: "Research" })).toBeTruthy();
    expect(await screen.findByRole("heading", { level: 2, name: "KYC updation rules 2024" })).toBeTruthy();
    for (const name of ["Summary", "Steps (2)", "Key findings (1)", "Sources & citations (1)"]) {
      expect(screen.getByRole("heading", { name })).toBeTruthy();
    }
  });

  it("48. list rows are keyboard-operable buttons", async () => {
    renderResearch();
    await screen.findByText("KYC updation rules 2024");
    const btn = screen.getByRole("button", { name: /KYC updation rules 2024/ });
    btn.focus();
    expect(document.activeElement).toBe(btn);
  });

  it("article landmark scopes the report for assistive tech", async () => {
    renderResearch("/research/r1");
    await screen.findByText("KYC updation rules 2024", { selector: "h2" });
    expect(screen.getByRole("article")).toBeTruthy();
    const svg = screen.queryByRole("img");
    expect(svg).toBeNull();
  });
});
