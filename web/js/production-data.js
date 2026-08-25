/* ============================================================================
 * FantasyStakes — production data snapshot
 *
 * One place loads authoritative reads and passes exact server values to the
 * view models. RC2 adds the FantasyStakes Championship read beside standings;
 * the browser does not derive Championship Score or final placement.
 * ========================================================================== */

import { ApiError, apiFetch, currentIdentity } from './session.js';

let snapshot = null;

async function optional(promise) {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) throw error;
    return null;
  }
}

/**
 * Load every authoritative read this session can see, in parallel.
 *
 * @param {{leagueId: number, week?: number}} context
 * @returns {Promise<object>}
 */
export async function loadProductionData({ leagueId, week }) {
  const context = await optional(apiFetch(`/league/${leagueId}/context/me`));
  const resolvedWeek = (week !== undefined && week !== null)
    ? week
    : (context && context.week_resolved ? context.current_week : null);
  const identity = currentIdentity();
  const isCommissioner = Boolean(
    identity && identity.capabilities
    && Array.isArray(identity.capabilities.commissioner_league_ids)
    && identity.capabilities.commissioner_league_ids.includes(leagueId),
  );

  const [ledger, settings, slate, previousSlate, positions, reconciliation, action,
         weekMatchups, previousWeekMatchups, lifecycle, skunk, standings, championship,
         championshipResults, championshipCorrections,
         championshipConfig] = await Promise.all([
    optional(apiFetch(`/league/${leagueId}/ledger/me`)),
    optional(apiFetch(`/league/${leagueId}/settings`)),
    resolvedWeek === null
      ? Promise.resolve(null)
      : optional(apiFetch(`/league/${leagueId}/pool/slate/${resolvedWeek}`)),
    resolvedWeek === null || resolvedWeek <= 1
      ? Promise.resolve(null)
      : optional(apiFetch(`/league/${leagueId}/pool/slate/${resolvedWeek - 1}`)),
    isCommissioner ? optional(apiFetch(`/league/${leagueId}/ledger/positions`))
                   : Promise.resolve(null),
    isCommissioner ? optional(apiFetch(`/league/${leagueId}/ledger/reconciliation`))
                   : Promise.resolve(null),
    optional(apiFetch(`/league/${leagueId}/action/me`)),
    resolvedWeek === null
      ? Promise.resolve(null)
      : optional(apiFetch(`/league/${leagueId}/week/${resolvedWeek}/matchups`)),
    /* FINAL POR §6 — THE WEEK THAT FINISHED IS FETCHED TOO.
     *
     * Wrap Up reviews a completed week, and only the CURRENT one was ever
     * loaded — so the previous week's module could only ever say "week N has
     * not been loaded". The pool slate already fetched its previous week for
     * exactly this reason; the matchups now do the same, on the same guard. */
    resolvedWeek === null || resolvedWeek <= 1
      ? Promise.resolve(null)
      : optional(apiFetch(`/league/${leagueId}/week/${resolvedWeek - 1}/matchups`)),
    isCommissioner ? optional(apiFetch(`/league/${leagueId}/lifecycle`))
                   : Promise.resolve(null),
    resolvedWeek === null
      ? Promise.resolve(null)
      : optional(apiFetch(`/league/${leagueId}/week/${resolvedWeek}/skunk`)),
    optional(apiFetch(`/league/${leagueId}/standings`)),
    // RC2 — server-owned Championship Score / cutoff state. During the regular
    // season this is the live chase; after the cutoff it is the immutable
    // regular-season snapshot even while ordinary FantasyStakes play continues.
    optional(apiFetch(`/league/${leagueId}/championship`)),
    // RC2 season results: lifecycle, frozen podium, recorded awards and the
    // Yahoo podium, all server-derived. The browser recomputes none of it.
    optional(apiFetch(`/league/${leagueId}/championship/results`)),
    // Append-only correction audit. Member-scoped, so the whole league can read
    // why a championship figure changed.
    optional(apiFetch(`/league/${leagueId}/championship/corrections`)),
    // The governed championship contributions. Commissioner-editable until
    // activation freezes them; the surface reads this rather than assuming a
    // default, so a league that configured its own amount sees its own amount.
    optional(apiFetch(`/league/${leagueId}/championship/config`)),
  ]);

  // Keep one standings binding seam in shell.js. RC2 championship state rides
  // beside the existing three server-ranked standings arrays; no ranking or
  // money is recomputed here.
  const standingsWithChampionship = standings
    ? Object.freeze({ ...standings, championship, championshipResults })
    : null;

  snapshot = Object.freeze({
    leagueId,
    context,
    week: resolvedWeek,
    weekMatchups,
    previousWeekMatchups,
    ledger,
    settings,
    slate,
    previousSlate,
    positions,
    reconciliation,
    action,
    lifecycle,
    skunk,
    standings: standingsWithChampionship,
    championship,
    championshipResults,
    championshipCorrections,
    championshipConfig,
  });
  return snapshot;
}

export function productionData() {
  return snapshot;
}

export function clearProductionData() {
  snapshot = null;
}

export function hasAuthoritative(slice) {
  return Boolean(snapshot && snapshot[slice] !== null
                 && snapshot[slice] !== undefined);
}
