/* ============================================================================
 * FantasyStakes — competitive standings + RC2 Championship state
 *
 * The server owns every ranking and every cent. During the regular season the
 * Overall table is the live FantasyStakes Championship Chase. Once the server
 * returns a FINAL championship snapshot, Overall switches to that immutable
 * regular-season result while Versus and Pool tables may continue reflecting
 * postseason FantasyStakes play.
 * ========================================================================== */

export const STANDINGS_MODE_DEMO = 'demo';
export const STANDINGS_MODE_AUTHORITATIVE = 'authoritative';
export const STANDINGS_MODE_UNAVAILABLE = 'unavailable';

export const STANDINGS_TABLES = Object.freeze([
  // UIRECON WAVE 2 — `OVERALL` rather than a second `FANTASYSTAKES
  // CHAMPIONSHIP`. The tab title directly above this table already names the
  // competition, and repeating it on the first table said the same thing twice
  // in about forty pixels while the two tables below carried real distinctions.
  // The table names WHICH standings it is; the tab names what they are for.
  Object.freeze({
    key: 'overall',
    heading: 'OVERALL',
    // UIRECON REV 1.4 — `POOLS`, not `PROP POOLS`.
    //
    // Two words could not be drawn on one line in a figure column at any
    // certified phone width: `PROP POOLS` measured 82px against a 60px cell,
    // took a second line, and stood the whole header row at 45px while the two
    // tables below it stood at 28px. The table it heads is already `PROP POOL
    // STANDINGS` and the column below it already holds Prop Pool Credits, so
    // the word `PROP` was carrying no information this header did not have.
    //
    // `MATCHUPS` IS NOT ABBREVIATED and is not `MATCHES`. It is the product's
    // term for the contest, it is the term the two tables below use, and a
    // column that names a different thing than the table it sits in would cost
    // more than the pixels it saved. The width it needs is bought in
    // `standings.css` instead — see the column-width contract there.
    // ── FINAL POR UI-2 §26 — SIX COLUMNS, AND THE LAST TWO ARE NEW ─────────
    //
    // `SKUNK` and `FS SCORE` replace the single `NET`. The Score gained a third
    // term in WP-7 (`Matchups + Prop Pools - Skunk Fees`), and a table that
    // shows two of the three terms and then a total the reader cannot derive
    // from them is worse than one that shows none: it invites the reader to
    // add the two columns they CAN see and conclude the total is wrong.
    //
    // `NET` BECAME `FS SCORE` because the column no longer holds a net. It
    // holds the FantasyStakes Score, which is the thing the championship is
    // decided on, and naming it after the concept is what lets the explanatory
    // copy below the table state the identity in the reader's own vocabulary.
    //
    // SKUNK IS A POSITIVE MAGNITUDE and the Score has already subtracted it.
    // The server says so on the field and this shows what the server sent; the
    // one thing a client must never do here is subtract it again.
    columns: Object.freeze(['RK', 'TEAM', 'MATCHUPS', 'POOLS', 'SKUNK',
                            'FS SCORE']),
  }),
  Object.freeze({
    key: 'versus',
    heading: 'MATCHUP STANDINGS',
    columns: Object.freeze(['RK', 'TEAM', 'W-L', 'NET']),
  }),
  Object.freeze({
    key: 'pools',
    heading: 'PROP POOL STANDINGS',
    columns: Object.freeze(['RK', 'TEAM', 'WINS', 'NET']),
  }),
]);

export const STANDINGS_STATE_READY = 'ready';
export const STANDINGS_STATE_LOADING = 'loading';
export const STANDINGS_STATE_NO_DATA = 'no-data';
export const STANDINGS_STATE_UNAVAILABLE = 'unavailable';
export const STANDINGS_STATE_NOT_ACTIVATED = 'not-activated';

let MODE = STANDINGS_MODE_DEMO;
let SERVED = null;
let LOADING = false;

function normalizedFrozenOverall(championship) {
  if (!championship || championship.status !== 'FINAL'
      || !Array.isArray(championship.rows)) return null;
  return championship.rows.map((row) => Object.freeze({
    team_id: Number(row.team_id),
    team_name: String(row.team_name || ''),
    owner: String(row.owner || ''),
    rank: Number(row.place),
    versus_net_cents: Number(row.matchup_net_cents),
    pool_net_cents: Number(row.prop_pool_net_cents),
    net_cents: Number(row.championship_score_cents),
    // A FROZEN RC2 SNAPSHOT CARRIES NO SKUNK, and that is correct rather than
    // a gap: the snapshot belongs to a legacy season, whose Score is the
    // two-term identity, and WP-7's era gate reports 0 for one either way.
    skunk_fees_cents: 0,
    championship_tied: Boolean(row.tied),
  }));
}

export function bindStandings(body) {
  const frozenOverall = normalizedFrozenOverall(body && body.championship);
  SERVED = body ? Object.freeze({ ...body, frozenOverall }) : body;
  MODE = STANDINGS_MODE_AUTHORITATIVE;
  LOADING = false;
}

export function markStandingsUnavailable() {
  SERVED = null;
  MODE = STANDINGS_MODE_UNAVAILABLE;
  LOADING = false;
}

export function markStandingsLoading() {
  LOADING = true;
}

export function unbindStandings() {
  SERVED = null;
  MODE = STANDINGS_MODE_DEMO;
  LOADING = false;
}

export function standingsMode() {
  return MODE;
}

export function servedStandings() {
  return SERVED;
}

export function championshipState() {
  if (MODE !== STANDINGS_MODE_AUTHORITATIVE || !SERVED) return null;
  return SERVED.championship || null;
}

export function championshipIsFinal() {
  const state = championshipState();
  return Boolean(state && state.status === 'FINAL');
}

/**
 * The server-derived championship lifecycle.
 *
 * FOUR STATES, NOT TWO. The frozen snapshot answers "is the field closed", which
 * is not the same question as "is every eligible result in" or "has the pot been
 * paid". Reporting FINAL the moment a snapshot exists told a GM the season was
 * decided while an eligible regular-season contest was still unresolved.
 *
 * DERIVED BY THE SERVER, READ HERE. `/championship/results` owns the rule; this
 * returns what it said and falls back to the older two-state read only when that
 * surface is unavailable, so an older server degrades rather than breaks.
 *
 * @returns {'LIVE'|'FROZEN'|'FINAL'|'PAID'}
 */
export function championshipLifecycle() {
  const results = championshipResults();
  if (results && typeof results.lifecycle === 'string') return results.lifecycle;
  // FAIL CONSERVATIVELY. A frozen snapshot proves the scoring window closed; it
  // proves nothing about whether every eligible result is in, and only the
  // server can answer that. Reporting FINAL here would tell a GM the season was
  // decided on the strength of a fact that does not decide it, so the fallback
  // reports FROZEN and lets the server upgrade it.
  return championshipIsFinal() ? 'FROZEN' : 'LIVE';
}

/** The `/championship/results` body, when bound. @returns {object|null} */
export function championshipResults() {
  if (MODE !== STANDINGS_MODE_AUTHORITATIVE || !SERVED) return null;
  return SERVED.championshipResults || null;
}

/** Eligible contests still unresolved. Empty once the championship is FINAL. */
export function championshipUnresolved() {
  const results = championshipResults();
  return results && Array.isArray(results.unresolved) ? results.unresolved : [];
}

/**
 * Whether this row shares its Championship Score with another GM.
 *
 * READ FROM THE SERVER'S OWN `tied` FLAG, never recomputed by comparing cents
 * here — that would be a second place the tie rule lives, and the payout splits
 * on the server's answer, not this one.
 */
export function isTiedRow(row) {
  return Boolean(row && (row.championship_tied || row.tied));
}

export function actingTeamId() {
  if (MODE !== STANDINGS_MODE_AUTHORITATIVE || !SERVED) return null;
  return typeof SERVED.acting_team_id === 'number'
    ? SERVED.acting_team_id : null;
}

export function standingsState() {
  if (LOADING) return STANDINGS_STATE_LOADING;
  if (MODE === STANDINGS_MODE_UNAVAILABLE) return STANDINGS_STATE_UNAVAILABLE;
  if (MODE === STANDINGS_MODE_DEMO || !SERVED) return STANDINGS_STATE_NO_DATA;
  if (rowsFor('overall').length === 0) return STANDINGS_STATE_NOT_ACTIVATED;
  return STANDINGS_STATE_READY;
}

export function rowsFor(key) {
  if (MODE !== STANDINGS_MODE_AUTHORITATIVE || !SERVED) return [];
  if (key === 'overall' && Array.isArray(SERVED.frozenOverall)) {
    return SERVED.frozenOverall;
  }
  const rows = SERVED[key];
  return Array.isArray(rows) ? rows : [];
}

export function cellsFor(key, row) {
  const base = { rank: Number(row.rank), teamName: String(row.team_name || '') };

  if (key === 'overall') {
    return {
      ...base,
      cells: [
        { kind: 'cents', value: Number(row.versus_net_cents) },
        { kind: 'cents', value: Number(row.pool_net_cents) },
        // SKUNK IS ITS OWN KIND. It is a positive magnitude — a fee assessed,
        // never a gain — so it must not be drawn with the signed +/- grammar
        // and the positive/negative colouring the three money columns use. A
        // green `+$5.00` in the Skunk column would say the opposite of what
        // happened. `0` is the common case and is drawn plainly.
        { kind: 'skunk', value: Number(row.skunk_fees_cents || 0) },
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

export function rankingCents(key, row) {
  if (key === 'overall') return Number(row.net_cents);
  if (key === 'versus') return Number(row.versus_net_cents);
  if (key === 'pools') return Number(row.pool_net_cents);
  throw new Error(`unknown standings table "${key}"`);
}
