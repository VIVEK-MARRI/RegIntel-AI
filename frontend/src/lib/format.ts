/**
 * Display formatters used across the UI.
 */

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

const UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 60 * 60 * 24 * 365],
  ["month", 60 * 60 * 24 * 30],
  ["week", 60 * 60 * 24 * 7],
  ["day", 60 * 60 * 24],
  ["hour", 60 * 60],
  ["minute", 60],
  ["second", 1],
];

export function formatRelative(epochSeconds: number | string | Date | undefined | null): string {
  if (epochSeconds === undefined || epochSeconds === null) return "—";
  const ts =
    typeof epochSeconds === "number"
      ? epochSeconds * (epochSeconds < 1e12 ? 1000 : 1)
      : new Date(epochSeconds).getTime();
  if (!Number.isFinite(ts)) return "—";
  const diff = (ts - Date.now()) / 1000;
  const abs = Math.abs(diff);
  for (const [unit, secs] of UNITS) {
    if (abs >= secs || unit === "second") {
      return RELATIVE.format(Math.round(diff / secs), unit);
    }
  }
  return RELATIVE.format(0, "second");
}

export function formatPercent(value: number | undefined | null, fractionDigits = 0): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(fractionDigits)}%`;
}

export function formatNumber(value: number | undefined | null, fractionDigits = 0): string {
  if (value === undefined || value === null || !Number.isFinite(value)) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

export function formatDurationMs(ms: number | undefined | null): string {
  if (ms === undefined || ms === null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

export function formatDate(epochSeconds: number | string | Date | undefined | null): string {
  if (epochSeconds === undefined || epochSeconds === null) return "—";
  const ts =
    typeof epochSeconds === "number"
      ? epochSeconds * (epochSeconds < 1e12 ? 1000 : 1)
      : new Date(epochSeconds).getTime();
  if (!Number.isFinite(ts)) return "—";
  return new Date(ts).toLocaleString();
}

export function truncate(text: string | undefined | null, max = 200): string {
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1).trimEnd()}…`;
}

export function healthTone(level: string | undefined | null):
  | "success"
  | "warning"
  | "danger"
  | "neutral" {
  switch (level) {
    case "healthy":
      return "success";
    case "degraded":
      return "warning";
    case "unhealthy":
      return "danger";
    default:
      return "neutral";
  }
}
