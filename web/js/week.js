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

import { PanelComposer, escapeHtml, note, sectionHeading } from './components.js';
import { formatCredits } from './credits.js';
import { CURRENT_WEEK, PAST_WEEK, WEEKS, weekBets, weekPools, yahooMatchups } from './data/week-data.js';
import {
  LEAGUE_MODE_DEMO, LEAGUE_MODE_UNAVAILABLE, currentWeek, leagueMode,
  weekMatchups,
} from './league-model.js';
import {
  ACTION_MODE_UNAVAILABLE, SECTIONS, actionMode, sectionCards,
} from './action-model.js';
import { poolBadge } from './data/league-data.js';
import {
  SLATE_MODE_DEMO,
  SLATE_MODE_DRAWN,
  SLATE_MODE_UNDRAWN,
  slateMode,
  slateRows,
} from './pool-slate-model.js';
import { lifecycleCard, wagerSheet } from './action.js';
import { poolSheet } from './league.js';
import { previewSheet } from './preview.js';
import { matchupMarketCells, wagerCard } from './wagercard.js';
import { onActivate } from './interaction.js';

/** Locked Rev 4.2 subtitle. */
export const WEEK_SUBTITLE = 'Official Yahoo matchups + FantasyStakes action';

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
export const BETS_HEADING = 'FANTASYSTAKES BETS · 4 SHOWN · SWIPE ↕';

/** The viewport cap the heading states. */
export const BETS_SHOWN = 4;

/** Which week the tab is showing. The current week is the opening state. */
let selectedWeek = CURRENT_WEEK;

/** @returns {number} */
export function currentSelectedWeek() {
  return selectedWeek;
}

/**
 * @param {number} week
 * @returns {number}
 */
export function selectWeek(week) {
  if (!WEEKS.includes(week)) throw new Error(`week ${week} is not on the switch`);
  selectedWeek = week;
  return selectedWeek;
}

/** Restore the opening state — used by the suites. */
export function resetWeek() {
  selectedWeek = CURRENT_WEEK;
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
    const selected = selectedWeek === week;
    return (
      `<button type="button" class="fs-wkswitch__opt${selected ? ' is-selected' : ''}" ` +
      `data-week="${week}" aria-pressed="${selected}">WEEK ${week}</button>`
    );
  };

  return (
    '<div class="fs-wkhead">' +
    '<div class="fs-wkswitch" role="group" aria-label="Week">' +
    control(PAST_WEEK) +
    '<span class="fs-wkswitch__mid">REGULAR SEASON</span>' +
    control(CURRENT_WEEK) +
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

  return (
    '<section class="fs-wkmod" data-module="yahoo">' +
    sectionHeading('YAHOO LEAGUE MATCHUPS · SWIPE ↕') +
    `<div class="fs-vcar" id="fs-yahoo-carousel" role="list">${body}</div>` +
    '</section>'
  );
}

function demoMatchupBody() {
  return yahooMatchups(selectedWeek)
    .map((m) => `<div class="fs-vcar__item" role="listitem">${yahooCard(m)}</div>`)
    .join('');
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
    return weekNote('unavailable',
      'Your league’s matchups could not be loaded.');
  }
  if (currentWeek() === null) {
    return weekNote('no-week',
      'No fantasy week has been published for this league yet.');
  }
  const rows = weekMatchups(selectedWeek);
  if (rows === null) {
    return weekNote('not-read',
      `Week ${selectedWeek} has not been loaded.`);
  }
  if (!rows.length) {
    return weekNote('empty',
      `No matchups have been published for week ${selectedWeek}.`);
  }
  return rows
    .map((m) => `<div class="fs-vcar__item" role="listitem">`
      + `${providerMatchupCard(m)}</div>`)
    .join('');
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

  const figures = m.final
    ? [{ label: 'Final',
         value: `${score(m.home)} — ${score(m.away)}` }]
    : [{ label: 'Live',
         value: `${score(m.home)} — ${score(m.away)}` }];

  const winner = m.winnerTeamId === m.home.teamId ? m.home.name
    : (m.winnerTeamId === m.away.teamId ? m.away.name : null);

  return wagerCard({
    identity: `${m.home.name} vs ${m.away.name}`,
    context: m.involvesActingTeam ? `You are ${m.actingSide}` : '',
    markets: null,
    interactiveMarkets: false,
    figures,
    badge: 'YAHOO',
    badgeTone: m.involvesActingTeam ? 'gold' : 'neutral',
    accent: m.final ? 'done' : '',
    footLabel: m.final
      ? (winner ? `FINAL · ${winner} won` : 'FINAL')
      : 'IN PROGRESS',
    footValue: '',
    tapAction: '',
    tapId: `provider-${m.matchupId}`,
    className: 'fs-wcard--yahoo',
  });
}

/* ── Module 2 · FantasyStakes bets ──────────────────────────────────────────*/

function betsModule() {
  // At most four, because that is what the locked heading says this module
  // presents. A week holding fewer real wagers draws fewer cards — the shortfall
  // is never made up by inventing a wager that no protocol record supports.
  const production = actionMode() !== 'demo';
  const body = production ? versusBody() : demoBetsBody();

  return (
    '<section class="fs-wkmod" data-module="bets">' +
    sectionHeading(BETS_HEADING) +
    `<div class="fs-vcar is-compact" id="fs-week-bets" role="list">${body}</div>` +
    '</section>'
  );
}

function demoBetsBody() {
  return weekBets(selectedWeek).slice(0, BETS_SHOWN)
    .map((card) => (
      `<div class="fs-vcar__item is-compact" role="listitem">${lifecycleCard(card)}</div>`
    ))
    .join('');
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
    return weekNote('unavailable', 'Your wagers could not be loaded.');
  }
  const rows = SECTIONS
    .flatMap((section) => sectionCards(section))
    .filter((card) => card.week === `WK ${selectedWeek}`)
    .slice(0, BETS_SHOWN);

  if (!rows.length) {
    return weekNote('empty', `No wagers for week ${selectedWeek}.`);
  }
  return rows
    .map((card) => (
      `<div class="fs-vcar__item is-compact" role="listitem">${lifecycleCard(card)}</div>`
    ))
    .join('');
}

/* ── Module 3 · FantasyStakes Pools ─────────────────────────────────────────*/

function poolRow(pool) {
  const badge = poolBadge(pool);
  const badgeClass = pool.scope === 'TEAM' ? 'is-team' : 'is-matchup';
  const rolling = pool.continuation || pool.rolledForward;

  const figure = pool.settled && pool.qualified ? pool.returnCents : pool.potCents;
  const figureLabel = pool.settled && pool.qualified ? 'Return' : 'Pot';

  return (
    `<button type="button" class="fs-poolrow" data-pool="${pool.catalogNumber}">` +
    `<span class="fs-poolrow__badge ${badgeClass}${rolling ? ' is-rollover' : ''}">` +
    `${escapeHtml(badge)}</span>` +
    '<span class="fs-poolrow__main">' +
    `<span class="fs-poolrow__name">${escapeHtml(pool.name)}</span>` +
    `<span class="fs-poolrow__state">${escapeHtml(pool.state)}</span>` +
    '</span>' +
    '<span class="fs-poolrow__fig">' +
    `<span class="fs-poolrow__figlabel">${figureLabel}</span>` +
    `<span class="fs-poolrow__figvalue${rolling ? ' is-carried' : ''}" ` +
    `data-exact-cents="${figure}">${escapeHtml(formatCredits(figure))}</span>` +
    '</span>' +
    '</button>'
  );
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
function poolsModule() {
  const mode = slateMode();
  const pools = mode === SLATE_MODE_DEMO ? weekPools(selectedWeek) : slateRows();

  if (mode === SLATE_MODE_UNDRAWN || mode === 'unavailable') {
    const reason = mode === SLATE_MODE_UNDRAWN
      ? 'No Pool slate has been drawn for this week yet. Four definitions must '
        + 'pass both catalog gates before a week can be drawn, and the '
        + 'league’s provider source readiness is not yet confirmed.'
      : 'This week’s Pool slate could not be read for this session.';
    return (
      `<section class="fs-wkmod" data-module="pools" data-state="${escapeHtml(mode)}">` +
      sectionHeading('FANTASYSTAKES POOLS') +
      '<div class="fs-poolrows" id="fs-week-pools"></div>' +
      note(reason, { pending: true }) +
      '</section>'
    );
  }

  return (
    `<section class="fs-wkmod" data-module="pools" data-state="${escapeHtml(mode)}">` +
    sectionHeading(`FANTASYSTAKES POOLS · ${pools.length} THIS WEEK`) +
    `<div class="fs-poolrows" id="fs-week-pools">${pools.map(poolRow).join('')}</div>` +
    '</section>'
  );
}

/* ── Panel ──────────────────────────────────────────────────────────────────*/

/**
 * @returns {string}
 */
export function buildWeekPanel() {
  const composer = new PanelComposer('week');

  composer.add(weekSwitch());
  // No strip, and therefore no Credits disclaimer. Both follow from the locked
  // Rev 4.2 Final POR, not from the work being unfinished.
  composer.add(
    '<div class="fs-wkscroll">' +
    yahooModule() +
    betsModule() +
    poolsModule() +
    '</div>',
  );

  return composer.toHTML();
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

  const matchups = yahooMatchups(selectedWeek);
  panel.querySelectorAll('[data-card-action="yahoo"]').forEach((el) => {
    onActivate(el, () => {
      const m = matchups.find((x) => x.id === el.dataset.cardId);
      if (m) api.openSheet(previewSheet(m));
    });
  });

  const bets = weekBets(selectedWeek);
  panel.querySelectorAll('[data-card-action="wager"]').forEach((el) => {
    onActivate(el, () => {
      const card = bets.find((c) => c.id === el.dataset.cardId);
      if (card) api.openSheet(wagerSheet(card));
    });
  });

  const pools = slateMode() === SLATE_MODE_DEMO
    ? weekPools(selectedWeek) : slateRows();
  panel.querySelectorAll('[data-pool]').forEach((el) => {
    el.addEventListener('click', () => {
      const pool = pools.find((p) => String(p.catalogNumber) === el.dataset.pool);
      if (pool) api.openSheet(poolSheet(pool));
    });
  });
}