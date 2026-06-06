import { Card, CardHeader } from "@/components/ui/Card";
import { Field, Input, Select } from "@/components/ui/Field";
import { useTheme } from "@/providers/ThemeProvider";
import { useState } from "react";

export function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState("/api/v1");
  const [density, setDensity] = useState("comfortable");

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <header>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Settings
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Personal preferences and connection details.
        </p>
      </header>

      <Card padding="none">
        <CardHeader title="Appearance" description="Theme and layout density" />
        <div className="card-body space-y-3">
          <Field label="Theme" id="settings-theme">
            <Select
              id="settings-theme"
              value={theme}
              onChange={(e) => setTheme(e.target.value as "light" | "dark")}
            >
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </Select>
          </Field>
          <Field label="Density" id="settings-density">
            <Select
              id="settings-density"
              value={density}
              onChange={(e) => setDensity(e.target.value)}
            >
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
            </Select>
          </Field>
        </div>
      </Card>

      <Card padding="none">
        <CardHeader title="API" description="Connection settings" />
        <div className="card-body space-y-3">
          <Field
            label="API base URL"
            id="settings-api-base"
            hint="The frontend proxies /api to the backend during development."
          >
            <Input
              id="settings-api-base"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
            />
          </Field>
          <Field
            label="API key"
            id="settings-api-key"
            hint="Stored locally in your browser. Used for authenticated requests."
          >
            <Input
              id="settings-api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="••••••••"
            />
          </Field>
        </div>
      </Card>

      <Card padding="none">
        <CardHeader
          title="About"
          description="RegIntel AI — Regulatory Intelligence Platform"
        />
        <div className="card-body text-sm text-slate-600 dark:text-slate-300">
          <p>Version 10.0.0 — User Experience Platform (M10.1 + M10.2)</p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Front-end built with React, TypeScript, Vite, Tailwind, TanStack
            Query, and Recharts.
          </p>
        </div>
      </Card>
    </div>
  );
}
