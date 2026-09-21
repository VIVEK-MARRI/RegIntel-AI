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
        const file = normalize(join(ROOT, p));
        const body = await readFile(file);
        res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
        res.end(body);
    } catch { res.writeHead(404).end("nf"); }
});
await new Promise((r) => server.listen(0, r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => console.log("[console:" + m.type() + "]", m.text()));
page.on("pageerror", (e) => console.log("[pageerror]", e.message, e.stack));
page.on("requestfailed", (r) => console.log("[reqfail]", r.url(), r.failure() && r.failure().errorText));
page.on("response", (r) => { if (r.status() >= 400) console.log("[http " + r.status() + "]", r.url()); });
await page.goto(`${base}/?t=10&debug`, { waitUntil: "load" });
await page.waitForTimeout(2500);
const info = await page.evaluate(() => {
    const v = document.getElementById("heroVisual");
    return { failReason: v && v.dataset.failReason, ready: v && v.dataset.ready, classes: v && v.className, h3d: !!window.__hero3d };
});
console.log("INFO", JSON.stringify(info));
await browser.close();
server.close();
