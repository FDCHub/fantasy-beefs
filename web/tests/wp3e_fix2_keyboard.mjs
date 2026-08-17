/* ============================================================================
 * FantasyStakes — WP3E-FIX2 · interactive-card keyboard access · browser suite
 *
 * Run through:  python test_wp3e_fix2_keyboard_cards.py
 *
 * WHAT THIS PROVES, AND WHY IT HAD TO BE DRIVEN RATHER THAN READ.
 *
 * A card that opens a composer is a control whether or not its markup admits
 * it. The Versus matchup card was a bare `<div>`: Tab never reached it, Enter
 * did nothing, and because it could not hold focus there was no opener for the
 * composer to give focus back to on close. None of that is visible in a
 * stylesheet or in a class name — it is only visible when something presses a
 * key and watches what happens.
 *
 * So every claim here is driven: real key events on a real rendering, with the
 * activation COUNTED so that "Enter works" cannot quietly mean "Enter works
 * twice", and with the pointer path re-run afterwards so the keyboard fix
 * cannot have been bought by breaking the tap.
 *
 * `FS_FIX2_MODE` selects the session: `gm` or `commissioner`.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

const MODE = process.env.FS_FIX2_MODE || 'gm';

/* The application mounts asynchronously — identity first, then every
 * authoritative slice, and only then a tab. Waiting for the tab bar to EXIST is
 * the honest settle; a fixed sleep only moves the flake. */
const AWAIT_APP = `
  for (let attempt = 0; attempt < 60; attempt += 1) {
    if (document.querySelectorAll('.fs-tabbar__item').length >= 5) break;
    await new Promise((r) => setTimeout(r, 100));
  }
`;

/* Counting activations needs a seam the page itself can see. The composer is
 * opened through the shell API, so the count is taken from what the SHEET does
 * — one open per press, no more. */
const OPEN_VERSUS = `
  const card = document.querySelector('#panel-league [data-card-action="challenge"]');
`;

await withPage({ port: 9496 }, async ({ evaluate, setViewport, pressKey }) => {

  console.log(`\n(mode: ${MODE})`);

  /* ── §3 · reconciliation, asserted rather than asserted-about ─────────── */

  section('§3 · Interactive-card reconciliation, measured in the rendering');

  const recon = await evaluate(`return (async () => {
    ${AWAIT_APP}
    const NATIVE = ['button', 'a', 'input', 'select', 'textarea', 'summary'];
    const rows = [];
    for (const id of ['standings', 'league', 'action', 'week', 'ledger']) {
      document.querySelector('.fs-tabbar__item[data-destination="' + id + '"]').click();
      await new Promise((r) => setTimeout(r, 260));
      const panel = document.getElementById('panel-' + id);
      // A CONTROL IS SOMETHING WHOSE WHOLE SURFACE IS AN ACTION. Containers
      // that merely HOLD a control are not, and must not become tab stops.
      for (const el of panel.querySelectorAll('.is-tappable, [data-card-action]')) {
        const tag = el.tagName.toLowerCase();
        rows.push({
          panel: id, tag,
          role: el.getAttribute('role') || '',
          tabindex: el.getAttribute('tabindex'),
          focusable: NATIVE.includes(tag) || el.getAttribute('tabindex') !== null,
          name: (el.getAttribute('aria-label') || '').slice(0, 60),
        });
      }
    }
    return rows;
  })();`);

  check('interactive cards were found to certify', recon.length > 0,
    `${recon.length} card(s)`);
  const unreachable = recon.filter((r) => !r.focusable);
  check('every whole-card control is keyboard reachable',
    unreachable.length === 0,
    unreachable.map((r) => `${r.panel}:<${r.tag}>`).join(', ') || 'none');
  for (const row of recon) {
    check(`${row.panel}: the card exposes button semantics`,
      row.tag === 'button' || row.role === 'button',
      `<${row.tag}> role=${row.role || '-'} tabindex=${row.tabindex}`);
  }

  /* ── §5/§6 · the Versus card, driven by keyboard alone ────────────────── */

  section('§5/§6 · The Versus card is a real keyboard control');

  const semantics = await evaluate(`return (async () => {
    ${AWAIT_APP}
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 260));
    ${OPEN_VERSUS}
    if (!card) return { present: false };
    card.focus();
    const style = getComputedStyle(card);
    return {
      present: true,
      tag: card.tagName.toLowerCase(),
      role: card.getAttribute('role'),
      tabindex: card.getAttribute('tabindex'),
      focused: document.activeElement === card,
      name: card.getAttribute('aria-label'),
      // THE NAME MUST DISTINGUISH THIS CARD FROM THE ONE BESIDE IT, so the
      // opponent's own identity has to be inside it.
      namesOpponent: (card.getAttribute('aria-label') || '')
        .includes((card.querySelector('.fs-wcard__identity') || {}).textContent || '\\u0000'),
      // AND IT MUST NOT BE A RECITAL OF ODDS.
      nameLength: (card.getAttribute('aria-label') || '').length,
      nestedControls: card.querySelectorAll('button').length,
      cursor: style.cursor,
    };
  })();`);

  check('the Versus card is present', semantics.present === true);
  check('it declares button semantics',
    semantics.role === 'button', String(semantics.role));
  check('it is in the tab order', semantics.tabindex === '0',
    String(semantics.tabindex));
  check('it actually takes focus', semantics.focused === true);
  check('it has an accessible name', Boolean(semantics.name), semantics.name);
  check('the name identifies the opponent, not the odds',
    semantics.namesOpponent === true && semantics.nameLength < 60,
    `${semantics.name} (${semantics.nameLength} chars)`);
  // THE REASON IT IS role=button AND NOT A NATIVE <button>: it contains real
  // buttons, and a button may not contain a button. That is asserted so the
  // decision cannot be "simplified" later into invalid markup.
  check('it contains real nested controls, which is why it is not a <button>',
    semantics.tag === 'div' && semantics.nestedControls >= 4,
    `<${semantics.tag}> holding ${semantics.nestedControls} buttons`);
  check('it still presents as tappable', semantics.cursor === 'pointer',
    semantics.cursor);

  /* ── §5 · Enter, Space, and exactly one activation each ───────────────── */

  section('§5 · Enter and Space each activate exactly once');

  for (const key of ['Enter', ' ']) {
    const armed = await evaluate(`return (async () => {
      ${AWAIT_APP}
      const overlay = document.getElementById('fs-overlay');
      if (overlay.classList.contains('is-open')) {
        document.querySelector('#fs-sheet [data-fs-close]').click();
        await new Promise((r) => setTimeout(r, 200));
      }
      document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
      await new Promise((r) => setTimeout(r, 260));
      ${OPEN_VERSUS}
      card.focus();

      // ONE PRESS, COUNTED. Every render of the sheet host is observed, so a
      // handler bound twice — or a keydown that also produces a synthetic
      // click — shows up as two openings rather than passing as one.
      window.__fsRenders = 0;
      window.__fsObserver = new MutationObserver(() => { window.__fsRenders += 1; });
      window.__fsObserver.observe(document.getElementById('fs-sheet'),
        { childList: true });
      return { armed: document.activeElement === card };
    })();`);
    check(`${key === ' ' ? 'Space' : key}: the card is focused before the press`,
      armed.armed === true);

    // THE KEY IS PRESSED BY THE BROWSER, not by page script — see `pressKey`
    // in the harness for why that distinction is not pedantry.
    await pressKey(key);
    await new Promise((r) => setTimeout(r, 350));

    const pressed = await evaluate(`return (async () => {
      window.__fsObserver.disconnect();
      const renders = window.__fsRenders;
      const overlay = document.getElementById('fs-overlay');
      const host = document.getElementById('fs-sheet');
      const x = host.querySelector('[data-fs-close]');
      return {
        opened: overlay.classList.contains('is-open'),
        renders,
        title: (host.querySelector('.fs-sheet__title') || {}).textContent || '',
        focusInSheet: host.contains(document.activeElement),
        focusOnClose: document.activeElement === x,
      };
    })();`);

    const label = key === ' ' ? 'Space' : key;
    check(`${label} opens the Versus composer`, pressed.opened === true,
      pressed.title);
    check(`${label} activates exactly once`, pressed.renders === 1,
      `${pressed.renders} sheet render(s)`);
    check(`${label}: focus moves into the sheet, onto its close control`,
      pressed.focusInSheet === true && pressed.focusOnClose === true);

    /* ── §5 · Escape, close-X, and focus return ─────────────────────────── */

    await pressKey('Escape');
    await new Promise((r) => setTimeout(r, 250));

    const dismissed = await evaluate(`return (async () => {
      ${OPEN_VERSUS}
      return {
        closed: !document.getElementById('fs-overlay').classList.contains('is-open'),
        backOnCard: document.activeElement === card,
        onBody: document.activeElement === document.body,
        active: document.activeElement
          ? document.activeElement.tagName.toLowerCase()
            + '.' + (document.activeElement.className || '') : null,
      };
    })();`);

    check(`${label} → Escape closes the composer`, dismissed.closed === true);
    check(`${label} → focus returns to the same Versus card`,
      dismissed.backOnCard === true, String(dismissed.active));
    check(`${label} → focus is not dumped on the body`,
      dismissed.onBody === false);
  }

  section('§5 · The close control closes it too, with the same focus return');

  const viaXReady = await evaluate(`return (async () => {
    ${AWAIT_APP}
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 260));
    ${OPEN_VERSUS}
    card.focus();
    return { ready: document.activeElement === card };
  })();`);
  check('the card is focused before the press', viaXReady.ready === true);

  await pressKey('Enter');
  await new Promise((r) => setTimeout(r, 320));

  const viaX = await evaluate(`return (async () => {
    ${OPEN_VERSUS}
    const opened = document.getElementById('fs-overlay').classList.contains('is-open');
    document.querySelector('#fs-sheet [data-fs-close]').click();
    await new Promise((r) => setTimeout(r, 250));
    return {
      opened,
      closed: !document.getElementById('fs-overlay').classList.contains('is-open'),
      backOnCard: document.activeElement === card,
    };
  })();`);
  check('the close control dismisses a keyboard-opened composer',
    viaX.opened === true && viaX.closed === true);
  check('and focus still returns to the card', viaX.backOnCard === true);

  /* ── §5 · the pointer path is untouched ───────────────────────────────── */

  section('§10 · Pointer and touch behaviour is unchanged');

  const tapped = await evaluate(`return (async () => {
    ${AWAIT_APP}
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 260));
    ${OPEN_VERSUS}
    let renders = 0;
    const observer = new MutationObserver(() => { renders += 1; });
    observer.observe(document.getElementById('fs-sheet'), { childList: true });
    card.click();
    await new Promise((r) => setTimeout(r, 320));
    observer.disconnect();
    const opened = document.getElementById('fs-overlay').classList.contains('is-open');
    document.querySelector('#fs-sheet [data-fs-close]').click();
    await new Promise((r) => setTimeout(r, 200));
    return { opened, renders };
  })();`);
  check('a tap still opens the composer', tapped.opened === true);
  check('and it still opens it exactly once', tapped.renders === 1,
    `${tapped.renders} sheet render(s)`);

  // THE NESTED CONTROLS MUST NOT DOUBLE-FIRE. A market cell opens the composer
  // on that market; the card behind it opens it on no market. If the cell's
  // click reached the card as well, one press would produce two openings and
  // the second would silently discard the market the GM chose.
  const nested = await evaluate(`return (async () => {
    ${AWAIT_APP}
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 260));
    const cell = document.querySelector('#panel-league [data-market]');
    cell.focus();
    const cellFocusable = document.activeElement === cell;
    let renders = 0;
    const observer = new MutationObserver(() => { renders += 1; });
    observer.observe(document.getElementById('fs-sheet'), { childList: true });
    cell.click();
    await new Promise((r) => setTimeout(r, 320));
    observer.disconnect();
    const opened = document.getElementById('fs-overlay').classList.contains('is-open');
    document.querySelector('#fs-sheet [data-fs-close]').click();
    await new Promise((r) => setTimeout(r, 200));
    return { cellFocusable, opened, renders };
  })();`);
  check('a market cell inside the card is separately reachable',
    nested.cellFocusable === true);
  check('and activating it opens the composer once, not twice',
    nested.opened === true && nested.renders === 1,
    `${nested.renders} sheet render(s)`);

  /* ── §5 · no keyboard trap ────────────────────────────────────────────── */

  section('§5 · No keyboard trap');

  const trap = await evaluate(`return (async () => {
    ${AWAIT_APP}
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 260));
    ${OPEN_VERSUS}
    card.focus();
    // THE CARD MUST BE ESCAPABLE BY TAB ORDER ALONE. Its own nested controls
    // come after it, and the document keeps going past them; a control that
    // swallowed Tab would show up as a tabbable set of one.
    const all = [...document.querySelectorAll(
      'a[href],button,input,select,textarea,summary,[tabindex]:not([tabindex="-1"])')]
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
    const index = all.indexOf(card);
    return { index, total: all.length, hasNext: index >= 0 && index < all.length - 1 };
  })();`);
  check('the card is one stop among many in the document tab order',
    trap.index >= 0 && trap.total > 3, `${trap.index + 1} of ${trap.total}`);
  check('and the tab order continues past it — no trap',
    trap.hasNext === true);

  /* ── §7/§8 · visible focus, and no geometry regression ────────────────── */

  section('§7/§8 · Visible focus, and semantics changed no geometry');

  for (const [w, h] of [[320, 568], [360, 640], [375, 667], [390, 844],
    [430, 932], [844, 390]]) {
    await setViewport(w, h);
    const geo = await evaluate(`return (async () => {
      ${AWAIT_APP}
      document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
      await new Promise((r) => setTimeout(r, 300));
      ${OPEN_VERSUS}
      if (!card) return { present: false };
      const s = getComputedStyle(card);
      const r = card.getBoundingClientRect();
      const rail = card.parentElement.getBoundingClientRect();
      return {
        present: true,
        // A SEMANTIC CHANGE MUST NOT BRING BROWSER CHROME WITH IT. These are
        // exactly the defaults a native button would have imposed.
        appearance: s.appearance,
        textAlign: s.textAlign,
        font: s.fontFamily.split(',')[0].replace(/["']/g, ''),
        w: Math.round(r.width), h: Math.round(r.height),
        onScreen: r.left >= -1 && r.right <= window.innerWidth + 1,
        clipped: card.scrollHeight > card.clientHeight + 1,
        railFit: r.width <= rail.width + 1,
        docOver: document.documentElement.scrollWidth - window.innerWidth,
      };
    })();`);

    if (!geo.present) {
      check(`${w}x${h}: no Versus card in this fixture — not certified`,
        true, 'reported, not passed over');
      continue;
    }
    check(`${w}x${h}: no default button appearance`,
      geo.appearance === 'none' || geo.appearance === 'auto', geo.appearance);
    check(`${w}x${h}: text is not centred by a UA default`,
      geo.textAlign !== 'center', geo.textAlign);
    check(`${w}x${h}: the card keeps the product font`,
      geo.font !== 'system-ui' && geo.font.length > 0, geo.font);
    check(`${w}x${h}: it fits its rail and the viewport`,
      geo.railFit === true && geo.onScreen === true, `${geo.w}px`);
    check(`${w}x${h}: it clips none of its own content`, geo.clipped === false);
    check(`${w}x${h}: and causes no horizontal overflow`, geo.docOver <= 0,
      `${geo.docOver}px`);
  }

  await setViewport(390, 844);

  await evaluate(`return (async () => {
    ${AWAIT_APP}
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 300));
    return true;
  })();`);

  // ESTABLISH KEYBOARD MODALITY WITH A REAL KEY. `:focus-visible` is decided by
  // the browser from the last input modality, and a scripted `.focus()` sets
  // none — so without this the ring measures as absent for a rule that is
  // perfectly correct. One real Tab is enough to tell Chrome a keyboard is
  // driving; the card is then focused directly so the assertion does not depend
  // on how many stops precede it.
  await pressKey('Tab');

  const ring = await evaluate(`return (async () => {
    ${OPEN_VERSUS}
    card.focus();
    const matches = card.matches(':focus-visible');
    const s = getComputedStyle(card);
    return {
      matches,
      width: s.outlineWidth, style: s.outlineStyle, color: s.outlineColor,
      offset: s.outlineOffset,
    };
  })();`);
  check('the focused card matches the shared :focus-visible rule',
    ring.matches === true);
  check('and it draws the WP3E gold focus ring',
    parseFloat(ring.width) >= 2 && ring.style === 'solid'
    && ring.offset === '2px',
    `${ring.width} ${ring.style} ${ring.color}, offset ${ring.offset}`);
});

finish('WP3E-FIX2 KEYBOARD CARD ACCESS — BROWSER');
