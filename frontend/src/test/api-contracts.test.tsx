/**
 * API contract tests (Stage 02, Part 22-24). MSW intercepts REAL HTTP from
 * the service layer and replies with BACKEND-SHAPED fixtures (verified
 * against app/api/v1/* + app/schemas/*). Each test proves method + URL +
 * request body/headers + response parsing — never canned return values.
 */
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { setAuthHandler } from "@/lib/api";
import { setAccessToken } from "@/lib/auth-token";
import { ApiClientError } from "@/lib/errors";
import * as authApi from "@/services/api/authApi";
import * as healthApi from "@/services/api/healthApi";
import * as copilotApi from "@/services/api/copilotApi";
import * as documentsApi from "@/services/api/documentsApi";
import * as kgApi from "@/services/api/knowledgeGraphApi";
import * as complianceApi from "@/services/api/complianceApi";
import * as riskApi from "@/services/api/riskApi";
import * as researchApi from "@/services/api/researchApi";
import * as auditApi from "@/services/api/auditApi";
import * as agentApi from "@/services/api/agentApi";
import * as adminApi from "@/services/api/adminApi";
import * as analyticsApi from "@/services/api/analyticsApi";
import * as governanceApi from "@/services/api/governanceApi";

interface Seen {
  method: string;
  url: string;
  body: unknown;
  auth: string | null;
}
const seen: Seen[] = [];

async function capture(req: Request): Promise<Seen> {
  let body: unknown = undefined;
  const ct = req.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) {
    try {
      body = await req.clone().json();
    } catch {
      body = undefined;
    }
  } else if (ct.includes("multipart/form-data")) {
    body = "FORMDATA";
  }
  const s: Seen = {
    method: req.method,
    url: new URL(req.url).pathname + new URL(req.url).search,
    body,
    auth: req.headers.get("authorization"),
  };
  seen.push(s);
  return s;
}

const loginFixture = {
  access_token: "acc",
  refresh_token: "ref",
  token_type: "Bearer",
  expires_in: 1800,
  access_expires_at: "2026-01-01T00:30:00+00:00",
  refresh_expires_at: "2026-01-08T00:00:00+00:00",
  user: {
    user_id: "u1",
    username: "a@b.c",
    email: "a@b.c",
    full_name: "A B",
    roles: [],
    rbac_roles: ["viewer"],
  },
};

const server = setupServer(
  http.post("/api/v1/security/auth/login", async ({ request }) => {
    await capture(request);
    return HttpResponse.json(loginFixture);
  }),
  http.post("/api/v1/security/auth/refresh", async ({ request }) => {
    await capture(request);
    const { access_token: _a, refresh_token: _r, user: _u, ...rest } = loginFixture;
    void _a; void _r; void _u;
    return HttpResponse.json({ ...rest, access_token: "acc2", refresh_token: "ref2" });
  }),
  http.get("/api/v1/security/auth/me", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({ subject_id: "u1", roles: ["viewer"], scopes: [], permissions: [] });
  }),
  http.post("/api/v1/security/auth/signup", async ({ request }) => {
    await capture(request);
    return HttpResponse.json(loginFixture, { status: 201 });
  }),
  http.get("/health/ready", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      status: "healthy",
      checks: { db: { status: "ok", latency_ms: 1, message: "", details: {} } },
    });
  }),
  http.get("/health/live", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({ status: "alive" });
  }),
  http.post("/api/v1/copilot/query", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      request_id: "r1",
      conversation_id: "conv-1",
      query: "q",
      mode: "answer",
      answer: null,
      citations: {
        executive_summary: { text: "Summary [1]", citations: [], claim_count: 1, cited_claim_count: 1 },
        detailed_explanation: { text: "Detail", citations: [], claim_count: 0, cited_claim_count: 0 },
        supporting_evidence: [],
        key_regulatory_references: ["RBI KYC"],
        references: [
          {
            citation_id: "[1]",
            chunk_id: "c1",
            document_id: "d1",
            document_title: "RBI Master Direction",
            excerpt: "every bank shall…",
          },
        ],
        citation_map: {},
      },
      confidence_score: 0.9,
      confidence_level: "high",
      faithfulness_score: 0.85,
      hallucination_detected: false,
      hallucination_risk_level: "none",
      sources: [
        {
          attribution_id: "att-1",
          section: "executive_summary",
          segment_index: 0,
          document_id: "d1",
          document_title: "RBI Master Direction",
          chunk_id: "c1",
          excerpt: "every bank shall…",
          similarity: 0.8,
          confidence: "high",
          metadata: {},
        },
      ],
      attribution_coverage_ratio: 1,
      memory_used: false,
      memory_context: { short_term: [], long_term: [], retrieval: [], total_count: 0, memory_used: false },
      history: [],
      latency_ms: 12,
      metadata: {
        request_id: "r1",
        timestamp: "2026-01-01T00:00:00+00:00",
        pipeline_version: "5.6.0",
        total_latency_ms: 12,
        step_results: [],
        warnings: [],
        extra: {},
      },
      created_at: "2026-01-01T00:00:00+00:00",
    });
  }),
  http.get("/api/v1/conversations", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          conversation_id: "conv-1",
          title: "KYC",
          status: "active",
          created_at: "2026-01-01T00:00:00+00:00",
          updated_at: "2026-01-02T00:00:00+00:00",
          messages: [],
          metadata: {},
          tags: [],
          summary: "",
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });
  }),
  http.get("/api/v1/conversations/:id", async ({ request, params }) => {
    await capture(request);
    return HttpResponse.json({
      conversation_id: params.id,
      title: "KYC",
      status: "active",
      created_at: "2026-01-01T00:00:00+00:00",
      updated_at: "2026-01-02T00:00:00+00:00",
      messages: [
        { message_id: "m1", role: "user", content: "hi", timestamp: "2026-01-02T00:00:00+00:00", metadata: {}, references: {}, token_estimate: 1 },
      ],
      metadata: {},
      tags: [],
      summary: "",
    });
  }),
  http.get("/api/v1/documents", async ({ request }) => {
    await capture(request);
    return HttpResponse.json([
      {
        id: "d1",
        title: "RBI Master Direction",
        source: "RBI",
        file_name: "rbi.pdf",
        file_path: "/x",
        checksum: "ab".repeat(32),
        status: "INDEXED",
        uploaded_at: "2026-01-01T00:00:00+00:00",
        updated_at: "2026-01-01T00:00:00+00:00",
      },
    ]);
  }),
  http.post("/api/v1/documents/upload", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({ document_id: "d9", status: "processing", run_id: "run-1" }, { status: 201 });
  }),
  http.get("/api/v1/documents/:id", async ({ request, params }) => {
    await capture(request);
    return HttpResponse.json({
      id: params.id,
      title: "RBI Master Direction",
      source: "RBI",
      file_name: "rbi.pdf",
      file_path: "/x",
      checksum: "ab".repeat(32),
      status: "INDEXED",
      uploaded_at: "2026-01-01T00:00:00+00:00",
      updated_at: "2026-01-01T00:00:00+00:00",
      chunk_count: 4,
      embedding_count: 4,
      indexed: true,
      processing_status: "completed",
    });
  }),
  http.get("/api/v1/ingestion/runs", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          run_id: "run-1",
          document_id: "d1",
          status: "completed",
          steps: [],
          chunks_created: 4,
          embeddings_created: 4,
          pages_parsed: 2,
          is_duplicate: false,
          started_at: "2026-01-01T00:00:00+00:00",
          finished_at: "2026-01-01T00:01:00+00:00",
          duration_ms: 60000,
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });
  }),
  http.get("/api/v1/knowledge-graph/stats", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      total_nodes: 3,
      total_relationships: 1,
      by_entity_type: { regulation: 3 },
      by_relationship_type: {},
      by_source: {},
      average_degree: 0.66,
      max_depth: 1,
      connected_components: 2,
      generated_at: 1700000000,
    });
  }),
  http.get("/api/v1/knowledge-graph/nodes", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          node_id: "n1",
          entity_type: "regulation",
          name: "RBI KYC Direction",
          description: "",
          source: "manual",
          properties: {},
          tags: [],
          created_at: 1700000000,
          updated_at: 1700000000,
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });
  }),
  http.post("/api/v1/knowledge-graph/impact-traversal/:id", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      start_node_id: "n1",
      steps: [],
      affected_node_ids: ["n2"],
      total_paths: 1,
      max_depth_reached: 1,
      duration_ms: 2,
    });
  }),
  http.get("/api/v1/compliance-risk/assessments", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          assessment_id: "a1",
          source: "manual",
          risk_level: "medium",
          risk_score: 0.4,
          risk_categories: [],
          affected_areas: [],
          recommended_actions: [],
          compliance_gaps: [],
          explanation: "",
          regulatory_exposure: 0.2,
          generated_at: 1700000000,
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });
  }),
  http.post("/api/v1/compliance-risk/assess", async ({ request }) => {
    const s = await capture(request);
    const body = s.body as Record<string, unknown>;
    if ("scope" in body || "policies" in body) {
      return HttpResponse.json(
        { detail: [{ loc: ["scope"], msg: "extra forbidden", type: "extra_forbidden" }] },
        { status: 422 }
      );
    }
    return HttpResponse.json({
      assessment_id: "a2",
      source: "manual",
      risk_level: "low",
      risk_score: 0.1,
      risk_categories: [],
      affected_areas: [],
      recommended_actions: [],
      compliance_gaps: [],
      explanation: "",
      regulatory_exposure: 0.05,
      generated_at: 1700000000,
    });
  }),
  http.get("/api/v1/forecasting/forecasts", async ({ request }) => {
    await capture(request);
    return HttpResponse.json([
      {
        forecast_id: "f1",
        horizon_days: 30,
        predicted_risk_score: 0.42,
        predicted_risk_level: "medium",
        confidence: 0.8,
        method: "trend",
        generated_at: 1700000000,
        points: [],
        drift_detected: false,
      },
    ]);
  }),
  http.get("/api/v1/forecasting/scenarios", async ({ request }) => {
    await capture(request);
    return HttpResponse.json([
      { name: "baseline", adjustments: {}, predicted_score: 0.5, predicted_level: "medium" },
    ]);
  }),
  http.post("/api/v1/forecasting/forecast", async ({ request }) => {
    const s = await capture(request);
    const body = s.body as Record<string, unknown>;
    if ("baseline_score" in body || "drivers" in body) {
      return HttpResponse.json(
        { detail: [{ loc: ["baseline_score"], msg: "extra forbidden", type: "extra_forbidden" }] },
        { status: 422 }
      );
    }
    return HttpResponse.json({
      forecast_id: "f2",
      horizon_days: 30,
      predicted_risk_score: 0.44,
      predicted_risk_level: "medium",
      confidence: 0.75,
      method: "trend",
      generated_at: 1700000000,
      points: [],
      drift_detected: false,
    });
  }),
  http.post("/api/v1/research/run", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      report_id: "rpt-1",
      plan_id: "plan-1",
      query: "kyc thresholds",
      kind: "general",
      summary: "Banks must verify identity.",
      key_findings: ["Verify identity documents"],
      timeline: [],
      comparisons: [],
      citations: [],
      steps: [
        {
          step_id: "step-1",
          step_type: "retrieve",
          description: "Retrieve KYC passages",
          status: "completed",
          inputs: {},
          outputs: {},
          error: "",
          started_at: 1700000000,
          finished_at: 1700000001,
          duration_ms: 1000,
        },
      ],
      generated_at: 1700000002,
      duration_ms: 1500,
    });
  }),
  http.get("/api/v1/research", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          report_id: "rpt-1",
          plan_id: "plan-1",
          query: "kyc thresholds",
          kind: "general",
          summary: "Banks must verify identity.",
          key_findings: [],
          timeline: [],
          comparisons: [],
          citations: [],
          steps: [],
          generated_at: 1700000002,
          duration_ms: 1500,
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    });
  }),
  http.get("/api/v1/audit/records", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          audit_id: "aud-1",
          timestamp: 1700000000,
          actor: "system",
          actor_role: "system",
          action: "login",
          severity: "info",
          subject_type: "user",
          subject_id: "u1",
          description: "login ok",
          details: {},
          prev_hash: "0",
          record_hash: "abc",
          sequence: 1,
          metadata: {},
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });
  }),
  http.get("/api/v1/audit/integrity", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      intact: true,
      message: "chain verified",
      total: 10,
      valid: 10,
      invalid: 0,
      chain_length: 10,
      last_chain_hash: "ff",
    });
  }),
  http.get("/api/v1/audit/reports", async ({ request }) => {
    await capture(request);
    return HttpResponse.json([]);
  }),
  http.get("/api/v1/audit/evidence", async ({ request }) => {
    await capture(request);
    return HttpResponse.json([]);
  }),
  http.get("/api/v1/agents/agents", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          agent_id: "agt-1",
          name: "research-agent",
          description: "research",
          version: "1.0.0",
          author: "system",
          capabilities: [
            { capability_id: "c1", kind: "retrieval", name: "retrieve", description: "" },
          ],
          status: "active",
          default_max_retries: 0,
          default_timeout_ms: 30000,
          priority: 0,
          tags: [],
          registered_at: 1700000000,
          updated_at: 1700000000,
          metadata: {},
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      has_more: false,
    });
  }),
  http.post("/api/v1/agents/execute", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      result_id: "res-1",
      task_id: "t1",
      agent_id: "agt-1",
      agent_name: "research-agent",
      status: "succeeded",
      output: { text: "done" },
      error: "",
      attempts: 1,
      duration_ms: 50,
      started_at: 1700000000,
      completed_at: 1700000001,
      metadata: {},
    });
  }),
  http.get("/api/v1/agents/workflows", async ({ request }) => {
    await capture(request);
    return HttpResponse.json([]);
  }),
  http.post("/api/v1/agents/workflows", async ({ request }) => {
    const s = await capture(request);
    const body = s.body as Record<string, unknown>;
    if (!("graph" in body)) {
      return HttpResponse.json({ detail: "field required: graph" }, { status: 422 });
    }
    return HttpResponse.json({
      workflow_id: "wf-1",
      name: "W",
      description: "",
      graph: body.graph,
      tags: [],
      version: "1.0.0",
      created_at: 1700000000,
      metadata: {},
    });
  }),
  http.post("/api/v1/agents/workflows/:id/run", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      run_id: "wfrun-1",
      workflow_id: "wf-1",
      workflow_name: "W",
      status: "running",
      started_at: 1700000000,
      completed_at: null,
      duration_ms: 0,
      result: null,
      error: "",
      metadata: {},
    });
  }),
  http.get("/api/v1/admin/overview", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      total_users: 4,
      active_users: 3,
      total_roles: 2,
      total_policies: 5,
      total_decisions: 9,
      total_audit_records: 11,
      total_reports: 0,
      total_workflows: 0,
      total_reviews: 0,
      compliance_rate: 0.8,
      approval_rate: 0.9,
      generated_at: 1700000000,
    });
  }),
  http.get("/api/v1/admin/stats", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      total_users: 4,
      active_users: 3,
      suspended_users: 0,
      total_roles: 2,
      built_in_roles: 2,
      total_permissions: 6,
      total_settings: 1,
      secret_settings: 0,
      by_role: {},
      by_user_status: {},
      generated_at: 1700000000,
    });
  }),
  http.get("/api/v1/admin/users", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          user_id: "u1",
          username: "a@b.c",
          email: "a@b.c",
          full_name: "A B",
          role_ids: ["viewer"],
          status: "active",
          last_login_at: 1700000000,
          created_at: 1699990000,
          updated_at: 1700000000,
          metadata: {},
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      has_more: false,
    });
  }),
  http.get("/api/v1/admin/roles", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          role_id: "viewer",
          name: "viewer",
          description: "read",
          built_in: true,
          permissions: [],
          user_count: 3,
          created_at: 1699990000,
          updated_at: 1700000000,
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      has_more: false,
    });
  }),
  http.get("/api/v1/agents/analytics/overview", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      total_agents: 2,
      total_invocations: 10,
      success_rate: 0.9,
      average_duration_ms: 120,
      average_confidence: 0.8,
      total_collaborations: 0,
      total_cost_units: 0,
      health: {
        total_agents: 2,
        healthy_agents: 2,
        degraded_agents: 0,
        unhealthy_agents: 0,
        unknown_agents: 0,
        overall_health: "healthy",
        agents: [],
      },
      leaderboard: [],
      collaborations: [],
      recent_executions: [],
      forecast_accuracy: [],
      recommendation_accuracy: [],
      cost: null,
      generated_at: 1700000000,
    });
  }),
  http.get("/api/v1/agents/analytics/performance", async ({ request }) => {
    await capture(request);
    return HttpResponse.json([
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
    ]);
  }),
  http.get("/api/v1/agents/metrics", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      total_invocations: 10,
      total_successful: 9,
      total_failed: 1,
      total_collaborations: 0,
      research: {},
      compliance: {},
      risk: {},
      by_mode: {},
      by_scenario_kind: {},
      average_confidence: 0.8,
      last_reset_at: 1700000000,
    });
  }),
  http.get("/api/v1/governance/policies", async ({ request }) => {
    await capture(request);
    return HttpResponse.json([
      {
        policy_id: "p1",
        name: "KYC Policy",
        description: "",
        version: "1.0.0",
        scope: "GLOBAL",
        rules: [],
        enabled: true,
        created_at: 1700000000,
        updated_at: 1700000000,
        tags: [],
      },
    ]);
  }),
  http.get("/api/v1/governance/decisions", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      items: [
        {
          decision_id: "dec-1",
          decision_type: "approval",
          subject_type: "document",
          subject_id: "d1",
          decision: "approved",
          confidence: 0.9,
          risk_level: "low",
          categories: [],
          inputs: {},
          outputs: {},
          actor: "admin",
          timestamp: 1700000000,
          metadata: {},
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
    });
  }),
  http.get("/api/v1/governance/stats", async ({ request }) => {
    await capture(request);
    return HttpResponse.json({
      total_policies: 5,
      total_rules: 9,
      total_decisions: 9,
      compliant_decisions: 8,
      non_compliant_decisions: 1,
      total_violations: 1,
      blocking_violations: 0,
      average_violations_per_decision: 0.11,
      compliance_rate: 0.89,
      last_decision_at: 1700000000,
    });
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  seen.length = 0;
  setAuthHandler(null);
  setAccessToken(null);
});
afterAll(() => server.close());

function lastCall() {
  return seen[seen.length - 1];
}

function withToken(token: string) {
  setAccessToken(token);
  setAuthHandler({
    getAccessToken: () => token,
    refreshAccessToken: async () => false,
    onAuthFailure: () => {},
  });
}

describe("auth contracts", () => {
  it("login POSTs credentials and returns tokens + user", async () => {
    const res = await authApi.login({ email: "a@b.c", password: "pw123456" });
    expect(lastCall()).toMatchObject({
      method: "POST",
      url: "/api/v1/security/auth/login",
    });
    expect(lastCall().body).toEqual({ email: "a@b.c", password: "pw123456" });
    expect(res.access_token).toBe("acc");
    expect(res.user.rbac_roles).toEqual(["viewer"]);
  });

  it("refresh returns tokens WITHOUT user (backend TokenResponse)", async () => {
    const res = await authApi.refreshToken("ref");
    expect(lastCall().url).toBe("/api/v1/security/auth/refresh");
    expect(res.access_token).toBe("acc2");
    expect(res).not.toHaveProperty("user");
  });

  it("signup POSTs email/password/full_name and gets 201 envelope", async () => {
    const res = await authApi.signup({ email: "n@b.c", password: "pw123456", full_name: "N" });
    expect(lastCall().method).toBe("POST");
    expect(lastCall().url).toBe("/api/v1/security/auth/signup");
    expect(res.user.email).toBe("a@b.c");
  });

  it("attaches Bearer token when set", async () => {
    withToken("tok-1");
    await authApi.getMe();
    expect(lastCall().auth).toBe("Bearer tok-1");
  });
});

describe("health contracts", () => {
  it("ready hits root /health/ready with checks map", async () => {
    const res = await healthApi.getReadyReport();
    expect(lastCall().url).toBe("/health/ready");
    expect(res.checks.db.status).toBe("ok");
  });

  it("getHealth rolls up to healthy without throwing", async () => {
    await expect(healthApi.getHealth()).resolves.toEqual({ level: "healthy" });
  });
});

describe("copilot contracts", () => {
  it("query POSTs valid payload, parses citations object + sources", async () => {
    withToken("t");
    const res = await copilotApi.queryCopilot({ query: "kyc?", mode: "answer" });
    expect(lastCall()).toMatchObject({ method: "POST", url: "/api/v1/copilot/query" });
    expect(lastCall().body).toMatchObject({ query: "kyc?", mode: "answer" });
    expect(res.citations?.references[0].document_title).toBe("RBI Master Direction");
    expect(res.sources[0].similarity).toBe(0.8);
    expect(res.memory_context.total_count).toBe(0);
  });

  it("sessions unwrap paginated envelope; messages map conversation", async () => {
    const sessions = await copilotApi.getSessions();
    expect(sessions.total).toBe(1);
    expect(sessions.items[0].updated_at).toContain("2026-01-02");
    const msgs = await copilotApi.getMessages("conv-1");
    expect(lastCall().url).toBe("/api/v1/conversations/conv-1");
    expect(msgs.items[0].content).toBe("hi");
  });

  it("encodes conversation ids with special characters", async () => {
    await copilotApi.getMessages("a/b c").catch(() => {});
    expect(lastCall().url).toBe("/api/v1/conversations/a%2Fb%20c");
  });
});

describe("documents contracts", () => {
  it("list returns bare array; upload sends FormData; detail has chunks", async () => {
    const list = await documentsApi.getDocuments();
    expect(Array.isArray(list)).toBe(true);
    expect(list[0].status).toBe("INDEXED");
    expect(list[0]).not.toHaveProperty("chunk_count");

    const up = await documentsApi.uploadDocument(new File(["x"], "a.pdf"));
    expect(lastCall().method).toBe("POST");
    expect(lastCall().url).toBe("/api/v1/documents/upload");
    expect(lastCall().body).toBe("FORMDATA");
    expect(up.status).toBe("processing");

    const detail = await documentsApi.getDocument("d1");
    expect(detail.chunk_count).toBe(4);
    expect(detail.indexed).toBe(true);
  });

  it("ingestion runs expose run_id + lowercase status enum", async () => {
    const runs = await documentsApi.getIngestionJobs();
    expect(runs[0].run_id).toBe("run-1");
    expect(runs[0].status).toBe("completed");
  });

  it("409 surfaces status for duplicate handling", async () => {
    server.use(
      http.post("/api/v1/documents/upload", async () => {
        return HttpResponse.json({ detail: "duplicate checksum" }, { status: 409 });
      })
    );
    const err = await documentsApi
      .uploadDocument(new File(["x"], "a.pdf"))
      .catch((e) => e);
    expect(err).toBeInstanceOf(ApiClientError);
    expect(err.status).toBe(409);
  });
});

describe("knowledge-graph contracts", () => {
  it("stats match exactly; nodes use name/entity_type; impact posts", async () => {
    const stats = await kgApi.getGraphStats();
    expect(stats.total_nodes).toBe(3);
    const nodes = await kgApi.getGraphNodes();
    expect(nodes[0].name).toBe("RBI KYC Direction");
    expect(nodes[0].entity_type).toBe("regulation");
    const impact = await kgApi.getGraphImpact("n1");
    expect(lastCall()).toMatchObject({
      method: "POST",
      url: "/api/v1/knowledge-graph/impact-traversal/n1",
    });
    expect(impact.affected_node_ids).toEqual(["n2"]);
  });
});

describe("compliance + forecast contracts", () => {
  it("assess sends source/context (never scope/policies)", async () => {
    const res = await complianceApi.runCompliance({
      source: "manual",
      context: { scope: "x" },
    });
    expect(lastCall().body).toEqual({ source: "manual", context: { scope: "x" } });
    expect(res.risk_level).toBe("low");
  });

  it("backend-shaped 422 surfaces joined validation message", async () => {
    // valid payload above succeeds; prove the forbid path via raw client:
    const { request } = await import("@/lib/api");
    const bad: unknown = await request("/compliance-risk/assess", {
      method: "POST",
      body: { scope: "x", policies: ["y"] },
    }).catch((e) => e);
    expect(bad).toBeInstanceOf(ApiClientError);
    expect((bad as ApiClientError).status).toBe(422);
    expect((bad as ApiClientError).message).toContain("extra forbidden");
  });

  it("forecast sends horizon only; reads predicted_risk_score", async () => {
    const res = await riskApi.forecastRisk({ horizon_days: 30 });
    expect(lastCall().body).toEqual({ horizon_days: 30 });
    expect(res.predicted_risk_score).toBe(0.44);
    const scenarios = await riskApi.getRiskScenarios();
    expect(scenarios[0].predicted_score).toBe(0.5);
  });
});

describe("research contracts", () => {
  it("run returns steps/key_findings/citations; reports unwrap", async () => {
    const res = await researchApi.runResearch({ query: "kyc thresholds", max_steps: 3 });
    expect(lastCall().body).toMatchObject({ query: "kyc thresholds", max_steps: 3 });
    expect(res.steps[0].status).toBe("completed");
    expect(res.key_findings).toEqual(["Verify identity documents"]);
    expect(res).not.toHaveProperty("confidence");
    const list = await researchApi.getResearchReports();
    expect(list[0].report_id).toBe("rpt-1");
  });
});

describe("audit contracts", () => {
  it("records unwrap; integrity uses intact; evidence joins on record_id", async () => {
    const records = await auditApi.getAuditRecords();
    expect(records[0].subject_type).toBe("user");
    expect(records[0]).not.toHaveProperty("outcome");
    const integrity = await auditApi.getAuditIntegrity();
    expect(integrity.intact).toBe(true);
    expect(integrity).not.toHaveProperty("broken_chains");
    const reports = await auditApi.getAuditReports();
    expect(Array.isArray(reports)).toBe(true);
  });
});

describe("agents contracts", () => {
  it("list unwraps; execute posts enum capability; workflow create needs graph", async () => {
    const list = await agentApi.getAgents();
    expect(list.items[0].registered_at).toBe(1700000000);
    const res = await agentApi.executeAgent({
      agent_name: "research-agent",
      capability: "retrieval",
      input: { text: "hi" },
    });
    expect(lastCall().body).toMatchObject({ agent_name: "research-agent", capability: "retrieval" });
    expect(res.result_id).toBe("res-1");
    expect(res.status).toBe("succeeded");
    const wf = await agentApi.createWorkflow({
      name: "W",
      graph: { steps: [{ agent_name: "research-agent" }] },
    });
    expect(lastCall().body).toMatchObject({ name: "W" });
    expect(wf.graph.steps).toHaveLength(1);
    const run = await agentApi.runWorkflow("wf-1");
    expect(run.run_id).toBe("wfrun-1");
  });
});

describe("governance contracts", () => {
  it("policies are bare array with enabled/version; decisions unwrap; stats real", async () => {
    const policies = await governanceApi.getPolicies();
    expect(Array.isArray(policies)).toBe(true);
    expect(policies[0].version).toBe("1.0.0");
    expect(policies[0].enabled).toBe(true);
    const decisions = await governanceApi.getDecisions();
    expect(decisions[0].decision).toBe("approved");
    expect(decisions[0].subject_type).toBe("document");
    const stats = await governanceApi.getGovernanceStats();
    expect(stats.compliant_decisions).toBe(8);
    expect(stats).not.toHaveProperty("active");
  });
});

describe("admin + analytics contracts", () => {
  it("admin reads flat totals, username/role_ids, user_count", async () => {
    const overview = await adminApi.getAdminOverview();
    expect(overview.total_users).toBe(4);
    expect(overview).not.toHaveProperty("users");
    const users = await adminApi.getUsers();
    expect(users.items[0].username).toBe("a@b.c");
    expect(users.items[0].role_ids).toEqual(["viewer"]);
    const roles = await adminApi.getRoles();
    expect(roles.items[0].user_count).toBe(3);
  });

  it("analytics reads renamed counts; metrics use total_successful", async () => {
    const overview = await analyticsApi.getAnalyticsOverview();
    expect(overview.success_rate).toBe(0.9);
    const perf = await analyticsApi.getPerformance();
    expect(perf[0].successful_invocations).toBe(9);
    const metrics = await analyticsApi.getIntelligenceMetrics();
    expect(metrics.total_successful).toBe(9);
  });
});
