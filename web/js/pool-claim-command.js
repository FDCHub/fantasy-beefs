/* ============================================================================
 * FantasyStakes — the governed Pool claim command
 * WP6C
 *
 * THE ONE POOL PICK MUTATION IN THE PRODUCT. It goes to `POST /pool/pick`,
 * which since WP6C is an adapter into `betting/pool_claims.submit_claim` and
 * writes a `PoolClaim` — the row the Rev1.3 settlement engine actually resolves
 * winners from.
 *
 * WHAT IT REPLACED, AND WHY THAT MATTERED. The same path used to write a
 * `PoolBetPick` against one of three hardcoded legacy pot names. It answered
 * 200. The GM saw their selection. Settlement read `pool_claim`, found nothing,
 * and rolled every pot over for want of a winning ticket. A pick surface that
 * cannot produce a payable ticket is worse than no pick surface, because it
 * reports success.
 *
 * NOTHING IS DECIDED HERE. The occurrence, the subjects it admits and the
 * week's lock all come from the authoritative slate read; this module posts the
 * GM's choice among them and shows whatever the server answers. In particular
 * it does not pre-check the lock, the duplicate rule or subject validity —
 * `submit_claim` owns all three, and a second copy on this side would be a
 * second definition free to drift from the one that settles.
 * ========================================================================== */

import { ApiError, apiFetch } from './session.js';

/** A refusal the server explained, carrying its governed reason code. */
export class PoolClaimCommandError extends Error {
  constructor(status, reasonCode, message) {
    super(message);
    this.name = 'PoolClaimCommandError';
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

/**
 * Submit the acting GM's claim on one governed Pool occurrence.
 *
 * `leagueId` and `week` are sent as ASSERTIONS, not as authority: the server
 * checks them against the occurrence and refuses a mismatch, which is what
 * stops a stale tab from claiming an occurrence the GM never looked at.
 *
 * @param {{leagueId: number, teamId: number, week: number,
 *          poolInstanceId: number, subjectId: number}} claim
 * @returns {Promise<object>} the persisted claim plus a refreshed week view
 */
export async function submitPoolClaim(claim) {
  try {
    return await apiFetch('/pool/pick', {
      method: 'POST',
      body: {
        league_id: claim.leagueId,
        team_id: claim.teamId,
        week: claim.week,
        pool_instance_id: claim.poolInstanceId,
        subject_id: claim.subjectId,
      },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      const detail = error.detail;
      const reason = detail && typeof detail === 'object'
        ? detail.reason_code : null;
      const message = detail && typeof detail === 'object'
        ? detail.message : String(detail || error.message);
      throw new PoolClaimCommandError(error.status, reason, message);
    }
    throw error;
  }
}

/**
 * Turn a governed refusal into a sentence a GM can act on.
 *
 * The reason codes are the ENGINE's own — `betting/pool_claims.py` — so the
 * wording here does not depend on prose the backend may reword. Anything
 * unrecognised falls through to the server's own message rather than to a
 * generic sentence that would hide a refusal this surface has not met before.
 *
 * @param {PoolClaimCommandError} error
 * @returns {string}
 */
export function explainPoolClaimRefusal(error) {
  switch (error.reasonCode) {
    case 'WINDOW_CLOSED':
      return 'The pick window for this week has closed. All four Pools lock at '
        + 'the week’s first kickoff.';
    case 'INSTANCE_SETTLED':
      return 'This Pool has already settled, so it accepts no further picks.';
    case 'INVALID_SUBJECT':
      return 'That selection is not part of this week’s Pool. Reload the week '
        + 'and pick again.';
    case 'SELF_PICK_BLOCKED':
      return 'This Pool does not allow picking your own team.';
    case 'NOT_IN_LEAGUE':
      return 'Your team is not in the league this Pool belongs to.';
    case 'DUPLICATE_CLAIM':
      return 'You already hold a pick on this Pool.';
    case 'OCCURRENCE_MISMATCH':
      return 'This page is showing a different week than the Pool you picked. '
        + 'Reload and pick again.';
    case 'SCHEDULE_NOT_READY':
      return 'The week’s kickoff times have not been announced yet, so there is '
        + 'no pick window open.';
    case 'INSTANCE_NOT_FOUND':
      return 'That Pool no longer exists. Reload the week.';
    default:
      if (error.status === 403) {
        return 'Your session cannot submit a pick for that team.';
      }
      return error.message || 'The pick was refused.';
  }
}