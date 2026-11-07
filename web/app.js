/* ==========================================================================
   Promo Review Desk — app.js
   No modules, no build step. Boots from window.CUTLIST_DATA when the data shim
   has already run, otherwise falls back to fetch('promos.json') for http.
   A loader may call window.CUTLIST_LOAD(data) at any time to (re)boot.
   ========================================================================== */
'use strict';

/* ------------------------------- constants ------------------------------ */

const LS_KEY = 'cutlist.decisions.v1';
const SCORE_KEYS = ['hook', 'cliff', 'intensity', 'standalone', 'shape'];
const MODEL_KEYS = { hook: 'hook', cliff: 'cliff', standalone: 'standalone' };
const KEY_ABBR = { hook: 'HK', cliff: 'CL', intensity: 'IN', standalone: 'SA', shape: 'SH' };
const KIND_LANE = { DIALOGUE: 0, ACTION: 1, CAMERA: 2, SFX: 2 };
const LANE_Y = [14, 30, 46];
const LANE_H = 12;
const HIT_BAND = [[8, 18], [26, 16], [42, 22]];   // per-lane invisible hit band
const STRIP_H = 76;
const RATES = [1, 2, 4];
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');

/* --------------------------------- state -------------------------------- */

const S = {
  data: null, promos: [], eps: new Map(),
  epBeats: new Map(),            // episode number -> beats known for it, sorted
  beatKey: new Map(),            // "ep:scene:index" -> beat
  bounds: new Map(),             // episode number -> sorted beat boundary times
  cursor: 0, lowCut: 0,
  decisions: {},                 // promo id -> 'approved' | 'rejected'
  trims: new Map(),              // promo id -> { in, out }
  strips: [], winBeats: [], active: -1, W: null,
  play: { on: false, dir: 1, rate: 1, t: 0, raf: 0, last: 0 }
};

/* -------------------------------- helpers ------------------------------- */

/** True while the desk owns the viewport. In film mode every key belongs to
    the page, not to the review queue. */
const onDesk = () => document.body.classList.contains('desk-mode');

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const clamp = (v, a, b) => v < a ? a : v > b ? b : v;
const pad = n => String(n).padStart(2, '0');
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** MM:SS.cs — matches the timecode format in the source data. */
function tc(sec) {
  const cs = Math.round(Math.max(0, sec) * 100);
  return pad(Math.floor(cs / 6000)) + ':' + pad(Math.floor((cs % 6000) / 100)) + '.' + pad(cs % 100);
}
const mmss = sec => Math.floor(sec / 60) + ':' + pad(Math.round(sec % 60));
const secs = sec => sec.toFixed(1) + 's';
const score99 = v => clamp(Math.round(v * 99), 0, 99);
const band = n => n >= 80 ? 'Strong' : n >= 65 ? 'Viable' : 'Weak';
const bkey = b => b.episode + ':' + b.scene + ':' + b.index;
const lane = kind => KIND_LANE[kind] == null ? 2 : KIND_LANE[kind];
const cur = () => S.promos[S.cursor];

/* ================================= BOOT ================================= */

function boot(data) {
  if (!data || !Array.isArray(data.promos)) return fail('Payload has no promos[].');
  S.data = data;
  S.promos = data.promos.slice();
  S.eps = new Map((data.episodes || []).map(e => [e.number, e]));

  // Episode beat index. episodes[] carries only a beat COUNT, so the fullest
  // picture of an episode is the union of every promo window that touches it.
  S.epBeats.clear(); S.beatKey.clear(); S.bounds.clear();
  for (const p of S.promos) for (const b of p.beats) {
    const k = bkey(b);
    if (S.beatKey.has(k)) continue;
    S.beatKey.set(k, b);
    if (!S.epBeats.has(b.episode)) S.epBeats.set(b.episode, []);
    S.epBeats.get(b.episode).push(b);
  }
  for (const [n, arr] of S.epBeats) {
    arr.sort((a, b) => a.start - b.start || lane(a.kind) - lane(b.kind));
    const t = new Set();
    for (const b of arr) { t.add(+b.start.toFixed(2)); t.add(+b.end.toFixed(2)); }
    S.bounds.set(n, Array.from(t).sort((a, b) => a - b));
  }

  // bottom-quartile cut-off for score colouring
  const sorted = S.promos.map(p => p.score_final).sort((a, b) => a - b);
  S.lowCut = sorted[Math.max(0, Math.ceil(sorted.length * 0.25) - 1)];

  S.decisions = readStore();
  renderTop(); renderList(); select(0, true);
}

function fail(msg) {
  $('#detail').innerHTML = '<div class="empty">No cut list loaded. ' + esc(msg) +
    '<br><br>Expecting <code>window.CUTLIST_DATA</code> from <code>promos.json.js</code>,' +
    ' or <code>promos.json</code> over http.</div>';
}

window.CUTLIST_LOAD = boot;
if (window.CUTLIST_DATA) boot(window.CUTLIST_DATA);
else fetch('promos.json').then(r => r.json()).then(boot).catch(e => fail(String(e.message || e)));

/* The film (reel.js) hands over to the desk through this, and only this. */
window.CUTLIST_DESK = {
  focus: function (i) { if (S.promos.length) select(i || 0); },
  count: function () { return S.promos.length; }
};

/* ============================== PERSISTENCE ============================= */

function readStore() {
  try { return JSON.parse(localStorage.getItem(LS_KEY)) || {}; } catch (e) { return {}; }
}
function writeStore() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(S.decisions)); } catch (e) { /* file:// may block */ }
}

/* ================================ TOP BAR =============================== */

function renderTop() {
  const m = S.data.meta || {};
  $('#showTitle').textContent = m.show || 'Cut list';
  const stats = [
    ['episodes', m.episodes], ['beats', (m.beats || 0).toLocaleString('en-US')],
    ['runtime', (m.runtime_min || 0) + 'm'], ['candidates', m.candidates],
    ['verified', m.verified], ['model', m.model]
  ];
  $('#metaStats').innerHTML = stats
    .map(([k, v]) => `<span class="stat"><span class="k">${esc(k)}</span><span class="v">${esc(v)}</span></span>`).join('');
  $('#listCount').textContent = S.promos.length + ' promos';
  paintTally();
}

function paintTally() {
  let ok = 0, no = 0;
  for (const p of S.promos) {
    if (S.decisions[p.id] === 'approved') ok++;
    else if (S.decisions[p.id] === 'rejected') no++;
  }
  $('#tally').innerHTML =
    `<span class="t-ok"><b>${pad(ok)}</b> approved</span>` +
    `<span class="t-no"><b>${pad(no)}</b> rejected</span>` +
    `<span class="t-wait"><b>${pad(S.promos.length - ok - no)}</b> pending</span>`;
}

/* =============================== LEFT LIST ============================== */

function renderList() {
  $('#promoList').innerHTML = S.promos.map((p, i) => {
    const n = score99(p.score_final);
    const eps = p.episodes.map(e => 'E' + e).join('→');
    const bars = SCORE_KEYS.slice(0, 4)
      .map(k => `<i><span style="width:${score99(p.scores[k])}%"></span></i>`).join('');
    return `<button class="row" type="button" role="option" data-i="${i}">
      <span class="rank">${pad(i + 1)}</span>
      <span class="row-main">
        <span class="row-top">
          <span class="row-dur">${esc(secs(p.duration))}</span>
          <span class="badge">${esc(eps)}</span>
          ${p.kind === 'stitched' ? '<span class="chip-stitch">stitch</span>' : ''}
        </span>
        <span class="excerpt">${esc(p.hook && p.hook.text || '')}</span>
        <span class="micro-bar">${bars}</span>
      </span>
      <span class="row-right">
        <span class="row-score${p.score_final <= S.lowCut ? ' low' : ''}">${n}</span>
        <span class="pill-slot"></span>
      </span>
    </button>`;
  }).join('');

  paintRows();
}

/** Row state classes: hovered (CSS), cursored, decided. */
function paintRows() {
  $$('#promoList .row').forEach((row, i) => {
    const d = S.decisions[S.promos[i].id];
    row.classList.toggle('cur', i === S.cursor);
    row.classList.toggle('decided', !!d);
    row.classList.toggle('approved', d === 'approved');
    row.classList.toggle('rejected', d === 'rejected');
    row.setAttribute('aria-selected', i === S.cursor ? 'true' : 'false');
    $('.pill-slot', row).outerHTML = d
      ? `<span class="pill-slot pill ${d === 'approved' ? 'ok' : 'no'}">${d === 'approved' ? 'A' : 'R'}</span>`
      : '<span class="pill-slot"></span>';
  });
}

function select(i, silent) {
  S.cursor = clamp(i, 0, S.promos.length - 1);
  stop(); S.play.t = 0;
  paintRows();
  if (!silent) {
    const row = $(`#promoList .row[data-i="${S.cursor}"]`);
    if (row) row.scrollIntoView({ block: 'nearest' });
  }
  renderDetail();
}

/* ============================ WINDOW / TRIM ============================= */

/** The window actually on screen: source segments with any local trim applied. */
function effWindow(p) {
  const t = S.trims.get(p.id);
  const segs = p.segments.map(s => ({ episode: s.episode, start: s.start, end: s.end }));
  if (t) { segs[0].start = t.in; segs[segs.length - 1].end = t.out; }
  let total = 0;
  for (const s of segs) { s.duration = Math.max(0, s.end - s.start); s.offset = total; total += s.duration; }
  return { segs, total, trimmed: !!t, hookKey: beatKeyAt(p.hook), cliffKey: beatKeyAt(p.cliff) };
}

/** hook/cliff are summaries, not beats. hook.at is a beat start; cliff.at is a beat end. */
function beatKeyAt(ref) {
  if (!ref) return '';
  const arr = S.epBeats.get(ref.episode) || [];
  const hit = arr.find(b => b.start_tc === ref.at) || arr.find(b => b.end_tc === ref.at);
  return hit ? bkey(hit) : '';
}

/** Beats overlapping the window, in order, tagged with promo-time offsets.
    The overlap rule reproduces promos[].beats exactly, lead-in beat included. */
function beatsIn(p, W) {
  const out = [];
  W.segs.forEach((s, si) => {
    const src = W.trimmed ? (S.epBeats.get(s.episode) || []) : p.beats.filter(b => b.episode === s.episode);
    for (const b of src) {
      if (b.end <= s.start + 0.0001 || b.start >= s.end - 0.0001) continue;
      out.push({ b, si, t: Math.max(0, s.offset + (b.start - s.start)) });
    }
  });
  return out;
}

/** I / O nudge: move an edge to the neighbouring beat boundary. Source untouched. */
function nudge(edge, back) {
  const p = cur(), W = S.W;
  const first = W.segs[0], last = W.segs[W.segs.length - 1];
  const ep = edge === 'in' ? first.episode : last.episode;
  const bounds = S.bounds.get(ep) || [];
  const now = edge === 'in' ? first.start : last.end;
  const next = back
    ? bounds.slice().reverse().find(t => t < now - 0.001)
    : bounds.find(t => t > now + 0.001);
  if (next == null) return;
  const epDur = (S.eps.get(ep) || {}).duration || next;
  const t = S.trims.get(p.id) || { in: first.start, out: last.end };
  // keep at least a second of window on the edge being moved
  if (edge === 'in') { if (next > first.end - 1) return; t.in = clamp(next, 0, epDur); }
  else { if (next < last.start + 1) return; t.out = clamp(next, 0, epDur); }
  S.trims.set(p.id, t);
  S.play.t = 0; renderDetail();
}

/* ============================== DETAIL PANE ============================= */

function renderDetail() {
  const p = cur();
  if (!p) return;
  const W = S.W = effWindow(p);
  const n = score99(p.score_final), low = p.score_final <= S.lowCut;
  const hasModel = p.model && p.model.model && p.model.model !== 'offline';
  const d = S.decisions[p.id];

  /* --- header --- */
  let html = `<section class="card dhead">
    <div>
      <div class="dh-id">
        <span class="mono id">${esc(p.id)}</span>
        <span class="kindchip${p.kind === 'stitched' ? ' stitched' : ''}">${esc(p.kind)}</span>
        ${W.trimmed ? '<span class="kindchip trim">trimmed</span>' : ''}
      </div>
      <div class="dh-meta">
        <span class="micro dim">rank ${pad(p.rank)}</span><span class="sep">/</span>
        <span class="mono">${esc(secs(W.total))}</span><span class="sep">/</span>
        <span>${p.episodes.length > 1 ? 'episodes' : 'episode'} ${p.episodes.join(', ')}</span><span class="sep">/</span>
        <span>${W.segs.length} ${W.segs.length > 1 ? 'segments' : 'segment'}</span><span class="sep">/</span>
        <span class="mono">${esc(tc(W.segs[0].start))} &rarr; ${esc(tc(W.segs[W.segs.length - 1].end))}</span>
      </div>
    </div>
    <div class="dh-right">
      <span class="statechip ${d === 'approved' ? 'ok' : d === 'rejected' ? 'no' : 'wait'}">${d || 'pending'}</span>
      <div class="dh-score">
        <div class="big mono${low ? ' low' : ''}">${n}</div>
        <div class="bandw">${band(n)}</div>
      </div>
    </div>
  </section>`;

  /* --- score breakdown --- */
  html += `<section class="card">
    <div class="card-head"><span class="sect">Score breakdown</span>
      <span class="micro dim mono">${SCORE_KEYS.map(k => KEY_ABBR[k] + ' ' +
        Math.round(((S.data.meta.weights || {})[k] || 0) * 100)).join('   ')}</span></div>
    ${hasModel ? `<div class="scorecols">
      <div class="scorecol"><span class="k">rule</span><span class="v">${score99(p.score_rules)}</span></div>
      <div class="scorecol"><span class="k">model</span><span class="v">${score99(modelAvg(p))}</span></div>
      <div class="scorecol"><span class="k">final</span><span class="v">${n}</span></div>
    </div>` : ''}
    ${SCORE_KEYS.map(k => {
      const v = score99(p.scores[k]);
      const mv = hasModel && MODEL_KEYS[k] ? score99((p.model[MODEL_KEYS[k]] || 0) / 10) : null;
      return `<div class="sb"><span class="k">${k}</span>
        <span class="track"><span class="fill" data-w="${v}" style="width:0"></span></span>
        <span class="v">${v}</span><span class="v2">${mv == null ? '' : mv}</span></div>`;
    }).join('')}
  </section>`;

  /* --- timeline --- */
  html += `<section class="card">
    <div class="card-head"><span class="sect">Timeline</span>
      <span class="micro dim">full episode, promo window in clear</span></div>
    ${W.segs.map((s, i) => stripHTML(p, s, i, W)).join('')}
    <div class="tl-foot">
      <span class="lk"><span class="hatch-key"></span>first 3s / hook</span>
      <span class="lk"><span class="out-key"></span>out-point</span>
      <span class="lk">10s ticks, 30s majors</span>
      <span class="lk">lanes: dialogue / action / camera+sfx</span>
    </div>
  </section>`;

  /* --- beat list --- */
  S.winBeats = beatsIn(p, W);
  html += `<section class="card">
    <div class="card-head"><span class="sect">Beats in window</span>
      <span class="micro dim mono">${pad(S.winBeats.length)}</span></div>
    <ul class="beats">${S.winBeats.map((e, i) => beatHTML(e, i, W, p)).join('')}</ul>
  </section>`;

  /* --- why / risk --- */
  html += `<section class="card">
    <div class="whygrid">
      <div class="blk"><span class="sect">Why</span><p>${esc(p.model && p.model.why || '—')}</p></div>
      <div class="blk"><span class="sect">Risk</span><p>${esc(p.model && p.model.risk || '—')}</p></div>
    </div>
    ${(p.reasons || []).length ? `<ul class="reasons">${p.reasons
      .map((r, i) => `<li><span class="n">${pad(i + 1)}</span><span>${esc(r)}</span></li>`).join('')}</ul>` : ''}
  </section>`;

  $('#detail').innerHTML = html;
  $('#detail').scrollTop = 0;
  growBars();
  wireStrips(W);
  paintActive(true);
  paintTransport();
}

/** Five numbers you compare dozens of times a day are easier to compare
    when they travel into place together than when they are simply there.
    Reduced motion kills the transition in CSS, so this becomes a no-op
    rather than needing a branch here. */
function growBars() {
  const fills = $$('#detail .sb .fill');
  requestAnimationFrame(() => {
    for (let i = 0; i < fills.length; i++) {
      fills[i].style.transitionDelay = (i * 45) + 'ms';
      fills[i].style.width = fills[i].dataset.w + '%';
    }
  });
}

const modelAvg = p => (((p.model.hook || 0) + (p.model.cliff || 0) + (p.model.standalone || 0)) / 3) / 10;

function beatHTML(entry, i, W, p) {
  const b = entry.b, k = bkey(b);
  const isHook = k === W.hookKey, isCliff = k === W.cliffKey;
  const emo = (b.emotions || []).slice(0, 3).map(e => `<span class="emo">${esc(e)}</span>`).join('');
  const divider = entry.si > 0 && (i === 0 || S.winBeats[i - 1].si !== entry.si)
    ? `<li class="seg-divider">segment ${entry.si + 1} &middot; episode ${b.episode}</li>` : '';
  return divider + `<li class="beat t-${b.kind}${isHook ? ' is-hook' : ''}${isCliff ? ' is-cliff' : ''}" data-i="${i}" style="--bi:${Math.min(i, 26)}">
    <span class="bt">${esc(b.start_tc || tc(b.start))}</span>
    <span class="dot k-${b.kind}"></span>
    <span class="bbody">
      ${b.speaker || emo ? `<span class="bmeta">${b.speaker ? `<span class="speaker">${esc(b.speaker)}</span>` : ''}${emo}</span>` : ''}
      <span class="btext">${esc(b.text)}</span>
    </span>
    ${isHook ? '<span class="bmark">HOOK</span>' : isCliff ? '<span class="bmark cliff">CLIFF</span>' : '<span></span>'}
  </li>`;
}

/* =============================== TIMELINE =============================== */

function stripHTML(p, seg, si, W) {
  const ep = S.eps.get(seg.episode);
  const D = Math.max(ep ? ep.duration : seg.end, seg.end, 1);
  const pc = t => (100 * clamp(t, 0, D) / D);
  const all = S.epBeats.get(seg.episode) || [];
  const uid = p.id + '-' + si;
  let sv = `<defs><pattern id="hx-${uid}" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
    <line x1="0" y1="0" x2="0" y2="6" stroke="#7170ff" stroke-width="2" opacity="0.30"/></pattern></defs>`;

  for (const y of LANE_Y) sv += `<rect class="lane-track" x="0" y="${y}" width="100%" height="${LANE_H}" rx="1"/>`;

  // 10-second tick grid, 30-second majors with an axis label
  for (let t = 10; t < D; t += 10) {
    const maj = Math.round(t) % 30 === 0, x = pc(t).toFixed(3);
    sv += `<line class="${maj ? 'tick-maj' : 'tick-min'}" x1="${x}%" x2="${x}%" y1="${maj ? 10 : 14}" y2="${maj ? 62 : 58}"/>`;
    if (maj) sv += `<text class="axis-lbl" x="${x}%" y="72" text-anchor="middle">${mmss(t)}</text>`;
  }

  // every known beat of the episode, by percentage, colour-coded, in 3 lanes
  let hits = '';
  for (const b of all) {
    const k = bkey(b), li = lane(b.kind);
    const w = Math.max(0.2, (b.end - b.start) / D * 100).toFixed(3);
    const mark = k === W.hookKey || k === W.cliffKey ? ' mark' : '';
    sv += `<rect class="b k-${b.kind}${mark}" x="${pc(b.start).toFixed(3)}%" y="${LANE_Y[li]}" width="${w}%" height="${LANE_H}" rx="1"/>`;
    // invisible hit target, never narrower than 8px
    hits += `<div class="hit" data-k="${k}" style="left:${pc(b.start).toFixed(3)}%;width:max(8px,${w}%);top:${HIT_BAND[li][0]}px;height:${HIT_BAND[li][1]}px"></div>`;
  }

  // dim everything outside the window — two overlays, nothing tints the inside
  sv += `<rect class="mask-out" x="0" y="0" width="${pc(seg.start).toFixed(3)}%" height="${STRIP_H}"/>`;
  sv += `<rect class="mask-out" x="${pc(seg.end).toFixed(3)}%" y="0" width="${(100 - pc(seg.end)).toFixed(3)}%" height="${STRIP_H}"/>`;

  // hook region: first 3 seconds of the window
  const hookW = (Math.min(seg.start + 3, seg.end) - seg.start) / D * 100;
  sv += `<rect x="${pc(seg.start).toFixed(3)}%" y="14" width="${hookW.toFixed(3)}%" height="44" fill="url(#hx-${uid})"/>`;
  sv += `<line class="in-rule" x1="${pc(seg.start).toFixed(3)}%" x2="${pc(seg.start).toFixed(3)}%" y1="10" y2="62"/>`;

  const known = all.length, total = ep ? ep.beats : known;
  return `<div class="strip">
    <div class="strip-head">
      <span class="l"><span class="ep">episode ${seg.episode}</span>
        <span class="tcs">${esc(tc(seg.start))} &rarr; ${esc(tc(seg.end))}</span>
        <span class="tcs dim">${esc(secs(seg.duration))}</span></span>
      <span class="r">${known}/${total} beats indexed &middot; ep ${esc(secs(D))}</span>
    </div>
    <div class="strip-body" data-si="${si}">
      <svg xmlns="http://www.w3.org/2000/svg" height="${STRIP_H}" aria-hidden="true">${sv}</svg>
      <div class="marks">
        <div class="hook-lbl" style="left:${pc(seg.start).toFixed(3)}%">HOOK</div>
        <div class="out-rule" style="left:${pc(seg.end).toFixed(3)}%"></div>
        <div class="out-pen" style="left:${pc(seg.end).toFixed(3)}%"></div>
        <div class="out-lbl" style="left:${pc(seg.end).toFixed(3)}%">OUT</div>
      </div>
      <div class="hitlayer">${hits}</div>
      <div class="hoverline"></div>
      <div class="playhead"></div>
      <div class="tip"></div>
    </div>
  </div>`;
}

/** Cache strip geometry and wire hover: a 1px rule plus a top-anchored tooltip. */
function wireStrips(W) {
  S.strips = $$('#detail .strip-body').map(box => {
    const si = +box.dataset.si, seg = W.segs[si], ep = S.eps.get(seg.episode);
    const st = {
      box, seg, D: Math.max(ep ? ep.duration : seg.end, seg.end, 1),
      head: $('.playhead', box), hover: $('.hoverline', box), tip: $('.tip', box)
    };
    box.addEventListener('mousemove', e => {
      const r = box.getBoundingClientRect(), x = clamp(e.clientX - r.left, 0, r.width);
      st.hover.style.transform = 'translateX(' + x + 'px)';
      st.hover.style.opacity = '1';
      const hit = e.target.closest && e.target.closest('.hit');
      const b = hit && S.beatKey.get(hit.dataset.k);
      if (!b) { st.tip.style.display = 'none'; return; }
      st.tip.innerHTML = `<span class="dot k-${b.kind}"></span><span class="t-tc">${esc(b.start_tc || tc(b.start))}</span>` +
        `<span class="t-txt">${esc(b.speaker ? b.speaker + ' · ' : '')}${esc(b.text.slice(0, 64))}${b.text.length > 64 ? '…' : ''}</span>`;
      st.tip.style.display = 'flex';
      st.tip.style.left = clamp(x, 70, r.width - 70) + 'px';
    });
    box.addEventListener('mouseleave', () => { st.hover.style.opacity = '0'; st.tip.style.display = 'none'; });
    box.addEventListener('click', e => {               // scrub by clicking the strip
      const r = box.getBoundingClientRect();
      const t = (e.clientX - r.left) / r.width * st.D;
      S.play.t = clamp(seg.offset + (t - seg.start), 0, S.W.total);
      paintPlayhead(); paintActive();
    });
    return st;
  });
  paintPlayhead();
}

/** Playhead lives outside the SVG and moves on transform only. */
function paintPlayhead() {
  const t = S.play.t;
  for (const st of S.strips) {
    const s = st.seg, inSeg = t >= s.offset - 0.001 && t <= s.offset + s.duration + 0.001;
    if (!inSeg) { st.head.style.opacity = '0'; continue; }
    const w = st.box.clientWidth;
    const x = (s.start + (t - s.offset)) / st.D * w;
    st.head.style.transform = 'translateX(' + x.toFixed(2) + 'px)';
    st.head.style.opacity = '1';
  }
}

/* =============================== PLAYBACK =============================== */

function paintActive(force) {
  let idx = -1;
  for (let i = 0; i < S.winBeats.length; i++) if (S.winBeats[i].t <= S.play.t + 0.001) idx = i;
  if (idx === S.active && !force) return;
  const prev = $(`#detail .beat[data-i="${S.active}"]`);
  if (prev) prev.classList.remove('on');
  S.active = idx;
  const node = $(`#detail .beat[data-i="${idx}"]`);
  if (node) {
    node.classList.add('on');
    if (S.play.on) node.scrollIntoView({ block: 'nearest' });
  }
}

function frame(ts) {
  if (!S.play.on) return;
  const dt = Math.min(0.1, (ts - S.play.last) / 1000);
  S.play.last = ts;
  S.play.t += dt * S.play.rate * S.play.dir;
  if (S.play.t >= S.W.total) { S.play.t = S.W.total; stop(); }
  else if (S.play.t <= 0) { S.play.t = 0; stop(); }
  paintPlayhead(); paintActive(); paintTransport();
  if (S.play.on) S.play.raf = requestAnimationFrame(frame);
}

function play(dir) {
  // Reduced motion: no real-time sweep. Step to the next beat boundary instead.
  if (reduced.matches) return step(dir);
  if (S.play.on && S.play.dir === dir) {
    S.play.rate = RATES[Math.min(RATES.indexOf(S.play.rate) + 1, RATES.length - 1)];
  } else {
    S.play.dir = dir; S.play.rate = 1; S.play.on = true;
    S.play.last = performance.now();
    S.play.raf = requestAnimationFrame(frame);
  }
  paintTransport();
}

function stop() {
  S.play.on = false; S.play.rate = 1;
  if (S.play.raf) cancelAnimationFrame(S.play.raf);
  S.play.raf = 0;
  paintTransport();
}

/** Discrete move, used for reduced motion and for clicking through beats. */
function step(dir) {
  const list = S.winBeats.map(e => e.t);
  const next = dir > 0 ? list.find(t => t > S.play.t + 0.001)
    : [...list].reverse().find(t => t < S.play.t - 0.001);
  S.play.t = next == null ? S.play.t : next;
  paintPlayhead(); paintActive(); paintTransport();
}

function paintTransport() {
  const W = S.W || { total: 0, trimmed: false };
  const rate = S.play.on ? (S.play.dir < 0 ? '-' : '') + S.play.rate + '×' : 'paused';
  $('#transport').innerHTML =
    `<span>${esc(tc(S.play.t))} / ${esc(tc(W.total))}</span>` +
    `<span class="rate">${esc(rate)}</span>` +
    (W.trimmed ? '<span>trimmed · 0 resets</span>' : '');
}

/* =============================== DECISIONS ============================== */

function decide(verdict) {
  const p = cur(); if (!p) return;
  if (verdict) S.decisions[p.id] = verdict; else delete S.decisions[p.id];
  writeStore(); paintRows(); paintTally();
  if (verdict) {
    if (S.cursor < S.promos.length - 1) select(S.cursor + 1);
    else renderDetail();
  } else renderDetail();
}

function nextUndecided() {
  for (let k = 1; k <= S.promos.length; k++) {
    const i = (S.cursor + k) % S.promos.length;
    if (!S.decisions[S.promos[i].id]) return select(i);
  }
}

function exportDecisions() {
  const pick = v => S.promos.filter(p => S.decisions[p.id] === v).map(p => {
    const W = effWindow(p);
    return {
      id: p.id, rank: p.rank, kind: p.kind, score: score99(p.score_final),
      score_final: p.score_final, duration: +W.total.toFixed(2), trimmed: W.trimmed,
      episodes: p.episodes,
      segments: W.segs.map(s => ({
        episode: s.episode, start: +s.start.toFixed(2), end: +s.end.toFixed(2),
        start_tc: tc(s.start), end_tc: tc(s.end), duration: +s.duration.toFixed(2)
      })),
      hook: p.hook && p.hook.text, cliff: p.cliff && p.cliff.text, characters: p.characters
    };
  });
  const out = {
    show: S.data.meta.show, model: S.data.meta.model, source_generated: S.data.meta.generated,
    exported: new Date().toISOString(), approved: pick('approved'), rejected: pick('rejected').map(p => p.id)
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url; a.download = 'cutlist-decisions.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/* ================================ OVERLAYS ============================== */

const sheetOpen = () => !$('#shortcuts').hidden || !$('#palette').hidden;
function toggleSheet(id, on) {
  const node = $(id);
  node.hidden = on == null ? !node.hidden : !on;
  if (id === '#palette' && !node.hidden) { $('#palInput').value = ''; renderPalette(); $('#palInput').focus(); }
}

const ACTIONS = [
  ['Approve promo', '↵', () => decide('approved')],
  ['Reject promo', 'R', () => decide('rejected')],
  ['Clear decision', 'U', () => decide(null)],
  ['Next undecided', 'N', () => nextUndecided()],
  ['Play / pause', 'Space', () => S.play.on ? stop() : play(1)],
  ['Nudge in-point later', 'I', () => nudge('in', false)],
  ['Nudge out-point earlier', '⇧O', () => nudge('out', true)],
  ['Reset trim', '0', () => { S.trims.delete(cur().id); renderDetail(); }],
  ['Export decisions', 'E', () => exportDecisions()],
  ['Keyboard shortcuts', '⇧?', () => toggleSheet('#shortcuts', true)]
];
let palSel = 0, palHits = ACTIONS;

function renderPalette() {
  const q = $('#palInput').value.trim().toLowerCase();
  palHits = ACTIONS.filter(a => a[0].toLowerCase().includes(q));
  palSel = clamp(palSel, 0, Math.max(0, palHits.length - 1));
  $('#palList').innerHTML = palHits.map((a, i) =>
    `<button class="pal-item${i === palSel ? ' on' : ''}" type="button" data-i="${i}">
      <span>${esc(a[0])}</span><span class="hintk">${esc(a[1])}</span></button>`).join('')
    || '<div class="empty">No action matches.</div>';
}

function runPalette(i) {
  const a = palHits[i];
  toggleSheet('#palette', false);
  if (a) a[2]();
}

/* ================================ KEYBOARD ============================== */

window.addEventListener('keydown', e => {
  if (!onDesk()) return;
  if (e.metaKey || e.ctrlKey) {
    if (e.key.toLowerCase() === 'k') { e.preventDefault(); toggleSheet('#palette'); }
    return;
  }
  // palette has its own key handling while open
  if (!$('#palette').hidden) {
    if (e.key === 'Escape') { e.preventDefault(); toggleSheet('#palette', false); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); palSel++; renderPalette(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); palSel--; renderPalette(); }
    else if (e.key === 'Enter') { e.preventDefault(); runPalette(palSel); }
    return;
  }
  if (e.key === '?' || (e.shiftKey && e.key === '/')) { e.preventDefault(); return toggleSheet('#shortcuts'); }
  if (e.key === 'Escape') { toggleSheet('#shortcuts', false); return; }
  if (!$('#shortcuts').hidden) return;

  switch (e.key) {
    case 'ArrowDown': e.preventDefault(); select(S.cursor + 1); break;
    case 'ArrowUp': e.preventDefault(); select(S.cursor - 1); break;
    case 'Enter': e.preventDefault(); decide('approved'); break;
    case ' ': e.preventDefault(); S.play.on ? stop() : play(1); break;
    default: {
      const k = e.key.toLowerCase();
      if (k === 'r') decide('rejected');
      else if (k === 'u') decide(null);
      else if (k === 'n') nextUndecided();
      else if (k === 'l') play(1);
      else if (k === 'j') play(-1);
      else if (k === 'k') stop();
      else if (k === 'i') nudge('in', e.shiftKey);
      else if (k === 'o') nudge('out', !e.shiftKey);
      else if (k === '0') { if (S.trims.delete(cur().id)) { S.play.t = 0; renderDetail(); } }
      else if (k === 'e') exportDecisions();
    }
  }
});

/* ================================= WIRING =============================== */

$('#promoList').addEventListener('click', e => {
  const row = e.target.closest('.row');
  if (row) select(+row.dataset.i);
});
$('#exportBtn').addEventListener('click', exportDecisions);
$('#hintBtn').addEventListener('click', () => toggleSheet('#shortcuts'));
$('#palInput').addEventListener('input', () => { palSel = 0; renderPalette(); });
$('#palList').addEventListener('click', e => {
  const b = e.target.closest('.pal-item'); if (b) runPalette(+b.dataset.i);
});
$$('.overlay').forEach(o => o.addEventListener('mousedown', e => { if (e.target === o) o.hidden = true; }));
$('#detail').addEventListener('click', e => {
  const li = e.target.closest('.beat');
  if (!li || !S.winBeats[+li.dataset.i]) return;
  S.play.t = S.winBeats[+li.dataset.i].t;
  paintPlayhead(); paintActive(); paintTransport();
});
window.addEventListener('resize', () => paintPlayhead());
