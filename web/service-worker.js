/* ============================================================================
 * FantasyStakes — service worker
 * WP3E · deliberately, aggressively minimal
 *
 * WHY THERE IS ONE AT ALL. Installability. iOS will add a page to the home
 * screen from a manifest alone, but Chrome and the Android install prompt want
 * a registered worker with a fetch handler before they will offer to install.
 * That is the ONLY reason this file exists.
 *
 * WHY IT CACHES ALMOST NOTHING. FantasyStakes is a live money-adjacent product.
 * A Wallet balance, a Ledger row, a market line, a provider state or a session
 * served from a cache is a figure presented as current that is not, and there
 * is no banner that makes that acceptable. So the rule here is the strict one:
 *
 *     NEVER CACHE ANYTHING FROM THE API. Not reads, not writes, not identity,
 *     not `/auth/*`, not provider data, not economics. Not once, not briefly.
 *
 * WHAT IT DOES CACHE: the static app shell — HTML, CSS, JS, icons, manifest —
 * and even those NETWORK-FIRST, so a deployed release is picked up on the next
 * load rather than on some later eviction. The cache is a fallback for a failed
 * request, not a source of truth.
 *
 * ── WHY NETWORK-FIRST AND NOT CACHE-FIRST ─────────────────────────────────
 *
 * Cache-first is the usual advice and it is wrong for this product. The locked
 * mid-season update requirement says a frontend release must reach users
 * without leaving them on indefinitely stale assets, and the deployment model
 * is frontend-independent: the server can move ahead of the page. A cache-first
 * shell would pin a browser to whatever JavaScript it happened to install,
 * potentially for weeks, talking to a server that had moved on. Network-first
 * costs one conditional request per asset and removes that failure entirely.
 *
 * ── UPDATE BEHAVIOUR, STATED ──────────────────────────────────────────────
 *
 *   install    pre-cache nothing; take over immediately (`skipWaiting`)
 *   activate   delete every cache whose name is not this version's, then
 *              `clients.claim()` so open tabs are governed by the new worker
 *   fetch      network first for same-origin static assets; cache only as a
 *              fallback; API and cross-origin requests are not intercepted
 *
 * Bump `VERSION` on any release whose static assets changed. The old cache is
 * deleted on activation, so there is no path by which a previous release's
 * assets survive into a new one.
 *
 * WHAT THIS IS NOT. It is not an offline mode. With no network the shell may
 * paint from cache and every authoritative read will fail — which the
 * application already renders as its governed unavailable states. It does not
 * fabricate a Wallet, a market or a league, and it never will from here.
 * ========================================================================== */

const VERSION = 'fs-shell-v1';

/* Requests that must NEVER touch a cache, matched before anything else.
 *
 * `/auth/` covers the session, the identity read, the Yahoo start and the
 * callback. `/league/` covers every authoritative read the product makes.
 * The list is a prefix match on the pathname, so a new route under any of them
 * is covered the day it is added rather than the day somebody remembers. */
const NEVER_CACHE = ['/auth/', '/league/', '/beef/', '/health', '/settle',
                     '/pool/', '/wallet/', '/economy', '/admin/'];

/* Only these extensions are ever stored. Anything without one — which is every
 * API path in this product — falls through untouched. */
const SHELL_EXTENSIONS = ['.html', '.css', '.js', '.mjs', '.png', '.svg',
                          '.woff', '.woff2', '.webmanifest', '.json'];

self.addEventListener('install', (event) => {
  // NOTHING IS PRE-CACHED. A pre-cache list is a second inventory of the app's
  // assets that drifts from the real one; the fetch handler fills the cache
  // with exactly what the page actually asked for.
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names
      .filter((name) => name !== VERSION)
      .map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

function isShellAsset(url) {
  if (NEVER_CACHE.some((prefix) => url.pathname.startsWith(prefix))) return false;
  const path = url.pathname.toLowerCase();
  if (path.endsWith('/') || path === '') return true;          // the app root
  return SHELL_EXTENSIONS.some((ext) => path.endsWith(ext));
}

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // ONLY PLAIN GETs. A POST, a PUT or a DELETE is a command and is never
  // replayed from anywhere.
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // SAME ORIGIN ONLY. A cross-origin request — the Yahoo attribution link, or
  // anything else that leaves — is the browser's business, not this worker's.
  if (url.origin !== self.location.origin) return;

  // CREDENTIALED REQUESTS ARE NEVER STORED. Anything carrying a session is by
  // definition per-user, and a shared cache is the wrong place for it.
  if (request.credentials === 'include') return;

  if (!isShellAsset(url)) return;

  event.respondWith((async () => {
    try {
      // NETWORK FIRST. A successful, non-partial, basic response replaces
      // whatever was stored; anything else is passed through untouched so an
      // opaque or partial response can never be mistaken for a good copy.
      const response = await fetch(request);
      if (response && response.status === 200 && response.type === 'basic') {
        const cache = await caches.open(VERSION);
        cache.put(request, response.clone());
      }
      return response;
    } catch (networkError) {
      // OFFLINE, OR THE SERVER IS UNREACHABLE. The stored shell is offered so
      // the application can paint and report its own unavailable states in
      // product language. If nothing is stored, the failure propagates and the
      // browser shows its own offline page, which is the honest outcome.
      const cached = await caches.match(request);
      if (cached) return cached;
      throw networkError;
    }
  })());
});
