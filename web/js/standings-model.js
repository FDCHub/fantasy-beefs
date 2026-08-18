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
  Object.freeze({
    key: 'overall',
    heading: 'FANTASYSTAKES CHAMPIONSHIP',
    columns: Object.freeze(['RK', 'TEAM', 'MATCHUPS', 'PROP POOLS', 'NET']),
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
