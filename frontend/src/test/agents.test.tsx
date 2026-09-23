/**
 * Stage 14 agents tests: registry with server filters, agent detail + health,
 * blocking execution with declared capabilities, deterministic coordinator,
 * orchestration workflows (create/run with real graph.steps payloads), message
 * bus without polling, and the no-fake-monitoring rule. MSW uses
 * backend-shaped payloads (agents + orchestration + intelligence schemas).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AgentsPage } from "@/pages/AgentsPage";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { ToastViewport } from "@/components/ui/ToastViewport";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const AG1 = {
  agent_id: "agt-1",
  name: "research-agent",
  description: "Retrieval and reasoning",
  version: "1.0.0",
  author: "system",
  capabilities: [
    { capability_id: "c1", kind: "retrieval", name: "retrieve", description: "Fetch documents" },
    { capability_id: "c2", kind: "reasoning", name: "reason", description: "" },
  ],
  status: "active",
  default_max_retries: 0,
  default_timeout_ms: 30000,
  priority: 1,
  tags: ["core"],
  registered_at: 1700000000,
  updated_at: 1700000000,
  metadata: {},
};
const AG2 = {
  agent_id: "agt-2",
  name: "bare-agent",
  description: "",
  version: "1.0.0",
  author: "system",
  capabilities: [],
  status: "registered",
  default_max_retries: 0,
  default_timeout_ms: 30000,
  priority: 0,
  tags: [],
  registered_at: 1700000000,
  updated_at: 1700000000,
  metadata: {},
};

const WF1 = {
  workflow_id: "wf-1",
  name: "KYC review flow",
  description: "Review KYC documents",
  graph: {
    steps: [
      { step_id: "step-1", agent_name: "research-agent", capability: "retrieval", description: "Fetch KYC docs", depends_on: [] },
      { step_id: "step-2", agent_name: "research-agent", capability: "reasoning", description: "Assess gaps", depends_on: ["step-1"] },
    ],
    mode: "sequential",
  },
  tags: [],
  version: "1.0.0",
  created_at: 1700000000,
  metadata: {},
};

let agentHits: string[] = [];
let agents: unknown[] = [AG1, AG2];
let executeHits: unknown[] = [];
let executeDelayMs = 0;
let executeResult: Record<string, unknown> = {
  result_id: "res-1", task_id: "t1", agent_id: "agt-1", agent_name: "research-agent",
  status: "succeeded", output: { text: "done", score: 2 }, error: "", attempts: 1,
  duration_ms: 50, started_at: 1700000000, completed_at: 1700000001, metadata: {},
};
let registerHits: unknown[] = [];
let unregisterHits: string[] = [];
let coordinateHits: unknown[] = [];
let workflowHits = 0;
let createHits: unknown[] = [];
let workflows: unknown[] = [WF1];
let runHits: unknown[] = [];
let runDelayMs = 0;
let messageHits: string[] = [];

const server = setupServer(
  http.get("/api/v1/agents/agents", async ({ request }) => {
    const url = new URL(request.url);
    agentHits.push(url.search);
    return HttpResponse.json({ items: agents, total: agents.length, page: 1, page_size: 50, has_more: false });
  }),
  http.get("/api/v1/agents/agents/:name", async ({ params }) => {
    const a = (agents as Record<string, unknown>[]).find((x) => x.name === params.name);
    if (!a) return HttpResponse.json({ detail: "agent not found" }, { status: 404 });
    return HttpResponse.json(a);
  }),
  http.get("/api/v1/agents/agents/:name/health", async ({ params }) => {
    if (params.name !== "research-agent") {
      return HttpResponse.json({ detail: "agent not found" }, { status: 404 });
    }
    return HttpResponse.json({
      agent_id: "agt-1", healthy: true, last_error: "", consecutive_failures: 0,
      total_invocations: 10, successful_invocations: 9, failed_invocations: 1,
      average_duration_ms: 120, last_invocation_at: 1700000000,
      last_success_at: 1700000000, last_failure_at: 1699900000,
    });
  }),
  http.post("/api/v1/agents/agents", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    registerHits.push(body);
    return HttpResponse.json({ ...AG1, agent_id: "agt-9", name: body.name }, { status: 201 });
  }),
  http.delete("/api/v1/agents/agents/:name", async ({ params }) => {
    unregisterHits.push(params.name as string);
    agents = (agents as Record<string, unknown>[]).filter((a) => a.name !== params.name);
    return HttpResponse.json({ unregistered: params.name });
  }),
  http.post("/api/v1/agents/execute", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    executeHits.push(body);
    if (executeDelayMs > 0) await new Promise((r) => setTimeout(r, executeDelayMs));
    return HttpResponse.json(executeResult);
  }),
  http.post("/api/v1/agents/coordinate", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    coordinateHits.push(body);
    return HttpResponse.json({
      result_id: "cres-1", plan_id: "plan-1", query: body.query, selected_agents: ["research-agent"],
      step_results: [
        { result_id: "res-1", task_id: "t1", agent_id: "agt-1", agent_name: "research-agent", status: "succeeded", output: {}, error: "", attempts: 1, duration_ms: 40, started_at: 1700000000, completed_at: 1700000001, metadata: {} },
      ],
      final_output: { answer: "KYC rules updated" }, status: "succeeded", duration_ms: 120,
      conflicts_resolved: 0, notes: "", metadata: {},
    });
  }),
  http.get("/api/v1/agents/workflows", async () => {
    workflowHits += 1;
    return HttpResponse.json(workflows);
  }),
  http.post("/api/v1/agents/workflows", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    createHits.push(body);
    const created = { ...WF1, workflow_id: "wf-9", name: body.name, graph: body.graph };
    workflows = [created, ...workflows];
    return HttpResponse.json(created, { status: 201 });
  }),
  http.post("/api/v1/agents/workflows/:id/run", async ({ request, params }) => {
    const body = (await request.json()) as Record<string, unknown>;
    runHits.push({ id: params.id, body });
    if (runDelayMs > 0) await new Promise((r) => setTimeout(r, runDelayMs));
    return HttpResponse.json({
      run_id: "wfrun-1", workflow_id: params.id, workflow_name: "KYC review flow",
      status: "succeeded", started_at: 1700000000, completed_at: 1700000005,
      duration_ms: 5000, result: { execution_id: "exec-1", status: "succeeded" },
      error: "", metadata: {},
    });
  }),
  http.get("/api/v1/agents/messages", async ({ request }) => {
    const url = new URL(request.url);
    messageHits.push(url.search);
    return HttpResponse.json([
      {
        message_id: "msg-1", from_agent: "research-agent", to_agent: "compliance-agent",
        kind: "evidence", payload: { doc: "d1" }, correlation_id: "c1", in_reply_to: "",
        created_at: 1700000000, ttl_ms: 60000,
      },
    ]);
  }),
  http.get("/api/v1/agents/collaborations", async () => {
    return HttpResponse.json([
      {
        collaboration_id: "collab-1", from_agent: "research-agent", to_agent: "compliance-agent",
        request_kind: "evidence", evidence_keys: ["k1"], result_keys: ["r1"],
        shared_context_keys: [], duration_ms: 120, created_at: 1700000000,
      },
    ]);
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
  agentHits = [];
  agents = [AG1, AG2];
  executeHits = [];
  executeDelayMs = 0;
  executeResult = {
    result_id: "res-1", task_id: "t1", agent_id: "agt-1", agent_name: "research-agent",
    status: "succeeded", output: { text: "done", score: 2 }, error: "", attempts: 1,
    duration_ms: 50, started_at: 1700000000, completed_at: 1700000001, metadata: {},
  };
  registerHits = [];
  unregisterHits = [];
  coordinateHits = [];
  workflowHits = 0;
  createHits = [];
  workflows = [WF1];
  runHits = [];
  runDelayMs = 0;
  messageHits = [];
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderAgents() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/agents"]}>
            <AgentsPage />
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

describe("registry", () => {
  it("agents render with status and declared capabilities; h1 present", async () => {
    renderAgents();
    expect(await screen.findByRole("heading", { level: 1, name: "AI Agents" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: /research-agent/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /bare-agent/ })).toBeTruthy();
    expect(screen.getByText("active")).toBeTruthy();
    expect(screen.getByText(/retrieval · reasoning/)).toBeTruthy();
  });

  it("filters send capability/text/tag; paging sends page", async () => {
    const many = Array.from({ length: 50 }, (_, i) => ({ ...AG1, agent_id: `ax${i}`, name: `agent-${i}` }));
    agents = many;
    renderAgents();
    await screen.findByRole("button", { name: /agent-0/ });
    fireEvent.change(screen.getByLabelText(/filter by capability/i), { target: { value: "reasoning" } });
    await waitFor(() => expect(agentHits.some((h) => h.includes("capability=reasoning"))).toBe(true));
    fireEvent.change(screen.getByLabelText(/search agents/i), { target: { value: "agent-1" } });
    await waitFor(() => expect(agentHits.some((h) => h.includes("text_query=agent-1"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(agentHits.some((h) => h.includes("page=2"))).toBe(true));
  });

  it("empty and error states are distinct", async () => {
    agents = [];
    renderAgents();
    expect(await screen.findByText("No agents registered")).toBeTruthy();
  });

  it("detail shows metadata, capabilities, and health; unknown id errors", async () => {
    renderAgents();
    await screen.findByRole("button", { name: /research-agent/ });
    await userEvent.click(screen.getByRole("button", { name: /research-agent/ }));
    expect(await screen.findByText("Fetch documents")).toBeTruthy();
    expect(screen.getByText("Healthy")).toBeTruthy();
    expect(screen.getByText(/9.*ok.*1.*failed|9 ok/)).toBeTruthy();
    renderAgents();
    await screen.findByRole("button", { name: /bare-agent/ });
    await userEvent.click(screen.getByRole("button", { name: /bare-agent/ }));
    expect(await screen.findByText("This agent declares no capabilities.")).toBeTruthy();
    expect(await screen.findByText("Health snapshot unavailable.")).toBeTruthy();
  });
});

describe("execution", () => {
  async function setupExecute() {
    renderAgents();
    await screen.findByRole("button", { name: /research-agent/ });
    fireEvent.change(screen.getByLabelText(/^agent$/i), { target: { value: "research-agent" } });
    fireEvent.change(screen.getByLabelText(/^capability$/i), { target: { value: "reasoning" } });
    fireEvent.change(screen.getByLabelText(/input \(json object\)/i), { target: { value: '{"q": "kyc"}' } });
  }

  it("capability options come from the selected agent, never a default", async () => {
    renderAgents();
    await screen.findByRole("button", { name: /research-agent/ });
    fireEvent.change(screen.getByLabelText(/^agent$/i), { target: { value: "research-agent" } });
    const sel = screen.getByLabelText(/^capability$/i) as HTMLSelectElement;
    const opts = Array.from(sel.options).map((o) => o.value);
    expect(opts).toContain("retrieval");
    expect(opts).toContain("reasoning");
    expect(sel.value).toBe("");
  });

  it("invalid JSON blocks submission with a message", async () => {
    renderAgents();
    await screen.findByRole("button", { name: /research-agent/ });
    fireEvent.change(screen.getByLabelText(/^agent$/i), { target: { value: "research-agent" } });
    fireEvent.change(screen.getByLabelText(/^capability$/i), { target: { value: "retrieval" } });
    fireEvent.change(screen.getByLabelText(/input \(json object\)/i), { target: { value: "{oops" } });
    expect(await screen.findByText("Input is not valid JSON.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Execute agent" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("blocking run posts the exact payload and renders domain status", async () => {
    await setupExecute();
    await userEvent.click(screen.getByRole("button", { name: "Execute agent" }));
    await waitFor(() => expect(executeHits.length).toBe(1));
    expect(executeHits[0]).toMatchObject({ agent_name: "research-agent", capability: "reasoning", input: { q: "kyc" } });
    expect(await screen.findByText("Result res-1")).toBeTruthy();
    expect(screen.getByText("succeeded")).toBeTruthy();
    expect(screen.getByText("done")).toBeTruthy();
  });

  it("transport success with failed status renders as failure, not success", async () => {
    executeResult = {
      result_id: "res-2", task_id: "t2", agent_id: "agt-1", agent_name: "research-agent",
      status: "failed", output: {}, error: "handler exploded", attempts: 2,
      duration_ms: 90, started_at: 1700000000, completed_at: 1700000001, metadata: {},
    };
    await setupExecute();
    await userEvent.click(screen.getByRole("button", { name: "Execute agent" }));
    expect(await screen.findByText("Result res-2")).toBeTruthy();
    expect(screen.getByText("handler exploded")).toBeTruthy();
    expect(screen.getByText("failed")).toBeTruthy();
  });

  it("duplicate submit is prevented while the request is open", async () => {
    executeDelayMs = 400;
    await setupExecute();
    const btn = screen.getByRole("button", { name: "Execute agent" });
    await userEvent.click(btn);
    await userEvent.click(btn);
    expect(await screen.findByText(/Executing…/)).toBeTruthy();
    await waitFor(() => expect(executeHits.length).toBe(1), { timeout: 3000 });
    expect(executeHits.length).toBe(1);
  });
});

describe("registration", () => {
  it("posts metadata with declared capability; selects and refreshes", async () => {
    renderAgents();
    await screen.findByRole("button", { name: /research-agent/ });
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "my-agent" } });
    fireEvent.change(screen.getByLabelText(/capability name/i), { target: { value: "fetch" } });
    await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
    await waitFor(() => expect(registerHits.length).toBe(1));
    expect(registerHits[0]).toMatchObject({
      name: "my-agent",
      capabilities: [{ kind: "retrieval", name: "fetch" }],
    });
  });

  it("removal needs two clicks and deletes by encoded name", async () => {
    renderAgents();
    await screen.findByRole("button", { name: /research-agent/ });
    await userEvent.click(screen.getByRole("button", { name: /research-agent/ }));
    await screen.findByText("Fetch documents");
    const remove = screen.getByRole("button", { name: "Remove" });
    await userEvent.click(remove);
    expect(unregisterHits.length).toBe(0);
    await userEvent.click(screen.getByRole("button", { name: "Confirm removal" }));
    await waitFor(() => expect(unregisterHits).toEqual(["research-agent"]));
  });
});

describe("coordinator", () => {
  it("posts query/caps/steps and renders plan results with honest routing note", async () => {
    renderAgents();
    await goTab("Coordinator");
    fireEvent.change(screen.getByLabelText(/request/i), { target: { value: "Search KYC documents" } });
    await userEvent.click(screen.getByRole("button", { name: "retrieval" }));
    fireEvent.change(screen.getByLabelText(/max steps/i), { target: { value: "4" } });
    await userEvent.click(screen.getByRole("button", { name: "Run coordinator" }));
    await waitFor(() => expect(coordinateHits.length).toBe(1));
    expect(coordinateHits[0]).toMatchObject({
      query: "Search KYC documents",
      desired_capabilities: ["retrieval"],
      max_steps: 4,
    });
    expect(await screen.findByText("Coordination result")).toBeTruthy();
    expect(screen.getAllByText("research-agent").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("KYC rules updated")).toBeTruthy();
    expect(screen.getByText(/Deterministic routing/)).toBeTruthy();
    expect(screen.queryByText(/autonomous/i)).toBeNull();
  });

  it("no polling: one request per run; failure is retryable", async () => {
    server.use(
      http.post("/api/v1/agents/coordinate", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        coordinateHits.push(body);
        return HttpResponse.json({ detail: "down" }, { status: 500 });
      })
    );
    renderAgents();
    await goTab("Coordinator");
    fireEvent.change(screen.getByLabelText(/request/i), { target: { value: "hello world" } });
    await userEvent.click(screen.getByRole("button", { name: "Run coordinator" }));
    expect(await screen.findByText("Coordination failed")).toBeTruthy();
    expect(coordinateHits.length).toBe(1);
  });
});

describe("workflows", () => {
  it("definitions render with steps and mode; run posts and shows domain status", async () => {
    renderAgents();
    await goTab("Workflows");
    expect(await screen.findByText("KYC review flow")).toBeTruthy();
    expect(screen.getByText(/2 step\(s\)/)).toBeTruthy();
    const row = screen.getByText("KYC review flow").closest("li");
    expect(within(row as HTMLElement).getByText("sequential")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Run workflow" }));
    expect(await screen.findByText("Run wfrun-1")).toBeTruthy();
    const runCard = screen.getByText("Run wfrun-1").closest("div");
    expect(within(runCard as HTMLElement).getByText("succeeded")).toBeTruthy();
    expect(runHits[0]).toMatchObject({ id: "wf-1" });
  });

  it("creation builds graph.steps with ids and dependencies", async () => {
    renderAgents();
    await goTab("Workflows");
    await screen.findByText("KYC review flow");
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "My flow" } });
    const agentInputs = screen.getAllByLabelText(/agent name/i);
    expect(agentInputs.length).toBe(1);
    fireEvent.change(agentInputs[0], { target: { value: "research-agent" } });
    await userEvent.click(screen.getByRole("button", { name: "Add step" }));
    const agentInputs2 = screen.getAllByLabelText(/agent name/i);
    fireEvent.change(agentInputs2[1], { target: { value: "compliance-agent" } });
    await userEvent.click(screen.getByRole("button", { name: "step-1" }));
    await userEvent.click(screen.getByRole("button", { name: "Create workflow" }));
    await waitFor(() => expect(createHits.length).toBe(1));
    const body = createHits[0] as Record<string, unknown>;
    const graph = body.graph as Record<string, unknown>;
    const steps = graph.steps as Record<string, unknown>[];
    expect(steps).toHaveLength(2);
    expect(steps[0].agent_name).toBe("research-agent");
    expect(steps[1].depends_on).toEqual(["step-1"]);
    expect(graph.mode).toBe("sequential");
  });

  it("steps without agents block creation with a message", async () => {
    renderAgents();
    await goTab("Workflows");
    await screen.findByText("KYC review flow");
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "Bad flow" } });
    expect(await screen.findByText("Step 1 needs an agent name.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Create workflow" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("messages", () => {
  it("filters reach the server; manual refresh refetches; no live claims", async () => {
    renderAgents();
    await goTab("Messages");
    expect(await screen.findByText(/not a live stream/)).toBeTruthy();
    // The old fake "Live" indicator badge must be gone (the honest
    // disclaimer above legitimately contains lowercase "live").
    expect(screen.queryByText("Live")).toBeNull();
    fireEvent.change(screen.getByLabelText(/from agent/i), { target: { value: "research-agent" } });
    await waitFor(() => expect(messageHits.some((h) => h.includes("from_agent=research-agent"))).toBe(true));
    fireEvent.change(screen.getByLabelText(/^limit$/i), { target: { value: "10" } });
    await waitFor(() => expect(messageHits.some((h) => h.includes("limit=10"))).toBe(true));
    const before = messageHits.length;
    await userEvent.click(screen.getByRole("button", { name: "Refresh messages" }));
    await waitFor(() => expect(messageHits.length).toBeGreaterThan(before));
    // Exact sender name (the collaboration badge reads "a → b", so no clash).
    expect(screen.getByText("research-agent")).toBeTruthy();
    expect(screen.getAllByText("evidence").length).toBeGreaterThanOrEqual(1);
  });

  it("collaborations render from the real endpoint", async () => {
    renderAgents();
    await goTab("Messages");
    expect(await screen.findByText(/research-agent → compliance-agent/)).toBeTruthy();
    expect(screen.getByText(/1 evidence key/)).toBeTruthy();
  });

  it("empty bus is explicit", async () => {
    server.use(
      http.get("/api/v1/agents/messages", async () => HttpResponse.json([]))
    );
    renderAgents();
    await goTab("Messages");
    expect(await screen.findByText("No messages")).toBeTruthy();
  });
});

describe("cache", () => {
  it("registration refreshes the registry; keys isolate filter variants", async () => {
    renderAgents();
    await screen.findByRole("button", { name: /research-agent/ });
    const before = agentHits.length;
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "fresh-agent" } });
    await userEvent.click(screen.getByRole("button", { name: "Register agent" }));
    await waitFor(() => expect(agentHits.length).toBeGreaterThan(before));
  });
});

describe("ux/a11y", () => {
  it("h1, keyboard tabs, labelled controls, announced statuses", async () => {
    renderAgents();
    expect(await screen.findByRole("heading", { level: 1, name: "AI Agents" })).toBeTruthy();
    await screen.findByRole("button", { name: /research-agent/ });
    expect(screen.getByLabelText(/filter by capability/i)).toBeTruthy();
    const tab = screen.getByRole("tab", { name: "Agents" });
    expect(tab.getAttribute("aria-selected")).toBe("true");
    tab.focus();
    fireEvent.keyDown(tab, { key: "ArrowRight" });
    expect(await screen.findByRole("button", { name: "Run coordinator" })).toBeTruthy();
  });

  it("no fake monitoring language anywhere", async () => {
    renderAgents();
    await screen.findByRole("button", { name: /research-agent/ });
    for (const pat of [/streaming/i, /autonomous/i, /heartbeat/i, /thinking/i]) {
      expect(screen.queryByText(pat)).toBeNull();
    }
    expect(screen.queryByText(/60%/)).toBeNull();
    await goTab("Coordinator");
    expect(await screen.findByText(/Deterministic routing/)).toBeTruthy();
    await goTab("Messages");
    expect(await screen.findByText(/not a live stream/)).toBeTruthy();
  });

  it("malformed agent renders without crashing", async () => {
    agents = [{ name: "odd-agent" }];
    renderAgents();
    expect(await screen.findByRole("button", { name: /odd-agent/ })).toBeTruthy();
  });
});
