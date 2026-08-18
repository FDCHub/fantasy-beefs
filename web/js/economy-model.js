/* ============================================================================
 * FantasyStakes — the league economy configuration read-model
 * WP3B · Rev 4.3 §16
 *
 * What the commissioner economy surface knows, in the same three modes every
 * other Sprint 8 model uses: demo, authoritative, unavailable.
 *
 * EVERY DERIVED FIGURE COMES FROM THE SERVER. `EconomyCalculation` in
 * `economy/league_economy_config.py` owns the arithmetic:
 *
 *     Weekly Minimum Reserve   = Weekly Bet Minimum × Regular-Season Weeks
 *     Yahoo Championship Reserve = Yahoo Championship Contribution
 *     (RC2 adds a second, independent FantasyStakes Championship Contribution;
 *      the full three-part total is served by /championship/results.allocation)
 *     Season-Opening Allocation = the two above, per player
 *     League allocation total  = Season-Opening Allocation × active teams
 *
 * THAT FORMULA IS REPRODUCED IN THIS COMMENT AND NOWHERE IN THIS CODE. Rev 4.3
 * §16.2 and §28: the frontend renders authoritative values and must not
 * reimplement the economic formula. There is no multiplication anywhere in this
 * module — a reader can check that claim by searching it for `*`, and the
 * certification suite does exactly that.
 *
 * A MISSING DERIVED VALUE IS REPORTED AS MISSING. The route returns `null` for
 * the derived figures when the season's week boundaries are not yet derivable,
 * and a league in that state cannot activate. Substituting a plausible number
 * would show a commissioner an allocation the server would not issue.
 * ========================================================================== */

import { championshipAllocation } from './settings-model.js';

export const ECONOMY_MODE_DEMO = 'demo';
export const ECONOMY_MODE_AUTHORITATIVE = 'authoritative';
export const ECONOMY_MODE_UNAVAILABLE = 'unavailable';

/**
 * The three editable inputs — Rev 4.3 §16.1.
 *
 * The ranges and defaults are the SERVER's, restated here only so the form can
 * set an `min`/`max` attribute and label a field before any read has landed.
 * They are presentation hints: nothing is clamped to them, the server validates
 * every submission, and `economy/league_economy_config.py` remains the only
 * place a bound is enforced.
 */
export const ECONOMY_INPUTS = Object.freeze([
  Object.freeze({
    key: 'weeklyBetMinimumCents',
    field: 'weekly_bet_minimum_cents',
    label: 'Weekly Bet Minimum',
    help: 'What each GM must have in play each week.',
    minCents: 100,
    maxCents: 10000,
    defaultCents: 1000,
  }),
  Object.freeze({
    key: 'championshipContributionCents',
    field: 'championship_contribution_cents',
    label: 'Yahoo Championship Contribution',
    help: 'Each GM’s share of the Yahoo Championship pot.',
    minCents: 100,
    maxCents: 100000,
    defaultCents: 8000,
  }),
  Object.freeze({
    key: 'skunkFeeCents',
    field: 'skunk_fee_cents',
    label: 'Skunk Fee',
    help: 'Charged to the week’s widest-margin loser.',
    minCents: 100,
    maxCents: 10000,
    defaultCents: 1000,
  }),
]);

/**
 * The server-derived, read-only figures — Rev 4.3 §16.2.
 *
 * `cents: false` marks a plain count rather than a money figure, so the view
 * knows not to draw a `$` in front of a number of weeks or teams.
 */
export const ECONOMY_DERIVED = Object.freeze([
  Object.freeze({
    field: 'regular_season_week_count',
    label: 'Regular-Season Weeks',
    cents: false,
  }),
  Object.freeze({
    field: 'weekly_minimum_reserve_per_player_cents',
    label: 'Weekly Minimum Reserve',
    cents: true,
  }),
  Object.freeze({
    field: 'championship_reserve_per_player_cents',
    label: 'Yahoo Championship Reserve',
    cents: true,
  }),
  // RC2 — the second, independent championship contribution. Read-only here:
  // it is configured through the championship surface and served by
  // `/championship/config`, so this panel reports it and never derives it.
  Object.freeze({
    field: 'fantasystakes_championship_contribution_cents',
    label: 'FantasyStakes Championship Contribution',
    cents: true,
  }),
  Object.freeze({
    field: 'season_opening_allocation_per_player_cents',
    label: 'Season-Opening Allocation',
    cents: true,
  }),
  Object.freeze({
    field: 'league_opening_allocation_cents',
    label: 'League allocation total',
    cents: true,
  }),
]);

let MODE = ECONOMY_MODE_DEMO;
let SERVED = null;
/** True only when the SERVER says this session holds commission here. */
let CAPABLE = false;

/**
 * Bind the authoritative economy configuration read.
 * @param {object} body an EconomyConfigOut
 */
export function bindEconomy(body) {
  SERVED = body;
  MODE = ECONOMY_MODE_AUTHORITATIVE;
}

/** The read failed or was refused — an ordinary state for a non-commissioner. */
export function markEconomyUnavailable() {
  SERVED = null;
  MODE = ECONOMY_MODE_UNAVAILABLE;
}

/** Return to the unbound default. Used on sign-out and by the suites. */
export function unbindEconomy() {
  SERVED = null;
  MODE = ECONOMY_MODE_DEMO;
  CAPABLE = false;
}

/**
 * Record whether this session may EDIT and ACTIVATE — Rev 4.3 §16, WP3B §17.
 *
 * PRESENTATION ONLY, AND SERVER-SUPPLIED. It decides what is DRAWN; both routes
 * are `require_league_commissioner` and refuse regardless of what was drawn. An
 * ordinary member never reaches this because the read itself is
 * commissioner-scoped — but a capability flag that defaulted to true would draw
 * an editable form for a GM whose every keystroke would 403, which is a worse
 * answer than not offering it.
 *
 * @param {boolean} value
 */
export function setEconomyCapability(value) {
  CAPABLE = value === true;
}

/** @returns {boolean} */
export function economyCapability() {
  return CAPABLE;
}

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function economyMode() {
  return MODE;
}

/** The served body, when bound. @returns {object|null} */
export function servedEconomy() {
  return SERVED;
}

/**
 * Whether this season's economy is frozen — the SERVER's own lifecycle state.
 *
 * NOT INFERRED FROM A DATE, A WEEK NUMBER OR THE PRESENCE OF AN ALLOCATION.
 * `frozen` is stamped by `freeze_economy_config` inside the same transaction
 * that issues the allocation, and it is the only thing that decides whether the
 * inputs are editable (Rev 4.3 §16.4).
 *
 * @returns {boolean}
 */
export function isFrozen() {
  if (MODE !== ECONOMY_MODE_AUTHORITATIVE || !SERVED) return false;
  return SERVED.frozen === true;
}

/**
 * Whether the inputs may be edited right now.
 *
 * Both halves are required: the season must not be frozen AND this session must
 * hold commission. Rev 4.3 §16.4 and WP3B §17.
 *
 * @returns {boolean}
 */
export function isEditable() {
  return economyCapability() && !isFrozen()
    && MODE === ECONOMY_MODE_AUTHORITATIVE;
}

/**
 * Whether activation can be offered.
 *
 * A league whose derived allocation is unknown CANNOT activate — the server
 * would refuse, and offering the button would be offering a certain refusal.
 * Rev 4.3 §16.4 wants the commissioner to review the derived values before
 * confirming, which presupposes there are derived values to review.
 *
 * @returns {boolean}
 */
export function canActivate() {
  return isEditable() && perPlayerAllocationCents() !== null;
}

/**
 * The three current input values, in exact cents, for the form to render.
 *
 * @returns {{weeklyBetMinimumCents: number|null,
 *            championshipContributionCents: number|null,
 *            skunkFeeCents: number|null}}
 */
export function currentInputs() {
  const out = {};
  for (const input of ECONOMY_INPUTS) {
    const value = SERVED ? SERVED[input.field] : null;
    out[input.key] = typeof value === 'number' ? value : null;
  }
  return out;
}

/**
 * The PRIMARY allocation figure — Season-Opening Allocation per player.
 *
 * @returns {number|null} exact integer cents, or null when not derivable
 */
export function perPlayerAllocationCents() {
  if (MODE !== ECONOMY_MODE_AUTHORITATIVE || !SERVED) return null;
  const value = SERVED.season_opening_allocation_per_player_cents;
  return typeof value === 'number' ? value : null;
}

/**
 * The SECONDARY allocation figure — the whole league's total.
 *
 * Rev 4.3 §16.3 and OR-5: shown, and shown as informational context beneath the
 * per-player figure. It must never imply that FantasyStakes collects money, so
 * the view labels it as a total and nothing else.
 *
 * @returns {{cents: number, teams: number}|null}
 */
export function leagueAllocation() {
  if (MODE !== ECONOMY_MODE_AUTHORITATIVE || !SERVED) return null;
  const cents = SERVED.league_opening_allocation_cents;
  const teams = SERVED.active_team_count;
  if (typeof cents !== 'number' || typeof teams !== 'number') return null;
  return { cents, teams };
}

/**
 * The two RC2 rows the `/settings` economy payload cannot carry.
 *
 * WHY THEY COME FROM SOMEWHERE ELSE. `/settings` serves the CERTIFIED base
 * economy: its `season_opening_allocation_per_player_cents` is Weekly Play
 * Reserve + Yahoo Championship Contribution, and it has no field at all for the
 * FantasyStakes Championship Contribution, which RC2 configures and freezes in
 * its own activation stage. Redefining the served base field to mean the new
 * total would change a certified value to fix a presentation problem. So these
 * two rows read the authoritative championship allocation — the same single
 * server read `/championship/results` returns and League Settings already binds
 * — and every other derived row is left entirely alone.
 *
 * NOTHING IS COMPUTED HERE. Both values are served figures; the total's
 * arithmetic happens once, on the server, in `_season_opening_allocation`.
 */
const ALLOCATION_SOURCED = Object.freeze({
  fantasystakes_championship_contribution_cents:
    'fantasystakes_championship_contribution_cents',
  season_opening_allocation_per_player_cents:
    'season_opening_allocation_cents',
});

/**
 * One derived row's served value, or null when the server did not derive it.
 *
 * @param {{field: string}} spec
 * @returns {number|null}
 */
export function derivedValue(spec) {
  const sourced = ALLOCATION_SOURCED[spec.field];
  if (sourced) {
    const allocation = championshipAllocation();
    const served = allocation ? allocation[sourced] : null;
    // Falls through to the certified base figure rather than drawing a dash:
    // before the championship read lands, the base allocation is still the
    // true answer for the stage the league is actually in.
    if (typeof served === 'number') return served;
  }
  if (MODE !== ECONOMY_MODE_AUTHORITATIVE || !SERVED) return null;
  const value = SERVED[spec.field];
  return typeof value === 'number' ? value : null;
}
