/* ============================================================================
 * FantasyStakes — League settings read-model
 * Sprint 8 Package 4B-3
 *
 * The four governed settings rows, from whichever source is bound, in the same
 * three modes the accounting models use:
 *
 *   demo           the POR's illustrative constants — component suites and
 *                  isolated review;
 *   authoritative  bound to GET /league/{id}/settings;
 *   unavailable    production, but the read failed or was refused.
 *
 * WHY UNAVAILABLE MATTERS HERE TOO. These rows carry money — a buy-in, a
 * weekly minimum, a Pool entry. A signed-in GM whose settings read failed must
 * not be shown the prototype's figures as though they were their league's
 * rules, for exactly the reason the Ledger must not show prototype money.
 *
 * ONE ROW IS MUTABLE, AND THE SERVER SAYS WHICH. The B2 ruling made Standard
 * Pool Bet the only settings mutation in MVP. `editable` is not decided here:
 * the settings response carries it per row, and the server refuses a write to
 * anything else because no command exists for it. This module reports what it
 * was told; it does not encode the ruling in JavaScript.
 * ========================================================================== */

import { formatCredits } from './credits.js';
import {
  CHAMPIONSHIP_SPLIT, ECONOMY_STOP, POOL_ENTRY, SETTINGS, SKUNK,
} from './data/rules-data.js';

export const SETTINGS_MODE_DEMO = 'demo';
export const SETTINGS_MODE_AUTHORITATIVE = 'authoritative';
export const SETTINGS_MODE_UNAVAILABLE = 'unavailable';

let MODE = SETTINGS_MODE_DEMO;
let SERVED = null;

/**
 * Bind the authoritative settings read.
 *
 * @param {object} body a LeagueSettingsOut from GET /league/{id}/settings
 */
export function bindSettings(body) {
  SERVED = body;
  MODE = SETTINGS_MODE_AUTHORITATIVE;
}

/** Enter production UNAVAILABLE mode — read failed or refused. */
export function markSettingsUnavailable() {
  SERVED = null;
  MODE = SETTINGS_MODE_UNAVAILABLE;
}

/** Restore the illustrative source. Used on sign-out and by the suites. */
export function unbindSettings() {
  SERVED = null;
  MODE = SETTINGS_MODE_DEMO;
}

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function settingsMode() {
  return MODE;
}

/** The served body, when bound. @returns {object|null} */
export function servedSettings() {
  return SERVED;
}

/**
 * The four rows, in the locked Rev 4.2 order.
 *
 * ORDER AND LABELS ARE THE POR'S and are not derived from the response — a
 * server that returned its keys in a different order must not reorder the
 * page. Only the VALUES and the editable flag come from the read.
 *
 * @returns {Array<object>} rows in `rules.js` settingRow shape
 */
export function settingsRows() {
  if (MODE !== SETTINGS_MODE_AUTHORITATIVE) return SETTINGS;

  const s = SERVED;
  const stop = s.economy_stop;
  const pool = s.pool_entry;

  return Object.freeze([
    // WP3C — SEASON-OPENING ALLOCATION, not "Economy Stop" (Rev 4.3 §15, §22).
    //
    // THREE STALE THINGS WENT. The label named the retired five-stop model; the
    // detail asserted "fourteen weeks", which is wrong for any league that does
    // not play fourteen; and both implied a fixed ladder the configurable
    // economy replaced. Every figure below is the SERVER's own — a configured
    // league reports its own derived terms and an unconfigured one reports the
    // historical fixed stop, and this surface cannot tell the difference
    // because it does not do the arithmetic.
    //
    // THE WEEK COUNT IS DESCRIBED, NOT STATED. It would be `min_reserve ÷
    // weekly_min`, and Rev 4.3 §16.2 forbids reimplementing the economic
    // formula in the browser to explain it. The components are shown; the
    // multiplication that relates them is the server's.
    Object.freeze({
      id: 'economy-stop',
      label: 'Season-Opening Allocation',
      value: formatCredits(stop.buyin_cents),
      exactCents: stop.buyin_cents,
      editable: stop.editable,
      detail:
        `Each GM is advanced ${formatCredits(stop.buyin_cents)} at season open: `
        + `${formatCredits(stop.min_reserve_cents)} as the Weekly Minimum `
        + `reserve — your league's ${formatCredits(stop.weekly_min_cents)} Weekly `
        + 'Bet Minimum across its regular-season weeks — plus '
        + `${formatCredits(stop.reserve_cents)} as the Championship Pot `
        + 'Contribution. The commissioner sets those two before the season and '
        + 'they lock at activation, because changing them would re-price '
        + 'obligations GMs have already funded. The Skunk Fee is contingent and '
        + 'is not part of this allocation.',
      source: 'League economy configuration',
    }),
    Object.freeze({
      id: 'pool-bet',
      label: 'Standard Pool Bet',
      value: formatCredits(pool.cents),
      exactCents: pool.cents,
      editable: pool.editable,
      frozen: pool.frozen,
      minCents: pool.min_cents,
      maxCents: pool.max_cents,
      detail:
        'The weekly entry for each of the week’s four Pools, set by the '
        + `commissioner and bounded to ${formatCredits(pool.min_cents)}–`
        + `${formatCredits(pool.max_cents)}. `
        + (pool.frozen
          ? 'Frozen for this season — the first Pool week has been collected.'
          : 'It freezes for the season once the first week is collected.'),
      source: 'League Pool settings',
    }),
    // WP3C — THE "max" IS GONE (Rev 4.3 §19, WP3C §24).
    //
    // The row read `$10 weekly · $140 max`, and both halves misdescribed the
    // rule. "Weekly" implied every GM pays every week; in fact exactly ONE GM
    // pays per completed regular-season week — the largest margin-of-defeat
    // loser. And the "max" was a CONCEPTUAL ceiling the backend computes for
    // reporting and NOTHING ENFORCES, presented as though it capped a GM's
    // exposure. §24 says not to show it, so it is not shown.
    Object.freeze({
      id: 'skunk-fee',
      label: 'Skunk Fee',
      value: formatCredits(s.skunk.weekly_cents),
      exactCents: s.skunk.weekly_cents,
      editable: s.skunk.editable,
      detail:
        `${formatCredits(s.skunk.weekly_cents)} per completed regular-season `
        + 'week, charged to the team that lost its Yahoo matchup by the largest '
        + 'margin. Tied largest losers split one fee. There is no postseason '
        + 'Skunk and no enforced season maximum. Fixed for the season.',
      source: 'Skunk rules',
    }),
    Object.freeze({
      id: 'championship-split',
      label: 'Championship split',
      value: s.championship_split.split.join(' / '),
      editable: s.championship_split.editable,
      detail:
        'How the championship pot divides: 60 to the champion, 30 to the '
        + 'runner-up, 10 to the official third place. Yahoo is authoritative for '
        + 'all three; there is no commissioner override and no standings-based '
        + 'fallback. Fixed for the season — changing it would re-price a pot GMs '
        + 'have already funded.',
      source: 'Championship rules',
    }),
  ]);
}

/**
 * Whether the acting session may edit the Standard Pool Bet.
 *
 * PRESENTATION ONLY. The server refuses a write from anyone without league
 * commissioner authority, and refuses one after the freeze, whatever this
 * returns. It exists so a control can be drawn disabled rather than offered
 * and then refused.
 *
 * @param {boolean} isCommissioner from /auth/me capabilities
 * @returns {boolean}
 */
export function poolEntryEditable(isCommissioner) {
  if (MODE !== SETTINGS_MODE_AUTHORITATIVE) return false;
  return Boolean(isCommissioner) && SERVED.pool_entry.editable === true;
}
