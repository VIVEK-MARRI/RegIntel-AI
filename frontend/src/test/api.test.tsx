import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useAnalyticsOverview, useAgents, useLeaderboard } from "@/hooks/api";
import { API_BASE } from "@/lib/api";

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function mockJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("API hooks (TanStack Query)", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("useAnalyticsOverview hits /agents/analytics/overview and returns data", async () => {
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

    const { result } = renderHook(() => useAnalyticsOverview(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.total_agents).toBe(5);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`${API_BASE}/agents/analytics/overview`),
      expect.objectContaining({ method: "GET" })
    );
  });

  it("useAgents returns paginated agent list", async () => {
    fetchMock.mockResolvedValue(
      mockJsonResponse({
        items: [{ agent_id: "a1", name: "agent-a", capabilities: ["x"] }],
        total: 1,
        page: 1,
        page_size: 20,
      })
    );
    const { result } = renderHook(() => useAgents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items[0].name).toBe("agent-a");
  });

  it("useLeaderboard passes top_n query param", async () => {
    fetchMock.mockResolvedValue(mockJsonResponse([]));
    const { result } = renderHook(() => useLeaderboard(3), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toMatch(/top_n=3/);
  });

  it("surfaces server errors as failures", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "boom" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      })
    );
    const { result } = renderHook(() => useAgents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toMatch(/boom/);
  });
});
