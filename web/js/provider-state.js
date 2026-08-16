/* ============================================================================
 * FantasyStakes — where this league's data comes from
 * WP3D · Rev 4.3 §21, §22
 *
 * ONE PLACE DECIDES THE SIX WORDS. Rev 4.3 §22 fixes the player-facing provider
 * vocabulary at six labels and no others. Before this module the product had
 * none of them: the backend has served `provider_state` and `demo` on every
 * league context read since WP2, and nothing rendered either. A GM could not
 * tell a synthetic Demo league from a live Yahoo one.
 *
 * SIX LABELS, AND THEY ARE NOT INTERCHANGEABLE:
 *
 *   DEMO                    synthetic data, from the governed Demo provider
 *   YAHOO · CONNECTED       bound, and the binding has produced usable state
 *   YAHOO · SYNCING         bound, and a refresh is actively running
 *   YAHOO · NOT SYNCED YET  bound, but nothing has been published yet
 *   NOT CONNECTED           no provider binding at all
 *   LEAGUE UNAVAILABLE      the context could not be read
 *
 * `YAHOO · SYNCING` IS DEFINED AND CURRENTLY UNREACHABLE, by owner ruling and
 * on purpose. There is no backend fact that means "a refresh is running right
 * now": the only reconciliation signal in the system is an unresolved
 * `ProviderConflict`, and an unresolved conflict is a contradiction awaiting a
 * human — not proof that anything is in flight. Mapping one to the other would
 * make a product assertion out of a diagnostic guess. The label stays in the
 * vocabulary so the day an authoritative syncing fact exists it has somewhere
 * to land, and `SYNCING_REACHABLE` records that today it does not.
 *
 * THIS MODULE INVENTS NOTHING. Every branch below reads a served field. There
 * is no timer, no staleness heuristic, no inference from the league's name, and
 * no fallback that would let an unreadable context present as a connected one.
 *
 * ATTRIBUTION ELIGIBILITY LIVES HERE TOO, because it is the same question asked
 * once: is this surface showing Yahoo Fantasy Information? Two conditions must
 * both hold, and the split matters —
 *
 *   1. the CONTEXT is Yahoo-backed and has actually produced usable data; and
 *   2. the SURFACE is actually displaying some of it.
 *
 * This module answers (1). Each panel answers (2) for itself, because only the
 * panel knows what it drew. A binding on its own is not Yahoo Fantasy
 * Information — Rev 4.3 §23 and the executed agreement are about DISPLAYED
 * information, so `NOT SYNCED YET`, which has published no week, no matchup and
 * no provider-given team name, is not attributable.
 * ========================================================================== */

import {
  LEAGUE_MODE_AUTHORITATIVE, PROVIDER_ABSENT, PROVIDER_BOUND, PROVIDER_PENDING,
  leagueMode, providerState, servedContext,
} from './league-model.js';

/* ── The vocabulary. Exactly six, in the order Rev 4.3 §22 lists them. ───── */

export const SOURCE_DEMO = 'DEMO';
export const SOURCE_YAHOO_CONNECTED = 'YAHOO · CONNECTED';
export const SOURCE_YAHOO_SYNCING = 'YAHOO · SYNCING';
export const SOURCE_YAHOO_NOT_SYNCED = 'YAHOO · NOT SYNCED YET';
export const SOURCE_NOT_CONNECTED = 'NOT CONNECTED';
export const SOURCE_LEAGUE_UNAVAILABLE = 'LEAGUE UNAVAILABLE';

/** Every permitted player-facing label. Nothing outside this list may render. */
export const SOURCE_LABELS = Object.freeze([
  SOURCE_DEMO,
  SOURCE_YAHOO_CONNECTED,
  SOURCE_YAHOO_SYNCING,
  SOURCE_YAHOO_NOT_SYNCED,
  SOURCE_NOT_CONNECTED,
  SOURCE_LEAGUE_UNAVAILABLE,
]);

/**
 * Which labels today's backend contract can actually produce.
 *
 * STATED RATHER THAN IMPLIED. A reader comparing `SOURCE_LABELS` against this
 * set can see at a glance which label is aspirational and why, instead of
 * discovering by grep that one of the six never appears.
 */
export const SOURCE_REACHABLE = Object.freeze([
  SOURCE_DEMO,
  SOURCE_YAHOO_CONNECTED,
  SOURCE_YAHOO_NOT_SYNCED,
  SOURCE_NOT_CONNECTED,
  SOURCE_LEAGUE_UNAVAILABLE,
]);

/**
 * Whether an authoritative fact exists that could select `YAHOO · SYNCING`.
 *
 * FALSE, by owner ruling. Flip this the day the backend can say a refresh is
 * actively running — and not before.
 */
export const SYNCING_REACHABLE = false;

/** Where a surface's factual league data comes from. */
export const FAMILY_DEMO = 'demo';
export const FAMILY_YAHOO = 'yahoo';
export const FAMILY_NONE = 'none';

/**
 * The league's source state, as a GM should be told it.
 *
 * @returns {{label: string, family: string, available: boolean,
 *            attributable: boolean}}
 */
export function sourceState() {
  // UNREADABLE COMES FIRST, and nothing below can override it. A page that
  // could not read the context must never present as connected on the strength
  // of what it remembered — Rev 4.3 §23's rule, and the reason this branch is
  // the first one rather than a fallback at the bottom.
  if (leagueMode() !== LEAGUE_MODE_AUTHORITATIVE) {
    return frozen(SOURCE_LEAGUE_UNAVAILABLE, FAMILY_NONE, false, false);
  }

  const context = servedContext();
  if (!context) {
    return frozen(SOURCE_LEAGUE_UNAVAILABLE, FAMILY_NONE, false, false);
  }

  // DEMO IS DECIDED BY THE BINDING, never by the league's name. The served
  // flag is derived server-side from which provider answers for this league,
  // so the badge and the behaviour cannot disagree: a live Yahoo league called
  // "Demo League" is not marked, and a Demo league its owner renamed still is.
  if (context.demo === true) {
    return frozen(SOURCE_DEMO, FAMILY_DEMO, true, false);
  }

  const state = providerState();

  if (state === PROVIDER_ABSENT) {
    return frozen(SOURCE_NOT_CONNECTED, FAMILY_NONE, true, false);
  }

  if (state === PROVIDER_PENDING) {
    // BOUND BUT SILENT. The binding exists; nothing has been published through
    // it. Not attributable: there is no Yahoo Fantasy Information on screen to
    // attribute, and the league name in this state is the locally-chosen one
    // rather than the provider's.
    return frozen(SOURCE_YAHOO_NOT_SYNCED, FAMILY_YAHOO, true, false);
  }

  if (state === PROVIDER_BOUND) {
    return frozen(SOURCE_YAHOO_CONNECTED, FAMILY_YAHOO, true, true);
  }

  // A provider_state this build does not recognise. Reported as unavailable
  // rather than guessed at — an unknown state is not a connected one.
  return frozen(SOURCE_LEAGUE_UNAVAILABLE, FAMILY_NONE, false, false);
}

/** The label alone. @returns {string} */
export function sourceLabel() {
  return sourceState().label;
}

/**
 * Whether this session's league may carry the Yahoo attribution AT ALL.
 *
 * THE CONTEXT HALF OF THE QUESTION. A panel must also be displaying Yahoo
 * Fantasy Information; see the module header. Both halves are required, and
 * neither is sufficient.
 *
 * @returns {boolean}
 */
export function attributionEligible() {
  return sourceState().attributable === true;
}

function frozen(label, family, available, attributable) {
  return Object.freeze({ label, family, available, attributable });
}
