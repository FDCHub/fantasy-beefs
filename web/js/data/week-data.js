/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · The Week illustrative view model
 * Sprint 7 Package 3
 *
 * VIEW-MODEL DATA, NOT PROTOCOL DATA. Nothing here reads or writes the ledger,
 * escrow, proposal, pool or provider layers. It exists so The Week's three
 * modules can be built and reviewed before a Yahoo read seam exists.
 *
 * THREE RULES GOVERN WHAT MAY LIVE HERE, and they are the same three Package 2
 * worked to.
 *
 * 1. Carried, not invented. The twelve teams, their records and ranks, and the
 *    moneylines on the viewer's own board come from `league-data.js`, which
 *    carried them from the accepted Rev4.1 prototype. Nothing new is priced.
 *
 * 2. Derived, not asserted. A team's Week 5 projection is its own lineup total;
 *    a matchup's spread is the difference between the two projections and its
 *    total is their sum. A card can therefore be checked against its own
 *    numbers. Week 4's final scores are the one carried figure — a result
 *    cannot be derived from a projection — and everything about Week 4 that
 *    follows from those scores (winner, margin, combined total) is computed.
 *
 * 3. Unquoted is drawn as unquoted. A moneyline comes from the simulation
 *    engine (`odds/monte_carlo.py`, converted by `p2o` in
 *    `odds/dynamic_pricing.py`). The POR carries moneylines for the viewer's
 *    own board and for no other matchup, and there is no frontend-legitimate
 *    way to turn a spread into a price. The other five matchups therefore carry
 *    `ml: null`, and the components draw that cell as unresolved rather than
 *    inventing a number that would look exactly as authoritative as a real one.
 * ========================================================================== */

import {
  OPPONENTS,
  POOLS,
  YOUR_LINEUP,
  YOUR_PROJECTION,
  YOUR_TEAM,
  opponentLineup,
} from './league-data.js';
import { CARDS, lifecycleOf } from './action-data.js';

/** The viewer's own team id within this module's team registry. */
export const YOU = 'you';

/** The two weeks the switch offers, and which one is current. */
export const CURRENT_WEEK = 5;
export const PAST_WEEK = 4;
export const WEEKS = Object.freeze([PAST_WEEK, CURRENT_WEEK]);

/**
 * Every team in the league, the viewer's included.
 *
 * @type {ReadonlyArray<{id: string, name: string, record: string, rank: string}>}
 */
export const TEAMS = Object.freeze([
  Object.freeze({ id: YOU, ...YOUR_TEAM }),
  ...OPPONENTS.map((o) => Object.freeze({
    id: o.id, name: o.name, record: o.record, rank: o.rank,
  })),
]);

function team(id) {
  const found = TEAMS.find((t) => t.id === id);
  if (!found) throw new Error(`unknown team "${id}"`);
  return found;
}

/**
 * A team's Week 5 projection.
 *
 * The viewer's is their lineup total. An opponent's is that total plus the
 * spread their board row carries, which is exactly how `league-data.matchup()`
 * derives it — so a team projects the same number here as it does on the
 * League tab.
 *
 * @param {string} id
 * @returns {number}
 */
export function projectionOf(id) {
  if (id === YOU) return YOUR_PROJECTION;
  const opponent = OPPONENTS.find((o) => o.id === id);
  if (!opponent) throw new Error(`unknown team "${id}"`);
  return round1(YOUR_PROJECTION + opponent.spread);
}

/**
 * The week's official Yahoo pairings. Twelve teams, six matchups, each team
 * exactly once — asserted by the suite rather than trusted.
 */
const PAIRINGS = Object.freeze({
  5: Object.freeze([
    [YOU, 'destroyers'], ['goodfellas', 'gravy'], ['icedtea', 'bombers'],
    ['enforcers', 'cartel'], ['racket', 'raiders'], ['braintrust', 'provolone'],
  ].map(Object.freeze)),
  4: Object.freeze([
    [YOU, 'enforcers'], ['destroyers', 'icedtea'], ['goodfellas', 'racket'],
    ['braintrust', 'bombers'], ['provolone', 'gravy'], ['raiders', 'cartel'],
  ].map(Object.freeze)),
});

/**
 * Week 4 final scores — the one carried figure in this module.
 *
 * A result is not derivable from a projection, so these are illustrative POR
 * figures. Everything Week 4 shows beyond them — who won, by how much, the
 * combined total — is computed from them.
 */
const WEEK4_FINALS = Object.freeze({
  you: 119.7, enforcers: 104.2, destroyers: 131.4, icedtea: 118.9,
  goodfellas: 127.6, racket: 111.3, braintrust: 108.5, bombers: 122.0,
  provolone: 133.1, gravy: 96.1, raiders: 114.8, cartel: 105.7,
});

/**
 * One Yahoo matchup, shaped so the Package 2 Matchup Preview and card grammar
 * read it unchanged.
 *
 * `you` is the SUBJECT side of the line and `name` the other — the field names
 * are Package 2's and are kept so the shared components need no fork. For the
 * viewer's own matchup the subject side really is the viewer, and
 * `viewerIsSubject` says so; for the other five it is simply the home team, and
 * the narrative addresses it by name.
 *
 * @param {number} week
 * @param {number} index
 * @returns {object}
 */
export function yahooMatchup(week, index) {
  const pairing = PAIRINGS[week];
  if (!pairing) throw new Error(`no Yahoo slate for week ${week}`);
  const [subjectId, opponentId] = pairing[index];
  if (!pairing[index]) throw new Error(`no matchup ${index} in week ${week}`);

  const subject = team(subjectId);
  const opponent = team(opponentId);
  const settled = week !== CURRENT_WEEK;
  const viewerIsSubject = subjectId === YOU;
  const viewerIsIn = viewerIsSubject || opponentId === YOU;

  // A settled week shows what happened; a live week shows what is projected.
  const subjectFigure = settled ? WEEK4_FINALS[subjectId] : projectionOf(subjectId);
  const opponentFigure = settled ? WEEK4_FINALS[opponentId] : projectionOf(opponentId);

  // Positive spread means the subject side is getting points, matching
  // league-data's convention exactly.
  const spread = round1(opponentFigure - subjectFigure);
  const total = round1(subjectFigure + opponentFigure);

  return {
    id: `yh-w${week}-${subjectId}-${opponentId}`,
    source: 'yahoo',
    week,
    weekLabel: `Week ${week}`,
    settled,
    viewerIsSubject,
    viewerIsIn,

    you: subject,
    name: opponent.name,
    record: opponent.record,
    rank: opponent.rank,

    yourProjection: subjectFigure,
    opponentProjection: opponentFigure,
    spread,
    total,
    // A PAST week carries no market data at all. The board's moneylines are
    // this week's prices for challenging those GMs, not the line a finished
    // matchup closed at, and no closing line is retained. Reusing the current
    // price on a settled fixture would be quietly wrong in the most plausible
    // possible way, so a settled matchup is unpriced.
    ml: settled ? null : moneylineFor(subjectId, opponentId),

    yourLineup: lineupFor(subjectFigure, settled, viewerIsSubject),
    opponentLineup: lineupFor(opponentFigure, settled, viewerIsIn && !viewerIsSubject),

    favourite: spread > 0 ? opponent.name : subject.name,
    status: settled ? 'FINAL' : 'PREGAME',
    score: settled ? `${subjectFigure.toFixed(1)} — ${opponentFigure.toFixed(1)}` : '',
    winner: settled ? (subjectFigure >= opponentFigure ? subject.name : opponent.name) : '',
  };
}

/**
 * A matchup's lineup for one side.
 *
 * A LIVE week has projections: the viewer's own are their real lineup, and an
 * opponent's are the slot shape scaled to their projected total.
 *
 * A SETTLED week has neither. Per-slot results for a past week are not retained
 * anywhere in this build, and scaling the slot shape to a FINAL score would
 * manufacture a box score — nine per-slot figures that look like what those
 * players did and are nothing of the kind. The slot shape is kept, the figures
 * are unresolved, and the team total stands on its own.
 *
 * @param {number} figure
 * @param {boolean} settled
 * @param {boolean} isViewer
 * @returns {Array<{slot: string, player: ?string, projection: ?number}>}
 */
function lineupFor(figure, settled, isViewer) {
  if (settled) {
    return YOUR_LINEUP.map((r) => ({
      slot: r.slot,
      player: isViewer ? r.player : null,
      projection: null,
    }));
  }
  return isViewer ? YOUR_LINEUP : opponentLineup(figure);
}

/**
 * The moneyline on a matchup, or null where none is quoted.
 *
 * The prototype carried a moneyline for each of the viewer's eleven possible
 * opponents. That is the whole of what this build holds.
 */
function moneylineFor(subjectId, opponentId) {
  if (subjectId === YOU) {
    const opponent = OPPONENTS.find((o) => o.id === opponentId);
    return opponent ? opponent.ml : null;
  }
  if (opponentId === YOU) {
    const opponent = OPPONENTS.find((o) => o.id === subjectId);
    // Quoted from the viewer's side; the subject side here is the other GM.
    return opponent ? -opponent.ml : null;
  }
  return null;
}

/**
 * Every Yahoo matchup for a week, the viewer's own first.
 *
 * @param {number} week
 * @returns {object[]}
 */
export function yahooMatchups(week) {
  const all = PAIRINGS[week].map((_, i) => yahooMatchup(week, i));
  return [...all.filter((m) => m.viewerIsIn), ...all.filter((m) => !m.viewerIsIn)];
}

/* ── FantasyStakes Bets, scoped to a week ───────────────────────────────────*/

/**
 * The viewer's wagers for a week.
 *
 * The cards are Action's cards — the same records, read through a week lens.
 * Building a second wager dataset here would let The Week and Action disagree
 * about the same wager, which is the one thing a weekly dashboard must not do.
 *
 * WHAT A WEEK SHOWS. A current week shows the wagers that are ACCEPTED and
 * running: those are the ones with money on this week's games, and they are
 * what a weekly dashboard is for. Offers still being negotiated are not week
 * state — they are decisions, and Action is where a GM makes them ("Your
 * wagers — the only place you manage them"). A past week shows what settled in
 * it. Neither list is truncated to reach a count: The Week draws every wager
 * the week has, and its heading counts what it drew.
 *
 * @param {number} week
 * @returns {object[]}
 */
export function weekBets(week) {
  const settledWeek = week !== CURRENT_WEEK;
  return CARDS.filter((c) => (settledWeek
    ? c.settled && c.week === `Wk ${week}`
    : lifecycleOf(c) === 'live'));
}

/* ── Pools, scoped to a week ────────────────────────────────────────────────*/

/**
 * Week 4 outcomes for the four fixed launch Pools.
 *
 * Pool #2 did not qualify and carried its pot forward, which is why Week 5
 * shows it as a continuation. The carry reconciles: an 800-cent Week 4 pot plus
 * nine fresh entries at 100 is the 1700 Week 5 pot `league-data` carries, and
 * the suite checks that rather than trusting it.
 */
const WEEK4_POOL_RESULTS = Object.freeze({
  2: Object.freeze({
    entered: 8, potCents: 800, qualified: false,
    outcome: 'No qualifier · pot rolled to Week 5', winner: null, returnCents: 0,
  }),
  13: Object.freeze({
    entered: 10, potCents: 1000, qualified: true,
    outcome: 'Won by Gridiron Goodfellas', winner: 'Gridiron Goodfellas', returnCents: 1000,
  }),
  20: Object.freeze({
    entered: 9, potCents: 900, qualified: true,
    outcome: 'Won by Numbers Racket', winner: 'Numbers Racket', returnCents: 900,
  }),
  87: Object.freeze({
    entered: 7, potCents: 700, qualified: true,
    outcome: 'Won by Provenza Provolone', winner: 'Provenza Provolone', returnCents: 700,
  }),
});

/**
 * The four launch Pools as a week sees them.
 *
 * The definitions themselves never change — they are the governing catalog's,
 * carried through `league-data.POOLS`. Only the week's state is layered on top,
 * so a Pool cannot acquire a different rule by being looked at in a past week.
 *
 * @param {number} week
 * @returns {object[]}
 */
export function weekPools(week) {
  const settledWeek = week !== CURRENT_WEEK;
  return POOLS.map((pool) => {
    if (!settledWeek) {
      return {
        ...pool,
        settled: false,
        state: `${pool.entered} in · pregame`,
      };
    }
    const result = WEEK4_POOL_RESULTS[pool.catalogNumber];
    return {
      ...pool,
      settled: true,
      entered: result.entered,
      potCents: result.potCents,
      // Rollover stays a modifier on the subject type. A Pool that did not
      // qualify carried; it did not become a different kind of Pool.
      continuation: false,
      rolledForward: !result.qualified,
      qualified: result.qualified,
      winner: result.winner,
      returnCents: result.returnCents,
      state: result.outcome,
    };
  });
}

/**
 * What a Week 4 Pool carried into Week 5, in exact cents.
 *
 * @returns {number}
 */
export function carriedForwardCents() {
  return Object.values(WEEK4_POOL_RESULTS)
    .filter((r) => !r.qualified)
    .reduce((sum, r) => sum + r.potCents, 0);
}

/* ── helpers ────────────────────────────────────────────────────────────────*/

function round1(value) {
  return Math.round(value * 10) / 10;
}