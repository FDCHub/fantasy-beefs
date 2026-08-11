/* ============================================================================
 * FantasyStakes — League context and provider-backed Week state
 * Sprint 8 Package 4C-3
 *
 * ONE MODULE FOR BOTH TABS, because both are asking the same backend the same
 * two questions: who is this league and what week is it, then what did the
 * provider publish for that week. Splitting them would give the two tabs their
 * own copy of "which week is it", which is the exact drift this package exists
 * to remove.
 *
 * THE WEEK IS NOT A CONSTANT. Until now `CURRENT_WEEK = 5` lived in an
 * illustrative fixture and was imported by the production shell, so a real
 * league in week 9 was served week 5 — its Pool slate, its Action header, every
 * week-scoped figure. The provider states its own current week; Sprint 6 parsed
 * it and dropped it, and S8-P4C-3 persists it. This module reads it and nothing
 * else does.
 *
 * FOUR STATES, AND THE DIFFERENCES BETWEEN THEM ARE LOAD-BEARING:
 *
 *   demo           the Rev 4.2 illustrative league — component suites;
 *   authoritative  a real context read is bound;
 *   unavailable    the read failed or was refused;
 *   and WITHIN authoritative, `provider_state` distinguishes:
 *       bound      a provider refresh has stated a week;
 *       pending    provider identity exists, but no refresh has run;
 *       absent     the league has no provider identity at all.
 *
 * `pending` IS NOT `unavailable`. A league that has never been refreshed has a
 * real, known answer — "nothing published yet" — and saying so is different
 * from admitting the page could not read anything. Yahoo credentials are not
 * present in this environment, so `pending` is the state most surfaces will
 * actually meet, and it must never render as illustrative data.
 * ========================================================================== */

export const LEAGUE_MODE_DEMO = 'demo';
export const LEAGUE_MODE_AUTHORITATIVE = 'authoritative';
export const LEAGUE_MODE_UNAVAILABLE = 'unavailable';

/** Provider states, mirroring `reports/league_read_model`. */
export const PROVIDER_BOUND = 'bound';
export const PROVIDER_PENDING = 'pending';
export const PROVIDER_ABSENT = 'absent';

let MODE = LEAGUE_MODE_DEMO;
let CONTEXT = null;
/** week number → served WeekStateOut */
const WEEKS = new Map();

/**
 * Bind the authoritative league context.
 *
 * @param {object} body a LeagueContextOut from GET /league/{id}/context/me
 */
export function bindLeagueContext(body) {
  if (!body || typeof body !== 'object'
      || typeof body.league_id !== 'number') {
    markLeagueUnavailable();
    return;
  }
  CONTEXT = body;
  MODE = LEAGUE_MODE_AUTHORITATIVE;
}

/**
 * Bind one week's provider-backed matchups.
 *
 * @param {number} week
 * @param {object} body a WeekStateOut
 */
export function bindWeekMatchups(week, body) {
  if (!body || typeof body !== 'object') return;
  WEEKS.set(week, body);
}

/** The read failed or was refused. */
export function markLeagueUnavailable() {
  CONTEXT = null;
  WEEKS.clear();
  MODE = LEAGUE_MODE_UNAVAILABLE;
}

/** Restore the illustrative source — component suites and sign-out. */
export function unbindLeague() {
  CONTEXT = null;
  WEEKS.clear();
  MODE = LEAGUE_MODE_DEMO;
}

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function leagueMode() {
  return MODE;
}

/** The served context, when bound. @returns {object|null} */
export function servedContext() {
  return CONTEXT;
}

/**
 * The authoritative current week, or null.
 *
 * NULL IS AN ANSWER, and callers must treat it as one. It means no provider
 * refresh has ever stated a week for this league — so a week-scoped surface has
 * nothing to scope to and says so, rather than falling back to 5.
 *
 * @returns {number|null}
 */
export function currentWeek() {
  if (MODE !== LEAGUE_MODE_AUTHORITATIVE || !CONTEXT) return null;
  return CONTEXT.week_resolved ? CONTEXT.current_week : null;
}

/** @returns {'bound'|'pending'|'absent'|null} */
export function providerState() {
  if (MODE !== LEAGUE_MODE_AUTHORITATIVE || !CONTEXT) return null;
  return CONTEXT.provider_state;
}

/**
 * The league's name, as the backend holds it.
 *
 * In production this is `leagues.name` — which is the PROVIDER's name for the
 * league once a refresh has bound it, and a locally-chosen one otherwise.
 * Either way it is the real league's name and never the fixture's.
 *
 * @returns {string|null}
 */
export function leagueName() {
  if (MODE !== LEAGUE_MODE_AUTHORITATIVE || !CONTEXT) return null;
  return CONTEXT.league_name;
}

/** The acting GM's own team, authoritative. @returns {object|null} */
export function actingTeam() {
  if (MODE !== LEAGUE_MODE_AUTHORITATIVE || !CONTEXT) return null;
  return Object.freeze({
    teamId: CONTEXT.acting_team_id,
    name: CONTEXT.acting_team_name,
    owner: CONTEXT.acting_team_owner,
    providerTeamKey: CONTEXT.acting_provider_team_key,
  });
}

/**
 * The acting GM's season record.
 *
 * `resolved: false` means no matchup has been both finalised AND given a
 * winner by the provider — so there is no record to state. The label is null
 * then, NOT `0–0`: a team that has played nothing and a team that has lost
 * everything are different, and one string cannot mean both.
 *
 * @returns {{resolved: boolean, label: string|null, wins: number|null,
 *            losses: number|null, decided: number}}
 */
export function seasonRecord() {
  if (MODE !== LEAGUE_MODE_AUTHORITATIVE || !CONTEXT) {
    return Object.freeze({ resolved: false, label: null, wins: null,
                           losses: null, decided: 0 });
  }
  return Object.freeze({
    resolved: Boolean(CONTEXT.record_resolved),
    label: CONTEXT.record_label ?? null,
    wins: CONTEXT.wins ?? null,
    losses: CONTEXT.losses ?? null,
    decided: CONTEXT.decided || 0,
  });
}

/**
 * The provider-backed matchups for one week.
 *
 * Returns `null` when nothing has been bound for that week — distinct from an
 * empty array, which would claim the provider published no matchups.
 *
 * @param {number} week
 * @returns {Array<object>|null}
 */
export function weekMatchups(week) {
  if (MODE !== LEAGUE_MODE_AUTHORITATIVE) return null;
  const served = WEEKS.get(week);
  if (!served) return null;
  return (served.matchups || []).map(normaliseMatchup);
}

/**
 * Whether the provider has published nothing for this week.
 *
 * AN AUTHORITATIVE EMPTY. Distinct from `weekMatchups() === null`, which means
 * the page has not read that week at all.
 *
 * @param {number} week
 * @returns {boolean}
 */
export function weekIsEmpty(week) {
  const served = WEEKS.get(week);
  return Boolean(served && served.empty);
}

/**
 * The acting GM's own matchup for a week, or null.
 *
 * ORIENTATION IS READ, NEVER CHOSEN. The served row already says which side is
 * home, decided from sorted provider team KEYS rather than payload order — so
 * this reports which side the GM is on and does not put them on one.
 *
 * @param {number} week
 * @returns {object|null}
 */
export function actingMatchup(week) {
  const rows = weekMatchups(week);
  if (!rows) return null;
  return rows.find((m) => m.involvesActingTeam) || null;
}

/** @param {object} row a WeekMatchupOut */
function normaliseMatchup(row) {
  return Object.freeze({
    matchupId: row.matchup_id,
    week: row.week,
    providerMatchupKey: row.provider_matchup_key,
    home: normaliseSide(row.home),
    away: normaliseSide(row.away),
    // FINALITY IS THE PROVIDER'S TIMESTAMP. Never "the week is in the past",
    // never "the score stopped moving".
    final: Boolean(row.final),
    finalizedAt: row.finalized_at || null,
    winnerTeamId: row.winner_team_id ?? null,
    refreshedAt: row.refreshed_at || null,
    involvesActingTeam: Boolean(row.involves_acting_team),
    actingSide: row.acting_side || null,
  });
}

function normaliseSide(side) {
  return Object.freeze({
    teamId: side.team_id,
    name: side.team_name,
    owner: side.owner,
    providerTeamKey: side.provider_team_key,
    // NULL, NOT 0. A provider that reported no points has not said the team
    // scored none, and the surface must be able to tell those apart.
    points: (typeof side.points === 'number') ? side.points : null,
    isActingTeam: Boolean(side.is_acting_team),
  });
}
