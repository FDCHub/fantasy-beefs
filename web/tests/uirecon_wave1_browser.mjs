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

      // ── THE SHEET CLAUSE, measured while a sheet is actually open ───────
      // The POR permits a sheet to scroll INTERNALLY. What it must not do is
      // make the document or the shell scroll, and it must not widen either.
      const doc = document.documentElement;
      const app = document.querySelector('.fs-app');
      out.sheet = {
        internalScroll: Boolean(sheet)
          && /auto|scroll/.test(getComputedStyle(sheet).overflowY),
        sheetHOverflow: sheet ? sheet.scrollWidth - sheet.clientWidth : null,
        docHOverflow: doc.scrollWidth - doc.clientWidth,
        docVOverflow: doc.scrollHeight - doc.clientHeight,
        appHOverflow: app.scrollWidth - app.clientWidth,
        withinViewport: sheet
          ? sheet.getBoundingClientRect().right <= window.innerWidth + 1
          : null,
      };

      const overlay = document.getElementById('fs-overlay');
      const close = overlay ? overlay.querySelector('[data-fs-close]') : null;
      if (close) close.click();
      return out;
    `);

    check(`the composer opens from a Play card — ${at}`, choice.opened === true);

    // ── Sheets scroll internally and contain themselves ─────────────────
    check(`an open sheet scrolls internally rather than the page — ${at}`,
      choice.sheet.internalScroll === true
      && choice.sheet.docVOverflow <= 0,
      `internal ${choice.sheet.internalScroll}, doc v ${choice.sheet.docVOverflow}`);
    check(`an open sheet never scrolls the document sideways — ${at}`,
      choice.sheet.docHOverflow <= 0 && choice.sheet.appHOverflow <= 0
      && choice.sheet.sheetHOverflow <= 1,
      `doc ${choice.sheet.docHOverflow} app ${choice.sheet.appHOverflow} sheet ${choice.sheet.sheetHOverflow}`);
    check(`and stays inside the viewport width — ${at}`,
      choice.sheet.withinViewport === true);

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
          const body = mod.querySelector('.fs-rescar, .fs-poolrows');
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

    /* FINAL POR §3 SCOPES THIS CLAIM. Status has to fit FOUR sections between
     * the summary strip and the bottom navigation with cards tall enough not
     * to clip; at 375x667 that leaves its headings no room for the gap Play
     * and Wrap Up can afford. The rule is therefore held per tab-shape rather
     * than across all three, and Status is held to its own consistency. */
    const gapPeers = [...gaps.play, ...gaps.wrap];
    const statusGaps = gaps.status;

    check(`no Play or Wrap Up title sits flush against its content — ${at}`,
      gapPeers.every((g) => g.gap > 0),
      gapPeers.map((g) => `${g.where}:${g.gap}`).join(' '));

    check(`one gap for Play and Wrap Up alike — ${at}`,
      gapPeers.every((g) => near(g.gap, gapPeers[0].gap)),
      gapPeers.map((g) => `${g.where}:${g.gap}`).join(' '));

    check(`the Play/Wrap Up gap comes from one declaration — ${at}`,
      gapPeers.every((g) => g.marginBottom === gapPeers[0].marginBottom),
      gapPeers.map((g) => g.marginBottom).join(' / '));

    check(`Status's four rails share one gap of their own — ${at}`,
      statusGaps.length === 0
      || statusGaps.every((g) => near(g.gap, statusGaps[0].gap)),
      statusGaps.map((g) => `${g.where}:${g.gap}`).join(' '));

    check(`Status's four rails share one declaration — ${at}`,
      statusGaps.length === 0
      || statusGaps.every((g) => g.marginBottom === statusGaps[0].marginBottom),
      statusGaps.map((g) => g.marginBottom).join(' / '));

    /* THE TYPE STEP IS STILL SHARED — except at 320x568, where 315px of column
     * cannot hold four 62px cards above four headings at the full step. That
     * is the only viewport §3's budget takes the step from, and it is asserted
     * as a deliberate exception rather than left to drift. */
    const shortViewport = vp.height <= 620;
    check(`section headings share one type step — ${at}`,
      shortViewport
        ? gapPeers.every((g) => g.size === gapPeers[0].size)
          && statusGaps.every((g) => g.size === statusGaps[0].size)
        : allGaps.every((g) => g.size === allGaps[0].size),
      allGaps.map((g) => `${g.where}:${g.size}`).join(' '));

    /* ── 4 · No regression in fit ────────────────────────────────────────── */

    /* ── 4 · The locked app-shell viewport POR ───────────────────────────────
     *
     * The addendum to Wave 1 fixes what the shell may and may not do, and it
     * is a per-TAB contract rather than a per-page one: every clause below is
     * measured on each of the five primary panels, because a primitive that
     * fits on Play and overflows on Wrap Up has still broken it.
     *
     *   no tab-level horizontal scrolling
     *   no new tab-level vertical overflow
     *   the bottom navigation stays visible AND reachable
     *   a carousel scrolls inside its own bounded viewport, and the overflow
     *     does not propagate to the tab or the page
     *   sheets and modals may scroll internally
     *
     * WHY REACHABILITY IS MEASURED WITH `elementFromPoint`. A navigation bar
     * can satisfy every rectangle assertion and still be unusable — covered by
     * an overlay, or pushed under a notch inset. Hit-testing the centre of each
     * tab asks the browser the question a thumb asks. */

    section(`App-shell viewport POR — ${at}`);

    const shell = await evaluate(`
      const PANELS = ['standings', 'league', 'action', 'week', 'ledger'];
      const out = { panels: [] };

      // ── page and shell level ───────────────────────────────────────────
      const doc = document.documentElement;
      out.docHOverflow = doc.scrollWidth - doc.clientWidth;
      out.docVOverflow = doc.scrollHeight - doc.clientHeight;
      const app = document.querySelector('.fs-app');
      const ar = app.getBoundingClientRect();
      out.appHOverflow = app.scrollWidth - app.clientWidth;
      out.appVOverflow = app.scrollHeight - app.clientHeight;
      out.appWithinViewport = ar.right <= window.innerWidth + 1 && ar.left >= -1;

      // ── the bottom navigation ──────────────────────────────────────────
      const bar = document.querySelector('.fs-tabbar');
      const br = bar.getBoundingClientRect();
      out.nav = {
        height: Math.round(br.height * 10) / 10,
        top: Math.round(br.top * 10) / 10,
        bottom: Math.round(br.bottom * 10) / 10,
        viewportH: window.innerHeight,
        // Inside the viewport on both edges, and not zero-height.
        withinViewport: br.height > 0 && br.top >= -1
          && br.bottom <= window.innerHeight + 1,
        // Inside the shell it belongs to.
        withinShell: br.bottom <= ar.bottom + 1,
        display: getComputedStyle(bar).display,
        visibility: getComputedStyle(bar).visibility,
      };
      // REACHABLE, not merely present: hit-test the centre of every tab.
      const unreachable = [];
      for (const item of bar.querySelectorAll('.fs-tabbar__item')) {
        const r = item.getBoundingClientRect();
        const hit = document.elementFromPoint(
          Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2));
        if (!hit || !bar.contains(hit)) {
          unreachable.push(item.dataset.destination + '->' +
            (hit ? (hit.className || hit.tagName) : 'null'));
        }
      }
      out.nav.unreachable = unreachable;

      // ── per-panel ──────────────────────────────────────────────────────
      // A SCROLL REGION IS DECLARED, NOT DISCOVERED. These are the containers
      // the POR permits to scroll; anything else that overflows is a defect
      // rather than a design.
      // UIRECON WAVE 4B — fs-vcar BECAME fs-rescar. Wrap Up's carousel
      // turned horizontal, so the POR still names exactly one scroll region on
      // that tab; only its axis changed. The old class no longer exists, and
      // leaving it here would have declared nothing while the real rail read as
      // undeclared.
      //
      // RC4 MOBILE RECONCILIATION — fs-zones IS DECLARED, AND THAT IS THE
      // WHOLE REPAIR STATED IN ONE LINE.
      //
      // Play used to hold its two sections in a height NEGOTIATION: neither
      // could scroll, so each rail took what its heading left and the Matchup
      // rail came out at 44.52px for a 155px card at 320x568 — clipped exactly
      // where the PROP POOLS heading begins. Play scrolls VERTICALLY now, like
      // Wrap Up's fs-wkscroll beside it in this list, which is what lets both
      // sections present a complete card on a phone too short for both at once.
      // A declared vertical scroll region is the POR's answer to that; an
      // undeclared one is the defect this assertion exists to catch, and this
      // is the declaration.
      const SCROLLERS = ['.fs-carousel', '.fs-rescar', '.fs-rail', '.fs-rails',
                         '.fs-wkscroll', '.fs-zones', '.fs-lscroll',
                         '.fs-st__scroll', '.fs-scroll', '.fs-pools',
                         '.fs-poolrows'];
      for (const id of PANELS) {
        { const tab = document.querySelector(
            '.fs-tabbar__item[data-destination="' + id + '"]');
          if (tab) tab.click(); }
        const panel = document.getElementById('panel-' + id);
        const pr = panel.getBoundingClientRect();
        const cs = getComputedStyle(panel);

        // WHAT THE POR FORBIDS IS A SCROLL CONTAINER NOBODY DECLARED.
        //
        // Not "any element whose scrollWidth exceeds its clientWidth" — that
        // is true of ordinary things the POR has no quarrel with: a table cell
        // reports it as a matter of table layout, a line-clamped Pool name
        // reports it BECAUSE it is clamped, and a text box reports a stray
        // pixel or two from its own descenders. None of those scroll, none of
        // them reach the tab, and an assertion that counted them would fail on
        // correct layout and teach the next reader to ignore it.
        //
        // A container that is overflow:auto or overflow:scroll AND actually
        // overflows is
        // a different thing: it is a region the user can scroll. Every one of
        // those must be a region the POR named.
        const scrollers = [];
        for (const el of panel.querySelectorAll('*')) {
          const hOver = el.scrollWidth - el.clientWidth;
          const vOver = el.scrollHeight - el.clientHeight;
          if (hOver <= 1 && vOver <= 1) continue;
          const style = getComputedStyle(el);
          if (!/auto|scroll/.test(style.overflowX + style.overflowY)) continue;
          scrollers.push({
            cls: (el.className || el.tagName).toString().slice(0, 48),
            h: hOver, v: vOver,
            declared: SCROLLERS.some((s) => el.matches(s)),
          });
        }

        out.panels.push({
          id,
          hOverflow: panel.scrollWidth - panel.clientWidth,
          vOverflow: panel.scrollHeight - panel.clientHeight,
          overflowX: cs.overflowX,
          overflowY: cs.overflowY,
          // The panel must sit entirely above the navigation bar.
          bottom: Math.round(pr.bottom * 10) / 10,
          navTop: Math.round(br.top * 10) / 10,
          clearsNav: pr.bottom <= br.top + 1,
          right: Math.round(pr.right * 10) / 10,
          withinWidth: pr.right <= window.innerWidth + 1 && pr.left >= -1,
          // Scroll regions this panel actually has, and any the POR did not name.
          scrollers,
          undeclared: scrollers.filter((s) => !s.declared),
        });
      }

      // ── a card may not clip its own content ────────────────────────────
      const clipped = [];
      for (const id of ['league', 'action', 'week']) {
        { const tab = document.querySelector(
            '.fs-tabbar__item[data-destination="' + id + '"]');
          if (tab) tab.click(); }
        for (const el of document.querySelectorAll('#panel-' + id + ' .fs-wcard')) {
          if (el.scrollHeight > el.clientHeight + 1) clipped.push(id + ':wcard');
        }
      }
      out.clipped = clipped;
      return out;
    `);

    // ── page and shell ──────────────────────────────────────────────────
    check(`the document never scrolls sideways — ${at}`,
      shell.docHOverflow <= 0, String(shell.docHOverflow));
    check(`the app shell never scrolls sideways — ${at}`,
      shell.appHOverflow <= 0, String(shell.appHOverflow));
    check(`the app shell is not itself a scroll container — ${at}`,
      shell.appVOverflow <= 1, String(shell.appVOverflow));
    check(`the app shell stays inside the viewport width — ${at}`,
      shell.appWithinViewport === true);

    // ── the bottom navigation ───────────────────────────────────────────
    check(`the bottom navigation is drawn — ${at}`,
      shell.nav.height > 0 && shell.nav.display !== 'none'
      && shell.nav.visibility !== 'hidden',
      `${shell.nav.height}px ${shell.nav.display}`);
    check(`it sits wholly inside the viewport — ${at}`,
      shell.nav.withinViewport === true,
      `top ${shell.nav.top} bottom ${shell.nav.bottom} of ${shell.nav.viewportH}`);
    check(`and inside the app shell — ${at}`, shell.nav.withinShell === true);
    check(`every tab is hit-testable, not merely present — ${at}`,
      shell.nav.unreachable.length === 0,
      shell.nav.unreachable.join(', ') || 'all five reachable');

    // ── per-tab ─────────────────────────────────────────────────────────
    check(`no tab scrolls horizontally — ${at}`,
      shell.panels.every((p) => p.hOverflow <= 1),
      shell.panels.map((p) => `${p.id}:${p.hOverflow}`).join(' '));
    check(`no tab overflows vertically past its own box — ${at}`,
      shell.panels.every((p) => p.vOverflow <= 1),
      shell.panels.map((p) => `${p.id}:${p.vOverflow}`).join(' '));
    check(`every tab clears the bottom navigation — ${at}`,
      shell.panels.every((p) => p.clearsNav),
      shell.panels.map((p) => `${p.id}:${p.bottom}/${p.navTop}`).join(' '));
    check(`every tab stays inside the viewport width — ${at}`,
      shell.panels.every((p) => p.withinWidth));

    // ── carousels contain their own overflow ────────────────────────────
    //
    // The containment clause has two halves and both are needed. Every scroll
    // region must be one the POR named — that is this assertion. And a region
    // that scrolls must not make its TAB scroll — that is the two panel-level
    // assertions above, which are what "rather than propagating to the
    // tab/page" actually means, measured on the tab.
    check(`every scrollable region is a declared one — ${at}`,
      shell.panels.every((p) => p.undeclared.length === 0),
      shell.panels.flatMap((p) => p.undeclared
        .map((o) => `${p.id}:${o.cls} h${o.h} v${o.v}`)).join(' | ') || 'none');
    check(`a scrolling region never makes its tab scroll — ${at}`,
      shell.panels.every((p) => p.scrollers.length === 0
        || (p.hOverflow <= 1 && p.vOverflow <= 1)),
      shell.panels.map((p) => `${p.id}:${p.scrollers.length}r/${p.hOverflow}h/${p.vOverflow}v`)
        .join(' '));

    check(`no wager card clips its own content — ${at}`,
      shell.clipped.length === 0, shell.clipped.join(', ') || 'none');
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

  // UIRECON REV 1.4 PART 3 — Play's two headings drop the brand prefix; every
  // other surface keeps the full term (see the Wrap Up check directly below,
  // which is unchanged). Asserted in BOTH directions so a regression that
  // restored the long form is caught as surely as one that shortened the wrong
  // surface.
  // READ FROM THE HEADING ELEMENTS, NOT FROM THE PANEL'S FLATTENED TEXT.
  // `copy.league` is `textContent`, which concatenates across element
  // boundaries with no separator — the sweep above needs that, because a term
  // hiding inside a collapsed disclosure must still be found. It means the
  // Play panel reads `...NO CASH VALUEMATCHUPS1 OPPONENT...`, where a bare
  // `MATCHUPS` has no word boundary on either side. The long form only matched
  // before because its own internal space supplied one.
  //
  // The claim is about two HEADINGS, so it is asserted against the headings.
  const playHeadings = await evaluate(`
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    return [...document.querySelectorAll('#panel-league .fs-heading__text')]
      .map((el) => el.textContent.trim());
  `);

  check('Play uses the Rev 1.4 short Matchups heading',
    playHeadings.includes('MATCHUPS')
    && !playHeadings.some((t) => t.startsWith('FANTASYSTAKES')),
    playHeadings.join(' | '));

  check('Play uses the Rev 1.4 short Prop Pools heading',
    playHeadings.includes('PROP POOLS')
    && !copy.league.includes('FANTASYSTAKES PROP POOLS'),
    playHeadings.join(' | '));

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
