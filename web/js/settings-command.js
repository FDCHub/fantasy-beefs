/* ============================================================================
 * FantasyStakes — the Standard Pool Bet command
 * Sprint 8 Package 4B-3
 *
 * THE ONE GOVERNED SETTINGS MUTATION IN MVP. It goes to
 * `PUT /league/{id}/settings/pool-entry`, which delegates to
 * `betting/pool_funding.configure_pool_weekly_entry` — the setter that owns the
 * governed $1–$5 bounds and the freeze at the season's first collection.
 *
 * IT IS NOT THE LEGACY ROUTE. `POST /pool/config` writes
 * `PoolConfig.weekly_entry_cents`, which belongs to the retired three-pot
 * engine and defaults to 1000. The Rev 4.2 Standard Pool Bet is
 * `pool_weekly_entry_cents`. Binding this control to the legacy route would
 * have written a column nothing reads and displayed a figure nothing honours.
 *
 * NOTHING IS CLAMPED HERE. An out-of-bounds value is SENT and the server's
 * refusal is shown. Clamping client-side would silently change what a
 * commissioner asked for and report success for a value they did not choose —
 * and it would hide a bounds regression in the setter, which is the one place
 * the bound is supposed to live.
 * ========================================================================== */

import { ApiError, apiFetch } from './session.js';

/** A refusal the server explained, carrying its reason code. */
export class SettingsCommandError extends Error {
  constructor(status, reasonCode, message) {
    super(message);
    this.name = 'SettingsCommandError';
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

/**
 * Set the league's Standard Pool Bet.
 *
 * @param {number} leagueId
 * @param {number} cents exact integer cents, unclamped
 * @returns {Promise<object>} the refreshed LeagueSettingsOut
 */
export async function updatePoolEntry(leagueId, cents) {
  try {
    // The route returns the whole settings body, so a successful save IS the
    // authoritative refresh — there is no second read to fall out of step with
    // what was just written.
    return await apiFetch(`/league/${leagueId}/settings/pool-entry`, {
      method: 'PUT',
      body: { cents },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      const detail = error.detail;
      const reason = detail && typeof detail === 'object'
        ? detail.reason_code : null;
      const message = detail && typeof detail === 'object'
        ? detail.message : String(detail || error.message);
      throw new SettingsCommandError(error.status, reason, message);
    }
    throw error;
  }
}

/**
 * Turn a refusal into a sentence a commissioner can act on.
 *
 * The server's own message is preferred where it is specific; these cover the
 * two governed refusals by reason code so the wording does not depend on
 * prose the backend may reword.
 *
 * @param {SettingsCommandError} error
 * @returns {string}
 */
export function explainRefusal(error) {
  if (error.reasonCode === 'ENTRY_FROZEN') {
    return 'The Standard Pool Bet is frozen for this season — the first Pool '
      + 'week has been collected and the entry is fixed from that point.';
  }
  if (error.reasonCode === 'ENTRY_OUT_OF_BOUNDS') {
    return error.message || 'That amount is outside the governed bounds.';
  }
  if (error.status === 403) {
    return 'Your session does not hold commissioner authority for this league.';
  }
  return error.message || 'The change was refused.';
}