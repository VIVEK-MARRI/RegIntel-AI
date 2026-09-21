/* hero3d/textures.js (v3) — procedural canvas textures. No assets. */
import * as THREE from "three";

export function makeDotTexture(inner, outer) {
    const c = document.createElement("canvas");
    c.width = 64; c.height = 64;
    const g = c.getContext("2d");
    const r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    r.addColorStop(0, inner);
    r.addColorStop(0.4, outer);
    r.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = r;
    g.fillRect(0, 0, 64, 64);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
}

// Procedural studio environment for metalness (no HDRI file).
export function makeStudioEnv(renderer) {
    const c = document.createElement("canvas");
    c.width = 256; c.height = 128;
    const g = c.getContext("2d");
    g.fillStyle = "#0b0e14";
    g.fillRect(0, 0, 256, 128);
    const strip = (x, y, w, h, a) => {
        const gr = g.createLinearGradient(x, y, x + w, y);
        gr.addColorStop(0, "rgba(241,236,224,0)");
        gr.addColorStop(0.5, `rgba(241,236,224,${a})`);
        gr.addColorStop(1, "rgba(241,236,224,0)");
        g.fillStyle = gr;
        g.fillRect(x, y, w, h);
    };
    strip(30, 18, 70, 10, 0.9);
    strip(160, 90, 60, 8, 0.55);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.mapping = THREE.EquirectangularReflectionMapping;
    const pmrem = new THREE.PMREMGenerator(renderer);
    const env = pmrem.fromScene(
        (() => {
            const s = new THREE.Scene();
            s.add(new THREE.Mesh(
                new THREE.SphereGeometry(10, 16, 12),
                new THREE.MeshBasicMaterial({ map: tex, side: THREE.BackSide })
            ));
            return s;
        })(),
        0.04
    ).texture;
    pmrem.dispose();
    return env;
}

function mulberry(seed) {
    let a = seed >>> 0;
    return () => {
        a |= 0; a = (a + 0x6d2b79f5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

// Document face: graphite sheet, serif small-caps header, brass rule,
// ragged ivory bars (texture, never fake prose), fold, margin ticks,
// section numbers, one connection node.
export function makeDocTexture(def, tokens, seed) {
    const W = 512, H = 724;
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const g = c.getContext("2d");
    const P = tokens;
    const rnd = mulberry(seed);

    const bg = g.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, "#222832");
    bg.addColorStop(1, "#141920");
    g.fillStyle = bg;
    g.fillRect(0, 0, W, H);

    // fold-corner triangle, top-right
    g.fillStyle = "rgba(0,0,0,0.28)";
    g.beginPath();
    g.moveTo(W - 64, 0); g.lineTo(W, 0); g.lineTo(W, 64); g.closePath();
    g.fill();
    g.strokeStyle = "rgba(212,179,119,0.25)";
    g.lineWidth = 1;
    g.beginPath();
    g.moveTo(W - 64, 0); g.lineTo(W, 64);
    g.stroke();

    // header: brass rule + agency small-caps + title + mono meta
    g.fillStyle = "rgba(184,136,64,0.9)";
    g.fillRect(44, 52, 110, 2);
    g.fillStyle = P.brassLight;
    g.font = "600 30px Spectral, Georgia, serif";
    g.fillText((def.head || "RECORD").toUpperCase().slice(0, 18), 44, 104);
    g.fillStyle = P.ivory;
    g.font = "600 33px Spectral, Georgia, serif";
    const words = (def.title || "ANNEX").split(" ");
    let line = "", y = 148;
    const flush = () => { if (line) { g.fillText(line, 44, y); y += 42; line = ""; } };
    words.forEach((wd) => {
        if ((line + " " + wd).trim().length > 16) { flush(); line = wd; }
        else line = line ? line + " " + wd : wd;
    });
    flush();
    g.fillStyle = "rgba(184,136,64,0.9)";
    g.font = "500 23px 'IBM Plex Mono', monospace";
    g.fillText(def.meta || "", 44, y + 22);
    g.fillStyle = "rgba(184,136,64,0.3)";
    g.fillRect(44, y + 36, 190, 1);

    // body bars
    let ly = y + 74;
    const secs = ["38", "6.2", "Annex II"];
    let si = 0;
    for (let i = 0; i < 12 && ly < H - 120; i++) {
        if (i % 4 === 1) {
            g.fillStyle = "rgba(212,179,119,0.55)";
            g.font = "500 20px 'IBM Plex Mono', monospace";
            g.fillText(secs[si++ % secs.length], 44, ly - 6);
        }
        const lw = 260 + rnd() * 170 - (rnd() < 0.25 ? 120 : 0);
        g.fillStyle = `rgba(241,236,224,${(0.1 + rnd() * 0.04).toFixed(2)})`;
        g.fillRect(44, ly, Math.min(Math.max(lw, 120), W - 88), 9);
        ly += 31;
    }

    // left-margin index ticks
    g.fillStyle = "rgba(144,152,164,0.5)";
    for (let i = 0; i < 9; i++) g.fillRect(22, 150 + i * 52, i % 3 === 0 ? 10 : 6, 1);

    // connection node at right edge
    g.fillStyle = "rgba(212,179,119,0.8)";
    g.fillRect(W - 30, H / 2 - 1, 4, 4);

    // footer meta
    g.fillStyle = "rgba(144,152,164,0.8)";
    g.font = "500 18px 'IBM Plex Mono', monospace";
    g.fillText("SEBI/HO/…/CIR/… · P07", 44, H - 48);

    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    return t;
}
