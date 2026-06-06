import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { Sidebar } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/providers/ThemeProvider";

function renderWithRouter(ui: React.ReactNode) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="*" element={ui} />
        </Routes>
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
    expect(hrefs).toContain("/agents");
    expect(hrefs).toContain("/governance");
  });
});
