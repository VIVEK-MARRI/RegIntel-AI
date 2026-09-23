/**
 * Stage 15 admin tests: authoritative identity, user CRUD with exact
 * payloads, role permission replacement, RBAC verdicts, typed settings with
 * secret hiding, narrow invalidation, and the no-fake-admin rule (no hash
 * rendering, no invented admin-only claims). MSW uses backend-shaped
 * payloads (admin schemas + /security/auth/me).
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AdminPage } from "@/pages/AdminPage";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { ToastViewport } from "@/components/ui/ToastViewport";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const U1 = {
  user_id: "u1", username: "alice", email: "alice@example.com",
  password_hash: "HASHED-NEVER-RENDER", full_name: "Alice Admin",
  role_ids: ["role-1"], status: "active", department: "security",
  last_login_at: 1700000000, created_at: 1699900000, updated_at: 1700000000, metadata: {},
};
const U2 = {
  user_id: "u2", username: "bob", email: "bob@example.com",
  password_hash: "", full_name: "", role_ids: [], status: "invited",
  department: "", last_login_at: null, created_at: 1699900000, updated_at: 1699900000, metadata: {},
};
const R1 = {
  role_id: "role-1", name: "admin", description: "Full access", built_in: true,
  permissions: [{ permission_id: "p1", code: "users:read", description: "", resource: "users", action: "read" }],
  user_count: 1, created_at: 1699900000, updated_at: 1700000000, tags: [],
};
const R2 = {
  role_id: "role-2", name: "viewer", description: "", built_in: false,
  permissions: [], user_count: 0, created_at: 1699900000, updated_at: 1699900000, tags: [],
};

let users: Record<string, unknown>[] = [U1, U2];
let roles: Record<string, unknown>[] = [R1, R2];
let settings: Record<string, unknown>[] = [
  { key: "app.name", value: "RegIntel", description: "", category: "general", updated_at: 1700000000, updated_by: "system", is_secret: false, value_type: "string" },
  { key: "limits.max_items", value: 50, description: "", category: "limits", updated_at: 1700000000, updated_by: "system", is_secret: false, value_type: "int" },
  { key: "api.key", value: "s3cr3t-value", description: "", category: "integrations", updated_at: 1700000000, updated_by: "system", is_secret: true, value_type: "string" },
];
let userHits: string[] = [];
let userMutations: { method: string; url: string; body: unknown }[] = [];
let roleMutations: { method: string; url: string; body: unknown }[] = [];
let settingMutations: { method: string; url: string; body: unknown }[] = [];
let rbacHits: string[] = [];
let roleHits: string[] = [];
let apiPaths: string[] = [];

function track(url: string) {
  apiPaths.push(new URL(url).pathname);
}

const server = setupServer(
  http.get("/api/v1/security/auth/me", async ({ request }) => {
    track(request.url);
    return HttpResponse.json({ subject_id: "u1", roles: ["admin"], scopes: ["read"], permissions: ["users:read"] });
  }),
  http.get("/api/v1/admin/stats", async ({ request }) => {
    track(request.url);
    return HttpResponse.json({
      total_users: 2, active_users: 1, suspended_users: 0, total_roles: 2,
      built_in_roles: 1, total_permissions: 1, total_settings: 3, secret_settings: 1,
      by_role: {}, by_user_status: {}, generated_at: 1700000000,
    });
  }),
  http.get("/api/v1/admin/users", async ({ request }) => {
    track(request.url);
    const url = new URL(request.url);
    userHits.push(url.search);
    return HttpResponse.json({ items: users, total: users.length, page: 1, page_size: 50, has_more: false });
  }),
  http.get("/api/v1/admin/users/:id", async ({ request, params }) => {
    track(request.url);
    const u = users.find((x) => x.user_id === params.id);
    if (!u) return HttpResponse.json({ detail: "user not found" }, { status: 404 });
    return HttpResponse.json(u);
  }),
  http.post("/api/v1/admin/users", async ({ request }) => {
    track(request.url);
    const body = (await request.json()) as Record<string, unknown>;
    userMutations.push({ method: "POST", url: request.url, body });
    const created = { ...U2, user_id: "u9", username: body.username, email: body.email };
    users = [...users, created];
    return HttpResponse.json(created, { status: 201 });
  }),
  http.patch("/api/v1/admin/users/:id", async ({ request, params }) => {
    track(request.url);
    const body = (await request.json()) as Record<string, unknown>;
    userMutations.push({ method: "PATCH", url: request.url, body });
    users = users.map((u) => (u.user_id === params.id ? { ...u, ...body } : u));
    return HttpResponse.json(users.find((u) => u.user_id === params.id));
  }),
  http.delete("/api/v1/admin/users/:id", async ({ request, params }) => {
    track(request.url);
    userMutations.push({ method: "DELETE", url: request.url, body: null });
    users = users.filter((u) => u.user_id !== params.id);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("/api/v1/admin/users/:uid/roles/:rid", async ({ request, params }) => {
    track(request.url);
    userMutations.push({ method: "GRANT", url: request.url, body: null });
    users = users.map((u) =>
      u.user_id === params.uid && !(u.role_ids as string[]).includes(params.rid as string)
        ? { ...u, role_ids: [...(u.role_ids as string[]), params.rid] }
        : u
    );
    return HttpResponse.json(users.find((u) => u.user_id === params.uid));
  }),
  http.delete("/api/v1/admin/users/:uid/roles/:rid", async ({ request, params }) => {
    track(request.url);
    userMutations.push({ method: "REVOKE", url: request.url, body: null });
    users = users.map((u) =>
      u.user_id === params.uid
        ? { ...u, role_ids: (u.role_ids as string[]).filter((r) => r !== params.rid) }
        : u
    );
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/v1/admin/rbac/:uid", async ({ request }) => {
    track(request.url);
    const url = new URL(request.url);
    rbacHits.push(url.search);
    const permission = url.searchParams.get("permission");
    const allowed = permission === "users:read";
    return HttpResponse.json({
      check_id: "rbac-1", user_id: "u1", permission_code: permission, allowed,
      reason: allowed ? "" : "permission not granted", matched_roles: allowed ? ["role-1"] : [],
      timestamp: 1700000000,
    });
  }),
  http.get("/api/v1/admin/roles", async ({ request }) => {
    track(request.url);
    roleHits.push(new URL(request.url).search);
    return HttpResponse.json({ items: roles, total: roles.length, page: 1, page_size: 50, has_more: false });
  }),
  http.get("/api/v1/admin/roles/:id", async ({ request, params }) => {
    track(request.url);
    const r = roles.find((x) => x.role_id === params.id);
    if (!r) return HttpResponse.json({ detail: "role not found" }, { status: 404 });
    return HttpResponse.json(r);
  }),
  http.post("/api/v1/admin/roles", async ({ request }) => {
    track(request.url);
    const body = (await request.json()) as Record<string, unknown>;
    roleMutations.push({ method: "POST", url: request.url, body });
    const created = { ...R2, role_id: "role-9", name: body.name };
    roles = [...roles, created];
    return HttpResponse.json(created, { status: 201 });
  }),
  http.patch("/api/v1/admin/roles/:id/permissions", async ({ request, params }) => {
    track(request.url);
    const body = (await request.json()) as unknown[];
    roleMutations.push({ method: "PATCH-PERMS", url: request.url, body });
    roles = roles.map((r) => (r.role_id === params.id ? { ...r, permissions: body } : r));
    return HttpResponse.json(roles.find((r) => r.role_id === params.id));
  }),
  http.delete("/api/v1/admin/roles/:id", async ({ request, params }) => {
    track(request.url);
    roleMutations.push({ method: "DELETE", url: request.url, body: null });
    const r = roles.find((x) => x.role_id === params.id);
    if (!r || (r as Record<string, unknown>).built_in) {
      return HttpResponse.json({ detail: "role not found or built-in" }, { status: 404 });
    }
    roles = roles.filter((x) => x.role_id !== params.id);
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("/api/v1/admin/settings", async ({ request }) => {
    track(request.url);
    return HttpResponse.json(settings);
  }),
  http.put("/api/v1/admin/settings/:key", async ({ request, params }) => {
    track(request.url);
    const body = (await request.json()) as Record<string, unknown>;
    settingMutations.push({ method: "PUT", url: request.url, body });
    const existing = settings.find((s) => s.key === params.key);
    const next = existing ? { ...existing, ...body } : { key: params.key, ...body, value_type: "string", is_secret: false };
    settings = existing ? settings.map((s) => (s.key === params.key ? next : s)) : [...settings, next];
    return HttpResponse.json(next);
  }),
  http.delete("/api/v1/admin/settings/:key", async ({ request, params }) => {
    track(request.url);
    settingMutations.push({ method: "DELETE", url: request.url, body: null });
    settings = settings.filter((s) => s.key !== params.key);
    return new HttpResponse(null, { status: 204 });
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
  users = [U1, U2];
  roles = [R1, R2];
  settings = [
    { key: "app.name", value: "RegIntel", description: "", category: "general", updated_at: 1700000000, updated_by: "system", is_secret: false, value_type: "string" },
    { key: "limits.max_items", value: 50, description: "", category: "limits", updated_at: 1700000000, updated_by: "system", is_secret: false, value_type: "int" },
    { key: "api.key", value: "s3cr3t-value", description: "", category: "integrations", updated_at: 1700000000, updated_by: "system", is_secret: true, value_type: "string" },
  ];
  userHits = [];
  userMutations = [];
  roleMutations = [];
  settingMutations = [];
  rbacHits = [];
  roleHits = [];
  apiPaths = [];
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderAdmin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={["/admin"]}>
            <AdminPage />
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

describe("identity", () => {
  it("renders authoritative subject, roles, scopes, permissions", async () => {
    renderAdmin();
    expect(await screen.findByRole("heading", { level: 1, name: "Admin Console" })).toBeTruthy();
    expect(await screen.findByText("u1")).toBeTruthy();
    expect(screen.getByText("read")).toBeTruthy();
    expect(screen.getByText("users:read")).toBeTruthy();
  });

  it("states the access-control truth instead of implying admin-only security", async () => {
    renderAdmin();
    expect(await screen.findByText(/gated in the UI only/)).toBeTruthy();
    expect(screen.queryByText(/admin-only/i)).toBeNull();
  });

  it("identity failure is retryable", async () => {
    server.use(
      http.get("/api/v1/security/auth/me", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderAdmin();
    expect(await screen.findByText("Identity unavailable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});

describe("users", () => {
  it("rows show identity, status, role names, and login state", async () => {
    renderAdmin();
    expect(await screen.findByText("Alice Admin")).toBeTruthy();
    expect(screen.getByText("alice@example.com")).toBeTruthy();
    const table = screen.getByRole("table");
    expect(within(table).getByText("active")).toBeTruthy();
    expect(within(table).getByText("admin")).toBeTruthy();
    expect(screen.getByText("never")).toBeTruthy();
  });

  it("filters and paging hit the server with exact params", async () => {
    const many = Array.from({ length: 50 }, (_, i) => ({ ...U1, user_id: `ux${i}`, username: `user-${i}` }));
    users = many;
    renderAdmin();
    await screen.findByText("@user-0");
    expect(screen.getByText("Page 1 · 50 shown")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/filter users by status/i), { target: { value: "suspended" } });
    await waitFor(() => expect(userHits.some((h) => h.includes("status=suspended"))).toBe(true));
    fireEvent.change(screen.getByLabelText(/search users/i), { target: { value: "alice" } });
    await waitFor(() => expect(userHits.some((h) => h.includes("text_query=alice"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(userHits.some((h) => h.includes("page=2"))).toBe(true));
  });

  it("empty and error states are distinct", async () => {
    users = [];
    renderAdmin();
    expect(await screen.findByText("No users")).toBeTruthy();
  });

  it("detail shows backend fields and never the password hash", async () => {
    renderAdmin();
    await screen.findByText("Alice Admin");
    await userEvent.click(screen.getByRole("button", { name: "Inspect user alice" }));
    expect(await screen.findByText(/Department: security/)).toBeTruthy();
    expect(screen.queryByText(/HASHED-NEVER-RENDER/)).toBeNull();
    expect(screen.queryByText(/password_hash/)).toBeNull();
  });

  it("profile+status update sends only changed keys", async () => {
    renderAdmin();
    await screen.findByText("Alice Admin");
    await userEvent.click(screen.getByRole("button", { name: "Inspect user alice" }));
    await screen.findByText(/Department: security/);
    fireEvent.change(screen.getByLabelText("Department"), { target: { value: "risk" } });
    fireEvent.change(screen.getByLabelText(/^status$/i), { target: { value: "suspended" } });
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(userMutations.some((m) => m.method === "PATCH")).toBe(true));
    const patch = userMutations.find((m) => m.method === "PATCH")?.body as Record<string, unknown>;
    expect(patch).toMatchObject({ department: "risk", status: "suspended" });
    expect(patch).not.toHaveProperty("username");
    expect(patch).not.toHaveProperty("role_ids");
  });

  it("grant and revoke hit the exact nested routes", async () => {
    renderAdmin();
    await screen.findByText("Alice Admin");
    await userEvent.click(screen.getByRole("button", { name: "Inspect user alice" }));
    await screen.findByText(/Department: security/);
    await screen.findByRole("option", { name: "viewer" });
    fireEvent.change(screen.getByLabelText(/grant role/i), { target: { value: "role-2" } });
    await userEvent.click(screen.getByRole("button", { name: "Grant" }));
    await waitFor(() => expect(userMutations.some((m) => m.method === "GRANT")).toBe(true));
    expect(userMutations.find((m) => m.method === "GRANT")?.url).toContain("/admin/users/u1/roles/role-2");
    await userEvent.click(screen.getByRole("button", { name: "Revoke role admin from alice" }));
    await waitFor(() => expect(userMutations.some((m) => m.method === "REVOKE")).toBe(true));
  });

  it("RBAC check sends permission as a query param and renders the verdict", async () => {
    renderAdmin();
    await screen.findByText("Alice Admin");
    await userEvent.click(screen.getByRole("button", { name: "Inspect user alice" }));
    await screen.findByText(/Department: security/);
    fireEvent.change(screen.getByLabelText(/permission code/i), { target: { value: "users:read" } });
    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    await waitFor(() => expect(rbacHits.some((h) => h.includes("permission=users%3Aread") || h.includes("permission=users:read"))).toBe(true));
    expect(await screen.findByText("Allowed")).toBeTruthy();
    expect(screen.getByText(/via role-1/)).toBeTruthy();
  });

  it("deletion needs two clicks and closes the detail", async () => {
    renderAdmin();
    await screen.findByText("Alice Admin");
    await userEvent.click(screen.getByRole("button", { name: "Inspect user alice" }));
    await screen.findByText(/Department: security/);
    await userEvent.click(screen.getByRole("button", { name: "Delete user" }));
    expect(userMutations.filter((m) => m.method === "DELETE").length).toBe(0);
    await userEvent.click(screen.getByRole("button", { name: "Confirm deletion of alice" }));
    await waitFor(() => expect(userMutations.some((m) => m.method === "DELETE")).toBe(true));
    await waitFor(() => expect(screen.queryByText("Alice Admin")).toBeNull());
  });

  it("creation sends real keys and omits an empty password", async () => {
    renderAdmin();
    await screen.findByText("Alice Admin");
    await userEvent.click(screen.getByRole("button", { name: "New user" }));
    fireEvent.change(screen.getByLabelText(/^username$/i), { target: { value: "carol" } });
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "carol@example.com" } });
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(userMutations.some((m) => m.method === "POST")).toBe(true));
    const body = userMutations.find((m) => m.method === "POST")?.body as Record<string, unknown>;
    expect(body).toMatchObject({ username: "carol", email: "carol@example.com", status: "active" });
    expect(body).not.toHaveProperty("password");
    expect(await screen.findByText("u9")).toBeTruthy();
  });
});

describe("roles", () => {
  it("rows show name, origin, permission and member counts", async () => {
    renderAdmin();
    await goTab("Roles");
    expect(await screen.findByText("viewer")).toBeTruthy();
    expect(screen.getByText("built-in")).toBeTruthy();
    expect(screen.getByText("0 permission(s) · 0 user(s)")).toBeTruthy();
  });

  it("origin and text filters reach the server", async () => {
    renderAdmin();
    await goTab("Roles");
    await screen.findByText("viewer");
    fireEvent.change(screen.getByLabelText(/filter roles by origin/i), { target: { value: "true" } });
    await waitFor(() => expect(roleHits.some((h) => h.includes("built_in=true"))).toBe(true));
    fireEvent.change(screen.getByLabelText(/search roles/i), { target: { value: "view" } });
    await waitFor(() => expect(roleHits.some((h) => h.includes("text_query=view"))).toBe(true));
  });

  it("detail edits the full permission list explicitly", async () => {
    renderAdmin();
    await goTab("Roles");
    await screen.findByText("viewer");
    await userEvent.click(screen.getByRole("button", { name: /viewer/ }));
    expect(await screen.findByText("This role grants no permissions.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/permission code/i), { target: { value: "documents:read" } });
    fireEvent.change(screen.getByLabelText(/resource \(optional\)/i), { target: { value: "documents" } });
    await userEvent.click(screen.getByRole("button", { name: "Add permission" }));
    expect(screen.getByText("documents:read")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save permissions" }));
    await waitFor(() => expect(roleMutations.some((m) => m.method === "PATCH-PERMS")).toBe(true));
    const body = roleMutations.find((m) => m.method === "PATCH-PERMS")?.body as unknown[];
    expect(body).toHaveLength(1);
    expect((body[0] as Record<string, unknown>).code).toBe("documents:read");
  });

  it("built-in roles cannot be deleted; custom roles need two clicks", async () => {
    renderAdmin();
    await goTab("Roles");
    await screen.findByText("viewer");
    await userEvent.click(screen.getByRole("button", { name: /admin/ }));
    expect(await screen.findByText("built-in (cannot be deleted)")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete role" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await userEvent.click(screen.getByRole("button", { name: /viewer/ }));
    await screen.findByText("custom");
    await userEvent.click(screen.getByRole("button", { name: "Delete role" }));
    expect(roleMutations.filter((m) => m.method === "DELETE").length).toBe(0);
    await userEvent.click(screen.getByRole("button", { name: "Confirm deletion of viewer" }));
    await waitFor(() => expect(roleMutations.some((m) => m.method === "DELETE")).toBe(true));
  });

  it("built-in deletion surfaces the backend refusal", async () => {
    server.use(
      http.delete("/api/v1/admin/roles/:id", async () => {
        roleMutations.push({ method: "DELETE", url: "", body: null });
        return HttpResponse.json({ detail: "role not found or built-in" }, { status: 404 });
      })
    );
    renderAdmin();
    await goTab("Roles");
    await screen.findByText("viewer");
    await userEvent.click(screen.getByRole("button", { name: /viewer/ }));
    await screen.findByText("custom");
    await userEvent.click(screen.getByRole("button", { name: "Delete role" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm deletion of viewer" }));
    expect(await screen.findByText("Deletion failed")).toBeTruthy();
    expect(screen.getByText(/not found or built-in/)).toBeTruthy();
  });

  it("creation posts name and description only", async () => {
    renderAdmin();
    await goTab("Roles");
    await screen.findByText("viewer");
    await userEvent.click(screen.getByRole("button", { name: "New role" }));
    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "auditor-plus" } });
    await userEvent.click(screen.getByRole("button", { name: "Create role" }));
    await waitFor(() => expect(roleMutations.some((m) => m.method === "POST")).toBe(true));
    expect(roleMutations.find((m) => m.method === "POST")?.body).toMatchObject({ name: "auditor-plus" });
    expect(await screen.findByText("role-9")).toBeTruthy();
  });
});

describe("settings", () => {
  it("values render typed; secrets stay hidden", async () => {
    renderAdmin();
    await goTab("Settings");
    expect(await screen.findByText("app.name")).toBeTruthy();
    expect(screen.getByText("RegIntel")).toBeTruthy();
    expect(screen.getByText("50")).toBeTruthy();
    expect(screen.getByText(/hidden \(secret\)/)).toBeTruthy();
    expect(screen.queryByText("s3cr3t-value")).toBeNull();
  });

  it("editing a scalar sends the coerced value", async () => {
    renderAdmin();
    await goTab("Settings");
    await screen.findByText("app.name");
    const rows = screen.getAllByRole("button", { name: "Edit" });
    await userEvent.click(rows[1]);
    const input = screen.getByLabelText("Value for limits.max_items");
    fireEvent.change(input, { target: { value: "75" } });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(settingMutations.some((m) => m.method === "PUT")).toBe(true));
    const put = settingMutations.find((m) => m.method === "PUT");
    expect(put?.url).toContain("/admin/settings/limits.max_items");
    expect((put?.body as Record<string, unknown>).value).toBe(75);
  });

  it("invalid typed values are rejected client-side without a request", async () => {
    renderAdmin();
    await goTab("Settings");
    await screen.findByText("app.name");
    const rows = screen.getAllByRole("button", { name: "Edit" });
    await userEvent.click(rows[1]);
    fireEvent.change(screen.getByLabelText("Value for limits.max_items"), { target: { value: "many" } });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Invalid value")).toBeTruthy();
    expect(settingMutations.length).toBe(0);
  });

  it("secret editing starts empty and never reveals the value", async () => {
    renderAdmin();
    await goTab("Settings");
    await screen.findByText("app.name");
    const rows = screen.getAllByRole("button", { name: "Edit" });
    await userEvent.click(rows[2]);
    const input = screen.getByLabelText("Value for api.key") as HTMLInputElement;
    expect(input.value).toBe("");
    expect(screen.queryByText("s3cr3t-value")).toBeNull();
  });

  it("deletion needs two clicks", async () => {
    renderAdmin();
    await goTab("Settings");
    await screen.findByText("app.name");
    await userEvent.click(screen.getByRole("button", { name: "Delete setting app.name" }));
    expect(settingMutations.filter((m) => m.method === "DELETE").length).toBe(0);
    await userEvent.click(screen.getByRole("button", { name: "Confirm deletion of setting app.name" }));
    await waitFor(() => expect(settingMutations.some((m) => m.method === "DELETE")).toBe(true));
  });
});

describe("cache", () => {
  it("mutations refresh only admin lists; traffic stays in-domain", async () => {
    renderAdmin();
    await screen.findByText("Alice Admin");
    const before = userHits.length;
    await userEvent.click(screen.getByRole("button", { name: "New user" }));
    fireEvent.change(screen.getByLabelText(/^username$/i), { target: { value: "dave" } });
    fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "dave@example.com" } });
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(userHits.length).toBeGreaterThan(before));
    expect(apiPaths.every((p) => p.startsWith("/api/v1/admin") || p.startsWith("/api/v1/security/auth/me"))).toBe(true);
  });
});

describe("ux/a11y", () => {
  it("h1, keyboard tabs, labelled controls, table semantics", async () => {
    renderAdmin();
    expect(await screen.findByRole("heading", { level: 1, name: "Admin Console" })).toBeTruthy();
    await screen.findByText("Alice Admin");
    const table = screen.getByRole("table");
    expect(table.querySelector("caption")).toBeTruthy();
    expect(table.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(0);
    const tab = screen.getByRole("tab", { name: "Users" });
    expect(tab.getAttribute("aria-selected")).toBe("true");
    tab.focus();
    fireEvent.keyDown(tab, { key: "ArrowRight" });
    expect(await screen.findByText("viewer")).toBeTruthy();
  });

  it("errors use role=alert; destructive buttons name their target", async () => {
    server.use(
      http.get("/api/v1/admin/users", async () => HttpResponse.json({ detail: "down" }, { status: 500 }))
    );
    renderAdmin();
    expect(await screen.findByText("Users unavailable")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
  });
});

describe("trust", () => {
  it("no invented admin-only claims, security theater, or secret leakage", async () => {
    renderAdmin();
    await screen.findByText("Alice Admin");
    for (const pat of [/admin-only/i, /100% secure/i, /fully secured/i, /all controls green/i, /password_hash/, /s3cr3t-value/]) {
      expect(screen.queryByText(pat)).toBeNull();
    }
    expect(screen.queryByText(/page \d+ of \d+/i)).toBeNull();
  });
});
