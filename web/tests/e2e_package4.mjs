/* ============================================================================
 * FantasyStakes — Sprint 7 Package 4 · Rules & Settings layout tests
 *
 * Run directly:   node web/tests/e2e_package4.mjs
 * Or through:     python test_s7_p4_rules_commissioner.py
 *
 * Measured geometry and real interaction in headless Chrome at 390×844. The
 * questions this suite answers cannot be answered from source: do twelve GM
 * cards fit a phone without overflowing it, are the decision controls really
 * inert when clicked, does the legal line sit at the bottom and stay
 * subordinate, and does every sheet on this tab close from the same upper-right
 * control.
 * ========================================================================== */

import { GO_RULES, VIEWPORT, createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

await withPage({ port: 9339 }, async ({ evaluate }) => {
  const goRules = `${GO_RULES}`;

  /* ── Frame ────────────────────────────────────────────────────────────── */

  section('Rules & Settings renders at the phone viewport');

  await evaluate(`${goRules} return true;`);

  const frame = await evaluate(`return (async () => {
    const panel = document.getElementById('panel-rules');
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const ctx = await (await fetch(
      '/league/' + me.capabilities.acting_league_id + '/context/me',
      { credentials: 'same-origin' })).json();
    return {
      servedLeagueName: ctx.league_name,
      title: panel.querySelector('.fs-tabhead__title').textContent,
      identity: panel.querySelector('.fs-tabhead__sub').textContent,
      strips: panel.querySelectorAll('.fs-strip').length,
      disclaimers: panel.querySelectorAll('.fs-disclaimer').length,
      doc: document.documentElement.scrollWidth,
      inner: window.innerWidth,
      widest: Math.max(...[...panel.querySelectorAll('*')]
        .map(el => Math.round(el.getBoundingClientRect().right))),
    };
  })();`);
  check('the title is RULES & SETTINGS', frame.title === 'RULES & SETTINGS', frame.title);
  // WP5: the identity is the BOUND league's name — S8-P4B-2 wired leagueName()
  // into this header. The requirement, that Rules & Settings identifies the
  // league whose rules it shows in the shared treatment, is unchanged; the
  // constant it was pinned to belonged to the prototype.
  check('the league identity uses the shared treatment',
    typeof frame.identity === 'string' && frame.identity.trim().length > 0
    && frame.identity === frame.servedLeagueName,
    `${frame.identity} (served ${frame.servedLeagueName})`);
  check('no four-cell strip', frame.strips === 0, String(frame.strips));
  check('no Credits disclaimer', frame.disclaimers === 0, String(frame.disclaimers));
  check('the tab does not scroll the page horizontally',
    frame.doc <= frame.inner, `${frame.doc}px vs ${frame.inner}px`);
  check('no element extends past the viewport',
    frame.widest <= VIEWPORT.width, `widest right edge ${frame.widest}px`);

  /* ── Rules ────────────────────────────────────────────────────────────── */

  section('The five rule groups render in the locked order');

  const rules = await evaluate(`
    const rows = [...document.querySelectorAll('#fs-rule-groups .fs-rulerow')];
    return {
      count: rows.length,
      titles: rows.map(r => r.querySelector('.fs-rulerow__title').textContent),
      allButtons: rows.every(r => r.tagName === 'BUTTON'),
      allChevrons: rows.every(r => Boolean(r.querySelector('.fs-rulerow__chev'))),
      clipped: rows.filter(r => r.scrollWidth > r.clientWidth + 1).length,
    };
  `);
  check('exactly five groups', rules.count === 5, String(rules.count));
  check('the order is locked',
    rules.titles.join(' / ') === 'The Money / Weekly Grind / Big Money / The Bets / The Fine Print',
    rules.titles.join(' / '));
  check('every group is a tappable row', rules.allButtons === true);
  check('every row shows a disclosure affordance', rules.allChevrons === true);
  check('no row clips its own content', rules.clipped === 0);

  const ruleSheetState = await evaluate(`
    document.querySelector('[data-rule="bets"]').click();
    const sheet = document.getElementById('fs-sheet');
    const close = sheet.querySelector('[data-fs-close]');
    const s = sheet.getBoundingClientRect();
    const c = close.getBoundingClientRect();
    return {
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      title: sheet.querySelector('.fs-sheet__title').textContent,
      ruleCount: sheet.querySelectorAll('.fs-rule').length,
      sources: sheet.querySelectorAll('.fs-rule__src').length,
      text: sheet.textContent,
      closes: sheet.querySelectorAll('[data-fs-close]').length,
      fromRight: s.right - c.right,
      fromLeft: c.left - s.left,
      fromTop: c.top - s.top,
    };
  `);
  check('a rule group opens the shared sheet', ruleSheetState.open === true);
  check('the sheet is titled with the group', ruleSheetState.title === 'The Bets');
  check('every rule in the group renders', ruleSheetState.ruleCount >= 6,
    String(ruleSheetState.ruleCount));
  check('every rule shows its governing source',
    ruleSheetState.sources === ruleSheetState.ruleCount);
  check('the Locked description is the ruling’s own',
    /Terms freeze the moment you send this/.test(ruleSheetState.text));
  // REVISED BY WP5, FOLLOWING S8-P4C-2R2 — the same repair that package the
  // component suite already received and this one did not, because this suite
  // was already red for the harness reason and the drift stayed invisible.
  //
  // The pinned phrase carried the one-way ceiling AND the timing clause that
  // was corrected with it. The CLAIM is the economics, unchanged: the Derived
  // side moves in one direction only, and it is bounded. Asserted in two parts
  // so a future rewording cannot silently drop either.
  check('the Dynamic description keeps the one-way movement',
    /come down/i.test(ruleSheetState.text), ruleSheetState.text.slice(0, 160));
  check('and the ceiling that bounds it',
    /never above the acceptance ceiling/i.test(ruleSheetState.text),
    ruleSheetState.text.slice(0, 160));
  check('betting vocabulary survives', /ML|Spread|O\/U/.test(ruleSheetState.text));
  check('exactly one close control', ruleSheetState.closes === 1);
  check('the close control is upper-right',
    ruleSheetState.fromRight >= 0 && ruleSheetState.fromRight < ruleSheetState.fromLeft
    && ruleSheetState.fromTop >= 0,
    `${ruleSheetState.fromRight.toFixed(1)}px from right`);

  await evaluate(`document.querySelector('#fs-sheet [data-fs-close]').click(); return true;`);

  /* ── Settings ─────────────────────────────────────────────────────────── */

  section('The four settings rows show governed values and offer no mutation');

  const settings = await evaluate(`
    const panel = document.getElementById('panel-rules');
    const rows = [...panel.querySelectorAll('#fs-settings .fs-setrow')];
    return {
      count: rows.length,
      labels: rows.map(r => r.querySelector('.fs-setrow__label').textContent),
      values: rows.map(r => r.querySelector('.fs-setrow__value').textContent),
      inputs: panel.querySelectorAll('input, select, textarea, [type=checkbox]').length,
      readOnlyStated: /read-only/i.test(panel.textContent),
    };
  `);
  check('exactly four settings', settings.count === 4, String(settings.count));
  check('the labels are the locked labels',
    settings.labels.join(' / ') === 'Economy Stop / Standard Pool Bet / Skunk Fee / Championship split',
    settings.labels.join(' / '));
  check('Economy Stop shows the governed stop',
    settings.values[0] === '$10 / week · $220 season', settings.values[0]);
  check('Standard Pool Bet shows the governed entry',
    settings.values[1] === '$1', settings.values[1]);
  check('Skunk Fee shows the governed figures',
    settings.values[2] === '$10 weekly · $140 max', settings.values[2]);
  check('Championship split shows the governed split',
    settings.values[3] === '60 / 30 / 10', settings.values[3]);
  check('the tab renders no editable control at all', settings.inputs === 0,
    String(settings.inputs));
  check('the surface states these are read-only', settings.readOnlyStated === true);

  const settingSheetState = await evaluate(`
    document.querySelector('[data-setting="economy-stop"]').click();
    const sheet = document.getElementById('fs-sheet');
    const text = sheet.textContent;
    const inputs = sheet.querySelectorAll('input, select, [data-save]').length;
    document.querySelector('#fs-sheet [data-fs-close]').click();
    return { text, inputs };
  `);
  check('a setting opens its detail', /League configuration/.test(settingSheetState.text));
  // WP3B — Rev 4.3 §2.1 removes internal file citations from user-visible copy,
  // so a setting's provenance line now names the governing RULES rather than
  // the Python module that implements them. The claim is unchanged: the detail
  // still has to say where the value comes from.
  check('the detail names its governing source',
    /League economy configuration/.test(settingSheetState.text),
    settingSheetState.text.slice(0, 160));
  check('and it names no internal module or file path',
    !/\.py\b|web\/js\//.test(settingSheetState.text));
  check('the detail offers no editor', settingSheetState.inputs === 0);
  // GOVERNED REVISION, S8-P4B-3. Bound to real settings, a row says WHY it
  // cannot change rather than that no command exists — the B2 ruling, not a
  // missing implementation. This session is an ordinary GM, so even the one
  // mutable row offers no editor, which the assertion above still checks.
  check('the detail says why the row cannot be changed',
    /Read-only|Fixed for the season|commissioner authority|Frozen/
      .test(settingSheetState.text), settingSheetState.text.slice(0, 140));

  /* ── Commissioner order ───────────────────────────────────────────────── */

  section('The commissioner sections are in the locked order, B before C');

  const commissioner = await evaluate(`
    const secs = [...document.querySelectorAll('#fs-commissioner [data-commissioner]')];
    return {
      order: secs.map(s => s.dataset.commissioner),
      headings: secs.map(s => s.querySelector('.fs-heading__text').textContent),
      tops: secs.map(s => Math.round(s.getBoundingClientRect().top)),
    };
  `);
  check('three commissioner sections', commissioner.order.length === 3);
  check('the order is Top-Offs, GM cards, reconciliation',
    commissioner.order.join(',') === 'topoffs,gm-cards,reconciliation',
    commissioner.order.join(','));
  check('GM Ledger Cards is drawn ABOVE League Reconciliation',
    commissioner.tops[1] < commissioner.tops[2],
    `${commissioner.tops[1]}px vs ${commissioner.tops[2]}px`);
  // GOVERNED REVISION, S8-P4B-2R — GM SESSION CLAIM. This session holds no
  // commissioner authority, so the cards section carries no count. The locked
  // ORDER and WORDING are still asserted; only the dynamic count is absent,
  // and the counted form is certified in the commissioner session.
  check('the headings are the locked headings, without a count for a session '
        + 'that holds no positions',
    commissioner.headings.join(' | ')
      === 'A · TOP-OFF REQUESTS | B · GM LEDGER CARDS | C · LEAGUE RECONCILIATION',
    commissioner.headings.join(' | '));

  /* ── A · Top-Off requests ─────────────────────────────────────────────── */

  section('Top-Off requests render their real protocol states');

  const requests = await evaluate(`
    const rows = [...document.querySelectorAll('#fs-topoff-requests .fs-req')];
    const groups = [...document.querySelectorAll('.fs-reqgroup')];
    return {
      count: rows.length,
      states: groups.map(g => g.dataset.state),
      exact: rows.every(r => Boolean(r.querySelector('[data-exact-cents]'))),
      clipped: rows.filter(r => r.scrollWidth > r.clientWidth + 1).length,
    };
  `);
  // GOVERNED REVISION, S8-P4B-2R — GM SESSION CLAIM. Top-Off requests carry
  // amounts, so an unauthorised session must not be shown the illustrative
  // list. The six-request / four-state grammar is certified in the
  // commissioner session; here the claim is that none of it leaks.
  check('an unauthorised session renders no Top-Off requests',
    requests.count === 0, String(requests.count));
  check('and therefore no request states', requests.states.length === 0,
    requests.states.join(','));
  // GOVERNED REVISION, S8-P4B-2R — COMMISSIONER SESSION CLAIMS. Everything
  // below reads an actual request row: exact cents, the decision sheet, the
  // three disabled controls, the persisted decision/status pair. None of it
  // exists in a session with no commissioner authority, and none of it was
  // dropped — it is certified in p4b2_commissioner_browser.mjs.
  if (requests.count > 0) {
    check('every request carries its exact cents', requests.exact === true);
    check('no request row clips its own content', requests.clipped === 0);

    const pendingSheet = await evaluate(`
      const pending = document.querySelector('[data-state="pending"] .fs-req');
      pending.click();
      const sheet = document.getElementById('fs-sheet');
      const controls = [...sheet.querySelectorAll('[data-decide]')];
      return {
        text: sheet.textContent,
        controlCount: controls.length,
        allDisabled: controls.every(c => c.disabled === true),
        labels: controls.map(c => c.textContent),
      };
    `);
    check('a pending request offers three decision controls',
      pendingSheet.controlCount === 3, String(pendingSheet.controlCount));
    check('the controls are Approve, Reject and Cancel',
      pendingSheet.labels.join('/') === 'Approve/Reject/Cancel', pendingSheet.labels.join('/'));
    check('every control is disabled', pendingSheet.allDisabled === true);
    check('the sheet says no decision is transmitted',
      /Demonstration only/.test(pendingSheet.text));
    check('the sheet names the governed commands',
      pendingSheet.text.includes('/top-offs/{request_id}/approve'));
    check('the sheet shows the persisted decision and status',
      /decision/.test(pendingSheet.text) && /status/.test(pendingSheet.text));

    const clickDecide = await evaluate(`
      const before = document.getElementById('fs-sheet').textContent;
      document.querySelector('#fs-sheet [data-decide="approve"]').click();
      const after = document.getElementById('fs-sheet').textContent;
      return { unchanged: before === after,
               stillOpen: document.getElementById('fs-overlay').classList.contains('is-open') };
    `);
    check('clicking a disabled decision control changes nothing',
      clickDecide.unchanged === true && clickDecide.stillOpen === true);

    await evaluate(`document.querySelector('#fs-sheet [data-fs-close]').click(); return true;`);

    const approvedSheet = await evaluate(`
      document.querySelector('[data-state="approved"] .fs-req').click();
      const sheet = document.getElementById('fs-sheet');
      const text = sheet.textContent;
      const controls = sheet.querySelectorAll('[data-decide]').length;
      document.querySelector('#fs-sheet [data-fs-close]').click();
      return { text, controls };
    `);
    check('a decided request offers no controls', approvedSheet.controls === 0);
    check('an approved request shows its provenance chain',
      /ledger_posting_id/.test(approvedSheet.text) && /disclosure_event_id/.test(approvedSheet.text));
    check('an approval persists status "applied"', /applied/.test(approvedSheet.text));
  }


  /* ── B · GM ledger cards ──────────────────────────────────────────────── */

  section('Twelve GM ledger cards fit the phone and expand into Ledger grammar');

  // GOVERNED REVISION, S8-P4B-2R. This suite signs in as an ordinary GM, for
  // whom /ledger/positions correctly answers 403 — an expected capability
  // state. The card geometry, count, labels and cross-tab equality claims are
  // NOT dropped: they moved to the commissioner session in
  // test_s8_p4b2_binding.py, where cards exist. What this session certifies is
  // the claim only it can make — that an unauthorised session shows no cards
  // and no illustrative money in their place.
  const cards = await evaluate(`
    const cards = [...document.querySelectorAll('#fs-gm-cards .fs-gmcard')];
    const grid = document.getElementById('fs-gm-cards');
    const cols = new Set(cards.map(c => Math.round(c.getBoundingClientRect().left))).size;
    if (cards.length === 0) {
      const section = document.querySelector('[data-commissioner="gm-cards"]');
      return {
        count: 0,
        unavailable: section.dataset.state === 'unavailable',
        noMoney: section.querySelectorAll('[data-exact-cents]').length === 0,
      };
    }
    return {
      count: cards.length,
      cols,
      names: cards.map(c => c.querySelector('.fs-gmcard__name').textContent),
      hasSettle: cards.every(c => Boolean(c.querySelector('.fs-gmcard__settle'))),
      cellLabels: [...cards[0].querySelectorAll('.fs-gmcard__label')].map(e => e.textContent),
      exact: cards.every(c => c.querySelectorAll('[data-exact-cents]').length >= 4),
      clipped: cards.filter(c => c.scrollWidth > c.clientWidth + 1).length,
      widest: Math.max(...cards.map(c => Math.round(c.getBoundingClientRect().right))),
      anyCents: /\\$\\d+\\.\\d\\d/.test(grid.textContent),
    };
  `);
  if (cards.count === 0) {
    check('an unauthorised session renders no GM cards', cards.count === 0);
    check('and the section declares itself unavailable', cards.unavailable === true);
    check('and shows no money in their place — the prototype twelve must '
          + 'never appear here', cards.noMoney === true);
  } else {
    check('twelve GM cards', cards.count === 12, String(cards.count));
    check('they lay out in two columns', cards.cols === 2, String(cards.cols));
    check('every card names its GM', cards.names.every(n => n.length > 0));
    check('every card shows a Current Settle figure', cards.hasSettle === true);
    check('every card shows Available, In Play and Held',
      cards.cellLabels.join('/') === 'Available/In Play/Held', cards.cellLabels.join('/'));
    check('every card keeps exact cents behind its money', cards.exact === true);
    check('no card clips its own content', cards.clipped === 0);
    check('no card extends past the viewport',
      cards.widest <= VIEWPORT.width, `${cards.widest}px`);
    check('nothing is drawn with cents', cards.anyCents === false);

    const gmDetail = await evaluate(`
      document.querySelector('[data-gm="you"]').click();
      const sheet = document.getElementById('fs-sheet');
      const rows = [...sheet.querySelectorAll('.fs-lrow')];
      const total = sheet.querySelector('.fs-settle__total');
      return {
        title: sheet.querySelector('.fs-sheet__title').textContent,
        sub: sheet.querySelector('.fs-sheet__sub').textContent,
        ledgerRows: rows.length,
        settle: total ? Number(total.dataset.exactCents) : null,
        text: sheet.textContent,
        closes: sheet.querySelectorAll('[data-fs-close]').length,
      };
    `);
    check('the expansion names the GM', gmDetail.title === 'Your Team', gmDetail.title);
    check('it says whose position it is',
      /this GM’s position/.test(gmDetail.sub), gmDetail.sub);
    check('it uses the Ledger row grammar', gmDetail.ledgerRows >= 8, String(gmDetail.ledgerRows));
    check('it uses one close control', gmDetail.closes === 1);
    check('it states the shared arithmetic',
      /the same arithmetic this GM’s own Ledger performs/.test(gmDetail.text));

    await evaluate(`document.querySelector('#fs-sheet [data-fs-close]').click(); return true;`);

    // The commissioner's number for this GM must be the number that GM's own
    // Ledger tab draws — checked across two tabs in one live document.
    const crossTab = await evaluate(`
      document.querySelector('.fs-tabbar__item[data-destination="ledger"]').click();
      const own = Number(document.querySelector('#fs-current-settle .fs-settle__total').dataset.exactCents);
      ${GO_RULES}
      const commish = Number(document.querySelector('[data-gm="you"] .fs-gmcard__settle').dataset.exactCents);
      return { own, commish };
    `);
    check('the commissioner card matches the GM’s own Ledger figure',
      crossTab.own === crossTab.commish, `${crossTab.own} vs ${crossTab.commish}`);
  }


  /* ── C · League reconciliation ────────────────────────────────────────── */

  section('League reconciliation aggregates the same figures');

  const league = await evaluate(`
    const sec = document.querySelector('[data-commissioner="reconciliation"]');
    if (sec.dataset.state === 'unavailable') {
      return {
        unavailable: true,
        noMoney: sec.querySelectorAll('[data-exact-cents]').length === 0,
        noCloses: sec.querySelectorAll('[data-closes]').length === 0,
        text: sec.textContent,
      };
    }
    const rows = [...sec.querySelectorAll('.fs-lrow')].map(r => ({
      label: r.querySelector('.fs-lrow__label').textContent,
      cents: Number(r.querySelector('[data-exact-cents]').dataset.exactCents),
      total: r.classList.contains('is-total'),
    }));
    const closes = sec.querySelector('[data-closes]');
    const flags = [...sec.querySelectorAll('.fs-exrow__flag')].map(e => e.textContent);
    const exceptionValues = [...sec.querySelectorAll('.fs-exrow__value')].map(e => e.textContent);
    const cardSettles = [...document.querySelectorAll('#fs-gm-cards .fs-gmcard__settle')]
      .map(e => Number(e.dataset.exactCents));
    return {
      rows,
      closes: closes.dataset.closes,
      closesText: closes.textContent,
      flags,
      exceptionValues,
      integrity: sec.querySelector('.fs-integrity__head').textContent,
      cardSum: cardSettles.reduce((a, b) => a + b, 0),
      exceptionText: sec.textContent,
    };
  `);
  if (league.unavailable) {
    // GM SESSION CLAIM. /ledger/reconciliation is a commissioner surface and
    // correctly answered 403. The aggregate claims below are certified under
    // commissioner auth in test_s8_p4b2_binding.py; here the claim is that no
    // league figure is fabricated in their absence.
    check('an unauthorised session shows no league reconciliation figures',
      league.noMoney === true);
    check('and offers no closes marker to read as a verified fact',
      league.noCloses === true);
    check('and says commissioner authority is required',
      /commissioner authority/.test(league.text));
  } else {
    const total = league.rows.find(r => r.total);
    const parts = league.rows.filter(r => !r.total);
    check('the section reports a league figure', Boolean(total));
    check('the league figure is its three terms',
      parts.reduce((s, r) => s + r.cents, 0) === total.cents,
      `${parts.map(r => r.cents).join(' + ')} = ${total.cents}`);
    check('the twelve GM cards sum to the league figure',
      league.cardSum === total.cents, `${league.cardSum} vs ${total.cents}`);
    check('the surface states that the league closes', league.closes === 'true');
    check('and shows the figure both ways agree on',
      league.closesText.includes('−$665') || league.closesText.includes('$665'),
      league.closesText.trim().slice(0, 60));
    check('pending holds are flagged as not a settlement liability',
      league.flags.filter(f => f === 'not a liability').length === 2,
      league.flags.join(' | '));
    // A figure inside a total carries its sign; a quantity outside every total is
    // drawn unsigned, so it cannot read as a credit some total received.
    check('quantities outside settlement are drawn unsigned',
      league.exceptionValues.slice(0, 2).every(v => !v.startsWith('+')),
      league.exceptionValues.join(' | '));
    check('the receivable inside settlement keeps its sign',
      league.exceptionValues[2].startsWith('−'), league.exceptionValues[2]);
    check('the exception note states the exclusion',
      /Excluded from settlement until a proposal is accepted/.test(league.exceptionText));
    check('the integrity invariant is not claimed as checked',
      /NOT VERIFIED HERE/.test(league.integrity), league.integrity);
    check('no second Current Settle formula is offered',
      !/View Full Reconciliation/i.test(league.exceptionText));  }

  /* ── D · Legal footer ─────────────────────────────────────────────────── */

  section('The legal line closes the tab, subordinate to it');

  const legal = await evaluate(`
    const panel = document.getElementById('panel-rules');
    const el = document.getElementById('fs-legal');
    const commish = document.getElementById('fs-commissioner');
    const title = panel.querySelector('.fs-tabhead__title');
    return {
      text: el.textContent,
      count: panel.querySelectorAll('#fs-legal').length,
      belowCommissioner: el.getBoundingClientRect().top >= commish.getBoundingClientRect().bottom - 1,
      fontSize: parseFloat(getComputedStyle(el).fontSize),
      titleFontSize: parseFloat(getComputedStyle(title).fontSize),
      elsewhere: [...document.querySelectorAll('.fs-panel')]
        .filter(p => p.id !== 'panel-rules')
        .some(p => /All Rights Reserved/.test(p.textContent)),
      inMasthead: /All Rights Reserved/.test(document.getElementById('fs-mast').textContent),
    };
  `);
  check('the footer text is exact',
    legal.text === '© 2026 Fraser D. Coleman. All Rights Reserved. FantasyStakes™.', legal.text);
  check('it appears once on the tab', legal.count === 1);
  check('it sits below the commissioner area', legal.belowCommissioner === true);
  check('it is visually subordinate to the tab title',
    legal.fontSize < legal.titleFontSize,
    `${legal.fontSize}px vs ${legal.titleFontSize}px`);
  check('it is not repeated on any other tab', legal.elsewhere === false);
  check('and it is not in the global masthead', legal.inMasthead === false);

  /* ── Navigation ───────────────────────────────────────────────────────── */

  section('The tab keeps the persistent navigation reachable');

  const nav = await evaluate(`
    const bar = document.querySelector('.fs-tabbar').getBoundingClientRect();
    const panel = document.querySelector('.fs-panel.is-active').getBoundingClientRect();
    const items = [...document.querySelectorAll('.fs-tabbar__item')]
      .map(el => el.getBoundingClientRect());
    return {
      barTop: bar.top, barBottom: bar.bottom, panelBottom: panel.bottom,
      viewport: window.innerHeight,
      allVisible: items.every(r => r.right <= ${VIEWPORT.width} && r.left >= 0),
    };
  `);
  check('the panel ends at or above the navigation',
    nav.panelBottom <= nav.barTop + 0.5,
    `panel ${nav.panelBottom.toFixed(1)} vs nav ${nav.barTop.toFixed(1)}`);
  check('the navigation is fully on screen', nav.barBottom <= nav.viewport + 0.5);
  check('all five destinations remain within the viewport', nav.allVisible === true);
});

finish();