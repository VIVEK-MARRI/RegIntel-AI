/* hero3d/timeline.js — the 18s (12s mobile) story loop, built twice so the
   two sequences alternate cleanly without GSAP repeat caching of
   function-based values. Beats: idle → query → retrieve → fuse → select →
   trace → verify → hold → reset. */
import { gsap } from "gsap";
import { CONFIG } from "./config.js";

const D = CONFIG.loopSeconds;

export function createStory(ctx) {
    const dur = ctx.duration; // 18 or 12
    const f = dur / D;       // beat scale
    const at = (s) => s * f;

    function build(seq) {
        const tl = gsap.timeline({ paused: true });
        const src = ctx.docs.docs[seq === 0 ? 0 : 1];
        const passage = ctx.docs.passages[seq === 0 ? 0 : 1];

        tl.call(() => ctx.setSequence(seq), null, 0);
        tl.call(() => ctx.resetPose(), null, 0);

        // --- query (2.0 → 3.5) ---
        tl.call(() => ctx.labels.show("query"), null, at(2.0));
        tl.to(ctx.streams.query.proxy, { o: 0.85, duration: 0.4 * f, ease: "power1.out" }, at(2.0));
        tl.to(ctx.streams.query.proxy, { p: 1, duration: 1.5 * f, ease: "power1.inOut" }, at(2.0));

        // --- retrieval (3.5 → 5.1) ---
        tl.call(() => { ctx.labels.show("bm25"); ctx.labels.show("dense"); }, null, at(3.5));
        ["bm25", "dense"].forEach((k) => {
            tl.to(ctx.streams[k].proxy, { o: 0.9, duration: 0.4 * f, ease: "power1.out" }, at(3.5));
            tl.to(ctx.streams[k].proxy, { p: 1, duration: 1.6 * f, ease: "power1.inOut" }, at(3.5));
        });

        // --- fusion (5.1) ---
        tl.call(() => {
            ctx.labels.show("rrf");
            ctx.labels.show("rank1"); ctx.labels.show("rank2"); ctx.labels.show("rank3");
        }, null, at(5.1));
        ctx.docs.docs.forEach((d) => {
            tl.to(d.bMat, { opacity: 0.9, duration: 0.25 * f, ease: "power2.out" }, at(5.1));
            tl.to(d.bMat, { opacity: 0.18, duration: 0.6 * f, ease: "power1.in" }, at(5.4));
        });

        // --- selection (6.0 → 7.2) ---
        const sel = CONFIG.selection;
        tl.to(src.outer.position, { x: sel.pos[0], y: sel.pos[1], z: sel.pos[2], duration: 1.2 * f, ease: "power2.inOut" }, at(6.0));
        tl.to(src.outer.rotation, { y: sel.rotYDeg * (Math.PI / 180), duration: 1.2 * f, ease: "power2.inOut" }, at(6.0));
        tl.to(src.outer.scale, { x: 1.06, y: 1.06, z: 1.06, duration: 1.2 * f, ease: "power2.inOut" }, at(6.0));
        ctx.docs.docs.forEach((d) => {
            if (d === src) return;
            tl.to([d.sheetMat, d.faceMat], { opacity: CONFIG.selection.dimOthers, duration: 1.2 * f }, at(6.0));
            tl.to(d.edge.material, { opacity: 0.05, duration: 1.2 * f }, at(6.0));
        });

        // --- evidence trace (7.4 → 8.7) ---
        tl.call(() => {
            ctx.labels.show("core_evidence");
            ctx.labels.show("core_source");
            ctx.labels.show("chip");
        }, null, at(7.4));
        tl.to([passage.strip.material, passage.tick.material], { opacity: 0.9, duration: 0.5 * f, ease: "power1.out" }, at(7.4));
        tl.call(() => ctx.drawTrace(), null, at(7.9));
        tl.to(ctx.trace.mat.uniforms.uHead, { value: 1, duration: 1.3 * f, ease: "power1.inOut" }, at(7.9));

        // --- verification (9.0 → 9.8) ---
        tl.call(() => {
            ctx.labels.show("verified");
            ctx.labels.show("core_verified");
            ctx.labels.show("confidence");
        }, null, at(9.2));
        tl.to(ctx.accent, { intensity: 2.2, duration: 0.6 * f, ease: "power2.out" }, at(9.2));
        tl.to(ctx.core.answer.marker.material, { opacity: 1, duration: 0.4 * f }, at(9.2));
        ctx.core.answer.bars.forEach((b, i) => {
            tl.to(b.material, { opacity: 0.5, duration: 0.4 * f }, at((9.3 + i * 0.18) * f));
        });

        // --- hold (9.8 → 13.5) ---
        tl.to({}, { duration: 3.7 * f }, at(9.8));

        // --- reset (13.5 → 16.5) ---
        tl.to(ctx.trace.mat.uniforms.uTail, { value: 1, duration: 0.9 * f, ease: "power1.in" }, at(13.5));
        tl.call(() => ctx.hideTrace(), null, at(14.5));
        tl.call(() => ctx.labels.hideAll(), null, at(14.5));
        tl.to(src.outer.position, { x: src.base.x, y: src.base.y, z: src.base.z, duration: 1.2 * f, ease: "power2.inOut" }, at(14.5));
        tl.to(src.outer.rotation, { y: src.base.ry, duration: 1.2 * f, ease: "power2.inOut" }, at(14.5));
        tl.to(src.outer.scale, { x: 1, y: 1, z: 1, duration: 1.2 * f, ease: "power2.inOut" }, at(14.5));
        ctx.docs.docs.forEach((d) => {
            tl.to([d.sheetMat, d.faceMat], { opacity: 1, duration: 1.0 * f }, at(14.5));
            tl.to(d.edge.material, { opacity: 0.14, duration: 1.0 * f }, at(14.5));
        });
        tl.to([passage.strip.material, passage.tick.material], { opacity: 0, duration: 0.6 * f }, at(14.5));
        tl.to(ctx.accent, { intensity: 0, duration: 0.8 * f }, at(14.5));
        tl.to(ctx.core.answer.marker.material, { opacity: 0, duration: 0.6 * f }, at(14.5));
        ctx.core.answer.bars.forEach((b) => tl.to(b.material, { opacity: 0.08, duration: 0.6 * f }, at(14.5)));
        tl.to({}, { duration: 1.5 * f }, at(16.5)); // pad to duration

        return tl;
    }

    const timelines = [build(0), build(1)];
    let seq = 0;

    function play(i) {
        seq = i;
        timelines[i].play(0);
    }
    timelines[0].eventCallback("onComplete", () => play(1));
    timelines[1].eventCallback("onComplete", () => play(0));

    return {
        start() { play(0); },
        seek(t) {
            const i = Math.floor(t / dur) % 2;
            const local = t % dur;
            timelines.forEach((tl, k) => { if (k !== i) tl.pause(0); });
            seq = i;
            timelines[i].play(0);
            // suppressEvents=false so scrubbing replays the beat callbacks
            // (label show/hide, drawTrace) up to the requested time.
            timelines[i].seek(local, false);
        },
        pause() { timelines[seq].pause(); },
        resume() { timelines[seq].resume(); },
        get sequence() { return seq; },
    };
}
