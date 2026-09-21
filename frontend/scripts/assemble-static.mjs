/**
 * Assemble the Render static-site publish directory:
 *
 *   dist/index.html            ← landing page (../landing/index.html)
 *   dist/hero-3d.js|css        ← landing 3D hero assets
 *   dist/favicon.svg           ← shared favicon
 *   dist/app/index.html        ← React SPA (Vite build, base /app/)
 *   dist/app/assets/*          ← SPA chunks (immutable-cached by Render rule)
 *
 * Layout contract (see render.yaml routes):
 *   /app/*  → /app/index.html   (SPA fallback)
 *   /*      → /index.html        (landing)
 *
 * Run via: npm run build:static   (from frontend/)
 */
import { cpSync, existsSync, mkdirSync, renameSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = join(here, "..");
const dist = join(frontend, "dist");
const landing = join(frontend, "..", "landing");

function mustExist(p, what) {
    if (!existsSync(p)) {
        console.error(`assemble-static: missing ${what}: ${p}`);
        process.exit(1);
    }
}

// 1. Vite output must be present.
mustExist(join(dist, "index.html"), "Vite index.html (run `vite build` first)");
mustExist(join(dist, "assets"), "Vite assets/");

// 2. Move the SPA under /app/.
mkdirSync(join(dist, "app"), { recursive: true });
renameSync(join(dist, "index.html"), join(dist, "app", "index.html"));
renameSync(join(dist, "assets"), join(dist, "app", "assets"));
if (existsSync(join(dist, "favicon.svg"))) {
    // keep one copy for the SPA + one for the landing root
    cpSync(join(dist, "favicon.svg"), join(dist, "app", "favicon.svg"));
}

// 3. Overlay the landing page at the root.
mustExist(join(landing, "index.html"), "landing/index.html");
cpSync(join(landing, "index.html"), join(dist, "index.html"));
for (const asset of ["hero-3d.js", "hero-3d.css", "importmap.json", "landing-init.js"]) {
    mustExist(join(landing, asset), `landing/${asset}`);
    cpSync(join(landing, asset), join(dist, asset));
}

// 4. Drop Vite-only leftovers that must not shadow routes.
for (const stale of ["vite.svg"]) {
    const p = join(dist, stale);
    if (existsSync(p)) rmSync(p);
}

console.log("assemble-static: dist/ ready (landing at /, SPA at /app/)");
