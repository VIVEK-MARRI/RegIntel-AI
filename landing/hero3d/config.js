/* hero3d/config.js (v3 rebuild) — single source of tunables.
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
    mobileLoopSeconds: 12,
    tiers: {
        full: { minWidth: 640, docs: 6, bgParticles: 70, dpr: 1.75, hover: true, parallax: 1.0, msaa: true },
        tablet: { minWidth: 400, docs: 4, bgParticles: 60, dpr: 1.5, hover: false, parallax: 0.5, msaa: false },
        mobile: { minWidth: 0, docs: 3, bgParticles: 40, dpr: 1.0, hover: false, parallax: 0.0, msaa: false },
    },
    parallax: { yawDeg: 3.5, pitchDeg: 2.0, smoothing: 0.045 },
    core: {
        pos: [0.55, -0.15, 0.0],
        outerR: 1.15, midR: 0.72, innerR: 0.3,
        // very slow counter-rotating facets (seconds per revolution)
        outerPeriod: 48, midPeriod: -36, innerPeriod: 24,
    },
    orbitals: {
        rings: [
            { r: 2.3, opacity: 0.1, tiltXDeg: 68, tiltYDeg: -12, period: 90 },
            { r: 3.0, opacity: 0.07, tiltXDeg: 74, tiltYDeg: 8, period: -120 },
        ],
        nodes: 3,
    },
    docs: [
        { id: "A", head: "RBI", title: "MASTER DIRECTION", meta: "KYC · § 4.2", pos: [-2.0, 1.25, -0.8], rotY: 24, rotZ: -3, w: 1.45, h: 2.05, sel: { pos: [-1.35, 0.55, 1.5], rotYDeg: 8 } },
        { id: "B", head: "SEBI", title: "CIRCULAR", meta: "REV 03", pos: [2.35, 1.6, -1.6], rotY: -20, rotZ: 4, w: 1.3, h: 1.84, sel: { pos: [2.0, 0.6, 1.35], rotYDeg: -8 } },
        { id: "C", head: "AMENDMENT", title: "REV 03", meta: "SCHED II", pos: [-2.6, -1.55, -2.2], rotY: 28, rotZ: 5, w: 1.3, h: 1.84 },
        { id: "D", head: "RBI", title: "CIRCULAR", meta: "§ 38", pos: [0.9, 0.35, -2.1], rotY: -8, rotZ: 0, w: 1.5, h: 2.1 },
        { id: "E", head: "SEBI", title: "MASTER CIRCULAR", meta: "KYC", pos: [2.6, -1.4, -0.5], rotY: -26, rotZ: -3, w: 1.2, h: 1.7 },
        { id: "F", head: "", title: "", meta: "Annex II", pos: [-0.4, 2.3, -3.6], rotY: 10, rotZ: 2, w: 0.9, h: 1.27 },
    ],
    selection: { scale: 1.06, edgeOpacity: 0.85, dimOthers: 0.65 },
    streams: { queryN: 30, branchN: 14, queryFrom: [-2.7, 0.4, 0.6] },
    trace: { tubeRadius: 0.006, holdOpacity: 0.9 },
    verify: { confidencePct: 94 },
    sequences: [
        { source: "rbi-kyc", chip: "§ 38 · ¶ 2" },
        { source: "sebi-circ", chip: "§ 12 · ¶ 4" },
    ],
    budgets: { drawCalls: 60, triangles: 60000, textures: 10, particles: 180, jsGzipKb: 250 },
};
