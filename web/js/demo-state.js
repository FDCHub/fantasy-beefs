/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · illustrative shell state
 * Sprint 7 Package 1
 *
 * ILLUSTRATIVE ONLY. Nothing here is read from, written to, or reconciled
 * against the ledger, escrow, pool or settlement protocols. These are the
 * POR's own illustrative figures for the single coherent league state at
 * Week 5, carried so the shared components can be seen rendering their locked
 * grammar before any data binding exists.
 *
 * Every money figure is held as EXACT INTEGER CENTS, the same representation
 * the accounting layer uses. Rounding to whole dollars happens once, at the
 * moment of drawing, in `credits.js` — never here.
 *
 * A later package replaces this module with real data. Any figure the POR has
 * not fixed is deliberately absent rather than invented; the components draw
 * those cells as unresolved.
 * ========================================================================== */

/**
 * Masthead — fixed and identical on every tab.
 *
 * REV 4.3 §2 AND §2.1. The tagline is the LOCKED PRIMARY PRODUCT TAGLINE, exact
 * to the character:
 *
 *     Real odds. Fantasy stakes. More ways to win.
 *
 * It supersedes the Rev 4.2 lockup line `FANTASY LEAGUES · VIRTUAL STAKES`.
 *
 * THE REVISION AND AUTHOR LINES ARE GONE, and their absence is the point.
 * §2.1 removes prototype and internal material from the production
 * application by name — the UI revision designation, the FINAL POR marker,
 * engineering dates and the Fraser D. Coleman byline. A masthead is the most
 * visible surface in the app and it was carrying all four on every tab. The
 * legal notice is not lost with them: it remains on Rules & Settings, which is
 * where §3.1 puts Legal.
 */
export const MASTHEAD = Object.freeze({
  tagline: 'Real odds. Fantasy stakes. More ways to win.',
});

/**
 * League identity. Rev4.2 presents the league name alone; the
 * `· Fantasy Sportsbook` suffix of Rev4.1 is superseded.
 */
export const LEAGUE_IDENTITY = Object.freeze({
  name: 'CULV APPRECIATION SOCIETY',
  week: 'Week 5 · Regular Season',
});

/** POR illustrative figures — exact cents. */
export const ILLUSTRATIVE = Object.freeze({
  // UIRECON WAVE 2 — NET WINNINGS MEANS NET WINNINGS.
  //
  // `netWinningsRank: '1st'` stood here and was the rank Rev 4.3 SS8.3
  // removed from the Play strip: a standings position drawn inside a money
  // cell. The cell stopped reading it, and the constant stayed — which left
  // the next edit a ready-made way to put it back. It is gone, so the cell
  // has no context to reintroduce and no fixture to reintroduce it from.
  // Rank belongs to Standings, which answers it properly.
  netWinningsCents: 12600,   // +$126
  walletCents: 5500,         // $55
  weeklyMinLeftCents: 1000,  // $10
  availableCents: 6500,      // $65
  kickoffCountdown: '2d 04:11:38',
});