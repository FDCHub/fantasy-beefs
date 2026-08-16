/* ============================================================================
 * FantasyStakes — Standings
 * WP3B · Rev 4.3 §7
 *
 * The default landing tab, and the one that answers "who is winning
 * FantasyStakes?".
 *
 * THREE COMPLETE TABLES, STACKED, ON ONE SCROLLING PAGE. Rev 4.3 §7 is explicit
 * about the shape and about what it forbids: no segmented selector, no
 * carousel, and no extra tap to reveal another standings category. All three
 * are in the document from the first paint and are reached by scrolling, the
 * way a fantasy-football standings page has always worked.
 *
 * That is a structural claim, so it is met structurally: this module emits
 * three `<table>` elements into one scroll region and has no selector control,
 * no rail, no snap container and no tab state of any kind. There is nothing
 * here that COULD hide a table.
 *
 * IT RANKS NOTHING AND COMPUTES NOTHING. The rank, the order and every cent
 * arrive from `standings-model.js`, which holds what the server sent. This
 * module decides how a row is DRAWN — nothing else. Rev 4.3 §28.
 *
 * THE ACTING GM'S ROW IS MARKED BY ID, IN ALL THREE TABLES, AT ANY RANK
 * (§7.4) — never by matching a display name, which two teams can share and a
 * rename can break.
 * ========================================================================== */

import { creditsDisclaimer, escapeHtml } from './components.js';
import { creditsTone, exactCentsAttr, formatSignedCredits } from './credits.js';
import {
  STANDINGS_STATE_LOADING,
  STANDINGS_STATE_NOT_ACTIVATED,
  STANDINGS_STATE_NO_DATA,
  STANDINGS_STATE_READY,
  STANDINGS_STATE_UNAVAILABLE,
  STANDINGS_TABLES,
  actingTeamId,
  cellsFor,
  rowsFor,
  standingsState,
} from './standings-model.js';

export const STANDINGS_TITLE = 'STANDINGS';

/**
 * The empty/unavailable states, in product language.
 *
 * NONE OF THESE INVENTS A TABLE. WP3B §8 and §26: a surface with no
 * authoritative answer says so. Raw reason codes, exception text and internal
 * identifiers never appear here — Rev 4.3 §27.
 */
const STATE_COPY = Object.freeze({
  [STANDINGS_STATE_LOADING]: {
    heading: 'Loading standings',
    body: 'Reading the league’s results.',
  },
  [STANDINGS_STATE_NO_DATA]: {
    heading: 'No standings yet',
    body: 'Standings appear once this league’s season is under way and its '
      + 'first results are in.',
  },
  [STANDINGS_STATE_NOT_ACTIVATED]: {
    heading: 'Season not activated',
    body: 'This league has no teams on its roster yet. The commissioner sets '
      + 'up the season from the menu.',
  },
  [STANDINGS_STATE_UNAVAILABLE]: {
    heading: 'Standings unavailable',
    body: 'We could not read this league’s results just now. Nothing is shown '
      + 'rather than an estimate.',
  },
});

/**
 * A money cell. Signed, toned, and carrying its exact cents.
 *
 * `data-exact-cents` travels with every figure, so the rounded string on screen
 * is never the only record of the value — the rule `credits.js` exists to keep.
 *
 * @param {number} cents
 * @returns {string}
 */
function moneyCell(cents) {
  const tone = creditsTone(cents);
  return (
    `<td class="fs-st__num fs-money ${tone}"${exactCentsAttr(cents)}>`
    + `${escapeHtml(formatSignedCredits(cents))}</td>`
  );
}

/**
 * One table's rows.
 *
 * @param {{key: string, columns: ReadonlyArray<string>}} table
 * @returns {string}
 */
function tableRows(table) {
  const me = actingTeamId();
  return rowsFor(table.key).map((row) => {
    const view = cellsFor(table.key, row);
    const isMe = me !== null && row.team_id === me;
    const cells = view.cells.map((cell) => (
      cell.kind === 'cents'
        ? moneyCell(cell.value)
        : `<td class="fs-st__num">${escapeHtml(String(cell.value))}</td>`
    )).join('');

    return (
      `<tr class="fs-st__row${isMe ? ' is-me' : ''}" `
      + `data-team-id="${escapeHtml(String(row.team_id))}"`
      // Announced rather than merely tinted: a row identified only by a
      // background colour is not identified for a screen reader, and §7.4 asks
      // for the GM's own row to be findable, not merely tinted.
      + `${isMe ? ' aria-current="true"' : ''}>`
      + `<td class="fs-st__rank">${escapeHtml(String(view.rank))}</td>`
      + `<td class="fs-st__team">${escapeHtml(view.teamName)}`
      + (isMe ? '<span class="fs-st__you">YOU</span>' : '')
      + '</td>'
      + cells
      + '</tr>'
    );
  }).join('');
}

/**
 * One complete standings table.
 *
 * RENDERED IN EVERY STATE, ROWS OR NOT. An empty league still shows all three
 * headings and all three column sets, which does two things: it tells a reader
 * what each table WILL contain, and it makes the §7 structural claim — three
 * complete tables, stacked, no selector — true of the empty page as well as the
 * populated one. A page whose shape changed with its contents would only be
 * certifiable in the state that happened to have data.
 *
 * @param {{key: string, heading: string, columns: ReadonlyArray<string>}} table
 * @param {boolean} withRows
 * @returns {string}
 */
function standingsTable(table, withRows) {
  const head = table.columns.map((column, i) => {
    // RK and TEAM lead; every remaining column is a figure and sits right.
    const cls = i === 0 ? 'fs-st__rank' : (i === 1 ? 'fs-st__team' : 'fs-st__num');
    return `<th class="${cls}" scope="col">${escapeHtml(column)}</th>`;
  }).join('');

  return (
    `<section class="fs-st${withRows ? '' : ' is-empty'}" `
    + `data-standings-table="${escapeHtml(table.key)}">`
    + `<h2 class="fs-st__heading">${escapeHtml(table.heading)}</h2>`
    + '<table class="fs-st__table">'
    + `<thead><tr>${head}</tr></thead>`
    + `<tbody>${withRows ? tableRows(table) : ''}</tbody>`
    + '</table>'
    + '</section>'
  );
}

/**
 * The intentional non-ready state.
 *
 * @param {string} state
 * @returns {string}
 */
function stateBlock(state) {
  const copy = STATE_COPY[state] || STATE_COPY[STANDINGS_STATE_NO_DATA];
  return (
    `<div class="fs-st__state" data-standings-state="${escapeHtml(state)}"`
    + (state === STANDINGS_STATE_LOADING ? ' aria-busy="true"' : '')
    + '>'
    + `<div class="fs-st__state-head">${escapeHtml(copy.heading)}</div>`
    + `<p class="fs-st__state-body">${escapeHtml(copy.body)}</p>`
    + '</div>'
  );
}

/**
 * The Standings panel.
 *
 * @returns {string}
 */
export function buildStandingsPanel() {
  const state = standingsState();

  const ready = state === STANDINGS_STATE_READY;
  const tables = STANDINGS_TABLES
    .map((table) => standingsTable(table, ready)).join('');
  const body = ready ? tables : stateBlock(state) + tables;

  // THE CREDITS DISCLAIMER, ONCE, ABOVE THE TABLES.
  //
  // Rev 4.3 §6 asks for the virtual-Credits disclosure wherever monetary
  // figures are prominent, and every one of these tables ranks on a money
  // column. Standings is also the DEFAULT TAB, so for most sessions it is the
  // first screen with a `$` on it — leaving the disclosure to the tabs a GM
  // reaches second would be leaving it off the one they always see.
  //
  // It sits under the header rather than under a four-cell strip because
  // Standings has no strip: §7 fixes this page's contents at three tables and
  // adding a summary strip to satisfy a layout convention would be adding a
  // component the POR did not ask for.
  return (
    '<div class="fs-tabhead">'
    + '<div class="fs-tabhead__main">'
    + `<div class="fs-tabhead__title">${escapeHtml(STANDINGS_TITLE)}</div>`
    + `<div class="fs-tabhead__sub">${escapeHtml(subheading())}</div>`
    + '</div>'
    + '</div>'
    + creditsDisclaimer()
    + `<div class="fs-st__scroll" id="fs-standings-scroll">${body}</div>`
  );
}

/**
 * The league context the shell supplied, or null.
 *
 * SUPPLIED RATHER THAN REACHED FOR, so this module reads the same context every
 * other surface does and there is one answer in the app to "which league, which
 * week". Declared before its readers, so nothing can reference it in the
 * temporal dead zone.
 *
 * @type {object|null}
 */
let CONTEXT = null;

/**
 * The page's context line — league and week.
 *
 * NOTHING HERE IS HARD-CODED (Rev 4.3 §17). The week comes from the server's
 * own answer; a session with no context says nothing about a week rather than
 * asserting one, and nowhere does this module write "Regular Season".
 *
 * @returns {string}
 */
function subheading() {
  if (!CONTEXT) return 'Who is winning FantasyStakes';
  const parts = [];
  if (CONTEXT.league_name) parts.push(String(CONTEXT.league_name));
  if (typeof CONTEXT.current_week === 'number') {
    parts.push(`Week ${CONTEXT.current_week}`);
  }
  return parts.length ? parts.join(' · ') : 'Who is winning FantasyStakes';
}

/**
 * Supply the league context line. Called by the shell after binding.
 *
 * @param {object|null} context a LeagueContextOut, or null
 */
export function setStandingsContext(context) {
  CONTEXT = context || null;
}

/**
 * Bind the panel.
 *
 * There is nothing interactive on Standings — no selector, no drill-in, no
 * command. The binder exists so the shell can treat every panel the same way,
 * and so that a future affordance has one place to be added.
 *
 * @param {HTMLElement} panel
 */
// eslint-disable-next-line no-unused-vars
export function bindStandings(panel) {
  /* intentionally empty — see above */
}
