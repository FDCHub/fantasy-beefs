/* ============================================================================
 * FantasyStakes — commissioner lifecycle read-model
 * WP4
 *
 * The state behind the lifecycle controls, in the same three modes every other
 * Sprint 8 model uses:
 *
 *   demo           nothing bound — component review and the signed-out shell;
 *   authoritative  bound to GET /league/{id}/lifecycle;
 *   unavailable    production, but the read failed or was refused.
 *
 * THERE IS NO ILLUSTRATIVE LIFECYCLE, AND THAT IS THE POINT. The other models
 * fall back to the POR's fixture when nothing is bound, because a prototype
 * league's figures are useful for reviewing a layout. A lifecycle has no such
 * harmless version: an invented "Ready" would tell a commissioner their league
 * can run Pools it cannot, and an invented "week open" would hide the action
 * that has not been taken. So DEMO here means "no state and no controls", not
 * "the fixture's state".
 *
 * EVERYTHING IS KEYED TO ONE LEAGUE, AND THE KEY IS CHECKED, NOT ASSUMED.
 * `BOUND_LEAGUE_ID` travels with the served body and with every action result.
 * `applyLeague()` is the ONLY way the active league changes, and it drops both
 * the moment the id differs — so a success banner from league A cannot be read
 * under league B's heading, and a stale readiness answer cannot leave a control
 * enabled for a league it was never measured against. Clearing on switch is not
 * a courtesy: the two leagues' answers are not interchangeable, and showing one
 * where the other belongs is showing a false statement about the league on
 * screen.
 * ========================================================================== */

export const LIFECYCLE_MODE_DEMO = 'demo';
export const LIFECYCLE_MODE_AUTHORITATIVE = 'authoritative';
export const LIFECYCLE_MODE_UNAVAILABLE = 'unavailable';

/** The three-valued Pool support answer, exactly as the server names it. */
export const POOL_SUPPORT_NOT_MEASURED = 'not_measured';
export const POOL_SUPPORT_INSUFFICIENT = 'insufficient';
export const POOL_SUPPORT_READY = 'ready';

/** The lifecycle actions, in the order a season runs them. */
export const LIFECYCLE_ACTIONS = Object.freeze([
  'pool-support', 'week-open', 'pool-collect', 'pool-settle', 'week-close',
  'season-close',
]);

let MODE = LIFECYCLE_MODE_DEMO;
let SERVED = null;
let BOUND_LEAGUE_ID = null;

/**
 * The outcome of the last attempt at each action, for THIS league only.
 * `{[action]: {status: 'success'|'refused'|'waiting', message: string}}`
 * @type {object}
 */
let RESULTS = {};

/** Actions with a request in flight. Membership is what disables a control. */
let IN_FLIGHT = new Set();

/* ── Binding ────────────────────────────────────────────────────────────── */

/**
 * Bind the authoritative lifecycle read for one league.
 *
 * @param {number} leagueId the league this body describes
 * @param {object} body a LeagueLifecycleOut
 */
export function bindLifecycle(leagueId, body) {
  // A body for a DIFFERENT league than the one currently active is not merged
  // in — it is a late reply to a request made before a switch, and applying it
  // would put the previous league's state back on screen.
  if (BOUND_LEAGUE_ID !== null && leagueId !== BOUND_LEAGUE_ID) return;
  BOUND_LEAGUE_ID = leagueId;
  SERVED = body;
  MODE = LIFECYCLE_MODE_AUTHORITATIVE;
}

/**
 * Enter production UNAVAILABLE — the read failed, or this session was refused.
 *
 * A GM's session is refused here by design, so this is a capability state and
 * not an error. Either way there is no lifecycle state and no control to draw.
 *
 * @param {number|null} [leagueId]
 */
export function markLifecycleUnavailable(leagueId = null) {
  if (leagueId !== null) BOUND_LEAGUE_ID = leagueId;
  SERVED = null;
  MODE = LIFECYCLE_MODE_UNAVAILABLE;
}

/** Return to the unbound default. Used on sign-out and by the suites. */
export function unbindLifecycle() {
  SERVED = null;
  MODE = LIFECYCLE_MODE_DEMO;
  BOUND_LEAGUE_ID = null;
  RESULTS = {};
  IN_FLIGHT = new Set();
}

/**
 * Make `leagueId` the active league, discarding anything from another one.
 *
 * THE ONLY DOOR FOR A LEAGUE CHANGE. Returns true when the league actually
 * changed, so a caller can tell a switch from a refresh without comparing ids
 * itself — two places deciding "did the league change" is one place too many.
 *
 * @param {number|null} leagueId
 * @returns {boolean} whether the active league changed
 */
export function applyLeague(leagueId) {
  if (BOUND_LEAGUE_ID === leagueId) return false;

  BOUND_LEAGUE_ID = leagueId;
  SERVED = null;
  // THE RESULTS GO WITH IT. A "Week opened" success or a governed refusal
  // describes something that happened to the PREVIOUS league; carried across a
  // switch it becomes a claim about this one.
  RESULTS = {};
  // In-flight markers go too. A request still running against the old league
  // must not leave a control disabled here, and its reply is discarded by the
  // league guard in `bindLifecycle` / `recordResult`.
  IN_FLIGHT = new Set();
  MODE = LIFECYCLE_MODE_DEMO;
  return true;
}

/* ── Reads ──────────────────────────────────────────────────────────────── */

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function lifecycleMode() {
  return MODE;
}

/** The league every figure below belongs to. @returns {number|null} */
export function lifecycleLeagueId() {
  return BOUND_LEAGUE_ID;
}

/** The served body, when bound. @returns {object|null} */
export function servedLifecycle() {
  return SERVED;
}

/**
 * Pool support for the active league.
 *
 * Returns null when nothing is bound — the surface draws the unresolved state
 * rather than guessing at a third value.
 *
 * @returns {object|null}
 */
export function poolSupport() {
  if (MODE !== LIFECYCLE_MODE_AUTHORITATIVE || !SERVED) return null;
  return SERVED.pool_support;
}

/** @returns {object|null} */
export function weekLifecycle() {
  if (MODE !== LIFECYCLE_MODE_AUTHORITATIVE || !SERVED) return null;
  return SERVED.week;
}

/** @returns {object|null} */
export function seasonLifecycle() {
  if (MODE !== LIFECYCLE_MODE_AUTHORITATIVE || !SERVED) return null;
  return SERVED.season_close;
}

/* ── Action state ───────────────────────────────────────────────────────── */

/**
 * Claim an action for a request about to be sent.
 *
 * THE DUPLICATE-CLICK GUARD LIVES HERE, NOT IN THE BUTTON. A disabled attribute
 * is presentation and can be raced — two clicks dispatched in the same frame
 * both see the enabled button. This returns false for the second claim, so the
 * second call never leaves the browser, and it is the binder's `if` rather than
 * the DOM that decides.
 *
 * @param {string} action
 * @returns {boolean} true when the caller owns the request
 */
export function claimAction(action) {
  if (IN_FLIGHT.has(action)) return false;
  IN_FLIGHT.add(action);
  return true;
}

/** Release an action's in-flight claim. @param {string} action */
export function releaseAction(action) {
  IN_FLIGHT.delete(action);
}

/** @param {string} action @returns {boolean} */
export function isInFlight(action) {
  return IN_FLIGHT.has(action);
}

/**
 * Record what an action did, for the league it was done to.
 *
 * @param {number|null} leagueId the league the command was sent for
 * @param {string} action
 * @param {{status: string, message: string}} result
 */
export function recordResult(leagueId, action, result) {
  // A reply that arrives after a league switch is DROPPED. It is a true
  // statement about a league that is no longer on screen, which makes it a
  // false one about the league that is.
  if (leagueId !== BOUND_LEAGUE_ID) return;
  RESULTS = { ...RESULTS, [action]: result };
}

/** @param {string} action @returns {object|null} */
export function actionResult(action) {
  return RESULTS[action] || null;
}

/** Every recorded result. @returns {object} */
export function actionResults() {
  return RESULTS;
}

/** Drop every recorded result, leaving the served state alone. */
export function clearResults() {
  RESULTS = {};
}