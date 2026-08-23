/* ============================================================================
 * FantasyStakes — FINAL POR · the universal close-X, and what it must not break
 *
 * THE RULING. The close control is UPPER-LEFT, visually attached to the active
 * card, sheet, modal or detail view, everywhere in the application including
 * Wrap Up. It supersedes every older upper-right reference — Rev 4.3 §25 and
 * Final POR §29 among them. It is a positional visual rule, not a redesign.
 *
 * WHY A DEDICATED SUITE FOR ONE CSS RULE. Because "not a redesign" is the part
 * that has to be proved. An absolutely-positioned control in a corner is
 * exactly the shape that silently overlaps a title, steals a badge's space,
 * pushes a sheet wider than the viewport or grows an expansion past its bound —
 * and every one of those would be a regression introduced by a rule that reads
 * as purely cosmetic. Each is measured here rather than assumed.
 *
 * WHAT IS ASSERTED, ON EVERY SURFACE AT EVERY CERTIFIED WIDTH:
 *
 *   X1  the control exists, is a real button, and is named
 *   X2  it is UPPER-LEFT, inside the sheet and attached to its corner
 *   X3  it overlaps no title and no badge
 *   X4  opening it shifts no card width and no page geometry
 *   X5  no horizontal overflow while it is open
 *   X6  no bottom-navigation collision
 *   X7  the expansion is still bounded — no height regression
 *   X8  it is the SAME control on Play, Status and Wrap Up
 *
 * X8 IS WHAT MAKES "EVERYWHERE" CHECKABLE. `sheet()` renders every dismissible
 * overlay in the product, so one implementation serves all three surfaces; the
 * suite opens a sheet on each and requires the same class, the same accessible
 * name and the same corner. A per-surface variant would show up here as a
 * disagreement rather than as a bug somebody eventually notices.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();

const VIEWPORTS = [
  { width: 320, height: 568, label: 'smallest certified phone' },
  { width: 375, height: 667, label: 'standard phone' },
  { width: 390, height: 844, label: 'modern phone' },
];

/** The three shared-shell surfaces the ruling names. */
const SURFACES = [
  { id: 'league', label: 'Play',
    open: "document.querySelector('#fs-bets-carousel [data-preview-opponent],"
        + " #fs-play-pools [data-pool]')" },
  { id: 'action', label: 'Status',
    open: "document.querySelector('#panel-action [data-card-action],"
        + " #panel-action [data-preview-opponent], #panel-action [data-pool]')" },
  { id: 'week', label: 'Wrap Up',
    open: "document.querySelector('#panel-week [data-card-action],"
        + " #panel-week [data-pool]')" },
];

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 8000;
    const poll = () => {
      const mounted = document.querySelector('.fs-tabbar__item')
        && document.querySelector('#fs-sheet');
      if (mounted || Date.now() > deadline) return resolve(Boolean(mounted));
      setTimeout(poll, 100);
    };
    poll();
  });
`;

const PROBE = (surface) => `return (async () => {
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: Math.round(r.left), right: Math.round(r.right),
             top: Math.round(r.top), bottom: Math.round(r.bottom),
             w: Math.round(r.width), h: Math.round(r.height) };
  };
  const overlaps = (a, b) => !!a && !!b
    && !(a.right <= b.left + 1 || b.right <= a.left + 1
         || a.bottom <= b.top + 1 || b.bottom <= a.top + 1);

  { const t = document.querySelector(
      '.fs-tabbar__item[data-destination="${surface.id}"]');
    if (t) t.click(); }
  await new Promise((r) => setTimeout(r, 250));

  const panel = document.getElementById('panel-${surface.id}');
  const firstCard = panel ? panel.querySelector(
    '.fs-carousel__item > *, .fs-rescar__item > *, .fs-rail__item > *') : null;

  // GEOMETRY BEFORE, so a shift caused by opening is measurable rather than
  // inferred from a single reading.
  const before = {
    card: box(firstCard),
    docScrollW: document.documentElement.scrollWidth,
    docClientW: document.documentElement.clientWidth,
  };

  const trigger = ${surface.open};
  if (!trigger) {
    return { opened: false, reason: 'no expandable card on this surface',
             before };
  }
  trigger.click();
  await new Promise((r) => setTimeout(r, 700));

  const overlay = document.getElementById('fs-overlay');
  const sheet = overlay && overlay.classList.contains('is-open')
    ? document.getElementById('fs-sheet') : null;
  if (!sheet) return { opened: false, reason: 'no sheet opened', before };

  const close = sheet.querySelector('.fs-sheet__close');
  const title = sheet.querySelector('.fs-sheet__title');
  const sub = sheet.querySelector('.fs-sheet__sub');
  const badges = [...sheet.querySelectorAll(
    '.fs-badge, .fs-pool__badge, .fs-wcard__badge, [class*="badge"]')];
  const nav = document.querySelector('.fs-tabbar');

  const s = box(sheet);
  const c = box(close);

  return {
    opened: true,
    before,
    sheet: s,
    close: c,
    tag: close ? close.tagName : null,
    cls: close ? close.className : null,
    label: close ? close.getAttribute('aria-label') : null,
    // ATTACHED TO THE SHEET, measured as insets from the sheet's own edges.
    insetLeft: c && s ? c.left - s.left : null,
    insetTop: c && s ? c.top - s.top : null,
    insetRight: c && s ? s.right - c.right : null,
    inSheet: c && s
      ? (c.left >= s.left - 1 && c.right <= s.right + 1
         && c.top >= s.top - 1) : null,
    overlapsTitle: overlaps(c, box(title)),
    overlapsSub: overlaps(c, box(sub)),
    overlapsBadge: badges.some((b) => overlaps(c, box(b))),
    badgeCount: badges.length,
    // AFTER, for the shift comparison.
    afterCard: box(firstCard),
    docScrollW: document.documentElement.scrollWidth,
    docClientW: document.documentElement.clientWidth,
    viewportH: window.innerHeight,
    navTop: nav ? Math.round(nav.getBoundingClientRect().top) : null,
  };
})();`;

await withPage({ port: 9491, settleMs: 2500 }, async ({ evaluate, setViewport }) => {

  /** Collected so X8 can compare the three surfaces against each other. */
  const seen = [];

  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    const tag = `${vp.width}×${vp.height}`;
    report.section(`Universal close-X at ${tag} (${vp.label})`);
    report.check(`${tag} · the application mounted`,
      await evaluate(READY) === true);

    for (const surface of SURFACES) {
      const m = await evaluate(PROBE(surface));
      const at = `${tag} · ${surface.label}`;

      report.check(`${at} — a card expands into a sheet`,
        m.opened === true, m.reason || 'opened');
      if (!m.opened) continue;

      /* ── X1 — the control ─────────────────────────────────────────── */
      report.check(`${at} — the close control exists`,
        m.close !== null, String(m.cls));
      report.check(`${at} — it is a real button`,
        m.tag === 'BUTTON', String(m.tag));
      report.check(`${at} — and it is named for assistive tech`,
        (m.label || '').toLowerCase() === 'close', String(m.label));

      /* ── X2 — UPPER-LEFT, attached ────────────────────────────────── */
      report.check(`${at} — it is in the sheet's LEFT half`,
        m.close.left < m.sheet.left + m.sheet.w / 2,
        `left ${m.close.left}, sheet centre ${
          Math.round(m.sheet.left + m.sheet.w / 2)}`);
      report.check(`${at} — and NOT upper-right`,
        m.insetLeft < m.insetRight,
        `inset left ${m.insetLeft} vs right ${m.insetRight}`);
      report.check(`${at} — attached to the sheet's top-left corner`,
        m.insetLeft >= 0 && m.insetLeft <= 24
        && m.insetTop >= 0 && m.insetTop <= 24,
        `left+${m.insetLeft} top+${m.insetTop}`);
      report.check(`${at} — and inside the sheet, not floating over the page`,
        m.inSheet === true, String(m.inSheet));
      report.check(`${at} — it meets a usable target size`,
        m.close.w >= 24 && m.close.h >= 24, `${m.close.w}×${m.close.h}`);

      /* ── X3 — no overlap ──────────────────────────────────────────── */
      report.check(`${at} — it overlaps no sheet title`,
        m.overlapsTitle === false, String(m.overlapsTitle));
      report.check(`${at} — nor the subtitle`,
        m.overlapsSub === false, String(m.overlapsSub));
      report.check(`${at} — nor any badge`,
        m.overlapsBadge === false, `${m.badgeCount} badges checked`);

      /* ── X4 — no geometry shift ───────────────────────────────────── */
      if (m.before.card && m.afterCard) {
        report.check(`${at} — opening it shifts no card width`,
          m.before.card.w === m.afterCard.w,
          `${m.before.card.w} → ${m.afterCard.w}`);
      }
      report.check(`${at} — and no page-width shift`,
        m.before.docClientW === m.docClientW,
        `${m.before.docClientW} → ${m.docClientW}`);

      /* ── X5 — no horizontal overflow ──────────────────────────────── */
      report.check(`${at} — no horizontal overflow while open`,
        m.docScrollW <= m.docClientW + 1,
        `${m.docScrollW} vs ${m.docClientW}`);
      report.check(`${at} — the sheet itself fits the viewport`,
        m.sheet.w <= m.docClientW + 1 && m.sheet.left >= -1,
        `sheet ${m.sheet.w} at ${m.sheet.left}`);

      /* ── X6 — no bottom-nav collision ─────────────────────────────── */
      if (m.navTop !== null) {
        report.check(`${at} — the close control clears the bottom navigation`,
          m.close.bottom <= m.navTop + 1,
          `close bottom ${m.close.bottom} vs nav top ${m.navTop}`);
      }

      /* ── X7 — the expansion is still bounded ──────────────────────── */
      /* §29's bound is "~75vh". 0.76 is the tolerance on the "~": it admits a
       * sheet sitting exactly on its 75% max-height plus a rounded pixel, and
       * refuses the 80% this measured before the bound was tightened. */
      report.check(`${at} — the expansion is still bounded (no height regression)`,
        m.sheet.h <= m.viewportH * 0.76,
        `${m.sheet.h}px of ${m.viewportH}px = ${
          Math.round((m.sheet.h / m.viewportH) * 100)}vh`);

      seen.push({ at, cls: m.cls, label: m.label,
                  insetLeft: m.insetLeft, insetTop: m.insetTop });
    }
  }

  /* ── X8 — one control, everywhere ───────────────────────────────────── */

  report.section('Universal close-X · it is the SAME control everywhere');
  report.check('every surface was measured at every width',
    seen.length === VIEWPORTS.length * SURFACES.length,
    `${seen.length} of ${VIEWPORTS.length * SURFACES.length}`);
  report.check('  · all of them use the one class',
    new Set(seen.map((s) => s.cls)).size <= 1,
    [...new Set(seen.map((s) => s.cls))].join(' | '));
  report.check('  · all of them carry the one accessible name',
    new Set(seen.map((s) => s.label)).size <= 1,
    [...new Set(seen.map((s) => s.label))].join(' | '));
  report.check('  · and all of them sit at the same corner inset',
    new Set(seen.map((s) => `${s.insetLeft}/${s.insetTop}`)).size <= 1,
    [...new Set(seen.map((s) => `${s.insetLeft}/${s.insetTop}`))].join(' | '));
});

report.finish();
