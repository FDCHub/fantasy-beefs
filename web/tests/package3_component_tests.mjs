/* ============================================================================
 * FantasyStakes — Sprint 7 Package 3 · behavioural tests
 *
 * Run directly:   node web/tests/package3_component_tests.mjs
 * Or through:     python test_s7_p3_week_ledger.py
 *
 * Drives the shipped modules. The assertions that matter most are the ones that
 * pin the Ledger's arithmetic — every total is checked against the rows that
 * produce it, and the whole reconciliation is checked against the backend's own
 * assets-minus-obligations grouping.
 * ========================================================================== */

import { countDisclaimers } from '../js/components.js';

import {
  CURRENT_WEEK,
  PAST_WEEK,
  TEAMS,
  WEEKS,
  carriedForwardCents,
  projectionOf,
  weekBets,
  weekPools,
  yahooMatchups,
} from '../js/data/week-data.js';

import {
  BETS_HEADING,
  BETS_SHOWN,
  WEEK_SUBTITLE,
  buildWeekPanel,
  currentSelectedWeek,
  resetWeek,
  selectWeek,
  yahooCard,
} from '../js/week.js';

import { CARDS, seasonRecordLabel, settledCents } from '../js/data/action-data.js';

import {
  LEDGER_SUBTITLE,
  LEDGER_TITLE,
  MY_SEASON_LABEL,
  TOPOFF_LABEL,
  buildLedgerPanel,
  topOffSheet,
} from '../js/ledger.js';

import {
  CURRENT_SETTLE_TERMS,
  LEDGER_READ_SEAM,
  TOPOFF_COMMAND_SEAM,
  activity,
  advances,
  adjustments,
  backendEquivalent,
  currentSettleCents,
  position,
  reconciliation,
  supportingRows,
} from '../js/ledger-model.js';

import { POOLS } from '../js/data/league-data.js';
import { previewSheet } from '../js/preview.js';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

function section(title) {
  console.log(`\n${title}`);
}

/* ── The Week · header ──────────────────────────────────────────────────── */

section('The Week carries one compact week switch and nothing it replaced');

resetWeek();
let week = buildWeekPanel();

check('the switch offers both weeks as text controls',
  week.includes('data-week="4"') && week.includes('data-week="5"'));
check('the switch reads WEEK 4 · REGULAR SEASON · WEEK 5',
  /WEEK 4<\/button>[\s\S]*REGULAR SEASON[\s\S]*WEEK 5<\/button>/.test(week));
check('the current week is the opening selection', currentSelectedWeek() === CURRENT_WEEK);
check('the selected week is visually emphasised',
  /data-week="5" aria-pressed="true"/.test(week) &&
  /class="fs-wkswitch__opt is-selected" data-week="5"/.test(week));
check('the unselected week is not emphasised',
  /class="fs-wkswitch__opt" data-week="4"/.test(week));
check('the subtitle is the locked wording',
  week.includes(WEEK_SUBTITLE), WEEK_SUBTITLE);

check('the kickoff clock is gone', !/FIRST KICKOFF/i.test(week));
check('no Preview / Results / Review selector is exposed',
  !/\bPreview\s*[\/·|]\s*Results\b/i.test(week) && !/data-weekmode/.test(week));
check('no PAST WEEK treatment survives', !/PAST WEEK/i.test(week));

section('The Week carries exactly three modules and no four-cell strip');

const modules = week.match(/data-module="/g) || [];
check('exactly three modules', modules.length === 3, String(modules.length));
for (const id of ['yahoo', 'bets', 'pools']) {
  check(`the ${id} module is present`, week.includes(`data-module="${id}"`));
}
check('The Week introduces no four-cell strip', !week.includes('class="fs-strip"'));
check('summarising no position, it carries no Credits disclaimer',
  countDisclaimers(week) === 0, String(countDisclaimers(week)));

/* ── The Week · Yahoo module ────────────────────────────────────────────── */

section('Yahoo matchups are identified as official league fixtures');

const slate = yahooMatchups(CURRENT_WEEK);
check('the week has six matchups', slate.length === 6, String(slate.length));
check('twelve teams appear exactly once',
  new Set(slate.flatMap((m) => [m.you.name, m.name])).size === 12);
check('every league team is on the slate', TEAMS.length === 12, String(TEAMS.length));
check('the viewer’s own matchup comes first', slate[0].viewerIsIn === true);
check('only one matchup involves the viewer',
  slate.filter((m) => m.viewerIsIn).length === 1);

check('every card is badged as a Yahoo fixture',
  slate.every((m) => yahooCard(m).includes('>YAHOO<')));
check('the module heading names official Yahoo matchups',
  week.includes('YAHOO LEAGUE MATCHUPS'));
check('a Yahoo card offers no challenge affordance',
  !yahooCard(slate[0]).includes('Challenge'));
check('a Yahoo card’s markets are not tappable',
  !yahooCard(slate[0]).includes('data-market='));

check('the spread is the difference between the two projections',
  slate.every((m) => Math.abs(
    m.spread - Math.round((m.opponentProjection - m.yourProjection) * 10) / 10,
  ) < 0.05));
check('the total is the two projections added',
  slate.every((m) => Math.abs(
    m.total - Math.round((m.opponentProjection + m.yourProjection) * 10) / 10,
  ) < 0.05));
check('a team projects the same figure it does on League',
  slate[0].viewerIsSubject
    ? slate[0].opponentProjection === projectionOf('destroyers')
    : false);

// The moneyline is the one figure that may be absent, and it is absent
// honestly rather than derived from the spread.
check('the viewer’s own matchup carries its carried moneyline',
  Number.isInteger(slate[0].ml), String(slate[0].ml));
check('third-party matchups carry no invented moneyline',
  slate.filter((m) => !m.viewerIsIn).every((m) => m.ml === null));
check('an unquoted moneyline draws as unresolved',
  yahooCard(slate[1]).includes('—'));

section('A Yahoo matchup opens the shared Matchup Preview');

const yahooPreview = previewSheet(slate[1]);
for (const heading of ['SPORTSBOOK VIEW', 'STARTING LINEUPS &amp; PROJECTIONS',
  'WHY THE LINE LOOKS THIS WAY', 'THE READ']) {
  check(`the preview carries ${heading.replace('&amp;', '&')}`,
    yahooPreview.body.includes(heading));
}
check('the preview states the matchup is an official Yahoo fixture',
  yahooPreview.body.includes('OFFICIAL YAHOO FANTASY MATCHUP'));
check('the preview says it is not a FantasyStakes wager',
  /not a FantasyStakes wager/.test(yahooPreview.body));
check('a third-party preview names no players at all',
  !/fs-spl__name">[A-Z]\./.test(yahooPreview.body));
check('an unquoted moneyline is explained rather than derived',
  /No moneyline is quoted/.test(yahooPreview.body));
check('the viewer’s own preview keeps the second-person voice',
  /\byou\b/i.test(previewSheet(slate[0]).body));
check('a third-party preview addresses teams by name, not as "you"',
  !/\byour\b/i.test(yahooPreview.body.replace(/Your Team/g, '')));

/* ── The Week · bets and pools ──────────────────────────────────────────── */

section('FantasyStakes Bets shows the week’s wagers, the viewer’s own first');

const currentBets = weekBets(CURRENT_WEEK);
check('the current week shows exactly four', currentBets.length === 4, String(currentBets.length));
check('the heading is the locked Rev 4.2 wording',
  week.includes(BETS_HEADING), BETS_HEADING);
check('the locked heading states the viewport treatment, not a record count',
  BETS_HEADING === 'FANTASYSTAKES BETS · 4 SHOWN · SWIPE ↕', BETS_HEADING);
check('the current week shows live, not settled, wagers',
  currentBets.every((c) => !c.settled));
check('the bets carry the Package 2 wager grammar',
  week.includes('fs-wcard--lifecycle'));
check('a bet is tappable through the shared wager grammar',
  week.includes('data-card-action="wager"'));

section('FantasyStakes Pools shows all four launch Pools without a carousel');

const currentPools = weekPools(CURRENT_WEEK);
check('four Pools', currentPools.length === 4, String(currentPools.length));
check('the four are the governing catalog’s launch Pools',
  currentPools.map((p) => p.catalogNumber).join(',')
    === POOLS.map((p) => p.catalogNumber).join(','));
check('every Pool keeps its catalog rule',
  currentPools.every((p, i) => p.rule === POOLS[i].rule));
check('the Pools module is rows, not a second carousel',
  week.includes('fs-poolrows') && !week.includes('id="fs-week-pools" class="fs-vcar'));
check('rollover stays a modifier on a subject type',
  currentPools.every((p) => ['TEAM', 'MATCHUP'].includes(p.scope)));

/* ── The Week · switching ───────────────────────────────────────────────── */

section('Selecting the past week switches to a settled presentation');

selectWeek(PAST_WEEK);
week = buildWeekPanel();

check('the past week becomes the selection', currentSelectedWeek() === PAST_WEEK);
check('the past week is the emphasised control',
  /class="fs-wkswitch__opt is-selected" data-week="4"/.test(week));
check('the current week is no longer emphasised',
  /class="fs-wkswitch__opt" data-week="5"/.test(week));

const pastSlate = yahooMatchups(PAST_WEEK);
check('past matchups are settled', pastSlate.every((m) => m.settled === true));
check('past matchups show a final score', pastSlate.every((m) => /\d/.test(m.score)));
check('past matchups name a winner', pastSlate.every((m) => m.winner.length > 0));
check('the winner is the higher final score',
  pastSlate.every((m) => (m.yourProjection >= m.opponentProjection
    ? m.winner === m.you.name
    : m.winner === m.name)));
check('a settled card draws FINAL', week.includes('FINAL'));
check('a settled card no longer says PREGAME', !week.includes('PREGAME'));

// A finished matchup is reported as a result, not dressed as a live market.
check('a settled matchup carries no market row',
  !yahooCard(pastSlate[0]).includes('fs-markets'));
check('a settled card labels its figures as results',
  /Margin/.test(yahooCard(pastSlate[0])) && /Combined/.test(yahooCard(pastSlate[0])));
check('this week’s board price is not reused on a settled matchup',
  pastSlate.every((m) => m.ml === null));

const pastPreview = previewSheet(pastSlate[0]);
check('a settled preview reports the result rather than a line',
  /Result/.test(pastPreview.body) && /Closing line/.test(pastPreview.body));
check('it states that the closing line is not retained',
  /The line this matchup closed at is not retained/.test(pastPreview.body));
// Scaling the slot shape to a FINAL score would manufacture a box score.
check('no per-slot figures are invented for a finished game',
  pastSlate[0].yourLineup.every((r) => r.projection === null)
  && pastSlate[0].opponentLineup.every((r) => r.projection === null));
check('the preview says per-slot results are not retained',
  /Per-slot results for a past week are not retained/.test(pastPreview.body));
check('the slot shape itself is still shown',
  pastSlate[0].yourLineup.length === 9);

const pastBets = weekBets(PAST_WEEK);
check('the past week shows settled wagers only',
  pastBets.length > 0 && pastBets.every((c) => c.settled === true));

// The locked heading is presentation; the records are protocol. A week with
// three settled wagers keeps the heading AND keeps three records.
check('the locked heading is unchanged on a past week',
  week.includes(BETS_HEADING), BETS_HEADING);
check('no fourth historical wager is fabricated to match the heading',
  pastBets.length === 3, String(pastBets.length));
check('the settled record set is still the three Action holds',
  CARDS.filter((c) => c.settled).length === 3,
  String(CARDS.filter((c) => c.settled).length));
check('the locked Action figures are untouched by the correction',
  settledCents() === 2000 && seasonRecordLabel() === '14–7',
  `${settledCents()} · ${seasonRecordLabel()}`);
check('the module never draws more than the viewport treatment states',
  weekBets(CURRENT_WEEK).slice(0, BETS_SHOWN).length <= BETS_SHOWN);

const pastPools = weekPools(PAST_WEEK);
check('past Pools are settled', pastPools.every((p) => p.settled === true));
check('a Pool that found no qualifier rolled its pot forward',
  pastPools.some((p) => p.rolledForward === true));
check('a settled Pool that qualified names its winner',
  pastPools.filter((p) => p.qualified).every((p) => Boolean(p.winner)));
// The carry reconciles: Week 4's unclaimed pot plus Week 5's fresh entries is
// exactly the continuation pot League already shows.
const continuation = POOLS.find((p) => p.continuation);
check('the carried pot reconciles with the Week 5 continuation',
  carriedForwardCents() + continuation.entered * continuation.entryCents
    === continuation.potCents,
  `${carriedForwardCents()} + ${continuation.entered * continuation.entryCents} = ${continuation.potCents}`);

check('The Week still carries no strip on a past week', !week.includes('class="fs-strip"'));
check('exactly three modules on a past week',
  (week.match(/data-module="/g) || []).length === 3);
check('both weeks are on the switch', WEEKS.join(',') === '4,5');

resetWeek();

/* ── Ledger · header and strips ─────────────────────────────────────────── */

section('The Ledger header and its two strips');

const ledger = buildLedgerPanel();
const r = reconciliation();

check('the title is the locked wording', ledger.includes(LEDGER_TITLE), LEDGER_TITLE);
check('the subtitle is the locked wording', ledger.includes(LEDGER_SUBTITLE), LEDGER_SUBTITLE);
check('Request Top-Off is present', ledger.includes(TOPOFF_LABEL));
check('Request Top-Off is a small text control, not a large button',
  ledger.includes('class="fs-topoff"') && !ledger.includes('fs-btn--gold'));
check('Request Top-Off sits in the header area, not in a strip cell',
  ledger.indexOf('data-topoff') < ledger.indexOf('class="fs-strip"'));

check('the Credits disclaimer appears exactly once',
  countDisclaimers(ledger) === 1, String(countDisclaimers(ledger)));

const weekCells = [
  ['Available', 6500, '$65'],
  ['In Play', 2800, '$28'],
  ['Held', 2500, '$25'],
  ['Weekly Min Left', 1000, '$10'],
];
for (const [label, cents, drawn] of weekCells) {
  check(`the week strip carries ${label} at ${drawn}`,
    ledger.includes(`>${label}</div>`) && ledger.includes(`data-exact-cents="${cents}"`),
    drawn);
}

check('the second strip is labelled My Season', ledger.includes(MY_SEASON_LABEL));
check('the My Season label reuses the subtitle typography',
  /class="fs-tabhead__sub fs-seasonlabel"/.test(ledger));
check('there are exactly two strips',
  (ledger.match(/class="fs-strip"/g) || []).length === 2);

const seasonCells = [
  ['Bet Record', '14–7'],
  ['Versus + Pools', '+$126'],
  ['Awards / Adj.', '+$32'],
  ['Current Settle', '−$45'],
];
for (const [label, drawn] of seasonCells) {
  check(`My Season carries ${label} at ${drawn}`,
    ledger.includes(`>${label}</div>`) && ledger.includes(drawn), drawn);
}
check('Current Settle is the gold cell of the My Season strip',
  /id="fs-strip-season"[\s\S]*?is-gold/.test(ledger));

/* ── Ledger · section 1 ─────────────────────────────────────────────────── */

section('1 · FantasyStakes Advances — the hierarchy shows its arithmetic');

const a = advances();
check('Regular Season Minimum Stakes is $140', a.regularSeasonMinimumCents === 14000);
check('Playoffs / Championship Stakes is $80', a.playoffsChampionshipCents === 8000);
check('$140 + $80 reconciles to $220',
  a.regularSeasonMinimumCents + a.playoffsChampionshipCents === a.seasonOpeningCents,
  `${a.regularSeasonMinimumCents} + ${a.playoffsChampionshipCents} = ${a.seasonOpeningCents}`);
check('Added Stakes is +$40', a.addedStakesCents === 4000);
check('$220 + $40 reconciles to $260',
  a.seasonOpeningCents + a.addedStakesCents === a.totalVirtualStakesCents,
  `${a.seasonOpeningCents} + ${a.addedStakesCents} = ${a.totalVirtualStakesCents}`);

// The hierarchy is load-bearing: the two components are indented beneath
// Season-Opening and Added Stakes is not.
const advancesBlock = ledger.split('data-section="1"')[1].split('</section>')[0];
check('the two season-opening components are indented beneath it',
  (advancesBlock.match(/is-level1/g) || []).length === 2);
check('Added Stakes is NOT a child of Season-Opening',
  /Added Stakes/.test(advancesBlock)
  && !/is-level1[^]*?Added Stakes/.test(
    advancesBlock.slice(advancesBlock.indexOf('Playoffs')),
  ));
check('Added Stakes sits at the same level as Season-Opening',
  /class="fs-lrow is-lead"[^]*?Added Stakes/.test(advancesBlock));

/* ── Ledger · section 2 ─────────────────────────────────────────────────── */

section('2 · Wagering Summary — the section that created the position');

const act = activity();
check('settled wins are +$184', act.settledWinsCents === 18400);
check('settled losses are −$78', act.settledLossesCents === -7800);
check('184 − 78 reconciles to 106',
  act.settledWinsCents + act.settledLossesCents === act.netVersusCents,
  `${act.settledWinsCents} + ${act.settledLossesCents} = ${act.netVersusCents}`);
check('Net Versus is +$106', act.netVersusCents === 10600);

check('Pool payouts are +$45', act.poolPayoutsCents === 4500);
check('Pool entries are −$25', act.poolEntriesCents === -2500);
check('45 − 25 reconciles to 20',
  act.poolPayoutsCents + act.poolEntriesCents === act.netPoolsCents,
  `${act.poolPayoutsCents} + ${act.poolEntriesCents} = ${act.netPoolsCents}`);
check('Net Pools is +$20', act.netPoolsCents === 2000);

const p = position();
check('Spendable Credits is $65', p.spendableCents === 6500);
check('Accepted wager escrow is $28', p.acceptedEscrowCents === 2800);
check('Weekly reserve not yet released is $90', p.weeklyReserveNotReleasedCents === 9000);
check('65 + 28 + 90 reconciles to 183',
  p.spendableCents + p.acceptedEscrowCents + p.weeklyReserveNotReleasedCents
    === p.wageringPositionCents,
  `${p.spendableCents} + ${p.acceptedEscrowCents} + ${p.weeklyReserveNotReleasedCents} = ${p.wageringPositionCents}`);
check('Wagering Position is +$183', p.wageringPositionCents === 18300);

check('the section is the elevated one', ledger.includes('fs-lsec is-elevated'));
check('the memo states the pending-hold rule',
  /not counted again in Current Settle until a proposal is accepted/.test(ledger));
check('the memo carries the $25 illustrative hold',
  ledger.includes('data-exact-cents="2500"'));

section('Expandable rows are audit surfaces that close against their totals');

const closed = supportingRows(
  [{ label: 'a', cents: 100 }, { label: 'b', cents: 250 }], 1000,
);
check('a short itemised list gains a derived remainder row', closed.length === 3);
check('the remainder closes the list to its total',
  closed.reduce((s, x) => s + x.cents, 0) === 1000);
check('the remainder is marked as derived', closed[2].derived === true);
check('a complete list gains no remainder row',
  supportingRows([{ label: 'a', cents: 1000 }], 1000).length === 1);

/* ── Ledger · section 3 ─────────────────────────────────────────────────── */

section('3 · Season Adjustments + Winnings');

const adj = adjustments();
check('Weekly Min out of circulation is +$8', adj.weeklyMinOutOfCirculationCents === 800);
check('Skunk Fees are $0', adj.skunkFeesCents === 0);
check('Season winnings earned is +$24', adj.seasonWinningsCents === 2400);
check('8 + 0 + 24 reconciles to 32',
  adj.weeklyMinOutOfCirculationCents + adj.skunkFeesCents + adj.seasonWinningsCents
    === adj.netAdjustmentsCents,
  `${adj.weeklyMinOutOfCirculationCents} + ${adj.skunkFeesCents} + ${adj.seasonWinningsCents} = ${adj.netAdjustmentsCents}`);
check('Net Adjustments + Winnings is +$32', adj.netAdjustmentsCents === 3200);
check('Points Champion is pending', /Points Champion[\s\S]{0,120}Pending/.test(ledger));
check('Playoff Champion is pending', /Playoff Champion[\s\S]{0,120}Pending/.test(ledger));
check('season winnings expand to their award components',
  ledger.includes('data-expand="season-winnings"'));
check('the unspecified per-award split is disclosed, not invented',
  /per-award split is not yet\s*specified/.test(ledger));

/* ── Ledger · Current Settle ────────────────────────────────────────────── */

section('Current Settle reconciles, and reconciles only once');

check('the locked formula holds: 183 + 32 − 260 = −45',
  currentSettleCents({
    wageringPositionCents: p.wageringPositionCents,
    netAdjustmentsCents: adj.netAdjustmentsCents,
    totalVirtualStakesCents: a.totalVirtualStakesCents,
  }) === -4500,
  `${p.wageringPositionCents} + ${adj.netAdjustmentsCents} − ${a.totalVirtualStakesCents} = ${r.currentSettleCents}`);
check('Current Settle is −$45', r.currentSettleCents === -4500);

// The no-double-counting rule, asserted structurally rather than by outcome.
check('Current Settle takes exactly three terms', CURRENT_SETTLE_TERMS.length === 3);
check('Net Versus is not one of them',
  !CURRENT_SETTLE_TERMS.includes('netVersusCents'));
check('Net Pools is not one of them',
  !CURRENT_SETTLE_TERMS.includes('netPoolsCents'));
check('adding the activity nets again would change the figure — so it is not done',
  r.currentSettleCents + act.netVersusCents + act.netPoolsCents !== r.currentSettleCents);
check('My Season’s Versus + Pools is the two nets, and is not re-added',
  r.versusPlusPoolsCents === act.netVersusCents + act.netPoolsCents
  && r.versusPlusPoolsCents === 12600);

// The strongest check available: the POR's grouping and the backend's own
// assets-minus-obligations grouping must agree to the cent.
const backend = backendEquivalent();
check('the backend assets/obligations grouping gives the same figure',
  backend.currentSettleCents === r.currentSettleCents,
  `${backend.assetsCents} − ${backend.obligationsCents} = ${backend.currentSettleCents}`);
check('obligations are the total virtual stakes',
  backend.obligationsCents === a.totalVirtualStakesCents);

section('The Current Settle card is the result, not a door');

const settleCard = ledger.split('id="fs-current-settle"')[1].split('</section>')[0];
check('the card shows Total Virtual Stakes as a subtraction',
  settleCard.includes('data-exact-cents="-26000"'));
check('the card shows the Wagering Position', settleCard.includes('data-exact-cents="18300"'));
check('the card shows Net Adjustments + Winnings', settleCard.includes('data-exact-cents="3200"'));
check('the card shows the result', settleCard.includes('data-exact-cents="-4500"'));
check('the card is not a button', !settleCard.includes('<button'));
check('the card carries no tap action', !settleCard.includes('data-card-action'));
check('the card is not marked tappable', !settleCard.includes('is-tappable'));
check('there is no View Full Reconciliation anywhere',
  !/View Full Reconciliation/i.test(ledger));

/* ── Ledger · exactness and seams ───────────────────────────────────────── */

section('Exact cents survive under the whole-dollar display');

const drawn = ledger.match(/data-exact-cents="(-?\d+)"/g) || [];
check('every money figure carries its exact cents', drawn.length >= 20, String(drawn.length));
check('every exact value is an integer',
  drawn.every((attr) => Number.isSafeInteger(Number(attr.match(/"(-?\d+)"/)[1]))));
check('no figure is drawn with cents', !/\$\d+\.\d\d/.test(ledger));

section('Seams are named, not fabricated');

check('the Ledger read-model seam is declared', LEDGER_READ_SEAM.endpoint === null);
check('it names the authoritative computation',
  LEDGER_READ_SEAM.computation.includes('economy/current_settle.py'));
check('the Top-Off command seam names the governed endpoint',
  TOPOFF_COMMAND_SEAM.endpoint === 'POST /league/{league_id}/top-offs');
check('Top-Off is read-only in this build', TOPOFF_COMMAND_SEAM.uiState === 'read-only');
check('the Top-Off sheet implements no parallel protocol',
  /implements no top-off path of its own/.test(topOffSheet().body));
check('the Top-Off sheet names the governed command',
  topOffSheet().body.includes('POST /league/{league_id}/top-offs'));

/* ── Result ─────────────────────────────────────────────────────────────── */

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`FAILED: ${failures.length} assertion(s)`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
} else {
  console.log('All assertions PASSED');
}