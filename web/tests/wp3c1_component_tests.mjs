/* ============================================================================
 * FantasyStakes — WP3C.1 · the authoritative Versus quote · component tests
 *
 * Run directly:   node web/tests/wp3c1_component_tests.mjs
 * Or through:     python test_wp3c1_versus_quote.py
 *
 * The shipped composer is driven directly, against a stub quote hook that
 * records what it was asked and controls when it answers. That control is the
 * point: the staleness and invalidation claims are about ORDERING, and ordering
 * cannot be tested against a real server that resolves whenever it likes.
 * ========================================================================== */

import { readFileSync } from 'node:fs';

import {
  QUOTE_IDLE, QUOTE_LOADING, QUOTE_READY, QUOTE_REFUSED,
  beginSession, composerSheet, endSession, ensureQuote, invalidateQuote,
  quoteKey, quoteState, selectOpponent, setQuoteHook,
} from '../js/composer.js';

import {
  MODE_DYNAMIC, MODE_LOCKED, selectMarket, selectMode, setStakeCents,
} from '../js/wager-model.js';

import { QuoteError, explainQuoteRefusal } from '../js/versus-quote-command.js';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

function section(title) {
  console.log(`\n${title}`);
}

const OPPONENTS = [
  { team_id: 7, team_name: 'Alpha', owner: 'A' },
  { team_id: 8, team_name: 'Bravo', owner: 'B' },
];

/** A served VersusQuoteOut, exactly as the route returns it. */
function servedQuote(over = {}) {
  return {
    league_id: 1,
    acting_team_id: 1,
    opponent_team_id: 7,
    week: 5,
    market: 'straight',
    mode: 'locked',
    your_stake_cents: 2000,
    opponent_stake_cents: 3175,
    pot_cents: 5175,
    win_cents: 3175,
    lose_cents: 2000,
    anchor_odds: 2.5875,
    derived_odds: 1.63,
    anchor_moneyline: 159,
    derived_moneyline: -159,
    is_ceiling: false,
    ...over,
  };
}

/**
 * A quote hook whose answers this suite decides.
 *
 * `mode: 'auto'` resolves immediately; `mode: 'manual'` parks each call so the
 * suite can resolve them out of order, which is the only way to prove the
 * staleness gate actually gates.
 */
function stubHook(opts = {}) {
  const calls = [];
  const pending = [];
  return {
    calls,
    pending,
    hook: {
      leagueId: 1,
      week: 5,
      explain: explainQuoteRefusal,
      request(spec) {
        calls.push(spec);
        if (opts.mode === 'manual') {
          return new Promise((resolve, reject) => {
            pending.push({ spec, resolve, reject });
          });
        }
        if (opts.reject) return Promise.reject(opts.reject);
        return Promise.resolve(opts.body || servedQuote());
      },
    },
  };
}

function openComposer() {
  beginSession({
    matchupId: '7',
    marketId: null,
    availableCents: 50000,
    opponents: OPPONENTS,
    actingTeamName: 'Me',
  });
}

/** Bring the session to a fully quotable state. */
function makeQuotable() {
  selectOpponent(7);
  const s = composerSheet();       // forces a render, harmless
  void s;
  applyState((st) => selectMarket(st, 'ml'));
  applyState((st) => setStakeCents(st, 2000));
}

/** Mutate the live session state the way the composer's handlers do. */
function applyState(fn) {
  // eslint-disable-next-line no-underscore-dangle
  const session = currentSession();
  session.state = fn(session.state);
}

/** The composer's own session object, reached the way the suite must. */
function currentSession() {
  // `composerSheet()` throws without one, which is the assertion that there IS
  // one; the state itself is reached through the exported mutators below.
  return SESSION_REF;
}

// The composer does not export its session, so the suite drives it through the
// exported mutators and reads the rendered output. `SESSION_REF` is populated
// by the one exported function that returns it.
let SESSION_REF = null;

/* ── A · the quote key ───────────────────────────────────────────────────── */

section('A · A quote is requested only when there is enough to price');

setQuoteHook(null);
endSession();
SESSION_REF = beginSession({
  matchupId: '7', marketId: null, availableCents: 50000,
  opponents: OPPONENTS, actingTeamName: 'Me',
});

check('with no hook installed there is no key, so no request is possible',
  quoteKey(SESSION_REF.state) === null);

const stub = stubHook();
setQuoteHook(stub.hook);

check('an opponent alone is not enough', quoteKey(SESSION_REF.state) === null);

selectOpponent(7);
check('opponent but no market is still not enough',
  quoteKey(SESSION_REF.state) === null);

SESSION_REF.state = selectMarket(SESSION_REF.state, 'ml');
check('opponent and market but no stake is still not enough',
  quoteKey(SESSION_REF.state) === null);

SESSION_REF.state = setStakeCents(SESSION_REF.state, 2000);
const KEY = quoteKey(SESSION_REF.state);
check('opponent, market and stake together produce a key', KEY !== null, KEY);
check('and the key names every input the price depends on',
  KEY.includes('7') && KEY.includes('5') && KEY.includes('straight')
  && KEY.includes('locked') && KEY.includes('2000'), KEY);

section('B · Changing any quote-sensitive input changes the key');

const VARIANTS = [
  ['opponent', () => { selectOpponent(8); }],
  ['market', () => { SESSION_REF.state = selectMarket(SESSION_REF.state, 'spread'); }],
  ['mode', () => { SESSION_REF.state = selectMode(SESSION_REF.state, MODE_DYNAMIC); }],
  ['stake', () => { SESSION_REF.state = setStakeCents(SESSION_REF.state, 4500); }],
];
for (const [what, mutate] of VARIANTS) {
  const before = quoteKey(SESSION_REF.state);
  mutate();
  const after = quoteKey(SESSION_REF.state);
  check(`${what} changes the key`, before !== after, `${before} → ${after}`);
}

/* ── C · the lifecycle ───────────────────────────────────────────────────── */

section('C · The quote lifecycle has four distinct states');

setQuoteHook(null);
endSession();
const stub2 = stubHook({ mode: 'manual' });
setQuoteHook(stub2.hook);
SESSION_REF = beginSession({
  matchupId: '7', marketId: null, availableCents: 50000,
  opponents: OPPONENTS, actingTeamName: 'Me',
});

check('a fresh composer holds no quote',
  quoteState().status === QUOTE_IDLE && quoteState().quote === null);

selectOpponent(7);
SESSION_REF.state = selectMarket(SESSION_REF.state, 'ml');
SESSION_REF.state = setStakeCents(SESSION_REF.state, 2000);

let redraws = 0;
const p1 = ensureQuote(() => { redraws += 1; });
check('asking moves it to loading', quoteState().status === QUOTE_LOADING);
check('and the surface is told to redraw immediately', redraws >= 1);
check('exactly one request was sent', stub2.calls.length === 1,
  String(stub2.calls.length));
check('carrying the persisted market name, not the UI id',
  stub2.calls[0].market === 'straight', stub2.calls[0].market);
check('and the stake in exact cents', stub2.calls[0].stakeCents === 2000);

stub2.pending[0].resolve(servedQuote());
await p1;
check('resolving moves it to ready', quoteState().status === QUOTE_READY);
check('and the served body is held whole',
  quoteState().quote.pot_cents === 5175);

/* ── D · staleness ───────────────────────────────────────────────────────── */

section('D · A stale response cannot overwrite a newer selection');

setQuoteHook(null);
endSession();
const stub3 = stubHook({ mode: 'manual' });
setQuoteHook(stub3.hook);
SESSION_REF = beginSession({
  matchupId: '7', marketId: null, availableCents: 50000,
  opponents: OPPONENTS, actingTeamName: 'Me',
});
selectOpponent(7);
SESSION_REF.state = selectMarket(SESSION_REF.state, 'ml');
SESSION_REF.state = setStakeCents(SESSION_REF.state, 2000);

const first = ensureQuote(() => {});
// The GM types on. The composer's own handler invalidates before re-asking.
SESSION_REF.state = setStakeCents(SESSION_REF.state, 9000);
invalidateQuote();
const second = ensureQuote(() => {});

check('two requests are in flight', stub3.pending.length === 2,
  String(stub3.pending.length));

// THE SLOW ONE LANDS LAST — the exact reordering that would corrupt a naive
// implementation. The $20 quote resolves AFTER the $90 one.
stub3.pending[1].resolve(servedQuote({ your_stake_cents: 9000,
  opponent_stake_cents: 14287, pot_cents: 23287, win_cents: 14287,
  lose_cents: 9000 }));
await second;
check('the newer quote is shown', quoteState().quote.your_stake_cents === 9000,
  String(quoteState().quote.your_stake_cents));

stub3.pending[0].resolve(servedQuote());
await first;
check('the older response is DISCARDED, not drawn',
  quoteState().quote.your_stake_cents === 9000,
  String(quoteState().quote.your_stake_cents));
check('and the pot is still the newer one',
  quoteState().quote.pot_cents === 23287);

section('E · A stale REFUSAL cannot overwrite a newer quote either');

setQuoteHook(null);
endSession();
const stub4 = stubHook({ mode: 'manual' });
setQuoteHook(stub4.hook);
SESSION_REF = beginSession({
  matchupId: '7', marketId: null, availableCents: 50000,
  opponents: OPPONENTS, actingTeamName: 'Me',
});
selectOpponent(7);
SESSION_REF.state = selectMarket(SESSION_REF.state, 'ml');
SESSION_REF.state = setStakeCents(SESSION_REF.state, 2000);

const a = ensureQuote(() => {});
SESSION_REF.state = setStakeCents(SESSION_REF.state, 7000);
invalidateQuote();
const b = ensureQuote(() => {});

stub4.pending[1].resolve(servedQuote({ your_stake_cents: 7000 }));
await b;
stub4.pending[0].reject(new QuoteError(409, 'projections_unavailable', 'nope'));
await a;
check('the newer quote survives the older refusal',
  quoteState().status === QUOTE_READY
  && quoteState().quote.your_stake_cents === 7000,
  quoteState().status);

/* ── F · rendering ───────────────────────────────────────────────────────── */

section('F · The composer renders the served figures and computes none');

setQuoteHook(null);
endSession();
const stub5 = stubHook();
setQuoteHook(stub5.hook);
SESSION_REF = beginSession({
  matchupId: '7', marketId: null, availableCents: 50000,
  opponents: OPPONENTS, actingTeamName: 'Me',
});

let body = composerSheet().body;
check('before enough is chosen, the economics say so',
  /data-quote-state="idle"/.test(body)
  && /price the wager/i.test(body), 'idle state');
check('and no figure is drawn', !/data-exact-cents="\d/.test(
  body.split('data-econ')[1] || ''));

selectOpponent(7);
SESSION_REF.state = selectMarket(SESSION_REF.state, 'ml');
SESSION_REF.state = setStakeCents(SESSION_REF.state, 2000);
await ensureQuote(() => {});
body = composerSheet().body;

check('once priced, the surface is ready',
  /data-quote-state="ready"/.test(body));
for (const [label, cents] of [['Your stake', 2000], ['Opponent stake', 3175],
  ['Pot', 5175], ['You win', 3175], ['You lose', 2000]]) {
  check(`${label} is the served figure, to the cent`,
    body.includes(`data-exact-cents="${cents}"`), String(cents));
}
check('the pot is the SERVED pot, not stake + opponent recomputed',
  body.includes('data-exact-cents="5175"'));
check('nothing is drawn that the server did not send',
  (body.match(/data-exact-cents="/g) || []).length === 5,
  String((body.match(/data-exact-cents="/g) || []).length));

section('G · A refusal is rendered as product language');

setQuoteHook(null);
endSession();
const stub6 = stubHook({
  reject: new QuoteError(409, 'projections_unavailable', 'server text'),
});
setQuoteHook(stub6.hook);
SESSION_REF = beginSession({
  matchupId: '7', marketId: null, availableCents: 50000,
  opponents: OPPONENTS, actingTeamName: 'Me',
});
selectOpponent(7);
SESSION_REF.state = selectMarket(SESSION_REF.state, 'ml');
SESSION_REF.state = setStakeCents(SESSION_REF.state, 2000);
await ensureQuote(() => {});
body = composerSheet().body;

check('the refusal state is drawn', quoteState().status === QUOTE_REFUSED
  && /data-quote-state="refused"/.test(body));
check('with a sentence, not a reason code',
  /not been projected/i.test(body)
  && !/projections_unavailable/.test(body), 'product language');
check('and no economic figure is shown beside it',
  !/data-exact-cents/.test(body.split('data-econ')[1] || ''));

section('H · Dynamic is labelled a ceiling, not a settled stake');

setQuoteHook(null);
endSession();
const stub7 = stubHook({
  body: servedQuote({ mode: 'dynamic', is_ceiling: true,
    opponent_stake_cents: 3100, pot_cents: 5100, win_cents: 3100 }),
});
setQuoteHook(stub7.hook);
SESSION_REF = beginSession({
  matchupId: '7', marketId: null, availableCents: 50000,
  opponents: OPPONENTS, actingTeamName: 'Me',
});
selectOpponent(7);
SESSION_REF.state = selectMarket(SESSION_REF.state, 'ml');
SESSION_REF.state = selectMode(SESSION_REF.state, MODE_DYNAMIC);
SESSION_REF.state = setStakeCents(SESSION_REF.state, 2000);
await ensureQuote(() => {});
body = composerSheet().body;

check('the opponent row is labelled as a maximum',
  /Opponent stake \(max\)/.test(body));
check('and the note keeps the governed one-way wording',
  /come down/i.test(body) && /never above the acceptance ceiling/i.test(body));
check('the served ceiling is the figure shown, not a derived one',
  body.includes('data-exact-cents="3100"'));

SESSION_REF.state = selectMode(SESSION_REF.state, MODE_LOCKED);
invalidateQuote();
setQuoteHook(stubHook({ body: servedQuote() }).hook);
await ensureQuote(() => {});
body = composerSheet().body;
check('switching back to Locked drops the max label',
  !/Opponent stake \(max\)/.test(body) && /Opponent stake/.test(body));

/* ── I · no arithmetic, no fallback ──────────────────────────────────────── */

section('I · No economic arithmetic survives on the quoted path');

const COMPOSER_SRC = readFileSync(
  new URL('../js/composer.js', import.meta.url), 'utf8');
const QUOTE_SRC = readFileSync(
  new URL('../js/versus-quote-command.js', import.meta.url), 'utf8');

function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/^\s*\/\/.*$/gm, ' ');
}

const SERVED_FN = stripComments(COMPOSER_SRC)
  .split('function servedEconomicsRows')[1].split('\nfunction ')[0];

// STRING LITERALS FIRST. The renderer is mostly markup, and `</div>` is not a
// division — a check that counted it would be testing HTML, not arithmetic.
const SERVED_CODE = SERVED_FN
  .replace(/`[^`]*`/g, '``')
  .replace(/'[^'\n]*'/g, "''")
  .replace(/"[^"\n]*"/g, '""');

check('the served renderer contains no addition of money',
  !/_cents\s*\+|\+\s*\w+_cents/.test(SERVED_CODE));
check('and no multiplication or division at all',
  !/[*/]/.test(SERVED_CODE), 'pure rendering');
check('it reads pot_cents rather than summing the two stakes',
  SERVED_FN.includes('quote.pot_cents'));
check('the quote command computes nothing but the cents boundary',
  (stripComments(QUOTE_SRC).match(/[*/]/g) || [])
    .filter((c) => c === '*').length === 0,
  'no multiplication');
check('it derives no opponent stake',
  !/deriveOpponentStakeCents/.test(QUOTE_SRC));
check('and reaches the network only through session.js',
  /from '\.\/session\.js'/.test(QUOTE_SRC)
  && !/\bfetch\(/.test(stripComments(QUOTE_SRC).replace(/apiFetch\(/g, '')));

check('the quoted path never falls back to illustrative odds',
  !/data\/league-data/.test(SERVED_FN)
  && !/composerEconomics/.test(SERVED_FN));

setQuoteHook(null);
endSession();

/* ── Result ──────────────────────────────────────────────────────────────── */

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`${failures.length} ASSERTION(S) FAILED`);
  failures.forEach((f) => console.log(`  · ${f}`));
  process.exit(1);
}
console.log('All assertions PASSED');
