import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { Sidebar } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { AuthProvider } from "@/providers/AuthProvider";

// Prevent AuthProvider from making real network calls during test
vi.mock("@/services/api/authApi", () => ({
  refreshToken: vi.fn().mockRejectedValue(new Error("no refresh token")),
  login: vi.fn(),
}));

function renderWithRouter(ui: React.ReactNode) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route path="*" element={ui} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </ThemeProvider>
  );
}

describe("AppShell accessibility", () => {
  it("Sidebar exposes a complementary landmark", () => {
    renderWithRouter(<Sidebar collapsed={false} />);
    expect(
      screen.getByRole("complementary", { name: /primary navigation/i })
    ).toBeInTheDocument();
  });

  it("Sidebar collapsed hides labels but keeps landmark", () => {
    renderWithRouter(<Sidebar collapsed={true} />);
    // Brand title hidden when collapsed
    expect(screen.queryByText(/RegIntel AI/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("complementary", { name: /primary navigation/i })
    ).toBeInTheDocument();
  });

  it("Sidebar links point to existing routes", () => {
    renderWithRouter(<Sidebar collapsed={false} />);
    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/");
    expect(hrefs).toContain("/copilot");
    expect(hrefs).toContain("/research");
    expect(hrefs).toContain("/compliance");
    expect(hrefs).toContain("/settings");
    // Role-gated links (agents, governance, audit, admin) are hidden
    // when no user is authenticated — tested in auth integration tests
  });
});
