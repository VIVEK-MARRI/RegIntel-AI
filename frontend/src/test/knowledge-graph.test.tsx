/**
 * Stage 09 knowledge-graph tests: entity search/filter/pagination,
 * selection → inspector, directional relationships, reachability,
 * dependencies, SVG graph interaction, deep links, and failure states.
 * MSW replies with backend-shaped payloads (knowledge_graph schemas).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KnowledgeGraphPage } from "@/pages/KnowledgeGraphPage";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const nodeFixture = (id: string, overrides: Record<string, unknown> = {}) => ({
  node_id: id,
  entity_type: "regulation",
  name: `Node ${id}`,
  description: `Description for ${id}.`,
  source: "manual",
  properties: {},
  tags: ["kyc"],
  created_at: 1700000000,
  updated_at: 1700000100,
  ...overrides,
});

const N1 = nodeFixture("n1", { name: "RBI KYC Direction" });
const N2 = nodeFixture("n2", { name: "KYC Circular 12", entity_type: "circular" });
const N0 = nodeFixture("n0", { name: "Banking Act", entity_type: "regulation", tags: [] });

const REL_OUT = {
  relationship_id: "rel-1",
  source_id: "n1",
  target_id: "n2",
  relationship_type: "references",
  weight: 1,
  confidence: 0.9,
  properties: {},
  created_at: 1700000000,
};
const REL_IN = {
  relationship_id: "rel-2",
  source_id: "n0",
  target_id: "n1",
  relationship_type: "amends",
  weight: 1,
  confidence: 1,
  properties: {},
  created_at: 1700000000,
};

let nodesHits: string[] = [];
let relHits: string[] = [];
let impactHits: string[] = [];
let depHits: string[] = [];

const server = setupServer(
  http.get("/api/v1/knowledge-graph/stats", async () => {
    return HttpResponse.json({
      total_nodes: 3,
      total_relationships: 2,
      by_entity_type: { regulation: 2, circular: 1 },
      by_relationship_type: { references: 1, amends: 1 },
      by_source: { manual: 3 },
      average_degree: 1.33,
      max_depth: 2,
      connected_components: 1,
      generated_at: 1700000000,
    });
  }),
  http.get("/api/v1/knowledge-graph/nodes", async ({ request }) => {
    const url = new URL(request.url);
    nodesHits.push(url.search);
    const q = url.searchParams.get("name_contains");
    const items = q ? [N1, N2, N0].filter((n) => (n.name as string).includes(q)) : [N1, N2];
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: 50, has_more: false });
  }),
  http.get("/api/v1/knowledge-graph/nodes/:id", async ({ params }) => {
    const all = { n1: N1, n2: N2, n0: N0 } as Record<string, unknown>;
    const node = all[params.id as string];
    if (!node) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    return HttpResponse.json(node);
  }),
  http.get("/api/v1/knowledge-graph/relationships", async ({ request }) => {
    const url = new URL(request.url);
    relHits.push(url.search);
    const src = url.searchParams.get("source_id");
    const tgt = url.searchParams.get("target_id");
    const items = [
      ...(src === "n1" ? [REL_OUT] : []),
      ...(tgt === "n1" ? [REL_IN] : []),
      ...(src === "n2" || tgt === "n2" ? [] : []),
    ];
    return HttpResponse.json({ items, total: items.length, page: 1, page_size: 100, has_more: false });
  }),
  http.post("/api/v1/knowledge-graph/impact-traversal/:id", async ({ request }) => {
    const url = new URL(request.url);
    impactHits.push(url.search);
    return HttpResponse.json({
      start_node_id: "n1",
      steps: [
        { from_node_id: "n1", to_node_id: "n2", relationship_type: "references", depth: 1, weight: 1, path: ["n1", "n2"] },
      ],
      affected_node_ids: ["n2"],
      total_paths: 1,
      max_depth_reached: 1,
      duration_ms: 2,
    });
  }),
  http.post("/api/v1/knowledge-graph/dependency-analysis/:id", async ({ request }) => {
    const url = new URL(request.url);
    depHits.push(url.search);
    return HttpResponse.json({
      root_node_id: "n1",
      upstream: [N0],
      downstream: [],
      cycles_detected: 1,
      max_chain_length: 2,
      duration_ms: 3,
    });
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
  nodesHits = [];
  relHits = [];
  impactHits = [];
  depHits = [];
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderKG(initialRoute = "/knowledge-graph") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[initialRoute]}>
            <Routes>
              <Route path="/knowledge-graph" element={<KnowledgeGraphPage />} />
              <Route path="/knowledge-graph/:nodeId" element={<KnowledgeGraphPage />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

async function selectN1() {
  renderKG();
  await screen.findByText("RBI KYC Direction");
  await userEvent.click(screen.getByRole("button", { name: "RBI KYC Direction regulation" }));
  await screen.findByText("Inspector");
  await screen.findByText("Description for n1.");
}

describe("overview + entity list", () => {
  it("renders stats from /stats, never from rows", async () => {
    renderKG();
    expect(await screen.findByText("Knowledge Graph")).toBeTruthy();
    expect(screen.getByText("Entities")).toBeTruthy();
    expect(await screen.findByText("3")).toBeTruthy();
    expect(screen.getByText("Relationships")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });

  it("lists entities with type badges; server search sends name_contains", async () => {
    renderKG();
    await screen.findByText("RBI KYC Direction");
    expect(nodesHits[0]).toContain("page=1");
    fireEvent.change(screen.getByLabelText(/search all entities/i), { target: { value: "KYC" } });
    await waitFor(() => expect(nodesHits.some((h) => h.includes("name_contains=KYC"))).toBe(true), { timeout: 3000 });
  });

  it("type filter sends entity_type; clear resets", async () => {
    renderKG();
    await screen.findByText("RBI KYC Direction");
    fireEvent.change(screen.getByLabelText(/entity type/i), { target: { value: "circular" } });
    await waitFor(() => expect(nodesHits.some((h) => h.includes("entity_type=circular"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect((screen.getByLabelText(/search all entities/i) as HTMLInputElement).value).toBe("");
  });

  it("short page disables Next; full page advances with page=2", async () => {
    const many = Array.from({ length: 50 }, (_, i) => nodeFixture(`dx${i}`, { name: `Node dx${i}` }));
    server.use(
      http.get("/api/v1/knowledge-graph/nodes", async ({ request }) => {
        const url = new URL(request.url);
        nodesHits.push(url.search);
        return HttpResponse.json({ items: many, total: 120, page: 1, page_size: 50, has_more: true });
      })
    );
    renderKG();
    await screen.findByText("Node dx0");
    expect(screen.getByText(/Page 1 · 50 shown/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(nodesHits.some((h) => h.includes("page=2"))).toBe(true));
  });

  it("stats failure shows retryable error", async () => {
    server.use(
      http.get("/api/v1/knowledge-graph/stats", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderKG();
    expect(await screen.findByText("Graph statistics unavailable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("malformed node renders safely with a fallback label", async () => {
    server.use(
      http.get("/api/v1/knowledge-graph/nodes", async () => {
        return HttpResponse.json({ items: [{ node_id: "bad" }], total: 1, page: 1, page_size: 50 });
      })
    );
    renderKG();
    expect(await screen.findByText("Untitled entity")).toBeTruthy();
  });
});

describe("selection, inspector, relationships", () => {
  it("selecting an entity loads inspector details", async () => {
    await selectN1();
    expect(screen.getByText("Description for n1.")).toBeTruthy();
    expect(screen.getByText("manual")).toBeTruthy();
    expect(screen.getByText("kyc")).toBeTruthy();
    expect(screen.queryByText("Invalid Date")).toBeNull();
  });

  it("directional relationship lists render; neighbor click reselects", async () => {
    await selectN1();
    expect(await screen.findByText("Outgoing (1)")).toBeTruthy();
    expect(screen.getByText("Incoming (1)")).toBeTruthy();
    expect(relHits.some((h) => h.includes("source_id=n1"))).toBe(true);
    expect(relHits.some((h) => h.includes("target_id=n1"))).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: /→ KYC Circular 12/ }));
    await waitFor(() => expect(screen.getByText("Description for n2.")).toBeTruthy());
  });

  it("relationship type filter refetches with rel_type", async () => {
    await selectN1();
    await screen.findByText("Outgoing (1)");
    fireEvent.change(screen.getByLabelText(/relationship type/i), { target: { value: "references" } });
    await waitFor(() => expect(relHits.some((h) => h.includes("rel_type=references"))).toBe(true));
  });

  it("svg graph centers selection; graph node click reselects", async () => {
    await selectN1();
    const svg = await screen.findByRole("img", { name: /relationship graph/i });
    expect(within(svg).getByRole("button", { name: "RBI KYC Direction, regulation, selected" })).toBeTruthy();
    await userEvent.click(within(svg).getByRole("button", { name: "KYC Circular 12, circular" }));
    await waitFor(() => expect(screen.getByText("Description for n2.")).toBeTruthy());
  });

  it("deep link preselects the entity without clicks", async () => {
    renderKG("/knowledge-graph/n1");
    expect(await screen.findByText("Description for n1.")).toBeTruthy();
    expect(await screen.findByText("Outgoing (1)")).toBeTruthy();
  });

  it("unknown deep-link id shows entity error, not a crash", async () => {
    renderKG("/knowledge-graph/nope");
    expect(await screen.findByText("Entity unavailable")).toBeTruthy();
  });
});

describe("impact + dependencies", () => {
  it("reachability shows counts and textual steps with depth", async () => {
    await selectN1();
    expect(impactHits[0]).toContain("max_depth=3");
    expect(await screen.findByText(/1 path\(s\) · max depth 1/)).toBeTruthy();
    expect(screen.getByText("depth 1")).toBeTruthy();
  });

  it("depth control refetches impact + dependency with new max_depth", async () => {
    await selectN1();
    await screen.findByText(/max depth 1/);
    fireEvent.change(screen.getByLabelText(/traversal depth/i), { target: { value: "5" } });
    await waitFor(() => expect(impactHits.some((h) => h.includes("max_depth=5"))).toBe(true));
    await waitFor(() => expect(depHits.some((h) => h.includes("max_depth=5"))).toBe(true));
  });

  it("dependencies show upstream list, cycle count, longest chain", async () => {
    await selectN1();
    expect(await screen.findByText(/Upstream — depends on \(1\)/)).toBeTruthy();
    // Upstream dependency also appears as an incoming relationship — both panels agree.
    expect(screen.getAllByText("Banking Act").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/1 dependency cycle\(s\) detected/)).toBeTruthy();
    expect(screen.getByText(/Longest chain: 2 hop\(s\)/)).toBeTruthy();
  });
});
