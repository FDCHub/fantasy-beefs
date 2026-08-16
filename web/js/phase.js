/* ============================================================================
 * FantasyStakes — the season phase, in one place
 * WP3C · Rev 4.3 §17, §22, §27
 *
 * FOUR SURFACES SAY WHAT PART OF THE SEASON IT IS — Play, Status, Wrap Up and
 * Account — and before WP3C each of them said it by writing the words
 * `Regular Season` into a template literal. A league in its championship week
 * read "Regular Season" on all four.
 *
 * So the phase is READ, not written, and it is read here. The value is decided
 * by `reports/league_read_model._season_phase`, which reads the league's own
 * `playoff_start_week`, its own `season_final_week` and its own
 * `season_closed_at`. This module holds that answer and turns it into a label.
 *
 * IT DECIDES NOTHING, AND ONE NON-DECISION IS LOAD-BEARING: THIS IS NOT
 * ELIGIBILITY. Rev 4.3 §27 keeps the two apart, and they are genuinely
 * different questions. "It is the postseason" is a fact about the calendar.
 * "You may challenge this team" is a fact about the championship track, decided
 * by `beefs/postseason_versus` and served as `versus_eligible`. A surface that
 * read `phase === 'postseason'` and drew its own conclusions about who may be
 * wagered against would be inferring eligibility from a week number, which is
 * exactly what WP3C forbids. Nothing here exposes a way to do that.
 *
 * NULL IS AN ANSWER. A league whose provider has never stated a week has no
 * phase, and every caller renders that as unresolved rather than assuming the
 * season is under way.
 * ========================================================================== */

import { servedContext } from './league-model.js';

/** The wire values `LeagueContextOut.phase` may carry. */
export const PHASE_REGULAR = 'regular';
export const PHASE_POSTSEASON = 'postseason';
export const PHASE_CHAMPIONSHIP = 'championship';
export const PHASE_COMPLETE = 'complete';

/**
 * The user-facing wording for each phase, as Rev 4.3 §17 and §27 name them.
 *
 * Title case, because these appear inside a context line beside a week number
 * rather than as a heading — `Week 15 · Championship`.
 */
const LABELS = Object.freeze({
  [PHASE_REGULAR]: 'Regular Season',
  [PHASE_POSTSEASON]: 'Postseason',
  [PHASE_CHAMPIONSHIP]: 'Championship',
  [PHASE_COMPLETE]: 'Season Complete',
});

/**
 * The authoritative phase for the bound league, or null.
 *
 * @returns {'regular'|'postseason'|'championship'|'complete'|null}
 */
export function seasonPhase() {
  const context = servedContext();
  if (!context) return null;
  const phase = context.phase;
  return Object.prototype.hasOwnProperty.call(LABELS, phase) ? phase : null;
}

/**
 * The phase as a user reads it, or null when there is no phase to state.
 *
 * @returns {string|null}
 */
export function seasonPhaseLabel() {
  const phase = seasonPhase();
  return phase === null ? null : LABELS[phase];
}

/**
 * `Week 5 · Regular Season`, degrading honestly.
 *
 * FOUR OUTCOMES, AND EACH SAYS SOMETHING DIFFERENT:
 *
 *   both known    `Week 15 · Championship`
 *   phase only    `Season Complete` — a closed season has no current week to
 *                 name, and pairing one with it would be describing a week
 *                 that is over as though it were in progress
 *   week only     `Week 9` — the provider stated a week but the boundaries
 *                 needed to classify it are not on the league row
 *   neither       null, and the caller draws its own unresolved treatment
 *
 * @param {number|null} week the authoritative current week
 * @returns {string|null}
 */
export function weekPhaseLabel(week) {
  const label = seasonPhaseLabel();
  const hasWeek = typeof week === 'number';

  if (seasonPhase() === PHASE_COMPLETE) return label;
  if (hasWeek && label) return `Week ${week} · ${label}`;
  if (hasWeek) return `Week ${week}`;
  return label;
}

/**
 * The same pairing in the upper-case grammar Status uses for its page heading.
 *
 * Rev 4.3 §13 keeps `ACTION` as content terminology on that heading even though
 * the tab is named Status, and the week and phase in front of it are the
 * authoritative ones.
 *
 * @param {number|null} week
 * @param {string} suffix e.g. `ACTION`
 * @returns {string}
 */
export function headingWithPhase(week, suffix) {
  const label = weekPhaseLabel(week);
  // NO SEPARATOR BEFORE THE SUFFIX. The locked Rev 4.2 grammar is
  // `WEEK 5 · REGULAR SEASON ACTION` — the middot separates the week from the
  // phase, and `ACTION` reads as part of the phrase rather than a third item.
  return label ? `${label.toUpperCase()} ${suffix}` : suffix;
}

/**
 * Whether the season has been closed.
 *
 * Offered so a surface can draw a season-complete state rather than an empty
 * in-progress one. It is NOT a wagering gate: what may be entered is the
 * server's to refuse, and it refuses on its own lifecycle rather than on this.
 *
 * @returns {boolean}
 */
export function seasonComplete() {
  return seasonPhase() === PHASE_COMPLETE;
}
