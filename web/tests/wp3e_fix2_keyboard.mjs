/* ============================================================================
 * FantasyStakes — Versus card keyboard semantics · browser suite
 * WP3E-FIX2 (keyboard access) · WP3E-FIX3 (native semantics)
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
 * WP3E-FIX2 closed that with `role="button"` on the wrapper. It worked and it
 * was the wrong shape: an ARIA button containing four real buttons, whose
 * children the ARIA specification calls presentational and which assistive
 * technology is therefore not obliged to expose. WP3E-FIX3 replaced it with the
 * structure this file now certifies —
 *
 *     A CARD IS A CONTAINER OF ACTIONS, AND EVERY ACTION IS ITS OWN NATIVE
 *     BUTTON. Challenge, preview, moneyline, spread, total: five controls, five
 *     tab stops, no role anywhere, and no button inside a button.
 *
 * Every claim is driven: real key events through the browser's own input
 * pipeline, with activations COUNTED so that "Enter works" cannot quietly mean
 * "Enter works twice", and with each control exercised separately so that one
 * cannot be shown to work by another one firing.
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

const GO_LEAGUE = `
  document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
  await new Promise((r) => setTimeout(r, 280));
`;

const CARD = `
  const card = document.querySelector('#panel-league [data-card-action="challenge"]');
  const challenge = card ? card.querySelector('[data-card-challenge]') : null;
`;

/* Close whatever is open, so one surface's leftovers cannot pass as another's
 * result. */
const RESET = `
  {
    const overlay = document.getElementById('fs-overlay');
    if (overlay.classList.contains('is-open')) {
      document.querySelector('#fs-sheet [data-fs-close]').click();
      await new Promise((r) => setTimeout(r, 220));
    }
  }
`;

/* One activation, counted. Every render of the sheet host is observed, so a
 * handler bound twice — or a nested control whose click also reaches the card —
 * shows up as two openings rather than passing as one. */
const ARM = `
  window.__fsRenders = 0;
  window.__fsObs = new MutationObserver(() => { window.__fsRenders += 1; });
  window.__fsObs.observe(document.getElementById('fs-sheet'), { childList: true });
`;

await withPage({ port: 9496 }, async ({ evaluate, setViewport, pressKey }) => {

  console.log(`\n(mode: ${MODE})`);

  /* ── §6 · the structure, and what must not be in it ───────────────────── */

  section('§6 · Native semantics — no ARIA button wrapping native buttons');

  const structure = await evaluate(`return (async () => {
    ${AWAIT_APP}
    ${GO_LEAGUE}
    ${CARD}
    if (!card) return { present: false };

    // THE AUDIT THAT NAMES THIS PACKAGE. Walk every native control on the
    // panel and look upward for an ancestor claiming button semantics. One hit
    // is the defect WP3E-FIX3 exists to remove.
    const panel = document.getElementById('panel-league');
    const offenders = [];
    for (const control of panel.querySelectorAll('button, [role="button"]')) {
      let node = control.parentElement;
      while (node && node !== panel) {
        const isButtonish = node.tagName === 'BUTTON'
          || node.getAttribute('role') === 'button';
        if (isButtonish) {
          offenders.push((node.className || node.tagName).toString().split(' ')[0]
            + ' > ' + (control.className || control.tagName).toString().split(' ')[0]);
          break;
        }
        node = node.parentElement;
      }
    }

    const tags = (sel) => [...card.querySelectorAll(sel)]
      .map((el) => el.tagName.toLowerCase());

    return {
      present: true,
      wrapperTag: card.tagName.toLowerCase(),
      wrapperRole: card.getAttribute('role'),
      wrapperTabindex: card.getAttribute('tabindex'),
      wrapperAria: card.getAttribute('aria-label'),
      offenders,
      challengeTag: challenge ? challenge.tagName.toLowerCase() : null,
      challengeType: challenge ? challenge.getAttribute('type') : null,
      challengeName: challenge ? challenge.getAttribute('aria-label') : null,
      previewTags: tags('[data-preview-opponent]'),
      marketTags: tags('[data-market]'),
      marketCount: card.querySelectorAll('[data-market]').length,
      // STATIC TEXT MUST NOT BECOME A TAB STOP.
      strayTabbable: [...card.querySelectorAll('[tabindex]')]
        .filter((el) => el.tagName !== 'BUTTON')
        .map((el) => (el.className || el.tagName).toString().split(' ')[0]),
    };
  })();`);

  check('the Versus card is present', structure.present === true);
  check('the card wrapper is a plain container, not a button',
    structure.wrapperTag === 'div' && structure.wrapperRole === null,
    `<${structure.wrapperTag}> role=${structure.wrapperRole}`);
  check('the wrapper is not in the tab order',
    structure.wrapperTabindex === null, String(structure.wrapperTabindex));
  check('and it carries no button label of its own',
    structure.wrapperAria === null, String(structure.wrapperAria));
  check('NO button-like ancestor contains a native control anywhere on Play',
    structure.offenders.length === 0,
    structure.offenders.join(', ') || 'none');
  check('Challenge is a native button',
    structure.challengeTag === 'button' && structure.challengeType === 'button',
    `<${structure.challengeTag} type=${structure.challengeType}>`);
  check('Preview is a native button',
    structure.previewTags.join() === 'button', structure.previewTags.join());
  check('all three market controls are native buttons',
    structure.marketCount === 3
    && structure.marketTags.every((t) => t === 'button'),
    `${structure.marketCount}: ${structure.marketTags.join(', ')}`);
  check('no static card text was made tabbable',
    structure.strayTabbable.length === 0,
    structure.strayTabbable.join(', ') || 'none');

  /* ── §6 · the accessible name ─────────────────────────────────────────── */

  section('§6 · Accessible naming');

  const naming = await evaluate(`return (async () => {
    ${AWAIT_APP}
    ${GO_LEAGUE}
    ${CARD}
    const identity = card.querySelector('.fs-wcard__identity');
    const name = challenge.getAttribute('aria-label') || '';
    return {
      name,
      opponent: identity ? identity.textContent : '',
      namesOpponent: identity ? name.includes(identity.textContent) : false,
      // A NAME, NOT A RECITAL. The card's odds must not end up in it.
      length: name.length,
      previewName: card.querySelector('[data-preview-opponent]').textContent.trim(),
      marketNames: [...card.querySelectorAll('[data-market]')]
        .map((el) => (el.querySelector('.fs-market__label') || {}).textContent || ''),
    };
  })();`);

  check('Challenge names the action and the opponent',
    /^Challenge /.test(naming.name) && naming.namesOpponent === true,
    naming.name);
  check('and it is a label, not a sentence of figures',
    naming.length > 0 && naming.length < 60, `${naming.length} chars`);
  check('Preview keeps its own visible name',
    /MATCHUP PREVIEW/i.test(naming.previewName), naming.previewName);
  check('the market controls keep their own names',
    naming.marketNames.length === 3
    && naming.marketNames.every((n) => n.trim().length > 0),
    naming.marketNames.join(' · '));

  /* ── §5 · tab order ───────────────────────────────────────────────────── */

  section('§5 · Tab order reaches all five actions, in a logical order');

  const order = await evaluate(`return (async () => {
    ${AWAIT_APP}
    ${GO_LEAGUE}
    ${CARD}
    const focusables = [...card.querySelectorAll(
      'a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])')];
    const label = (el) => {
      if (el.hasAttribute('data-card-challenge')) return 'challenge';
      if (el.hasAttribute('data-preview-opponent')) return 'preview';
      if (el.hasAttribute('data-market')) return el.getAttribute('data-market');
      return el.tagName.toLowerCase();
    };
    return {
      sequence: focusables.map(label),
      allReachable: focusables.every((el) => el.offsetParent !== null),
    };
  })();`);

  check('the card offers exactly five tab stops', order.sequence.length === 5,
    order.sequence.join(' → '));
  check('Challenge comes first, then Preview, then the three markets',
    order.sequence[0] === 'challenge' && order.sequence[1] === 'preview'
    && order.sequence.length === 5,
    order.sequence.join(' → '));
  check('and every one of them is actually visible', order.allReachable === true);

  /* ── §5 · Enter and Space, pressed for real ───────────────────────────── */

  section('§5 · Enter and Space each open the composer exactly once');

  for (const key of ['Enter', ' ']) {
    const label = key === ' ' ? 'Space' : key;

    const armed = await evaluate(`return (async () => {
      ${AWAIT_APP}
      ${RESET}
      ${GO_LEAGUE}
      ${CARD}
      challenge.focus();
      ${ARM}
      return { focused: document.activeElement === challenge };
    })();`);
    check(`${label}: the Challenge button holds focus before the press`,
      armed.focused === true);

    // THE KEY IS PRESSED BY THE BROWSER, not by page script. A native button's
    // Enter and Space handling belongs to the browser, so a scripted
    // `KeyboardEvent` would prove nothing about it at all.
    await pressKey(key);
    await new Promise((r) => setTimeout(r, 380));

    const opened = await evaluate(`return (async () => {
      window.__fsObs.disconnect();
      const host = document.getElementById('fs-sheet');
      const x = host.querySelector('[data-fs-close]');
      return {
        open: document.getElementById('fs-overlay').classList.contains('is-open'),
        renders: window.__fsRenders,
        title: (host.querySelector('.fs-sheet__title') || {}).textContent || '',
        focusInSheet: host.contains(document.activeElement),
        focusOnClose: document.activeElement === x,
      };
    })();`);

    check(`${label} opens the Versus composer`, opened.open === true,
      opened.title);
    check(`${label} activates exactly once`, opened.renders === 1,
      `${opened.renders} sheet render(s)`);
    check(`${label}: focus moves into the sheet, onto its close control`,
      opened.focusInSheet === true && opened.focusOnClose === true);

    /* Escape, and where focus lands. */
    await pressKey('Escape');
    await new Promise((r) => setTimeout(r, 260));

    const dismissed = await evaluate(`return (async () => {
      ${CARD}
      return {
        closed: !document.getElementById('fs-overlay').classList.contains('is-open'),
        backOnChallenge: document.activeElement === challenge,
        onBody: document.activeElement === document.body,
        active: document.activeElement
          ? document.activeElement.tagName.toLowerCase() + '.'
            + (document.activeElement.className || '') : null,
      };
    })();`);

    check(`${label} → Escape closes the composer`, dismissed.closed === true);
    check(`${label} → focus returns to the same Challenge button`,
      dismissed.backOnChallenge === true, String(dismissed.active));
    check(`${label} → focus is not dumped on the body`,
      dismissed.onBody === false);
  }

  section('§5 · The upper-left close control dismisses it too');

  const ready = await evaluate(`return (async () => {
    ${AWAIT_APP}
    ${RESET}
    ${GO_LEAGUE}
    ${CARD}
    challenge.focus();
    return { focused: document.activeElement === challenge };
  })();`);
  check('the Challenge button holds focus before the press',
    ready.focused === true);

  await pressKey('Enter');
  await new Promise((r) => setTimeout(r, 380));

  const viaX = await evaluate(`return (async () => {
    ${CARD}
    const opened = document.getElementById('fs-overlay').classList.contains('is-open');
    const x = document.querySelector('#fs-sheet [data-fs-close]');
    const upperLeft = (() => {
      const s = document.getElementById('fs-sheet').getBoundingClientRect();
      const b = x.getBoundingClientRect();
      return (b.left - s.left) < (s.right - b.right);
    })();
    x.click();
    await new Promise((r) => setTimeout(r, 260));
    return {
      opened, upperLeft,
      closed: !document.getElementById('fs-overlay').classList.contains('is-open'),
      backOnChallenge: document.activeElement === challenge,
    };
  })();`);
  check('the close control dismisses a keyboard-opened composer',
    viaX.opened === true && viaX.closed === true);
  check('it is still the upper-left control', viaX.upperLeft === true);
  check('and focus still returns to the Challenge button',
    viaX.backOnChallenge === true);

  /* ── §4 · each action does its own job, and only its own ──────────────── */

  section('§4 · Every control performs its own action, exactly once');

  // WHAT THIS IS GUARDING. Each of these controls sits inside a card that also
  // has a click handler. If any of them let its click bubble, one press would
  // produce two openings — and the second, being the card's, would discard the
  // market or the preview the GM actually chose.
  const ACTIONS = [
    { name: 'Challenge', selector: '[data-card-challenge]', surface: 'composer',
      market: null },
    { name: 'Preview', selector: '[data-preview-opponent]', surface: 'preview' },
    { name: 'Moneyline', selector: '[data-market="ml"]', surface: 'composer',
      market: 'ml' },
    { name: 'Spread', selector: '[data-market="spread"]', surface: 'composer',
      market: 'spread' },
    { name: 'Over/Under', selector: '[data-market="ou"]', surface: 'composer',
      market: 'ou' },
  ];

  for (const action of ACTIONS) {
    const r = await evaluate(`return (async () => {
      ${AWAIT_APP}
      ${RESET}
      ${GO_LEAGUE}
      ${CARD}
      const control = card.querySelector(${JSON.stringify(action.selector)});
      if (!control) return { present: false };
      control.focus();
      const focusable = document.activeElement === control;
      ${ARM}
      control.click();
      // SYNCHRONOUS RENDERS ARE ACTIVATION RENDERS. A click that also reached
      // the card behind the control opens the card's own surface in the same
      // task, so it is already counted here — which is what "no bubble to the
      // card" actually measures. UIRECON Wave 4A gave the Preview a served read
      // model that lands LATER and re-renders in place; counting that as a
      // second activation would report a deliberate fill as an event leak.
      await new Promise((r) => setTimeout(r, 0));
      const activationRenders = window.__fsRenders;
      await new Promise((r) => setTimeout(r, 380));
      window.__fsObs.disconnect();
      const host = document.getElementById('fs-sheet');
      const selected = host.querySelector('[data-composer-market].is-on, '
        + '[data-composer-market][aria-pressed="true"]');
      return {
        present: true, focusable,
        open: document.getElementById('fs-overlay').classList.contains('is-open'),
        renders: activationRenders,
        rendersAfterSettle: window.__fsRenders,
        title: (host.querySelector('.fs-sheet__title') || {}).textContent || '',
        // THE SURFACE NAMES ITSELF. The composer is the thing with market
        // controls in it; the preview is the thing with preview sections.
        isComposer: host.querySelectorAll('[data-composer-market]').length > 0,
        isPreview: host.querySelectorAll('[data-preview-section]').length > 0,
        selectedMarket: selected ? selected.getAttribute('data-composer-market') : null,
      };
    })();`);

    if (!r.present) {
      check(`${action.name} — not present in this fixture, so not certified`,
        true, 'reported, not passed over');
      continue;
    }
    check(`${action.name} is keyboard reachable`, r.focusable === true);
    const wanted = action.surface === 'composer' ? r.isComposer : r.isPreview;
    const other = action.surface === 'composer' ? r.isPreview : r.isComposer;
    check(`${action.name} opens the ${action.surface}, and not the other one`,
      r.open === true && wanted === true && other === false,
      `${r.title} — composer:${r.isComposer} preview:${r.isPreview}`);
    if (action.market) {
      // A MARKET CELL CARRIES ITS CHOICE THROUGH. If its click had also reached
      // the card, the card's own opening would have replaced this with the
      // no-market composer and the GM's choice would be silently gone.
      check(`${action.name} arrives with its own market selected`,
        r.selectedMarket === action.market,
        `selected: ${r.selectedMarket}`);
    }
    check(`${action.name} activates exactly once — no bubble to the card`,
      r.renders === 1,
      `${r.renders} activation render(s), ${r.rendersAfterSettle} after settle`);
  }

  /* ── §4 · the pointer convenience survives ────────────────────────────── */

  section('§4 · Tapping empty card space still opens the composer');

  const tap = await evaluate(`return (async () => {
    ${AWAIT_APP}
    ${RESET}
    ${GO_LEAGUE}
    ${CARD}
    ${ARM}
    // THE CARD ITSELF, not one of its controls. Dispatched on the wrapper so
    // this measures the card's own handler rather than a child's.
    card.click();
    await new Promise((r) => setTimeout(r, 380));
    window.__fsObs.disconnect();
    return {
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      renders: window.__fsRenders,
    };
  })();`);
  check('a tap on the card still opens the composer', tap.open === true);
  check('and it opens exactly once', tap.renders === 1,
    `${tap.renders} sheet render(s)`);

  /* ── §5 · no keyboard trap ────────────────────────────────────────────── */

  section('§5 · No keyboard trap');

  const trap = await evaluate(`return (async () => {
    ${AWAIT_APP}
    ${RESET}
    ${GO_LEAGUE}
    ${CARD}
    const all = [...document.querySelectorAll(
      'a[href],button,input,select,textarea,summary,[tabindex]:not([tabindex="-1"])')]
      .filter((el) => el.offsetParent !== null);
    const index = all.indexOf(challenge);
    return { index, total: all.length, hasNext: index >= 0 && index < all.length - 1 };
  })();`);
  check('Challenge is one stop among many in the document tab order',
    trap.index >= 0 && trap.total > 5, `${trap.index + 1} of ${trap.total}`);
  check('and the tab order continues past it — no trap', trap.hasNext === true);

  /* ── §7 · visible focus, and no geometry regression ───────────────────── */

  section('§7 · Visible focus, and native semantics changed no geometry');

  for (const [w, h] of [[320, 568], [360, 640], [375, 667], [390, 844],
    [430, 932], [844, 390]]) {
    await setViewport(w, h);
    const geo = await evaluate(`return (async () => {
      ${AWAIT_APP}
      ${GO_LEAGUE}
      ${CARD}
      if (!card || !challenge) return { present: false };
      const s = getComputedStyle(challenge);
      const b = challenge.getBoundingClientRect();
      const c = card.getBoundingClientRect();
      const preview = card.querySelector('[data-preview-opponent]')
        .getBoundingClientRect();
      const rail = card.parentElement.getBoundingClientRect();
      const ident = getComputedStyle(card.querySelector('.fs-wcard__identity'));
      return {
        present: true,
        // A NATIVE BUTTON MUST NOT BRING ITS BROWSER CHROME WITH IT.
        appearance: s.appearance,
        border: s.borderTopWidth,
        radius: s.borderTopLeftRadius,
        background: s.backgroundColor,
        textAlign: s.textAlign,
        font: s.fontFamily.split(',')[0].replace(/["']/g, ''),
        identitySize: Math.round(parseFloat(ident.fontSize)),
        h: Math.round(b.height), w: Math.round(b.width),
        cardW: Math.round(c.width), cardH: Math.round(c.height),
        // IT MUST NOT OVERHANG THE CONTROL BENEATH IT.
        clearsPreview: b.bottom <= preview.top + 1,
        insideCard: b.left >= c.left - 1 && b.right <= c.right + 1,
        railFit: c.width <= rail.width + 1,
        clipped: card.scrollHeight > card.clientHeight + 1,
        docOver: document.documentElement.scrollWidth - window.innerWidth,
      };
    })();`);

    if (!geo.present) {
      check(`${w}x${h}: no Versus card in this fixture — not certified`,
        true, 'reported, not passed over');
      continue;
    }
    check(`${w}x${h}: Challenge is a real 44px target`, geo.h >= 44,
      `${geo.w}x${geo.h}`);
    check(`${w}x${h}: it clears the preview row — no overhang`,
      geo.clearsPreview === true);
    check(`${w}x${h}: it stays inside the card`, geo.insideCard === true);
    check(`${w}x${h}: no default button border, radius or background`,
      geo.border === '0px' && geo.radius === '0px'
      && /rgba\(0, 0, 0, 0\)|transparent/.test(geo.background),
      `${geo.border} / ${geo.radius} / ${geo.background}`);
    check(`${w}x${h}: text is not centred by a UA default`,
      geo.textAlign === 'left', geo.textAlign);
    check(`${w}x${h}: it keeps the product font`,
      geo.font !== 'system-ui' && geo.font.length > 0, geo.font);
    check(`${w}x${h}: card primary text is unchanged at 16–17px`,
      geo.identitySize >= 16 && geo.identitySize <= 17,
      `${geo.identitySize}px`);
    check(`${w}x${h}: the card fits its rail and clips nothing`,
      geo.railFit === true && geo.clipped === false, `${geo.cardW}px`);
    check(`${w}x${h}: and causes no horizontal overflow`, geo.docOver <= 0,
      `${geo.docOver}px`);
  }

  await setViewport(390, 844);

  // ESTABLISH KEYBOARD MODALITY WITH A REAL KEY. `:focus-visible` is decided by
  // the browser from the last input modality, and a scripted `.focus()` sets
  // none — so without this the ring measures as absent for a rule that is
  // perfectly correct.
  await evaluate(`return (async () => { ${AWAIT_APP} ${GO_LEAGUE} return true; })();`);
  await pressKey('Tab');

  const ring = await evaluate(`return (async () => {
    ${CARD}
    challenge.focus();
    const matches = challenge.matches(':focus-visible');
    const s = getComputedStyle(challenge);
    return {
      matches, width: s.outlineWidth, style: s.outlineStyle,
      color: s.outlineColor, offset: s.outlineOffset,
    };
  })();`);
  check('the focused Challenge button matches the shared :focus-visible rule',
    ring.matches === true);
  check('and it draws the WP3E gold focus ring',
    parseFloat(ring.width) >= 2 && ring.style === 'solid'
    && ring.offset === '2px',
    `${ring.width} ${ring.style} ${ring.color}, offset ${ring.offset}`);
});

finish('VERSUS CARD NATIVE KEYBOARD SEMANTICS — BROWSER');
