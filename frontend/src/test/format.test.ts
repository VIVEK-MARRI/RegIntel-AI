import { describe, it, expect, beforeEach } from "vitest";
import {
  formatRelative,
  formatPercent,
  formatNumber,
  formatDurationMs,
  formatDate,
  truncate,
  healthTone,
} from "@/lib/format";

describe("format utilities", () => {
  beforeEach(() => {
    // Pin "now" implicitly by using recent epoch values relative to Date.now().
  });

  it("formatPercent returns formatted percentage", () => {
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(0.123, 1)).toBe("12.3%");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(undefined)).toBe("—");
  });

  it("formatNumber returns localised number", () => {
    expect(formatNumber(1234.5)).toBe("1,235");
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(null)).toBe("—");
  });

  it("formatDurationMs handles sub-second and minute ranges", () => {
    expect(formatDurationMs(250)).toBe("250 ms");
    expect(formatDurationMs(1500)).toBe("1.50 s");
    expect(formatDurationMs(120_000)).toBe("2.0 min");
    expect(formatDurationMs(null)).toBe("—");
  });

  it("formatRelative handles past and future", () => {
    const now = Math.floor(Date.now() / 1000);
    expect(formatRelative(now - 30)).toMatch(/ago|second/);
    expect(formatRelative("2024-01-01T00:00:00Z")).not.toBe("—");
    expect(formatRelative(null)).toBe("—");
  });

  it("formatDate produces locale string", () => {
    expect(formatDate(0)).toMatch(/1970|1969/); // epoch may be 1969 in some TZs
    expect(formatDate(null)).toBe("—");
  });

  it("truncate preserves short strings and clips long ones", () => {
    expect(truncate("hi")).toBe("hi");
    expect(truncate("a".repeat(300), 100)).toMatch(/…$/);
    expect(truncate("")).toBe("");
    expect(truncate(null)).toBe("");
  });

  it("healthTone maps levels to badge tones", () => {
    expect(healthTone("healthy")).toBe("success");
    expect(healthTone("degraded")).toBe("warning");
    expect(healthTone("unhealthy")).toBe("danger");
    expect(healthTone("unknown")).toBe("neutral");
    expect(healthTone(undefined)).toBe("neutral");
  });
});
