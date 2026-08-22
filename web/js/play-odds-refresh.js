/* ============================================================================
 * FantasyStakes — wiring Play's two odds-refresh controls
 * UIRECON · refine-refresh pass
 *
 * WHAT THIS FILE KNOWS THAT `odds-refresh.js` DOES NOT. That one is the
 * affordance — markup, states, a clock — and is testable with no browser and no
 * server. This one is the only part that knows the application exists: which
 * league is on screen, which week the board was priced for, where Play's cards
 * land, and how to put fresh figures back onto them.
 *
 * ── IT RE-READS; IT NEVER PRICES ────────────────────────────────────────────
 *
 * Both controls call the SAME GET the cards were drawn from,
 * `/league/{id}/versus/board`, with the per-card control adding the route's own
 * `opponent_team_id` filter. That route runs the Monte Carlo, applies the
 * governed median-and-round rule, decides the spread's sign and writes nothing.
 * Search this file for an arithmetic operator and you will not find one.
 *
 * So a refresh here is exactly what the first paint was, asked again. There is
 * no second pricing path to disagree with the first, and no browser-side model
 * that could drift from the server's.
 *
 * ── AND IT MOVES NO MONEY, BY CONSTRUCTION RATHER THAN BY CARE ──────────────
 *
 * A Play card is an OPPONENT, not a wager. Nothing on this surface has a stake,
 * an escrow account or an agreed term, because nothing has been proposed yet —
 * the market cells are an offer a GM has not taken. The route is a GET, the
 * board response carries no economic identifiers, and the only thing that
 * changes on screen is three cells and a timestamp.
 *
 * ── WHY THE CARDS ARE PATCHED IN PLACE ──────────────────────────────────────
 *
 * Re-rendering the Play panel would work and would be wrong: it destroys the
 * carousel's scroll position, so a GM who refreshed the price on the eighth
 * opponent would be returned to the first. The board is bound into
 * `market-model` and only the affected cells are rewritten, so the rail does
 * not move under a thumb that just tapped it.
 *
 * ── ONE DELEGATED LISTENER, AND WHY IT STOPS PROPAGATION ────────────────────
 *
 * The Play card is `is-tappable` with `data-card-action="challenge"`: a click
 * anywhere on it opens the composer. A refresh control lives INSIDE that card,
 * so its click must not also be a challenge. The handler claims the event
 * before the card's own handler can see it, which is the same discipline the
 * market cells and the preview row already use.
 * ========================================================================== */

import {
  applyMarketRow, bindMarketBoard, marketComputedAt, marketFor,
} from './market-model.js';
import {
  BOARD_STAMP_ID, oddsStamp, runRefresh, setRefreshStatus,
} from './odds-refresh.js';
import { requestMarketBoard } from './versus-market-command.js';
import { formatSpread } from './narrative.js';
import { formatOdds } from './wager-model.js';

/** The unresolved figure — the same dash the first paint uses. */
const PENDING_FIGURE = '—';

/** Live binding: which league and week the board on screen belongs to. */
let CONTEXT = null;

/**
 * Tell this module which board is on screen.
 *
 * WITHOUT A CONTEXT THE CONTROLS DO NOTHING, and that is the correct failure:
 * a refresh needs a league and the week the market was priced for, and guessing
 * either would ask the server to price a different market than the one the GM
 * is looking at.
 *
 * @param {{leagueId: number, week: number}|null} context
 */
export function setPlayRefreshContext(context) {
  const leagueId = context && Number(context.leagueId);
  const week = context && Number(context.week);
  CONTEXT = (Number.isFinite(leagueId) && Number.isFinite(week))
    ? { leagueId, week } : null;
}

/** @returns {{leagueId: number, week: number}|null} */
export function playRefreshContext() {
  return CONTEXT;
}

/**
 * Turn a board refusal into a sentence about the DISPLAY.
 *
 * NOTHING HERE SAYS A MATCHUP CHANGED, because nothing did — and on this
 * surface nothing could: there is no wager yet. Every sentence is about whether
 * a price could be read.
 *
 * @param {MarketError|Error} error
 * @returns {string}
 */
export function explainBoardRefusal(error) {
  const code = error && error.reasonCode;
  if (code === 'postseason_field_unknown') {
    return 'The postseason field is not settled yet, so no matchup can be priced.';
  }
  if (code === 'postseason_ineligible') {
    return 'Postseason Matchups are limited to teams still on the championship track.';
  }
  if (code === 'opponent_not_in_league') {
    return 'That team is not in this league.';
  }
  if (code === 'not_a_league_member') {
    return 'You do not hold a team in this league.';
  }
  return 'Fresh odds are not available right now. Nothing on this screen has changed.';
}

/**
 * Rewrite the three market cells of one already-rendered card.
 *
 * EVERY VALUE IS SERVED. `formatOdds` and `formatSpread` decide only how a
 * number is drawn; the sign of the spread was decided once, on the server, in
 * `odds/market_lines`. A pairing the model cannot price keeps the dash rather
 * than showing a zero that would read as a pick'em.
 *
 * @param {Element} card a `[data-card-id]` element
 * @param {number} teamId
 */
export function repaintMarketCells(card, teamId) {
  if (!card) return;
  const board = marketFor(teamId);
  const priced = Boolean(board && board.available);
  const cells = card.querySelectorAll('[data-market]');
  cells.forEach((cell) => {
    const value = cell.querySelector('.fs-market__value');
    if (!value) return;
    value.textContent = marketCellValue(cell.dataset.market, board, priced);
  });
}

/** The same projection `league.js` paints with, kept in one shape. */
function marketCellValue(marketId, board, priced) {
  if (!board) return 'Play ›';
  if (!priced) return PENDING_FIGURE;
  if (marketId === 'ml') {
    return typeof board.acting_moneyline === 'number'
      ? formatOdds(board.acting_moneyline) : PENDING_FIGURE;
  }
  if (marketId === 'spread') {
    return typeof board.acting_spread === 'number'
      ? formatSpread(board.acting_spread) : PENDING_FIGURE;
  }
  return typeof board.total_line === 'number'
    ? board.total_line.toFixed(1) : PENDING_FIGURE;
}

/** Repaint every Play card the panel currently holds. */
function repaintAll(panel) {
  panel.querySelectorAll('.fs-wcard--matchup[data-card-id]').forEach((card) => {
    const teamId = Number(card.dataset.cardId);
    if (Number.isFinite(teamId)) repaintMarketCells(card, teamId);
  });
}

/** Move the heading's stamp onto whatever the server last said. */
function repaintStamp(panel) {
  setRefreshStatus(panel, BOARD_STAMP_ID, oddsStamp(marketComputedAt()));
}

/**
 * Re-read the whole board and repaint every card — the heading control.
 *
 * @param {Element} panel
 * @returns {Promise<object>} the served board
 */
export async function refreshBoard(panel) {
  if (!CONTEXT) throw new Error('no board context');
  const board = await requestMarketBoard(CONTEXT.leagueId, CONTEXT.week);
  bindMarketBoard(board);
  repaintAll(panel);
  repaintStamp(panel);
  return board;
}

/**
 * Re-read ONE pairing and repaint only that card — the per-card control.
 *
 * THE MERGE IS `applyMarketRow`, NOT A REBIND. A one-opponent response carries
 * one row; binding it whole would blank every other card's market.
 *
 * @param {Element} panel
 * @param {number} teamId
 * @returns {Promise<object>} the served single-row board
 */
export async function refreshPairing(panel, teamId) {
  if (!CONTEXT) throw new Error('no board context');
  const board = await requestMarketBoard(CONTEXT.leagueId, CONTEXT.week, teamId);
  applyMarketRow(board);
  const card = panel.querySelector(`.fs-wcard--matchup[data-card-id="${teamId}"]`);
  repaintMarketCells(card, teamId);
  repaintStamp(panel);
  return board;
}

/**
 * Bind Play's refresh controls.
 *
 * DELEGATED FROM THE PANEL, so controls survive the panel being re-rendered
 * — Play redraws on every authoritative refresh and each redraw replaces the
 * card elements. A per-control listener would be gone after the first redraw.
 *
 * @param {Element} panel the `#panel-league` element
 */
export function bindPlayOddsRefresh(panel) {
  if (!panel || panel.dataset.oddsRefreshBound === 'true') return;
  panel.dataset.oddsRefreshBound = 'true';

  panel.addEventListener('click', (event) => {
    const button = event.target.closest
      ? event.target.closest('[data-odds-refresh]')
      : null;
    if (!button || !panel.contains(button)) return;

    // CLAIM THE EVENT. The card behind this control opens the composer on any
    // click it sees, so a refresh that bubbled would also propose a wager.
    event.preventDefault();
    event.stopPropagation();

    const scope = button.dataset.refreshScope;
    const target = Number(button.dataset.refreshTarget);
    const work = scope === 'pairing' && Number.isFinite(target)
      ? () => refreshPairing(panel, target)
      : () => refreshBoard(panel);

    runRefresh(button, {
      work,
      explain: explainBoardRefusal,
      status: { root: panel, id: BOARD_STAMP_ID },
    });
  });
}
