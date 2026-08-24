/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · The Week
 * Sprint 7 Package 3
 *
 * A compact three-module weekly dashboard: the league's official Yahoo
 * matchups, the GM's FantasyStakes bets for that week, and the week's four
 * Pools. Exactly three modules — the POR fixes the set, so this file has no
 * mechanism for a fourth.
 *
 * WHAT REV 4.2 REMOVED, AND WHY NOTHING REPLACES IT. The kickoff clock, the
 * PAST WEEK / WEEK 3 / WEEK 4 treatment and the Preview / Results / Review
 * selector are all gone. In their place is ONE control — a week switch reading
 * `WEEK 4 · REGULAR SEASON · WEEK 5` — and the presentation follows from which
 * week is selected rather than from a mode the GM has to pick. A current week
 * previews; a past week reviews. A GM never chooses between the two, because
 * for any given week only one of them is meaningful.
 *
 * THE WEEK CARRIES NO FOUR-CELL STRIP. The locked Rev 4.2 Final POR resolves
 * the Package 1 open question: this tab summarises no position, so it takes no
 * strip — and therefore no Credits disclaimer, which appears only under one.
 * ========================================================================== */

import { attributionFooter } from './attribution.js';
import {
  PENDING_FIGURE, PanelComposer, escapeHtml, note, sectionHeading,
} from './components.js';
import { formatCredits, formatSignedCredits } from './credits.js';
import { CURRENT_WEEK, PAST_WEEK, WEEKS, weekBets, weekPools, yahooMatchups } from './data/week-data.js';
import {
  LEAGUE_MODE_DEMO, LEAGUE_MODE_UNAVAILABLE, actingMatchup, currentWeek,
  leagueMode, servedContext, weekMatchups,
} from './league-model.js';
import {
  ACTION_MODE_UNAVAILABLE, SECTIONS, actionMode, sectionCards,
} from './action-model.js';
import { poolBadge } from './data/league-data.js';
import {
  SLATE_MODE_DEMO,
  SLATE_MODE_DRAWN,
  SLATE_MODE_UNDRAWN,
  previousSlateRows,
  slateMode,
  slateRows,
} from './pool-slate-model.js';
import { poolQuestion } from './league.js';
import { previewSheet } from './preview.js';
import { matchupMarketCells, wagerCard } from './wagercard.js';
import { onActivate } from './interaction.js';
import { skunkOfTheWeek, skunkWeek } from './skunk-model.js';
import { seasonResultsSection } from './season-results.js';
import { championshipResults } from './standings-model.js';
import {
  poolRead, providerMatchupRead, renderRead, takeaway, wagerRead,
} from './wrapup-read.js';

/** Locked Rev 4.2 subtitle. */
// WP3D — `Official` IS GONE, AND THE PROVENANCE IS NOT.
//
// Rev 4.3 §23 permits a statement of where data came from and nothing more.
// "Official Yahoo matchups" goes further than provenance: in a product Yahoo
// does not operate, endorse or approve, "official" reads as standing rather
// than as source. The subtitle still says exactly where the matchups come
// from — which §11 requires it not to weaken — and the exact contractual
// attribution at the foot of the tab now carries the formal statement.
export const WEEK_SUBTITLE = 'Yahoo matchups + FantasyStakes action';

/**
 * Locked Rev 4.2 heading for the FantasyStakes Bets module.
 *
 * `4 SHOWN` is the VIEWPORT treatment — how many wagers this module presents —
 * and it is locked copy, not a running count of records. Package 3 derived the
 * number from the card list, which made a past week with three settled records
 * draw `3 SHOWN`. That was the wrong correction to the right instinct: the
 * heading must not be invented, and neither must a fourth historical wager to
 * satisfy it. The heading is fixed here and the module shows at most four.
 */
// Rev 4.3 §11 — the word SWIPE carries the affordance; the redundant
// directional arrow is removed and not replaced with another glyph.
// UIRECON WAVE 1 — the locked public term. `BETS_HEADING` keeps its internal
// name: it is imported by name in three suites and by `week.js` itself, and
// the constant is not the copy.
// UIRECON WAVE 4B — the three result sections carry one heading grammar:
// NAME · SWIPE. `4 SHOWN` was this section's alone and described a viewport
// cap that a one-card carousel makes meaningless — a GM swipes to the next
// card whether there are two or four. The cap itself is unchanged and is
// still `BETS_SHOWN`; what is gone is a heading that named it.
export const BETS_HEADING = 'FANTASYSTAKES MATCHUPS · SCROLL';

/** The viewport cap the heading states. */
export const BETS_SHOWN = 4;

/** Which week the tab is showing. The current week is the opening state. */
let selectedWeek = null;

/**
 * The week this tab is showing.
 *
 * S8-P4C-5: THE FIXTURE WEEK IS THE FALLBACK, NOT THE DEFAULT. `selectedWeek`
 * used to initialise to the illustrative `CURRENT_WEEK`, so a production league
 * in week 9 opened The Week on week 5 — its Yahoo module read week 5, and its
 * Versus module filtered the GM's wagers for week 5 and found none. Both looked
 * like empty states rather than the wrong question.
 *
 * Null until something asks, so the authoritative week is consulted at read
 * time rather than captured at module load, before any binding has happened.
 */
/* THE SERVED LEAGUE IS THE DEMO ONE — the server's own flag, not a UI mode.
 *
 * `actionMode()` and `leagueMode()` both report AUTHORITATIVE for the showcase,
 * because the Demo league is served through the real read models rather than
 * through the illustrative fixtures. They answer "which data source is this
 * surface reading", which is a different question from "is this the demo",
 * and using them here made the §6 default silently never apply. */
function isDemoLeague() {
  const context = servedContext();
  return !!(context && context.demo === true);
}

function activeWeek() {
  if (selectedWeek !== null) return selectedWeek;
  const now = currentWeek() ?? CURRENT_WEEK;

  /* FINAL POR §6 — THE DEMO OPENS ON THE WEEK THAT FINISHED.
   *
   * A Wrap Up reviews a week that HAPPENED. Opening on the live week meant the
   * showcase's three rails led with LIVE, OPEN and PENDING records: a visitor
   * meeting the product saw a week still in flight and no final score, no
   * settled pot and no net anywhere in the tab that exists to report them.
   *
   * SCOPED TO THE DEMO, DELIBERATELY. A real league's Wrap Up still opens on
   * its own current week — that is the week its GMs are living in, and moving
   * a production default is not what §6 asks for. The switch still offers both
   * weeks in both modes, so nothing is unreachable either way. */
  if (isDemoLeague() && now > 1) return now - 1;
  return now;
}

/**
 * The pair of weeks the switch offers.
 *
 * FROM THE LEAGUE'S CURRENT WEEK, never from the SELECTED one. Deriving it from
 * the selection made the switch walk backwards: choosing week 8 redrew the pair
 * as 7 and 8, so week 9 vanished from the control that was supposed to offer
 * it. The pair is a property of when the season is, and selecting within it
 * cannot change it.
 */
function switchWeeks() {
  const now = currentWeek() ?? CURRENT_WEEK;
  return [now - 1, now];
}

/**
 * The week currently shown — resolved, never the raw internal state.
 *
 * Callers ask this to learn WHICH WEEK IS ON SCREEN, and `selectedWeek` is null
 * until a GM taps the switch. Returning the null would make the accessor mean
 * "nobody has tapped yet", which is a different question and not the one any
 * caller is asking.
 *
 * @returns {number}
 */
export function currentSelectedWeek() {
  return activeWeek();
}

/**
 * @param {number} week
 * @returns {number}
 */
export function selectWeek(week) {
  // THE SWITCH'S OWN TWO WEEKS, which follow the authoritative week — not the
  // fixture's fixed pair. A production league in week 9 offers weeks 8 and 9,
  // and `WEEKS` would have refused both.
  if (!switchWeeks().includes(week)) {
    throw new Error(`week ${week} is not on the switch`);
  }
  selectedWeek = week;
  return selectedWeek;
}

/** Restore the opening state — used by the suites. */
export function resetWeek() {
  selectedWeek = null;
}

/* ── Header ─────────────────────────────────────────────────────────────────*/

/**
 * The one compact week switch.
 *
 * Both weeks are text controls in a single line; the selected one is
 * emphasised. There is no third control, and no presentation selector — the
 * week IS the selector.
 *
 * @returns {string}
 */
function weekSwitch() {
  const control = (week) => {
    const selected = activeWeek() === week;
    return (
      `<button type="button" class="fs-wkswitch__opt${selected ? ' is-selected' : ''}" ` +
      `data-week="${week}" aria-pressed="${selected}">WEEK ${week}</button>`
    );
  };

  return (
    '<div class="fs-wkhead">' +
    '<div class="fs-wkswitch" role="group" aria-label="Week">' +
    control(switchWeeks()[0]) +
    '<span class="fs-wkswitch__mid">REGULAR SEASON</span>' +
    control(switchWeeks()[1]) +
    '</div>' +
    `<div class="fs-wkhead__sub">${escapeHtml(WEEK_SUBTITLE)}</div>` +
    '</div>'
  );
}

/* ── Module 1 · Yahoo league matchups ───────────────────────────────────────*/

/**
 * One official Yahoo matchup.
 *
 * Same card grammar as League and Action — and a YAHOO badge, no market
 * interactivity and no challenge affordance, because this is a league fixture
 * rather than something to wager on. The grammar is shared; the meaning is not
 * blurred.
 *
 * @param {object} m
 * @returns {string}
 */
export function yahooCard(m) {
  // A settled matchup shows RESULTS and carries no market row. Its margin and
  // combined score are outcomes, and putting them in cells labelled SPR and O/U
  // would present a finished game as a live market.
  const figures = m.settled
    ? [
      { label: 'Final', value: `${m.yourProjection.toFixed(1)} — ${m.opponentProjection.toFixed(1)}` },
      { label: 'Margin', value: Math.abs(m.spread).toFixed(1) },
      { label: 'Combined', value: m.total.toFixed(1) },
    ]
    : [
      { label: 'Projected', value: `${m.yourProjection.toFixed(1)} — ${m.opponentProjection.toFixed(1)}` },
      { label: 'Total', value: m.total.toFixed(1) },
    ];

  return wagerCard({
    identity: `${m.you.name} vs ${m.name}`,
    context: `${m.you.record} · ${m.you.rank}   ·   ${m.record} · ${m.rank}`,
    markets: m.settled ? null : matchupMarketCells(m),
    interactiveMarkets: false,
    figures,
    badge: 'YAHOO',
    badgeTone: m.viewerIsIn ? 'gold' : 'neutral',
    accent: m.settled ? 'done' : '',
    footLabel: m.settled ? `FINAL · ${m.winner} won` : 'PREGAME · official fixture',
    footValue: 'Preview ›',
    tapAction: 'yahoo',
    tapId: m.id,
    className: 'fs-wcard--yahoo',
  });
}

function yahooModule() {
  const production = leagueMode() !== LEAGUE_MODE_DEMO;
  const body = production ? providerMatchupBody() : demoMatchupBody();
  return resultSection({
    title: 'YAHOO LEAGUE MATCHUPS · SCROLL',
    id: 'yahoo',
    items: body.items,
    empty: body.empty,
  });
}


// UIRECON WAVE 4B — CARDS, NOT PRE-WRAPPED MARKUP. Both Yahoo body functions
// used to wrap each card in their own `.fs-vcar__item`; the shared
// `resultSection()` owns the item wrapper for all three sections now, so these
// return the cards and the empty state separately and let it decide.
function demoMatchupBody() {
  return { items: yahooMatchups(activeWeek()).map(yahooCard), empty: '' };
}

/**
 * The provider-backed matchups, or an honest statement that there are none.
 *
 * FOUR OUTCOMES, AND THEY ARE NOT THE SAME SENTENCE:
 *
 *   unavailable  the context read failed — say so, and never draw a fixture
 *                matchup in its place. An illustrative Yahoo card is the worst
 *                possible thing to show here: it looks exactly like the real
 *                one and names real-sounding teams and scores.
 *   no week      no provider refresh has stated a current week, so there is
 *                nothing to scope a matchup read to.
 *   not read     this week has not been fetched (only the current week is).
 *   empty        the read succeeded and the provider published nothing —
 *                an authoritative answer, not a failure.
 */
function providerMatchupBody() {
  if (leagueMode() === LEAGUE_MODE_UNAVAILABLE) {
    return { items: [], empty: weekNote('unavailable',
      'Your league’s matchups could not be loaded.') };
  }
  if (currentWeek() === null) {
    return { items: [], empty: weekNote('no-week',
      'No fantasy week has been published for this league yet.') };
  }
  const rows = weekMatchups(activeWeek());
  if (rows === null) {
    return { items: [], empty: weekNote('not-read',
      `Week ${activeWeek()} has not been loaded.`) };
  }
  if (!rows.length) {
    return { items: [], empty: weekNote('empty',
      `No matchups have been published for week ${activeWeek()}.`) };
  }
  return {
    items: mineFirst(rows, (m) => m.involvesActingTeam).map(providerMatchupCard),
    empty: '',
  };
}

function weekNote(state, text) {
  return `<p class="fs-wkmod__note" data-week-state="${state}">`
    + `${escapeHtml(text)}</p>`;
}

/**
 * One provider-backed matchup card.
 *
 * WHAT IT DOES NOT DRAW, and this is the point of the function existing
 * separately from `yahooCard`: no market row. The illustrative card carries
 * ML / SPR / O/U cells, and the fixture MANUFACTURES all three from
 * projections — `spread = opponentFigure - subjectFigure`,
 * `total = subjectFigure + opponentFigure`. The provider gateway captures no
 * betting lines of any kind; the only `total` anywhere in the corpus is a
 * player's fantasy points. Deriving a market from fantasy scores would be
 * inventing a line, so production shows the scores it has and no market at all.
 *
 * FINALITY IS `finalized_at`, not "the week looks over" and not "the score
 * stopped moving". ORIENTATION is the served home/away, decided from sorted
 * provider team keys, so a mirrored payload cannot flip the card.
 */
function providerMatchupCard(m) {
  const score = (side) => (side.points === null
    ? PENDING_FIGURE : side.points.toFixed(1));

  const bothScored = m.home.points !== null && m.away.points !== null;
  const marginValue = bothScored
    ? Math.abs(m.home.points - m.away.points).toFixed(1) : PENDING_FIGURE;

  // §6A — THE MARGIN SITS BESIDE THE SCORE. It is subtraction on two published
  // figures, and it is the number that says whether the week was ever in doubt.
  const figures = [
    { label: m.final ? 'Final' : 'Live',
      value: `${score(m.home)} — ${score(m.away)}` },
    { label: 'Margin', value: marginValue },
  ];

  const winner = m.winnerTeamId === m.home.teamId ? m.home.name
    : (m.winnerTeamId === m.away.teamId ? m.away.name : null);

  return wagerCard({
    identity: `${m.home.name} vs ${m.away.name}`,
    context: m.involvesActingTeam ? `You are ${m.actingSide}` : '',
    markets: null,
    interactiveMarkets: false,
    // §6A — the one-line read, from the same analysis the detail sheet prints.
    copy: takeaway(providerMatchupRead(m)),
    figures,
    badge: 'YAHOO',
    badgeTone: m.involvesActingTeam ? 'gold' : 'neutral',
    accent: m.final ? 'done' : '',
    footLabel: m.final
      ? (winner ? `FINAL · ${winner} won` : 'FINAL')
      : 'IN PROGRESS',
    footValue: '',
    // UI-5 GAP 1 CLOSED. This was '' -- the card carried no `data-card-action`
    // and nothing bound to it, so §29's Fantasy Football Breakdown existed for
    // the DEMO card and not for the real one. The gap was recorded rather than
    // guessed at because the honest question was what a breakdown may contain
    // when the provider gateway captures no lineups and no projections, and
    // §29 forbids fabricating analysis in the same breath as it asks for the
    // section. `providerMatchupSheet` answers it: everything below is a fact
    // the provider stated or arithmetic on two figures it stated, and the one
    // thing it cannot say it says outright.
    tapAction: 'provider',
    tapId: `provider-${m.matchupId}`,
    className: 'fs-wcard--yahoo',
  });
}

/**
 * §29's Fantasy Football Breakdown for a PROVIDER-BACKED matchup.
 *
 * WHAT IT MAY CONTAIN IS DECIDED BY WHAT THE PROVIDER SAID. The gateway
 * captures team names, owners, points, finality, the winner and a refresh
 * timestamp. It captures no lineups, no projections, no per-player scoring and
 * no betting lines. So this sheet draws those seven facts and the margin
 * between the two figures -- which is subtraction on provider numbers, not
 * analysis -- and nothing else.
 *
 * AND IT SAYS WHAT IT CANNOT SAY. §29 asks for a breakdown and forbids
 * fabricating one, and a sheet that quietly stopped after the score would leave
 * a reader assuming the per-player detail is coming. Stating the absence is the
 * only treatment that is both complete and true; inventing "drivers" from the
 * two team totals would be exactly the fabrication the section forbids.
 *
 * A NULL SCORE IS NOT ZERO. `normaliseSide` keeps them apart deliberately -- a
 * provider that reported no points has not said the team scored none -- so the
 * margin is withheld rather than computed from a stand-in.
 *
 * @param {object} m a normalised WeekMatchupOut
 * @returns {{title: string, sub: string, body: string}}
 */
/* ── FINAL POR §8 · ONE COMPONENT FAMILY FOR EVERY WRAP UP DETAIL ───────────
 *
 * The three detail sheets were built three ways. The Yahoo one emitted a bare
 * `.fs-rule__head` and loose `.fs-prev__row`s; the Matchup one wrapped its rows
 * in `<section class="fs-rule">`; the Pool one used a third wrapper again,
 * `.fs-prev__section`, and set its own paragraph copy at a size neither of the
 * others used. Three surfaces a GM reads as one thing, drawn as three.
 *
 * These are the only primitives the three sheets may use. Title typography,
 * week/status typography, section labels, key/value sizing, left/right
 * alignment, padding, dividers and vertical spacing are all decided once, in
 * `.fs-wrapsec` / `.fs-wraprow` / `.fs-wrapnote` — so the three cannot drift
 * again without changing all three at once. */
function detailSection(heading, inner) {
  return (
    '<section class="fs-wrapsec">'
    + `<h3 class="fs-wrapsec__head">${escapeHtml(heading)}</h3>`
    + inner
    + '</section>'
  );
}

function detailRow(label, value, extra = '') {
  return (
    '<div class="fs-wraprow">'
    + `<span class="fs-wraprow__label">${escapeHtml(label)}</span>`
    + `<span class="fs-wraprow__value ${extra}">${escapeHtml(value)}</span>`
    + '</div>'
  );
}

function detailNote(text) {
  return `<p class="fs-wrapnote">${escapeHtml(text)}</p>`;
}

export function providerMatchupSheet(m) {
  const figure = (side) => (side.points === null
    ? PENDING_FIGURE : side.points.toFixed(1));

  const bothScored = m.home.points !== null && m.away.points !== null;
  const margin = bothScored
    ? Math.abs(m.home.points - m.away.points).toFixed(1) : null;
  const leader = bothScored && m.home.points !== m.away.points
    ? (m.home.points > m.away.points ? m.home : m.away) : null;
  const winner = m.winnerTeamId === m.home.teamId ? m.home
    : (m.winnerTeamId === m.away.teamId ? m.away : null);

  /* FINAL POR 9A - THE SUBTITLE CARRIES THE OUTCOME, NOT JUST THE WEEK.
   *
   * "Week 10 - Final" told a reader nothing they had not already seen on the
   * card. Outcome-first means the first line of the sheet answers the question
   * the sheet was opened to ask, so the result and the score sit in it. */
  const outcome = (() => {
    if (!m.final) return `Week ${m.week} · In progress`;
    if (!bothScored) return `Week ${m.week} · Final`;
    const score = `${figure(m.home)}–${figure(m.away)}`;
    if (m.involvesActingTeam && m.actingSide) {
      const mine = m.actingSide === 'home' ? m.home.points : m.away.points;
      const theirs = m.actingSide === 'home' ? m.away.points : m.home.points;
      if (mine === theirs) return `Week ${m.week} · Final · TIED ${score}`;
      return `Week ${m.week} · Final · ${mine > theirs ? 'WIN' : 'LOSS'} ${score}`;
    }
    return `Week ${m.week} · Final · ${score}`;
  })();

  return {
    title: `${m.home.name} vs ${m.away.name}`,
    sub: outcome,
    body:
      renderRead(providerMatchupRead(m), detailSection, detailNote)
      + detailSection('FANTASY FOOTBALL BREAKDOWN',
        detailRow(m.home.name, figure(m.home), 'fs-money')
        + detailRow(m.away.name, figure(m.away), 'fs-money')
        // THE MARGIN IS SUBTRACTION, NOT A READ. Withheld outright when either
        // side has no figure, because a margin against a missing score would be
        // a number nobody stated.
        + (margin === null
          ? detailRow('Margin', PENDING_FIGURE)
          : detailRow('Margin', leader === null
            ? 'Level' : `${margin} · ${leader.name}`, 'fs-money'))
        + detailRow('Result', m.final
          ? (winner ? `${winner.name} won` : 'Final')
          : 'Not final yet')
        + (m.involvesActingTeam && m.actingSide
          ? detailRow('Your side', m.actingSide) : '')
        + (m.home.owner || m.away.owner
          ? detailRow('Managers', `${m.home.owner || '—'} vs ${m.away.owner || '—'}`)
          : ''))
      + (m.refreshedAt
        ? `<div class="fs-wrapsrc">Provider figures as at ${
          escapeHtml(String(m.refreshedAt))}</div>`
        : '')
      // THE HONEST LIMIT, stated rather than left to be inferred from silence.
      // It is also why 9A's Studs, Duds and bench-points sections are absent
      // rather than estimated - see `wrapup-read.js`.
      + detailNote('Your fantasy provider publishes team totals for this '
        + 'matchup and not per-player scoring, so there is no lineup breakdown '
        + 'to show. FantasyStakes will not estimate one from the team figures.'),
  };
}


/* ── Module 2 · FantasyStakes bets ──────────────────────────────────────────*/

function betsModule() {
  // At most four, because that is what the locked heading says this module
  // presents. A week holding fewer real wagers draws fewer cards — the shortfall
  // is never made up by inventing a wager that no protocol record supports.
  const production = actionMode() !== 'demo';
  const body = production ? versusBody() : demoBetsBody();
  return resultSection({
    title: BETS_HEADING,
    id: 'bets',
    items: body.items,
    empty: body.empty,
  });
}

function demoBetsBody() {
  return {
    items: weekBets(activeWeek()).slice(0, BETS_SHOWN).map(matchupRecapCard),
    empty: '',
  };
}

/**
 * The GM's own wagers for the selected week — from the ACTION read contract.
 *
 * NO SECOND WAGER READ MODEL. `reports/action_read_model.py` already classifies
 * this GM's proposals and wagers and serves opponent, stake, mode, terms,
 * finality and net outcome. A Week-specific reader would be a second answer to
 * the same question — and the two would agree until the day one of them was
 * corrected. Versus therefore filters the SAME served cards by week.
 *
 * Rendered with `lifecycleCard`, the same component the Action rails use, so a
 * wager cannot look like one thing on Action and another here.
 */
function versusBody() {
  if (actionMode() === ACTION_MODE_UNAVAILABLE) {
    return { items: [],
      empty: weekNote('unavailable', 'Your wagers could not be loaded.') };
  }
  const rows = SECTIONS
    .flatMap((section) => sectionCards(section))
    .filter((card) => card.week === `WK ${activeWeek()}`)
    .slice(0, BETS_SHOWN);

  if (!rows.length) {
    return { items: [],
      empty: weekNote('empty', `No wagers for week ${activeWeek()}.`) };
  }
  return {
    items: rows.map(matchupRecapCard),
    empty: '',
  };
}

/* ── Module 3 · FantasyStakes Pools ─────────────────────────────────────────*/

/**
 * One Prop Pool that has NOT settled yet, in the shared result shell.
 *
 * ── WHAT THIS REPLACES, AND WHY A ROW WAS THE WRONG COMPONENT ──────────────
 *
 * `.fs-poolrow` was a 45px button: badge, name, one state string and a figure,
 * on one line. It was correct for the flat list this module used to be, and
 * Wave 4B kept it deliberately — "an unsettled one keeps the compact row it has
 * always had, because still open is a different statement from here is what
 * happened".
 *
 * MEASURED ON THE DEPLOYED RC4 BUILD, that reasoning cost the section its
 * standing. At Week 11 every Pool on the slate is open, so all four items drew
 * the row and the third carousel measured 45px against 132.30px of Yahoo and
 * 150.06px of FantasyStakes Matchup — a strip beside two carousels, in a tab
 * whose whole construction is three peers.
 *
 * SO THE SHELL IS THE SHARED ONE AND THE CONTENT IS STILL "STILL OPEN". The
 * distinction Wave 4B was protecting was never about the BOX; it was about what
 * the card says. A settled Pool reports a winner and what it returned; an open
 * one reports what it is asking, what it costs to be in, how many are in and
 * what is in the pot. Same shell, different data — §11, applied one level
 * further in than Wave 4B took it.
 *
 * NOTHING HERE IS INVENTED. The question is the catalog's, through the same
 * `poolQuestion` the Play card asks it with — a second author would be exactly
 * what POR Rev 1.4 §3.2 forbids. The pick is read back from the served subject
 * list, and a GM who has not entered gets the unresolved mark rather than a
 * guess. `entered` is the claim COUNT the read model publishes, and is the
 * em dash where a demo row has no occurrence to count.
 *
 * @param {object} pool a slate row, or an illustrative fixture row
 * @returns {string}
 */
function poolOpenCard(pool) {
  // THE BADGE IS THE POOL'S OWN STATE, and every word of it is served. A drawn
  // slot is OPEN while the read model says claims are accepted and LOCKED once
  // the governed window has closed; the illustrative fixture carries its own
  // state string and keeps it.
  const badge = pool.openForClaims === undefined
    ? 'PREGAME'
    : (pool.openForClaims ? 'OPEN' : 'LOCKED');

  const figures = [
    { label: 'Buy-in', value: formatCredits(pool.entryCents),
      exactCents: pool.entryCents },
    { label: 'Entered', value: pool.entered === undefined
      ? PENDING_FIGURE : String(pool.entered) },
    { label: 'Pot', value: formatCredits(pool.potCents),
      exactCents: pool.potCents,
      // A CARRIED POT KEEPS ITS GOLD, which is how a rollover is marked without
      // a gold card. `is-carried` is the same modifier the Play Prop Pool card
      // and the retired Wrap Up row both used, so one Pool that carried is
      // marked one way wherever a GM meets it — and it is a MODIFIER on a
      // subject type, never a third type.
      tone: pool.continuation || pool.rolledForward ? 'carried' : '' },
  ];

  // WHOSE SIDE THIS GM IS ON, WHERE THE SETTLED CARD PUTS THE WINNER. A pool a
  // GM has not entered says so; it does not draw an empty slot.
  const picked = (pool.subjects || []).find(
    (s) => s.subject_id === pool.mySubjectId);
  const mine = picked ? picked.label
    : (pool.mySubjectId ? PENDING_FIGURE : 'Not entered');

  return resultCard({
    identity: pool.name,
    badge,
    badgeTone: 'neutral',
    // THE SCOPE AND THE QUESTION, in the slot the settled card gives the pick.
    // `poolBadge` is the same TEAM / MATCHUP / ROLLOVER word the Play card
    // carries, so a GM meets one vocabulary for one Pool on both surfaces.
    context: `${poolBadge(pool)} · ${poolQuestion(pool)}`,
    figures,
    footLabel: 'Your pick',
    footValue: mine,
    tapAction: 'pool',
    tapId: String(pool.catalogNumber),
  });
}

/**
 * The week's Pools.
 *
 * WHICH POOLS A WEEK HAS IS THE SLATE'S ANSWER, not this module's. In demo
 * mode the POR's four illustrative Pools are drawn so the cards stay
 * reviewable in isolation; in production the authoritative slate is drawn, and
 * when no slate has been drawn the row says so rather than inventing four.
 *
 * The Rev1.3 selector requires four definitions passing BOTH gates, and gate 2
 * is a per-league, per-provider source measurement that is unsatisfied without
 * provider access. An undrawn week is therefore ordinary, not a fault — and
 * falling back to the launch cards would present a retired fixed set as this
 * week's governed draw.
 */
/* ── FINAL POR §7 · THE GM'S OWN ITEM LEADS EVERY RAIL ──────────────────────
 *
 * A Wrap Up is read by somebody asking "how did I do". Their own matchup, their
 * own wager and their own Pool are the answer, and on a one-card carousel an
 * item that is not first is an item most readers never reach. So each rail is
 * ordered mine-first and league-activity-after.
 *
 * STABLE, NOT SORTED. `filter` twice preserves the server's order inside both
 * groups, so the league's own sequence is untouched and only the reader's item
 * is lifted. A GM with no item in a rail sees exactly what they saw before. */
function mineFirst(items, isMine) {
  const mine = items.filter(isMine);
  if (!mine.length) return items;
  return [...mine, ...items.filter((item) => !isMine(item))];
}

/* THE SLATE FOR THE WEEK ON SCREEN — Final POR §6.
 *
 * Two slates are bound: the current week's and the one before it. Wrap Up can
 * be showing either, so it asks for the one that matches the week it is
 * drawing rather than always taking the current one — which is what made a
 * completed week render this week's still-open Pools. */
function slateRowsForActiveWeek() {
  const now = currentWeek();
  if (now !== null && activeWeek() === now - 1) {
    const previous = previousSlateRows();
    if (previous && previous.length) return previous;
  }
  return slateRows();
}

function poolsModule() {
  const mode = slateMode();
  const pools = mode === SLATE_MODE_DEMO
    ? weekPools(activeWeek()) : slateRowsForActiveWeek();

  if (mode === SLATE_MODE_UNDRAWN || mode === 'unavailable') {
    const reason = mode === SLATE_MODE_UNDRAWN
      ? 'No Prop Pool slate has been drawn for this week yet. Four definitions must '
        + 'pass both catalog gates before a week can be drawn, and the '
        + 'league’s provider source readiness is not yet confirmed.'
      : 'This week’s Prop Pool slate could not be read for this session.';
    return resultSection({
      title: 'FANTASYSTAKES PROP POOLS · SCROLL',
      id: 'pools',
      state: mode,
      items: [],
      empty: note(reason, { pending: true }),
    });
  }

  // UIRECON WAVE 4B — A CAROUSEL, LIKE ITS TWO PEERS.
  //
  // This was a flat column of `.fs-poolrow` buttons while the two sections
  // above it were carousels — three things a GM reads the same way, built three
  // ways.
  //
  // RC4 — AND NOW ONE CARD FAMILY, LIKE ITS TWO PEERS. Wave 4B unified the
  // rail and left the ITEM split: a settled Pool drew the shared result card
  // and an open one kept its 45px row. At Week 11 every Pool on the slate is
  // open, so the section drew four rows and measured 45px beside 132.30px and
  // 150.06px of carousel. Both states take the shared shell now; what differs
  // is what they say inside it.
  return resultSection({
    title: 'FANTASYSTAKES PROP POOLS · SCROLL',
    id: 'pools',
    state: mode,
    items: mineFirst(pools, (pool) => (
      pool.mySubjectId != null || pool.myResult === 'won' || pool.myResult === 'lost'
    )).map((pool) => (
      pool.settled ? poolResultCard(pool) : poolOpenCard(pool))),
    empty: '',
  });
}

/* ── Panel ──────────────────────────────────────────────────────────────────*/

/**
 * @returns {string}
 */
/** Team display name from the frozen championship rows already served. */
function weekTeamName(teamId) {
  const results = championshipResults();
  const rows = (results && results.fantasystakes_podium) || [];
  const hit = rows.find((r) => Number(r.team_id) === Number(teamId));
  return hit ? (hit.team_name || `Team ${teamId}`) : `Team ${teamId}`;
}


export function buildWeekPanel() {
  const composer = new PanelComposer('week');

  composer.add(weekSwitch());
  // No strip, and therefore no Credits disclaimer. Both follow from the locked
  // Rev 4.2 Final POR, not from the work being unfinished.
  //
  // THE SKUNK CALLOUT IS NOT A FOURTH MODULE, and that is structural rather
  // than cosmetic. This file's own header records that the POR fixes the set at
  // three and gives it "no mechanism for a fourth"; the certification asserts
  // the three by name. The week's Skunk is a RESULT ANNOUNCEMENT, not a
  // dashboard module — it has no rail, no carousel and nothing to tap — so it
  // leads the scroll as a callout above the three, where the week's headline
  // belongs, and the locked module set is untouched.
  // SEASON RESULTS LEAD WRAP UP ONCE THE SEASON IS DECIDED, and only then. The
  // block returns '' for every lifecycle before FINAL, so the weekly modules
  // below are untouched during the season — the locked three-module set is not
  // extended, it is preceded by the season's own headline once there is one.
  composer.add(seasonResultsSection(championshipResults(), weekTeamName));

  // ── THE THREE MODULES ARE ONE DECK — RC4 MOBILE RECONCILIATION ───────────
  //
  // WAVE 4B MADE THEM ONE CONSTRUCTION AND LEFT THEM THREE SIZES. Each rail
  // took its height from its own tallest card, which is what a horizontal rail
  // does and what that wave explicitly wanted — "each takes what its content
  // needs". Measured on the deployed RC4 build at 390x844 that produced
  // 132.30px of Yahoo, 150.06px of FantasyStakes Matchup and 45px of Prop Pool:
  // three peer sections a GM reads the same way, drawn at three sizes.
  //
  // `.fs-wkdeck` PUTS THE THREE RAILS ON A MATCHED SET OF GRID TRACKS, so the
  // three result-card families measure identically by construction rather than
  // by agreement. Nothing about the sections themselves changes — same builder,
  // same rail, same item wrapper, same headings, same order, same separators.
  // See `gameplay.css` — "PARALLEL CARD GEOMETRY".
  //
  // THE SKUNK CALLOUT STAYS OUTSIDE IT. It is a result announcement rather than
  // a module — no rail, no carousel, nothing to tap — so it leads the scroll
  // and is not one of the three tracks.
  composer.add(
    '<div class="fs-wkscroll">' +
    skunkCallout() +
    '<div class="fs-wkdeck">' +
    yahooModule() +
    betsModule() +
    poolsModule() +
    '</div>' +
    '</div>',
  );

  // WP3D — THE DENSEST YAHOO SURFACE IN THE PRODUCT. Wrap Up draws the
  // provider's own matchups, their scores and their finality, under the
  // provider's week. It also draws FantasyStakes results beside them, which is
  // exactly why the attribution is a page-footer source disclosure rather than
  // a caption on any block.
  composer.add(attributionFooter());

  return composer.toHTML();
}

/**
 * Decimal places that honour the authoritative values and invent none.
 *
 * FantasyStakes scores are fractional and the margin is the product's headline
 * number, so rounding 30.64 to 31 would throw away the fact the callout exists
 * to state. Equally, printing 110.5 as 110.50 would claim a precision the
 * provider did not report.
 *
 * The trio is drawn to the WIDEST precision any of the three actually carries,
 * capped at two: that keeps the three numbers reading as one set while never
 * adding a digit the source did not have.
 *
 * @param {number[]} values
 * @returns {number} 0, 1 or 2
 */
function scorePrecision(values) {
  let places = 0;
  for (const value of values) {
    if (!Number.isFinite(value)) continue;
    // Two decimal places is the scoring grain; anything below it is float
    // noise from the subtraction, not reported precision.
    const rounded = Math.round(value * 100) / 100;
    if (Math.round(rounded * 100) % 10 !== 0) return 2;
    if (Math.round(rounded * 10) % 10 !== 0) places = Math.max(places, 1);
  }
  return places;
}

/**
 * SKUNK OF THE WEEK — the week's headline result.
 *
 * Drawn ONLY when the server says a GM was skunked. Every other state draws
 * nothing: an unassessed week (Week Close has not run), a tied week, an
 * unavailable read, and demo. None of them has a result to announce, and a
 * placeholder saying so would put the word "Skunk" beside a league that has not
 * had one.
 *
 * THE MARGIN IS THE KEY NUMBER and takes the strongest treatment on the card —
 * larger than the final score, which sits under it as the supporting detail.
 * That hierarchy is the ruling's, not a styling preference.
 *
 * @returns {string}
 */
export function skunkCallout() {
  const skunk = skunkOfTheWeek();
  if (!skunk) return '';

  // THE RESULT MUST BELONG TO THE WEEK ON SCREEN. The week switch re-renders
  // this panel, and a result bound for week 5 drawn under week 4's heading
  // would attribute a real GM's worst loss to a week they did not have it in.
  const bound = skunkWeek();
  if (bound !== null && bound !== activeWeek()) return '';

  const places = scorePrecision([skunk.margin, skunk.score, skunk.opponentScore]);
  const fmt = (n) => n.toFixed(places);

  return (
    '<section class="fs-skunk" data-module-aside="skunk" ' +
    `data-skunk-week="${escapeHtml(String(skunk.week))}">` +
    '<div class="fs-skunk__eyebrow">SKUNK OF THE WEEK</div>' +
    '<div class="fs-skunk__line" data-skunk-line>' +
    `<span class="fs-skunk__loser">${escapeHtml(skunk.teamName)}</span>` +
    ' got skunked by ' +
    `<span class="fs-skunk__winner">${escapeHtml(skunk.opponentName)}</span>` +
    '</div>' +
    '<div class="fs-skunk__margin" data-skunk-margin>' +
    `<span class="fs-skunk__marginvalue">${escapeHtml(fmt(skunk.margin))}</span>` +
    '<span class="fs-skunk__marginlabel">point margin</span>' +
    '</div>' +
    '<div class="fs-skunk__final" data-skunk-final>' +
    `Final: ${escapeHtml(fmt(skunk.opponentScore))}–${escapeHtml(fmt(skunk.score))}` +
    '</div>' +
    '<div class="fs-skunk__fee fs-money" data-skunk-fee ' +
    `data-exact-cents="${skunk.cents}">` +
    `${escapeHtml(formatCredits(skunk.cents))} Skunk</div>` +
    (skunk.tied
      // An exact-margin tie splits the ONE weekly contribution rather than
      // charging each GM in full. Said plainly, because the fee shown on this
      // card is then a share and a reader would otherwise assume it was the
      // whole $10.
      ? `<div class="fs-skunk__note">${skunk.tiedCount} GMs tied on the same ` +
        'margin — the week’s single Skunk is split between them.</div>'
      : '') +
    '</section>'
  );
}

/**
 * Wire the week switch and the three modules' tap paths.
 *
 * The switch re-renders the panel in place and re-binds it, so the whole tab
 * follows the selected week from one source rather than each module tracking
 * its own idea of which week it is showing.
 *
 * @param {HTMLElement} panel
 * @param {{openSheet: Function}} api
 */
export function bindWeek(panel, api) {
  panel.querySelectorAll('[data-week]').forEach((el) => {
    el.addEventListener('click', () => {
      selectWeek(Number(el.dataset.week));
      panel.innerHTML = buildWeekPanel();
      bindWeek(panel, api);
    });
  });

  // THE FIXTURE LOOKUPS ARE DEMO-ONLY. `yahooMatchups` and `weekBets` know
  // only the fixture's two weeks and THROW for any other — so a production
  // league in week 9 took down the whole panel build, and with it every panel
  // after it in the mount order. In production the cards are bound from the
  // served models, and these lookups must not run at all.
  const demo = leagueMode() === LEAGUE_MODE_DEMO;

  const matchups = demo ? yahooMatchups(activeWeek()) : [];
  panel.querySelectorAll('[data-card-action="yahoo"]').forEach((el) => {
    onActivate(el, () => {
      const m = matchups.find((x) => x.id === el.dataset.cardId);
      if (m) api.openSheet(previewSheet(m));
    });
  });

  // UI-5 GAP 1 -- the provider-backed cards, bound from the SERVED rows.
  // Deliberately separate from the `yahoo` binding above: that one looks the
  // matchup up in the demo fixture, which knows only two weeks and THROWS for
  // any other, and a production league in week 9 must never reach it.
  const providerRows = demo ? [] : (weekMatchups(activeWeek()) || []);
  panel.querySelectorAll('[data-card-action="provider"]').forEach((el) => {
    onActivate(el, () => {
      const m = providerRows.find(
        (x) => `provider-${x.matchupId}` === el.dataset.cardId);
      if (m) api.openSheet(providerMatchupSheet(m));
    });
  });

  const bets = actionMode() === 'demo'
    ? weekBets(activeWeek())
    : SECTIONS.flatMap((section) => sectionCards(section));
  panel.querySelectorAll('[data-card-action="wager-recap"]').forEach((el) => {
    onActivate(el, () => {
      const card = bets.find((c) => c.id === el.dataset.cardId);
      if (card) api.openSheet(matchupRecapSheet(card));
    });
  });

  // ONE OPENER FOR EVERY POOL PRESENTATION. Wave 4B bound two, because an open
  // Pool drew `.fs-poolrow[data-pool]` and a settled one drew the shared result
  // card. RC4 gives both states the shared card, so `data-card-action="pool"`
  // is the only path a Pool is reached by now — and the `[data-pool]` binding
  // is kept because Play's Prop Pool card still uses that attribute and this
  // panel must not become the reason a surface is silently inert.
  // FINAL POR §6 — THE SLATE THE CARDS WERE DRAWN FROM, NOT THIS WEEK'S.
  //
  // This looked the tapped Pool up in the CURRENT week's slate while the rail
  // above it was drawing the COMPLETED week's. On a week where the two slates
  // hold different catalog numbers the lookup simply missed, so a settled Pool
  // card was inert: nothing opened, and any sheet already on screen stayed
  // there — which reads as "the Pool detail is wrong" rather than "no detail
  // opened". It asks the same helper the rail does.
  const pools = slateMode() === SLATE_MODE_DEMO
    ? weekPools(activeWeek()) : slateRowsForActiveWeek();
  const openPool = (id) => {
    const pool = pools.find((p) => String(p.catalogNumber) === String(id));
    if (pool) api.openSheet(poolRecapSheet(pool));
  };
  panel.querySelectorAll('[data-pool]').forEach((el) => {
    el.addEventListener('click', () => openPool(el.dataset.pool));
  });
  panel.querySelectorAll('[data-card-action="pool"]').forEach((el) => {
    onActivate(el, () => openPool(el.dataset.cardId));
  });
}

/* ══ THE THREE RESULT SECTIONS — UIRECON Wave 4B ═══════════════════════════
 *
 * ONE SECTION BUILDER, ONE CARD SHELL, THREE KINDS OF RESULT.
 *
 * Wrap Up carried three modules built three ways: Yahoo was a `.fs-vcar`
 * carousel, FantasyStakes wagers were the same carousel at a different fixed
 * height, and Prop Pools were not a carousel at all — a flat list of
 * `.fs-poolrow` buttons. Three headings, three geometries, three viewport
 * behaviours, for three things a GM reads the same way: what happened.
 *
 * `resultSection()` below is the only thing that draws a heading and a viewport
 * on this tab now, so "same heading treatment, same heading-to-carousel gap,
 * same carousel width, same swipe behaviour" is a fact about one function
 * rather than a promise repeated in three places.
 *
 * ── WHY THE CAROUSEL TURNED SIDEWAYS ────────────────────────────────────────
 *
 * The old one scrolled VERTICALLY inside a fixed `max-height`, with a
 * deliberate peek at the next card's header — a height tuned against Rev 4.2
 * card sizes. Rev 4.3 grew the cards and the peek became half a card, which is
 * the "1.5 cards" defect the POR names.
 *
 * Re-tuning the pixel value is how it went stale the first time. A horizontal
 * scroll-snap rail whose items are each exactly 100% of the viewport cannot
 * show a partial next card at any card height, at any width, ever: one item
 * fills the viewport by construction and `scroll-snap-stop: always` parks on
 * the next one. The viewport's height is then the card's, so the three sections
 * take the space their content needs and share the tab between them.
 *
 * ── WHAT REV 1.4 FINISHED ───────────────────────────────────────────────────
 *
 * Wave 4B made the three sections one construction and stopped at the item
 * wrapper. Inside it, the Pools section still drew `.fs-poolrow` with an outer
 * box of its own — a smaller corner, a thinner left edge — so three rails that
 * measured identically held two visibly different components. The shell is a
 * single stylesheet rule now (`ledger.css`, `.fs-rescar__item > .fs-wcard,
 * .fs-rescar__item > .fs-poolrow`), which is why THIS file still hands the rail
 * whichever presentation the row deserves and does not have to choose one:
 * outer geometry is no longer a property of which presentation was chosen.
 *
 * The gold left edge a finished wager carried came off with it. On Play it
 * says "this one has stopped moving", which distinguishes a card from its
 * neighbours; on Wrap Up every card has stopped moving, so it distinguished
 * nothing and read as decoration beside a badge already saying WON.
 */

/**
 * One result section: heading, then a bounded one-card carousel.
 *
 * @param {{title: string, id: string, items: string[], empty?: string}} spec
 * @returns {string}
 */
function resultSection(spec) {
  const { title, id, items, empty = '', state = '' } = spec;
  const hasItems = Array.isArray(items) && items.length > 0;

  // WP5 — `role="list"` ONLY WHEN THE SECTION HOLDS LISTITEMS. An empty or
  // unavailable section draws an explanatory paragraph instead of cards, and a
  // `<p>` inside `role="list"` is an ARIA violation.
  // AN EMPTY SECTION STILL TAKES THE ITEM WRAPPER. The rail is a flex row, and
  // a bare paragraph inside it is a shrinkable flex item — it would render
  // narrower than the cards its peers show, so the three sections would present
  // three widths on the one week where one of them has nothing. The wrapper
  // pins it to the same one-viewport width, WITHOUT `role="listitem"`, which
  // belongs only to actual list entries.
  const body = hasItems
    ? items.map((item) => (
      `<div class="fs-rescar__item" role="listitem">${item}</div>`
    )).join('')
    : (empty ? `<div class="fs-rescar__item">${empty}</div>` : '');

  // `data-state` IS THE SECTION'S OWN ANSWER TO "WHY DOES IT LOOK LIKE THIS".
  // The Pools module has carried it since the slate became authoritative —
  // drawn, undrawn, unavailable — and it is how a reader (and P4B-3's
  // acceptance suite) tells "this week has no Pools" apart from "this week's
  // Pools could not be read". A section with nothing to distinguish states
  // passes none rather than being given an empty one.
  return (
    `<section class="fs-wkmod" data-module="${escapeHtml(id)}"` +
    `${state ? ` data-state="${escapeHtml(state)}"` : ''}>` +
    sectionHeading(title.replace(/ · SCROLL$/, ''), `${items.length} · SCROLL`) +
    `<div class="fs-rescar" id="fs-${escapeHtml(id)}-carousel"` +
    `${hasItems ? ' role="list"' : ''}>${body}</div>` +
    '</section>'
  );
}

/**
 * The shared result-card shell.
 *
 * SAME SHELL, DIFFERENT DATA — which is the whole of §11. Outer box, heading
 * row, status placement, figure area and footer are this function's; what goes
 * in each slot is the caller's. A result type that has no footer meta passes
 * none rather than being given an empty one to fill.
 *
 * `figures` IS A LIST, NOT A FIXED SET, because the three result kinds
 * genuinely carry different counts — a wager has a stake and a credit outcome,
 * a Prop Pool has a pot and a return, a Yahoo fixture has neither. Forcing a
 * shape onto a type that does not have it is the failure §11 warns against.
 *
 * @param {{identity: string, badge?: string, badgeTone?: string,
 *          context?: string, figures?: Array<{label: string, value: string,
 *          tone?: string, exactCents?: number}>, footLabel?: string,
 *          footValue?: string, accent?: string, tapAction?: string,
 *          tapId?: string}} spec
 * @returns {string}
 */
function resultCard(spec) {
  return wagerCard({
    identity: spec.identity,
    badge: spec.badge || '',
    badgeTone: spec.badgeTone || '',
    context: spec.context || '',
    // FINAL POR (freeze) §6 — the one-line takeaway a full recap card carries.
    // `resultCard` forwarded every other field and silently dropped this one,
    // so the FantasyStakes and Prop Pool cards were built with a read and drew
    // without it while the Yahoo card — which calls `wagerCard` directly — did.
    copy: spec.copy || '',
    figures: spec.figures || [],
    footLabel: spec.footLabel || '',
    footValue: spec.footValue || '',
    accent: spec.accent || '',
    tapAction: spec.tapAction || '',
    tapId: spec.tapId || '',
    className: 'fs-wcard--result',
  });
}

/** The five words a settled wager may report, and the tone each carries. */
const OUTCOME_WORDS = Object.freeze({
  won: { word: 'WON', tone: 'positive', accent: 'done' },
  lost: { word: 'LOST', tone: 'negative', accent: 'waiting' },
  push: { word: 'PUSH', tone: 'neutral', accent: 'waiting' },
  void: { word: 'VOID', tone: 'neutral', accent: 'waiting' },
});

/**
 * One settled FantasyStakes Matchup, from the Action read model.
 *
 * NOTHING IS SETTLED HERE. `outcome` is `bets.status` carried through the read
 * model verbatim, and `netCents` is the net the read model computed from the
 * same row. The card reports both; it decides neither.
 *
 * @param {object} card an action card
 * @returns {string}
 */
function matchupResultCard(card) {
  const outcome = OUTCOME_WORDS[card.outcome]
    // A settled wager whose row carries a status this product does not name is
    // reported as settled without a word put in its mouth.
    || { word: 'SETTLED', tone: 'neutral', accent: 'done' };

  const figures = [
    { label: 'Stake', value: formatCredits(card.yourStakeCents),
      exactCents: card.yourStakeCents },
  ];
  // §6B — THE POT BELONGS ON THE CARD. Stake and net without it leaves a reader
  // unable to see what the wager was actually for.
  if (Number.isInteger(card.potCents)) {
    figures.push({ label: 'Pot', value: formatCredits(card.potCents),
      exactCents: card.potCents });
  }
  if (Number.isInteger(card.netCents)) {
    figures.push({
      label: 'Credits',
      value: formatSignedCredits(card.netCents),
      exactCents: card.netCents,
      tone: card.netCents > 0 ? 'positive' : (card.netCents < 0 ? 'negative' : ''),
    });
  }

  const line = card.line != null && card.line !== '' ? ` ${card.line}` : '';
  return resultCard({
    identity: card.opponent,
    badge: outcome.word,
    badgeTone: outcome.tone,
    accent: outcome.accent,
    context: `${card.marketLabel}${line}${card.mode ? ` · ${modeWord(card)}` : ''}`,
    // §6B — the sportsbook read, one line: the fantasy result and how it sat
    // against the locked number. Two sentences, because the cover is the half
    // a market reader is actually asking about.
    copy: takeaway(wagerRead(card, actingMatchup(activeWeek())), 2),
    figures,
    footLabel: card.week || '',
    tapAction: 'wager-recap',
    tapId: card.id,
  });
}

function poolRecapSheet(pool) {
  const picked = (pool.subjects || []).find((s) => s.subject_id === pool.mySubjectId);
  const pickLabel = picked ? picked.label : 'Not entered';

  const state = pool.settled ? 'Resolved'
    : (pool.openForClaims ? 'Open' : 'Locked');

  const outcome = (() => {
    if (!pool.settled) return `Week ${activeWeek()} · ${state}`;
    const word = String(pool.myResult || 'settled').replace('_', ' ').toUpperCase();
    return `Week ${activeWeek()} · Final · ${word}`;
  })();

  const rows =
    detailRow('Your pick', pickLabel)
    + (Number.isInteger(pool.entryCents)
      ? detailRow('Buy-in', formatCredits(pool.entryCents), 'fs-money') : '')
    + detailRow('Pot', formatCredits(pool.potCents), 'fs-money')
    + detailRow('State', state)
    + (pool.settled
      ? detailRow('Result',
        String(pool.myResult || 'Settled').replace('_', ' ')) : '')
    + (pool.settled && Number.isInteger(pool.myNetCents)
      ? detailRow('Net', formatSignedCredits(pool.myNetCents), 'fs-money') : '');

  return {
    title: pool.name,
    sub: outcome,
    body:
      renderRead(poolRead(pool, pickLabel), detailSection, detailNote)
      + detailSection('POOL REVIEW', rows)
      + detailSection('FANTASY FOOTBALL DRIVERS',
        // 8 - THE QUESTION, NEVER THE NOTATION. `pool.rule` is the governed
        // definition and reads as an internal formula; the Pool's own question
        // is the football statement of the same thing, and it is what a GM
        // came here to read.
        // ONE AUTHOR FOR THE QUESTION, AND IT IS THE CATALOG. `poolQuestion`
        // returns the served sentence or the integrity mark and composes
        // nothing in between; reading `pool.question` directly here would be a
        // second author for the same sentence, which is what that reader
        // exists to prevent.
        detailNote(poolQuestion(pool))
        + detailNote('Measured across the named fantasy-football results and '
          + 'evaluated once, at settlement.'))
      + detailNote('Review only. Pool choices are made on Play.'),
  };
}

/** Read-only recap for both settled and still-open selected-week wagers. */
function matchupRecapCard(card) {
  if (card.settled) {
    return matchupResultCard(card);
  }
  const line = card.line != null && card.line !== '' ? ` ${card.line}` : '';
  return resultCard({
    identity: card.opponent,
    badge: card.protocolState === 'accepted' ? 'LIVE' : 'PENDING',
    badgeTone: 'neutral',
    context: `${card.marketLabel}${line}${card.mode ? ` · ${modeWord(card)}` : ''}`,
    figures: [
      { label: 'Stake', value: formatCredits(card.yourStakeCents), exactCents: card.yourStakeCents },
      ...(Number.isInteger(card.potCents)
        ? [{ label: 'Pot', value: formatCredits(card.potCents), exactCents: card.potCents }]
        : []),
    ],
    footLabel: card.week || `WK ${activeWeek()}`,
    footValue: 'Read-only',
    tapAction: 'wager-recap',
    tapId: card.id,
  });
}

function matchupRecapSheet(card) {
  // 9B - the fantasy result the market was priced against. Real, served data:
  // the acting GM's own provider matchup for the week this wager belongs to.
  const matchup = actingMatchup(activeWeek());

  const settledOutcome = (() => {
    if (!card.settled) return `Week ${activeWeek()} · read-only review`;
    if (!Number.isInteger(card.netCents)) return `Week ${activeWeek()} · Final`;
    return `Week ${activeWeek()} · Final · ${card.netCents > 0 ? 'WON' : 'LOST'} `
      + `${formatSignedCredits(card.netCents)}`;
  })();

  const marketRows =
    detailRow('Market', `${card.marketLabel || 'Matchup'} ${card.line || ''}`.trim())
    + detailRow('Terms', String(card.mode || 'locked').toUpperCase())
    + detailRow('Your stake', formatCredits(card.yourStakeCents), 'fs-money')
    + (Number.isInteger(card.potCents)
      ? detailRow('Pot', formatCredits(card.potCents), 'fs-money') : '')
    + (card.settled && Number.isInteger(card.netCents)
      ? detailRow('Net', formatSignedCredits(card.netCents), 'fs-money') : '');

  return {
    title: `vs ${card.opponent}`,
    sub: settledOutcome,
    body:
      renderRead(wagerRead(card, matchup), detailSection, detailNote)
      + detailSection('MARKET REVIEW', marketRows)
      + detailSection('FANTASY FOOTBALL DRIVERS',
        detailNote(card.copy
          || 'The selected-week fantasy matchup and market terms provide the '
             + 'review context.'))
      + detailNote('Review only. Manage current FantasyStakes activity on Status.'),
  };
}

/** LOCKED / DYNAMIC as one word, for the card's context line. */
function modeWord(card) {
  return card.mode === 'dynamic' ? 'Dynamic' : 'Locked';
}

/** What a settled Prop Pool did for this GM, in one word. */
const POOL_RESULT_WORDS = Object.freeze({
  won: { word: 'WON', tone: 'positive', accent: 'done' },
  lost: { word: 'LOST', tone: 'negative', accent: 'waiting' },
  no_result: { word: 'NO WINNER', tone: 'neutral', accent: 'waiting' },
  not_entered: { word: 'NOT ENTERED', tone: 'neutral', accent: 'waiting' },
});

/**
 * One settled Prop Pool, from the slate's settled view.
 *
 * THE WINNING SUBJECT IS THE SERVER'S. `pool_result_view` derives it from the
 * winner-distribution posting and the claims it paid — the surface neither
 * evaluates the pool nor divides the pot, and an empty winner list means
 * nobody picked one, which the card says rather than hides.
 *
 * @param {object} pool a slate row
 * @returns {string}
 */
function poolResultCard(pool) {
  const result = POOL_RESULT_WORDS[pool.myResult]
    || { word: 'SETTLED', tone: 'neutral', accent: 'done' };

  // §6C — BUY-IN BESIDE THE POT. What it cost to be in it is half of what a
  // settled pool result means, and the card carried only the other half.
  const figures = [
    ...(Number.isInteger(pool.entryCents)
      ? [{ label: 'Buy-in', value: formatCredits(pool.entryCents),
          exactCents: pool.entryCents }]
      : []),
    { label: 'Pot', value: formatCredits(pool.potCents),
      exactCents: pool.potCents },
    { label: 'Entered', value: pool.entered === undefined
      ? PENDING_FIGURE : String(pool.entered) },
  ];
  if (pool.myResult === 'won' || pool.myReturnCents) {
    figures.push({
      label: 'Credits', value: formatSignedCredits(pool.myReturnCents),
      exactCents: pool.myReturnCents,
      tone: pool.myReturnCents > 0 ? 'positive' : '',
    });
  }

  // THE PICK'S LABEL COMES FROM THE SERVED SUBJECT LIST — the same labels the
  // pick control offered — so the answer is read back in the words the question
  // was asked in. A claim whose subject is no longer in the served list falls
  // back to the unresolved mark rather than to an id a GM cannot read.
  const picked = (pool.subjects || []).find(
    (s) => s.subject_id === pool.mySubjectId);
  const mine = picked ? picked.label : PENDING_FIGURE;
  const won = pool.winningSubjects && pool.winningSubjects.length
    ? pool.winningSubjects.join(', ')
    : 'No entry qualified';

  return resultCard({
    identity: pool.name,
    badge: result.word,
    badgeTone: result.tone,
    accent: result.accent,
    context: `Your pick: ${mine}`,
    // §6C — why it landed the way it did, in one line.
    copy: takeaway(poolRead(pool, mine)),
    figures,
    footLabel: 'Winner',
    footValue: won,
    tapAction: 'pool',
    tapId: String(pool.catalogNumber),
  });
}
