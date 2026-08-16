/* ============================================================================
 * FantasyStakes — reading the authoritative Versus market board
 * WP3C.2
 *
 * ONE FUNCTION, ONE GET. The board is a pure read of the pricing model, so it
 * travels as a GET through `session.js` — the app's one network door — and
 * carries no CSRF header because it is not a write and does not pretend to be.
 *
 * NOTHING HERE COMPUTES. It asks and it returns. The spread's sign, the
 * rounding of the line and the choice of median all happened on the server,
 * in `odds/market_lines.py`, before this request was answered.
 * ========================================================================== */

import { ApiError, apiFetch } from './session.js';

/** A refusal the server explained, carrying its reason code. */
export class MarketError extends Error {
  constructor(status, reasonCode, message) {
    super(message);
    this.name = 'MarketError';
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

/**
 * Read this GM's offered Versus markets for a week.
 *
 * @param {number} leagueId
 * @param {number} week the authoritative week
 * @returns {Promise<object>} a VersusBoardOut
 */
export async function requestMarketBoard(leagueId, week) {
  try {
    return await apiFetch(`/league/${leagueId}/versus/board?week=${week}`);
  } catch (error) {
    if (error instanceof ApiError) {
      const detail = error.detail;
      const reason = detail && typeof detail === 'object'
        ? detail.reason_code : null;
      const message = detail && typeof detail === 'object'
        ? detail.message : String(detail || error.message);
      throw new MarketError(error.status, reason, message);
    }
    throw error;
  }
}
