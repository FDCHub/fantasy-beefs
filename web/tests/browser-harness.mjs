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
 * overflowed.
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

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
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
 * @param {{port?: number, path?: string, settleMs?: number}} options
 * @param {(ctx: {evaluate: (expression: string) => Promise<any>}) => Promise<void>} body
 */
export async function withPage(options, body) {
  const { port = 9333, path = '/index.html', settleMs = 900 } = options || {};

  const chrome = findChrome();
  if (!chrome) {
    console.log('  [FAIL] a Chrome or Edge binary is available for the layout tests');
    console.log('\nFAILED: 1 assertion(s)\n  - no browser found; set CHROME_PATH');
    process.exit(1);
  }

  const server = await startServer();
  const { port: httpPort } = server.address();
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
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${httpPort}${path}` });
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

    await body({ evaluate });
  } finally {
    if (cdp) cdp.close();
    browser.kill();
    server.close();
    await rm(profile, { recursive: true, force: true }).catch(() => {});
  }
}