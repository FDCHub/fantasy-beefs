/* ============================================================================
 * FantasyStakes — authenticated client seam
 * Sprint 8 Package 1
 *
 * THE ONLY MODULE IN THE APPLICATION THAT MAKES A NETWORK REQUEST. That is an
 * invariant the certification suite enforces by scanning every other module for
 * `fetch(`, not a convention. One door means one place where credentials are
 * attached, one place where a CSRF token is echoed, and one place where a 401
 * is turned into "you are signed out" — and no illustrative surface can reach
 * the server by some other path that forgot a step.
 *
 * NO TOKEN LIVES HERE, OR ANYWHERE ELSE IN THE BROWSER. Sprint 8's ruling is
 * that the browser authenticates with a Secure, HttpOnly, SameSite=Lax cookie.
 * The page cannot read that cookie and this module never tries. There is no
 * localStorage, no sessionStorage, and no cookie WRITE anywhere in the app —
 * the credential is issued, held and expired by the server.
 *
 * WHAT IS READ FROM document.cookie, AND WHY THAT IS NOT A CONTRADICTION. The
 * server sets a SECOND, deliberately readable cookie holding a CSRF token, and
 * an unsafe request must echo it in a header. That token is not a credential:
 * on its own it authenticates nothing and grants nothing. It is one half of a
 * pair whose other half is a claim inside the signed session token the page
 * cannot see, which is what makes it unforgeable by anything that can merely
 * write cookies. Reading it is the mechanism working, not a leak.
 *
 * IDENTITY IS THE SERVER'S ANSWER, HELD IN MEMORY ONLY. `/auth/me` is
 * authoritative. This module caches the reply for the lifetime of the page so
 * every surface reads one consistent answer, and drops it on 401. It does not
 * persist identity, because a persisted identity is a claim about authority
 * that outlives the server's willingness to honour it.
 *
 * CAPABILITY IS PRESENTATION ONLY. `can()` decides what to DRAW. It decides
 * nothing about what may happen: every route re-derives authority from the
 * credential before it writes, so a client that lied to itself gets a 403.
 * ========================================================================== */

/** The readable half of the CSRF pair. Set by the server; never written here. */
const CSRF_COOKIE = 'fs_csrf';

/** The header the server checks against the claim inside the session token. */
const CSRF_HEADER = 'X-FS-CSRF';

/** Methods that may change state, and therefore need the CSRF token. */
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * The server's last answer about who is acting, or null when signed out.
 * Module-scoped and in-memory: it dies with the page, as it should.
 * @type {object|null}
 */
let identity = null;

/** Listeners notified whenever identity changes, including on an expiry 401. */
const listeners = new Set();

function setIdentity(next) {
  identity = next;
  listeners.forEach((fn) => fn(identity));
}

/**
 * Subscribe to identity changes.
 *
 * @param {(identity: object|null) => void} fn
 * @returns {() => void} unsubscribe
 */
export function onIdentityChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/* ── CSRF ───────────────────────────────────────────────────────────────── */

/**
 * The current CSRF token, or null.
 *
 * Parsed rather than regexed out: a cookie value can legitimately contain `=`,
 * so splitting on the FIRST separator is the only correct read.
 *
 * @returns {string|null}
 */
function csrfToken() {
  if (typeof document === 'undefined' || !document.cookie) return null;

  for (const part of document.cookie.split(';')) {
    const raw = part.trim();
    const eq = raw.indexOf('=');
    if (eq === -1) continue;
    if (raw.slice(0, eq) === CSRF_COOKIE) {
      return decodeURIComponent(raw.slice(eq + 1)) || null;
    }
  }
  return null;
}

/* ── The one door ───────────────────────────────────────────────────────── */

/** Thrown for any non-2xx reply, carrying the status so a caller can branch. */
export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `request failed (${status})`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Call the API as the signed-in GM.
 *
 * `credentials: 'same-origin'` is explicit rather than relied upon. The
 * default varies by browser generation, and a default that silently dropped
 * the cookie would present as "mysteriously signed out" rather than as an
 * error — the kind of bug that gets worked around instead of fixed.
 *
 * @param {string} path absolute API path, e.g. '/auth/me'
 * @param {{method?: string, body?: any, headers?: object}} [options]
 * @returns {Promise<any>} parsed JSON, or null for 204
 */
export async function apiFetch(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});

  if (UNSAFE_METHODS.has(method)) {
    const token = csrfToken();
    // Sent when present. Its ABSENCE is not worked around: if the server wants
    // a token and there is none, the right outcome is the server's 403, not a
    // client-side guess at what it would have accepted.
    if (token) headers.set(CSRF_HEADER, token);
  }

  let body;
  if (options.body !== undefined && options.body !== null) {
    body = typeof options.body === 'string' ? options.body : JSON.stringify(options.body);
    if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, {
    method,
    headers,
    body,
    credentials: 'same-origin',
    redirect: 'error',
  });

  if (response.status === 401) {
    // The session ended — expired, revoked, or never established. Dropping the
    // cached identity here is what makes every surface agree, immediately,
    // without each one having to notice for itself.
    setIdentity(null);
    throw new ApiError(401, 'Not authenticated');
  }

  if (response.status === 204) return null;

  let payload = null;
  const type = response.headers.get('Content-Type') || '';
  if (type.includes('application/json')) {
    payload = await response.json().catch(() => null);
  }

  if (!response.ok) {
    throw new ApiError(response.status, payload && payload.detail);
  }
  return payload;
}

/* ── Session lifecycle ──────────────────────────────────────────────────── */

/**
 * Ask the server who is acting. The authoritative read.
 *
 * @returns {Promise<object|null>} identity, or null when signed out
 */
export async function refreshIdentity() {
  try {
    const me = await apiFetch('/auth/me');
    setIdentity(me);
    return me;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

/**
 * Sign in. On success the server sets the session pair; nothing is stored here.
 *
 * @param {string} email
 * @param {string} password
 * @returns {Promise<object>} identity
 */
export async function login(email, password) {
  const me = await apiFetch('/auth/session', {
    method: 'POST',
    body: { email, password },
  });
  setIdentity(me);
  return me;
}

/**
 * Sign out, clearing the session cookies server-side.
 *
 * Local identity is dropped in `finally`. If the call fails because the
 * session had already expired, the GM still asked to be signed out and the UI
 * must honour that — leaving them looking signed in would be worse than the
 * error.
 *
 * @returns {Promise<void>}
 */
export async function logout() {
  try {
    await apiFetch('/auth/session', { method: 'DELETE' });
  } finally {
    setIdentity(null);
  }
}

/* ── Reads ──────────────────────────────────────────────────────────────── */

/** The cached identity, or null. @returns {object|null} */
export function currentIdentity() {
  return identity;
}

/** @returns {boolean} whether a GM is signed in */
export function isAuthenticated() {
  return identity !== null;
}

/**
 * A server-derived capability flag, for PRESENTATION.
 *
 * Defaults to false when signed out or when the server did not name the
 * capability — an unknown capability is one the server did not grant.
 *
 * @param {string} name key of the capabilities object from /auth/me
 * @returns {boolean}
 */
export function can(name) {
  if (!identity || !identity.capabilities) return false;
  return identity.capabilities[name] === true;
}

/**
 * Whether the acting user holds commissioner authority for a specific league.
 *
 * The global `is_commissioner` role is NOT the same question, and conflating
 * them is the exact confusion S8-P2 exists to remove from the server. The
 * client must not reintroduce it: this reads the league list the server sent.
 *
 * @param {number} leagueId
 * @returns {boolean}
 */
export function isCommissionerOf(leagueId) {
  if (!identity || !identity.capabilities) return false;
  const ids = identity.capabilities.commissioner_league_ids;
  return Array.isArray(ids) && ids.includes(leagueId);
}