/* ============================================================================
 * FantasyStakes — Sprint 7 Package 1 · shell layout end-to-end tests
 *
 * Run directly:   node web/tests/e2e_shell.mjs
 * Or through the repository suite:   python test_s7_p1_ui_shell.py
 *
 * Drives a real headless Chrome over the DevTools protocol and asserts against
 * MEASURED GEOMETRY. Source inspection can show that the navigation is in
 * normal flow; only a laid-out page can show that it does not overlap the
 * active panel at a phone viewport, that nothing overflows horizontally, and
 * that the close control really lands in the upper-right of the sheet.
 *
 * S8-P1 — NOW ON THE SHARED HARNESS. This suite was written before Package 2
 * extracted `browser-harness.mjs`, and carried its own copy of the Chrome
 * discovery, the static server and the CDP client. That duplication became a
 * defect the moment Sprint 8 gave the shell a session: the shared harness
 * learned to serve the suites from the real application and to sign in first,
 * and this file — alone among the five — did not. It went on measuring a
 * sign-in gate and reporting that the shell had not mounted.
 *
 * The duplicated harness is gone. The assertions below are untouched: they are
 * the ones certified at 6be0f50, now measured against the application a GM
 * actually loads.
 * ========================================================================== */

// VIEWPORT comes from the harness now rather than being redeclared here. The
// values are identical (390x844); the point of importing it is that a suite
// asserting "nothing exceeds the viewport width" and the harness that SETS
// that width can no longer drift apart.
import { VIEWPORT, withPage } from './browser-harness.mjs';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

await withPage({ port: 9333 }, async ({ evaluate }) => {
  console.log('\nThe app renders in a real browser at a phone viewport');

  check('the shell mounted', await evaluate(`
    return document.querySelectorAll('.fs-tabbar__item').length === 5;
  `));
  check('the masthead rendered its lockup', await evaluate(`
    return document.querySelector('.fs-mast__word').textContent === 'FantasyStakes';
  `));
  check('the tagline rendered', await evaluate(`
    return document.querySelector('.fs-mast__tagline').textContent
      === 'FANTASY LEAGUES · VIRTUAL STAKES';
  `));
  check('neither half of the tagline is broken across lines', await evaluate(`
    return [...document.querySelectorAll('.fs-mast__tagline .fs-nowrap')]
      .every(span => span.getClientRects().length === 1);
  `));

  console.log('\nNothing overflows the phone viewport');

  const overflow = await evaluate(`
    return {
      docWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
      appWidth: document.getElementById('fs-app').scrollWidth,
    };
  `);
  check(
    'the document does not scroll horizontally',
    overflow.docWidth <= overflow.innerWidth,
    `document ${overflow.docWidth}px vs viewport ${overflow.innerWidth}px`,
  );
  check(
    'the app frame fits the viewport',
    overflow.appWidth <= overflow.innerWidth,
    `app ${overflow.appWidth}px vs viewport ${overflow.innerWidth}px`,
  );

  console.log('\nAll five navigation destinations are reachable');

  const destinations = await evaluate(`
    return [...document.querySelectorAll('.fs-tabbar__item')]
      .map(el => el.dataset.destination);
  `);
  check('five destinations are bound', destinations.length === 5, destinations.join(', '));

  for (const id of destinations) {
    const state = await evaluate(`
      document.querySelector('.fs-tabbar__item[data-destination="${id}"]').click();
      const panel = document.querySelector('.fs-panel.is-active');
      const tab = document.querySelector('.fs-tabbar__item.is-active');
      const rect = panel ? panel.getBoundingClientRect() : null;
      return {
        activePanels: document.querySelectorAll('.fs-panel.is-active').length,
        panelId: panel ? panel.id : null,
        tabId: tab ? tab.dataset.destination : null,
        selected: tab ? tab.getAttribute('aria-selected') : null,
        visible: rect ? rect.width > 0 && rect.height > 0 : false,
      };
    `);
    check(
      `${id} opens exactly one visible panel`,
      state.activePanels === 1 && state.panelId === `panel-${id}` && state.visible,
      `${state.panelId}, ${state.activePanels} active`,
    );
    check(
      `${id} is marked selected for assistive tech`,
      state.tabId === id && state.selected === 'true',
    );
  }

  console.log('\nThe persistent navigation never covers tab content');

  for (const id of destinations) {
    const geometry = await evaluate(`
      document.querySelector('.fs-tabbar__item[data-destination="${id}"]').click();
      const bar = document.querySelector('.fs-tabbar').getBoundingClientRect();
      const panel = document.querySelector('.fs-panel.is-active').getBoundingClientRect();
      const children = [...document.querySelector('.fs-panel.is-active').children]
        .map(el => el.getBoundingClientRect().bottom);
      return {
        barTop: bar.top,
        barBottom: bar.bottom,
        panelBottom: panel.bottom,
        lowestChild: children.length ? Math.max(...children) : 0,
        viewport: window.innerHeight,
      };
    `);
    check(
      `${id}: the panel ends at or above the navigation`,
      geometry.panelBottom <= geometry.barTop + 0.5,
      `panel ${geometry.panelBottom.toFixed(1)}px vs nav top ${geometry.barTop.toFixed(1)}px`,
    );
    check(
      `${id}: no panel content is drawn under the navigation`,
      geometry.lowestChild <= geometry.barTop + 0.5,
      `lowest content ${geometry.lowestChild.toFixed(1)}px`,
    );
    check(
      `${id}: the navigation sits fully on screen`,
      geometry.barBottom <= geometry.viewport + 0.5,
      `nav bottom ${geometry.barBottom.toFixed(1)}px vs viewport ${geometry.viewport}px`,
    );
  }

  console.log('\nThe shared strip renders consistently across tabs');

  // Each strip is measured while ITS OWN tab is active. A hidden panel reports
  // zero-sized rectangles, and measuring one would make every geometry
  // assertion here pass vacuously.
  const strips = [];
  for (const id of destinations) {
    const measured = await evaluate(`
      document.querySelector('.fs-tabbar__item[data-destination="${id}"]').click();
      const panel = document.querySelector('.fs-panel.is-active');
      const strip = panel.querySelector('.fs-strip');
      if (!strip) return null;
      const cells = [...strip.querySelectorAll('.fs-strip__cell')];
      const widths = cells.map(c => Math.round(c.getBoundingClientRect().width));
      const box = strip.getBoundingClientRect();
      return {
        id: strip.id,
        cellCount: cells.length,
        widths,
        left: Math.round(box.left),
        right: Math.round(box.right),
        height: Math.round(box.height),
        icons: strip.querySelectorAll('svg, img').length,
        clipped: cells.some(c => c.scrollWidth > c.clientWidth + 1),
      };
    `);
    if (measured) strips.push(measured);
  }

  check('League, Action and Ledger each carry a strip', strips.length === 3, `${strips.length} strips`);
  for (const strip of strips) {
    check(`${strip.id}: four cells`, strip.cellCount === 4, `${strip.cellCount}`);
    check(
      `${strip.id}: the strip is actually laid out`,
      strip.height > 0 && strip.widths.every((w) => w > 0),
      `height ${strip.height}px, widths ${strip.widths.join('/')}`,
    );
    check(
      `${strip.id}: cells are equal width`,
      new Set(strip.widths).size === 1,
      strip.widths.join('/'),
    );
    check(
      `${strip.id}: the fourth cell is fully on screen`,
      strip.left >= 0 && strip.right <= VIEWPORT.width,
      `${strip.left}px…${strip.right}px in a ${VIEWPORT.width}px viewport`,
    );
    check(`${strip.id}: no cell clips its own content`, strip.clipped === false);
    check(`${strip.id}: icon-free`, strip.icons === 0);
  }

  check(
    'every strip renders at the same geometry — one shared component',
    new Set(strips.map((s) => `${s.left}:${s.right}:${s.widths.join('/')}`)).size === 1,
    strips.map((s) => s.widths.join('/')).join('  vs  '),
  );

  console.log('\nCredit figures draw as whole dollars over exact cents');

  const money = await evaluate(`
    const values = [...document.querySelectorAll('[data-exact-cents]')];
    return values.map(el => ({
      exact: el.getAttribute('data-exact-cents'),
      drawn: el.textContent.trim(),
    }));
  `);
  check('rendered money carries its exact cents', money.length >= 4, `${money.length} figures`);
  check(
    'no rendered Credit figure shows cents',
    money.every((m) => !/\$\d[\d,]*\.\d/.test(m.drawn)),
    money.map((m) => m.drawn).join(' '),
  );
  check(
    'each drawn figure is its exact value rounded to whole dollars',
    money.every((m) => {
      const cents = Number(m.exact);
      const dollars = (cents < 0 ? -1 : 1) * Math.floor((Math.abs(cents) + 50) / 100);
      return m.drawn.includes(`$${Math.abs(dollars).toLocaleString('en-US')}`);
    }),
  );

  console.log('\nThe Credits disclaimer appears under its strip, once per tab');

  const disclaimers = await evaluate(`
    const out = [];
    for (const panel of document.querySelectorAll('.fs-panel')) {
      const found = panel.querySelectorAll('.fs-disclaimer');
      const strip = panel.querySelector('.fs-strip');
      out.push({
        id: panel.id,
        count: found.length,
        text: found[0] ? found[0].textContent : null,
        belowStrip: found[0] && strip
          ? found[0].getBoundingClientRect().top >= strip.getBoundingClientRect().top
          : null,
        fits: found[0] ? found[0].scrollWidth <= found[0].clientWidth : null,
      });
    }
    return out;
  `);
  for (const panel of disclaimers) {
    check(`${panel.id}: at most one disclaimer`, panel.count <= 1, `${panel.count}`);
    if (panel.count === 1) {
      check(
        `${panel.id}: the disclaimer reads exactly the approved string`,
        panel.text === 'VIRTUAL CREDITS · $ IS DISPLAY ONLY · NO CASH VALUE',
        panel.text,
      );
      check(`${panel.id}: the disclaimer sits under the strip`, panel.belowStrip === true);
      check(`${panel.id}: the disclaimer is not clipped`, panel.fits === true);
    }
  }

  console.log('\nThe shared pop-out closes from an upper-right control');

  // Opened from Ledger's Request Top-Off control. Package 1 opened this sheet
  // from the ledger strip's gold cell; Package 3 gave that strip the POR's four
  // week cells and moved Current Settle to the My Season strip, so the stable
  // sheet-opening control on this tab is now Top-Off. What is under test is the
  // shared pop-out, not which control summoned it.
  const sheetGeometry = await evaluate(`
    document.querySelector('.fs-tabbar__item[data-destination="ledger"]').click();
    document.querySelector('#panel-ledger [data-topoff]').click();
    const overlay = document.getElementById('fs-overlay');
    const sheet = document.getElementById('fs-sheet');
    const close = sheet.querySelector('[data-fs-close]');
    const s = sheet.getBoundingClientRect();
    const c = close.getBoundingClientRect();
    return {
      open: overlay.classList.contains('is-open'),
      hidden: overlay.getAttribute('aria-hidden'),
      fromRight: s.right - c.right,
      fromTop: c.top - s.top,
      fromLeft: c.left - s.left,
      sheetWidth: s.width,
      sheetHeight: s.height,
      focused: document.activeElement === close,
      anchoredBottom: Math.abs(s.bottom - window.innerHeight) < 1,
    };
  `);
  check('the sheet opens', sheetGeometry.open === true);
  check('the sheet is exposed to assistive tech', sheetGeometry.hidden === 'false');
  check('the sheet is anchored to the bottom edge', sheetGeometry.anchoredBottom === true);
  check(
    'the close control sits in the upper-right of the sheet',
    sheetGeometry.fromRight >= 0 &&
    sheetGeometry.fromRight < sheetGeometry.sheetWidth / 4 &&
    sheetGeometry.fromTop >= 0 &&
    sheetGeometry.fromTop < sheetGeometry.sheetHeight / 3,
    `${sheetGeometry.fromRight.toFixed(1)}px from right, ${sheetGeometry.fromTop.toFixed(1)}px from top`,
  );
  check(
    'the close control is nearer the right edge than the left',
    sheetGeometry.fromRight < sheetGeometry.fromLeft,
    `right ${sheetGeometry.fromRight.toFixed(1)}px vs left ${sheetGeometry.fromLeft.toFixed(1)}px`,
  );
  check('the close control takes focus on open', sheetGeometry.focused === true);

  const closed = await evaluate(`
    document.querySelector('#fs-sheet [data-fs-close]').click();
    return {
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      hidden: document.getElementById('fs-overlay').getAttribute('aria-hidden'),
    };
  `);
  check('the close control closes the sheet', closed.open === false && closed.hidden === 'true');

  const reopenedThenNavigated = await evaluate(`
    document.querySelector('#panel-ledger [data-topoff]').click();
    const wasOpen = document.getElementById('fs-overlay').classList.contains('is-open');
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    return { wasOpen, stillOpen: document.getElementById('fs-overlay').classList.contains('is-open') };
  `);
  check(
    'a destination change dismisses the sheet',
    reopenedThenNavigated.wasOpen === true && reopenedThenNavigated.stillOpen === false,
  );});

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`FAILED: ${failures.length} assertion(s)`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
} else {
  console.log('All assertions PASSED');
}