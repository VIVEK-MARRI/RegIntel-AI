import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, useTheme } from "@/providers/ThemeProvider";

function Probe() {
  const { theme, setTheme, toggle } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button onClick={() => setTheme("dark")} type="button">
        set-dark
      </button>
      <button onClick={toggle} type="button">
        toggle
      </button>
    </div>
  );
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  it("renders with default theme and persists changes", async () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>
    );
    const themeEl = screen.getByTestId("theme");
    expect(["light", "dark"]).toContain(themeEl.textContent);

    await userEvent.click(screen.getByText("set-dark"));
    expect(themeEl.textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(window.localStorage.getItem("regintel:theme")).toBe("dark");

    await userEvent.click(screen.getByText("toggle"));
    expect(themeEl.textContent).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("throws when used outside provider", () => {
    // Suppress error logging
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/useTheme must be used within/);
    spy.mockRestore();
  });
});
