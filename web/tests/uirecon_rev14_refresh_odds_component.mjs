/* ============================================================================
 * FantasyStakes — UIRECON Rev 1.4 · `↻ REFRESH ODDS` · component tests
 *
 * Run directly:   node web/tests/uirecon_rev14_refresh_odds_component.mjs
 * Or through:     python test_uirecon_rev14_refresh_odds.py
 *
 * WHY A COMPONENT TIER AND NOT A BROWSER ONE. Everything this feature can get
 * wrong in the browser is a property of three pure functions — which cards the
 * control appears on, what it says, and what the stamp reads — and all three
 * are decidable without a shell, a session or a seeded league. Driving a
 * headless Chrome to assert that a Locked card has no button would prove the
 * same fact through four more moving parts, and would only be runnable on a
 * machine that happens to have a demo origin with a live Dynamic Matchup in it.
 *
 * THE ASSERTIONS THAT MATTER MOST ARE THE ABSENCES. A Locked Matchup must not
 * get the control at all, an unbound app must not draw a button that cannot
 * work, and no line of copy may suggest the wager repriced. Each of those is a
 * thing NOT being in a string, which is exactly the kind of claim that rots
 * silently unless something asserts it.
 * ========================================================================== */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  NEVER_REFRESHED, REFRESH_CONFIRMATION, REFRESH_LABEL,
  canRefreshOdds, refreshConfirmation, refreshHookBound, refreshOddsControl,
  refreshStamp, setRefreshHook,
} from '../js/refresh-odds.js';

import { explainRefreshRefusal, RefreshError } from '../js/refresh-odds-command.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const JS = (name) => readFileSync(join(HERE, '..', 'js', name), 'utf8');

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

function section(title) {
  console.log(`\n${title}`);
}

/** A live Dynamic Matchup, in the shape `action-model.normaliseCard` produces. */
const DYNAMIC_LIVE = Object.freeze({
  id: 'challenge-41',
  challengeId: 41,
  mode: 'dynamic',
  protocolState: 'accepted',
  derivedRepriced: true,
  settled: false,
  section: 'live',
});

const LOCKED_LIVE = Object.freeze({ ...DYNAMIC_LIVE, id: 'challenge-42',
  challengeId: 42, mode: 'locked' });

// ── §1 · eligibility ─────────────────────────────────────────────────────────

section('§1 · which Matchups may offer the control');

check('a live, handshaken Dynamic Matchup may', canRefreshOdds(DYNAMIC_LIVE));
check('a LOCKED Matchup may not — its terms froze when it was offered',
  canRefreshOdds(LOCKED_LIVE) === false);
check('a Dynamic Matchup that has not Handshaken may not',
  canRefreshOdds({ ...DYNAMIC_LIVE, derivedRepriced: false }) === false);
check('an offered Dynamic Matchup awaiting a decision may not',
  canRefreshOdds({ ...DYNAMIC_LIVE, protocolState: 'offered' }) === false);
check('a settled Matchup may not',
  canRefreshOdds({ ...DYNAMIC_LIVE, settled: true }) === false);
check('nothing at all may', canRefreshOdds(null) === false);

// ── §2 · the control, and the absence of one ────────────────────────────────

section('§2 · what the card actually draws');

setRefreshHook(null);
check('an unbound app draws no control rather than an inert button',
  refreshHookBound() === false
  && refreshOddsControl(DYNAMIC_LIVE, { eligible: true }) === '');

setRefreshHook({ read: async () => ({}), refresh: async () => ({}),
                 explain: () => '' });

const control = refreshOddsControl(DYNAMIC_LIVE, {
  refreshedAt: '2026-08-21T14:42:03', eligible: true });

check('the control carries the locked label', control.includes(REFRESH_LABEL));
// SUPERSEDED BY THE REFINE-REFRESH PASS. Rev 1.4 put the words on the face of a
// full-width button. That is the size this product uses for DECISIONS, and a
// refresh is a GM looking something up — so the face became the shared small
// glyph and the words became the accessible name, which a keyboard and a screen
// reader reach and a caption on a 26px control could not carry anyway.
check('and the label names its subject, as the accessible name of the control',
  REFRESH_LABEL === 'Refresh odds for this Matchup', REFRESH_LABEL);
check('  · which is where the control actually announces itself',
  control.includes(`aria-label="${REFRESH_LABEL}"`));
check('  · and the glyph is the shared one', control.includes('↻'));
check('it is a real button, so it has a keyboard path',
  control.includes('<button type="button"'));
check('it names the challenge it belongs to',
  control.includes('data-challenge-id="41"'));
check('it carries a live region for the confirmation',
  control.includes('aria-live="polite"'));
check('a LOCKED card draws nothing at all — not a disabled control',
  refreshOddsControl(LOCKED_LIVE, { eligible: true }) === ''
  && !refreshOddsControl(LOCKED_LIVE, { eligible: true }).includes('disabled'));
check('a card the SERVER ruled ineligible draws nothing either',
  refreshOddsControl(DYNAMIC_LIVE, { eligible: false }) === '');

// ── §3 · the stamp ──────────────────────────────────────────────────────────

section('§3 · Updated 10:42 AM');

// The server stores naive UTC. 14:42Z is 10:42 in UTC-4, so the assertion is
// written against the offset the runner is actually in rather than pinning a
// timezone the certification machine may not have.
const sample = new Date('2026-08-21T14:42:03Z');
const expected = (() => {
  const h24 = sample.getHours();
  const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
  const mm = String(sample.getMinutes()).padStart(2, '0');
  return `Updated ${h12}:${mm} ${h24 < 12 ? 'AM' : 'PM'}`;
})();

check('a served timestamp renders as `Updated H:MM AM`',
  refreshStamp('2026-08-21T14:42:03') === expected,
  refreshStamp('2026-08-21T14:42:03'));
check('a naive server timestamp is read as UTC, not as the viewer’s clock',
  refreshStamp('2026-08-21T14:42:03') === refreshStamp('2026-08-21T14:42:03Z'));
check('minutes are zero-padded',
  /Updated \d{1,2}:\d{2} (AM|PM)$/.test(refreshStamp('2026-08-21T14:05:00Z')),
  refreshStamp('2026-08-21T14:05:00Z'));
check('midnight and noon are 12, never 0',
  !refreshStamp('2026-08-21T00:30:00Z').includes('Updated 0:')
  && !refreshStamp('2026-08-21T12:30:00Z').includes('Updated 0:'));
check('never refreshed says so rather than showing a fabricated time',
  refreshStamp(null) === NEVER_REFRESHED && !/\d/.test(NEVER_REFRESHED));
check('an unparseable timestamp degrades to the same honest answer',
  refreshStamp('not-a-time') === NEVER_REFRESHED);

// ── §4 · the confirmation must not imply a reprice ──────────────────────────

section('§4 · the confirmation says what happened and nothing more');

check('line one names the source of the new odds',
  REFRESH_CONFIRMATION[0] === 'Fresh odds from current projections',
  REFRESH_CONFIRMATION[0]);
check('line two says the wager did not move',
  REFRESH_CONFIRMATION[1] === 'Wager unchanged', REFRESH_CONFIRMATION[1]);
check('both lines are rendered, in order',
  refreshConfirmation().indexOf(REFRESH_CONFIRMATION[0])
  < refreshConfirmation().indexOf(REFRESH_CONFIRMATION[1]));

const CONFIRMATION_TEXT = REFRESH_CONFIRMATION.join(' ').toLowerCase();
for (const forbidden of ['repriced', 're-priced', 'new stake', 'new terms',
                         'updated wager', 'your stake changed', 'accepted']) {
  check(`the confirmation never says "${forbidden}"`,
    !CONFIRMATION_TEXT.includes(forbidden));
}

// ── §5 · refusals never blame the wager ─────────────────────────────────────

section('§5 · a refusal is about the display, never about the Matchup');

const LOCKED_REFUSAL = explainRefreshRefusal(
  new RefreshError(409, 'refresh_not_dynamic', 'server sentence'));
check('a Locked refusal explains the Locked model rather than an error',
  LOCKED_REFUSAL.toLowerCase().includes('locked'), LOCKED_REFUSAL);
check('and never offers Refresh & Relock from here — that is a counter',
  !LOCKED_REFUSAL.toLowerCase().includes('relock'));

const FINAL = explainRefreshRefusal(
  new RefreshError(409, 'refresh_after_final_lock', ''));
check('a past-Final-Lock refusal names Final Lock',
  FINAL.includes('Final Lock'), FINAL);

const GENERIC = explainRefreshRefusal(
  new RefreshError(409, 'cannot_price', ''));
check('a pricing refusal states the Matchup is unchanged',
  GENERIC.includes('unchanged'), GENERIC);

// ── §6 · no economics in the browser ────────────────────────────────────────

section('§6 · nothing here computes a price');

const COMMAND = JS('refresh-odds-command.js');
const AFFORDANCE = JS('refresh-odds.js');

check('the command module derives no stake, pot or payout',
  !/\*\s*ratio|\/\s*100\b|Math\.floor|Math\.round/.test(
    COMMAND.replace(/\/\*[\s\S]*?\*\//g, '')));
check('the affordance module holds no probability or odds arithmetic',
  !/p_issuer\s*[*/+-]|moneyline\s*[*/+-]/.test(AFFORDANCE));
check('both read figures the server anchored on the issuer',
  AFFORDANCE.includes('issuer') && COMMAND.includes('issuer'));
check('the POST goes through session.js, the app’s one door',
  COMMAND.includes("from './session.js'")
  && COMMAND.includes("method: 'POST'"));

// ── §7 · the card grammar was extended, not forked ──────────────────────────

section('§7 · one card grammar');

const CARD = JS('wagercard.js');
check('`wagerCard` gained an `aside` slot rather than a second card function',
  CARD.includes('aside = \'\'') && CARD.includes('fs-wcard__aside'));
check('the slot sits between the copy and the foot',
  CARD.indexOf('fs-wcard__copy') < CARD.indexOf('fs-wcard__aside')
  && CARD.indexOf('fs-wcard__aside') < CARD.lastIndexOf('footHtml'));
check('and there is still exactly one exported card builder',
  (CARD.match(/^export function wagerCard/gm) || []).length === 1);

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`${failures.length} ASSERTION(S) FAILED`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
console.log('All assertions PASSED');
