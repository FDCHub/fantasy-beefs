/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · matchup analysis
 * Sprint 7 Package 2
 *
 * Builds the Matchup Preview's two analysis sections from the matchup's own
 * numbers.
 *
 * GROUNDING RULE. Every sentence produced here is a statement about inputs we
 * actually hold: the lineup slots, the projections, the spread, the total and
 * the moneyline. There is no source in this repository for injuries, weather,
 * real-NFL news, snap counts, or beat reporting, so no sentence may imply one.
 * Generating the prose from the figures — rather than storing written prose —
 * is what makes that guarantee hold: a sentence about an injury cannot appear
 * because nothing here can produce one. `test_s7_p2_league_action.py` asserts
 * the forbidden vocabulary never reaches the rendered output.
 *
 * "Why The Line Looks This Way" is market analysis. "The Read" is fantasy
 * analysis. The POR keeps them separate, so the market section does not carry
 * roster storytelling and the fantasy section does not re-explain the line.
 * ========================================================================== */

import { formatOdds } from './wager-model.js';

/**
 * Implied win probability of American odds, as a percentage.
 *
 * Standard odds arithmetic on the quoted line — no vig model, no adjustment.
 *
 * @param {number} americanOdds
 * @returns {number} 0–100, one decimal
 */
export function impliedProbability(americanOdds) {
  if (!Number.isInteger(americanOdds) || americanOdds === 0) {
    throw new TypeError(`odds must be a non-zero whole number, got ${americanOdds}`);
  }
  const probability = americanOdds > 0
    ? 100 / (americanOdds + 100)
    : Math.abs(americanOdds) / (Math.abs(americanOdds) + 100);
  return Math.round(probability * 1000) / 10;
}

/**
 * The other side of the same quoted line.
 *
 * The mirror, not a repriced market: no hold is applied, because no source
 * gives one. Displayed as the opponent's side of the line the GM was quoted.
 *
 * @param {number} americanOdds
 * @returns {number}
 */
export function mirrorOdds(americanOdds) {
  return -americanOdds;
}

/**
 * @param {number} spread
 * @returns {string} e.g. `+4.5`, `−7.5`
 */
export function formatSpread(spread) {
  const magnitude = Math.abs(spread).toFixed(1);
  if (spread === 0) return 'PK';
  return spread > 0 ? `+${magnitude}` : `−${magnitude}`;
}

/**
 * Sportsbook view — the numbers, stated plainly.
 *
 * @param {object} m a matchup from league-data
 * @returns {{rows: Array<{label: string, value: string}>, favourite: string}}
 */
export function sportsbookView(m) {
  return {
    favourite: m.favourite,
    rows: [
      { label: 'Favourite', value: `${m.favourite} by ${Math.abs(m.spread).toFixed(1)}` },
      { label: `ML · ${m.you.name}`, value: formatOdds(m.ml) },
      { label: `ML · ${m.name}`, value: formatOdds(mirrorOdds(m.ml)) },
      { label: 'Spread · your side', value: formatSpread(m.spread) },
      { label: 'Total', value: m.total.toFixed(1) },
      { label: 'Projected score', value: `${m.yourProjection.toFixed(1)} — ${m.opponentProjection.toFixed(1)}` },
    ],
  };
}

/**
 * Why The Line Looks This Way — market analysis only.
 *
 * @param {object} m
 * @returns {string[]} paragraphs
 */
export function whyTheLine(m) {
  const gap = Math.abs(m.spread).toFixed(1);
  const youAreDog = m.spread > 0;
  const probability = impliedProbability(m.ml);

  return [
    `${m.favourite} is laying ${gap}. The projections are the whole of it: ` +
    `${m.name} projects ${m.opponentProjection.toFixed(1)} against your ` +
    `${m.yourProjection.toFixed(1)}, and the spread reproduces that ${gap}-point ` +
    'gap rather than adding a view of its own.',

    `The total of ${m.total.toFixed(1)} is those same two projections added. ` +
    'It moves when either lineup moves, which is the only thing that moves it.',

    `On the moneyline you are ${youAreDog ? 'getting' : 'laying'} ` +
    `${formatOdds(m.ml)} — priced to win ${probability}% of the time. ` +
    (youAreDog
      ? 'The market is paying you to be the shorter projection, so the edge, ' +
        'if there is one, is in the gap being smaller than it looks.'
      : 'You are paying for the longer projection, so the edge, if there is ' +
        'one, is in the gap holding all the way to kickoff.'),
  ];
}

/**
 * The Read — fantasy analysis from the lineup and projection inputs.
 *
 * @param {object} m
 * @returns {string[]} paragraphs
 */
export function theRead(m) {
  const ranked = [...m.yourLineup].sort((a, b) => b.projection - a.projection);
  const [first, second, third] = ranked;
  const topThree = first.projection + second.projection + third.projection;
  const share = Math.round((topThree / m.yourProjection) * 100);

  const theirRanked = [...m.opponentLineup].sort((a, b) => b.projection - a.projection);
  const theirTop = theirRanked[0];
  const gap = Math.abs(m.spread).toFixed(1);

  return [
    `Your ${m.yourProjection.toFixed(1)} is concentrated: ${first.player} at ` +
    `${first.projection.toFixed(1)}, ${second.player} at ${second.projection.toFixed(1)} ` +
    `and ${third.player} at ${third.projection.toFixed(1)} carry ${share}% of it. ` +
    'Concentration cuts both ways — it is where your ceiling comes from and ' +
    'where a quiet week hurts most.',

    `Their ${m.opponentProjection.toFixed(1)} leans hardest on the ${theirTop.slot} ` +
    `slot at ${theirTop.projection.toFixed(1)}. Opponent starters bind from Yahoo ` +
    'once the provider read is wired; the slot shape and projections are what ' +
    'the inputs give us today.',

    m.spread > 0
      ? `You need ${gap} points of the gap back. On these projections that is ` +
        'one starter beating their projection by that much, not a lineup-wide ' +
        'change of fortune.'
      : `You are giving ${gap}. On these projections you clear it only if your ` +
        'top slots hit — the margin is smaller than the record gap suggests.',
  ];
}