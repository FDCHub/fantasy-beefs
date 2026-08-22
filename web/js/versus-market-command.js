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
 * ONE OPPONENT, OR ALL OF THEM. `opponent_team_id` is the route's own optional
 * filter and has been since WP3C.2; the per-card refresh control uses it so
 * re-reading one price costs one pairing's Monte Carlo rather than the league's.
 * Passing nothing is the whole board, exactly as before.
 *
 * IT IS THE SAME GET EITHER WAY — same eligibility authority, same refusal
 * vocabulary, same nothing-is-written guarantee. A narrower question does not
 * get a weaker answer.
 *
 * @param {number} leagueId
 * @param {number} week the authoritative week
 * @param {number|null} [opponentTeamId] one pairing, or null for the board
 * @returns {Promise<object>} a VersusBoardOut
 */
export async function requestMarketBoard(leagueId, week, opponentTeamId = null) {
  // THE NULLISH CHECK IS LOAD-BEARING, and it is the whole reason this is not
  // one `Number.isFinite` call. `Number(null)` is 0 and `Number('')` is 0 —
  // both finite — so a coercion-only guard turns "the whole board" into
  // "opponent 0", which is not a team and which the route correctly refuses
  // with a 400. That refusal reaches the shell as a failed board read, and
  // every card on Play draws its unpriced state.
  const scoped = opponentTeamId !== null && opponentTeamId !== undefined
    && opponentTeamId !== '' && Number.isFinite(Number(opponentTeamId));
  const scope = scoped ? `&opponent_team_id=${Number(opponentTeamId)}` : '';
  try {
    return await apiFetch(`/league/${leagueId}/versus/board?week=${week}${scope}`);
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
