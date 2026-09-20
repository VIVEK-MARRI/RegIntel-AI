import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  // Sub-path serving: the SPA lives under /app (FastAPI-embedded and
  // nginx both serve it there). Override with SPA_BASE=/ for root
  // serving (e.g. Render static site via render.yaml).
  base: process.env.SPA_BASE ?? "/app/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    // Sourcemaps ship original TS sources to every browser — useful for
    // local debugging, an info leak in a public bundle. Enabled for dev
    // builds, disabled for production.
    sourcemap: process.env.NODE_ENV !== "production",
  },
});
