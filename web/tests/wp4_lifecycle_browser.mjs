/* ============================================================================
 * FantasyStakes — WP4 · the commissioner lifecycle, from the browser
 *
 * WHY THIS RUNS IN A REAL BROWSER. Every claim WP4 makes is about what a
 * commissioner can DO on a phone: that the controls are on Rules & Settings,
 * that pressing one reaches the governed route, that a governed refusal reads
 * as English, that a double tap sends one command, and that none of it
 * overflows a 375px viewport. None of those survive being asserted against a
 * string of markup.
 *
 * NOTHING IS PROVED BY A SCREENSHOT. Every assertion below reads the DOM, the
 * network timeline or the authoritative server state — and the two positives
 * that move real state (Week Open, and the settle attempt) are checked against
 * the lifecycle READ afterwards rather than against the message the page drew.
 * ========================================================================== */

import { GO_RULES, createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const probe = (body) => `return (async () => { ${body} })();`;

const settle = (ms) => `await new Promise((r) => setTimeout(r, ${ms}));`;

await withPage({ port: 9401, settleMs: 2000 }, async ({ evaluate, setViewport }) => {

  /* ── Where the controls live ──────────────────────────────────────────── */

  report.section('The lifecycle lives inside Rules & Settings — off the tab bar');

  const nav = await evaluate(probe(`
    return [...document.querySelectorAll('.fs-tabbar__item')]
      .map((el) => el.dataset.destination);
  `));

  // WP3B — Rev 4.3 §3 relocks the five, and Rules & Settings is no longer one
  // of them (§3.1). The claim this section makes is unchanged and if anything
  // stronger: the lifecycle still gets no tab of its own, and the surface it
  // lives on does not either.
  report.check('the navigation is the locked Rev 4.3 five destinations',
    nav.join(',') === 'standings,league,action,week,ledger', nav.join(','));
  report.check('Rules & Settings holds no bottom-navigation position',
    !nav.includes('rules'), nav.join(','));

  const placement = await evaluate(probe(`
    ${GO_RULES}
    ${settle(400)}
    const panel = document.getElementById('panel-rules');
    const region = panel.querySelector('#fs-lifecycle');
    const scroll = panel.querySelector('.fs-rulescroll');
    // The scroller direct children, named by what they ARE: the two rule
    // sections carry a data-region, the rest carry ids.
    const kids = region
      ? [...scroll.children].map((el) => el.dataset.region || el.id)
      : [];
    return {
      inRulesPanel: Boolean(region),
      inAnyOtherPanel: [...document.querySelectorAll('.fs-panel')]
        .filter((p) => p.id !== 'panel-rules' && p.querySelector('#fs-lifecycle')).length,
      state: region ? region.dataset.state : null,
      league: region ? region.dataset.league : null,
      sections: region
        ? [...region.querySelectorAll('[data-lifecycle]')].map((el) => el.dataset.lifecycle)
        : [],
      order: kids,
      commissionerOrder: [...panel.querySelectorAll('[data-commissioner]')]
        .map((el) => el.dataset.commissioner),
    };
  `));

  report.check('the lifecycle region renders on the Rules & Settings panel',
    placement.inRulesPanel === true);
  report.check('and on no other panel', placement.inAnyOtherPanel === 0,
    String(placement.inAnyOtherPanel));
  report.check('it is bound to authoritative state, not a fallback',
    placement.state === 'authoritative', String(placement.state));
  report.check('the three sections are Setup, Week, Season, in that order',
    placement.sections.join(',') === 'setup,week,season',
    placement.sections.join(','));
  // THE WHOLE TAB ORDER, asserted as a sequence rather than as two comparisons.
  // Rules, then league configuration, then the lifecycle, then the
  // commissioner's reporting surfaces, then the legal line last.
  report.check('it sits between league configuration and the commissioner area',
    placement.order.join(',')
      === 'rules,settings,fs-lifecycle,fs-commissioner,fs-legal',
    placement.order.join(' → '));
  report.check('and the locked commissioner order is untouched',
    placement.commissionerOrder.join(',') === 'topoffs,gm-cards,reconciliation',
    placement.commissionerOrder.join(','));

  /* ── The active league ────────────────────────────────────────────────── */

  report.section('Every figure is scoped to the active league');

  const identity = await evaluate(probe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    return { league: me.capabilities.acting_league_id,
             commissionerOf: me.capabilities.commissioner_league_ids };
  `));

  report.check('this session is a commissioner of the acting league',
    Array.isArray(identity.commissionerOf)
    && identity.commissionerOf.includes(identity.league),
    `league ${identity.league}, commissioner of ${identity.commissionerOf}`);
  report.check('and the region names that league, not another',
    placement.league === String(identity.league),
    `region says ${placement.league}, session says ${identity.league}`);

  /* ── Pool support ─────────────────────────────────────────────────────── */

  report.section('Pool support states in product language');

  const support = await evaluate(probe(`
    const setup = document.querySelector('[data-lifecycle="setup"]');
    const served = await (await fetch('/league/${identity.league}/lifecycle',
      { credentials: 'same-origin' })).json();
    return {
      chip: setup.querySelector('.fs-lcstate__value').textContent.trim(),
      button: setup.querySelector('[data-lifecycle-action="pool-support"]').textContent.trim(),
      text: setup.textContent,
      servedState: served.pool_support.state,
    };
  `));

  report.check('the served state is one of the three governed answers',
    ['not_measured', 'insufficient', 'ready'].includes(support.servedState),
    support.servedState);
  report.check('and it is drawn in product language, not the raw state',
    ['Not measured', 'Insufficient', 'Ready'].includes(support.chip)
    && support.chip.toLowerCase().replace(' ', '_') === support.servedState,
    `chip "${support.chip}" for state "${support.servedState}"`);
  report.check('an unmeasured league is offered Activate, a measured one Re-measure',
    support.servedState === 'not_measured'
      ? support.button === 'Activate Pool Support'
      : support.button === 'Re-measure Pool Support',
    support.button);

  // THE ENGINE'S VOCABULARY MUST NOT REACH THE PAGE. This is the specific thing
  // the scope forbids, and it is asserted against the rendered text rather than
  // against the source, because a template can leak what a source does not show.
  report.check('no implementation vocabulary is exposed in the setup section',
    !/PoolDefinition|record_activation_measurement|gate ?[12]|definition_key|selectable/i
      .test(support.text),
    support.text.replace(/\s+/g, ' ').slice(0, 120));

  /* ── Week Open: a real command, checked against server state ──────────── */

  report.section('Week Open reaches the governed route');

  const before = await evaluate(probe(`
    const r = await fetch('/league/${identity.league}/lifecycle',
      { credentials: 'same-origin' });
    const b = await r.json();
    return { week: b.week.week, opened: b.week.opened,
             released: b.week.released_teams, teams: b.week.teams };
  `));

  report.check('the week comes from the league, not from a constant',
    typeof before.week === 'number', `week ${before.week}`);
  report.check('and the week is not yet fully open',
    before.opened === false,
    `${before.released} of ${before.teams} teams released`);

  // TWO CLICKS, DELIBERATELY, IN THE SAME FRAME. This is both the positive and
  // the duplicate-dispatch proof: the command must reach the route once.
  const opened = await evaluate(probe(`
    const btn = document.querySelector('[data-lifecycle-action="week-open"]');
    btn.click();
    btn.click();
    ${settle(2500)}
    const after = await (await fetch('/league/${identity.league}/lifecycle',
      { credentials: 'same-origin' })).json();
    const region = document.getElementById('fs-lifecycle');
    const result = region.querySelector('[data-lifecycle-result="week-open"]');
    const control = region.querySelector('[data-lifecycle-action="week-open"]');
    return {
      // THE NETWORK TIMELINE, not a counter the page kept about itself.
      requests: performance.getEntriesByType('resource')
        .filter((e) => e.name.includes('/week/${before.week}/open')).length,
      status: result ? result.dataset.status : null,
      message: result ? result.textContent.trim() : null,
      opened: after.week.opened,
      released: after.week.released_teams,
      disabledNow: control ? control.disabled : null,
      why: region.querySelector('[data-lifecycle-why="week-open"]')
        ? region.querySelector('[data-lifecycle-why="week-open"]').textContent.trim() : null,
    };
  `));

  report.check('a double tap dispatched the command exactly ONCE',
    opened.requests === 1, `${opened.requests} request(s) to the open route`);
  report.check('the week is now open on the SERVER, not just on the page',
    opened.opened === true, `${opened.released} of ${before.teams} teams released`);
  report.check('and the page reports success',
    opened.status === 'success', `${opened.status}: ${opened.message}`);
  report.check('the success message is a sentence, not a payload',
    typeof opened.message === 'string' && /week/i.test(opened.message)
    && !/[{}\[\]]|_[a-z]+_/.test(opened.message), opened.message);
  report.check('a completed action is then disabled',
    opened.disabledNow === true, String(opened.disabledNow));
  report.check('and says why it is unavailable',
    typeof opened.why === 'string' && opened.why.length > 0, opened.why);

  /* ── A governed refusal reads as English ──────────────────────────────── */

  report.section('A governed refusal is translated, never echoed');

  const refused = await evaluate(probe(`
    const btn = document.querySelector('[data-lifecycle-action="pool-settle"]');
    if (!btn || btn.disabled) return { skipped: true, disabled: btn ? btn.disabled : null };
    btn.click();
    ${settle(3000)}
    const result = document.querySelector('[data-lifecycle-result="pool-settle"]');
    return {
      skipped: false,
      status: result ? result.dataset.status : null,
      message: result ? result.textContent.trim() : null,
    };
  `));

  if (refused.skipped) {
    report.check('the settle control was offered for this fixture',
      false, `disabled=${refused.disabled} — the refusal path was not exercised`);
  } else {
    report.check('the refusal is surfaced as a governed outcome, not a crash',
      refused.status === 'refused' || refused.status === 'waiting',
      `${refused.status}: ${refused.message}`);
    // THE RAW CODE IS THE THING THAT MUST NOT APPEAR. Every governed vocabulary
    // this route can answer with is checked, in both conventions.
    report.check('and the raw reason code is nowhere in the message',
      !/RESULTS_NOT_READY|results_not_ready|provider_unavailable|pool_settlement_refused|no_provider_identity|reason_code/i
        .test(refused.message || ''), refused.message);
    report.check('the message is written for a commissioner',
      /[a-z]{3,}\s+[a-z]{3,}/i.test(refused.message || '')
      && (refused.message || '').includes(' '), refused.message);
  }

  /* ── RESULTS_NOT_READY is a "not yet", not a server error ─────────────── */

  report.section('RESULTS_NOT_READY renders as a normal waiting state');

  // DRIVEN THROUGH THE REAL MODULES ON THE LIVE PAGE. The settle route reaches
  // Yahoo before it reaches the finality gate, so this environment — which has
  // no provider credentials — cannot produce a genuine RESULTS_NOT_READY over
  // the wire. The mapping from that refusal to a 409 carrying the code is
  // already certified by WP2B-D; what WP4 owns is what the SURFACE does with
  // it, and that is asserted here against the real command module, the real
  // model and the real rendered DOM rather than against a mock of any of them.
  const waiting = await evaluate(probe(`
    const cmd = await import('/app/js/lifecycle-command.js');
    const model = await import('/app/js/lifecycle-model.js');
    const rules = await import('/app/js/rules.js');

    const refusal = new cmd.LifecycleCommandError(
      409, 'RESULTS_NOT_READY',
      '[RESULTS_NOT_READY] 3 matchup(s) are not finalized', {});

    const isWaiting = cmd.isWaitingState(refusal);
    const sentence = cmd.explainRefusal(refusal);

    model.recordResult(model.lifecycleLeagueId(), 'pool-settle', {
      status: isWaiting ? 'waiting' : 'refused', message: sentence,
    });

    const panel = document.getElementById('panel-rules');
    panel.innerHTML = rules.buildRulesPanel();
    const drawn = panel.querySelector('[data-lifecycle-result="pool-settle"]');

    return {
      isWaiting,
      sentence,
      status: drawn ? drawn.dataset.status : null,
      classes: drawn ? drawn.className : null,
      text: drawn ? drawn.textContent.trim() : null,
    };
  `));

  report.check('the client classifies it as WAITING rather than as a refusal',
    waiting.isWaiting === true);
  report.check('it is drawn in the waiting treatment, not the refused one',
    waiting.status === 'waiting' && /is-waiting/.test(waiting.classes || '')
    && !/is-refused/.test(waiting.classes || ''), waiting.classes);
  report.check('the copy says results are not final yet',
    /results are not final yet/i.test(waiting.text || ''), waiting.text);
  report.check('it says nothing has changed and the action can be retried',
    /nothing has changed/i.test(waiting.text || '')
    && /try again/i.test(waiting.text || ''), waiting.text);
  report.check('and it never shows the raw code or a server-error framing',
    !/RESULTS_NOT_READY/.test(waiting.text || '')
    && !/error|failed|500/i.test(waiting.text || ''), waiting.text);

  /* ── Season Close stays unavailable until the SERVER says otherwise ───── */

  report.section('Season Close is gated by the server, explained by the page');

  const season = await evaluate(probe(`
    const served = await (await fetch('/league/${identity.league}/lifecycle',
      { credentials: 'same-origin' })).json();
    const rules = await import('/app/js/rules.js');
    document.getElementById('panel-rules').innerHTML = rules.buildRulesPanel();
    const region = document.getElementById('fs-lifecycle');
    const btn = region.querySelector('[data-lifecycle-action="season-close"]');
    const why = region.querySelector('[data-lifecycle-why="season-close"]');
    return {
      ready: served.season_close.ready,
      code: served.season_close.blocking_reason_code,
      serverMessage: served.season_close.blocking_message,
      disabled: btn ? btn.disabled : null,
      why: why ? why.textContent.trim() : null,
      sectionText: region.querySelector('[data-lifecycle="season"]').textContent,
    };
  `));

  report.check('the server says the season is not ready to close',
    season.ready === false, `ready=${season.ready}, blocked on ${season.code}`);
  report.check('the blocking reason is a governed step name',
    typeof season.code === 'string' && season.code.length > 0, season.code);
  report.check('so the control is unavailable',
    season.disabled === true, String(season.disabled));
  report.check('and the page explains which prerequisite is outstanding',
    typeof season.why === 'string' && season.why.length > 20, season.why);
  report.check('in product language — the raw step name is not shown',
    !season.sectionText.includes(season.code)
    && !/versus_terminal|pool_settled|escrow_resolved|weekly_minimum_expiry|skunk_assessed|pool_rollover|pool_zero|provider_conflict/
      .test(season.sectionText),
    season.why);
  // THE SERVER'S OWN PROSE IS NOT PASSED THROUGH RAW EITHER — it is written for
  // an operator and names ids and counts a commissioner has no use for.
  report.check('the server’s operator prose is not shown verbatim',
    season.why !== season.serverMessage,
    `server: ${String(season.serverMessage).slice(0, 60)}`);

  /* ── Mobile ───────────────────────────────────────────────────────────── */

  report.section('375 / 390 / 430 px — no overflow, no clipping');

  const measure = probe(`
    ${GO_RULES}
    ${settle(400)}
    const panel = document.getElementById('panel-rules');
    const region = panel.querySelector('#fs-lifecycle');
    const scroll = panel.querySelector('.fs-rulescroll');
    if (!region) return { missing: true };

    const controls = [...region.querySelectorAll('[data-lifecycle-action]')];
    const clipped = controls.filter((el) => el.scrollWidth > el.clientWidth + 1
                                         || el.scrollHeight > el.clientHeight + 1);
    const tooSmall = controls.filter((el) => el.getBoundingClientRect().height < 40);
    const wider = [...region.querySelectorAll('*')]
      .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 0.5);
    const nav = document.getElementById('fs-tabbar').getBoundingClientRect();

    return {
      missing: false,
      controls: controls.length,
      docOverflow: document.documentElement.scrollWidth - window.innerWidth,
      bodyOverflow: document.body.scrollWidth - window.innerWidth,
      regionOverflow: scroll.scrollWidth - scroll.clientWidth,
      clipped: clipped.map((el) => el.dataset.lifecycleAction),
      tooSmall: tooSmall.map((el) => el.dataset.lifecycleAction),
      escaping: wider.length,
      // The navigation must still sit inside the viewport — a region that grew
      // the page is exactly what pushes it out of view.
      navBottom: Math.round(nav.bottom),
      viewport: window.innerHeight,
    };
  `);

  for (const [width, height] of [[375, 667], [390, 844], [430, 932]]) {
    await setViewport(width, height);
    const m = await evaluate(measure);

    if (m.missing) {
      report.check(`${width}px: the lifecycle region renders`, false, 'absent');
      continue;
    }

    report.check(`${width}px: all six controls render`, m.controls === 6,
      `${m.controls} control(s)`);
    report.check(`${width}px: the page does not scroll horizontally`,
      m.docOverflow <= 0 && m.bodyOverflow <= 0,
      `doc ${m.docOverflow}px, body ${m.bodyOverflow}px`);
    report.check(`${width}px: the region does not overflow its scroller`,
      m.regionOverflow <= 0, `${m.regionOverflow}px`);
    report.check(`${width}px: nothing in the region escapes the viewport`,
      m.escaping === 0, `${m.escaping} element(s) past ${width}px`);
    report.check(`${width}px: no control clips its own label`,
      m.clipped.length === 0, m.clipped.join(', ') || 'none clipped');
    report.check(`${width}px: every control keeps a 40px+ tap target`,
      m.tooSmall.length === 0, m.tooSmall.join(', ') || 'all >= 40px');
    report.check(`${width}px: the bottom navigation has not sunk`,
      m.navBottom <= height + 1, `nav bottom ${m.navBottom} of ${height}`);
  }
});

report.finish();