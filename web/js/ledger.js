/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Ledger
 * Sprint 7 Package 3
 *
 * "Four-cell strips show the answer. Ledger shows the math."
 *
 * Every other tab summarises a position. This one explains it, and the
 * explanation has to close: each section adds its own rows to its own total,
 * and the three section totals produce Current Settle. Nothing is typed twice —
 * `ledger-model.js` derives every total from the terms, so a figure on screen
 * and the rows above it cannot disagree.
 *
 * THE RECONCILIATION IS THE PAGE. There is no `View Full Reconciliation`
 * anywhere in this file and no route to one: the three sections ARE the full
 * reconciliation, and a link promising a fuller one would be promising
 * something that does not exist. For the same reason the Current Settle card is
 * inert — it is the result of the page, not a door to another.
 * ========================================================================== */

import { PanelComposer, escapeHtml } from './components.js';
import { formatCredits, formatSignedCredits } from './credits.js';
import {
  CHAMPIONSHIPS,
  POOL_ENTRIES_SUPPORT,
  POOL_PAYOUTS_SUPPORT,
  PENDING_OFFER_HOLD_CENTS,
  SEASON_AWARDS,
  VERSUS_LOSSES_SUPPORT,
  VERSUS_WINS_SUPPORT,
  WEEK_STRIP,
  BET_RECORD,
} from './data/ledger-data.js';
import { TOPOFF_COMMAND_SEAM, reconciliation, supportingRows } from './ledger-model.js';

/** Locked Rev 4.2 header copy. */
export const LEDGER_TITLE = 'FANTASYSTAKES LEDGER';
export const LEDGER_SUBTITLE = 'My Week 5 · Regular Season';
export const MY_SEASON_LABEL = 'My Season';
export const TOPOFF_LABEL = 'Request Top-Off';

/* ── Header ─────────────────────────────────────────────────────────────────*/

/**
 * The Ledger header.
 *
 * Built from the shared `.fs-tabhead` structure rather than a new one, so the
 * title and subtitle carry exactly the typography every other tab uses. Request
 * Top-Off sits in the aside as a small TEXT control — Rev 4.2 demotes it from a
 * button and it is emphatically not a summary cell competing with the strip.
 *
 * @returns {string}
 */
function ledgerHeader() {
  return (
    '<div class="fs-tabhead">' +
    '<div class="fs-tabhead__main">' +
    `<div class="fs-tabhead__title">${escapeHtml(LEDGER_TITLE)}</div>` +
    `<div class="fs-tabhead__sub">${escapeHtml(LEDGER_SUBTITLE)}</div>` +
    '</div>' +
    '<div class="fs-tabhead__aside">' +
    `<button type="button" class="fs-topoff" data-topoff>${escapeHtml(TOPOFF_LABEL)}</button>` +
    '</div>' +
    '</div>'
  );
}

/* ── Row primitives ─────────────────────────────────────────────────────────*/

/**
 * One reconciliation row.
 *
 * Exported as `ledgerRow` so the commissioner's per-GM detail is drawn in this
 * grammar rather than a second one. A commissioner reading a GM's position
 * should be reading the same statement the GM reads.
 *
 * @param {{label: string, cents?: number, text?: string, level?: number,
 *   signed?: boolean, total?: boolean, lead?: boolean, id?: string}} spec
 * @returns {string}
 */
export function ledgerRow(spec) {
  const { label, cents, text, level = 0, signed = false, total = false, lead = false, id = '' } = spec;

  const classes = ['fs-lrow'];
  if (level) classes.push(`is-level${level}`);
  if (total) classes.push('is-total');
  if (lead) classes.push('is-lead');

  let valueHtml;
  if (typeof cents === 'number') {
    const drawn = signed ? formatSignedCredits(cents) : formatCredits(cents);
    const tone = cents > 0 && signed ? ' is-positive' : (cents < 0 ? ' is-negative' : '');
    valueHtml =
      `<span class="fs-lrow__value fs-money${tone}" data-exact-cents="${cents}">` +
      `${escapeHtml(drawn)}</span>`;
  } else {
    valueHtml = `<span class="fs-lrow__value is-state">${escapeHtml(text)}</span>`;
  }

  // The ↳ is a child marker, not decoration: it is what makes the arithmetic
  // of the advances hierarchy legible without a diagram.
  const marker = level ? '<span class="fs-lrow__mark">↳</span>' : '';

  return (
    `<div class="${classes.join(' ')}"${id ? ` id="${escapeHtml(id)}"` : ''}>` +
    `<span class="fs-lrow__label">${marker}${escapeHtml(label)}</span>` +
    valueHtml +
    '</div>'
  );
}

/**
 * A row whose supporting detail can be expanded.
 *
 * AUDIT SURFACE ONLY. The expansion shows what is behind the figure; it never
 * contributes to a total, and the rows it reveals are closed against the
 * header figure by `supportingRows()` so an expansion always adds up to the row
 * it expands.
 *
 * @param {{label: string, cents: number, signed?: boolean, items: Array<object>, key: string}} spec
 * @returns {string}
 */
function expandableRow(spec) {
  const { label, cents, signed = true, items, key } = spec;
  const detail = supportingRows(items, cents);

  return (
    `<div class="fs-lexp" data-expand="${escapeHtml(key)}">` +
    `<button type="button" class="fs-lexp__head" aria-expanded="false">` +
    `<span class="fs-lrow__label"><span class="fs-lexp__chev">›</span>${escapeHtml(label)}</span>` +
    `<span class="fs-lrow__value fs-money${cents < 0 ? ' is-negative' : ' is-positive'}" ` +
    `data-exact-cents="${cents}">${escapeHtml(formatSignedCredits(cents))}</span>` +
    '</button>' +
    '<div class="fs-lexp__body">' +
    detail.map((item) => (
      '<div class="fs-lexp__row">' +
      `<span class="fs-lexp__label">${escapeHtml(item.label)}</span>` +
      `<span class="fs-lexp__value fs-money" data-exact-cents="${item.cents}">` +
      `${escapeHtml(formatSignedCredits(item.cents))}</span>` +
      '</div>'
    )).join('') +
    '</div></div>'
  );
}

function ledgerSection(spec) {
  const { number, title, sub, body, elevated = false } = spec;
  return (
    `<section class="fs-lsec${elevated ? ' is-elevated' : ''}" data-section="${number}">` +
    `<div class="fs-lsec__head"><span class="fs-lsec__num">${number}</span>` +
    `<span class="fs-lsec__title">${escapeHtml(title)}</span></div>` +
    `<div class="fs-lsec__sub">${escapeHtml(sub)}</div>` +
    `<div class="fs-lsec__body">${body}</div>` +
    '</section>'
  );
}

/* ── Sections ───────────────────────────────────────────────────────────────*/

function advancesSection(r) {
  const a = r.advances;
  return ledgerSection({
    number: '1',
    title: 'FANTASYSTAKES ADVANCES',
    sub: 'Virtual stakes advanced to you for the season.',
    body:
      // Season-Opening is a PARENT of its two components and a SIBLING of Added
      // Stakes. Nesting Added Stakes underneath would claim it was part of the
      // opening allocation, which it is not.
      ledgerRow({ label: 'Season-Opening FantasyStakes', cents: a.seasonOpeningCents, lead: true }) +
      ledgerRow({ label: 'Regular Season Minimum Stakes', cents: a.regularSeasonMinimumCents, level: 1 }) +
      ledgerRow({ label: 'Playoffs / Championship Stakes', cents: a.playoffsChampionshipCents, level: 1 }) +
      ledgerRow({ label: 'Added Stakes', cents: a.addedStakesCents, signed: true, lead: true }) +
      ledgerRow({ label: 'Total Virtual Stakes', cents: a.totalVirtualStakesCents, total: true }),
  });
}

function wageringSection(r) {
  const act = r.activity;
  const pos = r.position;

  const versus =
    '<div class="fs-lgroup"><div class="fs-lgroup__head">VERSUS ACTIVITY</div>' +
    expandableRow({
      label: 'Settled wins', cents: act.settledWinsCents,
      items: VERSUS_WINS_SUPPORT, key: 'versus-wins',
    }) +
    expandableRow({
      label: 'Settled losses', cents: act.settledLossesCents,
      items: VERSUS_LOSSES_SUPPORT, key: 'versus-losses',
    }) +
    ledgerRow({ label: 'Net Versus', cents: act.netVersusCents, signed: true, total: true }) +
    '</div>';

  const pools =
    '<div class="fs-lgroup"><div class="fs-lgroup__head">POOL ACTIVITY</div>' +
    expandableRow({
      label: 'Pool payouts', cents: act.poolPayoutsCents,
      items: POOL_PAYOUTS_SUPPORT, key: 'pool-payouts',
    }) +
    expandableRow({
      label: 'Pool entries', cents: act.poolEntriesCents,
      items: POOL_ENTRIES_SUPPORT, key: 'pool-entries',
    }) +
    ledgerRow({ label: 'Net Pools', cents: act.netPoolsCents, signed: true, total: true }) +
    '</div>';

  const positionGroup =
    '<div class="fs-lgroup"><div class="fs-lgroup__head">CURRENT WAGER POSITION</div>' +
    ledgerRow({ label: 'Spendable Credits', cents: pos.spendableCents }) +
    ledgerRow({ label: 'Accepted wager escrow', cents: pos.acceptedEscrowCents }) +
    ledgerRow({ label: 'Weekly reserve not yet released', cents: pos.weeklyReserveNotReleasedCents }) +
    ledgerRow({ label: 'Wagering Position', cents: pos.wageringPositionCents, signed: true, total: true }) +
    '</div>';

  // The memo is the anti-double-counting rule stated to the GM in the same
  // words the model enforces it in.
  const memo =
    '<div class="fs-lmemo">' +
    `<span class="fs-lmemo__mark">MEMO</span> Pending offer holds reduce what you can spend, ` +
    'but are not counted again in Current Settle until a proposal is accepted. ' +
    `Currently held: <span class="fs-money" data-exact-cents="${PENDING_OFFER_HOLD_CENTS}">` +
    `${escapeHtml(formatCredits(PENDING_OFFER_HOLD_CENTS))}</span>.` +
    '</div>';

  return ledgerSection({
    number: '2',
    title: 'WAGERING SUMMARY',
    sub: 'The four-cell strips show where you stand. This section shows what created that position.',
    elevated: true,
    body: versus + pools + positionGroup + memo,
  });
}

function adjustmentsSection(r) {
  const adj = r.adjustments;

  const awardsDetail = SEASON_AWARDS.map((award) => (
    '<div class="fs-lexp__row">' +
    `<span class="fs-lexp__label">${escapeHtml(award.label)}</span>` +
    (typeof award.cents === 'number'
      ? `<span class="fs-lexp__value fs-money" data-exact-cents="${award.cents}">` +
        `${escapeHtml(formatSignedCredits(award.cents))}</span>`
      : `<span class="fs-lexp__value is-state">${escapeHtml(award.state)}</span>`) +
    '</div>'
  )).join('');

  return ledgerSection({
    number: '3',
    title: 'SEASON ADJUSTMENTS + WINNINGS',
    sub: 'Amounts outside ordinary Versus and Pool wagering.',
    body:
      ledgerRow({ label: 'Weekly Min · out of circulation', cents: adj.weeklyMinOutOfCirculationCents, signed: true }) +
      ledgerRow({ label: 'Skunk Fees', cents: adj.skunkFeesCents }) +
      '<div class="fs-lexp" data-expand="season-winnings">' +
      '<button type="button" class="fs-lexp__head" aria-expanded="false">' +
      '<span class="fs-lrow__label"><span class="fs-lexp__chev">›</span>Season winnings earned</span>' +
      `<span class="fs-lrow__value fs-money is-positive" data-exact-cents="${adj.seasonWinningsCents}">` +
      `${escapeHtml(formatSignedCredits(adj.seasonWinningsCents))}</span>` +
      '</button>' +
      `<div class="fs-lexp__body">${awardsDetail}` +
      '<div class="fs-note">Rev 4.2 fixes the total; the per-award split is not yet ' +
      'specified, and the Skunk pot distributes at season close rather than weekly.</div>' +
      '</div></div>' +
      CHAMPIONSHIPS.map((c) => ledgerRow({ label: c.label, text: c.state })).join('') +
      ledgerRow({ label: 'Net Adjustments + Winnings', cents: adj.netAdjustmentsCents, signed: true, total: true }),
  });
}

/**
 * The Current Settle card.
 *
 * A plain `div`, deliberately: no button, no tap target, no `data-card-action`.
 * It shows its three inputs and the result, and the three inputs are the three
 * section totals above it — so the card can be checked against the page without
 * going anywhere.
 */
function currentSettleCard(r) {
  const rows = [
    { label: 'Total Virtual Stakes', cents: -r.advances.totalVirtualStakesCents },
    { label: 'Wagering Position', cents: r.position.wageringPositionCents },
    { label: 'Net Adjustments + Winnings', cents: r.adjustments.netAdjustmentsCents },
  ];

  return (
    '<section class="fs-settle" id="fs-current-settle">' +
    '<div class="fs-settle__head">CURRENT SETTLE</div>' +
    rows.map((item) => (
      '<div class="fs-settle__row">' +
      `<span class="fs-settle__label">${escapeHtml(item.label)}</span>` +
      `<span class="fs-settle__value fs-money${item.cents < 0 ? ' is-negative' : ' is-positive'}" ` +
      `data-exact-cents="${item.cents}">${escapeHtml(formatSignedCredits(item.cents))}</span>` +
      '</div>'
    )).join('') +
    '<div class="fs-settle__result">' +
    '<span class="fs-settle__label">Current Settle</span>' +
    `<span class="fs-settle__total fs-money${r.currentSettleCents < 0 ? ' is-negative' : ' is-positive'}" ` +
    `data-exact-cents="${r.currentSettleCents}">` +
    `${escapeHtml(formatSignedCredits(r.currentSettleCents))}</span>` +
    '</div>' +
    '<div class="fs-note">You owe the league when this is negative. Figures are ' +
    'derived from posted Ledger state; nothing on this card moves Credits.</div>' +
    '</section>'
  );
}

/* ── Panel ──────────────────────────────────────────────────────────────────*/

/**
 * @returns {string}
 */
export function buildLedgerPanel() {
  const composer = new PanelComposer('ledger');
  const r = reconciliation();

  composer.add(ledgerHeader());

  composer.addStrip({
    id: 'fs-strip-ledger',
    label: 'My week',
    cells: [
      { label: 'Available', cents: WEEK_STRIP.availableCents, anchor: true },
      { label: 'In Play', cents: WEEK_STRIP.inPlayCents },
      { label: 'Held', cents: WEEK_STRIP.heldCents },
      { label: 'Weekly Min Left', cents: WEEK_STRIP.weeklyMinLeftCents },
    ],
  });

  composer.addDisclaimer();

  // The approved second strip. Its label reuses the subtitle typography of
  // `My Week 5` rather than introducing a heading style for one line.
  composer.add(`<div class="fs-tabhead__sub fs-seasonlabel">${escapeHtml(MY_SEASON_LABEL)}</div>`);
  composer.addStrip({
    id: 'fs-strip-season',
    label: 'My season',
    cells: [
      { label: 'Bet Record', text: BET_RECORD },
      { label: 'Versus + Pools', cents: r.versusPlusPoolsCents, signed: true },
      { label: 'Awards / Adj.', cents: r.adjustments.netAdjustmentsCents, signed: true },
      { label: 'Current Settle', cents: r.currentSettleCents, signed: true, gold: true },
    ],
  });

  composer.add(
    '<div class="fs-lscroll">' +
    advancesSection(r) +
    wageringSection(r) +
    adjustmentsSection(r) +
    currentSettleCard(r) +
    '</div>',
  );

  return composer.toHTML();
}

/**
 * Wire the Ledger's two interactions: expanding supporting detail, and the
 * read-only Top-Off control.
 *
 * @param {HTMLElement} panel
 * @param {{openSheet: Function}} api
 */
export function bindLedger(panel, api) {
  panel.querySelectorAll('[data-expand] .fs-lexp__head').forEach((head) => {
    head.addEventListener('click', () => {
      const holder = head.parentElement;
      const open = holder.classList.toggle('is-open');
      head.setAttribute('aria-expanded', String(open));
    });
  });

  const topoff = panel.querySelector('[data-topoff]');
  if (topoff) topoff.addEventListener('click', () => api.openSheet(topOffSheet()));
}

/**
 * Request Top-Off, read-only.
 *
 * The governed command already exists and is named here. What does not exist is
 * the web app's session binding, so this sheet explains the request and stops —
 * it does not collect an amount and post it through a path of its own devising.
 *
 * @returns {{title: string, sub: string, body: string}}
 */
export function topOffSheet() {
  return {
    title: TOPOFF_LABEL,
    sub: 'Ask the commissioner for additional virtual stakes',
    body:
      '<div class="fs-prev__row"><span class="fs-prev__label">Request goes to</span>' +
      '<span class="fs-prev__value">Your league commissioner</span></div>' +
      '<div class="fs-prev__row"><span class="fs-prev__label">Approval</span>' +
      '<span class="fs-prev__value">Required before Credits are issued</span></div>' +
      '<div class="fs-prev__row"><span class="fs-prev__label">Added so far</span>' +
      '<span class="fs-prev__value fs-money" data-exact-cents="4000">$40</span></div>' +
      '<div class="fs-note">Approved Top-Offs raise Total Virtual Stakes, which ' +
      'lowers Current Settle by the same amount. A Top-Off is an advance, not ' +
      'winnings.</div>' +
      `<div class="fs-note">Read-only in this build. The governed command is ` +
      `<code>${escapeHtml(TOPOFF_COMMAND_SEAM.endpoint)}</code>; this surface binds ` +
      'to it when the session seam lands, and implements no top-off path of its own.</div>',
  };
}