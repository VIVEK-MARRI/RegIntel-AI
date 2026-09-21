/* hero3d/particles.js — background dust + query/retrieval streams.
   BM25 reads exact/gridded (square points, quantized steps); DENSE reads
   continuous (soft round points, smooth arcs). Three Points draws total. */
import * as THREE from "three";
import { CONFIG } from "./config.js";
import { makeDotTexture } from "./textures.js";

export function buildBackground(tokens, scene, count) {
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(count * 3);
    const seed = [];
    const rnd = (() => { let a = 7; return () => { a = (a * 16807) % 2147483647; return a / 2147483647; }; })();
    for (let i = 0; i < count; i++) {
        const x = -4.5 + rnd() * 9.5, y = -3.4 + rnd() * 6.8, z = -7 + rnd() * 3;
        pos[i * 3] = x; pos[i * 3 + 1] = y; pos[i * 3 + 2] = z;
        seed.push({ x, y, ph: rnd() * 6.28, per: 10 + rnd() * 4 });
    }
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({
        map: makeDotTexture("rgba(241,236,224,1)", "rgba(241,236,224,0.25)"),
        color: new THREE.Color(tokens.ivory), size: 0.05,
        transparent: true, opacity: 0.12, depthWrite: false,
    }));
    pts.frustumCulled = false;
    scene.add(pts);
    return { pts, seed };
}

export function driftBackground(bg, t) {
    const pos = bg.pts.geometry.attributes.position;
    for (let i = 0; i < bg.seed.length; i++) {
        const s = bg.seed[i];
        pos.setXYZ(i,
            s.x + Math.sin(t * (6.28 / s.per) + s.ph) * 0.18,
            s.y + Math.cos(t * (6.28 / (s.per + 2)) + s.ph) * 0.14,
            pos.getZ(i));
    }
    pos.needsUpdate = true;
}

export function makeStream(n, size, color, map, opacity) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({
        map: map || null, color, size, transparent: true, opacity: 0,
        depthWrite: false, blending: THREE.AdditiveBlending,
    }));
    pts.frustumCulled = false;
    return { pts, n, head: 0, opacity };
}

// Lay points along a curve; stepped=true quantizes (BM25 exactness).
export function layStream(s, curve, spread, stepped, tmp) {
    const pos = s.pts.geometry.attributes.position;
    for (let i = 0; i < s.n; i++) {
        let t = s.head - (i * 1.2) / s.n;
        t = ((t % 1) + 1) % 1;
        if (stepped) t = Math.floor(t * 8) / 8;
        curve.getPoint(t, tmp);
        const jx = spread ? (Math.sin(i * 12.9898) * 43758.5453 % 1) * spread : 0;
        const jy = spread ? (Math.sin(i * 78.233) * 12543.1234 % 1) * spread : 0;
        pos.setXYZ(i, tmp.x + jx, tmp.y + jy, tmp.z);
    }
    pos.needsUpdate = true;
}

export function buildTraceHead(tokens, scene, dotTex) {
    const dot = new THREE.Sprite(new THREE.SpriteMaterial({
        map: dotTex, color: new THREE.Color(tokens.brassLight),
        transparent: true, opacity: 0, depthWrite: false,
        blending: THREE.AdditiveBlending,
    }));
    dot.scale.set(0.22, 0.22, 1);
    scene.add(dot);
    return dot;
}
