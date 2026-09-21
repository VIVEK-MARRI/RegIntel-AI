/* hero3d/entry.js (v3) — orchestrator. Boots the scene, wires the story,
   drives ambient motion, exposes debug hooks, owns graceful degradation. */
import * as THREE from "three";
import { CONFIG, readTokens } from "./config.js";
import { createScene } from "./scene.js";
import { buildCore } from "./core.js";
import { buildDocs } from "./docs.js";
import { buildOrbitals, driftOrbitals } from "./orbitals.js";
import { buildBackground, buildTraceHead, layStream, makeStream, driftBackground } from "./particles.js";
import { buildTrace } from "./trace.js";
import { buildLabels } from "./labels.js";
import { pickTier, tierDocs, createQualityMonitor } from "./quality.js";
import { createInteraction } from "./interaction.js";
import { createStory } from "./timeline.js";
import { makeDotTexture } from "./textures.js";

const params = new URLSearchParams(location.search);
const FLAG_STATIC = params.has("static");
const FLAG_TIER = params.get("tier");
const FLAG_DEBUG = params.has("debug");
const FLAG_T = params.get("t");
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const container = document.getElementById("heroVisual");
const canvas = document.getElementById("hero3d");
const heroSection = document.querySelector(".hero") || container;
const poster = document.getElementById("heroPoster");

function failStatic(reason) {
    if (container) {
        container.classList.add("is-fallback");
        container.dataset.ready = "1";
        container.dataset.failReason = reason;
    }
    try { console.info("[hero3d] static fallback: " + reason); } catch (e) {}
}

function useVerifiedPoster() {
    if (poster && poster.dataset.verified) poster.src = poster.dataset.verified;
    if (container) container.dataset.ready = "1";
}

if (!container || !canvas) {
    // nothing to mount
} else if (FLAG_STATIC || reduced) {
    useVerifiedPoster();
} else {
    try {
        boot();
    } catch (err) {
        failStatic((err && err.message) || "boot-error");
    }
}

function boot() {
    const tokens = readTokens(container);
    const tierName = FLAG_TIER != null
        ? ["full", "tablet", "mobile"][Math.min(parseInt(FLAG_TIER, 10) || 0, 2)]
        : pickTier(container);
    const tier = CONFIG.tiers[tierName];
    const docIdx = tierDocs(tierName);
    const mobile = tierName === "mobile";
    const duration = mobile ? CONFIG.mobileLoopSeconds : CONFIG.loopSeconds;

    const { renderer, scene, camera, look, accent, resize } = createScene(canvas, container, tokens, tier);
    if (!renderer.getContext()) { failStatic("no-webgl"); return; }

    const corePos = new THREE.Vector3(...CONFIG.core.pos);
    const core = buildCore(tokens);
    scene.add(core.group);
    const docs = buildDocs(tokens, scene, CONFIG.core.pos, docIdx.length);
    const orbitals = buildOrbitals(tokens, scene);
    const bg = buildBackground(tokens, scene, tier.bgParticles);
    const trace = buildTrace(tokens, scene);
    const labels = buildLabels(document.getElementById("heroLabels"));

    // --- streams: query → core mouth, then core → docs (BM25 stepped, DENSE smooth)
    const dotTex = makeDotTexture("rgba(212,179,119,1)", "rgba(212,179,119,0.3)");
    const coreMouth = corePos.clone().add(new THREE.Vector3(-1.25, 0.1, 0.35));
    const queryFrom = new THREE.Vector3(...CONFIG.streams.queryFrom);
    const queryCurve = new THREE.QuadraticBezierCurve3(
        queryFrom, new THREE.Vector3(-1.9, 0.35, 0.95), coreMouth.clone()
    );
    const tmp = new THREE.Vector3();

    function branchCurve(target) {
        const mid = coreMouth.clone().lerp(target, 0.5);
        mid.z += 0.6; mid.y += 0.2;
        return new THREE.QuadraticBezierCurve3(coreMouth.clone(), mid, target.clone());
    }
    const streams = {
        query: { proxy: { p: 0, o: 0 }, parts: [{ s: makeStream(CONFIG.streams.queryN, 0.06, new THREE.Color(tokens.brassLight), dotTex), curve: queryCurve, stepped: false, spread: 0.05, phase: 0 }] },
        bm25: { proxy: { p: 0, o: 0 }, parts: [] },
        dense: { proxy: { p: 0, o: 0 }, parts: [] },
    };
    [0, 3].forEach((di, i) => {
        const d = docs.docs[di];
        if (d) streams.bm25.parts.push({ s: makeStream(CONFIG.streams.branchN, 0.05, new THREE.Color(tokens.brassLight), null), curve: branchCurve(d.outer.position), stepped: true, spread: 0, phase: i * 0.18 });
    });
    [1, 4].forEach((di, i) => {
        const d = docs.docs[di];
        if (d) streams.dense.parts.push({ s: makeStream(CONFIG.streams.branchN, 0.07, new THREE.Color(tokens.ivory), dotTex), curve: branchCurve(d.outer.position), stepped: false, spread: 0.04, phase: i * 0.22 });
    });
    Object.values(streams).forEach((st) => st.parts.forEach((p) => scene.add(p.s.pts)));
    const traceHead = buildTraceHead(tokens, scene, dotTex);

    const interaction = createInteraction(container, heroSection, camera, new THREE.Vector3(...CONFIG.camera.pos), look, {
        parallax: tier.parallax,
    });
    if (!tier.hover) interaction.setEnabled(false);
    const quality = createQualityMonitor();

    const anchors = {
        query: queryFrom.clone(),
        bm25: streams.bm25.parts[0] ? streams.bm25.parts[0].curve.getPoint(0.5, new THREE.Vector3()) : coreMouth.clone(),
        dense: streams.dense.parts[0] ? streams.dense.parts[0].curve.getPoint(0.5, new THREE.Vector3()) : coreMouth.clone(),
        rrf: coreMouth.clone().add(new THREE.Vector3(0.15, -0.6, 0.2)),
        rank1: new THREE.Vector3(), rank2: new THREE.Vector3(), rank3: new THREE.Vector3(),
        chip: new THREE.Vector3(),
        verified: corePos.clone().add(new THREE.Vector3(0.85, -1.35, 0.4)),
        confidence: corePos.clone().add(new THREE.Vector3(0.85, -1.7, 0.4)),
        core_evidence: corePos.clone().add(new THREE.Vector3(-0.5, 1.35, 0)),
        core_source: corePos.clone().add(new THREE.Vector3(-0.65, -1.3, 0)),
        core_verified: corePos.clone().add(new THREE.Vector3(1.15, 0.35, 0.2)),
        core_confidence: corePos.clone().add(new THREE.Vector3(1.0, -0.9, 0.2)),
    };
    Object.keys(anchors).forEach((k) => labels.set(k, anchors[k]));

    const hoverTargets = docs.docs.map(() => ({ x: 0, y: 0, z: 0, r: 0 }));
    const hitMeshes = [...docs.docs.map((d) => d.hit), core.coreHit];

    const CORE_MICRO = ["core_evidence", "core_source", "core_verified", "core_confidence"];
    let coreMicroHover = false;
    let coreHoverOn = false;
    function setCoreMicro(on) {
        if (on === coreMicroHover) return;
        coreMicroHover = on;
        CORE_MICRO.forEach((id) => {
            const L = labels.els[id];
            if (!L) return;
            if (on) {
                if (!L.on) { L.el.style.opacity = "0.85"; L.hover = true; }
            } else if (L.hover && !L.on) {
                L.el.style.opacity = "0"; L.hover = false;
            }
        });
    }
    let connTarget = 0.06;

    // --- story context
    let activeSeq = 0;
    const ctx = {
        duration, tokens, scene, camera, core, docs, labels, trace, accent,
        streams,
        setSequence(i) {
            activeSeq = i;
            labels.setText("chip", CONFIG.sequences[i].chip);
        },
        resetPose() {
            docs.docs.forEach((d) => {
                d.outer.position.set(d.base.x, d.base.y, d.base.z);
                d.outer.rotation.set(0, d.base.ry, d.base.rz);
                d.outer.scale.set(1, 1, 1);
                d.sheetMat.opacity = 1; d.faceMat.opacity = 1;
                d.edge.material.opacity = 0.14;
                d.bMat.opacity = 0;
            });
            Object.values(streams).forEach((st) => { st.proxy.p = 0; st.proxy.o = 0; });
            Object.values(streams).forEach((st) => st.parts.forEach((p) => { p.s.pts.material.opacity = 0; }));
            docs.passages.forEach((ps) => {
                if (!ps) return;
                ps.strip.material.opacity = 0; ps.tick.material.opacity = 0;
            });
            trace.mat.uniforms.uHead.value = 0;
            trace.mat.uniforms.uTail.value = 0;
            trace.hide();
            accent.intensity = 0;
            this.calmCore();
        },
        drawTrace() {
            const src = docs.passages[activeSeq];
            if (!src) return;
            const from = new THREE.Vector3();
            src.strip.getWorldPosition(from);
            // into the core: stop at the facet facing the source
            const dir = corePos.clone().sub(from).normalize();
            const to = corePos.clone().addScaledVector(dir, CONFIG.core.outerR * 0.92);
            const mid = from.clone().lerp(to, 0.5);
            mid.z += 0.9; mid.y += 0.3;
            trace.setPath(from, mid, to);
        },
        hideTrace() { trace.hide(); },
        pulseCore() {
            core.edgeMat.opacity = 0.95;
            core.heartMat.emissiveIntensity = 0.55;
        },
        calmCore() {
            core.edgeMat.opacity = 0.32;
            core.heartMat.emissiveIntensity = 0;
        },
    };
    ctx.resetPose();

    const story = createStory(ctx);

    const debug = {
        seek(t) { debugTime = t; story.seek(t); renderFrame(t); },
        ready: false,
        destroy,
        stats() {
            const info = renderer.info;
            const visLabels = Array.from(document.querySelectorAll(".hero-label"))
                .filter((el) => parseFloat(getComputedStyle(el).opacity) > 0.05).length;
            return {
                calls: info.render.calls, triangles: info.render.triangles,
                textures: info.memory.textures, geometries: info.memory.geometries,
                programs: info.programs ? info.programs.length : 0,
                tier: tierName, visibleLabels: visLabels,
                live: container.classList.contains("is-live"),
                fallback: container.classList.contains("is-fallback"),
            };
        },
    };
    window.__hero3d = debug;

    function onResize() { resize(); }
    window.addEventListener("resize", onResize);
    resize();

    let visible = true;
    const io = new IntersectionObserver((es) => {
        visible = es[0].isIntersecting;
        if (visible) story.resume(); else story.pause();
    }, { threshold: 0.01 });
    io.observe(container);
    function onVis() {
        if (document.hidden) story.pause(); else if (visible) story.resume();
    }
    document.addEventListener("visibilitychange", onVis);

    canvas.addEventListener("webglcontextlost", (e) => {
        e.preventDefault();
        try { story.pause(); } catch (err) { /* already torn down */ }
        useVerifiedPoster();
        container.classList.remove("is-live");
        container.dataset.failReason = "context-lost";
        try { console.info("[hero3d] static fallback: context-lost"); } catch (err2) { /* noop */ }
    });

    let debugTime = FLAG_T != null ? parseFloat(FLAG_T) : null;
    const clock = new THREE.Clock();
    let firstFrame = true;
    let hoverIndex = -1;
    let raf = 0;

    let hud = null;
    if (FLAG_DEBUG) {
        hud = document.createElement("div");
        hud.className = "hero-debug";
        container.appendChild(hud);
    }

    function applyStreams() {
        [["query", streams.query], ["bm25", streams.bm25], ["dense", streams.dense]].forEach(([, st]) => {
            st.parts.forEach((part) => {
                part.s.head = st.proxy.p + part.phase;
                layStream(part.s, part.curve, part.spread, part.stepped, tmp);
                part.s.pts.material.opacity = st.proxy.o;
            });
        });
    }

    function updateAnchors() {
        const setDoc = (key, di, dy) => {
            const d = docs.docs[di];
            if (!d) { labels.hide(key); return; }
            d.outer.getWorldPosition(anchors[key]);
            anchors[key].y += dy;
        };
        setDoc("rank1", activeSeq === 0 ? 0 : 1, docs.docs[0].def.h / 2 + 0.18);
        setDoc("rank2", 3, docs.docs[3] ? docs.docs[3].def.h / 2 + 0.18 : 0);
        setDoc("rank3", 1, docs.docs[1] ? docs.docs[1].def.h / 2 + 0.18 : 0);
        const ps = docs.passages[activeSeq];
        if (ps) { ps.strip.getWorldPosition(anchors.chip); anchors.chip.x -= 0.55; }
    }

    function updateHover(now) {
        const hit = interaction.pick(hitMeshes, now);
        const idx = hit && !hit.object.userData.coreHit ? hit.object.userData.docIndex : -1;
        const coreHitNow = !!hit && !!hit.object.userData.coreHit;
        if (idx !== hoverIndex) hoverIndex = idx;
        hoverTargets.forEach((h, i) => {
            const on = i === idx;
            h.x = on ? 0.12 : 0;
            h.y = on ? 0.08 : 0;
            h.z = on ? 0.28 : 0;
            h.r = on ? 0.05 : 0;
        });
        if (idx >= 0 && tier.hover) {
            const d = docs.docs[idx];
            labels.tip(d.def.head ? `${d.def.head} · ${d.def.meta}` : d.def.meta,
                interaction.state.pointerPx.x, interaction.state.pointerPx.y);
        } else if (idx < 0) {
            labels.tip(null);
        }
        connTarget = (idx >= 0 && tier.hover) ? 0.15 : 0.06;
        coreHoverOn = coreHitNow && tier.hover;
        setCoreMicro(coreHoverOn);
    }

    function renderFrame(t) {
        const dt = clock.getDelta();
        const now = performance.now();

        interaction.update();
        driftBackground(bg, t);
        driftOrbitals(orbitals, t);

        // core: very slow counter-rotating facets + gentle bob
        const cp = CONFIG.core;
        core.outer.rotation.y = (t * 2 * Math.PI) / cp.outerPeriod;
        core.edges.rotation.y = core.outer.rotation.y;
        core.mid.rotation.y = (t * 2 * Math.PI) / cp.midPeriod;
        core.midEdges.rotation.y = core.mid.rotation.y;
        core.heart.rotation.y = (t * 2 * Math.PI) / cp.innerPeriod;
        core.group.position.y = CONFIG.core.pos[1] + Math.sin(t * 0.7) * 0.04;
        const cs = coreHoverOn ? 1.03 : 1;
        core.group.scale.setScalar(core.group.scale.x + (cs - core.group.scale.x) * 0.08);

        docs.docs.forEach((d, i) => {
            const h = hoverTargets[i];
            const fy = Math.cos((t * 2 * Math.PI) / d.floatDur + d.floatPhase) * d.floatAmp;
            d.inner.position.x += (h.x - d.inner.position.x) * 0.08;
            d.inner.position.y += (fy - d.inner.position.y) * 0.08;
            d.inner.position.z += (h.z - d.inner.position.z) * 0.08;
            d.inner.rotation.y += (h.r - d.inner.rotation.y) * 0.08;
        });

        applyStreams();

        if (trace.mesh.visible && trace.curve) {
            const head = trace.mat.uniforms.uHead.value;
            const tail = trace.mat.uniforms.uTail.value;
            trace.curve.getPoint(Math.min(head, 1), tmp);
            traceHead.position.copy(tmp);
            traceHead.material.opacity = (head > 0.01 && tail < 0.99) ? 0.9 : 0;
        } else {
            traceHead.material.opacity = 0;
        }

        if (docs.conn) {
            const cm = docs.conn.material;
            cm.opacity += (connTarget - cm.opacity) * 0.1;
        }

        updateAnchors();
        updateHover(now);
        labels.update(camera, container.getBoundingClientRect());

        renderer.render(scene, camera);

        if (firstFrame) {
            firstFrame = false;
            container.classList.add("is-live");
            container.classList.remove("is-fallback");
            container.dataset.ready = "1";
            debug.ready = true;
        }

        if (hud) {
            hud.textContent = `fps ${(1 / Math.max(dt, 0.0001)).toFixed(0)} · calls ${renderer.info.render.calls} · tris ${renderer.info.render.triangles} · ${tierName}`;
        }

        const step = quality.push(dt * 1000);
        if (step) {
            renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1));
            interaction.setEnabled(false);
            labels.tip(null);
        }
    }

    function loop() {
        raf = requestAnimationFrame(loop);
        if (debugTime != null) {
            story.pause();
            renderFrame(debugTime);
            return;
        }
        renderFrame(clock.getElapsedTime());
    }

    function destroy() {
        try { story.pause(); } catch (err) { /* noop */ }
        cancelAnimationFrame(raf);
        try { io.disconnect(); } catch (err) { /* noop */ }
        window.removeEventListener("resize", onResize);
        document.removeEventListener("visibilitychange", onVis);
        try { interaction.destroy(); } catch (err) { /* noop */ }
        labels.hideAll();
        labels.tip(null);
        scene.traverse((o) => {
            if (o.geometry) o.geometry.dispose();
            const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
            mats.forEach((m) => {
                if (m.map) m.map.dispose();
                m.dispose();
            });
        });
        try { renderer.dispose(); } catch (err) { /* noop */ }
        try { renderer.forceContextLoss(); } catch (err) { /* noop */ }
        container.classList.remove("is-live");
        window.__hero3d = null;
    }

    story.start();
    if (debugTime != null) { story.seek(debugTime); renderFrame(debugTime); }
    loop();
}
