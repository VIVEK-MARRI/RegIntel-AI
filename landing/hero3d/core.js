/* hero3d/core.js (v3) — faceted Evidence Core: a precision-cut translucent
   polyhedron, a nested inner shell, and a tiny solid octahedron heart.
   Thin brass edge-work, dark interior, restrained emissive lift on verify.
   No spheres-as-hero, no reactor, no wireframe logo. */
import * as THREE from "three";
import { CONFIG } from "./config.js";

export function buildCore(tokens) {
    const cfg = CONFIG.core;
    const group = new THREE.Group();
    group.position.set(...cfg.pos);

    const brass = new THREE.Color(tokens.brass);
    const brassLight = new THREE.Color(tokens.brassLight);

    // outer shell: faceted translucent faces, mostly invisible
    const outerGeo = new THREE.IcosahedronGeometry(cfg.outerR, 1);
    const outer = new THREE.Mesh(outerGeo, new THREE.MeshStandardMaterial({
        color: new THREE.Color(tokens.surface),
        transparent: true, opacity: 0.26,
        roughness: 0.18, metalness: 0.12,
        flatShading: true, depthWrite: false,
    }));
    outer.renderOrder = 10;
    group.add(outer);

    // thin brass outlines: only some edges catch the light (single draw)
    const edgeMat = new THREE.LineBasicMaterial({
        color: brassLight, transparent: true, opacity: 0.32, depthWrite: false,
    });
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(outerGeo), edgeMat);
    edges.renderOrder = 11;
    group.add(edges);

    // nested mid shell, counter-rotating
    const midGeo = new THREE.IcosahedronGeometry(cfg.midR, 0);
    const mid = new THREE.Mesh(midGeo, new THREE.MeshStandardMaterial({
        color: new THREE.Color(tokens.surface),
        transparent: true, opacity: 0.32,
        roughness: 0.25, metalness: 0.15,
        flatShading: true, depthWrite: false,
    }));
    mid.renderOrder = 9;
    group.add(mid);
    const midEdges = new THREE.LineSegments(
        new THREE.EdgesGeometry(midGeo),
        new THREE.LineBasicMaterial({ color: brass, transparent: true, opacity: 0.18, depthWrite: false })
    );
    midEdges.renderOrder = 11;
    group.add(midEdges);

    // tiny solid heart: dark brass octahedron, faintly warm inside
    const heartMat = new THREE.MeshStandardMaterial({
        color: brass, metalness: 0.95, roughness: 0.3,
        emissive: new THREE.Color(tokens.brassLight), emissiveIntensity: 0,
    });
    const heart = new THREE.Mesh(new THREE.OctahedronGeometry(cfg.innerR, 0), heartMat);
    group.add(heart);

    // generous invisible hit proxy for hover
    const coreHit = new THREE.Mesh(
        new THREE.BoxGeometry(cfg.outerR * 2 + 0.4, cfg.outerR * 2 + 0.4, cfg.outerR * 2 + 0.4),
        new THREE.MeshBasicMaterial({ visible: false })
    );
    coreHit.userData.coreHit = true;
    group.add(coreHit);

    return { group, outer, edges, edgeMat, mid, midEdges, heart, heartMat, coreHit };
}
