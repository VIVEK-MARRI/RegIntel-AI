/* hero3d/config.js — single source of tunables. No magic numbers elsewhere.
   Colors resolve from --h3d-* page tokens (hex fallbacks only). */

export function readTokens(container) {
    const cs = getComputedStyle(container);
    const get = (name, fallback) => {
        const v = cs.getPropertyValue(name).trim();
        return v || fallback;
    };
    return {
        ink: get("--h3d-ink", "#11141B"),
        surface: get("--h3d-surface", "#1A1F26"),
        ivory: get("--h3d-ivory", "#F1ECE0"),
        muted: get("--h3d-muted", "#C9C2AE"),
        faint: get("--h3d-faint", "#8E8773"),
        brass: get("--h3d-brass", "#B88840"),
        brassLight: get("--h3d-brass-light", "#D4B377"),
        verify: get("--h3d-verify", "#5FA886"),
        serif: get("--h3d-serif", "'Spectral', Georgia, serif").replace(/^['"]|['"]$/g, ""),
        sans: get("--h3d-sans", "'Inter', system-ui, sans-serif").replace(/^['"]|['"]$/g, ""),
        mono: get("--h3d-mono", "'IBM Plex Mono', monospace").replace(/^['"]|['"]$/g, ""),
    };
}

export const CONFIG = {
    camera: { fov: 34, pos: [0.3, 0.2, 11], look: [0.3, -0.1, 0] },
    fog: { near: 10, far: 22 },
    toneMappingExposure: 0.95,
    loopSeconds: 18,
    tiers: {
        // keyed by CONTAINER width (the scene degrades with its own box)
        full: { minWidth: 640, docs: 6, bgParticles: 70, dpr: 1.75, hover: true, parallax: 1.0, msaa: true },
        tablet: { minWidth: 400, docs: 4, bgParticles: 60, dpr: 1.5, hover: false, parallax: 0.5, msaa: false },
        mobile: { minWidth: 0, docs: 3, bgParticles: 40, dpr: 1.0, hover: false, parallax: 0.0, msaa: false },
    },
    mobileLoopSeconds: 12,
    parallax: { yawDeg: 3.5, pitchDeg: 2.0, smoothing: 0.045 },
    core: {
        pos: [0.7, -0.1, 0.2],
        plates: 6, plateW: 2.0, plateH: 2.6, plateD: 0.03,
        plateGap: 0.22, twistDeg: 4, yawAmpDeg: 14, yawPeriod: 40,
        innerParticles: 24,
    },
    answerPlane: { pos: [0.95, -0.95, 1.05], rotYDeg: -6, w: 1.55, h: 0.95 },
    docs: [
        { id: "A", head: "RBI", title: "MASTER DIRECTION", meta: "KYC · § 4.2", pos: [-2.0, 1.25, -0.8], rotY: 24, rotZ: -3, w: 1.45, h: 2.05, role: "selected" },
        { id: "B", head: "SEBI", title: "CIRCULAR", meta: "REV 03", pos: [2.35, 1.6, -1.6], rotY: -20, rotZ: 4, w: 1.3, h: 1.84, role: "rank3" },
        { id: "C", head: "AMENDMENT", title: "REV 03", meta: "SCHED II", pos: [-2.6, -1.55, -2.2], rotY: 28, rotZ: 5, w: 1.3, h: 1.84, role: "far" },
        { id: "D", head: "RBI", title: "CIRCULAR", meta: "§ 38", pos: [0.9, 0.2, -2.0], rotY: -8, rotZ: 0, w: 1.5, h: 2.1, role: "rank2" },
        { id: "E", head: "SEBI", title: "MASTER CIRCULAR", meta: "KYC", pos: [2.6, -1.4, -0.5], rotY: -26, rotZ: -3, w: 1.2, h: 1.7, role: "edge" },
        { id: "F", head: "", title: "", meta: "Annex II", pos: [-0.4, 2.3, -3.6], rotY: 10, rotZ: 2, w: 0.9, h: 1.27, role: "far" },
    ],
    selection: { pos: [-1.35, 0.55, 1.5], rotYDeg: 8, scale: 1.0, edgeOpacity: 0.85, dimOthers: 0.65 },
    streams: { queryN: 36, branchN: 20, queryFrom: [-2.7, 0.4, 0.6] },
    trace: { tubeRadius: 0.007, holdOpacity: 0.7 },
    verify: { confidencePct: 94, barWidthPx: 88 },
    sequences: [
        { source: "rbi-kyc", chip: "§ 38 · ¶ 2" },
        { source: "sebi-circ", chip: "§ 12 · ¶ 4" },
    ],
    budgets: { drawCalls: 60, triangles: 60000, textures: 10, particles: 180, jsGzipKb: 250 },
};
