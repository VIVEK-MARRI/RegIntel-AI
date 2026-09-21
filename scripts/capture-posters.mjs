/* Dev-only: capture hero posters (idle + verified) as WebP via Chromium. */
import http from "node:http";
import { readFile, writeFile } from "node:fs/promises";
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
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });

async function capture(t, out) {
    await page.goto(`${base}/?t=${t}`, { waitUntil: "load" });
    await page.waitForTimeout(1200);
    const hero = await page.$("#heroVisual");
    const png = await hero.screenshot({ type: "png" });
    const dataUrl = await page.evaluate(async (b64) => {
        const img = new Image();
        img.src = "data:image/png;base64," + b64;
        await img.decode();
        const c = document.createElement("canvas");
        c.width = img.naturalWidth; c.height = img.naturalHeight;
        c.getContext("2d").drawImage(img, 0, 0);
        return c.toDataURL("image/webp", 0.92);
    }, png.toString("base64"));
    const buf = Buffer.from(dataUrl.split(",")[1], "base64");
    await writeFile(out, buf);
    console.log(out, (buf.length / 1024).toFixed(1) + " KB");
}

await capture(0.8, "landing/hero-poster-idle.webp");
await capture(11, "landing/hero-poster-verified.webp");
await browser.close();
server.close();
