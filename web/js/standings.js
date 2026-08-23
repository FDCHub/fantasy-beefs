/* ============================================================================
 * FantasyStakes — first-tab standings / Championship Chase
 * ========================================================================== */

import { attributionFooter } from './attribution.js';
import { creditsDisclaimer, escapeHtml } from './components.js';
import {
  creditsTone, exactCentsAttr, formatCredits, formatSignedCredits,
} from './credits.js';
import {
  STANDINGS_STATE_LOADING,
  STANDINGS_STATE_NOT_ACTIVATED,
  STANDINGS_STATE_NO_DATA,
  STANDINGS_STATE_READY,
  STANDINGS_STATE_UNAVAILABLE,
  STANDINGS_TABLES,
  actingTeamId,
  cellsFor,
  championshipLifecycle,
  championshipState,
  championshipUnresolved,
  isTiedRow,
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

/* SKUNK IS A FEE, NOT A RESULT — Final POR UI-2 §26.
 *
 * Drawn without the signed grammar and without the positive/negative tone the
 * three money columns carry. A Skunk is always an amount assessed AGAINST a GM,
 * so `+$5.00` in green would say the opposite of what happened, and `-$5.00` in
 * red would double-state a subtraction the FS SCORE column has already made.
 *
 * ZERO IS DRAWN AS A DASH. Most GMs are never skunked, and a column of `$0.00`
 * would make the exceptions harder to find rather than easier — which is the
 * only thing this column is for. The exact cents stay on the element for a
 * reader who needs them. */
function skunkCell(cents) {
  const amount = Math.abs(Number(cents) || 0);
  const text = amount === 0 ? '—' : formatCredits(amount);
  return (
    `<td class="fs-st__num fs-st__skunk${amount === 0 ? ' is-none' : ''}"`
    + `${exactCentsAttr(amount)}>${escapeHtml(text)}</td>`
  );
}

function tableRows(table) {
  const me = actingTeamId();
  return rowsFor(table.key).map((row) => {
    const view = cellsFor(table.key, row);
    const isMe = me !== null && row.team_id === me;
    // EXACT TIES ARE REAL TIES and are shown as such. The flag is the server's;
    // nothing here compares cents, because the payout splits on the server's
    // answer and a second opinion would eventually disagree with it.
    const tied = table.key === 'overall' && isTiedRow(row);
    const cells = view.cells.map((cell) => {
      if (cell.kind === 'cents') return moneyCell(cell.value);
      if (cell.kind === 'skunk') return skunkCell(cell.value);
      return `<td class="fs-st__num">${escapeHtml(String(cell.value))}</td>`;
    }).join('');

    return (
      `<tr class="fs-st__row${isMe ? ' is-me' : ''}" `
      + `data-team-id="${escapeHtml(String(row.team_id))}"`
      + `${isMe ? ' aria-current="true"' : ''}>`
      + `<td class="fs-st__rank">${escapeHtml(String(view.rank))}`
      + (tied ? '<span class="fs-st__tie" title="Exact tie">T</span>' : '')
      + '</td>'
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

/**
 * The subheading, driven by the four-state server lifecycle.
 *
 * FROZEN AND FINAL ARE DIFFERENT SENTENCES. Frozen means the field and the
 * scoring window are closed; final means every eligible result is actually in.
 * Saying FINAL while a regular-season contest is still unsettled tells a GM the
 * season is decided when it is not.
 */
function championshipSubheading() {
  const championship = championshipState();
  const through = Number(
    championship ? championship.scoring_through_week : NaN);
  const suffix = Number.isFinite(through) ? ` · through Week ${through}` : '';

  switch (championshipLifecycle()) {
    case 'PAID':
      return `PAID · FantasyStakes Championship${suffix}`;
    case 'FINAL':
      return `FINAL · Championship scoring${suffix}`;
    case 'FROZEN': {
      const open = championshipUnresolved().length;
      return `FROZEN${suffix}`
        + (open ? ` · ${open} eligible result${open === 1 ? '' : 's'} outstanding`
                : '');
    }
    default: {
      const parts = ['CHAMPIONSHIP CHASE'];
      if (CONTEXT && typeof CONTEXT.current_week === 'number') {
        parts.push(`Week ${CONTEXT.current_week}`);
      }
      return parts.join(' · ');
    }
  }
}

/**
 * One line telling a GM what this number actually is.
 *
 * SHORT ON PURPOSE. This sits directly under the standings, where a paragraph
 * is a wall a GM scrolls past. It states the one fact that is genuinely
 * confusable — a wallet full of Credits is not a lead — and leaves the rest to
 * Rules, which is where long-form reading belongs.
 */
/* THE APPROVED EXPLANATORY COPY — Final POR UI-2 §26, verbatim.
 *
 * Three sentences, and each does one job the other two cannot:
 *
 *   1. what the Score IS FOR — it decides championship standing;
 *   2. what it IS — the identity, spelled out in the same words the six column
 *      headers use, so a reader can add the columns up and get the total;
 *   3. what it is NOT — Wallet balance, which is the single most common
 *      misreading and the reason the identity is stated at all.
 *
 * Sentence 2 exists BECAUSE the table now shows three terms and a total. The
 * reader who could previously see two of three terms had no way to check the
 * arithmetic; now they can, and the copy tells them the rule they are checking
 * against. */
export const STANDINGS_EXPLAINER_LINES = Object.freeze([
  'Your FantasyStakes Score determines your championship standing.',
  'FantasyStakes Score = Matchups + Prop Pools − Skunk Fees',
  'Wallet balance does not affect championship position.',
]);

function championshipExplainer() {
  const base = STANDINGS_EXPLAINER_LINES.join(' ');
  switch (championshipLifecycle()) {
    case 'PAID':
      return `${base} Pot paid.`;
    case 'FINAL':
      return `${base} Scoring closed.`;
    // FROZEN IS A LEGACY-ERA STATE ONLY. WP-8 retired the playoff-boundary
    // freeze, so a Final POR season never reports it; the case is kept because
    // a legacy season's snapshot still does and its sentence is still true
    // for one.
    case 'FROZEN':
      return `${base} Scoring closed; postseason play no longer changes it.`;
    default:
      return base;
  }
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
    + `<p class="fs-st__explainer">${escapeHtml(championshipExplainer())}</p>`
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
