/* hero3d/scene.js — renderer, camera, lights, fog. Long-lens premium look. */
import * as THREE from "three";
import { CONFIG } from "./config.js";
import { makeStudioEnv } from "./textures.js";

export function createScene(canvas, container, tokens, tier) {
    const msaa = tier.msaa;
    const renderer = new THREE.WebGLRenderer({
        canvas,
        antialias: msaa,
        alpha: true,
        stencil: false,
        powerPreference: "high-performance",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, tier.dpr));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = CONFIG.toneMappingExposure;
    renderer.shadowMap.enabled = false;

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(
        new THREE.Color(tokens.ink).getHex(),
        CONFIG.fog.near,
        CONFIG.fog.far
    );

    const camera = new THREE.PerspectiveCamera(
        CONFIG.camera.fov, 1, 0.1, 60
    );
    camera.position.set(...CONFIG.camera.pos);
    const look = new THREE.Vector3(...CONFIG.camera.look);
    camera.lookAt(look);

    // very soft hemisphere ambient (cool sky, near-black ground)
    scene.add(new THREE.HemisphereLight(0x8a93a3, 0x07090d, 0.55));
    // warm ivory key, upper-left
    const key = new THREE.DirectionalLight(0xf3e9d2, 1.5);
    key.position.set(-6, 7, 8);
    scene.add(key);
    // cool blue-gray rim, back-right
    const rim = new THREE.DirectionalLight(0x5a6b85, 0.6);
    rim.position.set(6, -2, -7);
    scene.add(rim);
    // tiny warm accent near the answer plane (driven 0→up at verification)
    const accent = new THREE.PointLight(0xd4b377, 0, 9, 2);
    accent.position.set(0.95, -0.6, 2.2);
    scene.add(accent);

    // procedural studio reflections for the brass metalness
    scene.environment = makeStudioEnv(renderer, tokens);

    function resize() {
        const w = container.clientWidth, h = container.clientHeight;
        if (!w || !h) return;
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
    }

    return { renderer, scene, camera, look, accent, resize };
}
