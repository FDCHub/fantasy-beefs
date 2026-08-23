/* ============================================================================
 * FantasyStakes — WP3C · Rev 4.3 gameplay surfaces · component tests
 *
 * Run directly:   node web/tests/wp3c_component_tests.mjs
 * Or through:     python test_wp3c_rev43_gameplay.py
 *
 * The shipped ES modules are executed directly, against served bodies shaped
 * exactly as the routes return them. The geometry and interaction claims are
 * the browser suite's; these are the ones that can be made from the modules.
 * ========================================================================== */

import { readFileSync } from 'node:fs';

import {
  VERSUS_STATE_FIELD_UNKNOWN, VERSUS_STATE_NONE_ELIGIBLE,
  VERSUS_STATE_NO_DATA, VERSUS_STATE_READY, VERSUS_STATE_UNAVAILABLE,
  allOpponents, bindVersus, fieldDeterminable, markVersusUnavailable,
  playableCount, playableOpponents, unbindVersus, versusPhase, versusState,
} from '../js/versus-model.js';

import { bindAction, unbindAction } from '../js/action-model.js';
import { buildLeaguePanel } from '../js/league.js';
import { previewSheet } from '../js/preview.js';
import { counterStakeSheet, parseWholeCredits } from '../js/counter-stake.js';
import { MARKETS } from '../js/wager-model.js';
import {
  bindLeagueContext, unbindLeague,
} from '../js/league-model.js';
import {
  headingWithPhase, seasonComplete, seasonPhase, seasonPhaseLabel,
  weekPhaseLabel,
} from '../js/phase.js';
import { LEDGER_TRUST_ANCHOR, buildLedgerPanel } from '../js/ledger.js';
import { RULE_GROUPS, SETTINGS, SKUNK } from '../js/data/rules-data.js';
import { buildRulesPanel, ruleSheet, settingSheet } from '../js/rules.js';
import { settingsRows } from '../js/settings-model.js';
import { BETS_HEADING } from '../js/week.js';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

function section(title) {
  console.log(`\n${title}`);
}

/** An ActionStateOut, exactly as `/league/{id}/action/me` returns it. */
function actionBody(opts = {}) {
  return {
    team_id: 1,
    league_id: 1,
    counts: { action: 0, waiting: 0, live: 0, completed: 0 },
    sections: { action: [], waiting: [], live: [], completed: [] },
    opponents: opts.opponents ?? [
      { team_id: 7, team_name: 'Alpha', owner: 'A Owner', versus_eligible: true },
      { team_id: 8, team_name: 'Bravo', owner: 'B Owner', versus_eligible: true },
    ],
    versus_phase: opts.phase ?? 'regular',
    versus_field_determinable: opts.determinable ?? true,
  };
}

/** A LeagueContextOut. */
function contextBody(opts = {}) {
  return {
    league_id: 1,
    league_name: 'Test League',
    season: 2026,
    current_week: opts.week === undefined ? 5 : opts.week,
    week_resolved: opts.week !== null,
    provider: 'yahoo',
    provider_league_key: 'k',
    provider_state: 'bound',
    demo: false,
    acting_team_id: 1,
    acting_team_name: 'Me',
    acting_team_owner: 'Owner',
    acting_provider_team_key: 't1',
    season_final_week: 17,
    playoff_start_week: 15,
    phase: opts.phase === undefined ? 'regular' : opts.phase,
  };
}

function bindAll(opts = {}) {
  bindLeagueContext(contextBody(opts));
  bindAction(actionBody(opts));
  bindVersus();
}

function unbindAll() {
  unbindVersus();
  unbindAction();
  unbindLeague();
}

/* ── A · Play discovers real opponents — §4, §6 ──────────────────────────── */

section('A · Play discovers the server’s opponents and invents none');

unbindAll();
check('unbound, discovery has nobody',
  allOpponents().length === 0 && versusState() === VERSUS_STATE_NO_DATA,
  versusState());
check('and the panel draws an intentional state, not cards',
  buildLeaguePanel().includes('data-versus-state')
  && !buildLeaguePanel().includes('data-card-action="challenge"'));

bindAll();
check('bound, the opponents are exactly the served ones',
  allOpponents().map((o) => o.teamId).join(',') === '7,8',
  allOpponents().map((o) => o.teamId).join(','));
check('with the server’s own names',
  allOpponents().map((o) => o.name).join(',') === 'Alpha,Bravo');
check('the state is ready', versusState() === VERSUS_STATE_READY);

const bound = buildLeaguePanel();
check('every card carries a real team id',
  (bound.match(/data-card-id="7"/g) || []).length === 1
  && (bound.match(/data-card-id="8"/g) || []).length === 1);
check('no invented opponent name reaches the panel',
  !/CULV Destroyers|Gridiron Goodfellas|Bada Bing Bombers|Sunday Gravy/.test(bound));
check('no invented record, rank, projection or teaser either',
  !/7–0|Projected|Biggest dog on the board/.test(bound));

section('B · No fabricated market values — §4');

check('the card names the three markets',
  (bound.match(/fs-market__label/g) || []).length === 6,
  `${(bound.match(/fs-market__label/g) || []).length} cells across 2 cards`);
check('and quotes none of them',
  !/[+−-]\d{3}|\bu \d|\bo \d/.test(bound));
check('the markets are ML | SPR | O/U',
  MARKETS.map((m) => m.short).join(' | ') === 'ML | SPR | O/U');

section('C · The Versus card hierarchy — §7');

check('VIEW MATCHUP PREVIEW appears once per card',
  (bound.match(/VIEW MATCHUP PREVIEW/g) || []).length === 2);
check('it is a full-width action row, not a text link',
  bound.includes('class="fs-previewrow"'));
check('and it sits ABOVE the market cells on every card',
  bound.split('data-card-action="challenge"').slice(1).every((card) => {
    const p = card.indexOf('fs-previewrow');
    const m = card.indexOf('fs-markets');
    return p !== -1 && m !== -1 && p < m;
  }));
check('identity comes before the preview row',
  bound.indexOf('fs-wcard__identity') < bound.indexOf('fs-previewrow'));

section('D · Postseason eligibility is READ, never inferred — §6');

bindAll({
  phase: 'postseason',
  opponents: [
    { team_id: 7, team_name: 'Alive', owner: 'A', versus_eligible: true },
    { team_id: 8, team_name: 'Eliminated', owner: 'B', versus_eligible: false },
    { team_id: 9, team_name: 'Consolation', owner: 'C', versus_eligible: false },
  ],
});
check('the phase is the server’s answer', versusPhase() === 'postseason');
check('only the eligible team is playable',
  playableCount() === 1 && playableOpponents()[0].teamId === 7,
  `${playableCount()} of ${allOpponents().length}`);
const postseason = buildLeaguePanel();
check('an ineligible team is not offered',
  postseason.includes('Alive')
  && !postseason.includes('Eliminated')
  && !postseason.includes('Consolation'));
check('the heading counts the playable subset, not the roster',
  /1 OPPONENT ·/.test(postseason), 'singular, and one');

check('the model reads no week, seed, record or standings position', (() => {
  // STRUCTURAL, AND READ FROM THE CODE RATHER THAN THE PROSE. The module
  // cannot infer eligibility from a week number because it never sees one —
  // it imports only the Action read. Its own header explains that rule and
  // therefore contains the words, so comments are stripped first.
  const src = stripComments(versusModelSource());
  return !/currentWeek|playoff|seed|standings|\brank\b/i.test(src);
})(), 'no week, seed or standings input exists to infer from');

bindAll({ phase: 'postseason', determinable: false,
  opponents: [{ team_id: 7, team_name: 'Alpha', owner: 'A', versus_eligible: false }] });
check('an undeterminable field fails closed',
  fieldDeterminable() === false
  && versusState() === VERSUS_STATE_FIELD_UNKNOWN, versusState());
check('and nobody is offered',
  playableCount() === 0 && !buildLeaguePanel().includes('data-card-action="challenge"'));
check('the copy explains the championship track, not a reason code',
  /championship track/.test(buildLeaguePanel()));
check('and leaks no code shape to the reader', (() => {
  // SNAKE_CASE AND PATHS, not merely capitals: the page's own headings are
  // legitimately upper case, and banning capitals would test the POR's wording
  // rather than leaked identifiers.
  const text = buildLeaguePanel().replace(/<[^>]*>/g, ' ')
    .replace(/data-[a-z-]+="[^"]*"/g, ' ');
  return !/[a-z]_[a-z]|[A-Z]+_[A-Z]+|\.py\b|web\/js\//.test(text);
})());

bindAll({ phase: 'postseason',
  opponents: [{ team_id: 8, team_name: 'Out', owner: 'B', versus_eligible: false }] });
check('an eliminated GM with a known field sees a different sentence',
  versusState() === VERSUS_STATE_NONE_ELIGIBLE, versusState());
check('and is told Pools stay open to them',
  /Pools stay open/.test(buildLeaguePanel()));

markVersusUnavailable();
check('a failed read is unavailable, never demo',
  versusState() === VERSUS_STATE_UNAVAILABLE);

/* ── E · Play removals — §5, §12 ─────────────────────────────────────────── */

section('E · Play’s removals');

bindAll();
const play = buildLeaguePanel();
check('no FIRST KICKOFF countdown', !/FIRST KICKOFF/i.test(play));
check('no standings rank in the summary strip',
  !/\b1st\b|\b2nd\b|\b3rd\b/.test(play));
check('no Fantasy Sportsbook suffix', !/Fantasy Sportsbook/i.test(play));
check('no directional arrow in any heading', !play.includes('↕'));
check('the word SWIPE still carries the affordance', play.includes('SWIPE'));
check('the four-cell strip is retained',
  (play.match(/fs-strip__cell/g) || []).length === 4);
// UIRECON WAVE 1 — the labels are held to one line at the smallest certified
// width, so two of them were reworded. The claim is unchanged: four cells,
// four locked labels, and no rank among them.
check('and its labels are the locked four',
  ['Net Won', 'Wallet', 'Min Left', 'Available']
    .every((l) => play.includes(l)));

/* ── F · The Matchup Preview — §8 ────────────────────────────────────────── */

section('F · Matchup Preview is analysis, not a second wagering surface');

const previewModel = {
  id: '7', name: 'Alpha', record: '3–1', rank: '',
  you: { name: 'Me', record: '2–2' },
  weekLabel: 'Week 5', ml: null, spread: null, total: null,
  yourProjection: null, opponentProjection: null,
  yourLineup: [], opponentLineup: [], settled: false,
};
const prev = previewSheet(previewModel);
const prevTitles = [...prev.body.matchAll(/fs-prev__title">([^<]*)/g)].map((m) => m[1]);

// UIRECON WAVE 4A — THE MATCHUP IS NAMED ONCE.
//
// A `MATCHUP` block listing both team names sat under a sheet subtitle
// that had just given both team names — the same two facts twice inside
// about sixty pixels, and in the bound state the second copy carried two
// blank values. The slot now carries what the subtitle does not: the
// market on offer (`ON OFFER`) for a live pairing, or the final score
// (`RESULT`) for a settled one. An UNBOUND preview has neither, so it
// renders no second block at all — which is what these fixtures are.
/* FINAL POR UI-3E §27E — LINEUPS LEADS THE PREVIEW SHEET.
 *
 * The locked order is now LINEUPS → WHY THE LINE LOOKS THIS WAY → THE READ.
 * The claim is unchanged and is still the one worth holding: the sheet's
 * section order is LOCKED and is not something a later change may quietly
 * reshuffle. Only the locked order moved.
 *
 * WHY IT MOVED. §27E puts the reader's own roster first: LINEUPS is the fact
 * the two analysis modules rest on, and a reader deciding whether to accept a
 * wager looks at who is playing before they read why the line sits where it
 * does. Left behind by the run that implemented §27E and replaced here rather
 * than relaxed. */
check('the section order is the locked one',
  prevTitles.join(' → ')
    === 'LINEUPS → WHY THE LINE LOOKS THIS WAY → THE READ',
  prevTitles.join(' → '));
check('there is no SPORTSBOOK VIEW block',
  !prev.body.includes('SPORTSBOOK VIEW'));
check('and no market cell of any kind',
  !/data-market|fs-market__label/.test(prev.body));
/* §27E — the lineups precede the analysis, which is the same claim inverted.
 * Kept as a SEPARATE check from the order above because it is the one a future
 * change is most likely to break by accident: the titles array can be right
 * while the rendered body is not, if a section is emitted out of band. */
check('the lineups precede the analysis',
  prev.body.indexOf('LINEUPS') < prev.body.indexOf('WHY THE LINE')
  && prev.body.indexOf('LINEUPS') < prev.body.indexOf('THE READ'));
check('both analysis sections are open by default',
  (prev.body.match(/aria-expanded="true"/g) || []).length === 2);
check('the lineups are collapsed',
  (prev.body.match(/aria-expanded="false"/g) || []).length === 1);
check('it says closing loses nothing',
  /nothing you have entered is lost/i.test(prev.body));
check('an unpriced matchup says so rather than inventing a line',
  /has not been priced yet/.test(prev.body));

/* ── G · The counter-stake sheet — §15 ───────────────────────────────────── */

section('G · Counter uses product UI, never window.prompt');

check('whole Credits parse to exact cents', parseWholeCredits('25') === 2500);
check('a fractional entry is refused, not rounded',
  parseWholeCredits('25.50') === null);
check('zero is refused', parseWholeCredits('0') === null);
check('a negative is refused', parseWholeCredits('-5') === null);
check('junk is refused', parseWholeCredits('abc') === null
  && parseWholeCredits('') === null && parseWholeCredits(null) === null);

const counter = counterStakeSheet({
  card: { opponent: 'Alpha', marketLabel: 'Moneyline', termsLabel: 'LOCKED' },
  availableCents: 6500,
  onSubmit: async () => {},
  explain: () => 'refused',
});
check('the sheet names what is being countered',
  counter.sub === 'Alpha' && /Moneyline/.test(counter.body));
check('it shows the GM what they can spend',
  /data-exact-cents="6500"/.test(counter.body));
check('it offers a stake field, a send and a cancel',
  /id="fs-cstake-input"/.test(counter.body)
  && /id="fs-cstake-send"/.test(counter.body)
  && /id="fs-cstake-cancel"/.test(counter.body));
check('it has somewhere for a server refusal to land',
  /id="fs-cstake-error"/.test(counter.body) && /role="alert"/.test(counter.body));
check('and it clamps nothing — no Math.min or Math.max',
  !/Math\.(min|max)/.test(counterStakeSource()));

const unknownAvailable = counterStakeSheet({
  card: { opponent: 'Alpha' }, availableCents: null,
  onSubmit: async () => {}, explain: () => '',
});
check('an unreadable Available says so rather than showing zero',
  /could not be read/.test(unknownAvailable.body)
  && !/data-exact-cents="0"/.test(unknownAvailable.body));

/* ── H · The dynamic season phase — §17, §21, §27 ────────────────────────── */

section('H · The season phase is authoritative on every surface');

unbindLeague();
check('unbound, there is no phase to state', seasonPhase() === null
  && seasonPhaseLabel() === null && weekPhaseLabel(5) === 'Week 5');

for (const [wire, label] of [['regular', 'Regular Season'],
  ['postseason', 'Postseason'], ['championship', 'Championship']]) {
  bindLeagueContext(contextBody({ phase: wire }));
  check(`${wire} renders as ${label}`, seasonPhaseLabel() === label,
    String(seasonPhaseLabel()));
  check(`and pairs with the week: Week 5 · ${label}`,
    weekPhaseLabel(5) === `Week 5 · ${label}`, String(weekPhaseLabel(5)));
}

bindLeagueContext(contextBody({ phase: 'complete' }));
check('a closed season is Season Complete', seasonPhaseLabel() === 'Season Complete');
check('and names no current week, because there is none',
  weekPhaseLabel(5) === 'Season Complete', String(weekPhaseLabel(5)));
check('seasonComplete reports it', seasonComplete() === true);

bindLeagueContext(contextBody({ phase: null }));
check('an unclassifiable week degrades to the week alone',
  weekPhaseLabel(9) === 'Week 9', String(weekPhaseLabel(9)));

bindLeagueContext(contextBody({ phase: 'championship' }));
check('the Status heading grammar keeps ACTION as content terminology',
  headingWithPhase(16, 'ACTION') === 'WEEK 16 · CHAMPIONSHIP ACTION',
  headingWithPhase(16, 'ACTION'));

check('no gameplay surface writes a hard-coded phase CLAIM', (() => {
  // TARGETED AT THE CLAIM, NOT THE WORDS. `Regular Season Minimum Stakes` is a
  // Ledger ROW LABEL naming a component of the allocation — legitimate
  // accounting terminology that says nothing about what week it is now. What
  // §17 and §27 forbid is a surface ASSERTING the current phase, which reads
  // as `Week N · Regular Season` or `REGULAR SEASON ACTION`. Only those shapes
  // are banned, and only outside the demo fixture constants.
  const sources = [leagueSource(), actionSource(), ledgerSource(), weekSource()];
  const CLAIM = /(Week \$?\{?[^'"`]*\}?\s*·\s*Regular Season|REGULAR SEASON ACTION)/;
  return sources.every((src) => stripComments(src)
    .split('\n')
    // TWO NAMED FIXTURE CONSTANTS ARE EXEMPT, and only these two. Each is
    // rendered ONLY in demo mode — `ledgerSubtitle()` and `actionHeader()` both
    // return the live phase for a bound session and fall back to these for the
    // illustrative league. §28 keeps governed Demo fixtures; what it forbids is
    // production falling back to them, and the two functions are guarded on
    // mode. Naming them keeps the exemption explicit rather than implied by a
    // looser pattern.
    .filter((line) => !line.includes('LEDGER_SUBTITLE =')
      && !line.includes('ACTION_HEADER ='))
    .every((line) => !CLAIM.test(line)));
})());
check('and each of the four reads the phase helper instead',
  [actionSource(), ledgerSource(), leagueSource()]
    .every((src) => /from '\.\/phase\.js'/.test(src)));

/* ── I · Account — §18–§21 ───────────────────────────────────────────────── */

section('I · Account keeps every figure and reduces the overload');

bindLeagueContext(contextBody());
const account = buildLedgerPanel();

check('the trust anchor is exact', LEDGER_TRUST_ANCHOR
  === 'Real odds. Fantasy stakes. Ledger keeps score.');
check('it appears on Account, once', (account.match(/fs-anchor/g) || []).length === 1);
check('the top-level strips answer the four questions',
  ['Available', 'In Play', 'Escrow', 'Min Left', 'Settle']
    .every((l) => account.includes(l)));
check('Current Settle is visible without expanding anything',
  account.indexOf('fs-current-settle') > 0
  && !/data-disclosure[^]*?fs-current-settle/.test(
    account.slice(account.indexOf('fs-lscroll'),
      account.indexOf('fs-current-settle'))
      .split('</section>').pop()));
// UIRECON WAVE 2 — FOUR SECTIONS, ONE CONSTRUCTION. Current Settle stopped
// being a bespoke card and became section 4.
//
// FINAL POR UI-6 §30 — ALL FOUR NOW START CLOSED. Rev 4.3 §14.2 excepted
// section 4 so the figure the tab derives needed no tap; §30 removed the
// exception, because one card behaving differently from three
// identical-looking siblings reads as a bug rather than as an affordance. The
// claim here is unchanged — four real disclosures, each with a real toggle
// button carrying an accessible expanded state — and only the expected state
// moved, for all four together. Left behind by the run that implemented §30.
check('the four accounting sections are disclosures',
  (account.match(/data-disclosure/g) || []).length === 4);
check('each has a real button with aria-expanded',
  (account.match(/data-lsec-toggle/g) || []).length === 4
  // `>=` ON THE FALSE COUNT, `===` ON THE TRUE ONE. The panel also contains
  // expandable ROWS inside the sections, which carry their own collapsed
  // `aria-expanded`, so the false count is a floor rather than an exact number
  // — the original assertion used `>= 3` for exactly this reason. The true
  // count is exact and is the one carrying §30's claim: nothing on this panel
  // starts expanded.
  && (account.match(/aria-expanded="false"/g) || []).length >= 4
  && (account.match(/aria-expanded="true"/g) || []).length === 0);
check('no accounting row was deleted — the detail is in the DOM',
  account.includes('Season-Opening FantasyStakes')
  && account.includes('MATCHUP ACTIVITY')
  && account.includes('PROP POOL ACTIVITY'));

/* ── J · Rules terminology — §22–§26 ─────────────────────────────────────── */

section('J · Rules say what is actually true');

let rulesText = buildRulesPanel();
for (const g of RULE_GROUPS) rulesText += ruleSheet(g).body;
for (const row of settingsRows()) rulesText += settingSheet(row).body;
rulesText = rulesText.replace(/<[^>]*>/g, ' ');

for (const stale of ['BAB', 'BAB-504', 'Economy Stop', 'fourteen',
  '14-week', 'capped at', '$140 max', 'Buy-In', 'buy-in',
  'five certified stops', 'Championship Pot Contribution']) {
  check(`no stale term: ${stale}`, !rulesText.includes(stale));
}

// A3.2 — "14 weeks" was banned outright while the rules ASSERTED a fixed
// fourteen-week season. RC2 derives the Weekly Play Reserve from each league's
// own Yahoo schedule, and the rules now show a worked example so a GM can see
// how the three parts combine. A worked example needs numbers. So the ban
// becomes what it always meant: a week count may appear only inside a passage
// that says it is one league's arithmetic and that another league differs.
const weekCountSentences = (rulesText.match(/[^.]*\b\d{1,2} weeks\b[^.]*\./g) || []);
check('a week count is only ever shown as a labelled example',
  weekCountSentences.every((s) => /works out as/.test(s)),
  JSON.stringify(weekCountSentences));
check('and the example says plainly that another league differs',
  weekCountSentences.length === 0
  || /different weekly minimum or a different schedule gets a different/
    .test(rulesText));
check('the rules never state a week count as universal',
  !/every league plays \d{1,2} weeks|all leagues play \d{1,2} weeks|the \d{1,2}-week season/i
    .test(rulesText));
check('no internal file citation', !/\.py\b|web\/js\//.test(rulesText));

for (const required of [
  'Season-Opening Allocation', 'Weekly Bet Minimum',
  // A3.2 — RC2 has TWO independently configured contributions, so the rules
  // must name both rather than the retired single "Championship Pot".
  'Weekly Play Reserve', 'Yahoo Championship Contribution',
  'FantasyStakes Championship Contribution', 'Skunk Fee',
  'largest margin', 'Tied largest losers split one fee',
  'Points For', 'no enforced season maximum',
  'no Skunk in the postseason', 'no Weekly Minimum in the postseason',
  '60 / 30 / 10', 'official third place', 'no commissioner override',
  'championship track',
]) {
  check(`states: ${required}`, rulesText.includes(required));
}

check('the Skunk fixture carries a fee and no maximum',
  SKUNK.feeCents === 1000 && SKUNK.seasonMaximumCents === undefined);
check('the settings row is Season-Opening Allocation',
  SETTINGS[0].label === 'Season-Opening Allocation', SETTINGS[0].label);
check('Pools are described as open to every member postseason',
  /every league member keeps entering them/.test(rulesText));
check('the Skunk winner is the Points For leader, not the champion',
  /highest cumulative Yahoo regular-season Points For/.test(rulesText)
  && /not the best record, not the champion, not a seed/.test(rulesText));

/* ── K · Wrap Up — §16 ───────────────────────────────────────────────────── */

section('K · Wrap Up keeps its shape and loses the arrow');

check('the bets heading carries no directional arrow',
  !BETS_HEADING.includes('↕'), BETS_HEADING);
// UIRECON WAVE 4B — the viewport treatment IS the whole heading now. `4 SHOWN`
// named a cap that a one-card carousel makes meaningless; `SWIPE` names what a
// GM does, and all three Wrap sections say it the same way.
check('and still states the viewport treatment',
  BETS_HEADING === 'FANTASYSTAKES MATCHUPS · SWIPE', BETS_HEADING);

unbindAll();

/* ── helpers ─────────────────────────────────────────────────────────────── */

function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/^\s*\/\/.*$/gm, ' ');
}

/**
 * One module's own source, for the STRUCTURAL claims.
 *
 * A few properties here are about what a module CANNOT do rather than what it
 * does — `versus-model.js` cannot infer eligibility from a week because it
 * never imports one, and `counter-stake.js` cannot clamp because it contains no
 * clamp. Those are checkable only against the text.
 */
function readSource(name) {
  return readFileSync(new URL(`../js/${name}`, import.meta.url), 'utf8');
}
function versusModelSource() { return readSource('versus-model.js'); }
function counterStakeSource() { return readSource('counter-stake.js'); }
function leagueSource() { return readSource('league.js'); }
function actionSource() { return readSource('action.js'); }
function ledgerSource() { return readSource('ledger.js'); }
function weekSource() { return readSource('week.js'); }

/* ── Result ──────────────────────────────────────────────────────────────── */

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`${failures.length} ASSERTION(S) FAILED`);
  failures.forEach((f) => console.log(`  · ${f}`));
  process.exit(1);
}
console.log('All assertions PASSED');
