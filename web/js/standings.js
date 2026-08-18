/* ============================================================================
 * FantasyStakes — first-tab standings / Championship Chase
 * ========================================================================== */

import { attributionFooter } from './attribution.js';
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
  championshipState,
  rowsFor,
  standingsState,
} from './standings-model.js';

export const STANDINGS_TITLE = 'FANTASYSTAKES CHAMPIONSHIP';

const STATE_COPY = Object.freeze({
  [STANDINGS_STATE_LOADING]: {
    heading: 'Loading championship chase',
    body: 'Reading the league’s results.',
  },
  [STANDINGS_STATE_NO_DATA]: {
    heading: 'No championship standings yet',
    body: 'The FantasyStakes Championship Chase appears once the season is under way.',
  },
  [STANDINGS_STATE_NOT_ACTIVATED]: {
    heading: 'Season not activated',
    body: 'This league has no teams on its roster yet. The commissioner sets up the season from the menu.',
  },
  [STANDINGS_STATE_UNAVAILABLE]: {
    heading: 'Championship standings unavailable',
    body: 'We could not read this league’s results just now. Nothing is shown rather than an estimate.',
  },
});

function moneyCell(cents) {
  const tone = creditsTone(cents);
  return (
    `<td class="fs-st__num fs-money ${tone}"${exactCentsAttr(cents)}>`
    + `${escapeHtml(formatSignedCredits(cents))}</td>`
  );
}

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

function standingsTable(table, withRows) {
  const head = table.columns.map((column, i) => {
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

let CONTEXT = null;

function championshipSubheading() {
  const championship = championshipState();
  if (championship && championship.status === 'FINAL') {
    const through = Number(championship.scoring_through_week);
    return Number.isFinite(through)
      ? `FINAL · Championship scoring through Week ${through}`
      : 'FINAL · FantasyStakes Championship';
  }

  const parts = ['CHAMPIONSHIP CHASE'];
  if (CONTEXT && typeof CONTEXT.current_week === 'number') {
    parts.push(`Week ${CONTEXT.current_week}`);
  }
  return parts.join(' · ');
}

export function buildStandingsPanel() {
  const state = standingsState();
  const ready = state === STANDINGS_STATE_READY;
  const tables = STANDINGS_TABLES
    .map((table) => standingsTable(table, ready)).join('');
  const body = ready ? tables : stateBlock(state) + tables;

  return (
    '<div class="fs-tabhead">'
    + '<div class="fs-tabhead__main">'
    + `<div class="fs-tabhead__title">${escapeHtml(STANDINGS_TITLE)}</div>`
    + `<div class="fs-tabhead__sub">${escapeHtml(championshipSubheading())}</div>`
    + '</div>'
    + '</div>'
    + creditsDisclaimer()
    + `<div class="fs-st__scroll" id="fs-standings-scroll">${body}</div>`
    + attributionFooter()
  );
}

export function setStandingsContext(context) {
  CONTEXT = context || null;
}

// Standings remains read-only; the first tab has no local command surface.
// eslint-disable-next-line no-unused-vars
export function bindStandings(panel) {
  /* intentionally empty */
}
