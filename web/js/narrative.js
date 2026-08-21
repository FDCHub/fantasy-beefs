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
 *
 * TWO PERSPECTIVES, ONE SET OF SENTENCES. Package 3 shows the league's official
 * Yahoo matchups, most of which the viewer is not playing in. Rather than fork
 * the prose, every sentence is built through `voice()`: the subject side is
 * addressed as "you" when the viewer is in the matchup and by name when they
 * are not. The analysis is the same analysis either way.
 *
 * AN UNQUOTED MONEYLINE IS DRAWN AS UNQUOTED. A spread and a total are
 * arithmetic on projections we hold. A moneyline is not: it comes from the
 * simulation engine (`odds/monte_carlo.py`, converted by `p2o` in
 * `odds/dynamic_pricing.py`), and no seam exposes it to the web app. The POR
 * carries moneylines for the viewer's own board and for nothing else, so a
 * matchup without one says so instead of deriving a number from the spread.
 * ========================================================================== */

import { PENDING_FIGURE } from './components.js';
import { formatOdds } from './wager-model.js';

/**
 * How to address the two sides of a matchup.
 *
 * `m.viewerIsSubject` defaults to true, so a League matchup — where the subject
 * side IS the viewer — keeps the second-person voice it has always had.
 *
 * @param {object} m
 * @returns {object}
 */
function voice(m) {
  const isViewer = m.viewerIsSubject !== false;
  const name = m.you.name;
  return {
    isViewer,
    subject: isViewer ? 'you' : name,
    Subject: isViewer ? 'You' : name,
    possessive: isViewer ? 'your' : `${name}’s`,
    Possessive: isViewer ? 'Your' : `${name}’s`,
    are: isViewer ? 'are' : 'is',
    need: isViewer ? 'need' : 'needs',
    clear: isViewer ? 'clear' : 'clears',
  };
}

/**
 * How to refer to a lineup row.
 *
 * A row binds a player name only where a source supports one. Where it does
 * not, the slot is the honest reference — never a name chosen to fill the
 * sentence.
 *
 * @param {{slot: string, player: ?string, projection: number}} row
 * @returns {string}
 */
function lineupRef(row) {
  return row.player
    ? `${row.player} at ${row.projection.toFixed(1)}`
    : `the ${row.slot} slot at ${row.projection.toFixed(1)}`;
}

/**
 * Whether this matchup carries a quoted moneyline.
 *
 * @param {object} m
 * @returns {boolean}
 */
export function hasQuotedMoneyline(m) {
  return Number.isInteger(m.ml) && m.ml !== 0;
}

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
  const quoted = hasQuotedMoneyline(m);
  const v = voice(m);

  // A finished matchup is reported as a RESULT. Drawing a realised margin under
  // a `Spread` label, or this week's board price on a matchup that closed days
  // ago, would dress results up as a market.
  if (m.settled) {
    return {
      favourite: m.favourite,
      quoted: false,
      settled: true,
      rows: [
        { label: 'Result', value: `${m.winner} by ${Math.abs(m.spread).toFixed(1)}` },
        { label: `Final · ${m.you.name}`, value: m.yourProjection.toFixed(1) },
        { label: `Final · ${m.name}`, value: m.opponentProjection.toFixed(1) },
        { label: 'Combined', value: m.total.toFixed(1) },
        { label: 'Closing line', value: PENDING_FIGURE },
      ],
    };
  }

  return {
    favourite: m.favourite,
    quoted,
    settled: false,
    rows: [
      { label: 'Favourite', value: `${m.favourite} by ${Math.abs(m.spread).toFixed(1)}` },
      { label: `ML · ${m.you.name}`, value: quoted ? formatOdds(m.ml) : PENDING_FIGURE },
      { label: `ML · ${m.name}`, value: quoted ? formatOdds(mirrorOdds(m.ml)) : PENDING_FIGURE },
      { label: `Spread · ${v.isViewer ? 'your side' : m.you.name}`, value: formatSpread(m.spread) },
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
  // WP3C — NO LINE, NOTHING TO EXPLAIN. Rev 4.2's opponents all carried a
  // fixture spread, so this function could assume one. Play now discovers real
  // opponents (§4) and a pairing has no line until the pricing engine prices
  // the market the GM chooses. Explaining a line that does not exist would mean
  // inventing one, so the absence is stated instead.
  if (typeof m.spread !== 'number') {
    return [
      'This matchup has not been priced yet. A line is produced when you pick a '
      + 'market, against both teams’ projected lineups for the week.',
      'Until then there is nothing here to explain — a number shown now would '
      + 'be one nobody quoted.',
    ];
  }

  const gap = Math.abs(m.spread).toFixed(1);
  const subjectIsDog = m.spread > 0;
  const v = voice(m);

  // Nothing to explain about a line this build does not hold. The result is
  // reported instead, and the absence is stated rather than filled.
  if (m.settled) {
    return [
      `${m.winner} won it by ${gap} — ${m.yourProjection.toFixed(1)} to ` +
      `${m.opponentProjection.toFixed(1)}, ${m.total.toFixed(1)} between them.`,

      'The line this matchup closed at is not retained in this build, so there ' +
      'is no price here to check that result against. What we hold is the ' +
      'scoreline, and it is shown as itself.',
    ];
  }

  const moneylineParagraph = hasQuotedMoneyline(m)
    ? `On the moneyline ${v.subject} ${v.are} ${subjectIsDog ? 'getting' : 'laying'} ` +
      `${formatOdds(m.ml)} — priced to win ${impliedProbability(m.ml)}% of the time. ` +
      (subjectIsDog
        ? `The market is paying ${v.subject} to be the shorter projection, so the ` +
          'edge, if there is one, is in the gap being smaller than it looks.'
        : `${v.Subject} ${v.are} paying for the longer projection, so the edge, if ` +
          'there is one, is in the gap holding all the way to kickoff.')
    // Deriving a price from the spread would be inventing a pricing model. The
    // spread and total above need no quote; the moneyline does.
    : 'No moneyline is quoted on this matchup. The spread and the total above ' +
      'are arithmetic on the projections and stand on their own; a price is a ' +
      'separate thing, and it binds when the pricing engine is wired through.';

  return [
    `${m.favourite} is laying ${gap}. The projections are the whole of it: ` +
    `${m.name} projects ${m.opponentProjection.toFixed(1)} against ${v.possessive} ` +
    `${m.yourProjection.toFixed(1)}, and the spread reproduces that ${gap}-point ` +
    'gap rather than adding a view of its own.',

    `The total of ${m.total.toFixed(1)} is those same two projections added. ` +
    'It moves when either lineup moves, which is the only thing that moves it.',

    moneylineParagraph,
  ];
}

/**
 * The Read — fantasy analysis from the lineup and projection inputs.
 *
 * @param {object} m
 * @returns {string[]} paragraphs
 */
export function theRead(m) {
  const v = voice(m);

  // WP3C — the same absence as `whyTheLine`, and for the same reason. The Read
  // ranks a lineup against a line; with neither bound there is no read to give,
  // and saying so beats ranking nothing.
  if (typeof m.spread !== 'number') {
    return [
      'Starting lineups and projections for this matchup bind from the '
      + 'provider. Once they do, the read is what those lineups say about the '
      + 'price.',
    ];
  }

  const gap = Math.abs(m.spread).toFixed(1);

  // A settled matchup has no per-slot figures to read — see `lineupFor` in
  // week-data. Ranking a lineup whose rows are unresolved would be ranking
  // nothing, so The Read works from the two totals it actually has.
  if (m.settled) {
    const close = Math.abs(m.spread) < 10;
    return [
      `${v.Possessive} ${m.yourProjection.toFixed(1)} against ` +
      `${m.name}’s ${m.opponentProjection.toFixed(1)} was ` +
      `${close ? 'a one-swing game' : 'a comfortable margin'} at ${gap} points.`,

      'Which slots produced that total is not retained for a past week. It ' +
      'binds from Yahoo once the provider read is wired; naming the players ' +
      'who did it would be inventing a box score.',
    ];
  }

  const ranked = [...m.yourLineup].sort((a, b) => b.projection - a.projection);
  const [first, second, third] = ranked;
  const topThree = first.projection + second.projection + third.projection;
  const share = Math.round((topThree / m.yourProjection) * 100);

  const theirRanked = [...m.opponentLineup].sort((a, b) => b.projection - a.projection);
  const theirTop = theirRanked[0];

  return [
    `${v.Possessive} ${m.yourProjection.toFixed(1)} is concentrated: ` +
    `${lineupRef(first)}, ${lineupRef(second)} and ${lineupRef(third)} carry ` +
    `${share}% of it. Concentration cuts both ways — it is where ${v.possessive} ` +
    'ceiling comes from and where a quiet week hurts most.',

    `${m.name} projects ${m.opponentProjection.toFixed(1)}, leaning hardest on the ` +
    `${theirTop.slot} slot at ${theirTop.projection.toFixed(1)}. Starters bind from ` +
    'Yahoo once the provider read is wired; the slot shape and projections are ' +
    'what the inputs give us today.',

    m.spread > 0
      ? `${v.Subject} ${v.need} ${gap} points of the gap back. On these projections ` +
        'that is one starter beating their projection by that much, not a ' +
        'lineup-wide change of fortune.'
      : `${v.Subject} ${v.are} giving ${gap}. On these projections ${v.subject} ` +
        `${v.clear} it only if ${v.possessive} top slots hit — the margin is ` +
        'smaller than the record gap suggests.',
  ];
}
/* ══ THE SERVED PREVIEW'S OWN NARRATIVE — UIRECON Wave 4A ══════════════════
 *
 * WHY THERE ARE TWO NARRATIVE PATHS IN THIS FILE, AND WHY THAT IS RIGHT.
 *
 * `whyTheLine` and `theRead` above answer for a preview that has NOTHING bound
 * — no lineups, no board — which before Wave 4A was every preview in the
 * product. They are unchanged, still certified, and still what an unbound
 * surface says: that nothing is priced and nothing may be named.
 *
 * The two below answer for a preview the server actually described. They are a
 * different job, not a variant of the same one: one explains an absence, the
 * other explains a matchup.
 *
 * THE GROUNDING RULE FROM THE TOP OF THIS FILE STILL BINDS, and binds harder.
 * Every sentence produced here is a statement about a field the read model
 * served: a projected lineup total, a projected margin, a simulated win
 * probability, a spread, a total, a moneyline. There is no source in this
 * repository for real-world player availability, conditions or roster
 * movement, so no sentence may imply one — and generating the prose from the
 * figures is what makes that guarantee hold rather than merely assert it.
 *
 * NOTHING HERE COMPUTES A PRICE. The probability, the spread, the total and the
 * moneyline are the simulation's, read verbatim. The only arithmetic is
 * `Math.abs` on a served margin and a percentage rendered from a served
 * probability — presentation of numbers the server produced.
 */

/** A served figure, or null. Keeps every sentence below free of type checks. */
function servedNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** A served probability as a percentage, one decimal. */
function servedPercent(probability) {
  const p = servedNumber(probability);
  return p === null ? null : Math.round(p * 1000) / 10;
}

/**
 * WHY THE LINE LOOKS THIS WAY, from the served preview.
 *
 * METHOD FIRST, THEN THIS MATCHUP'S NUMBERS. The first paragraph is the same
 * every time because the method is the same every time — it is what the product
 * claims and what a GM is owed before they are shown a price. The paragraphs
 * after it are this pairing's, and each is dropped rather than softened when
 * the field behind it was not served.
 *
 * @param {object} view a served MatchupPreviewOut
 * @param {{marketId?: string}} [opts] the market the GM entered from
 * @returns {string[]} paragraphs
 */
export function whyTheLineFromPreview(view, opts = {}) {
  const market = (view && view.market) || {};
  const acting = (view && view.acting) || {};
  const opponent = (view && view.opponent) || {};

  const method =
    'FantasyStakes projects both starting lineups using your league’s scoring '
    + 'settings and each player’s current projection, then simulates the '
    + 'matchup many times over. The spread is the simulation’s expected margin, '
    + 'the total is its expected combined score, and the moneyline is how often '
    + 'each side comes out ahead across those runs.';

  if (!market.available) {
    return [
      method,
      market.unavailable_reason
        || 'This matchup has no market on offer right now.',
    ];
  }

  const paragraphs = [method];

  const winPct = servedPercent(market.acting_win_probability);
  const spread = servedNumber(market.acting_spread);
  const moneyline = servedNumber(market.acting_moneyline);

  // THE SENTENCE THE WHOLE SURFACE EXISTS FOR: the simulation's own output, and
  // the market that output produced.
  if (winPct !== null && spread !== null) {
    if (spread === 0) {
      paragraphs.push(
        `Across those runs ${acting.team_name} comes out ahead ${winPct}% of `
        + 'the time and the two lineups finish level, which is why this '
        + 'matchup prices as a pick’em.');
    } else {
      paragraphs.push(
        `Across those runs ${acting.team_name} comes out ahead ${winPct}% of `
        + `the time, for an expected margin of ${Math.abs(spread).toFixed(1)}. `
        + `That margin is the ${formatSpread(spread)} on the Spread`
        + (moneyline === null ? '.'
          : ` and the ${formatOdds(moneyline)} on the Moneyline.`));
    }
  }

  const total = servedNumber(market.total_line);
  const actingTotal = servedNumber(acting.projected_total);
  const opponentTotal = servedNumber(opponent.projected_total);
  if (total !== null) {
    paragraphs.push(
      `The Over/Under of ${total.toFixed(1)} is the combined score those same `
      + 'runs expect'
      + (actingTotal !== null && opponentTotal !== null
        ? `, against projected lineup totals of ${actingTotal.toFixed(1)} and `
          + `${opponentTotal.toFixed(1)}.`
        : '.'));
  }

  // The market the GM entered from is named last, so the explanation reads the
  // same whichever one they came in on and still answers the one they chose.
  const chosen = { ml: 'Moneyline', spread: 'Spread', ou: 'Over/Under' }[
    opts.marketId];
  paragraphs.push(chosen
    ? `${chosen} is the market you opened. Calculated for your league.`
    : 'Calculated for your league.');

  return paragraphs;
}

/**
 * THE READ — what the numbers mean, from the served preview.
 *
 * IT INTERPRETS; IT DOES NOT RE-EXPLAIN THE METHOD. Every claim below is one
 * the served fields support on their own: which lineup projects higher, by how
 * much, how close that leaves the price to a pick'em, and how the expected
 * combined score sits against the two lineup totals. Where the read model
 * supports nothing, this says nothing rather than reaching for football.
 *
 * @param {object} view a served MatchupPreviewOut
 * @returns {string[]} paragraphs
 */
export function theReadFromPreview(view) {
  const market = (view && view.market) || {};
  const acting = (view && view.acting) || {};
  const opponent = (view && view.opponent) || {};

  const actingTotal = servedNumber(acting.projected_total);
  const opponentTotal = servedNumber(opponent.projected_total);
  const margin = servedNumber(view && view.projected_margin);
  const actingRows = Array.isArray(acting.lineup) ? acting.lineup.length : 0;
  const opponentRows = Array.isArray(opponent.lineup) ? opponent.lineup.length : 0;

  // NO LINEUPS, NO READ. Two sides with no projected starters give nothing to
  // interpret, and saying so is the honest answer.
  if (actingTotal === null || opponentTotal === null
      || (actingRows === 0 && opponentRows === 0)) {
    return ['Starting lineups for this matchup are not bound yet, so there is '
      + 'nothing here to read.'];
  }

  const actingAhead = margin !== null && margin > 0;
  const aheadName = actingAhead ? acting.team_name : opponent.team_name;
  const behindName = actingAhead ? opponent.team_name : acting.team_name;
  const aheadTotal = actingAhead ? actingTotal : opponentTotal;
  const behindTotal = actingAhead ? opponentTotal : actingTotal;
  const gap = margin === null ? null : Math.abs(margin);

  const paragraphs = [];

  if (gap !== null && gap === 0) {
    paragraphs.push(
      `${acting.team_name} and ${opponent.team_name} project to the same `
      + `total — ${actingTotal.toFixed(1)} each. There is nothing between `
      + 'these two lineups on paper.');
  } else if (gap !== null) {
    // HOW CLOSE THIS IS reads off the PRICE, not off the projection gap.
    //
    // Judging it from the gap alone was wrong in an instructive way: a 4.5
    // point difference read as "near a pick'em" in the same breath as a 65.8%
    // win probability, because a lineup gap and a market are not the same
    // measure of closeness. The spread IS the market's answer to that question
    // — it is the simulation's expected margin — so it is the one that decides
    // the sentence. Within a point either way is a pick'em in a product whose
    // smallest line step is half a point.
    const spread = servedNumber(market.acting_spread);
    const nearPickEm = spread !== null && Math.abs(spread) <= 1.0;
    paragraphs.push(
      `${aheadName} carries the higher projected lineup total — `
      + `${aheadTotal.toFixed(1)} to ${behindTotal.toFixed(1)}, a gap of `
      + `${gap.toFixed(1)}. `
      + (nearPickEm
        ? 'The market lands within a point of level, so either lineup can '
          + 'take it.'
        : 'That edge carries into the price rather than washing out.'));
  }

  const winPct = servedPercent(market.acting_win_probability);
  if (winPct !== null) {
    const decisive = winPct >= 60 || winPct <= 40;
    paragraphs.push(
      `The simulation puts ${acting.team_name} at ${winPct}%`
      + (decisive
        ? ' — the runs separate these two by more than the projected totals '
          + 'alone suggest.'
        : ' — near enough to even that the outcome is genuinely open.'));
  }

  const total = servedNumber(market.total_line);
  if (total !== null) {
    const combined = actingTotal + opponentTotal;
    paragraphs.push(
      `The expected combined score of ${total.toFixed(1)} sits `
      + (total > combined ? 'above' : 'below')
      + ` the ${combined.toFixed(1)} these two lineups project on paper, which `
      + 'is the spread of outcomes the simulation adds to the two totals.');
  }

  return paragraphs.length ? paragraphs
    : ['There is not enough bound for this matchup to read yet.'];
}
