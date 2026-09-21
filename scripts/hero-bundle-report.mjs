import { readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";

const OUT = "landing/dist/hero-3d.min.js";
const BUDGET_KB = 250;

const raw = readFileSync(OUT);
const gz = gzipSync(raw, { level: 9 });
const kb = (n) => (n / 1024).toFixed(1);
const gzKb = gz.length / 1024;

console.log(`hero-3d.min.js  raw ${kb(raw.length)} KB  ·  gzip ${gzKb.toFixed(1)} KB`);
if (gzKb > BUDGET_KB) {
    console.error(`FAIL: gzip ${gzKb.toFixed(1)} KB exceeds budget ${BUDGET_KB} KB`);
    process.exit(1);
}
console.log(`OK: within ${BUDGET_KB} KB gzip budget (${((gzKb / BUDGET_KB) * 100).toFixed(0)}%)`);
void statSync;
