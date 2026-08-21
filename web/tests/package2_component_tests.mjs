/* ============================================================================
 * FantasyStakes — Sprint 7 Package 2 · behavioural tests
 *
 * Run directly:   node web/tests/package2_component_tests.mjs
 * Or through:     python test_s7_p2_league_action.py
 *
 * Drives the shipped modules. The assertions that matter most are the ones
 * that pin UI copy to the governing ruling and UI groupings to protocol state.
 * ========================================================================== */

import {
  MARKETS,
  MIN_STAKE_CENTS,
  MODE_COPY,
  MODE_DYNAMIC,
  MODE_LOCKED,
  composerEconomics,
  createComposerState,
  deriveOpponentStakeCents,
  dynamicCeilingNote,
  formatOdds,
  lockedFreezeNote,
  parseStakeInput,
  selectMarket,
  selectMode,
  setStakeCents,
  validateComposer,
} from '../js/wager-model.js';

import {
  formatSpread,
  impliedProbability,
  mirrorOdds,
  sportsbookView,
  theRead,
  whyTheLine,
} from '../js/narrative.js';

import {
  OPPONENTS,
  POOLS,
  YOUR_LINEUP,
  YOUR_PROJECTION,
  allMatchups,
  matchup,
  poolBadge,
} from '../js/data/league-data.js';

import {
  CARDS,
  RAILS,
  betThisWeekCents,
  cardsFor,
  lifecycleOf,
  railHeading,
  seasonRecordLabel,
  settledCents,
  upsideLeftCents,
} from '../js/data/action-data.js';

import { buildLeaguePanel } from '../js/league.js';
import { ACTION_HEADER, buildActionPanel, lifecycleCard } from '../js/action.js';
import { matchupCard, matchupMarketCells } from '../js/wagercard.js';
import { beginSession, composerSheet, currentSession, endSession } from '../js/composer.js';
import { previewSheet } from '../js/preview.js';
import { countDisclaimers } from '../js/components.js';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

function throws(fn) {
  try { fn(); return false; } catch { return true; }
}

function section(title) { console.log(`\n${title}`); }

/* ── Locked / Dynamic copy against the ruling ───────────────────────────── */

section('Mode copy does not contradict the adopted Locked/Dynamic ruling');

const dynamicBody = MODE_COPY[MODE_DYNAMIC].body;
const lockedBody = MODE_COPY[MODE_LOCKED].body;

// REVISED BY S8-P4C-2R2, ON EXPLICIT AUTHORISATION — and revised rather than
// relaxed. The verbatim pin above froze the §5.3 text including its timing
// clause, "lock in at kickoff". That phrase was checked against the governing
// trigger and found ambiguous: GE-901 / AP-212 fix Final Lock immediately
// before the EARLIEST scheduled kickoff among players in EITHER covered final
// Yahoo starting lineup, so "kickoff" invites a GM to picture their own
// matchup's Sunday start when a covered Thursday-night starter — on either
// side — locks the whole wager days earlier.
//
// A verbatim pin cannot survive a correction to the text it pins, so what the
// pin was PROTECTING is asserted directly instead: every substantive claim the
// §5.3 copy makes about the economics, each checked on its own. Those claims
// are unchanged. Only the timing clause moved, and the trigger it now names is
// certified against the trigger's real behaviour in
// `test_s8_p4c2r2_final_lock_copy.py`.
check(
  'Dynamic copy does not say a stake can flex up — the retired conflict',
  !/flex up|flex up or down|can go up|may increase/i.test(dynamicBody),
);
check('Dynamic copy states the issuer stake is fixed',
  /Anchor Stake stays fixed/i.test(dynamicBody), dynamicBody);
check('Dynamic copy states the derived stake may only come down',
  /come\s+down/i.test(dynamicBody) && /never above/i.test(dynamicBody),
  dynamicBody);
check('Dynamic copy states the ceiling bounds it',
  /ceiling/i.test(dynamicBody), dynamicBody);
check('Dynamic copy names Final Lock as the event',
  /Final Lock/i.test(dynamicBody), dynamicBody);
check('and the first COVERED player’s game as the trigger',
  /first covered player/i.test(dynamicBody), dynamicBody);
check('never the GM’s own first player',
  !/(first of your players|your first player)/i.test(dynamicBody), dynamicBody);

const lockedCopy = `${MODE_COPY[MODE_LOCKED].headline} ${lockedBody}`;
check('Locked copy states terms freeze on creation, not on acceptance',
  /freez|frozen/i.test(lockedCopy) && /captured now/i.test(lockedBody));
check('Locked copy states Yahoo changes never touch the terms',
  /Yahoo lineup changes/i.test(lockedBody) && /never touch/i.test(lockedBody));
check('Locked copy states acceptance does not reprice',
  /not repriced on acceptance/i.test(lockedBody));
check('Locked copy names Refresh & Relock as the only way to change terms',
  /Refresh & Relock/i.test(lockedBody));
check('Locked copy does not claim the wager freezes at acceptance',
  !/freezes? (only )?(at|on) acceptance/i.test(lockedBody));

check('the ceiling note never promises the derived stake can rise',
  !/can (go|come) up|may rise/i.test(dynamicCeilingNote({ opponentStakeCents: 3300 })));
check('the locked note says acceptance selects the frozen terms',
  /Accepting selects them unchanged/.test(lockedFreezeNote()));

/* ── Market vocabulary ──────────────────────────────────────────────────── */

section('Betting vocabulary and persisted values');

check('three markets', MARKETS.length === 3);
// UIRECON WAVE 3A — `label` carries the locked PUBLIC wording, which the
// composer's market selector draws. `short` keeps the abbreviations for the
// narrow three-cell rows on the Play card and the Status rails, and is asserted
// separately below so the two cannot be confused for one field.
check('the public labels are Moneyline, Spread and Over/Under',
  MARKETS.map((m) => m.label).join(' ') === 'Moneyline Spread Over/Under');
check('the narrow-cell abbreviations are unchanged',
  MARKETS.map((m) => m.short).join(' ') === 'ML SPR O/U');
check('ML persists as the engine\'s `straight`',
  MARKETS.find((m) => m.id === 'ml').persisted === 'straight');
check('Spread persists as `spread`',
  MARKETS.find((m) => m.id === 'spread').persisted === 'spread');
check('O/U persists as `over_under`',
  MARKETS.find((m) => m.id === 'ou').persisted === 'over_under');
check('the minimum stake is the engine\'s MIN_BET of $5.00', MIN_STAKE_CENTS === 500);
check('odds format with an explicit plus', formatOdds(165) === '+165');
check('negative odds keep their sign', formatOdds(-150) === '−150' || formatOdds(-150) === '-150',
  formatOdds(-150));

/* ── Composer state ─────────────────────────────────────────────────────── */

section('The composer opens at $0, untouched');

let state = createComposerState({ opponent: { id: 'x', name: 'X' }, availableCents: 6500 });
check('the stake opens at zero', state.stakeCents === 0);
check('the composer opens untouched', state.touched === false);
check('no market is selected by a whole-card open', state.marketId === null);
check('Locked is the opening mode', state.mode === MODE_LOCKED);
check('an untouched composer offers the funding rule, not an error',
  validateComposer(state).hint === 'Wagers fund from Weekly Min first, then Wallet.');

const preselected = createComposerState({
  opponent: { id: 'x', name: 'X' }, marketId: 'spread', availableCents: 6500,
});
check('a market tap opens the composer with that market selected',
  preselected.marketId === 'spread');
check('the stake still opens at $0 when a market was tapped', preselected.stakeCents === 0);
check('an unknown market is refused', throws(() => createComposerState({
  opponent: { id: 'x', name: 'X' }, marketId: 'parlay', availableCents: 6500,
})));

section('Send stays disabled until every rule is satisfied');

check('$0 cannot be sent', validateComposer(state).ok === false);
state = selectMarket(state, 'ml');
check('a market alone does not enable send', validateComposer(state).ok === false);
state = setStakeCents(state, 100);
check('below the $5 minimum cannot be sent', validateComposer(state).ok === false);
check('the reason names the minimum',
  /minimum stake is \$5/.test(validateComposer(state).reasons[0]),
  validateComposer(state).reasons[0]);
state = setStakeCents(state, 500);
check('exactly the minimum can be sent', validateComposer(state).ok === true);
state = setStakeCents(state, 6600);
check('more than available cannot be sent', validateComposer(state).ok === false);
check('the reason names the available figure',
  /\$65 available/.test(validateComposer(state).reasons[0]),
  validateComposer(state).reasons[0]);
state = setStakeCents(state, 6500);
check('exactly available can be sent', validateComposer(state).ok === true);
check('a market must be chosen',
  validateComposer({ ...state, marketId: null }).ok === false);
check('entering a stake marks the composer touched', state.touched === true);
check('clearing back to zero returns to untouched',
  setStakeCents(state, 0).touched === false);

section('Stake entry refuses what the engine refuses');

check('plain dollars parse', parseStakeInput('20').cents === 2000);
check('a dollar sign is tolerated', parseStakeInput('$20').cents === 2000);
check('thousands separators are tolerated', parseStakeInput('1,200').cents === 120000);
check('cents parse exactly', parseStakeInput('20.05').cents === 2005);
check('one decimal place parses', parseStakeInput('20.5').cents === 2050);
check('a sub-cent stake is refused, not rounded',
  parseStakeInput('20.005').error === 'Stakes are whole cents.');
check('letters are refused', Boolean(parseStakeInput('twenty').error));
check('a negative is refused', Boolean(parseStakeInput('-5').error));
check('an empty field is the untouched zero', parseStakeInput('').cents === 0);
check('a negative stake cannot be set', throws(() => setStakeCents(state, -100)));

/* ── Economics ──────────────────────────────────────────────────────────── */

section('Composer economics are exact and never reprice');

check('a $20 stake at +165 meets $33', deriveOpponentStakeCents(2000, 165) === 3300);
check('a $34 stake at −170 meets $20', deriveOpponentStakeCents(3400, -170) === 2000);
check('a $25 stake at −125 meets $20', deriveOpponentStakeCents(2500, -125) === 2000);
check('derivation returns exact integer cents',
  Number.isSafeInteger(deriveOpponentStakeCents(1234, 137)));
check('a fractional stake is refused', throws(() => deriveOpponentStakeCents(20.5, 165)));
check('zero odds are refused', throws(() => deriveOpponentStakeCents(2000, 0)));

const econState = setStakeCents(selectMarket(
  createComposerState({ opponent: { id: 'x', name: 'X' }, availableCents: 6500 }), 'ml'), 2000);
const econ = composerEconomics(econState, { odds: 165 });
check('the pot is both stakes', econ.potCents === econ.yourStakeCents + econ.opponentStakeCents);
check('you win the opponent stake', econ.winCents === econ.opponentStakeCents);
check('you lose your own stake', econ.loseCents === econ.yourStakeCents);
check('an unquoted line is marked as derived', econ.quoted === false);

const quotedEcon = composerEconomics(econState, { odds: 165, quotedDerivedStakeCents: 3936 });
check('a quote from the pricing seam is used unchanged',
  quotedEcon.opponentStakeCents === 3936 && quotedEcon.quoted === true);

/* ── League dataset consistency ─────────────────────────────────────────── */

section('League matchups are internally consistent');

check('eleven opponents', OPPONENTS.length === 11);
check('your projection is the sum of your own lineup',
  YOUR_PROJECTION === Math.round(YOUR_LINEUP.reduce((s, r) => s + r.projection, 0) * 10) / 10,
  String(YOUR_PROJECTION));

for (const m of allMatchups()) {
  check(
    `${m.name}: moneyline and spread agree in direction`,
    (m.ml > 0) === (m.spread > 0),
    `ml ${m.ml}, spread ${m.spread}`,
  );
  check(
    `${m.name}: their projection is yours plus the spread`,
    Math.abs(m.opponentProjection - (m.yourProjection + m.spread)) < 0.05,
    `${m.yourProjection} + ${m.spread} vs ${m.opponentProjection}`,
  );
  check(
    `${m.name}: the total is the two projections added`,
    Math.abs(m.total - (m.yourProjection + m.opponentProjection)) < 0.05,
    `${m.total}`,
  );
  check(
    `${m.name}: their lineup sums to their projection`,
    Math.abs(m.opponentLineup.reduce((s, r) => s + r.projection, 0) - m.opponentProjection) < 0.051,
  );
  check(`${m.name}: nine starters a side`,
    m.yourLineup.length === 9 && m.opponentLineup.length === 9);
}

check('your projection is the same on every card',
  new Set(allMatchups().map((m) => m.yourProjection)).size === 1);
check('no GM opposes themselves',
  !OPPONENTS.some((o) => o.name === matchup(o.id).you.name));
check('every matchup carries its own teaser',
  new Set(OPPONENTS.map((o) => o.teaser)).size === 11);

/* ── Narrative grounding ────────────────────────────────────────────────── */

section('Analysis is grounded in lineup, projection and market inputs only');

// Word-anchored: a substring test would flag "B-rain- Trust" for weather and
// call a team name a forbidden claim.
const FORBIDDEN = [
  'injur', 'questionable', 'doubtful', 'ruled out', 'weather', 'wind', 'rain',
  'snow', 'practice', 'beat writer', 'report', 'trade', 'suspend', 'coach',
  'snap count', 'target share', 'news',
];

const allProse = allMatchups()
  .flatMap((m) => [...whyTheLine(m), ...theRead(m), m.teaser])
  .join(' ')
  .toLowerCase();

for (const word of FORBIDDEN) {
  const pattern = new RegExp(`\\b${word.replace(/ /g, '\\s+')}`, 'i');
  check(`no unsupported context: "${word}"`, !pattern.test(allProse));
}

check('implied probability of +165', impliedProbability(165) === 37.7, String(impliedProbability(165)));
check('implied probability of −150', impliedProbability(-150) === 60, String(impliedProbability(-150)));
check('the opposite side is the mirror of the quoted line', mirrorOdds(165) === -165);
check('spreads format with a sign', formatSpread(4.5) === '+4.5' && formatSpread(-7.5) === '−7.5');

const view = sportsbookView(matchup('destroyers'));
check('the sportsbook view carries ML for both sides',
  view.rows.filter((r) => r.label.startsWith('ML')).length === 2);
check('the sportsbook view carries the spread, total and projected score',
  ['Spread · your side', 'Total', 'Projected score'].every(
    (label) => view.rows.some((r) => r.label === label)));
check('the favourite is named', Boolean(view.favourite));

/* ── Pools ──────────────────────────────────────────────────────────────── */

section('Pools follow the catalog and treat rollover as a modifier');

check('exactly four Pools this week', POOLS.length === 4);
check('every Pool subject is TEAM or MATCHUP',
  POOLS.every((p) => ['TEAM', 'MATCHUP'].includes(p.scope)));
check('ROLLOVER is never a subject type on its own',
  !POOLS.some((p) => p.scope.includes('ROLLOVER')));
check('a continuation badges its type with the modifier',
  poolBadge(POOLS.find((p) => p.continuation)) === 'TEAM · ROLLOVER');
check('a non-continuation badges its type alone',
  POOLS.filter((p) => !p.continuation).every((p) => poolBadge(p) === p.scope));
check('only a rollover-eligible Pool may be a continuation',
  POOLS.filter((p) => p.continuation).every((p) => p.rolloverEligible === true));
check('every Pool carries a deterministic rule', POOLS.every((p) => Boolean(p.rule)));
check('every Pool carries its catalog number',
  POOLS.every((p) => Number.isInteger(p.catalogNumber)));
check('entry sits inside the configured bounds of $1–$5',
  POOLS.every((p) => p.entryCents >= 100 && p.entryCents <= 500));

/* ── Cards ──────────────────────────────────────────────────────────────── */

section('One card grammar for League and Action');

const card = matchupCard(matchup('destroyers'));
check('a matchup card names both teams', /Your Team vs CULV Destroyers/.test(card));
check('a matchup card carries the three-cell market row',
  (card.match(/data-market="/g) || []).length === 3);
check('market cells are real buttons', /<button[^>]*data-market=/.test(card));
check('a matchup card carries the projected score', /Projected/.test(card));
check('a matchup card carries its teaser', /Biggest dog on the board/.test(card));
check('a matchup card carries a challenge affordance', /Challenge/.test(card));
check('the whole card is a tap target', /data-card-action="challenge"/.test(card));

const cells = matchupMarketCells(matchup('destroyers'));
check('market cells are ML, SPR and O/U',
  cells.map((c) => c.label).join(' ') === 'ML SPR O/U');

const liveCard = lifecycleCard(CARDS.find((c) => c.id === 'liv-goodfellas'));
const doneCard = lifecycleCard(CARDS.find((c) => c.id === 'cmp-enforcers'));
for (const [name, html] of [['live', liveCard], ['completed', doneCard]]) {
  check(`the ${name} card uses the shared wager-card grammar`, /class="fs-wcard/.test(html));
  check(`the ${name} card names the opponent`, /fs-wcard__identity/.test(html));
  check(`the ${name} card carries the market and mode`, /fs-wcard__context/.test(html));
  check(`the ${name} card carries both stakes and the pot`,
    /You<\/span>/.test(html) && /Them<\/span>/.test(html) && /Pot<\/span>/.test(html));
}
check('a completed card adds the net result', /Net<\/span>/.test(doneCard));
check('a live card does not pretend to a net result', !/Net<\/span>/.test(liveCard));
check('a completed card keeps a final score', /119.7/.test(doneCard));
check('money on a card carries its exact cents',
  (doneCard.match(/data-exact-cents="/g) || []).length >= 4);

/* ── Action lifecycle over protocol state ───────────────────────────────── */

section('Lifecycle rails are a grouping over protocol state, never a rename');

check('four rails', RAILS.length === 4);
check('rail order is Action Required, Waiting, Live, Completed',
  RAILS.join(' ') === 'action waiting live completed');
check('ACTION REQUIRED holds two', cardsFor('action').length === 2);
check('WAITING holds two', cardsFor('waiting').length === 2);
check('LIVE holds four', cardsFor('live').length === 4);
check('COMPLETED holds the settled wagers', cardsFor('completed').length === 3);

check('every card carries its persisted protocol state',
  CARDS.every((c) => ['offered', 'countered', 'accepted', 'declined', 'expired', 'cancelled']
    .includes(c.protocolState)));
check('every card names its Response Card',
  CARDS.every((c) => ['Incoming', 'Accepted', 'Countered', 'Declined', 'Expired']
    .includes(c.responseCard)));
check('an incoming offer needs your decision',
  lifecycleOf(CARDS.find((c) => c.id === 'inc-destroyers')) === 'action');
check('a counter you received as issuer is actionable — Response Card §6.1',
  lifecycleOf(CARDS.find((c) => c.id === 'ctr-racket')) === 'action');
check('a counter you sent is read-only and waits — §6.2',
  lifecycleOf(CARDS.find((c) => c.id === 'ctr-braintrust')) === 'waiting');
check('your sent offer waits', lifecycleOf(CARDS.find((c) => c.id === 'snt-bombers')) === 'waiting');
check('accepted is live', lifecycleOf(CARDS.find((c) => c.id === 'liv-cartel')) === 'live');
check('settled is completed', lifecycleOf(CARDS.find((c) => c.id === 'cmp-gravy')) === 'completed');
check('an unknown protocol state has no rail',
  throws(() => lifecycleOf({ protocolState: 'invented', role: 'issuer' })));

section('Action strip figures are derived from the cards and match the locked values');

check('Season Bet Record is 14–7', seasonRecordLabel() === '14–7');
check('Bet this week derives to $129', betThisWeekCents() === 12900, String(betThisWeekCents()));
check('Upside left derives to +$129', upsideLeftCents() === 12900, String(upsideLeftCents()));
check('Settled derives to +$20', settledCents() === 2000, String(settledCents()));
check('an incoming offer commits none of your money',
  CARDS.find((c) => c.id === 'inc-destroyers').committed === false);
check('every open wager\'s pot is both stakes',
  CARDS.filter((c) => c.committed)
    .every((c) => c.potCents === c.yourStakeCents + c.opponentStakeCents));

section('Rail headings match the locked wording');

check('ACTION REQUIRED 2', railHeading('action') === 'ACTION REQUIRED 2');
check('WAITING 2', railHeading('waiting') === 'WAITING 2');
check('LIVE 4', railHeading('live') === 'LIVE 4');
check('COMPLETED · 14–7 SEASON', railHeading('completed') === 'COMPLETED · 14–7 SEASON');

// S8-P4C-2R — THE DEMO HALF OF THE SEASON-RECORD REPAIR. Production drops the
// record because 14–7 has no authoritative source; the locked Rev 4.2 heading
// must survive here, where the illustrative fixture IS the subject. The two
// halves are asserted in different suites on purpose: this one has no server,
// and the browser suite has no fixture.
const { railHeading: uiRailHeading } = await import('../js/action.js');
const { actionMode } = await import('../js/action-model.js');
check('the shipped heading is in demo mode by default', actionMode() === 'demo');
check('and the shipped COMPLETED heading keeps the locked record in demo',
  uiRailHeading('completed') === 'COMPLETED · 14–7 SEASON',
  uiRailHeading('completed'));
check('while ACTION REQUIRED still counts the fixture in demo',
  uiRailHeading('action') === 'ACTION REQUIRED 2', uiRailHeading('action'));

/* ── Panels ─────────────────────────────────────────────────────────────── */

section('League and Action panels');

const league = buildLeaguePanel();
// WP3C RE-POINTED THESE AT REV 4.3, and the change is a rewrite rather than a
// rename. The rail used to render eleven INVENTED opponents from
// `data/league-data.js` in production; §4 called that a Launch Ready blocker
// and Play now discovers the server's own opponent list. Unbound — which is
// what a component suite is — there is nobody to discover, so the rail draws
// its intentional empty state and the eleven-card count is gone with the
// eleven invented cards. The heading also loses its `↕` (§12).
check('the Matchups rail heading carries no directional arrow',
  !league.includes('↕'), 'SWIPE ↕ removed');
check('unbound discovery draws an intentional state, never invented opponents',
  league.includes('data-versus-state')
  && (league.match(/fs-carousel__item/g) || []).length === 0);
// WP3C — the count moved into the heading's HELPER slot. At the §5.1 section
// step the whole string wrapped to two lines at 375px, and on Play that height
// came straight out of the card zone beneath it. The vocabulary is unchanged;
// what changed is which of `sectionHeading`'s two slots each half sits in.
// UIRECON WAVE 1 — the locked public term is FantasyStakes Prop Pools on first
// reference. The heading is the first reference on this tab.
check('Prop Pools heading is the locked wording',
  league.includes('FANTASYSTAKES PROP POOLS') && league.includes('4 THIS WEEK'));
check('Play uses the locked Matchups term and no public Versus',
  league.includes('FANTASYSTAKES MATCHUPS') && !league.includes('FANTASYSTAKES VERSUS'));
check('League presents four Prop Pools', (league.match(/data-pool="/g) || []).length === 4);
check('League carries the disclaimer once', countDisclaimers(league) === 1);
check('League keeps the four strip figures',
  ['+$126', '$55', '$10', '$65'].every((v) => league.includes(v)));

const action = buildActionPanel();
check('the Action header is the locked wording', ACTION_HEADER === 'WEEK 5 · REGULAR SEASON ACTION');
check('the Action header renders', action.includes('WEEK 5 · REGULAR SEASON ACTION'));
check('Action has exactly four rails', (action.match(/data-rail="/g) || []).length === 4);
check('Action carries the disclaimer once', countDisclaimers(action) === 1);
check('Action draws the four locked figures',
  ['14–7', '$129', '+$129', '+$20'].every((v) => action.includes(v)));
check('Action keeps exact cents behind its money',
  action.includes('data-exact-cents="12900"') && action.includes('data-exact-cents="2000"'));

/* ── Composer sheet ─────────────────────────────────────────────────────── */

section('The unified composer renders in the required order');

beginSession({ matchupId: 'destroyers', marketId: null, availableCents: 6500 });
const spec = composerSheet();
const body = spec.body;

check('the sheet names the challenge and opponent', /CULV Destroyers/.test(spec.title));

// WP3C — REV 4.3 §9 INVERTS THE FIRST TWO. The preview answers "why does this
// matchup look this way?" and the markets answer "what do I want to play?", so
// the POR puts the explanation above the choice. The assertion is unchanged in
// kind: it still pins the whole sequence, against the governing order.
const order = [
  ['VIEW MATCHUP PREVIEW', body.indexOf('VIEW MATCHUP PREVIEW')],
  ['market selector', body.indexOf('data-composer-market')],
  ['LOCKED | DYNAMIC', body.indexOf('data-composer-mode')],
  ['mode explanation', body.indexOf('fs-modenote')],
  ['YOUR STAKE', body.indexOf('YOUR STAKE')],
  ['economics', body.indexOf('data-econ')],
  ['send', body.indexOf('data-composer-send')],
];
check('every required section is present', order.every(([, i]) => i >= 0),
  order.filter(([, i]) => i < 0).map(([n]) => n).join(', ') || 'all present');
for (let i = 1; i < order.length; i += 1) {
  check(`${order[i][0]} follows ${order[i - 1][0]}`, order[i][1] > order[i - 1][1]);
}

check('the stake field opens at 0', /value="0"/.test(body));
check('send opens disabled', /data-composer-send\s+disabled/.test(body));
check('there is no intermediate market-selection sheet — the selector is in the composer',
  body.indexOf('data-composer-market') < body.indexOf('YOUR STAKE'));
check('the composer explains the selected mode', body.includes(MODE_COPY[MODE_LOCKED].headline));

beginSession({ matchupId: 'destroyers', marketId: 'ou', availableCents: 6500 });
check('a market tap preselects that market in the same composer',
  /data-composer-market="ou"[^>]*aria-pressed="true"/.test(composerSheet().body));
check('the session is the composer\'s own state', currentSession().state.marketId === 'ou');
check('the stake is still $0 after a market tap', currentSession().state.stakeCents === 0);

const dynSpec = (() => {
  beginSession({ matchupId: 'destroyers', marketId: 'ml', availableCents: 6500 });
  const s = currentSession();
  s.state = selectMode(s.state, MODE_DYNAMIC);
  return composerSheet();
})();
check('choosing Dynamic swaps the explanation',
  dynSpec.body.includes(MODE_COPY[MODE_DYNAMIC].headline));
// THE CLAIM IS THAT THE BODY REACHES THE SHEET, not that one phrase does — and
// pinning a phrase from the timing clause tied this check to wording S8-P4C-2R2
// corrected. Asserting the body itself keeps the check true through any future
// authorised copy change while still failing if the explanation goes missing.
check('the Dynamic explanation reaches the rendered composer',
  dynSpec.body.includes(MODE_COPY[MODE_DYNAMIC].body),
  MODE_COPY[MODE_DYNAMIC].body.slice(0, 60));

section('The Matchup Preview holds the four required sections');

const preview = previewSheet(matchup('destroyers'));
// WP3C — REV 4.3 §10 REBUILT THIS SURFACE, and two of the old assertions are
// now assertions of the opposite thing.
//
// SPORTSBOOK VIEW IS GONE. It restated the moneyline, the spread and the total
// inside the surface meant to EXPLAIN them, which made the preview read as a
// second place to bet. §10 removes the market block outright, so the check that
// it is present becomes a check that it is absent.
//
// THE ORDER IS INVERTED. Analysis now comes before the dense lineup table —
// §10's "analysis must appear before dense lineup content" — where Rev 4.2 put
// Sportsbook View and the lineups first and the analysis last.
// UIRECON WAVE 4A — THE MATCHUP IS NAMED ONCE.
//
// A `MATCHUP` block listing both team names sat under a sheet subtitle
// that had just given both team names — the same two facts twice inside
// about sixty pixels, and in the bound state the second copy carried two
// blank values. The slot now carries what the subtitle does not: the
// market on offer (`ON OFFER`) for a live pairing, or the final score
// (`RESULT`) for a settled one. An UNBOUND preview has neither, so it
// renders no second block at all — which is what these fixtures are.
for (const heading of ['WHY THE LINE LOOKS THIS WAY', 'THE READ',
  'LINEUPS']) {
  check(`the preview carries ${heading}`, preview.body.includes(heading));
}
check('the unbound preview lists no second copy of the two teams',
  !preview.body.includes('fs-prev__title">MATCHUP<'));
check('the preview carries NO odds-market block (§10)',
  !preview.body.includes('SPORTSBOOK VIEW')
  && !/data-market/.test(preview.body));
check('the explanation is the first thing in the sheet body',
  preview.body.indexOf('WHY THE LINE') >= 0
  && !/fs-prev__title">(?!WHY THE LINE)/.test(preview.body.slice(0, 200)));
check('Why The Line precedes The Read',
  preview.body.indexOf('WHY THE LINE') < preview.body.indexOf('THE READ'));
check('and BOTH analysis sections precede the lineups',
  preview.body.indexOf('THE READ') < preview.body.indexOf('LINEUPS'));
check('an unbound preview has no static identity block to draw',
  !/fs-prev__head is-static/.test(preview.body));
check('the analysis sections are open by default; the lineups are not',
  /is-open[^]*WHY THE LINE/.test(preview.body)
  && preview.body.includes('aria-expanded="false"'));
check('the preview says nothing is lost on close',
  /nothing you have entered is lost/i.test(preview.body));

endSession();

/* ── Result ─────────────────────────────────────────────────────────────── */

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`FAILED: ${failures.length} assertion(s)`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
} else {
  console.log('All assertions PASSED');
}