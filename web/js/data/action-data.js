/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Action illustrative view model
 * Sprint 7 Package 2
 *
 * VIEW-MODEL DATA, NOT PROTOCOL DATA. No lifecycle transition, escrow movement
 * or settlement is performed or implied by this module. It describes what a
 * card SHOWS; the state machine that decides what a card IS lives in
 * beefs/proposal_lifecycle.py.
 *
 * PROTOCOL STATE IS CARRIED, NOT RENAMED. Every card carries `protocolState`,
 * one of the persisted values (`offered`, `countered`, `accepted`, `declined`,
 * `expired`, `cancelled`), and `responseCard`, one of the five cards in the
 * Response Card Specification (Incoming, Accepted, Countered, Declined,
 * Expired). ACTION REQUIRED / WAITING / LIVE / COMPLETED are presentation
 * groupings OVER those states — a rail name is a place to look, never a state.
 * `lifecycleOf()` performs the grouping and is the only place the mapping
 * exists.
 *
 * The four strip figures are DERIVED from these cards, not typed beside them,
 * so the summary cannot drift from the rows that explain it. The suite asserts
 * the derived figures equal the locked Rev 4.2 values.
 * ========================================================================== */

/** Lifecycle rails, in POR order. */
export const RAILS = Object.freeze(['action', 'waiting', 'live', 'completed']);

/**
 * Every wager card. `yourStakeCents` and `opponentStakeCents` are exact
 * integer cents; `potCents` is their sum on every open wager.
 */
export const CARDS = Object.freeze([
  /* ── ACTION REQUIRED ──────────────────────────────────────────────────── */
  Object.freeze({
    id: 'inc-destroyers',
    opponent: 'CULV Destroyers',
    protocolState: 'offered',
    responseCard: 'Incoming',
    role: 'recipient',
    market: 'ml',
    marketLabel: 'ML',
    line: '+165',
    mode: 'locked',
    // An incoming offer commits none of your money until you take it, so this
    // card contributes nothing to Bet this week.
    yourStakeCents: 2000,
    opponentStakeCents: 3300,
    potCents: 5300,
    committed: false,
    expiresIn: '42m left',
    actions: ['Take it', 'Counter', 'Decline'],
    copy: 'They sent it. Terms are frozen as offered.',
  }),
  Object.freeze({
    id: 'ctr-racket',
    opponent: 'Numbers Racket',
    protocolState: 'countered',
    responseCard: 'Countered',
    role: 'issuer',           // §6.1 — the issuer view is the actionable one
    market: 'spread',
    marketLabel: 'SPR',
    line: '−2.5',
    mode: 'locked',
    yourStakeCents: 1500,
    opponentStakeCents: 1364,
    potCents: 2864,
    committed: true,
    expiresIn: '1h 06m left',
    actions: ['Accept', 'Decline'],
    copy: 'Your offer came back countered. Accept it or decline — no re-counter.',
  }),

  /* ── WAITING ──────────────────────────────────────────────────────────── */
  Object.freeze({
    id: 'snt-bombers',
    opponent: 'Bada Bing Bombers',
    protocolState: 'offered',
    responseCard: 'Incoming',   // their card; yours is the read-only sent view
    role: 'issuer',
    market: 'ml',
    marketLabel: 'ML',
    line: '+165',
    mode: 'locked',
    yourStakeCents: 1000,
    opponentStakeCents: 1650,
    potCents: 2650,
    committed: true,
    held: true,
    expiresIn: '18m left',
    copy: 'Sent and held. They have not answered yet.',
  }),
  Object.freeze({
    id: 'ctr-braintrust',
    opponent: 'The Brain Trust',
    protocolState: 'countered',
    responseCard: 'Countered',
    role: 'recipient',          // §6.2 — read-only while the issuer decides
    market: 'ou',
    marketLabel: 'O/U',
    line: '251.6',
    mode: 'dynamic',
    // The terms YOUR counter put on the table. A counter carries its own Anchor
    // Stake and lineup-derived quote (proposal_lifecycle §7.2), and the Anchor
    // role stays with the original issuer (A4) — so their stake is the Anchor
    // here and yours is the Derived side.
    yourStakeCents: 2500,
    opponentStakeCents: 2500,
    potCents: 5000,
    // Countering escrows nothing: counter-time capacity validation is read-only
    // and posts nothing (§7.2, seam to Package 2B), so this commits no money and
    // contributes to neither Bet this week nor Upside left.
    committed: false,
    expiresIn: '54m left',
    copy: 'You countered. It is with them now — read-only until they answer.',
  }),

  /* ── LIVE ─────────────────────────────────────────────────────────────── */
  Object.freeze({
    id: 'liv-goodfellas',
    opponent: 'Gridiron Goodfellas',
    protocolState: 'accepted',
    responseCard: 'Accepted',
    role: 'issuer',
    market: 'ml',
    marketLabel: 'ML',
    line: '+130',
    mode: 'locked',
    yourStakeCents: 1500,
    opponentStakeCents: 1950,
    potCents: 3450,
    committed: true,
    score: '62.4 — 58.1',
    status: 'ahead',
    copy: 'Frozen terms. Yahoo changes do not touch them.',
  }),
  Object.freeze({
    id: 'liv-provolone',
    opponent: 'Provenza Provolone',
    protocolState: 'accepted',
    responseCard: 'Accepted',
    role: 'issuer',
    market: 'spread',
    marketLabel: 'SPR',
    line: '−4.5',
    mode: 'dynamic',
    yourStakeCents: 3000,          // the Anchor — fixed
    // Quoted by the pricing seam, not derived here. It may hold or come down
    // before Final Lock; it may never rise above this figure.
    opponentStakeCents: 3936,
    potCents: 6936,
    committed: true,
    score: '71.2 — 66.8',
    status: 'covering',
    copy: 'Live until kickoff. Your stake is fixed; theirs can only come down.',
  }),
  Object.freeze({
    id: 'liv-raiders',
    opponent: 'Racconti Raiders',
    protocolState: 'accepted',
    responseCard: 'Accepted',
    role: 'recipient',
    market: 'ou',
    marketLabel: 'O/U',
    line: '251.6',
    mode: 'locked',
    yourStakeCents: 2500,
    opponentStakeCents: 2000,
    potCents: 4500,
    committed: true,
    score: '128.9 combined',
    status: 'under pace',
    copy: 'Frozen terms. Combined total decides it.',
  }),
  Object.freeze({
    id: 'liv-cartel',
    opponent: 'Contabile Cartel',
    protocolState: 'accepted',
    responseCard: 'Accepted',
    role: 'issuer',
    market: 'ml',
    marketLabel: 'ML',
    line: '−170',
    mode: 'locked',
    yourStakeCents: 3400,
    opponentStakeCents: 2000,
    potCents: 5400,
    committed: true,
    score: '55.0 — 61.3',
    status: 'behind',
    copy: 'Frozen terms. You are laying the price.',
  }),

  /* ── COMPLETED ────────────────────────────────────────────────────────── */
  Object.freeze({
    id: 'cmp-enforcers',
    opponent: "Skipolini's Enforcers",
    protocolState: 'accepted',
    responseCard: 'Accepted',
    role: 'issuer',
    market: 'ml',
    marketLabel: 'ML',
    line: '−115',
    mode: 'locked',
    yourStakeCents: 2000,
    opponentStakeCents: 2600,
    potCents: 4600,
    committed: false,
    settled: true,
    won: true,
    netCents: 2600,
    score: '119.7 — 104.2',
    week: 'Wk 4',
    copy: 'Final · settled · Credits posted to Wallet.',
  }),
  Object.freeze({
    id: 'cmp-gravy',
    opponent: 'Sunday Gravy',
    protocolState: 'accepted',
    responseCard: 'Accepted',
    role: 'recipient',
    market: 'spread',
    marketLabel: 'SPR',
    line: '−7.5',
    mode: 'dynamic',
    yourStakeCents: 1500,
    opponentStakeCents: 1200,
    potCents: 2700,
    committed: false,
    settled: true,
    won: false,
    netCents: -1500,
    score: '98.3 — 96.1',
    week: 'Wk 4',
    copy: 'Final · settled · stake released to the pot.',
  }),
  Object.freeze({
    id: 'cmp-icedtea',
    opponent: 'Third And Long Island Iced Tea',
    protocolState: 'accepted',
    responseCard: 'Accepted',
    role: 'issuer',
    market: 'ou',
    marketLabel: 'O/U',
    line: '248.0',
    mode: 'locked',
    yourStakeCents: 1000,
    opponentStakeCents: 900,
    potCents: 1900,
    committed: false,
    settled: true,
    won: true,
    netCents: 900,
    score: '256.4 combined',
    week: 'Wk 4',
    copy: 'Final · settled · Credits posted to Wallet.',
  }),
]);

/**
 * Which rail a card appears on.
 *
 * A grouping over protocol state, never a replacement for it:
 *
 *   ACTION REQUIRED — the decision is yours: an offer you received, or your
 *                     own offer returned as a counter (Response Card §6.1).
 *   WAITING         — committed and with the other GM: your sent offer, or
 *                     your counter awaiting their answer (§6.2, read-only).
 *   LIVE            — accepted and not yet settled.
 *   COMPLETED       — settled.
 *
 * @param {object} card
 * @returns {'action'|'waiting'|'live'|'completed'}
 */
export function lifecycleOf(card) {
  if (card.settled) return 'completed';
  if (card.protocolState === 'accepted') return 'live';
  if (card.protocolState === 'offered') return card.role === 'recipient' ? 'action' : 'waiting';
  if (card.protocolState === 'countered') return card.role === 'issuer' ? 'action' : 'waiting';
  throw new Error(`no rail for protocol state "${card.protocolState}"`);
}

/**
 * @param {string} rail
 * @returns {object[]}
 */
export function cardsFor(rail) {
  if (!RAILS.includes(rail)) throw new Error(`unknown rail "${rail}"`);
  return CARDS.filter((c) => lifecycleOf(c) === rail);
}

/* ── Derived strip figures ──────────────────────────────────────────────── */

/** Season record — wins and losses across the season, not just this week. */
export const SEASON_RECORD = Object.freeze({ wins: 14, losses: 7 });

/** `14–7`, the locked Rev 4.2 figure. */
export function seasonRecordLabel() {
  return `${SEASON_RECORD.wins}–${SEASON_RECORD.losses}`;
}

/** Your money committed to open wagers this week, exact cents. */
export function betThisWeekCents() {
  return CARDS.filter((c) => c.committed).reduce((sum, c) => sum + c.yourStakeCents, 0);
}

/** What those open wagers can still return you, exact cents. */
export function upsideLeftCents() {
  return CARDS.filter((c) => c.committed).reduce((sum, c) => sum + c.opponentStakeCents, 0);
}

/** Net of this week's settled wagers, exact cents. */
export function settledCents() {
  return CARDS.filter((c) => c.settled).reduce((sum, c) => sum + c.netCents, 0);
}

/** Rail headings, with counts derived from the cards themselves. */
export function railHeading(rail) {
  // FINAL POR §28 — THE LOCKED NAMES AND THE ONE GRAMMAR, HERE TOO.
  //
  // This is the DEMO fixture's heading builder and it drew a different set of
  // words from the shipped surface's: `WAITING` / `LIVE` / `COMPLETED · 14–7
  // SEASON`. Two heading vocabularies for four rails is how a demo comes to
  // describe a product that does not exist, so it now states the same four
  // locked category names in the same `LABEL · N · SWIPE` form.
  //
  // THE SEASON RECORD DID NOT GO ANYWHERE. `seasonRecordLabel()` still draws it
  // in the summary strip's Bet Record cell, which is a figure's slot rather
  // than a heading's.
  const words = {
    action: 'ACTION REQUIRED',
    waiting: 'PENDING ACTION',
    live: 'LOCKED ACTION',
    completed: 'RESOLVED ACTION',
  };
  const word = words[rail];
  if (!word) throw new Error(`unknown rail "${rail}"`);
  return `${word} · ${cardsFor(rail).length} · SWIPE`;
}