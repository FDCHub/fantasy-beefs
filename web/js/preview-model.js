/* ============================================================================
 * FantasyStakes — the served Matchup Preview
 * UIRECON Wave 4A
 *
 * WHAT THIS HOLDS. Everything the Matchup Preview explains from, exactly as
 * `/league/{id}/versus/preview` served it: both projected starting lineups, the
 * projections behind them, the board the pricing engine produced for the
 * pairing, and — since Rev 1.4 Lane C — the provider's own statement of what
 * each starter and each team HAS scored so far this week.
 *
 * WHAT IT DOES NOT DO — AND THE LIST IS THE POINT. It does not simulate. It
 * does not price. It does not sum a lineup, round a line, decide a sign, or
 * turn a probability into odds. Search this file for an arithmetic operator and
 * you will not find one: every number arrived over the wire and leaves
 * unchanged. `projected_total` and `projected_margin` are the SERVER's sums —
 * recomputing them here would give the surface a second opinion about its own
 * figures, and the two would agree until the day one of them was corrected.
 *
 * THREE MODES, as everywhere else in this build: demo (nothing bound), bound,
 * and unavailable. An unavailable preview is not an empty one — the difference
 * is "we could not ask" versus "there is nothing to explain", and the surface
 * says a different thing for each.
 * ========================================================================== */

export const PREVIEW_MODE_DEMO = 'demo';
export const PREVIEW_MODE_AUTHORITATIVE = 'authoritative';
export const PREVIEW_MODE_UNAVAILABLE = 'unavailable';

let MODE = PREVIEW_MODE_DEMO;

/** The served `MatchupPreviewOut`, verbatim. @type {object|null} */
let SERVED = null;

/**
 * Bind one served preview.
 *
 * @param {object} view a MatchupPreviewOut
 */
export function bindPreview(view) {
  SERVED = view && view.acting && view.opponent ? view : null;
  MODE = SERVED ? PREVIEW_MODE_AUTHORITATIVE : PREVIEW_MODE_UNAVAILABLE;
}

/** The read failed or was refused. */
export function markPreviewUnavailable() {
  SERVED = null;
  MODE = PREVIEW_MODE_UNAVAILABLE;
}

/** Return to the unbound default — sheet close, sign-out and the suites. */
export function unbindPreview() {
  SERVED = null;
  MODE = PREVIEW_MODE_DEMO;
}

/** @returns {'demo'|'authoritative'|'unavailable'} */
export function previewMode() {
  return MODE;
}

/** The served view, when bound. @returns {object|null} */
export function servedPreview() {
  return SERVED;
}

/**
 * One side's lineup rows, or an empty list.
 *
 * NULL IS NOT AN EMPTY LINEUP. A side the server did not describe returns `[]`
 * and the surface draws its unresolved state; a side with a genuinely empty
 * starting lineup also returns `[]` and the server's own refusal explains why.
 * Both are honest; neither invents a roster.
 *
 * @param {'acting'|'opponent'} side
 * @returns {Array<object>}
 */
export function lineupFor(side) {
  if (MODE !== PREVIEW_MODE_AUTHORITATIVE || !SERVED) return [];
  const view = SERVED[side];
  return view && Array.isArray(view.lineup) ? view.lineup : [];
}

/**
 * One side's identity and its two SERVER-COMPUTED totals.
 *
 * `liveTotal` IS NULL UNTIL A STARTER HAS BEEN MEASURED, and the null is
 * forwarded rather than coerced. Rev 1.4 §L2: a team whose starters have not
 * kicked off has not scored 0.0, and the difference between "no figure" and
 * "zero" has to survive every hop between the provider and the pixel.
 *
 * @param {'acting'|'opponent'} side
 * @returns {{teamId: number|null, teamName: string, projectedTotal: number|null,
 *            liveTotal: number|null, liveMeasuredCount: number|null,
 *            starterCount: number|null}}
 */
export function sideFor(side) {
  if (MODE !== PREVIEW_MODE_AUTHORITATIVE || !SERVED) {
    return {
      teamId: null, teamName: '', projectedTotal: null, liveTotal: null,
      liveMeasuredCount: null, starterCount: null,
    };
  }
  const view = SERVED[side] || {};
  return {
    teamId: typeof view.team_id === 'number' ? view.team_id : null,
    teamName: view.team_name || '',
    projectedTotal: typeof view.projected_total === 'number'
      ? view.projected_total : null,
    liveTotal: typeof view.live_total === 'number' ? view.live_total : null,
    liveMeasuredCount: typeof view.live_measured_count === 'number'
      ? view.live_measured_count : null,
    starterCount: typeof view.starter_count === 'number'
      ? view.starter_count : null,
  };
}

/**
 * Whether the provider ANSWERED about current scoring for this week.
 *
 * NOT "ARE THERE FIGURES". A healthy pre-kickoff read is available and carries
 * none, and the surface must be able to tell that apart from a provider it
 * could not reach — the two look identical on screen and mean entirely
 * different things. `previewLiveReason()` carries which.
 *
 * @returns {boolean}
 */
export function previewLiveAvailable() {
  if (MODE !== PREVIEW_MODE_AUTHORITATIVE || !SERVED) return false;
  return SERVED.live_available === true;
}

/**
 * The server's own reason code for an absent live figure, or null.
 *
 * One of `providers.live_scoring`'s governed codes. Reported, never authored
 * here: a sentence the surface invented for a state the server did not describe
 * is a claim about a provider nobody asked.
 *
 * @returns {string|null}
 */
export function previewLiveReason() {
  if (MODE !== PREVIEW_MODE_AUTHORITATIVE || !SERVED) return null;
  return typeof SERVED.live_reason === 'string' ? SERVED.live_reason : null;
}

/**
 * The board for this pairing, or null.
 *
 * A ROW THAT CAME BACK `available: false` IS STILL RETURNED — the caller needs
 * to tell an unpriceable matchup apart from one nobody asked about, and to show
 * the server's own sentence for it.
 *
 * @returns {object|null}
 */
export function previewMarket() {
  if (MODE !== PREVIEW_MODE_AUTHORITATIVE || !SERVED) return null;
  return SERVED.market || null;
}

/** Whether the board carries a priced market. @returns {boolean} */
export function previewPriced() {
  const market = previewMarket();
  return Boolean(market && market.available);
}

/** The server's projected margin — acting total minus opponent's. */
export function projectedMargin() {
  if (MODE !== PREVIEW_MODE_AUTHORITATIVE || !SERVED) return null;
  return typeof SERVED.projected_margin === 'number'
    ? SERVED.projected_margin : null;
}

/** The week the preview was built for. @returns {number|null} */
export function previewWeek() {
  if (MODE !== PREVIEW_MODE_AUTHORITATIVE || !SERVED) return null;
  return typeof SERVED.week === 'number' ? SERVED.week : null;
}
