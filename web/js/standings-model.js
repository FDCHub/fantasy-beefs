/* ============================================================================
 * FantasyStakes — the competitive standings read-model
 * WP3B · Rev 4.3 §7
 *
 * The three standings orderings, in the same three modes every other Sprint 8
 * model uses: demo, authoritative, unavailable.
 *
 * THERE IS NO ILLUSTRATIVE STANDINGS TABLE, AND THAT IS DELIBERATE — the same
 * ruling `skunk-model.js` makes, for the same reason. A prototype wager card is
 * useful for reviewing a layout. A prototype LEAGUE TABLE is not: it names real
 * GMs in a false order and states false winnings against them, and it is the
 * first thing a GM sees, because Standings is the default tab. WP3B §26 forbids
 * new fabricated production content and §8 requires an intentional empty state
 * instead. So DEMO here draws the no-data state, exactly as UNAVAILABLE does.
 *
 * IT RANKS NOTHING. The order is the SERVER's — `GET /league/{id}/standings`
 * returns three already-ordered lists with the rank already assigned, including
 * the documented ascending-team-id tie-break. This module holds them and reports
 * what it holds. Re-sorting here would be a second place the ranking rule lives,
 * and the two would eventually disagree.
 *
 * IT COMPUTES NO MONEY. Every figure arrives as exact integer cents and is
 * passed through untouched; `credits.js` decides how a cent figure is DRAWN, at
 * the moment of drawing. Rev 4.3 §28 — the frontend renders backend read models
 * and creates no second economic engine.
 * ========================================================================== */

export const STANDINGS_MODE_DEMO = 'demo';
export const STANDINGS_MODE_AUTHORITATIVE = 'authoritative';
export const STANDINGS_MODE_UNAVAILABLE = 'unavailable';

/** The three tables, in Rev 4.3 §7's stacked order. */
export const STANDINGS_TABLES = Object.freeze([
  Object.freeze({
    key: 'overall',
    heading: 'OVERALL STANDINGS',
    columns: Object.freeze(['RK', 'TEAM', 'VERSUS', 'POOLS', 'NET']),
  }),
  Object.freeze({
    key: 'versus',
    heading: 'VERSUS STANDINGS',
    columns: Object.freeze(['RK', 'TEAM', 'W-L', 'NET']),
  }),
  Object.freeze({
    key: 'pools',
    heading: 'POOL STANDINGS',
    columns: Object.freeze(['RK', 'TEAM', 'WINS', 'NET']),
  }),
]);

/** Why a table has no rows to draw. Presentation states, not error codes. */
export const STANDINGS_STATE_READY = 'ready';
export const STANDINGS_STATE_LOADING = 'loading';
export const STANDINGS_STATE_NO_DATA = 'no-data';
export const STANDINGS_STATE_UNAVAILABLE = 'unavailable';
export const STANDINGS_STATE_NOT_ACTIVATED = 'not-activated';

let MODE = STANDINGS_MODE_DEMO;
let SERVED = null;
let LOADING = false;

/**
 * Bind the authoritative standings read.
 *
 * @param {object} body a LeagueStandingsOut
 */
export function bindStandings(body) {
  SERVED = body;
  MODE = STANDINGS_MODE_AUTHORITATIVE;
  LOADING = false;
}

/** The read failed or was refused. The tables draw unavailable, never invented. */
export function markStandingsUnavailable() {
  SERVED = null;
  MODE = STANDINGS_MODE_UNAVAILABLE;
  LOADING = false;
}

/** The read is in flight. Distinct from "there is nothing to show". */
export function markStandingsLoading() {
  LOADING = true;
}

/** Return to the unbound default. Used on sign-out and by the suites. */
export function unbindStandings() {
  SERVED = null;
  MODE = STANDINGS_MODE_DEMO;
  LOADING = false;
}

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function standingsMode() {
  return MODE;
}

/** The served body, when bound. @returns {object|null} */
export function servedStandings() {
  return SERVED;
}

/**
 * The acting GM's team id, so the view can mark their row.
 *
 * FROM THE SERVER, NOT FROM A NAME MATCH. Two teams can share a display name,
 * and a renamed team would silently stop being highlighted. Rev 4.3 §7.4
 * requires the row be identifiable at any rank, which means identifying it by
 * the id the server ranked it under.
 *
 * @returns {number|null}
 */
export function actingTeamId() {
  if (MODE !== STANDINGS_MODE_AUTHORITATIVE || !SERVED) return null;
  return typeof SERVED.acting_team_id === 'number'
    ? SERVED.acting_team_id : null;
}

/**
 * The presentation state of the standings surface.
 *
 * LOADING WINS OVER EVERYTHING, because it is the only one of these that is
 * about the request rather than about the answer. A bound-but-empty league and
 * a league whose read is still in flight look identical if loading is not
 * reported first, and telling a GM "no standings yet" while the request is
 * still running is a wrong answer that will correct itself a moment later —
 * which is worse than saying nothing, because they will have read it.
 *
 * A LEAGUE WITH NO TEAMS IS `not-activated`, not `no-data`. An empty roster
 * means the season has not been set up, which is a different sentence from "the
 * season is set up and nobody has won anything yet" — and only the first of
 * those tells the commissioner there is something for them to do.
 *
 * @returns {'ready'|'loading'|'no-data'|'unavailable'|'not-activated'}
 */
export function standingsState() {
  if (LOADING) return STANDINGS_STATE_LOADING;
  if (MODE === STANDINGS_MODE_UNAVAILABLE) return STANDINGS_STATE_UNAVAILABLE;
  if (MODE === STANDINGS_MODE_DEMO || !SERVED) return STANDINGS_STATE_NO_DATA;
  if (rowsFor('overall').length === 0) return STANDINGS_STATE_NOT_ACTIVATED;
  return STANDINGS_STATE_READY;
}

/**
 * One table's rows, exactly as the server ordered them.
 *
 * @param {'overall'|'versus'|'pools'} key
 * @returns {Array<object>}
 */
export function rowsFor(key) {
  if (MODE !== STANDINGS_MODE_AUTHORITATIVE || !SERVED) return [];
  const rows = SERVED[key];
  return Array.isArray(rows) ? rows : [];
}

/**
 * The cell values one table shows for one row, already selected per column.
 *
 * WHY THE SELECTION LIVES HERE AND NOT IN THE VIEW. The three tables show
 * different columns over the same row shape, and a view that reached for
 * `row.versus_net_cents` in one table and `row.net_cents` in another is one
 * typo away from a table that ranks by one figure and prints another. This
 * names the pairing once, and the suite asserts each table's cells against the
 * ordering it was ranked by.
 *
 * Cents are returned as CENTS. Nothing here formats — `credits.js` owns that,
 * at the moment of drawing.
 *
 * @param {'overall'|'versus'|'pools'} key
 * @param {object} row
 * @returns {{rank: number, teamName: string,
 *            cells: Array<{kind: 'text'|'cents', value: any}>}}
 */
export function cellsFor(key, row) {
  const base = { rank: Number(row.rank), teamName: String(row.team_name || '') };

  if (key === 'overall') {
    return {
      ...base,
      cells: [
        { kind: 'cents', value: Number(row.versus_net_cents) },
        { kind: 'cents', value: Number(row.pool_net_cents) },
        { kind: 'cents', value: Number(row.net_cents) },
      ],
    };
  }
  if (key === 'versus') {
    return {
      ...base,
      cells: [
        { kind: 'text', value: String(row.versus_record || '') },
        { kind: 'cents', value: Number(row.versus_net_cents) },
      ],
    };
  }
  if (key === 'pools') {
    return {
      ...base,
      cells: [
        { kind: 'text', value: String(row.pool_wins) },
        { kind: 'cents', value: Number(row.pool_net_cents) },
      ],
    };
  }
  throw new Error(`unknown standings table "${key}"`);
}

/**
 * The figure a table is RANKED BY, for the suite to check the ordering against.
 *
 * Exported so the certification can assert that each served table is actually
 * descending in its own ranking figure — a claim that cannot be made from the
 * view, and that would otherwise rest entirely on the server being right.
 *
 * @param {'overall'|'versus'|'pools'} key
 * @param {object} row
 * @returns {number} exact integer cents
 */
export function rankingCents(key, row) {
  if (key === 'overall') return Number(row.net_cents);
  if (key === 'versus') return Number(row.versus_net_cents);
  if (key === 'pools') return Number(row.pool_net_cents);
  throw new Error(`unknown standings table "${key}"`);
}
