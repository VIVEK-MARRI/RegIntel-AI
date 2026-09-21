/* hero3d/entry.js — orchestrator. Boots the scene, wires the story loop,
   drives the per-frame ambient motion, exposes the debug hooks
   (window.__hero3d = { seek, ready }), and owns graceful degradation.
   This is the only module bundled as the page entry. */
import * as THREE from "three";
import { CONFIG, readTokens } from "./config.js";
import { createScene } from "./scene.js";
import { buildCore } from "./core.js";
import { buildDocs } from "./docs.js";
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

    const corePos = CONFIG.core.pos;
    const core = buildCore(tokens);
    scene.add(core.group);
    const docs = buildDocs(tokens, scene, corePos, docIdx.length);
    const bg = buildBackground(tokens, scene, tier.bgParticles);
    const trace = buildTrace(tokens, scene);
    const labels = buildLabels(document.getElementById("heroLabels"));

    // --- streams: query → core, then core → docs (BM25 stepped, DENSE smooth)
    const dotTex = makeDotTexture("rgba(212,179,119,1)", "rgba(212,179,119,0.3)");
    const coreEdge = new THREE.Vector3(corePos[0] - 1.05, corePos[1], corePos[2] + 0.35);
    const queryFrom = new THREE.Vector3(...CONFIG.streams.queryFrom);
    const queryCurve = new THREE.QuadraticBezierCurve3(
        queryFrom, new THREE.Vector3(-1.8, 0.35, 0.95), coreEdge.clone()
    );
    const tmp = new THREE.Vector3();

    function branchCurve(target) {
        const mid = coreEdge.clone().lerp(target, 0.5);
        mid.z += 0.6; mid.y += 0.2;
        return new THREE.QuadraticBezierCurve3(coreEdge.clone(), mid, target.clone());
    }
    const streams = {
        query: { proxy: { p: 0, o: 0 }, parts: [{ s: makeStream(30, 0.06, new THREE.Color(tokens.brassLight), dotTex, 0), curve: queryCurve, stepped: false, spread: 0.05, phase: 0 }] },
        bm25: { proxy: { p: 0, o: 0 }, parts: [] },
        dense: { proxy: { p: 0, o: 0 }, parts: [] },
    };
    [0, 3].forEach((di, i) => {
        const d = docs.docs[di];
        if (d) streams.bm25.parts.push({ s: makeStream(14, 0.05, new THREE.Color(tokens.brassLight), null, 0), curve: branchCurve(d.outer.position), stepped: true, spread: 0, phase: i * 0.18 });
    });
    [1, 4].forEach((di, i) => {
        const d = docs.docs[di];
        if (d) streams.dense.parts.push({ s: makeStream(14, 0.07, new THREE.Color(tokens.ivory), dotTex, 0), curve: branchCurve(d.outer.position), stepped: false, spread: 0.04, phase: i * 0.22 });
    });
    Object.values(streams).forEach((st) => st.parts.forEach((p) => scene.add(p.s.pts)));
    const traceHead = buildTraceHead(tokens, scene, dotTex);

    const interaction = createInteraction(container, heroSection, camera, new THREE.Vector3(...CONFIG.camera.pos), look, {
        parallax: tier.parallax,
    });
    if (!tier.hover) interaction.setEnabled(false);
    const quality = createQualityMonitor();

    // --- per-doc anchors (persistent; mutated each frame, zero alloc)
    const anchors = {
        query: queryFrom.clone(),
        bm25: streams.bm25.parts[0] ? streams.bm25.parts[0].curve.getPoint(0.5, new THREE.Vector3()) : coreEdge.clone(),
        dense: streams.dense.parts[0] ? streams.dense.parts[0].curve.getPoint(0.5, new THREE.Vector3()) : coreEdge.clone(),
        rrf: coreEdge.clone().add(new THREE.Vector3(0.1, -0.55, 0.2)),
        rank1: new THREE.Vector3(), rank2: new THREE.Vector3(), rank3: new THREE.Vector3(),
        chip: new THREE.Vector3(),
        verified: new THREE.Vector3(),
        confidence: new THREE.Vector3(),
        core_evidence: coreEdge.clone().add(new THREE.Vector3(0.4, 0.9, 0)),
        core_source: coreEdge.clone().add(new THREE.Vector3(0.4, -1.0, 0)),
        core_verified: coreEdge.clone().add(new THREE.Vector3(0.6, 0.2, 0.3)),
    };
    Object.keys(anchors).forEach((k) => labels.set(k, anchors[k]));

    const hoverTargets = docs.docs.map(() => ({ x: 0, y: 0, r: 0 }));
    const hitMeshes = docs.docs.map((d) => d.hit);

    // --- story context handed to the timeline
    let activeSeq = 0;
    const ctx = {
        duration, tokens, scene, camera, core, docs, labels, trace, accent,
        streams,
        setSequence(i) {
            activeSeq = i;
            labels.setText("chip", CONFIG.sequences[i].chip);
            // hero doc mirrors the sequence source
            docs.hero = docs.docs[i] || docs.docs[0];
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
            core.answer.marker.material.opacity = 0;
            core.answer.bars.forEach((b) => { b.material.opacity = 0.08; });
        },
        drawTrace() {
            const src = docs.passages[activeSeq];
            if (!src) return;
            const from = new THREE.Vector3();
            src.strip.getWorldPosition(from);
            const to = new THREE.Vector3();
            core.answer.marker.getWorldPosition(to);
            const mid = from.clone().lerp(to, 0.5);
            mid.z += 1.1; mid.y += 0.35;
            trace.setPath(from, mid, to);
        },
        hideTrace() { trace.hide(); },
    };
    ctx.resetPose();

    const story = createStory(ctx);

    // --- debug hooks
    const debug = {
        seek(t) { debugTime = t; story.seek(t); renderFrame(t); },
        ready: false,
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

    // --- resize
    function onResize() { resize(); }
    window.addEventListener("resize", onResize);
    resize();

    // --- visibility / intersection gating
    let visible = true;
    const io = new IntersectionObserver((es) => {
        visible = es[0].isIntersecting;
        if (visible) story.resume(); else story.pause();
    }, { threshold: 0.01 });
    io.observe(container);
    document.addEventListener("visibilitychange", () => {
        if (document.hidden) story.pause(); else if (visible) story.resume();
    });

    let debugTime = FLAG_T != null ? parseFloat(FLAG_T) : null;
    const clock = new THREE.Clock();
    let firstFrame = true;
    let hoverIndex = -1;

    // debug HUD
    let hud = null;
    if (FLAG_DEBUG) {
        hud = document.createElement("div");
        hud.className = "hero-debug";
        container.appendChild(hud);
    }

    function applyStreams() {
        const pairs = [["query", streams.query], ["bm25", streams.bm25], ["dense", streams.dense]];
        pairs.forEach(([, st]) => {
            st.parts.forEach((part) => {
                part.s.head = st.proxy.p + part.phase;
                layStream(part.s, part.curve, part.spread, part.stepped, tmp);
                part.s.pts.material.opacity = st.proxy.o;
            });
        });
    }

    function updateAnchors() {
        const v = new THREE.Vector3();
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
        core.answer.marker.getWorldPosition(anchors.verified);
        core.answer.group.getWorldPosition(v);
        anchors.confidence.copy(v); anchors.confidence.y -= core.answer.group.children[0].geometry.parameters.height / 2 + 0.25;
    }

    function updateHover(now) {
        const hit = interaction.pick(hitMeshes, now);
        const idx = hit ? hit.object.userData.docIndex : -1;
        if (idx !== hoverIndex) {
            hoverIndex = idx;
        }
        hoverTargets.forEach((h, i) => {
            const on = i === idx;
            h.x = on ? 0.12 : 0;
            h.y = on ? 0.08 : 0;
            h.r = on ? 0.05 : 0;
        });
        if (idx >= 0 && tier.hover) {
            const d = docs.docs[idx];
            labels.tip(d.def.head ? `${d.def.head} · ${d.def.meta}` : d.def.meta,
                interaction.state.pointerPx.x, interaction.state.pointerPx.y);
        } else if (idx < 0) {
            labels.tip(null);
        }
    }

    function renderFrame(t) {
        const dt = clock.getDelta();
        const now = performance.now();

        interaction.update();

        // ambient: background drift
        driftBackground(bg, t);

        // core: slow yaw + bob + internal points
        core.platesGroup.rotation.y = Math.sin((t * 2 * Math.PI) / CONFIG.core.yawPeriod) * (CONFIG.core.yawAmpDeg * Math.PI) / 180;
        core.group.position.y = corePos[1] + Math.sin(t * 0.7) * 0.05;
        const ppos = core.innerPts.geometry.attributes.position;
        core.pSeed.forEach((s, i) => {
            ppos.setXYZ(i, s.x + Math.sin(t * s.sp + s.ph) * 0.08, s.y + Math.cos(t * s.sp * 0.8 + s.ph) * 0.1, s.z + Math.sin(t * s.sp * 1.2 + s.ph) * 0.06);
        });
        ppos.needsUpdate = true;

        // docs: additive float + idle yaw on inner; hover offset; timeline owns outer
        docs.docs.forEach((d, i) => {
            const h = hoverTargets[i];
            const fy = Math.cos((t * 2 * Math.PI) / d.floatDur + d.floatPhase) * d.floatAmp;
            d.inner.position.x += (h.x - d.inner.position.x) * 0.08;
            d.inner.position.y += (fy - d.inner.position.y) * 0.08;
            d.inner.rotation.y += (h.r - d.inner.rotation.y) * 0.08;
        });

        applyStreams();

        // trace head marker rides the drawing edge
        if (trace.mesh.visible && trace.curve) {
            const head = trace.mat.uniforms.uHead.value;
            const tail = trace.mat.uniforms.uTail.value;
            trace.curve.getPoint(Math.min(head, 1), tmp);
            traceHead.position.copy(tmp);
            traceHead.material.opacity = (head > 0.01 && tail < 0.99) ? 0.9 : 0;
        } else {
            traceHead.material.opacity = 0;
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

        // adaptive quality: step down once, never up
        const step = quality.push(dt * 1000);
        if (step) {
            renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1));
            interaction.setEnabled(false);
            labels.tip(null);
        }
    }

    function loop() {
        requestAnimationFrame(loop);
        if (debugTime != null) {
            story.pause();
            renderFrame(debugTime);
            return;
        }
        renderFrame(clock.getElapsedTime());
    }

    story.start();
    if (debugTime != null) { story.seek(debugTime); renderFrame(debugTime); }
    loop();
}
