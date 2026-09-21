import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { chromium } from "playwright";

const ROOT = "landing";
const MIME = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".webp": "image/webp" };
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
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errs = [];
page.on("pageerror", (e) => errs.push(e.message));
await page.goto(`${base}/?tier=0&t=1`, { waitUntil: "load" });
await page.waitForTimeout(1500);

const box = await page.$eval("#heroVisual", (el) => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; });
// hover the core (center-right of the stage)
await page.mouse.move(box.x + box.w * 0.62, box.y + box.h * 0.45);
await page.waitForTimeout(900);
const core = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll(".hero-label")).filter((el) => parseFloat(getComputedStyle(el).opacity) > 0.5).map((el) => el.textContent);
    return els;
});
console.log("labels visible on core hover:", JSON.stringify(core));
// hover a doc (left side)
await page.mouse.move(box.x + box.w * 0.2, box.y + box.h * 0.35);
await page.waitForTimeout(900);
const tip = await page.$eval("#heroDocTip", (el) => el.classList.contains("is-shown") + "|" + el.textContent);
console.log("doc tooltip:", tip);
// destroy
const destroyed = await page.evaluate(() => { window.__hero3d.destroy(); return window.__hero3d === null; });
await page.waitForTimeout(400);
console.log("destroy nulls hooks:", destroyed);
console.log("pageerrors:", errs.length, errs.join("; "));
await browser.close();
server.close();
