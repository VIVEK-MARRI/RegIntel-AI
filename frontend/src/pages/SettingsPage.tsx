import { Card, CardHeader } from "@/components/ui/Card";
import { Field, Input, Select } from "@/components/ui/Field";
import { useTheme } from "@/providers/ThemeProvider";
import { useHealth } from "@/providers/HealthProvider";
import { useState } from "react";

export function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const health = useHealth();
  const [apiBase, setApiBase] = useState("/api/v1");
  const [apiKey, setApiKey] = useState("");
  const [density, setDensity] = useState("comfortable");

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Settings</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">Provider configuration, storage settings, system information, and feature flags.</p>
      </header>

      <Card padding="none">
        <CardHeader title="Provider Configuration" description="LLM and embedding provider settings" />
        <div className="card-body space-y-3">
          <Field label="LLM Provider" id="settings-llm" hint="Set via LLM_PROVIDER env var (openai, gemini, litellm, mock)">
            <Input id="settings-llm" value={import.meta.env.VITE_LLM_PROVIDER || "mock"} disabled />
          </Field>
          <Field label="Embedding Model" id="settings-embedding" hint="BAAI/bge-small-en-v1.5 (384-dim)">
            <Input id="settings-embedding" value="BAAI/bge-small-en-v1.5" disabled />
          </Field>
          <Field label="Reranker Model" id="settings-reranker" hint="BAAI/bge-reranker-base">
            <Input id="settings-reranker" value="BAAI/bge-reranker-base" disabled />
          </Field>
          <Field label="API Base URL" id="settings-api-base" hint="Backend API endpoint">
            <Input id="settings-api-base" value={apiBase} onChange={(e) => setApiBase(e.target.value)} />
          </Field>
          <Field label="API Key" id="settings-api-key" hint="Stored locally in your browser">
            <Input id="settings-api-key" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="••••••••" />
          </Field>
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Appearance" description="Theme and layout" />
        <div className="card-body space-y-3">
          <Field label="Theme" id="settings-theme">
            <Select id="settings-theme" value={theme} onChange={(e) => setTheme(e.target.value as "light" | "dark")}>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </Select>
          </Field>
          <Field label="Density" id="settings-density">
            <Select id="settings-density" value={density} onChange={(e) => setDensity(e.target.value)}>
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
            </Select>
          </Field>
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="System Information" description="Platform version and health" />
        <div className="card-body space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-slate-500">Version</span><span className="font-medium text-slate-900 dark:text-slate-100">{health.status?.version ?? "—"}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Status</span><span className={`font-medium ${health.isHealthy ? "text-emerald-600" : health.isDegraded ? "text-amber-600" : "text-red-600"}`}>{health.status?.status ?? "Unknown"}</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Uptime</span><span className="font-medium text-slate-900 dark:text-slate-100">{health.status?.uptime_seconds ? `${Math.round(health.status.uptime_seconds / 60)} min` : "—"}</span></div>
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Feature Flags" description="Runtime feature toggles" />
        <div className="card-body space-y-2 text-sm">
          {[
            { key: "LLM_PROVIDER", value: import.meta.env.VITE_LLM_PROVIDER || "mock" },
            { key: "AUTH_ENABLED", value: import.meta.env.VITE_AUTH_ENABLED ?? "true" },
            { key: "RERANKER_ENABLED", value: import.meta.env.VITE_RERANKER_ENABLED ?? "true" },
          ].map((f) => (
            <div key={f.key} className="flex justify-between">
              <span className="font-mono text-[11px] text-slate-500">{f.key}</span>
              <span className="text-slate-900 dark:text-slate-100">{f.value}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="Storage" description="Data persistence" />
        <div className="card-body space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-slate-500">Document Storage</span><span className="text-slate-900 dark:text-slate-100">Local filesystem / pgvector</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Knowledge Graph</span><span className="text-slate-900 dark:text-slate-100">JSONL (storage/knowledge_graph/)</span></div>
          <div className="flex justify-between"><span className="text-slate-500">Audit Trail</span><span className="text-slate-900 dark:text-slate-100">JSONL (storage/audit/)</span></div>
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="About" />
        <div className="card-body text-sm text-slate-600 dark:text-slate-300">
          <p>RegIntel AI — Regulatory Intelligence Platform</p>
          <p className="mt-1 text-xs text-slate-500">Front-end built with React, TypeScript, Vite, Tailwind, and TanStack Query.</p>
        </div>
      </Card>
    </div>
  );
}
