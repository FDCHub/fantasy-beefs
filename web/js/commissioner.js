/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Commissioner surfaces
 * Sprint 7 Package 4
 *
 * Three sections in the locked Rev 4.2 order:
 *
 *     A · Top-Off Requests
 *     B · GM Ledger Cards · 12 · Tap to Expand
 *     C · League Reconciliation
 *
 * B BEFORE C IS LOCKED. A commissioner reads the twelve positions before the
 * league roll-up, because the roll-up is those twelve added together — the
 * older ordering put the conclusion before its evidence.
 *
 * NOTHING HERE DECIDES ANYTHING. The Top-Off decision routes exist, are
 * governed, and post real Credits with a disclosure event on approval. S8-P1
 * gave the app an authenticated session, so an acting commissioner CAN now be
 * named — but the twelve positions this tab draws are still illustrative, and
 * deciding a real posting against figures that were never read would be worse
 * than deciding one attributed to nobody. The controls are therefore still
 * demonstrative and say so in the surface itself, not only in a comment — see
 * `COMMISSIONER_AUTH_SEAM`.
 * ========================================================================== */

import { escapeHtml, note, sectionHeading } from './components.js';
import { formatCredits, formatSignedCredits } from './credits.js';
import { ledgerRow } from './ledger.js';
import {
  COMM_MODE_AUTHORITATIVE,
  COMM_MODE_UNAVAILABLE,
  COMMISSIONER_AUTH_SEAM,
  commissionerMode,
  LEAGUE_POSITIONS_SEAM,
  TOPOFF_ROUTES,
  gmPositions,
  hasProvenance,
  leagueReconciliation,
  requestsByState,
  topOffState,
} from './commissioner-model.js';
import { LEAGUE_SIZE, TOPOFF_REQUESTS } from './data/commissioner-data.js';

/** Locked Rev 4.2 headings. */
export const COMMISSIONER_HEADING = 'COMMISSIONER';
export const TOPOFF_HEADING = 'A · TOP-OFF REQUESTS';
/**
 * The GM-cards heading.
 *
 * COUNT COMES FROM THE POSITIONS ACTUALLY HELD, not from a constant. Rev 4.2
 * shows twelve because the illustrative league has twelve teams; a bound
 * league of eight must say eight, and an unavailable session must not claim a
 * count at all.
 *
 * @param {number} count
 * @returns {string}
 */
export function gmCardsHeading(count) {
  return `B · GM LEDGER CARDS · ${count} · TAP TO EXPAND`;
}

/** The demo-mode heading, kept for the component suites' locked-copy check. */
export const GM_CARDS_HEADING = gmCardsHeading(LEAGUE_SIZE);
export const RECONCILIATION_HEADING = 'C · LEAGUE RECONCILIATION';

/** The locked section order. Asserted by the suites rather than assumed. */
export const COMMISSIONER_SECTIONS = Object.freeze(['topoffs', 'gm-cards', 'reconciliation']);

const teamName = (teamId) => {
  const found = gmPositions().find((p) => p.teamId === teamId);
  return found ? found.name : teamId;
};

/* ── A · Top-Off Requests ───────────────────────────────────────────────────*/

function requestRow(request) {
  const state = topOffState(request);
  return (
    `<button type="button" class="fs-req" data-request="${request.id}">` +
    `<span class="fs-req__state is-${state.id}">${escapeHtml(state.label)}</span>` +
    '<span class="fs-req__main">' +
    `<span class="fs-req__team">${escapeHtml(teamName(request.team_id))}</span>` +
    `<span class="fs-req__meta">#${request.id} · ${escapeHtml(request.created_at.slice(0, 10))}` +
    `${request.self_approved ? ' · self-approved' : ''}</span>` +
    '</span>' +
    `<span class="fs-req__amount fs-money" data-exact-cents="${request.amount_cents}">` +
    `${escapeHtml(formatCredits(request.amount_cents))}</span>` +
    '</button>'
  );
}

export function topOffSection() {
  const groups = requestsByState();
  const open = groups.find((g) => g.state.id === 'pending').requests;

  const body = groups
    .filter((g) => g.requests.length > 0)
    .map((g) => (
      `<div class="fs-reqgroup" data-state="${g.state.id}">` +
      `<div class="fs-reqgroup__head">${escapeHtml(g.state.label)} · ${g.requests.length}</div>` +
      g.requests.map(requestRow).join('') +
      '</div>'
    ))
    .join('');

  return (
    '<section class="fs-comsec" data-commissioner="topoffs">' +
    sectionHeading(TOPOFF_HEADING, `${open.length} awaiting`) +
    `<div class="fs-reqs" id="fs-topoff-requests">${body}</div>` +
    '<div class="fs-note">A GM requests; an authorised league commissioner ' +
    'approves or rejects; approval posts a balanced issuance and the Credits ' +
    'reach the GM’s wallet. Nothing is issued until then.</div>' +
    '</section>'
  );
}

/**
 * One request's detail, with its decision controls.
 *
 * The controls are rendered because the lifecycle surface is the deliverable —
 * and they are disabled, labelled, and explained, because firing an approval
 * from this build would attribute an irreversible ledger posting and a
 * disclosure event to no identifiable commissioner.
 */
export function requestSheet(request) {
  const state = topOffState(request);
  const decidable = state.id === 'pending';

  const rows = [
    ['Request', `#${request.id}`],
    ['Team', teamName(request.team_id)],
    ['Season', String(request.season)],
    ['Requested by', `user ${request.requester_user_id}`],
    ['Amount', formatCredits(request.amount_cents)],
    ['decision', request.decision],
    ['status', request.status],
  ];
  if (request.decided_by_user_id !== null) rows.push(['Decided by', `user ${request.decided_by_user_id}`]);
  if (request.decided_at) rows.push(['Decided at', request.decided_at]);
  if (request.self_approved !== null) rows.push(['Self-approved', String(request.self_approved)]);
  if (request.decision_reason) rows.push(['Reason', request.decision_reason]);

  // The provenance chain is the whole reason a commissioner can traverse an
  // approval: request → posting → both ledger legs → disclosure.
  const provenance = hasProvenance(request)
    ? '<div class="fs-prov"><div class="fs-prov__head">PROVENANCE</div>' +
      `<div class="fs-prov__row"><span>ledger_posting_id</span><code>${escapeHtml(request.ledger_posting_id)}</code></div>` +
      `<div class="fs-prov__row"><span>disclosure_event_id</span><code>${escapeHtml(request.disclosure_event_id)}</code></div>` +
      '</div>'
    : '<div class="fs-note">No ledger posting and no disclosure event — only an ' +
      'approved request carries them, and a row holding either without the other ' +
      'is unrepresentable.</div>';

  const controls = decidable
    ? '<div class="fs-decide">' +
      ['Approve', 'Reject', 'Cancel'].map((label) => (
        `<button type="button" class="fs-btn fs-decide__btn" data-decide="${label.toLowerCase()}" disabled>` +
        `${label}</button>`
      )).join('') +
      '</div>' +
      // S8-P1 CORRECTION. This said the build had no authenticated session
      // naming the acting commissioner. It has one now, so that sentence
      // became false — and false in the worst possible place: a warning
      // explaining to a commissioner why a control is disabled. The reason it
      // is STILL disabled is the other half of the seam.
      '<div class="fs-note is-warn">Demonstration only — no decision is ' +
      'transmitted. Approving posts Credits and writes a disclosure event, and ' +
      'the positions on this tab are illustrative rather than read from the ' +
      'ledger — a real decision needs real figures under it. ' +
      `The governed commands are <code>${escapeHtml(TOPOFF_ROUTES.approve)}</code>, ` +
      `<code>${escapeHtml(TOPOFF_ROUTES.reject)}</code> and ` +
      `<code>${escapeHtml(TOPOFF_ROUTES.cancel)}</code>; this surface implements ` +
      'no issuance of its own.</div>'
    : '<div class="fs-note">Decided. A repeat of the same decision replays the ' +
      'original answer; a different one against a settled request is refused.</div>';

  return {
    title: `Top-Off · ${teamName(request.team_id)}`,
    sub: `${state.label} · ${formatCredits(request.amount_cents)}`,
    body:
      rows.map(([label, value]) => (
        '<div class="fs-prev__row">' +
        `<span class="fs-prev__label">${escapeHtml(label)}</span>` +
        `<span class="fs-prev__value">${escapeHtml(value)}</span></div>`
      )).join('') +
      provenance +
      controls,
  };
}

/* ── B · GM Ledger Cards ────────────────────────────────────────────────────*/

function gmCard(position) {
  const cells = [
    ['Available', position.spendableCents],
    ['In Play', position.acceptedEscrowCents],
    ['Held', position.heldCents],
  ];

  return (
    `<button type="button" class="fs-gmcard" data-gm="${escapeHtml(position.teamId)}">` +
    '<span class="fs-gmcard__head">' +
    `<span class="fs-gmcard__name">${escapeHtml(position.name)}</span>` +
    `<span class="fs-gmcard__settle fs-money${position.currentSettleCents < 0 ? ' is-negative' : ' is-positive'}" ` +
    `data-exact-cents="${position.currentSettleCents}">` +
    `${escapeHtml(formatSignedCredits(position.currentSettleCents))}</span>` +
    '</span>' +
    '<span class="fs-gmcard__cells">' +
    cells.map(([label, cents]) => (
      '<span class="fs-gmcard__cell">' +
      `<span class="fs-gmcard__label">${escapeHtml(label)}</span>` +
      `<span class="fs-gmcard__value fs-money" data-exact-cents="${cents}">` +
      `${escapeHtml(formatCredits(cents))}</span></span>`
    )).join('') +
    '</span>' +
    '<span class="fs-gmcard__foot">Current Settle · tap to expand</span>' +
    '</button>'
  );
}

export function gmCardsSection() {
  const mode = commissionerMode();

  // UNAVAILABLE IS NOT AN ERROR AND IS NOT DEMO. An ordinary GM's session gets
  // 403 from /ledger/positions because it is a commissioner surface — an
  // expected capability state. What must never happen is falling through to
  // the illustrative twelve, which would show a GM a league of fabricated
  // positions. So the section renders empty and says why.
  if (mode === COMM_MODE_UNAVAILABLE) {
    return (
      '<section class="fs-comsec" data-commissioner="gm-cards" ' +
      'data-state="unavailable">' +
      sectionHeading('B · GM LEDGER CARDS') +
      '<div class="fs-gmcards" id="fs-gm-cards"></div>' +
      note('League positions are not available to this session. Reading every ' +
           'GM’s position requires commissioner authority for this league.',
           { pending: true }) +
      '</section>'
    );
  }

  const positions = gmPositions();
  const provenance = mode === COMM_MODE_AUTHORITATIVE
    ? 'Read from <code>GET /league/{league_id}/ledger/positions</code>. Every ' +
      'card is that GM’s own Current Settle, produced by the arithmetic their ' +
      'own Ledger tab performs.'
    : 'Illustrative league state. These figures are the POR’s, not a read.';

  return (
    '<section class="fs-comsec" data-commissioner="gm-cards" ' +
    `data-state="${escapeHtml(mode)}">` +
    sectionHeading(gmCardsHeading(positions.length)) +
    `<div class="fs-gmcards" id="fs-gm-cards">${positions.map(gmCard).join('')}</div>` +
    `<div class="fs-note">${provenance}</div>` +
    '</section>'
  );
}

/**
 * One GM's position, in the Ledger's own statement grammar.
 *
 * Same rows, same order, same arithmetic as that GM's own Ledger tab — because
 * it IS that arithmetic, run through `ledger-model.currentSettleCents()`.
 */
export function gmSheet(position) {
  return {
    title: position.name,
    sub: 'Commissioner view · this GM’s position',
    body:
      '<div class="fs-lsec__body">' +
      ledgerRow({ label: 'Spendable Credits', cents: position.spendableCents }) +
      ledgerRow({ label: 'Accepted wager escrow', cents: position.acceptedEscrowCents }) +
      ledgerRow({ label: 'Weekly reserve not yet released', cents: position.weeklyReserveNotReleasedCents }) +
      ledgerRow({ label: 'Wagering Position', cents: position.wageringPositionCents, signed: true, total: true }) +
      '</div>' +
      '<div class="fs-lsec__body">' +
      ledgerRow({ label: 'Weekly Min · out of circulation', cents: position.weeklyMinOutOfCirculationCents, signed: true }) +
      ledgerRow({ label: 'Skunk Fees', cents: position.skunkFeesCents, signed: true }) +
      ledgerRow({ label: 'Season winnings earned', cents: position.seasonWinningsCents, signed: true }) +
      ledgerRow({ label: 'Net Adjustments + Winnings', cents: position.netAdjustmentsCents, signed: true, total: true }) +
      '</div>' +
      '<div class="fs-lsec__body">' +
      ledgerRow({ label: 'Season-Opening FantasyStakes', cents: position.seasonOpeningCents, lead: true }) +
      ledgerRow({ label: 'Added Stakes', cents: position.addedStakesCents, signed: true }) +
      ledgerRow({ label: 'Total Virtual Stakes', cents: position.totalVirtualStakesCents, total: true }) +
      '</div>' +
      '<div class="fs-settle">' +
      '<div class="fs-settle__head">CURRENT SETTLE</div>' +
      '<div class="fs-settle__result">' +
      `<span class="fs-settle__label">${escapeHtml(position.name)}</span>` +
      `<span class="fs-settle__total fs-money${position.currentSettleCents < 0 ? ' is-negative' : ' is-positive'}" ` +
      `data-exact-cents="${position.currentSettleCents}">` +
      `${escapeHtml(formatSignedCredits(position.currentSettleCents))}</span>` +
      '</div></div>' +
      (position.heldCents > 0
        ? `<div class="fs-note">${escapeHtml(formatCredits(position.heldCents))} is held against open ` +
          'offers. It reduces what this GM can spend and is not counted again in ' +
          'Current Settle until a proposal is accepted.</div>'
        : '') +
      '<div class="fs-note">Wagering Position + Net Adjustments − Total Virtual ' +
      'Stakes, the same arithmetic this GM’s own Ledger performs.</div>',
  };
}

/* ── C · League Reconciliation ──────────────────────────────────────────────*/

export function reconciliationSection() {
  const r = leagueReconciliation();
  const ex = r.exceptions;

  // A figure that is INSIDE a total carries its sign, because the sign is what
  // it contributes. A figure that is outside every total is a quantity under
  // consideration, and drawing it as `+$75` would imply a credit that no total
  // received.
  const exceptionRow = (label, item) => (
    '<div class="fs-exrow">' +
    `<span class="fs-exrow__label">${escapeHtml(label)}</span>` +
    `<span class="fs-exrow__count">${item.count}</span>` +
    `<span class="fs-exrow__value fs-money" data-exact-cents="${item.cents}">` +
    `${escapeHtml(item.settlementLiability
      ? formatSignedCredits(item.cents)
      : formatCredits(Math.abs(item.cents)))}</span>` +
    `<span class="fs-exrow__flag${item.settlementLiability ? ' is-liability' : ''}">` +
    `${item.settlementLiability ? 'in settlement' : 'not a liability'}</span>` +
    '</div>' +
    `<div class="fs-exrow__note">${escapeHtml(item.note)}</div>`
  );

  return (
    '<section class="fs-comsec" data-commissioner="reconciliation">' +
    sectionHeading(RECONCILIATION_HEADING) +
    '<div class="fs-lsec__body">' +
    ledgerRow({ label: `Total Virtual Stakes · ${r.teams} GMs`, cents: -r.totalVirtualStakesCents }) +
    ledgerRow({ label: 'Aggregate Wagering Position', cents: r.wageringPositionCents, signed: true }) +
    ledgerRow({ label: 'Aggregate Adjustments + Winnings', cents: r.netAdjustmentsCents, signed: true }) +
    ledgerRow({ label: 'League Current Settle', cents: r.aggregateSettleCents, signed: true, total: true }) +
    '</div>' +

    // The check that makes this a reconciliation rather than a summary: the sum
    // of the twelve GM figures and the aggregate of their terms must agree.
    `<div class="fs-closes${r.closes ? ' is-ok' : ' is-off'}" data-closes="${r.closes}">` +
    `<span class="fs-closes__mark">${r.closes ? '✓' : '✕'}</span>` +
    `<span>The twelve GM positions sum to the league figure — ` +
    `<span class="fs-money" data-exact-cents="${r.sumOfGmSettlesCents}">` +
    `${escapeHtml(formatSignedCredits(r.sumOfGmSettlesCents))}</span> either way.</span>` +
    '</div>' +

    '<div class="fs-exgroup"><div class="fs-exgroup__head">EXCEPTIONS &amp; PENDING</div>' +
    exceptionRow('Open Top-Off requests', ex.openTopOffs) +
    exceptionRow('Pending offer holds', ex.pendingOfferHolds) +
    exceptionRow('Skunk receivables', ex.skunkReceivables) +
    '</div>' +

    '<div class="fs-integrity">' +
    `<div class="fs-integrity__head">INTEGRITY · ${r.integrity.verified ? 'VERIFIED' : 'NOT VERIFIED HERE'}</div>` +
    `<div class="fs-integrity__body">${escapeHtml(r.integrity.invariant)} ` +
    `It is computed by <code>${escapeHtml(r.integrity.seam.computation)}</code>, which has no ` +
    'HTTP surface and is global rather than league-scoped — so this surface ' +
    'states the invariant and does not claim to have checked it.</div>' +
    '</div>' +
    '</section>'
  );
}

/* ── Assembly and binding ───────────────────────────────────────────────────*/

/**
 * The whole commissioner area, in the locked order.
 *
 * @returns {string}
 */
export function commissionerArea() {
  return (
    '<section class="fs-commish" id="fs-commissioner">' +
    `<div class="fs-commish__head">${escapeHtml(COMMISSIONER_HEADING)}</div>` +
    topOffSection() +
    gmCardsSection() +
    reconciliationSection() +
    '</section>'
  );
}

/**
 * @param {HTMLElement} panel
 * @param {{openSheet: Function}} api
 */
export function bindCommissioner(panel, api) {
  panel.querySelectorAll('[data-request]').forEach((el) => {
    el.addEventListener('click', () => {
      const request = TOPOFF_REQUESTS.find((r) => String(r.id) === el.dataset.request);
      if (request) api.openSheet(requestSheet(request));
    });
  });

  const positions = gmPositions();
  panel.querySelectorAll('[data-gm]').forEach((el) => {
    el.addEventListener('click', () => {
      const position = positions.find((p) => p.teamId === el.dataset.gm);
      if (position) api.openSheet(gmSheet(position));
    });
  });
}

/** Exposed for the suites: the seam this area is blocked on. */
export { COMMISSIONER_AUTH_SEAM, LEAGUE_POSITIONS_SEAM };