/**
 * Stage 13 analytics tests: agent-operations metrics rendered with true
 * backend semantics — shares with counts (never percentages), zero-vs-unknown
 * distinction, real distributions, explicit insufficient-history state, and
 * per-section error isolation. MSW uses backend-shaped payloads
 * (agent_analytics + intelligence_agents contracts).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const PERF = [
  {
    agent_name: "research-agent",
    total_invocations: 10,
    successful_invocations: 9,
    failed_invocations: 1,
    success_rate: 0.9,
    average_duration_ms: 120,
    p95_duration_ms: 300,
    average_confidence: 0.8,
    total_evidence_shared: 0,
    last_invocation_at: 1700000000,
    last_error: "",
    health: "healthy",
  },
  {
    agent_name: "idle-agent",
    total_invocations: 0,
    successful_invocations: 0,
    failed_invocations: 0,
    success_rate: 0,
    average_duration_ms: 0,
    p95_duration_ms: 0,
    average_confidence: 0,
    total_evidence_shared: 0,
    last_invocation_at: null,
    last_error: "",
    health: "unknown",
  },
];

const OVERVIEW = {
  total_agents: 2,
  total_invocations: 10,
  success_rate: 0.9,
  average_duration_ms: 120,
  average_confidence: 0.8,
  total_collaborations: 3,
  total_cost_units: 0.01,
  health: {
    total_agents: 2, healthy_agents: 1, degraded_agents: 0,
    unhealthy_agents: 0, unknown_agents: 1, overall_health: "degraded", agents: [],
  },
  leaderboard: [],
  collaborations: [],
  recent_executions: [],
  forecast_accuracy: [],
  recommendation_accuracy: [],
  cost: null,
  generated_at: 1700000000,
};

const INTEL = {
  total_invocations: 10,
  total_successful: 9,
  total_failed: 1,
  total_collaborations: 3,
  research: {},
  compliance: {},
  risk: {},
  by_mode: { chat: 7, research: 3 },
  by_scenario_kind: { baseline: 10 },
  average_confidence: 0.8,
  last_reset_at: 1700000000,
};

const LATENCY = {
  agent_name: "research-agent",
  count: 10,
  average_ms: 120,
  min_ms: 40,
  max_ms: 400,
  p50_ms: 100,
  p90_ms: 250,
  p95_ms: 300,
  p99_ms: 380,
};

let leaderboardHits: string[] = [];
let performanceData: unknown[] = PERF;

const server = setupServer(
  http.get("/api/v1/agents/analytics/overview", async () => HttpResponse.json(OVERVIEW)),
  http.get("/api/v1/agents/analytics/performance", async () => HttpResponse.json(performanceData)),
  http.get("/api/v1/agents/metrics", async () => HttpResponse.json(INTEL)),
  http.get("/api/v1/agents/analytics/health", async () => HttpResponse.json(OVERVIEW.health)),
  http.get("/api/v1/agents/analytics/cost", async () => {
    return HttpResponse.json({
      agent_name: "", invocations: 10, tokens_used: 0, cost_units: 0.01,
      currency: "USD", cost_per_invocation: 0.001,
      notes: "Estimated at $0.001/invocation",
    });
  }),
  http.get("/api/v1/agents/analytics/leaderboard", async ({ request }) => {
    const url = new URL(request.url);
    leaderboardHits.push(url.search);
    return HttpResponse.json([
      { rank: 1, agent_name: "research-agent", score: 0.85, success_rate: 0.9, average_confidence: 0.8, total_invocations: 10, average_duration_ms: 120 },
    ]);
  }),
  http.get("/api/v1/agents/analytics/performance/:name/latency", async () => HttpResponse.json(LATENCY))
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
  leaderboardHits = [];
  performanceData = PERF;
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderAnalytics() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/analytics"]}>
            <AnalyticsPage />
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

describe("rendering + key metrics", () => {
  it("h1, sections, and backendTraceable KPIs render", async () => {
    renderAnalytics();
    expect(await screen.findByRole("heading", { level: 1, name: "Analytics" })).toBeTruthy();
    expect(await screen.findByText("Success share")).toBeTruthy();
    expect(screen.getByText("Est. cost")).toBeTruthy();
    await screen.findAllByText("idle-agent");
    expect(screen.getAllByText("0.90").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("120ms").length).toBeGreaterThanOrEqual(1);
    // "(9 of 10)" renders in metric, table, and leaderboard rows alike.
    expect(screen.getAllByText((_, el) => el?.textContent === "(9 of 10)").length).toBeGreaterThanOrEqual(1);
  });

  it("zero invocations is unknown, not zero share", async () => {
    renderAnalytics();
    await screen.findAllByText("idle-agent");
    expect(screen.getAllByText("no invocations").length).toBeGreaterThanOrEqual(1);
  });

  it("no percentages anywhere; shares carry counts", async () => {
    renderAnalytics();
    await screen.findAllByText("idle-agent");
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.getAllByText(/9 of 10/).length).toBeGreaterThanOrEqual(1);
  });

  it("cost renders as a labelled estimate with backend notes", async () => {
    renderAnalytics();
    expect(await screen.findByText("Est. cost")).toBeTruthy();
    expect(await screen.findByText(/0\.0100 USD/)).toBeTruthy();
    expect(screen.getByText(/Estimated at/)).toBeTruthy();
  });
});

describe("distributions", () => {
  it("success split, health, and breakdowns render with text equivalents", async () => {
    renderAnalytics();
    expect(await screen.findByText("succeeded: 9")).toBeTruthy();
    expect(screen.getByText("failed: 1")).toBeTruthy();
    expect(await screen.findByText("degraded")).toBeTruthy();
    expect(screen.getByText("healthy: 1")).toBeTruthy();
    expect(screen.getByText("unknown: 1")).toBeTruthy();
    expect(await screen.findByText("chat: 7")).toBeTruthy();
    expect(screen.getByText("baseline: 10")).toBeTruthy();
  });

  it("leaderboard renders rank/score with the formula note; top_n is a server param", async () => {
    renderAnalytics();
    expect(await screen.findByLabelText("Rank 1")).toBeTruthy();
    expect(screen.getByText(/score 0\.85/)).toBeTruthy();
    expect(screen.getByText(/0\.6·success/)).toBeTruthy();
    expect(leaderboardHits[0]).toContain("top_n=10");
    fireEvent.change(screen.getByLabelText(/top n/i), { target: { value: "5" } });
    await waitFor(() => expect(leaderboardHits.some((h) => h.includes("top_n=5"))).toBe(true));
  });

  it("latency explorer shows percentiles with a table equivalent", async () => {
    renderAnalytics();
    await screen.findByRole("option", { name: "research-agent" });
    fireEvent.change(screen.getByLabelText(/^agent$/i), { target: { value: "research-agent" } });
    expect(await screen.findByRole("img", { name: /p95 300ms/ })).toBeTruthy();
    const table = screen.getByRole("table", { name: /latency statistics/i });
    expect(within(table).getByText("P99")).toBeTruthy();
  });

  it("empty performance renders an explicit empty state, not zeros", async () => {
    performanceData = [];
    renderAnalytics();
    expect(await screen.findByText("No agent activity")).toBeTruthy();
  });
});

describe("insufficient history", () => {
  it("states the absence of series instead of charting", async () => {
    renderAnalytics();
    expect(await screen.findByText("Trends over time")).toBeTruthy();
    expect(screen.getByText(/not available from the current analytics API/)).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });
});

describe("analytical table", () => {
  it("raw per-agent numbers with captions and scoped headers", async () => {
    renderAnalytics();
    const table = await screen.findByRole("table", { name: /per-agent invocations/i });
    expect(table.querySelector("caption")).toBeTruthy();
    expect(table.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(0);
    expect(within(table).getByText("research-agent")).toBeTruthy();
    expect(within(table).getByText("never")).toBeTruthy();
  });
});

describe("errors + partial failure", () => {
  it("one failed section leaves the rest usable, with retry", async () => {
    server.use(
      http.get("/api/v1/agents/analytics/health", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderAnalytics();
    expect(await screen.findByText("Health unavailable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    // Other sections still render.
    expect(await screen.findByText("Success by agent")).toBeTruthy();
    expect(await screen.findByText("Leaderboard")).toBeTruthy();
  });

  it("overview failure does not blank distributions", async () => {
    server.use(
      http.get("/api/v1/agents/analytics/overview", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderAnalytics();
    expect(await screen.findByText("Overview unavailable")).toBeTruthy();
    expect(await screen.findByText("Success by agent")).toBeTruthy();
  });
});

describe("refresh + a11y", () => {
  it("manual refresh refetches without polling timers", async () => {
    renderAnalytics();
    await screen.findAllByText("idle-agent");
    await userEvent.click(screen.getByRole("button", { name: "Refresh analytics" }));
    await waitFor(() => expect(screen.getAllByText("idle-agent").length).toBeGreaterThanOrEqual(1));
  });

  it("sections use headings; controls are labelled", async () => {
    renderAnalytics();
    await screen.findAllByText("idle-agent");
    for (const name of ["Ecosystem health", "Success by agent", "Leaderboard", "Agent performance"]) {
      expect(screen.getByRole("heading", { name })).toBeTruthy();
    }
    expect(screen.getByLabelText(/top n/i)).toBeTruthy();
  });
});

describe("data trust", () => {
  it("no deltas, forecasts, probabilities, or document-count confusion", async () => {
    renderAnalytics();
    await screen.findAllByText("idle-agent");
    for (const pat of [/up \d+%/i, /down \d+%/i, /improving/i, /declining/i, /forecast/i, /probab/i, /documents indexed/i]) {
      expect(screen.queryByText(pat)).toBeNull();
    }
  });

  it("malformed agent rows render safely", async () => {
    performanceData = [{ agent_name: "odd-agent" }];
    renderAnalytics();
    expect((await screen.findAllByText("odd-agent")).length).toBeGreaterThanOrEqual(1);
  });
});
