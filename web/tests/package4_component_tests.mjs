/* ============================================================================
 * FantasyStakes — Sprint 7 Package 4 · behavioural tests
 *
 * Run directly:   node web/tests/package4_component_tests.mjs
 * Or through:     python test_s7_p4_rules_commissioner.py
 *
 * Drives the shipped modules. The assertions that matter most are the ones that
 * keep the commissioner's arithmetic identical to the GM's, and the ones that
 * check the rules sheets against the ruling and configuration they quote.
 * ========================================================================== */

import { countDisclaimers } from '../js/components.js';

import {
  ECONOMY_STOP,
  CHAMPIONSHIP_SPLIT,
  LEGAL_LINE,
  POOL_ENTRY,
  RULE_GROUPS,
  SETTINGS,
  SETTINGS_SEAM,
  SKUNK,
} from '../js/data/rules-data.js';

import {
  RULES_TITLE,
  buildRulesPanel,
  ruleSheet,
  settingSheet,
} from '../js/rules.js';

import {
  COMMISSIONER_SECTIONS,
  GM_CARDS_HEADING,
  RECONCILIATION_HEADING,
  TOPOFF_HEADING,
  gmSheet,
  requestSheet,
} from '../js/commissioner.js';

import {
  COMMISSIONER_AUTH_SEAM,
  LEAGUE_POSITIONS_SEAM,
  TOPOFF_ROUTES,
  TRIAL_BALANCE_SEAM,
  gmPositions,
  hasProvenance,
  leagueReconciliation,
  openRequests,
  topOffState,
} from '../js/commissioner-model.js';

import { LEAGUE_SIZE, TOPOFF_REQUESTS, TOPOFF_STATES } from '../js/data/commissioner-data.js';
import { MODE_COPY, MODE_DYNAMIC, MODE_LOCKED, MIN_STAKE_CENTS } from '../js/wager-model.js';
import { reconciliation } from '../js/ledger-model.js';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

function section(title) {
  console.log(`\n${title}`);
}

const panel = buildRulesPanel();

/* ── Tab frame ──────────────────────────────────────────────────────────── */

section('Rules & Settings carries no strip and no disclaimer');

// Escaped in the markup, because the title contains an ampersand.
check('the title is the locked wording',
  panel.includes(RULES_TITLE.replace('&', '&amp;')), RULES_TITLE);
check('the league identity is present', panel.includes('CULV APPRECIATION SOCIETY'));
check('no four-cell strip', !panel.includes('class="fs-strip"'));
check('no Credits disclaimer', countDisclaimers(panel) === 0, String(countDisclaimers(panel)));

/* ── A · Rules ──────────────────────────────────────────────────────────── */

section('The five rule groups, in the locked order');

const LOCKED_ORDER = ['The Money', 'Weekly Grind', 'Big Money', 'The Bets', 'The Fine Print'];

check('exactly five top-level groups', RULE_GROUPS.length === 5, String(RULE_GROUPS.length));
check('the order is the locked order',
  RULE_GROUPS.map((g) => g.title).join(' / ') === LOCKED_ORDER.join(' / '),
  RULE_GROUPS.map((g) => g.title).join(' / '));
check('every group renders as a tappable row',
  RULE_GROUPS.every((g) => panel.includes(`data-rule="${g.id}"`)));
check('every row carries a disclosure affordance',
  (panel.match(/fs-rulerow__chev/g) || []).length === 5);
check('the rows appear in the locked order in the markup',
  RULE_GROUPS.every((g, i) => (i === 0
    ? true
    : panel.indexOf(`data-rule="${g.id}"`) > panel.indexOf(`data-rule="${RULE_GROUPS[i - 1].id}"`))));
check('every group holds at least one rule',
  RULE_GROUPS.every((g) => g.rules.length > 0));
check('every rule names its governing source',
  RULE_GROUPS.every((g) => g.rules.every((r) => r.source && r.source.length > 3)));

section('Rule copy does not contradict the governing specifications');

const allRuleText = RULE_GROUPS
  .flatMap((g) => g.rules.map((r) => `${r.heading} ${r.body}`))
  .join(' ');

check('the season advance is the governed $220',
  /\$220/.test(allRuleText) && ECONOMY_STOP.buyinCents === 22000);
check('the regular-season minimum reserve is the governed $140',
  /\$140/.test(allRuleText) && ECONOMY_STOP.minReserveCents === 14000);
check('the championship reserve is the governed $80',
  /\$80/.test(allRuleText) && ECONOMY_STOP.reserveCents === 8000);
check('the economy stop invariants hold',
  ECONOMY_STOP.minReserveCents + ECONOMY_STOP.reserveCents === ECONOMY_STOP.buyinCents
  && ECONOMY_STOP.minReserveCents === ECONOMY_STOP.weeklyMinCents * 14
  && ECONOMY_STOP.reserveCents * 11 === ECONOMY_STOP.buyinCents * 4);
check('the Skunk is the governed $10 weekly and $140 season maximum',
  SKUNK.weeklyCents === 1000 && SKUNK.seasonMaximumCents === 14000);
check('the minimum stake quoted is the engine minimum',
  allRuleText.includes('$5') && MIN_STAKE_CENTS === 500);
check('Current Settle is described as derived, never stored',
  /derived/i.test(allRuleText) && /never stored|no Current Settle column/i.test(allRuleText));

section('Locked and Dynamic descriptions remain the ruling’s own');

const bets = RULE_GROUPS.find((g) => g.id === 'bets');
const lockedRule = bets.rules.find((r) => r.heading.startsWith(MODE_COPY[MODE_LOCKED].label));
const dynamicRule = bets.rules.find((r) => r.heading.startsWith(MODE_COPY[MODE_DYNAMIC].label));

check('the Locked rule quotes the shared mode copy',
  lockedRule.body === MODE_COPY[MODE_LOCKED].body);
check('the Dynamic rule quotes the shared mode copy',
  dynamicRule.body === MODE_COPY[MODE_DYNAMIC].body);
check('the Dynamic rule keeps the one-way ceiling',
  /never up, never past the max set now/.test(dynamicRule.body));
check('the Locked rule says terms freeze on send, not on acceptance',
  /freeze the moment you send/.test(lockedRule.heading + lockedRule.body));
check('the retired "flex up or down" draft never appears', !/flex up/i.test(allRuleText));
check('one counter only is stated',
  /one counter/i.test(allRuleText) && /no\s*\n?\s*re-counter|there is no ' \+\n?\s*'re-counter|no re-counter/i.test(allRuleText.replace(/\s+/g, ' ')));

section('Betting vocabulary is intact and no payment path is reintroduced');

const rendered = panel + RULE_GROUPS.map((g) => ruleSheet(g).body).join('');

// The POLICY copy — headings and bodies. Source citations are provenance, not
// rules, and one of them legitimately names the addendum that REMOVED Stripe;
// a scan that tripped on that would be punishing the record of the removal.
const policyCopy = rendered.replace(/<div class="fs-rule__src">[^<]*<\/div>/g, ' ');

for (const term of ['wager', 'bets', 'stake', 'pot', 'ML', 'Spread', 'O/U', 'Locked', 'Dynamic']) {
  check(`the vocabulary keeps "${term}"`,
    new RegExp(`\\b${term.replace('/', '\\/')}\\b`, 'i').test(policyCopy), term);
}

// Payment PROCESSING, not the words for it: the copy is free to say Credits
// cannot be deposited or withdrawn, and does. What may not appear is a
// processor, an instrument, or a funding affordance.
for (const banned of ['Stripe', 'PayPal', 'Apple Pay', 'credit card', 'debit card',
  'payment method', 'billing', 'checkout', 'routing number', 'add funds']) {
  check(`no "${banned}" language`, !new RegExp(banned, 'i').test(policyCopy), banned);
}
check('Credits are stated to carry no cash value', /no cash value/i.test(policyCopy));
check('the copy denies any funding path outright',
  /cannot be deposited, withdrawn or redeemed/i.test(policyCopy));
check('and says no funding path is planned',
  /no funding path into this league and none is planned/i.test(policyCopy));

section('A rule group opens through the shared sheet');

const moneySheet = ruleSheet(RULE_GROUPS[0]);
check('the sheet is titled with the group', moneySheet.title === 'The Money');
check('the sheet renders every rule in the group',
  (moneySheet.body.match(/class="fs-rule__head"/g) || []).length === RULE_GROUPS[0].rules.length);
check('the sheet shows each rule’s source',
  (moneySheet.body.match(/class="fs-rule__src"/g) || []).length === RULE_GROUPS[0].rules.length);
check('the sheet defers to the specifications',
  /the specification is right/.test(moneySheet.body));

/* ── B · Settings ───────────────────────────────────────────────────────── */

section('The four locked settings rows');

const LOCKED_SETTINGS = ['Economy Stop', 'Standard Pool Bet', 'Skunk Fee', 'Championship split'];
check('exactly four settings', SETTINGS.length === 4, String(SETTINGS.length));
check('the labels are the locked labels',
  SETTINGS.map((s) => s.label).join(' / ') === LOCKED_SETTINGS.join(' / '),
  SETTINGS.map((s) => s.label).join(' / '));
for (const label of LOCKED_SETTINGS) {
  check(`${label} renders`, panel.includes(`>${label}</span>`), label);
}

check('Economy Stop shows the governed stop',
  SETTINGS[0].value === '$10 / week · $220 season', SETTINGS[0].value);
check('Standard Pool Bet shows the governed entry',
  SETTINGS[1].value === '$1' && POOL_ENTRY.cents === 100, SETTINGS[1].value);
check('the Pool entry sits inside its governed bounds',
  POOL_ENTRY.cents >= POOL_ENTRY.minCents && POOL_ENTRY.cents <= POOL_ENTRY.maxCents);
check('Skunk Fee shows the governed figures',
  SETTINGS[2].value === '$10 weekly · $140 max', SETTINGS[2].value);
check('Championship split shows the governed split',
  SETTINGS[3].value === '60 / 30 / 10'
  && CHAMPIONSHIP_SPLIT.split.reduce((a, b) => a + b, 0) === 100,
  SETTINGS[3].value);
check('every setting names its governing source',
  SETTINGS.every((s) => s.source && s.source.length > 3));

section('No mutation path is fabricated for a row that looks editable');

check('the settings seam records that no command exists',
  SETTINGS_SEAM.endpoint === null && SETTINGS_SEAM.status === 'NO CONFIGURATION COMMAND API');
check('the surface states the rows are read-only', panel.includes('read-only'));
check('the surface explains why', /no governed configuration command exists to call/.test(panel));
check('a setting sheet repeats the constraint',
  /Read-only\./.test(settingSheet(SETTINGS[0]).body));
check('no setting renders an input, a toggle or a save control',
  !/<input|<select|type="checkbox"|data-save|Save<\/button>/.test(panel));

/* ── C · Commissioner ───────────────────────────────────────────────────── */

section('The commissioner sections are in the locked order');

check('the area is present', panel.includes('id="fs-commissioner"'));
check('all three sections render',
  COMMISSIONER_SECTIONS.every((id) => panel.includes(`data-commissioner="${id}"`)));
check('Top-Off Requests comes first',
  panel.indexOf('data-commissioner="topoffs"') < panel.indexOf('data-commissioner="gm-cards"'));
check('GM Ledger Cards comes SECOND — before League Reconciliation',
  panel.indexOf('data-commissioner="gm-cards"') < panel.indexOf('data-commissioner="reconciliation"'));
check('the headings are the locked headings',
  panel.includes(TOPOFF_HEADING) && panel.includes(GM_CARDS_HEADING)
  && panel.includes(RECONCILIATION_HEADING));
check('the GM card heading names the league size',
  GM_CARDS_HEADING === 'B · GM LEDGER CARDS · 12 · TAP TO EXPAND', GM_CARDS_HEADING);

section('A · Top-Off requests model the real protocol states');

check('the four presentation states are declared', TOPOFF_STATES.length === 4);
check('an approved request persists status "applied", not "approved"',
  TOPOFF_STATES.find((s) => s.id === 'approved').status === 'applied');
check('every illustrative request maps to a presentation state',
  TOPOFF_REQUESTS.every((r) => Boolean(topOffState(r))));
check('all four states are exercised',
  new Set(TOPOFF_REQUESTS.map((r) => topOffState(r).id)).size === 4);
check('requests carry the persisted field names',
  TOPOFF_REQUESTS.every((r) => 'amount_cents' in r && 'requester_user_id' in r
    && 'decided_by_user_id' in r && 'ledger_posting_id' in r && 'disclosure_event_id' in r));
check('remaining_capacity_cents is absent, as the read route leaves it',
  TOPOFF_REQUESTS.every((r) => !('remaining_capacity_cents' in r)));

check('only an approved request carries the provenance chain',
  TOPOFF_REQUESTS.every((r) => (topOffState(r).id === 'approved'
    ? hasProvenance(r)
    : !r.ledger_posting_id && !r.disclosure_event_id)));
check('a self-approval carries its required reason',
  TOPOFF_REQUESTS.filter((r) => r.self_approved).every((r) => Boolean(r.decision_reason)));
check('open requests are the pending ones',
  openRequests().every((r) => r.decision === 'pending' && r.status === 'pending'));

section('No decision is transmitted, and the seam says why');

const pending = openRequests()[0];
const pendingSheet = requestSheet(pending);
const decidedSheet = requestSheet(TOPOFF_REQUESTS.find((r) => topOffState(r).id === 'approved'));

check('a pending request offers the three decision controls',
  ['approve', 'reject', 'cancel'].every((d) => pendingSheet.body.includes(`data-decide="${d}"`)));
check('every decision control is disabled',
  (pendingSheet.body.match(/data-decide="[a-z]+" disabled/g) || []).length === 3);
check('the sheet states that nothing is transmitted',
  /no decision is\s*\n?\s*transmitted|Demonstration only/.test(pendingSheet.body));
check('the sheet names the governed commands',
  pendingSheet.body.includes(TOPOFF_ROUTES.approve)
  && pendingSheet.body.includes(TOPOFF_ROUTES.reject)
  && pendingSheet.body.includes(TOPOFF_ROUTES.cancel));
check('the sheet disclaims issuance of its own',
  /implements\s*\n?\s*no issuance of its own/.test(pendingSheet.body));
check('a decided request offers no controls',
  !decidedSheet.body.includes('data-decide'));
check('a decided approval shows its provenance',
  /ledger_posting_id/.test(decidedSheet.body) && /disclosure_event_id/.test(decidedSheet.body));
check('the sheet shows the persisted decision and status, not just a label',
  /decision/.test(decidedSheet.body) && /applied/.test(decidedSheet.body));
check('the auth seam records the missing session, not a missing authority model',
  COMMISSIONER_AUTH_SEAM.uiState === 'illustrative — no decision is transmitted'
  && /is_league_commissioner/.test(COMMISSIONER_AUTH_SEAM.serverAuthority));

section('B · Twelve GM ledger cards, on the GM’s own arithmetic');

const positions = gmPositions();
check('twelve GM cards', positions.length === LEAGUE_SIZE, String(positions.length));
check('all twelve render', (panel.match(/data-gm="/g) || []).length === 12);
check('every card carries Available, In Play and Held',
  panel.includes('>Available<') && panel.includes('>In Play<') && panel.includes('>Held<'));
check('every card carries its exact cents',
  positions.every((p) => panel.includes(`data-exact-cents="${p.currentSettleCents}"`)));
check('no figure is drawn with cents', !/\$\d+\.\d\d/.test(panel));

// The one assertion that matters most: the commissioner's view of a GM and
// that GM's own Ledger tab must be the same number, from the same arithmetic.
const you = positions.find((p) => p.teamId === 'you');
const gmLedger = reconciliation();
check('the viewer’s commissioner card equals their own Ledger figure',
  you.currentSettleCents === gmLedger.currentSettleCents,
  `${you.currentSettleCents} vs ${gmLedger.currentSettleCents}`);
check('and its component terms match too',
  you.wageringPositionCents === gmLedger.position.wageringPositionCents
  && you.netAdjustmentsCents === gmLedger.adjustments.netAdjustmentsCents
  && you.totalVirtualStakesCents === gmLedger.advances.totalVirtualStakesCents);
check('every GM’s figure follows the same formula',
  positions.every((p) => p.currentSettleCents
    === p.wageringPositionCents + p.netAdjustmentsCents - p.totalVirtualStakesCents));
check('every GM is on the league’s single economy stop',
  positions.every((p) => p.seasonOpeningCents === ECONOMY_STOP.buyinCents));

const detail = gmSheet(you);
check('the expansion names the GM whose position it is',
  detail.title === you.name && /this GM’s position/.test(detail.sub));
check('the expansion uses the Ledger row grammar',
  (detail.body.match(/class="fs-lrow/g) || []).length >= 8);
check('the expansion shows the three section totals',
  detail.body.includes(`data-exact-cents="${you.wageringPositionCents}"`)
  && detail.body.includes(`data-exact-cents="${you.netAdjustmentsCents}"`)
  && detail.body.includes(`data-exact-cents="${you.totalVirtualStakesCents}"`));
check('the expansion states the shared arithmetic',
  /the same arithmetic this GM’s own Ledger performs/.test(detail.body));
check('a held balance is explained as excluded from settlement',
  /not counted again in\s*\n?\s*Current Settle/.test(gmSheet(you).body));
check('the league positions seam is declared',
  LEAGUE_POSITIONS_SEAM.endpoint === null);
check('the surface says the league state is illustrative',
  /Illustrative league state/.test(panel));

section('C · League reconciliation aggregates, and invents nothing');

const league = leagueReconciliation();
check('it covers all twelve GMs', league.teams === 12, String(league.teams));
check('the parts and the whole agree',
  league.sumOfGmSettlesCents === league.aggregateSettleCents,
  `${league.sumOfGmSettlesCents} vs ${league.aggregateSettleCents}`);
check('the league closes', league.closes === true);
check('the aggregate follows the same formula as a GM',
  league.aggregateSettleCents
    === league.wageringPositionCents + league.netAdjustmentsCents - league.totalVirtualStakesCents);
check('total stakes are the twelve advances',
  league.totalVirtualStakesCents === positions.reduce((t, p) => t + p.totalVirtualStakesCents, 0));

check('pending offer holds are reported as NOT a settlement liability',
  league.exceptions.pendingOfferHolds.settlementLiability === false);
check('open top-off requests are reported as NOT a settlement liability',
  league.exceptions.openTopOffs.settlementLiability === false);
check('neither exception is added into the league figure',
  league.aggregateSettleCents
    !== league.aggregateSettleCents
      - league.exceptions.pendingOfferHolds.cents
      - league.exceptions.openTopOffs.cents);
check('open top-offs count the pending requests',
  league.exceptions.openTopOffs.count === openRequests().length);
check('skunk receivables are already inside the GM adjustments',
  league.exceptions.skunkReceivables.settlementLiability === true);

check('the integrity invariant is stated but not claimed as checked',
  league.integrity.verified === false && /trial balance is zero/i.test(league.integrity.invariant));
check('the trial-balance seam names the computation',
  TRIAL_BALANCE_SEAM.computation.includes('trial_balance()')
  && TRIAL_BALANCE_SEAM.endpoint === null);
check('the surface reports the invariant as not verified here',
  panel.includes('NOT VERIFIED HERE'));
check('the reconciliation is not a second Current Settle formula',
  /the same arithmetic|Wagering Position \+ Net Adjustments/.test(gmSheet(you).body));

/* ── D · Legal ──────────────────────────────────────────────────────────── */

section('The legal line sits at the bottom, once');

check('the footer text is exact',
  LEGAL_LINE === '© 2026 Fraser D. Coleman. All Rights Reserved. FantasyStakes™.',
  LEGAL_LINE);
check('it renders on this tab', panel.includes('id="fs-legal"'));
check('it appears exactly once',
  (panel.match(/id="fs-legal"/g) || []).length === 1
  && (panel.split(LEGAL_LINE.slice(0, 20)).length - 1) === 1);
check('it is the last thing on the tab',
  panel.lastIndexOf('fs-legal') > panel.lastIndexOf('fs-commissioner'));

/* ── Result ─────────────────────────────────────────────────────────────── */

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`FAILED: ${failures.length} assertion(s)`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
} else {
  console.log('All assertions PASSED');
}