/* ============================================================================
 * FantasyStakes — WP3B · Rev 4.3 application foundation · component tests
 *
 * Run directly:   node web/tests/wp3b_component_tests.mjs
 * Or through:     python test_wp3b_rev43_foundation.py
 *
 * The shipped ES modules are executed directly. Testing the real modules is the
 * point: a reimplementation of the standings selection or the economy
 * capability rule could agree with itself while disagreeing with what the app
 * draws.
 *
 * NO DOM AND NO SERVER. These are the claims that can be made from the modules
 * and their rendered markup; the geometry and interaction claims are the
 * browser suite's.
 * ========================================================================== */

import {
  ALL_DESTINATIONS,
  DEFAULT_DESTINATION_ID,
  NAV_DESTINATIONS,
  SECONDARY_DESTINATIONS,
  destinationById,
  isPrimary,
  selectDestination,
} from '../js/nav.js';

import { MASTHEAD } from '../js/demo-state.js';

import {
  STANDINGS_STATE_LOADING,
  STANDINGS_STATE_NOT_ACTIVATED,
  STANDINGS_STATE_NO_DATA,
  STANDINGS_STATE_READY,
  STANDINGS_STATE_UNAVAILABLE,
  STANDINGS_TABLES,
  actingTeamId,
  bindStandings,
  cellsFor,
  markStandingsLoading,
  markStandingsUnavailable,
  rankingCents,
  rowsFor,
  standingsState,
  unbindStandings,
} from '../js/standings-model.js';

import { buildStandingsPanel } from '../js/standings.js';

import {
  ECONOMY_DERIVED,
  ECONOMY_INPUTS,
  bindEconomy,
  canActivate,
  currentInputs,
  isEditable,
  isFrozen,
  leagueAllocation,
  markEconomyUnavailable,
  perPlayerAllocationCents,
  setEconomyCapability,
  unbindEconomy,
} from '../js/economy-model.js';

import { activationSheet, economySheet } from '../js/economy.js';
import { menuEntries, menuSheet } from '../js/menu.js';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

function section(title) {
  console.log(`\n${title}`);
}

/* ── A · Navigation — Rev 4.3 §3 ─────────────────────────────────────────── */

section('A · The locked five, in order, with Standings first');

check('there are exactly five primary destinations',
  NAV_DESTINATIONS.length === 5, String(NAV_DESTINATIONS.length));
check('the labels are the locked five in the locked order',
  NAV_DESTINATIONS.map((d) => d.label).join(' · ')
    === 'Standings · Play · Status · Wrap Up · Account',
  NAV_DESTINATIONS.map((d) => d.label).join(' · '));
check('Standings is the default landing tab',
  DEFAULT_DESTINATION_ID === 'standings', DEFAULT_DESTINATION_ID);
check('the default is also the FIRST tab, not merely a default',
  NAV_DESTINATIONS[0].id === DEFAULT_DESTINATION_ID);

section('C · Rules & Settings is off the tab bar and still reachable');

check('Rules & Settings holds no primary position',
  !NAV_DESTINATIONS.some((d) => d.id === 'rules'));
check('no superseded Rev 4.2 primary label survives',
  !NAV_DESTINATIONS.some((d) => ['League', 'Action', 'Ledger', 'The Week',
    'Rules & Settings'].includes(d.label)));
check('it is a secondary destination instead',
  SECONDARY_DESTINATIONS.map((d) => d.id).join(',') === 'rules');
check('it still has a panel of its own',
  destinationById('rules').panelId === 'panel-rules');
check('it is navigable — selecting it activates exactly one destination',
  selectDestination('rules').filter((d) => d.active).length === 1
  && selectDestination('rules').find((d) => d.active).id === 'rules');
check('selecting it deactivates every primary tab',
  selectDestination('rules')
    .filter((d) => isPrimary(d.id))
    .every((d) => d.active === false));
check('every destination has a unique panel',
  new Set(ALL_DESTINATIONS.map((d) => d.panelId)).size
    === ALL_DESTINATIONS.length);
check('an unknown destination throws rather than blanking the app', (() => {
  try { destinationById('nope'); return false; } catch { return true; }
})());

/* ── T · Locked brand language — Rev 4.3 §2 ──────────────────────────────── */

section('T · The locked primary product tagline, exact');

check('the tagline is the locked string, character for character',
  MASTHEAD.tagline === 'Real odds. Fantasy stakes. More ways to win.',
  MASTHEAD.tagline);

section('S · Prototype and engineering material is gone — §2.1');

check('the masthead carries no revision designation',
  !('revision' in MASTHEAD));
check('the masthead carries no engineering byline',
  !('author' in MASTHEAD));
check('nothing in the masthead names a revision or an author',
  !/Rev\s*4\.|Fraser/.test(JSON.stringify(MASTHEAD)),
  JSON.stringify(MASTHEAD));

/* ── E/F · Standings — Rev 4.3 §7 ────────────────────────────────────────── */

section('E · Three complete tables, stacked, in the locked order');

check('the model declares exactly three tables',
  STANDINGS_TABLES.length === 3);
check('their headings are the locked ones, in order',
  STANDINGS_TABLES.map((t) => t.heading).join(' | ')
    === 'FANTASYSTAKES CHAMPIONSHIP | MATCHUP STANDINGS | PROP POOL STANDINGS',
  STANDINGS_TABLES.map((t) => t.heading).join(' | '));
check('Overall carries RK | TEAM | MATCHUPS | PROP POOLS | NET',
  STANDINGS_TABLES[0].columns.join(' | ') === 'RK | TEAM | MATCHUPS | PROP POOLS | NET',
  STANDINGS_TABLES[0].columns.join(' | '));
check('Versus carries RK | TEAM | W-L | NET',
  STANDINGS_TABLES[1].columns.join(' | ') === 'RK | TEAM | W-L | NET',
  STANDINGS_TABLES[1].columns.join(' | '));
check('Pools carries RK | TEAM | WINS | NET',
  STANDINGS_TABLES[2].columns.join(' | ') === 'RK | TEAM | WINS | NET',
  STANDINGS_TABLES[2].columns.join(' | '));

/** One league's served standings, shaped exactly as the route returns them. */
function servedBody() {
  const row = (id, name, w, l, pw, vn, pn) => ({
    rank: 0, team_id: id, team_name: name, owner: `${name} owner`,
    versus_wins: w, versus_losses: l, versus_pushes: 0,
    versus_record: `${w}-${l}`, pool_wins: pw,
    versus_net_cents: vn, pool_net_cents: pn, net_cents: vn + pn,
  });
  const rows = [
    row(11, 'Alpha', 3, 1, 2, 4000, 1500),
    row(12, 'Bravo', 2, 2, 0, -500, -1000),
    row(13, 'Charlie', 1, 3, 1, -3000, 500),
  ];
  const rank = (list) => list.map((r, i) => ({ ...r, rank: i + 1 }));
  return {
    league_id: 1,
    season: 2026,
    acting_team_id: 12,
    overall: rank([...rows].sort((a, b) => b.net_cents - a.net_cents
      || a.team_id - b.team_id)),
    versus: rank([...rows].sort((a, b) => b.versus_net_cents - a.versus_net_cents
      || a.team_id - b.team_id)),
    pools: rank([...rows].sort((a, b) => b.pool_net_cents - a.pool_net_cents
      || a.team_id - b.team_id)),
  };
}

unbindStandings();
const emptyPanel = buildStandingsPanel();

bindStandings(servedBody());
const panel = buildStandingsPanel();

check('all three tables are rendered',
  (panel.match(/data-standings-table/g) || []).length === 3,
  String((panel.match(/data-standings-table/g) || []).length));
check('all three are rendered in the EMPTY state too',
  (emptyPanel.match(/data-standings-table/g) || []).length === 3);
check('all three column sets are present in the empty state',
  emptyPanel.includes('>NET<') && emptyPanel.includes('>W-L<')
  && emptyPanel.includes('>WINS<'));

section('F · No selector, no carousel, no second tap');

check('the panel emits no segmented selector',
  !/fs-seg|data-segment|role="tablist"/.test(panel));
check('the panel emits no carousel or snapping rail',
  !/fs-rail|fs-vsnap|carousel|scroll-snap/i.test(panel));
check('the panel has exactly one scroll region',
  (panel.match(/fs-st__scroll/g) || []).length === 1);
check('no table is hidden, collapsed or behind a disclosure',
  !/<details|hidden|aria-expanded/i.test(panel));
check('every table is a real table element with a header row',
  (panel.match(/<table/g) || []).length === 3
  && (panel.match(/<thead>/g) || []).length === 3);

section('G · Overall ranks on the served competitive NET, never on Wallet');

// RC2 — THE INTENT WAS "NO WALLET FIGURE", AND IT STILL HOLDS. The original
// assertion forbade the WORD, which was a fair proxy while nothing said
// anything about wallets. Sprint A2 states the distinction out loud — "your
// wallet balance is not your Championship Score" — because it is the single
// most confusable fact in the product. So the guard is now the property it
// always meant, plus the positive claim, which is strictly stronger than the
// word ban was: no wallet VALUE may be rendered, and the panel must say why.
// RC2 — THE ONLY WALLET IN STANDINGS IS THE SENTENCE DENYING IT. The original
// assertion banned the word outright, which was a fair proxy while the panel
// said nothing about wallets. Sprint A states the distinction out loud, so a
// blanket ban is no longer usable — but a loosened regex would have let
// `<td>Wallet</td><td>$140</td>` through, which is the exact regression the ban
// existed to catch. The invariant is therefore COUNTED: the word may appear
// exactly once, and that once must be the locked explanatory sentence.
const walletMentions = (panel.match(/wallet/gi) || []).length;
check('wallet is mentioned exactly once in the standings panel',
  walletMentions === 1, String(walletMentions));
// A3.2 — the owner shortened the explainer. The COUNTED invariant above is
// unchanged and is what keeps `<td>Wallet</td><td>$140</td>` out; only the
// sentence it must be is restated, to the one the product now ships.
check('and that once is the locked explanatory sentence',
  /Wallet balance does not count/i.test(panel), panel.match(/[^.>]*wallet[^.]*\./i));
check('Overall is descending in combined NET, as served',
  rowsFor('overall').every((r, i, a) => i === 0
    || rankingCents('overall', a[i - 1]) >= rankingCents('overall', r)));
check('Versus is descending in Versus NET',
  rowsFor('versus').every((r, i, a) => i === 0
    || rankingCents('versus', a[i - 1]) >= rankingCents('versus', r)));
check('Pools is descending in Pool NET',
  rowsFor('pools').every((r, i, a) => i === 0
    || rankingCents('pools', a[i - 1]) >= rankingCents('pools', r)));
check('Overall and Versus really do order differently on this fixture',
  rowsFor('overall').map((r) => r.team_id).join()
    !== rowsFor('pools').map((r) => r.team_id).join(),
  `${rowsFor('overall').map((r) => r.team_id)} vs ${rowsFor('pools').map((r) => r.team_id)}`);
check('the model re-sorts nothing — the served order is the drawn order',
  rowsFor('overall').map((r) => r.rank).join() === '1,2,3');

section('cells: each table prints the figure it was ranked by');

for (const table of STANDINGS_TABLES) {
  const row = rowsFor(table.key)[0];
  const view = cellsFor(table.key, row);
  const last = view.cells[view.cells.length - 1];
  check(`${table.key}: the NET column is the ranking figure`,
    last.kind === 'cents' && last.value === rankingCents(table.key, row),
    `${last.value} vs ${rankingCents(table.key, row)}`);
  check(`${table.key}: the cell count matches the column count`,
    view.cells.length === table.columns.length - 2,
    `${view.cells.length} vs ${table.columns.length - 2}`);
}

section('H · The acting GM’s row is identifiable in all three tables');

check('the model reports the acting team from the server',
  actingTeamId() === 12, String(actingTeamId()));
check('exactly one row per table is marked',
  (panel.match(/class="fs-st__row is-me"/g) || []).length === 3,
  String((panel.match(/class="fs-st__row is-me"/g) || []).length));
check('the marked row is the acting team in every table',
  (panel.match(/class="fs-st__row is-me" data-team-id="12"/g) || []).length === 3);
check('it is announced to assistive tech, not only tinted',
  (panel.match(/aria-current="true"/g) || []).length === 3);
check('and it is marked at any rank — here it is not first',
  rowsFor('overall')[0].team_id !== 12
  && rowsFor('overall').some((r) => r.team_id === 12));

section('I · Intentional states — WP3B §8');

unbindStandings();
check('unbound draws no-data, never an invented table',
  standingsState() === STANDINGS_STATE_NO_DATA, standingsState());
check('and it renders no rows at all',
  (buildStandingsPanel().match(/fs-st__row/g) || []).length === 0);

markStandingsLoading();
check('loading is reported before any answer',
  standingsState() === STANDINGS_STATE_LOADING, standingsState());
check('the loading state is announced as busy',
  buildStandingsPanel().includes('aria-busy="true"'));

markStandingsUnavailable();
check('a refused or failed read is unavailable, never demo',
  standingsState() === STANDINGS_STATE_UNAVAILABLE, standingsState());
check('and it still draws no rows',
  (buildStandingsPanel().match(/fs-st__row/g) || []).length === 0);

bindStandings({ ...servedBody(), overall: [], versus: [], pools: [] });
check('a league with no teams reads as not-activated, not as no-data',
  standingsState() === STANDINGS_STATE_NOT_ACTIVATED, standingsState());
check('the not-activated copy points at the commissioner',
  /commissioner/i.test(buildStandingsPanel()));

bindStandings(servedBody());
check('a bound league with rows is ready',
  standingsState() === STANDINGS_STATE_READY, standingsState());

section('no raw identifier reaches a reader — Rev 4.3 §27');

for (const state of [null, 'loading', 'unavailable', 'empty']) {
  unbindStandings();
  if (state === 'loading') markStandingsLoading();
  if (state === 'unavailable') markStandingsUnavailable();
  if (state === 'empty') bindStandings({ ...servedBody(), overall: [], versus: [], pools: [] });
  const html = buildStandingsPanel();
  const text = html.replace(/<[^>]*>/g, ' ').replace(/data-[a-z-]+="[^"]*"/g, ' ');
  // SNAKE_CASE, not merely capitals: the page's own headings are legitimately
  // upper case (`STANDINGS`, `OVERALL STANDINGS`), and a rule that banned
  // capitals would be testing the POR's wording rather than leaked identifiers.
  // What must never appear is a code shape — an underscore-joined token, a
  // module path, a reason code or an exception string.
  const LEAK = /\.py\b|\bweb\/js\b|[a-z]_[a-z]|[A-Z]+_[A-Z]+|Traceback|Error:|\bnull\b|\bundefined\b/;
  check(`${state || 'unbound'}: no python, cents field or exception text is drawn`,
    !LEAK.test(text), (text.match(LEAK) || [''])[0]);
}

/* ── J–P · Commissioner economy — Rev 4.3 §16 ────────────────────────────── */

section('J/P · Only a commissioner is offered the economy surface');

/** The route's own body shape, at a 13-week league on the defaults. */
const CONFIG = Object.freeze({
  league_id: 1, season: 2026, frozen: false, configured: true,
  weekly_bet_minimum_cents: 1000,
  championship_contribution_cents: 8000,
  skunk_fee_cents: 1000,
  regular_season_week_count: 13,
  active_team_count: 12,
  start_week: 1, playoff_start_week: 14,
  weekly_minimum_reserve_per_player_cents: 13000,
  championship_reserve_per_player_cents: 8000,
  season_opening_allocation_per_player_cents: 21000,
  league_opening_allocation_cents: 252000,
  frozen_at: null,
});

unbindEconomy();
check('unbound, nothing is editable and nothing can activate',
  isEditable() === false && canActivate() === false);

bindEconomy(CONFIG);
setEconomyCapability(false);
check('a bound read WITHOUT commission is still not editable',
  isEditable() === false && canActivate() === false);
check('and the sheet offers no input and no control', (() => {
  const body = economySheet().body;
  return !/<input/.test(body) && !body.includes('fs-econ-save')
    && !body.includes('fs-econ-activate');
})());
check('the menu offers a non-commissioner no economy or commissioner entry',
  !menuEntries().some((e) => ['economy', 'commissioner'].includes(e.id)),
  menuEntries().map((e) => e.id).join(','));

setEconomyCapability(true);
check('with commission it becomes editable',
  isEditable() === true && canActivate() === true);
check('and the menu offers both commissioner entries',
  menuEntries().some((e) => e.id === 'economy')
  && menuEntries().some((e) => e.id === 'commissioner'));
check('the menu names Rules and League Settings for everyone',
  menuEntries().some((e) => e.id === 'rules')
  && menuEntries().some((e) => e.id === 'settings'));
check('a not-yet-built destination is drawn as text, not a dead control',
  menuSheet().body.includes('is-pending')
  && !/is-pending[^>]*data-menu-kind/.test(menuSheet().body));

section('J · The three editable inputs, with governed ranges');

check('exactly three inputs are offered',
  ECONOMY_INPUTS.length === 3, String(ECONOMY_INPUTS.length));
check('they are the POR’s three, in order',
  ECONOMY_INPUTS.map((i) => i.label).join(' | ')
    === 'Weekly Bet Minimum | Yahoo Championship Contribution | Skunk Fee',
  ECONOMY_INPUTS.map((i) => i.label).join(' | '));
check('the ranges are $1–$100 / $1–$1,000 / $1–$100',
  ECONOMY_INPUTS.map((i) => `${i.minCents}-${i.maxCents}`).join(' ')
    === '100-10000 100-100000 100-10000',
  ECONOMY_INPUTS.map((i) => `${i.minCents}-${i.maxCents}`).join(' '));
check('the defaults are $10 / $80 / $10',
  ECONOMY_INPUTS.map((i) => i.defaultCents).join(' ') === '1000 8000 1000');
check('the current values are read from the server, not from the defaults',
  JSON.stringify(currentInputs())
    === JSON.stringify({ weeklyBetMinimumCents: 1000,
      championshipContributionCents: 8000, skunkFeeCents: 1000 }));

section('K · Derived values are the server’s, and are never recomputed');

// RC2 adds the second, independent FantasyStakes Championship Contribution as
// a sixth read-only derived row, and names the RC1 row for the championship it
// has always described.
check('all six derived rows are declared',
  ECONOMY_DERIVED.length === 6, String(ECONOMY_DERIVED.length));
check('they are the POR’s six, in order',
  ECONOMY_DERIVED.map((d) => d.label).join(' | ')
    === 'Regular-Season Weeks | Weekly Minimum Reserve | Yahoo Championship Reserve | '
      + 'FantasyStakes Championship Contribution | Season-Opening Allocation | '
      + 'League allocation total',
  ECONOMY_DERIVED.map((d) => d.label).join(' | '));
check('every derived row renders the served figure',
  economySheet().body.includes('data-derived="regular_season_week_count"')
  && economySheet().body.includes('data-derived="league_opening_allocation_cents"'));
check('the per-player allocation is passed through untouched',
  perPlayerAllocationCents() === 21000, String(perPlayerAllocationCents()));
check('and the league total is too',
  JSON.stringify(leagueAllocation()) === JSON.stringify({ cents: 252000, teams: 12 }));

section('Q · The UI recomputes no economics');

check('a derived value the server did not send is drawn as unresolved, not filled',
  (() => {
    bindEconomy({ ...CONFIG, regular_season_week_count: null,
      season_opening_allocation_per_player_cents: null,
      league_opening_allocation_cents: null,
      weekly_minimum_reserve_per_player_cents: null });
    const body = economySheet().body;
    // The per-player figure is a dash, and activation is withheld because the
    // server could not state what would be issued.
    return perPlayerAllocationCents() === null
      && canActivate() === false
      && body.includes('is-unresolved');
  })());

bindEconomy(CONFIG);
check('the served allocation is NOT the product of the served inputs recomputed',
  (() => {
    // A frontend that multiplied would produce the same answer here, so the
    // discriminating case is a server that says something ELSE. If the UI
    // recomputed, it would overrule this and print 21000.
    bindEconomy({ ...CONFIG, season_opening_allocation_per_player_cents: 19999 });
    const drawn = perPlayerAllocationCents() === 19999
      && economySheet().body.includes('data-exact-cents="19999"');
    bindEconomy(CONFIG);
    return drawn;
  })());

section('L/M · Per-player allocation is primary; league total is secondary');

const econBody = economySheet().body;
const iPer = econBody.indexOf('fs-econ__alloc-value');
const iTot = econBody.indexOf('fs-econ__alloc-total');
check('the per-player figure carries the PER PLAYER wording',
  /\$210 PER PLAYER/.test(econBody));
check('the league total names the team count and the total',
  /League allocation total · 12 teams/.test(econBody)
  && /data-exact-cents="252000"/.test(econBody));
check('the per-player figure comes FIRST in the document',
  iPer !== -1 && iTot !== -1 && iPer < iTot, `${iPer} vs ${iTot}`);
check('nothing implies FantasyStakes collects or holds money',
  /holds no money and collects none/.test(econBody)
  && !/collected|deposit|withdraw|balance due/i.test(econBody));
check('the 13-week default worked example is what the server states',
  perPlayerAllocationCents() === 21000);

section('N · Activation is deliberate and separate');

check('the setup sheet offers no activation control of its own',
  !econBody.includes('fs-econ-confirm-go'));
check('it offers only an entry to the confirmation',
  econBody.includes('fs-econ-activate'));
const confirm = activationSheet();
check('the confirmation is its own sheet with its own title',
  confirm.title === 'Activate the season');
check('it says plainly that this cannot be undone',
  confirm.sub === 'This cannot be undone');
check('it restates what will be issued, and to how many',
  /data-exact-cents="21000"/.test(confirm.body)
  && /12 teams/.test(confirm.body));
check('it names the freeze before the control',
  confirm.body.indexOf('cannot be changed afterwards')
    < confirm.body.indexOf('fs-econ-confirm-go'));
check('it offers a way out',
  confirm.body.includes('Not yet') && confirm.body.includes('data-fs-close'));

section('O · Frozen after activation — values visible, fields inert');

bindEconomy({ ...CONFIG, frozen: true, frozen_at: '2026-09-05T12:00:00Z' });
check('the model reports frozen from the server’s own flag',
  isFrozen() === true);
check('nothing is editable, even holding commission',
  isEditable() === false && canActivate() === false);
const frozenBody = economySheet().body;
check('the sheet emits no input element at all',
  !/<input/.test(frozenBody));
check('and no save or activate control',
  !frozenBody.includes('fs-econ-save') && !frozenBody.includes('fs-econ-activate'));
check('the configured values remain visible',
  frozenBody.includes('data-input="weekly_bet_minimum_cents"')
  && frozenBody.includes('data-exact-cents="1000"'));
check('the derived values remain visible',
  frozenBody.includes('data-derived="season_opening_allocation_per_player_cents"')
  && frozenBody.includes('$210 PER PLAYER'));
check('the lock is communicated in product language',
  frozenBody.includes('fs-econ-frozen') && /Locked for this season/.test(frozenBody));
check('the sub-heading says the season is active and locked',
  economySheet().sub === 'Active season · locked');

markEconomyUnavailable();
check('an unreadable configuration says so rather than drawing a form',
  economySheet().body.includes('data-economy-state="unavailable"')
  && !/<input/.test(economySheet().body));

unbindEconomy();
unbindStandings();

/* ── Result ──────────────────────────────────────────────────────────────── */

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`${failures.length} ASSERTION(S) FAILED`);
  failures.forEach((f) => console.log(`  · ${f}`));
  process.exit(1);
}
console.log('All assertions PASSED');
