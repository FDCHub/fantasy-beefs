/* ============================================================================
 * FantasyStakes — WP3D · provider identity and Yahoo attribution · components
 *
 * Run directly:   node web/tests/wp3d_component_tests.mjs
 * Or through:     python test_wp3d_provider_attribution.py
 *
 * THE STATE MODEL, DRIVEN THROUGH EVERY BRANCH IT HAS. The browser tier runs
 * the real page against four differently-bound leagues and can prove what each
 * renders; what it CANNOT do is produce a failed context read on demand, or
 * feed the model a provider state this build does not recognise. Both are
 * one line here, and both are states a GM can really meet.
 * ========================================================================== */

import { readFileSync } from 'node:fs';

import {
  FAMILY_DEMO, FAMILY_NONE, FAMILY_YAHOO,
  SOURCE_DEMO, SOURCE_LABELS, SOURCE_LEAGUE_UNAVAILABLE, SOURCE_NOT_CONNECTED,
  SOURCE_REACHABLE, SOURCE_YAHOO_CONNECTED, SOURCE_YAHOO_NOT_SYNCED,
  SOURCE_YAHOO_SYNCING, SYNCING_REACHABLE,
  attributionEligible, sourceLabel, sourceState,
} from '../js/provider-state.js';

import {
  YAHOO_ATTRIBUTION_HREF, YAHOO_ATTRIBUTION_TEXT, attributionFooter,
  isDemoSource, sourceChip,
} from '../js/attribution.js';

import {
  bindLeagueContext, markLeagueUnavailable, unbindLeague,
} from '../js/league-model.js';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

function section(title) {
  console.log(`\n${title}`);
}

/** A served LeagueContextOut, in whichever provider state is wanted. */
function context(over = {}) {
  return {
    league_id: 1,
    league_name: 'Certification League',
    season: 2026,
    current_week: 5,
    week_resolved: true,
    provider: 'yahoo',
    provider_league_key: '461.l.certification',
    provider_state: 'bound',
    demo: false,
    acting_team_id: 1,
    acting_team_name: 'Gravy Train',
    acting_team_owner: 'A. Gm',
    acting_provider_team_key: null,
    season_final_week: 17,
    playoff_start_week: 15,
    phase: 'regular',
    record_resolved: true,
    wins: 2, losses: 0, ties: 0, decided: 2, record_label: '2–0',
    ...over,
  };
}

/* ── A · the vocabulary ──────────────────────────────────────────────────── */

section('A · Six labels, and no seventh');

check('the vocabulary holds exactly six', SOURCE_LABELS.length === 6,
  String(SOURCE_LABELS.length));
check('and they are Rev 4.3 §22 verbatim, in order',
  SOURCE_LABELS.join(' | ')
    === 'DEMO | YAHOO · CONNECTED | YAHOO · SYNCING | '
      + 'YAHOO · NOT SYNCED YET | NOT CONNECTED | LEAGUE UNAVAILABLE',
  SOURCE_LABELS.join(' | '));
check('the list is frozen — no surface can add a label at runtime',
  Object.isFrozen(SOURCE_LABELS));

let mutated = false;
try { SOURCE_LABELS.push('YAHOO · PROBABLY FINE'); } catch { mutated = true; }
check('and pushing to it fails rather than succeeding quietly',
  mutated || SOURCE_LABELS.length === 6, String(SOURCE_LABELS.length));

/* ── B · the unreachable sixth ───────────────────────────────────────────── */

section('B · YAHOO · SYNCING is defined and cannot be selected');

check('it is in the vocabulary', SOURCE_LABELS.includes(SOURCE_YAHOO_SYNCING));
check('it is NOT in the reachable set',
  !SOURCE_REACHABLE.includes(SOURCE_YAHOO_SYNCING),
  SOURCE_REACHABLE.join(' | '));
check('and the module says so in one place a reader can find',
  SYNCING_REACHABLE === false);
check('the other five ARE reachable', SOURCE_REACHABLE.length === 5);

// NO INPUT PRODUCES IT. Every provider_state the backend can emit, crossed with
// both demo values, and none of them selects the syncing label. This is the
// assertion that would fail the day somebody wired an open provider conflict to
// it — which the owner ruling forbids.
const EVERY_INPUT = [];
for (const state of ['bound', 'pending', 'absent', 'something-new', null]) {
  for (const demo of [true, false]) {
    unbindLeague();
    bindLeagueContext(context({ provider_state: state, demo }));
    EVERY_INPUT.push(sourceLabel());
  }
}
check('no combination of served facts produces YAHOO · SYNCING',
  !EVERY_INPUT.includes(SOURCE_YAHOO_SYNCING),
  [...new Set(EVERY_INPUT)].join(' | '));
check('and every answer it DOES give is one of the six',
  EVERY_INPUT.every((l) => SOURCE_LABELS.includes(l)),
  [...new Set(EVERY_INPUT)].join(' | '));

/* ── C · the five reachable states ───────────────────────────────────────── */

section('C · Each reachable state, and what it permits');

const CASES = [
  ['a Yahoo league with a stated week',
    context(), SOURCE_YAHOO_CONNECTED, FAMILY_YAHOO, true, true],
  ['a Yahoo league that has never synced',
    context({ provider_state: 'pending', current_week: null,
      week_resolved: false }),
    SOURCE_YAHOO_NOT_SYNCED, FAMILY_YAHOO, true, false],
  ['a league with no provider binding',
    context({ provider_state: 'absent', provider: null,
      provider_league_key: null }),
    SOURCE_NOT_CONNECTED, FAMILY_NONE, true, false],
  ['a Demo league',
    context({ demo: true, provider: 'demo',
      provider_league_key: 'demo.l.certification' }),
    SOURCE_DEMO, FAMILY_DEMO, true, false],
];

for (const [what, body, label, family, available, attributable] of CASES) {
  unbindLeague();
  bindLeagueContext(body);
  const state = sourceState();
  check(`${what} reads ${label}`, state.label === label, state.label);
  check(`  · its source family is ${family}`, state.family === family,
    state.family);
  check('  · availability is reported truthfully',
    state.available === available);
  check(`  · attribution is ${attributable ? 'permitted' : 'REFUSED'}`,
    attributionEligible() === attributable, String(attributionEligible()));
}

section('D · An unreadable context is unavailable, never connected');

unbindLeague();
bindLeagueContext(context());
check('a bound session reads connected',
  sourceLabel() === SOURCE_YAHOO_CONNECTED);

markLeagueUnavailable();
check('and a failed read immediately reads LEAGUE UNAVAILABLE',
  sourceLabel() === SOURCE_LEAGUE_UNAVAILABLE, sourceLabel());
check('never both — the previous state does not survive the failure',
  sourceLabel() !== SOURCE_YAHOO_CONNECTED);
check('attribution goes with it', attributionEligible() === false);
check('and the surface is reported unavailable',
  sourceState().available === false);

unbindLeague();
check('an unbound model reads LEAGUE UNAVAILABLE too — not demo, not connected',
  sourceLabel() === SOURCE_LEAGUE_UNAVAILABLE, sourceLabel());

bindLeagueContext(null);
check('and a malformed body cannot present as connected',
  sourceLabel() === SOURCE_LEAGUE_UNAVAILABLE, sourceLabel());

bindLeagueContext(context({ provider_state: 'a-state-from-the-future' }));
check('an unrecognised provider state fails CLOSED, not open',
  sourceLabel() === SOURCE_LEAGUE_UNAVAILABLE
  && attributionEligible() === false, sourceLabel());

/* ── E · the chip ────────────────────────────────────────────────────────── */

section('E · The chip is readable text, not a colour');

unbindLeague();
bindLeagueContext(context({ demo: true, provider: 'demo',
  provider_league_key: 'demo.l.certification' }));
let chip = sourceChip();
check('DEMO renders as the word DEMO', chip.includes('>DEMO<'), chip);
check('and carries its state for styling, not for meaning',
  chip.includes('data-source-state="demo"'));
check('the label is also exposed as data, for assertions and tooling',
  chip.includes('data-source-label="DEMO"'));
check('nothing about it reads as a debug badge',
  !/debug|dev|test|fixture|prototype|mock|sandbox/i.test(chip), chip);
check('and it does not rename the product',
  !chip.includes('FantasyStakes'));
check('isDemoSource agrees with the chip', isDemoSource() === true);

unbindLeague();
bindLeagueContext(context());
chip = sourceChip();
check('a connected league renders the full label',
  chip.includes('>YAHOO · CONNECTED<'), chip);
check('and is not marked demo', chip.includes('data-source-state="yahoo"')
  && isDemoSource() === false);

/* ── F · the attribution ─────────────────────────────────────────────────── */

section('F · The attribution appears only where both conditions hold');

unbindLeague();
bindLeagueContext(context());
let footer = attributionFooter();
check('a connected league, on a Yahoo surface, is attributed',
  footer.includes(YAHOO_ATTRIBUTION_TEXT), footer);
check('the text is exactly the agreement’s',
  YAHOO_ATTRIBUTION_TEXT === 'Fantasy data provided by Yahoo Fantasy',
  YAHOO_ATTRIBUTION_TEXT);
check('the link points at the ruled official Yahoo Fantasy destination',
  footer.includes(`href="${YAHOO_ATTRIBUTION_HREF}"`)
  && YAHOO_ATTRIBUTION_HREF === 'https://football.fantasysports.yahoo.com/',
  YAHOO_ATTRIBUTION_HREF);
check('and the URL is not printed as visible copy',
  !footer.includes(`>${YAHOO_ATTRIBUTION_HREF}<`));
check('it is a real anchor, so it is keyboard-focusable by default',
  /<a [^>]*href=/.test(footer));
check('no endorsement language rides along',
  !/powered by|official|partner|approved|endorse/i.test(footer), footer);

check('a surface that shows NO Yahoo information is not attributed',
  attributionFooter({ showsYahooInformation: false }) === '');

unbindLeague();
bindLeagueContext(context({ provider_state: 'pending', current_week: null,
  week_resolved: false }));
check('a binding ALONE is not Yahoo Fantasy Information — no attribution',
  attributionFooter() === '', attributionFooter());

unbindLeague();
bindLeagueContext(context({ demo: true, provider: 'demo',
  provider_league_key: 'demo.l.certification' }));
check('DEMO IS NEVER ATTRIBUTED — the hard rule',
  attributionFooter() === '' && attributionFooter({
    showsYahooInformation: true }) === '',
  'no footer under any caller argument');

unbindLeague();
bindLeagueContext(context({ provider_state: 'absent', provider: null,
  provider_league_key: null }));
check('an unconnected league is not attributed',
  attributionFooter() === '');

markLeagueUnavailable();
check('and neither is one whose context could not be read',
  attributionFooter() === '');

/* ── G · the trap ────────────────────────────────────────────────────────── */

section('G · The name never decides anything');

unbindLeague();
bindLeagueContext(context({ league_name: 'Demo League' }));
check('a live Yahoo league CALLED "Demo League" is not badged DEMO',
  sourceLabel() === SOURCE_YAHOO_CONNECTED, sourceLabel());
check('and it IS attributed, because it really is Yahoo-backed',
  attributionEligible() === true);

unbindLeague();
bindLeagueContext(context({ demo: true, provider: 'demo',
  provider_league_key: 'demo.l.x', league_name: 'Sunday Gravy Invitational' }));
check('a Demo league called anything at all is still badged DEMO',
  sourceLabel() === SOURCE_DEMO, sourceLabel());
check('and is still not attributed', attributionEligible() === false);

/* ── H · sign-out ────────────────────────────────────────────────────────── */

section('H · Signing out takes the source with it');

unbindLeague();
bindLeagueContext(context());
check('a signed-in session shows its source',
  sourceLabel() === SOURCE_YAHOO_CONNECTED && attributionEligible() === true);

unbindLeague();   // what `clearAuthoritativeData` calls on sign-out
check('after the session-bound models are cleared, no source is claimed',
  sourceLabel() === SOURCE_LEAGUE_UNAVAILABLE, sourceLabel());
check('and no attribution survives it',
  attributionFooter() === '' && attributionEligible() === false);
check('the chip does not go blank — it states the truth instead',
  sourceChip().includes('>LEAGUE UNAVAILABLE<'));

/* ── I · the source scan ─────────────────────────────────────────────────── */

section('I · Nothing in the chrome can render a diagnostic');

const src = (name) => readFileSync(
  new URL(`../js/${name}`, import.meta.url), 'utf8');
const codeOnly = (t) => t
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/^\s*\/\/.*$/gm, ' ');

const MODEL = codeOnly(src('provider-state.js'));
const ATTR = codeOnly(src('attribution.js'));

for (const forbidden of ['status', 'stack', 'oauth', 'token', 'endpoint',
  'conflict', 'exception', 'refresh']) {
  check(`the state model never touches ${forbidden}`,
    !new RegExp(forbidden, 'i').test(MODEL.replace(/providerState|sourceState|SOURCE_[A-Z_]+/g, '')),
    'clean');
}
check('and the attribution module reads only the state model',
  !/fetch|apiFetch|XMLHttpRequest/.test(ATTR));

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`${failures.length} ASSERTION(S) FAILED`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
console.log('All assertions PASSED');
