/* hero3d/labels.js — HTML overlay micro-labels. All type lives in the DOM
   (page font stack, WCAG-AA ivory), positioned by Vector3.project().
   Updates run only while a label is visible; transforms via translate3d. */
import { CONFIG } from "./config.js";

export function buildLabels(layer) {
    const els = {};
    function make(id, html, cls) {
        const el = document.createElement("span");
        el.className = "hero-label" + (cls ? " " + cls : "");
        el.innerHTML = html;
        layer.appendChild(el);
        els[id] = { el, anchor: null, dx: 0, dy: 0, on: false };
        return els[id];
    }

    make("query", "QUERY");
    make("bm25", "BM25");
    make("dense", "DENSE");
    make("rrf", "RRF");
    make("rank1", "1", "is-gold");
    make("rank2", "2");
    make("rank3", "3");
    make("chip", "§ 38 · ¶ 2", "is-gold");
    make("verified", "✓ SOURCE VERIFIED", "is-verify");
    // confidence row: label + bar + pct (static 94% state indicator)
    const conf = document.createElement("span");
    conf.className = "hero-label is-verify hero-conf";
    conf.innerHTML = `CONFIDENCE<span class="bar"><i></i></span><span class="pct">${CONFIG.verify.confidencePct}%</span>`;
    layer.appendChild(conf);
    els.confidence = { el: conf, anchor: null, dx: 0, dy: 0, on: false };
    ["evidence", "source", "verified", "confidence"].forEach((k) => {
        make("core_" + k, k.toUpperCase());
    });

    const tip = document.getElementById("heroDocTip");

    return {
        els,
        set(id, anchor, dx = 0, dy = 0) {
            const L = els[id];
            if (!L) return;
            L.anchor = anchor; L.dx = dx; L.dy = dy;
        },
        show(id, barFill) {
            const L = els[id];
            if (!L || L.on) return;
            L.on = true;
            L.el.style.opacity = "1";
            if (id === "confidence" && barFill !== false) {
                const bar = L.el.querySelector(".bar > i");
                if (bar) {
                    bar.style.transition = "none";
                    bar.style.width = "0";
                    requestAnimationFrame(() => {
                        bar.style.transition = "width 0.6s cubic-bezier(.2,.7,.2,1)";
                        bar.style.width = CONFIG.verify.confidencePct + "%";
                    });
                }
            }
        },
        hide(id) {
            const L = els[id];
            if (!L || !L.on) return;
            L.on = false;
            L.el.style.opacity = "0";
            if (id === "confidence") {
                const bar = L.el.querySelector(".bar > i");
                if (bar) bar.style.width = "0";
            }
        },
        setText(id, text) {
            const L = els[id];
            if (L) L.el.textContent = text;
        },
        hideAll() {
            Object.keys(els).forEach((id) => this.hide(id));
        },
        update(camera, rect) {
            for (const id in els) {
                const L = els[id];
                if (!L.on || !L.anchor) continue;
                _v.copy(L.anchor).project(camera);
                const x = (_v.x * 0.5 + 0.5) * rect.width + L.dx;
                const y = (-_v.y * 0.5 + 0.5) * rect.height + L.dy;
                L.el.style.transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) translate(-50%,-50%)`;
            }
        },
        tip(text, x, y) {
            if (!tip) return;
            if (text == null) { tip.classList.remove("is-shown"); return; }
            tip.textContent = text;
            tip.style.left = x + "px";
            tip.style.top = y + "px";
            tip.classList.add("is-shown");
        },
    };
}

// module-scope temp (zero per-frame allocation)
import * as THREE from "three";
const _v = new THREE.Vector3();
