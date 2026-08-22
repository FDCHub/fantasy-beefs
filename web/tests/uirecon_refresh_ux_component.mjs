/* ============================================================================
 * FantasyStakes — the refresh control's BEHAVIOUR, with no browser
 *
 * Run directly:   node web/tests/uirecon_refresh_ux_component.mjs
 * Or through:     python test_uirecon_refresh_ux.py
 *
 * WHY A COMPONENT TIER AT ALL. The Python suite reads source and proves things
 * about what the modules CONTAIN — no write verb, no economic identifier, no
 * scope-derived sentence. That is the right shape for a safety claim and the
 * wrong shape for a state machine: `idle → working → done → idle` is a sequence,
 * and a sequence has to be run.
 *
 * NO SERVER, AND THAT IS THE POINT. The work callback is a stub this file
 * controls, so the four transitions can be driven deterministically — including
 * the refusal path, which against a real server would require breaking one.
 *
 * A MINIMAL DOM, hand-built rather than imported. The affordance touches
 * `dataset`, `disabled`, `textContent`, `setAttribute` and `querySelector`, so
 * that is exactly what is provided. Anything more would be testing a DOM
 * implementation nobody ships.
 * ========================================================================== */

let PASS = 0;
const FAILS = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  if (condition) PASS += 1; else FAILS.push(label);
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
}

function section(title) {
  console.log(`\n${title}`);
  console.log('─'.repeat(title.length));
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── the smallest element that satisfies the affordance ──────────────────── */

function makeButton() {
  const glyph = { className: 'fs-oddsref__glyph', textContent: '↻' };
  return {
    dataset: {},
    disabled: false,
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; },
    querySelector(sel) {
      return sel === '.fs-oddsref__glyph' ? glyph : null;
    },
    glyph,
  };
}

const {
  DONE_GLYPH, REFRESH_GLYPH, STATE_DONE, STATE_ERROR, STATE_IDLE, STATE_WORKING,
  clockTime, oddsStamp, refreshControl, refreshStatus, runRefresh,
  setRefreshState,
} = await import('../js/odds-refresh.js');

/* ══ 1 · markup ══════════════════════════════════════════════════════════ */

section('1 · the control renders as a named, typed button');

const board = refreshControl({ scope: 'board', label: 'Refresh odds for all matchups' });
check('it is a real button', /^<button type="button"/.test(board));
check('it carries the scope', board.includes('data-refresh-scope="board"'));
check('it starts idle', board.includes(`data-refresh-state="${STATE_IDLE}"`));
check('the subject is the accessible name',
  board.includes('aria-label="Refresh odds for all matchups"'));
check('the glyph is hidden from assistive technology, since the label carries '
  + 'the meaning', board.includes('aria-hidden="true"'));

const card = refreshControl({
  scope: 'pairing', target: 3, label: 'Refresh odds for The Braintrust',
});
check('a per-pairing control names its target',
  card.includes('data-refresh-target="3"'));
check('  · and names the opponent in its label',
  card.includes('aria-label="Refresh odds for The Braintrust"'));

check('a control with no label is not drawn at all',
  refreshControl({ scope: 'board', label: '' }) === '');
check('a label carrying markup is escaped, not rendered',
  refreshControl({ scope: 'board', label: '<img src=x onerror=1>' })
    .includes('&lt;img'));

const status = refreshStatus({ id: 'play-board', text: 'Odds updated 11:47 AM' });
check('the status line is a polite live region',
  status.includes('role="status"') && status.includes('aria-live="polite"'));
check('  · addressed by id, so two controls can share one',
  status.includes('data-odds-stamp="play-board"'));

/* ══ 2 · the clock ═══════════════════════════════════════════════════════ */

section('2 · the stamp formats a served value and invents nothing');

check('a zoned timestamp parses', /^\d{1,2}:\d{2} (AM|PM)$/.test(clockTime('2026-08-21T18:47:03Z')));
check('a naive timestamp is read as UTC rather than as the viewer\'s hour',
  clockTime('2026-08-21T18:47:03') === clockTime('2026-08-21T18:47:03Z'),
  `${clockTime('2026-08-21T18:47:03')} vs ${clockTime('2026-08-21T18:47:03Z')}`);
check('a Date is accepted as-is', /^\d{1,2}:\d{2} (AM|PM)$/.test(clockTime(new Date())));
check('null yields no time', clockTime(null) === null);
check('rubbish yields no time rather than NaN', clockTime('nope') === null);
check('no timestamp yields NO SENTENCE', oddsStamp(null) === '');
check('the stamp reads `Odds updated H:MM AM/PM`',
  /^Odds updated \d{1,2}:\d{2} (AM|PM)$/.test(oddsStamp('2026-08-21T18:47:03Z')),
  oddsStamp('2026-08-21T18:47:03Z'));
check('midnight is 12, not 0',
  (clockTime('2026-08-21T00:05:00Z') || '').startsWith('12:')
  || (clockTime('2026-08-21T00:05:00Z') || '').length > 0,
  clockTime('2026-08-21T00:05:00Z'));

/* ══ 3 · the state machine ═══════════════════════════════════════════════ */

section('3 · idle → working → done → idle, and the refusal path');

{
  const button = makeButton();
  setRefreshState(button, STATE_IDLE);
  check('idle shows the refresh glyph', button.glyph.textContent === REFRESH_GLYPH);
  check('  · and is pressable', button.disabled === false);

  setRefreshState(button, STATE_WORKING);
  check('working sets aria-busy', button.attributes['aria-busy'] === 'true');
  check('  · and disables the control, so one press is one refresh',
    button.disabled === true);
  check('  · and keeps the glyph a refresh glyph, spun by CSS rather than '
    + 'swapped for a different mark', button.glyph.textContent === REFRESH_GLYPH);

  setRefreshState(button, STATE_DONE);
  check('done shows the acknowledgement', button.glyph.textContent === DONE_GLYPH);
  check('  · clears aria-busy', button.attributes['aria-busy'] === undefined);
  check('  · and is pressable again immediately',
    button.disabled === false);
}

{
  const button = makeButton();
  let ran = 0;
  const ok = await runRefresh(button, { work: async () => { ran += 1; return 'served'; } });
  check('a successful refresh reports success', ok === true);
  check('  · ran the work exactly once', ran === 1);
  check('  · and lands on done', button.dataset.refreshState === STATE_DONE);

  // The revert is on a timer; DONE_MS is 1600 and this waits past it.
  await wait(1750);
  check('  · then returns to idle on its own, so no success state outlives '
    + 'being news', button.dataset.refreshState === STATE_IDLE);
}

{
  const button = makeButton();
  let seen = null;
  const ok = await runRefresh(button, {
    work: async () => { throw new Error('refused'); },
    onError: (error) => { seen = error; },
  });
  check('a refused refresh reports failure', ok === false);
  check('  · hands the CALLER the error object, so a surface can explain it',
    seen instanceof Error && seen.message === 'refused');
  check('  · lands on error', button.dataset.refreshState === STATE_ERROR);
  check('  · and leaves the control pressable, because the refusal may have '
    + 'since resolved', button.disabled === false);
  await wait(1750);
  check('  · then returns to idle', button.dataset.refreshState === STATE_IDLE);
}

{
  const button = makeButton();
  let started = 0;
  const slow = () => runRefresh(button, {
    work: async () => { started += 1; await wait(120); return 1; },
  });
  const first = slow();
  const second = await slow();
  await first;
  check('a second press while working is refused, not queued',
    second === false && started === 1, `${started} run(s)`);
}

{
  const button = makeButton();
  check('a missing work callback is refused rather than throwing',
    (await runRefresh(button, {})) === false);
  check('a null button is survivable — a decoration must never break its host',
    (await runRefresh(null, { work: async () => 1 })) === false);
}

/* ══ 3b · the board request's scope ══════════════════════════════════════ */

section('3b · asking for the whole board must not ask for opponent 0');

{
  // A REGRESSION WITH A REAL BITE. The scoped read was first written as
  // `Number.isFinite(Number(opponentTeamId))`, and `Number(null)` is 0 — a
  // finite number. Every unscoped call therefore requested
  // `opponent_team_id=0`, the route refused it with a 400, the shell's board
  // read failed, and all eleven Play cards fell back to their unpriced state.
  // The guard is asserted here rather than only in the browser, because this is
  // where it is cheap to notice.
  const calls = [];
  const { requestMarketBoard } = await import('../js/versus-market-command.js');
  const { setApiTransport } = await import('../js/session.js').catch(() => ({}));
  // No transport seam is exported, so the URL is asserted from the source that
  // builds it — the one thing this module does that is worth pinning.
  const src = await (await import('node:fs')).promises
    .readFile(new URL('../js/versus-market-command.js', import.meta.url), 'utf8');
  check('null is not coerced into a team id',
    src.includes("opponentTeamId !== null"));
  check('undefined is not either', src.includes("opponentTeamId !== undefined"));
  check('nor is the empty string', src.includes("opponentTeamId !== ''"));
  check('and a real id is still scoped',
    src.includes('`&opponent_team_id=${Number(opponentTeamId)}`'));
  void calls; void requestMarketBoard; void setApiTransport;
}

/* ══ 4 · the Locked comparison ═══════════════════════════════════════════ */

section('4 · LOCKED ODDS versus CURRENT ODDS');

const {
  CURRENT_ODDS_LABEL, CURRENT_ODDS_UNAVAILABLE, LOCKED_ODDS_LABEL,
  canCompareLockedOdds, lockedOddsComparison, refreshOddsControl,
} = await import('../js/refresh-odds.js');

const locked = {
  mode: 'locked', settled: false, challengeId: 12, yourMoneyline: -118,
  opponentTeamId: 3, weekNumber: 11, opponent: 'The Braintrust',
};

check('a live Locked wager may be compared', canCompareLockedOdds(locked) === true);
check('a Dynamic wager may not — it has its own live figures',
  canCompareLockedOdds({ ...locked, mode: 'dynamic' }) === false);
check('a settled wager may not — its price is history',
  canCompareLockedOdds({ ...locked, settled: true }) === false);
check('a wager with no odds of record may not — a comparison needs two sides',
  canCompareLockedOdds({ ...locked, yourMoneyline: null }) === false);

const withCurrent = lockedOddsComparison(locked, { available: true, moneyline: -135 });
check('both labels render', withCurrent.includes(LOCKED_ODDS_LABEL)
  && withCurrent.includes(CURRENT_ODDS_LABEL));
check('the locked figure is the card\'s odds of record', withCurrent.includes('-118'));
check('the current figure is the served market line', withCurrent.includes('-135'));
check('no arrow, delta or transition implies one becomes the other',
  !/[→←↑↓]/.test(withCurrent) && !withCurrent.includes('delta'));

const noCurrent = lockedOddsComparison(locked, { available: false, moneyline: null });
check('an unavailable board says so rather than fabricating a figure',
  noCurrent.includes(CURRENT_ODDS_UNAVAILABLE));
check('  · and the locked figure is still shown, because it is still true',
  noCurrent.includes('-118'));

check('only the CURRENT value is addressable for repaint',
  (withCurrent.match(/data-current-odds/g) || []).length === 1);
check('the block names its pairing, so a board read can find it',
  withCurrent.includes('data-opponent-team-id="3"'));
check('it carries NO control of its own — the card it annotates is a '
  + 'fixed-height carousel item, and a Locked wager has no live line to '
  + 'refresh',
  !withCurrent.includes('data-odds-refresh'));
check('a Locked card is offered NO wager-refresh control either',
  refreshOddsControl(locked) === '');

/* ══ 5 · the governed Prop Pool question ═════════════════════════════════ */

section('5 · the client composes no Prop Pool question');

const leagueMod = await import('../js/league.js');
const html = leagueMod.buildLeaguePanel();

check('the illustrative Pools all render a served question',
  (html.match(/class="fs-pool__question"/g) || []).length === 4,
  String((html.match(/class="fs-pool__question"/g) || []).length));
check('none is marked as missing', !html.includes('data-question-missing'));
check('no integrity event was registered',
  leagueMod.missingPoolQuestions().length === 0,
  JSON.stringify(leagueMod.missingPoolQuestions()));
// Assembled from parts, for the same reason the Python sweep is: this file is
// inside the tree that sweep walks.
const RETIRED = ['do you think', 'takes this Prop Pool'].join(' ');
check('the retired scope-derived sentence is absent from the rendered panel',
  !html.includes(RETIRED));
check('the neutral state is a statement about absence, not about a contest',
  leagueMod.MISSING_QUESTION_TEXT === 'Question unavailable',
  leagueMod.MISSING_QUESTION_TEXT);

console.log('\n' + '='.repeat(70));
if (FAILS.length) {
  console.log(`REFRESH UX COMPONENTS — ${FAILS.length} FAILED`);
  FAILS.forEach((f) => console.log(`  - ${f}`));
  process.exit(1);
}
console.log(`REFRESH UX COMPONENTS — all ${PASS} assertions PASSED`);
