/* ============================================================================
 * FantasyStakes — Wrap Up · THE READ
 * Final POR §9 / §10
 *
 * A Wrap Up is not a receipt. Every completed detail sheet carries a short
 * postgame read: what happened, why, and the one thing to do about it next
 * week. This module owns that copy for all three detail types so the three
 * sheets cannot drift into three different voices.
 *
 * ── §10 · WHAT MAY BE SAID, AND WHAT MAY NOT ───────────────────────────────
 *
 * THE RULE IS THAT NOTHING HERE IS INVENTED. Every sentence below is derived
 * from a figure the product already holds: the provider's final team scores,
 * the market and line the wager locked, the stake, the pot and the settled net.
 * Subtraction and comparison of those is analysis. Anything that would need a
 * fact the product does not have is NOT produced — not estimated, not
 * approximated, and not filled in from a plausible-looking default.
 *
 * SO THERE IS NO OPTIMAL EFFICIENCY, NO TARGET SHARE, NO SNAP COUNT, NO
 * ROUTES, NO TOUCHES, NO BENCH POINTS AND NO STUDS-AND-DUDS SECTION. §9A asks
 * for them where trustworthy data exists, and §10 forbids them where it does
 * not. It does not: the provider publishes TEAM totals for a matchup and not
 * per-player scoring — the same limit `providerMatchupSheet` has always stated
 * on its face — so there is no lineup, no usage and no bench to read. A
 * per-player usage feed is what those sections need, and until one is served
 * the honest answer is the simpler one §10 explicitly permits.
 *
 * THE SAME RULE BINDS THE DEMO. §10 allows the showcase deterministic
 * synthetic analytics, and this module deliberately does not take that
 * permission for player metrics: the Demo's completed weeks are settled by the
 * ordinary engine against real seeded results, so its reads are computed from
 * those results exactly as a production league's are. Nothing here branches on
 * whether the league is the Demo, which is the strongest form of "clearly
 * isolated from provider production truth" available — there is no synthetic
 * analytic to isolate.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import { formatCredits, formatSignedCredits } from './credits.js';

/** The heading every postgame read sits under. */
export const READ_HEADING = 'THE READ';

/**
 * How decisive a fantasy margin was, in football language rather than a number.
 *
 * THE BANDS ARE STATED, NOT TUNED. A fantasy week turns on a handful of
 * possessions; under a converted touchdown is the range a single late catch
 * decides, and over four scores is a result no lineup call was going to change.
 *
 * @param {number} margin
 * @returns {{word: string, narrow: boolean}}
 */
export function marginShape(margin) {
  const m = Math.abs(Number(margin) || 0);
  if (m < 7) return { word: 'a one-possession game', narrow: true };
  if (m < 14) return { word: 'a two-score win', narrow: false };
  if (m < 28) return { word: 'a comfortable margin', narrow: false };
  return { word: 'a blowout', narrow: false };
}

/**
 * THE READ for a completed provider matchup — §9A.
 *
 * WIN/LOSS AND THE MARGIN ARE THE WHOLE READ, because they are the whole of
 * what the provider published. The second sentence says what the margin MEANS,
 * which is the part a reader cannot get from the scoreline itself.
 *
 * @param {object} m a normalised matchup
 * @returns {{sentences: string[], next: string}|null}
 */
export function providerMatchupRead(m) {
  if (!m || !m.final) return null;
  const home = m.home ? m.home.points : null;
  const away = m.away ? m.away.points : null;
  if (home === null || away === null) return null;

  const margin = Math.abs(home - away);
  const shape = marginShape(margin);
  const level = home === away;

  if (!m.involvesActingTeam || !m.actingSide) {
    // A LEAGUE MATCHUP THE READER IS NOT IN still gets a read; it is just not
    // written in the second person, because it is not their result.
    const leader = home > away ? m.home : m.away;
    return {
      sentences: level
        ? ['This one finished level.']
        : [`${leader.name} took it by ${margin.toFixed(1)}, ${shape.word}.`],
      next: '',
    };
  }

  const mine = m.actingSide === 'home' ? home : away;
  const theirs = m.actingSide === 'home' ? away : home;
  const won = mine > theirs;

  if (level) {
    return {
      sentences: ['You tied. Nothing separated the two lineups on the week.'],
      next: 'Nothing to change on this result alone.',
    };
  }

  const sentences = won
    ? [`You won by ${margin.toFixed(1)} — ${shape.word}.`]
    : [`You lost by ${margin.toFixed(1)} — ${shape.word}.`];

  sentences.push(shape.narrow
    ? 'A margin this thin turns on one late score either way, so read it as a '
      + 'close call rather than as a verdict on the lineup.'
    : (won
      ? 'A margin that size was not in doubt late; the lineup did its job.'
      : 'A margin that size was not a lineup call — the week was lost on '
        + 'production, not on who you started.'));

  return {
    sentences,
    next: shape.narrow
      ? 'Next week: the close ones are where a start/sit actually pays. Check '
        + 'your flex before kickoff.'
      : (won
        ? 'Next week: keep the same core and do not chase a matchup you do not need.'
        : 'Next week: look at the positions that produced least, not at the ones you benched.'),
  };
}

/**
 * THE READ for a settled FantasyStakes matchup — §9B.
 *
 * FANTASY FIRST, MARKET SECOND. The fantasy result is what happened; the line
 * is the price that result was measured against. Reading them in that order is
 * what makes the cover margin mean something rather than read as a second,
 * competing score.
 *
 * THE COVER IS COMPUTED, NOT QUOTED. It is the fantasy margin measured against
 * the locked line, both of which the product holds. There is no closing line,
 * no price movement and no implied probability here, because none of those is
 * served — §10.
 *
 * @param {object} card a wager card
 * @param {object|null} matchup the acting GM's provider matchup for that week
 * @returns {{sentences: string[], next: string}|null}
 */
export function wagerRead(card, matchup) {
  if (!card || !card.settled) return null;

  const net = Number.isInteger(card.netCents) ? card.netCents : null;
  const won = net !== null ? net > 0 : null;
  const sentences = [];

  const line = parseFloat(card.line);
  const hasLine = Number.isFinite(line);

  let margin = null;
  let mine = null;
  let theirs = null;
  if (matchup && matchup.final && matchup.involvesActingTeam && matchup.actingSide) {
    const home = matchup.home ? matchup.home.points : null;
    const away = matchup.away ? matchup.away.points : null;
    if (home !== null && away !== null) {
      mine = matchup.actingSide === 'home' ? home : away;
      theirs = matchup.actingSide === 'home' ? away : home;
      margin = mine - theirs;
    }
  }

  if (margin !== null) {
    const verb = margin >= 0 ? 'won' : 'lost';
    sentences.push(`Your fantasy matchup ${verb} by ${Math.abs(margin).toFixed(1)}.`);
    if (hasLine) {
      // THE CUSHION: how much room the result had beyond the number that was
      // locked. Stated as a distance, never as a probability.
      const cushion = margin - line;
      const covered = cushion > 0;
      sentences.push(covered
        ? `You took ${line > 0 ? `+${line}` : line} and cleared it by `
          + `${Math.abs(cushion).toFixed(1)} beyond the line.`
        : `You took ${line > 0 ? `+${line}` : line} and came up `
          + `${Math.abs(cushion).toFixed(1)} short of it.`);
      sentences.push(Math.abs(cushion) < 3
        ? 'That is a narrow finish — this one was decided inside the line, not '
          + 'comfortably outside it.'
        : 'That is real daylight against the number, not a lucky finish.');
    }
  } else if (won !== null) {
    sentences.push(won
      ? 'This wager settled in your favour.'
      : 'This wager settled against you.');
  }

  if (net !== null) {
    sentences.push(`It settled ${formatSignedCredits(net)} against a `
      + `${formatCredits(card.yourStakeCents)} stake.`);
  }

  if (!sentences.length) return null;

  return {
    sentences,
    next: hasLine && margin !== null && Math.abs(margin - line) < 3
      ? 'Next time: a line this tight is a coin flip — size the stake for it.'
      : 'Next time: the edge came from the lineup, not the number. Price the matchup first.',
  };
}

/**
 * THE READ for a settled Prop Pool — §9C.
 *
 * WHY IT WON OR LOST, IN FOOTBALL WORDS. The Pool's own governed definition
 * says what was measured; this says which side of it the pick landed on. The
 * definition is never printed as notation — §8 — so a rule stated as a formula
 * is described rather than shown.
 *
 * @param {object} pool a settled slate row
 * @param {string} pickLabel what the GM picked
 * @returns {{sentences: string[], next: string}|null}
 */
export function poolRead(pool, pickLabel) {
  if (!pool || !pool.settled) return null;

  const result = String(pool.myResult || '');
  const driver = poolDriver(pool);
  const sentences = [];

  if (result === 'won') {
    sentences.push(`${pickLabel} came out on top of this Pool.`);
    sentences.push(`It was decided on ${driver}, and that is where your pick `
      + 'had the edge.');
  } else if (result === 'lost') {
    sentences.push(`${pickLabel} did not win this Pool.`);
    sentences.push(`It was decided on ${driver}, and another entry's side `
      + 'produced more of it.');
  } else if (result === 'not_entered') {
    sentences.push('You did not enter this Pool.');
    sentences.push(`It was decided on ${driver}.`);
  } else {
    sentences.push('This Pool settled with no winning entry.');
    sentences.push(`It was decided on ${driver}.`);
  }

  if (Number.isInteger(pool.myNetCents)) {
    sentences.push(`Your net was ${formatSignedCredits(pool.myNetCents)}.`);
  }

  return {
    sentences,
    next: result === 'won'
      ? 'Next week: the same read travels — back the side with the volume, not the name.'
      : 'Next week: pick the side getting the opportunities, not the one that scored last week.',
  };
}

/**
 * The football driver a Pool turned on, in plain language.
 *
 * §8 FORBIDS THE NOTATION. A governed definition reads
 * `sum(both teams offensive_yards)` internally, and printing that in a GM's
 * Wrap Up is exposing an implementation detail as if it were an explanation.
 * The subject the definition names is matched to the football thing it
 * measures, and anything unrecognised falls back to a true general statement
 * rather than to the formula.
 *
 * @param {object} pool
 * @returns {string}
 */
export function poolDriver(pool) {
  const text = `${pool.question || ''} ${pool.rule || ''} ${pool.name || ''}`
    .toLowerCase();

  /* ORDER MATTERS. A Pool asking for the fewest INTERCEPTIONS also contains
   * the word "passing" in its category, and a Pool measuring YARDS PER TOUCH
   * also contains "yard" — so the narrower football idea is matched first and
   * the broad volume words are the fallback, not the headline. */
  if (text.includes('interception') || text.includes('turnover')
      || text.includes('fumble')) return 'ball security';
  if (text.includes('per touch') || text.includes('per carry')
      || text.includes('per target') || text.includes('per reception')
      || text.includes('efficiency') || text.includes('averages')) {
    return 'how much each touch produced';
  }
  if (text.includes('field goal')) return 'red-zone finishing and the kicking game';
  if (text.includes('sack')) return 'pressure up front';
  if (text.includes('touchdown')) return 'trips to the end zone';
  if (text.includes('receiving') || text.includes('reception')
      || text.includes('catch') || text.includes('target')) return 'receiving volume';
  if (text.includes('rush') || text.includes('carr')) return 'rushing volume';
  if (text.includes('passing') || text.includes('pass ')) return 'passing volume';
  if (text.includes('yard')) return 'total yardage';
  if (text.includes('point') || text.includes('score')) return 'scoring';
  return 'the week’s production in the categories this Pool measures';
}

/**
 * The first sentence of a read — the card-sized version of the same analysis.
 *
 * FINAL POR §6 — a carousel card carries the takeaway, the detail sheet
 * carries the argument. Taking the card's line from the SAME read is what
 * stops the two drifting: there is one analysis, printed at two lengths.
 *
 * @param {{sentences: string[]}|null} read
 * @param {number} [count] how many leading sentences to keep
 * @returns {string} '' when there is no read to take one from
 */
export function takeaway(read, count = 1) {
  if (!read || !read.sentences || !read.sentences.length) return '';
  return read.sentences.slice(0, count).join(' ');
}

/**
 * THE READ, rendered.
 *
 * @param {{sentences: string[], next: string}|null} read
 * @param {(heading: string, inner: string) => string} section
 * @param {(text: string) => string} paragraph
 * @returns {string}
 */
export function renderRead(read, section, paragraph) {
  if (!read) return '';
  const body = read.sentences.map((s) => paragraph(s)).join('')
    + (read.next ? paragraph(read.next) : '');
  return section(READ_HEADING, body);
}

/** Escaped paragraph, for callers that want the default shape. */
export function readParagraph(text) {
  return `<p class="fs-wrapnote">${escapeHtml(text)}</p>`;
}
