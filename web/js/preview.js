/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · Matchup Preview
 * Sprint 7 Package 2
 *
 * Opened from VIEW MATCHUP PREVIEW inside the composer, in the shared sheet.
 * It is pushed ON TOP of the composer rather than replacing it, so closing it
 * returns to a composer that still holds the market, mode and stake the GM had
 * entered. Nothing in this file writes composer state.
 *
 * Section order is fixed: numbers first, then the data behind them, then the
 * market interpretation, then the fantasy interpretation.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import { sportsbookView, theRead, whyTheLine } from './narrative.js';

/**
 * @param {object} m a matchup from league-data
 * @returns {{title: string, sub: string, body: string, onMount: Function}}
 */
export function previewSheet(m) {
  // Where the matchup came from is stated, not implied. An official Yahoo
  // league matchup is not a FantasyStakes wager, and the preview must not let a
  // GM mistake one for the other just because the grammar is shared.
  const fromYahoo = m.source === 'yahoo';
  const week = m.weekLabel || 'Week 5';

  const sourceBanner = fromYahoo
    ? '<div class="fs-srcbanner" data-source="yahoo">OFFICIAL YAHOO FANTASY MATCHUP</div>'
    : '';

  const closingNote = fromYahoo
    ? '<div class="fs-note">Analysis only. This is an official Yahoo league ' +
      'matchup, not a FantasyStakes wager — nothing here stakes Credits.</div>'
    : '<div class="fs-note">Analysis only — no wager runs through this card. ' +
      'Close to return to your challenge; nothing you have entered is lost.</div>';

  return {
    title: 'Matchup Preview',
    sub: `${m.you.name} vs ${m.name} · ${week}`,
    body:
      sourceBanner +
      sportsbookSection(m) +
      lineupsSection(m) +
      collapsible('WHY THE LINE LOOKS THIS WAY', paragraphs(whyTheLine(m))) +
      collapsible('THE READ', paragraphs(theRead(m))) +
      closingNote,
    onMount: (host) => {
      host.querySelectorAll('[data-collapse]').forEach((headEl) => {
        headEl.addEventListener('click', () => {
          headEl.parentElement.classList.toggle('is-open');
        });
      });
    },
  };
}

/* Sportsbook View — open by default, not collapsible. */
function sportsbookSection(m) {
  const view = sportsbookView(m);
  return (
    '<section class="fs-prev">' +
    '<div class="fs-prev__head is-static"><span class="fs-prev__title">SPORTSBOOK VIEW</span></div>' +
    '<div class="fs-prev__body is-open">' +
    view.rows.map((row) => (
      '<div class="fs-prev__row">' +
      `<span class="fs-prev__label">${escapeHtml(row.label)}</span>` +
      `<span class="fs-prev__value fs-money">${escapeHtml(row.value)}</span>` +
      '</div>'
    )).join('') +
    '</div></section>'
  );
}

/** A per-slot figure, or the unresolved mark where none is retained. */
function figure(row) {
  return typeof row.projection === 'number' ? row.projection.toFixed(1) : '—';
}

function lineupsSection(m) {
  const rows = m.yourLineup.map((mine, i) => {
    const theirs = m.opponentLineup[i];
    return (
      '<div class="fs-spl__row">' +
      `<span class="fs-spl__name">${mine.player ? escapeHtml(mine.player) : '—'}</span>` +
      `<span class="fs-spl__proj">${figure(mine)}</span>` +
      `<span class="fs-spl__slot">${escapeHtml(mine.slot)}</span>` +
      `<span class="fs-spl__proj">${figure(theirs)}</span>` +
      `<span class="fs-spl__name is-right">${theirs.player ? escapeHtml(theirs.player) : '—'}</span>` +
      '</div>'
    );
  }).join('');

  // What is unknown depends on the matchup: the viewer's own roster is known
  // and an opponent's is not; in a third-party Yahoo matchup neither is; and in
  // a PAST week the per-slot figures themselves are not retained on either side.
  const named = m.yourLineup.some((r) => r.player);
  const bindingNote = m.settled
    ? 'Per-slot results for a past week are not retained in this build. The ' +
      'team totals are the result; the rows above them bind from Yahoo once ' +
      'the provider read is wired.'
    : (named
      ? 'Opponent starters bind from Yahoo once the provider read is wired; the ' +
        'slot shape and projections are what the inputs give us today.'
      : 'Starters for both teams bind from Yahoo once the provider read is wired. ' +
        'Naming them here would be inventing a roster no source supports.');

  const body =
    '<div class="fs-spl">' +
    '<div class="fs-spl__head">' +
    `<span>${escapeHtml(m.you.name.toUpperCase())}</span><span>PROJ</span><span></span>` +
    `<span>PROJ</span><span class="is-right">${escapeHtml(shorten(m.name).toUpperCase())}</span>` +
    '</div>' +
    rows +
    '<div class="fs-spl__row is-total">' +
    '<span class="fs-spl__name">Total</span>' +
    `<span class="fs-spl__proj">${m.yourProjection.toFixed(1)}</span>` +
    '<span class="fs-spl__slot"></span>' +
    `<span class="fs-spl__proj">${m.opponentProjection.toFixed(1)}</span>` +
    '<span class="fs-spl__name is-right"></span>' +
    '</div>' +
    '</div>' +
    '<div class="fs-note">Projections are the pregame projection and refresh ' +
    `until the week’s first kickoff. ${bindingNote}</div>`;

  return collapsible('STARTING LINEUPS &amp; PROJECTIONS', body, { open: true });
}

function collapsible(title, bodyHtml, options = {}) {
  const open = options.open ? ' is-open' : '';
  return (
    `<section class="fs-prev${open}">` +
    '<div class="fs-prev__head" data-collapse>' +
    `<span class="fs-prev__title">${title}</span>` +
    '<span class="fs-prev__chev">›</span>' +
    '</div>' +
    `<div class="fs-prev__body">${bodyHtml}</div>` +
    '</section>'
  );
}

function paragraphs(list) {
  return list.map((text) => `<p class="fs-prev__p">${escapeHtml(text)}</p>`).join('');
}

function shorten(name) {
  return name.length > 16 ? `${name.slice(0, 15)}…` : name;
}