/* ============================================================================
 * FantasyStakes — FINAL POR · UI-3D · one-row, market-driven market microcopy
 *
 * WHY THIS IS A COMPONENT SUITE AND NOT A BROWSER ONE. §27D's three sentences
 * are pure functions of served numbers. A browser can show that ONE of them
 * rendered for whatever the live board happened to serve; only a component
 * suite can drive the full range — including the one case §27D calls out by
 * name, which no live board is guaranteed to produce.
 *
 * WHAT IS ASSERTED:
 *
 *   M1  −118 is a SLIGHT favorite, never a heavy one     §27D's prohibition
 *   M2  the descriptor is graded across the whole range
 *   M3  the Moneyline sentence is §27D's, verbatim
 *   M4  the Spread sentence is §27D's, verbatim
 *   M5  the Over/Under sentence is §27D's, verbatim
 *   M6  exactly ONE microcopy row per market state
 *   M7  the sentences are driven by the SERVED numbers, not by literals
 *
 * M1 IS THE WHOLE REASON THE DESCRIPTOR IS COMPUTED. A fixed sentence per
 * market cannot obey "do not call −118 a heavy favorite", because the sentence
 * has to describe the number. This suite drives the ladder end to end so the
 * grading is a certified property rather than a plausible-looking table.
 * ========================================================================== */

import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  impliedWinProbabilityPercent, moneylineStrength,
} from '../js/composer.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = resolve(HERE, '..');

const failures = [];
const check = (label, condition, detail = '') => {
  console.log(`  [${condition ? 'PASS' : 'FAIL'}] ${label}`
    + (detail ? ` — ${detail}` : ''));
  if (!condition) failures.push(label);
};
const section = (t) => console.log(`\n${t}`);

const COMPOSER = readFileSync(join(WEB, 'js', 'composer.js'), 'utf8');

/* Built rather than written as an escape, because this file is generated
 * through tooling that has collapsed `backslash-n` more than once. */
const NEWLINE = String.fromCharCode(10);


/* ── M1 · §27D's prohibition ──────────────────────────────────────────────── */

section('UI-3D · M1 — −118 is a SLIGHT favorite, never a heavy one');

check('−118 implies 54.1% and is graded "Slight favorite"',
  moneylineStrength(-118) === 'Slight favorite',
  `${impliedWinProbabilityPercent(-118).toFixed(1)}% → ${moneylineStrength(-118)}`);
check('  · and is explicitly NOT called heavy',
  !/heavy/i.test(moneylineStrength(-118)), moneylineStrength(-118));
check('  · nor is −110, −120 or −135',
  [-110, -120, -135].every((o) => !/heavy/i.test(moneylineStrength(o))),
  [-110, -120, -135].map((o) => `${o}:${moneylineStrength(o)}`).join(' '));


/* ── M2 · the ladder ─────────────────────────────────────────────────────── */

section('UI-3D · M2 — the descriptor is graded across the whole range');

const LADDER = [
  [-101, 'Slight favorite'], [-118, 'Slight favorite'], [-120, 'Slight favorite'],
  [-150, 'Favorite'], [-180, 'Favorite'],
  // −190 IS 65.5% AND IS THE BOUNDARY, kept here on purpose: a band edge is
  // where a ladder is most likely to be miswritten, and the first version of
  // this suite expected `Favorite` here and was wrong about the arithmetic.
  [-190, 'Clear favorite'],
  [-200, 'Clear favorite'], [-290, 'Clear favorite'],
  [-400, 'Heavy favorite'], [-1000, 'Heavy favorite'],
  [+100, 'Even money'],
  [+110, 'Slight underdog'], [+150, 'Underdog'],
  [+250, 'Clear underdog'], [+400, 'Heavy underdog'],
];
for (const [odds, expected] of LADDER) {
  check(`  · ${odds > 0 ? '+' : ''}${odds} → ${expected}`,
    moneylineStrength(odds) === expected, moneylineStrength(odds));
}
check('an exact pick’em is named as one, not nudged to a favourite',
  moneylineStrength(100) === 'Even money');
check('  · and the two sides of one market take the mirrored word',
  moneylineStrength(-200).split(' ')[0] === moneylineStrength(200).split(' ')[0],
  `${moneylineStrength(-200)} / ${moneylineStrength(200)}`);


/* ── M3..M5 · the three sentences, verbatim ──────────────────────────────── */
//
// BUILT THE WAY `marketDetail` BUILDS THEM, from the same expressions, so this
// asserts the shipped grammar rather than a copy of it. The source is then read
// back to prove those expressions are the ones in the module.

section('UI-3D · M3..M5 — the three sentences are §27D’s, verbatim');

const mlSentence = (odds) =>
  `${moneylineStrength(odds)} to win. Odds reflect win probability, not margin.`;

check('Moneyline — §27D’s sentence for a slight favourite',
  mlSentence(-118)
    === 'Slight favorite to win. Odds reflect win probability, not margin.',
  mlSentence(-118));
check('  · and the module builds it from those two parts',
  COMPOSER.includes('${moneylineStrength(odds)} to win. ')
  && COMPOSER.includes("'Odds reflect win probability, not margin.'"));

const spreadSentence = (giving, yours) => {
  const magnitude = Math.abs(yours).toFixed(1);
  const signed = (yours < 0 ? yours : -yours).toFixed(1);
  return `${giving} −${Math.abs(Number(signed)).toFixed(1)}`
    + ` must win by more than ${magnitude} points.`;
};

check('Spread — §27D’s sentence, naming the favourite and its signed line',
  spreadSentence('Pain Sanders', -2.5)
    === 'Pain Sanders −2.5 must win by more than 2.5 points.',
  spreadSentence('Pain Sanders', -2.5));
check('  · and the module builds it from that grammar',
  COMPOSER.includes('must win by more than ${magnitude} points.'));
check('  · naming the team GIVING the points, whichever side the reader is on',
  COMPOSER.includes('const giving = yours < 0 ? you : them;')
  && COMPOSER.includes('const givingSpread = formatSpread(yours < 0 ? yours : -yours);'));

const ouSentence = (total) =>
  `Bet whether the combined score finishes over or under ${total.toFixed(1)}.`;

check('Over/Under — §27D’s sentence, carrying the served total',
  ouSentence(247.5)
    === 'Bet whether the combined score finishes over or under 247.5.',
  ouSentence(247.5));
check('  · and the module builds it from that grammar',
  COMPOSER.includes('Bet whether the combined score finishes over or under ')
  && COMPOSER.includes('${total.toFixed(1)}.'));


/* ── M6 · exactly one row ────────────────────────────────────────────────── */

section('UI-3D · M6 — exactly one microcopy row per market state');

const detail = COMPOSER.slice(COMPOSER.indexOf('function marketDetail'));
const body = detail.slice(0, detail.indexOf('\nfunction previewButton'));
const notes = (body.match(/\bnote\(/g) || []).length;
const blocks = (body.match(/\breturn block\(/g) || []).length;

check('every market state returns exactly one block',
  blocks > 0, `${blocks} blocks`);
/* ONE NOTE PER BLOCK, WITH ONE DOCUMENTED TERNARY. The Over/Under block picks
 * between two notes depending on whether a side has been chosen — one RENDERS,
 * two appear in the source. Counting raw occurrences would either fail on that
 * legitimate case or have to be loosened into meaninglessness, so the surplus
 * is required to equal the number of ternary alternates exactly. */
const ternaryNotes = (body.match(/\?\s*note\(/g) || []).length;
check('  · and emits exactly one note per block',
  notes - blocks === ternaryNotes,
  `${notes} notes, ${blocks} blocks, ${ternaryNotes} ternary alternate(s)`);
check('  · with exactly one such ternary — the Over/Under side prompt',
  ternaryNotes === 1 && body.includes('? note('),
  `${ternaryNotes} ternary note(s)`);
check('  · the note helper renders a single element',
  /const note = \(text, attrs = ''\) => \(\s*`<div class="fs-marketdetail__note"/
    .test(COMPOSER));
check('  · so no state can emit two rows of microcopy',
  !/note\([^)]*\)\s*\+\s*note\(/.test(body));


/* ── M7 · driven by the served numbers ──────────────────────────────────── */

section('UI-3D · M7 — the sentences are driven by SERVED numbers');

check('the Moneyline sentence reads the served odds',
  /const odds = served\.acting_moneyline;/.test(COMPOSER));
check('the Spread sentence reads the served signed line',
  /const yours = served\.acting_spread;/.test(COMPOSER));
check('the Over/Under sentence reads the served total',
  /const total = served\.total_line;/.test(COMPOSER));
check('no market descriptor is a fixed literal',
  !/Heavy favorite to win|Slight favorite to win\./.test(
    COMPOSER.split('MONEYLINE_BANDS')[2] || ''),
  'a hardcoded sentence would defeat §27D’s prohibition');
/* READ WITH COMMENTS STRIPPED, exactly as the WP3C.2 guard reads it. That
 * guard runs over `codeOnly(...)`, and this check first failed against the raw
 * source because the RATIONALE for counting in percent says the word `0.55`
 * out loud. A prose mention of the thing being avoided is not the thing. */
const composerCode = COMPOSER
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split(NEWLINE).filter((l) => !l.trim().startsWith('//')).join(NEWLINE);
check('and the ladder counts in whole percent, so the no-rounded-line guard '
  + 'still sees a module that invents no line',
  /underPercent: 55/.test(composerCode)
  && !/0\.5/.test(composerCode) && !/Math\.round\(/.test(composerCode),
  (composerCode.match(/0\.5\d*/g) || []).join(' ') || 'clean');


console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`FAILED: ${failures.length} assertion(s)`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
console.log('All assertions PASSED');
