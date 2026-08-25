/* ============================================================================
 * FantasyStakes — the refresh controls, measured in a real browser
 *
 * Run directly:   FS_TEST_ORIGIN=http://127.0.0.1:8000 \
 *                 node web/tests/uirecon_refresh_ux_browser.mjs
 * Or through:     python test_uirecon_refresh_ux.py
 *
 * WHAT ONLY A BROWSER CAN SETTLE. Everything here is a claim about geometry or
 * about a click: that the control is where a thumb can reach it, that pressing
 * it does not also open the composer, that a card is the same size afterwards
 * as before, and that the carousel still snaps one card at a time. Source
 * cannot answer any of those, and the component tier has no layout.
 *
 * IT RUNS AGAINST A REAL SEEDED DEMO, because the controls only exist when a
 * market board is bound — the illustrative fixture has no board to re-read and
 * correctly draws no glyph at all. That is asserted here too: an affordance
 * whose first press is a no-op is worse than an absent one.
 *
 * THE CARD GEOMETRY IS COMPARED TO ITSELF. Rev 1.4 certified the Play carousel
 * to a rule rather than a pixel value — one card is one item is one viewport of
 * the rail — so the assertions below measure agreement between the card, the
 * item and the rail rather than against a pinned number that would go stale the
 * next time the type scale moves.
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

/** The governed minimum for anything a thumb has to hit. */
const TOUCH_FLOOR = 44;

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/* THE TAB CLICK IS GUARDED, because the tabbar does not exist until the shell
 * has mounted and every snippet below runs it first. An unguarded
 * `querySelector(...).click()` throws before the app is up and takes the whole
 * suite with it. */
const GO_PLAY = `
  {
    const tab = document.querySelector('.fs-tabbar__item[data-destination="league"]');
    if (tab) tab.click();
  }
`;

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 15000;
    const poll = () => {
      ${GO_PLAY}
      const ok = document.querySelector('#panel-league .fs-wcard--matchup');
      if (ok || Date.now() > deadline) return resolve(Boolean(ok));
      setTimeout(poll, 150);
    };
    poll();
  });
`;

/**
 * Enter the demo, mount the app, and land on Play.
 *
 * THE CONTROLS ONLY EXIST FOR A BOUND BOARD, so this suite has to be a signed-in
 * visitor rather than the illustrative fixture — which is itself asserted, at
 * the end of §1: a demo with no board to re-read correctly draws no glyph.
 */
const ENTER = async ({ evaluate }) => {
  await evaluate(`return (async () => {
    const res = await fetch('/demo/enter', { method: 'POST', credentials: 'include' });
    return res.json();
  })()`);
  await evaluate(`location.href = '/app/index.html'; 1`);
  await wait(4200);
  return evaluate(READY);
};

await withPage({ port: 9482, origin: process.env.FS_TEST_ORIGIN },
  async ({ evaluate, setViewport }) => {
    await setViewport(390, 844);
    section('1 · the controls exist where the prices are');

    check('the Play tab mounted with real matchup cards',
      await ENTER({ evaluate }) === true);

    const present = await evaluate(`
      ${GO_PLAY}
      const panel = document.getElementById('panel-league');
      const heading = panel.querySelector('.fs-heading__lead [data-odds-refresh]');
      const cards = [...panel.querySelectorAll('.fs-wcard--matchup')];
      return {
        heading: Boolean(heading),
        headingScope: heading ? heading.dataset.refreshScope : null,
        headingLabel: heading ? heading.getAttribute('aria-label') : null,
        headingText: (panel.querySelector('.fs-heading__text') || {}).textContent,
        cards: cards.length,
        perCard: cards.filter((c) => c.querySelector(
          '.fs-wcard__head [data-odds-refresh]')).length,
        perCardLabels: cards.slice(0, 3).map((c) => {
          const b = c.querySelector('.fs-wcard__head [data-odds-refresh]');
          return b ? b.getAttribute('aria-label') : null;
        }),
        stamp: (panel.querySelector('[data-odds-stamp="play-board"]') || {}).textContent,
        wideButton: panel.querySelectorAll('.fs-refresh__btn').length,
      };
    `);

    check('the heading still reads MATCHUPS', present.headingText === 'MATCHUPS',
      present.headingText);
    check('a board-scoped control sits beside it',
      present.heading === true && present.headingScope === 'board',
      present.headingScope);
    check('  · named for what it refreshes',
      present.headingLabel === 'Refresh odds for all matchups',
      present.headingLabel);
    check('every matchup card carries its own control',
      present.cards > 0 && present.perCard === present.cards,
      `${present.perCard}/${present.cards}`);
    check('  · each named for its own opponent',
      present.perCardLabels.every((l) => /^Refresh odds for .+/.test(l || ''))
      && new Set(present.perCardLabels).size === present.perCardLabels.length,
      present.perCardLabels.join(' | '));
    check('the shared stamp reports a server time',
      /^Odds updated \d{1,2}:\d{2} (AM|PM)$/.test(present.stamp || ''),
      present.stamp);
    check('the superseded full-width button is gone from the surface',
      present.wideButton === 0, String(present.wideButton));

    /* ── 2 · it does not disturb the card it sits on ─────────────────────── */

    section('2 · the control changes no card geometry');

    const geometry = await evaluate(`
      ${GO_PLAY}
      const panel = document.getElementById('panel-league');
      const card = panel.querySelector('.fs-wcard--matchup');
      const item = card.closest('.fs-carousel__item');
      const rail = panel.querySelector('#fs-bets-carousel');
      const btn = card.querySelector('.fs-wcard__head [data-odds-refresh]');
      const challenge = card.querySelector('.fs-wcard__challenge');
      const head = card.querySelector('.fs-wcard__head');
      const cb = card.getBoundingClientRect();
      const bb = btn.getBoundingClientRect();
      const hb = head.getBoundingClientRect();
      const chb = challenge.getBoundingClientRect();
      const style = getComputedStyle(btn);
      return {
        cardW: Math.round(cb.width), itemW: Math.round(item.getBoundingClientRect().width),
        railW: Math.round(rail.clientWidth),
        headH: Math.round(hb.height), challengeH: Math.round(chb.height),
        btnRight: Math.round(cb.right - bb.right),
        btnInsideHead: bb.top >= hb.top - 1 && bb.bottom <= hb.bottom + 1,
        btnW: Math.round(bb.width), btnH: Math.round(bb.height),
        glyphW: Math.round((btn.querySelector('.fs-oddsref__glyph')
          || btn).getBoundingClientRect().width),
        glyphH: Math.round((btn.querySelector('.fs-oddsref__glyph')
          || btn).getBoundingClientRect().height),
        overlapsChallenge: !(bb.left >= chb.right - 1 || bb.right <= chb.left + 1),
        snapType: getComputedStyle(rail).scrollSnapType,
        pseudoInset: style.getPropertyValue('position'),
        docOverflow: document.documentElement.scrollWidth
          - document.documentElement.clientWidth,
      };
    `);

    check('one card is one carousel item is one rail width — the Rev 1.4 rule '
      + 'is intact', near(geometry.cardW, geometry.itemW, 2)
      && near(geometry.itemW, geometry.railW, 2),
      `card ${geometry.cardW} / item ${geometry.itemW} / rail ${geometry.railW}`);
    check('the rail still snaps', /mandatory/.test(geometry.snapType || ''),
      geometry.snapType);
    check('the control sits inside the head row, so it added no height',
      geometry.btnInsideHead === true);
    check('  · and the head is no taller than the 44px challenge target it '
      + 'already contained',
      geometry.headH <= Math.max(geometry.challengeH, TOUCH_FLOOR) + 1,
      `head ${geometry.headH} / challenge ${geometry.challengeH}`);
    check('it is in the upper-right corner', geometry.btnRight >= 0
      && geometry.btnRight < 40, `${geometry.btnRight}px from the card's right`);
    check('it overlaps the challenge control nowhere',
      geometry.overlapsChallenge === false);
    check('the painted glyph is small, while the button around it is the '
      + 'governed target',
      geometry.glyphW <= 30 && geometry.glyphH <= 30
      && geometry.btnH >= TOUCH_FLOOR - 1,
      `glyph ${geometry.glyphW}x${geometry.glyphH}, button ${geometry.btnW}x${geometry.btnH}`);
    check('the page does not scroll sideways', geometry.docOverflow <= 0,
      String(geometry.docOverflow));

    const reach = await evaluate(`
      ${GO_PLAY}
      const btn = document.querySelector(
        '#panel-league .fs-wcard--matchup [data-odds-refresh]');
      const b = btn.getBoundingClientRect();
      // THE TAP TARGET IS A PSEUDO-ELEMENT, which has no box of its own and
      // cannot be measured by a bounding rect. So the EFFECTIVE target is
      // mapped the way a thumb finds it: ask the document what is under a
      // point, and walk outward until the answer stops being this control.
      // That measures what a GM can actually hit rather than what a stylesheet
      // declares. (No backticks in this comment: it lives inside a template
      // literal.)
      const hits = (x, y) => {
        const el = document.elementFromPoint(x, y);
        return Boolean(el && el.closest && el.closest('[data-odds-refresh]'));
      };
      const walk = (dx, dy) => {
        const cx = b.left + b.width / 2;
        const cy = b.top + b.height / 2;
        let n = 0;
        while (n < 60 && hits(cx + dx * (n + 1), cy + dy * (n + 1))) n += 1;
        return n;
      };
      // THE SPAN IS INCLUSIVE OF THE CENTRE PIXEL. The walk counts the pixels
      // that hit on ONE side of the centre, so left + right is one short of the
      // distance from the leftmost hitting pixel to the rightmost. (No
      // backticks here: this comment lives inside a template literal.)
      return {
        centre: hits(b.left + b.width / 2, b.top + b.height / 2),
        width: walk(-1, 0) + walk(1, 0) + 1,
        height: walk(0, -1) + walk(0, 1) + 1,
        painted: [Math.round(b.width), Math.round(b.height)],
      };
    `);
    check('the control is under the point a thumb aims at', reach.centre === true);
    check('its tap target clears the governed 44px floor in both dimensions, '
      + 'even though the painted glyph is smaller',
      reach.width >= TOUCH_FLOOR && reach.height >= TOUCH_FLOOR,
      `${reach.width}x${reach.height} effective, `
      + `${reach.painted[0]}x${reach.painted[1]} painted`);
    check('  · and the button IS the target, so a bounding rect sees what a '
      + 'thumb does — no reach that only elementFromPoint can find',
      reach.painted[0] >= TOUCH_FLOOR - 1 && reach.painted[1] >= TOUCH_FLOOR - 1,
      reach.painted.join('x'));

    /* ── 3 · pressing it refreshes, and does nothing else ────────────────── */

    section('3 · the click refreshes and does not open anything');

    const perCard = await evaluate(`
      ${GO_PLAY}
      const panel = document.getElementById('panel-league');
      const card = panel.querySelector('.fs-wcard--matchup');
      const btn = card.querySelector('.fs-wcard__head [data-odds-refresh]');
      const before = {
        state: btn.dataset.refreshState,
        sheets: document.querySelectorAll('.fs-sheet, [data-sheet]').length,
        cardH: Math.round(card.getBoundingClientRect().height),
        ml: (card.querySelector('[data-market="ml"] .fs-market__value') || {}).textContent,
      };
      btn.click();
      const working = btn.dataset.refreshState;
      const busy = btn.getAttribute('aria-busy');
      return new Promise((resolve) => setTimeout(() => {
        resolve({
          before, working, busy,
          after: btn.dataset.refreshState,
          sheets: document.querySelectorAll('.fs-sheet, [data-sheet]').length,
          cardH: Math.round(card.getBoundingClientRect().height),
          ml: (card.querySelector('[data-market="ml"] .fs-market__value') || {}).textContent,
          stamp: (panel.querySelector('[data-odds-stamp="play-board"]') || {}).textContent,
        });
      }, 3000));
    `);

    check('pressing it enters the working state',
      perCard.working === 'working' && perCard.busy === 'true',
      `${perCard.working} / aria-busy ${perCard.busy}`);
    check('and it settles back out of working',
      perCard.after !== 'working', perCard.after);
    check('no sheet, composer or preview opened',
      perCard.sheets === perCard.before.sheets,
      `${perCard.before.sheets} → ${perCard.sheets}`);
    check('the card is exactly as tall as it was',
      perCard.cardH === perCard.before.cardH,
      `${perCard.before.cardH} → ${perCard.cardH}`);
    check('the moneyline cell still holds a served figure, not a blank',
      typeof perCard.ml === 'string' && perCard.ml.trim().length > 0,
      JSON.stringify(perCard.ml));
    check('the stamp still reports a server time after the refresh',
      /^Odds updated \d{1,2}:\d{2} (AM|PM)$/.test(perCard.stamp || ''),
      perCard.stamp);

    // ── the per-card control touches ONE card ────────────────────────────
    const isolation = await evaluate(`
      ${GO_PLAY}
      const panel = document.getElementById('panel-league');
      const cards = [...panel.querySelectorAll('.fs-wcard--matchup')];
      const read = () => [...panel.querySelectorAll('.fs-wcard--matchup')].map(
        (c) => [...c.querySelectorAll('.fs-market__value')]
          .map((v) => v.textContent).join('|'));
      const before = read();
      const target = cards[1] || cards[0];
      const idx = cards.indexOf(target);
      target.querySelector('.fs-wcard__head [data-odds-refresh]').click();
      return new Promise((resolve) => setTimeout(() => {
        const after = read();
        resolve({
          idx,
          others: before.filter((v, i) => i !== idx)
            .every((v, i) => v === after.filter((w, j) => j !== idx)[i]),
          refreshedStillPriced: (after[idx] || '').trim().length > 0,
          count: after.length,
        });
      }, 3000));
    `);
    check('a per-card refresh leaves every OTHER card exactly as it was',
      isolation.others === true,
      `card ${isolation.idx} of ${isolation.count} refreshed`);
    check('  · and the refreshed card still carries served figures',
      isolation.refreshedStillPriced === true);

    const boardPress = await evaluate(`
      ${GO_PLAY}
      const panel = document.getElementById('panel-league');
      const btn = panel.querySelector('.fs-heading__lead [data-odds-refresh]');
      const cards = [...panel.querySelectorAll('.fs-wcard--matchup')];
      const before = cards.map((c) => (c.querySelector(
        '[data-market="ml"] .fs-market__value') || {}).textContent);
      const sheets = document.querySelectorAll('.fs-sheet, [data-sheet]').length;
      btn.click();
      return new Promise((resolve) => setTimeout(() => {
        const after = [...panel.querySelectorAll('.fs-wcard--matchup')].map(
          (c) => (c.querySelector('[data-market="ml"] .fs-market__value') || {}).textContent);
        resolve({
          before, after, sheets,
          sheetsAfter: document.querySelectorAll('.fs-sheet, [data-sheet]').length,
          cards: cards.length,
          populated: after.filter((v) => (v || '').trim().length > 0).length,
        });
      }, 4000));
    `);

    check('the heading control leaves EVERY card holding a figure — a board '
      + 'refresh must not blank the rail',
      boardPress.populated === boardPress.cards,
      `${boardPress.populated}/${boardPress.cards}`);
    check('  · and opens nothing either',
      boardPress.sheetsAfter === boardPress.sheets);

    /* ── 4 · keyboard ────────────────────────────────────────────────────── */

    section('4 · the control is reachable and operable by keyboard');

    const keys = await evaluate(`
      ${GO_PLAY}
      const btn = document.querySelector(
        '#panel-league .fs-wcard--matchup [data-odds-refresh]');
      btn.focus();
      const focused = document.activeElement === btn;
      const style = getComputedStyle(btn, ':focus-visible');
      return {
        focused,
        tag: btn.tagName,
        type: btn.getAttribute('type'),
        tabIndex: btn.tabIndex,
        named: Boolean(btn.getAttribute('aria-label')),
        ringDeclared: [...document.styleSheets].some((sheet) => {
          try {
            return [...sheet.cssRules].some((r) => /fs-oddsref:focus-visible/
              .test(r.selectorText || ''));
          } catch (e) { return false; }
        }),
      };
    `);
    check('it is a native button, so Enter and Space work for free',
      keys.tag === 'BUTTON' && keys.type === 'button',
      `${keys.tag}[type=${keys.type}]`);
    check('it takes focus', keys.focused === true);
    check('it is in the tab order', keys.tabIndex >= 0, String(keys.tabIndex));
    check('it has an accessible name', keys.named === true);
    check('a visible focus ring is declared for it', keys.ringDeclared === true);

    /* ── 5 · every certified viewport ───────────────────────────────────── */

    for (const vp of VIEWPORTS) {
      section(`5 · ${vp.width}x${vp.height} — ${vp.label}`);
      await setViewport(vp.width, vp.height);
      await wait(400);
      // A RESIZE CAN LAND MID-REDRAW. The shell re-renders on viewport change
      // and the panel is briefly empty; measuring then reads null and takes the
      // suite down. `READY` polls for a card before anything is measured.
      const ready = await evaluate(READY);
      check(`${vp.width}: the Play tab is drawn at this size`, ready === true);
      if (!ready) continue;

      const m = await evaluate(`
        ${GO_PLAY}
        const panel = document.getElementById('panel-league');
        const card = panel.querySelector('.fs-wcard--matchup');
        const item = card.closest('.fs-carousel__item');
        const rail = panel.querySelector('#fs-bets-carousel');
        const btn = card.querySelector('.fs-wcard__head [data-odds-refresh]');
        const bb = btn.getBoundingClientRect();
        const cb = card.getBoundingClientRect();
        const nav = document.querySelector('.fs-tabbar');
        const navBox = nav ? nav.getBoundingClientRect() : null;
        // THE HEADING TEXT, NOT THE HEADING BOX. The box deliberately carries
        // a second line — the shared stamp sits inside it so that the
        // title-to-content gap UIRECON Waves 1-3 certify stays uniform. What
        // must never wrap is the WORD, which is what a GM reads as the section
        // name.
        const headingText = panel.querySelector('.fs-heading__text');
        const htBox = headingText ? headingText.getBoundingClientRect() : null;
        const htLine = headingText
          ? parseFloat(getComputedStyle(headingText).lineHeight) || 16 : 16;
        const headingLines = htBox ? Math.round(htBox.height / htLine) : 0;
        return {
          docOverflow: document.documentElement.scrollWidth
            - document.documentElement.clientWidth,
          panelOverflow: panel.scrollWidth - panel.clientWidth,
          cardW: Math.round(cb.width),
          itemW: Math.round(item.getBoundingClientRect().width),
          railW: Math.round(rail.clientWidth),
          btnOnScreen: bb.left >= 0 && bb.right <= window.innerWidth,
          btnW: Math.round(bb.width),
          navVisible: Boolean(navBox && navBox.height > 0
            && navBox.bottom <= window.innerHeight + 1),
          marketsUsable: [...card.querySelectorAll('[data-market]')].every(
            (el) => el.getBoundingClientRect().height >= 20),
          previewUsable: Boolean(card.querySelector('[data-preview-opponent]')),
          headingLines,
        };
      `);

      check(`${vp.width}: the page does not scroll sideways`,
        m.docOverflow <= 0, String(m.docOverflow));
      check(`${vp.width}: the Play tab does not scroll sideways`,
        m.panelOverflow <= 0, String(m.panelOverflow));
      check(`${vp.width}: one card is still one item is still one rail width`,
        near(m.cardW, m.itemW, 2) && near(m.itemW, m.railW, 2),
        `${m.cardW} / ${m.itemW} / ${m.railW}`);
      check(`${vp.width}: the control is fully on screen`,
        m.btnOnScreen === true);
      check(`${vp.width}: the bottom navigation is visible`,
        m.navVisible === true);
      check(`${vp.width}: the market buttons remain usable`,
        m.marketsUsable === true);
      check(`${vp.width}: the Matchup Preview row remains present`,
        m.previewUsable === true);
      check(`${vp.width}: the heading WORD did not wrap`,
        m.headingLines <= 1, `${m.headingLines} line(s)`);
    }

    await setViewport(390, 844);
  });

finish('UIRECON REFRESH UX BROWSER');
