/* ============================================================================
 * FantasyStakes — the commissioner economy commands
 * WP3B · Rev 4.3 §16
 *
 * TWO GOVERNED CALLS, AND NEITHER OF THEM DECIDES ANYTHING.
 *
 *   PUT  /league/{id}/economy-config      set the three inputs (refused once frozen)
 *   POST /league/{id}/season-allocation   activate: issue the allocation, freeze the config
 *
 * `economy/league_economy_config.py` owns the governed ranges, the whole-Credit
 * rule and the post-activation refusal. `economy/season_allocation.py` owns the
 * issuance, its idempotency and the freeze it performs on the way through. This
 * module sends and reports; it holds no bound, computes no allocation and
 * decides no lifecycle state. Rev 4.3 §28.
 *
 * NOTHING IS CLAMPED HERE, on the same reasoning `settings-command.js` records:
 * an out-of-range value is SENT and the server's refusal is shown. Clamping
 * would silently change what a commissioner asked for, report success for a
 * value they did not choose, and hide a bounds regression in the one module
 * that is supposed to hold the bound.
 *
 * ACTIVATION IS NOT REACHABLE BY EDITING. There is no path from `saveEconomyConfig`
 * to `activateSeason` in this file — they are two exports and the caller must
 * choose the second deliberately. Rev 4.3 §16.4 requires activation to be a
 * deliberate confirmation, and the surest way to keep an accidental activation
 * impossible is for the editing path to have no way to cause one.
 * ========================================================================== */

import { ApiError, apiFetch } from './session.js';

/** A refusal the server explained, carrying its reason code. */
export class EconomyCommandError extends Error {
  constructor(status, reasonCode, message) {
    super(message);
    this.name = 'EconomyCommandError';
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

/** @param {unknown} error @returns {never} */
function rethrow(error) {
  if (error instanceof ApiError) {
    const detail = error.detail;
    const reason = detail && typeof detail === 'object'
      ? detail.reason_code : null;
    const message = detail && typeof detail === 'object'
      ? detail.message : String(detail || error.message);
    throw new EconomyCommandError(error.status, reason, message);
  }
  throw error;
}

/**
 * Read this league-season's economy configuration — draft or frozen.
 *
 * @param {number} leagueId
 * @returns {Promise<object>} an EconomyConfigOut
 */
export async function readEconomyConfig(leagueId) {
  try {
    return await apiFetch(`/league/${leagueId}/economy-config`);
  } catch (error) {
    return rethrow(error);
  }
}

/**
 * Set the three commissioner inputs.
 *
 * The route returns the WHOLE configuration including every derived value, so
 * a successful save is also the authoritative refresh — there is no second read
 * to fall out of step with what was just written, and the review figures the
 * commissioner is about to activate against are the server's own.
 *
 * @param {number} leagueId
 * @param {{weeklyBetMinimumCents: number,
 *          championshipContributionCents: number,
 *          skunkFeeCents: number}} inputs exact integer cents, unclamped
 * @returns {Promise<object>} the refreshed EconomyConfigOut
 */
export async function saveEconomyConfig(leagueId, inputs) {
  try {
    return await apiFetch(`/league/${leagueId}/economy-config`, {
      method: 'PUT',
      body: {
        weekly_bet_minimum_cents: inputs.weeklyBetMinimumCents,
        championship_contribution_cents: inputs.championshipContributionCents,
        skunk_fee_cents: inputs.skunkFeeCents,
      },
    });
  } catch (error) {
    return rethrow(error);
  }
}

/**
 * Activate the season: issue the opening allocation and freeze the economy.
 *
 * ONE CALL, WHOLE-LEAGUE, IDEMPOTENT. The route posts every team's allocation
 * and the freeze inside a single transaction; re-activating a league whose
 * allocation is already complete and matching returns `created: false` and
 * posts nothing. That is the server's guarantee, not this module's, and it is
 * why a double-tap cannot double-issue.
 *
 * @param {number} leagueId
 * @returns {Promise<object>} a SeasonAllocationOut
 */
export async function activateSeason(leagueId) {
  try {
    return await apiFetch(`/league/${leagueId}/season-allocation`, {
      method: 'POST',
    });
  } catch (error) {
    return rethrow(error);
  }
}

/**
 * Turn a refusal into a sentence a commissioner can act on.
 *
 * The reason codes are the server's own. Raw codes never reach the page
 * (Rev 4.3 §27); where a code is not one of the governed few, the server's
 * message is preferred over a guess.
 *
 * @param {EconomyCommandError} error
 * @returns {string}
 */
export function explainRefusal(error) {
  const code = error.reasonCode;

  if (code === 'ECONOMY_CONFIG_FROZEN') {
    return 'This season’s economy is locked. It governs Credits that have '
      + 'already been issued, so it cannot change until next season.';
  }
  if (code === 'ECONOMY_CONFIG_OUT_OF_RANGE') {
    return error.message || 'That amount is outside the allowed range.';
  }
  if (code === 'ECONOMY_CONFIG_NOT_WHOLE_CREDITS') {
    return 'Enter whole Credits — no fractions of a Credit.';
  }
  if (code === 'ECONOMY_CONFIG_BOUNDARY_UNAVAILABLE'
      || code === 'ECONOMY_CONFIG_BOUNDARY_INVALID') {
    return 'The season’s week boundaries are not set yet, so the allocation '
      + 'cannot be worked out. Connect the league to its provider first.';
  }
  if (code === 'ECONOMY_CONFIG_NO_ACTIVE_TEAMS') {
    return 'This league has no teams on its roster yet.';
  }
  if (error.status === 409) {
    return error.message
      || 'This league’s allocation is already partly issued and does not match '
      + 'the current configuration. Nothing has been changed.';
  }
  if (error.status === 400) {
    return error.message || 'The season could not be activated.';
  }
  if (error.status === 403) {
    return 'Your session does not hold commissioner authority for this league.';
  }
  return error.message || 'The change was refused.';
}
