/**
 * Stage 17 hardening tests: the AppErrorBoundary keeps navigation alive when
 * a page crashes, shows no internals, and recovers on route change.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AppErrorBoundary } from "@/components/ui/ErrorBoundary";

function Bomb(): React.ReactNode {
  throw new Error("boom");
}

describe("AppErrorBoundary", () => {
  it("renders a localized fallback without internals when a child crashes", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <AppErrorBoundary resetKey="a">
        <Bomb />
      </AppErrorBoundary>
    );
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("Something went wrong on this page")).toBeTruthy();
    expect(screen.queryByText(/boom/)).toBeNull();
    expect(screen.queryByText(/at Bomb|Error:/)).toBeNull();
    expect(screen.getByRole("button", { name: "Reload application" })).toBeTruthy();
    spy.mockRestore();
  });

  it("recovers when the reset key changes", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(
      <AppErrorBoundary resetKey="a">
        <Bomb />
      </AppErrorBoundary>
    );
    expect(screen.getByText("Something went wrong on this page")).toBeTruthy();
    rerender(
      <AppErrorBoundary resetKey="b">
        <p>recovered content</p>
      </AppErrorBoundary>
    );
    expect(screen.getByText("recovered content")).toBeTruthy();
    expect(screen.queryByText("Something went wrong on this page")).toBeNull();
    spy.mockRestore();
  });

  it("reload button triggers a full application reload", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const reload = vi.fn();
    Object.defineProperty(window, "location", { value: { reload }, writable: true });
    render(
      <AppErrorBoundary resetKey="a">
        <Bomb />
      </AppErrorBoundary>
    );
    await userEvent.click(screen.getByRole("button", { name: "Reload application" }));
    expect(reload).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });
});
