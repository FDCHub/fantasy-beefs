/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Ledger illustrative view model
 * Sprint 7 Package 3
 *
 * VIEW-MODEL DATA, NOT PROTOCOL DATA. Nothing here posts, mutates, settles or
 * reconciles. These are the Rev 4.2 POR's locked illustrative figures for the
 * single coherent league state at Week 5, held as EXACT INTEGER CENTS — the
 * same representation `ledger/ledger.py` uses. Rounding to whole dollars
 * happens once, at the moment of drawing, in `credits.js`.
 *
 * ONLY IRREDUCIBLE FIGURES LIVE HERE. Every total the Ledger shows is derived
 * in `ledger-model.js` from the terms below, never typed beside them. That is
 * what makes the reconciliation checkable: a reader can add the rows on screen
 * and get the total on screen, because the total was produced by adding them.
 *
 * The one exception is `betRecord`, which is a record rather than an amount and
 * is not derivable from any figure in this module.
 * ========================================================================== */

/**
 * FantasyStakes Advances — virtual stakes advanced to the GM for the season.
 *
 * `seasonOpening` is deliberately absent: it is the sum of its two parts, and
 * the POR's hierarchy exists precisely to show that $140 + $80 = $220.
 */
export const ADVANCES = Object.freeze({
  regularSeasonMinimumCents: 14000,      // $140
  playoffsChampionshipCents: 8000,       // $80
  addedStakesCents: 4000,                // +$40
});

/**
 * Versus activity — settled wagers against other GMs, season to date.
 *
 * Losses are held NEGATIVE so the net is an addition rather than a subtraction
 * the reader has to trust. A figure that means "money out" carries its sign.
 */
export const VERSUS_ACTIVITY = Object.freeze({
  settledWinsCents: 18400,               // +$184
  settledLossesCents: -7800,             // −$78
});

/** Pool activity — season to date, same sign convention. */
export const POOL_ACTIVITY = Object.freeze({
  poolPayoutsCents: 4500,                // +$45
  poolEntriesCents: -2500,               // −$25
});

/**
 * Current wager position — where the GM's Credits are right now.
 *
 * These three are the holdings themselves, not a summary of activity. The
 * distinction is the whole reason Net Versus and Net Pools may not be added to
 * Current Settle a second time: the outcome of that activity is already sitting
 * in these balances.
 */
export const POSITION = Object.freeze({
  spendableCents: 6500,                  // $65
  acceptedEscrowCents: 2800,             // $28
  weeklyReserveNotReleasedCents: 9000,   // $90
});

/**
 * Credits held against pending offers.
 *
 * A hold reduces what can be spent — `spendableCents` is already net of it —
 * and is NOT counted again in Current Settle until a proposal is accepted and
 * the funds become escrow. Carried separately so the memo can state the figure
 * without any total being tempted to include it.
 */
export const PENDING_OFFER_HOLD_CENTS = 2500;   // $25

/** Season adjustments and winnings — amounts outside ordinary wagering. */
export const ADJUSTMENTS = Object.freeze({
  weeklyMinOutOfCirculationCents: 800,   // +$8
  skunkFeesCents: 0,                     // $0
  seasonWinningsCents: 2400,             // +$24
});

/**
 * Season awards, by state.
 *
 * The POR fixes the +$24 total; it does not fix a per-award split, and this
 * build does not invent one. The two championship awards are Pending by the
 * POR's own rows, and the Skunk pot distributes at SEASON CLOSE rather than
 * weekly (`economy/skunk.py` — "weekly assessment and season distribution"), so
 * no protocol-identified award has paid out by Week 5. The expansion therefore
 * states what is known and marks the rest unresolved.
 */
export const SEASON_AWARDS = Object.freeze([
  Object.freeze({
    label: 'Season awards credited to date',
    cents: ADJUSTMENTS.seasonWinningsCents,
    state: 'credited',
  }),
  Object.freeze({
    label: 'Skunk distribution · season close',
    cents: null,
    state: 'Pending',
  }),
]);

/** Championship awards — Pending until the season closes. */
export const CHAMPIONSHIPS = Object.freeze([
  Object.freeze({ label: 'Points Champion', state: 'Pending' }),
  Object.freeze({ label: 'Playoff Champion', state: 'Pending' }),
]);

/**
 * The Week strip's four cells, exact cents.
 *
 * `availableCents` is already net of `PENDING_OFFER_HOLD_CENTS`; `heldCents` is
 * that hold, shown so the GM can see why Available is what it is.
 */
export const WEEK_STRIP = Object.freeze({
  availableCents: 6500,                  // $65
  inPlayCents: 2800,                     // $28
  heldCents: 2500,                       // $25
  weeklyMinLeftCents: 1000,              // $10
});

/**
 * The GM's season record. Not derivable from any amount here, so it is carried.
 * It is the same 14–7 Action derives from its own cards.
 */
export const BET_RECORD = '14–7';

/* ── Supporting detail ──────────────────────────────────────────────────────
 * AUDIT SURFACES ONLY. An expandable row shows what is behind a figure; it
 * never changes one. Each list below is the itemised RECENT detail, not the
 * whole season — so `ledger-model.supportingRows()` closes each list against
 * its own header total with a single derived remainder row. Itemising every
 * entry back to Week 1 would mean inventing a per-week schedule the POR has not
 * fixed, and leaving the lists short would show an expansion that does not add
 * up to the row it expands. */

export const VERSUS_WINS_SUPPORT = Object.freeze([
  Object.freeze({ label: 'Wk 4 · vs Skipolini’s Enforcers · ML', cents: 2600 }),
  Object.freeze({ label: 'Wk 4 · vs Third And Long Island Iced Tea · O/U', cents: 900 }),
  Object.freeze({ label: 'Wk 3 · vs Bada Bing Bombers · Spread', cents: 4500 }),
]);

export const VERSUS_LOSSES_SUPPORT = Object.freeze([
  Object.freeze({ label: 'Wk 4 · vs Sunday Gravy · Spread', cents: -1500 }),
  Object.freeze({ label: 'Wk 3 · vs CULV Destroyers · ML', cents: -2100 }),
]);

export const POOL_PAYOUTS_SUPPORT = Object.freeze([
  Object.freeze({ label: 'Wk 3 · Most Total Touchdowns · won', cents: 1200 }),
  Object.freeze({ label: 'Wk 2 · Highest Combined Passing Yards · won', cents: 900 }),
]);

export const POOL_ENTRIES_SUPPORT = Object.freeze([
  Object.freeze({ label: 'Wk 4 · four Prop Pools entered', cents: -400 }),
  Object.freeze({ label: 'Wk 3 · four Prop Pools entered', cents: -400 }),
]);