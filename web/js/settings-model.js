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
  VC_ALLOCATION_DEMO,
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
/**
 * The FULL RC2 Season-Opening Allocation, served by
 * `/championship/results.allocation`.
 *
 * WHY IT IS BOUND SEPARATELY. `/settings` reports the certified BASE stage —
 * Weekly Play Reserve + Yahoo Championship Contribution — and that field is not
 * to be redefined to mean something new. RC2 advances a second, independently
 * configured FantasyStakes Championship Contribution in its own stage, so the
 * total a GM actually owes is the base plus that. The server derives the whole
 * thing; this holds the answer and does no arithmetic.
 */
let ALLOCATION = null;

export function bindChampionshipAllocation(allocation) {
  ALLOCATION = allocation || null;
}

export function championshipAllocation() {
  return ALLOCATION;
}

export function settingsRows() {
  if (MODE !== SETTINGS_MODE_AUTHORITATIVE) return SETTINGS;

  const s = SERVED;
  const stop = s.economy_stop;
  const pool = s.pool_entry;
  const alloc = ALLOCATION;

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
    // RC2 — THREE PARTS WHEN THE CHAMPIONSHIP READ IS AVAILABLE, two when it is
    // not. Every figure is the server's: the Weekly Play Reserve is the
    // commissioner's weekly minimum multiplied by this league's own Yahoo
    // regular-season week count, so a 13-week league reports a different
    // reserve and a different total than a 14-week one. No number below is
    // fixed by FantasyStakes and none is computed here.
    Object.freeze({
      id: 'economy-stop',
      label: 'Season-Opening Allocation',
      value: formatCredits(
        alloc ? alloc.season_opening_allocation_cents : stop.buyin_cents),
      exactCents: (
        alloc ? alloc.season_opening_allocation_cents : stop.buyin_cents),
      editable: stop.editable,
      detail: alloc
        ? `Each GM is advanced ${formatCredits(alloc.season_opening_allocation_cents)} `
          + 'at season open, in three parts. Weekly Play Reserve '
          + `${formatCredits(alloc.weekly_play_reserve_cents)} — your league's `
          + `${formatCredits(alloc.weekly_minimum_cents)} weekly minimum across `
          + `its ${alloc.regular_season_week_count} Yahoo regular-season weeks. `
          + `Yahoo Championship Contribution `
          + `${formatCredits(alloc.yahoo_championship_contribution_cents)}. `
          + 'FantasyStakes Championship Contribution '
          + `${formatCredits(alloc.fantasystakes_championship_contribution_cents)}. `
          + 'The commissioner sets the weekly minimum and both contributions '
          + 'before the season and they lock at activation, because changing '
          + 'them would re-price obligations GMs have already funded. The Skunk '
          + 'Fee is contingent and is not part of this allocation.'
        : `Each GM is advanced ${formatCredits(stop.buyin_cents)} at season open: `
          + `${formatCredits(stop.min_reserve_cents)} as the Weekly Play `
          + `Reserve — your league's ${formatCredits(stop.weekly_min_cents)} weekly `
          + 'minimum across its regular-season weeks — plus '
          + `${formatCredits(stop.reserve_cents)} as the Yahoo Championship `
          + 'Contribution. The FantasyStakes Championship Contribution could not '
          + 'be read, so it is not shown rather than shown wrongly.',
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

/* ── FINAL POR §23 · the VC ALLOCATION table ────────────────────────────────*/

/**
 * §23's table for the bound league, or the illustrative one.
 *
 * IT CARRIES ITS OWN AVAILABILITY, and that is not the same question as
 * `settingsMode()`. A settings read can succeed completely and still return no
 * VC allocation table — a LEGACY season has none, because four of the seven
 * rows describe pots the retired architecture does not have. The server says
 * `available: false` with a named reason and the surface states it, rather than
 * drawing seven blank rows or failing the whole page.
 *
 * @returns {{available: boolean, unavailableReason: string|null,
 *            weeklyMinimumCents: number|null, allocation: Array<object>,
 *            inSeason: Array<object>, seasonRules: Array<object>}}
 */
export function vcAllocation() {
  if (MODE !== SETTINGS_MODE_AUTHORITATIVE) {
    return MODE === SETTINGS_MODE_UNAVAILABLE
      // PRODUCTION, AND THE READ FAILED. The illustrative table is NOT shown
      // here, for the same reason the Ledger does not show prototype money: a
      // signed-in GM must never read another league's economy as their own.
      ? { available: false, unavailableReason: 'SETTINGS_UNAVAILABLE',
          weeklyMinimumCents: null, allocation: [], inSeason: [],
          seasonRules: [] }
      : { available: true,
          unavailableReason: null,
          weeklyMinimumCents: VC_ALLOCATION_DEMO.weeklyMinimumCents,
          allocation: VC_ALLOCATION_DEMO.allocation,
          inSeason: VC_ALLOCATION_DEMO.inSeason,
          seasonRules: VC_ALLOCATION_DEMO.seasonRules };
  }

  const served = SERVED && SERVED.vc_allocation;
  if (!served || served.available !== true) {
    return {
      available: false,
      unavailableReason: (served && served.unavailable_reason)
        || 'SETTINGS_NOT_SERVED',
      weeklyMinimumCents: null, allocation: [], inSeason: [], seasonRules: [],
    };
  }

  // SHAPED, NOT DERIVED. Every figure — the ratio above all — is the server's
  // own. §16.2 forbids reimplementing the economic formula here, and a division
  // in this function would be exactly that.
  return {
    available: true,
    unavailableReason: null,
    weeklyMinimumCents: served.weekly_minimum_cents,
    allocation: (served.allocation || []).map((row) => ({
      id: row.id, label: row.label, amountCents: row.amount_cents,
      state: row.state, ratio: row.ratio, source: row.source,
    })),
    inSeason: (served.in_season || []).map((row) => ({
      id: row.id, label: row.label, amountCents: row.amount_cents,
      source: row.source,
    })),
    seasonRules: (served.season_rules || []).map((rule) => ({
      label: rule.label, value: rule.value,
    })),
  };
}

/**
 * How one VC ALLOCATION amount is drawn.
 *
 * THE THREE STATES DRAW DIFFERENTLY, WHICH IS THE WHOLE REASON THEY EXIST. The
 * schema keeps "nobody entered an amount" apart from "this league plays without
 * one" so an audit can tell them apart; rendering both as `$0` would discard
 * that at the last possible step. UNCONFIGURED has no figure to show and says
 * so in words; DECLINED shows a real zero, because the league really did choose
 * zero.
 *
 * @param {{amountCents: number|null, state: string}} row
 * @returns {string}
 */
export function allocationAmountText(row) {
  if (row.state === STATE_UNCONFIGURED || row.amountCents === null
      || row.amountCents === undefined) {
    return 'Not set';
  }
  return formatCredits(row.amountCents);
}

export const STATE_CONFIGURED = 'CONFIGURED';
export const STATE_DECLINED = 'DECLINED';
export const STATE_UNCONFIGURED = 'UNCONFIGURED';
