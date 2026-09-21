/* hero3d/core.js — Evidence Core: fanned ledger of 6 smoked-glass plates,
   slim brass corner brackets, internal data points, answer plane + [1].
   No spheres, no wireframes, no reactor. */
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { CONFIG } from "./config.js";
import { makeAnswerTexture, makeDotTexture } from "./textures.js";

function mulberry(seed) {
    let a = seed >>> 0;
    return () => {
        a |= 0; a = (a + 0x6d2b79f5) | 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

const glassVert = `
varying vec3 vNormal;
varying vec3 vView;
void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vNormal = normalize(normalMatrix * normal);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
}`;
const glassFrag = `
uniform vec3 uColor;
varying vec3 vNormal;
varying vec3 vView;
void main() {
    float f = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.5);
    float a = mix(0.10, 0.22, f);
    gl_FragColor = vec4(uColor, a);
}`;

function markerTexture(tokens) {
    const c = document.createElement("canvas");
    c.width = 96; c.height = 96;
    const g = c.getContext("2d");
    g.font = "600 52px 'IBM Plex Mono', monospace";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillStyle = tokens.brassLight;
    g.fillText("[1]", 48, 52);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
}

export function buildCore(tokens) {
    const cfg = CONFIG.core;
    const group = new THREE.Group();
    group.position.set(...cfg.pos);

    const glassMat = new THREE.ShaderMaterial({
        uniforms: { uColor: { value: new THREE.Color(tokens.surface) } },
        vertexShader: glassVert,
        fragmentShader: glassFrag,
        transparent: true,
        depthWrite: false,
    });
    const etchMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(tokens.ivory),
        transparent: true, opacity: 0.09, depthWrite: false,
    });
    const chunkMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(tokens.brassLight),
        transparent: true, opacity: 0.32, depthWrite: false,
    });

    const plateGeo = new THREE.BoxGeometry(cfg.plateW, cfg.plateH, cfg.plateD);

    const platesGroup = new THREE.Group();
    group.add(platesGroup);
    const plates = [];
    const twist = (cfg.twistDeg * Math.PI) / 180;

    for (let i = 0; i < cfg.plates; i++) {
        const rnd = mulberry(1000 + i * 77);
        const pg = new THREE.Group();
        const z = (i - (cfg.plates - 1) / 2) * cfg.plateGap;
        pg.position.set((rnd() - 0.5) * 0.06, 0, z);
        pg.rotation.y = i * twist;
        pg.userData.baseZ = z;

        const plate = new THREE.Mesh(plateGeo, glassMat);
        plate.renderOrder = 10 + i;
        pg.add(plate);

        // etched hairline text bars + indexed-chunk markers, merged into two
        // meshes per plate to keep draw calls low (geometry is static).
        const bars = 5 + Math.floor(rnd() * 5);
        const barGeos = [];
        for (let b = 0; b < bars; b++) {
            const w = 0.9 + rnd() * 0.7;
            const g = new THREE.PlaneGeometry(w, 0.035);
            g.translate((rnd() - 0.5) * 0.3, 1.0 - b * 0.24 - rnd() * 0.08, cfg.plateD / 2 + 0.002);
            barGeos.push(g);
        }
        const barMesh = new THREE.Mesh(mergeGeometries(barGeos), etchMat);
        barMesh.renderOrder = 20 + i;
        pg.add(barMesh);

        const chunks = 2 + Math.floor(rnd() * 3);
        const chunkGeos = [];
        for (let k = 0; k < chunks; k++) {
            const g = new THREE.PlaneGeometry(0.09, 0.09);
            g.translate((rnd() - 0.5) * 1.4, (rnd() - 0.5) * 2.0, cfg.plateD / 2 + 0.002);
            chunkGeos.push(g);
        }
        const chunkMesh = new THREE.Mesh(mergeGeometries(chunkGeos), chunkMat);
        chunkMesh.renderOrder = 20 + i;
        pg.add(chunkMesh);
        platesGroup.add(pg);
        plates.push(pg);
    }

    // slim brass frame: 4 corner brackets (2 arms each), metallic
    const frameMat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(tokens.brass),
        metalness: 0.9, roughness: 0.35,
    });
    const frame = new THREE.Group();
    const hw = cfg.plateW / 2 + 0.06, hh = cfg.plateH / 2 + 0.06;
    const armL = 0.22, armT = 0.035, armD = 0.05;
    const zf = ((cfg.plates - 1) / 2) * cfg.plateGap + 0.02;
    const frameGeos = [];
    [[-hw, hh], [hw, hh], [-hw, -hh], [hw, -hh]].forEach(([cx, cy]) => {
        const sx = Math.sign(cx), sy = Math.sign(cy);
        const hBar = new THREE.BoxGeometry(armL, armT, armD);
        hBar.translate(cx - sx * armL / 2 + sx * armT / 2, cy, zf);
        const vBar = new THREE.BoxGeometry(armT, armL, armD);
        vBar.translate(cx, cy - sy * armL / 2 + sy * armT / 2, zf);
        frameGeos.push(hBar, vBar);
    });
    frame.add(new THREE.Mesh(mergeGeometries(frameGeos), frameMat));
    group.add(frame);

    // generous invisible hit proxy so the core is hoverable (§11)
    const coreHit = new THREE.Mesh(
        new THREE.BoxGeometry(cfg.plateW + 0.4, cfg.plateH + 0.4, 1.8),
        new THREE.MeshBasicMaterial({ visible: false })
    );
    coreHit.userData.coreHit = true;
    group.add(coreHit);

    // ~24 internal points drifting along plate normals
    const PN = cfg.innerParticles;
    const pGeo = new THREE.BufferGeometry();
    const pPos = new Float32Array(PN * 3);
    const pSeed = [];
    const prnd = mulberry(42);
    for (let i = 0; i < PN; i++) {
        pSeed.push({
            x: (prnd() - 0.5) * 1.6, y: (prnd() - 0.5) * 2.2,
            z: (prnd() - 0.5) * 1.1, sp: 0.05 + prnd() * 0.1, ph: prnd() * 6.28,
        });
    }
    pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
    const innerPts = new THREE.Points(pGeo, new THREE.PointsMaterial({
        map: makeDotTexture("rgba(212,179,119,1)", "rgba(212,179,119,0.3)"),
        color: new THREE.Color(tokens.brassLight), size: 0.06,
        transparent: true, opacity: 0.7, depthWrite: false,
        blending: THREE.AdditiveBlending,
    }));
    innerPts.frustumCulled = false;
    group.add(innerPts);

    // Answer plane + resolving bars + [1] marker
    const ans = CONFIG.answerPlane;
    const ansGroup = new THREE.Group();
    ansGroup.position.set(...ans.pos);
    ansGroup.rotation.y = (ans.rotYDeg * Math.PI) / 180;
    const ansFace = new THREE.Mesh(
        new THREE.PlaneGeometry(ans.w, ans.h),
        new THREE.MeshStandardMaterial({
            map: makeAnswerTexture(tokens), roughness: 0.9, metalness: 0.02,
        })
    );
    ansGroup.add(ansFace);
    const ansEdge = new THREE.LineSegments(
        new THREE.EdgesGeometry(new THREE.PlaneGeometry(ans.w, ans.h)),
        new THREE.LineBasicMaterial({ color: new THREE.Color(tokens.faint), transparent: true, opacity: 0.35 })
    );
    ansGroup.add(ansEdge);
    const barMat = new THREE.MeshBasicMaterial({
        color: new THREE.Color(tokens.ivory), transparent: true, opacity: 0.08, depthWrite: false,
    });
    const bars = [];
    // line slots match the texture's faint tracks (fractions of height)
    [0.30, 0.47, 0.64].forEach((fy) => {
        const bar = new THREE.Mesh(new THREE.PlaneGeometry(1.28, 0.045), barMat.clone());
        bar.position.set(-0.02, ans.h / 2 - fy * ans.h, 0.004);
        ansGroup.add(bar);
        bars.push(bar);
    });
    const marker = new THREE.Sprite(new THREE.SpriteMaterial({
        map: markerTexture(tokens), transparent: true, opacity: 0, depthWrite: false,
    }));
    marker.scale.set(0.3, 0.3, 1);
    marker.position.set(0.62, ans.h / 2 - 0.47 * ans.h + 0.02, 0.03);
    ansGroup.add(marker);
    group.add(ansGroup);

    return {
        group, platesGroup, plates, frame, innerPts, pSeed, coreHit,
        answer: { group: ansGroup, bars, marker },
        twist,
    };
}
