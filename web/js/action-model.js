/* ============================================================================
 * FantasyStakes — Action read-model binding
 * Sprint 8 Package 4C-2
 *
 * THE SECTIONS ARE SERVED, NOT DECIDED HERE. Which rail a wager sits on is a
 * statement about the proposal protocol — whose decision it is, whether the
 * negotiation is open, whether the wager is live — and Sprint 7 derived it in
 * this layer from a `protocolState` and a `role` string. That was right for a
 * fixture and wrong for production: the rule would then exist in two languages,
 * and the JavaScript copy is the one nobody notices drifting.
 *
 * `reports/action_read_model.py` names the section now. This module binds what
 * it says and refuses to second-guess it. The one thing it will not do is
 * compute a section, a count, a price or a decision owner.
 *
 * THREE MODES, AND THE THIRD IS WHY THIS FILE EXISTS.
 *
 *   demo           the Rev 4.2 illustrative cards — component suites and
 *                  isolated review;
 *   authoritative  a real Action read is bound;
 *   unavailable    the read failed or was refused.
 *
 * A FAILED PRODUCTION READ MUST NEVER FALL BACK TO DEMO. Illustrative cards
 * name real-looking opponents and real-looking stakes; showing them to a
 * signed-in GM whose read just failed would be indistinguishable from showing
 * them their actual wagers. `unavailable` exists so the surface can say the
 * true thing instead.
 *
 * AN EMPTY PRODUCTION STATE IS NOT AN ERROR. A GM with no wagers has four empty
 * rails, and that is a fact about their week rather than a failure to load. The
 * two states are kept distinct for the same reason `undrawn` and `unavailable`
 * are distinct on the Pool slate.
 * ========================================================================== */

import {
  RAILS,
  cardsFor,
  lifecycleOf,
} from './data/action-data.js';

export const ACTION_MODE_DEMO = 'demo';
export const ACTION_MODE_AUTHORITATIVE = 'authoritative';
export const ACTION_MODE_UNAVAILABLE = 'unavailable';

/** The governed section keys, in Rev 4.2's rail order. */
export const SECTIONS = Object.freeze(['action', 'waiting', 'live', 'completed']);

/** The locked user-facing lifecycle vocabulary. Never extended client-side. */
export const LIFECYCLE_WORDS = Object.freeze([
  'Incoming', 'Accepted', 'Countered', 'Declined', 'Expired',
]);

let MODE = ACTION_MODE_DEMO;
let SERVED = null;

/**
 * Bind an authoritative Action read.
 *
 * @param {object} body an ActionStateOut from GET /league/{id}/action/me
 */
export function bindAction(body) {
  if (!body || typeof body !== 'object' || !body.sections || !body.counts) {
    // A malformed body is an UNAVAILABLE read, not a bound one. Binding it
    // would produce a surface that looks authoritative and reports nothing.
    markActionUnavailable();
    return;
  }
  SERVED = body;
  MODE = ACTION_MODE_AUTHORITATIVE;
}

/** The read failed or was refused. */
export function markActionUnavailable() {
  SERVED = null;
  MODE = ACTION_MODE_UNAVAILABLE;
}

/** Restore the illustrative source — component suites and sign-out. */
export function unbindAction() {
  SERVED = null;
  MODE = ACTION_MODE_DEMO;
}

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function actionMode() {
  return MODE;
}

/** The served body, when bound. @returns {object|null} */
export function servedAction() {
  return SERVED;
}

/**
 * The cards for one section.
 *
 * In `demo` this is the illustrative set, classified by the fixture's own
 * `lifecycleOf`. In `authoritative` it is exactly what the server placed there
 * — no re-sorting, no re-classification. In `unavailable` it is EMPTY, which is
 * what makes the surface draw its unresolved treatment rather than cards.
 *
 * @param {string} section
 * @returns {Array<object>}
 */
export function sectionCards(section) {
  if (!SECTIONS.includes(section)) throw new Error(`unknown section "${section}"`);
  if (MODE === ACTION_MODE_DEMO) return cardsFor(section);
  if (MODE !== ACTION_MODE_AUTHORITATIVE || !SERVED) return [];
  return (SERVED.sections[section] || []).map(normaliseCard);
}

/**
 * The count for one heading.
 *
 * FROM THE SERVER'S OWN COUNT in production, not from the length of what this
 * client happened to render. Those agree today; if they ever disagreed, the
 * server is right and the discrepancy is worth seeing rather than hiding.
 *
 * @param {string} section
 * @returns {number}
 */
export function sectionCount(section) {
  if (!SECTIONS.includes(section)) throw new Error(`unknown section "${section}"`);
  if (MODE === ACTION_MODE_DEMO) return cardsFor(section).length;
  if (MODE !== ACTION_MODE_AUTHORITATIVE || !SERVED) return 0;
  return SERVED.counts[section] || 0;
}

/**
 * Whether production has a genuinely empty Action tab.
 *
 * Distinct from `unavailable`: this is a real answer.
 * @returns {boolean}
 */
export function actionIsEmpty() {
  if (MODE !== ACTION_MODE_AUTHORITATIVE || !SERVED) return false;
  return SECTIONS.every((s) => (SERVED.counts[s] || 0) === 0);
}

/**
 * The GM's own Credits committed to wagers for one week.
 *
 * S8-P4C-3. This was unresolved through P4C-2 for one reason: it is week-scoped
 * and no authoritative current week existed. The provider states one and the
 * gateway now persists it, so the figure is derivable — and every OTHER input
 * was already served per card.
 *
 * A SUM OF SERVED FIELDS, NOT A NEW MEASUREMENT. `your_stake_cents` is the
 * GM's own side of a wager, taken from the frozen proposal; the week is the
 * challenge's own; and settled wagers are excluded because their money has
 * already resolved and is no longer committed.
 *
 * Null when no week is bound, which is what keeps the cell unresolved rather
 * than quietly totalling every week at once.
 *
 * @param {number|null} week
 * @returns {number|null}
 */
export function committedCentsForWeek(week) {
  if (MODE !== ACTION_MODE_AUTHORITATIVE || !SERVED) return null;
  if (week === null || week === undefined) return null;

  let total = 0;
  for (const section of SECTIONS) {
    for (const row of SERVED.sections[section] || []) {
      if (row.week !== week) continue;
      if (row.settled) continue;
      // OPEN AND LIVE ONLY. A declined or expired proposal committed nothing —
      // its escrow was reversed — and counting it would report money the GM
      // still has as money they have staked.
      if (!['offered', 'countered', 'accepted'].includes(row.protocol_state)) {
        continue;
      }
      total += Number.isInteger(row.your_stake_cents) ? row.your_stake_cents : 0;
    }
  }
  return total;
}

/**
 * One served card in the shape the renderer already speaks.
 *
 * A TRANSLATION, NOT A DERIVATION. Every field below is copied from the served
 * payload; the only computed values are display strings assembled from served
 * parts. Nothing here decides a section, an owner, a price or a status word.
 *
 * @param {object} row an ActionCardOut
 * @returns {object}
 */
function normaliseCard(row) {
  const stake = Number.isInteger(row.your_stake_cents) ? row.your_stake_cents : 0;
  const theirs = Number.isInteger(row.their_stake_cents) ? row.their_stake_cents : null;

  return Object.freeze({
    id: `challenge-${row.challenge_id}`,
    challengeId: row.challenge_id,
    // THE SERVED SECTION, carried onto the card. The renderer's accent follows
    // the rail, and re-deriving the rail from `protocolState` is exactly the
    // duplicated classification this model exists to remove — the fixture's
    // classifier knows only the four states a fixture can reach and throws on a
    // real `declined` or `expired`.
    section: row.section,
    opponent: row.opponent_name,
    opponentTeamId: row.opponent_team_id,
    role: row.direction === 'sent' ? 'issuer' : 'recipient',
    protocolState: row.protocol_state,
    status: row.status,
    mode: row.mode,
    week: row.week ? `WK ${row.week}` : '',

    // WHOSE MOVE, straight from the server. The renderer offers controls from
    // this and from nothing else.
    viewerDecides: Boolean(row.viewer_decides),
    controls: Object.freeze([...(row.controls || [])]),

    marketLabel: marketLabel(row),
    line: lineLabel(row),

    yourStakeCents: stake,
    opponentStakeCents: theirs,
    potCents: Number.isInteger(row.pot_cents) ? row.pot_cents : null,
    escrowCents: Number.isInteger(row.escrow_cents) ? row.escrow_cents : 0,

    // DYNAMIC ONLY. `null` on Locked — see the mode note in `action.js`.
    derivedCeilingCents: Number.isInteger(row.derived_ceiling_cents)
      ? row.derived_ceiling_cents : null,
    derivedRepriced: Boolean(row.derived_repriced),

    settled: Boolean(row.settled),
    netCents: Number.isInteger(row.net_cents) ? row.net_cents : null,
    won: row.settled && Number.isInteger(row.net_cents) ? row.net_cents >= 0 : false,

    expiresAt: row.expires_at || null,
    versionNumber: row.version_number || null,
  });
}

/** The wager class, in the product's words rather than the column's. */
function marketLabel(row) {
  if (row.wager_type === 'straight') return 'Moneyline';
  if (row.wager_type === 'spread') return 'Spread';
  if (row.wager_type === 'over_under') return 'Total';
  return row.wager_type || '';
}

/** The line/side, when the wager class has one. */
function lineLabel(row) {
  if (row.line === null || row.line === undefined) return '';
  const side = row.side ? `${row.side} ` : '';
  return `${side}${row.line}`;
}

/**
 * The illustrative classifier, re-exported so component suites keep working.
 *
 * Production never calls it — `sectionCards` short-circuits to the served
 * sections first. It is kept because the demo fixture is still the only source
 * for isolated rendering tests, and deleting it would take those with it.
 */
export { lifecycleOf, RAILS };
