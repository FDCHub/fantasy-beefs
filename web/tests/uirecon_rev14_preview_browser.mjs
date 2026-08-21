/* ============================================================================
 * FantasyStakes — UIRECON Rev 1.4 Lane C · the Matchup Preview comparison
 *
 * Run directly:   node web/tests/uirecon_rev14_preview_browser.mjs
 * Or through:     python test_uirecon_rev14_preview.py
 *
 * ── §L1 · TWO LINEUPS ON ONE SCREEN IS NOT A COMPARISON ────────────────────
 *
 * Wave 4A gave LINEUPS real data and drew it as two `lineupTable()` calls
 * stacked one above the other. Every figure in them was true, and the panel
 * still made the one judgement it exists for the hardest thing on it: the
 * quarterback a GM was weighing sat nine rows above the quarterback it was
 * being weighed against, and at 320px the pair was never on screen together.
 *
 * The assertions below are therefore GEOMETRIC and not cosmetic. It is not
 * enough that both teams appear; the two cells of a row must sit at the SAME
 * TOP and DIFFERENT LEFT at every certified viewport, which is the machine-
 * checkable form of "side by side". A stacked layout satisfies "both teams are
 * present" and fails every check in §2.
 *
 * ── §L2 · A FORECAST WITH NO SCOREBOARD BESIDE IT ──────────────────────────
 *
 * Every starter now carries LIVE above PROJ, and so does every team footer.
 * §3 asserts the pair is present for EVERY starter on BOTH sides — a live
 * column that appeared for one team and not the other would be worse than none,
 * because a GM would read the gap as a difference between the teams.
 *
 * ── WHAT THIS SUITE MEASURES AGAINST, AND WHAT IT CANNOT ───────────────────
 *
 * The certification fixture's league is bound to the `yahoo` provider and holds
 * no authorization, so its current scoring is correctly UNREADABLE and every
 * LIVE figure is an em dash. That is not a gap in this suite — it is the exact
 * state §L2's hard rules are about, and §4 certifies it: no fabricated number,
 * an em dash in every live position, and every projection still on screen. The
 * figures a healthy feed produces are certified in Python, against the Demo
 * provider's own deterministic snapshot, where a fixture cannot fake them.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

const VIEWPORTS = [
  { width: 320, height: 568, label: 'smallest certified phone' },
  { width: 375, height: 667, label: 'standard phone' },
  { width: 390, height: 844, label: 'modern phone' },
  { width: 768, height: 1024, label: 'tablet portrait' },
  { width: 1024, height: 768, label: 'tablet landscape' },
];

/** Sub-pixel noise is not a difference; anything a GM could see is. */
const near = (a, b, tol = 1) => Math.abs(a - b) <= tol;

/** The em dash, as the page writes it. */
const DASH = '—';

/**
 * THE SMALLEST TYPE THIS PRODUCT ALREADY SHIPS — `--fs-size-eyebrow`, 9px.
 *
 * Read as a FLOOR and not as a target. A comparison that fits at 320px by
 * shrinking its type below what the rest of the application uses has not solved
 * the layout problem, it has moved it into the GM's eyesight. Pinned to the
 * token's value rather than to a number invented here: if the product ever
 * raises its floor, this fails and is meant to.
 */
const TYPE_FLOOR = 9;

/** Figures and names a GM actually reads sit at `--fs-size-fine` or above. */
const READING_FLOOR = 11;

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 9000;
    const poll = () => {
      const ok = document.querySelector('#panel-league .fs-strip__cell');
      if (ok || Date.now() > deadline) return resolve(Boolean(ok));
      setTimeout(poll, 100);
    };
    poll();
  });
`;

/**
 * Open the preview on a PRICED pairing and expand LINEUPS.
 *
 * A JS SNIPPET RATHER THAN A FUNCTION, because `setViewport` re-navigates —
 * every viewport starts from a fresh page and has to walk the same real path a
 * GM walks. An unpriced pairing refuses, and a comparison measured against a
 * refusal would certify the graceful-degradation path while claiming to
 * certify the served one.
 */
const OPEN_PREVIEW = `
  const tab = document.querySelector('.fs-tabbar__item[data-destination="league"]');
  if (tab) tab.click();
  const card = [...document.querySelectorAll('#panel-league .fs-wcard--matchup')]
    .find((c) => [...c.querySelectorAll('.fs-market__value')]
      .some((v) => v.textContent.trim() !== '\\u2014'));
  if (!card) return 'no priced card on Play';
  const button = card.querySelector('[data-preview-opponent]');
  if (!button) return 'no preview control on the priced card';
  button.click();
  return 'opened';
`;

/**
 * LINEUPS ships COLLAPSED — Rev 4.3 §10 puts the dense module last and closed.
 * A width read off a shut section is zero, and zero equals zero, so every
 * geometry assertion below would pass on a layout no GM can see.
 */
const EXPAND_LINEUPS = `
  const sheet = document.getElementById('fs-sheet');
  const s = sheet && [...sheet.querySelectorAll('.fs-prev')]
    .find((x) => x.querySelector('.fs-prev__title').textContent.trim() === 'LINEUPS');
  if (s && !s.classList.contains('is-open')) s.querySelector('.fs-prev__head').click();
  return Boolean(s && s.classList.contains('is-open'));
`;

/** Everything the matrix is, measured in one pass. */
const READ_MATRIX = `
  const sheet = document.getElementById('fs-sheet');
  if (!sheet) return { error: 'no sheet' };
  const cmp = sheet.querySelector('.fs-cmp');
  if (!cmp) return { error: 'no comparison matrix' };

  const box = (el) => {
    const r = el.getBoundingClientRect();
    return { top: Math.round(r.top), left: Math.round(r.left),
             right: Math.round(r.right), width: Math.round(r.width),
             height: Math.round(r.height) };
  };
  const size = (el) => (el ? parseFloat(getComputedStyle(el).fontSize) : null);
  const figure = (cell, label) => {
    const fig = [...cell.querySelectorAll('.fs-cmp__fig')]
      .find((f) => f.querySelector('.fs-cmp__figlabel').textContent.trim() === label);
    if (!fig) return null;
    return {
      label,
      value: fig.querySelector('.fs-cmp__fignum').textContent.trim(),
      numSize: size(fig.querySelector('.fs-cmp__fignum')),
      labelSize: size(fig.querySelector('.fs-cmp__figlabel')),
    };
  };
  const cellOf = (el, side) => {
    const cell = el.querySelector(\`.fs-cmp__cell[data-cmp-side="\${side}"]\`);
    if (!cell) return null;
    const player = cell.querySelector('.fs-cmp__player');
    return {
      side,
      player: player ? player.textContent.trim() : null,
      playerSize: size(player),
      live: figure(cell, 'LIVE') || figure(cell, 'LIVE TOTAL'),
      proj: figure(cell, 'PROJ') || figure(cell, 'PROJECTED'),
      classes: cell.className,
      figCount: cell.querySelectorAll('.fs-cmp__fig').length,
      box: box(cell),
    };
  };

  const head = cmp.querySelector('.fs-cmp__head');
  const totalRow = cmp.querySelector('.fs-cmp__row.is-total');
  const rows = [...cmp.querySelectorAll('.fs-cmp__row:not(.is-total)')];

  return {
    doc: { sw: document.documentElement.scrollWidth,
           cw: document.documentElement.clientWidth,
           bodySW: document.body.scrollWidth, bodyCW: document.body.clientWidth },
    sheet: { sw: sheet.scrollWidth, cw: sheet.clientWidth },
    matrix: box(cmp),
    head: head ? {
      pos: head.querySelector('.fs-cmp__pos').textContent.trim(),
      teams: [...head.querySelectorAll('.fs-cmp__team')].map((t) => ({
        name: t.textContent.trim(), side: t.dataset.cmpSide,
        box: box(t), size: size(t),
      })),
    } : null,
    rows: rows.map((r) => ({
      pos: r.querySelector('.fs-cmp__pos').textContent.trim(),
      posSize: size(r.querySelector('.fs-cmp__pos')),
      cells: r.querySelectorAll('.fs-cmp__cell').length,
      acting: cellOf(r, 'acting'),
      opponent: cellOf(r, 'opponent'),
      box: box(r),
    })),
    total: totalRow ? {
      acting: cellOf(totalRow, 'acting'),
      opponent: cellOf(totalRow, 'opponent'),
    } : null,
    note: (() => {
      const s = [...sheet.querySelectorAll('.fs-prev')]
        .find((x) => x.querySelector('.fs-prev__title').textContent.trim() === 'LINEUPS');
      const n = s && s.querySelector('.fs-note');
      return n ? n.textContent.trim() : null;
    })(),
    stackedSurvivors: sheet.querySelectorAll('.fs-lineup').length,
  };
`;

await withPage({ port: 9431 }, async ({ evaluate, setViewport }) => {
  await setViewport(390, 844);
  await evaluate(READY);

  const opened = await evaluate(OPEN_PREVIEW);
  section('§L1 · the preview opens on a PRICED pairing');
  check('a priced pairing offers a preview control', opened === 'opened', opened);
  await new Promise((r) => setTimeout(r, 1800));
  const expanded = await evaluate(EXPAND_LINEUPS);
  check('LINEUPS expands', expanded === true, String(expanded));

  const view = await evaluate(READ_MATRIX);
  // A MISSING MATRIX IS FATAL AND IS REPORTED AS ONE. Every assertion below
  // reads off it, so continuing would produce a page of TypeErrors instead of
  // the one finding that matters.
  if (view.error) {
    check('the comparison matrix is built', false, view.error);
    return;
  }
  check('the comparison matrix is built', true);

  /* ══════════════════════════════════════════════════════════════════════
   * §1 · THE STRUCTURE IS A COMPARISON MATRIX
   * ════════════════════════════════════════════════════════════════════ */

  section('§1 · §L1 LINEUPS is one matrix keyed by roster position');

  check('the matrix replaces the stacked lineup tables entirely',
    view.stackedSurvivors === 0, `${view.stackedSurvivors} stacked table(s)`);
  check('the left edge is a POSITION column',
    view.head && view.head.pos === 'POS', view.head && view.head.pos);
  check('exactly two teams head the matrix',
    view.head && view.head.teams.length === 2,
    view.head && view.head.teams.map((t) => t.name).join(' | '));
  check('the two team headings are the two sides, named',
    view.head && view.head.teams[0].side === 'acting'
    && view.head.teams[1].side === 'opponent',
    view.head && view.head.teams.map((t) => t.side).join(','));
  check('the matrix carries starter rows', view.rows.length > 0,
    `${view.rows.length} row(s)`);
  check('every row is one position and exactly two team cells',
    view.rows.every((r) => r.cells === 2 && r.pos.length > 0),
    view.rows.map((r) => `${r.pos}:${r.cells}`).join(' '));
  check('a team footer states both totals',
    Boolean(view.total && view.total.acting && view.total.opponent));

  /* ══════════════════════════════════════════════════════════════════════
   * §2 · ROW BY ROW, THE TWO TEAMS ARE SIDE BY SIDE
   * ════════════════════════════════════════════════════════════════════ */

  section('§2 · §L1 the row-to-row matchup relationship');

  // THE MACHINE-CHECKABLE FORM OF "SIDE BY SIDE". Same top, different left,
  // in that order — a stacked layout has different tops and identical lefts,
  // and a layout that merely floated the two near each other would fail the
  // top check the moment one cell wrapped.
  const paired = view.rows.filter((r) => r.acting && r.opponent);
  check('every row pairs an acting cell with an opponent cell',
    paired.length === view.rows.length,
    `${paired.length}/${view.rows.length}`);
  check('the two cells of a row share a top edge',
    paired.every((r) => near(r.acting.box.top, r.opponent.box.top)),
    paired.map((r) => `${r.acting.box.top}/${r.opponent.box.top}`).join(' '));
  check('the opponent cell sits to the RIGHT of the acting cell',
    paired.every((r) => r.opponent.box.left > r.acting.box.left),
    paired.slice(0, 3).map((r) => `${r.acting.box.left}<${r.opponent.box.left}`).join(' '));
  check('the two team columns never overlap',
    paired.every((r) => r.acting.box.right <= r.opponent.box.left + 1));
  check('the two team columns are the same width',
    paired.every((r) => near(r.acting.box.width, r.opponent.box.width)),
    paired.slice(0, 3).map((r) => `${r.acting.box.width}/${r.opponent.box.width}`).join(' '));

  // ONE CONSTRUCTION, NOT TWO THAT MATCH. Neither cell may carry a class or a
  // figure the other does not — that is what makes the parallelism structural
  // rather than a coincidence of two stylesheets agreeing.
  check('neither cell carries a class the other does not',
    paired.every((r) => r.acting.classes === r.opponent.classes),
    paired.slice(0, 2).map((r) => `${r.acting.classes} vs ${r.opponent.classes}`).join(' | '));
  check('neither cell carries a figure the other does not',
    paired.every((r) => r.acting.figCount === r.opponent.figCount
      && r.acting.figCount === 2));
  check('every row is one line tall on both sides',
    paired.every((r) => near(r.acting.box.height, r.opponent.box.height)));

  // THE COLUMN HEADING SITS OVER ITS OWN COLUMN. A header that drifted off its
  // cells would still read as two teams and would pair the wrong names with the
  // wrong figures.
  if (view.head && paired.length) {
    const [ha, ho] = view.head.teams;
    check('each team heading sits over its own column',
      ho.box.left > ha.box.left,
      `${ha.box.left} / ${ho.box.left}`);
  }

  /* ══════════════════════════════════════════════════════════════════════
   * §3 · EVERY STARTER CARRIES BOTH FIGURES
   * ════════════════════════════════════════════════════════════════════ */

  section('§3 · §L2 LIVE above PROJ, for every starter and both teams');

  const cells = paired.flatMap((r) => [r.acting, r.opponent]);
  check('every starter cell names a player',
    cells.every((c) => c.player && c.player.length > 0));
  check('every starter carries a PROJ figure',
    cells.every((c) => c.proj && c.proj.label === 'PROJ'),
    `${cells.filter((c) => c.proj).length}/${cells.length}`);
  check('every starter carries a LIVE figure',
    cells.every((c) => c.live && c.live.label === 'LIVE'),
    `${cells.filter((c) => c.live).length}/${cells.length}`);

  // THE PROJECTION IS ALWAYS A NUMBER on a served pairing — it is the figure
  // the market was simulated from, and a preview that lost it would have
  // nothing left to explain the price with.
  check('every projection is a figure, not a placeholder',
    cells.every((c) => /^-?\d+(\.\d+)?$/.test(c.proj.value)),
    cells.slice(0, 3).map((c) => c.proj.value).join(' '));

  check('the team footer states LIVE TOTAL on both sides',
    view.total.acting.live && view.total.acting.live.label === 'LIVE TOTAL'
    && view.total.opponent.live && view.total.opponent.live.label === 'LIVE TOTAL');
  check('the team footer states PROJECTED on both sides',
    view.total.acting.proj && view.total.acting.proj.label === 'PROJECTED'
    && view.total.opponent.proj && view.total.opponent.proj.label === 'PROJECTED');

  // THE SERVED TOTAL EQUALS THE SUM OF THE SERVED ROWS. Wave 4A's rule, kept:
  // the two agree only because the surface is REPORTING a figure it was given.
  // A surface that added the column up itself would pass "a total is present"
  // and fail this.
  for (const side of ['acting', 'opponent']) {
    const sum = paired.reduce((s, r) => s + parseFloat(r[side].proj.value), 0);
    const stated = parseFloat(view.total[side].proj.value);
    check(`${side} — the served projected total equals the sum of its rows`,
      Math.abs(sum - stated) <= 0.15,
      `rows=${sum.toFixed(1)} total=${view.total[side].proj.value}`);
  }

  /* ══════════════════════════════════════════════════════════════════════
   * §4 · THE ABSENT LIVE FIGURE IS AN EM DASH, NEVER A ZERO
   * ════════════════════════════════════════════════════════════════════ */

  section('§4 · §L2 a figure no provider stated is never drawn');

  const liveValues = cells.map((c) => c.live.value);
  const measured = liveValues.filter((v) => v !== DASH);
  const totalsLive = [view.total.acting.live.value, view.total.opponent.live.value];

  check('no live figure is blank — it is a figure or an em dash',
    liveValues.every((v) => v === DASH || /^-?\d+(\.\d+)?$/.test(v)),
    [...new Set(liveValues)].join(' '));

  if (measured.length === 0) {
    // THE FIXTURE'S OWN STATE, AND IT IS THE STATE THE HARD RULES ARE ABOUT.
    // This league is bound to a provider it holds no authorization for, so its
    // current scoring is genuinely unreadable.
    check('with no live data, every starter reads an em dash',
      liveValues.every((v) => v === DASH), `${liveValues.length} starter(s)`);
    check('with no live data, no team total is invented either',
      totalsLive.every((v) => v === DASH), totalsLive.join(' / '));
    check('and not one of them is a zero',
      !liveValues.includes('0.0') && !totalsLive.includes('0.0'));
    check('the projections are shown regardless',
      cells.every((c) => c.proj.value !== DASH));
    check('the note says the figures are unavailable rather than nil',
      Boolean(view.note) && /not available|not been scored/i.test(view.note),
      (view.note || '').slice(0, 90));
  } else {
    check('a measured week states a live team total too',
      totalsLive.every((v) => v !== DASH), totalsLive.join(' / '));
    check('the note explains what LIVE is measuring',
      Boolean(view.note) && /LIVE/.test(view.note),
      (view.note || '').slice(0, 90));
  }

  // NOTHING ON THIS SURFACE MAY IMPLY A SOURCE THIS PRODUCT DOES NOT HAVE.
  // The same forbidden vocabulary the League and Wave 4 suites scan for,
  // applied to the sentence Lane C added.
  const FORBIDDEN = ['injury report', 'injured', 'questionable', 'doubtful',
    'weather', 'wind', 'beat writer', 'insider', 'sources say', 'snap count',
    'target share', 'report says'];
  const leak = FORBIDDEN.filter((w) => (view.note || '').toLowerCase().includes(w));
  check('the note implies no source this product does not have',
    leak.length === 0, leak.join(', '));

  /* ══════════════════════════════════════════════════════════════════════
   * §5 · THE TYPE FLOOR
   * ════════════════════════════════════════════════════════════════════ */

  section('§5 · §L1 the matrix fits without shrinking the type');

  const labelSizes = cells.flatMap((c) => [c.live.labelSize, c.proj.labelSize])
    .concat(view.head.teams.map((t) => t.size))
    .filter((n) => typeof n === 'number');
  const readingSizes = cells.flatMap((c) => [c.playerSize, c.live.numSize,
    c.proj.numSize]).filter((n) => typeof n === 'number');

  check('no label is smaller than the product’s existing floor',
    labelSizes.every((n) => n >= TYPE_FLOOR),
    `min ${Math.min(...labelSizes)}px, floor ${TYPE_FLOOR}px`);
  check('every name and figure sits at the reading size or above',
    readingSizes.every((n) => n >= READING_FLOOR),
    `min ${Math.min(...readingSizes)}px, floor ${READING_FLOOR}px`);

  /* ══════════════════════════════════════════════════════════════════════
   * §6 · EVERY CERTIFIED VIEWPORT
   * ════════════════════════════════════════════════════════════════════ */

  for (const vp of VIEWPORTS) {
    section(`§6 · ${vp.width}×${vp.height} — ${vp.label}`);

    await setViewport(vp.width, vp.height);
    await evaluate(READY);
    const state = await evaluate(OPEN_PREVIEW);
    if (state !== 'opened') {
      check(`${vp.width}px — the preview opens`, false, state);
      continue;
    }
    await new Promise((r) => setTimeout(r, 1600));
    await evaluate(EXPAND_LINEUPS);
    const m = await evaluate(READ_MATRIX);
    if (m.error) {
      check(`${vp.width}px — the matrix is built`, false, m.error);
      continue;
    }

    // NO HORIZONTAL DOCUMENT SCROLL, AT ANY CERTIFIED SIZE. The rule with no
    // pixel in it: whatever the matrix needs, the document may not be wider
    // than the viewport that has to show it.
    check(`${vp.width}px — the document does not scroll sideways`,
      m.doc.sw <= m.doc.cw, `scrollWidth ${m.doc.sw} vs clientWidth ${m.doc.cw}`);
    check(`${vp.width}px — the body does not scroll sideways either`,
      m.doc.bodySW <= m.doc.bodyCW + 1,
      `${m.doc.bodySW} vs ${m.doc.bodyCW}`);
    check(`${vp.width}px — the sheet does not scroll sideways`,
      m.sheet.sw <= m.sheet.cw + 1, `${m.sheet.sw} vs ${m.sheet.cw}`);
    check(`${vp.width}px — the matrix fits inside the viewport`,
      m.matrix.width > 0 && m.matrix.right <= m.doc.cw + 1,
      `right ${m.matrix.right} vs ${m.doc.cw}`);

    const pairs = m.rows.filter((r) => r.acting && r.opponent);
    check(`${vp.width}px — both teams still draw every row`,
      pairs.length === m.rows.length && pairs.length > 0,
      `${pairs.length}/${m.rows.length}`);
    check(`${vp.width}px — the two teams are on the same row`,
      pairs.every((r) => near(r.acting.box.top, r.opponent.box.top)),
      pairs.slice(0, 3).map((r) => `${r.acting.box.top}=${r.opponent.box.top}`).join(' '));
    check(`${vp.width}px — the two teams are at different x`,
      pairs.every((r) => r.opponent.box.left > r.acting.box.left
        && r.acting.box.right <= r.opponent.box.left + 1),
      pairs.slice(0, 3).map((r) => `${r.acting.box.left}→${r.opponent.box.left}`).join(' '));
    check(`${vp.width}px — every cell has real width`,
      pairs.every((r) => r.acting.box.width > 0 && r.opponent.box.width > 0),
      `min ${Math.min(...pairs.flatMap((r) => [r.acting.box.width, r.opponent.box.width]))}px`);

    const vpCells = pairs.flatMap((r) => [r.acting, r.opponent]);
    check(`${vp.width}px — every starter still carries LIVE and PROJ`,
      vpCells.every((c) => c.live && c.proj), `${vpCells.length} cell(s)`);
    check(`${vp.width}px — the type stays at or above the floor`,
      vpCells.every((c) => c.playerSize >= READING_FLOOR
        && c.live.numSize >= READING_FLOOR
        && c.live.labelSize >= TYPE_FLOOR),
      `min label ${Math.min(...vpCells.map((c) => c.live.labelSize))}px`);
  }
});

finish();
