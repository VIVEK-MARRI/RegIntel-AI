import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, beforeAll, vi } from "vitest";

// Async utilities (findBy*, waitFor) default to 1000ms, which flakes under
// parallel workers on loaded machines. 5000ms keeps failure detection fast
// while tolerating CI-style contention. Test infrastructure only.
configure({ asyncUtilTimeout: 5000 });

beforeAll(() => {
  // jsdom doesn't implement matchMedia / ResizeObserver by default.
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  // Stub scrollTo for components that auto-scroll.
  HTMLElement.prototype.scrollTo = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();

  // Recharts ResponsiveContainer relies on getBoundingClientRect + ResizeObserver.
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

afterEach(() => {
  cleanup();
});
