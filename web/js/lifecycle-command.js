/* ============================================================================
 * FantasyStakes — the commissioner lifecycle commands
 * WP4
 *
 * SIX COMMANDS AND ONE READ, ALL ALREADY GOVERNED. Nothing in this module
 * decides anything: each function names a route that already exists, already
 * resolves league commissioner authority for itself, and already owns whatever
 * rule it enforces. This is the client's half of the conversation and nothing
 * more.
 *
 * IT REACHES THE NETWORK THROUGH `apiFetch` AND NOWHERE ELSE, like every other
 * module in the application. The session module stays the single door, so the
 * session cookie and the CSRF echo are attached in one place for these six
 * unsafe requests exactly as they are for every other.
 *
 * THE REASON CODE IS THE PRODUCT COPY'S ONLY INPUT, and the translation lives
 * here rather than in the surface. `explainRefusal` maps a governed code to a
 * sentence a commissioner can act on; the raw code is never drawn. That is a
 * translation, NOT a second rulebook — the server has already decided, and this
 * only says what its decision means in the league's own language.
 *
 * NO CLIENT-SIDE PRE-CHECK STANDS IN FRONT OF A COMMAND. A control may be drawn
 * disabled from the lifecycle READ, which is the server's own answer; but
 * nothing here re-derives a prerequisite and refuses on its own authority. A
 * second, weaker copy of a governed rule in the browser is how two definitions
 * of "ready" drift apart, and the money rules are not the ones to learn that on.
 * ========================================================================== */

import { ApiError, apiFetch } from './session.js';

/** A refusal the server explained, carrying its governed reason code. */
export class LifecycleCommandError extends Error {
  constructor(status, reasonCode, message, detail) {
    super(message);
    this.name = 'LifecycleCommandError';
    this.status = status;
    this.reasonCode = reasonCode;
    this.detail = detail;
  }
}

/**
 * Run one lifecycle call, turning an ApiError into a governed refusal.
 *
 * The server answers a refusal as `{reason_code, message}` on every one of
 * these routes, so the shape is unwrapped once here instead of six times.
 *
 * @param {string} path
 * @param {{method?: string}} [options]
 * @returns {Promise<any>}
 */
async function command(path, options = {}) {
  try {
    return await apiFetch(path, { method: options.method || 'POST' });
  } catch (error) {
    if (error instanceof ApiError) {
      const detail = error.detail;
      const structured = detail && typeof detail === 'object';
      throw new LifecycleCommandError(
        error.status,
        structured ? detail.reason_code : null,
        structured ? detail.message : String(detail || error.message),
        structured ? detail : null,
      );
    }
    throw error;
  }
}

/* ── The read ───────────────────────────────────────────────────────────── */

/**
 * This league's lifecycle state — pool support, the week, season readiness.
 *
 * @param {number} leagueId
 * @returns {Promise<object>} a LeagueLifecycleOut
 */
export function readLifecycle(leagueId) {
  return command(`/league/${leagueId}/lifecycle`, { method: 'GET' });
}

/* ── League setup ───────────────────────────────────────────────────────── */

/**
 * Measure whether the provider's data supports this league's Pool slate.
 *
 * The week is a REQUIRED query parameter of the governed route: the measurement
 * reads what one week's payload actually carried. It is passed through from the
 * league's own current week and never defaulted here — a measurement of the
 * wrong week is a confident answer about the wrong thing.
 *
 * @param {number} leagueId
 * @param {number} week
 * @returns {Promise<object>} a PoolActivationOut
 */
export function activatePoolSupport(leagueId, week) {
  return command(`/league/${leagueId}/pool/activate?week=${week}`);
}

/* ── The week ───────────────────────────────────────────────────────────── */

/** @returns {Promise<object>} a WeekOpenOut */
export function openWeek(leagueId, week) {
  return command(`/league/${leagueId}/week/${week}/open`);
}

/** @returns {Promise<object>} a PoolCollectionOut */
export function collectPools(leagueId, week) {
  return command(`/league/${leagueId}/pool/collect/${week}`);
}

/** @returns {Promise<object>} a PoolWeekSettlementOut */
export function settlePools(leagueId, week) {
  return command(`/league/${leagueId}/pool/settle/${week}`);
}

/** @returns {Promise<object>} a WeekCloseOut */
export function closeWeek(leagueId, week) {
  return command(`/league/${leagueId}/week/${week}/close`);
}

/* ── The season ─────────────────────────────────────────────────────────── */

/** @returns {Promise<object>} a SeasonCloseOut */
export function closeSeason(leagueId) {
  return command(`/league/${leagueId}/season/close`);
}

/* ── Refusals, in the league's language ─────────────────────────────────── */

/**
 * Governed reason code → the sentence a commissioner is shown.
 *
 * KEYED IN LOWER CASE because the codes arrive in two conventions and both are
 * the engines' own: the season-close orchestrator names its steps
 * `versus_terminal`, `pool_settled`, … while the funding, weekly-minimum and
 * finality engines shout `ALREADY_COLLECTED`, `RESULTS_NOT_READY`. Neither is
 * wrong and neither is this surface's to rename, so the lookup folds case and
 * the vocabularies stay where they are.
 *
 * EVERY SENTENCE NAMES WHAT TO FINISH. `exc.step` exists precisely so an
 * operator is told what is outstanding rather than that something was refused,
 * and a translation that lost that would be worse than the raw code.
 */
const REFUSALS = Object.freeze({
  /* ── Results finality ─────────────────────────────────────────────────── */
  // NOT AN ERROR, AND IT MUST NOT READ AS ONE. The week's games are simply not
  // final yet. The action is correct, the timing is early, and it will succeed
  // unchanged once the scores are in.
  results_not_ready:
    'Results are not final yet. Yahoo has not finished every game of this '
    + 'week, so the Pools cannot be settled. Nothing has changed — try again '
    + 'once the week’s scores are final.',

  /* ── Season close prerequisites ───────────────────────────────────────── */
  versus_terminal:
    'Some head-to-head wagers are still open. Every wager has to be settled, '
    + 'declined or expired before the season can close.',
  pool_settled:
    'Some of this season’s Pools have not been settled. Settle every week’s '
    + 'Pools before closing the season.',
  escrow_resolved:
    'Credits are still held against unresolved wagers. Nothing can close while '
    + 'money is committed to a wager that has not finished.',
  weekly_minimum_expiry:
    'At least one week has not been closed. Close every week of the season '
    + 'before closing the season itself.',
  skunk_assessed:
    'Weekly Skunk charges have not been assessed for every week of the season.',
  pool_rollover:
    'A Pool pot is still carried forward to a week that was never played out. '
    + 'It has to be resolved before the season can close.',
  pool_zero:
    'The league’s Pool account still holds Credits. Every week’s Pool money '
    + 'has to reach its destination before the season can close.',
  provider_conflict:
    'There are unresolved scoring conflicts from Yahoo. They have to be '
    + 'settled before the season can close.',
  conservation:
    'The league’s accounts do not reconcile yet. Season close is held until '
    + 'they do — closing over a discrepancy would bake it in.',
  trial_balance:
    'The league’s accounts do not reconcile yet. Season close is held until '
    + 'they do — closing over a discrepancy would bake it in.',
  season_close_conflict:
    'Another season close is already running for this league. Wait for it to '
    + 'finish rather than starting a second one.',

  /* ── Pool collection ──────────────────────────────────────────────────── */
  already_collected:
    'This week’s Pools have already been opened. Every GM was charged once, '
    + 'and repeating it would not charge them again.',
  prior_week_unsettled:
    'An earlier week’s Pools are still unsettled. Settle them before opening '
    + 'this week’s, so last week’s money is not still sitting in the pot.',
  entry_frozen:
    'The Standard Pool Bet is frozen for this season — the first Pool week has '
    + 'been collected and the entry is fixed from that point.',
  entry_out_of_bounds:
    'The Standard Pool Bet is outside the amount the league rules allow.',
  no_teams:
    'This league has no teams to charge.',
  no_wallet:
    'At least one GM has no wallet, so the weekly entry cannot be collected '
    + 'from everyone. Nothing was charged.',
  pool_funding_refused:
    'This week’s Pools could not be opened. Nothing was charged.',
  pool_settlement_refused:
    'This week’s Pools could not be settled. No money moved.',

  /* ── The weekly minimum ───────────────────────────────────────────────── */
  not_applicable_week:
    'This is not a regular-season week for the league, so there is no weekly '
    + 'allowance to release.',
  insufficient_reserve:
    'A GM’s season allowance does not cover another weekly release. Nothing '
    + 'was released, rather than over-spending the season’s allocation.',

  /* ── The provider binding ─────────────────────────────────────────────── */
  no_provider_identity:
    'This league is not connected to Yahoo yet, so its data cannot be read.',
  provider_unavailable:
    'Yahoo could not be reached just now. Nothing has changed — try again in '
    + 'a moment.',

  /* ── Identity ─────────────────────────────────────────────────────────── */
  league_not_found:
    'That league could not be found.',
  not_a_league_member:
    'Your session has no access to this league.',
});

/**
 * Whether a refusal is the ordinary "not yet" rather than a problem.
 *
 * SURFACED SEPARATELY BECAUSE IT IS A DIFFERENT KIND OF ANSWER. A week whose
 * results are not final is the expected state for most of the week, and drawing
 * it in the same red as a genuine refusal would train a commissioner to ignore
 * both.
 *
 * @param {LifecycleCommandError} error
 * @returns {boolean}
 */
export function isWaitingState(error) {
  return normalise(error && error.reasonCode) === 'results_not_ready';
}

/** @param {string|null|undefined} code @returns {string} */
function normalise(code) {
  return String(code == null ? '' : code).toLowerCase();
}

/**
 * Turn a refusal into a sentence a commissioner can act on.
 *
 * THE RAW CODE IS NEVER RETURNED. An unmapped code falls back to the server's
 * own prose, and failing that to a plain sentence — a commissioner reading
 * `weekly_minimum_expiry` on their settings page has been handed the engine's
 * private vocabulary, which tells them nothing and looks like a fault.
 *
 * @param {LifecycleCommandError} error
 * @returns {string}
 */
export function explainRefusal(error) {
  if (!error) return 'The action was refused.';

  const mapped = REFUSALS[normalise(error.reasonCode)];
  if (mapped) return mapped;

  if (error.status === 403) {
    return 'Your session does not hold commissioner authority for this league.';
  }
  if (error.status === 401) {
    return 'Your session has ended. Sign in again to continue.';
  }
  // The server's own prose, when it wrote any. It is written for an operator
  // and is better than a generic line — but only when it is prose: a bare
  // reason code echoed back would defeat the whole point of this function.
  const message = String(error.message || '');
  if (message && !/^[A-Z0-9_]+$/.test(message)) return message;

  return 'The action was refused. Nothing has changed.';
}

/**
 * The blocking sentence for a season close that is not yet possible.
 *
 * Same table, reached from the lifecycle READ rather than from a refusal — the
 * button explains why it is unavailable BEFORE it is pressed, using the
 * server's own answer about which prerequisite is outstanding.
 *
 * @param {string|null} reasonCode
 * @returns {string|null}
 */
export function explainPrerequisite(reasonCode) {
  if (!reasonCode) return null;
  return REFUSALS[normalise(reasonCode)]
    || 'The season is not ready to close yet.';
}

/** Exposed for the suites: every governed code this surface can translate. */
export const TRANSLATED_REASON_CODES = Object.freeze(Object.keys(REFUSALS));
