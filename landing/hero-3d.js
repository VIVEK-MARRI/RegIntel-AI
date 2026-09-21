/* ============================================================================
   RegIntel-AI — Hero 3D: "Regulatory Evidence Network"
   ----------------------------------------------------------------------------
   A restrained, art-directed product visualization for the landing hero.
   Story: QUERY → RETRIEVAL (BM25 + DENSE) → FUSION (RRF) → EVIDENCE
   SELECTION → PASSAGE HIGHLIGHT → CITATION TRACE → VERIFICATION → RESET.

   Design constraints (do not regress):
   - Ink / paper / brass system only. No neon, no glow-bloat, no symmetry.
   - Camera parallax capped at a few degrees. Nothing spins fast.
   - Single canvas. DPR capped. Pauses off-screen. Reduced-motion safe.
   - Vanilla JS + Three.js (CDN) + GSAP (CDN). No framework, no assets.

   Sections:
     0. Guards, tiers, dom refs          4. Core + labels
     1. Renderer / scene / camera        5. Documents + textures
     2. Lights / fog                     6. Streams, trace, particles
     3. Helpers (canvas text, sprites)   7. Choreography   8. Loop/interaction
   ============================================================================ */
import * as THREE from 'three';

(function () {
    'use strict';

    /* ================= 0. GUARDS, TIERS, DOM ================= */
    var container = document.getElementById('heroVisual');
    if (!container) return;
    var canvas = document.getElementById('hero3d');
    var tooltip = document.getElementById('heroDocTip');
    var chipQuery = document.getElementById('chipQuery');
    var chipBm25 = document.getElementById('chipBm25');
    var chipDense = document.getElementById('chipDense');
    var chipRrf = document.getElementById('chipRrf');
    var chipVerified = document.getElementById('chipVerified');
    var chipConfidence = document.getElementById('chipConfidence');

    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var coarsePointer = window.matchMedia('(pointer: coarse)').matches;

    function tier() {
        var w = container.clientWidth || 560;
        if (w < 420) return 'mobile';
        if (w < 620) return 'tablet';
        return 'desktop';
    }
    var TIER = tier();

    function failStatic(reason) {
        container.classList.add('is-fallback');
        container.dataset.failReason = reason;
        try { console.info('[hero3d] static fallback: ' + reason); } catch (e) {}
        if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
    }

    function markReady() {
        // Cancel a premature watchdog fallback (slow CDN): a successfully
        // booted scene always wins over the static panel.
        container.classList.remove('is-fallback');
        container.dataset.ready = '1';
    }

    if (!window.WebGLRenderingContext) { failStatic('no-webgl'); return; }
    if (typeof gsap === 'undefined') { failStatic('no-gsap'); return; }

    /* ================= 1. RENDERER / SCENE / CAMERA ================= */
    var renderer;
    try {
        renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    } catch (e) { failStatic('renderer-failed'); return; }

    var DPR = TIER === 'mobile' ? 1 : (TIER === 'tablet' ? Math.min(window.devicePixelRatio || 1, 1.5) : Math.min(window.devicePixelRatio || 1, 2));
    renderer.setPixelRatio(DPR);

    var scene = new THREE.Scene();
    // Fog into hero ink so depth dissolves into the page background.
    scene.fog = new THREE.FogExp2(0x11141b, 0.016);

    var camera = new THREE.PerspectiveCamera(30, 1, 0.1, 60);
    var CAM_BASE = { x: 0.2, y: 0.55, z: 14.6 };
    var CAM_LOOK = new THREE.Vector3(0.15, -0.05, 0);
    camera.position.set(CAM_BASE.x, CAM_BASE.y, CAM_BASE.z);
    camera.lookAt(CAM_LOOK);

    /* ================= 2. LIGHTS ================= */
    scene.add(new THREE.AmbientLight(0x8a93a3, 0.85));
    var key = new THREE.DirectionalLight(0xf3e9d2, 1.35);
    key.position.set(-6, 7, 8);
    scene.add(key);
    var rim = new THREE.DirectionalLight(0x5a6b85, 0.55);
    rim.position.set(6, -2, -7);
    scene.add(rim);
    var brassGlow = new THREE.PointLight(0xd4b377, 5, 13, 2);
    brassGlow.position.set(1.7, 0.4, 2.2);
    scene.add(brassGlow);

    /* ================= 3. HELPERS ================= */
    var IVORY = '#F1ECE0', BRASS = '#B88840', BRASS_LT = '#D4B377',
        SLATE = '#9098A4', GRAPHITE = '#20262F', VERIFY = '#5FA886';

    function canvasTex(w, h, draw) {
        var c = document.createElement('canvas');
        c.width = w; c.height = h;
        draw(c.getContext('2d'), w, h);
        var t = new THREE.CanvasTexture(c);
        t.colorSpace = THREE.SRGBColorSpace;
        t.anisotropy = 4;
        return t;
    }

    // Soft radial dot (particles, trace head, shadow blobs).
    function dotTexture(inner, outer) {
        return canvasTex(64, 64, function (g) {
            var r = g.createRadialGradient(32, 32, 0, 32, 32, 32);
            r.addColorStop(0, inner);
            r.addColorStop(0.4, outer);
            r.addColorStop(1, 'rgba(0,0,0,0)');
            g.fillStyle = r;
            g.fillRect(0, 0, 64, 64);
        });
    }
    var TEX_DOT_IVORY = dotTexture('rgba(241,236,224,1)', 'rgba(241,236,224,0.28)');
    var TEX_DOT_BRASS = dotTexture('rgba(212,179,119,1)', 'rgba(212,179,119,0.30)');
    var TEX_SHADOW = dotTexture('rgba(0,0,0,0.55)', 'rgba(0,0,0,0.22)');

    function textSprite(text, opts) {
        opts = opts || {};
        var size = opts.size || 44;               // canvas px
        var color = opts.color || IVORY;
        var font = opts.font || '500 ' + size + 'px "IBM Plex Mono", monospace';
        var pad = 18;
        var meas = document.createElement('canvas').getContext('2d');
        meas.font = font;
        var tw = Math.ceil(meas.measureText(text).width);
        var tex = canvasTex(tw + pad * 2, size + pad * 2, function (g, w, h) {
            g.font = font;
            g.textBaseline = 'middle';
            if (opts.tracking) {
                // manual letter-spacing for micro-labels
                var x = pad, y = h / 2;
                g.fillStyle = color;
                for (var i = 0; i < text.length; i++) {
                    g.fillText(text[i], x, y);
                    x += meas.measureText(text[i]).width + opts.tracking;
                }
            } else {
                g.fillStyle = color;
                g.fillText(text, pad, h / 2 + 1);
            }
        });
        var aspect = tex.image.width / tex.image.height;
        var height = opts.world || 0.22;
        var mat = new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0, depthWrite: false });
        var sp = new THREE.Sprite(mat);
        sp.scale.set(height * aspect, height, 1);
        return sp;
    }

    function shadowBlob(w) {
        var m = new THREE.Mesh(
            new THREE.PlaneGeometry(w, w * 0.42),
            new THREE.MeshBasicMaterial({ map: TEX_SHADOW, transparent: true, opacity: 0.5, depthWrite: false })
        );
        m.rotation.x = 0;
        return m;
    }

    /* ================= 4. EVIDENCE CORE ================= */
    var CORE_POS = new THREE.Vector3(1.7, 0.1, 0.2);
    var core = new THREE.Group();
    core.position.copy(CORE_POS);
    scene.add(core);

    var glassMat = new THREE.MeshPhysicalMaterial({
        color: 0x2c333d, transparent: true, opacity: 0.17,
        roughness: 0.12, metalness: 0.4, depthWrite: false
    });
    var glassMat2 = glassMat.clone(); glassMat2.opacity = 0.13;

    var outerGeo = new THREE.IcosahedronGeometry(1.15, 0);
    core.add(new THREE.Mesh(outerGeo, glassMat));
    var outerFrame = new THREE.LineSegments(
        new THREE.EdgesGeometry(outerGeo),
        new THREE.LineBasicMaterial({ color: 0xb88840, transparent: true, opacity: 0.7 })
    );
    core.add(outerFrame);

    var midGeo = new THREE.OctahedronGeometry(0.68, 0);
    var midMesh = new THREE.Mesh(midGeo, glassMat2);
    midMesh.rotation.y = 0.5;
    core.add(midMesh);
    var midFrame = new THREE.LineSegments(
        new THREE.EdgesGeometry(midGeo),
        new THREE.LineBasicMaterial({ color: 0xd4b377, transparent: true, opacity: 0.45 })
    );
    midFrame.rotation.y = 0.5;
    core.add(midFrame);

    var nucleus = new THREE.Mesh(
        new THREE.OctahedronGeometry(0.2, 0),
        new THREE.MeshStandardMaterial({
            color: 0x8c6526, emissive: 0x8c6526, emissiveIntensity: 0.55,
            roughness: 0.35, metalness: 0.7
        })
    );
    core.add(nucleus);

    // faint etched orbit rings — structure, not decoration
    var ringMat = new THREE.LineBasicMaterial({ color: 0x6b7480, transparent: true, opacity: 0.28 });
    var ring1 = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(
        new THREE.EllipseCurve(0, 0, 1.5, 1.5).getPoints(72)), ringMat);
    ring1.rotation.x = Math.PI / 2.35;
    core.add(ring1);
    var ring2 = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(
        new THREE.EllipseCurve(0, 0, 1.78, 1.78).getPoints(72)), ringMat.clone());
    ring2.material.opacity = 0.16;
    ring2.rotation.x = Math.PI / 1.85;
    ring2.rotation.y = 0.4;
    core.add(ring2);

    // tiny internal data particles
    var CORE_P = TIER === 'mobile' ? 22 : 46;
    var corePGeo = new THREE.BufferGeometry();
    var corePPos = new Float32Array(CORE_P * 3);
    var corePSeed = [];
    for (var i = 0; i < CORE_P; i++) {
        var r = 0.25 + Math.random() * 0.7, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
        corePSeed.push({ r: r, th: th, ph: ph, sp: 0.05 + Math.random() * 0.12 });
        corePPos[i * 3] = r * Math.sin(ph) * Math.cos(th);
        corePPos[i * 3 + 1] = r * Math.cos(ph);
        corePPos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
    }
    corePGeo.setAttribute('position', new THREE.BufferAttribute(corePPos, 3));
    var corePts = new THREE.Points(corePGeo, new THREE.PointsMaterial({
        map: TEX_DOT_BRASS, color: 0xd4b377, size: 0.075,
        transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending
    }));
    core.add(corePts);

    var coreShadow = shadowBlob(3.4);
    coreShadow.position.set(CORE_POS.x, -2.6, CORE_POS.z - 0.6);
    scene.add(coreShadow);

    // core micro-labels (hover only)
    var coreLabels = [];
    [['EVIDENCE', 0, 1.62, 0], ['VERIFIED', 1.55, 0.5, 0], ['SOURCE', -1.5, -0.4, 0], ['CONFIDENCE', 0.2, -1.55, 0]]
        .forEach(function (d) {
            var sp = textSprite(d[0], { world: 0.2, color: 'rgba(212,179,119,1)', tracking: 3 });
            sp.position.set(d[1], d[2], d[3]);
            core.add(sp);
            coreLabels.push(sp);
        });

    /* ================= 5. REGULATORY DOCUMENTS ================= */
    // Document "paper": dark graphite sheet, ivory text-line texture.
    function docTexture(head, title, section, meta) {
        return canvasTex(512, 700, function (g, w, h) {
            var bg = g.createLinearGradient(0, 0, 0, h);
            bg.addColorStop(0, '#232932');
            bg.addColorStop(1, '#141920');
            g.fillStyle = bg;
            g.fillRect(0, 0, w, h);
            // top rule
            g.fillStyle = 'rgba(184,136,64,0.85)';
            g.fillRect(40, 44, 120, 3);
            // header
            g.fillStyle = '#D4B377';
            g.font = '600 30px "IBM Plex Mono", monospace';
            g.fillText(head, 40, 96);
            g.fillStyle = '#F1ECE0';
            g.font = '600 34px Inter, sans-serif';
            var words = title.split(' ');
            var line = '', y = 142;
            words.forEach(function (wd) {
                if ((line + ' ' + wd).length > 17) { g.fillText(line, 40, y); y += 42; line = wd; }
                else line = line ? line + ' ' + wd : wd;
            });
            g.fillText(line, 40, y);
            // section marker
            g.fillStyle = 'rgba(184,136,64,0.9)';
            g.font = '500 24px "IBM Plex Mono", monospace';
            g.fillText(section, 40, y + 58);
            g.fillStyle = 'rgba(184,136,64,0.35)';
            g.fillRect(40, y + 74, 200, 1);
            // body text lines (texture, not content)
            var ly = y + 116;
            var seed = head.length * 7 + title.length * 13;
            function rnd() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
            for (var i = 0; i < 11 && ly < h - 130; i++) {
                var lw = 300 + rnd() * 130;
                if (i === 6) lw = 220 + rnd() * 60; // short line rhythm
                g.fillStyle = 'rgba(241,236,224,' + (0.10 + rnd() * 0.14).toFixed(2) + ')';
                g.fillRect(40, ly, Math.min(lw, w - 80), 9);
                ly += 30;
            }
            // footer meta
            g.fillStyle = 'rgba(144,152,164,0.85)';
            g.font = '500 19px "IBM Plex Mono", monospace';
            g.fillText(meta, 40, h - 58);
            g.fillStyle = 'rgba(184,136,64,0.5)';
            g.fillRect(w - 130, h - 72, 90, 1);
        });
    }

    var DOC_DEFS = [
        { head: 'RBI', title: 'MASTER DIRECTION', section: '§ 4.2 · KYC', meta: 'REF 012 · REV 04', hero: true },
        { head: 'SEBI', title: 'CIRCULAR', section: '§ 12 · AMENDMENT', meta: 'REF 208 · REV 02' },
        { head: 'RBI', title: 'SECTION 38', section: 'CAPITAL ADEQUACY', meta: 'SCHED I · REV 01' },
        { head: 'SEBI', title: 'SCHEDULE I', section: 'RISK WEIGHTS', meta: 'REF 114 · REV 03' },
        { head: 'RBI', title: 'KYC NORMS', section: 'ANNEX B', meta: 'REF 077 · REV 05' },
        { head: 'SEBI', title: 'MASTER CIRCULAR', section: '§ 7 · DISCLOSURE', meta: 'REF 301 · REV 01' },
        { head: 'RBI', title: 'FAQ CLARIFICATION', section: 'KYC · V4', meta: 'REF 044 · REV 04' }
    ];
    // Art-directed placement: irregular depth, nothing symmetric.
    // [x, y, z, rotY, rotZ]
    var DOC_PLACE = [
        [-1.35, 0.62, 2.3, 0.34, 0.03],
        [3.75, 1.55, -1.4, -0.42, -0.05],
        [-3.55, -1.25, 0.1, 0.52, 0.04],
        [0.35, -2.05, -0.7, 0.12, -0.02],
        [4.35, -0.85, 1.0, -0.58, 0.05],
        [-4.35, 1.7, -2.4, 0.3, -0.03],
        [-2.3, 2.3, -1.9, 0.22, 0.06]
    ];

    var docCount = TIER === 'mobile' ? 3 : (TIER === 'tablet' ? 5 : 7);
    var docs = [];
    var sheetGeo = new THREE.BoxGeometry(1.5, 2.05, 0.035);
    var faceGeo = new THREE.PlaneGeometry(1.44, 1.99);

    for (var di = 0; di < docCount; di++) {
        (function (idx) {
            var def = DOC_DEFS[idx], pl = DOC_PLACE[idx];
            var grp = new THREE.Group();
            grp.position.set(pl[0], pl[1], pl[2]);
            grp.rotation.set(0, pl[3], pl[4] || 0);

            var sheet = new THREE.Mesh(sheetGeo, new THREE.MeshStandardMaterial({
                color: 0x1a1f26, roughness: 0.85, metalness: 0.08
            }));
            grp.add(sheet);
            var face = new THREE.Mesh(faceGeo, new THREE.MeshStandardMaterial({
                map: docTexture(def.head, def.title, def.section, def.meta),
                roughness: 0.9, metalness: 0.02
            }));
            face.position.z = 0.019;
            grp.add(face);
            var edge = new THREE.LineSegments(
                new THREE.EdgesGeometry(sheetGeo),
                new THREE.LineBasicMaterial({ color: 0xd4b377, transparent: true, opacity: 0.14 })
            );
            grp.add(edge);
            // exact-match marker (tiny diamond, flashes during BM25)
            var marker = new THREE.Mesh(
                new THREE.OctahedronGeometry(0.07, 0),
                new THREE.MeshBasicMaterial({ color: 0xd4b377, transparent: true, opacity: 0 })
            );
            marker.position.set(0.62, 0.88, 0.08);
            grp.add(marker);

            // generous invisible hit plane for calm hover targeting
            var hit = new THREE.Mesh(
                new THREE.PlaneGeometry(1.9, 2.5),
                new THREE.MeshBasicMaterial({ visible: false })
            );
            hit.position.z = 0.05;
            hit.userData.docIndex = idx;
            grp.add(hit);

            var sh = shadowBlob(2.2);
            sh.position.set(pl[0], pl[1] - 1.5, pl[2] - 0.7);
            scene.add(sh);
            scene.add(grp);

            docs.push({
                def: def, group: grp, face: face, edge: edge, marker: marker,
                shadow: sh, hit: hit,
                base: { x: pl[0], y: pl[1], z: pl[2], ry: pl[3], rz: pl[4] || 0 },
                floatPhase: Math.random() * Math.PI * 2,
                floatAmp: 0.06 + Math.random() * 0.05,
                floatDur: 5 + Math.random() * 3,
                hero: !!def.hero, selected: false
            });
        })(di);
    }
    var heroDoc = docs[0];

    // passage highlight strip on the hero document (one narrow line only)
    var passage = new THREE.Mesh(
        new THREE.PlaneGeometry(1.06, 0.085),
        new THREE.MeshBasicMaterial({
            color: 0xd4b377, transparent: true, opacity: 0,
            blending: THREE.AdditiveBlending, depthWrite: false
        })
    );
    passage.position.set(-0.08, 0.18, 0.032);
    heroDoc.group.add(passage);

    /* ================= 6. STREAMS, TRACE, PARTICLES ================= */
    function streamPoints(n, size, tex, color, opacity) {
        var geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
        var pts = new THREE.Points(geo, new THREE.PointsMaterial({
            map: tex, color: color, size: size, transparent: true, opacity: opacity,
            depthWrite: false, blending: THREE.AdditiveBlending
        }));
        pts.frustumCulled = false;
        scene.add(pts);
        return { pts: pts, n: n, head: 0 };
    }

    function layStream(s, curve, spread) {
        var pos = s.pts.geometry.attributes.position;
        for (var i = 0; i < s.n; i++) {
            var t = ((s.head - i * 0.016) % 1 + 1) % 1;
            var p = curve.getPoint(t);
            pos.setXYZ(i, p.x + (Math.random() - 0.5) * spread, p.y + (Math.random() - 0.5) * spread, p.z + (Math.random() - 0.5) * spread);
        }
        pos.needsUpdate = true;
    }

    var V3 = function (x, y, z) { return new THREE.Vector3(x, y, z); };
    var curveQuery = new THREE.CatmullRomCurve3([V3(-5.4, -1.7, 0.4), V3(-3.2, -1.1, 1.1), V3(-1.2, -0.4, 1.2), V3(0.45, 0.1, 0.7)]);
    var SPLIT = V3(0.45, 0.1, 0.7);
    // Stream targets follow the docs that actually exist in this tier.
    var bm25Doc = docs[2] || docs[0];
    var denseDoc = docs[docs.length - 1];
    function docTop(d) { return V3(d.base.x, d.base.y + 0.4, d.base.z + 0.3); }
    var curveBm25 = new THREE.CatmullRomCurve3([SPLIT, V3(-1.6, -0.3, 0.9), V3(-2.9, -0.9, 0.4), docTop(bm25Doc)]);
    var curveDense = new THREE.CatmullRomCurve3([SPLIT, V3(1.6, -0.5, 1.5), V3(3.2, -0.9, 1.3), docTop(denseDoc)]);

    var sQuery = streamPoints(26, 0.1, TEX_DOT_IVORY, 0xf1ece0, 0);
    var sBm25 = streamPoints(15, 0.085, TEX_DOT_IVORY, 0xcfd4da, 0);
    var sDense = streamPoints(15, 0.085, TEX_DOT_BRASS, 0xd4b377, 0);

    // citation trace (built at selection time from live world positions)
    var traceLine = null, traceDot = null, traceCurve = null;
    function buildTrace(from, to) {
        if (traceLine) { scene.remove(traceLine); traceLine.geometry.dispose(); traceLine.material.dispose(); }
        var mid = from.clone().add(to).multiplyScalar(0.5);
        mid.y += 0.55; mid.z += 0.5;
        traceCurve = new THREE.QuadraticBezierCurve3(from, mid, to);
        var geo = new THREE.BufferGeometry().setFromPoints(traceCurve.getPoints(60));
        traceLine = new THREE.Line(geo, new THREE.LineDashedMaterial({
            color: 0xd4b377, dashSize: 0.16, gapSize: 0.11, transparent: true, opacity: 0
        }));
        traceLine.computeLineDistances();
        traceLine.frustumCulled = false;
        scene.add(traceLine);
        if (!traceDot) {
            traceDot = new THREE.Sprite(new THREE.SpriteMaterial({
                map: TEX_DOT_BRASS, color: 0xf3e2b8, transparent: true, opacity: 0,
                depthWrite: false, blending: THREE.AdditiveBlending
            }));
            traceDot.scale.set(0.34, 0.34, 1);
            scene.add(traceDot);
        }
    }

    // background dust (one Points cloud) + faint far fragments
    var BG_P = TIER === 'mobile' ? 40 : (TIER === 'tablet' ? 80 : 130);
    var bgGeo = new THREE.BufferGeometry();
    var bgPos = new Float32Array(BG_P * 3);
    for (var bi = 0; bi < BG_P; bi++) {
        bgPos[bi * 3] = -9 + Math.random() * 18;
        bgPos[bi * 3 + 1] = -5 + Math.random() * 10;
        bgPos[bi * 3 + 2] = -9 + Math.random() * 6;
    }
    bgGeo.setAttribute('position', new THREE.BufferAttribute(bgPos, 3));
    var bgPts = new THREE.Points(bgGeo, new THREE.PointsMaterial({
        map: TEX_DOT_IVORY, color: 0x6b7480, size: 0.06,
        transparent: true, opacity: 0.32, depthWrite: false
    }));
    scene.add(bgPts);

    var fragments = [];
    if (TIER !== 'mobile') {
        for (var fi = 0; fi < 4; fi++) {
            var fmat = new THREE.MeshBasicMaterial({
                map: docTexture(fi % 2 ? 'SEBI' : 'RBI', fi % 2 ? 'CIRCULAR' : 'DIRECTION', '§ ' + (fi + 2), 'ARCHIVE'),
                transparent: true, opacity: 0.05 + Math.random() * 0.03, depthWrite: false
            });
            var frag = new THREE.Mesh(new THREE.PlaneGeometry(2.6 + fi * 0.4, 3.5 + fi * 0.5), fmat);
            frag.position.set(-6 + fi * 4.1, 2.6 - fi * 1.7, -6.5 - fi * 0.8);
            frag.rotation.set(0.1 * fi, 0.3 * (fi - 1.5), 0.06 * fi);
            scene.add(frag);
            fragments.push({ m: frag, ph: fi * 1.7 });
        }
    }

    /* ================= 7. CHOREOGRAPHY ================= */
    var sto = { n: 0 }; // trace draw progress
    var verifyPos = new THREE.Vector3();

    function dimOthers(on) {
        docs.forEach(function (d) {
            if (d === heroDoc) return;
            gsap.to(d.face.material, { opacity: on ? 0.45 : 1, duration: 1.1, ease: 'power2.inOut' });
            d.face.material.transparent = true;
            gsap.to(d.edge.material, { opacity: on ? 0.05 : 0.14, duration: 1.1 });
        });
    }

    function selectDoc() {
        heroDoc.selected = true;
        hoverDoc = -1;
        if (tooltip) tooltip.classList.remove('is-shown');
        gsap.to(heroDoc.group.position, { x: -0.85, z: 3.5, duration: 1.4, ease: 'power3.inOut' });
        gsap.to(heroDoc.group.rotation, { y: 0.1, z: 0, duration: 1.4, ease: 'power3.inOut' });
        gsap.to(heroDoc.group.scale, { x: 1.12, y: 1.12, z: 1.12, duration: 1.4, ease: 'power3.inOut' });
        gsap.to(heroDoc.edge.material, { opacity: 1, duration: 0.9 });
        dimOthers(true);
    }
    function releaseDoc() {
        heroDoc.selected = false;
        var b = heroDoc.base;
        gsap.to(heroDoc.group.position, { x: b.x, z: b.z, duration: 1.6, ease: 'power3.inOut' });
        gsap.to(heroDoc.group.rotation, { y: b.ry, z: b.rz, duration: 1.6, ease: 'power3.inOut' });
        gsap.to(heroDoc.group.scale, { x: 1, y: 1, z: 1, duration: 1.6, ease: 'power3.inOut' });
        gsap.to(heroDoc.edge.material, { opacity: 0.14, duration: 1.2 });
        dimOthers(false);
    }

    function flashMarkers(list, op) {
        list.forEach(function (d) {
            gsap.to(d.marker.material, { opacity: op, duration: 0.5, overwrite: 'auto' });
        });
    }

    function chip(el, show, dur) {
        if (!el) return;
        gsap.to(el, { opacity: show ? 1 : 0, duration: dur || 0.45, ease: 'power1.out', overwrite: 'auto' });
    }

    function masterTimeline() {
        var tl = gsap.timeline({ repeat: -1, defaults: { ease: 'power2.inOut' } });
        // PHASE 1 — idle drift (floats run independently)
        tl.call(function () {}, null, 0);
        // PHASE 2 — query arrives (3.2 → 4.7)
        tl.call(function () { chip(chipQuery, true); sQuery.head = 0; }, null, 3.2);
        tl.to(sQuery.pts.material, { opacity: 0.95, duration: 0.3 }, 3.2);
        tl.to(sQuery, { head: 1, duration: 1.4, ease: 'power1.in', onUpdate: function () { layStream(sQuery, curveQuery, 0.1); } }, 3.2);
        tl.call(function () { chip(chipQuery, false); }, null, 4.7);
        tl.to(sQuery.pts.material, { opacity: 0, duration: 0.5 }, 4.6);
        // PHASE 3 — retrieval split (4.8 → 7.3)
        tl.call(function () {
            chip(chipBm25, true); chip(chipDense, true);
            sBm25.head = 0; sDense.head = 0;
            flashMarkers([bm25Doc, denseDoc], 0.9);
        }, null, 4.8);
        tl.to([sBm25.pts.material, sDense.pts.material], { opacity: 0.9, duration: 0.3 }, 4.8);
        tl.to(sBm25, {
            head: 1, duration: 1.5, ease: 'power1.out',
            onUpdate: function () { layStream(sBm25, curveBm25, 0.07); }
        }, 4.8);
        tl.to(sDense, {
            head: 1, duration: 1.7, ease: 'power1.out',
            onUpdate: function () { layStream(sDense, curveDense, 0.07); }
        }, 4.9);
        tl.call(function () {
            chip(chipBm25, false); chip(chipDense, false);
            flashMarkers(docs, 0);
        }, null, 7.3);
        tl.to([sBm25.pts.material, sDense.pts.material], { opacity: 0, duration: 0.5 }, 7.1);
        // PHASE 4 — fusion (7.4 → 8.8)
        tl.call(function () { chip(chipRrf, true); }, null, 7.4);
        tl.to(nucleus.scale, { x: 1.3, y: 1.3, z: 1.3, duration: 0.5, ease: 'power2.out' }, 7.4);
        tl.to(nucleus.scale, { x: 1, y: 1, z: 1, duration: 0.9, ease: 'power2.inOut' }, 7.9);
        tl.call(function () { chip(chipRrf, false); }, null, 8.8);
        // PHASE 5 — evidence selection (8.9 → 10.4)
        tl.call(selectDoc, null, 8.9);
        // PHASE 6 — passage highlight (10.5 → 11.6)
        tl.to(passage.material, { opacity: 0.9, duration: 0.7 }, 10.5);
        // PHASE 7 — citation trace (11.7 → 13.4)
        tl.call(function () {
            passage.updateWorldMatrix(true, false);
            var from = new THREE.Vector3();
            passage.getWorldPosition(from);
            var to = new THREE.Vector3(CORE_POS.x - 1.0, CORE_POS.y + 0.1, CORE_POS.z + 0.4);
            buildTrace(from, to);
            if (traceLine) {
                traceLine.material.opacity = 0.95;
                traceLine.geometry.setDrawRange(0, 0); // grow from the passage
            }
            sto.n = 0;
        }, null, 11.7);
        tl.to(sto, {
            n: 60, duration: 1.4, ease: 'power1.inOut',
            onUpdate: function () {
                if (!traceLine || !traceCurve) return;
                traceLine.geometry.setDrawRange(0, Math.floor(sto.n));
                var p = traceCurve.getPoint(Math.min(sto.n / 60, 1));
                traceDot.position.copy(p);
                traceDot.material.opacity = 0.95;
            }
        }, 11.8);
        // PHASE 8 — verification (13.5 → 15.4)
        tl.call(function () {
            chip(chipVerified, true, 0.5);
            chip(chipConfidence, true, 0.5);
        }, null, 13.5);
        // PHASE 9 — reset (15.5 → 17.2)
        tl.call(function () { chip(chipVerified, false); chip(chipConfidence, false); }, null, 15.5);
        tl.to(passage.material, { opacity: 0, duration: 0.8 }, 15.6);
        tl.call(function () {
            if (traceLine) gsap.to(traceLine.material, { opacity: 0, duration: 0.7 });
            if (traceDot) gsap.to(traceDot.material, { opacity: 0, duration: 0.7 });
        }, null, 15.7);
        tl.call(releaseDoc, null, 15.8);
        tl.to({}, { duration: 0.4 }); // ~17.2s loop tail
        return tl;
    }

    /* ---- idle float (independent, layered timing) ----
       Y is owned by renderFrame (sine ease) so it never fights the
       selection tweens, which only drive x / z / rotation / scale. */
    if (!reduceMotion) {
        gsap.to(core.rotation, { y: '+=' + Math.PI * 2, duration: 52, repeat: -1, ease: 'none' });
        gsap.to(midMesh.rotation, { y: '-=' + Math.PI * 2, duration: 38, repeat: -1, ease: 'none' });
        gsap.to(midFrame.rotation, { y: '-=' + Math.PI * 2, duration: 38, repeat: -1, ease: 'none' });
    }

    /* ================= 8. LOOP / INTERACTION / LIFECYCLE ================= */
    var clockT = 0;
    var parallax = { x: 0, y: 0, tx: 0, ty: 0 };
    var heroSection = container.closest('.hero') || container;
    var visible = true;
    var degraded = false;
    var fpsAcc = 0, fpsN = 0, fpsT = 0;

    function projectTo(el, v3, dx, dy) {
        verifyPos.copy(v3).project(camera);
        var r = container.getBoundingClientRect();
        el.style.left = ((verifyPos.x * 0.5 + 0.5) * r.width + dx) + 'px';
        el.style.top = ((-verifyPos.y * 0.5 + 0.5) * r.height + dy) + 'px';
    }

    function renderFrame(dt) {
        clockT += dt;
        // idle float: layered sine per document; gentler while selected
        docs.forEach(function (d) {
            var amp = d.selected ? d.floatAmp * 0.35 : d.floatAmp;
            var ty = (d.selected ? 0.4 : d.base.y) +
                Math.sin(clockT * (Math.PI * 2 / d.floatDur) + d.floatPhase) * amp;
            d.group.position.y += (ty - d.group.position.y) * Math.min(1, dt * 3);
        });
        // core internals drift
        var pos = corePts.geometry.attributes.position;
        for (var i = 0; i < corePSeed.length; i++) {
            var s = corePSeed[i];
            var th = s.th + clockT * s.sp;
            pos.setXYZ(i,
                s.r * Math.sin(s.ph) * Math.cos(th),
                s.r * Math.cos(s.ph) * 0.9 + Math.sin(clockT * 0.6 + i) * 0.02,
                s.r * Math.sin(s.ph) * Math.sin(th));
        }
        pos.needsUpdate = true;
        bgPts.rotation.y = clockT * 0.004;
        bgPts.position.y = Math.sin(clockT * 0.07) * 0.25;
        fragments.forEach(function (f) {
            f.m.rotation.z += Math.sin(clockT * 0.1 + f.ph) * 0.0004;
            f.m.position.y += Math.cos(clockT * 0.09 + f.ph) * 0.0009;
        });
        // parallax ease (capped ≈ ±4°)
        parallax.x += (parallax.tx - parallax.x) * 0.045;
        parallax.y += (parallax.ty - parallax.y) * 0.045;
        camera.position.x = CAM_BASE.x + parallax.x;
        camera.position.y = CAM_BASE.y + parallax.y;
        camera.lookAt(CAM_LOOK);
        // keep verify chips glued near the core while shown
        if (chipVerified && chipVerified.style.opacity !== '0' && chipVerified.style.opacity !== '') {
            var anchor = new THREE.Vector3(CORE_POS.x + 0.4, CORE_POS.y + 1.75, CORE_POS.z);
            projectTo(chipVerified, anchor, 0, 0);
            projectTo(chipConfidence, anchor, 0, 30);
        }
        renderer.render(scene, camera);
    }

    function resize() {
        var w = container.clientWidth, h = container.clientHeight;
        if (!w || !h) return;
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
    }

    // mouse parallax + hover (fine pointers only)
    var raycaster = null, pointerNDC = null, hoverDoc = -1, hoverCore = false;
    var pointerDirty = false;
    if (!coarsePointer && TIER === 'desktop') {
        raycaster = new THREE.Raycaster();
        pointerNDC = new THREE.Vector2();
        heroSection.addEventListener('mousemove', function (e) {
            var r = container.getBoundingClientRect();
            if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) return;
            var nx = ((e.clientX - r.left) / r.width - 0.5) * 2;
            var ny = ((e.clientY - r.top) / r.height - 0.5) * 2;
            parallax.tx = nx * 0.55;
            parallax.ty = -ny * 0.38;
            pointerNDC.set(nx, -ny);
            pointerDirty = true;
            // tooltip follows
            if (tooltip && hoverDoc >= 0) {
                tooltip.style.left = (e.clientX - r.left) + 'px';
                tooltip.style.top = (e.clientY - r.top) + 'px';
            }
        });
        heroSection.addEventListener('mouseleave', function () {
            parallax.tx = 0; parallax.ty = 0;
            pointerNDC.set(10, 10); // push the ray off-screen so hover clears
            pointerDirty = true;
        });
    } else if (!reduceMotion) {
        // touch / small screens: whisper-quiet auto drift instead of parallax
        gsap.to(parallax, {
            tx: 0.22, duration: 7, yoyo: true, repeat: -1, ease: 'sine.inOut',
            onUpdate: function () { parallax.ty = parallax.tx * 0.4; }
        });
    }

    function pickHover() {
        if (!raycaster || !pointerNDC || !pointerDirty) return;
        pointerDirty = false;
        raycaster.setFromCamera(pointerNDC, camera);
        var hits = raycaster.intersectObjects(docs.map(function (d) { return d.hit; }));
        var idx = hits.length ? hits[0].object.userData.docIndex : -1;
        if (idx !== hoverDoc) {
            if (hoverDoc >= 0 && !docs[hoverDoc].selected) {
                gsap.to(docs[hoverDoc].group.position, { z: docs[hoverDoc].base.z, duration: 0.5, ease: 'power2.out', overwrite: 'auto' });
                gsap.to(docs[hoverDoc].edge.material, { opacity: 0.14, duration: 0.4 });
            }
            hoverDoc = idx;
            if (idx >= 0) {
                var d = docs[idx];
                if (!d.selected) gsap.to(d.group.position, { z: d.base.z + 0.55, duration: 0.5, ease: 'power2.out', overwrite: 'auto' });
                gsap.to(d.edge.material, { opacity: 1, duration: 0.4 });
                if (tooltip) {
                    tooltip.textContent = d.def.head + ' · ' + d.def.section;
                    tooltip.classList.add('is-shown');
                }
            } else if (tooltip) {
                tooltip.classList.remove('is-shown');
            }
        }
        // core hover
        var coreHit = raycaster.intersectObject(core.children[0], false).length > 0;
        if (coreHit !== hoverCore) {
            hoverCore = coreHit;
            gsap.to(core.scale, { x: coreHit ? 1.06 : 1, y: coreHit ? 1.06 : 1, z: coreHit ? 1.06 : 1, duration: 0.6, ease: 'power2.out' });
            coreLabels.forEach(function (sp) {
                gsap.to(sp.material, { opacity: coreHit ? 0.95 : 0, duration: 0.5 });
            });
        }
    }

    // pause off-screen; fps auto-degrade
    if ('IntersectionObserver' in window) {
        new IntersectionObserver(function (entries) {
            visible = entries[0].isIntersecting;
            if (story) story.paused(!visible);
        }, { threshold: 0.02 }).observe(container);
    }
    if ('ResizeObserver' in window) {
        new ResizeObserver(resize).observe(container);
    }
    window.addEventListener('resize', resize);
    // Stylesheets may still be loading when this module first runs;
    // re-measure once the page is fully loaded.
    window.addEventListener('load', resize);

    var story = null;
    if (!reduceMotion) {
        story = masterTimeline();
        markReady();
        var last = performance.now();
        gsap.ticker.add(function () {
            var now = performance.now();
            var dt = Math.min((now - last) / 1000, 0.1);
            last = now;
            if (!visible) return;
            // fps monitor → one-step graceful degrade
            if (!degraded) {
                fpsAcc += dt; fpsN++;
                if (fpsAcc >= 2.5) {
                    var avg = fpsN / fpsAcc;
                    if (avg < 38) {
                        degraded = true;
                        renderer.setPixelRatio(1);
                        bgPts.material.opacity = 0.18;
                        raycaster = null; // hover off, story untouched
                    }
                    fpsAcc = 0; fpsN = 0;
                }
            }
            pickHover();
            renderFrame(dt);
        });
    }

    function boot() {
        resize();
        // settle webfonts before baking text textures (1.2s cap)
        var ready = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();
        var timeout = new Promise(function (res) { setTimeout(res, 1200); });
        Promise.race([ready, timeout]).then(function () {
            // re-bake doc faces now that IBM Plex Mono / Inter are present
            docs.forEach(function (d) {
                var old = d.face.material.map;
                d.face.material.map = docTexture(d.def.head, d.def.title, d.def.section, d.def.meta);
                d.face.material.needsUpdate = true;
                if (old) old.dispose();
            });
            if (reduceMotion) {
                // one calm, premium still frame: the idle system at rest.
                // No tweens, no loop, no parallax — chips stay hidden.
                docs.forEach(function (d) { d.group.position.y = d.base.y; });
                renderFrame(0.016);
                markReady();
                return;
            }
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
    document.fonts && document.fonts.ready.then(function () { resize(); });
})();
