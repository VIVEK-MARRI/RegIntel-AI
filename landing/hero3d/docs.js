/* hero3d/docs.js (v3) — floating regulatory source artifacts at real depths.
   Hover offsets live on an inner additive group; the timeline owns outer. */
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { CONFIG } from "./config.js";
import { makeDocTexture, makeDotTexture } from "./textures.js";

const D2R = Math.PI / 180;

export function buildDocs(tokens, scene, corePos, count) {
    const defs = CONFIG.docs.slice(0, count);
    const dotTex = makeDotTexture("rgba(212,179,119,1)", "rgba(212,179,119,0.25)");
    const docs = [];
    const connPositions = [];
    const nodeGeos = [];

    defs.forEach((def, idx) => {
        const outer = new THREE.Group();
        outer.position.set(...def.pos);
        outer.rotation.set(0, def.rotY * D2R, (def.rotZ || 0) * D2R);
        const inner = new THREE.Group();
        outer.add(inner);

        const sheet = new THREE.Mesh(
            new THREE.BoxGeometry(def.w, def.h, 0.012),
            new THREE.MeshStandardMaterial({ color: 0x1a1f26, roughness: 0.9, metalness: 0.06, transparent: true })
        );
        inner.add(sheet);
        const face = new THREE.Mesh(
            new THREE.PlaneGeometry(def.w - 0.05, def.h - 0.05),
            new THREE.MeshStandardMaterial({
                map: makeDocTexture(def, tokens, 1000 + idx * 131),
                roughness: 0.9, metalness: 0.02, transparent: true,
            })
        );
        face.position.z = 0.008;
        inner.add(face);
        const edge = new THREE.LineSegments(
            new THREE.EdgesGeometry(sheet.geometry),
            new THREE.LineBasicMaterial({ color: new THREE.Color(tokens.brassLight), transparent: true, opacity: 0.14 })
        );
        inner.add(edge);

        // exact-match [ ] ticks, one draw, hidden until flashed
        const bMat = new THREE.LineBasicMaterial({ color: new THREE.Color(tokens.brassLight), transparent: true, opacity: 0 });
        const bw = 0.16, bh = 0.12, bx = -0.3, by = 0.3;
        const bPos = [];
        [[-1, -1], [1, -1], [-1, 1], [1, 1]].forEach(([sx, sy]) => {
            bPos.push(
                bx + sx * bw, by, 0,
                bx + sx * bw - sx * 0.05, by, 0,
                bx + sx * bw - sx * 0.05, by + sy * bh, 0
            );
        });
        const bGeo = new THREE.BufferGeometry();
        bGeo.setAttribute("position", new THREE.Float32BufferAttribute(bPos, 3));
        const brackets = new THREE.Line(bGeo, bMat);
        brackets.position.z = 0.02;
        inner.add(brackets);

        // generous invisible hit plane
        const hit = new THREE.Mesh(
            new THREE.PlaneGeometry(def.w + 0.5, def.h + 0.5),
            new THREE.MeshBasicMaterial({ visible: false })
        );
        hit.position.z = 0.06;
        hit.userData.docIndex = docs.length;
        inner.add(hit);

        // faint link toward the core (merged across docs: 2 draws total)
        const from = new THREE.Vector3(...def.pos);
        const dir = new THREE.Vector3(...corePos).sub(from);
        const to = from.clone().addScaledVector(dir, 0.78);
        connPositions.push(from.x, from.y, from.z, to.x, to.y, to.z);
        [from, to].forEach((p) => {
            const g = new THREE.SphereGeometry(0.022, 8, 8);
            g.translate(p.x, p.y, p.z);
            nodeGeos.push(g);
        });

        scene.add(outer);
        docs.push({
            def, outer, inner, face, edge, brackets, bMat, hit,
            sheetMat: sheet.material, faceMat: face.material,
            base: { x: def.pos[0], y: def.pos[1], z: def.pos[2], ry: def.rotY * D2R, rz: (def.rotZ || 0) * D2R },
            floatPhase: idx * 1.37, floatAmp: 0.05 + (idx % 3) * 0.012,
            floatDur: 5 + (idx % 4),
        });
    });

    // passage strips: one narrow line each, built for the two sequence sources
    function addPassage(doc, y) {
        const strip = new THREE.Mesh(
            new THREE.PlaneGeometry(1.0, 0.075),
            new THREE.MeshBasicMaterial({
                color: new THREE.Color(tokens.brassLight), transparent: true, opacity: 0,
                blending: THREE.AdditiveBlending, depthWrite: false,
            })
        );
        strip.position.set(-0.1, y, 0.032);
        doc.inner.add(strip);
        const tick = new THREE.Mesh(new THREE.PlaneGeometry(0.03, 0.15), strip.material.clone());
        tick.position.set(-0.66, y, 0.032);
        doc.inner.add(tick);
        return { strip, tick };
    }
    const passages = [addPassage(docs[0], 0.42), docs[1] ? addPassage(docs[1], 0.3) : null];

    const connGeo = new THREE.BufferGeometry();
    connGeo.setAttribute("position", new THREE.Float32BufferAttribute(connPositions, 3));
    const conn = new THREE.LineSegments(connGeo, new THREE.LineDashedMaterial({
        color: new THREE.Color(tokens.faint), dashSize: 0.09, gapSize: 0.07,
        transparent: true, opacity: 0.06, depthWrite: false,
    }));
    conn.computeLineDistances();
    scene.add(conn);
    if (nodeGeos.length) {
        scene.add(new THREE.Mesh(mergeGeometries(nodeGeos), new THREE.MeshBasicMaterial({
            color: new THREE.Color(tokens.brassLight), transparent: true, opacity: 0.35,
        })));
    }

    // fake contact shadow behind the first doc only
    const shC = document.createElement("canvas");
    shC.width = 64; shC.height = 64;
    const sg = shC.getContext("2d");
    const grad = sg.createRadialGradient(32, 32, 4, 32, 32, 30);
    grad.addColorStop(0, "rgba(0,0,0,0.5)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    sg.fillStyle = grad;
    sg.fillRect(0, 0, 64, 64);
    const shadow = new THREE.Mesh(
        new THREE.PlaneGeometry(2.4, 1.4),
        new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(shC), transparent: true, opacity: 0.55, depthWrite: false })
    );
    shadow.position.set(docs[0].base.x, docs[0].base.y - 1.5, docs[0].base.z - 0.8);
    scene.add(shadow);

    return { docs, passages, dotTex, shadow, conn };
}
