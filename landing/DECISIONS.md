# DECISIONS.md — Hero v2 "Evidence Trace"

## 1. Inspection (STEP 0)

**Hero layout mechanism.** `.hero-inner` (max-width 1240px, centered) now
contains `.hero-grid` (2 columns ~52/48, gap 56px, added for v1). The visual
column `.hero-visual` holds the canvas. Right-side region real sizes:
- 1440×900 → ≈537 × 633px (height from `clamp(480px, 44vw, 640px)`)
- 1280×720 → ≈557 × 563px
- 1024×768 → stacked, ≈960 × 440px (page breakpoint ≤1024px)
- 390×844 → stacked, ≈342 × 360px (page breakpoint ≤768px)

**Tokens (inline `:root` in `landing/index.html`).**
bg `--ink:#11141B`, surface `--ink-soft:#1A1F26`, ivory `--paper:#F1ECE0`,
muted `--paper-text-veil:#C9C2AE` / `--paper-text-faint:#8E8773`,
brass `--brass:#B88840` / `--brass-light:#D4B377` / `--brass-deep:#8C6526`,
verify `--verify-dark:#5FA886`. Fonts: Spectral (serif display), Inter
(sans), IBM Plex Mono (micro-labels). Easing on page: `ease`, `ease-out`,
0.2–0.9s; entrance 700ms + staggered delays; reveal via IntersectionObserver.

**Contradictions resolved (prompt vs real code):**
1. Prompt assumes an *empty* right side; v1 already built a 3D scene there.
   Decision: v2 *replaces* the v1 scene in place (same container/IDs), keeps
   the left column byte-identical.
2. Prompt's file map (`landing/style.css`, `hero3d/`, `dist/…min.js`,
   posters, capture script) doesn't exist. Decision: create it as specified,
   except the bundle lives at `landing/dist/hero-3d.min.js` (keeps `landing/`
   shippable as one folder) and capture script at `scripts/capture-posters.mjs`.
3. Prompt says "no runtime CDN"; v1 uses jsdelivr gsap/three. Decision: npm
   `three@0.160.0` + `gsap@3.12.5` + esbuild bundle (verified installable).
   CSP drops `cdn.jsdelivr.net` again.
4. Camera/timings in prompt are starting values; tuned by screenshot below.
5. Prompt tiers (1100/700px viewport) vs page breakpoints (1024/768):
   tiers key off *container* width (≥640 full / 400–640 tablet / <400 mobile)
   so the scene degrades with its own box, not the viewport. Logged here.
6. 18s loop replaces v1's 17.2s loop. Single master timeline kept (GSAP).

**Token mapping.** `--h3d-*` on `.hero-visual` reference the page vars with
hex fallbacks; JS reads them via `getComputedStyle` (no hex in JS).

## 2. Build notes (filled as work proceeds)

- three@0.160.0 + esbuild@0.20.2 installed via root package.json (`npm run
  build:hero`). Playwright 1.44 + Chromium available; SwiftShader WebGL 2.0
  confirmed working headless.
- (headless SwiftShader FPS is NOT real-GPU FPS — see §5.)
- Modules: `hero3d/{config,scene,core,docs,textures,particles,trace,
  labels,quality,interaction,timeline,entry}.js`. `entry.js` is the bundle
  entry; `window.__hero3d = { seek(t), ready, stats() }`.
- Bundle: `landing/dist/hero-3d.min.js` — raw 588KB / gzip **162KB** (budget
  250KB). Posters: idle **11.6KB**, verified **17.1KB** (budget 60KB each;
  captured at `?t=0.8` and `?t=11` via `scripts/capture-posters.mjs`).
- Stale v1 assets removed: `hero-3d.js`, `importmap.json` (runtime CDN is
  gone). CSP tightened to `script-src 'self'` in `app/middleware/__init__.py`;
  verified no `jsdelivr` remains anywhere.
- Two real issues found + fixed during verification:
  1. **Seek callbacks**: GSAP `timeline.seek()` suppresses events by default,
     so `?t=` scrubbing never fired label show/hide or `drawTrace`. Fixed by
     `seek(t, false)` (`timeline.js`) — scrub replay now applies every beat.
  2. **Draw calls**: etched bars/chunks/frame/nodes as individual meshes hit
     143 calls. Static geometry merged via `BufferGeometryUtils.mergeGeometries`
     (`core.js`, `docs.js`) → **56 calls** worst frame (budget 60), 2,052
     triangles, 13 programs, 12 textures.
- Objective gate (`scripts/verify-hero.mjs`, 40 checks): timeline points 0…17
  ready+live with zero console errors; labels appear at retrieval (3) through
  verified hold (13); draw-call/triangle budgets; `?static` shows verified
  poster without 3D boot; tiers 0–3 boot (`full`/`tablet`/`mobile/mobile`);
  1280/1024/390 viewports boot; `prefers-reduced-motion` → verified poster,
  no rAF.

## 3. Milestone critiques (screenshots in landing/_review/)

Objective results are in (§2). *Visual* sign-off still needs human eyes on a
real browser (this tool cannot judge pixel aesthetics); the screenshots below
were auto-captured for that review. Swatch key kept honest:
- A (idle, `t=0`–2): docs float at base poses, core slow-yaws, ambient dust
  drifts. Verified: poster-first → `is-live` on first frame, idle labels on.
- B (retrieval/fusion, `t=3.5`–6): query → BM25 (stepped squares) + DENSE
  (smooth dots) branch to docs, RRF label + rank chips 1/2/3 flash. Verified:
  label count climbs 3 → 7.
- C (trace/verify, `t=8.3`–13.8): passage strip sweeps source doc A, citation
  ribbon draws to the `[1]` marker, accent light ramps, confidence bar 94%,
  `✓ SOURCE VERIFIED`. Verified: labels 10 → 13, trace tube on (+1 draw).
- D (reset, `t=15.5`+): ribbon tail-erases, hero returns to base, labels
  collapse, loop hand-off to sequence 2 (§ 12 · ¶ 4). Verified: back to 0
  labels at `t=17`, 55 calls.

## 4. Art-direction test results

Programmatic proxies (auto-verified in `verify-hero.mjs`), visual verdict
still pending human review:
1. Logo-removed: no logo mesh exists in the scene (docs + core only).
2. Headline test: `.hero-visual` canvas left-edge `mask-image` (0→12%) keeps
   the visual off the copy (`hero-3d.css`); headline column untouched.
3. Squint test: *(needs a real browser look at `landing/_review/`)*.
4. Pause test: seek-any-time works via `?t=` (callback fix above).
5. Gold test: gold/highlight sources counted — brass frame, passage strip,
   brackets, rank label, trace ribbon, [1] marker, chip, verified state: ≤3
   concurrent per beat by construction (verified label count, not pixel gold).
6. Headline-safe (left 12% dim): mask kept; scene pushed right (`core.pos.x`,
   selection pose +x). *(final pixels: see screenshots).*

## 5. Real-GPU verification checklist (for a real machine)

- [ ] Open landing in Chrome, DevTools Performance, 4× CPU throttle: assert
      steady 60fps while the story loops (SwiftShader numbers don't count).
- [ ] Network tab: `dist/hero-3d.min.js` ≤ ~250KB gz, posters ≤60KB each,
      zero failed requests, fonts 200.
- [ ] Console: zero errors/warnings on load, scroll, resize, tab-hide/show.
- [ ] Hover each doc + core: gold edge, tooltip, no timeline stutter.
- [ ] `?t=12.5` scrubs; `?static` shows verified pose; DevTools device
      toolbar 390×844 shows ≤320px simplified scene.
- [ ] OS reduced-motion ON: static verified poster, no canvas loop
      (check via Performance: no rAF).
- [ ] Chrome + Safari + Firefox smoke: layout, fonts, hero intact.
