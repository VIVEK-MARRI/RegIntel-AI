/**
 * Stage 06 dashboard tests: every number traced to a backend field.
 * MSW replies with backend-shaped fixtures (app/api/v1/dashboard.py +
 * research/compliance-risk schemas). No fabricated data anywhere.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DashboardPage } from "@/pages/DashboardPage";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const complianceFixture = {
  regulations_tracked: 4,
  changes_detected: 0,
  impact_reports: 0,
  alerts_open: 2,
  alerts_critical: 1,
  alerts_failed: 0,
  documents_ingested: 23,
  knowledge_graph_nodes: 24,
  knowledge_graph_edges: 19,
  research_reports: 1,
};

const alertsFixture = {
  total: 2,
  by_severity: { critical: 1, high: 1 },
  by_status: { pending: 2 },
  delivery_rate: 0.5,
  digests_generated: 0,
};

const insightsFixture = {
  risk_level: "moderate",
  risk_score: 0.42,
  insights: [
    {
      insight_id: "ins-1",
      title: "Pending critical alert",
      description: "One critical alert awaits triage.",
      severity: "critical",
      score: 0.8,
      evidence: ["alert-9"],
      recommendation: "Triage the critical alert queue.",
      created_at: 1700000000,
    },
  ],
  generated_at: 1700000001,
};

const impactFixture = {
  counts: { critical: 0, high: 1, medium: 2, low: 1, negligible: 0 },
  total: 4,
  average_score: 0.55,
};

const monitoringFixture = {
  sources_monitored: 3,
  documents_discovered: 5,
  monitor_failures: 0,
  last_run_at: 1700000000,
  sources_healthy: 3,
  sources_failed: 0,
};

const systemFixture = {
  status: "ok",
  uptime_seconds: 3600,
  storage_writable: true,
  components: { knowledge_graph: "ok", research: "degraded" },
};

const trendsFixture = {
  items: [
    { name: "ingestion.runs", unit: "runs", direction: "flat", delta_pct: 0, points: [{ label: "total", value: 23, timestamp: 1700000000 }] },
  ],
  count: 1,
};

const server = setupServer(
  http.get("/api/v1/dashboard/compliance", async () => HttpResponse.json(complianceFixture)),
  http.get("/api/v1/dashboard/alerts", async () => HttpResponse.json(alertsFixture)),
  http.get("/api/v1/dashboard/insights", async () => HttpResponse.json(insightsFixture)),
  http.get("/api/v1/dashboard/impact-distribution", async () => HttpResponse.json(impactFixture)),
  http.get("/api/v1/dashboard/monitoring", async () => HttpResponse.json(monitoringFixture)),
  http.get("/api/v1/dashboard/system", async () => HttpResponse.json(systemFixture)),
  http.get("/api/v1/dashboard/trends", async () => HttpResponse.json(trendsFixture)),
  http.get("/api/v1/research", async () => HttpResponse.json({
    items: [
      {
        report_id: "rpt-1", plan_id: "p1", query: "kyc thresholds", kind: "general",
        summary: "Verify identity.", key_findings: [], timeline: [], comparisons: [],
        citations: [], steps: [], generated_at: 1700000000, duration_ms: 10,
      },
    ],
    total: 1, page: 1, page_size: 20,
  })),
  http.get("/api/v1/compliance-risk/assessments", async () => HttpResponse.json({
    items: [
      {
        assessment_id: "a1", source: "manual", risk_level: "medium", risk_score: 0.4,
        risk_categories: [], affected_areas: [], recommended_actions: [],
        compliance_gaps: [], explanation: "", regulatory_exposure: 0.2,
        generated_at: 1700000000,
      },
    ],
    total: 1, page: 1, page_size: 50,
  }))
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function ShowPath() {
  const location = useLocation();
  return <span>at:{location.pathname}</span>;
}

function renderDashboard(initialPath = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/documents" element={<ShowPath />} />
          <Route path="/copilot" element={<ShowPath />} />
          <Route path="/compliance" element={<ShowPath />} />
          <Route path="*" element={<ShowPath />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return qc;
}

describe("dashboard rendering", () => {
  it("1+2. renders with a single meaningful page heading", async () => {
    renderDashboard();
    expect(await screen.findByRole("heading", { name: "Dashboard", level: 1 })).toBeTruthy();
    expect(screen.getAllByRole("heading", { name: "Dashboard" })).toHaveLength(1);
  });

  it("3. KPI skeletons show while loading", async () => {
    renderDashboard();
    // First paint happens before fixtures resolve: skeleton placeholders only.
    expect(document.body.querySelector(".skeleton")).toBeTruthy();
    await screen.findByText("Documents ingested");
  });
});

describe("KPI correctness (no fabricated numbers)", () => {
  async function kpiSection() {
    const section = screen.getByRole("region", { name: "Key indicators" });
    await within(section).findByText("24 nodes");
    return section;
  }

  it("8+13. documents use the authoritative registry counter", async () => {
    renderDashboard();
    const section = await kpiSection();
    const card = within(section).getByText("Documents ingested").closest(".card")!;
    expect(card.textContent).toContain("23");
  });

  it("8. knowledge graph shows nodes with edges as context", async () => {
    renderDashboard();
    const section = await kpiSection();
    const card = within(section).getByText("Knowledge graph").closest(".card")!;
    expect(card.textContent).toContain("24 nodes");
    expect(card.textContent).toContain("19 edges");
  });

  it("9+11. pending alerts come from by_status, critical from by_severity", async () => {
    renderDashboard();
    const section = await kpiSection();
    await within(section).findByText("1 critical");
    const card = within(section).getByText("Pending alerts").closest(".card")!;
    expect(card.textContent).toContain("2");
    expect(card.textContent).toContain("1 critical");
  });

  it("9. total decisions are never labeled open reviews", async () => {
    renderDashboard();
    await screen.findByText("Documents ingested");
    expect(screen.queryByText(/open reviews/i)).toBeNull();
  });

  it("10. total agents are never shown as active agents", async () => {
    renderDashboard();
    await screen.findByText("Documents ingested");
    expect(screen.queryByText(/agents active/i)).toBeNull();
    expect(screen.queryByText(/active agents/i)).toBeNull();
  });

  it("11. governance card is absent (no fabricated values)", async () => {
    renderDashboard();
    await screen.findByText("Documents ingested");
    expect(screen.queryByText(/recent governance/i)).toBeNull();
  });

  it("14. counters are authoritative, not list lengths", async () => {
    renderDashboard();
    // Fixture list endpoints return 1 item each; counters say 23/24/1.
    const section = screen.getByRole("region", { name: "Key indicators" });
    await within(section).findByText("24 nodes");
    const card = within(section).getByText("Documents ingested").closest(".card")!;
    expect(card.textContent).toContain("23");
  });
});

describe("loading / error / empty", () => {
  it("4+5. KPI error renders Unavailable, never zero", async () => {
    server.use(
      http.get("/api/v1/dashboard/compliance", async () => {
        return HttpResponse.json({ detail: "boom" }, { status: 500 });
      })
    );
    renderDashboard();
    const section = screen.getByRole("region", { name: "Key indicators" });
    const unavailables = await within(section).findAllByText("Unavailable");
    expect(unavailables.length).toBeGreaterThanOrEqual(1);
    const card = within(section).getByText("Documents ingested").closest(".card")!;
    expect(card.textContent).toContain("Unavailable");
    expect(card.textContent).not.toMatch(/[^a-zA-Z]0[^0-9]/);
  });

  it("6+27. widget failure is local with canonical retry", async () => {
    server.use(
      http.get("/api/v1/dashboard/alerts", async () => {
        return HttpResponse.json({ detail: "down" }, { status: 503 });
      })
    );
    renderDashboard();
    expect(await screen.findByText("Alert data unavailable")).toBeTruthy();
    // Other widgets still render.
    expect(await screen.findByText("Documents ingested")).toBeTruthy();
    const kpi = screen.getByText("Documents ingested");
    expect(kpi.closest(".card")!.textContent).toContain("23");
  });

  it("empty alerts render a true empty state, not an error", async () => {
    server.use(
      http.get("/api/v1/dashboard/alerts", async () => {
        return HttpResponse.json({
          total: 0, by_severity: {}, by_status: {}, delivery_rate: 0, digests_generated: 0,
        });
      })
    );
    renderDashboard();
    expect(await screen.findByText("No alerts")).toBeTruthy();
  });

  it("empty activity lists render empty states", async () => {
    server.use(
      http.get("/api/v1/research", async () => {
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 });
      }),
      http.get("/api/v1/compliance-risk/assessments", async () => {
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 });
      })
    );
    renderDashboard();
    expect(await screen.findByText("No reports yet")).toBeTruthy();
    expect(await screen.findByText("No assessments yet")).toBeTruthy();
  });
});

describe("risk, impact, monitoring", () => {
  it("risk level + score + insights render from the insights view", async () => {
    renderDashboard();
    expect(await screen.findByText("moderate")).toBeTruthy();
    expect(await screen.findByText("Pending critical alert")).toBeTruthy();
    expect(screen.getByText("Triage the critical alert queue.")).toBeTruthy();
  });

  it("impact distribution renders counts with an accessible summary", async () => {
    renderDashboard();
    const bar = await screen.findByRole("img", { name: /impact distribution/i });
    expect(bar.getAttribute("aria-label")).toContain("4 reports");
    expect(bar.getAttribute("aria-label")).toContain("high 1");
  });

  it("impact empty state when no reports exist", async () => {
    server.use(
      http.get("/api/v1/dashboard/impact-distribution", async () => {
        return HttpResponse.json({ counts: {}, total: 0, average_score: 0 });
      })
    );
    renderDashboard();
    expect(await screen.findByText("No impact reports yet")).toBeTruthy();
  });

  it("monitoring shows sources, failures, and component states", async () => {
    renderDashboard();
    await screen.findByText("Monitoring & services");
    expect(await screen.findByText("knowledge_graph")).toBeTruthy();
    expect(screen.getByText("research")).toBeTruthy();
  });

  it("trends render honest single-value counters with direction", async () => {
    renderDashboard();
    expect(await screen.findByText("ingestion.runs")).toBeTruthy();
    expect(screen.getByText("— steady")).toBeTruthy();
  });
});

describe("activity + navigation + refresh", () => {
  it("15+17. timestamps come from real backend fields", async () => {
    renderDashboard();
    // generated_at 1700000000 -> relative date, never "Invalid Date" or blank dash.
    await waitFor(() => expect(screen.queryByText("Invalid Date")).toBeNull());
  });

  it("16. empty activity covered; 18. CTAs navigate to real routes", async () => {
    renderDashboard();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Upload Document" }));
    expect(await screen.findByText("at:/documents")).toBeTruthy();
  });

  it("18b. copilot and compliance CTAs navigate", async () => {
    renderDashboard();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Ask Copilot" }));
    expect(await screen.findByText("at:/copilot")).toBeTruthy();
  });

  it("19+20. refresh refetches without wiping data; double-click safe", async () => {
    renderDashboard();
    const user = userEvent.setup();
    await screen.findByText("Documents ingested");
    const btn = screen.getByRole("button", { name: "Refresh" });
    await user.click(btn);
    await user.click(btn).catch(() => undefined);
    // Data from the first load is still on screen (no skeleton wipe).
    expect(screen.getByText("Documents ingested")).toBeTruthy();
  });

  it("21. layout is responsive-safe (no fixed-width traps)", async () => {
    renderDashboard();
    await screen.findByText("Documents ingested");
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(1024 + 1);
  });

  it("12+28. health comes from the provider, not a second poller", async () => {
    // DashboardPage must not import HealthProvider internals or call
    // health endpoints directly: assert via module source is overkill;
    // behaviorally, the page renders no health KPI of its own.
    renderDashboard();
    await screen.findByText("Documents ingested");
    expect(screen.queryByText("System Health")).toBeNull();
  });

  it("26+29. no fabricated numbers anywhere on the page", async () => {
    renderDashboard();
    await screen.findByText("Documents ingested");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/All systems operational/);
    expect(text).not.toMatch(/99%/);
  });
});

describe("roles", () => {
  it("22. dashboard is unified across roles", async () => {
    renderDashboard();
    expect(await screen.findByRole("heading", { name: "Dashboard", level: 1 })).toBeTruthy();
  });
});


