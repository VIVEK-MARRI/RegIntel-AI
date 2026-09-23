import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // jsdom + MSW suites flake under full parallel load on modest machines;
    // two workers keeps the gate deterministic without serializing everything.
    // Test infrastructure only — no product impact.
    poolOptions: {
      threads: { minThreads: 1, maxThreads: 2 },
      forks: { minForks: 1, maxForks: 2 },
    },
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx"],
    },
  },
});
