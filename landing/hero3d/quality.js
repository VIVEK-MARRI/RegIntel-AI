/* hero3d/quality.js — tiers + adaptive quality (step DOWN only, never up).
   Tiers key off container width so the scene degrades with its own box:
   full ≥640px · tablet 400–640px · mobile <400px. */
import { CONFIG } from "./config.js";

export function pickTier(container, force) {
    if (force) return force;
    const w = container.clientWidth || 600;
    if (w >= CONFIG.tiers.full.minWidth) return "full";
    if (w >= CONFIG.tiers.tablet.minWidth) return "tablet";
    return "mobile";
}

export function tierDocs(tier) {
    // full: all 6 · tablet: drop the two farthest (C, F) · mobile: A + B + D
    if (tier === "full") return [0, 1, 2, 3, 4, 5];
    if (tier === "tablet") return [0, 1, 3, 4];
    return [0, 1, 3];
}

export function createQualityMonitor() {
    const samples = [];
    let degraded = false;
    return {
        get degraded() { return degraded; },
        // rolling median of 60 frames; step down once past 24ms
        push(dtMs) {
            samples.push(dtMs);
            if (samples.length > 60) samples.shift();
            if (samples.length < 60 || degraded) return null;
            const sorted = [...samples].sort((a, b) => a - b);
            const median = sorted[30];
            if (median > 24) {
                degraded = true;
                return true;
            }
            return null;
        },
    };
}
