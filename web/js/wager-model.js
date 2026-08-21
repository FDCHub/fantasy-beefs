/* ============================================================================
 * FantasyStakes — UI/UX Rev 4.2 · wager presentation model
 * Sprint 7 Package 2
 *
 * The composer's state, its validation, and the copy that explains Locked and
 * Dynamic. Pure — no DOM, no I/O.
 *
 * WHAT THIS MODULE MAY AND MAY NOT DO
 *
 * It presents. It does not price, settle, escrow, or decide. Three boundaries
 * follow from that, and each is enforced below rather than merely stated:
 *
 *   1. The Locked and Dynamic explanations are QUOTED from the adopted ruling
 *      (spec/LOCKED_VS_DYNAMIC_WAGER_MODEL_RULING.md). The Dynamic copy is the
 *      corrected card copy ruled in §5.3 on 2026-07-19, verbatim. Earlier draft
 *      copy said a stake could "flex up or down"; that contradicted the model
 *      and is gone. No wording here may drift from the ruling.
 *
 *   2. The opponent's stake shown while composing is DISPLAY ARITHMETIC on the
 *      quoted line, not a repricing. When the pricing seam supplies a quote,
 *      the view model passes `quotedDerivedStakeCents` and it is used
 *      unchanged. The Dynamic adjustment formula is not reimplemented here,
 *      and this module never moves a derived stake up or down over time.
 *
 *   3. Validation mirrors the rules the engine already enforces — whole cents,
 *      then MIN_BET, then funding — in that order, so the composer refuses
 *      exactly what the backend would refuse and invents no further rule.
 *      MAX_BET_PCT is deliberately absent: it is a single-party bet-sizing cap
 *      applied by betting/bet_engine.py, and beefs/beef_engine.py does not
 *      apply it to a challenge. Enforcing it here would fabricate a limit.
 * ========================================================================== */

import { assertIntegerCents, formatCredits } from './credits.js';

/* ── Vocabulary ─────────────────────────────────────────────────────────────
 * Display labels are the locked betting vocabulary. `persisted` mirrors the
 * value the proposal record stores (beefs/proposal_lifecycle.py
 * VALID_WAGER_TYPES) so the UI label and the protocol value never drift:
 * "Moneyline"/"ML" is a display label for the persisted `straight`. */
// WP3C ADDED `short`, THE CARD-CELL ABBREVIATION. Rev 4.3 §9 fixes the market
// row as `ML | SPR | O/U`, and `SPR` was previously a literal inside
// `wagercard.matchupMarketCells` while `label` said `Spread`. Two spellings of
// one market in two files is how they come to disagree; the abbreviation now
// lives beside the market it abbreviates.
/* UIRECON WAVE 3A — `label` CARRIES THE PUBLIC WORDING.
 *
 * The composer's market selector reads `label` and drew `ML` / `Spread` /
 * `O/U`: two abbreviations and a word, in three cells that are meant to be
 * peers. The locked public wording is Moneyline, Spread and Over/Under, and
 * these cells are the widest place the product names a market, so they are
 * where it says so in full.
 *
 * `short` IS A DIFFERENT FIELD FOR A DIFFERENT REASON and is deliberately not
 * touched. It labels the three-cell row on the Play discovery card and on the
 * Status lifecycle cards, where a cell is roughly 68px wide; `Over/Under` would
 * ellipsize there, which is a worse answer than the abbreviation the surface
 * was designed around. `persisted` is protocol and is never a display concern.
 */
export const MARKETS = Object.freeze([
  Object.freeze({ id: 'ml', label: 'Moneyline', short: 'ML', longLabel: 'Moneyline', persisted: 'straight' }),
  Object.freeze({ id: 'spread', label: 'Spread', short: 'SPR', longLabel: 'Spread', persisted: 'spread' }),
  Object.freeze({ id: 'ou', label: 'Over/Under', short: 'O/U', longLabel: 'Over / Under', persisted: 'over_under' }),
]);

export const MODE_LOCKED = 'locked';
export const MODE_DYNAMIC = 'dynamic';
export const MODES = Object.freeze([MODE_LOCKED, MODE_DYNAMIC]);

/** wallet/wallet_manager.py MIN_BET = $5.00. */
export const MIN_STAKE_CENTS = 500;

/**
 * Mode explanations, quoted from the adopted ruling.
 *
 * LOCKED — the ruling's §1 central principle and the §4 UI consequence: the
 * terms are frozen inside FantasyStakes, Yahoo changes never touch them at any
 * stage, and Refresh & Relock in-app is the only way to put different terms on
 * the table.
 *
 * DYNAMIC — §5.3 corrected card copy, verbatim.
 */
export const MODE_COPY = Object.freeze({
  [MODE_LOCKED]: Object.freeze({
    label: 'LOCKED',
    headline: 'Terms freeze the moment you send this.',
    body:
      'The lineups, odds and both stakes are captured now and held inside ' +
      'FantasyStakes. Later Yahoo lineup changes by either GM never touch them, ' +
      'at any stage. Accepting picks this frozen offer exactly as it stands — ' +
      'it is not repriced on acceptance. The only way to put different terms on ' +
      'the table is Refresh & Relock in-app.',
  }),
  [MODE_DYNAMIC]: Object.freeze({
    label: 'DYNAMIC',
    headline: 'Lineups and odds stay live until Final Lock.',
    // §5.3, CORRECTED — S8-P4C-2R2, on explicit authorisation.
    //
    // This block was carried verbatim from the UX spec and said the terms
    // "lock in at kickoff". Checked against the governing trigger, that phrase
    // is ambiguous rather than merely loose: GE-901 / AP-212 fix Final Lock
    // immediately before the EARLIEST scheduled kickoff among players in
    // EITHER covered final Yahoo starting lineup. "Kickoff" invites a GM to
    // picture their own matchup's Sunday start, when a covered Thursday-night
    // starter — on either side — locks the whole wager days earlier.
    //
    // The substantive Locked/Dynamic explanation is preserved exactly: the
    // Anchor is fixed, only the Derived side may move, it may only come DOWN,
    // and never past the ceiling set at acceptance. Only the timing clause
    // changed, and it changed to match the protocol rather than to soften it.
    body:
      'Lineups and odds stay live until Final Lock, just before the first ' +
      'covered player’s game begins. Your Anchor Stake stays fixed; the ' +
      'opponent’s Derived Stake may come down, never above the acceptance ' +
      'ceiling.',
  }),
});

/* ── Odds ───────────────────────────────────────────────────────────────────*/

/**
 * Format American odds for display.
 *
 * @param {number} odds
 * @returns {string}
 */
export function formatOdds(odds) {
  if (!Number.isInteger(odds)) throw new TypeError(`odds must be a whole number, got ${odds}`);
  return odds > 0 ? `+${odds}` : String(odds);
}

/**
 * The opponent's stake against a stake of `yourStakeCents` at `americanOdds`.
 *
 * DISPLAY ARITHMETIC on the quoted line — the standard American-odds relation,
 * applied once to show what the offer is worth. It is not a pricing model and
 * carries no time behaviour: nothing here adjusts a stake as odds move. When
 * the pricing seam quotes a derived stake, `composerEconomics` uses that quote
 * instead of this function.
 *
 * @param {number} yourStakeCents exact integer cents
 * @param {number} americanOdds
 * @returns {number} exact integer cents, half away from zero
 */
export function deriveOpponentStakeCents(yourStakeCents, americanOdds) {
  assertIntegerCents(yourStakeCents, 'stake');
  if (!Number.isInteger(americanOdds) || americanOdds === 0) {
    throw new TypeError(`odds must be a non-zero whole number, got ${americanOdds}`);
  }
  const ratio = americanOdds > 0 ? americanOdds / 100 : 100 / Math.abs(americanOdds);
  const exact = yourStakeCents * ratio;
  return Math.sign(exact) * Math.round(Math.abs(exact));
}

/* ── Composer state ─────────────────────────────────────────────────────────*/

/**
 * @typedef {object} ComposerState
 * @property {object} opponent      identity of the GM being challenged
 * @property {string|null} marketId null until a market is chosen
 * @property {string} mode          MODE_LOCKED or MODE_DYNAMIC
 * @property {number} stakeCents    exact integer cents; 0 is the untouched default
 * @property {boolean} touched      whether the GM has entered anything yet
 * @property {number} availableCents funding capacity, exact integer cents
 */

/**
 * A fresh composer.
 *
 * The stake opens at $0 and `touched` is false: $0 is the untouched default
 * state, not a rejected entry, so the composer must not open showing a
 * validation error against a figure the GM has not typed.
 *
 * @param {{opponent: object, marketId?: string|null, mode?: string, availableCents: number}} spec
 * @returns {ComposerState}
 */
export function createComposerState(spec) {
  const { opponent, marketId = null, mode = MODE_LOCKED, availableCents } = spec || {};
  if (!opponent) throw new TypeError('a composer needs an opponent');
  assertIntegerCents(availableCents, 'availableCents');
  if (marketId !== null) assertMarket(marketId);
  assertMode(mode);
  return {
    opponent,
    marketId,
    mode,
    stakeCents: 0,
    touched: false,
    availableCents,
    // WP3C.2 — THE ONE MARKET CHOICE THAT IS THE GM'S.
    //
    // Over or Under on a total, and nothing else. It starts NULL rather than
    // 'over' deliberately: a default here would place one side of a real wager
    // on a GM who never picked it, and the quote route refuses a total with no
    // side for exactly that reason. The line itself is never in this state —
    // it is the server's, and the composer reads it from the served board.
    side: null,
  };
}

/**
 * @param {string} id
 * @returns {{id: string, label: string, longLabel: string, persisted: string}}
 */
export function marketById(id) {
  const found = MARKETS.find((m) => m.id === id);
  if (!found) throw new Error(`unknown market "${id}"`);
  return found;
}

function assertMarket(id) {
  marketById(id);
}

function assertMode(mode) {
  if (!MODES.includes(mode)) throw new Error(`unknown wager mode "${mode}"`);
}

/** The two sides of a total. */
export const SIDES = Object.freeze(['over', 'under']);

/** @returns {ComposerState} */
export function selectMarket(state, marketId) {
  assertMarket(marketId);
  // LEAVING A TOTAL CLEARS THE SIDE. A GM who picks O/U, chooses Under, then
  // switches to Spread and back would otherwise return to a composer that
  // still held Under — a choice they made about a market they had left.
  return { ...state, marketId, side: marketId === 'ou' ? state.side : null };
}

/**
 * Choose Over or Under on a total.
 *
 * @param {ComposerState} state
 * @param {'over'|'under'|null} side
 * @returns {ComposerState}
 */
export function selectSide(state, side) {
  if (side !== null && !SIDES.includes(side)) {
    throw new Error(`unknown side "${side}"`);
  }
  return { ...state, side };
}

/** @returns {ComposerState} */
export function selectMode(state, mode) {
  assertMode(mode);
  return { ...state, mode };
}

/**
 * Set the stake. Clearing the field returns the composer to its untouched $0
 * state rather than to a zero the GM is told off for.
 *
 * @param {ComposerState} state
 * @param {number} cents exact integer cents
 * @returns {ComposerState}
 */
export function setStakeCents(state, cents) {
  assertIntegerCents(cents, 'stake');
  if (cents < 0) throw new RangeError('a stake cannot be negative');
  return { ...state, stakeCents: cents, touched: cents !== 0 };
}

/**
 * Parse typed dollars into exact cents.
 *
 * Sub-cent input is refused rather than rounded — the engine treats a sub-cent
 * stake as malformed input, and rounding it here would submit a figure the GM
 * did not type.
 *
 * @param {string} text
 * @returns {{cents: number}|{error: string}}
 */
export function parseStakeInput(text) {
  const trimmed = String(text == null ? '' : text).trim().replace(/^\$/, '').replace(/,/g, '');
  if (trimmed === '') return { cents: 0 };
  if (!/^\d+(\.\d{1,})?$/.test(trimmed)) return { error: 'Enter a dollar amount.' };
  const [dollars, fraction = ''] = trimmed.split('.');
  if (fraction.length > 2) return { error: 'Stakes are whole cents.' };
  const cents = Number(dollars) * 100 + Number(fraction.padEnd(2, '0'));
  if (!Number.isSafeInteger(cents)) return { error: 'That amount is too large.' };
  return { cents };
}

/* ── Validation ─────────────────────────────────────────────────────────────*/

/**
 * Whether this composer may be sent, and why not.
 *
 * Order mirrors the engine: malformed before rule-breaking (FR-7.50 §ordering),
 * then the minimum, then funding. `blocking` is what disables Send; `hint` is
 * what the GM is shown while the composer is still untouched.
 *
 * @param {ComposerState} state
 * @returns {{ok: boolean, reasons: string[], hint: string|null}}
 */
export function validateComposer(state) {
  const reasons = [];

  if (!state.marketId) reasons.push('Choose ML, Spread or O/U.');
  if (!MODES.includes(state.mode)) reasons.push('Choose Locked or Dynamic.');

  if (!Number.isSafeInteger(state.stakeCents)) {
    reasons.push('Stakes are whole cents.');
  } else if (state.stakeCents === 0) {
    reasons.push(`Enter a stake of at least ${formatCredits(MIN_STAKE_CENTS)}.`);
  } else if (state.stakeCents < MIN_STAKE_CENTS) {
    reasons.push(`The minimum stake is ${formatCredits(MIN_STAKE_CENTS)}.`);
  } else if (state.stakeCents > state.availableCents) {
    reasons.push(`That is more than your ${formatCredits(state.availableCents)} available.`);
  }

  return {
    ok: reasons.length === 0,
    reasons,
    // An untouched composer explains the funding rule instead of complaining.
    hint: state.touched ? null : 'Wagers fund from Weekly Min first, then Wallet.',
  };
}

/* ── Economics ──────────────────────────────────────────────────────────────*/

/**
 * The four figures the composer shows: both stakes, the pot, and what the
 * wager wins or loses.
 *
 * Every figure is exact integer cents. `potCents` is simply both stakes — the
 * escrow ceiling under Dynamic is that same pot, frozen at Handshake, which is
 * why the ceiling shown here is the pot at the quoted terms and never grows.
 *
 * @param {ComposerState} state
 * @param {{odds: number, quotedDerivedStakeCents?: number}} line
 * @returns {{yourStakeCents: number, opponentStakeCents: number, potCents: number,
 *   winCents: number, loseCents: number, quoted: boolean}}
 */
export function composerEconomics(state, line) {
  const yourStakeCents = state.stakeCents;
  assertIntegerCents(yourStakeCents, 'stake');

  // A quote from the pricing seam wins outright; the display arithmetic is the
  // fallback while that seam does not exist.
  const quoted = Number.isSafeInteger(line?.quotedDerivedStakeCents);
  const opponentStakeCents = quoted
    ? line.quotedDerivedStakeCents
    : deriveOpponentStakeCents(yourStakeCents, line.odds);

  return {
    yourStakeCents,
    opponentStakeCents,
    potCents: yourStakeCents + opponentStakeCents,
    winCents: opponentStakeCents,
    loseCents: yourStakeCents,
    quoted,
  };
}

/**
 * The ceiling sentence shown under Dynamic economics.
 *
 * States the governed direction of travel — hold or come down, never up, never
 * past the maximum set at Handshake — without recomputing anything.
 *
 * @param {{opponentStakeCents: number}} economics
 * @returns {string}
 */
export function dynamicCeilingNote(economics) {
  return (
    `Your opponent’s stake is quoted at ${formatCredits(economics.opponentStakeCents)}. ` +
    'It can hold or come down before kickoff — never up, and never past that ' +
    'maximum. Your own stake does not move.'
  );
}

/**
 * The frozen-terms sentence shown under Locked economics.
 *
 * @returns {string}
 */
export function lockedFreezeNote() {
  return 'These terms freeze when you send. Accepting selects them unchanged.';
}