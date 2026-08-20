/* ============================================================================
 * FantasyStakes — UIRECON Wave 1 · shared primitives · browser suite
 *
 * Run directly:   node web/tests/uirecon_wave1_browser.mjs
 * Or through:     python test_uirecon_wave1.py
 *
 * WHAT THIS SUITE IS FOR. Wave 1 established four shared primitives — the
 * metric cell, the choice cell, the section-heading gap and the canonical token
 * layer — and the whole point of a primitive is that peers cannot drift apart
 * again. A component suite can prove the markup is shared; only a browser can
 * prove the RENDERED GEOMETRY is, because that is where the cascade, the media
 * queries and the grid actually resolve.
 *
 * So every assertion here is a measurement of computed layout, and the ones
 * that matter most are comparisons BETWEEN peers rather than absolute numbers:
 * four cells that are equal to each other, a market cell and a terms cell that
 * are the same control, five section headings that leave the same gap. An
 * absolute pixel value would pin this build; a peer comparison pins the rule.
 *
 * VIEWPORTS. 375x667 and 390x844 are the phone sizes the reconciliation brief
 * names, and 768 and 1024 are the tablet/desktop widths where the app's 480px
 * frame is centred rather than stretched — a layout that only works on a phone
 * is not a layout that works. 320x568 is included because it is the smallest
 * size the existing Rev 4.3 certification measures, and it is the width that
 * decided the strip labels: the one-line budget is a 68px cell there.
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

/** Round to one decimal — sub-pixel noise is not a difference. */
const R1 = (n) => Math.round(n * 10) / 10;

/** Two measurements are the same if they agree to within a device pixel. */
const near = (a, b, tol = 1) => Math.abs(a - b) <= tol;

/* A tab switch, as a statement that can appear more than once in one
 * `evaluate` — hence the block, which keeps `tab` from colliding with itself. */
const GO = (id) => `
  { const tab = document.querySelector('.fs-tabbar__item[data-destination="${id}"]');
    if (tab) tab.click(); }
`;

/**
 * Wait until the application has actually mounted its panels.
 *
 * `setViewport` re-navigates so the metrics override applies to a fresh load,
 * and the shell asks `/auth/me` and its read models before it draws anything —
 * so a fixed settle is a race, not a guarantee. It lost that race here at the
 * second viewport and reported "no strips" as though the primitive had failed.
 * Polling for the thing about to be measured is the honest wait.
 */
const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 8000;
    const poll = () => {
      const mounted = document.querySelector('.fs-tabbar__item')
        && document.querySelector('#panel-league .fs-strip__cell');
      if (mounted || Date.now() > deadline) return resolve(Boolean(mounted));
      setTimeout(poll, 100);
    };
    poll();
  });
`;

await withPage({ port: 9411 }, async ({ evaluate, setViewport }) => {
  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    const at = `${vp.width}x${vp.height}`;
    check(`the application mounted — ${at}`, await evaluate(READY) === true);

    /* ── 1 · The metric cell ─────────────────────────────────────────────── */

    section(`Metric cell — ${at} (${vp.label})`);

    // Every strip in the product, not just Play's: the primitive's whole claim
    // is that Play, Status and Account's two strips are one construction.
    const strips = await evaluate(`
      ${GO('league')}
      const read = (panelId) => [...document.querySelectorAll(panelId + ' .fs-strip')]
        .map(strip => ({
          id: strip.id,
          cells: [...strip.querySelectorAll('.fs-strip__cell')].map(cell => {
            const label = cell.querySelector('.fs-strip__label');
            const value = cell.querySelector('.fs-strip__value');
            const cr = cell.getBoundingClientRect();
            const lr = label.getBoundingClientRect();
            const vr = value.getBoundingClientRect();
            const ls = getComputedStyle(label);
            const vs = getComputedStyle(value);
            return {
              text: label.textContent,
              w: Math.round(cr.width * 10) / 10,
              h: Math.round(cr.height * 10) / 10,
              // A label on one line is exactly one line-height tall.
              labelH: Math.round(lr.height * 10) / 10,
              lineH: Math.round(parseFloat(ls.lineHeight) * 10) / 10,
              // Does the label's own text overflow the box it is allowed?
              labelOverflows: label.scrollWidth > label.clientWidth + 1,
              labelWhiteSpace: ls.whiteSpace,
              // Offsets of each element's centre from the cell's centre.
              labelDx: Math.round(((lr.left + lr.width / 2) - (cr.left + cr.width / 2)) * 10) / 10,
              valueDx: Math.round(((vr.left + vr.width / 2) - (cr.left + cr.width / 2)) * 10) / 10,
              // The value box occupies everything under the label; its CONTENT
              // is what has to sit in the middle of it.
              valueBoxTop: Math.round(vr.top * 10) / 10,
              valueBoxBottom: Math.round(vr.bottom * 10) / 10,
              valueAlign: vs.alignItems,
              valueJustify: vs.justifyContent,
              labelBottom: Math.round(lr.bottom * 10) / 10,
              cellBottom: Math.round(cr.bottom * 10) / 10,
              labelSize: ls.fontSize,
              valueSize: vs.fontSize,
              valueFamily: vs.fontFamily,
            };
          }),
        }));
      const out = { league: read('#panel-league') };
      ${GO('action')} out.action = read('#panel-action');
      ${GO('ledger')} out.ledger = read('#panel-ledger');
      return out;
    `);

    const allStrips = [...strips.league, ...strips.action, ...strips.ledger];

    check(`every strip has exactly four cells — ${at}`,
      allStrips.length > 0 && allStrips.every((s) => s.cells.length === 4),
      allStrips.map((s) => `${s.id || '?'}:${s.cells.length}`).join(' '));

    check(`the four cells are equal width — ${at}`,
      allStrips.every((s) => {
        const w = s.cells.map((c) => c.w);
        return w.every((x) => near(x, w[0]));
      }),
      allStrips.map((s) => s.cells.map((c) => c.w).join('/')).join('  '));

    // The wrap guard, stated two ways: the box is one line high, and the text
    // inside it is not being clipped to make that true.
    check(`no label wraps to a second line — ${at}`,
      allStrips.every((s) => s.cells.every((c) => near(c.labelH, c.lineH, 1.5))),
      allStrips.flatMap((s) => s.cells
        .filter((c) => !near(c.labelH, c.lineH, 1.5))
        .map((c) => `${c.text} ${c.labelH}/${c.lineH}`)).join(', ') || 'all one line');

    check(`no label is ellipsized to fit — ${at}`,
      allStrips.every((s) => s.cells.every((c) => !c.labelOverflows)),
      allStrips.flatMap((s) => s.cells
        .filter((c) => c.labelOverflows).map((c) => c.text)).join(', ') || 'none');

    check(`the no-wrap rule is the primitive's, not a screen's — ${at}`,
      allStrips.every((s) => s.cells.every((c) => c.labelWhiteSpace === 'nowrap')));

    check(`labels are centred horizontally in their cell — ${at}`,
      allStrips.every((s) => s.cells.every((c) => near(c.labelDx, 0))),
      allStrips.flatMap((s) => s.cells
        .filter((c) => !near(c.labelDx, 0)).map((c) => `${c.text} ${c.labelDx}`)).join(', ') || 'all centred');

    check(`values are centred horizontally in their cell — ${at}`,
      allStrips.every((s) => s.cells.every((c) => near(c.valueDx, 0))),
      allStrips.flatMap((s) => s.cells
        .filter((c) => !near(c.valueDx, 0)).map((c) => `${c.text} ${c.valueDx}`)).join(', ') || 'all centred');

    // VERTICAL CENTRING, MEASURED RATHER THAN DECLARED. The value box fills
    // everything between the label and the bottom of the cell's content area,
    // and centres its content inside that box. Asserting the box fills the
    // remainder is what makes `align-items: center` mean "centred in the cell"
    // rather than "centred in whatever height the text happened to take".
    check(`the value box takes the whole cell below the label — ${at}`,
      allStrips.every((s) => s.cells.every((c) =>
        c.valueBoxTop >= c.labelBottom - 1
        && c.valueBoxBottom <= c.cellBottom + 1
        && (c.valueBoxBottom - c.valueBoxTop) > 0)));

    check(`and centres its content on both axes — ${at}`,
      allStrips.every((s) => s.cells.every((c) =>
        c.valueAlign === 'center' && c.valueJustify === 'center')));

    check(`every strip shares one typography — ${at}`,
      allStrips.every((s) => s.cells.every((c) =>
        c.labelSize === allStrips[0].cells[0].labelSize
        && c.valueSize === allStrips[0].cells[0].valueSize
        && c.valueFamily === allStrips[0].cells[0].valueFamily)),
      `${allStrips[0].cells[0].labelSize} / ${allStrips[0].cells[0].valueSize}`);

    check(`values are the canonical monospace number face — ${at}`,
      /mono/i.test(allStrips[0].cells[0].valueFamily),
      allStrips[0].cells[0].valueFamily);

    /* ── 2 · The choice cell ─────────────────────────────────────────────── */

    section(`Choice cell — ${at}`);

    // The market cells on a Play card and the market / terms cells inside the
    // composer are the same control. Opening the composer is how the two are
    // brought into one measurement.
    const choice = await evaluate(`
      ${GO('league')}
      const shape = (el) => {
        if (!el) return null;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        const label = el.querySelector('.fs-market__label, .fs-seg__label');
        const value = el.querySelector('.fs-market__value, .fs-seg__value');
        const ls = label ? getComputedStyle(label) : null;
        const vs = value ? getComputedStyle(value) : null;
        return {
          h: Math.round(r.height * 10) / 10,
          radius: s.borderTopLeftRadius,
          minHeight: s.minHeight,
          direction: s.flexDirection,
          align: s.alignItems,
          justify: s.justifyContent,
          border: s.borderTopWidth,
          background: s.backgroundColor,
          labelSize: ls ? ls.fontSize : null,
          labelWeight: ls ? ls.fontWeight : null,
          labelColor: ls ? ls.color : null,
          valueSize: vs ? vs.fontSize : null,
          valueFamily: vs ? vs.fontFamily : null,
        };
      };
      const out = {};
      out.playMarket = shape(document.querySelector('#panel-league .fs-market'));
      // Open the composer from the first Play card's own control.
      const card = document.querySelector('#panel-league [data-card-challenge]');
      if (card) card.click();
      const sheet = document.getElementById('fs-sheet');
      out.opened = Boolean(sheet && sheet.querySelector('.fs-seg__opt'));
      out.composerMarket = shape(document.querySelector('.fs-seg--market .fs-seg__opt'));
      // LOCKED is selected by default, so an unselected cell is the fair
      // sample for the resting treatment; the selected one is measured
      // separately below.
      out.composerMode = shape(
        document.querySelector('.fs-seg--mode .fs-seg__opt:not(.is-selected)'));
      // Selected-state parity: what the gold treatment does to each.
      const sel = (el) => {
        if (!el) return null;
        const s = getComputedStyle(el);
        return { bg: s.backgroundColor, border: s.borderTopColor };
      };
      out.selectedMode = sel(document.querySelector('.fs-seg--mode .fs-seg__opt.is-selected'));
      const overlay = document.getElementById('fs-overlay');
      const close = overlay ? overlay.querySelector('[data-fs-close]') : null;
      if (close) close.click();
      return out;
    `);

    check(`the composer opens from a Play card — ${at}`, choice.opened === true);

    const peers = [choice.playMarket, choice.composerMarket, choice.composerMode]
      .filter(Boolean);

    check(`all three choice-cell consumers render — ${at}`, peers.length === 3,
      `${peers.length}/3`);

    check(`peers share one border radius — ${at}`,
      peers.every((p) => p.radius === peers[0].radius),
      peers.map((p) => p.radius).join(' / '));

    check(`peers share one min-height — ${at}`,
      peers.every((p) => p.minHeight === peers[0].minHeight),
      peers.map((p) => p.minHeight).join(' / '));

    check(`peers meet the 44px tappable floor — ${at}`,
      peers.every((p) => parseFloat(p.minHeight) >= 44),
      peers.map((p) => p.minHeight).join(' / '));

    check(`peers share one label typography — ${at}`,
      peers.every((p) => p.labelSize === peers[0].labelSize
        && p.labelWeight === peers[0].labelWeight),
      peers.map((p) => `${p.labelSize}/${p.labelWeight}`).join(' / '));

    // Rev 4.3 SS5.1 classifies a market label as CARD SECONDARY text, and
    // WP3C's certification asserts the 14px floor directly. Wave 1 raised the
    // composer's segment label to meet the Play card rather than the reverse.
    check(`labels clear the Rev 4.3 card-secondary floor — ${at}`,
      peers.every((p) => parseFloat(p.labelSize) >= 14),
      peers.map((p) => p.labelSize).join(' / '));

    check(`peers share one unselected ground and border — ${at}`,
      peers.every((p) => p.background === peers[0].background
        && p.border === peers[0].border),
      peers.map((p) => p.background).join(' / '));

    check(`peers centre their content on both axes — ${at}`,
      peers.every((p) => p.direction === 'column'
        && p.align === 'center' && p.justify === 'center'),
      peers.map((p) => `${p.direction}/${p.align}/${p.justify}`).join(' '));

    // A market cell carries a line and a terms cell does not; where BOTH carry
    // a value it must be drawn the same way.
    const valued = peers.filter((p) => p.valueSize);
    check(`a value, wherever it appears, is one treatment — ${at}`,
      valued.length > 0 && valued.every((p) => p.valueSize === valued[0].valueSize
        && p.valueFamily === valued[0].valueFamily),
      valued.map((p) => p.valueSize).join(' / '));

    check(`the selected state is the gold treatment — ${at}`,
      choice.selectedMode !== null
      && choice.selectedMode.bg !== peers[0].background
      && choice.selectedMode.border !== peers[0].border,
      JSON.stringify(choice.selectedMode));

    /* ── 3 · The section-heading gap ─────────────────────────────────────── */

    section(`Section heading gap — ${at}`);

    const gaps = await evaluate(`
      const measure = (root, pairs) => pairs.map(([sel, contentSel]) => {
        const head = root.querySelector(sel + ' .fs-heading');
        const body = root.querySelector(sel + ' ' + contentSel);
        if (!head || !body) return null;
        const hs = getComputedStyle(head);
        return {
          where: sel,
          gap: Math.round((body.getBoundingClientRect().top
                           - head.getBoundingClientRect().bottom) * 10) / 10,
          marginBottom: hs.marginBottom,
          size: getComputedStyle(head.querySelector('.fs-heading__text')).fontSize,
        };
      }).filter(Boolean);
      const out = {};
      ${GO('league')}
      out.play = measure(document.getElementById('panel-league'),
        [['.fs-zone--bets', '.fs-carousel, .fs-emptyzone'],
         ['.fs-zone--pools', '.fs-pools, .fs-emptyzone']]);
      ${GO('action')}
      out.status = [...document.querySelectorAll('#panel-action .fs-railsec')]
        .map(sec => {
          const head = sec.querySelector('.fs-heading');
          const body = sec.querySelector('.fs-rail');
          if (!head || !body) return null;
          return {
            where: sec.dataset.rail,
            gap: Math.round((body.getBoundingClientRect().top
                             - head.getBoundingClientRect().bottom) * 10) / 10,
            marginBottom: getComputedStyle(head).marginBottom,
            size: getComputedStyle(head.querySelector('.fs-heading__text')).fontSize,
          };
        }).filter(Boolean);
      ${GO('week')}
      out.wrap = [...document.querySelectorAll('#panel-week .fs-wkmod')]
        .map(mod => {
          const head = mod.querySelector('.fs-heading');
          const body = mod.querySelector('.fs-vcar, .fs-poolrows');
          if (!head || !body) return null;
          return {
            where: mod.dataset.module,
            gap: Math.round((body.getBoundingClientRect().top
                             - head.getBoundingClientRect().bottom) * 10) / 10,
            marginBottom: getComputedStyle(head).marginBottom,
            size: getComputedStyle(head.querySelector('.fs-heading__text')).fontSize,
          };
        }).filter(Boolean);
      return out;
    `);

    const allGaps = [...gaps.play, ...gaps.status, ...gaps.wrap];

    check(`every section heading was measured — ${at}`, allGaps.length >= 5,
      `${allGaps.length} sections`);

    check(`no section title sits flush against its content — ${at}`,
      allGaps.every((g) => g.gap > 0),
      allGaps.map((g) => `${g.where}:${g.gap}`).join(' '));

    check(`one gap for Play, Status and Wrap Up alike — ${at}`,
      allGaps.every((g) => near(g.gap, allGaps[0].gap)),
      allGaps.map((g) => `${g.where}:${g.gap}`).join(' '));

    check(`the gap comes from one declaration — ${at}`,
      allGaps.every((g) => g.marginBottom === allGaps[0].marginBottom),
      allGaps.map((g) => g.marginBottom).join(' / '));

    check(`section headings share one type step — ${at}`,
      allGaps.every((g) => g.size === allGaps[0].size),
      allGaps.map((g) => `${g.where}:${g.size}`).join(' '));

    /* ── 4 · No regression in fit ────────────────────────────────────────── */

    section(`Fit and clipping — ${at}`);

    const fit = await evaluate(`
      const out = {};
      out.hOverflow = document.documentElement.scrollWidth
        - document.documentElement.clientWidth;
      const tabbar = document.querySelector('.fs-tabbar');
      const app = document.querySelector('.fs-app');
      out.tabbarVisible = Boolean(tabbar)
        && tabbar.getBoundingClientRect().bottom
           <= app.getBoundingClientRect().bottom + 1;
      // A card may be taller than its rail — the rail scrolls, which is the
      // certified carousel behaviour. What may NOT happen is a card clipping
      // its OWN content, which is the 375x667 regression this wave had to
      // avoid recreating.
      const clipped = [];
      ${GO('league')}
      for (const el of document.querySelectorAll('#panel-league .fs-wcard')) {
        if (el.scrollHeight > el.clientHeight + 1) clipped.push('play:' + el.className);
      }
      ${GO('action')}
      for (const el of document.querySelectorAll('#panel-action .fs-wcard')) {
        if (el.scrollHeight > el.clientHeight + 1) clipped.push('status:' + el.className);
      }
      out.clipped = clipped;
      return out;
    `);

    check(`the page never scrolls sideways — ${at}`, fit.hOverflow <= 0,
      String(fit.hOverflow));
    check(`the bottom navigation is not pushed off — ${at}`, fit.tabbarVisible);
    check(`no wager card clips its own content — ${at}`, fit.clipped.length === 0,
      fit.clipped.join(', ') || 'none');
  }

  /* ── 5 · Terminology, on the rendered surfaces ──────────────────────────── */

  section('Public terminology — the locked vocabulary, as rendered');

  await setViewport(390, 844);
  check('the application mounted for the terminology sweep',
    await evaluate(READY) === true);

  const copy = await evaluate(`
    const out = {};
    // textContent, NOT innerText. Account's accounting groups sit inside
    // collapsed disclosures, so innerText reports only what is currently
    // painted and a stale term hiding one tap away would pass the sweep.
    // (No backticks in this comment: it lives inside a template literal.)
    const text = (id) => {
      const t = document.querySelector('.fs-tabbar__item[data-destination="' + id + '"]');
      if (t) t.click();
      const p = document.getElementById('panel-' + id);
      return p ? p.textContent : '';
    };
    out.league = text('league');
    out.action = text('action');
    out.week = text('week');
    out.ledger = text('ledger');
    out.standings = text('standings');
    return out;
  `);

  const surfaces = Object.entries(copy);

  check('no public-facing Versus on any primary tab',
    surfaces.every(([, t]) => !/versus/i.test(t)),
    surfaces.filter(([, t]) => /versus/i.test(t)).map(([k]) => k).join(', ') || 'none');

  check('Play names FantasyStakes Matchups on first reference',
    /FANTASYSTAKES MATCHUPS/.test(copy.league), '');

  check('Play names FantasyStakes Prop Pools on first reference',
    /FANTASYSTAKES PROP POOLS/.test(copy.league), '');

  check('Wrap Up names both FantasyStakes surfaces with the locked terms',
    /FANTASYSTAKES MATCHUPS/.test(copy.week)
    && /FANTASYSTAKES PROP POOLS/.test(copy.week), '');

  check('Account groups activity under the locked terms',
    /MATCHUP ACTIVITY/.test(copy.ledger)
    && /PROP POOL ACTIVITY/.test(copy.ledger), '');

  check('Standings keeps FantasyStakes Championship',
    /FANTASYSTAKES CHAMPIONSHIP/.test(copy.standings), '');

  // A bare "Pools" heading would be the pre-Wave-1 wording surviving somewhere.
  check('no bare FANTASYSTAKES POOLS heading remains',
    surfaces.every(([, t]) => !/FANTASYSTAKES POOLS/.test(t)),
    surfaces.filter(([, t]) => /FANTASYSTAKES POOLS/.test(t)).map(([k]) => k).join(', ') || 'none');
});

finish();
