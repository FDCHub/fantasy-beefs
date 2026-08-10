/* ============================================================================
 * FantasyStakes — Sprint 7 Package 1 · shell layout end-to-end tests
 *
 * Run directly:   node web/tests/e2e_shell.mjs
 * Or through the repository suite:   python test_s7_p1_ui_shell.py
 *
 * Drives a real headless Chrome over the DevTools protocol and asserts against
 * MEASURED GEOMETRY. Source inspection can show that the navigation is in
 * normal flow; only a laid-out page can show that it does not overlap the
 * active panel at a phone viewport, that nothing overflows horizontally, and
 * that the close control really lands in the upper-right of the sheet.
 *
 * No dependencies: a small static server and a raw CDP client over the WebSocket
 * built into Node.
 * ========================================================================== */

import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = resolve(HERE, '..');

/** Phone viewport used for every geometry assertion. */
const VIEWPORT = { width: 390, height: 844 };

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

/* ── Chrome discovery ───────────────────────────────────────────────────── */

function findChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ].filter(Boolean);
  return candidates.find((p) => existsSync(p)) || null;
}

/* ── Static server ──────────────────────────────────────────────────────── */

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
};

function startServer() {
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const rel = url.pathname === '/' ? '/index.html' : url.pathname;
    const path = join(WEB_ROOT, rel);
    if (!path.startsWith(WEB_ROOT)) {
      res.writeHead(403).end();
      return;
    }
    try {
      const body = await readFile(path);
      res.writeHead(200, { 'Content-Type': MIME[extname(path)] || 'application/octet-stream' });
      res.end(body);
    } catch {
      res.writeHead(404).end();
    }
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok(server)));
}

/* ── Minimal CDP client ─────────────────────────────────────────────────── */

async function connectCdp(port) {
  let targets;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      if (targets.some((t) => t.type === 'page' && t.webSocketDebuggerUrl)) break;
    } catch { /* browser still starting */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  const page = (targets || []).find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  if (!page) throw new Error('no debuggable page target');

  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((ok, fail) => {
    socket.addEventListener('open', ok, { once: true });
    socket.addEventListener('error', () => fail(new Error('CDP socket failed')), { once: true });
  });

  let nextId = 0;
  const pending = new Map();
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    const entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id);
    if (message.error) entry.fail(new Error(message.error.message));
    else entry.ok(message.result);
  });

  const send = (method, params = {}) => new Promise((ok, fail) => {
    const id = (nextId += 1);
    pending.set(id, { ok, fail });
    socket.send(JSON.stringify({ id, method, params }));
  });

  return { send, close: () => socket.close() };
}

/**
 * Evaluate an expression in the page and return its value.
 */
async function evaluate(cdp, expression) {
  const result = await cdp.send('Runtime.evaluate', {
    expression: `(() => { ${expression} })()`,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || 'evaluation failed');
  }
  return result.result.value;
}

/* ── Test run ───────────────────────────────────────────────────────────── */

const chrome = findChrome();
if (!chrome) {
  console.log('  [FAIL] a Chrome or Edge binary is available for the layout tests');
  console.log('\nFAILED: 1 assertion(s)\n  - no browser found; set CHROME_PATH');
  process.exit(1);
}

const server = await startServer();
const { port } = server.address();
const profile = await mkdtemp(join(tmpdir(), 'fs-e2e-'));

const browser = spawn(chrome, [
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  '--no-default-browser-check',
  '--remote-debugging-port=9333',
  `--user-data-dir=${profile}`,
  `--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
  'about:blank',
], { stdio: 'ignore' });

let cdp;
try {
  cdp = await connectCdp(9333);

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  // Emulate a phone viewport exactly: desktop Chrome otherwise ignores the
  // viewport meta tag, and the layout under test is a mobile layout.
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: VIEWPORT.width,
    height: VIEWPORT.height,
    deviceScaleFactor: 3,
    mobile: true,
  });

  await cdp.send('Page.navigate', { url: `http://127.0.0.1:${port}/index.html` });
  await new Promise((r) => setTimeout(r, 900));

  console.log('\nThe app renders in a real browser at a phone viewport');

  check('the shell mounted', await evaluate(cdp, `
    return document.querySelectorAll('.fs-tabbar__item').length === 5;
  `));
  check('the masthead rendered its lockup', await evaluate(cdp, `
    return document.querySelector('.fs-mast__word').textContent === 'FantasyStakes';
  `));
  check('the tagline rendered', await evaluate(cdp, `
    return document.querySelector('.fs-mast__tagline').textContent
      === 'FANTASY LEAGUES · VIRTUAL STAKES';
  `));
  check('neither half of the tagline is broken across lines', await evaluate(cdp, `
    return [...document.querySelectorAll('.fs-mast__tagline .fs-nowrap')]
      .every(span => span.getClientRects().length === 1);
  `));

  console.log('\nNothing overflows the phone viewport');

  const overflow = await evaluate(cdp, `
    return {
      docWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      appWidth: document.getElementById('fs-app').scrollWidth,
    };
  `);
  check(
    'the document does not scroll horizontally',
    overflow.docWidth <= overflow.innerWidth,
    `document ${overflow.docWidth}px vs viewport ${overflow.innerWidth}px`,
  );
  check(
    'the app frame fits the viewport',
    overflow.appWidth <= overflow.innerWidth,
    `app ${overflow.appWidth}px vs viewport ${overflow.innerWidth}px`,
  );

  console.log('\nAll five navigation destinations are reachable');

  const destinations = await evaluate(cdp, `
    return [...document.querySelectorAll('.fs-tabbar__item')]
      .map(el => el.dataset.destination);
  `);
  check('five destinations are bound', destinations.length === 5, destinations.join(', '));

  for (const id of destinations) {
    const state = await evaluate(cdp, `
      document.querySelector('.fs-tabbar__item[data-destination="${id}"]').click();
      const panel = document.querySelector('.fs-panel.is-active');
      const tab = document.querySelector('.fs-tabbar__item.is-active');
      const rect = panel ? panel.getBoundingClientRect() : null;
      return {
        activePanels: document.querySelectorAll('.fs-panel.is-active').length,
        panelId: panel ? panel.id : null,
        tabId: tab ? tab.dataset.destination : null,
        selected: tab ? tab.getAttribute('aria-selected') : null,
        visible: rect ? rect.width > 0 && rect.height > 0 : false,
      };
    `);
    check(
      `${id} opens exactly one visible panel`,
      state.activePanels === 1 && state.panelId === `panel-${id}` && state.visible,
      `${state.panelId}, ${state.activePanels} active`,
    );
    check(
      `${id} is marked selected for assistive tech`,
      state.tabId === id && state.selected === 'true',
    );
  }

  console.log('\nThe persistent navigation never covers tab content');

  for (const id of destinations) {
    const geometry = await evaluate(cdp, `
      document.querySelector('.fs-tabbar__item[data-destination="${id}"]').click();
      const bar = document.querySelector('.fs-tabbar').getBoundingClientRect();
      const panel = document.querySelector('.fs-panel.is-active').getBoundingClientRect();
      const children = [...document.querySelector('.fs-panel.is-active').children]
        .map(el => el.getBoundingClientRect().bottom);
      return {
        barTop: bar.top,
        barBottom: bar.bottom,
        panelBottom: panel.bottom,
        lowestChild: children.length ? Math.max(...children) : 0,
        viewport: window.innerHeight,
      };
    `);
    check(
      `${id}: the panel ends at or above the navigation`,
      geometry.panelBottom <= geometry.barTop + 0.5,
      `panel ${geometry.panelBottom.toFixed(1)}px vs nav top ${geometry.barTop.toFixed(1)}px`,
    );
    check(
      `${id}: no panel content is drawn under the navigation`,
      geometry.lowestChild <= geometry.barTop + 0.5,
      `lowest content ${geometry.lowestChild.toFixed(1)}px`,
    );
    check(
      `${id}: the navigation sits fully on screen`,
      geometry.barBottom <= geometry.viewport + 0.5,
      `nav bottom ${geometry.barBottom.toFixed(1)}px vs viewport ${geometry.viewport}px`,
    );
  }

  console.log('\nThe shared strip renders consistently across tabs');

  // Each strip is measured while ITS OWN tab is active. A hidden panel reports
  // zero-sized rectangles, and measuring one would make every geometry
  // assertion here pass vacuously.
  const strips = [];
  for (const id of destinations) {
    const measured = await evaluate(cdp, `
      document.querySelector('.fs-tabbar__item[data-destination="${id}"]').click();
      const panel = document.querySelector('.fs-panel.is-active');
      const strip = panel.querySelector('.fs-strip');
      if (!strip) return null;
      const cells = [...strip.querySelectorAll('.fs-strip__cell')];
      const widths = cells.map(c => Math.round(c.getBoundingClientRect().width));
      const box = strip.getBoundingClientRect();
      return {
        id: strip.id,
        cellCount: cells.length,
        widths,
        left: Math.round(box.left),
        right: Math.round(box.right),
        height: Math.round(box.height),
        icons: strip.querySelectorAll('svg, img').length,
        clipped: cells.some(c => c.scrollWidth > c.clientWidth + 1),
      };
    `);
    if (measured) strips.push(measured);
  }

  check('League, Action and Ledger each carry a strip', strips.length === 3, `${strips.length} strips`);
  for (const strip of strips) {
    check(`${strip.id}: four cells`, strip.cellCount === 4, `${strip.cellCount}`);
    check(
      `${strip.id}: the strip is actually laid out`,
      strip.height > 0 && strip.widths.every((w) => w > 0),
      `height ${strip.height}px, widths ${strip.widths.join('/')}`,
    );
    check(
      `${strip.id}: cells are equal width`,
      new Set(strip.widths).size === 1,
      strip.widths.join('/'),
    );
    check(
      `${strip.id}: the fourth cell is fully on screen`,
      strip.left >= 0 && strip.right <= VIEWPORT.width,
      `${strip.left}px…${strip.right}px in a ${VIEWPORT.width}px viewport`,
    );
    check(`${strip.id}: no cell clips its own content`, strip.clipped === false);
    check(`${strip.id}: icon-free`, strip.icons === 0);
  }

  check(
    'every strip renders at the same geometry — one shared component',
    new Set(strips.map((s) => `${s.left}:${s.right}:${s.widths.join('/')}`)).size === 1,
    strips.map((s) => s.widths.join('/')).join('  vs  '),
  );

  console.log('\nCredit figures draw as whole dollars over exact cents');

  const money = await evaluate(cdp, `
    const values = [...document.querySelectorAll('[data-exact-cents]')];
    return values.map(el => ({
      exact: el.getAttribute('data-exact-cents'),
      drawn: el.textContent.trim(),
    }));
  `);
  check('rendered money carries its exact cents', money.length >= 4, `${money.length} figures`);
  check(
    'no rendered Credit figure shows cents',
    money.every((m) => !/\$\d[\d,]*\.\d/.test(m.drawn)),
    money.map((m) => m.drawn).join(' '),
  );
  check(
    'each drawn figure is its exact value rounded to whole dollars',
    money.every((m) => {
      const cents = Number(m.exact);
      const dollars = (cents < 0 ? -1 : 1) * Math.floor((Math.abs(cents) + 50) / 100);
      return m.drawn.includes(`$${Math.abs(dollars).toLocaleString('en-US')}`);
    }),
  );

  console.log('\nThe Credits disclaimer appears under its strip, once per tab');

  const disclaimers = await evaluate(cdp, `
    const out = [];
    for (const panel of document.querySelectorAll('.fs-panel')) {
      const found = panel.querySelectorAll('.fs-disclaimer');
      const strip = panel.querySelector('.fs-strip');
      out.push({
        id: panel.id,
        count: found.length,
        text: found[0] ? found[0].textContent : null,
        belowStrip: found[0] && strip
          ? found[0].getBoundingClientRect().top >= strip.getBoundingClientRect().top
          : null,
        fits: found[0] ? found[0].scrollWidth <= found[0].clientWidth : null,
      });
    }
    return out;
  `);
  for (const panel of disclaimers) {
    check(`${panel.id}: at most one disclaimer`, panel.count <= 1, `${panel.count}`);
    if (panel.count === 1) {
      check(
        `${panel.id}: the disclaimer reads exactly the approved string`,
        panel.text === 'VIRTUAL CREDITS · $ IS DISPLAY ONLY · NO CASH VALUE',
        panel.text,
      );
      check(`${panel.id}: the disclaimer sits under the strip`, panel.belowStrip === true);
      check(`${panel.id}: the disclaimer is not clipped`, panel.fits === true);
    }
  }

  console.log('\nThe shared pop-out closes from an upper-right control');

  const sheetGeometry = await evaluate(cdp, `
    document.querySelector('.fs-tabbar__item[data-destination="ledger"]').click();
    document.querySelector('#fs-strip-ledger .fs-strip__cell.is-gold').click();
    const overlay = document.getElementById('fs-overlay');
    const sheet = document.getElementById('fs-sheet');
    const close = sheet.querySelector('[data-fs-close]');
    const s = sheet.getBoundingClientRect();
    const c = close.getBoundingClientRect();
    return {
      open: overlay.classList.contains('is-open'),
      hidden: overlay.getAttribute('aria-hidden'),
      fromRight: s.right - c.right,
      fromTop: c.top - s.top,
      fromLeft: c.left - s.left,
      sheetWidth: s.width,
      sheetHeight: s.height,
      focused: document.activeElement === close,
      anchoredBottom: Math.abs(s.bottom - window.innerHeight) < 1,
    };
  `);
  check('the sheet opens', sheetGeometry.open === true);
  check('the sheet is exposed to assistive tech', sheetGeometry.hidden === 'false');
  check('the sheet is anchored to the bottom edge', sheetGeometry.anchoredBottom === true);
  check(
    'the close control sits in the upper-right of the sheet',
    sheetGeometry.fromRight >= 0 &&
    sheetGeometry.fromRight < sheetGeometry.sheetWidth / 4 &&
    sheetGeometry.fromTop >= 0 &&
    sheetGeometry.fromTop < sheetGeometry.sheetHeight / 3,
    `${sheetGeometry.fromRight.toFixed(1)}px from right, ${sheetGeometry.fromTop.toFixed(1)}px from top`,
  );
  check(
    'the close control is nearer the right edge than the left',
    sheetGeometry.fromRight < sheetGeometry.fromLeft,
    `right ${sheetGeometry.fromRight.toFixed(1)}px vs left ${sheetGeometry.fromLeft.toFixed(1)}px`,
  );
  check('the close control takes focus on open', sheetGeometry.focused === true);

  const closed = await evaluate(cdp, `
    document.querySelector('#fs-sheet [data-fs-close]').click();
    return {
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      hidden: document.getElementById('fs-overlay').getAttribute('aria-hidden'),
    };
  `);
  check('the close control closes the sheet', closed.open === false && closed.hidden === 'true');

  const reopenedThenNavigated = await evaluate(cdp, `
    document.querySelector('#fs-strip-ledger .fs-strip__cell.is-gold').click();
    const wasOpen = document.getElementById('fs-overlay').classList.contains('is-open');
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    return { wasOpen, stillOpen: document.getElementById('fs-overlay').classList.contains('is-open') };
  `);
  check(
    'a destination change dismisses the sheet',
    reopenedThenNavigated.wasOpen === true && reopenedThenNavigated.stillOpen === false,
  );
} finally {
  if (cdp) cdp.close();
  browser.kill();
  server.close();
  await rm(profile, { recursive: true, force: true }).catch(() => {});
}

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`FAILED: ${failures.length} assertion(s)`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
} else {
  console.log('All assertions PASSED');
}