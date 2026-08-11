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
 * The acting-commissioner seam. NARROWED BY S8-P1, NOT CLOSED.
 *
 * The authority model is fully built and enforced server-side:
 * `auth/jwt_auth.py` resolves the caller, `is_league_commissioner()` checks
 * authority for the specific league, and every decision route re-checks it
 * under lock before committing.
 *
 * WHAT PACKAGE 1 SUPPLIED. The web app now has an authenticated session.
 * `/auth/me` names the acting user and reports, server-side, whether they hold
 * commissioner authority and for which leagues. The half of this seam that
 * read "there is no acting commissioner for a decision to be attributed to" is
 * therefore answered: there is one, and the server named them.
 *
 * WHAT REMAINS, AND WHY THE CONTROLS ARE STILL INERT. A decision posts real
 * Credits and writes a disclosure event. Knowing WHO is acting does not by
 * itself make it safe to fire one from a tab whose twelve GM positions are
 * still illustrative — the commissioner would be deciding about figures that
 * were never read. Binding the decision commands belongs in the same package
 * as binding the data they act on, so that a control and the number it acts on
 * become real together rather than one sprint apart.
 *
 * That is why this is narrowed rather than closed. Reporting it solved because
 * authentication landed would claim a working decision path that does not
 * exist.
 */
export const COMMISSIONER_AUTH_SEAM = Object.freeze({
  status: 'SESSION IDENTITY EXISTS · DECISION COMMANDS NOT YET BOUND',
  serverAuthority: 'auth/jwt_auth.py · is_league_commissioner() · re-checked under lock',
  sessionIdentity: 'S8-P1 — HttpOnly cookie session; /auth/me names the acting user',
  missing: 'the Top-Off decision routes bound to the acting commissioner, over read league positions',
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
  // S8-P3 built it, and built it as an aggregation of the SAME per-GM
  // calculation rather than as a second query — so a commissioner's view of a
  // GM is that GM's own figure by construction, not by coincidence. The cards
  // below are still illustrative until P4 binds them.
  status: 'READ MODEL EXISTS · NOT YET BOUND',
  computation: 'economy/current_settle.py — one team at a time',
  endpoint: 'GET /league/{league_id}/ledger/positions',
  readModel: 'reports/ledger_read_model.py · league_positions() → gm_ledger()',
  reconciliation: 'GET /league/{league_id}/ledger/reconciliation',
  needs: 'the twelve cards bound to that route in place of the figures below',
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
  // AN AUTHORITY BOUNDARY, NOT A GAP. S8-P3 briefly exposed this invariant over
  // HTTP; S8-P3R withdrew it. The reasoning is worth keeping because it is the
  // whole point:
  //
  // The invariant is GLOBAL — it sums every entry in every league. Serving it
  // therefore needs platform authority, and this system's authority model tops
  // out at league commissioner: the seeding convention gives a league's
  // commissioner the global role string, so any route guarded by that role is
  // reachable by an ordinary commissioner. Rather than weaken the authority to
  // make the surface visible, or invent a league-scoped substitute that would
  // be a new derivation wearing an existing invariant's name, the invariant
  // stays where it can be held safely: in the backend.
  //
  // The commissioner is not left without an answer. "Does my league's money add
  // up?" is a LEAGUE question and has a league-scoped answer — the
  // reconciliation route below. Global conservation is an operator concern,
  // exercised in certification, and the two were never the same claim.
  status: 'GLOBAL INVARIANT EXISTS · BACKEND-ONLY',
  computation: 'ledger/ledger.py · trial_balance()',
  scope: 'global',
  endpoint: null,
  reason: 'current MVP authority model has no distinct platform-operator tier',
  doesNotProve: 'individual league reconciliation',
  commissionerSurface: 'GET /league/{league_id}/ledger/reconciliation',
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

/* ── Source binding (S8-P4B) ────────────────────────────────────────────────*/

/**
 * The rows `gmPositions()` maps, and the league roll-up's exception figures.
 *
 * Defaults to the illustrative league so the components stay reviewable and
 * testable without a server. `bindCommissioner()` replaces them with the
 * authoritative read models. `gmPosition()` itself is untouched by binding —
 * the same arithmetic runs over whichever rows are bound, which is what stops
 * a commissioner-side formula from appearing.
 */
/** Same three modes as the Ledger, and for the same reason — see ledger-model. */
export const COMM_MODE_DEMO = 'demo';
export const COMM_MODE_AUTHORITATIVE = 'authoritative';
export const COMM_MODE_UNAVAILABLE = 'unavailable';

let POSITIONS_SOURCE = GM_POSITIONS;
let SERVER_RECONCILIATION = null;
let COMM_MODE = COMM_MODE_DEMO;

/**
 * Bind the authoritative league positions and reconciliation.
 *
 * THE PER-GM MAPPING IS THE LEDGER'S, DELIBERATELY. Every field below maps
 * exactly as `ledger-model.bindLedger()` maps it, including both P4A
 * corrections: `acceptedEscrow` takes the WHOLE of `in_play`, and `held` stays
 * a memo that no total consumes. A commissioner reading a GM's card and that
 * GM reading their own Ledger are then looking at one figure produced one way,
 * which is the property the Sprint 7 certification asserts across packages.
 *
 * `seasonOpening` takes the POSTED advance rather than an economy-stop
 * lookup — a card is a per-GM figure and the posting is what that GM actually
 * received.
 *
 * @param {Array<object>} positions GmLedgerOut rows from /ledger/positions
 * @param {object|null} [reconciliation] LeagueReconciliationOut, for exceptions
 */
export function bindCommissioner(positions, reconciliation = null) {
  POSITIONS_SOURCE = positions.map((p) => Object.freeze({
    teamId: p.team_id,
    name: p.team_name,
    spendableCents: p.available_cents,
    acceptedEscrowCents: p.in_play_cents,
    weeklyReserveNotReleasedCents: p.min_reserve_cents,
    heldCents: p.held_open_challenges_cents,
    weeklyMinOutOfCirculationCents: p.expired_min_cents,
    skunkFeesCents: -p.receivable_cents,
    // No authoritative source; zero in the identity, unresolved on screen.
    seasonWinningsCents: 0,
    seasonOpeningCents: p.season_advance_cents,
    addedStakesCents: p.topoff_issued_cents,
  }));
  SERVER_RECONCILIATION = reconciliation;
  COMM_MODE = COMM_MODE_AUTHORITATIVE;
}

/**
 * Enter production UNAVAILABLE mode — the ordinary-GM case.
 *
 * /ledger/positions and /ledger/reconciliation are commissioner surfaces, so a
 * GM's session gets 403 for both. That is an EXPECTED CAPABILITY STATE, not an
 * application failure: the correct response is an empty authoritative set and
 * a surface that says so. Falling back to `GM_POSITIONS` here would show a GM
 * twelve fabricated league positions, which is the exact defect the first
 * shell binding exposed.
 */
export function markCommissionerUnavailable() {
  POSITIONS_SOURCE = [];
  SERVER_RECONCILIATION = null;
  COMM_MODE = COMM_MODE_UNAVAILABLE;
}

/** The current mode. @returns {'demo'|'authoritative'|'unavailable'} */
export function commissionerMode() {
  return COMM_MODE;
}

/** Restore the illustrative league. Used on sign-out and by the suites. */
export function unbindCommissioner() {
  POSITIONS_SOURCE = GM_POSITIONS;
  SERVER_RECONCILIATION = null;
  COMM_MODE = COMM_MODE_DEMO;
}

/** Whether the cards currently drawn came from the backend. */
export function isCommissionerBound() {
  return COMM_MODE === COMM_MODE_AUTHORITATIVE;
}

/** The server's own reconciliation, when bound — for comparison. */
export function boundReconciliation() {
  return SERVER_RECONCILIATION;
}

/** Every GM's position, in league order. */
export function gmPositions() {
  return POSITIONS_SOURCE.map(gmPosition);
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

  // When bound, the open-Top-Off figures come from the server's own
  // reconciliation rather than from the illustrative request list. The
  // SETTLEMENT treatment is identical either way — reported, never counted —
  // so binding changes the numbers and not the accounting.
  const serverOpen = SERVER_RECONCILIATION
    && SERVER_RECONCILIATION.exceptions
    && SERVER_RECONCILIATION.exceptions.open_top_offs;
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
        count: serverOpen ? serverOpen.count : open.length,
        cents: serverOpen ? serverOpen.cents
                          : open.reduce((t, r) => t + r.amount_cents, 0),
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