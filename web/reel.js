/* ==========================================================================
   CUTLIST - reel.js
   Act I: the scroll film, and the cut that takes you into the desk.

   Everything drawn here is read from window.CUTLIST_DATA, the same file the
   EDLs were written beside. There are no decorative numbers and no stock
   imagery: a "frame" is an episode's own stop-power curve, the grounding
   wall is the real lattice of legal in-points, and the strip's perforations
   are an inline SVG pattern. If the pipeline is re-run with different
   weights, this page changes with it.

   Two engineering notes worth stating up front:

   - The reel is 50 cells on a shallow parabola in Z, each cell carrying its
     own perforations. Film is built that way, and modelling it that way is
     also the only way the strip stays a strip when it curves: a single flat
     backing plate behind curved frames gets occluded by its own film.

   - Scroll position is read once per frame inside the rAF callback and
     never during an event, so no handler here can force a layout.
   ========================================================================== */
'use strict';

(function () {

  /* ------------------------------- plumbing ------------------------------ */

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const easeOut = t => 1 - Math.pow(1 - t, 3);
  const pad2 = n => String(n).padStart(2, '0');
  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const group = n => Math.round(n).toLocaleString('en-US');

  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const still = () => motion.matches;

  /* backdrop.js is an independent layer; the film must run without it. */
  const BD = (function () {
    const noop = () => {};
    const stub = { mount: noop, setMood: noop, setEnergy: noop, pulse: noop, weave: noop, destroy: noop };
    return new Proxy(stub, {
      get: (t, k) => (window.Backdrop && typeof window.Backdrop[k] === 'function')
        ? window.Backdrop[k].bind(window.Backdrop) : t[k] || noop
    });
  })();

  const KIND_COLOR = { DIALOGUE: '#77aadc', ACTION: '#e28a60', CAMERA: '#64a6af', SFX: '#be8ce9' };
  const ACCENT = '#7170ff';

  const D = window.CUTLIST_DATA;
  if (!D || !D.episodes || !D.promos) {
    const n = $('#film');
    if (n) n.innerHTML = '<div class="scene"><div class="scene-in"><h2 class="display">' +
      'No cut list loaded.</h2><p class="lead">This page reads <span class="mono">promos.js</span>, ' +
      'written by <span class="mono">python -m cutlist run data/scripts</span>. Run it and reload.</p></div></div>';
    return;
  }

  const EPS = D.episodes.slice().sort((a, b) => a.number - b.number);
  const BY_NO = new Map(EPS.map(e => [e.number, e]));
  const PROMOS = D.promos;
  const META = D.meta || {};
  const N = EPS.length;

  /* Which promo, if any, each episode carries. First (best-ranked) wins. */
  const PROMO_OF = new Map();
  for (const p of PROMOS) {
    for (const s of p.segments) if (!PROMO_OF.has(s.episode)) PROMO_OF.set(s.episode, { p: p, seg: s });
  }

  /* ----------------------------------------------------------------------
     FILM GEOMETRY
     35mm KS: four perforations per frame, holes on both long edges, the
     image inset from the edge. The frames here are 9:16 because that is the
     delivery format - vertical frames in a horizontal strip, which is what
     a microdrama reel would actually look like if it existed on film.
     ---------------------------------------------------------------------- */

  /* SMPTE ST 139-2003 Table 1, in millimetres. Kept as the real dimensions
     and scaled once, so the drawing is a measurement rather than a
     resemblance - and so the hole-to-pitch ratio comes out at the true 0.418
     instead of the 0.5 everybody draws by eye. */
  const MM = {
    filmW: 34.975,      // 1.377in
    perfAcross: 2.794,  // the long axis of the hole, across the film
    perfAlong: 1.981,   // the short axis, along the film: 1.981/4.740 = 0.418
    perfPitch: 4.740,   // short (negative) pitch
    edgeToPerf: 2.007,
    fillet: 0.508,
    frameLine: 0.15
  };
  MM.pitch3 = MM.perfPitch * 3;                                  // 14.220 - 3-perf pulldown
  MM.usable = MM.filmW - 2 * (MM.edgeToPerf + MM.perfAcross);     // 25.373 between the perfs
  MM.picAlong = MM.pitch3 - MM.frameLine * 2;                     // 13.920
  MM.picAcross = MM.picAlong * 16 / 9;                            // 24.747 - fits with 0.31 to spare

  const SCALE = 11.6;                                             // px per mm
  const px = mm => mm * SCALE;
  const FR = {
    cellW: px(MM.pitch3), cellH: px(MM.filmW),
    band: px(MM.edgeToPerf + MM.perfAcross),
    picX: (px(MM.pitch3) - px(MM.picAlong)) / 2,
    picY: (px(MM.filmW) - px(MM.picAcross)) / 2,
    pitch: px(MM.perfPitch),
    imgW: px(MM.picAlong), imgH: px(MM.picAcross)
  };

  /** One perforation, as an SVG pattern cell: one pitch wide, one band tall. */
  function perfPattern() {
    const w = FR.pitch, h = FR.band;
    const hw = px(MM.perfAlong), hh = px(MM.perfAcross);
    const x = (w - hw) / 2, y = px(MM.edgeToPerf), r = px(MM.fillet);
    const hole = 'x="' + x.toFixed(2) + '" y="' + y.toFixed(2) + '" width="' + hw.toFixed(2) +
      '" height="' + hh.toFixed(2) + '" rx="' + r.toFixed(2) + '"';
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="' + w.toFixed(2) + '" height="' + h.toFixed(2) + '">' +
      '<rect width="100%" height="100%" fill="#0A0A12"/>' +
      '<rect ' + hole + ' fill="#CFD0DC" fill-opacity="0.13"/>' +
      '<rect ' + hole + ' fill="none" stroke="#000" stroke-opacity="0.75"/>' +
      '</svg>';
    return 'url("data:image/svg+xml,' + encodeURIComponent(svg) + '")';
  }

  /* ----------------------------------------------------------------------
     AN EPISODE, DRAWN
     The curve is the per-second maximum stop-power the ranker computed -
     exported straight out of signals.py. Drawn as a symmetric envelope so a
     vertical frame reads as a shape rather than a graph.
     ---------------------------------------------------------------------- */

  function envelopeSVG(ep, w, h, opts) {
    const o = opts || {};
    const prof = ep.profile || [];
    if (!prof.length) return '';
    /* Stepped, not smoothed. The underlying number is a per-second maximum,
       so a step is what the data actually says; interpolating between them
       would draw a curve the ranker never computed. */
    const n = prof.length, mid = h / 2, amp = h * (o.amp || 0.40);
    let top = '', bot = '';
    for (let i = 0; i < n; i++) {
      const x0 = ((i / n) * w).toFixed(1), x1 = (((i + 1) / n) * w).toFixed(1);
      // a floor, so a quiet stretch still reads as exposed film, not as a gap
      const a = (0.055 + 0.945 * (prof[i] / 100)) * amp;
      const up = (mid - a).toFixed(1), dn = (mid + a).toFixed(1);
      top += (i ? 'L' : 'M') + x0 + ' ' + up + 'L' + x1 + ' ' + up;
      bot = 'L' + x1 + ' ' + dn + 'L' + x0 + ' ' + dn + bot;
    }
    const fill = o.fill || '#2A2C45';
    const line = o.line || '#555A86';
    let out = '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true">' +
      '<path d="' + top + bot + 'Z" fill="' + fill + '"/>' +
      '<path d="' + top + '" fill="none" stroke="' + line + '" stroke-width="0.9"/>' +
      '<line x1="0" y1="' + mid + '" x2="' + w + '" y2="' + mid + '" stroke="#ffffff" stroke-opacity="0.05"/>';

    // beat-kind ticks along the base, for the frames big enough to show them
    if (o.ticks && o.ticks.length) {
      for (const t of o.ticks) {
        const x = (t.at / ep.duration) * w;
        out += '<rect x="' + x.toFixed(1) + '" y="' + (h - 7) + '" width="1.3" height="5" fill="' +
          (KIND_COLOR[t.kind] || '#666') + '" fill-opacity="0.85"/>';
      }
    }
    return out + '</svg>';
  }

  /* ============================== REVEAL =============================== */

  const revealer = new IntersectionObserver(entries => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const el = e.target;
      const delay = +(el.dataset.reveal || 0);
      if (delay) el.style.transitionDelay = delay + 'ms';
      el.classList.add('seen');
      revealer.unobserve(el);
      // the counter is usually a span inside the revealed block, not the block
      (el.matches('[data-count]') ? [el] : $$('[data-count]', el)).forEach(countUp);
    }
  }, { rootMargin: '0px 0px -12% 0px', threshold: 0.08 });

  function watchReveals(root) {
    $$('[data-reveal]', root || document).forEach(el => {
      if (!el.classList.contains('seen')) revealer.observe(el);
    });
  }

  /** Numbers arrive by counting, because a figure this large should take a
      moment to land. Reduced motion gets it immediately. */
  function countUp(el) {
    const to = +el.dataset.count, dp = +(el.dataset.dp || 0);
    if (still()) { el.firstChild.nodeValue = to.toFixed(dp); return; }
    const t0 = performance.now(), ms = 1100;
    const node = el.firstChild;
    (function tick(now) {
      const t = clamp((now - t0) / ms, 0, 1);
      node.nodeValue = (to * easeOut(t)).toFixed(dp);
      if (t < 1) requestAnimationFrame(tick);
      else node.nodeValue = dp ? to.toFixed(dp) : group(to);
    })(t0);
  }

  /* =========================== SCENE 1: LEADER =========================== */

  /* ----------------------------------------------------------------------
     The SMPTE Universal Leader, to spec.

     SMPTE RP 428-6: the leader "is based upon a sweeping clock arm
     completing one revolution per second" - 15 degrees per frame at 24fps -
     and runs exactly 192 frames. Frame 1 reads PICTURE START, each numeral
     holds 24 frames from 8 down to 3, frame 145 is the sync pop, and the
     47 black frames after it put the pop exactly 2.000 seconds before first
     picture. There is no numeral 2: the pop is what happens at two.

     On the first frame of every numeral the arm, the inner circle and the
     crosshairs all disappear and the disc resets - a one-frame strobe,
     once a second, which is the detail that makes it read as film rather
     than as a loading spinner.

     The clock is quantised to 24fps on purpose. The one deliberate
     departure is tonal: a real leader is dark figures on light grey, which
     as a 300px disc on this page would be a torch pointed at the reader, so
     the values are inverted. Geometry and timing are untouched.
     ---------------------------------------------------------------------- */
  const LEADER = {
    fps: 24, total: 192, first: 2, hold: 24, from: 8, to: 3, pop: 145,
    font: 'ui-monospace, "SF Mono", Menlo, monospace'
  };

  function leader(canvas) {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    let R = 0, cx = 0, cy = 0;

    function size() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const r = canvas.getBoundingClientRect();
      const w = Math.max(80, r.width), h = Math.max(80, r.height);
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cx = w / 2; cy = h / 2; R = Math.min(w, h) / 2 - 2;
    }

    function ring(k, style, lw) {
      ctx.strokeStyle = style; ctx.lineWidth = lw || 1;
      ctx.beginPath(); ctx.arc(cx, cy, R * k, 0, Math.PI * 2); ctx.stroke();
    }

    function crosshair() {
      ctx.strokeStyle = 'rgba(163,164,191,0.26)'; ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(cx - R, cy); ctx.lineTo(cx - R * 0.12, cy);
      ctx.moveTo(cx + R * 0.12, cy); ctx.lineTo(cx + R, cy);
      ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy - R * 0.12);
      ctx.moveTo(cx, cy + R * 0.12); ctx.lineTo(cx, cy + R);
      ctx.stroke();
    }

    function ticks() {
      ctx.strokeStyle = 'rgba(163,164,191,0.16)'; ctx.lineWidth = 1;
      for (let i = 0; i < 48; i++) {
        const a = (i / 48) * Math.PI * 2, r1 = R * 0.88, r2 = i % 4 ? R * 0.93 : R * 0.97;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
        ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2);
        ctx.stroke();
      }
    }

    /** What the leader holds on once it has run out: the corpus itself. */
    function settled() {
      ctx.clearRect(0, 0, cx * 2, cy * 2);
      ring(0.97, 'rgba(163,164,191,0.20)');
      ring(0.70, 'rgba(163,164,191,0.14)');
      ring(0.42, 'rgba(163,164,191,0.10)');
      crosshair(); ticks();
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = 'rgba(163,164,191,0.52)';
      ctx.font = '510 ' + (R * 0.105).toFixed(0) + 'px ' + LEADER.font;
      ctx.fillText('PICTURE START', cx, cy - R * 0.17);
      ctx.fillStyle = 'rgba(252,252,252,0.82)';
      ctx.font = '300 ' + (R * 0.30).toFixed(0) + 'px ' + LEADER.font;
      ctx.fillText(group(META.beats || 0), cx, cy + R * 0.11);
      ctx.fillStyle = 'rgba(163,164,191,0.40)';
      ctx.font = '400 ' + (R * 0.082).toFixed(0) + 'px ' + LEADER.font;
      ctx.fillText('BEATS INDEXED', cx, cy + R * 0.32);
    }

    size();
    window.addEventListener('resize', () => { size(); if (done) settled(); });

    if (still()) { settled(); return; }

    const t0 = performance.now();
    let done = false;

    function draw(now) {
      const frame = 1 + Math.floor((now - t0) / (1000 / LEADER.fps));
      if (frame > LEADER.total) { done = true; settled(); return; }

      ctx.clearRect(0, 0, cx * 2, cy * 2);

      const counting = frame >= LEADER.first && frame < LEADER.pop;
      const k = counting ? (frame - LEADER.first) % LEADER.hold : -1;   // frame within numeral
      const numeral = counting ? LEADER.from - Math.floor((frame - LEADER.first) / LEADER.hold) : 0;
      const reset = k === 0;                                            // the one-frame strobe

      if (counting) {
        // disc: light ahead of the arm, dark behind it
        ctx.fillStyle = 'rgba(126,128,166,0.10)';
        ctx.beginPath(); ctx.arc(cx, cy, R * 0.97, 0, Math.PI * 2); ctx.fill();
        if (!reset) {
          const a = (Math.PI / 180) * 15 * k;
          ctx.fillStyle = 'rgba(7,7,12,0.74)';
          ctx.beginPath(); ctx.moveTo(cx, cy);
          ctx.arc(cx, cy, R * 0.97, -Math.PI / 2, -Math.PI / 2 + a);
          ctx.closePath(); ctx.fill();
          ctx.strokeStyle = 'rgba(224,225,235,0.50)'; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(cx, cy);
          ctx.lineTo(cx + Math.cos(-Math.PI / 2 + a) * R * 0.97, cy + Math.sin(-Math.PI / 2 + a) * R * 0.97);
          ctx.stroke();
        }
      }

      ring(0.97, 'rgba(163,164,191,0.22)');
      if (!reset) ring(0.42, 'rgba(163,164,191,0.12)');
      if (!reset) crosshair();
      ticks();

      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      if (frame === 1) {
        ctx.fillStyle = 'rgba(252,252,252,0.88)';
        ctx.font = '510 ' + (R * 0.15).toFixed(0) + 'px ' + LEADER.font;
        ctx.fillText('PICTURE', cx, cy - R * 0.15);
        ctx.font = '510 ' + (R * 0.30).toFixed(0) + 'px ' + LEADER.font;
        ctx.fillText('START', cx, cy + R * 0.16);
      } else if (counting) {
        // RP 428-6: numeral height is 47.4% of frame height
        ctx.fillStyle = 'rgba(252,252,252,0.92)';
        ctx.font = '300 ' + (R * 0.95).toFixed(0) + 'px ' + LEADER.font;
        ctx.fillText(String(numeral), cx, cy + R * 0.03);
      } else if (frame === LEADER.pop) {
        // the sync pop: everything inside the outer circle goes white
        ctx.fillStyle = 'rgba(237,237,242,0.94)';
        ctx.beginPath(); ctx.arc(cx, cy, R * 0.97, 0, Math.PI * 2); ctx.fill();
        crosshair();
        BD.pulse(0.45);
      }

      requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
  }

  /* ======================== SCENE 2: THE CREATIVE FIELD ================== */

  /* 5,770 tiles would be 5,770 nodes for one metaphor. 1,200 is the same
     picture at a fifth of the cost, and the caption says what the scale is
     rather than letting the grid imply it. */
  function creativeField(host, lit) {
    const cells = 1200;
    let html = '';
    const on = new Set();
    while (on.size < lit) on.add(Math.floor(Math.random() * cells));
    for (let i = 0; i < cells; i++) html += on.has(i) ? '<i class="lit"></i>' : '<i></i>';
    host.innerHTML = html;
  }

  /* ========================== SCENE 3: THE REEL ========================== */

  const reel = {
    rail: null, cells: [], focus: 0, target: 0, running: false, built: false,
    read: null, ticks: [], cursor: null, lastShown: -1
  };

  function buildReel() {
    const stage = $('#reelStage');
    if (!stage) return;
    const root = document.documentElement.style;
    root.setProperty('--cell-w', FR.cellW.toFixed(2) + 'px');
    root.setProperty('--cell-h', FR.cellH.toFixed(2) + 'px');
    root.setProperty('--perf-band', FR.band.toFixed(2) + 'px');
    root.setProperty('--perf-pitch', FR.pitch.toFixed(2) + 'px');
    root.setProperty('--pic-x', FR.picX.toFixed(2) + 'px');
    root.setProperty('--pic-y', FR.picY.toFixed(2) + 'px');
    root.setProperty('--perf-svg', perfPattern());

    const rail = document.createElement('div');
    rail.className = 'reel-rail';

    reel.cells = EPS.map((ep, i) => {
      const cell = document.createElement('div');
      cell.className = 'fr';
      cell.style.left = (i * FR.cellW).toFixed(2) + 'px';

      const hit = PROMO_OF.get(ep.number);
      let win = '';
      if (hit) {
        const l = (hit.seg.start / ep.duration) * 100, w = (hit.seg.duration / ep.duration) * 100;
        win = '<div class="fr-win" style="left:' + l.toFixed(2) + '%;width:' + w.toFixed(2) + '%"></div>';
      }
      cell.innerHTML =
        '<div class="em">' +
          envelopeSVG(ep, FR.imgW, FR.imgH, { amp: 0.40 }) + win +
          '<span class="fr-no">' + pad2(ep.number) + '</span>' +
          (hit ? '<span class="fr-rank">P' + pad2(hit.p.rank) + '</span>' : '') +
        '</div>';
      rail.appendChild(cell);
      return { el: cell, ep: ep, i: i, shown: true, promo: hit };
    });

    stage.appendChild(rail);
    const fade = document.createElement('div');
    fade.className = 'reel-fade';
    stage.appendChild(fade);
    reel.rail = rail;
    reel.read = {
      no: $('#rrNo'), log: $('#rrLog'), stats: $('#rrStats'), mix: $('#rrMix')
    };

    // scrub strip: one tick per episode, marked where a promo was found
    const sc = $('#reelTicks');
    if (sc) {
      sc.innerHTML = EPS.map(e => '<i class="' + (PROMO_OF.has(e.number) ? 'has' : '') + '"></i>').join('');
      reel.ticks = $$('i', sc);
      reel.cursor = $('#reelCursor');
    }
    reel.built = true;
    layoutReel();
    showEpisode(0);
  }

  /* The strip is rigid: 16 degrees off the camera, slid along its own axis.
     cos(16) = 0.961, so the foreshortening is 4% - it reads as a strip
     running away from you, not as a fanned-out deck of cards.

     Per frame this writes ONE transform. Everything else - the fade at both
     ends, the size falloff - is perspective and a static overlay doing the
     work, which is the difference between a reel that holds 60fps with 50
     frames in it and one that does not. */
  const WINDOW = 11;
  let shownCentre = -999;

  function layoutReel() {
    const f = reel.focus;
    const tx = -(f * FR.cellW + FR.cellW / 2);
    /* The pushback is first, in world space, so the whole strip sits back
       from the lens. Without it the near end of a 24-degree strip magnifies
       past 1.5x and grows out of the stage; with it the reel fits the band
       it has been given and still recedes. */
    reel.rail.style.transform =
      'translateZ(-240px) rotateX(7deg) rotateY(24deg) translate3d(' + tx.toFixed(2) + 'px,0,0)';

    const centre = clamp(Math.round(f), 0, N - 1);
    if (centre !== shownCentre) {
      shownCentre = centre;
      // visibility, not display: the cells are absolutely positioned, so
      // hiding them this way skips the paint without forcing the strip
      // through layout again every time the focus crosses a frame line.
      for (const c of reel.cells) {
        const show = Math.abs(c.i - centre) <= WINDOW;
        if (show !== c.shown) { c.el.style.visibility = show ? '' : 'hidden'; c.shown = show; }
      }
      for (const c of reel.cells) c.el.classList.toggle('focus', c.i === centre);
    }
  }

  function showEpisode(i) {
    if (i === reel.lastShown || !reel.read) return;
    reel.lastShown = i;
    const ep = EPS[i], hit = PROMO_OF.get(ep.number);
    reel.read.no.innerHTML = 'EP' + pad2(ep.number) + ' <span>/ ' + pad2(N) + '</span>';
    reel.read.log.innerHTML = esc(ep.logline || '');
    const peak = Math.max.apply(null, ep.profile && ep.profile.length ? ep.profile : [0]);
    reel.read.stats.innerHTML =
      stat(ep.beats, 'beats') +
      stat(ep.duration_tc, 'runtime') +
      stat((ep.characters || []).length, 'speaking') +
      stat(peak, 'peak') +
      stat(hit ? 'P' + pad2(hit.p.rank) : '--', 'promo');
    const mix = ep.mix || {};
    const tot = Math.max(1, (mix.DIALOGUE || 0) + (mix.ACTION || 0) + (mix.CAMERA || 0) + (mix.SFX || 0));
    reel.read.mix.innerHTML = ['DIALOGUE', 'ACTION', 'CAMERA', 'SFX']
      .map(k => '<i style="width:' + ((mix[k] || 0) / tot * 100).toFixed(2) + '%;background:' + KIND_COLOR[k] + '"></i>').join('');

    for (let k = 0; k < reel.ticks.length; k++) reel.ticks[k].classList.toggle('on', k === i);
    if (reel.cursor) reel.cursor.style.left = ((i / Math.max(1, N - 1)) * 100).toFixed(3) + '%';
  }

  const stat = (v, k) => '<span class="s"><span class="v">' + esc(v) + '</span><span class="k">' + esc(k) + '</span></span>';

  /* =========================== SCENE 5: THE WALL ========================= */

  /* 61,612 cells: every timestamp these screenplays can express at the
     precision they are written in. 3,419 are lit - the in-points that
     actually exist. The dark ones are the space a model asked for a raw
     timestamp is sampling from. */
  function buildWall(canvas) {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const total = EPS.reduce((a, e) => a + (e.expressible || 0), 0);
    const legal = new Uint8Array(total);
    let base = 0;
    for (const ep of EPS) {
      const n = ep.expressible || 0;
      for (const s of (ep.starts || [])) if (s >= 0 && s < n) legal[base + s] = 1;
      base += n;
    }

    const CELL = 2;
    let cols = 0, rows = 0, dpr = 1, revealed = 0;

    function size() {
      const w = Math.max(240, canvas.parentElement.clientWidth - 26);
      cols = Math.max(40, Math.floor(w / CELL));
      rows = Math.ceil(total / cols);
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.style.width = (cols * CELL) + 'px';
      canvas.style.height = (rows * CELL) + 'px';
      canvas.width = Math.round(cols * CELL * dpr);
      canvas.height = Math.round(rows * CELL * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      revealed = 0;
      ctx.clearRect(0, 0, cols * CELL, rows * CELL);
    }

    /** Draws columns [from, to). Called in slices so the plate develops. */
    function paint(from, to) {
      for (let c = from; c < to; c++) {
        for (let r = 0; r < rows; r++) {
          const i = r * cols + c;
          if (i >= total) break;
          const x = c * CELL, y = r * CELL;
          if (legal[i]) {
            ctx.fillStyle = ACCENT;
            ctx.fillRect(x, y, CELL - 0.4, CELL - 0.4);
          } else {
            // dark cells still have to be visible: the point of the picture
            // is the ratio, and a ratio needs both terms on screen
            ctx.fillStyle = '#1E2030';
            ctx.fillRect(x + 0.3, y + 0.3, CELL - 0.9, CELL - 0.9);
          }
        }
      }
    }

    size();
    window.addEventListener('resize', () => { size(); if (seen) develop(true); });

    let seen = false;
    function develop(instant) {
      if (instant || still()) { paint(revealed, cols); revealed = cols; return; }
      const t0 = performance.now(), ms = 1500, from = revealed;
      (function tick(now) {
        const t = clamp((now - t0) / ms, 0, 1);
        const want = Math.round(from + (cols - from) * easeOut(t));
        if (want > revealed) { paint(revealed, want); revealed = want; }
        if (t < 1) requestAnimationFrame(tick);
      })(t0);
    }

    new IntersectionObserver((es, ob) => {
      for (const e of es) if (e.isIntersecting) { seen = true; develop(false); ob.disconnect(); }
    }, { threshold: 0.15 }).observe(canvas);
  }

  /* ========================= SCENE 6: THE CUT SHEET ====================== */

  function buildSheet(host) {
    const W = 150, H = 267;
    host.innerHTML = PROMOS.map((p, i) => {
      const seg = p.segments[0], ep = BY_NO.get(seg.episode);
      if (!ep) return '';
      const ticks = (p.beats || [])
        .filter(b => b.episode === seg.episode)
        .map(b => ({ at: b.start, kind: b.kind }));
      const l = (seg.start / ep.duration) * 100, w = (seg.duration / ep.duration) * 100;
      const n = Math.round(p.score_final * 99);
      return '<button class="cut" type="button" data-i="' + i + '" ' +
        'aria-label="Promo P' + pad2(p.rank) + ', episode ' + seg.episode + ', score ' + n + '">' +
        '<span class="art">' +
          envelopeSVG(ep, W, H, { amp: 0.36, ticks: ticks, fill: '#272943', line: '#6E73A8' }) +
          '<span class="win" style="left:' + l.toFixed(2) + '%;width:' + w.toFixed(2) + '%"></span>' +
          '<span class="glare"></span>' +
          '<span class="hd"><span class="id">P' + pad2(p.rank) + '</span><span class="sc">' + n + '</span></span>' +
          (p.kind === 'stitched' ? '<span class="stitch">stitch</span>' : '') +
        '</span>' +
        '<span class="ft">' +
          '<span class="ep">EP' + pad2(seg.episode) +
            (p.episodes.length > 1 ? '+' + pad2(p.episodes[p.episodes.length - 1]) : '') +
            ' &middot; ' + p.duration.toFixed(0) + 's</span>' +
          '<span class="tcs">' + seg.start_tc + ' &rarr; ' +
            p.segments[p.segments.length - 1].end_tc + '</span>' +
          '<span class="hk">' + esc((p.hook && p.hook.text) || '') + '</span>' +
        '</span>' +
      '</button>';
    }).join('');

    /* Pointer tilt.

       7 and 5 degrees, not the 14 and 20 the tilt libraries default to: past
       about 8 degrees a card stops looking like a thing on a table and
       starts looking like a toy. The angle is lerped at 0.12 per frame
       toward the pointer rather than tracking it directly - about 63% closed
       in eight frames - because tracking a pointer exactly is what makes
       these effects feel twitchy. Geometry is measured when the pointer
       enters a card and not again, so the loop never reads layout. */
    const TILT = { ry: 7, rx: 5, lift: 22, lerp: 0.12 };
    let live = null, raf = 0;

    function loop() {
      raf = 0;
      if (!live) return;
      live.ry = lerp(live.ry, live.tRy, TILT.lerp);
      live.rx = lerp(live.rx, live.tRx, TILT.lerp);
      live.card.style.transform = 'rotateY(' + live.ry.toFixed(2) + 'deg) rotateX(' +
        live.rx.toFixed(2) + 'deg) translateZ(' + TILT.lift + 'px)';
      if (Math.abs(live.ry - live.tRy) > 0.02 || Math.abs(live.rx - live.tRx) > 0.02) kick();
    }
    function kick() { if (!raf) raf = requestAnimationFrame(loop); }

    function release() {
      if (!live) return;
      live.card.style.transform = '';
      live = null;
    }

    host.addEventListener('pointerover', e => {
      if (still() || (e.pointerType === 'touch')) return;
      const card = e.target.closest ? e.target.closest('.cut') : null;
      if (!card || (live && live.card === card)) return;
      release();
      const r = card.getBoundingClientRect();
      live = { card: card, r: r, rx: 0, ry: 0, tRx: 0, tRy: 0 };
      kick();
    });

    host.addEventListener('pointermove', e => {
      if (!live) return;
      const r = live.r;
      const fx = clamp((e.clientX - r.left) / r.width, 0, 1);
      const fy = clamp((e.clientY - r.top) / r.height, 0, 1);
      live.tRy = (fx - 0.5) * 2 * TILT.ry;
      live.tRx = (0.5 - fy) * 2 * TILT.rx;
      live.card.style.setProperty('--mx', (fx * 100).toFixed(1) + '%');
      live.card.style.setProperty('--my', (fy * 100).toFixed(1) + '%');
      kick();
    });

    host.addEventListener('pointerout', e => {
      if (live && !live.card.contains(e.relatedTarget)) release();
    });
    host.addEventListener('pointerleave', release);
    window.addEventListener('scroll', release, { passive: true });

    host.addEventListener('click', e => {
      const card = e.target.closest ? e.target.closest('.cut') : null;
      if (card) openDesk(+card.dataset.i);
    });
  }

  /* ============================ SCROLL ENGINE ============================ */

  /* One rAF loop owns every scroll-linked value. Handlers only set a flag;
     all reads happen here, so nothing in this file can thrash layout. */
  const scroll = { y: 0, dirty: true, raf: 0 };

  const sections = [];
  function registerSection(el, mood, energy) {
    if (el) sections.push({ el: el, mood: mood, energy: energy });
  }

  let mood = '';
  function tick() {
    scroll.raf = 0;
    const y = window.scrollY || window.pageYOffset || 0;
    const vh = window.innerHeight;

    /* HUD progress */
    const max = Math.max(1, document.documentElement.scrollHeight - vh);
    const p = clamp(y / max, 0, 1);
    hudBar.style.width = (p * 100).toFixed(2) + '%';
    hudPct.textContent = Math.round(p * 100) + '%';

    /* reel focus from its own sticky track */
    if (reel.built) {
      const tr = reelTrack.getBoundingClientRect();
      const span = Math.max(1, reelTrack.offsetHeight - vh);
      const rp = clamp(-tr.top / span, 0, 1);
      reel.target = rp * (N - 1);
      const near = tr.top < vh && tr.bottom > 0;
      if (near) {
        reel.focus = still() ? reel.target : lerp(reel.focus, reel.target, 0.16);
        if (Math.abs(reel.focus - reel.target) < 0.0015) reel.focus = reel.target;
        layoutReel();
        showEpisode(clamp(Math.round(reel.focus), 0, N - 1));
        if (Math.abs(reel.focus - reel.target) > 0.0015) request();
      }
    }

    /* pipeline rail + dots */
    if (pipeRail) {
      const r = pipeSection.getBoundingClientRect();
      const q = clamp((vh * 0.78 - r.top) / Math.max(1, r.height * 0.62), 0, 1);
      pipeRail.style.width = (q * 100).toFixed(2) + '%';
      for (let i = 0; i < pipeSteps.length; i++) {
        pipeSteps[i].classList.toggle('on', q > (i + 0.35) / pipeSteps.length);
      }
    }

    /* the backdrop takes its mood from whichever scene owns the middle of
       the screen; energy rises where the page is loud. */
    const midline = vh * 0.5;
    for (const s of sections) {
      const r = s.el.getBoundingClientRect();
      if (r.top <= midline && r.bottom >= midline) {
        if (s.mood !== mood) { mood = s.mood; BD.setMood(s.mood); }
        BD.setEnergy(s.energy);
        break;
      }
    }
  }

  function request() { if (!scroll.raf) scroll.raf = requestAnimationFrame(tick); }

  /* ============================= THE CUT ================================= */

  /* Going from the film to the desk is a splice: one white frame and a jump,
     then a different picture. It is 150ms because a cut that announces
     itself for longer is a transition, and this is meant to feel like an
     edit rather than a page change. */
  let returnY = 0;

  function openDesk(i) {
    if (document.body.classList.contains('desk-mode')) return;
    returnY = window.scrollY || 0;
    const go = () => {
      document.body.classList.remove('film-mode', 'cutting');
      document.body.classList.add('desk-mode');
      BD.setMood('desk'); BD.setEnergy(0.25); BD.weave(false);
      if (window.CUTLIST_DESK) window.CUTLIST_DESK.focus(i || 0);
      window.scrollTo(0, 0);
    };
    if (still()) return go();
    BD.pulse(1);
    document.body.classList.add('cutting');
    setTimeout(go, 95);
  }

  function backToFilm() {
    if (!document.body.classList.contains('desk-mode')) return;
    const go = () => {
      document.body.classList.remove('desk-mode', 'cutting');
      document.body.classList.add('film-mode');
      BD.setMood(mood || 'cold'); BD.setEnergy(0.5); BD.weave(true);
      window.scrollTo(0, returnY);
      request();
    };
    if (still()) return go();
    BD.pulse(0.8);
    document.body.classList.add('cutting');
    setTimeout(go, 95);
  }

  window.CUTLIST_FILM = { openDesk: openDesk, backToFilm: backToFilm };

  /* ================================ BOOT ================================= */

  let hudBar, hudPct, reelTrack, pipeRail, pipeSection, pipeSteps = [];

  function fillCopy() {
    const g = META.grounding || {}, c = META.corpus || {};
    const text = {
      cTags: group(c.emotion_tags || 0),
      cSpeakers: c.speakers || 0,
      cScenes: c.scenes || 0,
      mShow: META.show || 'show',
      mEpisodes: META.episodes, mBeats: group(META.beats || 0),
      mRuntime: (META.runtime_min || 0).toFixed(0), mCands: META.candidates,
      mVerified: META.verified, mSeconds: (META.seconds || 0).toFixed(2),
      mTop: PROMOS.length, mModel: META.model,
      gStarts: group(g.beat_starts || 0), gTotal: group(g.expressible_timestamps || 0),
      gDark: group((g.expressible_timestamps || 0) - (g.beat_starts || 0)),
      gPct: (g.pct_of_guesses_that_would_be_invalid || 0).toFixed(1),
      gLegal: (100 * (g.legal_start_fraction || 0)).toFixed(2),
      mGenerated: (META.generated || '').split(' ')[0],
      mStitched: PROMOS.filter(p => p.kind === 'stitched').length,
      mShortest: Math.min.apply(null, PROMOS.map(p => p.duration)).toFixed(0),
      mLongest: Math.max.apply(null, PROMOS.map(p => p.duration)).toFixed(0),
      mTouched: new Set(PROMOS.flatMap(p => p.episodes)).size
    };
    $$('[data-v]').forEach(el => {
      const v = text[el.dataset.v];
      if (v != null) el.textContent = String(v);
    });
  }

  function start() {
    document.body.classList.add('film-mode');

    const bd = $('#bd');
    if (bd) { BD.mount(bd); BD.setMood('leader'); BD.setEnergy(0.55); BD.weave(true); }

    hudBar = $('#hudBar'); hudPct = $('#hudPct');
    reelTrack = $('#reelTrack');
    pipeSection = $('#s-pipe'); pipeRail = $('#pipeRail');
    pipeSteps = $$('#s-pipe .pipe-st');

    fillCopy();

    const la = $('#leaderArt');
    if (la) leader(la);

    const cf = $('#creativeField');
    if (cf) creativeField(cf, 46);

    buildReel();

    const wall = $('#wallCanvas');
    if (wall) buildWall(wall);

    const sheet = $('#sheetGrid');
    if (sheet) buildSheet(sheet);

    registerSection($('#s-leader'), 'leader', 0.62);
    registerSection($('#s-spend'), 'warm', 0.5);
    registerSection($('#s-reel'), 'cold', 0.42);
    registerSection($('#s-pipe'), 'cold', 0.3);
    registerSection($('#s-wall'), 'warm', 0.52);
    registerSection($('#s-cuts'), 'warm', 0.45);

    watchReveals();

    window.addEventListener('scroll', request, { passive: true });
    window.addEventListener('resize', () => {
      if (reel.built) layoutReel();
      request();
    }, { passive: true });
    motion.addEventListener('change', () => request());

    $$('[data-open-desk]').forEach(b => b.addEventListener('click', () => {
      openDesk(+(b.dataset.openDesk || 0));
    }));
    $$('[data-back-film]').forEach(b => b.addEventListener('click', backToFilm));

    const sheetStage = $('#sheetStage');
    if (sheetStage) {
      $('#flatten').addEventListener('click', e => {
        sheetStage.classList.toggle('flat');
        e.currentTarget.textContent = sheetStage.classList.contains('flat') ? 'Tilt the table' : 'Lay it flat';
      });
    }

    /* Escape while the desk is up belongs to app.js, which dismisses an open
       overlay first and calls backToFilm() only when there was nothing to
       dismiss. Two listeners both acting on one key is what broke it. */

    document.addEventListener('visibilitychange', () => { if (!document.hidden) request(); });
    request();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

})();
