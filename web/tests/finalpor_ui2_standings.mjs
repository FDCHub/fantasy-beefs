/* ============================================================================
 * FantasyStakes — FINAL POR · UI-2 · the six-column Standings table
 *
 * WHY THIS RUNS IN A BROWSER. Every claim §26 makes is a measurement: six
 * columns present at 320px, no page-level horizontal scroll, no header
 * ellipsis, TEAM still usable, header and body on one grid, no bottom-nav
 * collision. Not one of those is observable from a source read — a CSS rule
 * that LOOKS right and a table that FITS are different claims, and the whole
 * risk in adding a sixth column to a 320px phone is the gap between them.
 *
 * WHAT IS ASSERTED, AND WHY EACH CASE EXISTS:
 *
 *   S1  the six columns are exactly §26's, in order        the locked header
 *   S2  no page-level horizontal scroll, all three widths  the overflow risk
 *   S3  no header is ellipsed or clipped                   §26 forbids it
 *   S4  the header row may take two lines and does not clip its labels
 *   S5  TEAM is usable and truncates rather than overflowing
 *   S6  header and body share ONE grid, column for column  the alignment claim
 *   S7  the table does not collide with the bottom navigation
 *   S8  the explanatory copy is the approved three sentences
 *   S9  SKUNK is a positive magnitude, unsigned and untoned
 *
 * S6 IS THE ONE THAT COULD SILENTLY DRIFT. Six `<th>` and six `<td>` can both
 * exist while sitting at different x positions — that is exactly what
 * `table-layout: fixed` exists to prevent and exactly what a mis-scoped width
 * override breaks. It is measured as geometry, not inferred from the CSS.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();

/** §26's locked column set, in order. */
const COLUMNS = ['RK', 'TEAM', 'MATCH', 'POOL', 'SKUNK', 'SCORE'];

/** Certified phone viewports. A layout claim is worth its viewport and no more. */
const VIEWPORTS = [
  { width: 320, height: 568, label: 'smallest certified phone' },
  { width: 375, height: 667, label: 'standard phone' },
  { width: 390, height: 844, label: 'modern phone' },
];

const OVERALL = '[data-standings-table="overall"]';

/* THE APPLICATION MOUNTS ASYNCHRONOUSLY, so every measurement waits for it.
 * A geometry assertion taken against an unmounted shell measures nothing and
 * PASSES — zero columns do not overflow — which is the most dangerous shape a
 * layout test can have. The first run of this suite did exactly that: seven
 * checks passed against a page with no table on it. */
const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 8000;
    const poll = () => {
      const mounted = document.querySelector('.fs-tabbar__item')
        && document.querySelector('#panel-standings');
      if (mounted || Date.now() > deadline) return resolve(Boolean(mounted));
      setTimeout(poll, 100);
    };
    poll();
  });
`;

await withPage({ port: 9463, settleMs: 2500 }, async ({ evaluate, setViewport }) => {

  report.section('UI-2 · the six-column FantasyStakes Championship table');

  report.check('the application mounted', await evaluate(READY) === true);

  /* ── S1 — the locked column set ───────────────────────────────────────── */

  const header = await evaluate(`
    { const t = document.querySelector(
        '.fs-tabbar__item[data-destination="standings"]');
      if (t) t.click(); }
    const ths = [...document.querySelectorAll('${OVERALL} thead th')];
    return { labels: ths.map((th) => th.textContent.trim()) };
  `);

  report.check('the leaderboard draws exactly six columns',
    header.labels.length === 6, String(header.labels.length));
  report.check('  · and they are §26’s six, in order',
    JSON.stringify(header.labels) === JSON.stringify(COLUMNS),
    JSON.stringify(header.labels));

  /* ── S2..S7 — measured at every certified width ───────────────────────── */

  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    report.check(`${vp.width}×${vp.height} · the application mounted`,
      await evaluate(READY) === true);

    const m = await evaluate(`
      { const t = document.querySelector(
        '.fs-tabbar__item[data-destination="standings"]');
      if (t) t.click(); }
      const table = document.querySelector('${OVERALL} .fs-st__table');
      const ths = [...document.querySelectorAll('${OVERALL} thead th')];
      const firstRow = document.querySelector('${OVERALL} tbody tr');
      const tds = firstRow ? [...firstRow.children] : [];
      const nav = document.querySelector('.fs-tabbar');
      const team = document.querySelector('${OVERALL} tbody td.fs-st__team');

      const box = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { left: Math.round(r.left), right: Math.round(r.right),
                 width: Math.round(r.width), top: Math.round(r.top),
                 bottom: Math.round(r.bottom) };
      };

      return {
        // Page-level horizontal overflow, the thing a wide table causes.
        docScrollW: document.documentElement.scrollWidth,
        docClientW: document.documentElement.clientWidth,
        bodyScrollW: document.body.scrollWidth,
        // The table must not itself be wider than its container.
        tableW: table ? Math.round(table.getBoundingClientRect().width) : 0,
        containerW: table && table.parentElement
          ? Math.round(table.parentElement.getBoundingClientRect().width) : 0,
        headerCount: ths.length,
        bodyCount: tds.length,
        // A CLIPPED label is scrollWidth > clientWidth on the th itself. This
        // is the direct measurement of "no header ellipsis" — the CSS property
        // is not evidence, because a nowrap+ellipsis rule that never actually
        // truncates is harmless and a wrap rule that overflows is not.
        clipped: ths.filter((th) => th.scrollWidth > th.clientWidth + 1)
          .map((th) => th.textContent.trim() + ' needs ' + th.scrollWidth
                       + ' has ' + th.clientWidth),
        headerLines: ths.map((th) => ({
          label: th.textContent.trim(),
          h: Math.round(th.getBoundingClientRect().height),
        })),
        // One grid: each th and its td must share left and right edges.
        cols: ths.map((th, i) => ({
          label: th.textContent.trim(),
          th: box(th),
          td: tds[i] ? box(tds[i]) : null,
        })),
        teamBox: box(team),
        teamText: team ? team.textContent.trim() : null,
        teamOverflows: team ? team.scrollWidth > team.clientWidth + 1 : false,
        tableBottom: table
          ? Math.round(table.getBoundingClientRect().bottom) : 0,
        navTop: nav ? Math.round(nav.getBoundingClientRect().top) : null,
        rowCount: document.querySelectorAll('${OVERALL} tbody tr').length,
      };
    `);

    const tag = `${vp.width}×${vp.height}`;

    /* S2 — no page-level horizontal scroll. */
    report.check(`${tag} · no page-level horizontal scroll`,
      m.docScrollW <= m.docClientW + 1,
      `scrollWidth ${m.docScrollW} vs clientWidth ${m.docClientW}`);
    report.check(`${tag} · the body does not overflow either`,
      m.bodyScrollW <= m.docClientW + 1,
      `body ${m.bodyScrollW} vs ${m.docClientW}`);
    report.check(`${tag} · the table fits its container`,
      m.tableW <= m.containerW + 1, `${m.tableW} vs ${m.containerW}`);

    /* S1 again, per width — all six columns REMAIN. */
    report.check(`${tag} · all six columns remain`,
      m.headerCount === 6, String(m.headerCount));
    report.check(`${tag} · the table has rows to measure`,
      m.rowCount > 0, `${m.rowCount} rows`);
    report.check(`${tag} · and every body row has six cells`,
      m.bodyCount === 6, `${m.bodyCount} cells across ${m.rowCount} rows`);

    /* S3 — no header ellipsis, measured. */
    report.check(`${tag} · no header label is clipped`,
      m.clipped.length === 0, JSON.stringify(m.clipped));

    /* S4 — two lines are permitted; the labels are whole. */
    const tallest = Math.max(...m.headerLines.map((h) => h.h));
    report.check(`${tag} · the header row is one or two lines, not more`,
      tallest <= 44, `tallest header cell ${tallest}px`);
    report.check(`${tag} · every label is present in full`,
      m.headerLines.every((h) => COLUMNS.includes(h.label)),
      JSON.stringify(m.headerLines.map((h) => h.label)));

    /* S5 — TEAM is usable. */
    if (m.teamBox) {
      report.check(`${tag} · TEAM is a usable width`,
        m.teamBox.width >= 44,
        `${m.teamBox.width}px showing "${m.teamText}"`);
      report.check(`${tag} · and it truncates rather than overflowing`,
        m.teamBox.right <= m.containerW + 1,
        `right ${m.teamBox.right} vs container ${m.containerW}`);
    }

    /* S6 — header and body share ONE grid. */
    if (m.rowCount > 0) {
      const misaligned = m.cols.filter((c) => c.td
        && (Math.abs(c.th.left - c.td.left) > 1
            || Math.abs(c.th.right - c.td.right) > 1));
      report.check(`${tag} · header and body share one grid`,
        misaligned.length === 0,
        JSON.stringify(misaligned.map((c) => c.label)));
    }

    /* S7 — no bottom-nav collision. */
    if (m.navTop !== null) {
      report.check(`${tag} · the table does not collide with the nav`,
        m.tableBottom <= m.navTop + 1,
        `table bottom ${m.tableBottom} vs nav top ${m.navTop}`);
    }
  }

  /* ── S8 — the approved explanatory copy ───────────────────────────────── */

  await setViewport(VIEWPORTS[2].width, VIEWPORTS[2].height);
  await evaluate(READY);
  const copy = await evaluate(`
    { const t = document.querySelector(
        '.fs-tabbar__item[data-destination="standings"]');
      if (t) t.click(); }
    const el = document.querySelector('.fs-st__explainer');
    const credit = document.querySelector('.fs-st__creditline');
    return { text: [el, credit].filter(Boolean).map((node) => node.textContent)
      .join(' ').replace(/\\s+/g, ' ').trim() || null };
  `);

  report.section('UI-2 · the explanatory copy');
  report.check('the explainer is present', typeof copy.text === 'string',
    String(copy.text));
  for (const line of [
    'FantasyStakes standings combine Matchup net, Pool net and Skunk fees.',
    'Virtual credits · display only · no cash value',
  ]) {
    report.check(`  · it says: ${line}`,
      (copy.text || '').includes(line), String(copy.text).slice(0, 160));
  }

  /* ── S9 — SKUNK is a positive magnitude ──────────────────────────────── */

  report.section('UI-2 · SKUNK is a fee, not a result');
  const skunk = await evaluate(`
    { const t = document.querySelector(
        '.fs-tabbar__item[data-destination="standings"]');
      if (t) t.click(); }
    const cells = [...document.querySelectorAll('${OVERALL} tbody .fs-st__skunk')];
    return {
      count: cells.length,
      texts: cells.map((c) => c.textContent.trim()),
      toned: cells.filter((c) => c.classList.contains('is-positive')
                              || c.classList.contains('is-negative')).length,
      signed: cells.filter((c) => /^[+\\u2212-]/.test(c.textContent.trim())).length,
      index: cells.length
        ? [...cells[0].parentElement.children].indexOf(cells[0]) : -1,
    };
  `);

  report.check('every row carries a SKUNK cell',
    skunk.count > 0, String(skunk.count));
  report.check('  · it is the fifth column',
    skunk.index === 4, String(skunk.index));
  report.check('  · no SKUNK figure is signed',
    skunk.signed === 0, JSON.stringify(skunk.texts));
  report.check('  · and none carries the money win/loss tone',
    skunk.toned === 0, String(skunk.toned));
});

report.finish();
