/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.3 · Play
 * WP3C (was League, Sprint 7 Package 2)
 *
 * "What can I play?" — Rev 4.3 §4.
 *
 * TWO ZONES UNDER THE STRIP, and both Rev 4.2 shapes are deliberately kept:
 * FantasyStakes Versus is a vertical carousel presenting one card at a time,
 * and FantasyStakes Pools is a compact 2×2 grid. OR-3 preserved both, and
 * Rev 4.3 §8.5 is explicit that Play's Pools must NOT become Status-style
 * horizontal rails for the sake of cross-tab consistency.
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
import { marketFor } from './market-model.js';
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
  // IT ENDS THE POOLS ZONE RATHER THAN THE PANEL, AND THAT IS A MEASURED
  // DECISION. Play's two zones split whatever height the panel has left, and
  // at 375x667 the Versus carousel has exactly none to give: measured at HEAD,
  // the rail was 128px for a card that needs 128px. A block placed after the
  // zones takes its height from BOTH of them, and the wager card is the one
  // that cannot afford it — it clipped its own markets the moment the line was
  // added there. The Pools grid is compact and has the room, so the line ends
  // that zone instead. It is still the last thing on the surface, still one
  // instance, still above the bottom navigation.
  composer.add(
    '<div class="fs-zones">' +
    `<div class="fs-zone fs-zone--bets">${versusZone()}</div>` +
    '<div class="fs-zone fs-zone--pools">'
    + poolsZone() + attributionFooter() + '</div>' +
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
      sectionHeading('FANTASYSTAKES MATCHUPS')
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
    sectionHeading('FANTASYSTAKES MATCHUPS',
      `${count} OPPONENT${count === 1 ? '' : 'S'} · ${SWIPE_WORD}`)
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
 * One compact Pool card.
 *
 * ESSENTIAL INFORMATION ONLY — Rev 4.3 §8.5. The Rev 4.2 card carried the
 * definition's full settle condition as a line of microcopy under the name,
 * which at 2×2 on a phone was three lines of 8px text nobody could read. Type,
 * name, entry and pot/entries stay; the explanation moves to the detail sheet,
 * which is where §8.5 puts it and where it is already rendered in full.
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
    `<button type="button" class="fs-pool" data-pool="${escapeHtml(String(pool.catalogNumber))}">`
    + `<span class="fs-pool__badge ${badgeClass}${pool.continuation ? ' is-rollover' : ''}">`
    + `${escapeHtml(badge)}</span>`
    + `<span class="fs-pool__name">${escapeHtml(pool.name)}</span>`
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
      sectionHeading('FANTASYSTAKES PROP POOLS')
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

  return (
    sectionHeading('FANTASYSTAKES PROP POOLS', `${rows.length} THIS WEEK`)
    + `<div class="fs-pools" id="fs-pools-grid">${rows.map(poolCard).join('')}</div>`
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
 * What this Prop Pool is asking, composed from what the server served.
 *
 * DERIVED, NOT AUTHORED, AND DELIBERATELY SO. The catalog carries a display
 * name and a settle condition; it does not carry a written question, and Wave 3
 * is explicit that no catalog field may be added to invent one. So the sentence
 * is built from the served SCOPE — the same value that decides which subjects
 * the census admits — and the settle condition is shown in full on its own row
 * directly beneath. A GM reads what they are picking and what decides it,
 * without this file claiming to know anything the catalog did not say.
 *
 * @param {object} pool a row from `slateRows()`
 * @returns {string}
 */
function poolQuestion(pool) {
  return pool.scope === 'MATCHUP'
    ? 'Which matchup do you think takes this Prop Pool?'
    : 'Which team do you think takes this Prop Pool?';
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
