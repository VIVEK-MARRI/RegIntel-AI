/* hero3d/trace.js (v3) — the citation ribbon: a fine path from the source
   passage INTO the Evidence Core. uHead draws it on, uTail erases it from
   the tail forward. Single mesh, zero per-frame allocation. */
import * as THREE from "three";
import { CONFIG } from "./config.js";

const traceVert = `
varying vec2 vUv;
void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;
const traceFrag = `
uniform vec3 uColor;
uniform float uHead;
uniform float uTail;
uniform float uOpacity;
varying vec2 vUv;
void main() {
    float x = vUv.x;
    float headFade = smoothstep(uHead, uHead - 0.06, x);
    float tailFade = smoothstep(uTail, uTail + 0.06, x);
    float a = uOpacity * headFade * (1.0 - tailFade);
    if (a < 0.003) discard;
    gl_FragColor = vec4(uColor, a);
}`;

export function buildTrace(tokens, scene) {
    const mat = new THREE.ShaderMaterial({
        uniforms: {
            uColor: { value: new THREE.Color(tokens.brassLight) },
            uHead: { value: 0 },
            uTail: { value: 0 },
            uOpacity: { value: CONFIG.trace.holdOpacity },
        },
        vertexShader: traceVert,
        fragmentShader: traceFrag,
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
    });
    const mesh = new THREE.Mesh(new THREE.BufferGeometry(), mat);
    mesh.frustumCulled = false;
    mesh.visible = false;
    scene.add(mesh);
    return {
        mesh, mat,
        curve: null,
        setPath(from, mid, to) {
            if (mesh.geometry) mesh.geometry.dispose();
            this.curve = new THREE.QuadraticBezierCurve3(from, mid, to);
            mesh.geometry = new THREE.TubeGeometry(this.curve, 64, CONFIG.trace.tubeRadius, 6, false);
            mat.uniforms.uHead.value = 0;
            mat.uniforms.uTail.value = 0;
            mesh.visible = true;
        },
        hide() { mesh.visible = false; },
    };
}
