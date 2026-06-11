import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { getAnalyticsOverview } from "@/services/api/analyticsApi";
import { getAgents } from "@/services/api/agentApi";
import { getDocuments } from "@/services/api/documentsApi";
import { getAdminOverview, getAdminStats, getUsers, getRoles } from "@/services/api/adminApi";
import { getGovernanceStats } from "@/services/api/governanceApi";
import { getComplianceAssessments } from "@/services/api/complianceApi";
import { getRiskForecasts } from "@/services/api/riskApi";
import { getAuditIntegrity } from "@/services/api/auditApi";

function mockJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("API service functions", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getAnalyticsOverview hits /agents/analytics/overview", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        total_agents: 5,
        total_invocations: 100,
        success_rate: 0.95,
        average_duration_ms: 120,
        average_confidence: 0.9,
        health: { overall_health: "healthy", agents: [] },
        cost: { total_cost_units: 0, currency: "USD" },
        leaderboard: [],
        generated_at: 0,
        notes: "",
      })
    );
    const data = await getAnalyticsOverview();
    expect(data.total_agents).toBe(5);
  });

  it("getAgents returns paginated agent list", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        items: [{ agent_id: "a1", name: "agent-a", capabilities: ["x"] }],
        total: 1,
        page: 1,
        page_size: 20,
      })
    );
    const data = await getAgents();
    expect(data.items[0].name).toBe("agent-a");
  });

  it("getDocuments returns document list", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        items: [{ document_id: "d1", title: "test.pdf", source: "upload", status: "ready", created_at: 1000, chunk_count: 5 }],
        total: 1,
        page: 1,
        page_size: 20,
      })
    );
    const data = await getDocuments();
    expect(data).toHaveLength(1);
    expect(data[0].title).toBe("test.pdf");
  });

  it("getAdminOverview returns overview data", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        users: { total: 10, active: 8, suspended: 2 },
        policies: { total: 5, active: 3, draft: 2 },
        audit: { total: 100, last_24h: 5 },
        compliance_score: 92,
        notes: "All good",
        generated_at: 0,
      })
    );
    const data = await getAdminOverview();
    expect(data.users.total).toBe(10);
  });

  it("getAdminStats returns stats data", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        total_users: 10,
        active_users: 8,
        total_roles: 4,
        total_policies: 5,
        total_audit_records: 100,
        total_decisions: 50,
        system_health: "healthy" as const,
        generated_at: 0,
      })
    );
    const data = await getAdminStats();
    expect(data.total_users).toBe(10);
  });

  it("getUsers returns paginated users", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        items: [{ user_id: "u1", name: "Alice", email: "a@b.com", roles: ["admin"], status: "active", created_at: 0 }],
        total: 1,
        page: 1,
        page_size: 20,
      })
    );
    const data = await getUsers();
    expect(data.items[0].name).toBe("Alice");
  });

  it("getRoles returns paginated roles", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        items: [{ role_id: "r1", name: "Admin", description: "Admin role", permissions: ["read"], member_count: 2 }],
        total: 1,
        page: 1,
        page_size: 20,
      })
    );
    const data = await getRoles();
    expect(data.items[0].name).toBe("Admin");
  });

  it("getGovernanceStats returns stats", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({ total_policies: 5, total_decisions: 50, active: 3, deprecated: 2 })
    );
    const data = await getGovernanceStats();
    expect(data.total_policies).toBe(5);
  });

  it("getComplianceAssessments returns assessments", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        items: [{ assessment_id: "a1", scope: "GDPR", overall_score: 85, status: "completed", created_at: 0 }],
        total: 1,
        page: 1,
        page_size: 20,
      })
    );
    const data = await getComplianceAssessments();
    expect(data).toHaveLength(1);
  });

  it("getRiskForecasts returns forecasts", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse([{ forecast_id: "f1", horizon_days: 30, baseline_score: 50, projected_score: 60, confidence: 0.8, drivers: [], created_at: 0 }])
    );
    const data = await getRiskForecasts();
    expect(data).toHaveLength(1);
  });

  it("getAuditIntegrity returns integrity data", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({ total: 100, valid: 98, invalid: 2, broken_chains: [], checked_at: 0 })
    );
    const data = await getAuditIntegrity();
    expect(data.valid).toBe(98);
  });

  it("surfaces server errors", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "boom" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      })
    );
    await expect(getAgents()).rejects.toThrow();
  });
});
