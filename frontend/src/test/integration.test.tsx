import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { ThemeProvider } from "@/providers/ThemeProvider";
import { ToastProvider } from "@/providers/ToastProvider";
import { ToastViewport } from "@/components/ui/ToastViewport";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } })
    )
  );
});

describe("App integration: routing + providers + viewport", () => {
  it("ToastViewport renders with region role and notification label", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ThemeProvider>
          <ToastProvider>
            <MemoryRouter>
              <ToastViewport />
            </MemoryRouter>
          </ToastProvider>
        </ThemeProvider>
      </QueryClientProvider>
    );
    expect(
      screen.getByRole("region", { name: /notifications/i })
    ).toBeInTheDocument();
  });
});
