/**
 * Stage 04 shell tests: observable navigation/drawer/role/health behavior.
 * MSW serves health + auth; viewports are controlled via matchMedia stubs.
 */
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/providers/AuthProvider";
import { HealthProvider } from "@/providers/HealthProvider";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { Shell } from "@/components/layout/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import { CopilotPage } from "@/pages/CopilotPage";
import { setAccessToken } from "@/lib/auth-token";
import { setAuthHandler } from "@/lib/api";

const server = setupServer(
  http.post("/api/v1/security/auth/refresh", async () => {
    return HttpResponse.json({
      access_token: "acc-r1",
      refresh_token: "ref-r1",
      token_type: "Bearer",
      expires_in: 3600,
      access_expires_at: "x",
      refresh_expires_at: "y",
    });
  }),
  http.get("/api/v1/security/auth/me", async () => {
    return HttpResponse.json({ subject_id: "u-1", roles: ["analyst"], scopes: [], permissions: [] });
  }),
  http.get("/health/ready", async () => {
    return HttpResponse.json({ status: "healthy", checks: {} });
  }),
  http.get("/api/v1/copilot/health", async () => {
    return HttpResponse.json({ status: "ok", module: "copilot" });
  }),
  http.get("/api/v1/conversations", async () => {
    return HttpResponse.json({
      items: [
        {
          conversation_id: "conv-1",
          title: "KYC review",
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
      page_size: 20,
    });
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
beforeEach(() => {
  localStorage.clear();
  setAccessToken(null);
  setAuthHandler(null);
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function setViewport(desktop: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: desktop ? query.includes("min-width: 1024px") : false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

function seedSession() {
  localStorage.setItem("regintel_refresh_token", "ref-old");
}

function meAs(roles: string[]) {
  server.use(
    http.get("/api/v1/security/auth/me", async () => {
      return HttpResponse.json({ subject_id: "u-1", roles, scopes: [], permissions: [] });
    })
  );
}

function renderShell(initialPath = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <ToastProvider>
          <HealthProvider>
            <MemoryRouter initialEntries={[initialPath]}>
              <AuthProvider>
                <Shell>
                  <Routes>
                    <Route
                      path="*"
                      element={
                        <ProtectedRoute>
                          <span>page-body</span>
                        </ProtectedRoute>
                      }
                    />
                  </Routes>
                </Shell>
              </AuthProvider>
            </MemoryRouter>
          </HealthProvider>

        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

async function loginAs(roles: string[]) {
  seedSession();
  meAs(roles);
}

describe("desktop sidebar", () => {
  it("1. sidebar renders all base links", async () => {
    setViewport(true);
    await loginAs(["analyst"]);
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    const nav = screen.getByRole("complementary", { name: "Primary navigation" });
    for (const label of ["Dashboard", "Copilot", "Research", "Documents", "Knowledge Graph", "Compliance", "Audit", "Analytics", "Settings"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeTruthy();
    }
  });

  it("2. collapse toggle works and persists", async () => {
    setViewport(true);
    await loginAs(["analyst"]);
    const user = userEvent.setup();
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    expect(screen.getByRole("link", { name: "Dashboard" }).textContent).toContain("Dashboard");
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(localStorage.getItem("regintel:sidebar-collapsed")).toBe("1");
    // icon-only: accessible name retained, visible label gone.
    const dashLink = screen.getByRole("link", { name: "Dashboard" });
    expect(dashLink.textContent).not.toContain("Dashboard");
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(localStorage.getItem("regintel:sidebar-collapsed")).toBe("0");
    expect(screen.getByRole("link", { name: "Dashboard" }).textContent).toContain("Dashboard");
  });

  it("3. collapsed links keep accessible names", async () => {
    setViewport(true);
    localStorage.setItem("regintel:sidebar-collapsed", "1");
    await loginAs(["admin"]);
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    expect(screen.getByRole("link", { name: "Admin" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "AI Agents" })).toBeTruthy();
  });
});

describe("mobile drawer", () => {
  it("4. hamburger opens the drawer on mobile", async () => {
    setViewport(false);
    await loginAs(["analyst"]);
    const user = userEvent.setup();
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    expect(screen.queryByRole("dialog", { name: "Primary navigation" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("dialog", { name: "Primary navigation" })).toBeTruthy();
  });

  it("5. close button closes the drawer", async () => {
    setViewport(false);
    await loginAs(["analyst"]);
    const user = userEvent.setup();
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(screen.queryByRole("dialog", { name: "Primary navigation" })).toBeNull();
  });

  it("6. backdrop closes the drawer", async () => {
    setViewport(false);
    await loginAs(["analyst"]);
    const user = userEvent.setup();
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("dialog", { name: "Primary navigation" })).toBeTruthy();
    await user.click(screen.getByTestId("nav-backdrop"));
    expect(screen.queryByRole("dialog", { name: "Primary navigation" })).toBeNull();
  });

  it("7. Escape closes the drawer", async () => {
    setViewport(false);
    await loginAs(["analyst"]);
    const user = userEvent.setup();
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("dialog", { name: "Primary navigation" })).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Primary navigation" })).toBeNull();
  });

  it("8. selecting navigation closes the drawer and navigates", async () => {
    setViewport(false);
    await loginAs(["analyst"]);
    const user = userEvent.setup();
    renderShell("/audit");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    const dialog = screen.getByRole("dialog", { name: "Primary navigation" });
    await user.click(within(dialog).getByRole("link", { name: "Compliance" }));
    expect(screen.queryByRole("dialog", { name: "Primary navigation" })).toBeNull();
    expect(screen.getByRole("link", { name: "Compliance" }).getAttribute("aria-current")).toBe("page");
  });
});

describe("active routes", () => {
  it("9. exact route is active without marking siblings", async () => {
    setViewport(true);
    await loginAs(["analyst"]);
    renderShell("/compliance");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    const nav = screen.getByRole("complementary", { name: "Primary navigation" });
    expect(within(nav).getByRole("link", { name: "Compliance" }).getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: "Dashboard" }).getAttribute("aria-current")).toBeNull();
  });

  it("10. nested /copilot/:id activates Copilot", async () => {
    setViewport(true);
    await loginAs(["analyst"]);
    renderShell("/copilot/conv-123");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    expect(screen.getByRole("link", { name: "Copilot" }).getAttribute("aria-current")).toBe("page");
  });

  it("11. nested /research/:id activates Research", async () => {
    setViewport(true);
    await loginAs(["analyst"]);
    renderShell("/research/rpt-9");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    expect(screen.getByRole("link", { name: "Research" }).getAttribute("aria-current")).toBe("page");
  });
});

describe("role visibility", () => {
  async function linksFor(roles: string[]) {
    setViewport(true);
    await loginAs(roles);
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    const nav = screen.getByRole("complementary", { name: "Primary navigation" });
    return within(nav)
      .getAllByRole("link")
      .map((l) => l.getAttribute("aria-label") ?? l.textContent);
  }

  it("13. viewer sees base links only", async () => {
    const labels = await linksFor(["viewer"]);
    expect(labels).toContain("Dashboard");
    expect(labels).not.toContain("AI Agents");
    expect(labels).not.toContain("Admin");
  });

  it("14. analyst sees Agents (guard parity) but not Admin", async () => {
    const labels = await linksFor(["analyst"]);
    expect(labels).toContain("Copilot");
    expect(labels).toContain("AI Agents");
    expect(labels).not.toContain("Admin");
  });

  it("15. operator sees Agents but not Admin", async () => {
    const labels = await linksFor(["operator"]);
    expect(labels).toContain("AI Agents");
    expect(labels).not.toContain("Admin");
  });

  it("16. auditor sees base links only", async () => {
    const labels = await linksFor(["auditor"]);
    expect(labels).toContain("Audit");
    expect(labels).not.toContain("AI Agents");
    expect(labels).not.toContain("Admin");
  });

  it("17. admin sees everything", async () => {
    const labels = await linksFor(["admin"]);
    expect(labels).toContain("AI Agents");
    expect(labels).toContain("Admin");
  });
});

describe("account menu", () => {
  it("18. menu shows identity and only real actions", async () => {
    setViewport(true);
    await loginAs(["analyst"]);
    const user = userEvent.setup();
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    await user.click(screen.getByRole("button", { name: /Account menu for/ }));
    const menu = screen.getByRole("menu", { name: "Account" });
    expect(within(menu).getByRole("menuitem", { name: "Sign out" })).toBeTruthy();
    expect(within(menu).queryByRole("menuitem", { name: "Profile" })).toBeNull();
    expect(within(menu).queryByRole("menuitem", { name: "API Keys" })).toBeNull();
    expect(within(menu).queryByRole("menuitem", { name: "Activity Log" })).toBeNull();
  });

  it("19 + 23. sign out delegates to AuthProvider and lands on login", async () => {
    setViewport(true);
    await loginAs(["analyst"]);
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ToastProvider>
            <HealthProvider>
              <MemoryRouter initialEntries={["/"]}>
                <AuthProvider>
                  <Routes>
                    <Route path="/login" element={<LoginPage />} />
                    <Route
                      path="*"
                      element={
                        <Shell>
                          <Routes>
                            <Route
                              path="*"
                              element={
                                <ProtectedRoute>
                                  <span>page-body</span>
                                </ProtectedRoute>
                              }
                            />
                          </Routes>
                        </Shell>
                      }
                    />
                  </Routes>
                </AuthProvider>
              </MemoryRouter>
            </HealthProvider>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>
    );
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    await user.click(screen.getByRole("button", { name: /Account menu for/ }));
    await user.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(await screen.findByLabelText("Email")).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Primary navigation" })).toBeNull();
    expect(localStorage.getItem("regintel_refresh_token")).toBeNull();
  });
});

describe("health status", () => {
  it("20. pill reflects healthy / degraded / unavailable", async () => {
    setViewport(true);
    await loginAs(["analyst"]);
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    expect(await screen.findByText("Operational")).toBeTruthy();

    server.use(
      http.get("/health/ready", async () => {
        return HttpResponse.json({ status: "degraded", checks: {} });
      })
    );
    // force a refetch by remounting with a fresh client
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ToastProvider>
            <HealthProvider>
              <MemoryRouter initialEntries={["/"]}>
                <AuthProvider>
                  <Shell>
                    <span>second-shell</span>
                  </Shell>
                </AuthProvider>
              </MemoryRouter>
            </HealthProvider>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>
    );
    expect(await screen.findByText("Degraded")).toBeTruthy();
  });

  it("20b. backend outage shows Unavailable", async () => {
    setViewport(true);
    await loginAs(["analyst"]);
    server.use(
      http.get("/health/ready", async () => {
        return HttpResponse.json({ detail: "down" }, { status: 500 });
      }),
      http.get("/health/live", async () => {
        return HttpResponse.json({ detail: "down" }, { status: 500 });
      })
    );
    renderShell("/");
    await waitFor(() => expect(screen.getByText("page-body")).toBeTruthy());
    expect(await screen.findByText("Unavailable")).toBeTruthy();
  });
});

describe("auth-shell interaction", () => {
  it("21. bootstrap shows splash, not navigation", async () => {
    setViewport(true);
    localStorage.setItem("regintel_refresh_token", "ref-old");
    renderShell("/");
    expect(screen.getByText("Loading workspace…")).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Primary navigation" })).toBeNull();
    expect(await screen.findByText("page-body")).toBeTruthy();
  });

  it("22. unauthenticated unknown path goes to login without shell", async () => {
    setViewport(true);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ToastProvider>
            <HealthProvider>
              <MemoryRouter initialEntries={["/nope"]}>
                <AuthProvider>
                  <Routes>
                    <Route path="/login" element={<LoginPage />} />
                    <Route
                      path="*"
                      element={
                        <Shell>
                          <Routes>
                            <Route
                              path="*"
                              element={
                                <ProtectedRoute>
                                  <span>page-body</span>
                                </ProtectedRoute>
                              }
                            />
                          </Routes>
                        </Shell>
                      }
                    />
                  </Routes>
                </AuthProvider>
              </MemoryRouter>
            </HealthProvider>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>
    );
    // Mirrors App.tsx: /login lives outside the shell, so the shell unmounts.
    expect(await screen.findByLabelText("Email")).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Primary navigation" })).toBeNull();
  });
});

describe("copilot mobile sessions", () => {
  it("24. mobile trigger opens the same session list and navigates", async () => {
    setViewport(false);
    await loginAs(["analyst"]);
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ToastProvider>
            <HealthProvider>
              <MemoryRouter initialEntries={["/copilot"]}>
                <AuthProvider>
                  <Routes>
                    <Route path="/copilot" element={<CopilotPage />} />
                    <Route path="/copilot/:conversationId" element={<span>at-conv</span>} />
                  </Routes>
                </AuthProvider>
              </MemoryRouter>
            </HealthProvider>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>
    );
    await user.click(screen.getByRole("button", { name: "Conversations" }));
    const dialog = await screen.findByRole("dialog", { name: "Conversations" });
    await user.click(within(dialog).getByRole("button", { name: /KYC review/ }));
    expect(await screen.findByText("at-conv")).toBeTruthy();
    expect(screen.queryByRole("dialog", { name: "Conversations" })).toBeNull();
  });
});



