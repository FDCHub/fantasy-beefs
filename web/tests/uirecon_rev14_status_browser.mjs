/* ============================================================================
 * FantasyStakes — UIRECON Rev 1.4 · the Status tab's four lifecycle carousels
 *
 * Run directly:   node web/tests/uirecon_rev14_status_browser.mjs
 * Or through:     python test_uirecon_rev14_status.py
 *
 * WHAT REV 1.4 CHANGED, AND WHAT IT DELIBERATELY DID NOT.
 *
 * Status has always had four rails and Wave 5 finally gave all four of them
 * real records to carry. What it could not give them was ROOM. Each rail item
 * was a fixed 216px, so a 390px phone showed one card and half of the next, and
 * the four sections stacked to 929px of content inside a 534px viewport — a GM
 * meeting Status for the first time saw ACTION REQUIRED and WAITING and had to
 * discover that LIVE and COMPLETED existed at all.
 *
 * The half card is the defect, not the scrolling. It reads as a rendering fault
 * rather than as an invitation to swipe, and it spends a third of the rail on a
 * card nobody can read. Rev 1.4 makes every item exactly one rail wide, which
 * is the same mechanism Wrap Up's result carousels use: one card fills the
 * viewport BY CONSTRUCTION, at any card height and any viewport width, so there
 * is no pixel constant here to go stale and no arrangement in which a second
 * card is partly visible.
 *
 * ── WHAT THESE ASSERTIONS ARE, AND ARE NOT ──────────────────────────────────
 *
 * NOT "the carousel is 366px wide". That is the number this build happens to
 * produce at one viewport, and pinning it would re-create the stale constant
 * the change removes. §4 asserts the RULE instead — an item is its rail's
 * client width, so the snap step is one card and a second card cannot be
 * exposed — and re-asserts it at all five certified sizes.
 *
 * NOT "the heading says ACTION REQUIRED: 1". The counts belong to whatever
 * league is bound. §3 reads `/league/{id}/action/me` in the same session and
 * requires the four headings, the four `data-rail-count` attributes, the
 * rendered card counts and the server's own tally to be four descriptions of
 * one set of wagers. A fixture number would pass with the server disconnected.
 *
 * NOT "the tab is short enough". §6 states a design target in words — all four
 * sections simultaneously present inside the Status tab's own scroll viewport
 * at 390x844, above the persistent bottom navigation — and measures the two
 * things that make it true: the sections do not overflow the viewport they sit
 * in, and the last one ends above the navigation bar.
 *
 * §10 IS THE ONE THAT COULD NOT BE DRIVEN FROM THE DEMO. The canonical showcase
 * deliberately fills all four rails, so an empty rail is unreachable by
 * clicking. It is reached by binding an EMPTY authoritative read through the
 * application's own `bindAction` and re-rendering through its own
 * `buildActionPanel` — the real code answering a real shape — and it runs last,
 * because binding a different read is a change to the live surface.
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

/** The viewport the vertical-fit design target is stated against. */
const FIT_TARGET = { width: 390, height: 844 };

/** The governed minimum for anything a thumb has to hit. */
const TOUCH_FLOOR = 44;

/** Sub-pixel noise is not a difference; anything a GM could see is. */
const near = (a, b, tol = 1) => Math.abs(a - b) <= tol;

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 12000;
    const poll = () => {
      const ok = document.querySelector('#panel-action .fs-strip__cell');
      if (ok || Date.now() > deadline) return resolve(Boolean(ok));
      setTimeout(poll, 120);
    };
    poll();
  });
`;

/**
 * Enter the demo, mount the app, and land on Status.
 *
 * Returns the demo league's own id, because §3 has to ask the server what it
 * served and cannot be told the answer by this file.
 */
const ENTER = async ({ evaluate }) => {
  const entered = await evaluate(`return (async () => {
    const res = await fetch('/demo/enter', { method: 'POST', credentials: 'include' });
    return res.json();
  })()`);
  await evaluate(`location.href = '/app/index.html'; 1`);
  await wait(4200);
  await evaluate(READY);
  await evaluate(`
    const tab = document.querySelector('.fs-tabbar__item[data-destination="action"]');
    if (tab) tab.click();
    1;
  `);
  await wait(1600);
  return entered && entered.league_id;
};

/**
 * Everything the geometry assertions read, in one pass.
 *
 * A CARD IS "FULLY VISIBLE" WHEN ITS WHOLE BOX IS INSIDE THE RAIL'S BOX. That
 * is the reader's definition, not a proxy for it: a card whose right edge is
 * one pixel past the rail is the half-card defect in miniature, and a count of
 * cards satisfying it is the only honest way to say "one at a time".
 */
const READ_STATUS = `
  const panel = document.getElementById('panel-action');
  const rails = panel.querySelector('.fs-rails');
  const bar = document.getElementById('fs-tabbar');
  const barRect = bar ? bar.getBoundingClientRect() : null;
  const zones = [...panel.querySelectorAll('.fs-railsec')];
  const last = zones[zones.length - 1];
  return {
    docSW: document.documentElement.scrollWidth,
    docCW: document.documentElement.clientWidth,
    panelSW: panel.scrollWidth,
    panelCW: panel.clientWidth,
    railsSH: rails ? rails.scrollHeight : null,
    railsCH: rails ? rails.clientHeight : null,
    railsIsScroller: rails
      ? /auto|scroll/.test(getComputedStyle(rails).overflowY) : null,
    lastBottom: last ? +last.getBoundingClientRect().bottom.toFixed(1) : null,
    // The four sections' own stacked height, measured rather than inferred
    // from scrollHeight, which never reports less than the viewport it is
    // measured in and so cannot say how much room is left over.
    contentH: zones.length
      ? +(zones[zones.length - 1].getBoundingClientRect().bottom
          - zones[0].getBoundingClientRect().top).toFixed(1)
      : null,
    navTop: barRect ? +barRect.top.toFixed(1) : null,
    nav: barRect ? {
      height: Math.round(barRect.height),
      onScreen: barRect.bottom <= window.innerHeight + 1 && barRect.height > 0,
      reachable: [...document.querySelectorAll('.fs-tabbar__item')].every((el) => {
        const r = el.getBoundingClientRect();
        const hit = document.elementFromPoint(
          Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2));
        return hit && bar.contains(hit);
      }),
    } : null,
    zones: zones.map((zone) => {
      const head = zone.querySelector('.fs-heading__text');
      const rail = zone.querySelector('.fs-rail');
      const rs = rail ? getComputedStyle(rail) : null;
      const rb = rail ? rail.getBoundingClientRect() : null;
      const items = rail ? [...rail.querySelectorAll(':scope > .fs-rail__item')] : [];
      const note = zone.querySelector('.fs-rail__note');
      return {
        rail: zone.dataset.rail,
        heading: head ? head.textContent.trim() : null,
        declaredCount: Number(zone.dataset.railCount),
        n: items.length,
        cards: items.filter((i) => i.querySelector('.fs-wcard')).length,
        note: note ? note.textContent.trim() : null,
        noteWidth: note ? +note.getBoundingClientRect().width.toFixed(1) : null,
        railCW: rail ? rail.clientWidth : null,
        railSW: rail ? rail.scrollWidth : null,
        railW: rb ? +rb.width.toFixed(1) : null,
        railL: rb ? +rb.left.toFixed(1) : null,
        railH: rb ? +rb.height.toFixed(1) : null,
        overflowX: rs ? rs.overflowX : null,
        snapType: rs ? rs.scrollSnapType : null,
        railVOverflow: rail ? rail.scrollHeight - rail.clientHeight : null,
        // The scrollbar's own thickness. A rail that shows one is a rail whose
        // horizontal scroll is visible furniture rather than a swipe.
        scrollbar: rail ? rail.offsetHeight - rail.clientHeight : null,
        itemW: [...new Set(items.map(
          (i) => +i.getBoundingClientRect().width.toFixed(1)))],
        snapAlign: [...new Set(items.map(
          (i) => getComputedStyle(i).scrollSnapAlign))],
        snapStop: [...new Set(items.map(
          (i) => getComputedStyle(i).scrollSnapStop))],
        fullyVisible: rb ? items.filter((i) => {
          const b = i.getBoundingClientRect();
          return b.left >= rb.left - 1 && b.right <= rb.right + 1;
        }).length : null,
        partlyVisible: rb ? items.filter((i) => {
          const b = i.getBoundingClientRect();
          const inside = Math.min(b.right, rb.right) - Math.max(b.left, rb.left);
          return inside > 1 && inside < b.width - 1;
        }).length : null,
        cardW: [...new Set(items.map((i) => {
          const c = i.querySelector('.fs-wcard');
          return c ? +c.getBoundingClientRect().width.toFixed(1) : null;
        }))],
        cardH: [...new Set(items.map((i) => {
          const c = i.querySelector('.fs-wcard');
          return c ? +c.getBoundingClientRect().height.toFixed(1) : null;
        }))],
        // Content preservation, per card: the sentence, the figures and the
        // foot all still on the card after the density pass.
        content: items.map((i) => {
          const c = i.querySelector('.fs-wcard');
          if (!c) return null;
          const text = (sel) => {
            const el = c.querySelector(sel);
            return el ? el.textContent.trim() : '';
          };
          return {
            identity: text('.fs-wcard__identity'),
            badge: text('.fs-wcard__badge'),
            context: text('.fs-wcard__context'),
            copy: text('.fs-wcard__copy'),
            figures: [...c.querySelectorAll('.fs-wcard__figure')].map((f) => ({
              label: f.querySelector('.fs-wcard__figlabel').textContent.trim(),
              value: f.querySelector('.fs-wcard__figvalue').textContent.trim(),
              cents: f.querySelector('.fs-wcard__figvalue').dataset.exactCents,
            })),
            foot: text('.fs-wcard__foot'),
            tappable: c.classList.contains('is-tappable'),
            tapHeight: Math.round(c.getBoundingClientRect().height),
            // Nothing inside the card may be cut off by the density pass —
            // descendants included, which is where a squeezed figure column
            // would show up first.
            clipped: c.scrollHeight > c.clientHeight + 1
              || c.scrollWidth > c.clientWidth + 1
              || [...c.querySelectorAll('*')].some((n) => (
                getComputedStyle(n).overflow === 'visible'
                && (n.scrollWidth > n.clientWidth + 1
                    || n.scrollHeight > n.clientHeight + 1))),
          };
        }),
      };
    }),
  };
`;

const RAILS = ['action', 'waiting', 'live', 'completed'];
const WORDS = {
  action: 'ACTION REQUIRED', waiting: 'WAITING', live: 'LIVE',
  completed: 'COMPLETED',
};

await withPage({ port: 9436, origin: process.env.FS_TEST_ORIGIN },
  async ({ evaluate, setViewport }) => {
    await setViewport(FIT_TARGET.width, FIT_TARGET.height);
    const leagueId = await ENTER({ evaluate });

    let m = await evaluate(READ_STATUS);

    /* ══════════════════════════════════════════════════════════════════════
     * §2 · THE FOUR CAROUSELS, AND THE ONE HEADING GRAMMAR
     * ════════════════════════════════════════════════════════════════════ */

    section('§2 · Status carries four carousels under one heading grammar');

    check('Status draws exactly four lifecycle sections', m.zones.length === 4,
      `${m.zones.length}`);
    check('they are the locked rails, in the locked order',
      m.zones.map((z) => z.rail).join(',') === RAILS.join(','),
      m.zones.map((z) => z.rail).join(','));
    check('every heading reads exactly `LABEL: N`',
      m.zones.every((z) => new RegExp(`^${WORDS[z.rail]}: \\d+$`).test(z.heading)),
      m.zones.map((z) => z.heading).join(' | '));
    check('no heading carries anything but the label and the count',
      m.zones.every((z) => !/·|SEASON|–/.test(z.heading)),
      m.zones.map((z) => z.heading).join(' | '));

    /* ══════════════════════════════════════════════════════════════════════
     * §3 · THE COUNT IS THE SERVER'S, NOT THIS FILE'S
     * ════════════════════════════════════════════════════════════════════ */

    section('§3 · every count is the authoritative served record count');

    const served = await evaluate(`return (async () => {
      const res = await fetch('/league/${leagueId}/action/me',
                              { credentials: 'include' });
      if (!res.ok) return { status: res.status };
      const body = await res.json();
      return {
        status: res.status,
        counts: body.counts,
        lengths: Object.fromEntries(Object.entries(body.sections)
          .map(([k, v]) => [k, v.length])),
      };
    })()`);

    check('the Action read model answered this session',
      served.status === 200 && Boolean(served.counts), `HTTP ${served.status}`);
    check('the server counts what the server served',
      RAILS.every((r) => served.counts[r] === served.lengths[r]),
      RAILS.map((r) => `${r} ${served.counts[r]}/${served.lengths[r]}`).join(' '));
    check('every heading states the served count',
      m.zones.every((z) => z.heading === `${WORDS[z.rail]}: ${served.counts[z.rail]}`),
      m.zones.map((z) => z.heading).join(' | '));
    check('every section declares the same count to the DOM',
      m.zones.every((z) => z.declaredCount === served.counts[z.rail]),
      m.zones.map((z) => `${z.rail}=${z.declaredCount}`).join(' '));
    check('every carousel holds exactly that many cards',
      m.zones.every((z) => z.cards === served.counts[z.rail]),
      m.zones.map((z) => `${z.rail}=${z.cards}`).join(' '));
    check('the four counts are not all the same number',
      new Set(RAILS.map((r) => served.counts[r])).size > 1,
      RAILS.map((r) => `${r}=${served.counts[r]}`).join(' '));

    /* ══════════════════════════════════════════════════════════════════════
     * §4 · ONE CARD AT A TIME — the geometry, stated as a rule
     * ════════════════════════════════════════════════════════════════════ */

    section('§4 · one card fills the rail; a second is never partly shown');

    check('every rail is its own horizontal scroll container',
      m.zones.every((z) => /auto|scroll/.test(String(z.overflowX))),
      m.zones.map((z) => z.overflowX).join(' '));
    check('every rail snaps mandatorily along x',
      m.zones.every((z) => /^x /.test(String(z.snapType))
        && /mandatory/.test(String(z.snapType))),
      m.zones.map((z) => z.snapType).join(' | '));
    check('every card is exactly one rail wide',
      m.zones.every((z) => z.itemW.length === 1 && near(z.itemW[0], z.railCW)),
      m.zones.map((z) => `${z.itemW.join('/')} in ${z.railCW}`).join(' · '));
    check('so exactly one card is fully visible on every rail',
      m.zones.every((z) => z.fullyVisible === 1),
      m.zones.map((z) => `${z.rail}=${z.fullyVisible}`).join(' '));
    check('and no card is ever partly exposed beside it',
      m.zones.every((z) => z.partlyVisible === 0),
      m.zones.map((z) => `${z.rail}=${z.partlyVisible}`).join(' '));
    check('every card snaps to the rail start and stops there',
      m.zones.every((z) => z.snapAlign.every((a) => a === 'start')
        && z.snapStop.every((s) => s === 'always')),
      m.zones.map((z) => `${z.snapAlign}/${z.snapStop}`).join(' '));
    check('no rail shows a horizontal scrollbar',
      m.zones.every((z) => z.scrollbar === 0),
      m.zones.map((z) => z.scrollbar).join(','));
    check('no rail scrolls vertically inside itself',
      m.zones.every((z) => z.railVOverflow <= 1),
      m.zones.map((z) => z.railVOverflow).join(','));

    // THE SNAP IS DRIVEN, NOT INFERRED. Everything above describes the
    // declarations that should produce per-card snapping; this makes the
    // browser prove it, by scrolling a fraction of a card and asking where it
    // came to rest. A rail that free-scrolled would rest where it was put.
    const snapped = await evaluate(`
      const zone = document.querySelector(
        '#panel-action .fs-railsec[data-rail="completed"]');
      const rail = zone.querySelector('.fs-rail');
      const items = [...rail.querySelectorAll(':scope > .fs-rail__item')];
      if (items.length < 2) return { skipped: true };
      const step = Math.round(items[1].getBoundingClientRect().left
                              - items[0].getBoundingClientRect().left);
      return new Promise((resolve) => {
        rail.scrollLeft = Math.round(step * 0.4);
        setTimeout(() => {
          const back = rail.scrollLeft;
          rail.scrollLeft = Math.round(step * 0.9);
          setTimeout(() => {
            const forward = rail.scrollLeft;
            rail.scrollLeft = 0;
            resolve({ step, back, forward, cardW: rail.clientWidth });
          }, 400);
        }, 400);
      });
    `);
    check('a short drag falls back onto the card it started on',
      snapped.skipped || snapped.back === 0, JSON.stringify(snapped));
    check('a long drag lands on the next card and not between them',
      snapped.skipped || snapped.forward === snapped.step, JSON.stringify(snapped));
    check('the snap step is one whole card, not a fraction of one',
      snapped.skipped || snapped.step >= snapped.cardW,
      `${snapped.step} vs card ${snapped.cardW}`);

    /* ══════════════════════════════════════════════════════════════════════
     * §5 · THE SCROLL IS THE RAIL'S AND STAYS THERE
     * ════════════════════════════════════════════════════════════════════ */

    section('§5 · the horizontal scroll never reaches the tab or the document');

    check('the document does not scroll sideways',
      m.docSW <= m.docCW + 1, `${m.docSW} vs ${m.docCW}`);
    check('the tab does not scroll sideways',
      m.panelSW <= m.panelCW + 1, `${m.panelSW} vs ${m.panelCW}`);
    check('a rail with several cards genuinely has somewhere to scroll',
      m.zones.some((z) => z.railSW > z.railCW + 1),
      m.zones.map((z) => `${z.railSW}/${z.railCW}`).join(' '));
    check('every rail shares one width and one left edge',
      m.zones.every((z) => near(z.railW, m.zones[0].railW)
        && near(z.railL, m.zones[0].railL)),
      m.zones.map((z) => `${z.railW}@${z.railL}`).join(' '));

    /* ══════════════════════════════════════════════════════════════════════
     * §6 · THE VERTICAL DESIGN TARGET
     * ════════════════════════════════════════════════════════════════════ */

    section(`§6 · the design target — all four sections are simultaneously `
      + `present inside the Status tab's own scroll viewport at `
      + `${FIT_TARGET.width}x${FIT_TARGET.height}, above the bottom navigation`);

    check('the Status tab is the thing that scrolls, if anything does',
      m.railsIsScroller === true, String(m.railsIsScroller));
    check('the four sections do not overflow that viewport',
      m.railsSH <= m.railsCH + 1,
      `four sections stack to ${m.contentH}px in a ${m.railsCH}px viewport`);
    check('the last section ends above the bottom navigation',
      m.lastBottom !== null && m.navTop !== null && m.lastBottom <= m.navTop,
      `COMPLETED ends at ${m.lastBottom}px, the bar starts at ${m.navTop}px`);
    check('the bottom navigation is visible and hit-testable',
      Boolean(m.nav && m.nav.onScreen && m.nav.reachable), JSON.stringify(m.nav));
    check('every card is the same height, so no section is taller than another',
      new Set(m.zones.flatMap((z) => z.cardH)).size === 1,
      [...new Set(m.zones.flatMap((z) => z.cardH))].join(','));

    /* ══════════════════════════════════════════════════════════════════════
     * §7 · DENSITY COST NOTHING A GM WAS READING
     * ════════════════════════════════════════════════════════════════════ */

    section('§7 · every card still carries everything it carried before');

    const everyCard = m.zones.flatMap((z) => z.content).filter(Boolean);

    check('every card names its opponent',
      everyCard.every((c) => /^vs \S/.test(c.identity)),
      everyCard.map((c) => c.identity).join(' | ').slice(0, 120));
    check('every card states its market, terms and week',
      everyCard.every((c) => /FIXED|FLOATING/.test(c.context)
        && /WK \d+/.test(c.context)),
      [...new Set(everyCard.map((c) => c.context))].join(' | ').slice(0, 160));
    check('every card still says in words what it is doing',
      everyCard.every((c) => c.copy.length > 0 && /\.$/.test(c.copy)),
      [...new Set(everyCard.map((c) => c.copy))].join(' | ').slice(0, 200));
    check('every card shows both stakes and the pot',
      everyCard.every((c) => c.figures.some((f) => /you/i.test(f.label))
        && c.figures.some((f) => /them/i.test(f.label))
        && c.figures.some((f) => /pot/i.test(f.label))),
      everyCard.map((c) => c.figures.length).join(','));
    check('every money figure still carries the served exact cents',
      everyCard.every((c) => c.figures.every(
        (f) => f.cents !== undefined && f.cents !== '')),
      'exact cents present on all');
    check('every card still carries its foot',
      everyCard.every((c) => c.foot.length > 0),
      [...new Set(everyCard.map((c) => c.foot))].join(' | ').slice(0, 160));
    check('nothing on any card is clipped by the density pass',
      everyCard.every((c) => !c.clipped),
      `${everyCard.filter((c) => c.clipped).length} of ${everyCard.length} clipped`);

    // THE FOUR RAILS STILL ANSWER FOUR DIFFERENT QUESTIONS.
    const copyByRail = Object.fromEntries(
      m.zones.map((z) => [z.rail, (z.content[0] || {}).copy || '']));
    check('ACTION REQUIRED says what is being asked of this GM',
      /sent you a .* Matchup\.$/.test(copyByRail.action), copyByRail.action);
    check('WAITING says who is being waited on',
      /^Waiting for .* to respond\.$/.test(copyByRail.waiting), copyByRail.waiting);
    check('LIVE says the Matchup is live',
      /live/i.test(copyByRail.live), copyByRail.live);
    check('COMPLETED says where the Credits went',
      /^Final\./.test(copyByRail.completed), copyByRail.completed);

    /* ══════════════════════════════════════════════════════════════════════
     * §8 · ACTION REQUIRED IS STILL ACTIONABLE
     * ════════════════════════════════════════════════════════════════════ */

    section('§8 · the ACTION REQUIRED card and its controls remain usable');

    const actionZone = m.zones[0];
    check('the ACTION REQUIRED card is itself the control',
      actionZone.content.every((c) => c.tappable), 'is-tappable');
    check('and it clears the governed touch floor',
      actionZone.content.every((c) => c.tapHeight >= TOUCH_FLOOR),
      `${actionZone.content.map((c) => c.tapHeight).join(',')}px`);

    const controls = await evaluate(`
      const zone = document.querySelector(
        '#panel-action .fs-railsec[data-rail="action"]');
      const card = zone.querySelector('.fs-wcard');
      const cardRect = card.getBoundingClientRect();
      const hitCard = document.elementFromPoint(
        Math.round(cardRect.left + cardRect.width / 2),
        Math.round(cardRect.top + cardRect.height / 2));
      card.click();
      return new Promise((resolve) => setTimeout(() => {
        const sheet = document.getElementById('fs-sheet');
        const buttons = sheet ? [...sheet.querySelectorAll('[data-respond]')] : [];
        resolve({
          cardHitTestable: Boolean(hitCard) && card.contains(hitCard),
          opened: Boolean(sheet),
          controls: buttons.map((b) => b.dataset.respond),
          words: buttons.map((b) => b.textContent.trim()),
          challengeIds: [...new Set(buttons.map((b) => b.dataset.challengeId))],
          minHeight: buttons.length ? Math.min(...buttons.map(
            (b) => Math.round(b.getBoundingClientRect().height))) : null,
          minWidth: buttons.length ? Math.min(...buttons.map(
            (b) => Math.round(b.getBoundingClientRect().width))) : null,
          hitTestable: buttons.every((b) => {
            const r = b.getBoundingClientRect();
            const hit = document.elementFromPoint(
              Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2));
            return Boolean(hit) && (hit === b || b.contains(hit));
          }),
          clipped: buttons.some((b) => b.scrollWidth > b.clientWidth + 1
            || b.scrollHeight > b.clientHeight + 1),
        });
      }, 800));
    `);

    check('the card in the carousel is hit-testable where a thumb lands',
      controls.cardHitTestable === true, String(controls.cardHitTestable));
    check('opening it still offers the three governed responses',
      ['accept', 'counter', 'decline'].every(
        (c) => controls.controls.includes(c)),
      controls.controls.join(','));
    check('each control still names the challenge it would act on',
      controls.challengeIds.length === 1 && /^\d+$/.test(controls.challengeIds[0]),
      controls.challengeIds.join(','));
    check('every control clears the governed touch floor',
      controls.minHeight !== null && controls.minHeight >= TOUCH_FLOOR,
      `${controls.minHeight}px tall, ${controls.minWidth}px wide`);
    check('every control is hit-testable at its own centre',
      controls.hitTestable === true, String(controls.hitTestable));
    check('no control clips its own word',
      controls.clipped === false, controls.words.join(' · '));

    await evaluate(`
      const close = document.querySelector('#fs-sheet [data-fs-close]');
      if (close) close.click();
      1;
    `);
    await wait(600);

    /* ══════════════════════════════════════════════════════════════════════
     * §9 · EVERY CERTIFIED VIEWPORT
     * ════════════════════════════════════════════════════════════════════ */

    for (const vp of VIEWPORTS) {
      section(`§9 · ${vp.width}x${vp.height} — ${vp.label}`);
      await setViewport(vp.width, vp.height);
      await ENTER({ evaluate });
      m = await evaluate(READ_STATUS);

      check('Status is actually laid out at this size',
        m.zones.length === 4 && m.zones.every((z) => z.railW > 0),
        m.zones.map((z) => z.railW).join(' / '));
      check('every heading still reads `LABEL: N`',
        m.zones.every((z) => new RegExp(`^${WORDS[z.rail]}: \\d+$`).test(z.heading)),
        m.zones.map((z) => z.heading).join(' | '));
      check('the document does not scroll sideways',
        m.docSW <= m.docCW + 1, `${m.docSW} vs ${m.docCW}`);
      check('the tab does not scroll sideways',
        m.panelSW <= m.panelCW + 1, `${m.panelSW} vs ${m.panelCW}`);
      check('every rail is still the scroll container',
        m.zones.every((z) => /auto|scroll/.test(String(z.overflowX))
          && z.railVOverflow <= 1),
        m.zones.map((z) => `${z.overflowX}:${z.railVOverflow}`).join(' '));
      check('every card is still exactly one rail wide',
        m.zones.every((z) => z.itemW.length === 1 && near(z.itemW[0], z.railCW)),
        m.zones.map((z) => `${z.itemW.join('/')} in ${z.railCW}`).join(' · '));
      check('exactly one card is fully visible per rail',
        m.zones.every((z) => z.fullyVisible === 1),
        m.zones.map((z) => z.fullyVisible).join(','));
      check('no second card is partly exposed',
        m.zones.every((z) => z.partlyVisible === 0),
        m.zones.map((z) => z.partlyVisible).join(','));
      check('no rail shows a horizontal scrollbar',
        m.zones.every((z) => z.scrollbar === 0),
        m.zones.map((z) => z.scrollbar).join(','));
      check('the bottom navigation stays visible and hit-testable',
        Boolean(m.nav && m.nav.onScreen && m.nav.reachable),
        JSON.stringify(m.nav));

      const cards = m.zones.flatMap((z) => z.content).filter(Boolean);
      check('no card clips its own content at this size',
        cards.every((c) => !c.clipped),
        `${cards.filter((c) => c.clipped).length} clipped of ${cards.length}`);
      check('every ACTION REQUIRED card clears the touch floor at this size',
        m.zones[0].content.every((c) => c.tapHeight >= TOUCH_FLOOR),
        `${m.zones[0].content.map((c) => c.tapHeight).join(',')}px`);

      if (vp.width === FIT_TARGET.width && vp.height === FIT_TARGET.height) {
        check('THE DESIGN TARGET — all four sections fit the Status viewport',
          m.railsSH <= m.railsCH + 1,
          `four sections stack to ${m.contentH}px in a ${m.railsCH}px viewport`);
        check('  · and the last of them ends above the bottom navigation',
          m.lastBottom <= m.navTop,
          `COMPLETED ends at ${m.lastBottom}px, the bar starts at ${m.navTop}px `
          + `— ${(m.navTop - m.lastBottom).toFixed(1)}px clear`);
      }
    }

    /* ══════════════════════════════════════════════════════════════════════
     * §10 · THE EMPTY CAROUSEL
     * ════════════════════════════════════════════════════════════════════ */

    section('§10 · a rail the server served nothing for says so and draws no card');

    await setViewport(FIT_TARGET.width, FIT_TARGET.height);
    await ENTER({ evaluate });

    // THE REAL CODE, ANSWERING A REAL SHAPE. `bindAction` is the function the
    // shell calls with the body of `/league/{id}/action/me`, and
    // `buildActionPanel` is the function that draws Status from it. Nothing is
    // stubbed and no markup is written by this suite — an empty read is simply
    // an ActionStateOut whose sections are empty, which is what a GM with no
    // wagers is served. It is unreachable by clicking, because the canonical
    // showcase deliberately fills all four rails.
    const empty = await evaluate(`return (async () => {
      const model = await import('/app/js/action-model.js');
      const view = await import('/app/js/action.js');
      const RAILS = ['action', 'waiting', 'live', 'completed'];
      const panel = document.getElementById('panel-action');

      const read = (bodySections, bodyCounts) => {
        model.bindAction({ sections: bodySections, counts: bodyCounts });
        panel.innerHTML = view.buildActionPanel();
        return [...panel.querySelectorAll('.fs-railsec')].map((zone) => {
          const note = zone.querySelector('.fs-rail__note');
          const rail = zone.querySelector('.fs-rail');
          return {
            rail: zone.dataset.rail,
            heading: zone.querySelector('.fs-heading__text').textContent.trim(),
            declared: Number(zone.dataset.railCount),
            cards: zone.querySelectorAll('.fs-wcard').length,
            note: note ? note.textContent.trim() : null,
            noteW: note ? Math.round(note.getBoundingClientRect().width) : null,
            railCW: rail ? rail.clientWidth : null,
            role: rail ? rail.getAttribute('role') : null,
          };
        });
      };

      const none = Object.fromEntries(RAILS.map((r) => [r, []]));
      const zeros = Object.fromEntries(RAILS.map((r) => [r, 0]));
      const allEmpty = read(none, zeros);

      // AND ONE EMPTY RAIL AMONG POPULATED ONES, which is a different sentence
      // in the product ("Nothing needs your decision." rather than "No wagers
      // yet this season.") and the case a real GM meets far more often.
      const live = await (await fetch('/league/${leagueId}/action/me',
                                      { credentials: 'include' })).json();
      const mixed = read({ ...live.sections, action: [] },
                         { ...live.counts, action: 0 });
      return { allEmpty, mixed, servedCounts: live.counts };
    })()`);

    check('an all-empty read still draws four sections',
      empty.allEmpty.length === 4, `${empty.allEmpty.length}`);
    check('every heading reads `LABEL: 0`',
      empty.allEmpty.every((z) => z.heading === `${WORDS[z.rail]}: 0`),
      empty.allEmpty.map((z) => z.heading).join(' | '));
    check('and no card is fabricated to fill any of them',
      empty.allEmpty.every((z) => z.cards === 0),
      empty.allEmpty.map((z) => z.cards).join(','));
    check('each empty carousel says one true sentence instead',
      empty.allEmpty.every((z) => z.note === 'No wagers yet this season.'),
      [...new Set(empty.allEmpty.map((z) => z.note))].join(' | '));
    check('the empty state fills the carousel page rather than shrinking to fit',
      empty.allEmpty.every((z) => near(z.noteW, z.railCW, 2)),
      empty.allEmpty.map((z) => `${z.noteW}/${z.railCW}`).join(' '));
    check('an empty carousel is not announced as a list of nothing',
      empty.allEmpty.every((z) => z.role === null),
      empty.allEmpty.map((z) => String(z.role)).join(','));

    const mixedAction = empty.mixed.find((z) => z.rail === 'action');
    check('one empty rail among populated ones reads `ACTION REQUIRED: 0`',
      mixedAction.heading === 'ACTION REQUIRED: 0', mixedAction.heading);
    check('  · draws no card',
      mixedAction.cards === 0, `${mixedAction.cards}`);
    check('  · and says the thing that is true of THAT rail',
      mixedAction.note === 'Nothing needs your decision.', mixedAction.note);
    check('  · while its peers keep the counts the server served',
      empty.mixed.filter((z) => z.rail !== 'action')
        .every((z) => z.heading === `${WORDS[z.rail]}: ${empty.servedCounts[z.rail]}`
          && z.cards === empty.servedCounts[z.rail]),
      empty.mixed.map((z) => `${z.heading}/${z.cards}`).join(' | '));
  });

finish();
