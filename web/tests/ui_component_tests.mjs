/* ============================================================================
 * FantasyStakes — Sprint 7 Package 1 · behavioural UI tests
 *
 * Run directly:   node web/tests/ui_component_tests.mjs
 * Or through the repository suite:   python test_s7_p1_ui_shell.py
 *
 * Assertions print in the repository's `[PASS]` / `[FAIL]` style and the
 * process exits non-zero on any failure.
 *
 * These tests drive the real modules the browser loads — no copies, no
 * reimplementations of the rules under test.
 * ========================================================================== */

import {
  MINUS,
  assertIntegerCents,
  creditsTone,
  exactCentsAttr,
  formatCredits,
  formatSignedCredits,
  isRoundedForDisplay,
  readExactCents,
  roundCentsToWholeDollars,
} from '../js/credits.js';

import {
  CREDITS_DISCLAIMER,
  PanelComposer,
  card,
  closeControl,
  countDisclaimers,
  creditsDisclaimer,
  equalZones,
  escapeHtml,
  rail,
  sectionHeading,
  sheet,
  summaryStrip,
  vSnapList,
} from '../js/components.js';

import {
  DEFAULT_DESTINATION_ID,
  NAV_DESTINATIONS,
  destinationById,
  selectDestination,
} from '../js/nav.js';

import { buildPanelContent } from '../js/shell.js';
import { ILLUSTRATIVE, LEAGUE_IDENTITY, MASTHEAD } from '../js/demo-state.js';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  const suffix = detail ? ` — ${detail}` : '';
  console.log(`  [${mark}] ${label}${suffix}`);
  if (!condition) failures.push(label);
}

function throws(fn) {
  try {
    fn();
    return false;
  } catch {
    return true;
  }
}

function section(title) {
  console.log(`\n${title}`);
}

/* ── Credits: rounding ──────────────────────────────────────────────────── */

section('Display rounding: exact cents to whole dollars, half away from zero');

const roundingVectors = [
  [0, 0],
  [1, 0],
  [49, 0],
  [50, 1],
  [51, 1],
  [99, 1],
  [100, 1],
  [149, 1],
  [150, 2],
  [12600, 126],
  [12649, 126],
  [12650, 127],
  [-49, 0],
  [-50, -1],
  [-149, -1],
  [-150, -2],
  [-9449, -94],
  [-9450, -95],
];

for (const [cents, dollars] of roundingVectors) {
  check(
    `${cents} cents rounds to ${dollars} dollars`,
    roundCentsToWholeDollars(cents) === dollars,
    `got ${roundCentsToWholeDollars(cents)}`,
  );
}

check(
  'rounding is symmetric about zero',
  roundingVectors.every(([c, d]) => roundCentsToWholeDollars(-c) === -d),
);

/* ── Credits: formatting ────────────────────────────────────────────────── */

section('Credit figures draw as whole dollars');

check('5500 cents draws as $55', formatCredits(5500) === '$55', formatCredits(5500));
check('12600 cents draws as $126', formatCredits(12600) === '$126', formatCredits(12600));
check('1000 cents draws as $10', formatCredits(1000) === '$10', formatCredits(1000));
check('6500 cents draws as $65', formatCredits(6500) === '$65', formatCredits(6500));
check(
  '12649 cents draws as $126 — the remainder is not shown',
  formatCredits(12649) === '$126',
  formatCredits(12649),
);
check(
  'no cents ever appear in a drawn Credit figure',
  roundingVectors.every(([c]) => !formatCredits(c).includes('.')),
);
check(
  'signed positive draws with a plus',
  formatSignedCredits(12600) === '+$126',
  formatSignedCredits(12600),
);
check(
  `negative draws with ${MINUS} (U+2212)`,
  formatSignedCredits(-9400) === `${MINUS}$94`,
  formatSignedCredits(-9400),
);
check('zero takes no sign', formatSignedCredits(0) === '$0', formatSignedCredits(0));
check(
  'an amount rounding to zero takes no sign',
  formatSignedCredits(-49) === '$0',
  formatSignedCredits(-49),
);
check(
  'thousands are grouped',
  formatCredits(123456) === '$1,235',
  formatCredits(123456),
);

section('Tone follows the drawn figure, not the exact one');
check('positive is green', creditsTone(12600) === 'is-positive');
check('negative is red', creditsTone(-9400) === 'is-negative');
check('exact zero is untinted', creditsTone(0) === '');
check('an amount that draws as $0 is untinted', creditsTone(-49) === '');

/* ── Credits: the exactness guarantee ───────────────────────────────────── */

section('Underlying accounting values stay exact');

check(
  'a fractional cent is rejected, not silently rounded',
  throws(() => formatCredits(100.5)),
);
check('NaN is rejected', throws(() => formatCredits(NaN)));
check('Infinity is rejected', throws(() => formatCredits(Infinity)));
check('a numeric string is rejected', throws(() => formatCredits('12600')));
check('null is rejected', throws(() => formatCredits(null)));
check('undefined is rejected', throws(() => formatCredits(undefined)));
check(
  'an unsafe integer is rejected',
  throws(() => formatCredits(Number.MAX_SAFE_INTEGER + 2)),
);
check('an exact integer passes through unchanged', assertIntegerCents(12649) === 12649);

const beforeFormat = 12649;
formatCredits(beforeFormat);
formatSignedCredits(beforeFormat);
roundCentsToWholeDollars(beforeFormat);
check(
  'formatting does not mutate the value it was given',
  beforeFormat === 12649,
  `got ${beforeFormat}`,
);

check(
  'the exact value rides along with the drawn figure',
  exactCentsAttr(12649) === ' data-exact-cents="12649"',
  exactCentsAttr(12649),
);
check(
  'the exact value reads back as the original integer',
  readExactCents({ getAttribute: () => '12649' }) === 12649,
);
check(
  'a corrupted exact value is rejected on read-back',
  throws(() => readExactCents({ getAttribute: () => '126.49' })),
);
check('a missing exact value is rejected on read-back',
  throws(() => readExactCents({ getAttribute: () => null })));
check('rounding is disclosable', isRoundedForDisplay(12649) === true);
check('an exact dollar amount is not flagged as rounded', isRoundedForDisplay(12600) === false);

/* ── Four-cell strip ────────────────────────────────────────────────────── */

section('The four-cell summary strip is one shared component');

const fourCells = [
  { label: 'Wallet', cents: 5500 },
  { label: 'Available', cents: 6500, anchor: true },
  { label: 'In Play', pending: true },
  { label: 'Weekly Min Left', cents: 1000 },
];
const stripHtml = summaryStrip({ cells: fourCells });

check(
  'a strip renders exactly four cells',
  (stripHtml.match(/class="fs-strip__cell/g) || []).length === 4,
);
check('three cells is a construction error',
  throws(() => summaryStrip({ cells: fourCells.slice(0, 3) })));
check('five cells is a construction error',
  throws(() => summaryStrip({ cells: [...fourCells, { label: 'Extra' }] })));
check('a missing cells array is a construction error',
  throws(() => summaryStrip({})));
check(
  'at most one cell may carry the anchor or gold treatment',
  throws(() => summaryStrip({
    cells: [
      { label: 'A', anchor: true },
      { label: 'B', gold: true },
      { label: 'C' },
      { label: 'D' },
    ],
  })),
);
check(
  'strip money cells carry their exact cents',
  stripHtml.includes('data-exact-cents="5500"') &&
  stripHtml.includes('data-exact-cents="6500"') &&
  stripHtml.includes('data-exact-cents="1000"'),
);
check(
  'strip money cells draw whole dollars and no cents',
  stripHtml.includes('>$55<') && stripHtml.includes('>$65<') &&
  !/\$\d+\.\d/.test(stripHtml),
);
check('the strip is icon-free', !/<svg|<img/i.test(stripHtml));
check(
  'an unresolved cell draws as unresolved rather than as a figure',
  stripHtml.includes('is-pending') && stripHtml.includes('—'),
);
check(
  'rank context is rendered as context, not as a second figure',
  summaryStrip({
    cells: [
      { label: 'Net Winnings', cents: 12600, signed: true, context: '1st' },
      { label: 'B' }, { label: 'C' }, { label: 'D' },
    ],
  }).includes('fs-strip__context'),
);
check(
  'cell content is escaped',
  summaryStrip({
    cells: [
      { label: '<script>x</script>', text: '&' },
      { label: 'B' }, { label: 'C' }, { label: 'D' },
    ],
  }).includes('&lt;script&gt;'),
);
check(
  'a fractional-cent strip value is rejected',
  throws(() => summaryStrip({
    cells: [{ label: 'A', cents: 55.5 }, { label: 'B' }, { label: 'C' }, { label: 'D' }],
  })),
);

/* ── Credits disclaimer ─────────────────────────────────────────────────── */

section('Credits disclaimer');

check(
  'the disclaimer string is exactly the approved wording',
  CREDITS_DISCLAIMER === 'VIRTUAL CREDITS · $ IS DISPLAY ONLY · NO CASH VALUE',
  CREDITS_DISCLAIMER,
);
check(
  'the rendered disclaimer carries that string verbatim',
  creditsDisclaimer().includes(CREDITS_DISCLAIMER),
);
check('the disclaimer is not sanitised of the $ symbol', CREDITS_DISCLAIMER.includes('$'));

const composer = new PanelComposer('league');
composer.addStrip({ cells: fourCells });
composer.addDisclaimer();
check('a tab may carry one disclaimer', countDisclaimers(composer.toHTML()) === 1);
check('a second disclaimer on the same tab is refused', throws(() => composer.addDisclaimer()));
check(
  'a disclaimer with no strip above it is refused',
  throws(() => new PanelComposer('rules').addDisclaimer()),
);
check(
  'the disclaimer follows its strip in document order',
  composer.toHTML().indexOf('fs-strip') < composer.toHTML().indexOf('fs-disclaimer'),
);

/* ── Sheet and close control ────────────────────────────────────────────── */

section('Pop-out sheet and the universal close control');

const sheetHtml = sheet({ title: 'The Sheet', sub: 'Reconciliation', body: '<p>x</p>' });

check('the sheet carries a close control', sheetHtml.includes('fs-sheet__close'));
check(
  'the close control is the first element in the sheet',
  sheetHtml.indexOf('fs-sheet__close') < sheetHtml.indexOf('fs-sheet__title'),
);
check('the close control is a real button', closeControl().startsWith('<button'));
check('the close control is labelled for assistive tech',
  closeControl().includes('aria-label="Close"'));
check('the close control is addressable by the shared handler',
  closeControl().includes('data-fs-close'));
check('sheet titles are escaped',
  sheet({ title: '<b>x</b>' }).includes('&lt;b&gt;'));

/* ── Other shared primitives ────────────────────────────────────────────── */

section('Shared primitives');

check('the rail scroll-snaps horizontally', rail(['<div>a</div>']).includes('fs-rail'));
check('rail items are snap targets', rail(['<div>a</div>']).includes('fs-rail__item'));
check('the vertical list snaps', vSnapList(['<div>a</div>']).includes('fs-vsnap__item'));
check('equal zones wrap each child', (equalZones(['a', 'b']).match(/fs-zone"/g) || []).length === 2);
check('cards render', card('body').includes('fs-card'));
check('section headings render their helper', sectionHeading('BIG BOARD', "this week's action")
  .includes('fs-heading__helper'));
check('heading text is escaped', sectionHeading('<i>x</i>').includes('&lt;i&gt;'));
check('escapeHtml handles quotes', escapeHtml('"a"') === '&quot;a&quot;');

/* ── Navigation ─────────────────────────────────────────────────────────── */

section('Navigation — five destinations, POR order');

check('there are exactly five primary destinations', NAV_DESTINATIONS.length === 5);
check(
  'the order is League · Action · Ledger · The Week · Rules & Settings',
  NAV_DESTINATIONS.map((d) => d.label).join(' · ') ===
    'League · Action · Ledger · The Week · Rules & Settings',
  NAV_DESTINATIONS.map((d) => d.label).join(' · '),
);
check('no Wrap Up label survives in the navigation',
  !NAV_DESTINATIONS.some((d) => /wrap/i.test(d.label)));
check('there is no My Team primary tab',
  !NAV_DESTINATIONS.some((d) => /my team/i.test(d.label)));
check('every destination has a unique panel',
  new Set(NAV_DESTINATIONS.map((d) => d.panelId)).size === 5);
check('every destination carries an inline SVG icon and no emoji',
  NAV_DESTINATIONS.every((d) => /<(path|rect)/.test(d.icon)));
check('the default destination is League', DEFAULT_DESTINATION_ID === 'league');

for (const d of NAV_DESTINATIONS) {
  const state = selectDestination(d.id);
  check(
    `selecting ${d.label} activates exactly that destination`,
    state.filter((s) => s.active).length === 1 &&
    state.find((s) => s.active).id === d.id,
  );
}
check('an unknown destination throws rather than blanking the app',
  throws(() => selectDestination('my-team')));
check('destinationById validates', throws(() => destinationById('nope')));

/* ── Panel composition ──────────────────────────────────────────────────── */

section('Every destination builds a panel');

for (const d of NAV_DESTINATIONS) {
  let html = '';
  const built = !throws(() => { html = buildPanelContent(d.id); });
  check(`${d.label} builds`, built && html.length > 0);
  check(
    `${d.label} carries at most one Credits disclaimer`,
    countDisclaimers(html) <= 1,
    `count ${countDisclaimers(html)}`,
  );
}

const leagueHtml = buildPanelContent('league');
check(
  'League draws the POR figures as whole dollars',
  leagueHtml.includes('+$126') && leagueHtml.includes('$55') &&
  leagueHtml.includes('$10') && leagueHtml.includes('$65'),
);
check(
  'League keeps the exact cents behind those figures',
  leagueHtml.includes('data-exact-cents="12600"') &&
  leagueHtml.includes('data-exact-cents="5500"') &&
  leagueHtml.includes('data-exact-cents="1000"') &&
  leagueHtml.includes('data-exact-cents="6500"'),
);
check('League cell 1 carries no win/loss record',
  !/\d+\s*[-–]\s*\d+/.test(leagueHtml.split('fs-strip__label')[1] || ''));
check('League carries the disclaimer once', countDisclaimers(leagueHtml) === 1);
check('Action carries the disclaimer once', countDisclaimers(buildPanelContent('action')) === 1);
check('Ledger carries the disclaimer once', countDisclaimers(buildPanelContent('ledger')) === 1);
check(
  'Rules & Settings summarises no position, so carries no disclaimer',
  countDisclaimers(buildPanelContent('rules')) === 0,
);
check(
  'Ledger marks Current Settle as the gold cell',
  buildPanelContent('ledger').includes('is-gold'),
);
check(
  'unresolved figures are drawn as unresolved, not invented',
  buildPanelContent('action').includes('is-pending'),
);

/* ── Rev4.2 locked global copy ──────────────────────────────────────────── */

section('Rev4.2 locked global copy');

check(
  'the tagline is FANTASY LEAGUES · VIRTUAL STAKES',
  MASTHEAD.tagline === 'FANTASY LEAGUES · VIRTUAL STAKES',
  MASTHEAD.tagline,
);
check('the superseded Rev4.1 tagline is gone',
  !MASTHEAD.tagline.includes('OUR THING'));
check(
  'the league identity is the league name alone',
  LEAGUE_IDENTITY.name === 'CULV APPRECIATION SOCIETY',
  LEAGUE_IDENTITY.name,
);
check('the superseded Fantasy Sportsbook suffix is gone',
  !JSON.stringify(LEAGUE_IDENTITY).includes('Fantasy Sportsbook'));
check('the masthead identifies the build as Rev 4.2',
  MASTHEAD.revision.includes('Rev 4.2'));
check(
  'illustrative money is held as exact integer cents',
  [
    ILLUSTRATIVE.netWinningsCents,
    ILLUSTRATIVE.walletCents,
    ILLUSTRATIVE.weeklyMinLeftCents,
    ILLUSTRATIVE.availableCents,
  ].every((c) => Number.isSafeInteger(c)),
);

/* ── Result ─────────────────────────────────────────────────────────────── */

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`FAILED: ${failures.length} assertion(s)`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
} else {
  console.log('All assertions PASSED');
}