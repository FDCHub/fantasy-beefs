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
import { accordion, bindAccordions, escapeHtml } from './components.js';
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
      // FINAL POR §27E — LINEUPS SITS ABOVE ON OFFER.
      //
      // `identitySection` draws the `ON OFFER` block. LINEUPS is the roster the
      // price rests on, and a reader comparing an offer against the lineups now
      // meets the lineups first rather than scrolling past the analysis to
      // reach them. Still COLLAPSED — moving it up changes the order, not the
      // density.
      lineupsSection(m, served) +
      identitySection(m, served) +
      collapsible('WHY THE LINE LOOKS THIS WAY', paragraphs(why)) +
      collapsible('THE READ', paragraphs(read)) +
      closingNote +
      sourceFooter,
    onMount: bindAccordions,
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
  if (!filtered.length) {
    filtered.push({ label: 'Market', value: 'Not priced yet' });
  }

  const heading = m.settled ? 'RESULT' : 'ON OFFER';
  return accordion({
    key: 'preview-offer',
    title: heading,
    className: 'fs-prev',
    bodyHtml: filtered.map((row) => (
      '<div class="fs-prev__row">' +
      `<span class="fs-prev__label">${escapeHtml(row.label)}</span>` +
      `<span class="fs-prev__value">${escapeHtml(row.value)}</span>` +
      '</div>'
    )).join(''),
  });
}

/** A per-slot PROJECTION, or the unresolved mark where none is retained. */
function figure(row) {
  return typeof row.projection === 'number' ? row.projection.toFixed(1) : '—';
}

/**
 * The LIVE figure for one starter, or the em dash.
 *
 * THE EM DASH IS THE ONLY THING AN UNMEASURED STARTER MAY SHOW — Rev 1.4 §L2.
 * The server sends `live_measured: false` with `live_points: null` for a player
 * its provider has said nothing about, which before the week's first kickoff is
 * every starter on both rosters. Drawing that as `0.0` would tell a GM the
 * player had taken the field and busted.
 *
 * A MEASURED ZERO IS A DIFFERENT FACT and reaches here as `live_measured: true`
 * with `live_points: 0`. It prints `0.0`. That is why the flag is consulted and
 * the value is never merely tested for truthiness.
 */
function liveFigure(row) {
  return row.liveMeasured && typeof row.live === 'number'
    ? row.live.toFixed(1) : '—';
}

/**
 * A labelled figure. One markup shape wherever LIVE sits above PROJ.
 *
 * @param {string} label
 * @param {string} value
 * @param {string} [modifier] an `is-*` class naming the figure's role
 * @returns {string}
 */
function figurePair(label, value, modifier = '') {
  return (
    `<span class="fs-cmp__fig${modifier ? ` ${modifier}` : ''}">` +
    `<span class="fs-cmp__figlabel">${escapeHtml(label)}</span>` +
    `<span class="fs-cmp__fignum">${escapeHtml(value)}</span>` +
    '</span>'
  );
}

/**
 * ONE team's half of ONE comparison row.
 *
 * BOTH TEAMS USE THIS FUNCTION, and that is the whole of Rev 1.4's parallel-
 * construction requirement. Wave 4A drew two independent `lineupTable()` calls
 * stacked one above the other: parallel in construction, and not a comparison.
 * The quarterback a GM was weighing sat nine rows above the quarterback it was
 * being weighed against, and on a 320px phone the two were never on screen
 * together — so the panel a GM opens before spending Credits made the one
 * judgement it exists for the hardest thing on it.
 *
 * The acting GM's cell and the opponent's are now the same call, in the same
 * row, differing only in the data handed to them. Neither can carry a figure
 * the other cannot, and neither carries emphasis the other does not.
 *
 * A SIDE WITH NO STARTER IN THIS SLOT DRAWS AN EMPTY CELL, never a shifted row.
 * Pulling the opponent's next player up to close the gap would pair two
 * starters the lineups do not pair — a comparison no server ever served.
 *
 * @param {{row: object|null, side: string}} spec
 * @returns {string}
 */
function teamCell(spec) {
  const row = spec.row;
  const name = row ? (row.player || '—') : '—';
  const empty = row ? '' : ' is-empty';
  return (
    `<div class="fs-cmp__cell${empty}" role="cell" ` +
    `data-cmp-side="${escapeHtml(spec.side)}">` +
    `<span class="fs-cmp__player">${escapeHtml(name)}</span>` +
    '<span class="fs-cmp__figs">' +
    figurePair('LIVE', row ? liveFigure(row) : '—', 'is-live') +
    figurePair('PROJ', row ? figure(row) : '—') +
    '</span>' +
    '</div>'
  );
}

/**
 * The row's POSITION key — the thing the two cells beside it are keyed by.
 *
 * THE LINEUPS ARE PAIRED BY LINEUP ORDINAL, which is what the engine's own
 * ordering means: `_fetch_starters_for_odds` takes the first `N_START` roster
 * rows by id, so a player's position in that list IS its lineup slot. Where
 * both sides fill the slot with the same roster position — which every seeded
 * roster in this product does — the key is that position.
 *
 * WHERE THEY DIFFER, BOTH ARE NAMED. Labelling the row with one team's position
 * alone would assert a pairing the other team's roster does not support, and a
 * GM reading `RB` would believe it was comparing two running backs.
 *
 * @param {object|null} a
 * @param {object|null} b
 * @returns {string}
 */
function positionKey(a, b) {
  const left = (a && a.position) || '';
  const right = (b && b.position) || '';
  if (left && right && left !== right) return `${left}/${right}`;
  return left || right || '—';
}

/**
 * A team's footer figures — the two totals the SERVER computed.
 *
 * NEITHER TOTAL IS ADDED UP HERE. `projected_total` and `live_total` are the
 * read model's own sums; recomputing them in the browser would give the surface
 * a second opinion about its own figures, and the two would agree right up
 * until the day one of them was corrected. Rev 4.3 §28.
 *
 * `live_total` IS NULL UNTIL SOMETHING HAS BEEN MEASURED, and null draws the em
 * dash. A team whose starters have not kicked off has not scored 0.0.
 *
 * @param {{liveTotal: number|null, projectedTotal: number|null, side: string}} spec
 * @returns {string}
 */
function totalCell(spec) {
  const live = typeof spec.liveTotal === 'number'
    ? spec.liveTotal.toFixed(1) : '—';
  const projected = typeof spec.projectedTotal === 'number'
    ? spec.projectedTotal.toFixed(1) : '—';
  return (
    `<div class="fs-cmp__cell" role="cell" ` +
    `data-cmp-side="${escapeHtml(spec.side)}">` +
    '<span class="fs-cmp__figs">' +
    figurePair('LIVE TOTAL', live, 'is-live') +
    figurePair('PROJECTED', projected) +
    '</span>' +
    '</div>'
  );
}

/**
 * The comparison matrix — both starting lineups, paired row by row.
 *
 * ONE TABLE, NOT TWO TABLES SIDE BY SIDE. Two full-width lineup cards jammed
 * next to each other is what a 320px viewport cannot carry; a matrix keyed by
 * roster position down the left edge, with one narrow column per team, is what
 * it can. The two teams therefore stay horizontally adjacent at every certified
 * viewport, and the wider presentations widen this same grid rather than
 * re-laying it out — which is what preserves the row-to-row matchup
 * relationship the phone build states.
 *
 * @param {{teams: Array<{name: string, rows: Array<object>,
 *          projectedTotal: number|null, liveTotal: number|null}>}} spec
 * @returns {string}
 */
function comparisonMatrix(spec) {
  const [left, right] = spec.teams;
  const depth = Math.max(left.rows.length, right.rows.length);

  const rows = [];
  for (let i = 0; i < depth; i += 1) {
    const a = left.rows[i] || null;
    const b = right.rows[i] || null;
    rows.push(
      '<div class="fs-cmp__row" role="row">' +
      `<span class="fs-cmp__pos" role="rowheader">${escapeHtml(positionKey(a, b))}</span>` +
      teamCell({ row: a, side: 'acting' }) +
      teamCell({ row: b, side: 'opponent' }) +
      '</div>');
  }

  return (
    '<div class="fs-cmp" role="table">' +
    '<div class="fs-cmp__head" role="row">' +
    '<span class="fs-cmp__pos" role="columnheader">POS</span>' +
    `<span class="fs-cmp__team" role="columnheader" data-cmp-side="acting">${escapeHtml(left.name)}</span>` +
    `<span class="fs-cmp__team" role="columnheader" data-cmp-side="opponent">${escapeHtml(right.name)}</span>` +
    '</div>' +
    rows.join('') +
    '<div class="fs-cmp__row is-total" role="row">' +
    '<span class="fs-cmp__pos" role="rowheader"></span>' +
    totalCell({ side: 'acting', liveTotal: left.liveTotal,
      projectedTotal: left.projectedTotal }) +
    totalCell({ side: 'opponent', liveTotal: right.liveTotal,
      projectedTotal: right.projectedTotal }) +
    '</div>' +
    '</div>'
  );
}

/**
 * What the two figures under each player MEAN, in the state they are in.
 *
 * THREE STATES, AND THE SURFACE SAYS A DIFFERENT THING FOR EACH. Rev 1.4 §L2
 * forbids one sentence covering all three, because "no starter has been scored
 * yet" and "we could not read this league's provider" look identical on screen
 * — both are em dashes — and mean entirely different things to the GM
 * looking at them. The server distinguishes them with `live_available` and its
 * governed `live_reason`; this reads that distinction rather than guessing at
 * it from whether any figure happens to be present.
 *
 * PROJECTIONS ARE DESCRIBED IN EVERY BRANCH. A live read that failed must cost
 * a GM the LIVE column and nothing else, so no branch below implies the
 * projections are degraded, stale or absent.
 *
 * @param {object} served the MatchupPreviewOut
 * @returns {string}
 */
function liveNote(served) {
  const scored = [served.acting, served.opponent]
    .some((side) => side && typeof side.live_total === 'number');

  if (scored) {
    return '<div class="fs-note">LIVE is what this league\u2019s provider '
      + 'reports these starters have scored so far this week. PROJ is the '
      + 'pregame projection FantasyStakes simulated the market above from \u2014 '
      + 'the two are different measurements and neither replaces the other. A '
      + 'starter its provider has not scored yet reads \u2014.</div>';
  }

  if (served.live_available) {
    return '<div class="fs-note">No starter has been scored yet this week, so '
      + 'every LIVE figure reads \u2014. PROJ is the pregame projection '
      + 'FantasyStakes simulated the market above from, and it is unaffected.'
      + '</div>';
  }

  return '<div class="fs-note">Current scoring is not available from this '
    + 'league\u2019s provider right now, so every LIVE figure reads \u2014. '
    + 'Showing a number there would mean inventing one. PROJ is the pregame '
    + 'projection FantasyStakes simulated the market above from, and it is '
    + 'unaffected.</div>';
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
/* FINAL POR (freeze) §3B — THE LINEUP BODY, REUSABLE.
 *
 * The Action Required detail needs the SAME lineups the Matchup Preview draws
 * — the owner approved that presentation and §3B says to reuse it rather than
 * invent a second one. `lineupsSection` wraps this in Preview's own accordion;
 * this is the body without the wrapper, so a caller can put it inside its own.
 *
 * IT INVENTS NOTHING WHEN UNBOUND. With no served preview it returns the same
 * honest sentence Preview shows, because naming players from an unbound read
 * would be inventing a roster.
 *
 * @param {object|null} served a served preview view
 * @param {{you?: string, them?: string}} names fallback team names
 * @returns {string}
 */
export function lineupsBody(served, names = {}) {
  if (!served) {
    return '<div class="fs-note">Starting lineups bind from the provider once '
      + 'its read is wired for this matchup. Naming players here would be '
      + 'inventing a roster no source supports.</div>';
  }
  const acting = served.acting || {};
  const opponent = served.opponent || {};
  const map = (row) => ({
    position: row.position,
    player: row.player_name,
    projection: row.projected_points,
    live: typeof row.live_points === 'number' ? row.live_points : null,
    liveMeasured: row.live_measured === true,
  });
  const actingRows = (acting.lineup || []).map(map);
  const opponentRows = (opponent.lineup || []).map(map);
  if (!actingRows.length && !opponentRows.length) {
    return '<div class="fs-note">Neither team has a starting lineup bound for '
      + 'this week yet, so there are no projections to show.</div>';
  }
  return comparisonMatrix({
    teams: [
      { name: acting.team_name || names.you || 'You', rows: actingRows,
        projectedTotal: typeof acting.projected_total === 'number'
          ? acting.projected_total : null,
        liveTotal: typeof acting.live_total === 'number' ? acting.live_total : null },
      { name: opponent.team_name || names.them || 'Opponent', rows: opponentRows,
        projectedTotal: typeof opponent.projected_total === 'number'
          ? opponent.projected_total : null,
        liveTotal: typeof opponent.live_total === 'number' ? opponent.live_total : null },
    ],
  }) + liveNote(served);
}

function lineupsSection(m, served) {
  if (served) {
    const acting = served.acting || {};
    const opponent = served.opponent || {};
    // A STRAIGHT RENAME OF SERVED FIELDS AND NOTHING ELSE. No figure is
    // rounded, summed or defaulted on the way through: `live` stays null where
    // the server sent null, and `liveMeasured` carries the server's own
    // affirmative flag so a measured 0.0 survives the hop.
    const map = (row) => ({
      position: row.position,
      player: row.player_name,
      projection: row.projected_points,
      live: typeof row.live_points === 'number' ? row.live_points : null,
      liveMeasured: row.live_measured === true,
    });
    const actingRows = (acting.lineup || []).map(map);
    const opponentRows = (opponent.lineup || []).map(map);

    if (!actingRows.length && !opponentRows.length) {
      return collapsible('LINEUPS',
        '<div class="fs-note">Neither team has a starting lineup bound for '
        + 'this week yet, so there are no projections to show.</div>');
    }

    return collapsible('LINEUPS',
      comparisonMatrix({
        teams: [
          { name: acting.team_name || m.you.name, rows: actingRows,
            projectedTotal: typeof acting.projected_total === 'number'
              ? acting.projected_total : null,
            liveTotal: typeof acting.live_total === 'number'
              ? acting.live_total : null },
          { name: opponent.team_name || m.name, rows: opponentRows,
            projectedTotal: typeof opponent.projected_total === 'number'
              ? opponent.projected_total : null,
            liveTotal: typeof opponent.live_total === 'number'
              ? opponent.live_total : null },
        ],
      })
      + liveNote(served));
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
  return accordion({
    title,
    bodyHtml,
    open: options.open === true,
    className: 'fs-prev',
  });
}

function paragraphs(list) {
  return list.map((text) => `<p class="fs-prev__p">${escapeHtml(text)}</p>`).join('');
}

function shorten(name) {
  return name.length > 16 ? `${name.slice(0, 15)}…` : name;
}
