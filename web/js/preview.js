/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.3 · Matchup Preview
 * WP3C (was Sprint 7 Package 2)
 *
 * AN ANALYSIS SURFACE, AND ONLY THAT — Rev 4.3 §10.
 *
 * WHAT CHANGED AND WHY. Rev 4.2's preview opened with a SPORTSBOOK VIEW block
 * restating the moneyline, the spread and the total, then showed lineups, then
 * the analysis. Three things were wrong with that under Rev 4.3:
 *
 *   1. IT DUPLICATED THE MARKETS. The same three numbers the GM had just tapped
 *      past were repeated inside the surface meant to explain them, which made
 *      the preview read like a second place to bet. §10 removes the block.
 *   2. THE ANALYSIS CAME LAST. A GM opening "why does this line look this way?"
 *      met a table of nine roster slots before a sentence of explanation.
 *   3. THE ORDER WAS NOT THE POR'S.
 *
 * The locked order is now exactly:
 *
 *     MATCHUP PREVIEW
 *     matchup identity / records
 *     WHY THE LINE LOOKS THIS WAY   ← analysis
 *     THE READ                      ← short, stronger takeaway
 *     LINEUPS                       ← dense content, last
 *
 * ANALYSIS BEFORE LINEUPS is the whole point, so both analysis sections open by
 * default and the lineups collapse. That inverts Rev 4.2, where the lineups
 * were the section held open.
 *
 * IT IS PUSHED, NOT SWAPPED. Opening the preview from inside the composer
 * pushes a sheet level rather than replacing one, so closing it returns to a
 * composer still holding the market, mode and stake the GM entered (§10's
 * closing requirement). Nothing in this file writes composer state.
 *
 * IT RECOMPUTES NOTHING. `whyTheLine` and `theRead` are narrative over inputs
 * the surface was already given; no line is priced here and no settlement rule
 * is applied. Rev 4.3 §28.
 * ========================================================================== */

import { attributionFooter } from './attribution.js';
import { escapeHtml } from './components.js';
import { theRead, whyTheLine } from './narrative.js';

/**
 * @param {object} m a matchup view model
 * @returns {{title: string, sub: string, body: string, onMount: Function}}
 */
export function previewSheet(m) {
  // Where the matchup came from is stated, not implied. A Yahoo league matchup
  // is not a FantasyStakes wager, and the preview must not let a GM mistake one
  // for the other just because the grammar is shared.
  const fromYahoo = m.source === 'yahoo';
  const week = m.weekLabel || '';

  // WP3D — THE OLD SOURCE BANNER IS GONE, and the exact contractual
  // attribution replaces it.
  //
  // The banner was written to keep a GM from mistaking a Yahoo league matchup
  // for a FantasyStakes wager, which is a real and worthwhile distinction — and
  // the sentence below still draws it. What the banner ALSO did, unintentionally,
  // was claim official standing for the matchup, in a product Yahoo does not
  // operate, endorse or approve. Rev 4.3 §23 permits a data-source statement
  // and no more, so that claim had to go whether or not the attribution
  // replaced it. The retired wording is named in the WP3D report and in the
  // suites that used to pin it; it is deliberately not spelled here, because
  // the shipped source is scanned for it.
  //
  // The attribution is not a substitute for the distinction, and the closing
  // note is not a substitute for the attribution. Both are kept, each doing its
  // own job: one says where the matchup came from, the other says what it is
  // not.
  const closingNote = fromYahoo
    ? '<div class="fs-note">Analysis only. This is a Yahoo league matchup, ' +
      'not a FantasyStakes wager — nothing here stakes Credits.</div>'
    : '<div class="fs-note">Analysis only — no wager runs through this card. ' +
      'Close to return to your challenge; nothing you have entered is lost.</div>';

  // ATTRIBUTED ONLY WHEN THIS SHEET IS ACTUALLY SHOWING YAHOO INFORMATION.
  //
  // Two conditions, both required, and they are different questions. `fromYahoo`
  // is whether THIS MATCHUP came from the provider; `attributionFooter` checks
  // whether the SESSION's league is Yahoo-backed at all. A Demo session fails
  // the second and gets nothing, which is the hard rule — the same component
  // renders both, and only the authoritative provider binding decides.
  const sourceFooter = attributionFooter({ showsYahooInformation: fromYahoo });

  return {
    title: 'Matchup Preview',
    sub: [`${m.you.name} vs ${m.name}`, week].filter(Boolean).join(' · '),
    body:
      identitySection(m) +
      // ANALYSIS FIRST, BOTH OPEN. §10.
      collapsible('WHY THE LINE LOOKS THIS WAY', paragraphs(whyTheLine(m)),
                  { open: true }) +
      collapsible('THE READ', paragraphs(theRead(m)), { open: true }) +
      // DENSE CONTENT LAST, AND COLLAPSED.
      lineupsSection(m) +
      closingNote +
      sourceFooter,
    onMount: (host) => {
      host.querySelectorAll('[data-collapse]').forEach((headEl) => {
        headEl.addEventListener('click', () => {
          const section = headEl.parentElement;
          const open = section.classList.toggle('is-open');
          headEl.setAttribute('aria-expanded', open ? 'true' : 'false');
        });
      });
    },
  };
}

/**
 * Matchup identity and records — the POR's second block.
 *
 * NO MARKET CELLS. This is where Rev 4.2's SPORTSBOOK VIEW sat, and what
 * replaces it carries who is playing and what they have done, not what the
 * board says. A record the surface does not hold is left out rather than
 * drawn as a dash beside one it does.
 *
 * @param {object} m
 * @returns {string}
 */
function identitySection(m) {
  // A SETTLED MATCHUP REPORTS ITS RESULT HERE.
  //
  // Rev 4.2 carried the final scores inside SPORTSBOOK VIEW, which §10 removed
  // — and removing the block must not silently lose the result with it. A final
  // score is not a market: it is the matchup's own record, which is exactly
  // what §10's second block is for. So it moves here, and what does NOT come
  // with it is the `Closing line` row, because a closing line is a market
  // figure and this build does not retain one anyway.
  const rows = m.settled
    ? [
      { label: 'Result', value: m.winner ? `${m.winner} by `
        + `${Math.abs(m.spread).toFixed(1)}` : '' },
      { label: `Final · ${m.you.name}`,
        value: typeof m.yourProjection === 'number'
          ? m.yourProjection.toFixed(1) : '' },
      { label: `Final · ${m.name}`,
        value: typeof m.opponentProjection === 'number'
          ? m.opponentProjection.toFixed(1) : '' },
    ].filter((r) => r.value)
    : [
      { label: m.you.name, value: m.you.record || '' },
      { label: m.name, value: m.record || '' },
    ].filter((r) => r.label);

  return (
    '<section class="fs-prev is-open" data-preview-section="identity">' +
    '<div class="fs-prev__head is-static">' +
    '<span class="fs-prev__title">MATCHUP</span></div>' +
    '<div class="fs-prev__body is-open">' +
    rows.map((row) => (
      '<div class="fs-prev__row">' +
      `<span class="fs-prev__label">${escapeHtml(row.label)}</span>` +
      `<span class="fs-prev__value">${escapeHtml(row.value)}</span>` +
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
  const mine = Array.isArray(m.yourLineup) ? m.yourLineup : [];
  const theirs = Array.isArray(m.opponentLineup) ? m.opponentLineup : [];

  if (mine.length === 0 && theirs.length === 0) {
    return collapsible('LINEUPS',
      '<div class="fs-note">Starting lineups bind from the provider once its '
      + 'read is wired for this matchup. Naming players here would be inventing '
      + 'a roster no source supports.</div>');
  }

  const rows = mine.map((slot, i) => {
    const other = theirs[i] || { player: null, projection: null, slot: '' };
    return (
      '<div class="fs-spl__row">' +
      `<span class="fs-spl__name">${slot.player ? escapeHtml(slot.player) : '—'}</span>` +
      `<span class="fs-spl__proj">${figure(slot)}</span>` +
      `<span class="fs-spl__slot">${escapeHtml(slot.slot)}</span>` +
      `<span class="fs-spl__proj">${figure(other)}</span>` +
      `<span class="fs-spl__name is-right">${other.player ? escapeHtml(other.player) : '—'}</span>` +
      '</div>'
    );
  }).join('');

  // What is unknown depends on the matchup: the viewer's own roster is known
  // and an opponent's is not; in a third-party Yahoo matchup neither is; and in
  // a PAST week the per-slot figures themselves are not retained on either side.
  const named = mine.some((r) => r.player);
  const bindingNote = m.settled
    ? 'Per-slot results for a past week are not retained in this build. The '
      + 'team totals are the result; the rows above them bind from the provider '
      + 'once its read is wired.'
    : (named
      ? 'Opponent starters bind from the provider once its read is wired; the '
        + 'slot shape and projections are what the inputs give us today.'
      : 'Starters for both teams bind from the provider once its read is wired. '
        + 'Naming them here would be inventing a roster no source supports.');

  const totals = (typeof m.yourProjection === 'number'
                  && typeof m.opponentProjection === 'number')
    ? '<div class="fs-spl__row is-total">' +
      '<span class="fs-spl__name">Total</span>' +
      `<span class="fs-spl__proj">${m.yourProjection.toFixed(1)}</span>` +
      '<span class="fs-spl__slot"></span>' +
      `<span class="fs-spl__proj">${m.opponentProjection.toFixed(1)}</span>` +
      '<span class="fs-spl__name is-right"></span>' +
      '</div>'
    : '';

  const body =
    '<div class="fs-spl">' +
    '<div class="fs-spl__head">' +
    `<span>${escapeHtml(m.you.name.toUpperCase())}</span><span>PROJ</span><span></span>` +
    `<span>PROJ</span><span class="is-right">${escapeHtml(shorten(m.name).toUpperCase())}</span>` +
    '</div>' +
    rows +
    totals +
    '</div>' +
    '<div class="fs-note">Projections are the pregame projection and refresh ' +
    `until the week’s first kickoff. ${bindingNote}</div>`;

  // COLLAPSED BY DEFAULT — the inversion of Rev 4.2, and the mechanism by which
  // "analysis appears before dense lineup content" is true on screen and not
  // merely true in the source order.
  return collapsible('LINEUPS', body);
}

function collapsible(title, bodyHtml, options = {}) {
  const open = options.open ? ' is-open' : '';
  return (
    `<section class="fs-prev${open}">` +
    '<button type="button" class="fs-prev__head" data-collapse ' +
    `aria-expanded="${options.open ? 'true' : 'false'}">` +
    `<span class="fs-prev__title">${title}</span>` +
    '<span class="fs-prev__chev" aria-hidden="true">›</span>' +
    '</button>' +
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
