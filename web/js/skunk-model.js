/* ============================================================================
 * FantasyStakes — the weekly Skunk read-model
 * WP6A
 *
 * The week's Skunk outcome, in the same three modes every other Sprint 8 model
 * uses: demo, authoritative, unavailable.
 *
 * THERE IS NO ILLUSTRATIVE SKUNK, AND THAT IS DELIBERATE. The other Week
 * modules fall back to the POR's fixture when nothing is bound, because a
 * prototype wager is useful for reviewing a layout. A Skunk result is not: it
 * names a real GM as the week's worst loss and states a real $10 obligation
 * against them. An invented one would put a fabricated humiliation and a
 * fabricated debt on screen under a real league's name. So DEMO here means no
 * callout at all.
 *
 * IT DECIDES NOTHING. Who was skunked, by how much, and for how much are the
 * server's answers — `GET /league/{id}/week/{week}/skunk`, which reads the
 * governed assessment event and the finalized matchup rows behind it. This
 * module holds that answer and reports whether there is one.
 *
 * `assessed: false` IS NOT `no skunk`. It means Week Close has not run for this
 * week yet. A surface that drew "no Skunk this week" for an unassessed week
 * would state a result nobody has measured, so the two are kept apart here and
 * only the assessed case draws anything.
 * ========================================================================== */

export const SKUNK_MODE_DEMO = 'demo';
export const SKUNK_MODE_AUTHORITATIVE = 'authoritative';
export const SKUNK_MODE_UNAVAILABLE = 'unavailable';

/** The server's own classifications. */
export const SKUNK_ASSESSED = 'ASSESSED';
export const SKUNK_NO_LOSER = 'NO_LOSER';

let MODE = SKUNK_MODE_DEMO;
let SERVED = null;

/**
 * Bind the authoritative weekly Skunk read.
 *
 * @param {object} body a WeeklySkunkOut
 */
export function bindSkunk(body) {
  SERVED = body;
  MODE = SKUNK_MODE_AUTHORITATIVE;
}

/** The read failed or was refused. No callout is drawn. */
export function markSkunkUnavailable() {
  SERVED = null;
  MODE = SKUNK_MODE_UNAVAILABLE;
}

/** Return to the unbound default. Used on sign-out and by the suites. */
export function unbindSkunk() {
  SERVED = null;
  MODE = SKUNK_MODE_DEMO;
}

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function skunkMode() {
  return MODE;
}

/** The served body, when bound. @returns {object|null} */
export function servedSkunk() {
  return SERVED;
}

/**
 * The week this result describes, or null.
 *
 * The Week tab lets a GM switch weeks, and a result bound for week 5 must not
 * be drawn under week 4's heading. The view compares this against the week it
 * is rendering rather than assuming the two agree.
 *
 * @returns {number|null}
 */
export function skunkWeek() {
  if (MODE !== SKUNK_MODE_AUTHORITATIVE || !SERVED) return null;
  return typeof SERVED.week === 'number' ? SERVED.week : null;
}

/**
 * The week's Skunk, when there is one to draw.
 *
 * Returns null for every state that is NOT "a GM was skunked and we know who":
 * unbound, unavailable, not yet assessed, and the genuine NO_LOSER outcome
 * where every matchup tied. Only the first of those is an error; the view draws
 * nothing in all of them, because none of them has a result to announce.
 *
 * @returns {{teamName: string, score: number, opponentName: string,
 *            opponentScore: number, margin: number, cents: number,
 *            week: number}|null}
 */
export function skunkOfTheWeek() {
  if (MODE !== SKUNK_MODE_AUTHORITATIVE || !SERVED) return null;
  if (SERVED.assessed !== true) return null;
  if (SERVED.classification !== SKUNK_ASSESSED) return null;

  const entries = Array.isArray(SERVED.entries) ? SERVED.entries : [];
  if (entries.length === 0) return null;

  // ONE OUTCOME PER WEEK is the product model, and the engine produces one
  // except on an exact-margin tie — which fractional scoring makes vanishingly
  // rare and which the engine handles by SPLITTING the single $10 rather than
  // charging twice. The first canonical entry leads; `tied` lets the view say
  // so honestly instead of silently presenting one of several as the only one.
  const first = entries[0];
  return {
    teamName: String(first.team_name || ''),
    score: Number(first.score),
    opponentName: String(first.opponent_team_name || ''),
    opponentScore: Number(first.opponent_score),
    margin: Number(first.margin),
    cents: Number(first.cents),
    week: SERVED.week,
    tied: entries.length > 1,
    tiedCount: entries.length,
  };
}