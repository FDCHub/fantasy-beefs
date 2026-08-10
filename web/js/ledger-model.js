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
  status: 'COMPUTATION EXISTS · NO HTTP READ-MODEL',
  computation: 'economy/current_settle.py · CurrentSettle.as_dict()',
  endpoint: null,
  nearest: 'GET /wallet/{team_id} — balance and transactions only',
  needs: 'a GM-scoped read route returning the CurrentSettle components',
});

/**
 * The Request Top-Off seam.
 *
 * Unlike the read-model, the COMMAND API already exists and is governed:
 * `POST /league/{league_id}/top-offs` takes an amount alone, resolves team and
 * requester from the authenticated user, and runs the §10 approval flow. The
 * web app has no session binding yet, so the control is presented read-only and
 * points at that endpoint. Implementing a parallel top-off path in the frontend
 * is expressly out of bounds — this constant exists so the wiring target is
 * unambiguous when the session seam lands.
 */
export const TOPOFF_COMMAND_SEAM = Object.freeze({
  status: 'COMMAND API EXISTS · NOT YET BOUND',
  endpoint: 'POST /league/{league_id}/top-offs',
  authority: 'league membership, resolved from the authenticated user',
  uiState: 'read-only',
});

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
    ADVANCES.regularSeasonMinimumCents,
    ADVANCES.playoffsChampionshipCents,
  );
  return {
    ...ADVANCES,
    seasonOpeningCents,
    totalVirtualStakesCents: sum(seasonOpeningCents, ADVANCES.addedStakesCents),
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
    ...POSITION,
    wageringPositionCents: sum(
      POSITION.spendableCents,
      POSITION.acceptedEscrowCents,
      POSITION.weeklyReserveNotReleasedCents,
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
    ...ADJUSTMENTS,
    netAdjustmentsCents: sum(
      ADJUSTMENTS.weeklyMinOutOfCirculationCents,
      ADJUSTMENTS.skunkFeesCents,
      ADJUSTMENTS.seasonWinningsCents,
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