/* ============================================================================
 * FantasyStakes — Sprint 7 · full-application browser certification
 *
 * Run directly:   node web/tests/e2e_certification.mjs
 * Or through:     python test_s7_full_ui_certification.py
 *
 * This suite does not re-test what the four package suites already prove. It
 * certifies the things that only exist BETWEEN packages:
 *
 *   · the five tabs behave at three real phone viewports, not just one;
 *   · one wager object survives League → composer → preview → Action → Week;
 *   · every tappable surface has a keyboard path and a usable target;
 *   · the shared pop-out behaves identically wherever it is opened from;
 *   · nothing in the running application can post, mutate, or issue.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

const VIEWPORTS = [
  { width: 375, height: 667, label: 'iPhone SE / 8' },
  { width: 390, height: 844, label: 'iPhone 14' },
  { width: 430, height: 932, label: 'iPhone 15 Pro Max' },
];

const TABS = ['league', 'action', 'ledger', 'week', 'rules'];
const go = (tab) => `document.querySelector('.fs-tabbar__item[data-destination="${tab}"]').click();`;

await withPage({ port: 9341 }, async ({ evaluate, setViewport }) => {
  /* ── Responsive certification ─────────────────────────────────────────── */

  for (const vp of VIEWPORTS) {
    section(`${vp.width}×${vp.height} — ${vp.label}`);
    await setViewport(vp.width, vp.height);

    for (const tab of TABS) {
      const r = await evaluate(`
        ${go(tab)}
        const panel = document.getElementById('panel-${tab}');
        const bar = document.querySelector('.fs-tabbar').getBoundingClientRect();
        const p = panel.getBoundingClientRect();

        // Content inside a horizontal rail is MEANT to extend past the fold —
        // that is what makes it scrollable. Everything else must fit.
        const outside = [...panel.querySelectorAll('*')]
          .filter(el => !el.closest('.fs-rail'))
          .filter(el => Math.round(el.getBoundingClientRect().right) > ${vp.width})
          .map(el => (el.className || '').toString().split(' ')[0]);

        const strips = [...panel.querySelectorAll('.fs-strip')];
        const stripClipped = strips.filter(s =>
          s.scrollWidth > s.clientWidth + 1 ||
          [...s.querySelectorAll('.fs-strip__value')].some(v => v.scrollWidth > v.clientWidth + 1)
        ).length;

        const rails = [...panel.querySelectorAll('.fs-rail')];
        const snaps = [...panel.querySelectorAll('.fs-carousel, .fs-vcar')];

        return {
          docWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
          outside: [...new Set(outside)],
          panelBottom: p.bottom, barTop: bar.top, barBottom: bar.bottom,
          viewportHeight: window.innerHeight,
          navItemsVisible: [...document.querySelectorAll('.fs-tabbar__item')]
            .every(el => { const b = el.getBoundingClientRect();
                           return b.left >= 0 && b.right <= ${vp.width}; }),
          stripClipped,
          railsFit: rails.every(x => Math.round(x.getBoundingClientRect().right) <= ${vp.width}),
          railsScrollable: rails.every(x => x.scrollWidth > x.clientWidth + 1),
          snapsSnap: snaps.every(x => getComputedStyle(x).scrollSnapType.startsWith('y')),
          // A card that overflows its own box slices text through the glyphs.
          // Short phones are where this bites, so it is measured at each size.
          clippedCards: [...panel.querySelectorAll('.fs-wcard, .fs-pool, .fs-poolrow, .fs-gmcard')]
            .filter(el => el.scrollHeight > el.clientHeight + 1)
            .map(el => (el.className || '').toString().split(' ')[0]),
        };
      `);

      check(`${tab}: the page does not scroll horizontally`,
        r.docWidth <= r.innerWidth, `${r.docWidth} vs ${r.innerWidth}`);
      check(`${tab}: nothing outside a rail overflows the viewport`,
        r.outside.length === 0, r.outside.join(', '));
      check(`${tab}: the panel ends at or above the navigation`,
        r.panelBottom <= r.barTop + 0.5,
        `${r.panelBottom.toFixed(1)} vs ${r.barTop.toFixed(1)}`);
      check(`${tab}: the navigation is fully on screen and reachable`,
        r.barBottom <= r.viewportHeight + 0.5 && r.navItemsVisible === true);
      check(`${tab}: no summary strip clips`, r.stripClipped === 0, String(r.stripClipped));
      check(`${tab}: no card clips its own content`,
        r.clippedCards.length === 0, r.clippedCards.join(', '));
      if (r.railsScrollable !== undefined && tab === 'action') {
        check(`${tab}: rails fit and communicate scrollability`,
          r.railsFit === true && r.railsScrollable === true);
      }
      if (tab === 'league' || tab === 'week') {
        check(`${tab}: vertical carousels snap`, r.snapsSnap === true);
      }
    }

    // League's 2×2 Pools grid must stay coherent at every width.
    const pools = await evaluate(`
      ${go('league')}
      const cards = [...document.querySelectorAll('#fs-pools-grid .fs-pool')];
      const cols = new Set(cards.map(c => Math.round(c.getBoundingClientRect().left))).size;
      const rows = new Set(cards.map(c => Math.round(c.getBoundingClientRect().top))).size;
      const grid = document.getElementById('fs-pools-grid');
      return { count: cards.length, cols, rows,
               scrolls: grid.scrollHeight > grid.clientHeight + 1,
               allVisible: cards.every(c => c.getBoundingClientRect().height > 0) };
    `);
    check('League Pools stay a 2×2 grid with all four visible',
      pools.count === 4 && pools.cols === 2 && pools.rows === 2
      && pools.allVisible === true && pools.scrolls === false,
      `${pools.cols}×${pools.rows}, scrolls=${pools.scrolls}`);

    // The commissioner's twelve cards and the legal footer must remain usable.
    const commish = await evaluate(`
      ${go('rules')}
      const scroll = document.querySelector('#panel-rules .fs-rulescroll');
      scroll.scrollTop = scroll.scrollHeight;
      const cards = [...document.querySelectorAll('#fs-gm-cards .fs-gmcard')];
      const legal = document.getElementById('fs-legal').getBoundingClientRect();
      const bar = document.querySelector('.fs-tabbar').getBoundingClientRect();
      return {
        cards: cards.length,
        cols: new Set(cards.map(c => Math.round(c.getBoundingClientRect().left))).size,
        legalReachable: legal.top < bar.top && legal.bottom > 0,
        legalText: document.getElementById('fs-legal').textContent,
      };
    `);
    check('the commissioner 12-card surface stays usable',
      commish.cards === 12 && commish.cols === 2, `${commish.cards} cards, ${commish.cols} cols`);
    check('the legal footer can be reached by scrolling',
      commish.legalReachable === true);

    // A sheet must fit and stay closable at every size.
    const sheet = await evaluate(`
      ${go('league')}
      document.querySelector('#panel-league .fs-wcard__cta').click();
      const s = document.getElementById('fs-sheet').getBoundingClientRect();
      const close = document.querySelector('#fs-sheet [data-fs-close]').getBoundingClientRect();
      const fits = s.right <= ${vp.width} + 0.5 && s.left >= -0.5 && s.bottom <= window.innerHeight + 0.5;
      const closeOnScreen = close.top >= 0 && close.right <= ${vp.width} && close.bottom <= window.innerHeight;
      document.querySelector('#fs-sheet [data-fs-close]').click();
      const closed = !document.getElementById('fs-overlay').classList.contains('is-open');
      return { fits, closeOnScreen, closed };
    `);
    check('a sheet fits the viewport and stays closable',
      sheet.fits && sheet.closeOnScreen && sheet.closed,
      `fits=${sheet.fits} closeVisible=${sheet.closeOnScreen} closed=${sheet.closed}`);
  }

  await setViewport(390, 844);

  /* ── One wager object across five contexts ────────────────────────────── */

  section('One wager object moves through League, composer, preview and Action');

  const grammar = await evaluate(`
    const read = (tab, sel) => {
      document.querySelector('.fs-tabbar__item[data-destination="' + tab + '"]').click();
      return [...document.querySelectorAll(sel)];
    };
    const leagueMarkets = read('league', '#fs-bets-carousel .fs-wcard .fs-market__label')
      .map(e => e.textContent);
    const weekMarkets = read('week', '[data-module="yahoo"] .fs-wcard .fs-market__label')
      .map(e => e.textContent);
    const actionModes = read('action', '.fs-wcard__context')
      .map(e => (e.textContent.match(/LOCKED|DYNAMIC/) || [''])[0]).filter(Boolean);
    const weekBetModes = read('week', '[data-module="bets"] .fs-wcard__context')
      .map(e => (e.textContent.match(/LOCKED|DYNAMIC/) || [''])[0]).filter(Boolean);
    return {
      leagueMarkets: [...new Set(leagueMarkets)],
      weekMarkets: [...new Set(weekMarkets)],
      actionModes: [...new Set(actionModes)],
      weekBetModes: [...new Set(weekBetModes)],
    };
  `);
  check('League and The Week use one market vocabulary',
    grammar.leagueMarkets.join(',') === grammar.weekMarkets.join(','),
    `${grammar.leagueMarkets.join(',')} vs ${grammar.weekMarkets.join(',')}`);
  check('the market vocabulary is ML, SPR and O/U',
    grammar.leagueMarkets.join(',') === 'ML,SPR,O/U', grammar.leagueMarkets.join(','));
  check('Action and The Week draw modes from one vocabulary',
    grammar.weekBetModes.every(m => grammar.actionModes.includes(m)),
    `${grammar.actionModes.join(',')} / ${grammar.weekBetModes.join(',')}`);

  const journey = await evaluate(`
    ${go('league')}
    // Whole-card tap: no market selected.
    document.querySelector('#panel-league .fs-wcard').click();
    const opened = document.getElementById('fs-sheet').textContent;
    const stakeAtOpen = document.querySelector('#fs-stake-input').value;
    const sendDisabledAtOpen = document.querySelector('[data-composer-send]').disabled;

    // Choose a market and a stake.
    document.querySelector('[data-composer-market="ml"]').click();
    const input = document.querySelector('#fs-stake-input');
    input.value = '20';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const sendAfterStake = document.querySelector('[data-composer-send]').disabled;
    const econBefore = [...document.querySelectorAll('[data-econ] [data-exact-cents]')]
      .map(e => e.dataset.exactCents).join(',');

    // Push the preview on top, then come back.
    document.querySelector('[data-composer-preview]').click();
    const previewOpen = /SPORTSBOOK VIEW/.test(document.getElementById('fs-sheet').textContent);
    document.querySelector('#fs-sheet [data-fs-close]').click();
    const backInComposer = /YOUR STAKE/.test(document.getElementById('fs-sheet').textContent);
    const stakeAfter = document.querySelector('#fs-stake-input').value;
    const marketAfter = document.querySelector('[data-composer-market="ml"]').getAttribute('aria-pressed');
    const econAfter = [...document.querySelectorAll('[data-econ] [data-exact-cents]')]
      .map(e => e.dataset.exactCents).join(',');
    const sendAfter = document.querySelector('[data-composer-send]').disabled;
    document.querySelector('#fs-sheet [data-fs-close]').click();
    return { opened: /YOUR STAKE/.test(opened), stakeAtOpen, sendDisabledAtOpen,
             sendAfterStake, previewOpen, backInComposer, stakeAfter, marketAfter,
             econBefore, econAfter, sendAfter,
             closedAtEnd: !document.getElementById('fs-overlay').classList.contains('is-open') };
  `);
  check('a whole-card tap reaches the composer', journey.opened === true);
  check('the stake opens at $0, untouched', journey.stakeAtOpen === '0', journey.stakeAtOpen);
  check('Send opens disabled', journey.sendDisabledAtOpen === true);
  check('Send enables once market, mode and stake are satisfied',
    journey.sendAfterStake === false);
  check('the Matchup Preview opens over the composer', journey.previewOpen === true);
  check('closing the preview returns the composer', journey.backInComposer === true);
  check('the stake survived the round trip', journey.stakeAfter === '20', journey.stakeAfter);
  check('the market selection survived', journey.marketAfter === 'true');
  check('the economics are unchanged by the trip',
    journey.econBefore === journey.econAfter,
    `${journey.econBefore} vs ${journey.econAfter}`);
  check('Send is still enabled on return', journey.sendAfter === false);
  check('closing the composer closes the sheet entirely', journey.closedAtEnd === true);

  section('The same wager keeps one detail grammar wherever it is opened');

  const details = await evaluate(`
    const open = (tab, sel) => {
      document.querySelector('.fs-tabbar__item[data-destination="' + tab + '"]').click();
      document.querySelector(sel).click();
      const t = document.getElementById('fs-sheet').textContent;
      document.querySelector('#fs-sheet [data-fs-close]').click();
      return t;
    };
    return {
      fromAction: open('action', '[data-rail="live"] .fs-wcard'),
      fromWeek: open('week', '[data-module="bets"] .fs-wcard'),
    };
  `);
  for (const [where, text] of Object.entries(details)) {
    check(`${where}: the detail names the protocol state, not a rail`,
      /Protocol state/.test(text) && /accepted/.test(text));
    check(`${where}: the detail names the Response Card`, /Response card/.test(text));
    check(`${where}: the detail shows both stakes and the pot`,
      /Your stake/.test(text) && /Their stake/.test(text) && /Pot/.test(text));
  }

  /* ── Accessibility certification ──────────────────────────────────────── */

  section('Every tappable surface has semantics, a keyboard path and a target');

  const a11y = await evaluate(`
    const out = { badLists: [], nameless: [], smallTargets: [], loudIcons: 0, inertDivs: [] };
    for (const tab of ${JSON.stringify(TABS)}) {
      document.querySelector('.fs-tabbar__item[data-destination="' + tab + '"]').click();
      const panel = document.getElementById('panel-' + tab);

      for (const list of panel.querySelectorAll('[role="list"]')) {
        if ([...list.children].some(c => c.getAttribute('role') !== 'listitem')) {
          out.badLists.push(tab + ':' + (list.className || list.id));
        }
      }
      for (const b of panel.querySelectorAll('button')) {
        if (!(b.textContent || '').trim() && !b.getAttribute('aria-label')) {
          out.nameless.push(tab + ':' + b.className);
        }
      }
      for (const b of panel.querySelectorAll('button, [role="button"]')) {
        const r = b.getBoundingClientRect();
        if (r.width > 0 && (r.height < 30 || r.width < 30)) {
          out.smallTargets.push(tab + ':' + (b.className||'').split(' ')[0]
            + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
        }
      }
      // Anything carrying a tap hook must be a control or declare itself one.
      for (const el of panel.querySelectorAll('[data-card-action], [data-pool], [data-rule], [data-setting], [data-gm], [data-request], [data-week]')) {
        const isControl = ['BUTTON','A'].includes(el.tagName) || el.getAttribute('role') === 'button';
        const hasNestedControls = el.querySelector('button, a');
        if (!isControl && !hasNestedControls) out.inertDivs.push(tab + ':' + el.className);
      }
      out.loudIcons += [...panel.querySelectorAll('svg')]
        .filter(s => s.getAttribute('aria-hidden') !== 'true').length;
    }
    return out;
  `);
  check('every role=list holds only listitems',
    a11y.badLists.length === 0, a11y.badLists.join(' | '));
  check('every button has an accessible name',
    a11y.nameless.length === 0, a11y.nameless.join(' | '));
  check('every control meets a usable phone target',
    a11y.smallTargets.length === 0, a11y.smallTargets.join(' | '));
  check('no tappable surface is an inert div without semantics or a control inside',
    a11y.inertDivs.length === 0, a11y.inertDivs.join(' | '));
  check('decorative icons are hidden from assistive tech', a11y.loudIcons === 0);

  const keyboard = await evaluate(`
    const activate = (tab, sel, key) => {
      document.querySelector('.fs-tabbar__item[data-destination="' + tab + '"]').click();
      const el = document.querySelector(sel);
      el.focus();
      const focused = document.activeElement === el;
      if (el.tagName === 'BUTTON') el.click();
      else el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
      const opened = document.getElementById('fs-overlay').classList.contains('is-open');
      if (opened) document.querySelector('#fs-sheet [data-fs-close]').click();
      return { focused, opened };
    };
    return {
      leagueCta: activate('league', '#panel-league .fs-wcard__cta', 'Enter'),
      actionCard: activate('action', '#panel-action [data-card-action="wager"]', 'Enter'),
      weekYahoo: activate('week', '#panel-week [data-card-action="yahoo"]', ' '),
      weekBet: activate('week', '#panel-week [data-module="bets"] [data-card-action="wager"]', 'Enter'),
      pool: activate('league', '#panel-league [data-pool]', 'Enter'),
      rule: activate('rules', '#panel-rules [data-rule]', 'Enter'),
      gmCard: activate('rules', '#panel-rules [data-gm]', 'Enter'),
    };
  `);
  for (const [name, r] of Object.entries(keyboard)) {
    check(`${name}: focusable and activated from the keyboard`,
      r.focused === true && r.opened === true,
      `focused=${r.focused} opened=${r.opened}`);
  }

  const states = await evaluate(`
    ${go('week')}
    const weeks = [...document.querySelectorAll('#panel-week [data-week]')]
      .map(w => w.getAttribute('aria-pressed'));
    document.querySelector('#panel-league .fs-wcard__cta').click();
    const modes = [...document.querySelectorAll('[data-composer-mode]')]
      .map(m => m.getAttribute('aria-pressed'));
    document.querySelector('#fs-sheet [data-fs-close]').click();
    const nav = [...document.querySelectorAll('.fs-tabbar__item')]
      .map(i => i.getAttribute('aria-selected'));
    return { weeks, modes, nav, navRoles: [...document.querySelectorAll('.fs-tabbar__item')]
      .every(i => i.getAttribute('role') === 'tab') };
  `);
  check('the selected week is programmatically distinguishable',
    states.weeks.filter(v => v === 'true').length === 1, states.weeks.join(','));
  check('the selected mode is programmatically distinguishable',
    states.modes.filter(v => v === 'true').length === 1, states.modes.join(','));
  check('exactly one navigation destination is selected',
    states.nav.filter(v => v === 'true').length === 1, states.nav.join(','));
  check('navigation items carry the tab role', states.navRoles === true);

  const sheetSemantics = await evaluate(`
    ${go('rules')}
    document.querySelector('[data-rule="money"]').click();
    const overlay = document.getElementById('fs-overlay');
    const sheet = document.getElementById('fs-sheet');
    const close = sheet.querySelector('[data-fs-close]');
    const r = close.getBoundingClientRect();
    const s = sheet.getBoundingClientRect();
    const result = {
      role: sheet.getAttribute('role'),
      modal: sheet.getAttribute('aria-modal'),
      labelledby: sheet.getAttribute('aria-labelledby'),
      titleId: sheet.querySelector('.fs-sheet__title').id,
      closeName: close.getAttribute('aria-label'),
      focused: document.activeElement === close,
      upperRight: (s.right - r.right) >= 0 && (s.right - r.right) < (r.left - s.left) && (r.top - s.top) >= 0,
      hidden: overlay.getAttribute('aria-hidden'),
    };
    // Navigating away must dismiss the sheet.
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    result.dismissedByNav = !overlay.classList.contains('is-open');
    return result;
  `);
  check('the sheet is a labelled modal dialog',
    sheetSemantics.role === 'dialog' && sheetSemantics.modal === 'true'
    && sheetSemantics.labelledby === sheetSemantics.titleId,
    `${sheetSemantics.role}/${sheetSemantics.modal}/${sheetSemantics.labelledby}`);
  check('the close control has an accessible name',
    sheetSemantics.closeName === 'Close', String(sheetSemantics.closeName));
  check('the close control is upper-right and takes focus',
    sheetSemantics.upperRight === true && sheetSemantics.focused === true);
  check('the sheet is exposed to assistive tech while open',
    sheetSemantics.hidden === 'false');
  check('a destination change dismisses the sheet',
    sheetSemantics.dismissedByNav === true);

  section('Commissioner controls are inert, and nothing can mutate');

  const inert = await evaluate(`
    ${go('rules')}
    document.querySelector('[data-state="pending"] .fs-req').click();
    const controls = [...document.querySelectorAll('#fs-sheet [data-decide]')];
    const before = document.getElementById('fs-sheet').textContent;
    controls.forEach(c => c.click());
    const after = document.getElementById('fs-sheet').textContent;
    document.querySelector('#fs-sheet [data-fs-close]').click();
    return { count: controls.length, allDisabled: controls.every(c => c.disabled === true),
             unchanged: before === after };
  `);
  check('every commissioner decision control is disabled',
    inert.count === 3 && inert.allDisabled === true);
  check('clicking them changes nothing', inert.unchanged === true);

  const network = await evaluate(`
    // Nothing in the running application may reach the network. Any attempt
    // would be an issuance or configuration path this build must not have.
    let calls = 0;
    const realFetch = window.fetch;
    window.fetch = (...a) => { calls += 1; return realFetch(...a); };
    const realOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function (...a) { calls += 1; return realOpen.apply(this, a); };
    for (const tab of ${JSON.stringify(TABS)}) {
      document.querySelector('.fs-tabbar__item[data-destination="' + tab + '"]').click();
    }
    document.querySelector('#panel-rules [data-topoff]') && document.querySelector('#panel-rules [data-topoff]').click();
    if (document.getElementById('fs-overlay').classList.contains('is-open')) {
      document.querySelector('#fs-sheet [data-fs-close]').click();
    }
    return { calls, forms: document.querySelectorAll('form').length,
             inputs: document.querySelectorAll('input[type=password], input[name*=card]').length };
  `);
  check('no request is issued while driving the application',
    network.calls === 0, String(network.calls));
  check('the application renders no form', network.forms === 0);
  check('and no payment or credential input', network.inputs === 0);
});

finish();