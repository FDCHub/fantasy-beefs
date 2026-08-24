/* ============================================================================
 * FantasyStakes — RC4 MOBILE RECONCILIATION · parallel construction, measured
 *
 * Run directly:   FS_TEST_ORIGIN=http://127.0.0.1:8000 \
 *                 node web/tests/uirecon_rc4_parallel_browser.mjs
 * Or through:     python test_uirecon_rc4_parallel.py
 *
 * ── WHY THIS SUITE EXISTS, AND WHAT THE EXISTING ONES COULD NOT SEE ────────
 *
 * The deployed RC4 build passed every certified viewport in five browser suites
 * while a real iPhone showed the Matchup card running under the Prop Pools
 * section. That is not a flaky test; it is a suite asking the wrong question.
 * Rev 1.4 certified Play's carousel to a RULE — "one card is one item is one
 * viewport of the rail" — and every assertion compared the CARD to the ITEM and
 * the ITEM to the RAIL. Both held. What nothing compared was the RAIL to the
 * CARD:
 *
 *     320x568   Matchups zone 133.11px · heading 88.59px · RAIL 44.52px
 *               `.fs-carousel__item` min-height:100%  ->  item 160px
 *               `.fs-wcard--matchup`                  ->  CARD 155px
 *
 * The card was three and a half times its rail. `getBoundingClientRect` on the
 * item reported the full 160px because layout position is not visibility, so a
 * suite measuring agreement between two overflowing boxes agreed with itself.
 *
 * SO EVERY GEOMETRY CLAIM BELOW IS A CONTAINMENT OR AN EQUALITY BETWEEN TWO
 * DIFFERENT THINGS, and the two that matter most are stated as the owner states
 * them:
 *
 *     measured_width (Play Matchup card)  == measured_width (Play Pool card)
 *     measured_height(Play Matchup card)  == measured_height(Play Pool card)
 *
 *     measured_width (Yahoo result) == (FS Matchup result) == (FS Pool result)
 *     measured_height(Yahoo result) == (FS Matchup result) == (FS Pool result)
 *
 * ── AND THE VIEWPORT LIST IS LONGER THAN THE DEVICE LIST ───────────────────
 *
 * `390x844` is an iPhone 12's SCREEN. It is not the box the page is laid out
 * in: with Safari's address bar and toolbar showing, `window.innerHeight` is
 * about 664. The suites certified the screen, the defect lived in the
 * difference, and 44.52px of rail is exactly what a hundred and eighty missing
 * pixels buys. Every device size below is therefore certified TWICE — once at
 * its full screen height and once at a reduced usable height representative of
 * Safari with its chrome visible.
 *
 * ── WHAT IS DELIBERATELY NOT ASSERTED HERE ─────────────────────────────────
 *
 * Nothing about pricing, the board route, escrow, ledger movement or Dynamic
 * Final Lock. The refresh controls appear only as GEOMETRY and as "the surface
 * survives being refreshed" — `uirecon_refresh_ux_browser.mjs` owns their
 * behaviour and `test_uirecon_refresh_ux.py` owns the proof that they move no
 * money. A suite that restated those claims would fail for reasons its own diff
 * could not explain.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

/* THE CERTIFIED SET, AND WHY EACH ROW IS HERE.
 *
 * `usable` rows are the same devices with browser chrome showing — measured
 * `window.innerHeight` on iOS Safari with the address bar and toolbar visible,
 * which is the composition the owner's screenshots were taken in and the one
 * the previous certification never ran. */
const VIEWPORTS = [
  { width: 320, height: 568, label: 'smallest certified phone' },
  { width: 320, height: 454, label: 'smallest phone · Safari chrome visible' },
  { width: 375, height: 667, label: 'standard phone' },
  { width: 375, height: 553, label: 'standard phone · Safari chrome visible' },
  { width: 390, height: 844, label: 'modern phone' },
  { width: 390, height: 664, label: 'modern phone · Safari chrome visible' },
  { width: 768, height: 1024, label: 'tablet portrait' },
  { width: 1024, height: 768, label: 'tablet landscape' },
];

/** The governed minimum for anything a thumb has to hit. */
const TOUCH_FLOOR = 44;

/* SUBPIXEL ONLY. A tolerance wide enough to hide a difference a GM could see is
 * a tolerance that certifies nothing — the defect this suite exists for was
 * 110px of it. Half a CSS pixel is fractional-layout noise and nothing else. */
const SUBPIXEL = 0.5;

const same = (a, b) => Math.abs(a - b) <= SUBPIXEL;

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const GO = (destination) => `
  {
    const tab = document.querySelector(
      '.fs-tabbar__item[data-destination="${destination}"]');
    if (tab) tab.click();
  }
`;

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 15000;
    const poll = () => {
      ${GO('league')}
      const ok = document.querySelector('#panel-league .fs-wcard--matchup');
      if (ok || Date.now() > deadline) return resolve(Boolean(ok));
      setTimeout(poll, 150);
    };
    poll();
  });
`;

/**
 * Enter the seeded showcase demo and land on Play.
 *
 * IT HAS TO BE THE REAL DEMO. The illustrative fixture draws no market board
 * and therefore no refresh control, and its Prop Pools are four frozen objects
 * rather than the governed weekly draw — so a geometry claim measured against it
 * would be a claim about `data/league-data.js`.
 */
const ENTER = async ({ evaluate }) => {
  await evaluate(`return (async () => {
    const res = await fetch('/demo/enter', { method: 'POST', credentials: 'include' });
    return res.status;
  })()`);
  await evaluate(`location.href = '/app/index.html'; 1`);
  await wait(4200);
  return evaluate(READY);
};

/* ── The shared measurement snippets ────────────────────────────────────────
 *
 * `box` is declared once and interpolated, so every rect in this suite is read
 * the same way and rounded the same way. Two decimals: enough to see a real
 * difference, not so many that a fractional layout reports noise as drift. */
const BOX = `
  const box = (el) => {
    if (!el) return null;
    const b = el.getBoundingClientRect();
    return {
      x: +b.left.toFixed(2), y: +b.top.toFixed(2),
      w: +b.width.toFixed(2), h: +b.height.toFixed(2),
      right: +b.right.toFixed(2), bottom: +b.bottom.toFixed(2),
    };
  };
  const clipped = (el) => ({
    scrollH: el.scrollHeight, clientH: el.clientHeight,
    scrollW: el.scrollWidth, clientW: el.clientWidth,
  });
`;

/** Every rail on both tabs, read identically. */
const RAIL = `
  const railOf = (rail) => {
    if (!rail) return null;
    const items = [...rail.querySelectorAll(':scope > .fs-carousel__item, '
      + ':scope > .fs-rescar__item')];
    const cs = getComputedStyle(rail);
    return {
      box: box(rail),
      overflow: clipped(rail),
      snapType: cs.scrollSnapType,
      overflowX: cs.overflowX,
      overflowY: cs.overflowY,
      overscrollX: cs.overscrollBehaviorX,
      itemCount: items.length,
      items: items.map((i) => {
        const is = getComputedStyle(i);
        return {
          box: box(i),
          offsetLeft: i.offsetLeft,
          align: is.scrollSnapAlign,
          stop: is.scrollSnapStop,
        };
      }),
      cards: items.map((i) => i.firstElementChild).filter(Boolean).map((c) => ({
        cls: c.className,
        box: box(c),
        overflow: clipped(c),
      })),
    };
  };
`;

const PLAY = `
  ${GO('league')}
  ${BOX}
  ${RAIL}
  const panel = document.getElementById('panel-league');
  const nav = document.querySelector('.fs-tabbar');
  const scroller = panel.querySelector('.fs-zones');
  const deck = panel.querySelector('.fs-playdeck');
  const bets = panel.querySelector('#fs-bets-carousel');
  const pools = panel.querySelector('#fs-play-pools');
  const headings = [...panel.querySelectorAll('.fs-heading')].map((h) => ({
    text: (h.querySelector('.fs-heading__text') || {}).textContent,
    helper: (h.querySelector('.fs-heading__helper') || {}).textContent || '',
    box: box(h),
  }));
  const targets = [...panel.querySelectorAll('[data-odds-refresh]')].map((b) => ({
    scope: b.dataset.refreshScope,
    target: b.dataset.refreshTarget || '',
    label: b.getAttribute('aria-label'),
    box: box(b),
  }));
  return JSON.stringify({
    panelText: panel.innerText,
    scroller: scroller ? { box: box(scroller), overflow: clipped(scroller) } : null,
    deck: deck ? { box: box(deck), rows: getComputedStyle(deck).gridTemplateRows } : null,
    bets: railOf(bets),
    pools: railOf(pools),
    headings,
    targets,
    nav: box(nav),
    navVisible: Boolean(nav && nav.getBoundingClientRect().height > 0
      && nav.getBoundingClientRect().bottom <= window.innerHeight + 1),
    docOverflow: document.documentElement.scrollWidth
      - document.documentElement.clientWidth,
    panelOverflow: panel.scrollWidth - panel.clientWidth,
    innerHeight: window.innerHeight,
  });
`;

const WRAP = `
  ${GO('week')}
  ${BOX}
  ${RAIL}
  const panel = document.getElementById('panel-week');
  const nav = document.querySelector('.fs-tabbar');
  const deck = panel.querySelector('.fs-wkdeck');
  const mods = [...panel.querySelectorAll('.fs-wkmod')].map((m) => ({
    id: m.dataset.module,
    heading: {
      text: (m.querySelector('.fs-heading__text') || {}).textContent,
      box: box(m.querySelector('.fs-heading')),
    },
    rail: railOf(m.querySelector('.fs-rescar')),
  }));
  return JSON.stringify({
    deck: deck ? { box: box(deck), rows: getComputedStyle(deck).gridTemplateRows } : null,
    mods,
    nav: box(nav),
    navVisible: Boolean(nav && nav.getBoundingClientRect().height > 0
      && nav.getBoundingClientRect().bottom <= window.innerHeight + 1),
    docOverflow: document.documentElement.scrollWidth
      - document.documentElement.clientWidth,
    panelOverflow: panel.scrollWidth - panel.clientWidth,
  });
`;

/** Every card in a rail is inside its rail's box — the containment claim. */
function containment(rail) {
  return rail.cards.every((c) => c.box.y >= rail.box.y - SUBPIXEL
    && c.box.bottom <= rail.box.bottom + SUBPIXEL
    && c.box.x >= rail.box.x - SUBPIXEL - 1
    && c.box.right <= rail.box.right + rail.overflow.scrollW);
}

/** No card's own content spills the shell it is drawn in. */
function unclipped(rail) {
  return rail.cards.every((c) => c.overflow.scrollH <= c.overflow.clientH + 1);
}

/** Every card in one rail measures the same — no variable carousel height. */
function uniform(rail) {
  return rail.cards.every((c) => same(c.box.w, rail.cards[0].box.w)
    && same(c.box.h, rail.cards[0].box.h));
}

await withPage({ port: 9488, origin: process.env.FS_TEST_ORIGIN },
  async ({ evaluate, setViewport }) => {
    await setViewport(390, 844);
    check('the seeded demo mounted with real Play cards',
      await ENTER({ evaluate }) === true);

    for (const vp of VIEWPORTS) {
      await setViewport(vp.width, vp.height);
      const at = `${vp.width}x${vp.height}`;
      const ready = await evaluate(READY);
      check(`the Play tab is drawn — ${at}`, ready === true);
      if (!ready) continue;

      /* ══ PLAY ═══════════════════════════════════════════════════════════ */

      section(`PLAY · parallel construction — ${at} (${vp.label})`);

      const play = JSON.parse(await evaluate(PLAY));

      check(`the deck exists and is a grid of four rows — ${at}`,
        Boolean(play.deck) && play.deck.rows.split(/\s+/).length === 4,
        play.deck ? play.deck.rows : 'no deck');

      check(`MATCHUPS is still the first heading — ${at}`,
        play.headings[0] && play.headings[0].text === 'MATCHUPS',
        play.headings[0] ? play.headings[0].text : 'none');
      check(`PROP POOLS is still the second — ${at}`,
        play.headings[1] && play.headings[1].text === 'PROP POOLS',
        play.headings[1] ? play.headings[1].text : 'none');
      check(`  · and it still says N THIS WEEK · SCROLL — ${at}`,
        /^\d+ THIS WEEK · SCROLL$/.test(
          (play.headings[1] || {}).helper || ''),
        (play.headings[1] || {}).helper);

      /* ── the vertical flow, in order and without overlap ───────────────── */

      const flow = [
        ['MATCHUPS heading', play.headings[0].box],
        ['Matchups rail', play.bets.box],
        ['PROP POOLS heading', play.headings[1].box],
        ['Prop Pools rail', play.pools.box],
      ];
      const ordered = flow.every((entry, i) => i === 0
        || entry[1].y >= flow[i - 1][1].bottom - SUBPIXEL);
      check(`heading → rail → gap → heading → rail, with no overlap — ${at}`,
        ordered, flow.map(([n, b]) => `${n} ${b.y}→${b.bottom}`).join(' | '));

      check(`the Matchups rail never reaches the PROP POOLS heading — ${at}`,
        play.bets.box.bottom <= play.headings[1].box.y + SUBPIXEL,
        `${play.bets.box.bottom} vs ${play.headings[1].box.y}`);

      const gap = +(play.headings[1].box.y - play.bets.box.bottom).toFixed(2);
      check(`  · and the gap between them is a controlled one — ${at}`,
        gap > 0 && gap < 40, `${gap}px`);

      /* ── one complete card, in the box that is supposed to hold it ─────── */

      for (const [name, rail] of [['Matchups', play.bets], ['Prop Pools', play.pools]]) {
        check(`the ${name} rail holds its cards completely — ${at}`,
          containment(rail),
          `rail ${rail.box.y}→${rail.box.bottom}, first card `
          + `${rail.cards[0].box.y}→${rail.cards[0].box.bottom}`);
        check(`  · the ${name} card is the full height of its rail — ${at}`,
          same(rail.cards[0].box.h, rail.box.h),
          `card ${rail.cards[0].box.h} / rail ${rail.box.h}`);
        check(`  · no ${name} card clips its own content — ${at}`,
          unclipped(rail),
          rail.cards.map((c) => `${c.overflow.scrollH}/${c.overflow.clientH}`).join(' '));
        check(`  · every ${name} card measures the same — ${at}`,
          uniform(rail),
          rail.cards.map((c) => `${c.box.w}x${c.box.h}`).join(' '));
        check(`  · the ${name} rail does not scroll vertically at all — ${at}`,
          rail.overflow.scrollH <= rail.overflow.clientH + 1
          && rail.overflowY === 'hidden',
          `${rail.overflow.scrollH}/${rail.overflow.clientH} ${rail.overflowY}`);

        /* ── one card at a time, snapping one card at a time ─────────────── */

        check(`  · one ${name} item is exactly one rail wide — ${at}`,
          rail.items.every((i) => same(i.box.w, rail.overflow.clientW)),
          rail.items.map((i) => i.box.w).join(' '));
        check(`  · the ${name} rail snaps on the horizontal axis — ${at}`,
          /x\s+mandatory/.test(rail.snapType) && rail.overflowX === 'auto',
          `${rail.snapType} / ${rail.overflowX}`);
        check(`  · every ${name} item is a hard snap stop — ${at}`,
          rail.items.every((i) => i.align === 'start' && i.stop === 'always'));
        check(`  · a scroll past the last ${name} card does not chain — ${at}`,
          rail.overscrollX === 'contain', rail.overscrollX);
        if (rail.items.length > 1) {
          check(`  · no partial next ${name} card is exposed at rest — ${at}`,
            rail.items[1].box.x >= rail.box.right - SUBPIXEL,
            `next item at ${rail.items[1].box.x}, rail ends ${rail.box.right}`);
        }
      }

      /* ── THE OWNER ASSERTION ───────────────────────────────────────────── */

      const m = play.bets.cards[0].box;
      const p = play.pools.cards[0].box;
      check(`measured_width(Play Matchup) == measured_width(Play Prop Pool) `
        + `— ${at}`, same(m.w, p.w), `${m.w} vs ${p.w}`);
      check(`measured_height(Play Matchup) == measured_height(Play Prop Pool) `
        + `— ${at}`, same(m.h, p.h), `${m.h} vs ${p.h}`);
      check(`  · and the two rails are one viewport geometry — ${at}`,
        same(play.bets.box.w, play.pools.box.w)
        && same(play.bets.box.h, play.pools.box.h),
        `${play.bets.box.w}x${play.bets.box.h} vs `
        + `${play.pools.box.w}x${play.pools.box.h}`);

      /* ── the tab, the nav and the refresh targets ──────────────────────── */

      check(`Play does not scroll sideways — ${at}`,
        play.docOverflow <= 0 && play.panelOverflow <= 0,
        `doc ${play.docOverflow} / panel ${play.panelOverflow}`);
      check(`the bottom navigation is visible and unobstructed — ${at}`,
        play.navVisible === true);
      check(`  · and nothing on Play is drawn over it — ${at}`,
        play.pools.box.bottom <= play.nav.y + SUBPIXEL
        || play.scroller.box.bottom <= play.nav.y + SUBPIXEL,
        `pools rail ends ${play.pools.box.bottom}, `
        + `scroller ends ${play.scroller.box.bottom}, nav starts ${play.nav.y}`);

      const heading = play.targets.find((t) => t.scope === 'board');
      const perCard = play.targets.filter((t) => t.scope === 'pairing');
      check(`the heading-level refresh is still there — ${at}`,
        Boolean(heading), heading ? heading.label : 'absent');
      check(`a per-card refresh is still on every Matchup card — ${at}`,
        perCard.length === play.bets.cards.length,
        `${perCard.length} controls / ${play.bets.cards.length} cards`);
      check(`  · each names one opponent, so a refresh isolates one card — ${at}`,
        new Set(perCard.map((t) => t.target)).size === perCard.length
        && perCard.every((t) => t.target),
        perCard.map((t) => t.target).join(','));
      check(`every refresh target is at least ${TOUCH_FLOOR}x${TOUCH_FLOOR} — ${at}`,
        play.targets.every((t) => t.box.w >= TOUCH_FLOOR - 1
          && t.box.h >= TOUCH_FLOOR - 1),
        play.targets.map((t) => `${t.box.w}x${t.box.h}`).join(' '));

      /* ── Play is Play, and there is no public Versus ───────────────────── */

      check(`no public-facing "Versus" appears on Play — ${at}`,
        !/versus/i.test(play.panelText || ''));
      check(`the Prop Pool question is the governed one — ${at}`,
        !/Question unavailable/.test(play.panelText || ''));

      /* ══ WRAP UP ════════════════════════════════════════════════════════ */

      section(`WRAP UP · three true peer carousels — ${at} (${vp.label})`);

      await evaluate(WRAP);
      await wait(350);
      const wrap = JSON.parse(await evaluate(WRAP));

      check(`the three modules are one deck of six rows — ${at}`,
        Boolean(wrap.deck) && wrap.deck.rows.split(/\s+/).length === 6,
        wrap.deck ? wrap.deck.rows : 'no deck');

      const TITLES = [
        ['yahoo', 'YAHOO LEAGUE MATCHUPS · SCROLL'],
        ['bets', 'FANTASYSTAKES MATCHUPS · SCROLL'],
        ['pools', 'FANTASYSTAKES PROP POOLS · SCROLL'],
      ];
      check(`three sections, in order, under their locked headings — ${at}`,
        wrap.mods.length === 3
        && wrap.mods.every((mod, i) => mod.id === TITLES[i][0]
          && mod.heading.text === TITLES[i][1]),
        wrap.mods.map((mod) => `${mod.id}:${mod.heading.text}`).join(' | '));

      const rails = wrap.mods.map((mod) => mod.rail).filter(Boolean);
      check(`  · and all three drew a carousel — ${at}`, rails.length === 3);
      if (rails.length !== 3) continue;

      for (let i = 0; i < 3; i += 1) {
        const name = wrap.mods[i].id;
        const rail = rails[i];
        check(`the ${name} rail holds its cards completely — ${at}`,
          containment(rail),
          `rail ${rail.box.y}→${rail.box.bottom}, first card `
          + `${rail.cards[0].box.y}→${rail.cards[0].box.bottom}`);
        check(`  · no ${name} card clips its own content — ${at}`,
          unclipped(rail),
          rail.cards.map((c) => `${c.overflow.scrollH}/${c.overflow.clientH}`).join(' '));
        check(`  · every ${name} card measures the same — ${at}`,
          uniform(rail),
          rail.cards.map((c) => `${c.box.w}x${c.box.h}`).join(' '));
        check(`  · one ${name} item is exactly one rail wide — ${at}`,
          rail.items.every((it) => same(it.box.w, rail.overflow.clientW)));
        check(`  · the ${name} rail snaps one card at a time — ${at}`,
          /x\s+mandatory/.test(rail.snapType)
          && rail.items.every((it) => it.align === 'start' && it.stop === 'always'),
          rail.snapType);
        if (rail.items.length > 1) {
          check(`  · no partial next ${name} card is exposed at rest — ${at}`,
            rail.items[1].box.x >= rail.box.right - SUBPIXEL);
        }
        if (i > 0) {
          check(`  · the ${name} section does not overlap the one above — ${at}`,
            wrap.mods[i].heading.box.y >= rails[i - 1].box.bottom - SUBPIXEL,
            `${wrap.mods[i].heading.box.y} vs ${rails[i - 1].box.bottom}`);
        }
      }

      /* ── THE OWNER ASSERTION ───────────────────────────────────────────── */

      const [y, b, pl] = rails.map((rail) => rail.cards[0].box);
      check(`measured_width(Yahoo) == (FantasyStakes Matchup) == `
        + `(FantasyStakes Prop Pool) — ${at}`,
        same(y.w, b.w) && same(b.w, pl.w), `${y.w} / ${b.w} / ${pl.w}`);
      check(`measured_height(Yahoo) == (FantasyStakes Matchup) == `
        + `(FantasyStakes Prop Pool) — ${at}`,
        same(y.h, b.h) && same(b.h, pl.h), `${y.h} / ${b.h} / ${pl.h}`);
      check(`  · and the three rails are one viewport geometry — ${at}`,
        rails.every((rail) => same(rail.box.w, rails[0].box.w)
          && same(rail.box.h, rails[0].box.h)),
        rails.map((rail) => `${rail.box.w}x${rail.box.h}`).join(' / '));

      /* ── the Prop Pool result card is a CARD ───────────────────────────── */

      check(`every Wrap Up Prop Pool item is the shared card shell — ${at}`,
        rails[2].cards.every((c) => /fs-wcard/.test(c.cls)
          && !/fs-poolrow/.test(c.cls)),
        rails[2].cards.map((c) => c.cls).join(' | '));

      check(`Wrap Up does not scroll sideways — ${at}`,
        wrap.docOverflow <= 0 && wrap.panelOverflow <= 0,
        `doc ${wrap.docOverflow} / panel ${wrap.panelOverflow}`);
      check(`the bottom navigation is visible on Wrap Up — ${at}`,
        wrap.navVisible === true);
    }

    /* ══ THE SIDE RAIL, AND THE REFRESH THAT MUST CHANGE NO GEOMETRY ══════ */

    await setViewport(390, 844);
    await evaluate(READY);

    section('Wrap Up · no status side rail breaks the shared shell');

    await evaluate(WRAP);
    await wait(400);
    const edges = await evaluate(`
      ${GO('week')}
      const panel = document.getElementById('panel-week');
      const out = [];
      for (const mod of panel.querySelectorAll('.fs-wkmod')) {
        for (const card of mod.querySelectorAll('.fs-rescar__item > .fs-wcard')) {
          const cs = getComputedStyle(card);
          out.push({
            mod: mod.dataset.module,
            cls: card.className,
            leftColor: cs.borderLeftColor,
            leftWidth: cs.borderLeftWidth,
            radius: cs.borderTopLeftRadius,
            badge: (card.querySelector('.fs-wcard__badge') || {}).textContent || '',
          });
        }
      }
      return JSON.stringify(out);
    `).then(JSON.parse);

    const fsCards = edges.filter((e) => e.mod !== 'yahoo');
    const neutral = edges.find((e) => e.mod === 'yahoo').leftColor;
    check('every FantasyStakes result card carries the shared neutral edge',
      fsCards.length > 0 && fsCards.every((e) => e.leftColor === neutral),
      fsCards.map((e) => `${e.mod}:${e.leftColor}`).join(' | '));
    check('  · in particular no LIVE green rail survives',
      !fsCards.some((e) => /\b151,\s*196,\s*89\b/.test(e.leftColor)),
      fsCards.map((e) => e.leftColor).join(' '));
    check('  · and the three families share one edge width and one radius',
      new Set(edges.map((e) => e.leftWidth)).size === 1
      && new Set(edges.map((e) => e.radius)).size === 1,
      `${[...new Set(edges.map((e) => e.leftWidth))].join(',')} / `
      + `${[...new Set(edges.map((e) => e.radius))].join(',')}`);
    check('  · the status is still told, in the badge',
      fsCards.every((e) => e.badge.trim().length > 0),
      fsCards.map((e) => e.badge.trim()).join(' | '));

    section('Play · a refresh changes no geometry and loses no place');

    const refreshed = await evaluate(`
      ${GO('league')}
      return (async () => {
        const panel = document.getElementById('panel-league');
        const rail = panel.querySelector('#fs-bets-carousel');
        const measure = () => {
          const card = panel.querySelector('#fs-bets-carousel .fs-wcard');
          const pool = panel.querySelector('#fs-play-pools .fs-pool--card');
          const r = (el) => {
            const bb = el.getBoundingClientRect();
            return { w: +bb.width.toFixed(2), h: +bb.height.toFixed(2) };
          };
          return { card: r(card), pool: r(pool), left: Math.round(rail.scrollLeft) };
        };
        // Move off the first card, so "the place is kept" is a real claim.
        rail.scrollLeft = rail.clientWidth;
        await new Promise((r) => setTimeout(r, 400));
        const before = measure();
        const control = panel.querySelector(
          '.fs-heading__lead [data-odds-refresh]');
        if (!control) return { skipped: true };
        control.click();
        await new Promise((r) => setTimeout(r, 2500));
        return { before, after: measure() };
      })();
    `);

    check('the heading-level refresh is reachable and fires',
      refreshed.skipped !== true);
    if (refreshed.skipped !== true) {
      check('  · the Matchup card is the same size afterwards',
        same(refreshed.before.card.w, refreshed.after.card.w)
        && same(refreshed.before.card.h, refreshed.after.card.h),
        `${refreshed.before.card.w}x${refreshed.before.card.h} → `
        + `${refreshed.after.card.w}x${refreshed.after.card.h}`);
      check('  · the Prop Pool card is the same size afterwards',
        same(refreshed.before.pool.w, refreshed.after.pool.w)
        && same(refreshed.before.pool.h, refreshed.after.pool.h),
        `${refreshed.before.pool.w}x${refreshed.before.pool.h} → `
        + `${refreshed.after.pool.w}x${refreshed.after.pool.h}`);
      check('  · and the card the GM was looking at is still the one on screen',
        refreshed.before.left === refreshed.after.left,
        `${refreshed.before.left} → ${refreshed.after.left}`);
      check('  · the two families still measure identically after a refresh',
        same(refreshed.after.card.w, refreshed.after.pool.w)
        && same(refreshed.after.card.h, refreshed.after.pool.h),
        `${refreshed.after.card.w}x${refreshed.after.card.h} vs `
        + `${refreshed.after.pool.w}x${refreshed.after.pool.h}`);
    }
  });

finish();
