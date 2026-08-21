/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.3 · Matchup Preview
 * WP3C, reconciled by UIRECON Wave 4A
 *
 * AN ANALYSIS SURFACE, AND ONLY THAT — Rev 4.3 §10.
 *
 * The locked order is:
 *
 *     MATCHUP PREVIEW               the sheet title
 *     identity + market snapshot    who, when, and what is on offer
 *     WHY THE LINE LOOKS THIS WAY   ← the method, then this matchup's numbers
 *     THE READ                      ← what those numbers mean
 *     LINEUPS                       ← the projections both of the above rest on
 *
 * ── WHAT WAVE 4A CHANGED, AND WHY EACH ONE MATTERED ────────────────────────
 *
 *   IT HAS DATA NOW. `shell.js openPreview()` handed this surface
 *   `spread: null`, `yourLineup: []` and `opponentLineup: []`, so every branch
 *   in `narrative.js` took its "not priced yet" path and LINEUPS drew its empty
 *   state. The demo has seeded nine starters and a projection per player per
 *   week the whole time; what was missing was a read model between them, and
 *   `reports/matchup_preview_read_model.py` is it.
 *
 *   THE MATCHUP IS NAMED ONCE. The sheet subtitle read `A vs B · Week n` and
 *   the block underneath it repeated `A` and `B` as two rows — both teams,
 *   twice, inside about sixty pixels, and in the bound state the second copy
 *   carried two blank values. The identity block now carries what the subtitle
 *   does not: the market on offer.
 *
 *   THE THREE MODULES ARE PEERS. WHY THE LINE, THE READ and LINEUPS are one
 *   `collapsible()` construction — same header height, same chevron, same
 *   border, same padding, same typography — with content-specific bodies only.
 *
 * IT RECOMPUTES NOTHING. Every figure drawn here is a served field: the
 * projections, the server's own lineup totals, the win probabilities, the
 * spread, the total and the moneyline. Rev 4.3 §28.
 * ========================================================================== */

import { attributionFooter } from './attribution.js';
import { escapeHtml } from './components.js';
import {
  theRead, theReadFromPreview, whyTheLine, whyTheLineFromPreview,
} from './narrative.js';
import { formatOdds } from './wager-model.js';
import { formatSpread } from './narrative.js';

/**
 * @param {object} m a matchup view model
 * @param {{served?: object|null, marketId?: string|null}} [ctx]
 * @returns {{title: string, sub: string, body: string, onMount: Function}}
 */
export function previewSheet(m, ctx = {}) {
  const served = ctx.served || null;

  // Where the matchup came from is stated, not implied. A Yahoo league matchup
  // is not a FantasyStakes wager, and the preview must not let a GM mistake one
  // for the other just because the grammar is shared.
  const fromYahoo = m.source === 'yahoo';
  const week = m.weekLabel || '';

  const closingNote = fromYahoo
    ? '<div class="fs-note">Analysis only. This is a Yahoo league matchup, ' +
      'not a FantasyStakes wager — nothing here stakes Credits.</div>'
    : '<div class="fs-note">Analysis only — no wager runs through this card. ' +
      'Close to return to your challenge; nothing you have entered is lost.</div>';

  const sourceFooter = attributionFooter({ showsYahooInformation: fromYahoo });

  // THE TWO NARRATIVE PATHS ANSWER DIFFERENT QUESTIONS. A served preview
  // explains a real matchup from real figures; an unbound one explains that
  // there is nothing bound. Neither is a degraded version of the other.
  const why = served
    ? whyTheLineFromPreview(served, { marketId: ctx.marketId })
    : whyTheLine(m);
  const read = served ? theReadFromPreview(served) : theRead(m);

  return {
    title: 'Matchup Preview',
    sub: [`${m.you.name} vs ${m.name}`, week].filter(Boolean).join(' · '),
    body:
      identitySection(m, served) +
      // ANALYSIS FIRST, BOTH OPEN. §10.
      collapsible('WHY THE LINE LOOKS THIS WAY', paragraphs(why), { open: true }) +
      collapsible('THE READ', paragraphs(read), { open: true }) +
      // DENSE CONTENT LAST, AND COLLAPSED.
      lineupsSection(m, served) +
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
 * The market snapshot — what this block carries INSTEAD of the team names.
 *
 * THE SUBTITLE ALREADY SAID WHO IS PLAYING. Rev 4.2's SPORTSBOOK VIEW sat here
 * and §10 removed it for restating the three markets the GM had just tapped
 * past; what replaced it restated the two team names the subtitle had just
 * given. Wave 4A puts the one thing neither of those carried in this slot: the
 * offer itself, in the same three-market vocabulary the composer uses.
 *
 * A SETTLED MATCHUP REPORTS ITS RESULT HERE INSTEAD. A final score is not a
 * market — it is the matchup's own record, which is what §10's second block is
 * for.
 *
 * @param {object} m
 * @param {object|null} served
 * @returns {string}
 */
function identitySection(m, served) {
  const rows = [];

  if (m.settled) {
    rows.push(
      { label: 'Result', value: m.winner
        ? `${m.winner} by ${Math.abs(m.spread).toFixed(1)}` : '' },
      { label: `Final · ${m.you.name}`,
        value: typeof m.yourProjection === 'number'
          ? m.yourProjection.toFixed(1) : '' },
      { label: `Final · ${m.name}`,
        value: typeof m.opponentProjection === 'number'
          ? m.opponentProjection.toFixed(1) : '' },
    );
  } else if (served && served.market && served.market.available) {
    const market = served.market;
    if (typeof market.acting_moneyline === 'number') {
      rows.push({ label: 'Moneyline', value: formatOdds(market.acting_moneyline) });
    }
    if (typeof market.acting_spread === 'number') {
      rows.push({ label: 'Spread', value: formatSpread(market.acting_spread) });
    }
    if (typeof market.total_line === 'number') {
      rows.push({ label: 'Over/Under', value: market.total_line.toFixed(1) });
    }
  } else if (served && served.market) {
    rows.push({ label: 'Market', value: '—' });
  }

  const filtered = rows.filter((row) => row.value);
  if (!filtered.length) return '';

  const heading = m.settled ? 'RESULT' : 'ON OFFER';
  return (
    '<section class="fs-prev is-open" data-preview-section="identity">' +
    '<div class="fs-prev__head is-static">' +
    `<span class="fs-prev__title">${heading}</span></div>` +
    '<div class="fs-prev__body is-open">' +
    filtered.map((row) => (
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

/**
 * One team's projected starting lineup.
 *
 * BOTH TEAMS USE THIS FUNCTION. That is the whole of the parallel-construction
 * requirement for LINEUPS: the acting GM's column and the opponent's are not
 * "styled the same", they are the same call with different data. There is no
 * emphasis on either side beyond the team name each carries.
 *
 * @param {{name: string, rows: Array<object>, total: number|null}} spec
 * @returns {string}
 */
function lineupTable(spec) {
  const rows = spec.rows.map((row) => (
    '<div class="fs-lineup__row">' +
    `<span class="fs-lineup__pos">${escapeHtml(row.position || '—')}</span>` +
    `<span class="fs-lineup__name">${escapeHtml(row.player || '—')}</span>` +
    `<span class="fs-lineup__proj">${escapeHtml(figure(row))}</span>` +
    '</div>'
  )).join('');

  const total = typeof spec.total === 'number'
    ? spec.total.toFixed(1) : '—';

  return (
    '<div class="fs-lineup">' +
    `<div class="fs-lineup__team">${escapeHtml(spec.name)}</div>` +
    '<div class="fs-lineup__head">' +
    '<span class="fs-lineup__pos">POS</span>' +
    '<span class="fs-lineup__name">PLAYER</span>' +
    '<span class="fs-lineup__proj">PROJ</span>' +
    '</div>' +
    rows +
    '<div class="fs-lineup__row is-total">' +
    '<span class="fs-lineup__pos"></span>' +
    '<span class="fs-lineup__name">Projected total</span>' +
    `<span class="fs-lineup__proj">${escapeHtml(total)}</span>` +
    '</div>' +
    '</div>'
  );
}

/**
 * LINEUPS — the projections the price rests on.
 *
 * THE ROWS ARE THE ONES THE SIMULATOR WAS HANDED. `matchup_preview_read_model`
 * reads them through `_fetch_starters_for_odds`, which is the same call
 * `compute_market_board` makes, so what a GM sees here is what priced the
 * matchup rather than a second roster read that could disagree with it.
 *
 * @param {object} m
 * @param {object|null} served
 * @returns {string}
 */
function lineupsSection(m, served) {
  if (served) {
    const acting = served.acting || {};
    const opponent = served.opponent || {};
    const map = (row) => ({
      position: row.position,
      player: row.player_name,
      projection: row.projected_points,
    });
    const actingRows = (acting.lineup || []).map(map);
    const opponentRows = (opponent.lineup || []).map(map);

    if (!actingRows.length && !opponentRows.length) {
      return collapsible('LINEUPS',
        '<div class="fs-note">Neither team has a starting lineup bound for '
        + 'this week yet, so there are no projections to show.</div>');
    }

    return collapsible('LINEUPS',
      '<div class="fs-lineups">'
      + lineupTable({ name: acting.team_name || m.you.name,
        rows: actingRows, total: acting.projected_total })
      + lineupTable({ name: opponent.team_name || m.name,
        rows: opponentRows, total: opponent.projected_total })
      + '</div>'
      + '<div class="fs-note">These are the projected starters and projections '
      + 'FantasyStakes simulated to produce the market above. Projections '
      + 'refresh until the week’s first kickoff.</div>');
  }

  // ── UNBOUND. Unchanged from WP3C, and it has to be: with no served preview
  // there is no source for either roster, and naming players here would be
  // inventing one.
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

  const named = mine.some((r) => r.player);
  const bindingNote = m.settled
    ? 'Per-slot results for a past week are not retained in this build. The '
      + 'team totals are the result; the rows above them bind from the provider '
      + 'once its read is wired.'
    : (named
      ? 'Opponent starters bind from Yahoo once its read is wired; the '
        + 'slot shape and projections are what the inputs give us today.'
      : 'Starters for both teams bind from Yahoo once the provider read is '
        + 'wired. Naming them here would be inventing a roster no source '
        + 'supports.');

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
