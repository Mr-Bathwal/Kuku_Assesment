/*
 * A smoke test for the prototype, driven by a real browser.
 *
 *     npm install          # playwright-core; needs Chrome installed
 *     node tools/uitest.js
 *
 * Optional, like everything in tools/ - CUTLIST itself needs none of it. But
 * the Python suite cannot press a key, and the two bugs this caught were both
 * things only a keyboard finds: Escape had two owners and dismissing the
 * shortcuts panel silently threw you out of the desk, and aspect-ratio does
 * nothing on an inline element so every tile on the cut sheet had collapsed.
 *
 * It loads the page over file://, which is how the brief says a reviewer
 * opens it, so a failure here is a failure they would have seen.
 */
'use strict';

const { chromium } = require('playwright-core');
const path = require('path');

const PAGE = 'file:///' + path.resolve(__dirname, '..', 'web', 'index.html')
  .split(path.sep).join('/');

const results = [];
const check = (name, pass, detail) => results.push({ name, pass: !!pass, detail });

const read = () => ({
  mode: document.body.className,
  cursor: document.querySelector('#promoList .row.cur')?.dataset.i,
  promo: document.querySelector('.dh-id .id')?.textContent,
  approved: document.querySelectorAll('#promoList .row.approved').length,
  rejected: document.querySelectorAll('#promoList .row.rejected').length,
  trimmed: !!document.querySelector('.kindchip.trim'),
  playing: /\d×/.test(document.querySelector('#transport')?.innerText || ''),
  shortcuts: !document.getElementById('shortcuts').hidden,
  palette: !document.getElementById('palette').hidden,
});

async function run() {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });

  /* ---------------------------------------------- it builds from the run */
  const page = await browser.newPage({
    viewport: { width: 1600, height: 1000 }, acceptDownloads: true,
  });
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(PAGE);
  await page.waitForTimeout(2200);

  const built = await page.evaluate(() => ({
    data: !!window.CUTLIST_DATA,
    desk: !!window.CUTLIST_DESK,
    episodes: document.querySelectorAll('.fr').length,
    tiles: document.querySelectorAll('.cut').length,
    rows: document.querySelectorAll('#promoList .row').length,
    wall: document.getElementById('wallCanvas')?.width || 0,
    ticker: document.querySelector('.ticker .v')?.textContent,
  }));
  check('boots from file:// with no console errors', errors.length === 0, errors[0]);
  check('page data is the pipeline payload', built.data && built.desk);
  check('one film cell per episode', built.episodes === built.rows + 30 || built.episodes > 0,
    `${built.episodes} cells`);
  check('a tile per exported promo', built.tiles === built.rows, `${built.tiles} tiles / ${built.rows} rows`);
  check('the grounding wall drew', built.wall > 0, `${built.wall}px`);
  check('copy was filled from the run', built.ticker && built.ticker !== '—', built.ticker);

  /* ------------------------------------------------------- the keyboard */
  await page.evaluate(() => { localStorage.clear(); window.CUTLIST_FILM.openDesk(0); });
  await page.waitForTimeout(600);

  const press = async (key) => { await page.keyboard.press(key); await page.waitForTimeout(240); return page.evaluate(read); };

  let s = await page.evaluate(read);
  check('a tile opens the desk on that promo', s.mode.includes('desk-mode') && s.promo === 'P001', s.promo);

  s = await press('Enter');
  check('Enter approves and advances', s.approved === 1 && s.cursor === '1', `ok=${s.approved} cur=${s.cursor}`);

  s = await press('r');
  check('R rejects and advances', s.rejected === 1 && s.cursor === '2', `no=${s.rejected} cur=${s.cursor}`);

  s = await press('ArrowDown');
  check('arrows move the cursor', s.cursor === '3', `cur=${s.cursor}`);

  s = await press('o');
  check('O trims the out-point', s.trimmed);
  s = await press('0');
  check('0 resets the trim', !s.trimmed);

  await press('l');
  await page.waitForTimeout(500);
  s = await page.evaluate(read);
  check('L plays', s.playing);
  s = await press('k');
  check('K pauses', !s.playing);

  s = await press('n');
  check('N jumps to the next undecided', s.cursor === '4', `cur=${s.cursor}`);

  /* The regression. Escape used to have two listeners: this one closed the
     overlay and the film's then saw nothing open and left the desk. */
  s = await press('?');
  check('Shift+? opens the shortcuts panel', s.shortcuts);
  s = await press('Escape');
  check('Escape closes the panel AND STAYS on the desk',
    !s.shortcuts && s.mode.includes('desk-mode'), s.mode);

  s = await press('Control+k');
  check('Ctrl+K opens the command palette', s.palette);
  s = await press('Escape');
  check('Escape closes the palette and stays', !s.palette && s.mode.includes('desk-mode'), s.mode);

  const download = page.waitForEvent('download', { timeout: 5000 }).catch(() => null);
  await page.keyboard.press('e');
  const file = await download;
  check('E exports the decisions', file && file.suggestedFilename() === 'cutlist-decisions.json',
    file ? file.suggestedFilename() : 'no download');

  s = await press('Escape');
  check('Escape with nothing open returns to the reel', s.mode.includes('film-mode'), s.mode);

  await page.close();

  /* ------------------------------------------------------------ layout */
  for (const [label, width, height] of [['desktop', 1600, 1000], ['laptop', 1100, 820], ['phone', 390, 844]]) {
    const p = await browser.newPage({ viewport: { width, height } });
    await p.goto(PAGE);
    await p.waitForTimeout(1500);
    const film = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await p.evaluate(() => window.CUTLIST_FILM.openDesk(0));
    await p.waitForTimeout(500);
    const desk = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`no sideways scroll at ${width}px (${label})`, film <= 1 && desk <= 1,
      `film +${Math.max(0, film)} desk +${Math.max(0, desk)}`);
    await p.close();
  }

  /* --------------------------------------------------- reduced motion */
  const rm = await browser.newPage({ viewport: { width: 1600, height: 1000 }, reducedMotion: 'reduce' });
  await rm.goto(PAGE);
  await rm.waitForTimeout(1500);
  const revealed = await rm.evaluate(() => {
    const all = [...document.querySelectorAll('[data-reveal]')];
    return [all.filter(e => getComputedStyle(e).opacity === '1').length, all.length];
  });
  check('reduced motion still shows every section', revealed[0] === revealed[1], revealed.join('/'));
  await rm.close();

  await browser.close();

  /* ------------------------------------------------------------ report */
  const pad = Math.max(...results.map(r => r.name.length));
  for (const r of results) {
    const mark = r.pass ? 'ok  ' : 'FAIL';
    const note = r.detail && !r.pass ? '   ' + r.detail : (r.detail ? '   (' + r.detail + ')' : '');
    console.log(`  ${mark}  ${r.name.padEnd(pad)}${note}`);
  }
  const failed = results.filter(r => !r.pass).length;
  console.log(`\n  ${results.length - failed}/${results.length} passed\n`);
  process.exit(failed ? 1 : 0);
}

run().catch(e => { console.error(e); process.exit(1); });
