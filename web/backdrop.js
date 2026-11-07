/* ==========================================================================
   Backdrop — the atmosphere layer that sits behind the cutting-room UI.

   Seven passes, back to front: base wash, two drifting light leaks, vignette,
   film grain, dust and hairs, projector flicker, all under an optional
   sub-pixel gate weave. It has to stay invisible as work — the budget is
   2.5ms a frame at 1600x1000 — so gradients are built once at the origin and
   positioned with the transform, the loop allocates nothing, and noise tiles
   are generated at mount.

   The one non-obvious decision is the grain cadence. Each exposed frame of
   film carries its own statistically independent grain, so grain advances at
   the capture rate — 24Hz — and not at the refresh rate of whatever panel it
   ends up on. Advance it every refresh and the eye reads video noise, which
   looks like a broken signal rather than like emulsion. So the tile and its
   sub-tile offset change 24 times a second and hold in between.

   On a 60Hz display a 24Hz clock cannot land evenly, and it is not supposed
   to: each tile then holds for either two or three drawn frames, which is
   2:3 pulldown — exactly how 24fps film has always been shown on 60Hz. The
   pattern fills once per drawn frame either way, so the cadence buys nothing
   in cost. It is purely what makes the layer read as film.
   ========================================================================== */
(function () {
  'use strict';

  /* ------------------------------- tuning -------------------------------- */
  var DPR_CAP = 1.5, TAU = Math.PI * 2;
  var FADE_MS = 900, ENERGY_TAU = 180;          // mood cross-fade, energy easing
  var PULSE_TAU = 40;                           // 3 tau ~= the 120ms decay the cut wants
  var GRAIN_STEP = 1000 / 24, GRAIN_TILE = 128, GRAIN_TILES = 4;   // cadence: see header
  // 30fps idle draws, which on a 60Hz panel is exactly every second tick. The
  // 24Hz grain clock is then sampled often enough to keep its own schedule -
  // each tile holds for one or two draws, averaging 24Hz - while the layer
  // costs half what drawing at 48 did. Measured against a scrolling reel, the
  // backdrop was the largest single contributor to dropped frames at 48.
  var IDLE_STEP = 1000 / 30;
  var DEBRIS_PER_SEC = 0.45;                    // dust and hairs together, so: sparse
  var WEAVE_PX = 0.55;                          // hard bound: the weave sines sum to 1
  var LEAK_RADIUS = [0.90, 0.62];               // x the short side
  var DUST_FILL = 'rgba(255,253,245,1)', HAIR_LINE = 'rgba(248,246,238,1)';
  var WHITE = '#ffffff', BLACK = '#000000';

  // Periods are deliberately non-commensurate so the pair never re-phases into
  // something the eye can clock as a loop.
  var LEAK_PATH = [
    { px: 23000, py: 37000, ax: 0.30, ay: 0.26, ph: 0.00, qh: 1.10 },
    { px: 31000, py: 19000, ax: 0.26, ay: 0.32, ph: 2.30, qh: 0.40 }
  ];

  var MOODS = {
    leader: { wash: ['#08080E', '#0D0D18'], leak: ['#7170ff', '#64a6af'], gain: [1, 1], grit: 1 },
    cold:   { wash: ['#0A0B14', '#10111C'], leak: ['#7170ff', '#64a6af'], gain: [1, 1], grit: 1 },
    warm:   { wash: ['#110E12', '#16111A'], leak: ['#e28a60', '#be8ce9'], gain: [1, 1], grit: 1 },
    danger: { wash: ['#140A0E', '#180D12'], leak: ['#e2605f', '#7170ff'], gain: [1, 1], grit: 1 },
    // The working mood. Flat wash, one leak at half strength, and grit 0 —
    // which is what suppresses debris and flicker while someone is cutting.
    desk:   { wash: ['#0D0D18', '#0D0D18'], leak: ['#7170ff', '#7170ff'], gain: [0.5, 0], grit: 0 }
  };

  /* ------------------------------- state --------------------------------- */
  var canvas = null, ctx = null, w = 0, h = 0, scale = 1;
  var rafId = 0, lastTick = 0, sinceDraw = 0, needsDraw = true, running = false, resizeTimer = 0;
  var energy = 0.35, energyTarget = 0.35, pulseLevel = 0, reduced = false;
  var weaving = false, weaveX = 0, weaveY = 0;
  var moodName = 'leader', moodMix = 1, moodTo = null;
  var wash = null, vignette = null, leakGrad = [null, null];
  var grainPatterns = [], grainTile = 0, grainX = 0, grainY = 0, grainClock = 0;
  var mq = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

  // Fixed pool: debris is rare, but spawning must never allocate mid-frame.
  var debris = [];
  for (var slot = 0; slot < 6; slot++) {
    debris.push({ frames: 0, hair: false, x: 0, y: 0, size: 1, len: 0, ang: 0, amp: 0, wob: 0, lum: 1 });
  }

  /* ------------------------------- colour -------------------------------- */
  function blankMood() { return { wash: [[0, 0, 0], [0, 0, 0]], leak: [[0, 0, 0], [0, 0, 0]], gain: [0, 0], grit: 0 }; }
  function hexToRgb(hex) { var n = parseInt(hex.slice(1), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
  function mix(a, b, t) { return a + (b - a) * t; }
  function blendMood(a, b, t, dst) {
    for (var k = 0; k < 2; k++) {
      for (var c = 0; c < 3; c++) {
        dst.wash[k][c] = mix(a.wash[k][c], b.wash[k][c], t);
        dst.leak[k][c] = mix(a.leak[k][c], b.leak[k][c], t);
      }
      dst.gain[k] = mix(a.gain[k], b.gain[k], t);
    }
    dst.grit = mix(a.grit, b.grit, t);
  }
  function copyMood(src, dst) { blendMood(src, src, 1, dst); }
  function rgba(c, a) { return 'rgba(' + (c[0] | 0) + ',' + (c[1] | 0) + ',' + (c[2] | 0) + ',' + a + ')'; }

  // Parsed once at load so the loop only ever interpolates numbers.
  var MOOD_RGB = {};
  Object.keys(MOODS).forEach(function (name) {
    var m = MOODS[name];
    MOOD_RGB[name] = { wash: m.wash.map(hexToRgb), leak: m.leak.map(hexToRgb), gain: m.gain, grit: m.grit };
  });
  var moodFrom = blankMood(), live = blankMood();
  moodTo = MOOD_RGB[moodName];
  copyMood(moodTo, live); copyMood(moodTo, moodFrom);

  /* ------------------------------ resources ------------------------------ */
  // Gradients live at the origin and are positioned by the transform, so a
  // leak that drifts all frame still only costs one cached fill.
  function buildMoodGradients() {
    wash = ctx.createLinearGradient(0, 0, 0, h);
    wash.addColorStop(0, rgba(live.wash[0], 1));
    wash.addColorStop(1, rgba(live.wash[1], 1));
    var short = Math.min(w, h);
    for (var k = 0; k < 2; k++) {
      var g = ctx.createRadialGradient(0, 0, 0, 0, 0, short * LEAK_RADIUS[k]);
      g.addColorStop(0, rgba(live.leak[k], 1));
      g.addColorStop(0.45, rgba(live.leak[k], 0.26));
      g.addColorStop(1, rgba(live.leak[k], 0));
      leakGrad[k] = g;
    }
  }
  function buildVignette() {
    var outer = Math.sqrt(w * w + h * h) / 2;   // full density lands exactly on the corners
    vignette = ctx.createRadialGradient(w / 2, h / 2, outer * 0.34, w / 2, h / 2, outer);
    vignette.addColorStop(0, 'rgba(0,0,0,0)');
    vignette.addColorStop(1, 'rgba(0,0,0,1)');
  }

  // Bipolar tiles: white where the deviation is positive, black where it is
  // negative, magnitude in the alpha channel. That is what lets plain
  // source-over + globalAlpha work here. A mid-grey tile at low alpha blends
  // the whole frame toward grey and veils the blacks, while 'overlay' and
  // 'soft-light' are multiplicative and die in the toe — over a #0A0B14 wash
  // they produce nothing at all. Signing the deviation into alpha keeps the
  // tile zero-mean, so positive pixels add light, negative ones eat the little
  // headroom the wash has, and the black floor survives.
  function buildGrainTiles() {
    grainPatterns.length = 0;
    for (var t = 0; t < GRAIN_TILES; t++) {
      var tile = document.createElement('canvas');
      tile.width = tile.height = GRAIN_TILE;
      var tctx = tile.getContext('2d');
      if (!tctx || !tctx.createImageData) { grainPatterns.length = 0; return; }
      var img = tctx.createImageData(GRAIN_TILE, GRAIN_TILE), d = img.data;
      for (var p = 0; p < d.length; p += 4) {
        // Three uniforms summed give a bell rather than a flat hash, which is
        // what separates grain from salt and pepper.
        var dev = (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;
        d[p] = d[p + 1] = d[p + 2] = dev > 0 ? 255 : 0;
        d[p + 3] = Math.abs(dev) * 255;
      }
      tctx.putImageData(img, 0, 0);
      var pat = ctx.createPattern(tile, 'repeat');
      if (!pat) { grainPatterns.length = 0; return; }
      grainPatterns.push(pat);
    }
  }

  /* -------------------------------- frame -------------------------------- */
  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, DPR_CAP);
    var cw = canvas.clientWidth || window.innerWidth || 1;
    var ch = canvas.clientHeight || window.innerHeight || 1;
    var pw = Math.max(1, Math.round(cw * dpr)), ph = Math.max(1, Math.round(ch * dpr));
    if (pw === w && ph === h) return;           // a resize event is not a resize
    canvas.width = w = pw; canvas.height = h = ph; scale = dpr;
    buildMoodGradients();
    buildVignette();
    needsDraw = true;
  }
  function onResize() { window.clearTimeout(resizeTimer); resizeTimer = window.setTimeout(resize, 150); }

  function integrate(dt) {
    energy += (energyTarget - energy) * (1 - Math.exp(-dt / ENERGY_TAU));
    if (pulseLevel > 0) pulseLevel *= Math.exp(-dt / PULSE_TAU);
    if (moodMix < 1) {
      moodMix = Math.min(1, moodMix + dt / FADE_MS);
      blendMood(moodFrom, moodTo, moodMix, live);
      buildMoodGradients();                     // only while the fade is in flight
    }
  }

  function tickGrain(dt) {
    if (reduced) return;                        // one tile, one offset, forever
    grainClock += dt;
    if (grainClock < GRAIN_STEP) return;
    grainClock %= GRAIN_STEP;                   // modulo, not reset, so 14Hz does not drift
    // Always land on a different tile — a held repeat reads as a stutter.
    grainTile = (grainTile + 1 + (Math.random() * (GRAIN_TILES - 1) | 0)) % GRAIN_TILES;
    grainX = Math.random() * GRAIN_TILE | 0;
    grainY = Math.random() * GRAIN_TILE | 0;
  }

  function tickDebris(dt) {
    for (var k = 0; k < debris.length; k++) if (debris[k].frames > 0) debris[k].frames--;
    if (reduced || live.grit < 0.5) return;
    if (Math.random() >= DEBRIS_PER_SEC * live.grit * dt / 1000) return;
    for (var s = 0; s < debris.length; s++) {
      var d = debris[s];
      if (d.frames > 0) continue;
      d.frames = 1 + (Math.random() * 3 | 0);
      d.hair = Math.random() < 0.3;
      d.x = Math.random() * w; d.y = Math.random() * h;
      d.lum = 0.35 + Math.random() * 0.45;
      d.size = (1 + Math.random()) * scale;
      d.len = (8 + Math.random() * 22) * scale;
      d.ang = Math.random() * TAU; d.wob = Math.random() * TAU;
      d.amp = (0.8 + Math.random() * 1.8) * scale;
      return;
    }
  }

  /* -------------------------------- draw --------------------------------- */
  function drawDebris() {
    for (var s = 0; s < debris.length; s++) {
      var d = debris[s];
      if (d.frames <= 0) continue;
      ctx.globalAlpha = d.lum;
      if (!d.hair) { ctx.fillStyle = DUST_FILL; ctx.fillRect(d.x, d.y, d.size, d.size); continue; }
      ctx.strokeStyle = HAIR_LINE;
      ctx.lineWidth = scale;
      ctx.beginPath();
      ctx.moveTo(d.x, d.y);
      for (var f = 0.25; f <= 1.001; f += 0.25) {
        ctx.lineTo(d.x + Math.cos(d.ang) * d.len * f + Math.sin(f * 6.1 + d.wob) * d.amp,
                   d.y + Math.sin(d.ang) * d.len * f + Math.cos(f * 5.3 + d.wob) * d.amp);
      }
      ctx.stroke();
    }
  }

  function draw(now) {
    weaveX = weaveY = 0;
    if (weaving && !reduced) {
      weaveX = WEAVE_PX * scale * (Math.sin(now * 0.0041) * 0.6 + Math.sin(now * 0.0113) * 0.4);
      weaveY = WEAVE_PX * scale * (Math.sin(now * 0.0053 + 1.7) * 0.55 + Math.sin(now * 0.0089 + 0.4) * 0.45);
    }
    // Every pass overdraws by 2px so the weave never exposes an edge.
    ctx.setTransform(1, 0, 0, 1, weaveX, weaveY);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    ctx.fillStyle = wash;
    ctx.fillRect(-2, -2, w + 4, h + 4);

    ctx.globalCompositeOperation = 'screen';
    for (var k = 0; k < 2; k++) {
      if (live.gain[k] < 0.004) continue;
      var p = LEAK_PATH[k], lx = w / 2, ly = h / 2;
      if (!reduced) {
        lx += Math.sin(TAU * now / p.px + p.ph) * w * p.ax;
        ly += Math.sin(TAU * now / p.py + p.qh) * h * p.ay;
      }
      ctx.globalAlpha = (0.05 + 0.05 * energy) * live.gain[k];
      ctx.fillStyle = leakGrad[k];
      ctx.setTransform(1, 0, 0, 1, weaveX + lx, weaveY + ly);
      ctx.fillRect(-lx - 2, -ly - 2, w + 4, h + 4);
    }

    ctx.setTransform(1, 0, 0, 1, weaveX, weaveY);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 0.55 + 0.10 * (1 - energy);
    ctx.fillStyle = vignette;
    ctx.fillRect(-2, -2, w + 4, h + 4);

    if (grainPatterns.length) {
      ctx.globalAlpha = 0.035 + 0.05 * energy + 0.05 * pulseLevel;
      ctx.fillStyle = grainPatterns[grainTile];
      ctx.setTransform(1, 0, 0, 1, weaveX - grainX, weaveY - grainY);
      ctx.fillRect(grainX - 2, grainY - 2, w + 4, h + 4);
      ctx.setTransform(1, 0, 0, 1, weaveX, weaveY);
    }
    drawDebris();

    // Irregular by summation rather than by random walk: it cannot drift into a
    // visible pump, and it costs three sines.
    if (!reduced && live.grit > 0.01) {
      var flick = Math.sin(now * 0.0137) * 0.5 + Math.sin(now * 0.0241) * 0.3 + Math.sin(now * 0.0079) * 0.2;
      ctx.globalAlpha = Math.abs(flick) * 0.018 * energy * live.grit;
      ctx.fillStyle = flick > 0 ? WHITE : BLACK;
      ctx.fillRect(-2, -2, w + 4, h + 4);
    }
    if (pulseLevel > 0.002) {
      ctx.globalAlpha = 0.09 * pulseLevel;
      ctx.fillStyle = WHITE;
      ctx.fillRect(-2, -2, w + 4, h + 4);
    }
    ctx.globalAlpha = 1;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  /* -------------------------------- loop --------------------------------- */
  function tick(now) {
    rafId = window.requestAnimationFrame(tick);
    if (!lastTick) lastTick = now;
    var dt = Math.min(now - lastTick, 120);     // a backgrounded tab must not teleport
    lastTick = now;
    integrate(dt);
    var busy = Math.abs(energyTarget - energy) > 0.002 || moodMix < 1 || pulseLevel > 0.002;
    if (busy) needsDraw = true;
    sinceDraw += dt;
    // Idling still draws, because grain and leaks have to keep moving — just
    // not every refresh. Resetting sinceDraw rather than carrying the remainder
    // quantises the idle rate onto the refresh grid (every 3rd tick, so 20fps
    // on a 60Hz panel) and keeps the grain clock summing to real elapsed time.
    // Reduced motion settles into a genuinely static frame instead, so once it
    // is drawn there is nothing left to redraw at all.
    var step = busy ? 0 : (reduced ? Infinity : IDLE_STEP);
    if (!needsDraw && sinceDraw < step) return;
    var frameDt = sinceDraw;
    sinceDraw = 0; needsDraw = false;
    tickGrain(frameDt);
    tickDebris(frameDt);
    draw(now);
  }
  function start() {
    if (running || !ctx || document.hidden === true) return;
    running = true; lastTick = 0;
    rafId = window.requestAnimationFrame(tick);
  }
  function stop() { running = false; if (rafId) window.cancelAnimationFrame(rafId); rafId = 0; }
  function onVisibility() {
    if (document.hidden) stop();
    else { needsDraw = true; start(); }
  }
  function onReducedChange() {
    reduced = !!(mq && mq.matches);
    grainClock = 0;
    for (var s = 0; s < debris.length; s++) debris[s].frames = 0;
    needsDraw = true;
  }
  function listen(add) {
    var ev = add ? 'addEventListener' : 'removeEventListener';
    window[ev]('resize', onResize);
    document[ev]('visibilitychange', onVisibility);
    if (!mq) return;
    if (mq[ev]) mq[ev]('change', onReducedChange);
    else if (mq.addListener) mq[add ? 'addListener' : 'removeListener'](onReducedChange);
  }

  /* --------------------------------- api --------------------------------- */
  function destroy() {
    stop();
    window.clearTimeout(resizeTimer);
    if (canvas) listen(false);
    if (ctx) { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, w, h); }
    canvas = ctx = wash = vignette = null;
    leakGrad[0] = leakGrad[1] = null;
    grainPatterns.length = 0;
    for (var s = 0; s < debris.length; s++) debris[s].frames = 0;
    w = h = 0;
  }
  function mount(el) {
    if (!el || typeof el.getContext !== 'function') return;
    if (el === canvas && ctx) { start(); return; }
    if (canvas) destroy();
    ctx = el.getContext('2d');
    if (!ctx) return;                           // no 2d context: every method stays inert
    canvas = el;
    reduced = !!(mq && mq.matches);
    w = h = 0;
    resize();
    buildGrainTiles();
    listen(true);
    needsDraw = true;
    start();
  }
  function setMood(name) {
    if (!MOOD_RGB[name] || name === moodName) return;
    copyMood(live, moodFrom);                   // fade from wherever we actually are
    moodName = name;
    moodTo = MOOD_RGB[name];
    moodMix = 0;
    needsDraw = true;
  }
  function setEnergy(v) {
    v = +v;
    if (isFinite(v)) { energyTarget = v < 0 ? 0 : v > 1 ? 1 : v; needsDraw = true; }
  }
  function pulse(strength) {
    var s = +strength;
    if (!isFinite(s)) s = 1;
    pulseLevel = Math.max(pulseLevel, s < 0 ? 0 : s > 1 ? 1 : s);
    needsDraw = true;
  }
  function weave(on) { weaving = !!on; needsDraw = true; }

  window.Backdrop = {
    mount: mount, setMood: setMood, setEnergy: setEnergy,
    pulse: pulse, weave: weave, destroy: destroy
  };
}());
