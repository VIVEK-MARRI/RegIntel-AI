/* hero3d/interaction.js (v3) — damped pointer parallax (true camera orbit)
   + persistent throttled hover picking. Hover offsets use each doc's inner
   additive group; the timeline owns outer, so the two never fight. */
import * as THREE from "three";
import { CONFIG } from "./config.js";

const D2R = Math.PI / 180;

export function createInteraction(container, heroSection, camera, basePos, lookAt, opts) {
    const state = {
        tx: 0, ty: 0, x: 0, y: 0,
        pointer: new THREE.Vector2(10, 10),
        pointerDirty: false,
        pointerPx: { x: 0, y: 0 },
        enabled: true,
        strength: opts.parallax ?? 1,
    };
    const raycaster = new THREE.Raycaster();
    let lastPick = 0;
    let lastHit = null;

    function onMove(e) {
        const r = container.getBoundingClientRect();
        if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) return;
        const nx = ((e.clientX - r.left) / r.width - 0.5) * 2;
        const ny = ((e.clientY - r.top) / r.height - 0.5) * 2;
        state.tx = nx * Math.tan(CONFIG.parallax.yawDeg * D2R) * basePos.z * state.strength;
        state.ty = -ny * Math.tan(CONFIG.parallax.pitchDeg * D2R) * basePos.z * state.strength;
        state.pointer.set(nx, -ny);
        state.pointerPx = { x: e.clientX - r.left, y: e.clientY - r.top };
        state.pointerDirty = true;
    }
    function onLeave() {
        state.tx = 0; state.ty = 0;
        state.pointer.set(10, 10);
        state.pointerDirty = true;
    }
    heroSection.addEventListener("mousemove", onMove);
    heroSection.addEventListener("mouseleave", onLeave);

    let tapTimer = 0;
    function onTouch(e) {
        const t = e.touches[0];
        if (!t) return;
        const r = container.getBoundingClientRect();
        state.pointer.set(
            ((t.clientX - r.left) / r.width - 0.5) * 2,
            -(((t.clientY - r.top) / r.height - 0.5) * 2)
        );
        state.pointerPx = { x: t.clientX - r.left, y: t.clientY - r.top };
        state.pointerDirty = true;
        clearTimeout(tapTimer);
        tapTimer = setTimeout(() => {
            state.pointer.set(10, 10);
            state.pointerDirty = true;
        }, 2000);
    }
    container.addEventListener("touchstart", onTouch, { passive: true });

    return {
        state,
        update() {
            const k = CONFIG.parallax.smoothing;
            state.x += (state.tx - state.x) * k;
            state.y += (state.ty - state.y) * k;
            camera.position.set(basePos.x + state.x, basePos.y + state.y, basePos.z);
            camera.lookAt(lookAt);
        },
        // throttled (~30Hz); the last hit persists while the pointer is still
        pick(hitMeshes, nowMs) {
            if (!state.enabled) return null;
            if (!state.pointerDirty) return lastHit;
            if (nowMs - lastPick < 33) return lastHit;
            lastPick = nowMs;
            state.pointerDirty = false;
            raycaster.setFromCamera(state.pointer, camera);
            const hits = raycaster.intersectObjects(hitMeshes, false);
            lastHit = hits.length ? hits[0] : null;
            return lastHit;
        },
        setEnabled(on) { state.enabled = on; },
        destroy() {
            heroSection.removeEventListener("mousemove", onMove);
            heroSection.removeEventListener("mouseleave", onLeave);
            container.removeEventListener("touchstart", onTouch);
            clearTimeout(tapTimer);
        },
    };
}
