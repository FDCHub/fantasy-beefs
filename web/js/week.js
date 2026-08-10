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

import { PanelComposer, escapeHtml, sectionHeading } from './components.js';
import { formatCredits } from './credits.js';
import { CURRENT_WEEK, PAST_WEEK, WEEKS, weekBets, weekPools, yahooMatchups } from './data/week-data.js';
import { poolBadge } from './data/league-data.js';
import { lifecycleCard, wagerSheet } from './action.js';
import { poolSheet } from './league.js';
import { previewSheet } from './preview.js';
import { matchupMarketCells, wagerCard } from './wagercard.js';

/** Locked Rev 4.2 subtitle. */
export const WEEK_SUBTITLE = 'Official Yahoo matchups + FantasyStakes action';

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
  const matchups = yahooMatchups(selectedWeek);
  const cards = matchups
    .map((m) => `<div class="fs-vcar__item">${yahooCard(m)}</div>`)
    .join('');

  return (
    '<section class="fs-wkmod" data-module="yahoo">' +
    sectionHeading('YAHOO LEAGUE MATCHUPS · SWIPE ↕') +
    `<div class="fs-vcar" id="fs-yahoo-carousel" role="list">${cards}</div>` +
    '</section>'
  );
}

/* ── Module 2 · FantasyStakes bets ──────────────────────────────────────────*/

function betsModule() {
  const bets = weekBets(selectedWeek);
  const cards = bets
    .map((card) => `<div class="fs-vcar__item is-compact">${lifecycleCard(card)}</div>`)
    .join('');

  // The count is derived, never typed: a heading that claimed four while the
  // module drew three would be the one lie a weekly dashboard cannot afford.
  return (
    '<section class="fs-wkmod" data-module="bets">' +
    sectionHeading(`FANTASYSTAKES BETS · ${bets.length} SHOWN · SWIPE ↕`) +
    `<div class="fs-vcar is-compact" id="fs-week-bets" role="list">${cards}</div>` +
    '</section>'
  );
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

function poolsModule() {
  const pools = weekPools(selectedWeek);
  return (
    '<section class="fs-wkmod" data-module="pools">' +
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
    el.addEventListener('click', () => {
      const m = matchups.find((x) => x.id === el.dataset.cardId);
      if (m) api.openSheet(previewSheet(m));
    });
  });

  const bets = weekBets(selectedWeek);
  panel.querySelectorAll('[data-card-action="wager"]').forEach((el) => {
    el.addEventListener('click', () => {
      const card = bets.find((c) => c.id === el.dataset.cardId);
      if (card) api.openSheet(wagerSheet(card));
    });
  });

  const pools = weekPools(selectedWeek);
  panel.querySelectorAll('[data-pool]').forEach((el) => {
    el.addEventListener('click', () => {
      const pool = pools.find((p) => String(p.catalogNumber) === el.dataset.pool);
      if (pool) api.openSheet(poolSheet(pool));
    });
  });
}