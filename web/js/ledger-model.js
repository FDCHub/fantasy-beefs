/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Ledger presentation read-model
 * Sprint 7 Package 3
 *
 * "Four-cell strips show the answer. Ledger shows the math." This module is the
 * math — and nothing else. Pure functions over exact integer cents: no DOM, no
 * I/O, no mutation, no posting.
 *
 * WHAT THIS MODULE MAY AND MAY NOT DO
 *
 * It REGROUPS an authoritative position for display. It does not define one.
 * Three boundaries follow, and each is enforced below rather than merely
 * stated:
 *
 *   1. NO NEW ACCOUNTING. Current Settle is DERIVED, never stored, and its
 *      authoritative definition lives in `economy/current_settle.py`:
 *
 *          Current Settle = settlement-relevant GM assets − GM obligations
 *
 *      Rev 4.2 presents the same quantity in a different grouping:
 *
 *          Current Settle = Wagering Position
 *                         + Season Adjustments & Winnings
 *                         − Total Virtual Stakes
 *
 *      Those are the same arithmetic over the same terms, not two competing
 *      definitions. `backendEquivalent()` computes the assets/obligations form
 *      from the same inputs, and the suite asserts the two agree to the cent.
 *      If they ever diverge, that is a defect in this module, not a licence to
 *      adjust the figure.
 *
 *   2. NO DOUBLE COUNTING. Net Versus and Net Pools are EXPLANATORY summaries
 *      of activity whose outcome is already sitting in the spendable, escrow
 *      and reserve balances. Adding them to Current Settle would count the same
 *      money twice. This is structural, not a comment: `CURRENT_SETTLE_TERMS`
 *      names the only three inputs, `currentSettleCents()` reads exactly those
 *      three fields, and the activity figures are produced by a different
 *      function that no total consumes.
 *
 *   3. NO FABRICATED SEAM. Where the production read-model does not exist yet,
 *      this module says so by name rather than inventing an endpoint. See
 *      `LEDGER_READ_SEAM` and `TOPOFF_COMMAND_SEAM`.
 * ========================================================================== */

import { assertIntegerCents } from './credits.js';
import {
  ADJUSTMENTS,
  ADVANCES,
  POOL_ACTIVITY,
  POSITION,
  VERSUS_ACTIVITY,
} from './data/ledger-data.js';

/* ── Seams ──────────────────────────────────────────────────────────────────*/

/**
 * The Ledger read-model seam.
 *
 * The COMPUTATION exists and is authoritative: `economy/current_settle.py`
 * derives a `CurrentSettle` dataclass from posted ledger state and exposes
 * every component through `as_dict()`. What does NOT exist is an HTTP surface
 * for it — there is no route in `api/main.py` that returns a GM's current
 * settle or its components. `/wallet/{team_id}` returns a balance and a
 * transaction list, which is not the same thing and cannot be regrouped into
 * the sections below.
 *
 * This build therefore renders POR figures and names the seam. It does not
 * recompute settlement from frontend rules, and it must not: the identity in
 * `backendEquivalent()` is a consistency check on the presentation, not a
 * second implementation of the accounting.
 */
export const LEDGER_READ_SEAM = Object.freeze({
  // S8-P3 built the read model. What is left is the binding, which is P4's —
  // this module still draws the illustrative figures below, and saying the
  // seam is closed while it does that would be the same lie in the other
  // direction.
  status: 'READ MODEL EXISTS · NOT YET BOUND',
  computation: 'economy/current_settle.py · CurrentSettle.as_dict()',
  endpoint: 'GET /league/{league_id}/ledger/me',
  readModel: 'reports/ledger_read_model.py · gm_ledger()',
  units: 'exact integer cents; whole-dollar display stays in credits.js',
  needs: 'the Ledger tab bound to that route in place of the figures below',
});

/**
 * The Request Top-Off seam.
 *
 * Unlike the read-model, the COMMAND API already exists and is governed:
 * `POST /league/{league_id}/top-offs` takes an amount alone, resolves team and
 * requester from the authenticated user, and runs the §10 approval flow. The
 * web app now HAS a session (S8-P1), so the authority half is settled: the app
 * can name the acting user, and the endpoint resolves team and requester from
 * them. What is still missing is the Ledger READ — the figures on this tab are
 * illustrative, and a request raised against them would be a real advance
 * sized by a number nobody read. Implementing a parallel top-off path in the
 * frontend remains expressly out of bounds; this constant exists so the wiring
 * target is unambiguous when the binding lands.
 */
export const TOPOFF_COMMAND_SEAM = Object.freeze({
  status: 'COMMAND API EXISTS · NOT YET BOUND',
  endpoint: 'POST /league/{league_id}/top-offs',
  authority: 'league membership, resolved from the authenticated user',
  sessionIdentity: 'S8-P1 — the acting user is now known to the app',
  blockedOn: 'the Ledger read-model binding, not authentication',
  uiState: 'read-only',
});

/* ── Source binding (S8-P4) ─────────────────────────────────────────────────*/

/**
 * The terms the derivations below read.
 *
 * Defaults to the POR's illustrative figures — which is what makes the
 * components reviewable, and testable, without a server. `bindLedger()`
 * replaces them with the authoritative read model once a session has loaded
 * one. THE DERIVATIONS DO NOT CHANGE: the same arithmetic runs over whichever
 * terms are bound, so binding cannot quietly introduce a second formula.
 */
/**
 * THREE MODES, AND THE THIRD ONE IS THE POINT.
 *
 *   demo           the POR's illustrative figures. Component suites and
 *                  isolated review render this, and it is the default so a
 *                  module imported on its own still draws something coherent.
 *   authoritative  bound to a real read model.
 *   unavailable    PRODUCTION, but the read failed or was refused.
 *
 * Without the third mode, a 403 or a 500 in an authenticated session would
 * fall through to `demo` and a GM would be shown the prototype's −$45 as
 * though it were their money. That is the single worst outcome available to
 * this package, and a boolean cannot express the difference: "not bound" and
 * "bound to nothing" have to be distinguishable.
 */
export const MODE_DEMO = 'demo';
export const MODE_AUTHORITATIVE = 'authoritative';
export const MODE_UNAVAILABLE = 'unavailable';

const DEMO_SOURCE = {
  position: POSITION, adjustments: ADJUSTMENTS, advances: ADVANCES,
  mode: MODE_DEMO, currentSettleCents: null, heldCents: null,
};

let SOURCE = DEMO_SOURCE;

/**
 * Season-opening advance, split into its two governed legs when they reconcile.
 *
 * @param {object} model GmLedgerOut
 * @param {object} [settings] LeagueSettingsOut
 * @returns {{regularSeasonMinimumCents: number, playoffsChampionshipCents: number,
 *   addedStakesCents: number, splitResolved: boolean}}
 */
function splitAdvance(model, settings) {
  const stop = settings && settings.economy_stop;
  const reconciles = Boolean(stop)
    && stop.min_reserve_cents + stop.reserve_cents === model.season_advance_cents;

  return {
    regularSeasonMinimumCents: reconciles ? stop.min_reserve_cents
                                          : model.season_advance_cents,
    playoffsChampionshipCents: reconciles ? stop.reserve_cents : 0,
    addedStakesCents: model.topoff_issued_cents,
    // Drawn as one figure rather than a breakdown when the legs are unknown.
    splitResolved: reconciles,
  };
}

/**
 * Bind the authoritative GM Ledger read model.
 *
 * THE MAPPING, AND THE ONE CORRECTION IT FORCES. Rev 4.2 draws three sections;
 * `economy/current_settle.py` groups the same money as assets − obligations.
 * They reconcile term for term:
 *
 *   spendable                    → available (wallet + live weekly minimum)
 *   weeklyReserveNotReleased     → min_reserve
 *   acceptedEscrow               → in_play
 *   weeklyMinOutOfCirculation    → expired_min
 *   skunkFees (signed, negative) → −receivable
 *   seasonOpening                → season_advance
 *   addedStakes                  → topoff_issued
 *
 * `acceptedEscrow` maps to the WHOLE of `in_play`, not to in_play minus the
 * held amount. The illustrative dataset implied otherwise and still balanced,
 * because its invented season-winnings figure happened to offset the
 * difference. Against real state that coincidence disappears: subtracting held
 * from the escrow term and then adding a winnings term the backend does not
 * have would produce a Current Settle that disagreed with the ledger. Held
 * remains what the POR always said it was — a memo reported beside the
 * position, never inside a total.
 *
 * `seasonWinnings` binds to NOTHING. P3 established it has no authoritative
 * source, and the backend's settlement position carries no awards component,
 * so it contributes zero to the identity and is drawn unresolved rather than
 * given a number.
 *
 * @param {object} model a GmLedgerOut body from /league/{id}/ledger/me
 * @param {object} [settings] a LeagueSettingsOut body, for the advance split
 */
export function bindLedger(model, settings) {
  SOURCE = {
    position: Object.freeze({
      spendableCents: model.available_cents,
      acceptedEscrowCents: model.in_play_cents,
      weeklyReserveNotReleasedCents: model.min_reserve_cents,
    }),
    adjustments: Object.freeze({
      weeklyMinOutOfCirculationCents: model.expired_min_cents,
      // A fee is negative here; the backend reports the obligation magnitude.
      skunkFeesCents: -model.receivable_cents,
      // No authoritative source — see above. Zero in the identity, unresolved
      // on screen.
      seasonWinningsCents: 0,
    }),
    // THE SPLIT COMES FROM THE ECONOMY STOP, NOT FROM THE CURRENT BALANCE.
    // `min_reserve_cents` is what is LEFT in the reserve today and falls every
    // week as the minimum releases; the season-opening split is fixed at
    // activation. Using the live balance would have shrunk "Regular Season
    // Minimum" week by week while the advance it describes never moved.
    //
    // The stop is used only when its two legs reconcile to the posted advance.
    // If they disagree, the posted figure is authoritative and the split is
    // not shown as a breakdown of it — a hierarchy whose parts do not add to
    // its total is worse than a single honest number.
    advances: Object.freeze(splitAdvance(model, settings)),
    mode: MODE_AUTHORITATIVE,
    // Carried so a caller can compare the drawn total against the server's own
    // figure rather than trusting that the mapping above was right.
    currentSettleCents: model.current_settle_cents,
    heldCents: model.held_open_challenges_cents,
    // Carried separately because `spendableCents` groups wallet AND live
    // weekly minimum into one spendable pool, while the strip draws the
    // weekly-minimum component as its own cell.
    weeklyMinLiveCents: model.weekly_min_live_cents,
  };
}

/**
 * Enter production UNAVAILABLE mode.
 *
 * Zeroed terms so the derivations stay total functions and no caller has to
 * guard every arithmetic site against null. The zeros are never DRAWN — the
 * renderers read `ledgerMode()` and show the unresolved treatment — but they
 * keep a stray `reconciliation()` call from throwing, which would take the tab
 * down instead of degrading it.
 */
export function markLedgerUnavailable() {
  const zero = {
    position: Object.freeze({ spendableCents: 0, acceptedEscrowCents: 0,
                              weeklyReserveNotReleasedCents: 0 }),
    adjustments: Object.freeze({ weeklyMinOutOfCirculationCents: 0,
                                 skunkFeesCents: 0, seasonWinningsCents: 0 }),
    advances: Object.freeze({ regularSeasonMinimumCents: 0,
                              playoffsChampionshipCents: 0,
                              addedStakesCents: 0, splitResolved: false }),
  };
  SOURCE = { ...zero, mode: MODE_UNAVAILABLE, currentSettleCents: null,
             heldCents: null };
}

/** The current mode. @returns {'demo'|'authoritative'|'unavailable'} */
export function ledgerMode() {
  return SOURCE.mode;
}

/** Restore the illustrative source. Used on sign-out and by the suites. */
export function unbindLedger() {
  SOURCE = DEMO_SOURCE;
}

/** Whether the figures currently drawn came from the backend. */
export function isLedgerBound() {
  return SOURCE.mode === MODE_AUTHORITATIVE;
}

/**
 * The server's own Current Settle, when bound — for comparison, not display.
 * @returns {number|null}
 */
export function boundCurrentSettleCents() {
  return SOURCE.currentSettleCents;
}

/** Credits held against open challenges, when bound. @returns {number|null} */
export function boundHeldCents() {
  return SOURCE.heldCents;
}

/**
 * The GM's spendable Credits — wallet plus live weekly minimum.
 *
 * Reads the SAME `position.spendableCents` the Ledger tab totals from, so the
 * League strip and the Ledger cannot disagree about what is spendable. Null in
 * demo, where there is no bound position.
 *
 * @returns {number|null}
 */
export function boundAvailableCents() {
  return ledgerMode() === MODE_AUTHORITATIVE
    ? SOURCE.position.spendableCents : null;
}

export function boundWeeklyMinLiveCents() {
  return SOURCE.weeklyMinLiveCents ?? null;
}

/**
 * Whether Season winnings has an authoritative source in the current binding.
 *
 * False when bound: the backend has no awards component, so the figure is
 * drawn unresolved rather than as a number. True on the illustrative source,
 * where the POR fixed one.
 */
export function seasonWinningsResolved() {
  return SOURCE.mode === MODE_DEMO;
}

/* ── Derivations ────────────────────────────────────────────────────────────*/

function sum(...values) {
  values.forEach((v, i) => assertIntegerCents(v, `term ${i}`));
  return values.reduce((total, v) => total + v, 0);
}

/**
 * FantasyStakes Advances.
 *
 * The hierarchy is the point: the two season-opening components add to the
 * season-opening figure, and Added Stakes joins at the SAME level rather than
 * beneath it. Both totals are computed here so the drawn hierarchy cannot show
 * arithmetic it does not do.
 *
 * @returns {{regularSeasonMinimumCents: number, playoffsChampionshipCents: number,
 *   seasonOpeningCents: number, addedStakesCents: number, totalVirtualStakesCents: number}}
 */
export function advances() {
  const seasonOpeningCents = sum(
    SOURCE.advances.regularSeasonMinimumCents,
    SOURCE.advances.playoffsChampionshipCents,
  );
  return {
    ...SOURCE.advances,
    seasonOpeningCents,
    totalVirtualStakesCents: sum(seasonOpeningCents,
                                SOURCE.advances.addedStakesCents),
  };
}

/**
 * Versus and Pool activity — EXPLANATORY ONLY.
 *
 * Nothing in this return value feeds Current Settle. See boundary 2 above.
 *
 * @returns {{settledWinsCents: number, settledLossesCents: number, netVersusCents: number,
 *   poolPayoutsCents: number, poolEntriesCents: number, netPoolsCents: number}}
 */
export function activity() {
  return {
    ...VERSUS_ACTIVITY,
    netVersusCents: sum(
      VERSUS_ACTIVITY.settledWinsCents,
      VERSUS_ACTIVITY.settledLossesCents,
    ),
    ...POOL_ACTIVITY,
    netPoolsCents: sum(POOL_ACTIVITY.poolPayoutsCents, POOL_ACTIVITY.poolEntriesCents),
  };
}

/**
 * Current wager position — the holdings themselves.
 *
 * @returns {{spendableCents: number, acceptedEscrowCents: number,
 *   weeklyReserveNotReleasedCents: number, wageringPositionCents: number}}
 */
export function position() {
  return {
    ...SOURCE.position,
    wageringPositionCents: sum(
      SOURCE.position.spendableCents,
      SOURCE.position.acceptedEscrowCents,
      SOURCE.position.weeklyReserveNotReleasedCents,
    ),
  };
}

/**
 * Season adjustments and winnings.
 *
 * `skunkFeesCents` is SIGNED, and a fee is negative: it maps to the backend's
 * `receivable:` obligation, which subtracts. Holding the sign in the value
 * rather than in the arithmetic keeps this a sum like the others, and keeps the
 * mapping exact for a future non-zero figure.
 *
 * @returns {{weeklyMinOutOfCirculationCents: number, skunkFeesCents: number,
 *   seasonWinningsCents: number, netAdjustmentsCents: number}}
 */
export function adjustments() {
  return {
    ...SOURCE.adjustments,
    netAdjustmentsCents: sum(
      SOURCE.adjustments.weeklyMinOutOfCirculationCents,
      SOURCE.adjustments.skunkFeesCents,
      SOURCE.adjustments.seasonWinningsCents,
    ),
  };
}

/**
 * The ONLY three inputs to Current Settle.
 *
 * Named as data so a test can assert what is absent — the activity nets — and
 * not merely that a number happens to come out right.
 */
export const CURRENT_SETTLE_TERMS = Object.freeze([
  'wageringPositionCents',
  'netAdjustmentsCents',
  'totalVirtualStakesCents',
]);

/**
 * Current Settle, from exactly the three terms above.
 *
 * @param {{wageringPositionCents: number, netAdjustmentsCents: number,
 *   totalVirtualStakesCents: number}} terms
 * @returns {number} exact integer cents
 */
export function currentSettleCents(terms) {
  CURRENT_SETTLE_TERMS.forEach((key) => assertIntegerCents(terms[key], key));
  return terms.wageringPositionCents
    + terms.netAdjustmentsCents
    - terms.totalVirtualStakesCents;
}

/**
 * The same position in the backend's own grouping.
 *
 * `economy/current_settle.py` computes assets − obligations over these
 * components:
 *
 *   assets       wallet + live weekly minimum + minimum reserve
 *                + expired minimum + in play + awards
 *   obligations  season advance + approved Top-Off + receivable
 *
 * Rev 4.2 draws the same terms in three sections instead. This function exists
 * so the two forms can be compared to the cent, which the suite does. It is a
 * CHECK, not a second source of truth.
 *
 * @returns {{assetsCents: number, obligationsCents: number, currentSettleCents: number}}
 */
export function backendEquivalent() {
  const p = position();
  const a = adjustments();
  const adv = advances();

  const assetsCents = sum(
    // wallet + live weekly minimum + minimum reserve, as the POR groups them
    p.spendableCents,
    p.weeklyReserveNotReleasedCents,
    p.acceptedEscrowCents,                    // in play, attributed
    a.weeklyMinOutOfCirculationCents,         // expired_min:
    a.seasonWinningsCents,                    // awards
  );

  const obligationsCents = sum(
    adv.seasonOpeningCents,                   // season advance
    adv.addedStakesCents,                     // approved Top-Off issuance
    -a.skunkFeesCents,                        // receivable: — a fee is negative above
  );

  return {
    assetsCents,
    obligationsCents,
    currentSettleCents: assetsCents - obligationsCents,
  };
}

/**
 * The whole Ledger, reconciled.
 *
 * Every figure the tab draws comes from this one object, so a section and the
 * strip above it cannot disagree about the same quantity.
 *
 * @returns {object}
 */
export function reconciliation() {
  const adv = advances();
  const act = activity();
  const pos = position();
  const adj = adjustments();

  const settleCents = currentSettleCents({
    wageringPositionCents: pos.wageringPositionCents,
    netAdjustmentsCents: adj.netAdjustmentsCents,
    totalVirtualStakesCents: adv.totalVirtualStakesCents,
  });

  return {
    advances: adv,
    activity: act,
    position: pos,
    adjustments: adj,
    currentSettleCents: settleCents,
    // My Season's middle cell is the two activity nets together — derived, so
    // the strip cannot drift from the section that explains it.
    versusPlusPoolsCents: act.netVersusCents + act.netPoolsCents,
  };
}

/**
 * Close an itemised support list against the total it expands.
 *
 * The itemised rows are recent detail, not the whole season. Rather than show
 * an expansion that does not add up — or invent every historical row — the
 * remainder is derived and shown as one labelled row. The list therefore always
 * reconciles to its header by construction.
 *
 * @param {Array<{label: string, cents: number}>} items
 * @param {number} totalCents
 * @param {string} [remainderLabel]
 * @returns {Array<{label: string, cents: number, derived?: boolean}>}
 */
export function supportingRows(items, totalCents, remainderLabel = 'Earlier this season') {
  assertIntegerCents(totalCents, 'support total');
  const itemised = items.reduce((total, row) => total + assertIntegerCents(row.cents, row.label), 0);
  const remainder = totalCents - itemised;
  return remainder === 0
    ? [...items]
    : [...items, { label: remainderLabel, cents: remainder, derived: true }];
}