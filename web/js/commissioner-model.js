/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · commissioner read-model
 * Sprint 7 Package 4
 *
 * Pure functions over exact integer cents. No DOM, no I/O, no posting.
 *
 * ONE FORMULA, USED TWICE. A commissioner looking at a GM must see the figure
 * that GM sees. So every per-GM position here is produced by
 * `ledger-model.currentSettleCents()` — the same three terms, the same
 * subtraction, the same module the Ledger tab uses. There is no commissioner
 * settlement formula, and the league roll-up is an AGGREGATION of those same
 * per-GM figures rather than a second calculation that happens to agree.
 *
 * WHAT THE LEAGUE VIEW MAY NOT CLAIM. Pending offer holds reduce what a GM can
 * spend and are NOT settlement liabilities — governing accounting excludes them
 * until a proposal is accepted. They are reported as an exception count with
 * that exclusion stated, never added into a total.
 *
 * THREE SEAMS, ALL REAL. The commissioner surfaces are the part of this build
 * that most obviously wants a backend, and each gap is named rather than
 * papered over.
 * ========================================================================== */

import { assertIntegerCents } from './credits.js';
import { currentSettleCents } from './ledger-model.js';
import { GM_POSITIONS, TOPOFF_REQUESTS, TOPOFF_STATES } from './data/commissioner-data.js';

/* ── Seams ──────────────────────────────────────────────────────────────────*/

/**
 * The acting-commissioner seam.
 *
 * The authority model is fully built and enforced server-side:
 * `auth/jwt_auth.py` resolves the caller, `is_league_commissioner()` checks
 * authority for the specific league, and every decision route re-checks it
 * under lock before committing. What is missing is upstream of all of that —
 * the web app has no authenticated session, so there is no acting commissioner
 * for a decision to be attributed to.
 *
 * A decision posts real Credits and writes a disclosure event. Firing one from
 * illustrative browser state would attribute an irreversible ledger posting to
 * nobody, so the controls on this tab are demonstrative and say so.
 */
export const COMMISSIONER_AUTH_SEAM = Object.freeze({
  status: 'AUTHORITY MODEL EXISTS · NO SESSION IDENTITY IN THE WEB APP',
  serverAuthority: 'auth/jwt_auth.py · is_league_commissioner() · re-checked under lock',
  missing: 'an authenticated session that names the acting commissioner',
  uiState: 'illustrative — no decision is transmitted',
});

/**
 * The Top-Off command surface. All four routes exist and are governed.
 *
 * They are named here so the binding target is unambiguous when the session
 * seam lands, and so nothing in this build reimplements issuance.
 */
export const TOPOFF_ROUTES = Object.freeze({
  create: 'POST /league/{league_id}/top-offs',
  approve: 'POST /league/{league_id}/top-offs/{request_id}/approve',
  reject: 'POST /league/{league_id}/top-offs/{request_id}/reject',
  cancel: 'POST /league/{league_id}/top-offs/{request_id}/cancel',
  read: 'GET /league/{league_id}/top-offs',
});

/**
 * The league-wide positions seam.
 *
 * `economy/current_settle.py` computes ONE GM's position from posted ledger
 * state. Nothing computes twelve, and no route returns a league's worth:
 * `GET /league/{league_id}/top-offs` returns requests, `/wallet/{team_id}`
 * returns one balance, and `/reports/settlement/{league_id}` is the season-end
 * championship settlement rather than a live position roll-up.
 *
 * So the twelve GM cards on this tab are illustrative league state, held in
 * `data/commissioner-data.js` and kept explicitly separate from anything read.
 */
export const LEAGUE_POSITIONS_SEAM = Object.freeze({
  status: 'PER-GM COMPUTATION EXISTS · NO LEAGUE-WIDE READ-MODEL',
  computation: 'economy/current_settle.py — one team at a time',
  endpoint: null,
  nearest: 'GET /reports/settlement/{league_id} — season-end championship settlement only',
  needs: 'a league-scoped route returning every GM\'s CurrentSettle components',
});

/**
 * The integrity-check seam.
 *
 * `ledger.trial_balance()` is the continuous double-entry check and it is
 * authoritative, but it is a Python callable with no HTTP surface, and it is
 * global rather than league-scoped. The reconciliation below states the
 * invariant and reports it as unverified from the browser rather than
 * computing a substitute for it.
 */
export const TRIAL_BALANCE_SEAM = Object.freeze({
  status: 'INVARIANT EXISTS · NOT READABLE FROM THE WEB APP',
  computation: 'ledger/ledger.py · trial_balance()',
  endpoint: null,
  scope: 'global across all leagues, not league-scoped',
  needs: 'a league-scoped integrity read the commissioner surface can call',
});

/* ── Per-GM positions ───────────────────────────────────────────────────────*/

function sum(...values) {
  values.forEach((v, i) => assertIntegerCents(v, `term ${i}`));
  return values.reduce((total, v) => total + v, 0);
}

/**
 * One GM's position, in the Ledger's own three terms.
 *
 * @param {object} record a row from GM_POSITIONS
 * @returns {object}
 */
export function gmPosition(record) {
  const wageringPositionCents = sum(
    record.spendableCents,
    record.acceptedEscrowCents,
    record.weeklyReserveNotReleasedCents,
  );
  const netAdjustmentsCents = sum(
    record.weeklyMinOutOfCirculationCents,
    record.skunkFeesCents,
    record.seasonWinningsCents,
  );
  const totalVirtualStakesCents = sum(record.seasonOpeningCents, record.addedStakesCents);

  return {
    teamId: record.teamId,
    name: record.name,
    spendableCents: record.spendableCents,
    acceptedEscrowCents: record.acceptedEscrowCents,
    weeklyReserveNotReleasedCents: record.weeklyReserveNotReleasedCents,
    heldCents: record.heldCents,
    weeklyMinOutOfCirculationCents: record.weeklyMinOutOfCirculationCents,
    skunkFeesCents: record.skunkFeesCents,
    seasonWinningsCents: record.seasonWinningsCents,
    seasonOpeningCents: record.seasonOpeningCents,
    addedStakesCents: record.addedStakesCents,
    wageringPositionCents,
    netAdjustmentsCents,
    totalVirtualStakesCents,
    // The GM's own figure, by the GM's own arithmetic.
    currentSettleCents: currentSettleCents({
      wageringPositionCents,
      netAdjustmentsCents,
      totalVirtualStakesCents,
    }),
  };
}

/** Every GM's position, in league order. */
export function gmPositions() {
  return GM_POSITIONS.map(gmPosition);
}

/* ── Top-Off requests ───────────────────────────────────────────────────────*/

/**
 * The presentation state of a persisted request.
 *
 * Matched on the persisted `decision` and `status` TOGETHER, because the pair
 * is what the protocol writes and either one alone would be ambiguous: an
 * approved request carries status `applied`, not `approved`.
 *
 * @param {object} request
 * @returns {{id: string, label: string, decision: string, status: string}}
 */
export function topOffState(request) {
  const found = TOPOFF_STATES.find(
    (s) => s.decision === request.decision && s.status === request.status,
  );
  if (!found) {
    throw new Error(
      `no presentation state for decision "${request.decision}" / status "${request.status}"`,
    );
  }
  return found;
}

/** Requests awaiting a decision — the only ones a commissioner can act on. */
export function openRequests() {
  return TOPOFF_REQUESTS.filter((r) => topOffState(r).id === 'pending');
}

/** Every request, grouped by presentation state, in the locked state order. */
export function requestsByState() {
  return TOPOFF_STATES.map((state) => ({
    state,
    requests: TOPOFF_REQUESTS.filter((r) => topOffState(r).id === state.id),
  }));
}

/**
 * Whether a request carries the provenance chain.
 *
 * Only an approved one does — request → posting → both ledger legs →
 * disclosure. A rejected or cancelled row holding either linkage field is
 * unrepresentable by CHECK constraint, so this is a property to display, not a
 * rule to enforce here.
 *
 * @param {object} request
 * @returns {boolean}
 */
export function hasProvenance(request) {
  return Boolean(request.ledger_posting_id && request.disclosure_event_id);
}

/* ── League reconciliation ──────────────────────────────────────────────────*/

/**
 * The league-wide check.
 *
 * AGGREGATION, NOT A SECOND FORMULA. Each total is the sum of the per-GM
 * figures produced above, and `closes` asserts that summing the parts and
 * summing the whole give the same answer — the same relation each GM's own
 * Ledger card shows, checked across twelve of them.
 *
 * EXCEPTIONS ARE COUNTED, NOT CAPITALISED. Open top-off requests are potential
 * future obligations and are not in any total. Pending offer holds are excluded
 * from settlement by governing accounting until a proposal is accepted, and are
 * reported with that exclusion stated. Skunk receivables are already inside
 * each GM's adjustments — no controlling authority collects them, so they are
 * reported for visibility and not added again.
 *
 * @returns {object}
 */
export function leagueReconciliation() {
  const positions = gmPositions();

  const totalVirtualStakesCents = positions.reduce((t, p) => t + p.totalVirtualStakesCents, 0);
  const wageringPositionCents = positions.reduce((t, p) => t + p.wageringPositionCents, 0);
  const netAdjustmentsCents = positions.reduce((t, p) => t + p.netAdjustmentsCents, 0);
  const sumOfGmSettlesCents = positions.reduce((t, p) => t + p.currentSettleCents, 0);

  // The same three terms, aggregated. If these disagree, the roll-up is wrong —
  // not the GMs.
  const aggregateSettleCents = currentSettleCents({
    wageringPositionCents,
    netAdjustmentsCents,
    totalVirtualStakesCents,
  });

  const open = openRequests();
  const holds = positions.filter((p) => p.heldCents > 0);
  const receivables = positions.filter((p) => p.skunkFeesCents < 0);

  return {
    teams: positions.length,
    totalVirtualStakesCents,
    wageringPositionCents,
    netAdjustmentsCents,
    sumOfGmSettlesCents,
    aggregateSettleCents,
    // The league closes when the parts and the whole agree.
    closes: sumOfGmSettlesCents === aggregateSettleCents,
    exceptions: Object.freeze({
      openTopOffs: Object.freeze({
        count: open.length,
        cents: open.reduce((t, r) => t + r.amount_cents, 0),
        settlementLiability: false,
        note: 'Requested, not decided. Nothing is issued until a commissioner approves.',
      }),
      pendingOfferHolds: Object.freeze({
        count: holds.length,
        cents: holds.reduce((t, p) => t + p.heldCents, 0),
        settlementLiability: false,
        note: 'Held against open offers. Excluded from settlement until a proposal '
          + 'is accepted — reported here, never added to a total.',
      }),
      skunkReceivables: Object.freeze({
        count: receivables.length,
        cents: receivables.reduce((t, p) => t + p.skunkFeesCents, 0),
        settlementLiability: true,
        note: 'Already inside each GM’s adjustments. Nothing collects a receivable '
          + 'automatically; it nets arithmetically at close.',
      }),
    }),
    integrity: Object.freeze({
      invariant: 'Every ledger batch sums to zero, so the trial balance is zero.',
      verified: false,
      seam: TRIAL_BALANCE_SEAM,
    }),
  };
}