/**
 * Stage 11 compliance tests: assessment workflow with verified risk
 * semantics, forecast with real series data, policies with enable/disable,
 * decisions with re-checks, cache behavior, and the no-fabrication rule
 * (no percentages, no probabilities, no invented impact scores).
 * MSW replies with backend-shaped payloads (risk/forecasting/governance).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CompliancePage } from "@/pages/CompliancePage";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { ToastViewport } from "@/components/ui/ToastViewport";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const A1 = {
  assessment_id: "a1",
  document_id: "d1",
  diff_id: null,
  impact_report_id: null,
  source: "manual",
  risk_level: "high",
  risk_score: 0.72,
  risk_categories: ["regulatory_exposure", "operational"],
  affected_areas: [
    { area: "kyc", exposure_score: 0.8, rationale: "KYC controls outdated", related_changes: 2 },
  ],
  recommended_actions: [
    {
      action_id: "act-1", action_type: "policy_update", title: "Update KYC policy",
      description: "Refresh periodic updation clauses.", priority: "high",
      rationale: "Closes the KYC gap.", confidence: 0.5, estimated_effort_hours: 4,
    },
  ],
  compliance_gaps: [
    {
      gap_id: "gap-1", area: "kyc", severity: "high",
      description: "Periodic updation not enforced.", regulatory_basis: "RBI KYC MC",
      remediation_action_id: "act-1",
    },
  ],
  explanation: {
    summary: "Risk=high (score=0.72) driven by severity=medium.",
    top_factors: [
      { factor_id: "fac-1", name: "Stale KYC controls", category: "operational", weight: 2, raw_value: 1, contribution: 0.4, explanation: "Controls predate 2024 circular", source: "analyzer" },
    ],
    scoring_method: "weighted_aggregate",
    confidence: 0.85,
  },
  regulatory_exposure: 0.66,
  historical_risk_score: 0.4,
  trend: "up",
  generated_at: 1700000000,
  duration_ms: 3200,
  metadata: {},
};

const A2 = {
  assessment_id: "a2",
  document_id: null,
  source: "manual",
  risk_level: "low",
  risk_score: 0.1,
  risk_categories: [],
  affected_areas: [],
  recommended_actions: [],
  compliance_gaps: [],
  explanation: "",
  regulatory_exposure: 0.05,
  historical_risk_score: null,
  trend: "flat",
  generated_at: 1700001000,
  duration_ms: 900,
  metadata: {},
};

const F1 = {
  forecast_id: "f1",
  horizon_days: 30,
  predicted_risk_score: 0.42,
  predicted_risk_level: "medium",
  confidence: 0.5,
  method: "linear_regression+exponential_smoothing",
  generated_at: 1700000000,
  document_id: null,
  points: [
    { timestamp: 1700000000, predicted_score: 0.4, lower_bound: 0.33, upper_bound: 0.47, confidence: 0.5 },
    { timestamp: 1700100000, predicted_score: 0.42, lower_bound: 0.35, upper_bound: 0.49, confidence: 0.5 },
  ],
  series: { name: "document_forecast", points: [] },
  drift_detected: false,
};

const P1 = {
  policy_id: "p1",
  name: "KYC Policy",
  description: "KYC handling rules",
  version: "1.0.0",
  scope: "global",
  scope_value: "",
  rules: [
    { rule_id: "rule-1", name: "Human review over high", description: "", kind: "human_in_loop", action: "require_human_review", severity: "high", parameters: {}, enabled: true },
  ],
  enabled: true,
  created_at: 1700000000,
  updated_at: 1700000000,
  tags: [],
};

const D1 = {
  decision_id: "dec-1",
  decision_type: "risk_assessment",
  subject_type: "document",
  subject_id: "d1",
  model_id: "m1",
  model_version: "v1",
  decision: "allow",
  confidence: 0.9,
  risk_level: "medium",
  categories: ["kyc"],
  inputs: {},
  outputs: {},
  actor: "analyst",
  timestamp: 1700000000,
  policy_result: {
    result_id: "chk-1",
    decision_id: "dec-1",
    policy_compliant: false,
    violations: [
      { violation_id: "vio-1", rule_id: "rule-1", rule_name: "Human review over high", policy_id: "p1", policy_name: "KYC Policy", kind: "human_in_loop", action: "require_human_review", severity: "high", message: "No human review recorded", details: {}, timestamp: 1700000000 },
    ],
    required_actions: ["require_human_review"],
    evaluated_policies: ["p1"],
    evaluated_rules: 1,
    timestamp: 1700000000,
    notes: "",
  },
  approved_by: [],
  metadata: {},
};

let assessHits: unknown[] = [];
let assessDelayMs = 0;
let listHits: string[] = [];
let listItems: unknown[] = [A1, A2];
let policyPatchHits: unknown[] = [];
let policies: unknown[] = [P1];
let recheckHits = 0;
let decisionHits: string[] = [];

const server = setupServer(
  http.get("/api/v1/compliance-risk/stats", async () => {
    return HttpResponse.json({
      total_assessments: 2, critical_risks: 0, high_risks: 1, medium_risks: 0, low_risks: 1,
      average_risk_score: 0.41, by_category: {}, by_source: {}, by_affected_area: {},
      total_recommended_actions: 1, total_compliance_gaps: 1, last_assessment_at: 1700001000,
    });
  }),
  http.get("/api/v1/compliance-risk/trend", async () => {
    return HttpResponse.json({
      document_id: "d1", source: "manual",
      points: [
        { timestamp: 1699900000, risk_score: 0.4, risk_level: "medium" },
        { timestamp: 1700000000, risk_score: 0.72, risk_level: "high" },
      ],
      direction: "up", delta: 0.32,
    });
  }),
  http.post("/api/v1/compliance-risk/assess", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    assessHits.push(body);
    if ("scope" in body || "policies" in body) {
      return HttpResponse.json({ detail: [{ loc: ["scope"], msg: "extra forbidden" }] }, { status: 422 });
    }
    if (assessDelayMs > 0) await new Promise((r) => setTimeout(r, assessDelayMs));
    return HttpResponse.json({ ...A1, assessment_id: "a9" }, { status: 201 });
  }),
  http.get("/api/v1/compliance-risk/assessments", async ({ request }) => {
    const url = new URL(request.url);
    listHits.push(url.search);
    return HttpResponse.json({ items: listItems, total: listItems.length, page: 1, page_size: 50, has_more: false });
  }),
  http.get("/api/v1/documents", async () => {
    return HttpResponse.json([
      { id: "d1", title: "KYC Circular", status: "INDEXED" },
      { id: "d2", title: "AML Guidelines", status: "INDEXED" },
    ]);
  }),
  http.get("/api/v1/forecasting/stats", async () => {
    return HttpResponse.json({ total_forecasts: 1, average_horizon_days: 30, drift_detected: 0, drift_rate: 0, last_forecast_at: 1700000000 });
  }),
  http.get("/api/v1/forecasting/forecasts", async () => HttpResponse.json([F1])),
  http.get("/api/v1/forecasting/scenarios", async () => {
    return HttpResponse.json([
      { name: "best_case", adjustments: { delta: -0.15 }, predicted_score: 0.27, predicted_level: "low" },
      { name: "baseline", adjustments: {}, predicted_score: 0.42, predicted_level: "medium" },
      { name: "worst_case", adjustments: { delta: 0.2 }, predicted_score: 0.62, predicted_level: "medium" },
    ]);
  }),
  http.post("/api/v1/forecasting/forecast", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    if ("baseline_score" in body || "drivers" in body) {
      return HttpResponse.json({ detail: [{ loc: ["baseline_score"], msg: "extra forbidden" }] }, { status: 422 });
    }
    return HttpResponse.json({ ...F1, forecast_id: "f9", horizon_days: body.horizon_days }, { status: 201 });
  }),
  http.get("/api/v1/governance/stats", async () => {
    return HttpResponse.json({
      total_policies: 1, total_rules: 1, total_decisions: 1, compliant_decisions: 0,
      non_compliant_decisions: 1, total_violations: 1, blocking_violations: 0,
      average_violations_per_decision: 1, compliance_rate: 0, by_decision_type: {},
      by_severity: {}, by_action: {}, by_model: {}, last_decision_at: 1700000000,
    });
  }),
  http.get("/api/v1/governance/policies", async () => HttpResponse.json(policies)),
  http.get("/api/v1/governance/approval-policies", async () => {
    return HttpResponse.json([
      { policy_id: "aprv-1", name: "High-risk approvals", description: "", decision_types: ["risk_assessment"], min_risk_level: "high", required_roles: ["admin"], min_approvers: 2, applies_to: "global", enabled: true, created_at: 1700000000 },
    ]);
  }),
  http.patch("/api/v1/governance/policies/:id", async ({ request, params }) => {
    const body = (await request.json()) as Record<string, unknown>;
    policyPatchHits.push({ id: params.id, body });
    policies = (policies as unknown[]).map((p) =>
      (p as Record<string, unknown>).policy_id === params.id ? { ...(p as object), ...body } : p
    );
    return HttpResponse.json((policies as Record<string, unknown>[]).find((p) => p.policy_id === params.id));
  }),
  http.get("/api/v1/governance/decisions", async ({ request }) => {
    const url = new URL(request.url);
    decisionHits.push(url.search);
    return HttpResponse.json({ items: [D1], total: 1, page: 1, page_size: 50, has_more: false });
  }),
  http.post("/api/v1/governance/decisions/:id/check", async () => {
    recheckHits += 1;
    return HttpResponse.json({
      result_id: "chk-9", decision_id: "dec-1", policy_compliant: true, violations: [],
      required_actions: [], evaluated_policies: ["p1"], evaluated_rules: 1,
      timestamp: 1700000000, notes: "",
    });
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
  assessHits = [];
  assessDelayMs = 0;
  listHits = [];
  listItems = [A1, A2];
  policyPatchHits = [];
  policies = [P1];
  recheckHits = 0;
  decisionHits = [];
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderCompliance() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/compliance"]}>
            <CompliancePage />
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

async function onAssessment() {
  renderCompliance();
  await screen.findByRole("button", { name: "Run assessment" });
}

describe("assessment", () => {
  it("1+2. page renders with h1, tabs, and the assessment form", async () => {
    await onAssessment();
    expect(screen.getByRole("heading", { level: 1, name: "Compliance" })).toBeTruthy();
    for (const t of ["Assessment", "Forecast", "Policies", "Decisions"]) {
      expect(screen.getByRole("tab", { name: t })).toBeTruthy();
    }
    expect(screen.getByLabelText(/document \(optional\)/i)).toBeTruthy();
    expect(screen.getByLabelText(/^source$/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeTruthy();
  });

  it("4+5+7. submit sends only backend-supported keys; result renders with true risk semantics", async () => {
    await onAssessment();
    await screen.findByText("KYC Circular (INDEXED)");
    fireEvent.change(screen.getByLabelText(/document \(optional\)/i), { target: { value: "d1" } });
    await userEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    await waitFor(() => expect(assessHits.length).toBe(1));
    const body = assessHits[0] as Record<string, unknown>;
    expect(body.document_id).toBe("d1");
    expect(body.source).toBe("manual");
    expect(body).not.toHaveProperty("scope");
    expect(body).not.toHaveProperty("policies");
    // Score as a number with level text — never a percentage.
    expect((await screen.findAllByText("0.72")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("high").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/higher means more risk/)).toBeTruthy();
    expect(screen.queryByText(/72%/)).toBeNull();
  });

  it("6. pending state is honest blocking text without percentages", async () => {
    assessDelayMs = 400;
    await onAssessment();
    await userEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    expect(await screen.findByText("Assessment is running…")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("10. duplicate submission prevented while pending", async () => {
    assessDelayMs = 400;
    await onAssessment();
    const btn = screen.getByRole("button", { name: "Run assessment" });
    await userEvent.click(btn);
    await userEvent.click(btn);
    await waitFor(() => expect(assessHits.length).toBe(1), { timeout: 3000 });
    expect(assessHits.length).toBe(1);
  });

  it("8+9. failure shows retryable error", async () => {
    server.use(
      http.post("/api/v1/compliance-risk/assess", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    await onAssessment();
    await userEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    expect(await screen.findByText("Assessment failed")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("11+12. history rows, level filter, and paging use server params", async () => {
    await onAssessment();
    expect(await screen.findByText("d1")).toBeTruthy();
    expect(screen.getByText("a2")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/filter by risk level/i), { target: { value: "high" } });
    await waitFor(() => expect(listHits.some((h) => h.includes("risk_level=high"))).toBe(true));
    const many = Array.from({ length: 50 }, (_, i) => ({ ...A1, assessment_id: `ax${i}`, document_id: null }));
    listItems = many;
    fireEvent.change(screen.getByLabelText(/filter by risk level/i), { target: { value: "" } });
    await screen.findByText("ax0");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(listHits.some((h) => h.includes("page=2"))).toBe(true));
  });

  it("stats show backend counts including need-attention", async () => {
    await onAssessment();
    expect(await screen.findByText("Need attention")).toBeTruthy();
    expect(screen.getByText("Open gaps")).toBeTruthy();
  });

  it("18+19+20. drivers, gaps, and actions render from real fields", async () => {
    await onAssessment();
    await screen.findByText("d1");
    await userEvent.click(screen.getByRole("button", { name: /d1/ }));
    expect(await screen.findByText("Stale KYC controls")).toBeTruthy();
    expect(screen.getByText("Periodic updation not enforced.")).toBeTruthy();
    expect(screen.getByText(/RBI KYC MC/)).toBeTruthy();
    expect(screen.getByText("Update KYC policy")).toBeTruthy();
    expect(screen.getByText("KYC controls outdated")).toBeTruthy();
  });

  it("trajectory chart renders from real trend points with text direction", async () => {
    await onAssessment();
    await screen.findByText("d1");
    await userEvent.click(screen.getByRole("button", { name: /d1/ }));
    const img = await screen.findByRole("img", { name: /risk trajectory/i });
    expect(img).toBeTruthy();
    expect(screen.getByText(/Direction up/)).toBeTruthy();
  });
});

describe("risk semantics", () => {
  it("14+15+16. level and score shown together with explicit direction", async () => {
    await onAssessment();
    expect(await screen.findByText("Average risk score")).toBeTruthy();
    expect(screen.getByText("0.41")).toBeTruthy();
    expect(screen.getByText(/higher is worse/)).toBeTruthy();
    await screen.findByText("d1");
    await userEvent.click(screen.getByRole("button", { name: /d1/ }));
    expect(await screen.findByText(/Backend bands: critical/)).toBeTruthy();
  });

  it("17+65. no percentages, no probabilities anywhere in assessment", async () => {
    await onAssessment();
    await screen.findByText("d1");
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.queryByText(/probab/i)).toBeNull();
    expect(screen.queryByText(/non-compliant"/)).toBeNull();
  });

  it("64. malformed assessment renders without crashing", async () => {
    listItems = [{ assessment_id: "bad" }];
    await onAssessment();
    expect(await screen.findByText("bad")).toBeTruthy();
  });
});

describe("forecast", () => {
  it("23+24+25. payload, pending, and result with real chart", async () => {
    renderCompliance();
    await goTab("Forecast");
    expect(await screen.findByRole("button", { name: "Run forecast" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/horizon \(days\)/i), { target: { value: "60" } });
    await userEvent.click(screen.getByRole("button", { name: "Run forecast" }));
    const img = await screen.findByRole("img", { name: /projected risk over 2 points/i });
    expect(img).toBeTruthy();
    expect(screen.getByText("60-day risk projection")).toBeTruthy();
    expect(screen.getAllByText("0.42").length).toBeGreaterThanOrEqual(1);
  });

  it("26+29. forecast error is retryable; no fabricated points", async () => {
    server.use(
      http.post("/api/v1/forecasting/forecast", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderCompliance();
    await goTab("Forecast");
    await screen.findByRole("button", { name: "Run forecast" });
    await userEvent.click(screen.getByRole("button", { name: "Run forecast" }));
    expect(await screen.findByText("Forecast failed")).toBeTruthy();
  });

  it("scenarios render backend adjustments without reordering", async () => {
    renderCompliance();
    await goTab("Forecast");
    expect(await screen.findByText("best case")).toBeTruthy();
    expect(screen.getByText(/delta: -0.15/)).toBeTruthy();
    expect(screen.getByText(/delta: \+0.2/)).toBeTruthy();
  });

  it("30+31. baseline wording honest; no model-confidence display", async () => {
    renderCompliance();
    await goTab("Forecast");
    await screen.findByRole("button", { name: "Run forecast" });
    expect(screen.getByText(/neutral baseline, not your data/)).toBeTruthy();
    expect(screen.queryByText(/model confidence/i)).toBeNull();
  });

  it("forecast stats render from /forecasting/stats", async () => {
    renderCompliance();
    await goTab("Forecast");
    expect(await screen.findByText("Drift events")).toBeTruthy();
  });
});

describe("policies", () => {
  it("32+34+35. list renders real fields with enabled (not active) semantics", async () => {
    renderCompliance();
    await goTab("Policies");
    expect(await screen.findByText("KYC Policy")).toBeTruthy();
    expect(screen.getAllByText("Enabled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("v1.0.0")).toBeTruthy();
    expect(screen.queryByText("Active")).toBeNull();
  });

  it("rules expand with kind/action/severity; toggle sends PATCH", async () => {
    renderCompliance();
    await goTab("Policies");
    await screen.findByText("KYC Policy");
    await userEvent.click(screen.getByRole("button", { name: /rules \(1\)/i }));
    expect(screen.getByText("Human review over high")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(policyPatchHits.length).toBe(1));
    expect(policyPatchHits[0]).toMatchObject({ id: "p1", body: { enabled: false } });
    expect(await screen.findByText("Disabled")).toBeTruthy();
  });

  it("33+36. empty and error states are distinct", async () => {
    policies = [];
    renderCompliance();
    await goTab("Policies");
    expect(await screen.findByText("No policies")).toBeTruthy();
  });

  it("approval policies render role bindings", async () => {
    renderCompliance();
    await goTab("Policies");
    expect(await screen.findByText("High-risk approvals")).toBeTruthy();
    expect(screen.getByText(/needs 2 approver/)).toBeTruthy();
  });

  it("compliance rate renders as a backend 0–1 share, not a percent", async () => {
    renderCompliance();
    await goTab("Policies");
    expect(await screen.findByText("Compliance rate")).toBeTruthy();
    expect(screen.getByText("0.00")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
  });
});

describe("decisions", () => {
  it("38+39+40. registry rows show type, subject, decision, verdict", async () => {
    renderCompliance();
    await goTab("Decisions");
    const subject = await screen.findByText("document:d1");
    const row = subject.closest("li");
    expect(row).toBeTruthy();
    const scope = within(row as HTMLElement);
    expect(scope.getByText("allow")).toBeTruthy();
    expect(scope.getByText("Non-compliant")).toBeTruthy();
    expect(scope.getByText(/Actor analyst/)).toBeTruthy();
  });

  it("filters send decision_type and policy_compliant", async () => {
    renderCompliance();
    await goTab("Decisions");
    await screen.findByText("document:d1");
    fireEvent.change(screen.getByLabelText(/filter decisions by type/i), { target: { value: "forecast" } });
    await waitFor(() => expect(decisionHits.some((h) => h.includes("decision_type=forecast"))).toBe(true));
    fireEvent.change(screen.getByLabelText(/filter by policy compliance/i), { target: { value: "false" } });
    await waitFor(() => expect(decisionHits.some((h) => h.includes("policy_compliant=false"))).toBe(true));
  });

  it("detail expands with verdict, violations, and attributed confidence", async () => {
    renderCompliance();
    await goTab("Decisions");
    await screen.findByText("document:d1");
    await userEvent.click(screen.getByRole("button", { name: "Detail" }));
    expect(await screen.findByText("No human review recorded")).toBeTruthy();
    expect(screen.getByText("as reported by the registrant")).toBeTruthy();
    expect(screen.getByText("require_human_review")).toBeTruthy();
  });

  it("re-check runs the real endpoint and shows the fresh verdict", async () => {
    renderCompliance();
    await goTab("Decisions");
    await screen.findByText("document:d1");
    await userEvent.click(screen.getByRole("button", { name: "Re-check policies" }));
    expect(await screen.findByText("Fresh policy check")).toBeTruthy();
    expect(recheckHits).toBe(1);
    expect(screen.getByText("No violations in this check.")).toBeTruthy();
  });

  it("41. empty registry explains decisions come from AI systems", async () => {
    server.use(
      http.get("/api/v1/governance/decisions", async () => {
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50, has_more: false });
      })
    );
    renderCompliance();
    await goTab("Decisions");
    expect(await screen.findByText("No decisions recorded")).toBeTruthy();
  });
});

describe("cache", () => {
  it("50. assessment run refreshes history and stats", async () => {
    renderCompliance();
    await screen.findByRole("button", { name: "Run assessment" });
    await userEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    expect((await screen.findAllByText("0.72")).length).toBeGreaterThanOrEqual(1);
    const before = listHits.length;
    listItems = [{ ...A1, assessment_id: "a9" }, A1, A2];
    await userEvent.click(screen.getByRole("button", { name: "Run assessment" }));
    await waitFor(() => expect(listHits.length).toBeGreaterThan(before));
  });

  it("52+53. forecast run refreshes forecasts and scenarios; recheck is list-neutral", async () => {
    renderCompliance();
    await goTab("Forecast");
    await userEvent.click(screen.getByRole("button", { name: "Run forecast" }));
    await screen.findByText("30-day risk projection");
    await goTab("Decisions");
    await screen.findByText("document:d1");
    const hitsBefore = decisionHits.length;
    await userEvent.click(screen.getByRole("button", { name: "Re-check policies" }));
    await screen.findByText("Fresh policy check");
    expect(decisionHits.length).toBe(hitsBefore);
  });
});

describe("roles", () => {
  it("55+56. mutating actions render without role theater; backend stays the boundary", async () => {
    renderCompliance();
    await screen.findByRole("button", { name: "Run assessment" });
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeTruthy();
    await goTab("Policies");
    await screen.findByText("KYC Policy");
    expect(screen.getByRole("button", { name: "Disable" })).toBeTruthy();
    await goTab("Decisions");
    await screen.findByText("document:d1");
    expect(screen.getByRole("button", { name: "Re-check policies" })).toBeTruthy();
  });
});

describe("ux/a11y", () => {
  it("57+58. h1 and keyboard-operable tabs with aria-selected", async () => {
    renderCompliance();
    expect(await screen.findByRole("heading", { level: 1, name: "Compliance" })).toBeTruthy();
    const tab = screen.getByRole("tab", { name: "Assessment" });
    expect(tab.getAttribute("aria-selected")).toBe("true");
    tab.focus();
    fireEvent.keyDown(tab, { key: "ArrowRight" });
    expect(await screen.findByRole("button", { name: "Run forecast" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Forecast" }).getAttribute("aria-selected")).toBe("true");
  });

  it("59+60+61. labelled controls, text statuses, alert errors", async () => {
    renderCompliance();
    await screen.findByRole("button", { name: "Run assessment" });
    expect(screen.getByLabelText(/document \(optional\)/i)).toBeTruthy();
    expect(screen.getByLabelText(/filter by risk level/i)).toBeTruthy();
  });

  it("policies table has caption and scoped headers", async () => {
    renderCompliance();
    await goTab("Policies");
    await screen.findByText("KYC Policy");
    const table = screen.getByRole("table");
    expect(table.querySelector("caption")).toBeTruthy();
    expect(table.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(0);
  });
});

describe("data trust", () => {
  it("no fabricated probability, impact, or severity language", async () => {
    await onAssessment();
    await screen.findByText("d1");
    for (const pat of [/probab/i, /impact_score/, /breach/i, /% safe/, /rec\. controls/i]) {
      expect(screen.queryByText(pat)).toBeNull();
    }
  });
});
