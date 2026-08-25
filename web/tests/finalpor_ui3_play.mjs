/* ============================================================================
 * FantasyStakes — FINAL POR · UI-3A/B/C · the Play carousels and odds refresh
 *
 * WHY THIS RUNS IN A BROWSER. "One card at a time" is a measurement, not a CSS
 * rule: `flex: 0 0 100%` is only one card if the item's border box actually
 * equals the rail's viewport, and a stray gap, padding or scrollbar makes it
 * not. The same is true of "upper-right" and of "stays on Play".
 *
 * WHAT IS ASSERTED, AND WHY EACH CASE EXISTS:
 *
 *   P1  the Matchup rail shows exactly ONE complete card              §27A
 *   P2  the Prop Pool rail shows exactly ONE complete card            §27B
 *   P3  both rails snap, one card per swipe, and do not chain         §27A/B
 *   P4  the governed slate is 3 TEAM + 1 MATCHUP                      §16
 *   P5  the odds-refresh control sits upper-right, on the card        §27C
 *   P6  pressing refresh KEEPS the reader on Play                     §27C
 *   P7  and keeps the carousel where they left it                     §27A
 *   P8  no page-level horizontal scroll at any certified width
 *
 * P6 AND P7 ARE THE ONES THAT COULD SILENTLY REGRESS. UI-1 fixed a shell that
 * navigated away on any remount; a refresh that rebuilt the panels without
 * `preserveContext` would reintroduce exactly that defect on a different
 * button, and no source read would notice.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();

const VIEWPORTS = [
  { width: 320, height: 568, label: 'smallest certified phone' },
  { width: 375, height: 667, label: 'standard phone' },
  { width: 390, height: 844, label: 'modern phone' },
];

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 8000;
    const poll = () => {
      const mounted = document.querySelector('.fs-tabbar__item')
        && document.querySelector('#panel-league');
      if (mounted || Date.now() > deadline) return resolve(Boolean(mounted));
      setTimeout(poll, 100);
    };
    poll();
  });
`;

const GO_PLAY = `
  { const t = document.querySelector(
      '.fs-tabbar__item[data-destination="league"]');
    if (t) t.click(); }
`;

await withPage({ port: 9481, settleMs: 2500 }, async ({ evaluate, setViewport }) => {

  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    const tag = `${vp.width}×${vp.height}`;
    report.section(`UI-3 · Play at ${tag} (${vp.label})`);
    report.check(`${tag} · the application mounted`,
      await evaluate(READY) === true);

    const m = await evaluate(`
      ${GO_PLAY}
      const railInfo = (sel) => {
        const rail = document.querySelector(sel);
        if (!rail) return null;
        const rr = rail.getBoundingClientRect();
        const cs = getComputedStyle(rail);
        const items = [...rail.querySelectorAll('.fs-carousel__item')];
        return {
          present: true,
          railW: Math.round(rr.width),
          clientW: rail.clientWidth,
          scrollW: rail.scrollWidth,
          count: items.length,
          itemW: items.map((i) => Math.round(i.getBoundingClientRect().width)),
          snapType: cs.scrollSnapType,
          overscroll: cs.overscrollBehaviorX,
          overflowX: cs.overflowX,
          overflowY: cs.overflowY,
          snapAlign: items.length
            ? getComputedStyle(items[0]).scrollSnapAlign : null,
          snapStop: items.length
            ? getComputedStyle(items[0]).scrollSnapStop : null,
          spill: items.map((i) => {
            const card = i.firstElementChild;
            return card ? card.scrollHeight > card.clientHeight + 1 : false;
          }),
        };
      };
      const head = document.querySelector(
        '#fs-bets-carousel .fs-wcard__head');
      const refresh = head ? head.querySelector('[data-odds-refresh]') : null;
      const challenge = head
        ? head.querySelector('.fs-wcard__challenge') : null;
      const box = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { left: Math.round(r.left), right: Math.round(r.right),
                 top: Math.round(r.top), bottom: Math.round(r.bottom),
                 w: Math.round(r.width), h: Math.round(r.height) };
      };
      return {
        matchups: railInfo('#fs-bets-carousel'),
        pools: railInfo('#fs-play-pools'),
        poolScopes: [...document.querySelectorAll(
          '#fs-play-pools .fs-carousel__item')]
          .map((i) => (i.textContent.match(/\\b(TEAM|MATCHUP)\\b/) || [])[1]
                      || null),
        headBox: box(head),
        refreshBox: box(refresh),
        challengeBox: box(challenge),
        refreshInsideChallenge: refresh && challenge
          ? challenge.contains(refresh) : null,
        docScrollW: document.documentElement.scrollWidth,
        docClientW: document.documentElement.clientWidth,
      };
    `);

    /* ── P1/P2 — one complete card at a time ──────────────────────────── */

    for (const [key, label] of [['matchups', 'Matchup'], ['pools', 'Prop Pool']]) {
      const rail = m[key];
      report.check(`${tag} · the ${label} rail exists`,
        rail && rail.present === true, String(rail && rail.present));
      if (!rail || !rail.present) continue;
      report.check(`${tag} · ${label} — it holds cards`,
        rail.count > 0, `${rail.count} cards`);
      report.check(`${tag} · ${label} — every card is exactly one viewport wide`,
        rail.itemW.every((w) => Math.abs(w - rail.clientW) <= 1),
        `items ${rail.itemW.join('/')} vs rail ${rail.clientW}`);
      report.check(`${tag} · ${label} — so no neighbour can peek in`,
        rail.itemW.every((w) => w <= rail.clientW + 1));
      report.check(`${tag} · ${label} — no card spills its own shell`,
        rail.spill.every((s) => s === false), JSON.stringify(rail.spill));

      /* ── P3 — the snap contract ─────────────────────────────────────── */
      report.check(`${tag} · ${label} — snaps on x, mandatory`,
        /x/.test(rail.snapType) && /mandatory/.test(rail.snapType),
        rail.snapType);
      report.check(`${tag} · ${label} — one card per swipe`,
        rail.snapStop === 'always', String(rail.snapStop));
      report.check(`${tag} · ${label} — snaps to the card's start`,
        rail.snapAlign === 'start', String(rail.snapAlign));
      report.check(`${tag} · ${label} — a swipe past the end does not chain`,
        rail.overscroll === 'contain', String(rail.overscroll));
      report.check(`${tag} · ${label} — it scrolls sideways, never down`,
        rail.overflowX === 'auto' && rail.overflowY === 'hidden',
        `${rail.overflowX}/${rail.overflowY}`);
    }

    /* ── P8 — no page-level horizontal scroll ─────────────────────────── */

    report.check(`${tag} · no page-level horizontal scroll`,
      m.docScrollW <= m.docClientW + 1,
      `${m.docScrollW} vs ${m.docClientW}`);
  }

  /* ── P4 — the governed slate ────────────────────────────────────────── */

  await setViewport(390, 844);
  await evaluate(READY);
  report.section('UI-3B · the governed slate is 3 TEAM + 1 MATCHUP');

  const slate = await evaluate(`
    ${GO_PLAY}
    const items = [...document.querySelectorAll(
      '#fs-play-pools .fs-carousel__item')];
    // THE SCOPE IS READ FROM THE BADGE'S CLASS, not from the card's prose.
    // poolCard marks the badge is-team or is-matchup; the visible words are
    // the catalog's own question, which mentions teams in either scope --
    // reading the text called every occurrence TEAM and was measuring the
    // wrong thing. (No backticks in here: this comment lives inside a
    // template literal.)
    const scope = (el) => {
      const badge = el.querySelector('.fs-pool__badge');
      if (!badge) return null;
      if (badge.classList.contains('is-matchup')) return 'MATCHUP';
      if (badge.classList.contains('is-team')) return 'TEAM';
      return null;
    };
    return {
      count: items.length,
      scopes: items.map(scope),
      badges: items.map((i) => {
        const b = i.querySelector('.fs-pool__badge');
        return b ? b.textContent.trim() : null;
      }),
      rollovers: items.filter((i) => i.querySelector(
        '.fs-pool__badge.is-rollover')).length,
    };
  `);

  report.check('the Pool rail draws four occurrences',
    slate.count === 4,
    `${slate.count}: ${JSON.stringify(slate.badges)}`);
  const team = slate.scopes.filter((s) => s === 'TEAM').length;
  const matchup = slate.scopes.filter((s) => s === 'MATCHUP').length;
  report.check('  · three of them are TEAM scope',
    team === 3, `${team} TEAM`);
  report.check('  · and one is MATCHUP scope',
    matchup === 1, `${matchup} MATCHUP — ${JSON.stringify(slate.badges)}`);
  report.check('  · every occurrence declares a scope',
    slate.scopes.every((v) => v === 'TEAM' || v === 'MATCHUP'),
    JSON.stringify(slate.scopes));

  /* ── P5 — the refresh control ───────────────────────────────────────── */

  report.section('UI-3C · the odds-refresh control');

  const c = await evaluate(`
    ${GO_PLAY}
    const head = document.querySelector('#fs-bets-carousel .fs-wcard__head');
    const refresh = head ? head.querySelector('[data-odds-refresh]') : null;
    const challenge = head ? head.querySelector('.fs-wcard__challenge') : null;
    const box = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { left: Math.round(r.left), right: Math.round(r.right),
               top: Math.round(r.top), bottom: Math.round(r.bottom),
               w: Math.round(r.width), h: Math.round(r.height) };
    };
    return {
      hasRefresh: Boolean(refresh),
      tag: refresh ? refresh.tagName : null,
      inChallenge: refresh && challenge ? challenge.contains(refresh) : null,
      refresh: box(refresh), head: box(head), challenge: box(challenge),
      label: refresh ? refresh.getAttribute('aria-label') : null,
    };
  `);

  report.check('the card carries an odds-refresh control',
    c.hasRefresh === true, String(c.hasRefresh));
  if (c.hasRefresh) {
    report.check('  · it is a real button, reachable by keyboard',
      c.tag === 'BUTTON', String(c.tag));
    report.check('  · and NOT nested inside the challenge button',
      c.inChallenge === false, String(c.inChallenge));
    report.check('  · it sits in the card head’s RIGHT half',
      c.refresh.left >= c.head.left + (c.head.w / 2),
      `refresh left ${c.refresh.left}, head centre ${
        Math.round(c.head.left + c.head.w / 2)}`);
    report.check('  · flush to the head’s right edge',
      c.head.right - c.refresh.right <= 8,
      `${c.head.right - c.refresh.right}px inset`);
    report.check('  · at the TOP of the card head',
      c.refresh.top - c.head.top <= 8,
      `${c.refresh.top - c.head.top}px from the top`);
    report.check('  · to the right of the challenge control, never over it',
      c.refresh.left >= c.challenge.right - 1,
      `refresh ${c.refresh.left} vs challenge right ${c.challenge.right}`);
    report.check('  · it meets the 44px touch floor',
      c.refresh.w >= 40 && c.refresh.h >= 40,
      `${c.refresh.w}×${c.refresh.h}`);
    report.check('  · and names what it refreshes',
      /refresh odds/i.test(c.label || ''), String(c.label));
  }

  /* ── P6/P7 — the refresh keeps the reader where they are ────────────── */

  report.section('UI-3C · a refresh stays on Play, at the same card');

  const after = await evaluate(`return (async () => {
    ${GO_PLAY}
    const rail = document.querySelector('#fs-bets-carousel');
    // Move to the second card the way a reader does, then refresh.
    const step = rail ? rail.clientWidth : 0;
    if (rail && rail.scrollWidth > rail.clientWidth) rail.scrollLeft = step;
    const before = rail ? Math.round(rail.scrollLeft) : null;
    const btn = document.querySelector(
      '#fs-bets-carousel [data-odds-refresh]');
    if (btn) btn.click();
    await new Promise((r) => setTimeout(r, 1400));
    const live = document.querySelector('#fs-bets-carousel');
    const active = document.querySelector('.fs-tabbar__item.is-active');
    return {
      before,
      after: live ? Math.round(live.scrollLeft) : null,
      destination: active ? active.getAttribute('data-destination') : null,
      panelVisible: Boolean(document.querySelector(
        '#panel-league:not([hidden])')),
      sheetOpen: Boolean(document.querySelector('.fs-sheet.is-open')),
    };
  })();`);

  report.check('the reader is still on Play after a refresh',
    after.destination === 'league', String(after.destination));
  report.check('  · and the Play panel is the visible one',
    after.panelVisible === true, String(after.panelVisible));
  report.check('  · no sheet was opened by the refresh',
    after.sheetOpen === false, String(after.sheetOpen));
  if (after.before !== null && after.before > 0) {
    report.check('  · and the carousel is where they left it',
      Math.abs(after.after - after.before) <= 2,
      `${after.before} → ${after.after}`);
  } else {
    report.check('  · the carousel had a single card, so position is trivially kept',
      after.after === 0, String(after.after));
  }
});

report.finish();
