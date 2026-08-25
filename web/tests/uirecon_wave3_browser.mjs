/* ============================================================================
 * FantasyStakes — UIRECON Wave 3 · wager parity and Prop Pool selection
 *
 * Run directly:   node web/tests/uirecon_wave3_browser.mjs
 * Or through:     python test_uirecon_wave3.py
 *
 * WAVE 3A — THE CARD MUST APPEAR STATIONARY.
 *
 * A GM moving Moneyline → Spread → Over/Under should feel that only the market
 * data changed. Measured before this wave, against a priced pairing at 390x844,
 * every slot below the market selector moved:
 *
 *                        ML     SPR     O/U
 *     Locked / Dynamic   259     322     345
 *     stake control      447     510     533
 *     Send Challenge     645     708     731
 *
 * Eighty-six pixels of travel on the control that spends Credits. So the
 * assertions here are not "each market renders correctly" — they are that the
 * three renderings are the SAME RECTANGLE. Every slot is captured for all three
 * markets and compared to the others, at one-pixel tolerance.
 *
 * WAVE 3B — THE PROP POOL PICK MUST BE MAKEABLE.
 *
 * The governed claim path was always sound: subjects are served, the census is
 * the engine's, and `submit_claim` refuses anything it should. What was wrong
 * was the surface — an unstyled native `<select>` captioned with the census
 * scope enum. The guards below check that the choice is served, selectable,
 * visible in `Your pick`, and that pressing Submit sends the SERVED subject id.
 *
 * A NOTE ON WHAT IS NOT ASSERTED. No absolute pixel value for any slot. Wave 3
 * makes the card taller than it was — three fixed slots cost more than three
 * collapsing ones — and pinning a height would fail the next legitimate change.
 * What is pinned is that the three markets agree with each other.
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

/** Every slot the brief names, in card order. */
const SLOTS = [
  ['B · market selector', '.fs-seg--market'],
  ['C/D/F · market block', '[data-market-detail]'],
  ['F · side control', '.fs-seg--side'],
  ['E · Locked / Dynamic', '.fs-seg--mode'],
  ['E · terms explanation', '.fs-modenote'],
  ['G · stake control', '.fs-stake'],
  ['G · economics', '.fs-econ'],
  ['H · primary action', '.fs-send__btn'],
  ['I · status / helper', '.fs-send__why'],
];

/** Read one slot's rectangle relative to the scrolled sheet. */
const MEASURE = `
  const sheet = document.getElementById('fs-sheet');
  const sr = sheet.getBoundingClientRect();
  const rect = (sel) => {
    const el = sheet.querySelector(sel);
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return {
      t: Math.round((b.top - sr.top + sheet.scrollTop) * 10) / 10,
      l: Math.round((b.left - sr.left) * 10) / 10,
      w: Math.round(b.width * 10) / 10,
      h: Math.round(b.height * 10) / 10,
    };
  };
`;

await withPage({ port: 9461 }, async ({ evaluate, setViewport }) => {
  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    const at = `${vp.width}x${vp.height}`;
    check(`the application mounted — ${at}`, await evaluate(READY) === true);

    /* ── 3A · The matchup wager card ─────────────────────────────────────── */

    section(`Matchup card parity — ${at} (${vp.label})`);

    // THE PRICED PAIRING IS THE ONE WORTH MEASURING. An unpriceable matchup
    // renders the same refusal for all three markets, so parity across it is
    // true and uninteresting; the seeded board gives a real moneyline, a signed
    // spread and a total, which is where the drift lived.
    const opened = await evaluate(`
      { const t = document.querySelector('.fs-tabbar__item[data-destination="league"]');
        if (t) t.click(); }
      const cards = [...document.querySelectorAll('#panel-league .fs-wcard--matchup')];
      const priced = cards.find((c) => [...c.querySelectorAll('.fs-market__value')]
        .some((v) => v.textContent.trim() !== '—' && v.textContent.trim() !== 'Play ›'));
      const target = priced || cards[0];
      if (!target) return 'no card';
      target.querySelector('[data-card-challenge]').click();
      const sheet = document.getElementById('fs-sheet');
      return sheet && sheet.querySelector('.fs-seg--market')
        ? (priced ? 'priced' : 'unpriced') : 'no composer';
    `);
    check(`the composer opens from a Play card — ${at}`,
      opened === 'priced' || opened === 'unpriced', String(opened));
    check(`and a priced pairing was available to measure — ${at}`,
      opened === 'priced', String(opened));

    // ── the three market states, captured ──
    const states = {};
    for (const market of ['ml', 'spread', 'ou']) {
      /* eslint-disable no-await-in-loop */
      states[market] = await evaluate(`
        const btn = document.querySelector(
          '.fs-seg--market [data-composer-market="${market}"]');
        if (btn) btn.click();
        ${MEASURE}
        const out = { slots: {}, outer: null, scrollH: sheet.scrollHeight,
                      clientH: sheet.clientHeight };
        out.outer = { w: Math.round(sr.width * 10) / 10,
                      h: Math.round(sr.height * 10) / 10,
                      t: Math.round(sr.top * 10) / 10,
                      l: Math.round(sr.left * 10) / 10 };
        for (const [, sel] of ${JSON.stringify(SLOTS)}) out.slots[sel] = rect(sel);
        const cells = [...sheet.querySelectorAll('.fs-seg--market .fs-seg__opt')];
        out.marketCells = cells.map((c) => {
          const b = c.getBoundingClientRect();
          const label = c.querySelector('.fs-seg__label');
          const ls = getComputedStyle(label);
          const cs = getComputedStyle(c);
          return {
            text: label.textContent,
            w: Math.round(b.width * 10) / 10, h: Math.round(b.height * 10) / 10,
            size: ls.fontSize, weight: ls.fontWeight,
            radius: cs.borderTopLeftRadius, minH: cs.minHeight,
            align: cs.alignItems, justify: cs.justifyContent,
            pressed: c.getAttribute('aria-pressed'),
            lines: label.getBoundingClientRect().height
              < parseFloat(ls.fontSize) * 1.8 ? 1 : 2,
          };
        });
        out.detailKind = (sheet.querySelector('[data-market-detail]') || {})
          .dataset ? sheet.querySelector('[data-market-detail]').dataset.marketDetail : null;
        return out;
      `);
      /* eslint-enable no-await-in-loop */
    }

    const M = ['ml', 'spread', 'ou'];
    const ref = states.ml;

    check(`each market renders its own block — ${at}`,
      M.every((m) => states[m].detailKind !== null)
      && new Set(M.map((m) => states[m].detailKind)).size === 3,
      M.map((m) => `${m}:${states[m].detailKind}`).join(' '));

    // ── OUTER CARD: the thing a GM sees move ──
    check(`the card's outer width never changes — ${at}`,
      M.every((m) => near(states[m].outer.w, ref.outer.w)),
      M.map((m) => states[m].outer.w).join(' / '));
    check(`the card's outer height never changes — ${at}`,
      M.every((m) => near(states[m].outer.h, ref.outer.h)),
      M.map((m) => states[m].outer.h).join(' / '));
    check(`the card never moves on screen — ${at}`,
      M.every((m) => near(states[m].outer.t, ref.outer.t)
        && near(states[m].outer.l, ref.outer.l)),
      M.map((m) => `${states[m].outer.t},${states[m].outer.l}`).join(' / '));
    check(`and its scroll extent never changes — ${at}`,
      M.every((m) => near(states[m].scrollH, ref.scrollH)),
      M.map((m) => states[m].scrollH).join(' / '));

    // ── EVERY SLOT, INDIVIDUALLY ──
    for (const [name, sel] of SLOTS) {
      const present = M.filter((m) => states[m].slots[sel] !== null);
      check(`${name} exists in all three markets — ${at}`,
        present.length === 3, `${present.length}/3 (${present.join(',')})`);
      if (present.length !== 3) continue;
      check(`${name} never moves vertically — ${at}`,
        M.every((m) => near(states[m].slots[sel].t, ref.slots[sel].t)),
        M.map((m) => states[m].slots[sel].t).join(' / '));
      check(`${name} never moves horizontally or resizes — ${at}`,
        M.every((m) => near(states[m].slots[sel].l, ref.slots[sel].l)
          && near(states[m].slots[sel].w, ref.slots[sel].w)
          && near(states[m].slots[sel].h, ref.slots[sel].h)),
        M.map((m) => `${states[m].slots[sel].l},${states[m].slots[sel].w}x${states[m].slots[sel].h}`).join(' / '));
    }

    /* ── The market selector as peer cells ───────────────────────────────── */

    const cells = ref.marketCells;
    check(`the market selector offers three cells — ${at}`, cells.length === 3,
      cells.map((c) => c.text).join(' | '));
    check(`with the locked public wording — ${at}`,
      cells.map((c) => c.text).join('|') === 'Moneyline|Spread|Over/Under',
      cells.map((c) => c.text).join('|'));
    check(`they are equal in size — ${at}`,
      cells.every((c) => near(c.w, cells[0].w) && near(c.h, cells[0].h)),
      cells.map((c) => `${c.w}x${c.h}`).join(' / '));
    check(`share one typography — ${at}`,
      cells.every((c) => c.size === cells[0].size && c.weight === cells[0].weight),
      `${cells[0].size}/${cells[0].weight}`);
    check(`share one radius and one touch floor — ${at}`,
      cells.every((c) => c.radius === cells[0].radius && c.minH === cells[0].minH)
      && parseFloat(cells[0].minH) >= 44,
      `${cells[0].radius} ${cells[0].minH}`);
    check(`centre their content on both axes — ${at}`,
      cells.every((c) => c.align === 'center' && c.justify === 'center'));
    check(`and hold their labels to one line — ${at}`,
      cells.every((c) => c.lines <= 1), cells.map((c) => c.lines).join('/'));
    // SELECTING MUST NOT RESIZE THE CELL. Compared across the three captures,
    // in each of which a different cell is the selected one.
    check(`selecting a market never resizes any cell — ${at}`,
      M.every((m) => states[m].marketCells.every(
        (c, i) => near(c.w, cells[i].w) && near(c.h, cells[i].h))),
      M.map((m) => states[m].marketCells.map((c) => `${c.w}x${c.h}`).join(',')).join(' | '));
    check(`exactly one market cell is pressed at a time — ${at}`,
      M.every((m) => states[m].marketCells
        .filter((c) => c.pressed === 'true').length === 1));

    /* ── Locked / Dynamic as peer cells ──────────────────────────────────── */

    section(`Locked / Dynamic parity — ${at}`);

    const modes = {};
    for (const mode of ['locked', 'dynamic']) {
      /* eslint-disable no-await-in-loop */
      modes[mode] = await evaluate(`
        const btn = document.querySelector('[data-composer-mode="${mode}"]');
        if (btn) btn.click();
        ${MEASURE}
        const out = { slots: {}, cells: [] };
        for (const [, sel] of ${JSON.stringify(SLOTS)}) out.slots[sel] = rect(sel);
        out.cells = [...sheet.querySelectorAll('.fs-seg--mode .fs-seg__opt')].map((c) => {
          const b = c.getBoundingClientRect();
          const cs = getComputedStyle(c);
          const label = c.querySelector('.fs-seg__label');
          const ls = getComputedStyle(label);
          return {
            text: label.textContent,
            w: Math.round(b.width * 10) / 10, h: Math.round(b.height * 10) / 10,
            radius: cs.borderTopLeftRadius, minH: cs.minHeight,
            padding: cs.paddingTop + '/' + cs.paddingLeft,
            align: cs.alignItems, justify: cs.justifyContent,
            size: ls.fontSize, weight: ls.fontWeight,
            pressed: c.getAttribute('aria-pressed'),
            bg: cs.backgroundColor, border: cs.borderTopColor,
          };
        });
        return out;
      `);
      /* eslint-enable no-await-in-loop */
    }

    const L = modes.locked.cells;
    const D = modes.dynamic.cells;

    check(`Locked and Dynamic are two cells — ${at}`, L.length === 2,
      L.map((c) => c.text).join('|'));
    check(`identical in size — ${at}`,
      near(L[0].w, L[1].w) && near(L[0].h, L[1].h),
      `${L[0].w}x${L[0].h} / ${L[1].w}x${L[1].h}`);
    check(`identical border, radius and padding — ${at}`,
      L[0].radius === L[1].radius && L[0].minH === L[1].minH
      && L[0].padding === L[1].padding,
      `${L[0].radius} ${L[0].minH} ${L[0].padding}`);
    check(`both centre their content on both axes — ${at}`,
      L.every((c) => c.align === 'center' && c.justify === 'center'));
    check(`identical typography — ${at}`,
      L[0].size === L[1].size && L[0].weight === L[1].weight);
    // THE SELECTED TREATMENT IS ONE TREATMENT, whichever cell holds it.
    const lockedSel = L.find((c) => c.pressed === 'true');
    const dynamicSel = D.find((c) => c.pressed === 'true');
    check(`selecting either mode gives the same treatment — ${at}`,
      Boolean(lockedSel) && Boolean(dynamicSel)
      && lockedSel.bg === dynamicSel.bg && lockedSel.border === dynamicSel.border,
      `${lockedSel && lockedSel.bg} / ${dynamicSel && dynamicSel.bg}`);
    check(`and never resizes the cell it lands on — ${at}`,
      L.every((c, i) => near(c.w, D[i].w) && near(c.h, D[i].h)),
      L.map((c, i) => `${c.w}x${c.h} vs ${D[i].w}x${D[i].h}`).join(' | '));

    // CHANGING MODE MOVES NOTHING ELSE — the §4 requirement, slot by slot.
    for (const [name, sel] of SLOTS) {
      const a = modes.locked.slots[sel];
      const b = modes.dynamic.slots[sel];
      if (!a || !b) continue;
      check(`${name} does not move when terms change — ${at}`,
        near(a.t, b.t) && near(a.h, b.h),
        `${a.t}:${a.h} vs ${b.t}:${b.h}`);
    }

    /* ── The shell POR, with the composer open ───────────────────────────── */

    const shell = await evaluate(`
      const doc = document.documentElement;
      const sheet = document.getElementById('fs-sheet');
      const bar = document.querySelector('.fs-tabbar');
      const br = bar.getBoundingClientRect();
      const out = {
        docH: doc.scrollWidth - doc.clientWidth,
        docV: doc.scrollHeight - doc.clientHeight,
        sheetScrollsInternally: /auto|scroll/.test(getComputedStyle(sheet).overflowY),
        sheetH: sheet.scrollWidth - sheet.clientWidth,
        // The card must never clip its OWN content: it scrolls, or it fits.
        cardClips: sheet.scrollHeight > sheet.clientHeight
          && !/auto|scroll/.test(getComputedStyle(sheet).overflowY),
        navVisible: br.height > 0 && br.bottom <= window.innerHeight + 1,
      };
      const close = document.querySelector('#fs-overlay [data-fs-close]');
      if (close) close.click();
      return out;
    `);

    check(`the document never scrolls sideways with the card open — ${at}`,
      shell.docH <= 0, String(shell.docH));
    check(`the card scrolls internally rather than the page — ${at}`,
      shell.sheetScrollsInternally === true && shell.docV <= 0,
      `internal ${shell.sheetScrollsInternally}, doc v ${shell.docV}`);
    check(`the card never scrolls sideways — ${at}`, shell.sheetH <= 1,
      String(shell.sheetH));
    check(`and never clips its own content — ${at}`, shell.cardClips === false);
    check(`the bottom navigation stays visible — ${at}`, shell.navVisible === true);

    /* ── 3B · The Prop Pool pick surface ─────────────────────────────────── */

    section(`Prop Pool pick surface — ${at}`);

    const pool = await evaluate(`
      { const t = document.querySelector('.fs-tabbar__item[data-destination="league"]');
        if (t) t.click(); }
      const cards = [...document.querySelectorAll('#panel-league [data-pool]')];
      if (!cards.length) return { none: true };
      // The pool that can actually be picked is the one worth measuring.
      let found = null;
      for (const c of cards) {
        c.click();
        const sheet = document.getElementById('fs-sheet');
        if (sheet.querySelector('#fs-poolpick-form')) { found = c; break; }
        const close = document.querySelector('#fs-overlay [data-fs-close]');
        if (close) close.click();
      }
      const sheet = document.getElementById('fs-sheet');
      if (!found) return { none: false, openable: false,
                           text: sheet ? sheet.textContent.slice(0, 120) : null };
      const grid = sheet.querySelector('.fs-poolpick__grid');
      const opts = [...sheet.querySelectorAll('[data-poolpick-subject]')];
      const held = sheet.querySelector('#fs-poolpick-held');
      const rects = opts.map((o) => {
        const b = o.getBoundingClientRect();
        const cs = getComputedStyle(o);
        return { w: Math.round(b.width * 10) / 10, h: Math.round(b.height * 10) / 10,
                 radius: cs.borderTopLeftRadius, align: cs.alignItems,
                 justify: cs.justifyContent,
                 label: o.querySelector('.fs-seg__label').textContent.trim(),
                 id: o.dataset.poolpickSubject };
      });
      return {
        none: false, openable: true,
        title: (sheet.querySelector('.fs-sheet__title') || {}).textContent,
        question: (sheet.querySelector('.fs-poolq') || {}).textContent,
        // The defect: a native dropdown, and a caption that was a scope enum.
        hasSelect: Boolean(sheet.querySelector('select')),
        saysScopeEnum: /(^|\\s)(Matchup|Team)(\\s*$)/.test(
          (sheet.querySelector('.fs-poolq') || {}).textContent || ''),
        optionCount: opts.length,
        rects,
        heldBefore: held ? held.textContent.trim() : null,
        gridCols: grid ? getComputedStyle(grid).gridTemplateColumns : null,
        submitPresent: Boolean(sheet.querySelector('#fs-poolpick-save')),
        submitHeight: sheet.querySelector('#fs-poolpick-save')
          ? Math.round(sheet.querySelector('#fs-poolpick-save')
            .getBoundingClientRect().height) : null,
      };
    `);

    if (pool.none) {
      check(`this league drew no Prop Pools — reported, not passed over — ${at}`,
        true, 'no slate');
    } else if (!pool.openable) {
      check(`a Prop Pool is open for the acting GM to pick — ${at}`, false,
        String(pool.text));
    } else {
      check(`the Prop Pool sheet names the served pool — ${at}`,
        typeof pool.title === 'string' && pool.title.trim().length > 0, pool.title);
      check(`it asks a question, not a scope enum — ${at}`,
        /^Which (team|matchup)/.test((pool.question || '').trim())
        && pool.saysScopeEnum === false, pool.question);
      check(`no native dropdown survives — ${at}`, pool.hasSelect === false);
      check(`the choices are rendered as cells — ${at}`, pool.optionCount > 1,
        String(pool.optionCount));
      check(`every choice carries a served subject id — ${at}`,
        pool.rects.every((r) => /^\d+$/.test(r.id)),
        pool.rects.map((r) => r.id).join(','));
      check(`every choice carries a served label — ${at}`,
        pool.rects.every((r) => r.label.length > 0));
      check(`the cells are equal in size — ${at}`,
        pool.rects.every((r) => near(r.w, pool.rects[0].w)
          && near(r.h, pool.rects[0].h)),
        pool.rects.map((r) => `${r.w}x${r.h}`).join(' / '));
      check(`they meet the governed touch size — ${at}`,
        pool.rects.every((r) => r.h >= 44), pool.rects.map((r) => r.h).join('/'));
      check(`and centre their content — ${at}`,
        pool.rects.every((r) => r.align === 'center' && r.justify === 'center'));
      check(`Your pick starts unresolved — ${at}`,
        pool.heldBefore === '—', String(pool.heldBefore));
      check(`Submit Pick is present and a full target — ${at}`,
        pool.submitPresent === true && pool.submitHeight >= 44,
        String(pool.submitHeight));

      // ── selecting, and what the claim carries ──
      const picked = await evaluate(`
        const sheet = document.getElementById('fs-sheet');
        const opts = [...sheet.querySelectorAll('[data-poolpick-subject]')];
        const target = opts[1] || opts[0];
        target.click();
        const held = sheet.querySelector('#fs-poolpick-held');
        return {
          pressed: opts.filter((o) => o.getAttribute('aria-pressed') === 'true')
            .map((o) => o.dataset.poolpickSubject),
          selectedClass: target.classList.contains('is-selected'),
          held: held.textContent.trim(),
          heldPending: held.classList.contains('is-pending'),
          wanted: target.querySelector('.fs-seg__label').textContent.trim(),
          wantedId: target.dataset.poolpickSubject,
        };
      `);
      check(`pressing a choice selects exactly one — ${at}`,
        picked.pressed.length === 1 && picked.pressed[0] === picked.wantedId,
        picked.pressed.join(','));
      check(`the selected cell shows the selected treatment — ${at}`,
        picked.selectedClass === true);
      check(`Your pick reflects the selected subject — ${at}`,
        picked.held === picked.wanted, `${picked.held} vs ${picked.wanted}`);
      check(`and reads as unsent until the server confirms — ${at}`,
        picked.heldPending === true);

      // THE REQUEST CARRIES THE SERVED SUBJECT ID, AND NOTHING ELSE DECIDES IT.
      // The submit is intercepted at `fetch` so the wire payload is read without
      // writing a claim — this suite must not mutate a governed table.
      const wire = await evaluate(`
        return new Promise((resolve) => {
          const real = window.fetch;
          window.fetch = (url, opts) => {
            window.fetch = real;
            let parsed = null;
            try { parsed = JSON.parse((opts && opts.body) || 'null'); } catch (e) {}
            resolve({ url: String(url), method: (opts || {}).method || 'GET',
                      body: parsed });
            // Never reaches the server: the promise below is what the handler
            // awaits, and it rejects so no claim is written by this test.
            return Promise.reject(new Error('intercepted by uirecon wave 3'));
          };
          document.getElementById('fs-poolpick-save').click();
          setTimeout(() => { window.fetch = real; resolve(null); }, 2500);
        });
      `);
      check(`Submit sends a governed claim request — ${at}`,
        Boolean(wire) && /pool/i.test(wire.url) && wire.method === 'POST',
        wire ? `${wire.method} ${wire.url}` : 'no request');
      check(`carrying the served subject id — ${at}`,
        Boolean(wire) && wire.body
        && String(wire.body.subject_id ?? wire.body.selected_subject_id)
          === String(picked.wantedId),
        wire && wire.body ? JSON.stringify(wire.body) : 'no body');

      await evaluate(`
        const close = document.querySelector('#fs-overlay [data-fs-close]');
        if (close) close.click();
        return 1;
      `);
    }

    /* ── Section parity is preserved ─────────────────────────────────────── */

    const zones = await evaluate(`
      const panel = document.getElementById('panel-league');
      return [...panel.querySelectorAll('.fs-zone')].map((z) => {
        const h = z.querySelector('.fs-heading');
        const body = z.querySelector('.fs-carousel, .fs-pools, .fs-emptyzone');
        return {
          title: h ? h.querySelector('.fs-heading__text').textContent : null,
          gap: (h && body) ? Math.round((body.getBoundingClientRect().top
            - h.getBoundingClientRect().bottom) * 10) / 10 : null,
          size: h ? getComputedStyle(h.querySelector('.fs-heading__text')).fontSize : null,
        };
      });
    `);
    check(`Matchups and Prop Pools keep one title treatment — ${at}`,
      zones.length === 2 && zones[0].size === zones[1].size,
      zones.map((z) => `${z.title}:${z.size}`).join(' | '));
    check(`and one title-to-content gap — ${at}`,
      zones.length === 2 && near(zones[0].gap, zones[1].gap),
      zones.map((z) => z.gap).join(' / '));
  }
});

finish();
