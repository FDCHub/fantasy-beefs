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

import { attributionFooter } from './attribution.js';
import { PanelComposer, bindAccordions, escapeHtml } from './components.js';
import { currentWeek } from './league-model.js';
import { weekPhaseLabel } from './phase.js';
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
import {
  MODE_AUTHORITATIVE,
  MODE_UNAVAILABLE,
  TOPOFF_COMMAND_SEAM,
  boundHeldCents,
  boundWeeklyMinLiveCents,
  MODE_DEMO,
  ledgerMode,
  reconciliation,
  seasonWinningsResolved,
  supportingRows,
} from './ledger-model.js';

/** Locked Rev 4.2 header copy. */
export const LEDGER_TITLE = 'FANTASYSTAKES LEDGER';
export const LEDGER_SUBTITLE = 'My Week 5 · Regular Season';

/**
 * The subtitle a signed-in GM reads.
 *
 * S8-P4C-5: `My Week 5` is a fixture string and was shown to every GM whatever
 * week their league was in. The locked grammar is preserved; only the number
 * becomes the league's own, and where no provider refresh has stated a week the
 * claim is dropped rather than guessed.
 *
 * @returns {string}
 */
export function ledgerSubtitle() {
  if (ledgerMode() === MODE_DEMO) return LEDGER_SUBTITLE;
  // WP3C — THE PHASE IS AUTHORITATIVE TOO (Rev 4.3 §17, §27). `Regular Season`
  // was a literal here, so a GM reading their Account in the championship week
  // was told it was the regular season. `phase.js` resolves week and phase from
  // the league's own boundaries; a session with neither says `My Week` alone
  // rather than asserting a phase it cannot state.
  const label = weekPhaseLabel(currentWeek());
  return label ? `My ${label}` : 'My Week';
}
/**
 * The locked Ledger / trust anchor — Rev 4.3 §2.
 *
 * EXACT TO THE CHARACTER, and asserted as such by the certification. It is a
 * locked brand string: the wording, the punctuation and the capitalisation may
 * not be altered, abbreviated or paraphrased.
 */
export const LEDGER_TRUST_ANCHOR = 'Real odds. Fantasy stakes. Ledger keeps score.';

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
    `<div class="fs-tabhead__sub">${escapeHtml(ledgerSubtitle())}</div>` +
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
  const { number, title, sub, body, elevated = false, open = false } = spec;

  // WP3C — THE SECTION IS A DISCLOSURE NOW (Rev 4.3 §14.2).
  //
  // WHAT THIS FIXES. The Account tab opened onto three full accounting sections
  // at once — advances, the whole wagering statement, adjustments — and a GM
  // whose question was "what is my Current Settle?" had to scroll past forty
  // rows to reach it. §14.2 asks for the top-level view to answer four
  // questions quickly and for the detail to move behind disclosure.
  //
  // NOTHING IS REMOVED, AND THAT IS THE OTHER HALF OF THE RULING. §14.2 is
  // explicit that authoritative detail stays available: every row that was on
  // the page is still on the page, one tap away, and the expanded section is
  // byte-identical to what Rev 4.2 rendered. Collapsing is presentation state
  // and nothing else — no read is deferred, no figure is dropped, and the
  // section is in the DOM whether it is open or shut, so assistive tech and
  // find-in-page still reach it.
  //
  // A REAL BUTTON WITH REAL `aria-expanded`, matching `expandableRow` above
  // rather than inventing a second disclosure grammar for the same tab.
  return (
    `<section class="fs-lsec fs-accordion${elevated ? ' is-elevated' : ''}` +
    `${open ? ' is-open' : ''}" data-section="${number}" data-disclosure>` +
    '<button type="button" class="fs-lsec__head fs-accordion__head" data-accordion-toggle data-lsec-toggle ' +
    `aria-expanded="${open ? 'true' : 'false'}">` +
    `<span class="fs-lsec__num fs-accordion__number">${number}</span>` +
    '<span class="fs-accordion__main">' +
    `<span class="fs-lsec__title fs-accordion__title">${escapeHtml(title)}</span>` +
    `<span class="fs-lsec__sub fs-accordion__sub">${escapeHtml(sub)}</span>` +
    '</span>' +
    '<span class="fs-lsec__chev fs-accordion__chev" aria-hidden="true">›</span></button>' +
    `<div class="fs-lsec__body fs-accordion__body">${body}</div>` +
    '</section>'
  );
}

/* ── Sections ───────────────────────────────────────────────────────────────*/

function advancesSection(r) {
  const a = r.advances;
  return ledgerSection({
    number: '1',
    // FINAL POR §30 — the approved public label. `Advances` reads as a loan
    // against a balance; what this section reports is the season's opening
    // allocation of virtual credits.
    title: 'OPENING FANTASYSTAKES ALLOCATION',
    sub: 'Virtual credits allocated to you for the season.',
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
    '<div class="fs-lgroup"><div class="fs-lgroup__head">MATCHUP ACTIVITY</div>' +
    expandableRow({
      label: 'Settled wins', cents: act.settledWinsCents,
      items: VERSUS_WINS_SUPPORT, key: 'versus-wins',
    }) +
    expandableRow({
      label: 'Settled losses', cents: act.settledLossesCents,
      items: VERSUS_LOSSES_SUPPORT, key: 'versus-losses',
    }) +
    ledgerRow({ label: 'Net Matchups', cents: act.netVersusCents, signed: true, total: true }) +
    '</div>';

  const pools =
    '<div class="fs-lgroup"><div class="fs-lgroup__head">PROP POOL ACTIVITY</div>' +
    expandableRow({
      label: 'Prop Pool payouts', cents: act.poolPayoutsCents,
      items: POOL_PAYOUTS_SUPPORT, key: 'pool-payouts',
    }) +
    expandableRow({
      label: 'Prop Pool entries', cents: act.poolEntriesCents,
      items: POOL_ENTRIES_SUPPORT, key: 'pool-entries',
    }) +
    ledgerRow({ label: 'Net Prop Pools', cents: act.netPoolsCents, signed: true, total: true }) +
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
    sub: 'Amounts outside ordinary Matchup and Prop Pool wagering.',
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
      '<div class="fs-note">The total is fixed; the per-award split is not yet ' +
      'specified, and the Skunk pot distributes at season close rather than weekly.</div>' +
      '</div></div>' +
      CHAMPIONSHIPS.map((c) => ledgerRow({ label: c.label, text: c.state })).join('') +
      ledgerRow({ label: 'Net Adjustments + Winnings', cents: adj.netAdjustmentsCents, signed: true, total: true }),
  });
}

/**
 * Section 4 — Current Settle.
 *
 * ── IT IS A PEER SECTION NOW, NOT A BESPOKE CARD (UIRECON Wave 2) ──────────
 *
 * What stood here was a `<section class="fs-settle">` with its own head, its
 * own row grammar, its own border and fill, and eighteen dedicated CSS rules —
 * sitting directly beneath three numbered `ledgerSection()` disclosures that
 * shared one construction between them. It was the only block on the tab that
 * was not a peer of its siblings, and it was the most important one.
 *
 * It renders through `ledgerSection()` now, so the header height, the number
 * treatment, the title typography, the chevron, the border, the spacing and the
 * expand/collapse behaviour are not "the same as" sections 1–3 — they ARE
 * sections 1–3's, because there is one function producing all four.
 *
 * ── WHY IT OPENS AND THEY DO NOT ───────────────────────────────────────────
 *
 * Rev 4.3 §14.2 is explicit: do not make Current Settle or key top-level
 * figures require expansion. Sections 1–3 are detail and open on demand; this
 * is the figure the whole tab exists to derive, and a GM who has to press
 * something to see it has been given a worse page than before.
 *
 * So the AFFORDANCE is identical — same button, same `aria-expanded`, same
 * chevron, same toggle through the same `[data-disclosure]` handler, and it
 * collapses like any other section when a GM chooses to. Only the INITIAL state
 * differs, and it differs for the one reason the POR names.
 *
 * ── WHAT DID NOT CHANGE ────────────────────────────────────────────────────
 *
 * Every figure, every `data-exact-cents`, the three input rows, the result row,
 * the note and the trust anchor. `id="fs-current-settle"` is kept so the
 * suites that locate this block still locate it. No arithmetic was touched:
 * the three inputs are still the three section totals above, which is what
 * lets the card be checked against the page without going anywhere.
 */
function currentSettleSection(r) {
  const rows = [
    { label: 'Total Virtual Stakes', cents: -r.advances.totalVirtualStakesCents },
    { label: 'Wagering Position', cents: r.position.wageringPositionCents },
    { label: 'Net Adjustments + Winnings', cents: r.adjustments.netAdjustmentsCents },
  ];

  const body =
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
    // THE LOCKED TRUST ANCHOR — Rev 4.3 §2 and §14.1, exact to the character.
    //
    // HERE AND NOWHERE ELSE. §14.1 asks for it "where appropriate" on Account
    // and the POR warns against over-repetition; the foot of the Current Settle
    // section is the one place on the tab where the claim is being made — this
    // is the number the whole page exists to derive, and the line says what
    // derived it.
    `<div class="fs-anchor">${escapeHtml(LEDGER_TRUST_ANCHOR)}</div>`;

  return ledgerSection({
    number: '4',
    title: 'CURRENT SETTLE',
    sub: 'What you would owe or be owed if the season closed now.',
    body: `<div id="fs-current-settle">${body}</div>`,
    // FINAL POR §30 — ALL FOUR ACCOUNT CARDS ARRIVE CLOSED.
    //
    // Current Settle opened on arrival because it is the number the page exists
    // to derive. But a reconciliation figure is not what a GM comes to Account
    // to read first, and opening the densest of the four cards by default put
    // an accounting statement in front of a reader who may only have wanted
    // their Wallet. The affordance is unchanged and one tap away.
    open: false,
  });
}

/* ── Panel ──────────────────────────────────────────────────────────────────*/

/**
 * @returns {string}
 */
/**
 * Weekly Minimum Left, from whichever source is bound.
 *
 * The bound model publishes `spendableCents` as wallet + live weekly minimum
 * (they are one spendable pool), so the live-minimum component is not
 * separately carried on the position. It is read from the strip fixture in
 * demo mode and from the authoritative advance split otherwise — see the P4B-1
 * expectation map, which keeps this cell exact at $10.
 *
 * @returns {number} exact integer cents
 */
function weeklyMinLeftCents() {
  const bound = boundWeeklyMinLiveCents();
  return bound === null ? WEEK_STRIP.weeklyMinLeftCents : bound;
}

export function buildLedgerPanel() {
  const composer = new PanelComposer('ledger');
  const r = reconciliation();

  composer.add(ledgerHeader());

  // MY WEEK — authoritative when bound, unresolved when production has no
  // answer, illustrative only in demo mode. `unresolved` is applied per cell
  // rather than to the strip, because the strip's four-cell grammar is locked
  // and an unavailable session still has four cells; what it does not have is
  // four figures.
  const mode = ledgerMode();
  const unresolved = mode === MODE_UNAVAILABLE;

  // Held has an authoritative source of its own and is NOT part of any total.
  // Bound, it is whatever the server reports — $0 on the live path today,
  // because no reachable code posts challenge escrow (P4B-0).
  const heldCents = mode === MODE_AUTHORITATIVE
    ? boundHeldCents()
    : WEEK_STRIP.heldCents;

  composer.addStrip({
    id: 'fs-strip-ledger',
    label: 'My week',
    cells: [
      { label: 'Available', cents: r.position.spendableCents, anchor: true,
        pending: unresolved },
      // In Play is the escrow the position counts. Held is reported beside it
      // and never subtracted from it again.
      { label: 'In Play', cents: r.position.acceptedEscrowCents,
        pending: unresolved },
      // UIRECON REV 1.4 CONSIDERED `Escrow` HERE AND REFUSED IT.
      //
      // The proposal was that this cell reports wager escrow and should say
      // so. It does not. `held_open_challenges_cents` is escrow on challenges
      // still in an OPEN response state — an offer nobody has accepted, which
      // has placed no Bet — and `reports/ledger_read_model.py` states it is
      // "a SUBSET of `in_play_cents` rather than an addition to it". The
      // escrow on unresolved WAGERS is the cell immediately to the left of
      // this one. Labelling the subset `Escrow` beside the whole of it would
      // have told a GM the two are different kinds of money and that adding
      // them means something — the exact double count both read models are
      // written to prevent.
      //
      // FINAL POR §30 — `ESCROW`, WITH THE SUBSET RELATIONSHIP MADE VISIBLE.
      //
      // The objection recorded above is real and is NOT dismissed: this figure
      // is `held_open_challenges_cents`, which `reports/ledger_read_model.py`
      // states is "a SUBSET of `in_play_cents` rather than an addition to it".
      // Labelling it `ESCROW` beside `In Play` without saying so would invite
      // exactly the addition both read models exist to prevent.
      //
      // So the POR's label is used AND the relationship is drawn: `included in
      // In Play` rides the cell as secondary context. THE ARITHMETIC IS
      // UNCHANGED — this cell is still reported beside the position and is
      // still never added to any total.
      { label: 'Escrow', cents: heldCents, pending: unresolved,
        context: 'included in In Play' },
      // UIRECON WAVE 1 — `Weekly Min Left` measured 93.8px against a 68px
      // cell and wrapped, stretching every cell on both of this tab's strips.
      { label: 'Min Left', cents: weeklyMinLeftCents(),
        pending: unresolved },
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
      // `Versus + Pools` failed both the terminology lock and the one-line
      // budget (85.5px). `Play Net` is the net of everything played — the
      // Matchup and Prop Pool totals this figure already sums.
      { label: 'Play Net', cents: r.versusPlusPoolsCents, signed: true },
      // AWARDS / ADJ. IS UNRESOLVED WHENEVER THE FIGURES ARE REAL.
      //
      // The cell means expired minimum + Skunk + season winnings. P3 proved
      // season winnings has no authoritative source: award credits sit inside
      // the wallet balance and no posted door attributes them. Two of the
      // three components are sourced, so a number COULD be printed — and that
      // is exactly the trap. Printing +$8 would put a partial subtotal under a
      // label that means the whole, and printing $0 would assert an
      // authoritative zero nobody measured. The approved unresolved treatment
      // draws it as —, and the expandable detail below still carries the two
      // components that ARE sourced.
      { label: 'Season Adj', cents: r.adjustments.netAdjustmentsCents,
        signed: true, pending: unresolved || !seasonWinningsResolved() },
      // `Current Settle` is 80.9px and fits at 375 and 390 but not at the
      // 320px cell. The concept keeps its full name on the card below, which
      // is where the figure is actually derived; the cell carries the noun.
      { label: 'Settle', cents: r.currentSettleCents, signed: true,
        gold: true, pending: unresolved },
    ],
  });

  // FOUR SECTIONS, ONE CONSTRUCTION. Three of them explain into the fourth,
  // and since UIRECON Wave 2 all four are built by `ledgerSection()` — so the
  // page reads as one statement rather than three sections and a card.
  composer.add(
    '<div class="fs-lscroll">' +
    advancesSection(r) +
    wageringSection(r) +
    adjustmentsSection(r) +
    currentSettleSection(r) +
    '</div>',
  );

  // WP3D — ACCOUNT CARRIES YAHOO CONTEXT, NOT YAHOO MONEY.
  //
  // Every figure on this tab is FantasyStakes' own: the Wallet, the Weekly
  // Minimum, Current Settle, the Ledger and net winnings are produced by this
  // product's accounting and by nothing else. What is Yahoo-derived here is the
  // league and week context the page is scoped to, and the opponent names on
  // the settled rows.
  //
  // So the attribution goes in the page footer, where it reads as a source
  // disclosure for the surface. Putting it near the balances would say Yahoo
  // supplied them, which is false.
  composer.add(attributionFooter());

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
  // WP3C — the section-level disclosures (§14.2). Same grammar as the row-level
  // one below: a real button, a real `aria-expanded`, and a class toggle that
  // changes nothing but what is visible.
  bindAccordions(panel);

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
      // S8-P1: the session seam HAS landed, so "when the session seam lands"
      // now describes something that already happened. What this control still
      // waits on is the binding package, not authentication.
      `<div class="fs-note">Read-only in this build. The governed command is ` +
      `<code>${escapeHtml(TOPOFF_COMMAND_SEAM.endpoint)}</code>; this surface binds ` +
      'to it when the Ledger above is read from the ledger, and implements no ' +
      'top-off path of its own.</div>',
  };
}
