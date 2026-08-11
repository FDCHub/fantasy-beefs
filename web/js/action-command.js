/* ============================================================================
 * FantasyStakes — the Action wager commands
 * Sprint 8 Package 4C-2
 *
 * Four governed mutations, each one route deep:
 *
 *   issue    POST /beef/challenge   → economy/challenge_funding.issue_funded_challenge
 *   accept   POST /beef/respond     → funded accept, or the Dynamic Handshake
 *   decline  POST /beef/respond     → funded decline, exact reverse legs
 *   counter  POST /beef/counter     → funded counter, validation only
 *
 * NO OPTIMISTIC STATE, ANYWHERE. Every command returns the server's result and
 * nothing here writes a card, moves one between rails, or adjusts a figure. A
 * wager is real money: a card that slid into LIVE before the server agreed
 * would be telling a GM their money had moved when it may not have. The caller
 * re-reads the authoritative Action state and draws that.
 *
 * NO PRICING, EITHER. The composer sends a stake, a wager class and a mode. It
 * does not send odds, a Derived stake, a probability or a ceiling — those are
 * produced by the pricing model behind the route, and a client that computed
 * them would be a second pricing implementation whose disagreements would show
 * up as money.
 *
 * MODE IS EXPLICIT AND GOVERNED. `locked` and `dynamic` are the proposal
 * lifecycle's own values, not a display vocabulary invented here.
 * ========================================================================== */

import { ApiError, apiFetch } from './session.js';

/** The governed challenge modes — `beefs/proposal_lifecycle.VALID_MODES`. */
export const MODE_LOCKED = 'locked';
export const MODE_DYNAMIC = 'dynamic';
export const VALID_MODES = Object.freeze([MODE_LOCKED, MODE_DYNAMIC]);

/** A refusal the server explained. */
export class ActionCommandError extends Error {
  constructor(status, reasonCode, message) {
    super(message);
    this.name = 'ActionCommandError';
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

function refusal(error) {
  if (!(error instanceof ApiError)) return error;
  const detail = error.detail;
  const reason = detail && typeof detail === 'object' ? detail.reason_code : null;
  const message = detail && typeof detail === 'object'
    ? (detail.message || JSON.stringify(detail))
    : String(detail || error.message);
  return new ActionCommandError(error.status, reason, message);
}

/**
 * Issue a funded challenge.
 *
 * THE ACTING TEAM IS THE CALLER'S OWN, and the server proves it independently —
 * `assert_wagering_team_owner` refuses any other id regardless of what is sent.
 * It is passed because the route's contract takes it, not because this layer is
 * trusted for it.
 *
 * @param {object} spec
 * @param {number} spec.challengerTeamId the acting GM's own team
 * @param {number} spec.challengedTeamId the opponent
 * @param {number} spec.week
 * @param {string} spec.wagerType straight | spread | over_under
 * @param {number} spec.amountCents exact integer cents
 * @param {string} [spec.mode] locked | dynamic
 * @param {number} [spec.line]
 * @param {string} [spec.side]
 * @param {number} [spec.playerId]
 * @returns {Promise<object>} the FundedChallengeOut
 */
export async function issueChallenge(spec) {
  if (!VALID_MODES.includes(spec.mode || MODE_LOCKED)) {
    throw new ActionCommandError(400, 'unknown_challenge_mode',
      `Mode must be one of ${VALID_MODES.join(', ')}.`);
  }
  if (!Number.isInteger(spec.amountCents) || spec.amountCents <= 0) {
    // REFUSED BEFORE THE NETWORK, because a non-integer stake is a bug in this
    // layer rather than a decision the server should have to rule on. The
    // server enforces the same thing again; this only keeps the error legible.
    throw new ActionCommandError(400, 'invalid_stake',
      'Stake must be a positive whole number of cents.');
  }
  try {
    return await apiFetch('/beef/challenge', {
      method: 'POST',
      body: {
        challenger_team_id: spec.challengerTeamId,
        challenged_team_id: spec.challengedTeamId,
        week: spec.week,
        bet_type: spec.wagerType,
        // The route takes dollars; cents are the authority everywhere else, so
        // the conversion happens once, here, at the boundary that requires it.
        amount: spec.amountCents / 100,
        challenge_mode: spec.mode || MODE_LOCKED,
        line: spec.line ?? null,
        side: spec.side ?? null,
        player_id: spec.playerId ?? null,
      },
    });
  } catch (error) {
    throw refusal(error);
  }
}

/**
 * Accept a challenge.
 *
 * ONE ROUTE FOR BOTH MODES. The server dispatches on the challenge's own stored
 * mode — Locked acceptance to the funded accept, Dynamic to the governed
 * Handshake. The client does not choose, and could not: the mode is a property
 * of the challenge, not of the click.
 *
 * @param {number} challengeId
 * @returns {Promise<object>}
 */
export async function acceptChallenge(challengeId) {
  try {
    return await apiFetch('/beef/respond', {
      method: 'POST',
      body: { challenge_id: challengeId, accept: true },
    });
  } catch (error) {
    throw refusal(error);
  }
}

/**
 * Decline a challenge — the issuer's escrow is refunded by exact reverse legs.
 *
 * @param {number} challengeId
 * @returns {Promise<object>}
 */
export async function declineChallenge(challengeId) {
  try {
    return await apiFetch('/beef/respond', {
      method: 'POST',
      body: { challenge_id: challengeId, accept: false },
    });
  } catch (error) {
    throw refusal(error);
  }
}

/**
 * Counter a challenge with a new stake.
 *
 * A COUNTER MOVES NO MONEY. It freezes a new immutable proposal version and
 * hands the decision back to the original issuer; the escrow already posted
 * stays exactly where it is. Nothing here should suggest otherwise to a GM.
 *
 * @param {number} challengeId
 * @param {number} amountCents exact integer cents
 * @returns {Promise<object>}
 */
export async function counterChallenge(challengeId, amountCents) {
  if (!Number.isInteger(amountCents) || amountCents <= 0) {
    throw new ActionCommandError(400, 'invalid_stake',
      'Counter stake must be a positive whole number of cents.');
  }
  try {
    return await apiFetch('/beef/counter', {
      method: 'POST',
      body: { challenge_id: challengeId, countered_amount: amountCents / 100 },
    });
  } catch (error) {
    throw refusal(error);
  }
}

/**
 * Read the authoritative Action state.
 *
 * THE REFRESH EVERY COMMAND ENDS WITH. Separated from the commands so there is
 * exactly one way for the tab to learn what is true, whether it arrived there
 * by acting or by loading.
 *
 * @param {number} leagueId
 * @returns {Promise<object>} an ActionStateOut
 */
export async function readActionState(leagueId) {
  try {
    return await apiFetch(`/league/${leagueId}/action/me`);
  } catch (error) {
    throw refusal(error);
  }
}

/**
 * Turn a refusal into a sentence a GM can act on.
 *
 * The server's own message is preferred — it names real amounts and real teams.
 * These cover the cases where the status alone is the whole story.
 *
 * @param {Error} error
 * @returns {string}
 */
export function explainRefusal(error) {
  if (!(error instanceof ActionCommandError)) {
    return 'Something went wrong. Nothing was staked.';
  }
  if (error.reasonCode === 'cross_league_challenge') {
    return 'You can only wager against teams in your own league.';
  }
  if (error.status === 403) {
    return 'You can only act on your own team’s wagers.';
  }
  if (error.status === 409) {
    // Capacity and lifecycle-state refusals both land here, and the server's
    // message distinguishes them far better than a status code can.
    return error.message || 'That is no longer possible. Nothing was staked.';
  }
  if (error.status === 404) {
    return 'That wager no longer exists.';
  }
  return error.message || 'That was refused. Nothing was staked.';
}