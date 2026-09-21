/* RegIntel landing init (extracted from index.html so the page works
   under a strict Content-Security-Policy with no 'unsafe-inline').
   Served same-origin at /landing-init.js. */
        (function () {
            'use strict';
            const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

            /* ---------- Hero entrance ---------- */
            function initHero() {
                const hero = document.querySelector('.hero');
                if (!hero) return;
                requestAnimationFrame(() => {
                    hero.classList.add('is-loaded');
                    // animate the hero trace line
                    if (prefersReducedMotion) return;
                    const line = hero.querySelector('.hero-trace-line');
                    const ends = hero.querySelectorAll('.hero-trace-end');
                    if (!line) return;
                    const len = line.getTotalLength();
                    line.style.strokeDasharray = len;
                    line.style.strokeDashoffset = len;
                    setTimeout(() => {
                        line.style.transition = 'stroke-dashoffset 1.4s ease-out';
                        line.style.strokeDashoffset = '0';
                        ends.forEach(e => { e.style.transition = 'opacity 0.4s ease 1.2s'; e.style.opacity = '1'; });
                    }, 900);
                });
            }

            /* ---------- Scroll reveal ---------- */
            function initReveal() {
                const els = document.querySelectorAll('.reveal');
                if (prefersReducedMotion) {
                    els.forEach(e => e.classList.add('is-in'));
                    return;
                }
                const io = new IntersectionObserver((entries) => {
                    entries.forEach(en => {
                        if (en.isIntersecting) {
                            en.target.classList.add('is-in');
                            io.unobserve(en.target);
                        }
                    });
                }, { rootMargin: '-10% 0px -10% 0px', threshold: 0.05 });
                els.forEach(e => io.observe(e));
            }

            /* ---------- Retrieval step-through ---------- */
            function initRetrievalSteps() {
                const section = document.querySelector('.retrieval');
                if (!section) return;
                const steps = section.querySelectorAll('.rstep');
                const stageLabel = document.getElementById('rdiag-stage');

                // diagram node groups per step
                const stepNodes = {
                    '1': ['n-query'],
                    '2': ['n-query', 'n-dense', 'e-qd'],
                    '3': ['n-query', 'n-bm25', 'e-qb'],
                    '4': ['n-fusion', 'e-df', 'e-bf', 'lbl-dense', 'lbl-bm25', 'lbl-fusion'],
                    '5': ['n-xenc', 'e-fx', 'lbl-xenc'],
                    '6': ['n-result', 'e-xr']
                };

                function setActive(stepNum) {
                    steps.forEach(s => {
                        s.classList.toggle('is-active', s.dataset.step === stepNum);
                    });
                    if (stageLabel) stageLabel.textContent = 'Stage 0' + stepNum + ' / 06';

                    // light up diagram nodes for this step (cumulative)
                    const allIds = ['n-query', 'n-dense', 'n-bm25', 'n-fusion', 'n-xenc', 'n-result', 'e-qd', 'e-qb', 'e-df', 'e-bf', 'e-fx', 'e-xr', 'lbl-dense', 'lbl-bm25', 'lbl-fusion', 'lbl-xenc'];
                    const activeForStep = new Set();
                    // accumulate from step 1 through current
                    for (let i = 1; i <= parseInt(stepNum, 10); i++) {
                        (stepNodes[String(i)] || []).forEach(id => activeForStep.add(id));
                    }
                    allIds.forEach(id => {
                        const el = document.getElementById(id);
                        if (!el) return;
                        const isActive = activeForStep.has(id);
                        if (el.classList.contains('rdiag-node')) {
                            el.classList.toggle('active', isActive);
                            el.classList.toggle('dim', !isActive);
                        } else if (el.classList.contains('rdiag-edge')) {
                            el.classList.toggle('active', isActive);
                        } else if (el.classList.contains('rdiag-label')) {
                            el.classList.toggle('active', isActive);
                        }
                    });
                }

                if (prefersReducedMotion) {
                    setActive('6');
                    return;
                }

                const io = new IntersectionObserver((entries) => {
                    entries.forEach(en => {
                        if (en.isIntersecting) {
                            setActive(en.target.dataset.step);
                        }
                    });
                }, { rootMargin: '-40% 0px -40% 0px', threshold: 0 });
                steps.forEach(s => io.observe(s));
            }

            /* ---------- Citation trace drawing ---------- */
            function initCitationTrace() {
                const container = document.getElementById('trace-container');
                if (!container) return;
                const path = document.getElementById('trace-path');
                const dotA = document.getElementById('trace-dot-a');
                const dotB = document.getElementById('trace-dot-b');
                const svg = document.getElementById('trace-svg');
                const target = document.getElementById('cite-target-1');
                const origin = document.getElementById('cite-origin-1');

                function positionAndDraw() {
                    if (!target || !origin || !container) return;
                    const cRect = container.getBoundingClientRect();
                    const tRect = target.getBoundingClientRect();
                    const oRect = origin.getBoundingClientRect();

                    // set svg viewBox to container size in px
                    svg.setAttribute('viewBox', `0 0 ${cRect.width} ${cRect.height}`);
                    svg.setAttribute('width', cRect.width);
                    svg.setAttribute('height', cRect.height);

                    // source point: right edge of target text, vertical center
                    const x1 = tRect.right - cRect.left;
                    const y1 = tRect.top + tRect.height / 2 - cRect.top;
                    // destination point: left edge of origin text, vertical center
                    const x2 = oRect.left - cRect.left;
                    const y2 = oRect.top + oRect.height / 2 - cRect.top;

                    // control points for a smooth curve
                    const dx = x2 - x1;
                    const midX = x1 + dx * 0.5;
                    const cp1x = x1 + dx * 0.3;
                    const cp1y = y1;
                    const cp2x = x2 - dx * 0.3;
                    const cp2y = y2;
                    const d = `M ${x1} ${y1} C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${x2} ${y2}`;
                    path.setAttribute('d', d);

                    dotA.setAttribute('cx', x1);
                    dotA.setAttribute('cy', y1);
                    dotB.setAttribute('cx', x2);
                    dotB.setAttribute('cy', y2);

                    if (prefersReducedMotion) {
                        path.style.strokeDasharray = 'none';
                        path.style.strokeDashoffset = '0';
                        dotA.style.opacity = 1;
                        dotB.style.opacity = 1;
                        target.classList.add('lit');
                        origin.classList.add('lit');
                        return;
                    }

                    const len = path.getTotalLength();
                    path.style.strokeDasharray = len;
                    path.style.strokeDashoffset = len;
                    path.style.transition = 'none';
                    // force reflow
                    void path.getBoundingClientRect();
                    path.style.transition = 'stroke-dashoffset 1.6s ease-out';
                    path.style.strokeDashoffset = '0';

                    dotA.style.opacity = '0';
                    dotB.style.opacity = '0';
                    dotA.style.transition = 'opacity 0.3s ease';
                    dotB.style.transition = 'opacity 0.3s ease 1.3s';
                    dotA.style.opacity = '1';
                    dotB.style.opacity = '1';

                    // light up the source and answer highlights
                    setTimeout(() => { target.classList.add('lit'); }, 200);
                    setTimeout(() => { origin.classList.add('lit'); }, 1300);
                }

                let triggered = false;
                function maybeTrigger() {
                    if (triggered) return;
                    const rect = container.getBoundingClientRect();
                    if (rect.top < window.innerHeight * 0.7 && rect.bottom > 0) {
                        triggered = true;
                        positionAndDraw();
                    }
                }

                if (prefersReducedMotion) {
                    positionAndDraw();
                    return;
                }

                window.addEventListener('scroll', maybeTrigger, { passive: true });
                window.addEventListener('resize', () => {
                    triggered = false;
                    positionAndDraw();
                    triggered = true;
                });
                maybeTrigger();
            }

            /* ---------- Knowledge graph reveal ---------- */
            function initGraph() {
                const graph = document.querySelector('.graph');
                if (!graph) return;
                if (prefersReducedMotion) {
                    graph.classList.add('is-in');
                    return;
                }
                const io = new IntersectionObserver((entries) => {
                    entries.forEach(en => {
                        if (en.isIntersecting) {
                            en.target.classList.add('is-in');
                            io.unobserve(en.target);
                        }
                    });
                }, { rootMargin: '-15% 0px -15% 0px', threshold: 0.1 });
                io.observe(graph);
            }

            /* ---------- Briefing form ---------- */
            function initForm() {
                const form = document.getElementById('briefing-form');
                const submit = document.getElementById('briefing-submit');
                const success = document.getElementById('closing-success');
                if (!form || !submit) return;
                submit.addEventListener('click', () => {
                    // minimal validation
                    const name = form.querySelector('#f-name');
                    const inst = form.querySelector('#f-inst');
                    const email = form.querySelector('#f-email');
                    let valid = true;
                    [name, inst, email].forEach(f => {
                        if (!f.value.trim()) {
                            f.style.borderBottomColor = 'var(--redline)';
                            valid = false;
                        } else {
                            f.style.borderBottomColor = '';
                        }
                    });
                    if (email && email.value && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value)) {
                        email.style.borderBottomColor = 'var(--redline)';
                        valid = false;
                    }
                    if (!valid) return;
                    if (success) success.classList.add('is-shown');
                    form.style.display = 'none';
                    submit.style.display = 'none';
                });
            }

            /* ---------- Smooth scroll for in-page anchors (with nav offset) ---------- */
            function initAnchors() {
                document.querySelectorAll('a[href^="#"]').forEach(a => {
                    a.addEventListener('click', (e) => {
                        const id = a.getAttribute('href');
                        if (id.length < 2) return;
                        const target = document.querySelector(id);
                        if (!target) return;
                        e.preventDefault();
                        const offset = 70;
                        const top = target.getBoundingClientRect().top + window.scrollY - offset;
                        window.scrollTo({ top, behavior: prefersReducedMotion ? 'auto' : 'smooth' });
                    });
                });
            }

            /* ---------- Init all ---------- */
            document.addEventListener('DOMContentLoaded', () => {
                initHero();
                initReveal();
                initRetrievalSteps();
                initCitationTrace();
                initGraph();
                initForm();
                initAnchors();
            });
        })();

/* Fallback watchdog: if the 3D module hasn't signalled readiness
   within 12s (blocked CDN, no WebGL, old browser), show the static
   fallback composition instead of an empty frame. The module cancels
   this via markReady() if it boots late, so slow networks recover. */
        (function () {
            setTimeout(function () {
                var v = document.getElementById('heroVisual');
                if (v && !v.dataset.ready) {
                    v.classList.add('is-fallback');
                    v.dataset.failReason = 'timeout';
                    try { console.info('[hero3d] static fallback: timeout'); } catch (e) {}
                }
            }, 12000);
        })();
