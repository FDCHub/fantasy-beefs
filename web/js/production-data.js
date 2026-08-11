/* ============================================================================
 * FantasyStakes — production data snapshot
 * Sprint 8 Package 4
 *
 * WHAT THIS IS. One place that loads the authoritative reads a signed-in GM's
 * session needs, holds them for the life of the page, and hands them to the
 * view models. It owns no arithmetic and no presentation: every figure it
 * carries came from a backend read model and is passed through untouched, in
 * exact integer cents.
 *
 * IT MAKES NO NETWORK CALL OF ITS OWN. Everything goes through `apiFetch` in
 * session.js, which is still the application's only door — the certification
 * suite scans every other module for `fetch(` and this one is not an
 * exception to that.
 *
 * WHY A SNAPSHOT RATHER THAN PER-COMPONENT FETCHING. The Rev 4.2 tabs render
 * synchronously from view models, and that is worth keeping: it is what makes
 * the derivations checkable and the components testable without a server. So
 * the data is loaded ONCE, before the panels are built, and the view models
 * read it synchronously afterwards. A component that fetched for itself would
 * also have to decide what to draw while waiting, and five tabs would answer
 * that question five ways.
 *
 * PARTIAL LOADS ARE NORMAL AND ARE NOT ERRORS. A GM is not a commissioner, so
 * the commissioner reads will 403 for most sessions; a league may have no Pool
 * slate drawn yet. Each read is therefore settled independently and a refusal
 * leaves that slice `null`. The view models treat `null` as "no authoritative
 * source in this session" and fall back to the accepted unresolved
 * presentation — which is exactly what the POR asks for, and is why a failed
 * commissioner read must not take the Ledger tab down with it.
 *
 * NOTHING HERE INVENTS A VALUE. Where the backend has no source for a field
 * the Sprint 7 Ledger showed — season winnings, award splits, the activity
 * nets — this module carries nothing for it, and the view model keeps the
 * illustrative-neutral treatment. P3 named those fields; P4 does not fill them.
 * ========================================================================== */

import { ApiError, apiFetch, currentIdentity } from './session.js';

/**
 * The loaded snapshot, or null before the first load.
 * @type {object|null}
 */
let snapshot = null;

/**
 * Settle a read without letting a refusal fail the whole load.
 *
 * A 401 is deliberately NOT swallowed: it means the session ended, and
 * `apiFetch` has already dropped the identity, so the shell is about to show
 * the gate. Turning that into `null` here would leave the app rendering an
 * empty-but-signed-in view of a session that no longer exists.
 *
 * @param {Promise<any>} promise
 * @returns {Promise<any|null>}
 */
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
 * @returns {Promise<object>} the snapshot
 */
export async function loadProductionData({ leagueId, week }) {
  const identity = currentIdentity();
  const isCommissioner = Boolean(
    identity && identity.capabilities
    && Array.isArray(identity.capabilities.commissioner_league_ids)
    && identity.capabilities.commissioner_league_ids.includes(leagueId),
  );

  const [ledger, settings, slate, positions, reconciliation, action]
      = await Promise.all([
    optional(apiFetch(`/league/${leagueId}/ledger/me`)),
    optional(apiFetch(`/league/${leagueId}/settings`)),
    week === undefined
      ? Promise.resolve(null)
      : optional(apiFetch(`/league/${leagueId}/pool/slate/${week}`)),
    // Asked for only when the server has already said this user holds
    // commissioner authority here. Requesting it regardless would work — the
    // route would refuse — but it would mean every GM's page load generated a
    // 403 in the operator's logs, which is noise that hides real refusals.
    isCommissioner ? optional(apiFetch(`/league/${leagueId}/ledger/positions`))
                   : Promise.resolve(null),
    isCommissioner ? optional(apiFetch(`/league/${leagueId}/ledger/reconciliation`))
                   : Promise.resolve(null),
    // The GM's own Action tab. Team-less by design — the route resolves the
    // acting team from the session, so there is no id here to substitute.
    optional(apiFetch(`/league/${leagueId}/action/me`)),
  ]);

  snapshot = Object.freeze({
    leagueId,
    week: week ?? null,
    ledger,
    settings,
    slate,
    positions,
    reconciliation,
    action,
  });
  return snapshot;
}

/** The loaded snapshot, or null. @returns {object|null} */
export function productionData() {
  return snapshot;
}

/** Drop the snapshot — used on sign-out so no league state survives it. */
export function clearProductionData() {
  snapshot = null;
}

/**
 * Whether an authoritative slice is present for this session.
 *
 * The view models ask this rather than testing truthiness themselves, because
 * `0` is a perfectly good authoritative figure and `null` is the absence of
 * one — a distinction a truthiness test loses exactly where money is involved.
 *
 * @param {string} slice
 * @returns {boolean}
 */
export function hasAuthoritative(slice) {
  return Boolean(snapshot && snapshot[slice] !== null
                 && snapshot[slice] !== undefined);
}