/* ============================================================================
 * FantasyStakes — UIRECON Rev 1.4 · presentation reconciliation · browser
 *
 * Run directly:   node web/tests/uirecon_rev14_presentation_browser.mjs
 * Or through:     python test_uirecon_rev14_presentation.py
 *
 * FOUR CLAIMS, AND EVERY ONE OF THEM IS A QUESTION ABOUT RENDERED PIXELS
 * rather than about which string a module exports. That is why they are asked
 * here and not in the Python tier:
 *
 *   STANDINGS   the OVERALL header reads RK · TEAM · MATCHUPS · POOLS · NET,
 *               each on ONE line, with no two header cells overlapping and no
 *               label clipped, at every certified width — and the page still
 *               does not scroll sideways.
 *
 *   THE HEADER  no caret, triangle or chevron survives between the team name
 *               and the Settings gear — in the DOM, in the text, and in the
 *               generated content of every pseudo-element in the control.
 *
 *   THE CONTROL the team name still opens the account sheet, by pointer and by
 *               keyboard, and still announces itself as something that opens.
 *
 *   ACCOUNT     the strip's third cell still reads `Held` — the POR's own term
 *               for pending offer holds — and `WAGERING SUMMARY` no longer
 *               carries a gold rule down its left edge.
 *
 * WHY A WRAP IS MEASURED WITH A RANGE AND NOT WITH A HEIGHT. A `<th>` that
 * takes two lines is taller than one that takes one, but only in comparison to
 * a sibling — and the failure this suite exists to prevent made EVERY cell in
 * the row two lines tall, so the row was internally consistent and only wrong
 * next to the tables below it. A Range over the cell's own text reports how
 * many line boxes that text actually occupies, which is the question, and it
 * is right about a lone cell as well as about a row.
 *
 * WHAT THIS SUITE DELIBERATELY DOES NOT ASSERT. It says nothing about the Wrap
 * Up result card: the same "no gold side ornament" instruction applies there,
 * but that surface belongs to another pass, and a suite that asserted both
 * would fail for a reason its own diff could not explain.
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

/** The OVERALL header, exactly. `POOLS`, and `MATCHUPS` unabbreviated. */
const OVERALL_COLUMNS = ['RK', 'TEAM', 'MATCHUPS', 'POOLS', 'NET'];

/* Anything a reader would call a caret. The set is deliberately wider than the
 * one glyph that was removed, because the instruction was not "delete this
 * character" — it was "no visible caret between the name and the gear". */
const CARET_GLYPHS = '▾▿▼▽▴▵▲△◂◃◀◄▸▹▶►⌄⌃˅˄⏷⏶⯆⯅';

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 8000;
    const poll = () => {
      const mounted = document.querySelector('.fs-tabbar__item')
        && document.querySelector('#panel-standings .fs-st__table');
      if (mounted || Date.now() > deadline) return resolve(Boolean(mounted));
      setTimeout(poll, 100);
    };
    poll();
  });
`;

const GO = (destination) => `
  const tab = document.querySelector(
    '.fs-tabbar__item[data-destination="${destination}"]');
  if (tab) tab.click();
  return Boolean(tab);
`;

await withPage({ port: 9471 }, async ({ evaluate, setViewport, pressKey }) => {
  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    const at = `${vp.width}x${vp.height}`;
    check(`the application mounted — ${at}`, await evaluate(READY) === true);

    /* ── 1 · The OVERALL header row ──────────────────────────────────────── */

    section(`Standings · OVERALL header — ${at} (${vp.label})`);

    await evaluate(GO('standings'));

    const tables = await evaluate(`
      // A cell's text occupies this many line boxes. One is the contract.
      const lines = (el) => {
        const range = document.createRange();
        range.selectNodeContents(el);
        return range.getClientRects().length;
      };
      const box = (el) => {
        const b = el.getBoundingClientRect();
        return { l: b.left, r: b.right, t: b.top, b: b.bottom,
                 w: Math.round(b.width), h: Math.round(b.height) };
      };
      // Two boxes share pixels. 1px of tolerance, because adjacent table cells
      // are edge-to-edge by construction and a shared edge is not an overlap.
      const overlaps = (a, b) => !(a.r <= b.l + 1 || b.r <= a.l + 1
        || a.b <= b.t + 1 || b.b <= a.t + 1);

      return [...document.querySelectorAll('#panel-standings .fs-st')].map((sec) => {
        const ths = [...sec.querySelectorAll('thead th')];
        const rows = [...sec.querySelectorAll('tbody tr')];
        const boxes = ths.map(box);
        let collision = null;
        for (let i = 0; i < boxes.length; i += 1) {
          for (let j = i + 1; j < boxes.length; j += 1) {
            if (overlaps(boxes[i], boxes[j])) {
              collision = ths[i].textContent + '/' + ths[j].textContent;
            }
          }
        }
        // A numeric column is right-aligned AND lands on the same right edge
        // as the figures under it — the second half is what makes the first
        // half worth anything.
        const columns = ths.map((th, i) => {
          const cell = rows[0] ? rows[0].children[i] : null;
          return {
            text: th.textContent,
            lines: lines(th),
            // Clipped rather than merely narrow: the header contract allows an
            // ellipsis as a guard, and this proves the guard is not in use.
            clipped: th.scrollWidth > th.clientWidth + 1,
            align: getComputedStyle(th).textAlign,
            cellAlign: cell ? getComputedStyle(cell).textAlign : null,
            right: Math.round(th.getBoundingClientRect().right),
            cellRight: cell ? Math.round(cell.getBoundingClientRect().right) : null,
            width: Math.round(th.getBoundingClientRect().width),
          };
        });
        const teamCell = rows[0] ? rows[0].querySelector('.fs-st__team') : null;
        const teamStyle = teamCell ? getComputedStyle(teamCell) : null;
        return {
          key: sec.dataset.standingsTable,
          columns,
          collision,
          headerHeight: ths.length ? box(ths[0]).h : null,
          rows: rows.length,
          // The readable measure of the name column: the width its text
          // actually gets, padding removed.
          teamContentWidth: teamCell && teamStyle
            ? Math.round(teamCell.getBoundingClientRect().width
              - parseFloat(teamStyle.paddingLeft)
              - parseFloat(teamStyle.paddingRight))
            : null,
          teamEllipsis: teamStyle ? teamStyle.textOverflow : null,
          tableWidth: Math.round(
            sec.querySelector('.fs-st__table').getBoundingClientRect().width),
        };
      });
    `);

    const overall = tables.find((t) => t.key === 'overall') || { columns: [] };

    check(`three tables are drawn — ${at}`, tables.length === 3,
      tables.map((t) => t.key).join(', '));
    check(`the OVERALL header reads ${OVERALL_COLUMNS.join(' / ')} — ${at}`,
      JSON.stringify(overall.columns.map((c) => c.text))
        === JSON.stringify(OVERALL_COLUMNS),
      overall.columns.map((c) => c.text).join(' / '));
    check(`no PROP POOLS, and Matchups is not abbreviated — ${at}`,
      !overall.columns.some((c) => /PROP|MATCHES|MTCH|MTCHUP/.test(c.text)),
      overall.columns.map((c) => c.text).join(' / '));

    for (const table of tables) {
      const twoLine = table.columns.filter((c) => c.lines !== 1);
      check(`no header cell takes a second line — ${table.key} — ${at}`,
        twoLine.length === 0,
        twoLine.map((c) => `${c.text}:${c.lines}`).join(', ') || 'all one line');
      check(`no two header cells overlap — ${table.key} — ${at}`,
        table.collision === null, table.collision || 'none');
      const clipped = table.columns.filter((c) => c.clipped);
      check(`no header label is clipped — ${table.key} — ${at}`,
        clipped.length === 0,
        clipped.map((c) => c.text).join(', ') || 'all whole');
    }

    // ONE LINE MEANS ONE HEIGHT, and the three tables have to agree about it —
    // the failure this replaces stood OVERALL's header at 45px against the
    // 28px of the two tables below it.
    const heights = tables.map((t) => t.headerHeight);
    check(`the three header rows are the same height — ${at}`,
      new Set(heights).size === 1, heights.join(' / '));

    /* ── 2 · The figures, and the name column ────────────────────────────── */

    section(`Standings · figures and names — ${at}`);

    for (const table of tables) {
      const figures = table.columns.slice(2);
      check(`every figure column is right-aligned, header and cell — `
        + `${table.key} — ${at}`,
        figures.every((c) => c.align === 'right')
        && figures.every((c) => c.cellAlign === null || c.cellAlign === 'right'),
        figures.map((c) => `${c.text}:${c.align}/${c.cellAlign}`).join(' '));
      check(`each figure header shares its column's right edge — `
        + `${table.key} — ${at}`,
        figures.every((c) => c.cellRight === null
          || Math.abs(c.right - c.cellRight) <= 1),
        figures.map((c) => `${c.text}:${c.right}/${c.cellRight}`).join(' '));
      check(`RK and TEAM lead the table — ${table.key} — ${at}`,
        table.columns[0].text === 'RK' && table.columns[1].text === 'TEAM');
    }

    // WHAT "READABLE" IS ALLOWED TO MEAN. The name column is the one that pays
    // for everything else, so the floor is stated rather than assumed: at the
    // narrowest certified width it still holds ~7 characters of a name in the
    // 16px card face, and it truncates with an ellipsis rather than a hard cut.
    // A wider viewport spends every additional pixel here, because TEAM is the
    // table's only `width: auto` column.
    for (const table of tables) {
      check(`the team column keeps a legible measure — ${table.key} — ${at}`,
        table.teamContentWidth === null || table.teamContentWidth >= 56,
        `${table.teamContentWidth}px`);
      check(`a long name ellipsizes rather than being cut — `
        + `${table.key} — ${at}`,
        table.teamEllipsis === null || table.teamEllipsis === 'ellipsis',
        String(table.teamEllipsis));
    }
    // THE FIVE COLUMNS ACCOUNT FOR THE WHOLE TABLE AND NO MORE. If a figure
    // column were ever sized past what is there, the surplus would come out of
    // TEAM until TEAM ran out — and then out of the page.
    check(`OVERALL's five columns fill the table exactly — ${at}`,
      overall.columns.length === 5
      && Math.abs(overall.columns.reduce((sum, c) => sum + c.width, 0)
        - overall.tableWidth) <= 1,
      `${overall.columns.map((c) => c.width).join('+')} vs ${overall.tableWidth}`);

    /* ── 3 · The page does not scroll sideways ───────────────────────────── */

    const doc = await evaluate(`
      const el = document.documentElement;
      const wide = [...document.querySelectorAll('#panel-standings *')]
        .filter((n) => n.getBoundingClientRect().right > el.clientWidth + 1)
        .map((n) => n.className || n.tagName);
      return { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,
               wide: wide.slice(0, 4) };
    `);
    check(`the Standings tab does not scroll sideways — ${at}`,
      doc.scrollWidth <= doc.clientWidth,
      `${doc.scrollWidth} <= ${doc.clientWidth}`);
    check(`nothing on Standings reaches past the right edge — ${at}`,
      doc.wide.length === 0, doc.wide.join(', ') || 'nothing');

    /* ── 4 · The header carries no caret ─────────────────────────────────── */

    section(`Header · the account control — ${at}`);

    const acct = await evaluate(`
      const caret = ${JSON.stringify(CARET_GLYPHS)};
      const button = document.getElementById('fs-account');
      const gear = document.getElementById('fs-gear');
      if (!button) return { present: false };

      // EVERY generated string in the control, not just the button's own. A
      // caret redrawn as a pseudo-element would be invisible to a text search
      // and is exactly the shape a "put it back, smaller" change would take.
      const generated = [];
      for (const node of [button, ...button.querySelectorAll('*')]) {
        for (const pseudo of ['::before', '::after']) {
          const value = getComputedStyle(node, pseudo).content;
          if (value && value !== 'none' && value !== 'normal') {
            generated.push(node.className + pseudo + '=' + value);
          }
        }
      }

      const glyphs = [...button.textContent]
        .filter((ch) => caret.includes(ch));

      return {
        present: true,
        tag: button.tagName,
        chevronNodes: button.querySelectorAll('.fs-acct__chev').length,
        childClasses: [...button.children].map((c) => c.className),
        glyphs: glyphs.join(''),
        generated,
        // The cluster order the caret used to sit inside.
        nameThenGear: Boolean(gear)
          && button.getBoundingClientRect().right <= gear.getBoundingClientRect().left + 1,
        // Nothing at all stands between the control and the gear.
        between: gear && button.nextElementSibling === gear,
        label: button.getAttribute('aria-label'),
        haspopup: button.getAttribute('aria-haspopup'),
        expanded: button.getAttribute('aria-expanded'),
        disabled: button.disabled === true,
        tabbable: button.tabIndex >= 0,
        name: (button.querySelector('.fs-ident__who') || {}).textContent || null,
        nameWidth: button.querySelector('.fs-ident__who')
          ? Math.round(button.querySelector('.fs-ident__who')
            .getBoundingClientRect().width) : null,
      };
    `);

    check(`the account control is present — ${at}`, acct.present === true);
    check(`no chevron element survives in the DOM — ${at}`,
      acct.chevronNodes === 0, `${acct.chevronNodes} node(s)`);
    check(`no caret or triangle glyph is drawn in it — ${at}`,
      acct.glyphs === '', acct.glyphs || 'none');
    check(`no pseudo-element draws one back — ${at}`,
      acct.generated.length === 0, acct.generated.join(', ') || 'no content');
    check(`the control holds the name and nothing decorative — ${at}`,
      acct.childClasses.every((c) => /fs-ident__(who|badge)/.test(c)),
      acct.childClasses.join(', ') || 'no children');
    check(`nothing at all stands between the name and the gear — ${at}`,
      acct.between === true && acct.nameThenGear === true,
      `between=${acct.between} order=${acct.nameThenGear}`);

    /* ── 5 · And is still the control it says it is ──────────────────────── */

    check(`it is a real button — ${at}`, acct.tag === 'BUTTON', acct.tag);
    check(`it is keyboard-focusable and enabled — ${at}`,
      acct.tabbable === true && acct.disabled === false,
      `tabbable=${acct.tabbable} disabled=${acct.disabled}`);
    check(`it keeps its accessible name — ${at}`,
      /^Account/.test(acct.label || ''), String(acct.label));
    check(`it still announces that it opens something — ${at}`,
      acct.haspopup === 'dialog' && acct.expanded !== null,
      `${acct.haspopup} · aria-expanded=${acct.expanded}`);
    check(`the team name is still what is drawn — ${at}`,
      Boolean(acct.name) && acct.nameWidth > 0,
      `${acct.name} @ ${acct.nameWidth}px`);

    // BY POINTER.
    const byClick = await evaluate(`
      document.getElementById('fs-account').click();
      const overlay = document.getElementById('fs-overlay');
      const sheet = document.getElementById('fs-sheet');
      return {
        open: Boolean(overlay && overlay.classList.contains('is-open')),
        signOut: Boolean(sheet && sheet.querySelector('#fs-signout')),
        title: sheet ? (sheet.textContent || '').slice(0, 24) : null,
      };
    `);
    check(`clicking the team name opens the account sheet — ${at}`,
      byClick.open === true && byClick.signOut === true,
      `open=${byClick.open} signOut=${byClick.signOut}`);

    await evaluate(`
      const overlay = document.getElementById('fs-overlay');
      if (overlay) overlay.classList.remove('is-open');
      window.FantasyStakes.closeSheet();
      return true;
    `);

    // AND BY KEYBOARD, through the browser's own input pipeline — a scripted
    // KeyboardEvent would prove only that a handler exists, and the claim here
    // is that a GM who never touches the screen can still reach the sheet.
    await evaluate(`
      const button = document.getElementById('fs-account');
      button.focus();
      return document.activeElement === button;
    `);
    await pressKey('Enter');
    const byKey = await evaluate(`
      const overlay = document.getElementById('fs-overlay');
      const sheet = document.getElementById('fs-sheet');
      return {
        focused: document.activeElement
          ? document.activeElement.id || document.activeElement.className : null,
        open: Boolean(overlay && overlay.classList.contains('is-open')),
        signOut: Boolean(sheet && sheet.querySelector('#fs-signout')),
      };
    `);
    check(`and Enter on the focused name opens it too — ${at}`,
      byKey.open === true && byKey.signOut === true,
      `open=${byKey.open} signOut=${byKey.signOut}`);

    await evaluate(`window.FantasyStakes.closeSheet(); return true;`);

    /* ── 6 · Account — the strip label and the section's edges ───────────── */

    section(`Account · strip label and section edges — ${at}`);

    await evaluate(GO('ledger'));

    const account = await evaluate(`
      const strip = document.getElementById('fs-strip-ledger');
      const labels = strip
        ? [...strip.querySelectorAll('.fs-strip__label')].map((l) => l.textContent)
        : [];
      const third = strip
        ? strip.querySelectorAll('.fs-strip__label')[2] : null;
      const range = third ? document.createRange() : null;
      if (range) range.selectNodeContents(third);

      const wagering = document.querySelector(
        '#panel-ledger .fs-lscroll .fs-lsec[data-section="2"]');
      const style = wagering ? getComputedStyle(wagering) : null;
      const pseudo = wagering
        ? ['::before', '::after'].map(
          (p) => p + '=' + getComputedStyle(wagering, p).content).join(' ')
        : null;

      return {
        labels,
        thirdLines: range ? range.getClientRects().length : null,
        thirdClipped: third ? third.scrollWidth > third.clientWidth + 1 : null,
        title: wagering
          ? (wagering.querySelector('.fs-lsec__title') || {}).textContent : null,
        boxShadow: style ? style.boxShadow : null,
        borders: style
          ? [style.borderLeftWidth, style.borderRightWidth,
             style.borderTopWidth, style.borderBottomWidth].join('/')
          : null,
        borderColours: style
          ? [style.borderLeftColor, style.borderRightColor].join(' vs ')
          : null,
        background: style ? style.backgroundColor : null,
        pseudo,
      };
    `);

    // THE PART 3 DECISION, ASSERTED AS A DECISION. `Held` is the POR's term for
    // pending offer holds and is NOT wager escrow — the escrow on unresolved
    // wagers is `In Play`, one cell to its left, of which this figure is a
    // documented subset. Renaming it `Escrow` would have said the two are
    // different money.
    // FINAL POR §30 — the cell is `Escrow` now, and the Rev 1.4 objection is
    // answered by the `included in In Play` context rather than by the label.
    check(`the Account strip reads Available / In Play / Escrow / `
      + `Min Left — ${at}`,
      JSON.stringify(account.labels)
        === JSON.stringify(['Available', 'In Play', 'Escrow', 'Min Left']),
      account.labels.join(' · '));
    check(`its label is one unclipped line — ${at}`,
      account.thirdLines === 1 && account.thirdClipped === false,
      `${account.thirdLines} line(s), clipped=${account.thirdClipped}`);

    check(`WAGERING SUMMARY is the section measured — ${at}`,
      account.title === 'WAGERING SUMMARY', String(account.title));
    check(`it carries no gold left rule — ${at}`,
      account.boxShadow === 'none', String(account.boxShadow));
    check(`and no pseudo-element draws one — ${at}`,
      /::before=none/.test(account.pseudo || '')
      && /::after=none/.test(account.pseudo || ''), String(account.pseudo));
    // THE BORDER HIERARCHY IS PRESERVED, NOT FLATTENED. Removing the ornament
    // was not licence to remove the section's edge: it keeps a border of equal
    // width on all four sides, and its lifted ground.
    check(`its border is still even on all four sides — ${at}`,
      new Set((account.borders || '').split('/')).size === 1,
      String(account.borders));
    check(`no side ornament replaced it — ${at}`,
      account.borderColours
      && account.borderColours.split(' vs ')[0]
        === account.borderColours.split(' vs ')[1],
      String(account.borderColours));
    check(`and the section keeps its lifted ground — ${at}`,
      account.background !== 'rgba(0, 0, 0, 0)'
      && account.background !== 'transparent', String(account.background));

    await evaluate(GO('standings'));
  }
});

finish();
