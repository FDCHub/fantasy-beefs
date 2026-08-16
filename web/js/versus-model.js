/* ============================================================================
 * FantasyStakes — Versus discovery
 * WP3C · Rev 4.3 §8 (Play), and WP3C §4, §6
 *
 * WHO CAN I PLAY THIS WEEK, AND MAY I?
 *
 * THE DEFECT THIS CLOSES IS THE BIGGEST ONE IN THE PACKAGE. Until now the Play
 * tab's Versus carousel came from `data/league-data.js` — eleven invented
 * opponents with invented records, invented ranks, invented projections and
 * invented moneylines, spreads and totals — and it rendered them to every
 * signed-in GM in production. A GM in a real league saw eleven teams that do
 * not exist, priced at lines nothing quoted, and could tap one to open a
 * composer. WP3C §4 calls that a Launch Ready blocker and it is.
 *
 * SO THE SUBJECTS ARE THE SERVER'S. `ActionStateOut.opponents` is the
 * authoritative target list — the same one the composer already sends against —
 * and it is the only source this module reads. There is no fallback: a session
 * that could not read it discovers nobody, and the surface says so.
 *
 * ELIGIBILITY IS READ, NEVER INFERRED (§6). Each opponent carries
 * `versus_eligible`, decided server-side by `beefs/postseason_versus` from the
 * championship track. This module reports it. It does NOT look at the week, the
 * phase, a seed, a record or a standings position — the four things §6 forbids
 * inferring from — and there is nothing here that could: the week is not even
 * imported.
 *
 * NO ODDS ARE INVENTED. Rev 4.2's card carried ML / SPR / O/U per opponent from
 * the fixture. Real quotes come from the pricing engine at composition time
 * against that specific pairing, and there is no read model that publishes a
 * board of them per opponent. So the discovery card names the OPPONENT and the
 * markets it will offer, and the quote appears in the composer where it is
 * actually priced. Drawing three unresolved cells would have been honest;
 * drawing three invented ones was not, and drawing none at all is clearer than
 * either.
 * ========================================================================== */

import { servedAction } from './action-model.js';

export const VERSUS_MODE_DEMO = 'demo';
export const VERSUS_MODE_AUTHORITATIVE = 'authoritative';
export const VERSUS_MODE_UNAVAILABLE = 'unavailable';

/** Presentation states for the discovery rail. */
export const VERSUS_STATE_READY = 'ready';
export const VERSUS_STATE_NO_DATA = 'no-data';
export const VERSUS_STATE_UNAVAILABLE = 'unavailable';
/** A postseason week whose championship field the provider cannot classify. */
export const VERSUS_STATE_FIELD_UNKNOWN = 'field-unknown';
/** A postseason week in which this GM's own team is off the track. */
export const VERSUS_STATE_NONE_ELIGIBLE = 'none-eligible';

let MODE = VERSUS_MODE_DEMO;

/**
 * Bind discovery to the authoritative Action read.
 *
 * NO SEPARATE FETCH. The opponents already arrive with Action, so a second read
 * would be a second answer to the same question, and the two could disagree
 * about who is in the league.
 */
export function bindVersus() {
  MODE = VERSUS_MODE_AUTHORITATIVE;
}

/** The read failed or was refused. */
export function markVersusUnavailable() {
  MODE = VERSUS_MODE_UNAVAILABLE;
}

/** Return to the unbound default — sign-out and the component suites. */
export function unbindVersus() {
  MODE = VERSUS_MODE_DEMO;
}

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function versusMode() {
  return MODE;
}

/**
 * Every opponent the server named, eligible or not.
 *
 * @returns {Array<{teamId: number, name: string, owner: string,
 *                  eligible: boolean}>}
 */
export function allOpponents() {
  if (MODE !== VERSUS_MODE_AUTHORITATIVE) return [];
  const served = servedAction();
  if (!served || !Array.isArray(served.opponents)) return [];
  return served.opponents.map((o) => Object.freeze({
    teamId: o.team_id,
    name: String(o.team_name || ''),
    owner: String(o.owner || ''),
    // ABSENT MEANS ELIGIBLE, matching the server's own default. A pre-WP3C
    // body carries no flag and described a regular season, where everyone is.
    eligible: o.versus_eligible !== false,
  }));
}

/**
 * The opponents a new wager may actually be offered against.
 *
 * @returns {Array<object>}
 */
export function playableOpponents() {
  return allOpponents().filter((o) => o.eligible);
}

/**
 * The Versus subject phase, as the server reported it.
 *
 * READ FROM THE ACTION CONTRACT, not from `phase.js`. The two agree in
 * practice, and they are still deliberately separate reads: this one is the
 * phase the ELIGIBILITY answer was computed under, so a surface explaining why
 * a field is restricted quotes the same read that restricted it.
 *
 * @returns {'regular'|'postseason'|null}
 */
export function versusPhase() {
  if (MODE !== VERSUS_MODE_AUTHORITATIVE) return null;
  const served = servedAction();
  return served && served.versus_phase ? served.versus_phase : null;
}

/**
 * Whether the eligible field could be determined at all.
 *
 * FALSE fails closed: no opponent is playable, and the surface says the field
 * is not yet known rather than listing the league.
 *
 * @returns {boolean}
 */
export function fieldDeterminable() {
  if (MODE !== VERSUS_MODE_AUTHORITATIVE) return true;
  const served = servedAction();
  return !served || served.versus_field_determinable !== false;
}

/**
 * What the discovery rail should draw.
 *
 * THE THREE EMPTY CASES ARE DIFFERENT SENTENCES and are kept apart because a GM
 * can act on the difference:
 *
 *   no-data         nobody was read — a league of one, or a read that returned
 *                   an empty roster
 *   field-unknown   it is the postseason and the bracket is not classified yet;
 *                   this resolves on its own once the provider reports
 *   none-eligible   the bracket IS known and this GM has nobody left to play;
 *                   their season's Versus is over, and Pools continue
 *
 * @returns {'ready'|'no-data'|'unavailable'|'field-unknown'|'none-eligible'}
 */
export function versusState() {
  if (MODE === VERSUS_MODE_UNAVAILABLE) return VERSUS_STATE_UNAVAILABLE;
  if (MODE === VERSUS_MODE_DEMO) return VERSUS_STATE_NO_DATA;
  if (allOpponents().length === 0) return VERSUS_STATE_NO_DATA;
  if (!fieldDeterminable()) return VERSUS_STATE_FIELD_UNKNOWN;
  if (playableOpponents().length === 0) return VERSUS_STATE_NONE_ELIGIBLE;
  return VERSUS_STATE_READY;
}

/**
 * The heading count — how many opponents are on offer.
 *
 * THE PLAYABLE COUNT, not the roster size. `11 OPPONENTS` above a rail holding
 * three championship-track teams would be counting something the GM cannot see.
 *
 * @returns {number}
 */
export function playableCount() {
  return playableOpponents().length;
}
