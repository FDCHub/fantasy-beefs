/* ==========================================================================
 * FantasyStakes marketing site - static server + headless Chrome, no deps
 *
 * The same approach the application suites already use (web/tests/browser-
 * harness.mjs): a Node static server, a headless Chrome and a raw DevTools
 * Protocol client over Node's built-in WebSocket. Nothing is installed, so the
 * site keeps its "no dependencies" property all the way through its own tooling.
 *
 * TWO CALLERS, ONE CONNECTION SHAPE: build_assets.mjs rasterises the icons and
 * the social card; preview_check.mjs drives the local preview at six viewports.
 *
 * THE SERVER APPLIES `_headers`. That is the point of it. A Content-Security-
 * Policy that is only ever exercised in production is a policy nobody has
 * tested, and the one failure mode that matters here - a CSP that silently
 * blocks the site's own stylesheet or script - is invisible unless the preview
 * serves the same headers Cloudflare Pages will.
 * ========================================================================== */

import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = resolve(HERE, '..', '..');
export const SITE_ROOT = join(REPO_ROOT, 'site');
export const TOOLS_ROOT = HERE;

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
  '.xml': 'application/xml; charset=utf-8',
};

export function findChrome() {
  return [
    process.env.CHROME_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ].filter(Boolean).find((p) => existsSync(p)) || null;
}

/**
 * Parse `site/_headers` into an ordered list of [pattern, headers] pairs.
 *
 * A deliberately small subset of the Cloudflare Pages syntax - a path line in
 * column 0, indented `Name: value` lines under it - because that is the entire
 * syntax this site uses. Anything richer would be a parser for a file nobody
 * wrote.
 */
export async function loadHeaderRules() {
  const path = join(SITE_ROOT, '_headers');
  if (!existsSync(path)) return [];
  const rules = [];
  let current = null;
  for (const raw of (await readFile(path, 'utf8')).split(/\r?\n/)) {
    if (!raw.trim() || raw.trim().startsWith('#')) continue;
    if (!/^\s/.test(raw)) {
      current = { pattern: raw.trim(), headers: {} };
      rules.push(current);
      continue;
    }
    const at = raw.indexOf(':');
    if (at > 0 && current) current.headers[raw.slice(0, at).trim()] = raw.slice(at + 1).trim();
  }
  return rules;
}

function matches(pattern, pathname) {
  if (pattern.endsWith('/*')) return pathname.startsWith(pattern.slice(0, -1));
  if (pattern === '/*') return true;
  return pattern === pathname;
}

/**
 * Serve `site/` the way Cloudflare Pages will: directory requests resolve to
 * `index.html`, unknown paths fall through to `404.html` with a 404 status, and
 * `_headers` is applied to every response.
 *
 * `/_tools/*` is an extra mount for files that must NOT be published - the
 * social-card source lives there.
 */
export function startServer(rules) {
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    let pathname = decodeURIComponent(url.pathname);

    // `/_tools/*` is never published, so the published site's `_headers` rules
    // do not describe it and are not applied to it. The social-card source
    // carries an inline <style> block that the site's CSP correctly forbids;
    // serving it under that CSP would break the card generator to enforce a
    // policy on a file that will never be served to anyone.
    let root = SITE_ROOT;
    let published = true;
    if (pathname.startsWith('/_tools/')) {
      root = TOOLS_ROOT;
      published = false;
      pathname = pathname.slice('/_tools'.length);
    }

    let rel = pathname;
    if (rel.endsWith('/')) rel += 'index.html';
    else if (!extname(rel)) rel += '/index.html';

    const file = join(root, rel);
    if (!file.startsWith(root)) { res.writeHead(403).end(); return; }

    const headers = {};
    if (published) {
      for (const rule of rules) {
        if (matches(rule.pattern, pathname)) Object.assign(headers, rule.headers);
      }
    }

    try {
      const body = await readFile(file);
      res.writeHead(200, { ...headers, 'Content-Type': MIME[extname(file)] || 'application/octet-stream' });
      res.end(body);
    } catch {
      try {
        const body = await readFile(join(SITE_ROOT, '404.html'));
        res.writeHead(404, { ...headers, 'Content-Type': MIME['.html'] });
        res.end(body);
      } catch {
        res.writeHead(404).end();
      }
    }
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok(server)));
}

async function connectCdp(port) {
  let targets = null;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      if (targets.some((t) => t.type === 'page' && t.webSocketDebuggerUrl)) break;
    } catch { /* still starting */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  const target = (targets || []).find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  if (!target) throw new Error('no debuggable page target');

  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok, fail) => {
    socket.addEventListener('open', ok, { once: true });
    socket.addEventListener('error', () => fail(new Error('CDP socket failed')), { once: true });
  });

  let nextId = 0;
  const pending = new Map();
  const listeners = [];
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (message.id === undefined) {
      for (const fn of listeners) fn(message);
      return;
    }
    const entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id);
    if (message.error) entry.fail(new Error(message.error.message));
    else entry.ok(message.result);
  });

  return {
    send: (method, params = {}) => new Promise((ok, fail) => {
      const id = (nextId += 1);
      pending.set(id, { ok, fail });
      socket.send(JSON.stringify({ id, method, params }));
    }),
    on: (fn) => listeners.push(fn),
    close: () => socket.close(),
  };
}

/**
 * Serve the site, open a headless Chrome against it, and hand the body a CDP
 * session plus the origin. Everything is torn down afterwards, pass or fail.
 */
export async function withBrowser(body) {
  const chrome = findChrome();
  if (!chrome) {
    console.error('no Chrome or Edge binary found; set CHROME_PATH');
    process.exit(1);
  }

  const rules = await loadHeaderRules();
  const server = await startServer(rules);
  const origin = `http://127.0.0.1:${server.address().port}`;
  const profile = await mkdtemp(join(tmpdir(), 'fs-site-'));
  const port = 9444 + Math.floor(server.address().port % 500);

  const browser = spawn(chrome, [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--hide-scrollbars',
    '--force-device-scale-factor=1',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    'about:blank',
  ], { stdio: 'ignore' });

  let cdp = null;
  try {
    cdp = await connectCdp(port);
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Log.enable');
    return await body({ cdp, origin });
  } finally {
    if (cdp) cdp.close();
    browser.kill();
    await new Promise((ok) => server.close(ok));
    await rm(profile, { recursive: true, force: true }).catch(() => {});
  }
}

/** Navigate and wait for the load event plus a short settle. */
export async function goto(cdp, url, settleMs = 400) {
  const loaded = new Promise((ok) => {
    const stop = cdp.on((m) => { if (m.method === 'Page.loadEventFired') ok(); });
    void stop;
  });
  await cdp.send('Page.navigate', { url });
  await Promise.race([loaded, new Promise((ok) => setTimeout(ok, 8000))]);
  await new Promise((ok) => setTimeout(ok, settleMs));
}

/** Evaluate an expression in the page and return its JSON value. */
export async function evaluate(cdp, expression) {
  const result = await cdp.send('Runtime.evaluate', {
    expression: `(function(){ ${expression} })()`,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || 'evaluate threw');
  }
  return result.result.value;
}
