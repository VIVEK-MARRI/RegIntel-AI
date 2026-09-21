/* hero3d/orbitals.js (v3) — thin orbital geometry around the core: two
   faint tilted rings with barely-visible drift + tiny node dots where the
   information space touches the rings. Quiet by design. */
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { CONFIG } from "./config.js";

const D2R = Math.PI / 180;

export function buildOrbitals(tokens, scene) {
    const center = new THREE.Vector3(...CONFIG.core.pos);
    const rings = [];
    CONFIG.orbitals.rings.forEach((def) => {
        const curve = new THREE.EllipseCurve(0, 0, def.r, def.r * 0.92);
        const pts = curve.getPoints(128).map((p) => new THREE.Vector3(p.x, p.y, 0));
        const ring = new THREE.LineLoop(
            new THREE.BufferGeometry().setFromPoints(pts),
            new THREE.LineBasicMaterial({
                color: new THREE.Color(tokens.faint), transparent: true,
                opacity: def.opacity, depthWrite: false,
            })
        );
        ring.position.copy(center);
        ring.rotation.set(def.tiltXDeg * D2R, def.tiltYDeg * D2R, 0);
        ring.userData.period = def.period;
        scene.add(ring);
        rings.push(ring);
    });

    // node dots riding the outer ring (merged, one draw)
    const outer = CONFIG.orbitals.rings[1];
    const nodeGeos = [];
    for (let i = 0; i < CONFIG.orbitals.nodes; i++) {
        const a = (i / CONFIG.orbitals.nodes) * Math.PI * 2 + 0.6;
        const local = new THREE.Vector3(Math.cos(a) * outer.r, Math.sin(a) * outer.r * 0.92, 0);
        const g = new THREE.SphereGeometry(0.028, 8, 8);
        g.translate(local.x, local.y, local.z);
        nodeGeos.push(g);
    }
    const nodes = new THREE.Mesh(mergeGeometries(nodeGeos), new THREE.MeshBasicMaterial({
        color: new THREE.Color(tokens.brassLight), transparent: true, opacity: 0.4, depthWrite: false,
    }));
    const nodeGroup = new THREE.Group();
    nodeGroup.position.copy(center);
    nodeGroup.rotation.set(outer.tiltXDeg * D2R, outer.tiltYDeg * D2R, 0);
    nodeGroup.add(nodes);
    scene.add(nodeGroup);

    return { rings, nodeGroup };
}

export function driftOrbitals(orbitals, t) {
    orbitals.rings.forEach((ring) => {
        ring.rotation.z = (t * 2 * Math.PI) / ring.userData.period;
    });
    orbitals.nodeGroup.rotation.z = (t * 2 * Math.PI) / CONFIG.orbitals.rings[1].period;
}
