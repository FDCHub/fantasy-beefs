/* ============================================================================
 * FantasyStakes — the governed championship mutations
 *
 * Five commissioner-only writes and one correction, each going to the certified
 * RC2 route that owns it. This module sends and reports; it decides nothing.
 *
 * NOTHING IS VALIDATED AWAY HERE. An amount outside the governed range, a
 * freeze before the boundary, a settle while an eligible contest is unresolved,
 * a correction after payout — every one of those is SENT and the server's
 * refusal is surfaced with its reason code. Refusing client-side would report a
 * decision the server never made, and would hide a regression in the guard that
 * is supposed to own it.
 *
 * THE CORRECTION CARRIES NO AMOUNT. `submitCorrection` accepts a contest and a
 * corrected RESULT. There is no cents parameter and no score parameter in this
 * module's surface, so no caller can supply one.
 * ========================================================================== */

import { ApiError, apiFetch } from './session.js';

/** A refusal the server explained, carrying its stable reason code. */
export class ChampionshipCommandError extends Error {
  constructor(status, reasonCode, message) {
    super(message);
    this.name = 'ChampionshipCommandError';
    this.status = status;
    this.reasonCode = reasonCode;
  }
}

/**
 * The reason code out of a refusal body.
 *
 * The championship routes answer 409 with `detail` as the full error string the
 * engine raised, which begins with its bracketed reason code —
 * `[FS_CHAMPIONSHIP_NOT_ACTIVATED] league 3 season ...`. Both halves are kept:
 * the code for the operator, the sentence for the human.
 */
export function explainRefusal(error) {
  if (!(error instanceof ChampionshipCommandError)) {
    return { code: '', message: error && error.message ? error.message : 'Failed.' };
  }
  return { code: error.reasonCode || '', message: error.message };
}

function refusalFrom(error) {
  const detail = (error && error.payload && error.payload.detail) || '';
  const text = typeof detail === 'string' ? detail : JSON.stringify(detail);
  const match = /^\[([A-Z0-9_]+)\]\s*(.*)$/s.exec(text || '');
  return new ChampionshipCommandError(
    error && error.status ? error.status : 0,
    match ? match[1] : '',
    match ? match[2] : (text || 'The server refused the request.'));
}

async function send(path, init) {
  try {
    return await apiFetch(path, init);
  } catch (error) {
    if (error instanceof ApiError) throw refusalFrom(error);
    throw error;
  }
}

/* ── Reads ──────────────────────────────────────────────────────────────── */

export function readConfig(leagueId) {
  return send(`/league/${leagueId}/championship/config`);
}

export function readResults(leagueId) {
  return send(`/league/${leagueId}/championship/results`);
}

export function readCorrections(leagueId) {
  return send(`/league/${leagueId}/championship/corrections`);
}

/* ── Writes ─────────────────────────────────────────────────────────────── */

/** Set the FantasyStakes Championship contribution. Sent unclamped. */
export function updateContribution(leagueId, cents) {
  return send(`/league/${leagueId}/championship/config`, {
    method: 'PUT',
    body: JSON.stringify({ contribution_cents: cents }),
  });
}

export function activateChampionship(leagueId) {
  return send(`/league/${leagueId}/championship/activate`, { method: 'POST' });
}

export function freezeChampionship(leagueId) {
  return send(`/league/${leagueId}/championship/freeze`, { method: 'POST' });
}

export function settleChampionship(leagueId) {
  return send(`/league/${leagueId}/championship/settle`, { method: 'POST' });
}

/**
 * A stable idempotence key for one correction attempt.
 *
 * WHY IT IS DERIVED FROM THE CORRECTION, NOT FROM THE CLOCK. The server treats
 * a repeated key as a replay and performs no second economics, so the key has
 * to be stable across a retry of the SAME correction and distinct for a
 * different one. Contest identity plus the corrected result gives exactly that:
 * pressing submit twice on one confirmed correction replays; correcting the
 * same contest again to a different result is a new key and a new revision.
 *
 * `attempt` exists for the deliberate case where a commissioner needs to restate
 * the same contest to the same result a second time; it is not incremented
 * automatically, because that would turn an accidental double-submit into two
 * revisions.
 */
export function correctionKey(draft, attempt = 1) {
  const parts = [
    'fs-corr',
    draft.competition_type,
    String(draft.contest_ref),
    draft.competition_type === 'versus'
      ? (draft.outcome === 'push' ? 'push' : `w${draft.winner_team_id}`)
      : `w${(draft.winner_team_ids || []).slice().sort((a, b) => a - b).join('-')}`,
    `a${attempt}`,
  ];
  return parts.join(':');
}

/**
 * File an authoritative correction.
 *
 * `body` must already be the certified request shape — build it with
 * `championship-admin.correctionRequest`, which has no field for an amount.
 */
export function submitCorrection(leagueId, body) {
  return send(`/league/${leagueId}/championship/corrections`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
