/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · League
 * Sprint 7 Package 2
 *
 * Two zones under the strip: FantasyStakes Bets and FantasyStakes Pools.
 *
 * BETS is a vertical carousel — one complete rich matchup card presented at a
 * time, snapped. Vertical discovery suits a large, variable opponent count and
 * lets one card carry identity, records, the market row, the projection and a
 * line of analysis without competing for width.
 *
 * POOLS shows all four of the week's Pools at once in a 2×2 grid. Rollover is
 * a modifier on a subject type, never a third type, and a rolling Pool does
 * not take a gold card — it takes a marked badge and its carried pot in gold.
 * ========================================================================== */

import { PENDING_FIGURE, PanelComposer, escapeHtml, sectionHeading, tabHeader } from './components.js';
import { formatCredits } from './credits.js';
import { ILLUSTRATIVE, LEAGUE_IDENTITY } from './demo-state.js';
import { OPPONENTS, POOLS, allMatchups, poolBadge } from './data/league-data.js';
import { matchupCard } from './wagercard.js';
import {
  LEAGUE_MODE_DEMO, currentWeek, leagueMode, leagueName,
} from './league-model.js';
import {
  boundAvailableCents, boundWeeklyMinLiveCents,
} from './ledger-model.js';

/**
 * @returns {string}
 */
export function buildLeaguePanel() {
  const composer = new PanelComposer('league');

  // PRODUCTION IDENTITY, OR NONE. `CULV APPRECIATION SOCIETY` is the fixture's
  // league and was shown to every signed-in GM regardless of which league they
  // are actually in. The bound name is `leagues.name` — the PROVIDER's name for
  // the league once a refresh has bound it, and a locally-chosen one otherwise.
  const production = leagueMode() !== LEAGUE_MODE_DEMO;
  const boundName = leagueName();
  const week = currentWeek();

  composer.add(tabHeader({
    title: production ? (boundName || 'LEAGUE UNAVAILABLE')
                      : LEAGUE_IDENTITY.name,
    // THE WEEK, WHEN THE PROVIDER HAS STATED ONE. `Week 5 · Regular Season`
    // was a fixture string; a league in week 9 read week 5. Where no refresh
    // has stated a week the label drops the claim rather than guessing.
    sub: production ? weekLabel(week) : LEAGUE_IDENTITY.week,
    // FIRST KICKOFF has no authoritative source: the gateway captures matchups
    // and finality, not a countdown to the next game.
    asideValue: production ? PENDING_FIGURE : ILLUSTRATIVE.kickoffCountdown,
    asideLabel: 'FIRST KICKOFF',
  }));

  // THE STRIP SPLITS THREE WAYS, and each cell is treated on its own evidence.
  //
  //   Wallet / Weekly Min Left / Available  AUTHORITATIVE — the bound Ledger
  //       already serves all three, and reading them from the same model the
  //       Ledger tab totals from is what stops the two tabs disagreeing.
  //
  //   Net Winnings + rank                   UNRESOLVED — P3 proved season
  //       winnings has no posted door, and the rank is a standings position the
  //       provider gateway does not expose. Neither is derivable, and the
  //       illustrative +$126 / 1st was being shown as this GM's own.
  const unresolved = production;
  composer.addStrip({
    id: 'fs-strip-league',
    label: 'League summary',
    cells: [
      {
        label: 'Net Winnings',
        cents: ILLUSTRATIVE.netWinningsCents,
        signed: true,
        context: production ? '' : ILLUSTRATIVE.netWinningsRank,
        pending: unresolved,
      },
      { label: 'Wallet',
        cents: production ? (boundWalletFigure() ?? 0) : ILLUSTRATIVE.walletCents,
        pending: production && boundWalletFigure() === null },
      { label: 'Weekly Min Left',
        cents: production ? (boundWeeklyMinLiveCents() ?? 0)
                          : ILLUSTRATIVE.weeklyMinLeftCents,
        pending: production && boundWeeklyMinLiveCents() === null },
      { label: 'Available',
        cents: production ? (boundAvailableCents() ?? 0)
                          : ILLUSTRATIVE.availableCents,
        anchor: true,
        pending: production && boundAvailableCents() === null },
    ],
  });

  composer.addDisclaimer();

  composer.add(
    '<div class="fs-zones">' +
    `<div class="fs-zone fs-zone--bets">${betsZone()}</div>` +
    `<div class="fs-zone fs-zone--pools">${poolsZone()}</div>` +
    '</div>',
  );

  return composer.toHTML();
}

/**
 * `Week N · Regular Season`, or the unresolved treatment.
 *
 * @param {number|null} week
 * @returns {string}
 */
function weekLabel(week) {
  if (week === null) return 'Week unavailable';
  const phase = 'Regular Season';
  return `Week ${week} · ${phase}`;
}

/**
 * Wallet alone, derived from the two bound terms the Ledger publishes.
 *
 * Available is spendable = wallet + live weekly minimum, so wallet is their
 * difference. A SUBTRACTION OF TWO AUTHORITATIVE FIGURES, not a new source —
 * and null whenever either term is missing, so it can never be half-real.
 *
 * @returns {number|null}
 */
function boundWalletFigure() {
  const available = boundAvailableCents();
  const weeklyMin = boundWeeklyMinLiveCents();
  if (available === null || weeklyMin === null) return null;
  return available - weeklyMin;
}

function betsZone() {
  const cards = allMatchups()
    .map((m) => `<div class="fs-carousel__item" role="listitem">${matchupCard(m)}</div>`)
    .join('');

  return (
    sectionHeading(`FANTASYSTAKES BETS · ${OPPONENTS.length} OPPONENTS · SWIPE ↕`) +
    `<div class="fs-carousel" id="fs-bets-carousel" role="list">${cards}</div>`
  );
}

function poolsZone() {
  const cards = POOLS.map((pool) => {
    const badge = poolBadge(pool);
    const badgeClass = pool.scope === 'TEAM' ? 'is-team' : 'is-matchup';
    const carried = pool.continuation
      ? `<span class="fs-pool__carried">Rolled from Wk ${pool.carriedFromWeek}</span>`
      : '';
    return (
      `<button type="button" class="fs-pool" data-pool="${pool.catalogNumber}">` +
      `<span class="fs-pool__badge ${badgeClass}${pool.continuation ? ' is-rollover' : ''}">` +
      `${escapeHtml(badge)}</span>` +
      `<span class="fs-pool__name">${escapeHtml(pool.name)}</span>` +
      `<span class="fs-pool__rule">${escapeHtml(pool.rule)}</span>` +
      '<span class="fs-pool__foot">' +
      `<span class="fs-pool__entry">${escapeHtml(formatCredits(pool.entryCents))} · ${pool.entered} in</span>` +
      `<span class="fs-pool__pot${pool.continuation ? ' is-carried' : ''}" ` +
      `data-exact-cents="${pool.potCents}">${escapeHtml(formatCredits(pool.potCents))}</span>` +
      '</span>' +
      carried +
      '</button>'
    );
  }).join('');

  return (
    sectionHeading(`FANTASYSTAKES POOLS · ${POOLS.length} THIS WEEK`) +
    `<div class="fs-pools" id="fs-pools-grid">${cards}</div>`
  );
}

/**
 * Wire League's two tap paths.
 *
 * A market cell opens the composer with that market selected; anywhere else on
 * the card opens the same composer with none selected. The market handler runs
 * first and stops propagation, so one tap never does both.
 *
 * @param {HTMLElement} panel
 * @param {{openComposer: Function, openSheet: Function}} api
 */
export function bindLeague(panel, api) {
  panel.querySelectorAll('[data-card-action="challenge"]').forEach((card) => {
    const matchupId = card.dataset.cardId;

    card.querySelectorAll('[data-market]').forEach((cell) => {
      cell.addEventListener('click', (event) => {
        event.stopPropagation();
        api.openComposer({ matchupId, marketId: cell.dataset.market });
      });
    });

    card.addEventListener('click', () => api.openComposer({ matchupId, marketId: null }));
  });

  panel.querySelectorAll('[data-pool]').forEach((el) => {
    el.addEventListener('click', () => {
      const pool = POOLS.find((p) => String(p.catalogNumber) === el.dataset.pool);
      if (pool) api.openSheet(poolSheet(pool));
    });
  });
}

/**
 * The Pool-detail sheet. Exported so The Week opens the same detail for the
 * same Pool. A week may layer state on top — a settled Pool carries its outcome
 * — but the definition, the rule and the catalog number are always the
 * catalog's own.
 *
 * @param {object} pool
 * @returns {{title: string, sub: string, body: string}}
 */
export function poolSheet(pool) {
  const outcomeRows = pool.settled
    ? '<div class="fs-prev__row"><span class="fs-prev__label">Outcome</span>' +
      `<span class="fs-prev__value">${escapeHtml(pool.state)}</span></div>` +
      (pool.qualified
        ? '<div class="fs-prev__row"><span class="fs-prev__label">Return</span>' +
          `<span class="fs-prev__value fs-money" data-exact-cents="${pool.returnCents}">` +
          `${escapeHtml(formatCredits(pool.returnCents))}</span></div>`
        : '')
    : '';

  return {
    title: pool.name,
    sub: `${poolBadge(pool)} · catalog #${pool.catalogNumber}`,
    body:
      outcomeRows +
      '<div class="fs-prev__row"><span class="fs-prev__label">Subject</span>' +
      `<span class="fs-prev__value">${escapeHtml(pool.subject)}</span></div>` +
      '<div class="fs-prev__row"><span class="fs-prev__label">Settles on</span>' +
      `<span class="fs-prev__value fs-money">${escapeHtml(pool.rule)}</span></div>` +
      '<div class="fs-prev__row"><span class="fs-prev__label">Entry</span>' +
      `<span class="fs-prev__value fs-money" data-exact-cents="${pool.entryCents}">` +
      `${escapeHtml(formatCredits(pool.entryCents))}</span></div>` +
      // S8-P4B-3R: `entered` is a count of entries, which the SLATE does not
      // carry — entries live in `pool_claim`, and no read model publishes them
      // yet. Drawing the em dash is the approved unresolved treatment; drawing
      // `undefined`, which is what an unguarded interpolation did, is not.
      '<div class="fs-prev__row"><span class="fs-prev__label">Entered</span>' +
      `<span class="fs-prev__value fs-money">` +
      `${pool.entered === undefined ? PENDING_FIGURE : pool.entered}</span></div>` +
      '<div class="fs-prev__row"><span class="fs-prev__label">Pot</span>' +
      `<span class="fs-prev__value fs-money" data-exact-cents="${pool.potCents}">` +
      `${escapeHtml(formatCredits(pool.potCents))}</span></div>` +
      (pool.continuation
        ? '<div class="fs-note">'
          + (pool.carriedFromWeek === undefined
            ? 'Carried from an earlier week. '
            : `Carried from Week ${pool.carriedFromWeek}. `)
          + 'A continuation occupies one of the week’s four slots.</div>'
        : '') +
      (pool.rolledForward
        ? '<div class="fs-note">No entry qualified, so the pot carried forward. ' +
          'Rolling over is a modifier on this Pool, not a different kind of Pool.</div>'
        : '') +
      (pool.settled
        ? '<div class="fs-note">Settled. Pool settlement is performed by the Pool ' +
          'engine; nothing here moves Credits.</div>'
        : '<div class="fs-note">All Pools for the week lock at the week’s first kickoff. ' +
          'Entry binds to the Pool engine when the session seam lands.</div>'),
  };
}