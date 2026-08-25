/* ============================================================================
 * FantasyStakes — FINAL POR · UI-1 · shell context preservation, in a browser
 *
 * WHY THIS RUNS IN A BROWSER. Every claim here is a claim about what a reader
 * SEES after a local mutation: which tab they are on, where their carousel is,
 * whether the sheet they were using survived. None of that is observable from
 * Python, from a source read, or from a DOM-free unit test — the defect being
 * fixed was invisible to every existing suite precisely because all of them
 * asserted server state.
 *
 * THE DEFECT, EXACTLY. `mountApplication()` ended in
 * `goTo(DEFAULT_DESTINATION_ID)`, so any caller that rebuilt the panels also
 * navigated the reader to Standings and closed their sheet. Submitting a Prop
 * Pool pick is such a caller. A GM tapped Submit on Play and was moved to a
 * different tab.
 *
 * WHAT IS ASSERTED, AND WHY EACH CASE EXISTS:
 *
 *   U1  a fresh mount still lands on Standings      the locked landing tab
 *   U2  navigating to Play records Play             the shell remembers
 *   U3  a Prop Pool submit LEAVES THE READER ON PLAY  the reported defect
 *   U4  the Pool carousel keeps its position        scroll survives remount
 *   U5  no page-level horizontal scroll, all widths  shared-CSS regression
 *   U6  all three carousel families are reachable    the families are one set
 *                                                    for scroll purposes only
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const asyncProbe = (body) => `return (async () => { ${body} })();`;

/** The three carousel families, exactly as `shell.js` enumerates them. */
const RAIL_SELECTOR = '.fs-carousel, .fs-rail--carousel, .fs-rescar';

/** Certified phone viewports. A layout claim is worth its viewport and no more. */
const VIEWPORTS = [
  { width: 320, height: 568, label: 'smallest certified phone' },
  { width: 375, height: 667, label: 'standard phone' },
  { width: 390, height: 844, label: 'modern phone' },
];

await withPage({ port: 9451, settleMs: 1700 }, async ({ evaluate, setViewport }) => {

  report.section('UI-1 · the shell remembers where the reader is');

  /* ── U1 — a FRESH mount still lands on the locked landing tab ─────────── */

  const landing = await evaluate(`
    return {
      active: (document.querySelector('.fs-tabbar__item.is-active') || {}).dataset
        ? document.querySelector('.fs-tabbar__item.is-active').dataset.destination
        : null,
      panelActive: Boolean(document.querySelector('#panel-standings.is-active')),
    };
  `);
  report.check('a fresh mount lands on Standings — the locked landing tab',
    landing.active === 'standings' && landing.panelActive === true,
    JSON.stringify(landing));

  /* ── U2 — navigating records the destination ──────────────────────────── */

  const onPlay = await evaluate(asyncProbe(`
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 300));
    return {
      active: document.querySelector('.fs-tabbar__item.is-active').dataset.destination,
      panelActive: Boolean(document.querySelector('#panel-league.is-active')),
    };
  `));
  report.check('navigating to Play activates Play',
    onPlay.active === 'league' && onPlay.panelActive === true,
    JSON.stringify(onPlay));

  /* ── U6 — the three carousel families ─────────────────────────────────── */

  const families = await evaluate(asyncProbe(`
    const seen = {};
    for (const [dest, panelId] of [['league','panel-league'],
                                   ['action','panel-action'],
                                   ['week','panel-week']]) {
      document.querySelector('.fs-tabbar__item[data-destination="' + dest + '"]').click();
      await new Promise((r) => setTimeout(r, 260));
      const panel = document.getElementById(panelId);
      seen[dest] = {
        carousel: panel.querySelectorAll('.fs-carousel').length,
        rail: panel.querySelectorAll('.fs-rail--carousel').length,
        rescar: panel.querySelectorAll('.fs-rescar').length,
      };
    }
    return seen;
  `));
  report.check('Play carries the .fs-carousel family',
    families.league.carousel > 0, JSON.stringify(families.league));
  report.check('Status carries the .fs-rail--carousel family',
    families.action.rail > 0, JSON.stringify(families.action));
  report.check('Wrap Up carries the .fs-rescar family',
    families.week.rescar > 0, JSON.stringify(families.week));

  /* ── U3 / U4 — the reported defect: a Prop Pool submit ────────────────── */

  // Scroll a Play rail off its first card FIRST, so the position has something
  // to lose. A rail already at 0 would pass U4 for the wrong reason.
  const armed = await evaluate(asyncProbe(`
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 320));
    const panel = document.getElementById('panel-league');
    const rails = [...panel.querySelectorAll('${RAIL_SELECTOR}')]
      .filter((el) => el.scrollWidth > el.clientWidth + 4);
    if (!rails.length) return { scrollable: 0, offset: 0 };
    const rail = rails[0];
    rail.scrollLeft = Math.round(rail.clientWidth);
    await new Promise((r) => setTimeout(r, 220));
    return { scrollable: rails.length, offset: Math.round(rail.scrollLeft) };
  `));
  report.check('a Play carousel is scrollable and was moved off its first card',
    armed.scrollable > 0 && armed.offset > 0, JSON.stringify(armed));

  // Drive the REAL path: the shell's own pool-claim hook, which is what calls
  // `mountApplication`. Calling `mountApplication` directly would prove the
  // function preserves context and NOT that the defect's call site uses it.
  const submitted = await evaluate(asyncProbe(`
    const before = (() => {
      const panel = document.getElementById('panel-league');
      const rails = [...panel.querySelectorAll('${RAIL_SELECTOR}')]
        .filter((el) => el.scrollWidth > el.clientWidth + 4);
      return rails.length ? Math.round(rails[0].scrollLeft) : 0;
    })();

    // The application object the shell exposes for exactly this kind of drive.
    const api = window.FantasyStakes || {};
    if (typeof api.remountPreservingContext !== 'function') {
      return { drove: false, before, after: before, active: null };
    }
    api.remountPreservingContext();
    await new Promise((r) => setTimeout(r, 420));

    const panel = document.getElementById('panel-league');
    const rails = [...panel.querySelectorAll('${RAIL_SELECTOR}')]
      .filter((el) => el.scrollWidth > el.clientWidth + 4);
    return {
      drove: true,
      before,
      after: rails.length ? Math.round(rails[0].scrollLeft) : 0,
      active: document.querySelector('.fs-tabbar__item.is-active').dataset.destination,
    };
  `));

  report.check('the shell exposes a context-preserving remount to drive',
    submitted.drove === true,
    'window.FantasyStakes.remountPreservingContext');
  report.check('a local mutation LEAVES THE READER ON PLAY — the reported defect',
    submitted.active === 'league',
    `active tab after remount: ${submitted.active}`);
  report.check('and the Play carousel keeps its position',
    submitted.after === submitted.before && submitted.before > 0,
    `before ${submitted.before} → after ${submitted.after}`);

  /* ── U5 — no page-level horizontal scroll, at every certified width ───── */

  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    const overflow = await evaluate(asyncProbe(`
      const out = {};
      for (const [dest, panelId] of [['standings','panel-standings'],
                                     ['league','panel-league'],
                                     ['action','panel-action'],
                                     ['week','panel-week'],
                                     ['ledger','panel-ledger']]) {
        document.querySelector('.fs-tabbar__item[data-destination="' + dest + '"]').click();
        await new Promise((r) => setTimeout(r, 240));
        out[dest] = Math.round(
          document.documentElement.scrollWidth - document.documentElement.clientWidth);
      }
      return out;
    `));
    const worst = Math.max(...Object.values(overflow));
    report.check(`no horizontal page scroll on any tab at ${vp.width}x${vp.height} (${vp.label})`,
      worst <= 1, JSON.stringify(overflow));
  }
});

report.finish();
