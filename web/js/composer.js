/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · unified Versus composer
 * Sprint 7 Package 2
 *
 * ONE composer. A whole-card tap opens it with no market selected; a market
 * tap opens the same composer with that market selected. There is no
 * intermediate market-selection sheet — choosing a market is a control inside
 * the composer, not a screen in front of it.
 *
 * Fixed order, top to bottom:
 *
 *     identity → VIEW MATCHUP PREVIEW → ML / Spread / O-U → LOCKED | DYNAMIC
 *
 * WP3C reordered the second and third of those to the Rev 4.3 §9 hierarchy.
 *     → selected-mode explanation → YOUR STAKE $0 → economics → send
 *
 * The stake opens at $0 untouched. Send stays disabled until the market, the
 * mode, the minimum and the funding rules are all satisfied — the same rules,
 * in the same order, that the engine applies.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import { formatCredits } from './credits.js';
import { matchup } from './data/league-data.js';
import { previewSheet } from './preview.js';
import { matchupMarketCells } from './wagercard.js';
import {
  MARKETS,
  MODE_COPY,
  MODE_DYNAMIC,
  MODE_LOCKED,
  composerEconomics,
  createComposerState,
  dynamicCeilingNote,
  lockedFreezeNote,
  marketById,
  parseStakeInput,
  selectMarket,
  selectMode,
  setStakeCents,
  validateComposer,
} from './wager-model.js';

/**
 * Live composer state. Held here rather than in the DOM so pushing the Matchup
 * Preview on top and closing it again cannot lose it.
 * @type {{state: object, matchup: object}|null}
 */
let session = null;

/** @returns {object|null} the current composer state, for tests and callers. */
/* ── The production command hook ────────────────────────────────────────── */

/**
 * How the composer reaches the live issue command.
 *
 * INSTALLED BY THE SHELL, not reached for from in here. The composer would
 * otherwise need to know the acting league, the acting team and how to refresh
 * the Action tab — three pieces of session knowledge that belong to the shell,
 * and that a sheet has no business discovering for itself.
 *
 * Null in `demo`: the component suites render and validate the composer without
 * a server, and a hook that defaulted to issuing would make every isolated
 * render one click away from posting real escrow.
 */
let ISSUE_HOOK = null;

/* ── WP3C.1 · the authoritative quote ────────────────────────────────────────
 *
 * THE COMPOSER NO LONGER PRICES ANYTHING. Rev 4.2 derived the opponent's stake
 * from the displayed American moneyline; WP3C removed that as a second economic
 * engine and left the figures unresolved; WP3C.1 asks the server, which prices
 * through the same function the write path freezes.
 *
 * THE HOOK IS INSTALLED BY THE SHELL, and is null in demo — the same rule the
 * issue hook follows, and for the same reason: an isolated render must not be
 * able to reach the network.
 *
 * @type {null|{leagueId: number, week: number|null, request: Function,
 *              explain: Function}}
 */
let QUOTE_HOOK = null;

/** @param {null|object} hook */
export function setQuoteHook(hook) {
  QUOTE_HOOK = hook;
}

/**
 * The quote this composer is showing, and what it was a quote FOR.
 *
 * STALENESS IS SOLVED BY A KEY, NOT BY A TIMER. Every request records the exact
 * inputs it was sent with; when a response lands, its key is compared against
 * what the composer currently holds and a mismatch is DISCARDED. Two requests
 * in flight — a GM typing `2`, then `25` — cannot resolve out of order into a
 * quote for the wrong stake, however the network reorders them.
 *
 * A SEQUENCE NUMBER ALONE WOULD NOT DO IT. It would catch out-of-order arrival
 * but not the case where the GM types `25`, changes to `30`, changes back to
 * `25`: the first response is then for the current inputs and is perfectly
 * usable. The key makes that a hit rather than a discard.
 *
 * @type {{key: string|null, status: string, quote: object|null,
 *         message: string}}
 */
let QUOTE = { key: null, status: 'idle', quote: null, message: '' };

/** Quote lifecycle states, in the order a GM meets them. */
export const QUOTE_IDLE = 'idle';           // not enough chosen yet
export const QUOTE_LOADING = 'loading';     // asked, waiting
export const QUOTE_READY = 'ready';         // priced
export const QUOTE_REFUSED = 'refused';     // the server said why

/**
 * The identity of a quote request — every input the price depends on.
 *
 * IF IT CHANGES THE PRICE, IT IS IN THE KEY. Opponent, market, mode, stake,
 * line and side each move the quote, so each is part of what makes one quote
 * different from another. The week is included too: it is authoritative and
 * cannot change mid-composer today, but a key that omitted it would silently
 * become wrong the day that stops being true.
 *
 * @param {object} state
 * @returns {string|null} null when there is not yet enough to quote
 */
export function quoteKey(state) {
  if (!QUOTE_HOOK) return null;
  const teamId = state.opponent.teamId;
  if (teamId === null || teamId === undefined) return null;
  if (!state.marketId) return null;
  if (!Number.isSafeInteger(state.stakeCents) || state.stakeCents <= 0) return null;
  if (QUOTE_HOOK.week === null || QUOTE_HOOK.week === undefined) return null;

  const market = MARKETS.find((m) => m.id === state.marketId);
  return [teamId, QUOTE_HOOK.week, market ? market.persisted : state.marketId,
          state.mode, state.stakeCents].join('|');
}

/** The quote state, for the renderer and the suites. @returns {object} */
export function quoteState() {
  return QUOTE;
}

/** Drop any held quote. Called whenever a quote-sensitive input changes. */
export function invalidateQuote() {
  QUOTE = { key: null, status: QUOTE_IDLE, quote: null, message: '' };
}

/**
 * Ask for a quote if the current inputs need one, and render when it lands.
 *
 * ALREADY-HELD QUOTES ARE NOT RE-REQUESTED. If the key has not changed there is
 * nothing to ask; re-asking would flicker a priced surface back to loading for
 * an answer it already has.
 *
 * @param {Function} onSettled called after the state changes, to redraw
 */
export async function ensureQuote(onSettled) {
  const key = quoteKey(session ? session.state : null);

  if (key === null) {
    // NOT ENOUGH CHOSEN YET. Anything held is for different inputs and must go
    // — leaving it visible would show a priced pot beside an emptied field.
    if (QUOTE.status !== QUOTE_IDLE) {
      invalidateQuote();
      if (onSettled) onSettled();
    }
    return;
  }
  if (key === QUOTE.key && QUOTE.status !== QUOTE_REFUSED) return;

  QUOTE = { key, status: QUOTE_LOADING, quote: null, message: '' };
  if (onSettled) onSettled();

  const state = session.state;
  const market = MARKETS.find((m) => m.id === state.marketId);
  try {
    const body = await QUOTE_HOOK.request({
      opponentTeamId: state.opponent.teamId,
      week: QUOTE_HOOK.week,
      market: market ? market.persisted : state.marketId,
      stakeCents: state.stakeCents,
      mode: state.mode,
      line: state.line ?? null,
      side: state.side ?? null,
    });
    // THE STALENESS GATE. If the composer has moved on, this answer is for
    // inputs nobody is looking at and is dropped rather than drawn.
    if (QUOTE.key !== key) return;
    QUOTE = { key, status: QUOTE_READY, quote: body, message: '' };
  } catch (refusal) {
    if (QUOTE.key !== key) return;
    QUOTE = {
      key,
      status: QUOTE_REFUSED,
      quote: null,
      message: QUOTE_HOOK.explain(refusal),
    };
  }
  if (onSettled) onSettled();
}


/**
 * @param {null|{leagueId: number, actingTeamId: number, issue: Function,
 *               refresh: Function}} hook
 */
export function setIssueHook(hook) {
  ISSUE_HOOK = hook;
}

/** @returns {boolean} whether a live issue command is installed. */
export function issueBound() {
  return ISSUE_HOOK !== null;
}

export function currentSession() {
  return session;
}

/** Discard the session — called when the sheet stack empties. */
export function endSession() {
  session = null;
  // WP3C.1 — THE QUOTE GOES WITH THE SESSION. A held quote is a price for one
  // GM's pairing at one stake; leaving it behind would let the next composer
  // open showing the previous one's pot for a frame, before its own request
  // landed. Any in-flight response is discarded by the key check regardless.
  invalidateQuote();
}

/**
 * Begin composing a challenge.
 *
 * @param {{matchupId: string, marketId?: string|null, availableCents: number}} spec
 */
export function beginSession(spec) {
  // A NEW COMPOSER STARTS WITH NO PRICE, for the same reason `endSession`
  // clears one. `ensureQuote` on mount asks for this pairing's own.
  invalidateQuote();
  const m = entryMatchup(spec);

  // THE AUTHORITATIVE TARGET LIST, or none. `opponents` are `ActionState` rows
  // — real team ids the server served. In demo it is empty, and the composer
  // then has no live target and no issue hook, so the two halves are never
  // half-present.
  const opponents = Array.isArray(spec.opponents) ? spec.opponents : [];

  // S8-P4C-2R: NO NAME BRIDGE. A caller MAY hand in an already-authoritative
  // `opponentTeamId`, but it is honoured only if it appears in the served list
  // — an id that does not is treated as absent rather than trusted. Nothing
  // resolves a target from display text.
  // WP3C — PLAY'S CARD ID IS ITSELF AN AUTHORITATIVE TARGET. A discovery card
  // carries the served `team_id`, so opening the composer from one already
  // names the opponent and the GM does not have to pick them again. It is still
  // honoured ONLY if it appears in the served list, which is the S8-P4C-2R rule
  // and the reason a display name can never steer the command.
  const handed = spec.opponentTeamId !== undefined && spec.opponentTeamId !== null
    ? spec.opponentTeamId
    : Number(spec.matchupId);
  const preselected = opponents.some((o) => o.team_id === handed)
    ? handed : null;

  session = {
    matchup: m,
    opponents,
    // The acting team's own name, from `/auth/me`. Null in demo.
    actingTeamName: spec.actingTeamName || null,
    state: createComposerState({
      // `id` and `name` remain the ILLUSTRATIVE entry context — the League card
      // this was opened from, which is still a fixture until P4C-3. `teamId` is
      // the only field carrying authority, and it comes from the served list.
      opponent: { id: m.id, name: m.name, teamId: preselected },
      marketId: spec.marketId ?? null,
      mode: MODE_LOCKED,
      availableCents: spec.availableCents,
    }),
  };
  return session;
}

/**
 * The composer's ENTRY CONTEXT — who this was opened against.
 *
 * WP3C — TWO SOURCES NOW, AND ONLY ONE OF THEM IS A FIXTURE.
 *
 * Rev 4.2's Play carousel was eleven invented opponents, so `matchupId` was
 * always a fixture key and `matchup()` always resolved. WP3C bound discovery to
 * the server's own opponent list (§4), so Play now hands over a real TEAM ID —
 * and `matchup()` throws for one, which took the composer down with it.
 *
 * So the fixture is tried first and a served opponent is the fallback. That
 * order matters: the demo carousel and every component suite still pass fixture
 * keys and must keep the rich fixture card, while production passes a team id
 * and gets an entry context built from what the server actually said.
 *
 * THE PRODUCTION CONTEXT CARRIES NO LINE, NO TOTAL AND NO PROJECTION, and that
 * is not an omission. None of the three has an authoritative source for an
 * arbitrary pairing before it is priced; the composer prices the market the GM
 * chooses, and until then there is nothing true to show. `null` is what the
 * market cells draw as unresolved.
 *
 * @param {object} spec
 * @returns {object} a matchup view model
 */
function entryMatchup(spec) {
  try {
    return matchup(spec.matchupId);
  } catch {
    // Not a fixture key. It is a served team id, or nothing.
    const opponents = Array.isArray(spec.opponents) ? spec.opponents : [];
    const served = opponents.find(
      (o) => String(o.team_id) === String(spec.matchupId));
    return {
      id: spec.matchupId,
      name: served ? served.team_name : 'Opponent',
      record: '',
      rank: '',
      you: { id: 'you', name: spec.actingTeamName || 'Your team', record: '', rank: '' },
      // NO INVENTED NUMBERS. Each is null and each draws unresolved.
      ml: null,
      spread: null,
      total: null,
      yourProjection: null,
      opponentProjection: null,
      teaser: '',
      yourLineup: [],
      opponentLineup: [],
      settled: false,
    };
  }
}

/**
 * Select the authoritative opponent, by team id.
 *
 * BY ID, FROM THE SERVED LIST, and refused otherwise. This is the only way a
 * composer session acquires a real target, which is what makes "the command
 * cannot be steered by display text" a structural property rather than a habit.
 *
 * @param {number} teamId
 */
export function selectOpponent(teamId) {
  if (!session) throw new Error('no composer session');
  const found = session.opponents.find((o) => o.team_id === teamId);
  if (!found) {
    throw new Error(`team ${teamId} is not an authoritative opponent`);
  }
  session.state = {
    ...session.state,
    opponent: {
      ...session.state.opponent,
      teamId: found.team_id,
      authoritativeName: found.team_name,
    },
  };
  return session.state;
}

/** Whether this session can name a real target. @returns {boolean} */
export function hasAuthoritativeOpponent() {
  return Boolean(session && session.state.opponent.teamId !== null
                 && session.state.opponent.teamId !== undefined);
}

/**
 * The composer's sheet spec. Re-invoked whenever the sheet stack returns to
 * this level, so it always renders from current state.
 *
 * @returns {{title: string, sub: string, body: string, onMount: Function}}
 */
export function composerSheet() {
  if (!session) throw new Error('no composer session');
  const { matchup: m, state } = session;

  // THE TITLE FOLLOWS THE AUTHORITATIVE TARGET once one is chosen. Leaving the
  // fixture's opponent name in the title while the command addressed a
  // different team is precisely the confusion this repair removes.
  const opponentName = state.opponent.authoritativeName || m.name;

  // AND THE GM'S OWN NAME COMES FROM THE SESSION in production. `m.you.name` is
  // the fixture's GM; a signed-in GM was being shown someone else's team name
  // above a control that would spend their money.
  const yourName = session.actingTeamName || m.you.name;

  // THE SUBTITLE ASSERTED A RECORD, A RANK AND A WEEK, all three from the
  // illustrative League fixture. None is Action's to source — record and rank
  // are League's and the week is Week's, both P4C-3 — so in production the line
  // says only what it is for. Demo keeps the locked Rev 4.2 line exactly.
  const sub = session.opponents.length
    ? 'Pick your market'
    : `${m.record} · ${m.rank} · Week 5 · pick your market`;

  return {
    title: `${yourName} vs ${opponentName}`,
    sub,
    body:
      opponentSelector(state) +
      // REV 4.3 SS9 — PREVIEW ABOVE MARKETS. Rev 4.2 put the market row first
      // and the preview button under it. The POR inverts that because the two
      // answer different questions in a fixed order: the preview answers "why
      // does this matchup look this way?" and the markets answer "what do I
      // want to play?", so the explanation is offered before the choice rather
      // than after it.
      previewButton() +
      marketSelector(m, state) +
      modeSelector(state) +
      modeExplanation(state) +
      stakeField(state) +
      economicsBlock(m, state) +
      sendControl(state),
    onMount: bindComposer,
  };
}

/* ── Sections ───────────────────────────────────────────────────────────── */

/**
 * Who the wager is against — the authoritative selector.
 *
 * DRAWN ONLY IN PRODUCTION. In demo there are no served opponents, so this
 * renders nothing and the locked Rev 4.2 composer is unchanged: the fixture
 * opens against one matchup and stays that way.
 *
 * IN PRODUCTION IT IS REQUIRED. The League card that opened this composer is
 * still illustrative until P4C-3, so it carries no authority to hand over — and
 * rather than let its display name stand in for one, the composer asks. `Send`
 * stays disabled until a real team is chosen.
 */
function opponentSelector(state) {
  if (!session.opponents.length) return '';
  const chosen = state.opponent.teamId;
  return (
    '<div class="fs-oppsel" data-opponent-block>' +
    '<div class="fs-oppsel__label">Who are you challenging?</div>' +
    session.opponents.map((o) => (
      '<button type="button" class="fs-btn fs-oppsel__btn'
      + (o.team_id === chosen ? ' is-selected' : '') + '" '
      + `data-composer-opponent="${o.team_id}" `
      + `aria-pressed="${o.team_id === chosen}">`
      + `${escapeHtml(o.team_name)}</button>`
    )).join('') +
    '</div>'
  );
}

function marketSelector(m, state) {
  const cells = matchupMarketCells(m);
  return (
    '<div class="fs-field">' +
    '<div class="fs-field__label">MARKET</div>' +
    '<div class="fs-seg fs-seg--market" role="group" aria-label="Market">' +
    MARKETS.map((market) => {
      const cell = cells.find((c) => c.id === market.id);
      const selected = state.marketId === market.id;
      return (
        `<button type="button" class="fs-seg__opt${selected ? ' is-selected' : ''}" ` +
        `data-composer-market="${escapeHtml(market.id)}" aria-pressed="${selected}">` +
        `<span class="fs-seg__label">${escapeHtml(market.label)}</span>` +
        `<span class="fs-seg__value">${escapeHtml(cell.value)}</span>` +
        '</button>'
      );
    }).join('') +
    '</div></div>'
  );
}

function previewButton() {
  return (
    '<button type="button" class="fs-btn fs-btn--ghost fs-preview-open" data-composer-preview>' +
    'VIEW MATCHUP PREVIEW' +
    '</button>'
  );
}

function modeSelector(state) {
  return (
    '<div class="fs-field">' +
    '<div class="fs-field__label">TERMS</div>' +
    '<div class="fs-seg fs-seg--mode" role="group" aria-label="Terms">' +
    [MODE_LOCKED, MODE_DYNAMIC].map((mode) => {
      const selected = state.mode === mode;
      return (
        `<button type="button" class="fs-seg__opt${selected ? ' is-selected' : ''}" ` +
        `data-composer-mode="${mode}" aria-pressed="${selected}">` +
        `<span class="fs-seg__label">${MODE_COPY[mode].label}</span>` +
        '</button>'
      );
    }).join('') +
    '</div></div>'
  );
}

function modeExplanation(state) {
  const copy = MODE_COPY[state.mode];
  return (
    '<div class="fs-modenote" data-mode-note>' +
    `<div class="fs-modenote__head">${escapeHtml(copy.headline)}</div>` +
    `<div class="fs-modenote__body">${escapeHtml(copy.body)}</div>` +
    '</div>'
  );
}

function stakeField(state) {
  const dollars = state.stakeCents === 0 ? '0' : (state.stakeCents / 100).toFixed(2).replace(/\.00$/, '');
  return (
    '<div class="fs-stake">' +
    '<label class="fs-stake__label" for="fs-stake-input">YOUR STAKE</label>' +
    '<div class="fs-stake__row">' +
    '<span class="fs-stake__cur">$</span>' +
    `<input class="fs-stake__input" id="fs-stake-input" data-composer-stake ` +
    `inputmode="decimal" autocomplete="off" value="${escapeHtml(dollars)}" ` +
    'aria-describedby="fs-stake-hint">' +
    '</div>' +
    '<div class="fs-stake__hint" id="fs-stake-hint" data-stake-hint></div>' +
    '</div>'
  );
}

function economicsBlock(m, state) {
  return `<div class="fs-econ" data-econ>${economicsRows(m, state)}</div>`;
}

/**
 * The economics rows. Rendered separately so typing updates them without
 * re-rendering the field the GM is typing into.
 */
function economicsRows(m, state) {
  // WP3C.1 — THE SERVED QUOTE WINS, ALWAYS. When a quote hook is installed this
  // surface renders the server's figures and computes none of its own. The
  // demo path below still uses the fixture arithmetic, because a demo composer
  // has no session to quote through and its numbers are illustrative anyway.
  if (QUOTE_HOOK) return servedEconomicsRows(state);

  // NO QUOTE, NO ECONOMICS. Rev 4.2's carousel always carried a fixture
  // moneyline, so `m.ml` was always a number. A real opponent has no quote until
  // the pricing engine produces one for the chosen market, and
  // `deriveOpponentStakeCents` refuses a null outright — correctly, because the
  // opponent's stake is a function of the odds and there are none.
  if (typeof m.ml !== 'number') {
    return (
      '<div class="fs-note">Your opponent’s stake and the pot are priced when '
      + 'you pick a market and enter a stake. Nothing is shown here until then '
      + '— an estimate would be a number nobody quoted.</div>'
    );
  }

  const line = { odds: m.ml };
  const econ = composerEconomics(state, line);
  const rows = [
    { label: 'Your stake', cents: econ.yourStakeCents },
    { label: 'Opponent stake', cents: econ.opponentStakeCents },
    { label: 'Pot', cents: econ.potCents, anchor: true },
    { label: 'You win', cents: econ.winCents, tone: 'is-positive' },
    { label: 'You lose', cents: econ.loseCents, tone: 'is-negative' },
  ];

  const note = state.mode === MODE_DYNAMIC ? dynamicCeilingNote(econ) : lockedFreezeNote();

  return (
    rows.map((row) => (
      `<div class="fs-econ__row${row.anchor ? ' is-anchor' : ''}">` +
      `<span class="fs-econ__label">${escapeHtml(row.label)}</span>` +
      `<span class="fs-econ__value fs-money ${row.tone || ''}" data-exact-cents="${row.cents}">` +
      `${escapeHtml(formatCredits(row.cents))}</span>` +
      '</div>'
    )).join('') +
    `<div class="fs-econ__note">${escapeHtml(note)}</div>`
  );
}

/**
 * The economics, drawn from the SERVED quote and nothing else.
 *
 * FOUR STATES, AND EACH SAYS SOMETHING DIFFERENT. A GM who has not chosen
 * enough yet, one waiting on a price, one looking at a price, and one whose
 * wager cannot be priced are four different situations, and collapsing any two
 * of them would mean showing a stale figure or an unexplained blank.
 *
 * EVERY FIGURE IS THE SERVER'S. `data-exact-cents` carries the integer the
 * route returned, and `formatCredits` only decides how it is drawn. There is no
 * arithmetic in this function — the pot is not `stake + opponent`, it is
 * `quote.pot_cents`, because the two could differ under a pricing rule this
 * surface does not know about and the server's answer is the one that governs.
 *
 * @param {object} state
 * @returns {string}
 */
function servedEconomicsRows(state) {
  const q = quoteState();

  if (q.status === QUOTE_LOADING) {
    return '<div class="fs-note" data-quote-state="loading" aria-busy="true">'
      + 'Pricing this wager…</div>';
  }
  if (q.status === QUOTE_REFUSED) {
    return `<div class="fs-note is-warn" data-quote-state="refused">${
      escapeHtml(q.message)}</div>`;
  }
  if (q.status !== QUOTE_READY || !q.quote) {
    return '<div class="fs-note" data-quote-state="idle">Pick a market and '
      + 'enter a stake, and FantasyStakes will price the wager.</div>';
  }

  const quote = q.quote;
  const rows = [
    { label: 'Your stake', cents: quote.your_stake_cents },
    { label: quote.is_ceiling ? 'Opponent stake (max)' : 'Opponent stake',
      cents: quote.opponent_stake_cents },
    { label: 'Pot', cents: quote.pot_cents, anchor: true },
    { label: 'You win', cents: quote.win_cents, tone: 'is-positive' },
    { label: 'You lose', cents: quote.lose_cents, tone: 'is-negative' },
  ];

  // THE MODE NOTE IS THE EXISTING LOCKED COPY, and the Dynamic one is now fed
  // the SERVED ceiling rather than a derived one. Neither ruling is reopened:
  // the sentences are `wager-model.js`'s own, unchanged.
  const note = state.mode === MODE_DYNAMIC
    ? dynamicCeilingNote({ opponentStakeCents: quote.opponent_stake_cents })
    : lockedFreezeNote();

  return (
    '<div data-quote-state="ready">'
    + rows.map((row) => (
      `<div class="fs-econ__row${row.anchor ? ' is-anchor' : ''}">`
      + `<span class="fs-econ__label">${escapeHtml(row.label)}</span>`
      + `<span class="fs-econ__value fs-money ${row.tone || ''}" `
      + `data-exact-cents="${row.cents}">`
      + `${escapeHtml(formatCredits(row.cents))}</span>`
      + '</div>'
    )).join('')
    + `<div class="fs-econ__note">${escapeHtml(note)}</div>`
    + '</div>'
  );
}

function sendControl(state) {
  const verdict = validateComposer(state);
  // A LIVE SEND NEEDS A REAL TARGET. Checked here rather than inside
  // `validateComposer`, which is shared with the demo composer that has no
  // target to choose and would otherwise be permanently invalid.
  const needsTarget = Boolean(session.opponents.length)
    && (state.opponent.teamId === null || state.opponent.teamId === undefined);
  const ok = verdict.ok && !needsTarget;
  const message = needsTarget
    ? 'Choose who you are challenging.'
    : (verdict.ok ? '' : (verdict.hint || verdict.reasons[0]));
  return (
    '<div class="fs-send" data-send-block>' +
    `<div class="fs-send__why" data-send-why>${escapeHtml(message)}</div>` +
    `<button type="button" class="fs-btn fs-btn--gold fs-send__btn" data-composer-send ` +
    `${ok ? '' : 'disabled'}>Send Challenge</button>` +
    '</div>'
  );
}

/* ── Binding ────────────────────────────────────────────────────────────── */

function bindComposer(host, api) {
  // WP3C.1 — EVERY QUOTE-SENSITIVE CHANGE DROPS THE OLD QUOTE FIRST, before
  // the surface is redrawn. Invalidating after the redraw would paint the
  // previous price beside the new selection for a frame, and a GM who changed
  // market and glanced at the pot would read a figure for the market they had
  // just left.
  host.querySelectorAll('[data-composer-market]').forEach((el) => {
    el.addEventListener('click', () => {
      session.state = selectMarket(session.state, el.dataset.composerMarket);
      invalidateQuote();
      api.rerender();
    });
  });

  host.querySelectorAll('[data-composer-opponent]').forEach((el) => {
    el.addEventListener('click', () => {
      selectOpponent(Number(el.dataset.composerOpponent));
      invalidateQuote();
      api.rerender();
    });
  });

  host.querySelectorAll('[data-composer-mode]').forEach((el) => {
    el.addEventListener('click', () => {
      session.state = selectMode(session.state, el.dataset.composerMode);
      invalidateQuote();
      api.rerender();
    });
  });

  const preview = host.querySelector('[data-composer-preview]');
  if (preview) {
    // Pushed on top: the composer stays underneath with its state intact.
    preview.addEventListener('click', () => api.push(() => previewSheet(session.matchup)));
  }

  // WP3C.1 — QUOTE ON MOUNT TOO. Opening from a market cell on a Play card
  // arrives with the opponent AND the market already chosen, so the only thing
  // missing is a stake; and re-entering this level from the Preview arrives
  // with all three. `ensureQuote` is a no-op when there is not enough to ask
  // and when the held quote already matches, so calling it unconditionally is
  // both correct and cheap.
  ensureQuote(() => refreshDerived(host));

  const input = host.querySelector('[data-composer-stake]');
  if (input) {
    input.addEventListener('input', () => {
      const parsed = parseStakeInput(input.value);
      if (parsed.error) {
        showStakeError(host, parsed.error);
        return;
      }
      session.state = setStakeCents(session.state, parsed.cents);
      // THE OLD PRICE GOES THE MOMENT THE STAKE DOES. `refreshDerived` redraws
      // immediately, so without this the pot for the previous stake would sit
      // under the new one until the next quote landed.
      invalidateQuote();
      refreshDerived(host);
      // DEBOUNCED, BECAUSE THIS FIRES PER KEYSTROKE. Typing `25` is two events
      // and would be two Monte Carlo simulations on the server; the second
      // supersedes the first anyway. The staleness key makes the debounce an
      // efficiency measure rather than a correctness one — an early response
      // that arrives late is discarded either way.
      scheduleQuote(host);
    });
  }

  const send = host.querySelector('[data-composer-send]');
  if (send && ISSUE_HOOK) {
    send.addEventListener('click', async () => {
      const { state } = session;
      // DISABLED FOR THE DURATION, so a second click cannot issue a second
      // funded challenge. Escrow posts at issue now: a double-send is two real
      // stakes, not two harmless rows.
      send.disabled = true;
      const why = host.querySelector('[data-send-why]');
      if (why) why.textContent = 'Sending…';
      try {
        await ISSUE_HOOK.issue({
          challengerTeamId: ISSUE_HOOK.actingTeamId,
          // THE SELECTED AUTHORITATIVE TEAM ID, and nothing else. No name, no
          // fixture id, no lookup — the value came from the served opponent
          // list at the moment the GM chose it.
          challengedTeamId: state.opponent.teamId,
          week: ISSUE_HOOK.week,
          wagerType: marketById(state.marketId).persisted,
          amountCents: state.stakeCents,
          mode: state.mode,
        });
        // THE AUTHORITATIVE REFRESH IS THE SUCCESS PATH. Nothing here writes a
        // card or moves a figure — the tab re-reads and draws what is true.
        await ISSUE_HOOK.refresh();
        api.close();
      } catch (error) {
        send.disabled = false;
        if (why) why.textContent = ISSUE_HOOK.explain(error);
      }
    });
  }

  refreshDerived(host);
}

/**
 * Update everything that follows from the stake, in place.
 *
 * In place, deliberately: re-rendering the whole sheet on each keystroke would
 * tear out the input the GM is typing into and drop the caret.
 */
/**
 * The pending debounce timer, if any.
 *
 * ONE TIMER FOR THE WHOLE COMPOSER, cleared on every keystroke, so a burst of
 * typing produces exactly one request rather than one per character.
 */
let QUOTE_TIMER = null;

/** How long to wait after the last keystroke before pricing. */
const QUOTE_DEBOUNCE_MS = 250;

/**
 * Ask for a quote shortly after the GM stops typing.
 *
 * @param {HTMLElement} host
 */
function scheduleQuote(host) {
  if (QUOTE_TIMER !== null) clearTimeout(QUOTE_TIMER);
  QUOTE_TIMER = setTimeout(() => {
    QUOTE_TIMER = null;
    // The host may have been torn down while the timer ran — a GM who closed
    // the sheet mid-type. Redrawing into a detached node is harmless but
    // pointless, and asking the server for a price nobody will see is worse.
    if (!host.isConnected) return;
    ensureQuote(() => refreshDerived(host));
  }, QUOTE_DEBOUNCE_MS);
}

function refreshDerived(host) {
  const { matchup: m, state } = session;

  const econ = host.querySelector('[data-econ]');
  if (econ) econ.innerHTML = economicsRows(m, state);

  const verdict = validateComposer(state);
  const needsTarget = Boolean(session.opponents.length)
    && (state.opponent.teamId === null || state.opponent.teamId === undefined);

  const send = host.querySelector('[data-composer-send]');
  if (send) send.disabled = !verdict.ok || needsTarget;

  const why = host.querySelector('[data-send-why]');
  if (why) {
    why.textContent = needsTarget
      ? 'Choose who you are challenging.'
      : (verdict.ok ? '' : (verdict.hint || verdict.reasons[0]));
  }

  const hint = host.querySelector('[data-stake-hint]');
  if (hint) {
    hint.textContent = state.touched ? '' : 'Wagers fund from Weekly Min first, then Wallet.';
    hint.classList.remove('is-error');
  }
}

function showStakeError(host, message) {
  const hint = host.querySelector('[data-stake-hint]');
  if (hint) {
    hint.textContent = message;
    hint.classList.add('is-error');
  }
  const send = host.querySelector('[data-composer-send]');
  if (send) send.disabled = true;
}