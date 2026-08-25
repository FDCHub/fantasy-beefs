/* ============================================================================
 * FantasyStakes — Sprint A3.2 · owner-ruling alignment · component tests
 *
 * Run directly:   node web/tests/a32_owner_ruling_component_tests.mjs
 *
 * Three owner rulings landed in the presentation layer, and each one is the
 * kind that a source-level grep can appear to satisfy while the rendered
 * surface still gets it wrong. So the shipped modules are executed and their
 * real markup is asserted:
 *
 *   1. the Grand Champion tiebreak is EXPLAINED where it decided a title, and
 *      is silent everywhere else — including where a tie survived unbroken
 *   2. the explanations are SHORT, and say what the Championship Score is
 *      without ever implying a wallet balance counts
 *   3. the economy surface reports the league's OWN FantasyStakes contribution
 *      out of the authoritative allocation read, not a module constant
 *
 * THE FRONTEND DOES NO COMPETITIVE ARITHMETIC. The last section proves it by
 * feeding the renderer a server payload whose champion contradicts the points
 * on screen, and asserting the screen still names the server's champion. A
 * client that recomputed would "fix" it, and that is precisely the failure.
 *
 * NO DOM AND NO SERVER.
 * ========================================================================== */

import {
  grandChampionSection,
  seasonResultsSection,
} from '../js/season-results.js';

const failures = [];

function check(label, ok, detail = '') {
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${label}${detail ? ` - ${detail}` : ''}`);
  if (!ok) failures.push(label);
}

const nameFor = (id) => `GM ${id}`;

/** A results payload shaped like `/championship/results` answers it. */
function results(standing) {
  return {
    lifecycle: 'PAID',
    grand_champion: standing,
  };
}

/* The owner's worked example, as the server reports it: level on points, and
   the Championship Score separated them. */
const DECIDED = {
  rows: [
    { team_id: 1, yahoo_points: '2', fantasystakes_points: '3',
      combined_points: '5', fantasystakes_score_cents: 8400 },
    { team_id: 2, yahoo_points: '3', fantasystakes_points: '2',
      combined_points: '5', fantasystakes_score_cents: 6300 },
  ],
  champion_team_ids: [1],
  co_champions: false,
  tiebreak_used: true,
};

/* Level on points AND level on score — a real co-championship. */
const UNBROKEN = {
  rows: [
    { team_id: 1, yahoo_points: '2', fantasystakes_points: '3',
      combined_points: '5', fantasystakes_score_cents: 8400 },
    { team_id: 2, yahoo_points: '3', fantasystakes_points: '2',
      combined_points: '5', fantasystakes_score_cents: 8400 },
  ],
  champion_team_ids: [1, 2],
  co_champions: true,
  tiebreak_used: false,
};

/* Nobody level: the tiebreak was never reached. */
const CLEAR = {
  rows: [
    { team_id: 1, yahoo_points: '3', fantasystakes_points: '3',
      combined_points: '6', fantasystakes_score_cents: 0 },
    { team_id: 2, yahoo_points: '2', fantasystakes_points: '2',
      combined_points: '4', fantasystakes_score_cents: 999999 },
  ],
  champion_team_ids: [1],
  co_champions: false,
  tiebreak_used: false,
};

/* ── 1 · the tiebreak is explained exactly when it decided something ─────── */

console.log('\nA32-1 - the Grand Champion tiebreak explains itself, once');

const decided = grandChampionSection(results(DECIDED), nameFor);
check('a decided tiebreak is explained on the results surface',
      decided.includes('Tiebreak: Championship Score'));
check('and it names the WINNER\'s Championship Score, signed',
      decided.includes('+$84'), decided.match(/Tiebreak[^<]*/));
check('the runner-up\'s score is not presented as the tiebreak',
      !decided.includes('+$63'));
check('the decided title is singular',
      decided.includes('Grand Champion') && !decided.includes('Co-Grand Champions'));

const unbroken = grandChampionSection(results(UNBROKEN), nameFor);
check('a tie the score did NOT break shows no tiebreak line',
      !unbroken.includes('Tiebreak:'));
check('and is presented as a co-championship',
      unbroken.includes('Co-Grand Champions'));
check('both co-champions are named',
      unbroken.includes('GM 1') && unbroken.includes('GM 2'));
check('the co-champion outcome is stated in the explanation',
      unbroken.includes('Still tied = co-Grand Champions.'));

const clear = grandChampionSection(results(CLEAR), nameFor);
check('an outright winner shows no tiebreak line',
      !clear.includes('Tiebreak:'));
check('and the lowest Championship Score still wins on points',
      clear.includes('GM 1') && !clear.includes('Co-Grand Champions'));
check('the tiebreak is never mentioned as having applied',
      !clear.includes('Tiebreak:') && !unbroken.includes('Tiebreak:'));

/* ── 2 · the explanations are short, and say the right thing ─────────────── */

console.log('\nA32-2 - the explanations are brief and cannot be misread');

const GC_NOTE = 'Yahoo + FantasyStakes finishes: 1st = 3 pts, 2nd = 2, 3rd = 1. '
  + 'Highest total wins. Ties go to the higher FantasyStakes Championship Score.';
check('the Grand Champion rule is stated in one short note',
      decided.includes(GC_NOTE));
check('and that note is under 200 characters',
      GC_NOTE.length < 200, `${GC_NOTE.length} chars`);
check('the tiebreak rule is stated even before a tie happens',
      clear.includes('Ties go to the higher FantasyStakes Championship Score.'));

/* The standings explainer is assembled inside standings.js from the lifecycle
   and is not exported, so the SHIPPED copy is read out of the module source.
   Asserting a re-declared copy here would pass while the screen said anything
   at all. */
const fs = await import('node:fs/promises');
const standingsSource = await fs.readFile(
  new URL('../js/standings.js', import.meta.url), 'utf-8');
const EXPLAINER = 'Championship Score is your net winnings from FantasyStakes '
  + 'matchups and prop pools. Highest score wins. Wallet balance does not count.';
check('the shipped standings explainer is exactly the ruled sentence',
      standingsSource.includes("'Championship Score is your net winnings from FantasyStakes '")
      && standingsSource.includes("'matchups and prop pools. Highest score wins. "
                                  + "Wallet balance does not count.'"));
check('and it is brief - under 200 characters',
      EXPLAINER.length < 200, `${EXPLAINER.length} chars`);
check('it says the score is NET WINNINGS, not a balance',
      EXPLAINER.includes('net winnings')
      && EXPLAINER.includes('Wallet balance does not count'));
check('it names both competition surfaces that feed the score',
      EXPLAINER.includes('matchups') && EXPLAINER.includes('prop pools'));
for (const [state, suffix] of [['PAID', 'Pot paid.'],
                               ['FINAL', 'Scoring closed.'],
                               ['FROZEN', 'postseason play no longer changes it.']]) {
  check(`the ${state} state appends a short lifecycle clause`,
        standingsSource.includes(suffix), suffix);
}
check('no lifecycle branch restates the whole rule',
      (standingsSource.match(/net winnings from FantasyStakes/g) || []).length === 1);

/* ── 3 · the frontend performs NO competitive Grand Champion arithmetic ──── */

console.log('\nA32-3 - the client renders the server\'s decision, never its own');

/* The server says GM 2 won. The points on screen say GM 1 leads. A client that
   recomputed would name GM 1 — which is the defect this asserts against. */
const CONTRADICTORY = {
  rows: [
    { team_id: 1, yahoo_points: '3', fantasystakes_points: '3',
      combined_points: '6', fantasystakes_score_cents: 100 },
    { team_id: 2, yahoo_points: '1', fantasystakes_points: '1',
      combined_points: '2', fantasystakes_score_cents: 100 },
  ],
  champion_team_ids: [2],
  co_champions: false,
  tiebreak_used: false,
};
const obeyed = grandChampionSection(results(CONTRADICTORY), nameFor);
/* Only the champion ELEMENT is inspected: the table below it legitimately
   lists every GM, so a loose window would find 'GM 1' and prove nothing. */
const winnerLine = (/class="fs-sr__winner"[^>]*>([\s\S]*?)<\/[a-z]+>/
  .exec(obeyed) || [])[1] || '';
check('the champion element was found',
      winnerLine.length > 0, JSON.stringify(winnerLine));
check('the server\'s champion is named even when the points contradict it',
      winnerLine.includes('GM 2'), winnerLine.replace(/<[^>]*>/g, ' ').trim());
check('the client did not promote the higher-points GM to champion',
      !winnerLine.includes('GM 1'));

/* Exact server Fractions must survive to the screen unrounded. */
const FRACTIONAL = {
  rows: [
    { team_id: 1, yahoo_points: '5/2', fantasystakes_points: '3',
      combined_points: '11/2', fantasystakes_score_cents: 100 },
    { team_id: 2, yahoo_points: '5/2', fantasystakes_points: '0',
      combined_points: '5/2', fantasystakes_score_cents: 100 },
  ],
  champion_team_ids: [1],
  co_champions: false,
  tiebreak_used: false,
};
const frac = grandChampionSection(results(FRACTIONAL), nameFor);
check('exact fractional points are rendered as sent',
      frac.includes('11/2') && frac.includes('5/2'));
check('and are never converted to a decimal',
      !frac.includes('5.5') && !frac.includes('2.5'));

/* The renderer must not contain the scoring table at all. */
const source = await fs.readFile(
  new URL('../js/season-results.js', import.meta.url), 'utf-8');
for (const forbidden of ['=== 1 ? 3', '? 3 :', 'POINTS_FOR_PLACE', '3 : 2 : 1']) {
  check(`the renderer contains no scoring table (${forbidden})`,
        !source.includes(forbidden));
}
check('the renderer never sums the two component point columns',
      !/yahoo_points\s*\+\s*\w*fantasystakes_points/.test(source)
      && !/Number\(\s*\w*\.yahoo_points/.test(source));
check('and never compares Championship Scores to pick a winner',
      !/fantasystakes_score_cents\s*[><]/.test(source));
check('the champion comes only from the server field',
      source.includes('champion_team_ids'));

/* ── 4 · the whole section renders without throwing on partial data ──────── */

console.log('\nA32-4 - degraded payloads degrade, they do not crash');

for (const [label, payload] of [
  ['no grand champion yet', { lifecycle: 'FROZEN' }],
  ['champion with no scores', { lifecycle: 'PAID', grand_champion: {
    rows: [{ team_id: 1, yahoo_points: '3', fantasystakes_points: '3',
             combined_points: '6', fantasystakes_score_cents: null }],
    champion_team_ids: [1], co_champions: false, tiebreak_used: false } }],
  ['tiebreak_used with a missing score', { lifecycle: 'PAID', grand_champion: {
    rows: [{ team_id: 1, yahoo_points: '3', fantasystakes_points: '3',
             combined_points: '6', fantasystakes_score_cents: null }],
    champion_team_ids: [1], co_champions: false, tiebreak_used: true } }],
]) {
  let html = null;
  let threw = null;
  try {
    html = seasonResultsSection(payload, nameFor);
  } catch (error) {
    threw = error;
  }
  check(`${label}: renders without throwing`, threw === null,
        threw ? String(threw.message) : '');
  if (label === 'tiebreak_used with a missing score') {
    check('an unexplainable tiebreak is omitted rather than half-stated',
          html !== null && !html.includes('Tiebreak:'));
  }
}

/* ── 5 · the FantasyStakes contribution row is SERVED, not blank ─────────── */

console.log('\nA32-5 - the economy panel reports the league\'s own contribution');

const econ = await import('../js/economy-model.js');
const settings = await import('../js/settings-model.js');

const FS_ROW = { field: 'fantasystakes_championship_contribution_cents' };
const TOTAL_ROW = { field: 'season_opening_allocation_per_player_cents' };
const RESERVE_ROW = { field: 'weekly_minimum_reserve_per_player_cents' };
const LEAGUE_ROW = { field: 'league_opening_allocation_cents' };

check('unbound, the contribution row reports missing rather than guessing',
      econ.derivedValue(FS_ROW) === null);

/* The certified base economy, exactly as `/settings` serves it. It has no
   field for the FantasyStakes contribution — that is the defect A3 found. */
econ.bindEconomy({
  regular_season_week_count: 14,
  weekly_minimum_reserve_per_player_cents: 14000,
  championship_reserve_per_player_cents: 8000,
  season_opening_allocation_per_player_cents: 22000,
  league_opening_allocation_cents: 220000,
  active_team_count: 10,
  frozen: false,
});
check('with only /settings bound, the base total is still the certified 220',
      econ.derivedValue(TOTAL_ROW) === 22000, String(econ.derivedValue(TOTAL_ROW)));
check('and the contribution row is honestly blank, not zero',
      econ.derivedValue(FS_ROW) === null, String(econ.derivedValue(FS_ROW)));

/* Now the authoritative championship allocation lands. */
settings.bindChampionshipAllocation({
  weekly_play_reserve_cents: 14000,
  yahoo_championship_contribution_cents: 8000,
  fantasystakes_championship_contribution_cents: 8000,
  season_opening_allocation_cents: 30000,
});
check('the contribution row is populated from the authoritative read',
      econ.derivedValue(FS_ROW) === 8000, String(econ.derivedValue(FS_ROW)));
check('and the allocation row becomes the full three-part total',
      econ.derivedValue(TOTAL_ROW) === 30000, String(econ.derivedValue(TOTAL_ROW)));

/* A DIFFERENT league must produce different numbers — the A3 defect was one
   league's figure shown to every league. */
settings.bindChampionshipAllocation({
  weekly_play_reserve_cents: 13000,
  yahoo_championship_contribution_cents: 8000,
  fantasystakes_championship_contribution_cents: 5000,
  season_opening_allocation_cents: 26000,
});
check('a different league reports its own contribution',
      econ.derivedValue(FS_ROW) === 5000, String(econ.derivedValue(FS_ROW)));
check('and its own allocation total',
      econ.derivedValue(TOTAL_ROW) === 26000, String(econ.derivedValue(TOTAL_ROW)));

/* Nothing else moved. */
check('the weekly reserve row is untouched by the override',
      econ.derivedValue(RESERVE_ROW) === 14000, String(econ.derivedValue(RESERVE_ROW)));
check('the league allocation total is untouched by the override',
      econ.derivedValue(LEAGUE_ROW) === 220000, String(econ.derivedValue(LEAGUE_ROW)));
check('the served week count is untouched by the override',
      econ.derivedValue({ field: 'regular_season_week_count' }) === 14);

/* And the panel draws it. */
const economyView = await import('../js/economy.js');
check('economy.js still loads with the model change',
      typeof economyView.economySheet === 'function');
const sheetBody = economyView.economySheet().body;
check('and its panel draws the contribution row',
      sheetBody.includes(
        'data-derived="fantasystakes_championship_contribution_cents"'));
/** The one `fs-econ__row` element carrying this field, and nothing after it. */
function drawnRowFor(field) {
  const at = sheetBody.indexOf(`data-derived="${field}"`);
  if (at < 0) return '';
  const end = sheetBody.indexOf('</div>', at);
  return end < 0 ? '' : sheetBody.slice(at, end);
}

const drawnRow = drawnRowFor('fantasystakes_championship_contribution_cents');
check('the drawn contribution is the served figure, not a dash',
      drawnRow.includes('$50') && !drawnRow.includes('fs-econ__pending'),
      drawnRow.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim());
const drawnTotal = drawnRowFor('season_opening_allocation_per_player_cents');
check('and the allocation row draws the full three-part total',
      drawnTotal.includes('$260'),
      drawnTotal.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim());

const economySource = await fs.readFile(
  new URL('../js/economy-model.js', import.meta.url), 'utf-8');
const codeOnly = economySource.replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '');
check('the model still contains no arithmetic operator',
      !codeOnly.includes('*') && !codeOnly.includes(' + ')
      && !/\d\s*[-/]\s*\d/.test(codeOnly));

/* ── report ─────────────────────────────────────────────────────────────── */

console.log(`\n${'='.repeat(64)}`);
if (failures.length) {
  console.log(`FAILED: ${failures.length} assertion(s)`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
console.log('PASS: A3.2 owner-ruling alignment component tests');
