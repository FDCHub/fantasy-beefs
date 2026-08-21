/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · League illustrative view model
 * Sprint 7 Package 2
 *
 * VIEW-MODEL DATA, NOT PROTOCOL DATA. Nothing here is read from or written to
 * the ledger, escrow, proposal, pool or provider layers. It exists so the
 * League components can be built and reviewed before a read seam exists, and a
 * later package replaces this module without changing component grammar.
 *
 * TWO RULES GOVERN WHAT MAY LIVE HERE.
 *
 * 1. Carried, not invented. The eleven opponents, their records and ranks,
 *    their moneylines and spreads, and their one-line teasers are carried
 *    forward from the accepted Rev4.1 prototype artifact. The Pool definitions
 *    are read from the governing catalog, not paraphrased from prototype copy.
 *
 * 2. Derived, not asserted. Every figure that follows from another is computed
 *    here rather than typed: your projection is the sum of your own lineup, an
 *    opponent's projection is your projection plus that matchup's spread, and
 *    the total is the two projections added. A reader can check any card
 *    against its own numbers and find them consistent.
 *
 *    This is a deliberate correction. The prototype's O/U totals (206–222) did
 *    not agree with its own lineup projections (125.8 a side, so 251.6 before
 *    any spread). Rather than carry a total that contradicts the lineup shown
 *    two taps away, the totals are derived. Rev4.1 §7 treats demo figures as
 *    unimportant EXCEPT where they reveal a calculation defect; this was one.
 * ========================================================================== */

/** The GM's own side. Rank 3rd is the seat the prototype's standings leave open. */
export const YOUR_TEAM = Object.freeze({
  name: 'Your Team',
  record: '5–2',
  rank: '3rd',
});

/**
 * Your starting lineup for the week — one lineup, the same on every card,
 * carried from the prototype. Projections are the frozen proposal projection.
 *
 * @type {ReadonlyArray<{slot: string, player: string, projection: number}>}
 */
export const YOUR_LINEUP = Object.freeze([
  { slot: 'QB', player: 'J. Hurts', projection: 21.4 },
  { slot: 'RB', player: 'B. Robinson', projection: 16.8 },
  { slot: 'RB', player: 'K. Walker', projection: 13.2 },
  { slot: 'WR', player: 'A. St. Brown', projection: 15.1 },
  { slot: 'WR', player: 'D. London', projection: 12.6 },
  { slot: 'TE', player: 'T. McBride', projection: 11.9 },
  { slot: 'FLEX', player: 'J. Jefferson', projection: 17.3 },
  { slot: 'K', player: 'H. Butker', projection: 8.5 },
  { slot: 'DEF', player: 'Ravens', projection: 9.0 },
].map(Object.freeze));

/** Your projected total — the sum of the lineup above, to one decimal. */
export const YOUR_PROJECTION = round1(YOUR_LINEUP.reduce((sum, r) => sum + r.projection, 0));

/**
 * The eleven opponents, in the prototype's board order.
 *
 * `spread` is the line from YOUR side: positive means you are getting points.
 * `ml` is American odds on YOUR side. The two agree in direction on every row.
 *
 * @type {ReadonlyArray<{id: string, name: string, record: string, rank: string,
 *   ml: number, spread: number, teaser: string}>}
 */
export const OPPONENTS = Object.freeze([
  { id: 'destroyers', name: 'CULV Destroyers', record: '7–0', rank: '1st', ml: 165, spread: 4.5,
    teaser: 'Biggest dog on the board. Low total — live upset.' },
  { id: 'goodfellas', name: 'Gridiron Goodfellas', record: '6–1', rank: '2nd', ml: 130, spread: 3.5,
    teaser: 'Plus money on the 2-seed. High total helps you.' },
  { id: 'icedtea', name: 'Third And Long Island Iced Tea', record: '5–2', rank: '4th', ml: 105, spread: 1.5,
    teaser: 'Coin flip, priced like one.' },
  { id: 'enforcers', name: "Skipolini's Enforcers", record: '4–3', rank: '5th', ml: -115, spread: -1.5,
    teaser: 'Tightest line here. One bench call decides it.' },
  { id: 'racket', name: 'Numbers Racket', record: '4–3', rank: '6th', ml: -125, spread: -2.5,
    teaser: 'Small favourite, lowest total. A grinder.' },
  { id: 'braintrust', name: 'The Brain Trust', record: '3–4', rank: '7th', ml: -135, spread: -3.5,
    teaser: 'You have the floor. They have the ceiling.' },
  { id: 'provolone', name: 'Provenza Provolone', record: '3–4', rank: '8th', ml: -145, spread: -4.5,
    teaser: 'High total. Shootout risk cuts both ways.' },
  { id: 'raiders', name: 'Racconti Raiders', record: '3–4', rank: '9th', ml: -150, spread: -4.5,
    teaser: 'Records say close. The line says a score.' },
  { id: 'cartel', name: 'Contabile Cartel', record: '2–5', rank: '10th', ml: -170, spread: -5.5,
    teaser: 'Highest total on your board. Points are the risk.' },
  { id: 'bombers', name: 'Bada Bing Bombers', record: '2–5', rank: '11th', ml: -185, spread: -6.5,
    teaser: 'Heavy chalk. Value’s in the total, not the side.' },
  { id: 'gravy', name: 'Sunday Gravy', record: '1–6', rank: '12th', ml: -210, spread: -7.5,
    teaser: 'Biggest spread you’ll lay. Their ceiling is live.' },
].map(Object.freeze));

/**
 * One matchup, with every derived figure resolved.
 *
 * @param {string} opponentId
 * @returns {object}
 */
export function matchup(opponentId) {
  const opponent = OPPONENTS.find((o) => o.id === opponentId);
  if (!opponent) throw new Error(`unknown opponent "${opponentId}"`);

  // You are getting `spread` points, so their projection sits that far above
  // yours. Both figures and the total therefore agree by construction.
  const yourProjection = YOUR_PROJECTION;
  const opponentProjection = round1(yourProjection + opponent.spread);
  const total = round1(yourProjection + opponentProjection);

  return {
    ...opponent,
    you: YOUR_TEAM,
    yourProjection,
    opponentProjection,
    total,
    yourLineup: YOUR_LINEUP,
    opponentLineup: opponentLineup(opponentProjection),
    favourite: opponent.spread > 0 ? opponent.name : YOUR_TEAM.name,
  };
}

/** Every matchup, in board order. */
export function allMatchups() {
  return OPPONENTS.map((o) => matchup(o.id));
}

/**
 * An opponent's starting lineup.
 *
 * Slots and per-slot weights follow your own lineup's shape, scaled so the
 * rows sum EXACTLY to that opponent's projection — the last row absorbs the
 * rounding remainder, so the column never disagrees with its own total.
 *
 * Player identity is deliberately absent. Naming eleven opposing rosters would
 * be fabricating ninety-nine player-to-team assignments that no source
 * supports; the slot and the projection are what the market inputs actually
 * give us. Identity binds when the Yahoo read seam is wired.
 *
 * @param {number} teamProjection
 * @returns {Array<{slot: string, player: null, projection: number}>}
 */
export function opponentLineup(teamProjection) {
  const weights = YOUR_LINEUP.map((r) => r.projection / YOUR_PROJECTION);
  const rows = weights.map((w) => round1(teamProjection * w));
  const drift = round1(teamProjection - rows.reduce((s, v) => s + v, 0));
  rows[rows.length - 1] = round1(rows[rows.length - 1] + drift);
  return YOUR_LINEUP.map((r, i) => ({ slot: r.slot, player: null, projection: rows[i] }));
}

/* ── Pools ──────────────────────────────────────────────────────────────────
 * Exactly four active Pools per fantasy week (POR §4.1). Each row below is a
 * real definition from spec/pool_catalog_rev1_4.json — catalog number, display
 * name, subject scope, rule text and public question are reproduced from that
 * file, not paraphrased. `test_s7_p2_league_action.py` reads the catalog and
 * fails if any of these four drifts from it.
 *
 * REV 1.4 · THE SET NOW ILLUSTRATES THE GOVERNED MIX. POR Rev 1.4 §4.2 rules
 * the normal weekly slate at 3 TEAM + 1 MATCHUP; this fixture was 2 and 2, which
 * is a shape the selector no longer draws. #56 Air Show (MATCHUP) is replaced by
 * #20 Air Raid (TEAM) so the illustrative week shows the week the product
 * actually builds. Nothing else about the four moved: the continuation is still
 * the continuation, the qualifier is still the qualifier, and the pots and
 * entered counts are unchanged.
 *
 * `question` is the catalog's `public_question` (§3), carried here for the same
 * reason the name is: the demo surface must show the governed sentence, not a
 * scope-derived stand-in. `web/js/league.js::poolQuestion` prefers it and falls
 * back only where a definition carries none.
 *
 * Rollover is a MODIFIER on a subject type, never a third type. A continuation
 * is a Pool that carried its pot forward and occupies one normal slate slot
 * (POR §5); it is marked on the definitions that actually carried, not on every
 * definition that happens to be rollover-eligible.
 *
 * Entry is the commissioner-set weekly Pool entry, bounded to $1–$5 by
 * ck_pool_config_weekly_entry_bounds. $1 is the illustrative setting. */
export const POOL_ENTRY_CENTS = 100;

export const POOLS = Object.freeze([
  Object.freeze({
    catalogNumber: 2,
    name: 'Triple Threat',
    question: 'Which team scores a passing, a rushing and a receiving touchdown?',
    scope: 'TEAM',
    rule: 'team recorded a passing, rushing and receiving TD',
    subject: 'One league team',
    rolloverEligible: true,
    continuation: true,
    carriedFromWeek: 4,
    entryCents: POOL_ENTRY_CENTS,
    entered: 9,
    potCents: 1700,
  }),
  Object.freeze({
    catalogNumber: 13,
    name: 'Touchdown Machine',
    question: 'Which team scores the most touchdowns?',
    scope: 'TEAM',
    rule: 'sum(total_touchdowns)',
    subject: 'One league team',
    rolloverEligible: false,
    continuation: false,
    entryCents: POOL_ENTRY_CENTS,
    entered: 11,
    potCents: 1100,
  }),
  Object.freeze({
    catalogNumber: 20,
    name: 'Air Raid',
    question: 'Which team throws for the most yards?',
    scope: 'TEAM',
    rule: 'sum(passing_yards)',
    subject: 'One league team',
    rolloverEligible: false,
    continuation: false,
    entryCents: POOL_ENTRY_CENTS,
    entered: 8,
    potCents: 800,
  }),
  Object.freeze({
    catalogNumber: 87,
    name: 'Turnover Free',
    question: 'Which matchup ends with no turnovers by either team?',
    scope: 'MATCHUP',
    rule: 'both teams interceptions_thrown + fumbles_lost == 0',
    subject: 'One scheduled matchup',
    rolloverEligible: true,
    continuation: false,
    entryCents: POOL_ENTRY_CENTS,
    entered: 7,
    potCents: 700,
  }),
]);

/**
 * The badge for a Pool: its subject type, with ROLLOVER as a modifier on a
 * continuation.
 *
 * @param {{scope: string, continuation: boolean}} pool
 * @returns {string}
 */
export function poolBadge(pool) {
  return pool.continuation ? `${pool.scope} · ROLLOVER` : pool.scope;
}

/* ── helpers ────────────────────────────────────────────────────────────────*/

function round1(value) {
  return Math.round(value * 10) / 10;
}