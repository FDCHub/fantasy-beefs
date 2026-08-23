/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.3 · Play
 * WP3C (was League, Sprint 7 Package 2)
 *
 * "What can I play?" — Rev 4.3 §4.
 *
 * TWO SECTIONS UNDER THE STRIP, AND THEY ARE ONE CARD FAMILY IN TWO CONTENTS.
 * Matchups and Prop Pools are each a horizontal carousel presenting exactly one
 * complete card at a time, at one shared outer width and one shared outer
 * height. Rev 4.2's vertical rail and 2×2 Pool grid are both superseded — the
 * grid by POR Rev 1.4 §4, which needs a line for the governed question, and the
 * vertical rail by the RC4 mobile reconciliation, which measured it clipping its
 * own card on a real phone. Rev 4.3 §8.5's concern was that Play's Pools must not
 * become STATUS-style rails of several small tiles; one complete card per
 * viewport is the opposite of that, and is what both sections now do.
 *
 * WHAT WP3C CHANGED, AND WHY EACH ONE MATTERED
 *
 *   THE DATA IS REAL NOW. Every card on this tab used to come from
 *   `data/league-data.js`: eleven invented opponents with invented records,
 *   ranks, projections, moneylines, spreads and totals, plus four invented
 *   Pools — rendered to signed-in GMs in production. Discovery now reads
 *   `versus-model.js` (the server's own opponent list) and Pools read
 *   `pool-slate-model.js` (the governed weekly draw). Neither has a production
 *   fallback: a session that could not read them discovers nothing and says so.
 *
 *   THE COUNTDOWN IS GONE (§8.2). `FIRST KICKOFF` had no authoritative source —
 *   the gateway captures matchups and finality, not a countdown — so in
 *   production it drew a permanent em dash under a label promising a clock.
 *
 *   THE RANK IS GONE FROM THE STRIP (§8.3). `+$126 · 1st` put a standings
 *   position inside a money cell. Rank belongs to Standings, which WP3B built.
 *
 *   THE PHASE IS READ (§17, §27). `Week 5 · Regular Season` was two fixture
 *   strings; a league in its championship week read both of them wrongly.
 *
 * NOTHING HERE PRICES ANYTHING. A discovery card names an opponent and the
 * markets on offer; the quote is produced by the pricing engine inside the
 * composer, against that specific pairing. Rev 4.3 §28.
 * ========================================================================== */

import {
  PENDING_FIGURE, PanelComposer, escapeHtml, sectionHeading, tabHeader,
} from './components.js';
import { formatCredits } from './credits.js';
import { ILLUSTRATIVE, LEAGUE_IDENTITY } from './demo-state.js';
import { POOLS, poolBadge } from './data/league-data.js';
import {
  LEAGUE_MODE_DEMO, currentWeek, leagueMode, leagueName,
} from './league-model.js';
import { attributionFooter } from './attribution.js';
import { marketComputedAt, marketFor, marketMode } from './market-model.js';
import {
  BOARD_STAMP_ID, oddsStamp, refreshControl, refreshStatus,
} from './odds-refresh.js';
import { bindPlayOddsRefresh } from './play-odds-refresh.js';
import { formatSpread } from './narrative.js';
import { weekPhaseLabel } from './phase.js';
import { SLATE_MODE_DEMO, slateMode, slateRows } from './pool-slate-model.js';
import {
  VERSUS_STATE_FIELD_UNKNOWN, VERSUS_STATE_NONE_ELIGIBLE,
  VERSUS_STATE_NO_DATA, VERSUS_STATE_READY, VERSUS_STATE_UNAVAILABLE,
  playableCount, playableOpponents, versusMode, versusState,
} from './versus-model.js';
import { MARKETS, formatOdds } from './wager-model.js';
import {
  boundAvailableCents, boundWeeklyMinLiveCents,
} from './ledger-model.js';

/** Rev 4.3 §11 — the word SWIPE, and no directional arrow. */
export const SWIPE_WORD = 'SWIPE';

/* ── Section headings — Rev 1.4 Part 3 ──────────────────────────────────────
 *
 * SHORT FORMS, BECAUSE THE TAB IS ALREADY INSIDE FANTASYSTAKES. Both headings
 * used to open with the brand — `FANTASYSTAKES MATCHUPS`, `FANTASYSTAKES PROP
 * POOLS` — which spent the widest line of each section restating the one word
 * a GM on this tab cannot be in any doubt about, and pushed the count and the
 * swipe affordance into the helper slot's remaining space.
 *
 * THE PRODUCT TERMS ARE UNCHANGED. `Matchups` and `Prop Pools` are still the
 * public nouns everywhere they are introduced — Wrap Up, Rules, Standings and
 * the Account ledger all still say FantasyStakes Matchups, because those
 * surfaces mix FantasyStakes results with the Yahoo league's own. This is a
 * shortening inside one tab's headings, not a renaming. Nothing reintroduces
 * the public-facing `Versus`, which remains an internal module name only.
 */
export const MATCHUPS_HEADING = 'MATCHUPS';
export const POOLS_HEADING = 'PROP POOLS';

/* ── The odds-refresh affordance on Play ────────────────────────────────────
 *
 * TWO LEVELS, ONE PROMISE. The heading control re-reads the whole board; each
 * card's control re-reads that one pairing. Both are the same glyph and both
 * re-run the SAME server-side pricing the cards were drawn from, so a GM never
 * has to work out which of two refreshes they just used.
 *
 * WHY PLAY IS WHERE THIS BELONGS. Play is the screen where prices are shopped:
 * eleven opponents, three markets each, all of them simulated against
 * projections that move. Before this the only refresh in the product was on a
 * wager that already existed — a GM could re-read a price they had committed to
 * and not one they were considering.
 *
 * THE STAMP IS THE SERVER'S. `marketComputedAt()` is the `computed_at` the
 * board came back with, so `Odds updated 11:47 AM` reports when a Monte Carlo
 * finished rather than when a response landed.
 *
 * DEMO DRAWS NO CONTROL. The illustrative fixture has no board to re-read, and
 * a glyph whose first press is a no-op is worse than an absent one.
 */
export const BOARD_REFRESH_LABEL = 'Refresh odds for all matchups';

/** @returns {string} the heading control, or '' when there is no board. */
function boardRefreshControl() {
  if (marketMode() !== 'authoritative') return '';
  return refreshControl({
    scope: 'board',
    label: BOARD_REFRESH_LABEL,
    extraClass: 'fs-oddsref--heading',
  });
}

/** @returns {string} the heading's stamp line, or '' when there is no board. */
function boardRefreshStamp() {
  if (marketMode() !== 'authoritative') return '';
  return refreshStatus({
    id: BOARD_STAMP_ID,
    text: oddsStamp(marketComputedAt()),
    extraClass: 'fs-oddsref__stamp--board',
  });
}

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

  // NO ASIDE. Rev 4.2 put `FIRST KICKOFF` here; §8.2 removes the countdown
  // outright. The header carries identity and context and nothing else.
  composer.add(tabHeader({
    title: production ? (boundName || 'LEAGUE UNAVAILABLE')
                      : LEAGUE_IDENTITY.name,
    sub: production ? (weekPhaseLabel(week) || 'Week unavailable')
                    : LEAGUE_IDENTITY.week,
  }));

  // THE STRIP SPLITS THREE WAYS, and each cell is treated on its own evidence.
  //
  //   Wallet / Weekly Min Left / Available  AUTHORITATIVE — the bound Ledger
  //       serves all three, and reading them from the same model the Account
  //       tab totals from is what stops the two tabs disagreeing.
  //
  //   Net Winnings                          UNRESOLVED. S8-P3 proved season
  //       winnings has no posted door. WP3B's Standings does publish a
  //       competitive NET, and it is deliberately NOT substituted here: that
  //       figure excludes allocation and Top-Offs by construction, so it means
  //       something different from what this label promises. The cell keeps its
  //       place and draws unresolved rather than carrying a near-miss.
  //
  //   THE RANK IS GONE (§8.3) — removed, not unresolved. It was never this
  //   cell's to carry and Standings answers it properly now.
  const unresolved = production;
  composer.addStrip({
    id: 'fs-strip-league',
    label: 'Play summary',
    cells: [
      // UIRECON WAVE 1 — LABELS ARE HELD TO ONE LINE, AND THAT IS A MEASUREMENT.
      //
      // `Net Winnings` and `Weekly Min Left` each wrapped to two lines at both
      // 375x667 and 390x844, and because grid rows stretch to the tallest cell
      // that made EVERY cell in the strip 75.38px instead of 59.78px — 15.6px
      // taken off the panel below by two labels that were unreadable on one
      // line anyway. The primitive now refuses to wrap, so the labels are
      // reworded to fit rather than truncated.
      //
      // THE BUDGET IS THE 320px CELL, which is 68px wide once the label
      // reclaims the cell's horizontal padding. Measured in the browser at the
      // rendered 13px: `Net Won` 52px, `Min Left` 48.2px. `Wallet` and
      // `Available` already fitted and are untouched.
      { label: 'Net Won',
        cents: production ? 0 : ILLUSTRATIVE.netWinningsCents,
        signed: true,
        pending: unresolved },
      { label: 'Wallet',
        cents: production ? (boundWalletFigure() ?? 0) : ILLUSTRATIVE.walletCents,
        pending: production && boundWalletFigure() === null },
      { label: 'Min Left',
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

  // WP3D — PLAY DISPLAYS YAHOO FANTASY INFORMATION, so it carries the exact
  // attribution. The league's own name is the provider's once a refresh has
  // bound it; every opponent on the rail is a provider-given team name; the
  // week and phase in the header are the provider's current week; and the
  // market board behind each card is simulated over provider-given starters
  // and projections.
  //
  // WHAT THE LINE DOES NOT CLAIM is everything FantasyStakes generates on this
  // same surface — the moneyline, the spread, the total, the Pool draw, the
  // Credits in the strip. It is a source disclosure at the foot of the page,
  // not a label attached to any figure.
  //
  // ── THE PLAY DECK — RC4 MOBILE RECONCILIATION ────────────────────────────
  //
  // WHAT WAS HERE, AND WHY IT FAILED ON A REAL PHONE. The two zones split
  // whatever height the panel had left, at `flex: 1 1 0` each, and each zone's
  // rail took what its own heading did not. Measured on the deployed RC4 build
  // at 320x568: the Matchups zone was 133.11px, its heading block 88.59px of
  // that, and the rail 44.52px — for a card whose content is 155px. The card
  // did not shrink and could not: `.fs-carousel__item` carries
  // `min-height: 100%`, so it grew to its content and the rail clipped it a
  // third of the way down, exactly where the PROP POOLS heading begins. That is
  // the "Matchup card runs under the Prop Pools section" report, and the earlier
  // certification could not see it because it compared the card to the ITEM and
  // the item to the RAIL — never the rail to the card.
  //
  // A HEIGHT NEGOTIATION IS THE WRONG SHAPE FOR THIS SURFACE. Two card zones
  // cannot both be given a complete card out of 276px of panel; the fixed
  // quantity is the CARD, and the screen has to yield to it. So the deck below
  // is sized by its content and the surface scrolls vertically when a phone is
  // too short — the same construction Wrap Up has used since Wave 4B, and the
  // reason Wrap Up never produced this defect.
  //
  // `.fs-playdeck` IS WHAT MAKES THE TWO CARD FAMILIES ONE SIZE. It is a grid
  // of four rows — heading, rail, heading, rail — and the two rail rows are a
  // matched pair of `minmax(0, 1fr)`, so they resolve to the SAME height at
  // every width, whichever family's content is taller. Neither zone contributes
  // a box of its own (`display: contents`), which is what keeps a heading out
  // of its rail's track: Matchups carries a refresh control and a stamp that
  // Prop Pools does not, and equal ZONES would therefore have produced unequal
  // RAILS. See `gameplay.css` — "PARALLEL CARD GEOMETRY".
  //
  // THE ATTRIBUTION LEAVES THE POOLS ZONE. It ended that zone because a block
  // after the zones took height from both of them, and at 375x667 the Matchup
  // card had none to give. The deck no longer negotiates height with anything,
  // so the source line goes back where it reads correctly: after both sections,
  // last on the surface, one instance, inside the scroll and above the nav.
  composer.add(
    '<div class="fs-zones">' +
    '<div class="fs-playdeck">' +
    `<div class="fs-zone fs-zone--bets">${versusZone()}</div>` +
    `<div class="fs-zone fs-zone--pools">${poolsZone()}</div>` +
    '</div>' +
    attributionFooter() +
    '</div>',
  );

  return composer.toHTML();
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

/* ── Versus discovery ───────────────────────────────────────────────────────*/

/**
 * The empty states, in product language. Rev 4.3 §27 — no reason codes, no
 * internal identifiers, and a different sentence for each different fact.
 */
const VERSUS_COPY = Object.freeze({
  [VERSUS_STATE_NO_DATA]: {
    heading: 'No opponents yet',
    body: 'Your league’s teams appear here once the league is set up and its '
      + 'roster is known.',
  },
  [VERSUS_STATE_UNAVAILABLE]: {
    heading: 'Opponents unavailable',
    body: 'We could not read your league’s teams just now. Nothing is shown '
      + 'rather than a guess.',
  },
  [VERSUS_STATE_FIELD_UNKNOWN]: {
    heading: 'Postseason field not settled yet',
    body: 'Matchups are limited to teams still alive on the championship track. '
      + 'That field is not confirmed for this week yet, so no matchups are '
      + 'offered.',
  },
  [VERSUS_STATE_NONE_ELIGIBLE]: {
    heading: 'No Matchups this week',
    body: 'Only teams still on the championship track can be played in the '
      + 'postseason. Prop Pools stay open to you either way.',
  },
});

/**
 * One opponent's discovery card.
 *
 * IDENTITY, THEN PREVIEW, THEN MARKETS — Rev 4.3 §9's locked hierarchy, and the
 * reason the preview row is emitted before the market row rather than after it.
 * The distinction the POR draws is real: the preview answers "why does this
 * matchup look this way?" and the markets answer "what do I want to play?", so
 * the question comes before the answer.
 *
 * THE MARKET CELLS CARRY NO QUOTE HERE. Rev 4.2 printed ML / SPR / O/U per
 * opponent from the fixture. A real quote is produced by the pricing engine for
 * one specific pairing at composition time, and no read model publishes a board
 * of them; the cells therefore name the three markets and the composer prices
 * the one that is chosen. That is why they are labelled and not valued.
 *
 * NO FOOT ROW, AND THAT IS BOTH A POR DECISION AND A MEASURED ONE. §9's locked
 * hierarchy is identity → preview → markets → supporting content; a
 * `Challenge ›` foot is not in it, and it offered a third way to reach a
 * composer the two rows above already reach. It also cost 40px, which at
 * 375x667 was the difference between a card that fits its rail and one that
 * clips its own markets — the four controls on the card are all focusable, so
 * removing it costs no keyboard path either.
 *
 * @param {{teamId: number, name: string, owner: string}} opponent
 * @returns {string}
 */
/**
 * What one market cell reads for this pairing.
 *
 * FORMATTING ONLY. Each branch picks a served field and hands it to an existing
 * formatter. Nothing is derived: there is no sign flip here, no rounding, no
 * fallback that would put a number on a cell the server left unpriced.
 *
 * `Play ›` is the honest label when there is no board at all — the demo
 * composer and any session whose board read failed. It invites the tap that
 * prices the market rather than asserting a price nobody quoted.
 *
 * @param {string} marketId ml | spread | ou
 * @param {object|null} board a served VersusMarketOut
 * @param {boolean} priced
 * @returns {string}
 */
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

function versusCard(opponent) {
  const id = escapeHtml(String(opponent.teamId));
  // WP3C.2 — THE CELLS NOW CARRY THE SERVER'S OWN LINES.
  //
  // The comment above described a build with no market read model. There is one
  // now, so the three cells show what FantasyStakes is actually offering:
  // moneyline, the acting GM's sportsbook-signed spread, and the total.
  //
  // EVERY VALUE IS SERVED. `acting_spread` already carries its sign — the
  // server negated the canonical threshold once, in `odds/market_lines`, and
  // this reads the result. `formatSpread` and `formatOdds` decide only how a
  // number is drawn. A pairing the model cannot price keeps the unresolved dash
  // rather than showing a zero that would read as a pick'em.
  const board = marketFor(opponent.teamId);
  const priced = Boolean(board && board.available);
  const cells = MARKETS.map((market) => (
    `<button type="button" class="fs-market" data-market="${escapeHtml(market.id)}">`
    + `<span class="fs-market__label">${escapeHtml(market.short)}</span>`
    + `<span class="fs-market__value">${escapeHtml(marketCellValue(market.id, board, priced))}</span>`
    + '</button>'
  )).join('');

  // WP3E-FIX3 — THE CARD IS A CONTAINER OF ACTIONS, AND EACH ACTION IS NATIVE.
  //
  // This card holds five distinct actions: challenge, preview, and three
  // markets. WP3E-FIX2 made the whole wrapper `role="button" tabindex="0"` to
  // give the challenge a keyboard path, which worked and was the wrong shape —
  // an ARIA button containing four real buttons is content assistive
  // technology is not obliged to expose consistently, because a button's
  // children are specified as presentational.
  //
  // So the wrapper carries NO role and NO tabindex, and the challenge gets a
  // control of its own: a real `<button>` that Tab reaches, Enter and Space
  // activate for free, and nothing has to re-implement.
  //
  // WHY THE BUTTON WRAPS THE NAME AND THE OWNER. It needs a 44px target, and
  // where that comes from was decided by measurement rather than by preference.
  // The identity line alone is 20px; padding it out to 44 would have pushed an
  // invisible hit area down across the preview row beneath it, or up into the
  // card above. Identity plus owner already measures 42px — two short — so the
  // button takes both and a `min-height` closes the gap. Both are spans, so
  // this stays phrasing content and the button stays valid HTML.
  //
  // A card with no owner keeps the same 44px head, which means the head is one
  // consistent height whether or not the server supplied an owner. That is a
  // side effect and a welcome one.
  //
  // THE NAME IS EXPLICIT, and that is a deliberate exception to preferring
  // visible text. The button's own contents are the opponent and the owner —
  // who, but not what. `Challenge {opponent}` says both, in the length of a
  // label rather than a sentence.
  const label = `Challenge ${escapeHtml(opponent.name)}`;

  return (
    `<div class="fs-wcard fs-wcard--matchup is-tappable" `
    + `data-card-action="challenge" data-card-id="${id}">`
    + '<div class="fs-wcard__head">'
    + '<button type="button" class="fs-wcard__challenge" '
    + `data-card-challenge="${id}" aria-label="${label}">`
    + `<span class="fs-wcard__identity">${escapeHtml(opponent.name)}</span>`
    + (opponent.owner
      ? `<span class="fs-wcard__context">${escapeHtml(opponent.owner)}</span>`
      : '')
    + '</button>'
    // THE PER-CARD REFRESH, in the head's trailing slot.
    //
    // `.fs-wcard__head` is a `space-between` row whose first child is the
    // challenge button, so a second child lands hard right — the upper-right
    // corner, where a market-refresh control belongs and where it collides with
    // nothing. It is INSIDE the head and OUTSIDE the challenge button, because
    // a button inside a button is invalid HTML and would make the refresh
    // unreachable by keyboard.
    + (marketMode() === 'authoritative'
      ? refreshControl({
        scope: 'pairing',
        target: opponent.teamId,
        label: `Refresh odds for ${opponent.name}`,
        extraClass: 'fs-oddsref--card',
      })
      : '')
    + '</div>'
    // §9 — a clear FULL-WIDTH action row, directly above the markets.
    + '<button type="button" class="fs-previewrow" '
    + `data-preview-opponent="${id}">VIEW MATCHUP PREVIEW</button>`
    + `<div class="fs-markets">${cells}</div>`
    + '</div>'
  );
}

function versusZone() {
  const state = versusState();

  if (state !== VERSUS_STATE_READY) {
    const copy = VERSUS_COPY[state] || VERSUS_COPY[VERSUS_STATE_NO_DATA];
    return (
      sectionHeading(MATCHUPS_HEADING)
      + `<div class="fs-emptyzone" data-versus-state="${escapeHtml(state)}">`
      + `<div class="fs-emptyzone__head">${escapeHtml(copy.heading)}</div>`
      + `<p class="fs-emptyzone__body">${escapeHtml(copy.body)}</p>`
      + '</div>'
    );
  }

  const count = playableCount();
  const cards = playableOpponents()
    .map((o) => `<div class="fs-carousel__item" role="listitem">${versusCard(o)}</div>`)
    .join('');

  // THE COUNT AND THE AFFORDANCE GO IN THE HELPER SLOT, not the heading.
  //
  // `sectionHeading(text, helper)` has always had two slots and Rev 4.2 put
  // everything in the first, because at 9px the whole string fitted one line.
  // At the §5.1 section step it wraps to two, and on Play a two-line heading
  // comes straight out of the card zone beneath it. The helper renders at the
  // metadata step beside it, which is what it is for and what §5's "fewer
  // readable facts" asks for.
  return (
    sectionHeading(MATCHUPS_HEADING,
      `${count} OPPONENT${count === 1 ? '' : 'S'} · ${SWIPE_WORD}`,
      boardRefreshControl() + boardRefreshStamp())
    + `<div class="fs-carousel" id="fs-bets-carousel" role="list">${cards}</div>`
  );
}

/* ── Pools ──────────────────────────────────────────────────────────────────*/

/**
 * The week's Pool rows — the governed draw, or the demo fixture.
 *
 * THE SAME GATE `week.js` ALREADY USED. Play was the one surface still reading
 * the static four-Pool constant in production; this brings it onto the slate
 * the Pool engine actually drew.
 *
 * @returns {Array<object>}
 */
function poolRows() {
  return slateMode() === SLATE_MODE_DEMO ? POOLS : slateRows();
}

/**
 * One Pool card, sized for the carousel — Rev 1.4 Part 4.
 *
 * WHY THE 2×2 GRID WENT. Four Pools shared one zone as quarter-tiles, and the
 * consequence was structural rather than aesthetic: a quarter of a phone holds
 * a two-line clamped name and nothing else, which is why Rev 4.3 §8.5 had to
 * move the definition's settle condition off the card and into the sheet. The
 * card could show WHICH Pool but never WHAT it asks, so the only way to learn
 * what a contest measured was to open it — four times.
 *
 * Rev 1.4 gives the catalog a `public_question`, and a question needs a line to
 * sit on. One card at a time is what buys that line.
 *
 * THE SAME CAROUSEL AS THE MATCHUPS ABOVE, LITERALLY. The card is placed in
 * `.fs-carousel__item` inside `.fs-carousel` — the identical elements the
 * Matchups rail uses, not a parallel implementation that agrees today. So the
 * outer width, the item width, the gutter, the horizontal snap, the gesture,
 * the hidden scrollbar and the "never half a card" guarantee are the same rules
 * and cannot drift apart.
 *
 * AND SINCE RC4 THE OUTER HEIGHT IS SHARED TOO, which reuse alone did not give:
 * each rail took the height its own zone had left, so the Pool card measured
 * 135.97px against the Matchup card's 155px in adjacent sections. Both rails
 * are now a matched pair of grid tracks, so the two families are one size by
 * construction. Only the card's INSIDE is Pool-specific, which is what §4 asks
 * for.
 *
 * WHAT THE CARD STILL CARRIES. The TEAM/MATCHUP badge and the ROLLOVER
 * modifier on it — a rolling Pool is not a different kind of Pool — the entry,
 * the entered count and the pot, with the carried pot still marked. Nothing was
 * dropped to make room; the room came from the layout.
 *
 * @param {object} pool
 * @returns {string}
 */
function poolCard(pool) {
  const badge = poolBadge(pool);
  const badgeClass = pool.scope === 'TEAM' ? 'is-team' : 'is-matchup';
  const entered = typeof pool.entered === 'number'
    ? `${pool.entered} in` : PENDING_FIGURE;

  return (
    `<button type="button" class="fs-pool fs-pool--card" `
    + `data-pool="${escapeHtml(String(pool.catalogNumber))}">`
    + '<span class="fs-pool__head">'
    + `<span class="fs-pool__badge ${badgeClass}${pool.continuation ? ' is-rollover' : ''}">`
    + `${escapeHtml(badge)}</span>`
    + '</span>'
    + `<span class="fs-pool__name">${escapeHtml(pool.name)}</span>`
    // THE QUESTION IS THE CARD'S SUBTITLE, and it is the server's sentence.
    // `poolQuestion` prefers the catalog's `public_question` and falls back to
    // the scope-derived prompt only where the catalog carries none.
    + `<span class="fs-pool__question${hasPoolQuestion(pool) ? '' : ' is-missing'}"`
    + `${hasPoolQuestion(pool) ? '' : ' data-question-missing'}>`
    + `${escapeHtml(poolQuestion(pool))}</span>`
    + '<span class="fs-pool__foot">'
    + `<span class="fs-pool__entry">${escapeHtml(formatCredits(pool.entryCents))}`
    + ` · ${escapeHtml(entered)}</span>`
    + `<span class="fs-pool__pot${pool.continuation ? ' is-carried' : ''}" `
    + `data-exact-cents="${pool.potCents}">${escapeHtml(formatCredits(pool.potCents))}</span>`
    + '</span>'
    + '</button>'
  );
}

function poolsZone() {
  const rows = poolRows();

  if (rows.length === 0) {
    // NO SLATE IS AN ORDINARY STATE (§8.5, and `pool-slate-model`'s own note):
    // four definitions must pass both gates for a week to be drawn, and gate 2
    // is a per-league provider measurement. Four Pools are not invented to fill
    // the grid.
    const undrawn = slateMode() === 'undrawn';
    return (
      sectionHeading(POOLS_HEADING)
      + `<div class="fs-emptyzone" data-pools-state="${escapeHtml(slateMode())}">`
      + `<div class="fs-emptyzone__head">${
        undrawn ? 'No Pools drawn yet' : 'Pools unavailable'}</div>`
      + `<p class="fs-emptyzone__body">${escapeHtml(undrawn
        ? 'This week’s Pools are drawn once enough of the catalog is supported '
          + 'for your league. Nothing is shown until then.'
        : 'We could not read this week’s Pools just now.')}</p>`
      + '</div>'
    );
  }

  // THE COUNT IS THE SERVED ONE. `poolRows()` is the drawn slate in production
  // and the illustrative fixture in demo; either way it is what the surface is
  // about to render, so the heading cannot claim a week has four Pools while
  // showing three.
  const cards = rows
    .map((p) => `<div class="fs-carousel__item" role="listitem">${poolCard(p)}</div>`)
    .join('');

  return (
    sectionHeading(POOLS_HEADING, `${rows.length} THIS WEEK · ${SWIPE_WORD}`)
    + `<div class="fs-carousel" id="fs-play-pools" role="list">${cards}</div>`
  );
}

/* ── Binding ────────────────────────────────────────────────────────────────*/

/**
 * Wire Play's three tap paths.
 *
 * A market cell opens the composer with that market selected; the preview row
 * opens the Matchup Preview; anywhere else on the card opens the composer with
 * no market selected. The two inner handlers stop propagation, so one tap never
 * does two things.
 *
 * THE CARD ID IS THE OPPONENT'S REAL TEAM ID in production, which is what makes
 * the composer's target authoritative rather than a name lookup.
 *
 * @param {HTMLElement} panel
 * @param {{openComposer: Function, openSheet: Function}} api
 */
export function bindLeague(panel, api) {
  // THE ODDS-REFRESH CONTROLS BIND FIRST, and by delegation from the panel
  // rather than per control. Play is redrawn on every authoritative refresh and
  // each redraw replaces the card elements underneath; a listener attached to a
  // button would be gone after the first one. `bindPlayOddsRefresh` is
  // idempotent, so calling it on every build costs one dataset read.
  bindPlayOddsRefresh(panel);

  panel.querySelectorAll('[data-card-action="challenge"]').forEach((card) => {
    const cardId = card.dataset.cardId;

    const preview = card.querySelector('[data-preview-opponent]');
    if (preview) {
      preview.addEventListener('click', (event) => {
        event.stopPropagation();
        if (api.openPreview) api.openPreview({ opponentId: cardId });
      });
    }

    card.querySelectorAll('[data-market]').forEach((cell) => {
      cell.addEventListener('click', (event) => {
        event.stopPropagation();
        api.openComposer({ matchupId: cardId, marketId: cell.dataset.market });
      });
    });

    // THE CHALLENGE ACTION HAS ITS OWN NATIVE CONTROL, and it is the only path
    // a keyboard user needs. `<button>` gives Enter and Space for nothing, so
    // there is no key handling here to get wrong.
    //
    // IT STOPS ITS OWN CLICK, like every other control in this card. Without
    // that the click would reach the card behind it and open the composer a
    // second time.
    const challenge = card.querySelector('[data-card-challenge]');
    if (challenge) {
      challenge.addEventListener('click', (event) => {
        event.stopPropagation();
        api.openComposer({ matchupId: cardId, marketId: null });
      });
    }

    // AND THE CARD KEEPS ITS POINTER CONVENIENCE. Tapping the empty space of a
    // card still opens the composer, which is how this surface has always
    // behaved on a phone. It is a POINTER affordance only — every one of the
    // card's five actions has its own control, so no keyboard user depends on
    // this handler and the card is not a tab stop.
    card.addEventListener('click', () => api.openComposer({
      matchupId: cardId, marketId: null }));
  });

  panel.querySelectorAll('[data-pool]').forEach((el) => {
    el.addEventListener('click', () => {
      const pool = poolRows().find(
        (p) => String(p.catalogNumber) === el.dataset.pool);
      if (pool) api.openSheet(poolSheet(pool));
    });
  });
}

/**
 * The Pool-detail sheet. Exported so Wrap Up opens the same detail for the same
 * Pool. A week may layer state on top — a settled Pool carries its outcome —
 * but the definition, the rule and the catalog number are always the catalog's.
 *
 * THIS IS WHERE THE FULL EXPLANATION LIVES (§8.5). The compact card was trimmed
 * to type, name, entry and pot; everything it dropped is here, in full, at a
 * size that can be read.
 *
 * @param {object} pool
 * @returns {{title: string, sub: string, body: string}}
 */
/**
 * §29's Fantasy Football drivers for a Prop Pool.
 *
 * UI-5 GAP 2 CLOSED. §29 asks a Pool expansion for *concise FF drivers plus
 * Pool/market analysis*. The Pool half was there -- the question, the settle
 * rule, the entry, the pot, the count entered -- and the football half was not,
 * so a reader learned what they were being asked and nothing about the field it
 * would be answered on.
 *
 * EVERY LINE BELOW IS SLATE CONTENT ALREADY PUBLISHED. The metric expression is
 * the catalog's own settle condition; the scope is the catalog's; the subjects
 * are the admissible ones the pick control already renders, so naming them here
 * discloses nothing that was not already on the screen. Nothing is derived from
 * a projection, because the slate carries none.
 *
 * WHAT IT DELIBERATELY DOES NOT SAY IS WHO IS WINNING. An open Pool has no
 * standing -- the metric is evaluated at settlement by the Pool engine, and a
 * running order computed in the browser would be a second evaluation that could
 * disagree with the one that pays. A settled Pool shows the winners settlement
 * actually wrote, which is a read rather than a computation.
 *
 * @param {object} pool a slate row
 * @returns {string}
 */
function poolFootballDrivers(pool) {
  const rows = [];
  const row = (label, value) => (
    '<div class="fs-prev__row">' +
    `<span class="fs-prev__label">${escapeHtml(label)}</span>` +
    `<span class="fs-prev__value">${escapeHtml(value)}</span></div>`
  );

  // WHAT ON THE FIELD DECIDES IT. `rule` is the definition's metric
  // expression; the em dash is the slate's own "the catalog carries none".
  if (pool.rule && pool.rule !== '\u2014') rows.push(row('Decided by', pool.rule));

  rows.push(row('Measured across',
    pool.subject === 'matchup'
      ? 'One fantasy matchup'
      : 'Every fantasy team in the league'));

  const subjects = Array.isArray(pool.subjects) ? pool.subjects : [];
  if (subjects.length) {
    rows.push(row('In contention', String(subjects.length)));
  }

  // THE WINNERS ARE SETTLEMENT'S, and only a settled Pool has any.
  if (pool.settled && Array.isArray(pool.winningSubjects)
      && pool.winningSubjects.length) {
    rows.push(row(pool.winningSubjects.length > 1 ? 'Winners' : 'Winner',
      pool.winningSubjects.join(', ')));
  }

  if (!rows.length) return '';

  return (
    '<div class="fs-rule__head">FANTASY FOOTBALL DRIVERS</div>' +
    rows.join('') +
    (pool.settled
      ? ''
      // SAID PLAINLY, because "who is ahead" is the first thing a reader looks
      // for and its absence would otherwise read as a page that failed to load.
      : '<div class="fs-note">No running order is shown while a Pool is open. '
        + 'The metric is evaluated once, at settlement, by the Pool engine \u2014 '
        + 'a standing computed here could disagree with the one that pays.</div>')
  );
}

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
      // UIRECON WAVE 3B — THE QUESTION, WHERE THE SCOPE ENUM USED TO BE.
      //
      // A row reading `Subject · Matchup` stood here. It named the census scope
      // the engine validates against, which is a true fact and not one a GM
      // asked for, and it was the same word the pick control below used as its
      // caption — so the sheet introduced itself with an enum twice. What a GM
      // needs before choosing is what they are being asked, and that is derived
      // from the served scope rather than invented.
      `<p class="fs-poolq">${escapeHtml(poolQuestion(pool))}</p>` +
      // FOOTBALL FIRST, THEN THE MARKET. §29 lists the FF drivers before the
      // Pool analysis, and it reads in that order too: what is being played
      // for on the field, and then what it costs and pays.
      poolFootballDrivers(pool) +
      '<div class="fs-prev__row"><span class="fs-prev__label">Settles on</span>' +
      `<span class="fs-prev__value fs-money">${escapeHtml(pool.rule)}</span></div>` +
      '<div class="fs-prev__row"><span class="fs-prev__label">Entry</span>' +
      `<span class="fs-prev__value fs-money" data-exact-cents="${pool.entryCents}">` +
      `${escapeHtml(formatCredits(pool.entryCents))}</span></div>` +
      // S8-P4B-3R noted that `entered` — a count of entries — lived in
      // `pool_claim` with no read model publishing it, so the em dash was the
      // approved unresolved treatment. WP6C published it: the slate now carries
      // a claim COUNT, not a roster, so the row resolves without disclosing who
      // picked what. The em dash remains for demo rows, which have no
      // occurrence and therefore no count.
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
          'A pick is a claim, not a stake — submitting one moves no Credits.</div>') +
      poolPickControl(pool),
    onMount: POOL_SHEET_MOUNT,
  };
}

/* ── WP6C · the governed pick control ───────────────────────────────────────*/

/**
 * The Pool sheet's mount hook.
 *
 * Set by the shell, which is the only thing that knows the acting league, the
 * acting team, the authoritative week and how to refresh afterwards. NULL in
 * demo mode and for any session whose slate did not bind — and a null hook
 * means no control is wired, which is the same rule the Action surfaces follow:
 * a GM whose state could not be read must not be offered a button, because
 * neither they nor the page knows what it would submit.
 *
 * @type {((host: HTMLElement, api: object) => void)|null}
 */
let POOL_SHEET_MOUNT = null;

/** @param {((host: HTMLElement, api: object) => void)|null} fn */
export function setPoolSheetMount(fn) {
  POOL_SHEET_MOUNT = fn;
}

/**
 * The subject picker, or the reason there isn't one.
 *
 * DRAWN FROM THE SERVER'S OWN ANSWER, never from a client-side rule. The
 * options are the subjects the occurrence admits — the census set
 * `pool_claims._validate_subject` checks against — and `openForClaims` is the
 * server's judgement on whether a submission could be accepted. Neither decides
 * anything: `submit_claim` refuses regardless of what was drawn. Drawing the
 * closed state rather than offering a control that is certain to be refused is
 * a courtesy, not a permission.
 *
 * @param {object} pool a row from `slateRows()`
 * @returns {string}
 */
function poolPickControl(pool) {
  // Demo rows carry no occurrence, so there is nothing to claim against and no
  // control is drawn. The illustrative cards were never a pick surface.
  if (typeof pool.poolInstanceId !== 'number') return '';

  const current = typeof pool.mySubjectId === 'number'
    ? (pool.subjects.find((s) => s.subject_id === pool.mySubjectId) || null)
    : null;

  // ALWAYS DRAWN, even with no claim yet, and the em dash is the accepted
  // unresolved treatment. It is also where a successful submission writes the
  // server's confirmed subject, so the row has to exist before the press —
  // a confirmation with nowhere to land is one the GM never sees.
  const held =
    '<div class="fs-prev__row"><span class="fs-prev__label">Your pick</span>' +
    `<span class="fs-prev__value" id="fs-poolpick-held">` +
    `${current ? escapeHtml(current.label) : PENDING_FIGURE}</span></div>`;

  if (pool.settled) return held;

  if (!pool.openForClaims) {
    return held + '<div class="fs-note is-warn">'
      + (pool.locked
        ? 'This week’s Pools are locked. The window closes at the week’s first '
          + 'kickoff, and the server holds that moment — not this page.'
        : 'This Pool is not accepting picks.')
      + '</div>';
  }

  // NOTHING TO CHOOSE FROM IS A REAL STATE. The census can admit no subjects —
  // an unplayed week, a scope the league cannot fill — and the server says so
  // by serving an empty list. Offering an empty grid and a Submit button would
  // be offering a press that is certain to be refused.
  if (!pool.subjects.length) {
    return held + '<div class="fs-note is-warn">No eligible '
      + escapeHtml(pool.subject) + 's for this week yet.</div>';
  }

  // ── THE CHOICE CELLS — UIRECON Wave 3B ───────────────────────────────────
  //
  // WHAT THIS REPLACES. A native `<select>` inside a `.fs-setform` that had no
  // CSS in any stylesheet — so the one control in the product that takes a
  // governed Prop Pool claim rendered as an unstyled user-agent dropdown on the
  // app's near-black ground, captioned with a scope enum. It was the least
  // usable control on the most playable surface.
  //
  // IT IS THE WAVE 1 CHOICE CELL. The same `.fs-seg__opt` a GM taps to pick a
  // market or a set of terms, with the same geometry, the same 44px floor, the
  // same gold selected treatment and the same `aria-pressed` grammar. A pick is
  // a pick wherever the product asks for one.
  //
  // EVERY OPTION IS THE SERVER'S. `subject_id` and `label` are carried straight
  // from `PoolSlotOut.subjects`, which the read model projects from the same
  // census `pool_claims._validate_subject` checks a submission against. Nothing
  // here enumerates a team, names a matchup, or filters the list.
  const cells = pool.subjects.map((s) => {
    const selected = Boolean(current && current.subject_id === s.subject_id);
    return (
      '<button type="button" class="fs-seg__opt is-wrap'
      + (selected ? ' is-selected' : '') + '" '
      + `data-poolpick-subject="${escapeHtml(String(s.subject_id))}" `
      + `aria-pressed="${selected}">`
      + `<span class="fs-seg__label">${escapeHtml(s.label)}</span>`
      + '</button>'
    );
  }).join('');

  // ONE COLUMN FOR MATCHUPS, TWO FOR TEAMS, and the served scope decides. A
  // matchup label names both sides — `Gravy Train vs The Braintrust` — and does
  // not fit half a phone; a team name does.
  const columns = pool.scope === 'MATCHUP' ? 'is-single' : 'is-double';

  return (
    `<form class="fs-poolpick" id="fs-poolpick-form" `
    + `data-instance="${pool.poolInstanceId}">`
    + `<div class="fs-poolpick__grid ${columns}" role="group" `
    + `aria-label="${escapeHtml(poolQuestion(pool))}">${cells}</div>`
    + held
    + '<button type="submit" class="fs-btn fs-btn--gold fs-poolpick__save" '
    + `id="fs-poolpick-save">${current ? 'Change Pick' : 'Submit Pick'}</button>`
    + '<p class="fs-poolpick__error" id="fs-poolpick-error" role="alert" '
    + 'aria-live="polite"></p>'
    + '</form>'
  );
}

/**
 * The neutral state for a drawable Pool that arrived without its question.
 *
 * IT DESCRIBES THE ABSENCE, NOT THE CONTEST. Every word that could pass for
 * product copy about what a GM is picking is exactly what must not be here: the
 * point of removing the derivation is that this file no longer has an opinion
 * about what any Pool asks. Four words that say a governed field is missing are
 * honest; a sentence a GM could mistake for the question is not.
 */
export const MISSING_QUESTION_TEXT = 'Question unavailable';

/**
 * Drawable Pools seen without a `public_question`, for the integrity path.
 *
 * A SET, NOT A COUNTER, so a test can name the offender. Cleared by nothing:
 * the register is per-page-load and a single occurrence is the whole signal.
 * @type {Set<string>}
 */
const MISSING_QUESTIONS = new Set();

/**
 * Which drawable Pools have rendered without a governed question this session.
 *
 * EXPOSED SO THE DEFECT IS OBSERVABLE rather than only visible. A card that
 * quietly drew a neutral placeholder would look like a design choice; this is
 * what lets a certification assert that it never happens, and what a developer
 * reads when it does.
 *
 * @returns {string[]} definition keys or catalog numbers, ascending
 */
export function missingPoolQuestions() {
  return [...MISSING_QUESTIONS].sort();
}

/**
 * What this Prop Pool is asking — the CATALOG'S sentence, and ONLY that.
 *
 * ── THE DERIVATION IS GONE, NOT DEMOTED ─────────────────────────────────────
 *
 * Wave 3 composed this sentence from `scope`, because the catalog held no
 * written question and no field was to be invented here to supply one. POR
 * Rev 1.4 §3 added `public_question` as governed catalog content and the
 * derivation was left in place as a fallback. That fallback is now REMOVED for
 * every Pool a league can draw.
 *
 * WHY A FALLBACK WAS THE WRONG SHAPE EVEN THOUGH IT NEVER FIRED. A client-side
 * generator that produces plausible product copy is indistinguishable, on the
 * surface, from the governed field it stands in for — so the one situation it
 * exists for, a Pool whose catalog data is broken, is precisely the situation in
 * which it hides the breakage. §3.2 makes the catalog the sole authority for
 * this sentence; a second author in the browser contradicts that whether or not
 * it is preferred.
 *
 * SO A MISSING QUESTION IS AN INTEGRITY EVENT. It is registered, warned about
 * once per definition, and rendered as `MISSING_QUESTION_TEXT` — and the Play
 * tab keeps working, because a broken row must not cost a GM the other three.
 *
 * THE 16 NON-DRAWABLE DEFINITIONS ARE NOT THIS CASE. §7 leaves them without a
 * question on purpose; they are never drawn, so they never reach this function.
 *
 * EXPORTED FOR WRAP UP — RC4 MOBILE RECONCILIATION. The Prop Pool result card
 * carries the same sentence the Play card asks, and it must be the SAME
 * sentence from the SAME source: a second reader with its own preference is how
 * two surfaces come to describe one contest differently. Nothing about the rule
 * changes by being exported — the catalog is still the sole authority, a
 * missing question is still an integrity event, and there is still no client
 * that can compose one.
 *
 * @param {object} pool a row from `slateRows()` or the illustrative fixture
 * @returns {string}
 */
export function poolQuestion(pool) {
  if (pool && pool.question) return pool.question;

  const subject = String(
    (pool && (pool.definitionKey || pool.catalogNumber)) || 'unknown');
  if (!MISSING_QUESTIONS.has(subject)) {
    MISSING_QUESTIONS.add(subject);
    // ONE WARNING PER DEFINITION. The card renders on every panel build, and a
    // per-render warning would bury the first one under its own repetitions.
    if (typeof console !== 'undefined' && console.warn) {
      console.warn(
        `[FantasyStakes] Prop Pool ${subject} was drawn without a governed `
        + 'public_question. POR Rev 1.4 §3 makes the catalog the sole authority '
        + 'for this sentence, so none is composed here.');
    }
  }
  return MISSING_QUESTION_TEXT;
}

/** @returns {boolean} whether this row carries its governed question. */
function hasPoolQuestion(pool) {
  return Boolean(pool && pool.question);
}

/**
 * Bind the Pool pick form, wherever it is rendered.
 *
 * Called from the sheet's own mount rather than from `bindLeague`, because the
 * form lives inside the SHEET and the sheet is created after the panel binds —
 * the same reason `bindPoolEntryForm` is mounted that way.
 *
 * NO OPTIMISTIC CONFIRMATION. The control reports success only after the
 * governed write has returned, and what it then displays is the SERVER's
 * persisted claim rather than the value the GM chose. That distinction is the
 * whole point of WP6C: the old surface confirmed a pick the settlement engine
 * could not see.
 *
 * @param {HTMLElement} host the sheet element
 * @param {{leagueId: number, teamId: number, week: number,
 *          submit: Function, explain: Function,
 *          onClaimed: (body: object) => void}} ctx
 */
export function bindPoolPickForm(host, ctx) {
  const form = host.querySelector('#fs-poolpick-form');
  if (!form) return;

  const save = form.querySelector('#fs-poolpick-save');
  const error = form.querySelector('#fs-poolpick-error');
  const held = host.querySelector('#fs-poolpick-held');
  const cells = [...form.querySelectorAll('[data-poolpick-subject]')];
  let inFlight = false;

  /** The pressed cell's served subject id, or NaN when none is pressed. */
  const chosen = () => {
    const pressed = cells.find((c) => c.getAttribute('aria-pressed') === 'true');
    return pressed
      ? Number.parseInt(pressed.dataset.poolpickSubject, 10) : Number.NaN;
  };

  // SELECTING IS LOCAL; SUBMITTING IS GOVERNED. Pressing a cell moves the
  // selection and updates `Your pick` so the GM can see what they are about to
  // send — it posts nothing. The claim is written only by the submit handler
  // below, through the same governed command as before.
  cells.forEach((cell) => {
    cell.addEventListener('click', () => {
      if (inFlight) return;
      cells.forEach((other) => {
        const isThis = other === cell;
        other.classList.toggle('is-selected', isThis);
        other.setAttribute('aria-pressed', String(isThis));
      });
      // `Your pick` FOLLOWS THE SELECTION, AND SAYS IT IS NOT YET SENT.
      //
      // WP6C's rule is that a CONFIRMATION must be the server's persisted
      // claim and never the value the GM chose, and that rule is kept below.
      // This is a different statement: it is what the GM is about to submit,
      // which they are entitled to read before pressing. `is-pending` is what
      // keeps the two apart on screen — the row is drawn as unresolved until
      // the governed write returns and rewrites it from `selected_subject_id`.
      if (held) {
        held.textContent = cell.querySelector('.fs-seg__label').textContent;
        held.classList.add('is-pending');
      }
      error.textContent = '';
      save.textContent = 'Submit Pick';
    });
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (inFlight) return;

    error.textContent = '';
    const subjectId = chosen();
    if (!Number.isInteger(subjectId)) {
      error.textContent = 'Choose one first.';
      return;
    }

    inFlight = true;
    save.disabled = true;
    save.textContent = 'Submitting…';
    try {
      const body = await ctx.submit({
        leagueId: ctx.leagueId,
        teamId: ctx.teamId,
        week: ctx.week,
        poolInstanceId: Number.parseInt(form.dataset.instance, 10),
        subjectId,
      });
      // THE CONFIRMATION IS THE SERVER'S. The cell matched below is found by
      // `selected_subject_id` — what was PERSISTED — not by the value the GM
      // chose. The two agree on every success, and on the one occasion they
      // would not, the GM is shown what the database holds. The only thing that
      // changed in Wave 3B is where the label is read from: the pressed choice
      // cell rather than a `<select>` option.
      const confirmed = cells.find((c) => Number.parseInt(
        c.dataset.poolpickSubject, 10) === body.selected_subject_id);
      if (held && confirmed) {
        held.textContent = confirmed.querySelector('.fs-seg__label').textContent;
        held.classList.remove('is-pending');
      }
      cells.forEach((c) => {
        const isConfirmed = c === confirmed;
        c.classList.toggle('is-selected', isConfirmed);
        c.setAttribute('aria-pressed', String(isConfirmed));
      });
      save.textContent = 'Pick recorded';
      ctx.onClaimed(body);
    } catch (refusal) {
      error.textContent = ctx.explain(refusal);
      save.disabled = false;
      save.textContent = 'Submit Pick';
    } finally {
      inFlight = false;
    }
  });
}
