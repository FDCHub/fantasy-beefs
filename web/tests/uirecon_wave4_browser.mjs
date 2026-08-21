/* ============================================================================
 * FantasyStakes — UIRECON Wave 4 · Matchup Preview and the Wrap Up results
 *
 * Run directly:   node web/tests/uirecon_wave4_browser.mjs
 * Or through:     python test_uirecon_wave4.py
 *
 * WAVE 4A — THE PREVIEW HAD NOTHING TO PREVIEW.
 *
 * `previewSheet()` drew a five-column split table over `m.yourStarters` and
 * `m.opponentStarters`, and no caller ever supplied either: the League card's
 * preview button opened a sheet built from a matchup object whose starter
 * arrays are empty by construction. So the panel a GM opened before spending
 * Credits showed a header, two empty columns and an explanatory note — and,
 * above them, a MATCHUP block restating the two team names already in the sheet
 * title.
 *
 * A read model serves the lineups now. The guards below therefore do not check
 * that the table renders — they check that it renders SERVED DATA: nine rows a
 * side, each carrying a position, a name and a projection, whose displayed
 * figures sum to the total the server supplied. A preview that computed its own
 * total would pass a "the total is present" test and fail this one.
 *
 * WAVE 4B — THREE THINGS A GM READS THE SAME WAY, BUILT THREE WAYS.
 *
 * Wrap Up carried a vertical snap carousel for Yahoo, the same carousel at a
 * different fixed height for wagers, and no carousel at all for Prop Pools —
 * a flat column of buttons. The two carousels were capped in PIXELS against
 * Rev 4.2 card sizes, so Rev 4.3's taller cards turned the deliberate peek at
 * the next card's title into half a visible card.
 *
 * The assertions below are consequently about AGREEMENT rather than about
 * values: the three sections are measured against each other for heading
 * treatment, heading-to-carousel gap, carousel width and left edge, and each
 * carousel is measured against its own items for the one-card rule. No pixel
 * height is pinned anywhere — pinning one is how the last cap went stale.
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

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

await withPage({ port: 9424 }, async ({ evaluate, setViewport }) => {
  await setViewport(390, 844);
  await evaluate(READY);

  /* ════════════════════════════════════════════════════════════════════════
   * WAVE 4A · THE MATCHUP PREVIEW
   * ══════════════════════════════════════════════════════════════════════ */

  section('4A · the preview opens on a PRICED pairing');

  // The preview has to be opened from a pairing the engine actually quoted.
  // An unpriced one refuses, and a suite that measured a refusal would certify
  // the graceful-degradation path while claiming to certify the served one.
  const opened = await evaluate(`
    const tab = document.querySelector('.fs-tabbar__item[data-destination="league"]');
    if (tab) tab.click();
    const card = [...document.querySelectorAll('#panel-league .fs-wcard--matchup')]
      .find((c) => [...c.querySelectorAll('.fs-market__value')]
        .some((v) => v.textContent.trim() !== '\\u2014'));
    if (!card) return 'no priced card on Play';
    const button = card.querySelector('[data-preview-opponent]');
    if (!button) return 'no preview control on the priced card';
    button.click();
    return 'opened';
  `);
  check('a priced pairing offers a preview control', opened === 'opened', opened);
  await wait(1800);

  // LINEUPS SHIPS COLLAPSED — §10 puts the dense module last and closed — so a
  // width read off it while shut is zero, and zero equals zero. It is opened
  // here so every geometry assertion below measures a lineup a GM can see.
  await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    const s = sheet && [...sheet.querySelectorAll('.fs-prev')]
      .find((x) => x.querySelector('.fs-prev__title').textContent.trim() === 'LINEUPS');
    if (s && !s.classList.contains('is-open')) s.querySelector('.fs-prev__head').click();
    1;
  `);

  const view = await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    if (!sheet) return { error: 'no sheet' };
    const sections = [...sheet.querySelectorAll('.fs-prev')];
    const titles = sections.map((s) => s.querySelector('.fs-prev__title').textContent.trim());
    const lineups = [...sheet.querySelectorAll('.fs-lineup')].map((l) => ({
      team: l.querySelector('.fs-lineup__team').textContent.trim(),
      rows: [...l.querySelectorAll('.fs-lineup__row:not(.is-total)')].map((r) => ({
        pos: r.querySelector('.fs-lineup__pos').textContent.trim(),
        name: r.querySelector('.fs-lineup__name').textContent.trim(),
        proj: r.querySelector('.fs-lineup__proj').textContent.trim(),
        h: Math.round(r.getBoundingClientRect().height),
      })),
      total: l.querySelector('.is-total .fs-lineup__proj').textContent.trim(),
      classes: l.className,
      w: Math.round(l.getBoundingClientRect().width),
    }));
    const body = (i) => (sections[i]
      ? [...sections[i].querySelectorAll('.fs-prev__p')].map((p) => p.textContent.trim())
      : []);
    return {
      title: (sheet.querySelector('.fs-sheet__title') || {}).textContent,
      sub: (sheet.querySelector('.fs-sheet__sub') || {}).textContent,
      titles,
      identityRows: [...sheet.querySelectorAll('[data-preview-section="identity"] .fs-prev__row')]
        .map((r) => r.querySelector('.fs-prev__label').textContent.trim()
          + '=' + r.querySelector('.fs-prev__value').textContent.trim()),
      why: body(titles.indexOf('WHY THE LINE LOOKS THIS WAY')),
      read: body(titles.indexOf('THE READ')),
      lineups,
      sheetText: sheet.textContent.replace(/\\s+/g, ' '),
      heads: sections.map((s) => {
        const h = s.querySelector('.fs-prev__head');
        const r = h.getBoundingClientRect();
        const cs = getComputedStyle(s.querySelector('.fs-prev__title'));
        return {
          tag: h.tagName, collapse: h.hasAttribute('data-collapse'),
          expanded: h.getAttribute('aria-expanded'),
          h: Math.round(r.height), w: Math.round(r.width), left: Math.round(r.left),
          size: cs.fontSize, weight: cs.fontWeight, track: cs.letterSpacing,
        };
      }),
    };
  `);

  section('4A · §5 the sheet states the pairing ONCE');

  // THE PAIRING LIVES IN THE SUBTITLE, and the title names the surface. That
  // split is what lets the identity block below carry the MARKET rather than a
  // second copy of the two team names.
  check('the sheet header carries the pairing once',
    typeof view.sub === 'string' && view.sub.includes(' vs '),
    `${view.title} / ${view.sub}`);
  check('no MATCHUP block restates it',
    !view.titles.includes('MATCHUP'), view.titles.join(' / '));
  // The identity section is now the SELECTED MARKET, not a second team listing.
  check('the first section is the market on offer',
    view.titles[0] === 'ON OFFER' || view.titles[0] === 'RESULT',
    view.titles[0]);
  const teamName = ((view.sub || '').split(' vs ')[1] || '').split(' · ')[0].trim();
  check('the opponent name is not repeated as a bare identity row',
    !view.identityRows.some((r) => r.includes(teamName)),
    view.identityRows.join(' | '));

  section('4A · §6 LINEUPS carries served rows, not empty columns');

  check('both teams draw a lineup', view.lineups.length === 2,
    `${view.lineups.length} lineup(s)`);
  check('LINEUPS is one of the sheet sections',
    view.titles.includes('LINEUPS'), view.titles.join(' / '));

  for (const l of view.lineups) {
    check(`${l.team} — rows are served, not empty`, l.rows.length > 0,
      `${l.rows.length} rows`);
    check(`${l.team} — every row carries position, player and projection`,
      l.rows.every((r) => r.pos && r.name && r.proj
        && r.name !== '\\u2014' && r.proj !== '\\u2014'),
      l.rows.slice(0, 1).map((r) => `${r.pos} ${r.name} ${r.proj}`).join(''));

    // THE TOTAL IS THE SERVER'S. Summing the displayed figures and comparing
    // them to the displayed total is what distinguishes "the read model
    // supplied a total" from "the surface added the column up itself" — the
    // two agree here only because the surface is reporting what it was given.
    const sum = l.rows.reduce((s, r) => s + parseFloat(r.proj), 0);
    check(`${l.team} — the served total equals the sum of the served rows`,
      near(sum, parseFloat(l.total), 0.15), `rows=${sum.toFixed(1)} total=${l.total}`);
  }

  section('4A · §6 the two lineups are the SAME construction');

  const [a, b] = view.lineups;
  if (a && b) {
    check('neither lineup carries a class the other does not',
      a.classes === b.classes, `${a.classes} vs ${b.classes}`);
    check('the two lineups are the same width',
      a.w > 0 && b.w > 0 && near(a.w, b.w), `${a.w} vs ${b.w}`);
    check('the two lineups show the same number of starters',
      a.rows.length === b.rows.length, `${a.rows.length} vs ${b.rows.length}`);
    const heights = [...a.rows, ...b.rows].map((r) => r.h);
    check('every lineup row across both teams is the same height',
      Math.max(...heights) - Math.min(...heights) <= 1,
      `${Math.min(...heights)}–${Math.max(...heights)}px`);
  }

  section('4A · §7 WHY THE LINE reports served numbers');

  const whyText = view.why.join(' ');
  check('WHY THE LINE LOOKS THIS WAY is present',
    view.titles.includes('WHY THE LINE LOOKS THIS WAY'), view.titles.join(' / '));
  check('it names a win probability', /\d+(\.\d+)?%/.test(whyText), whyText.slice(0, 90));
  check('it names the projected totals both lineups showed',
    view.lineups.every((l) => whyText.includes(l.total)),
    view.lineups.map((l) => l.total).join(' / '));
  check('it is not a fixed sentence — it moves with the data',
    !/lorem|placeholder|TBD/i.test(whyText), whyText.slice(0, 60));

  section('4A · §8 THE READ is grounded in the same served data');

  check('THE READ is present', view.titles.includes('THE READ'),
    view.titles.join(' / '));
  const readText = view.read.join(' ');
  check('THE READ says something', readText.length > 40, `${readText.length} chars`);
  // The Rev 4.3 grounding rule: no sentence may imply a source this product
  // does not have. The same forbidden vocabulary the S7 League suite scans for.
  const FORBIDDEN = ['injury report', 'injured', 'questionable', 'doubtful',
    'weather', 'wind', 'beat writer', 'insider', 'sources say', 'snap count',
    'target share', 'news', 'report says'];
  const leak = FORBIDDEN.filter((w) => (whyText + ' ' + readText).toLowerCase().includes(w));
  check('neither module implies a source this product does not have',
    leak.length === 0, leak.join(', '));

  section('4A · §9 the three disclosures share one geometry');

  const peers = view.heads.filter((h) => h.collapse);
  check('the three peer modules are collapsible', peers.length === 3,
    `${peers.length} collapsible head(s)`);
  if (peers.length === 3) {
    const [p, q, r] = peers;
    check('same head height', near(p.h, q.h) && near(q.h, r.h),
      [p.h, q.h, r.h].join(' / '));
    check('same head width', near(p.w, q.w) && near(q.w, r.w),
      [p.w, q.w, r.w].join(' / '));
    check('same left edge', near(p.left, q.left) && near(q.left, r.left),
      [p.left, q.left, r.left].join(' / '));
    check('same title typography',
      p.size === q.size && q.size === r.size
      && p.weight === q.weight && q.weight === r.weight
      && p.track === q.track && q.track === r.track,
      `${p.size}/${p.weight}/${p.track}`);
    check('each is a real button with an expanded state',
      peers.every((h) => h.tag === 'BUTTON' && (h.expanded === 'true' || h.expanded === 'false')),
      peers.map((h) => `${h.tag}:${h.expanded}`).join(' '));
  }

  section('4A · §6 LINEUPS expands and collapses');

  const toggled = await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    const s = [...sheet.querySelectorAll('.fs-prev')]
      .find((x) => x.querySelector('.fs-prev__title').textContent.trim() === 'LINEUPS');
    if (!s) return 'no LINEUPS section';
    const head = s.querySelector('.fs-prev__head');
    const before = s.classList.contains('is-open');
    head.click();
    const after = s.classList.contains('is-open');
    head.click();
    const back = s.classList.contains('is-open');
    return [before, after, back].join(',');
  `);
  const [t0, t1, t2] = String(toggled).split(',');
  check('activating the head toggles the section', t0 !== t1 && t0 === t2, toggled);

  section('4A · §10 the preview names the market the GM is choosing');

  const ctx = await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    const rows = [...sheet.querySelectorAll('[data-preview-section="identity"] .fs-prev__row')]
      .map((r) => r.querySelector('.fs-prev__label').textContent.trim());
    return rows.join('|');
  `);
  check('the market on offer is stated, not left to be inferred',
    /moneyline|spread|over|total/i.test(ctx), ctx);

  /* ════════════════════════════════════════════════════════════════════════
   * WAVE 4B · THE THREE WRAP UP RESULT SECTIONS
   * ══════════════════════════════════════════════════════════════════════ */

  section('4B · §12 exactly three sections, with the locked names');

  await evaluate(`
    const close = document.querySelector('#fs-sheet [data-sheet-close], #fs-sheet .fs-sheet__close');
    if (close) close.click();
    const tab = document.querySelector('.fs-tabbar__item[data-destination="week"]');
    if (tab) tab.click();
    1;
  `);
  await wait(1600);

  const EXPECTED = [
    'YAHOO LEAGUE MATCHUPS · SWIPE',
    'FANTASYSTAKES MATCHUPS · SWIPE',
    'FANTASYSTAKES PROP POOLS · SWIPE',
  ];

  const READ_SECTIONS = `
    const panel = document.getElementById('panel-week');
    const mods = [...panel.querySelectorAll('.fs-wkmod')];
    return {
      docSW: document.documentElement.scrollWidth,
      docCW: document.documentElement.clientWidth,
      panelSW: panel.scrollWidth, panelCW: panel.clientWidth,
      tabbar: (() => {
        const t = document.querySelector('.fs-tabbar');
        if (!t) return null;
        const r = t.getBoundingClientRect();
        return { top: Math.round(r.top), bottom: Math.round(r.bottom),
                 visible: r.bottom <= window.innerHeight + 1 && r.height > 0 };
      })(),
      mods: mods.map((s) => {
        const head = s.querySelector('.fs-heading');
        const car = s.querySelector('.fs-rescar');
        const hs = head ? getComputedStyle(head.querySelector('.fs-heading__text') || head) : null;
        const hb = head ? head.getBoundingClientRect() : null;
        const cb = car ? car.getBoundingClientRect() : null;
        const items = car ? [...car.querySelectorAll(':scope > .fs-rescar__item')] : [];
        return {
          mod: s.dataset.module,
          heading: head ? head.textContent.trim() : null,
          size: hs ? hs.fontSize : null, weight: hs ? hs.fontWeight : null,
          track: hs ? hs.letterSpacing : null, transform: hs ? hs.textTransform : null,
          gap: hb && cb ? +(cb.top - hb.bottom).toFixed(1) : null,
          carW: cb ? +cb.width.toFixed(1) : null,
          carL: cb ? +cb.left.toFixed(1) : null,
          carR: cb ? +cb.right.toFixed(1) : null,
          padL: car ? getComputedStyle(car).paddingLeft : null,
          snap: car ? getComputedStyle(car).scrollSnapType : null,
          overflowX: car ? getComputedStyle(car).overflowX : null,
          scrollW: car ? car.scrollWidth : null,
          clientW: car ? car.clientWidth : null,
          n: items.length,
          itemW: items.map((i) => +i.getBoundingClientRect().width.toFixed(1)),
          itemSnap: items.map((i) => getComputedStyle(i).scrollSnapStop),
          cards: items.map((i) => (i.firstElementChild ? i.firstElementChild.className : '')),
        };
      }),
    };
  `;

  let m = await evaluate(READ_SECTIONS);
  check('Wrap Up carries exactly three sections', m.mods.length === 3,
    `${m.mods.length}`);
  check('the three headings are the locked names',
    JSON.stringify(m.mods.map((x) => x.heading)) === JSON.stringify(EXPECTED),
    m.mods.map((x) => x.heading).join(' / '));

  section('4B · §12 the three sections share one construction');

  const [y, w, p] = m.mods;
  check('same heading typography',
    y.size === w.size && w.size === p.size && y.weight === w.weight
    && w.weight === p.weight && y.track === w.track && w.track === p.track
    && y.transform === w.transform && w.transform === p.transform,
    `${y.size}/${y.weight}/${y.track}`);
  check('same heading-to-carousel gap',
    near(y.gap, w.gap) && near(w.gap, p.gap), [y.gap, w.gap, p.gap].join(' / '));
  check('same carousel width',
    near(y.carW, w.carW) && near(w.carW, p.carW), [y.carW, w.carW, p.carW].join(' / '));
  check('same left edge',
    near(y.carL, w.carL) && near(w.carL, p.carL), [y.carL, w.carL, p.carL].join(' / '));
  check('same right edge',
    near(y.carR, w.carR) && near(w.carR, p.carR), [y.carR, w.carR, p.carR].join(' / '));
  check('same horizontal padding',
    y.padL === w.padL && w.padL === p.padL, [y.padL, w.padL, p.padL].join(' / '));
  check('same swipe behaviour',
    y.snap === w.snap && w.snap === p.snap && /x/.test(String(y.snap)),
    [y.snap, w.snap, p.snap].join(' / '));

  section('4B · §12 one card fills the viewport, and never one and a half');

  for (const s of m.mods) {
    if (!s.n) continue;
    check(`${s.mod} — every item is exactly one carousel wide`,
      s.clientW > 0 && s.itemW.every((v) => v > 0 && near(v, s.clientW)),
      `items ${[...new Set(s.itemW)].join(',')} vs viewport ${s.clientW}`);
    check(`${s.mod} — the rail parks on a card, never between two`,
      s.itemSnap.every((v) => v === 'always'), [...new Set(s.itemSnap)].join(','));
  }

  section('4B · §19 the carousels contain their own overflow');

  check('the document does not scroll sideways',
    m.docSW <= m.docCW + 1, `${m.docSW} vs ${m.docCW}`);
  check('the tab does not scroll sideways',
    m.panelSW <= m.panelCW + 1, `${m.panelSW} vs ${m.panelCW}`);
  check('the bottom navigation is present and on screen',
    Boolean(m.tabbar && m.tabbar.visible), JSON.stringify(m.tabbar));
  for (const s of m.mods) {
    check(`${s.mod} — the overflow lives in the rail`,
      s.overflowX === 'auto' || s.overflowX === 'scroll', String(s.overflowX));
  }

  section('4B · §11 every card in every section is the same shell');

  const shells = await evaluate(`
    const panel = document.getElementById('panel-week');
    const out = [];
    for (const s of panel.querySelectorAll('.fs-wkmod')) {
      for (const card of s.querySelectorAll('.fs-rescar__item .fs-wcard')) {
        const r = card.getBoundingClientRect();
        const cs = getComputedStyle(card);
        out.push({
          mod: s.dataset.module,
          w: Math.round(r.width), left: Math.round(r.left),
          pad: cs.padding, radius: cs.borderRadius,
          hasHead: Boolean(card.querySelector('.fs-wcard__head')),
          hasIdentity: Boolean(card.querySelector('.fs-wcard__identity')),
          identitySize: (() => {
            const el = card.querySelector('.fs-wcard__identity');
            return el ? getComputedStyle(el).fontSize : null;
          })(),
          figureLabelSize: (() => {
            const el = card.querySelector('.fs-wcard__figlabel');
            return el ? getComputedStyle(el).fontSize : null;
          })(),
        });
      }
    }
    return out;
  `);
  if (shells.length > 1) {
    const first = shells[0];
    check('every result card is the same width', shells.every((s) => near(s.w, first.w)),
      [...new Set(shells.map((s) => s.w))].join(','));
    check('every result card sits on the same left edge',
      shells.every((s) => near(s.left, first.left)),
      [...new Set(shells.map((s) => s.left))].join(','));
    check('every result card has the same padding',
      shells.every((s) => s.pad === first.pad),
      [...new Set(shells.map((s) => s.pad))].join(' | '));
    check('every result card has the same corner radius',
      shells.every((s) => s.radius === first.radius),
      [...new Set(shells.map((s) => s.radius))].join(' | '));
    check('every result card names its subject in one place',
      shells.every((s) => s.hasHead && s.hasIdentity), `${shells.length} card(s)`);
    const sizes = new Set(shells.map((s) => s.identitySize).filter(Boolean));
    check('identity typography does not differ between sections',
      sizes.size <= 1, [...sizes].join(' | '));
    const fig = new Set(shells.map((s) => s.figureLabelSize).filter(Boolean));
    check('figure labels do not differ between sections',
      fig.size <= 1, [...fig].join(' | '));
  } else {
    check('at least two result cards were available to compare', false,
      `${shells.length} card(s) on this week`);
  }

  section('4B · §14 no settlement arithmetic runs in the surface');

  // A settled card must report the served outcome word and the served net. The
  // surface has no access to a scoring input, so a card that showed a credit
  // figure the read model did not serve could only have invented it.
  const settled = await evaluate(`
    const panel = document.getElementById('panel-week');
    const cards = [...panel.querySelectorAll('.fs-wcard--result')];
    return cards.map((c) => ({
      badge: (c.querySelector('.fs-wcard__badge') || {}).textContent,
      figures: [...c.querySelectorAll('.fs-wcard__figure')].map((f) => ({
        label: f.querySelector('.fs-wcard__figlabel').textContent.trim(),
        value: f.querySelector('.fs-wcard__figvalue').textContent.trim(),
        exact: f.querySelector('.fs-wcard__figvalue').dataset.exactCents,
      })),
    }));
  `);
  const WORDS = ['WON', 'LOST', 'PUSH', 'VOID', 'SETTLED', 'NO WINNER', 'NOT ENTERED'];
  check('every result card carries a served outcome word',
    settled.every((c) => WORDS.includes(String(c.badge).trim())),
    settled.map((c) => c.badge).join(',') || 'no settled card on this week');
  check('every money figure carries the exact served cents',
    settled.every((c) => c.figures
      .filter((f) => /stake|credits|pot|return/i.test(f.label))
      .every((f) => f.exact !== undefined && f.exact !== '')),
    JSON.stringify(settled.flatMap((c) => c.figures)).slice(0, 160));

  /* ════════════════════════════════════════════════════════════════════════
   * §19 · THE APP-SHELL VIEWPORT POR, ON BOTH SURFACES
   * ══════════════════════════════════════════════════════════════════════ */

  for (const vp of VIEWPORTS) {
    section(`§19 · ${vp.width}x${vp.height} — ${vp.label}`);
    // `setViewport` NAVIGATES — mobile emulation only takes effect on a fresh
    // document — so the app remounts on its default tab. Without this the whole
    // block would measure a hidden panel, and every geometry assertion would
    // compare zero to zero and pass while proving nothing.
    await setViewport(vp.width, vp.height);
    await evaluate(READY);
    await evaluate(`
      const tab = document.querySelector('.fs-tabbar__item[data-destination="week"]');
      if (tab) tab.click();
      1;
    `);
    await wait(900);

    m = await evaluate(READ_SECTIONS);
    check('the Wrap tab is actually laid out at this size',
      m.mods.length === 3 && m.mods.every((x) => x.carW > 0),
      m.mods.map((x) => x.carW).join(' / '));
    check('no tab-level horizontal scrolling',
      m.panelSW <= m.panelCW + 1, `${m.panelSW} vs ${m.panelCW}`);
    check('no document-level horizontal scrolling',
      m.docSW <= m.docCW + 1, `${m.docSW} vs ${m.docCW}`);
    check('the bottom navigation stays on screen',
      Boolean(m.tabbar && m.tabbar.visible), JSON.stringify(m.tabbar));
    check('the three carousels stay the same width',
      near(m.mods[0].carW, m.mods[1].carW) && near(m.mods[1].carW, m.mods[2].carW),
      m.mods.map((x) => x.carW).join(' / '));
    check('the three heading gaps stay equal',
      near(m.mods[0].gap, m.mods[1].gap) && near(m.mods[1].gap, m.mods[2].gap),
      m.mods.map((x) => x.gap).join(' / '));
    for (const s of m.mods) {
      if (!s.n) continue;
      check(`${s.mod} — still exactly one card wide`,
        s.clientW > 0 && s.itemW.every((v) => v > 0 && near(v, s.clientW)),
        `${[...new Set(s.itemW)].join(',')} vs ${s.clientW}`);
    }

    // The preview sheet has to survive the same five widths, and it scrolls
    // INTERNALLY — a sheet that pushed the document is the defect the shell POR
    // names, and one that clipped its own content is the defect behind it.
    const sheet = await evaluate(`
      const tab = document.querySelector('.fs-tabbar__item[data-destination="league"]');
      if (tab) tab.click();
      const card = [...document.querySelectorAll('#panel-league .fs-wcard--matchup')]
        .find((c) => [...c.querySelectorAll('.fs-market__value')]
          .some((v) => v.textContent.trim() !== '\\u2014'));
      if (!card) return { skip: 'no priced card' };
      const button = card.querySelector('[data-preview-opponent]');
      if (!button) return { skip: 'no preview control' };
      button.click();
      return { clicked: true };
    `);
    if (!sheet.skip) {
      await wait(1500);
      await evaluate(`
        const sheet = document.getElementById('fs-sheet');
        const sec = sheet && [...sheet.querySelectorAll('.fs-prev')]
          .find((x) => x.querySelector('.fs-prev__title').textContent.trim() === 'LINEUPS');
        if (sec && !sec.classList.contains('is-open')) sec.querySelector('.fs-prev__head').click();
        1;
      `);
      const geom = await evaluate(`
        const s = document.getElementById('fs-sheet');
        if (!s) return { missing: true };
        const scroller = s.querySelector('.fs-sheet__body') || s;
        const r = s.getBoundingClientRect();
        const lineups = [...s.querySelectorAll('.fs-lineup')]
          .map((l) => Math.round(l.getBoundingClientRect().width));
        return {
          sheetSW: s.scrollWidth, sheetCW: s.clientWidth,
          bodySW: scroller.scrollWidth, bodyCW: scroller.clientWidth,
          bodyOverflowY: getComputedStyle(scroller).overflowY,
          right: Math.round(r.right), innerW: window.innerWidth,
          docSW: document.documentElement.scrollWidth,
          docCW: document.documentElement.clientWidth,
          lineups,
        };
      `);
      check('the preview sheet does not scroll sideways',
        !geom.missing && geom.bodySW <= geom.bodyCW + 1,
        `${geom.bodySW} vs ${geom.bodyCW}`);
      check('the preview sheet scrolls internally',
        /auto|scroll/.test(String(geom.bodyOverflowY)), String(geom.bodyOverflowY));
      check('the preview sheet does not push the document sideways',
        geom.docSW <= geom.docCW + 1, `${geom.docSW} vs ${geom.docCW}`);
      check('the preview draws both lineups at this size',
        Boolean(geom.lineups) && geom.lineups.length === 2
        && geom.lineups.every((v) => v > 0), (geom.lineups || []).join(' / '));
      if (geom.lineups && geom.lineups.length === 2) {
        check('both lineups keep the same width at this size',
          near(geom.lineups[0], geom.lineups[1]), geom.lineups.join(' / '));
      }
      await evaluate(`
        const close = document.querySelector('#fs-sheet [data-sheet-close], #fs-sheet .fs-sheet__close');
        if (close) close.click();
        const tab = document.querySelector('.fs-tabbar__item[data-destination="week"]');
        if (tab) tab.click();
        1;
      `);
      await wait(900);
    } else {
      check(`preview reachable at ${vp.width}px`, false, sheet.skip);
    }
  }
});

finish();
