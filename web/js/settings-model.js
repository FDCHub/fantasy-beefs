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
    Object.freeze({
      id: 'economy-stop',
      label: 'Economy Stop',
      value: `${formatCredits(stop.weekly_min_cents)} / week · `
        + `${formatCredits(stop.buyin_cents)} season`,
      exactCents: stop.buyin_cents,
      editable: stop.editable,
      detail:
        `${formatCredits(stop.weekly_min_cents)} released each week for fourteen `
        + `weeks (${formatCredits(stop.min_reserve_cents)}), plus a `
        + `${formatCredits(stop.reserve_cents)} championship reserve, advanced as `
        + `${formatCredits(stop.buyin_cents)} at season open. Fixed for the `
        + 'season: changing it would re-price obligations GMs have already funded.',
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
    Object.freeze({
      id: 'skunk-fee',
      label: 'Skunk Fee',
      value: `${formatCredits(s.skunk.weekly_cents)} weekly · `
        + `${formatCredits(s.skunk.season_maximum_cents)} max`,
      exactCents: s.skunk.weekly_cents,
      editable: s.skunk.editable,
      detail:
        `${formatCredits(s.skunk.weekly_cents)} a week, regular season only, `
        + `accumulating to at most ${formatCredits(s.skunk.season_maximum_cents)} `
        + 'across a season. Fixed for the season.',
      source: 'Skunk rules',
    }),
    Object.freeze({
      id: 'championship-split',
      label: 'Championship split',
      value: s.championship_split.split.join(' / '),
      editable: s.championship_split.editable,
      detail:
        'How the championship pot divides by place. Fixed for the season — '
        + 'changing it would re-price a pot GMs have already funded.',
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
