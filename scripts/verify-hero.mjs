/* Dev-only: objective hero verification (no human eyes). Serves landing/,
   walks timeline points + flags, and asserts budget/degradation contracts.
   Exit code 1 on failure. */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { chromium } from "playwright";

const ROOT = "landing";
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".webp": "image/webp", ".png": "image/png", ".svg": "image/svg+xml" };
const server = http.createServer(async (req, res) => {
    try {
        let p = decodeURIComponent(req.url.split("?")[0]);
        if (p === "/") p = "/index.html";
        const body = await readFile(normalize(join(ROOT, p)));
        res.writeHead(200, { "content-type": MIME[extname(p)] || "application/octet-stream" });
        res.end(body);
    } catch { res.writeHead(404).end("nf"); }
});
await new Promise((r) => server.listen(0, r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const results = [];
let failed = 0;
const ok = (name, cond, extra = "") => {
    results.push(`${cond ? "PASS" : "FAIL"}  ${name}${extra ? "  " + extra : ""}`);
    if (!cond) failed++;
};

async function open(url, vp = { width: 1440, height: 900 }) {
    const ctx = await browser.newContext({ viewport: vp });
    const page = await ctx.newPage();
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error" && !/404/.test(m.text())) errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
    await page.goto(url, { waitUntil: "load" });
    await page.waitForTimeout(900);
    return { ctx, page, errors };
}

// 1. timeline points: ready, stats within budget, labels appear
const timeline = [0, 3.5, 6, 8.3, 10, 11, 12.3, 13.8, 17];
let callsMax = 0, trisMax = 0;
for (const t of timeline) {
    const { ctx, page, errors } = await open(`${base}/?t=${t}&debug`);
    const s = await page.evaluate(() => (window.__hero3d ? window.__hero3d.stats() : null));
    ok(`t=${t} ready+live`, !!s && s.live && !s.fallback, JSON.stringify(s));
    ok(`t=${t} no errors`, errors.length === 0, errors.join("; "));
    if (s) { callsMax = Math.max(callsMax, s.calls); trisMax = Math.max(trisMax, s.triangles); }
    await ctx.close();
}
ok("draw calls <= 60", callsMax <= 60, "max=" + callsMax);
ok("triangles <= 60000", trisMax <= 60000, "max=" + trisMax);

// 2. labels visible at verification beat
{
    const { ctx, page } = await open(`${base}/?t=10`);
    const s = await page.evaluate(() => window.__hero3d.stats());
    ok("verification labels visible", s.visibleLabels >= 3, "labels=" + s.visibleLabels);
    await ctx.close();
}

// 3. static poster path
{
    const { ctx, page, errors } = await open(`${base}/?static`);
    const info = await page.evaluate(() => {
        const v = document.getElementById("heroVisual");
        const p = document.getElementById("heroPoster");
        return { ready: v.dataset.ready, live: v.classList.contains("is-live"), fallback: v.classList.contains("is-fallback"), src: p.currentSrc || p.src, h3d: !!window.__hero3d };
    });
    ok("static: verified poster", /verified/.test(info.src), info.src);
    ok("static: not live, not fallback", !info.live && !info.fallback, JSON.stringify(info));
    ok("static: no 3d boot", info.h3d === false);
    ok("static: no errors", errors.length === 0, errors.join("; "));
    await ctx.close();
}

// 4. tiers 0..3
for (const n of [0, 1, 2, 3]) {
    const { ctx, page, errors } = await open(`${base}/?tier=${n}&t=10`);
    const s = await page.evaluate(() => (window.__hero3d ? window.__hero3d.stats() : null));
    ok(`tier=${n} boots`, !!s && s.live && !s.fallback, s ? `tier=${s.tier}` : "null");
    ok(`tier=${n} no errors`, errors.length === 0, errors.join("; "));
    await ctx.close();
}

// 5. responsive containers
for (const vp of [{ width: 1280, height: 720 }, { width: 1024, height: 768 }, { width: 390, height: 844 }]) {
    const { ctx, page, errors } = await open(`${base}/?t=10`, vp);
    const s = await page.evaluate(() => (window.__hero3d ? window.__hero3d.stats() : null));
    ok(`${vp.width}x${vp.height} boots`, !!s && s.live, s ? `tier=${s.tier}` : "null");
    ok(`${vp.width}x${vp.height} no errors`, errors.length === 0, errors.join("; "));
    await ctx.close();
}

// 6. reduced motion -> poster
{
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    await page.goto(`${base}/`, { waitUntil: "load" });
    await page.waitForTimeout(600);
    const info = await page.evaluate(() => ({ h3d: !!window.__hero3d, src: document.getElementById("heroPoster").src, ready: document.getElementById("heroVisual").dataset.ready }));
    ok("reduced-motion: verified poster, no 3d", info.h3d === false && /verified/.test(info.src), JSON.stringify(info));
    await ctx.close();
}

console.log(results.join("\n"));
console.log(`\n${failed === 0 ? "ALL PASS" : failed + " FAILED"} (${results.length} checks)`);
await browser.close();
server.close();
process.exit(failed === 0 ? 0 : 1);
