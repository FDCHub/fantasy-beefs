/* ============================================================================
 * FantasyStakes — the served Versus market board
 * WP3C.2, under the owner ruling on market line methodology
 *
 * WHAT THIS HOLDS. The lines FantasyStakes is offering this GM this week, as
 * the server computed them: the moneyline both ways, the sportsbook-signed
 * spread for each side, and the total. One row per opponent.
 *
 * WHAT IT DOES NOT DO — AND THE LIST IS THE POINT. It does not compute a
 * median. It does not round. It does not decide a sign. It does not turn a
 * moneyline into a probability or a probability into a line. Search this file
 * for an arithmetic operator and you will not find one: every number here
 * arrived over the wire and leaves unchanged.
 *
 * WHY IT IS A SEPARATE READ FROM ACTION. `action-model` answers "who is in my
 * league and may I play them"; this answers "at what price". They move on
 * different clocks — eligibility changes when the championship track changes,
 * a line changes when projections do — and a board costs a Monte Carlo run per
 * pairing, which is not something the Action read should carry every time a GM
 * opens Status.
 *
 * THREE MODES, as everywhere else in this build: demo (nothing bound), bound,
 * and unavailable. An unavailable board is not an empty one — the difference is
 * "we could not ask" versus "there is nothing to offer", and the card says a
 * different thing for each.
 * ========================================================================== */

export const MARKET_MODE_DEMO = 'demo';
export const MARKET_MODE_AUTHORITATIVE = 'authoritative';
export const MARKET_MODE_UNAVAILABLE = 'unavailable';

let MODE = MARKET_MODE_DEMO;

/** The served `VersusBoardOut`, verbatim. @type {object|null} */
let SERVED = null;

/**
 * Bind to a served board.
 *
 * @param {object} board a VersusBoardOut
 */
export function bindMarketBoard(board) {
  SERVED = board && Array.isArray(board.markets) ? board : null;
  MODE = SERVED ? MARKET_MODE_AUTHORITATIVE : MARKET_MODE_UNAVAILABLE;
}

/** The read failed or was refused. */
export function markMarketBoardUnavailable() {
  SERVED = null;
  MODE = MARKET_MODE_UNAVAILABLE;
}

/** Return to the unbound default — sign-out and the component suites. */
export function unbindMarketBoard() {
  SERVED = null;
  MODE = MARKET_MODE_DEMO;
}

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function marketMode() {
  return MODE;
}

/** The week the served board was computed for. @returns {number|null} */
export function marketWeek() {
  return SERVED && typeof SERVED.week === 'number' ? SERVED.week : null;
}

/**
 * One opponent's offered markets, or null.
 *
 * NULL MEANS "NOT SERVED", which is not the same as "not priceable". A row that
 * came back with `available: false` IS returned — the caller needs to be able
 * to tell an unpriceable matchup apart from one nobody asked about, and to show
 * the server's own sentence for it.
 *
 * @param {number} teamId
 * @returns {object|null} a VersusMarketOut
 */
export function marketFor(teamId) {
  if (MODE !== MARKET_MODE_AUTHORITATIVE || !SERVED) return null;
  const row = SERVED.markets.find((m) => m.opponent_team_id === teamId);
  return row || null;
}

/**
 * Whether this pairing has a priced market on offer.
 *
 * @param {number} teamId
 * @returns {boolean}
 */
export function marketAvailable(teamId) {
  const row = marketFor(teamId);
  return Boolean(row && row.available);
}

/**
 * When the served board was priced, as the server stamped it.
 *
 * THE SERVER'S FACT, CARRIED VERBATIM. The Play surface prints
 * `Odds updated 11:47 AM` beside its refresh control, and that sentence is a
 * claim about when a Monte Carlo ran. Reading the client clock instead would
 * print round-trip latency as the model's completion time.
 *
 * @returns {string|null} an ISO timestamp, or null when nothing is bound
 */
export function marketComputedAt() {
  if (MODE !== MARKET_MODE_AUTHORITATIVE || !SERVED) return null;
  return SERVED.computed_at || null;
}

/**
 * Replace ONE pairing's row from a single-opponent board read.
 *
 * WHY A MERGE RATHER THAN A REBIND. The per-card refresh asks for one opponent
 * (`/versus/board?opponent_team_id=`), so the response carries one row. Binding
 * it whole would drop every other card's market and leave eleven cards showing
 * `Play ›` because one was refreshed — a per-card control that blanked the rail
 * is worse than no control.
 *
 * THE STAMP MOVES WITH IT, and that is deliberate rather than sloppy: the
 * heading's stamp says when the odds on screen were last priced, and after a
 * per-card refresh the newest thing on screen is that card. A stamp that only
 * moved on a full-board read would go stale while the GM watched a price
 * change.
 *
 * REFUSED IF NOTHING IS BOUND. A single row is not a board, and promoting one
 * to be the whole board would tell every other card it is unpriceable.
 *
 * @param {object} board a VersusBoardOut carrying one market row
 * @returns {boolean} whether the row was merged
 */
export function applyMarketRow(board) {
  if (MODE !== MARKET_MODE_AUTHORITATIVE || !SERVED) return false;
  if (!board || !Array.isArray(board.markets) || board.markets.length !== 1) {
    return false;
  }
  const fresh = board.markets[0];
  if (!fresh || typeof fresh.opponent_team_id !== 'number') return false;

  const markets = SERVED.markets.map(
    (row) => (row.opponent_team_id === fresh.opponent_team_id ? fresh : row));
  // A pairing the bound board never carried is ADDED rather than dropped: the
  // roster can gain a team between reads, and refusing to show a market the
  // server just priced would be the surface overruling it.
  if (!markets.some((row) => row.opponent_team_id === fresh.opponent_team_id)) {
    markets.push(fresh);
  }
  SERVED = { ...SERVED, markets, computed_at: board.computed_at || SERVED.computed_at };
  return true;
}
