/* hero3d/textures.js — canvas-generated textures. No font files, no assets.
   Doc texture 512x724: graphite paper, serif small-caps header, mono meta,
   ivory bars with ragged right edges (texture, never fake prose), fold
   triangle, margin ticks, section numbers, one connection node. */

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

// Procedural studio environment for the brass metalness (no HDRI file).
// Dark room + two soft ivory softbox strips.
export function makeStudioEnv(renderer, tokens) {
    const c = document.createElement("canvas");
    c.width = 256; c.height = 128;
    const g = c.getContext("2d");
    g.fillStyle = "#0b0e14";
    g.fillRect(0, 0, 256, 128);
    const strip = (x, y, w, h, a) => {
        const gr = g.createLinearGradient(x, y, x + w, y);
        gr.addColorStop(0, `rgba(241,236,224,0)`);
        gr.addColorStop(0.5, `rgba(241,236,224,${a})`);
        gr.addColorStop(1, `rgba(241,236,224,0)`);
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
            const m = new THREE.Mesh(
                new THREE.SphereGeometry(10, 16, 12),
                new THREE.MeshBasicMaterial({ map: tex, side: THREE.BackSide })
            );
            s.add(m);
            return s;
        })(),
        0.04
    ).texture;
    pmrem.dispose();
    return env;
}

export function makeDocTexture(def, tokens, seed) {
    const W = 512, H = 724;
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const g = c.getContext("2d");
    const P = tokens;

    // graphite paper, lifted ~6% over the page surface
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

    let s = seed;
    const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };

    // header band: agency small-caps serif + brass rule
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

    // body: ragged ivory bars, 10–14% alpha
    let ly = y + 74;
    const secs = ["38", "6.2", "Annex II"];
    for (let i = 0; i < 12 && ly < H - 120; i++) {
        if (i % 4 === 1) {
            g.fillStyle = "rgba(212,179,119,0.55)";
            g.font = "500 20px 'IBM Plex Mono', monospace";
            g.fillText(secs[(i / 4) | 0 % secs.length] || String(i), 44, ly - 6);
        }
        const lw = 260 + rnd() * 170 - (rnd() < 0.25 ? 120 : 0);
        g.fillStyle = `rgba(241,236,224,${(0.1 + rnd() * 0.04).toFixed(2)})`;
        g.fillRect(44, ly, Math.min(Math.max(lw, 120), W - 88), 9);
        ly += 31;
    }

    // left-margin index ticks
    g.fillStyle = "rgba(144,152,164,0.5)";
    for (let i = 0; i < 9; i++) g.fillRect(22, 150 + i * 52, i % 3 === 0 ? 10 : 6, 1);

    // 2px connection node at right edge
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

// Answer plane face: micro header + bars (bars are separate meshes so they
// can resolve line-by-line; the texture holds header + faint track lines).
export function makeAnswerTexture(tokens) {
    const W = 512, H = 312;
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const g = c.getContext("2d");
    g.fillStyle = "#1b212a";
    g.fillRect(0, 0, W, H);
    g.fillStyle = "rgba(184,136,64,0.9)";
    g.font = "600 24px 'IBM Plex Mono', monospace";
    g.fillText("ANSWER", 36, 52);
    g.fillStyle = "rgba(184,136,64,0.35)";
    g.fillRect(36, 66, 120, 1);
    // faint track lines where the resolving bars will sit
    g.fillStyle = "rgba(241,236,224,0.07)";
    [110, 152, 194].forEach((y) => g.fillRect(36, y, 440, 10));
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
}
