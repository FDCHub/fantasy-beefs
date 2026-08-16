/* ============================================================================
 * FantasyStakes — WP3C.2 · authoritative Versus market lines · component tests
 *
 * Run directly:   node web/tests/wp3c2_component_tests.mjs
 * Or through:     python test_wp3c2_versus_market_lines.py
 *
 * THE COMPOSER AND THE PLAY CARD, DRIVEN AGAINST A BOARD THIS SUITE WRITES.
 * That control is the point. A served board is a handful of numbers, and the
 * only way to prove the browser RENDERS them rather than deriving them is to
 * serve numbers no derivation would produce: a spread whose sign disagrees with
 * the moneyline, a total that is not the two projections added up, an
 * unavailable row beside an available one.
 * ========================================================================== */

import {
  QUOTE_IDLE, QUOTE_READY,
  beginSession, composerSheet, endSession, ensureQuote, invalidateQuote,
  marketLine, quoteKey, quoteState, selectOpponent, servedMarket,
  setMarketHook, setQuoteHook,
} from '../js/composer.js';

import {
  MODE_DYNAMIC, SIDES, selectMarket, selectMode, selectSide, setStakeCents,
} from '../js/wager-model.js';

import {
  bindMarketBoard, markMarketBoardUnavailable, marketAvailable, marketFor,
  marketMode, marketWeek, unbindMarketBoard,
} from '../js/market-model.js';

import { readFileSync } from 'node:fs';

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

/**
 * A served board.
 *
 * TEAM 7 IS A FAVOURITE, TEAM 8 IS UNPRICEABLE. Both rows are needed: an
 * available row proves the figures are drawn, and an unavailable one proves the
 * absence is drawn as an absence rather than as a zero.
 *
 * THE NUMBERS ARE DELIBERATELY UNRELATABLE. `−3.5` at `−162` with a total of
 * `211.5` is not derivable from anything else on the page, so a surface that
 * showed the right value can only have read it.
 */
function servedBoard(over = {}) {
  return {
    league_id: 1,
    week: 5,
    acting_team_id: 1,
    markets: [
      {
        opponent_team_id: 7,
        opponent_name: 'Alpha',
        available: true,
        unavailable_reason: null,
        reason_code: null,
        acting_moneyline: -162,
        opponent_moneyline: 162,
        spread_line: 3.5,
        acting_spread: -3.5,
        opponent_spread: 3.5,
        total_line: 211.5,
      },
      {
        opponent_team_id: 8,
        opponent_name: 'Bravo',
        available: false,
        unavailable_reason: 'One of these teams has no starting lineup for '
          + 'this week yet, so the matchup cannot be priced.',
        reason_code: 'roster_unavailable',
        acting_moneyline: null,
        opponent_moneyline: null,
        spread_line: null,
        acting_spread: null,
        opponent_spread: null,
        total_line: null,
      },
    ],
    ...over,
  };
}

function stubQuote(opts = {}) {
  const calls = [];
  return {
    calls,
    hook: {
      leagueId: 1,
      week: 5,
      explain: (e) => e.message,
      request(spec) {
        calls.push(spec);
        if (opts.reject) return Promise.reject(opts.reject);
        return Promise.resolve({
          league_id: 1, acting_team_id: 1, opponent_team_id: spec.opponentTeamId,
          week: 5, market: spec.market, mode: spec.mode,
          your_stake_cents: spec.stakeCents,
          opponent_stake_cents: 1900, pot_cents: 3900,
          win_cents: 1900, lose_cents: spec.stakeCents,
          anchor_odds: 1.95, derived_odds: 2.05,
          anchor_moneyline: -105, derived_moneyline: 105,
          is_ceiling: false,
          line: spec.line, display_line: spec.line === null ? null : -spec.line,
          side: spec.side,
        });
      },
    },
  };
}

/* ── A · the served board model ──────────────────────────────────────────── */

section('A · The board is held, never computed');

unbindMarketBoard();
check('an unbound model is in demo and offers nothing',
  marketMode() === 'demo' && marketFor(7) === null && marketWeek() === null);

markMarketBoardUnavailable();
check('a failed read is UNAVAILABLE, which is not the same as empty',
  marketMode() === 'unavailable' && marketFor(7) === null);

bindMarketBoard(servedBoard());
check('a bound board reports its week', marketWeek() === 5);
check('and serves the row for each opponent',
  marketFor(7).acting_spread === -3.5 && marketFor(8).available === false);
check('an opponent nobody asked about is null, not a blank row',
  marketFor(99) === null);
check('availability is the server’s answer, not an inference from the fields',
  marketAvailable(7) === true && marketAvailable(8) === false);

bindMarketBoard(null);
check('a malformed body binds nothing and reports unavailable',
  marketMode() === 'unavailable' && marketFor(7) === null);

/* ── B · the composer reads the board ────────────────────────────────────── */

section('B · The composer reads the served line and derives none');

bindMarketBoard(servedBoard());
setQuoteHook(null);
setMarketHook(null);
endSession();

let SESSION = beginSession({
  matchupId: '7', marketId: null, availableCents: 50000,
  opponents: OPPONENTS, actingTeamName: 'Gravy Train',
});

check('with no market hook the composer sees no board',
  servedMarket(SESSION.state) === null);

setMarketHook({ marketFor });
check('with one installed it sees the row for the preselected opponent',
  servedMarket(SESSION.state).opponent_team_id === 7);

SESSION.state = selectMarket(SESSION.state, 'ml');
check('a Moneyline has no line, and that is the answer not a gap',
  marketLine(SESSION.state) === null);

SESSION.state = selectMarket(SESSION.state, 'spread');
check('a spread reads the CANONICAL line, not the display value',
  marketLine(SESSION.state) === 3.5, String(marketLine(SESSION.state)));

SESSION.state = selectMarket(SESSION.state, 'ou');
check('a total reads the served total', marketLine(SESSION.state) === 211.5,
  String(marketLine(SESSION.state)));

selectOpponent(8);
check('an unpriceable opponent yields no line at all',
  marketLine(SESSION.state) === null);
selectOpponent(7);

/* ── C · what the composer draws ─────────────────────────────────────────── */

section('C · The market row shows the server’s figures');

SESSION.state = selectMarket(SESSION.state, 'spread');
let body = composerSheet().body;

check('the three market cells carry the served values',
  body.includes('−162') || body.includes('-162'),
  'moneyline');
check('the spread cell is the SERVED sportsbook value',
  body.includes('−3.5'), 'spread cell');
check('the total cell is the served total', body.includes('211.5'));
check('the spread detail names the acting team and its signed line',
  body.includes('Gravy Train −3.5'), 'identity + line');
check('and says in words who is giving the points',
  body.includes('Gravy Train gives 3.5 points to Alpha'),
  'plain-language grammar');
check('the exact served line travels on the element, unrounded',
  body.includes('data-exact-line="-3.5"'));
check('no free-form line input is offered',
  !body.includes('data-composer-line'));

SESSION.state = selectMarket(SESSION.state, 'ou');
body = composerSheet().body;
check('the total detail states the combined total',
  body.includes('Combined total 211.5'));
check('and offers BOTH sides', body.includes('data-composer-side="over"')
  && body.includes('data-composer-side="under"'));
check('with neither pre-selected — nothing is chosen for the GM',
  !body.includes('data-composer-side="over" aria-pressed="true"')
  && !body.includes('data-composer-side="under" aria-pressed="true"'));
check('and it says so', body.includes('Choose Over or Under to price'));

SESSION.state = selectSide(SESSION.state, 'under');
body = composerSheet().body;
check('choosing Under marks Under and only Under',
  body.includes('data-composer-side="under" aria-pressed="true"')
  && body.includes('data-composer-side="over" aria-pressed="false"'));
check('and the prompt goes once a side is held',
  !body.includes('Choose Over or Under to price'));

selectOpponent(8);
SESSION.state = selectMarket(SESSION.state, 'spread');
body = composerSheet().body;
check('an unpriceable pairing shows the server’s own sentence',
  body.includes('no starting lineup'), 'product language');
check('and NO figure — not a zero, not a pick’em',
  !body.includes('data-exact-line') && !body.includes('PK'));
selectOpponent(7);

/* ── D · the quote identity ──────────────────────────────────────────────── */

section('D · The line and the side are part of the quote’s identity');

const quote = stubQuote();
setQuoteHook(quote.hook);
SESSION.state = selectMarket(SESSION.state, 'spread');
SESSION.state = setStakeCents(SESSION.state, 2000);

const SPREAD_KEY = quoteKey(SESSION.state);
check('a spread is quotable once the board has a line', SPREAD_KEY !== null,
  SPREAD_KEY);
check('and the key names the line it will be priced against',
  SPREAD_KEY.includes('3.5'), SPREAD_KEY);

SESSION.state = selectMarket(SESSION.state, 'ou');
check('a total with no side is NOT quotable',
  quoteKey(SESSION.state) === null);
SESSION.state = selectSide(SESSION.state, 'over');
const OVER_KEY = quoteKey(SESSION.state);
check('picking Over makes it quotable', OVER_KEY !== null, OVER_KEY);
SESSION.state = selectSide(SESSION.state, 'under');
check('and Under is a DIFFERENT quote, not the same one relabelled',
  quoteKey(SESSION.state) !== OVER_KEY,
  `${OVER_KEY} vs ${quoteKey(SESSION.state)}`);

SESSION.state = selectMarket(SESSION.state, 'ml');
SESSION.state = setStakeCents(SESSION.state, 2000);
const ML_KEY = quoteKey(SESSION.state);
check('a Moneyline is quotable with no line and no side', ML_KEY !== null);
check('and its key carries neither', !ML_KEY.includes('3.5')
  && !ML_KEY.includes('over'), ML_KEY);

// THE MARKET MOVING IS A NEW QUOTE. This is the claim §27 of the package asks
// for: a board that changes under an open composer must change the identity, so
// the economics for the old line cannot survive beside the new one.
SESSION.state = selectMarket(SESSION.state, 'spread');
const BEFORE_MOVE = quoteKey(SESSION.state);
const moved = servedBoard();
moved.markets[0].spread_line = 4.0;
moved.markets[0].acting_spread = -4.0;
bindMarketBoard(moved);
check('a moved line changes the quote identity',
  quoteKey(SESSION.state) !== BEFORE_MOVE,
  `${BEFORE_MOVE} → ${quoteKey(SESSION.state)}`);
bindMarketBoard(servedBoard());

/* ── E · what the composer sends ─────────────────────────────────────────── */

section('E · The composer asserts the served line; it never invents one');

invalidateQuote();
SESSION.state = selectMarket(SESSION.state, 'spread');
SESSION.state = setStakeCents(SESSION.state, 2500);
await ensureQuote(() => {});

check('a quote was requested', quote.calls.length === 1);
const sent = quote.calls[0];
check('carrying the persisted market name', sent.market === 'spread');
check('and the CANONICAL line, not the displayed one',
  sent.line === 3.5, String(sent.line));
check('with no side, because a spread has none', sent.side === null);
check('and the answer is held', quoteState().status === QUOTE_READY);

invalidateQuote();
SESSION.state = selectMarket(SESSION.state, 'ou');
SESSION.state = selectSide(SESSION.state, 'under');
await ensureQuote(() => {});
const sentOu = quote.calls[quote.calls.length - 1];
check('a total sends the served total and the GM’s own side',
  sentOu.market === 'over_under' && sentOu.line === 211.5
  && sentOu.side === 'under',
  JSON.stringify(sentOu));

invalidateQuote();
SESSION.state = selectMarket(SESSION.state, 'ml');
await ensureQuote(() => {});
const sentMl = quote.calls[quote.calls.length - 1];
check('a Moneyline sends no line at all', sentMl.line === null);

/* ── F · leaving a total drops the side ──────────────────────────────────── */

section('F · A side belongs to the market it was chosen on');

let s = selectMarket(SESSION.state, 'ou');
s = selectSide(s, 'over');
check('the side is held while the total is selected', s.side === 'over');
s = selectMarket(s, 'spread');
check('and cleared on leaving it', s.side === null);
s = selectMarket(s, 'ou');
check('returning does not silently restore it', s.side === null);
check('the two sides are the only two', SIDES.join(',') === 'over,under');

let threw = false;
try { selectSide(s, 'sideways'); } catch { threw = true; }
check('an invented side is refused by the model', threw);

/* ── G · Dynamic is untouched ────────────────────────────────────────────── */

section('G · The ruling changed the line, not the wager model');

invalidateQuote();
SESSION.state = selectMarket(SESSION.state, 'spread');
SESSION.state = selectMode(SESSION.state, MODE_DYNAMIC);
SESSION.state = setStakeCents(SESSION.state, 2500);
const DYN_KEY = quoteKey(SESSION.state);
check('a Dynamic spread is quotable', DYN_KEY !== null);
check('and the mode is still part of the identity', DYN_KEY.includes('dynamic'),
  DYN_KEY);
await ensureQuote(() => {});
check('it sends the same authoritative line as Locked did',
  quote.calls[quote.calls.length - 1].line === 3.5);
check('and the mode it was composed in',
  quote.calls[quote.calls.length - 1].mode === MODE_DYNAMIC);

/* ── H · demo is unchanged ───────────────────────────────────────────────── */

section('H · A composer with no board draws the demo surface, not a broken one');

setMarketHook(null);
setQuoteHook(null);
endSession();
const demo = beginSession({
  matchupId: 'destroyers', marketId: null, availableCents: 50000,
  opponents: [], actingTeamName: null,
});
const demoBody = composerSheet().body;
check('the demo composer still renders', demoBody.includes('MARKET'));
check('with the fixture’s own cells', demoBody.includes('fs-seg--market'));
check('and no market-detail row, because there is no served board',
  !demoBody.includes('data-market-detail'));
check('nor any Over/Under control',
  !demoBody.includes('data-composer-side'));
check('demo state carries a null side, never a default',
  demo.state.side === null);

/* ── I · no line mathematics in the browser ──────────────────────────────── */

section('I · The browser formats lines and computes none');

const src = (name) => readFileSync(
  new URL(`../js/${name}`, import.meta.url), 'utf8');

function codeOnly(text) {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/^\s*\/\/.*$/gm, ' ')
    .replace(/`[^`]*`/g, '``')
    .replace(/'[^'\n]*'/g, "''")
    .replace(/"[^"\n]*"/g, '""');
}

const MARKET_MODEL = codeOnly(src('market-model.js'));
const COMPOSER = codeOnly(src('composer.js'));
const LEAGUE = codeOnly(src('league.js'));

check('market-model.js holds and returns — no operator anywhere',
  !/[*/+-]/.test(MARKET_MODEL.replace(/=>/g, '')), 'pure');
for (const [name, text] of [['composer.js', COMPOSER], ['league.js', LEAGUE]]) {
  check(`${name} computes no median`, !/median/i.test(text));
  check(`${name} rounds nothing to a half point`,
    !/Math\.round|\*\s*2\s*\)|0\.5/.test(text));
  check(`${name} reads acting_spread rather than negating anything`,
    text.includes('acting_spread')
    && !/-\s*(served|row|board)\.\w*spread/.test(text));
}
check('the composer sends marketLine(state), which is a read',
  COMPOSER.includes('line: marketLine(state)'));
check('and marketLine picks a served field rather than deriving one',
  /spread_line\s*:\s*row\.total_line|row\.spread_line/.test(COMPOSER));

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`${failures.length} ASSERTION(S) FAILED`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
console.log('All assertions PASSED');
