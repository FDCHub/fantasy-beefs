/* ============================================================================
 * FantasyStakes — the authoritative Versus quote
 * WP3C.1 · Rev 4.3 §28
 *
 * WHAT THIS REPLACES. The composer used to derive the opponent's stake in
 * JavaScript, from the American moneyline it happened to be displaying:
 *
 *     ratio = odds > 0 ? odds / 100 : 100 / |odds|
 *     opponentStake = round(yourStake * ratio)
 *
 * That is a second economic engine in the browser, which Rev 4.3 §28 forbids,
 * and it was a DIFFERENT engine from the server's: the backend prices from
 * simulated win probabilities and, in Dynamic, from `derive_stakes` — not from
 * a rounded integer moneyline. The two agreed on round numbers and diverged on
 * others. WP3C removed the derivation and left the figures unresolved rather
 * than keep it; WP3C.1 fills them from the server.
 *
 * NOTHING HERE COMPUTES. This module sends the GM's choices and holds the
 * answer. Search it for an arithmetic operator: the only one is the cents
 * conversion on the way out, which is a units boundary rather than economics.
 *
 * IT IS A READ, THROUGH A POST. The route mutates nothing — no challenge, no
 * proposal, no escrow, no ledger entry — and the suite proves that by counting
 * rows and balances around it. POST carries the inputs; it does not imply a
 * write. The CSRF header goes with it like every other POST, through
 * `session.js`, which stays the app's one door.
 * ========================================================================== */

import { ApiError, apiFetch } from './session.js';

/** A refusal the server explained, carrying its reason code. */
export class QuoteError extends Error {
  constructor(status, reasonCode, message) {
    super(message);
    this.name = 'QuoteError';
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

/**
 * Ask the server what this wager would cost.
 *
 * @param {number} leagueId
 * @param {object} spec
 * @param {number} spec.opponentTeamId  a served team id
 * @param {number} spec.week            the authoritative week
 * @param {string} spec.market          straight | spread | over_under
 * @param {number} spec.stakeCents      exact integer cents, unclamped
 * @param {string} spec.mode            locked | dynamic
 * @param {number|null} [spec.line]
 * @param {string|null} [spec.side]
 * @returns {Promise<object>} a VersusQuoteOut
 */
export async function requestQuote(leagueId, spec) {
  const body = {
    opponent_team_id: spec.opponentTeamId,
    week: spec.week,
    bet_type: spec.market,
    // CENTS OUT, DOLLARS IN. The route takes `amount` in dollars, exactly as
    // `/beef/challenge` does — so the quote and the write are given the stake
    // in the same units and cannot round it differently on the way in.
    amount: spec.stakeCents / 100,
    challenge_mode: spec.mode,
  };
  if (spec.line !== undefined && spec.line !== null) body.line = spec.line;
  if (spec.side !== undefined && spec.side !== null) body.side = spec.side;

  try {
    return await apiFetch(`/league/${leagueId}/versus/quote`, {
      method: 'POST',
      body,
    });
  } catch (error) {
    if (error instanceof ApiError) {
      const detail = error.detail;
      const reason = detail && typeof detail === 'object'
        ? detail.reason_code : null;
      const message = detail && typeof detail === 'object'
        ? detail.message : String(detail || error.message);
      throw new QuoteError(error.status, reason, message);
    }
    throw error;
  }
}

/**
 * Turn a refusal into a sentence a GM can act on.
 *
 * The server's own message is preferred where it is already product language —
 * WP3C.1 §6 requires the route to speak that way — and these cover the cases
 * where a shorter, more actionable line helps. No raw reason code reaches the
 * page.
 *
 * @param {QuoteError} error
 * @returns {string}
 */
export function explainQuoteRefusal(error) {
  const code = error.reasonCode;

  if (code === 'projections_unavailable') {
    return 'This week has not been projected yet, so there is nothing to price '
      + 'against.';
  }
  if (code === 'roster_unavailable') {
    return 'One of these teams has no starting lineup for this week yet.';
  }
  if (code === 'dynamic_not_priceable') {
    return 'This matchup is too one-sided for a Dynamic wager. Locked still '
      + 'works.';
  }
  if (code === 'postseason_field_unknown') {
    return 'The postseason field is not settled for this week yet.';
  }
  if (code === 'postseason_ineligible') {
    return 'Postseason Versus is limited to teams still on the championship '
      + 'track.';
  }
  if (code === 'stake_below_minimum') {
    return error.message || 'That stake is below the minimum.';
  }
  if (error.status === 403) {
    return 'Your session cannot price a wager in this league.';
  }
  return error.message || 'This wager could not be priced just now.';
}
