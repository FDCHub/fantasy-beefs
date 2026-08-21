/* ============================================================================
 * FantasyStakes — UIRECON Rev 1.4 · Wrap Up is three carousels of one card
 *
 * Run directly:   node web/tests/uirecon_rev14_wrap_browser.mjs
 * Or through:     python test_uirecon_rev14_wrap.py
 *
 * WHAT THIS SUITE IS ABOUT.
 *
 * Wave 4B turned Wrap Up's three modules into one construction — one section
 * builder, one horizontal snap rail, one item wrapper — and stopped at the item
 * wrapper's edge. Inside it the Prop Pools section still drew the `.fs-poolrow`
 * button it had drawn as a flat list: a smaller corner, a thinner left edge, a
 * tighter inset. So the three rails measured identically and the third one's
 * contents were visibly a different component, which is the "three things a GM
 * reads the same way, built three ways" defect one level further in.
 *
 * A finished wager also carried a gold left border, inherited from the Play and
 * Action rails where it means "this one has stopped moving". On Wrap Up every
 * card has stopped moving, so the mark distinguished nothing and read as a gold
 * rule beside a badge that already said WON.
 *
 * HOW IT ASSERTS, AND WHY NOT WITH NUMBERS.
 *
 * Every geometry claim below is an AGREEMENT between things measured in the
 * same layout — rail against rail, card against card, item against the rail
 * that holds it. Nothing is compared to a pinned pixel value. The stale
 * `max-height` this whole line of work exists to remove was a pinned pixel
 * value that was correct when it was written; a suite that pins one is only
 * ever certifying that nobody has redesigned the card yet.
 *
 * The one-card rule is therefore expressed as three measurements that cannot
 * all hold while a second card is peeking: the item is as wide as the rail's
 * own viewport, the next item begins at or past the rail's right edge, and the
 * rail parks on an item boundary rather than between two.
 *
 * WHAT IT DELIBERATELY DOES NOT DO. It does not read the stylesheet. Every
 * answer here comes from `getComputedStyle` and `getBoundingClientRect` on a
 * card the application actually mounted, so a rule that is present but
 * out-specificity'd fails exactly as loudly as one that was never written.
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

/** The three locked section names, in the order Wrap Up states them. */
const HEADINGS = [
  'YAHOO LEAGUE MATCHUPS · SWIPE',
  'FANTASYSTAKES MATCHUPS · SWIPE',
  'FANTASYSTAKES PROP POOLS · SWIPE',
];

/** Sub-pixel noise is not a difference; anything a GM could see is. */
const near = (a, b, tol = 1) => Math.abs(a - b) <= tol;

/** `--gold`, as the browser reports it once the token has resolved. */
const GOLD = '201,162,74';

/** A computed colour or shadow, with the spaces the browser inserts removed. */
const flat = (value) => String(value).replace(/\s+/g, '');

const carriesGold = (value) => flat(value).includes(GOLD);

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

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
 * Everything one viewport has to answer for, read in a single pass.
 *
 * ONE PASS RATHER THAN ONE PER ASSERTION, because a layout read between two
 * `evaluate` calls is a layout that may have settled differently — and a suite
 * whose assertions disagree about which frame they measured reports drift that
 * is its own.
 */
const READ = `
  const panel = document.getElementById('panel-week');
  if (!panel) return { missing: true };
  const num = (v) => +parseFloat(v || '0').toFixed(2);
  const mods = [...panel.querySelectorAll('.fs-wkmod')].map((s) => {
    const head = s.querySelector('.fs-heading');
    const rail = s.querySelector('.fs-rescar');
    const rs = rail ? getComputedStyle(rail) : null;
    const rb = rail ? rail.getBoundingClientRect() : null;
    const items = rail ? [...rail.querySelectorAll(':scope > .fs-rescar__item')] : [];
    return {
      mod: s.dataset.module,
      heading: head ? head.textContent.trim() : null,
      rail: rail ? {
        left: +rb.left.toFixed(1),
        right: +rb.right.toFixed(1),
        width: +rb.width.toFixed(1),
        clientW: rail.clientWidth,
        scrollW: rail.scrollWidth,
        offsetH: rail.offsetHeight,
        clientH: rail.clientHeight,
        offsetW: rail.offsetWidth,
        radius: rs.borderRadius,
        padL: rs.paddingLeft,
        padR: rs.paddingRight,
        gap: rs.columnGap,
        snap: rs.scrollSnapType,
        overflowX: rs.overflowX,
        overscrollX: rs.overscrollBehaviorX,
        scrollbar: rs.scrollbarWidth,
      } : null,
      items: items.map((i) => ({
        offsetLeft: i.offsetLeft,
        width: +i.getBoundingClientRect().width.toFixed(1),
        align: getComputedStyle(i).scrollSnapAlign,
        stop: getComputedStyle(i).scrollSnapStop,
      })),
      // The card is the item's own child, whatever presentation it drew. A
      // section with nothing to report draws an explanatory paragraph instead,
      // which is not a card and is not compared against one.
      cards: items.map((i) => i.firstElementChild).filter(Boolean)
        .filter((c) => c.classList.contains('fs-wcard')
                    || c.classList.contains('fs-poolrow'))
        .map((c) => {
          const cs = getComputedStyle(c);
          const b = c.getBoundingClientRect();
          return {
            cls: c.className,
            width: +b.width.toFixed(1),
            left: +b.left.toFixed(1),
            height: +b.height.toFixed(1),
            radius: cs.borderRadius,
            edge: num(cs.borderLeftWidth),
            padding: cs.padding,
            borderLeftColor: cs.borderLeftColor,
            boxShadow: cs.boxShadow,
          };
        }),
    };
  });
  const de = document.documentElement;
  return {
    mods,
    docSW: de.scrollWidth, docCW: de.clientWidth,
    bodySW: document.body.scrollWidth, bodyCW: document.body.clientWidth,
    panelSW: panel.scrollWidth, panelCW: panel.clientWidth,
  };
`;

await withPage({ port: 9438 }, async ({ evaluate, setViewport }) => {
  for (const vp of VIEWPORTS) {
    // `setViewport` NAVIGATES — mobile emulation only takes effect on a fresh
    // document — so the application remounts on its default tab and Wrap Up has
    // to be reached again. Measured without this, every rectangle below belongs
    // to a hidden panel and reads zero, and zero agrees with zero.
    await setViewport(vp.width, vp.height);
    await evaluate(READY);
    await evaluate(`
      const tab = document.querySelector('.fs-tabbar__item[data-destination="week"]');
      if (tab) tab.click();
      1;
    `);
    await wait(900);

    const at = (label) => `${vp.width}x${vp.height} — ${label}`;
    const m = await evaluate(READ);

    section(`Rev 1.4 · ${vp.width}x${vp.height} — ${vp.label}`);

    if (m.missing || !m.mods || m.mods.length !== 3) {
      check(at('Wrap Up mounted its three sections'), false,
        m.missing ? 'no week panel' : `${(m.mods || []).length} section(s)`);
      continue;
    }

    /* ── §1 · the locked names ───────────────────────────────────────────── */

    check(at('the three headings are stated verbatim, in order'),
      JSON.stringify(m.mods.map((s) => s.heading)) === JSON.stringify(HEADINGS),
      m.mods.map((s) => s.heading).join(' / '));

    /* ── §2 · one card at a time, and never one and a half ───────────────── */

    for (const s of m.mods) {
      if (!s.rail) {
        check(at(`${s.mod} — the section is a carousel`), false, 'no rail');
        continue;
      }
      check(at(`${s.mod} — the rail snaps on the horizontal axis`),
        /x/.test(s.rail.snap) && /mandatory/.test(s.rail.snap), s.rail.snap);

      if (!s.items.length) continue;

      // ONE CARD IS THE VIEWPORT. Not "about the viewport" — a card 20px
      // narrower than its rail is a card with the next one's corner showing.
      check(at(`${s.mod} — every item is exactly the rail's own width`),
        s.rail.clientW > 0
        && s.items.every((i) => i.width > 0 && near(i.width, s.rail.clientW)),
        `items ${[...new Set(s.items.map((i) => i.width))].join(',')} `
        + `vs rail ${s.rail.clientW}`);

      // THE SNAP IS PER CARD. `start` on every item and `always` on every item
      // is what makes a flick advance exactly one; either one missing turns the
      // rail back into a strip that happens to settle somewhere.
      check(at(`${s.mod} — every card is its own snap position`),
        s.items.every((i) => /start/.test(i.align)),
        [...new Set(s.items.map((i) => i.align))].join(','));
      check(at(`${s.mod} — the rail parks on a card, never between two`),
        s.items.every((i) => i.stop === 'always'),
        [...new Set(s.items.map((i) => i.stop))].join(','));

      // NO SECOND CARD IS PARTLY EXPOSED. With the rail at rest on card n,
      // card n+1 begins at or beyond the rail's right edge — so the distance
      // between two consecutive items is at least a full rail wide. This is
      // the 1.5-card defect stated as a measurement rather than as an eyeball.
      if (s.items.length > 1) {
        const steps = s.items.slice(1).map(
          (i, k) => i.offsetLeft - s.items[k].offsetLeft);
        check(at(`${s.mod} — the next card starts past the rail's edge`),
          steps.every((d) => d >= s.rail.clientW - 1),
          `steps ${steps.join(',')} vs rail ${s.rail.clientW}`);
      }
    }

    /* ── §3 · the three carousel families are one geometry ───────────────── */

    const rails = m.mods.map((s) => s.rail);
    const agree = (pick, label, detail = pick) => {
      const values = rails.map(pick);
      const same = values.every((v) => (typeof v === 'number'
        ? near(v, values[0]) : v === values[0]));
      check(at(label), same, rails.map(detail).join(' / '));
    };

    agree((r) => r.width, 'the three rails are one width');
    agree((r) => r.left, 'the three rails sit on one left inset');
    agree((r) => r.right, 'the three rails sit on one right inset');
    agree((r) => r.radius, 'the three rails carry one outer radius');
    agree((r) => r.gap, 'the three rails carry one gutter between cards');
    agree((r) => r.padL, 'the three rails carry one horizontal padding');
    agree((r) => r.snap, 'the three rails swipe the same way');

    /* ── §4 · every card in every family is one outer shell ──────────────── */

    const cards = m.mods.flatMap((s) => s.cards.map((c) => ({ ...c, mod: s.mod })));
    if (cards.length > 1) {
      const first = cards[0];
      const set = (pick) => [...new Set(cards.map(pick))].join(' | ');
      check(at('every result card is one width'),
        cards.every((c) => near(c.width, first.width)), set((c) => c.width));

      // THE LEAD CARD OF EACH RAIL, not every card of every rail. A rail's
      // second card is a full rail-width away — that is the one-card rule §2
      // measured — so its viewport x is off screen by construction and reading
      // it here would assert the opposite of what §2 just proved. What has to
      // agree is where the three sections BEGIN.
      const leads = m.mods.map((s) => s.cards[0]).filter(Boolean);
      check(at('the three sections begin on one left edge'),
        leads.length === 3 && leads.every((c) => near(c.left, leads[0].left)),
        leads.map((c) => c.left).join(' / '));
      check(at('every result card turns one corner'),
        cards.every((c) => c.radius === first.radius), set((c) => c.radius));
      check(at('every result card carries one left-edge weight'),
        cards.every((c) => near(c.edge, first.edge, 0.5)), set((c) => c.edge));
      check(at('every result card carries one inset'),
        cards.every((c) => c.padding === first.padding), set((c) => c.padding));
    } else {
      check(at('at least two result cards were mounted to compare'), false,
        `${cards.length} card(s)`);
    }

    /* ── §5 · the Prop Pool card IS the Matchup card, on the outside ─────── */

    const bets = m.mods.find((s) => s.mod === 'bets');
    const pools = m.mods.find((s) => s.mod === 'pools');
    if (bets && pools && bets.cards.length && pools.cards.length) {
      const b = bets.cards[0];
      const p = pools.cards[0];
      check(at('a Prop Pool card is as wide as a Matchup card'),
        near(b.width, p.width), `${b.width} vs ${p.width}`);
      check(at('a Prop Pool card turns the Matchup card’s corner'),
        b.radius === p.radius, `${b.radius} vs ${p.radius}`);
      check(at('a Prop Pool card carries the Matchup card’s left edge'),
        near(b.edge, p.edge, 0.5), `${b.edge} vs ${p.edge}`);
      check(at('a Prop Pool card carries the Matchup card’s inset'),
        b.padding === p.padding, `${b.padding} vs ${p.padding}`);
      check(at('a Prop Pool card fills its snap item like a Matchup card'),
        near(p.width, pools.rail.clientW) && near(b.width, bets.rail.clientW),
        `${p.width}/${pools.rail.clientW} vs ${b.width}/${bets.rail.clientW}`);
    } else {
      check(at('both a Matchup card and a Prop Pool card were mounted'), false,
        `bets ${bets ? bets.cards.length : 0} / pools ${pools ? pools.cards.length : 0}`);
    }

    /* ── §6 · the swipe is contained, and nothing leaks sideways ─────────── */

    for (const s of m.mods) {
      if (!s.rail) continue;
      check(at(`${s.mod} — the overflow lives in the rail`),
        s.rail.overflowX === 'auto' || s.rail.overflowX === 'scroll',
        s.rail.overflowX);
      // The gesture stops where the rail does. Without containment a flick past
      // the last card chains outward and the page moves instead.
      check(at(`${s.mod} — the swipe cannot chain out of the carousel`),
        s.rail.overscrollX === 'contain', String(s.rail.overscrollX));
      // A scrollbar that occupies layout takes height from the rail; a rail
      // whose border box and content box agree has no visible bar in it.
      check(at(`${s.mod} — the rail shows no horizontal scrollbar`),
        s.rail.scrollbar === 'none' && s.rail.offsetH === s.rail.clientH,
        `${s.rail.scrollbar}, ${s.rail.offsetH} vs ${s.rail.clientH}`);
    }

    check(at('the document does not scroll sideways'),
      m.docSW <= m.docCW + 1, `${m.docSW} vs ${m.docCW}`);
    check(at('the body does not scroll sideways'),
      m.bodySW <= m.bodyCW + 1, `${m.bodySW} vs ${m.bodyCW}`);
    check(at('the tab does not scroll sideways'),
      m.panelSW <= m.panelCW + 1, `${m.panelSW} vs ${m.panelCW}`);

    /* ── §7 · a flick lands on a card, measured ──────────────────────────── */

    // THE ONLY FUNCTIONAL CHECK IN THE SUITE. Everything above certifies the
    // declarations; this one certifies the behaviour they are supposed to
    // produce. The rail is pushed a fraction of a card and asked where it came
    // to rest: with per-card mandatory snapping it can only be an item
    // boundary, never the fraction it was pushed to.
    const snapped = await evaluate(`
      const rail = document.querySelector('#panel-week [data-module="pools"] .fs-rescar')
        || document.querySelector('#panel-week .fs-rescar');
      if (!rail) return { skip: 'no rail' };
      const items = [...rail.querySelectorAll(':scope > .fs-rescar__item')];
      if (items.length < 2) return { skip: 'one card only — nothing to advance to' };
      const step = items[1].offsetLeft - items[0].offsetLeft;
      rail.scrollLeft = Math.round(step * 0.6);
      return new Promise((done) => setTimeout(() => done({
        rest: rail.scrollLeft, step, stops: items.map((i) => i.offsetLeft - items[0].offsetLeft),
      }), 400));
    `);
    if (snapped.skip) {
      check(at('a rail with a second card was available to flick'), false, snapped.skip);
    } else {
      check(at('a flick comes to rest on a card boundary, not between two'),
        snapped.stops.some((s) => near(s, snapped.rest, 2)),
        `rest ${snapped.rest} of stops ${snapped.stops.join(',')}`);
    }

    /* ── §8 · no gold down the side of a FantasyStakes Matchup result ────── */

    if (bets && bets.cards.length) {
      check(at('no Matchup result card carries a gold left edge'),
        bets.cards.every((c) => !carriesGold(c.borderLeftColor)),
        bets.cards.map((c) => c.borderLeftColor).join(' | '));
      check(at('no Matchup result card carries a gold inset shadow'),
        bets.cards.every((c) => !carriesGold(c.boxShadow)),
        bets.cards.map((c) => c.boxShadow).join(' | '));
    } else {
      check(at('a Matchup result card was mounted to inspect'), false, 'none');
    }

    // THE FIXTURE'S WEEK HAS NO SETTLED WAGER, and the gold edge only ever
    // appeared on one. Asking the mounted cards alone would therefore certify
    // nothing: they were never going to be gold. So the finished state is put
    // ON a real card and the cascade is asked what it paints — the same
    // question a settled wager would ask, answered by the stylesheet the
    // application actually loaded rather than by reading the file.
    const probe = await evaluate(`
      const card = document.querySelector(
        '#panel-week [data-module="bets"] .fs-rescar__item > .fs-wcard');
      if (!card) return { skip: 'no Matchup card mounted' };
      const had = card.classList.contains('is-done');
      card.classList.add('is-done');
      const cs = getComputedStyle(card);
      const out = { edge: cs.borderLeftColor, shadow: cs.boxShadow,
                    width: cs.borderLeftWidth };
      if (!had) card.classList.remove('is-done');

      // THE CONTROL. The same class on a Play card must STILL paint gold, or
      // the assertion above would pass just as well if the token had been
      // deleted product-wide — which is a different change from the one asked
      // for, and a worse one.
      const play = document.querySelector('#panel-league .fs-wcard--matchup');
      if (play) {
        const hadPlay = play.classList.contains('is-done');
        play.classList.add('is-done');
        out.playEdge = getComputedStyle(play).borderLeftColor;
        if (!hadPlay) play.classList.remove('is-done');
      }
      return out;
    `);
    if (probe.skip) {
      check(at('a Matchup card was available to ask'), false, probe.skip);
    } else {
      check(at('a FINISHED Matchup result would still carry no gold edge'),
        !carriesGold(probe.edge), probe.edge);
      check(at('and no gold ornament took its place'),
        !carriesGold(probe.shadow), probe.shadow);
      check(at('the border hierarchy is preserved, not removed'),
        parseFloat(probe.width) > 0, probe.width);
      check(at('the gold lifecycle accent still exists elsewhere'),
        probe.playEdge === undefined || carriesGold(probe.playEdge),
        String(probe.playEdge));
    }
  }
});

finish();
