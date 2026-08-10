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

/** Masthead — fixed and identical on every tab. */
export const MASTHEAD = Object.freeze({
  /** Rev4.2 tagline. Supersedes `OUR THING · YOUR LEAGUE`. */
  tagline: 'FANTASY LEAGUES · VIRTUAL STAKES',
  revision: 'UI/UX Rev 4.2 · 2026',
  author: 'Fraser D. Coleman',
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
  netWinningsCents: 12600,   // +$126
  netWinningsRank: '1st',
  walletCents: 5500,         // $55
  weeklyMinLeftCents: 1000,  // $10
  availableCents: 6500,      // $65
  kickoffCountdown: '2d 04:11:38',
});