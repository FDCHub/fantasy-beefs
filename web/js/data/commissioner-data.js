/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · commissioner illustrative league state
 * Sprint 7 Package 4
 *
 * VIEW-MODEL DATA, NOT PROTOCOL DATA — and here that separation matters more
 * than anywhere else in the build, because a commissioner surface that blurred
 * it would be showing invented money to the one person authorised to move real
 * Credits. Nothing in this module is read from the ledger, and nothing it
 * describes has been posted.
 *
 * REAL FIELD NAMES, REAL STATES. The top-off rows below carry the persisted
 * column names from `TopOffRequestOut` and the persisted `decision`/`status`
 * pairs from `economy/top_off.py`. That includes the asymmetry an approval
 * introduces — decision `approved`, status `applied` — which is reproduced
 * rather than smoothed, and the linkage rule: only an approved request carries
 * `ledger_posting_id` and `disclosure_event_id`, because a biconditional CHECK
 * makes a rejected row holding either one unrepresentable.
 *
 * The viewer's own GM row is IMPORTED from `ledger-data.js` rather than
 * restated, so the commissioner's view of that GM and the GM's own Ledger tab
 * cannot disagree about the same position.
 * ========================================================================== */

import { ADJUSTMENTS, ADVANCES, PENDING_OFFER_HOLD_CENTS, POSITION } from './ledger-data.js';
import { OPPONENTS, YOUR_TEAM } from './league-data.js';
import { ECONOMY_STOP } from './rules-data.js';

/** The illustrative league: twelve teams on the default economy stop. */
export const LEAGUE_SIZE = 12;

/**
 * One GM's position, in the SAME terms the Ledger uses.
 *
 * Deliberately the same shape: `commissioner-model` runs these through
 * `ledger-model.currentSettleCents()`, so a commissioner reads the figure the
 * GM reads, produced by the arithmetic the GM's own tab does. A second formula
 * here would be a second answer.
 *
 * `seasonOpeningCents` is the league's stop and is identical for every GM.
 */
function gm(id, name, terms) {
  return Object.freeze({
    teamId: id,
    name,
    seasonOpeningCents: ECONOMY_STOP.buyinCents,
    ...terms,
  });
}

export const GM_POSITIONS = Object.freeze([
  // The viewer. Every figure carried from the Ledger tab's own source.
  gm('you', YOUR_TEAM.name, {
    spendableCents: POSITION.spendableCents,
    acceptedEscrowCents: POSITION.acceptedEscrowCents,
    weeklyReserveNotReleasedCents: POSITION.weeklyReserveNotReleasedCents,
    heldCents: PENDING_OFFER_HOLD_CENTS,
    weeklyMinOutOfCirculationCents: ADJUSTMENTS.weeklyMinOutOfCirculationCents,
    skunkFeesCents: ADJUSTMENTS.skunkFeesCents,
    seasonWinningsCents: ADJUSTMENTS.seasonWinningsCents,
    addedStakesCents: ADVANCES.addedStakesCents,
  }),
  gm('destroyers', OPPONENTS[0].name, {
    spendableCents: 11200, acceptedEscrowCents: 5400, weeklyReserveNotReleasedCents: 9000,
    heldCents: 0, weeklyMinOutOfCirculationCents: 1200, skunkFeesCents: 0,
    seasonWinningsCents: 3600, addedStakesCents: 0,
  }),
  gm('goodfellas', OPPONENTS[1].name, {
    spendableCents: 8300, acceptedEscrowCents: 4100, weeklyReserveNotReleasedCents: 9000,
    heldCents: 1500, weeklyMinOutOfCirculationCents: 900, skunkFeesCents: 0,
    seasonWinningsCents: 2800, addedStakesCents: 0,
  }),
  gm('icedtea', OPPONENTS[2].name, {
    spendableCents: 5900, acceptedEscrowCents: 2200, weeklyReserveNotReleasedCents: 9000,
    heldCents: 0, weeklyMinOutOfCirculationCents: 700, skunkFeesCents: -1000,
    seasonWinningsCents: 1600, addedStakesCents: 0,
  }),
  gm('enforcers', OPPONENTS[3].name, {
    spendableCents: 4100, acceptedEscrowCents: 3300, weeklyReserveNotReleasedCents: 9000,
    heldCents: 2000, weeklyMinOutOfCirculationCents: 600, skunkFeesCents: 0,
    seasonWinningsCents: 1200, addedStakesCents: 2000,
  }),
  gm('racket', OPPONENTS[4].name, {
    spendableCents: 3600, acceptedEscrowCents: 1900, weeklyReserveNotReleasedCents: 9000,
    heldCents: 0, weeklyMinOutOfCirculationCents: 500, skunkFeesCents: -2000,
    seasonWinningsCents: 900, addedStakesCents: 0,
  }),
  gm('braintrust', OPPONENTS[5].name, {
    spendableCents: 2800, acceptedEscrowCents: 2600, weeklyReserveNotReleasedCents: 9000,
    heldCents: 500, weeklyMinOutOfCirculationCents: 400, skunkFeesCents: 0,
    seasonWinningsCents: 800, addedStakesCents: 4000,
  }),
  gm('provolone', OPPONENTS[6].name, {
    spendableCents: 7400, acceptedEscrowCents: 3100, weeklyReserveNotReleasedCents: 9000,
    heldCents: 0, weeklyMinOutOfCirculationCents: 1100, skunkFeesCents: 0,
    seasonWinningsCents: 2100, addedStakesCents: 0,
  }),
  gm('raiders', OPPONENTS[7].name, {
    spendableCents: 5200, acceptedEscrowCents: 2400, weeklyReserveNotReleasedCents: 9000,
    heldCents: 1000, weeklyMinOutOfCirculationCents: 800, skunkFeesCents: 0,
    seasonWinningsCents: 1400, addedStakesCents: 0,
  }),
  gm('cartel', OPPONENTS[8].name, {
    spendableCents: 1900, acceptedEscrowCents: 1500, weeklyReserveNotReleasedCents: 9000,
    heldCents: 0, weeklyMinOutOfCirculationCents: 300, skunkFeesCents: -3000,
    seasonWinningsCents: 400, addedStakesCents: 6000,
  }),
  gm('bombers', OPPONENTS[9].name, {
    spendableCents: 3300, acceptedEscrowCents: 900, weeklyReserveNotReleasedCents: 9000,
    heldCents: 0, weeklyMinOutOfCirculationCents: 600, skunkFeesCents: -1000,
    seasonWinningsCents: 700, addedStakesCents: 0,
  }),
  gm('gravy', OPPONENTS[10].name, {
    spendableCents: 1200, acceptedEscrowCents: 600, weeklyReserveNotReleasedCents: 9000,
    heldCents: 0, weeklyMinOutOfCirculationCents: 200, skunkFeesCents: -4000,
    seasonWinningsCents: 300, addedStakesCents: 2000,
  }),
]);

/* ── Top-Off requests ───────────────────────────────────────────────────────*/

/**
 * The four presentation states, and the persisted pair behind each.
 *
 * Rev 4.2 asks for Pending / Approved / Rejected / Cancelled. Three of those
 * are the persisted `decision` verbatim; the fourth is not, and that is the
 * point of naming both here. An APPROVED request persists status `applied`,
 * because approval is the moment the issuance is applied to the ledger.
 */
export const TOPOFF_STATES = Object.freeze([
  Object.freeze({ id: 'pending', label: 'Pending', decision: 'pending', status: 'pending' }),
  Object.freeze({ id: 'approved', label: 'Approved', decision: 'approved', status: 'applied' }),
  Object.freeze({ id: 'rejected', label: 'Rejected', decision: 'rejected', status: 'rejected' }),
  Object.freeze({ id: 'cancelled', label: 'Cancelled', decision: 'cancelled', status: 'cancelled' }),
]);

/**
 * Illustrative requests, in the route's own ordering — created_at then id,
 * ascending.
 *
 * Field names are `TopOffRequestOut`'s. `remaining_capacity_cents` is
 * deliberately absent from every row: the read route does not return it,
 * because it is not stored and deriving it outside the approval lock would
 * report a number approval is free to contradict.
 */
export const TOPOFF_REQUESTS = Object.freeze([
  Object.freeze({
    id: 41,
    league_id: 1,
    team_id: 'gravy',
    season: 2026,
    requester_user_id: 118,
    amount_cents: 2000,
    decision: 'approved',
    status: 'applied',
    decided_by_user_id: 101,
    decided_at: '2026-09-22T18:04:11Z',
    self_approved: false,
    decision_reason: null,
    // Only an approved request carries the provenance chain.
    ledger_posting_id: '2f1c0a94-7b3e-4a51-9d0c-6e8f2a1b4c77',
    disclosure_event_id: 'c47a1d20-9f65-4b8e-a3d1-70b9e5c2f118',
    created_at: '2026-09-22T17:51:02Z',
  }),
  Object.freeze({
    id: 42,
    league_id: 1,
    team_id: 'you',
    season: 2026,
    requester_user_id: 101,
    amount_cents: 4000,
    decision: 'approved',
    status: 'applied',
    decided_by_user_id: 101,
    // A commissioner who owns a team may request as a GM; §5.3 makes authority
    // and team ownership independent, and a self-approval must state a reason.
    self_approved: true,
    decided_at: '2026-10-01T15:12:40Z',
    decision_reason: 'Commissioner self-approval: matched the standing cap for all GMs.',
    ledger_posting_id: '8d5b71e3-2c40-49af-bb16-3a7c9e0d5512',
    disclosure_event_id: 'a10f6c88-4e27-4d93-9c5b-1f2e7b6a0d34',
    created_at: '2026-10-01T14:58:19Z',
  }),
  Object.freeze({
    id: 43,
    league_id: 1,
    team_id: 'cartel',
    season: 2026,
    requester_user_id: 109,
    amount_cents: 6000,
    decision: 'rejected',
    status: 'rejected',
    decided_by_user_id: 101,
    decided_at: '2026-10-05T19:30:07Z',
    self_approved: false,
    decision_reason: 'Requested above the standing cap for this season.',
    ledger_posting_id: null,
    disclosure_event_id: null,
    created_at: '2026-10-05T19:02:55Z',
  }),
  Object.freeze({
    id: 44,
    league_id: 1,
    team_id: 'bombers',
    season: 2026,
    requester_user_id: 112,
    amount_cents: 1500,
    decision: 'cancelled',
    status: 'cancelled',
    decided_by_user_id: 112,
    decided_at: '2026-10-07T12:18:33Z',
    self_approved: false,
    decision_reason: null,
    ledger_posting_id: null,
    disclosure_event_id: null,
    created_at: '2026-10-07T11:44:20Z',
  }),
  Object.freeze({
    id: 45,
    league_id: 1,
    team_id: 'racket',
    season: 2026,
    requester_user_id: 105,
    amount_cents: 2500,
    decision: 'pending',
    status: 'pending',
    decided_by_user_id: null,
    decided_at: null,
    self_approved: null,
    decision_reason: null,
    ledger_posting_id: null,
    disclosure_event_id: null,
    created_at: '2026-10-09T09:26:14Z',
  }),
  Object.freeze({
    id: 46,
    league_id: 1,
    team_id: 'braintrust',
    season: 2026,
    requester_user_id: 106,
    amount_cents: 3000,
    decision: 'pending',
    status: 'pending',
    decided_by_user_id: null,
    decided_at: null,
    self_approved: null,
    decision_reason: null,
    ledger_posting_id: null,
    disclosure_event_id: null,
    created_at: '2026-10-09T10:03:48Z',
  }),
]);