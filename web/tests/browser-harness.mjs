/* ============================================================================
 * FantasyStakes — browser test harness
 * Sprint 7 Package 2
 *
 * A static server, a headless Chrome, and a raw DevTools-protocol client over
 * Node's built-in WebSocket. No dependencies.
 *
 * Layout claims are only worth as much as the layout they were measured in, so
 * every suite that uses this harness runs against a real phone viewport with
 * mobile emulation on. Desktop Chrome ignores the viewport meta tag, and a
 * suite that measured a desktop layout would pass while the phone build
 * overflowed. `setViewport` re-applies that emulation so one suite can certify
 * several phone sizes in a single session.
 * ========================================================================== */

import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const WEB_ROOT = resolve(HERE, '..');

/** The phone viewport every geometry assertion is measured in. */
export const VIEWPORT = Object.freeze({ width: 390, height: 844 });

/**
 * Navigate to Rules & Settings the way a GM now has to — WP3B, Rev 4.3 §3.1.
 *
 * Rules & Settings no longer holds a bottom-navigation position, so
 * `.fs-tabbar__item[data-destination="rules"]` does not exist and every suite
 * that used it would fail at the first line. This is the replacement, and it is
 * DELIBERATELY THE REAL PATH rather than a `FantasyStakes.goTo('rules')` short
 * cut: six suites reach Rules through it, so every one of them now also proves
 * WP3B §20 — that removing the tab did not make the surface unreachable.
 *
 * A JS SNIPPET RATHER THAN A FUNCTION, because these suites navigate from
 * inside `evaluate()` template strings and the snippet has to run in the page.
 *
 * @type {string}
 */
export const GO_RULES = `
  document.getElementById('fs-gear').click();
  document.querySelector('#fs-menu [data-menu="rules"]').click();
`;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  // WP3E — the static server must speak the PWA assets too, or a manifest and
  // an icon fetched from it arrive as octet-stream and the browser declines
  // them for reasons no assertion would explain.
  '.webmanifest': 'application/manifest+json',
  '.json': 'application/json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

/**
 * A [PASS]/[FAIL] reporter in the repository's suite style.
 */
export function createReporter() {
  const failures = [];
  return {
    failures,
    check(label, condition, detail = '') {
      const mark = condition ? 'PASS' : 'FAIL';
      console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
      if (!condition) failures.push(label);
    },
    section(title) {
      console.log(`\n${title}`);
    },
    finish() {
      console.log(`\n${'='.repeat(52)}`);
      if (failures.length) {
        console.log(`FAILED: ${failures.length} assertion(s)`);
        for (const f of failures) console.log(`  - ${f}`);
        process.exit(1);
      }
      console.log('All assertions PASSED');
    },
  };
}

export function findChrome() {
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

/**
 * A `--name=value` argument, falling back to an environment variable (Sprint 8).
 *
 * Read HERE rather than in each suite deliberately. Sprint 8 changed where the
 * suites are served from and whether a session is needed first; that is a
 * property of the harness, not of what any suite asserts. Centralising it
 * meant the five Sprint 7 suites required no edit at all, so their assertions
 * are recognisably the ones that were certified at 6be0f50.
 *
 * THE ENVIRONMENT FALLBACK IS WHAT MAKES THAT POSSIBLE. The certification
 * entry point runs Python package suites which run node suites, so an argv
 * value would have to be threaded through three layers of subprocess by hand —
 * three chances to forget one, each of which would silently fall back to the
 * static server and fail confusingly. An environment variable is inherited by
 * the whole chain.
 *
 * @param {string} name kebab-case, e.g. 'auth-email'
 * @returns {string|null}
 */
function harnessOption(name) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  if (hit) return hit.slice(name.length + 3);
  return process.env[`FS_TEST_${name.toUpperCase().replace(/-/g, '_')}`] || null;
}

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

async function connectCdp(port) {
  let targets;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      if (targets.some((t) => t.type === 'page' && t.webSocketDebuggerUrl)) break;
    } catch { /* the browser is still starting */ }
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
 * Serve `web/`, open it in a phone-emulated headless Chrome, and hand the body
 * an `evaluate` function. Everything is torn down afterwards, pass or fail.
 *
 * `origin` (Sprint 8) points the page at a server the CALLER already runs,
 * instead of this module's static one. The Sprint 7 suites certify static
 * markup, for which a file server is exactly right; a session suite cannot use
 * one, because cookies, same-origin fetch and CSRF only mean anything relative
 * to a real origin that also answers the API. Passing `origin` skips the
 * static server rather than starting one nothing will talk to.
 *
 * @param {{port?: number, path?: string, settleMs?: number, origin?: string}} options
 * @param {(ctx: {evaluate: (expression: string) => Promise<any>}) => Promise<void>} body
 */
export async function withPage(options, body) {
  const { port = 9333, settleMs = 900 } = options || {};

  // --origin wins over the option, so one driver can point every suite at the
  // application it started without each suite knowing that happened.
  const origin = harnessOption('origin') || options?.origin || null;

  // Served from the app's /app mount when there is an origin, from the static
  // server's root when there is not. A suite may still name its own path.
  const path = options?.path || (origin ? '/app/index.html' : '/index.html');

  const authEmail = harnessOption('auth-email');
  const authPassword = harnessOption('auth-password');

  const chrome = findChrome();
  if (!chrome) {
    console.log('  [FAIL] a Chrome or Edge binary is available for the layout tests');
    console.log('\nFAILED: 1 assertion(s)\n  - no browser found; set CHROME_PATH');
    process.exit(1);
  }

  const server = origin ? null : await startServer();
  const pageOrigin = origin || `http://127.0.0.1:${server.address().port}`;
  const profile = await mkdtemp(join(tmpdir(), 'fs-e2e-'));

  const browser = spawn(chrome, [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    `--window-size=${VIEWPORT.width},${VIEWPORT.height}`,
    'about:blank',
  ], { stdio: 'ignore' });

  let cdp;
  try {
    cdp = await connectCdp(port);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: VIEWPORT.width,
      height: VIEWPORT.height,
      deviceScaleFactor: 3,
      mobile: true,
    });
    // ── Establish a session BEFORE the application first mounts ────────────
    //
    // Since S8-P1 the shell asks who is acting before it draws anything, so a
    // suite that certifies the application has to arrive already signed in.
    // The sign-in is done from a page on the TARGET ORIGIN, because that is
    // the only way the browser will accept and keep the cookie — setting it
    // over CDP would test the harness's idea of a cookie rather than the
    // server's.
    if (authEmail && authPassword) {
      await cdp.send('Page.navigate', { url: `${pageOrigin}/app/index.html` });
      await new Promise((r) => setTimeout(r, settleMs));

      const signIn = await cdp.send('Runtime.evaluate', {
        expression: `(async () => {
          const res = await fetch('/auth/session', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              email: ${JSON.stringify(authEmail)},
              password: ${JSON.stringify(authPassword)},
            }),
          });
          return res.status;
        })()`,
        returnByValue: true,
        awaitPromise: true,
      });

      if (signIn.result?.value !== 200) {
        throw new Error(
          `harness sign-in failed for ${authEmail} (status ${signIn.result?.value})`);
      }
    }

    await cdp.send('Page.navigate', { url: `${pageOrigin}${path}` });
    await new Promise((r) => setTimeout(r, settleMs));

    const evaluate = async (expression) => {
      const result = await cdp.send('Runtime.evaluate', {
        expression: `(() => { ${expression} })()`,
        returnByValue: true,
        awaitPromise: true,
      });
      if (result.exceptionDetails) {
        throw new Error(result.exceptionDetails.exception?.description || 'evaluation failed');
      }
      return result.result.value;
    };

    /**
     * Re-emulate at a different phone size.
     *
     * Package 5 certifies three viewports rather than one, and a layout claim
     * is only worth as much as the layout it was measured in — so the metrics
     * override is reapplied rather than the page merely being resized.
     *
     * @param {number} width
     * @param {number} height
     */
    const setViewport = async (width, height) => {
      await cdp.send('Emulation.setDeviceMetricsOverride', {
        width, height, deviceScaleFactor: 3, mobile: true,
      });
      await cdp.send('Page.navigate', { url: `${pageOrigin}${path}` });
      await new Promise((r) => setTimeout(r, settleMs));
    };

    /**
     * Reload the page and wait for it to settle (Sprint 8).
     *
     * Driven from the DEBUGGER, not from an in-page `location.reload()`. An
     * in-page reload destroys the execution context that the pending
     * `Runtime.evaluate` belongs to, so the call that triggered it rejects
     * with "Inspected target navigated or closed" — the navigation succeeds
     * and the suite dies anyway. Navigating over CDP keeps the harness on the
     * outside of the thing it is driving.
     */
    const reload = async () => {
      await cdp.send('Page.navigate', { url: `${pageOrigin}${path}` });
      await new Promise((r) => setTimeout(r, settleMs));
    };

    await body({ evaluate, setViewport, reload });
  } finally {
    if (cdp) cdp.close();
    browser.kill();

    // WAIT FOR THE BROWSER TO ACTUALLY EXIT (Sprint 8). `kill()` only asks.
    // Chrome's renderer children outlive the parent's acknowledgement by some
    // tens of milliseconds, and until they are gone the profile directory is
    // still being written to. Deleting it underneath them left processes and
    // lock files behind, and the certification entry point — which runs five
    // of these back to back — intermittently had a later Chrome die at startup
    // with no output at all, which reads as "0 PASS / 0 FAIL" rather than as
    // anything diagnosable.
    //
    // Bounded, and a timeout is not fatal: a browser that will not exit is
    // worth neither hanging the suite nor failing a run whose assertions have
    // already been made.
    await new Promise((done) => {
      const timer = setTimeout(done, 3000);
      browser.once('exit', () => { clearTimeout(timer); done(); });
    });

    if (server) server.close();
    await rm(profile, { recursive: true, force: true }).catch(() => {});
  }
}