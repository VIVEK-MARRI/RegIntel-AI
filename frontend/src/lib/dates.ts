/**
 * ONE deliberate date normalization strategy.
 *
 * Backend timestamp surfaces (verified against app/schemas/*):
 * - ISO-8601 strings: conversations, documents (uploaded_at/updated_at),
 *   chunks/pages, ingestion runs (started_at/finished_at), KG nodes/edges.
 * - Epoch SECONDS (float): admin users/roles, audit records/integrity,
 *   governance policies/decisions/stats, research (generated_at),
 *   forecasting, KG stats, analytics overviews.
 * - Epoch MILLISECONDS: none currently emitted, but accepted on input.
 *
 * Boundary rule: services/adapters normalize to epoch MILLISECONDS (number)
 * via `toMillis()` at the point of consumption. Pages never guess units.
 */
const SECOND_CUTOFF = 1e12; // below: epoch seconds → ×1000
const MS_CUTOFF = 1e15; // below: epoch millis as-is; above: assume millis

export function toMillis(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Date) {
    const t = value.getTime();
    return Number.isNaN(t) ? null : t;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    if (value < SECOND_CUTOFF) return Math.round(value * 1000);
    if (value < MS_CUTOFF) return Math.round(value);
    return Math.round(value);
  }
  if (typeof value === "string") {
    const s = value.trim();
    if (!s) return null;
    if (/^-?\d+(\.\d+)?$/.test(s)) return toMillis(Number(s));
    const t = Date.parse(s);
    return Number.isNaN(t) ? null : t;
  }
  return null;
}

/** Millis (or null) → relative label, delegating to the existing formatter. */
export function toRelative(
  value: unknown,
  format: (v: number | null | undefined) => string
): string {
  return format(toMillis(value));
}
