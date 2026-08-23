/* ============================================================================
 * FantasyStakes — FINAL POR · UI-5 · Wrap Up
 *
 * WHY THIS RUNS IN A BROWSER. §29 is almost entirely geometry: three sections
 * that FIT, collapsed cards that are the SAME width and height, an expansion
 * bounded at ~75vh with its own internal scroll, and a close control in the
 * upper LEFT. None of that is readable from source.
 *
 * W8 SAYS UPPER LEFT BECAUSE THE OWNER RULED IT SO, superseding this section's
 * own older wording. The corner is certified in depth by `finalpor_closex.mjs`,
 * across three surfaces and three widths; W8 remains here so that Wrap Up --
 * the surface the ruling calls out by name -- carries the check itself rather
 * than inheriting it from a suite somebody could run separately.
 *
 * WHAT IS ASSERTED, AND WHY EACH CASE EXISTS:
 *
 *   W1  the three sections are exactly §29's, in order
 *   W2  every collapsed card is the same width                     one rail
 *   W3  every collapsed card is the same height                    one shell
 *   W4  all three sections fit, with nothing clipped
 *   W5  no page-level horizontal scroll
 *   W6  no bottom-navigation collision
 *   W7  an expansion is bounded at ~75vh and scrolls internally
 *   W8  its close control is in the UPPER LEFT                 owner ruling
 *   W9  the Yahoo expansion carries a Fantasy Football breakdown ONLY
 *   W10 the FantasyStakes expansion carries FF *and* Bet Market breakdowns
 *   W11 the Prop Pool expansion carries FF drivers and Pool/market analysis
 *   W12 no expansion fabricates analysis it has no source for
 *
 * W3 IS THE ONE THAT DRIFTS. Three sections drawing three different card
 * heights is what Wave 4B set out to fix, and a single card that grows because
 * its data happened to be longer would reintroduce it without any rule
 * changing. It is measured across every card in every section.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();

const VIEWPORTS = [
  { width: 320, height: 568, label: 'smallest certified phone' },
  { width: 375, height: 667, label: 'standard phone' },
  { width: 390, height: 844, label: 'modern phone' },
];

/** §29's three sections, in order. */
const SECTIONS = [
  'YAHOO LEAGUE MATCHUPS',
  'FANTASYSTAKES MATCHUPS',
  'FANTASYSTAKES PROP POOLS',
];

/* Vocabulary nothing in this application has a source for. A sentence using
 * any of it would be fabricated analysis, which §29 forbids by name. */
const FABRICATED = [
  'injury', 'injured', 'questionable', 'doubtful', 'weather', 'wind', 'rain',
  'snow', 'beat writer', 'reportedly', 'sources say', 'snap count',
  'practice report', 'coach said',
];

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 8000;
    const poll = () => {
      const mounted = document.querySelector('.fs-tabbar__item')
        && document.querySelector('#panel-week');
      if (mounted || Date.now() > deadline) return resolve(Boolean(mounted));
      setTimeout(poll, 100);
    };
    poll();
  });
`;

const GO_WRAP = `
  { const t = document.querySelector(
      '.fs-tabbar__item[data-destination="week"]');
    if (t) t.click(); }
`;

await withPage({ port: 9487, settleMs: 2500 }, async ({ evaluate, setViewport }) => {

  if (!process.env.FS_TEST_AUTH_EMAIL) {
    const entered = await evaluate(`return (async () => {
      const res = await fetch('/demo/enter', {
        method: 'POST', credentials: 'include'
      });
      return res.ok;
    })()`);
    report.check('the public showcase entry route succeeds before UI-5 is measured',
      entered === true, String(entered));
  }

  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    const tag = `${vp.width}×${vp.height}`;
    report.section(`UI-5 · Wrap Up at ${tag} (${vp.label})`);
    report.check(`${tag} · the application mounted`,
      await evaluate(READY) === true);

    const m = await evaluate(`
      ${GO_WRAP}
      const panel = document.getElementById('panel-week');
      const mods = [...panel.querySelectorAll('.fs-wkmod')];
      const nav = document.querySelector('.fs-tabbar');
      const box = (el) => {
        const r = el.getBoundingClientRect();
        return { left: Math.round(r.left), right: Math.round(r.right),
                 top: Math.round(r.top), bottom: Math.round(r.bottom),
                 w: Math.round(r.width), h: Math.round(r.height) };
      };
      const cards = [];
      for (const mod of mods) {
        for (const item of mod.querySelectorAll('.fs-rescar__item')) {
          const card = item.firstElementChild;
          if (!card) continue;
          cards.push({
            module: mod.getAttribute('data-module'),
            w: Math.round(item.getBoundingClientRect().width),
            h: Math.round(card.getBoundingClientRect().height),
            clipped: card.scrollHeight > card.clientHeight + 1,
          });
        }
      }
      return {
        titles: mods.map((mod) => {
          const h = mod.querySelector('.fs-heading__text');
          return h ? h.textContent.replace(/\\s+/g, ' ').trim() : null;
        }),
        modules: mods.map((mod) => mod.getAttribute('data-module')),
        rails: mods.map((mod) => {
          const rail = mod.querySelector('.fs-rescar');
          if (!rail) return null;
          return { clientW: rail.clientWidth,
                   items: [...rail.querySelectorAll('.fs-rescar__item')].length };
        }),
        cards,
        panelBox: box(panel),
        lastBottom: mods.length
          ? Math.round(mods[mods.length - 1].getBoundingClientRect().bottom)
          : null,
        navTop: nav ? Math.round(nav.getBoundingClientRect().top) : null,
        docScrollW: document.documentElement.scrollWidth,
        docClientW: document.documentElement.clientWidth,
      };
    `);

    /* ── W1 — the three sections ─────────────────────────────────────── */
    report.check(`${tag} · exactly three sections`,
      m.titles.length === 3, JSON.stringify(m.titles));
    report.check(`${tag} · headed §29's three, in order`,
      JSON.stringify(m.titles) === JSON.stringify(SECTIONS),
      JSON.stringify(m.titles));

    /* ── W2/W3 — one width, one height ───────────────────────────────── */
    const widths = [...new Set(m.cards.map((c) => c.w))];
    const heights = [...new Set(m.cards.map((c) => c.h))];
    report.check(`${tag} · there are cards to measure`,
      m.cards.length > 0, `${m.cards.length} cards`);
    report.check(`${tag} · every collapsed card is the same width`,
      widths.length <= 1, `widths ${widths.join('/')}`);
    report.check(`${tag} · and each is one rail wide`,
      m.rails.every((r) => !r || widths.length === 0
        || Math.abs(widths[0] - r.clientW) <= 1),
      `card ${widths[0]} vs rails ${m.rails.map((r) => r && r.clientW).join('/')}`);
    report.check(`${tag} · every collapsed card is the same height`,
      heights.length <= 1, `heights ${heights.join('/')}`);

    /* ── W4 — nothing clipped ────────────────────────────────────────── */
    const clipped = m.cards.filter((c) => c.clipped);
    report.check(`${tag} · no card is clipped`,
      clipped.length === 0,
      clipped.map((c) => c.module).join(', ') || 'none');

    /* ── W5/W6 — the page and the nav ────────────────────────────────── */
    report.check(`${tag} · no page-level horizontal scroll`,
      m.docScrollW <= m.docClientW + 1,
      `${m.docScrollW} vs ${m.docClientW}`);
    if (m.navTop !== null && m.lastBottom !== null) {
      report.check(`${tag} · the last section clears the bottom navigation`,
        m.lastBottom <= m.navTop + 1,
        `section bottom ${m.lastBottom} vs nav top ${m.navTop}`);
    }
  }

  /* ── W7..W12 — the expansions ───────────────────────────────────────── */

  await setViewport(390, 844);
  await evaluate(READY);

  const OPEN = (moduleId) => `return (async () => {
    ${GO_WRAP}
    const mod = document.querySelector('.fs-wkmod[data-module="${moduleId}"]');
    const card = mod ? mod.querySelector('.fs-rescar__item > *') : null;
    if (!card) return { opened: false, reason: 'no card in ' + '${moduleId}' };
    // THE HANDLER IS BOUND ON THE ELEMENT CARRYING data-card-action, which may
    // be the card itself or a descendant. Reported when neither is present, so
    // a card with no expansion at all is a stated finding rather than a
    // silent miss.
    const target = card.matches('[data-card-action]')
      ? card : card.querySelector('[data-card-action]');
    if (!target) {
      return { opened: false,
               reason: 'card carries no data-card-action: ' + card.className };
    }
    target.click();
    await new Promise((r) => setTimeout(r, 700));
    // THE SHEET IS #fs-sheet INSIDE #fs-overlay.is-open. shell.js opens the
    // overlay and renders the sheet body into the host; there is no
    // .fs-sheet.is-open element, which is why the first version of this probe
    // found nothing and reported every content check as empty.
    // (No backticks in here: this comment lives inside a template literal.)
    const overlay = document.getElementById('fs-overlay');
    const sheet = overlay && overlay.classList.contains('is-open')
      ? document.getElementById('fs-sheet') : null;
    if (!sheet) return { opened: false, reason: 'no sheet opened' };
    const sr = sheet.getBoundingClientRect();
    const close = sheet.querySelector('[data-fs-close], .fs-sheet__close');
    const cr = close ? close.getBoundingClientRect() : null;
    // THE SHEET ITSELF may be the scroller, so it is included rather than only
    // its descendants -- shell.js resets host.scrollTop, which is a strong hint
    // that the host is the scrolling element.
    const scroller = [sheet, ...sheet.querySelectorAll('*')].find((el) => {
      const cs = getComputedStyle(el);
      return /auto|scroll/.test(cs.overflowY);
    });
    // THE PRODUCT'S REAL SECTION-TITLE SELECTORS, and NOT the sheet's own
    // title. The first version of this listed .fs-psec__title and
    // .fs-sheet__sectitle -- neither of which exists anywhere in this build --
    // plus h3, which matches .fs-sheet__title. So "its sections are named"
    // passed on every sheet that had a TITLE, whether or not it had a single
    // named section, which is the vacuous pass W9-W11 rest on.
    // .fs-prev__title is what collapsible() draws and .fs-rule__head is what a
    // flat titled block draws; between them they are every section head in the
    // product.
    // (No backticks in here: this comment lives inside a template literal.)
    const titles = [...sheet.querySelectorAll(
      '.fs-prev__title, .fs-rule__head')]
      .map((h) => h.textContent.replace(/\\s+/g, ' ').trim())
      .filter(Boolean);
    return {
      opened: true,
      h: Math.round(sr.height),
      viewportH: window.innerHeight,
      ratio: sr.height / window.innerHeight,
      closeInUpperRight: cr && close
        ? (cr.left >= sr.left + sr.width / 2
           && cr.top - sr.top <= sr.height / 4) : null,
      closeInUpperLeft: cr && close
        ? (cr.left < sr.left + sr.width / 2
           && cr.top - sr.top <= sr.height / 4) : null,
      hasInternalScroll: Boolean(scroller),
      titles,
      text: sheet.textContent.replace(/\\s+/g, ' ').trim().toLowerCase(),
    };
  })();`;

  for (const [moduleId, label] of [
    ['yahoo', 'Yahoo league matchup'],
    ['bets', 'FantasyStakes matchup'],
    ['pools', 'FantasyStakes Prop Pool'],
  ]) {
    report.section(`UI-5 · the ${label} expansion`);
    const s = await evaluate(OPEN(moduleId));
    report.check(`${label} — the card expands`,
      s.opened === true, s.reason || 'opened');
    if (!s.opened) continue;

    /* 0.76, not 0.80: `.fs-sheet` was tightened from a 80% max-height to the
     * 75% this section actually asks for. The tolerance is on the "~". */
    report.check(`${label} — bounded at about 75vh`,
      s.ratio <= 0.76,
      `${s.h}px of ${s.viewportH}px = ${(s.ratio * 100).toFixed(0)}vh`);
    report.check(`${label} — it scrolls internally rather than growing`,
      s.hasInternalScroll === true, String(s.hasInternalScroll));
    report.check(`${label} — the close control is in the UPPER LEFT`,
      s.closeInUpperLeft === true,
      `upperRight=${s.closeInUpperRight} upperLeft=${s.closeInUpperLeft}`);

    /* WORD BOUNDARIES, NOT SUBSTRINGS. The first version matched `rain` inside
     * the team name "Gravy Train" and reported fabricated weather analysis on a
     * clean sheet — a false positive that would have sent someone hunting a
     * defect that was not there. */
    const B_B = '\\b';
    const B_S = '\\s+';
    const used = FABRICATED.filter((w) =>
      // DOUBLED, AND THIS CHECK HAS NEVER RUN UNTIL NOW. In an ordinary JS
      // string a single backslash-b is the BACKSPACE character and a single
      // backslash-s is a bare s, so the pattern built here was
      // <backspace>word s+<backspace> -- which matches nothing, ever. The
      // assertion below therefore reported a clean sheet on every sheet,
      // including one that fabricated every word in the list. It is the
      // §29 assertion that matters most, and it was the one silently
      // switched off.
      new RegExp(B_B + w.replace(/ /g, B_S) + B_B, 'i').test(s.text));
    report.check(`${label} — fabricates no analysis it has no source for`,
      used.length === 0, used.join(', ') || 'clean');
    report.check(`${label} — its sections are named`,
      s.titles.length > 0, JSON.stringify(s.titles));

    const hasFF = s.titles.some((t) => /READ|LINEUP|BREAKDOWN|DRIVERS/i.test(t));
    const hasMarket = s.titles.some((t) => /LINE|MARKET|ON OFFER/i.test(t));
    if (moduleId === 'yahoo') {
      report.check(`${label} — carries a Fantasy Football breakdown`,
        hasFF, JSON.stringify(s.titles));
      report.check(`${label} — and NO bet-market breakdown (§29)`,
        !hasMarket, JSON.stringify(s.titles));
    } else if (moduleId === 'bets') {
      report.check(`${label} — carries a Fantasy Football breakdown`,
        hasFF, JSON.stringify(s.titles));
      report.check(`${label} — AND a bet-market breakdown`,
        hasMarket, JSON.stringify(s.titles));
    } else {
      // UI-5 GAP 2 CLOSED. This accepted a bare mention of "points" anywhere
      // in the sheet as evidence of a drivers section, which the Pool sheet
      // satisfied without having one. §29 asks for a SECTION, so a section is
      // what is required -- named, and carrying the two facts that make it a
      // football section rather than a market one.
      report.check(`${label} — carries a named Fantasy Football drivers section`,
        s.titles.some((t) => /DRIVERS/i.test(t)), JSON.stringify(s.titles));
      report.check(`${label} — which says what on the field decides it`,
        /measured across/i.test(s.text), s.text.slice(0, 120));
      report.check(`${label} — and Pool/market analysis`,
        hasMarket || /pool|entr|pot/i.test(s.text),
        JSON.stringify(s.titles));
      // NO RUNNING ORDER WHILE OPEN, and it says so. A standing computed in
      // the browser would be a second evaluation of a metric the Pool engine
      // evaluates once, at settlement.
      report.check(`${label} — states no running order for an open Pool`,
        /evaluated once, at settlement/i.test(s.text)
        || /winner/i.test(s.text), s.text.slice(0, 160));
    }
  }
});

report.finish();
