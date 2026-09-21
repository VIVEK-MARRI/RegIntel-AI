/* Dev-only: serve landing/ and capture hero screenshots at fixed timeline
   points. Usage: node scripts/capture-hero.mjs [--static] [--shots]        */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const ROOT = "landing";
const OUT = "landing/_review";
mkdirSync(OUT, { recursive: true });

const MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json", ".webp": "image/webp", ".png": "image/png",
    ".svg": "image/svg+xml", ".woff2": "font/woff2", ".ico": "image/x-icon",
};

const server = http.createServer(async (req, res) => {
    try {
        let p = decodeURIComponent(req.url.split("?")[0]);
        if (p === "/") p = "/index.html";
        const file = normalize(join(ROOT, p));
        if (!file.startsWith(normalize(ROOT))) { res.writeHead(403).end(); return; }
        const body = await readFile(file);
        res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
        res.end(body);
    } catch {
        res.writeHead(404).end("not found");
    }
});
await new Promise((r) => server.listen(0, r));
const port = server.address().port;
const base = `http://127.0.0.1:${port}`;

const args = process.argv.slice(2);
const staticOnly = args.includes("--static");

const viewports = [
    { name: "1440x900", width: 1440, height: 900 },
    { name: "1280x720", width: 1280, height: 720 },
    { name: "1024x768", width: 1024, height: 768 },
    { name: "390x844", width: 390, height: 844 },
];
const times = [0, 3.5, 6, 8.3, 10, 11, 12.3, 13.8, 17];

const browser = await chromium.launch({
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
const errors = [];
const ctx = await browser.newContext({ viewport: viewports[0] });
const page = await ctx.newPage();
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

async function shot(vp, url, name) {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto(url, { waitUntil: "load" });
    await page.waitForTimeout(600);
    const hero = await page.$("#heroVisual");
    if (hero) await hero.screenshot({ path: join(OUT, `${name}.png`) });
}

if (staticOnly) {
    for (const vp of viewports) await shot(vp, `${base}/?static`, `static-${vp.name}`);
} else {
    for (const t of times) {
        await shot(viewports[0], `${base}/?t=${t}&debug`, `t-${t}-1440x900`);
    }
    await shot(viewports[0], `${base}/?t=10&debug`, "t-10-1440x900");
    for (const vp of viewports.slice(1)) await shot(vp, `${base}/?t=10`, `t-10-${vp.name}`);
    await shot(viewports[0], `${base}/?static`, "static-1440x900");
    await shot(viewports[3], `${base}/?static`, "static-390x844");
}

const ready = await page.evaluate(() => (window.__hero3d ? window.__hero3d.ready : false)).catch(() => false);
console.log("hero3d ready:", ready);
console.log("console errors:", errors.length);
errors.slice(0, 20).forEach((e) => console.log("  -", e));

await browser.close();
server.close();
