import { describe, it, expect } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { ToastProvider, useToast } from "@/providers/ToastProvider";
import { ToastViewport } from "@/components/ui/ToastViewport";

function Probe() {
  const { push, dismiss, clear, toasts } = useToast();
  return (
    <div>
      <span data-testid="count">{toasts.length}</span>
      <button
        onClick={() => push({ title: "Hello", tone: "info", durationMs: 60000 })}
        type="button"
      >
        push
      </button>
      <button
        onClick={() => push({ title: "Long", tone: "info", durationMs: 60000 })}
        type="button"
      >
        push-long
      </button>
      <button
        onClick={() => {
          const id = push({ title: "Manual", tone: "warning", durationMs: 60000 });
          dismiss(id);
        }}
        type="button"
      >
        push-and-dismiss
      </button>
      <button onClick={clear} type="button">
        clear
      </button>
    </div>
  );
}

describe("ToastProvider", () => {
  it("adds, manually dismisses, and clears toasts (viewport visible)", () => {
    render(
      <ToastProvider>
        <Probe />
        <ToastViewport />
      </ToastProvider>
    );

    // Push a toast and verify it appears in the viewport
    act(() => {
      screen.getByText("push").click();
    });
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByTestId("count").textContent).toBe("1");

    // Push and immediately dismiss via the provider (Hello is still present)
    act(() => {
      screen.getByText("push-and-dismiss").click();
    });
    expect(screen.getByTestId("count").textContent).toBe("1");
    expect(screen.queryByText("Manual")).not.toBeInTheDocument();

    // Push a long-lived toast and clear all
    act(() => {
      screen.getByText("push-long").click();
    });
    expect(screen.getByTestId("count").textContent).toBe("2");
    act(() => {
      screen.getByText("clear").click();
    });
    expect(screen.getByTestId("count").textContent).toBe("0");
    expect(screen.queryByText("Long")).not.toBeInTheDocument();
    expect(screen.queryByText("Hello")).not.toBeInTheDocument();
  });
});
