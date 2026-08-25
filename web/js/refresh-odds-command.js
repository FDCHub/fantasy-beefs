/* ============================================================================
 * FantasyStakes — the Dynamic informational odds refresh
 * UIRECON Rev 1.4 · Simulation Engine Rev 9 §5
 *
 * TWO CALLS, AND THE DIFFERENCE BETWEEN THEM IS THE WHOLE FEATURE.
 *
 *   readOddsRefresh   GET  — what is the CURRENT shared line, and may this
 *                            card even offer the control?
 *   requestOddsRefresh POST — re-run the informational simulation and make the
 *                            result the new shared line.
 *
 * BOTH GMs READ THE SAME ROW. The GET does not compute anything on the reader's
 * behalf: it returns the refresh that actually happened, whoever asked for it.
 * That is why the opponent of the GM who pressed the button sees the same
 * numbers rather than numbers of their own — projections move, so two
 * independent computations of "the current line" would be two different lines,
 * both correct, for one wager.
 *
 * NOTHING HERE COMPUTES. Search this file for an arithmetic operator and you
 * will not find one. Every probability, moneyline and cent figure arrived over
 * the wire and leaves unchanged; the server anchored them on the wager's issuer
 * so that neither GM's copy of the app has to agree with the other's about an
 * orientation.
 *
 * A POST THAT MOVES NO MONEY. The route appends one informational row and posts
 * no ledger entry, touches no escrow and mutates no agreed term. It is a POST
 * because it WRITES that row — the shared line has to be written down somewhere
 * for two people to read one of it — and it travels through `session.js` with
 * the CSRF header like every other write, because that is what it is.
 * ========================================================================== */

import { ApiError, apiFetch } from './session.js';

/** A refusal the server explained, carrying its reason code. */
export class RefreshError extends Error {
  constructor(status, reasonCode, message) {
    super(message);
    this.name = 'RefreshError';
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

function asRefreshError(error) {
  if (error instanceof ApiError) {
    const detail = error.detail;
    const reason = detail && typeof detail === 'object'
      ? detail.reason_code : null;
    const message = detail && typeof detail === 'object'
      ? detail.message : String(detail || error.message);
    return new RefreshError(error.status, reason, message);
  }
  return error;
}

function path(leagueId, challengeId) {
  return `/league/${leagueId}/challenge/${challengeId}/odds/refresh`;
}

/**
 * The current shared refresh for one Matchup, and whether it may be refreshed.
 *
 * A NULL `refreshed_at` IS AN ANSWER, NOT A FAILURE. It means nobody has
 * refreshed this Matchup yet; the wager's agreed terms are untouched and are
 * read from the Action contract exactly as before.
 *
 * @param {number} leagueId
 * @param {number} challengeId
 * @returns {Promise<object>} a DynamicOddsRefreshOut
 */
export async function readOddsRefresh(leagueId, challengeId) {
  try {
    return await apiFetch(path(leagueId, challengeId));
  } catch (error) {
    throw asRefreshError(error);
  }
}

/**
 * Re-run the informational simulation and publish the result to both GMs.
 *
 * @param {number} leagueId
 * @param {number} challengeId
 * @returns {Promise<object>} a DynamicOddsRefreshOut
 */
export async function requestOddsRefresh(leagueId, challengeId) {
  try {
    return await apiFetch(path(leagueId, challengeId), { method: 'POST' });
  } catch (error) {
    throw asRefreshError(error);
  }
}

/**
 * Turn a refusal into a sentence, without ever implying the wager changed.
 *
 * EVERY SENTENCE HERE IS ABOUT THE DISPLAY. A refresh that cannot run leaves
 * the Matchup exactly as it was — same stake, same line, same odds of record,
 * same status — and copy that said "this wager could not be updated" would be
 * describing something that never happens.
 *
 * @param {RefreshError} error
 * @returns {string}
 */
export function explainRefreshRefusal(error) {
  const code = error && error.reasonCode;

  if (code === 'refresh_not_dynamic') {
    // The Locked answer is Refresh & Relock, which is a COUNTER and puts new
    // terms on the table. It is deliberately not offered from here.
    return 'Locked Matchups keep the odds they were offered at.';
  }
  if (code === 'refresh_after_final_lock') {
    return 'This Matchup has reached Final Lock. Its terms are set.';
  }
  if (code === 'refresh_not_handshaken') {
    return 'This Matchup is not live yet.';
  }
  if (code === 'roster_unavailable') {
    return 'One of these teams has no starting lineup for this week yet, so '
      + 'there is nothing new to read.';
  }
  if (code === 'refresh_model_integrity' || code === 'cannot_price') {
    return 'Fresh odds are not available right now. Your Matchup is unchanged.';
  }
  if (code === 'not_a_participant') {
    return 'This Matchup is between two other GMs.';
  }
  return (error && error.message)
    || 'Fresh odds are not available right now. Your Matchup is unchanged.';
}
