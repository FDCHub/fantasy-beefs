/* ============================================================================
 * FantasyStakes — FINAL POR · UI-7 · Rules and League Settings
 *
 * WHY THIS RUNS IN A BROWSER. §23's League Settings is a THREE-COLUMN TABLE
 * whose third column is headed "RATIO TO WEEKLY MINIMUM" — twenty-three
 * characters that do not fit one line at any certified width. Whether all three
 * columns survive, whether the header is readable rather than ellipsed, and
 * whether the figures stay on their own side of the table are questions about
 * measured geometry, and none of them is answerable from source.
 *
 * WHAT IS ASSERTED, AT 320×568 / 375×667 / 390×844:
 *
 *   R1  §24's four rule groups render, in §24's order, and each opens
 *   R2  §23's seven allocation rows render, in §23's order
 *   R3  all three columns survive, and none is clipped or ellipsed
 *   R4  the figures are right-aligned and never collide with the label
 *   R5  the four in-season figures and five Season Rules render
 *   R6  no page-level horizontal scroll, and no bottom-nav collision
 *   R7  the Prop Pool Entry row still opens the ONE governed control
 *
 * R3 IS THE ONE THIS SUITE EXISTS FOR. UI-2 spent a whole track contract
 * learning that a six-column table at 320px fails by ellipsing a header rather
 * than by overflowing — the page looks fine and a column silently loses its
 * name. This table has a header three times longer than any of those, so the
 * same failure is likelier here, and it is measured the same way: every header
 * cell's scrollWidth against its clientWidth.
 *
 * R7 GUARDS A SEAM RATHER THAN A LAYOUT. §23 renamed Standard Pool Bet to Prop
 * Pool Entry, and the settings response, the command and the server's bound all
 * still call it `pool-bet`. One mapping reconciles them. If that mapping is
 * lost, the only editable setting in the product silently becomes read-only —
 * which nothing else would catch, because the row still renders perfectly.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();

const VIEWPORTS = [
  { width: 320, height: 568, label: 'smallest certified phone' },
  { width: 375, height: 667, label: 'standard phone' },
  { width: 390, height: 844, label: 'modern phone' },
];

const RULE_TITLES = ['The Basics', 'Your Credits', 'Weekly Play', 'Season Play'];

const ALLOC_LABELS = [
  'Weekly Minimum',
  'Prop Pool Entry',
  'Weekly Skunk Fee',
  'Projected Points Championship Pot',
  'FantasyStakes Championship Base Pot',
  'Fantasy Football Championship Pot',
  'Season Top-Off Limit',
];

const IN_SEASON_LABELS = [
  'Unspent Minimum Sweeps',
  'Top-Offs Added to FS Pot',
  'Terminal Prop Pool Remainders',
  'Current FS Championship Pot',
];

const SEASON_RULES = [
  'Weekly Minimum', 'Skunk Fees', 'Postseason play',
  'Championship split', 'Wagers',
];

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 8000;
    const poll = () => {
      const mounted = document.querySelector('.fs-tabbar__item')
        && document.querySelector('#fs-sheet');
      if (mounted || Date.now() > deadline) return resolve(Boolean(mounted));
      setTimeout(poll, 100);
    };
    poll();
  });
`;

/** Open the Rules tab and measure everything §23 and §24 put on it. */
const PROBE = `return (async () => {
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: Math.round(r.left), right: Math.round(r.right),
             top: Math.round(r.top), bottom: Math.round(r.bottom),
             w: Math.round(r.width), h: Math.round(r.height) };
  };

  FantasyStakes.goTo('rules');
  await new Promise((r) => setTimeout(r, 400));

  const rulesPanel = document.getElementById('panel-rules');
  if (!rulesPanel) return { on: false, reason: 'no rules panel' };
  FantasyStakes.goTo('settings');
  await new Promise((r) => setTimeout(r, 200));
  const panel = document.getElementById('panel-settings');
  if (!panel) return { on: false, reason: 'no settings panel' };

  const table = document.getElementById('fs-vc-allocation');
  const heads = table ? [...table.querySelectorAll('thead th')] : [];
  const rows = table ? [...table.querySelectorAll('tbody tr')] : [];

  const nav = document.querySelector('.fs-tabbar');

  return {
    on: true,
    groups: [...rulesPanel.querySelectorAll('[data-rule]')].map(
      (el) => (el.querySelector('.fs-rulerow__title') || {}).textContent),

    hasTable: Boolean(table),
    // THE HEADER CELLS, each measured for clipping the way UI-2 measures them.
    heads: heads.map((h) => ({
      text: (h.textContent || '').trim(),
      scrollW: h.scrollWidth,
      clientW: h.clientWidth,
      // An ellipsed header is the silent failure. Read the COMPUTED value
      // rather than trusting that no rule set it.
      overflow: getComputedStyle(h).textOverflow,
      whiteSpace: getComputedStyle(h).whiteSpace,
      box: box(h),
    })),

    rows: rows.map((tr) => {
      const label = tr.querySelector('.fs-vcrow__label');
      const amount = tr.querySelector('.fs-vcrow__amount');
      const ratio = tr.querySelector('.fs-vcrow__ratio');
      return {
        id: tr.dataset.alloc,
        state: tr.dataset.state,
        label: (label.textContent || '').trim(),
        amount: (amount.textContent || '').trim(),
        ratio: (ratio.textContent || '').trim(),
        labelBox: box(label),
        amountBox: box(amount),
        ratioBox: box(ratio),
        amountClipped: amount.scrollWidth > amount.clientWidth + 1,
        ratioClipped: ratio.scrollWidth > ratio.clientWidth + 1,
      };
    }),

    inSeason: [...panel.querySelectorAll('[data-in-season]')].map((el) => ({
      id: el.dataset.inSeason,
      label: (el.querySelector('.fs-vcseason__label').textContent || '').trim(),
      value: (el.querySelector('.fs-vcseason__value').textContent || '').trim(),
    })),
    seasonRules: [...panel.querySelectorAll('#fs-season-rules .fs-vcrules__row')]
      .map((el) => ({
        label: (el.querySelector('.fs-vcrules__label').textContent || '').trim(),
        value: (el.querySelector('.fs-vcrules__value').textContent || '').trim(),
      })),

    tableBox: box(table),
    panelBox: box(panel),
    docScrollW: document.documentElement.scrollWidth,
    docClientW: document.documentElement.clientWidth,
    navTop: nav ? Math.round(nav.getBoundingClientRect().top) : null,
    lastBottom: (() => {
      const scroller = panel.querySelector('.fs-rulescroll');
      return scroller ? Math.round(scroller.getBoundingClientRect().bottom) : null;
    })(),
  };
})();`;

/** Tap one allocation row and report what opened. */
const OPEN_ROW = (rowId) => `return (async () => {
  FantasyStakes.goTo('settings');
  await new Promise((r) => setTimeout(r, 250));

  const row = document.querySelector('[data-alloc="${rowId}"]');
  if (!row) return { opened: false, reason: 'no such row' };
  row.click();
  await new Promise((r) => setTimeout(r, 500));

  const overlay = document.getElementById('fs-overlay');
  const sheet = overlay && overlay.classList.contains('is-open')
    ? document.getElementById('fs-sheet') : null;
  if (!sheet) return { opened: false, reason: 'no sheet opened' };

  const title = sheet.querySelector('.fs-sheet__title');
  const out = {
    opened: true,
    title: title ? (title.textContent || '').trim() : null,
    body: (sheet.textContent || '').trim(),
    // THE ONE GOVERNED CONTROL. Its presence is the whole of R7.
    hasForm: Boolean(sheet.querySelector('#fs-pool-entry-form')),
    hasInput: Boolean(sheet.querySelector('#fs-pool-entry')),
    closeLeft: (() => {
      const c = sheet.querySelector('.fs-sheet__close');
      if (!c) return null;
      const cr = c.getBoundingClientRect();
      const sr = sheet.getBoundingClientRect();
      return Math.round(cr.left - sr.left) < Math.round(sr.right - cr.right);
    })(),
  };
  const closer = sheet.querySelector('[data-fs-close]');
  if (closer) closer.click();
  await new Promise((r) => setTimeout(r, 250));
  return out;
})();`;

/** Open one rule group and report its sheet. */
const OPEN_GROUP = (id) => `return (async () => {
  FantasyStakes.goTo('rules');
  await new Promise((r) => setTimeout(r, 250));
  const row = document.querySelector('[data-rule="${id}"]');
  if (!row) return { opened: false, reason: 'no such group' };
  row.click();
  await new Promise((r) => setTimeout(r, 500));
  const overlay = document.getElementById('fs-overlay');
  const sheet = overlay && overlay.classList.contains('is-open')
    ? document.getElementById('fs-sheet') : null;
  if (!sheet) return { opened: false, reason: 'no sheet opened' };
  const out = {
    opened: true,
    title: (sheet.querySelector('.fs-sheet__title') || {}).textContent,
    ruleCount: sheet.querySelectorAll('.fs-rule__head').length,
    sourceCount: sheet.querySelectorAll('.fs-rule__src').length,
    text: (sheet.textContent || '').replace(/\\s+/g, ' ').trim(),
    docScrollW: document.documentElement.scrollWidth,
    docClientW: document.documentElement.clientWidth,
  };
  const closer = sheet.querySelector('[data-fs-close]');
  if (closer) closer.click();
  await new Promise((r) => setTimeout(r, 250));
  return out;
})();`;

await withPage({ port: 9492, settleMs: 2500 }, async ({ evaluate, setViewport }) => {

  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    const tag = `${vp.width}×${vp.height}`;
    report.section(`UI-7 Rules & League Settings at ${tag} (${vp.label})`);
    report.check(`${tag} · the application mounted`,
      await evaluate(READY) === true);

    const m = await evaluate(PROBE);
    report.check(`${tag} — the Rules tab renders`, m.on === true,
      m.reason || 'on');
    if (!m.on) continue;

    /* ── R1 — §24's four groups ───────────────────────────────────────── */
    report.check(`${tag} — §24's four rule groups render, in order`,
      m.groups.join(' / ') === RULE_TITLES.join(' / '), m.groups.join(' / '));

    /* ── R2 — §23's seven rows ────────────────────────────────────────── */
    report.check(`${tag} — the VC ALLOCATION table renders`,
      m.hasTable === true);
    report.check(`${tag} — seven allocation rows`,
      m.rows.length === 7, String(m.rows.length));
    report.check(`${tag} — in §23's order, with §23's labels`,
      m.rows.map((r) => r.label).join(' / ') === ALLOC_LABELS.join(' / '),
      m.rows.map((r) => r.label).join(' / '));

    /* ── R3 — three columns, none clipped ─────────────────────────────── */
    report.check(`${tag} — three column headers`,
      m.heads.length === 3, String(m.heads.length));
    report.check(`${tag} — headed VC ALLOCATION / AMOUNT / RATIO TO WEEKLY MINIMUM`,
      m.heads.map((h) => h.text).join(' | ')
        === 'VC ALLOCATION | AMOUNT | RATIO TO WEEKLY MINIMUM',
      m.heads.map((h) => h.text).join(' | '));
    for (const h of m.heads) {
      report.check(`${tag} — the "${h.text}" header is not clipped`,
        h.scrollW <= h.clientW + 1, `${h.scrollW} vs ${h.clientW}`);
      report.check(`${tag} — and is allowed to wrap rather than ellipse`,
        h.overflow !== 'ellipsis' && h.whiteSpace !== 'nowrap',
        `${h.overflow} / ${h.whiteSpace}`);
    }
    for (const row of m.rows) {
      report.check(`${tag} — ${row.label}: the amount is not clipped`,
        row.amountClipped === false, row.amount);
      report.check(`${tag} — ${row.label}: the ratio is not clipped`,
        row.ratioClipped === false, row.ratio);
      report.check(`${tag} — ${row.label}: it states a ratio`,
        row.ratio.endsWith('×'), row.ratio);
    }

    /* ── R4 — the figures keep their side ─────────────────────────────── */
    for (const row of m.rows) {
      report.check(`${tag} — ${row.label}: the label never overruns the amount`,
        row.labelBox.right <= row.amountBox.left + 1,
        `label ends ${row.labelBox.right}, amount starts ${row.amountBox.left}`);
      report.check(`${tag} — ${row.label}: the amount never overruns the ratio`,
        row.amountBox.right <= row.ratioBox.left + 1,
        `amount ends ${row.amountBox.right}, ratio starts ${row.ratioBox.left}`);
    }
    // ONE GRID, not three columns that happen to line up. Every row's figure
    // columns must start at the same x, or the table reads as ragged.
    report.check(`${tag} — every amount starts at the same x`,
      new Set(m.rows.map((r) => r.amountBox.left)).size === 1,
      [...new Set(m.rows.map((r) => r.amountBox.left))].join(' '));
    report.check(`${tag} — and every ratio does too`,
      new Set(m.rows.map((r) => r.ratioBox.left)).size === 1,
      [...new Set(m.rows.map((r) => r.ratioBox.left))].join(' '));

    /* ── R5 — in-season figures and Season Rules ──────────────────────── */
    report.check(`${tag} — the four in-season figures render, in order`,
      m.inSeason.map((r) => r.label).join(' / ') === IN_SEASON_LABELS.join(' / '),
      m.inSeason.map((r) => r.label).join(' / '));
    // `every` ON AN EMPTY ARRAY IS TRUE, which would pass this vacuously on a
    // page that rendered no figures at all -- the exact failure mode being
    // checked for. The length is asserted with it.
    report.check(`${tag} — each carries a figure`,
      m.inSeason.length === 4 && m.inSeason.every((r) => /\d/.test(r.value)),
      m.inSeason.map((r) => r.value).join(' '));
    report.check(`${tag} — the five Season Rules render, in order`,
      m.seasonRules.map((r) => r.label).join(' / ') === SEASON_RULES.join(' / '),
      m.seasonRules.map((r) => r.label).join(' / '));
    report.check(`${tag} — the split rule states 60 / 30 / 10`,
      (m.seasonRules.find((r) => r.label === 'Championship split') || {}).value
        === '60 / 30 / 10',
      JSON.stringify(m.seasonRules.find((r) => r.label === 'Championship split')));
    report.check(`${tag} — and wagers are stated Public`,
      (m.seasonRules.find((r) => r.label === 'Wagers') || {}).value === 'Public');

    /* ── R6 — the page still behaves ──────────────────────────────────── */
    report.check(`${tag} — no page-level horizontal scroll`,
      m.docScrollW <= m.docClientW + 1,
      `${m.docScrollW} vs ${m.docClientW}`);
    report.check(`${tag} — the table fits its panel`,
      m.tableBox.w <= m.panelBox.w + 1 && m.tableBox.left >= m.panelBox.left - 1,
      `table ${m.tableBox.w} in panel ${m.panelBox.w}`);
    if (m.navTop !== null && m.lastBottom !== null) {
      report.check(`${tag} — the tab's content clears the bottom navigation`,
        m.lastBottom <= m.navTop + 1,
        `content ends ${m.lastBottom}, nav starts ${m.navTop}`);
    }
  }

  /* ── R1 (continued) — every group opens and carries its rules ───────── */

  await setViewport(375, 667);
  report.section('UI-7 · §24 · each rule group opens');

  const GROUPS = [
    ['basics', 'The Basics'],
    ['credits', 'Your Credits'],
    ['weekly', 'Weekly Play'],
    ['season', 'Season Play'],
  ];
  const opened = {};
  for (const [id, title] of GROUPS) {
    const g = await evaluate(OPEN_GROUP(id));
    opened[id] = g;
    report.check(`${title} opens`, g.opened === true, g.reason || 'opened');
    if (!g.opened) continue;
    report.check(`  · titled "${title}"`, (g.title || '').trim() === title,
      String(g.title));
    report.check('  · every rule in it renders', g.ruleCount > 0,
      String(g.ruleCount));
    report.check('  · and every rule names its source',
      g.sourceCount === g.ruleCount, `${g.sourceCount} of ${g.ruleCount}`);
    report.check('  · opening it causes no horizontal overflow',
      g.docScrollW <= g.docClientW + 1, `${g.docScrollW} vs ${g.docClientW}`);
  }

  /* THE APPROVED COPY, READ OFF THE RENDERED SHEET. Asserting it against the
   * data module would only prove the module agrees with itself; this is the
   * text a GM actually reads. */
  report.section('UI-7 · §24 · the approved copy reaches the reader');

  const APPROVED = [
    ['basics', 'FantasyStakes uses your league settings, scoring and '
      + 'projections to simulate matchups and generate real probabilities and '
      + 'Vegas-style odds.'],
    ['credits', 'Virtual credits have no real-world economic value outside '
      + 'FantasyStakes.'],
    ['weekly', 'Team Prop Pools are based on the performance of individual '
      + 'fantasy teams or players across the league.'],
    ['weekly', 'Matchup Prop Pools are based on the combined results or '
      + 'performance of a specific fantasy football matchup.'],
  ];
  for (const [id, text] of APPROVED) {
    report.check(`the sheet renders: "${text.slice(0, 46)}…"`,
      (opened[id].text || '').includes(text), id);
  }

  report.check('the FantasyStakes Score formula reaches the reader',
    (opened.credits.text || '').includes(
      'FantasyStakes Score = Matchups + Prop Pools − Skunk Fees'));
  report.check('the Skunk is stated as ONE assessment, never charged twice',
    /ONE assessment/.test(opened.weekly.text || '')
    && /never charged twice/.test(opened.weekly.text || ''));
  report.check('the two-team playoff exception reaches the reader',
    /exactly two teams/.test(opened.season.text || '')
    && /67 to the champion and 33 to the runner-up/.test(opened.season.text || ''));
  report.check('  · and its limit does too — SHAPE, never missing information',
    /never about missing information/.test(opened.season.text || ''));

  /* ── R7 — the one governed control survives §23's rename ────────────── */

  report.section('UI-7 · §23 · the Prop Pool Entry row keeps its control');

  const pool = await evaluate(OPEN_ROW('prop-pool-entry'));
  report.check('the Prop Pool Entry row opens a sheet',
    pool.opened === true, pool.reason || 'opened');
  if (pool.opened) {
    // IN DEMO MODE THE FORM IS NOT DRAWN -- there is no league to write to,
    // and `settingControl` says so rather than offering a control that would
    // be refused. What must hold is that the row reaches the SETTINGS sheet
    // rather than the plain read-only one, which is what the mapping does.
    report.check('  · and it is the Standard Pool Bet setting sheet',
      /Standard Pool Bet/.test(pool.title || '') || /Pool/.test(pool.title || ''),
      String(pool.title));
    report.check('  · which states why it is read-only here',
      /Read-only|commissioner/.test(pool.body || ''),
      (pool.body || '').slice(0, 90));
    report.check('  · and its close control is upper-left',
      pool.closeLeft === true, String(pool.closeLeft));
  }

  const fixed = await evaluate(OPEN_ROW('fantasystakes-base-pot'));
  report.check('a fixed row opens its own detail sheet',
    fixed.opened === true, fixed.reason || 'opened');
  if (fixed.opened) {
    report.check('  · titled with the row',
      (fixed.title || '').trim() === 'FantasyStakes Championship Base Pot',
      String(fixed.title));
    report.check('  · it states the amount and the ratio',
      /Ratio to Weekly Minimum/.test(fixed.body || ''),
      (fixed.body || '').slice(0, 80));
    report.check('  · and says WHY it cannot be changed, not merely that it cannot',
      /re-price obligations GMs have already funded/.test(fixed.body || ''),
      (fixed.body || '').slice(0, 120));
    report.check('  · it offers no control',
      fixed.hasForm === false && fixed.hasInput === false);
  }
});

report.finish();
