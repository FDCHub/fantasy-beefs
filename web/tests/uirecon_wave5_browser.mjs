/* ============================================================================
 * FantasyStakes — UIRECON Wave 5 · the Status tab's four lifecycle rails
 *
 * Run directly:   node web/tests/uirecon_wave5_browser.mjs
 * Or through:     python test_uirecon_wave5.py
 *
 * WHAT WAVE 5 CHANGED, AND WHAT IT DELIBERATELY DID NOT.
 *
 * Status has always had four rails, and the showcase could only ever fill two
 * of them: every contest it played was accepted on the same tick it was issued,
 * so ACTION REQUIRED and WAITING were structurally unreachable. A GM meeting the
 * product for the first time could not see what "something needs your decision"
 * looks like, because the demo had nothing that needed one.
 *
 * The fixture now leaves TWO live-week challenges unanswered — one issued to the
 * visitor and one issued by them — through the same funded lifecycle
 * `/beef/respond` answers. So the assertions below are not "four rails render".
 * They are that the two new rails carry REAL records with the terms the server
 * served, that the one the visitor may answer offers controls and the one they
 * may not does not, and that a card is the same object on every rail.
 *
 * THE CARD SHELL IS NOT NEW. `lifecycleCard` already drew every rail through
 * `wagerCard`, which is why §10's parallel-construction assertions compare rails
 * to each other rather than to a pinned value: the requirement is that changing
 * rails feels like watching one wager move, and that is a statement about
 * agreement, not about pixels. What Wave 5 changed here is the card's SENTENCE —
 * it used to fall back to the mode note, so all four rails said "Terms are
 * frozen as offered" whatever the wager was doing.
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

/** Enter the demo, mount the app, and land on Status. */
const ENTER = async ({ evaluate }) => {
  await evaluate(`return (async () => {
    await fetch('/demo/enter', { method: 'POST', credentials: 'include' });
    return 1;
  })()`);
  await evaluate(`location.href = '/app/index.html'; 1`);
  await wait(4200);
  await evaluate(READY);
  await evaluate(`
    const tab = document.querySelector('.fs-tabbar__item[data-destination="action"]');
    if (tab) tab.click();
    1;
  `);
  await wait(1800);
};

/** Everything the assertions below read, in one pass. */
const READ_STATUS = `
  const panel = document.getElementById('panel-action');
  const bar = document.getElementById('fs-tabbar');
  const barRect = bar ? bar.getBoundingClientRect() : null;
  const zones = [...panel.querySelectorAll('.fs-railsec')];
  return {
    docSW: document.documentElement.scrollWidth,
    docCW: document.documentElement.clientWidth,
    panelSW: panel.scrollWidth, panelCW: panel.clientWidth,
    panelVOverflow: panel.scrollHeight - panel.clientHeight,
    nav: barRect ? {
      height: Math.round(barRect.height),
      bottom: Math.round(barRect.bottom),
      onScreen: barRect.bottom <= window.innerHeight + 1 && barRect.height > 0,
      reachable: [...document.querySelectorAll('.fs-tabbar__item')].every((el) => {
        const r = el.getBoundingClientRect();
        const hit = document.elementFromPoint(
          Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2));
        return hit && bar.contains(hit);
      }),
    } : null,
    zones: zones.map((zone) => {
      const head = zone.querySelector('.fs-heading__text') || zone.querySelector('.fs-heading');
      const rail = zone.querySelector('.fs-rail');
      const items = rail ? [...rail.querySelectorAll(':scope > .fs-rail__item')] : [];
      const hb = head ? head.getBoundingClientRect() : null;
      const rb = rail ? rail.getBoundingClientRect() : null;
      const hs = head ? getComputedStyle(head) : null;
      return {
        heading: head ? head.textContent.trim() : null,
        headSize: hs ? hs.fontSize : null,
        headWeight: hs ? hs.fontWeight : null,
        headTrack: hs ? hs.letterSpacing : null,
        headWrapped: hb && hs
          ? hb.height > parseFloat(hs.lineHeight || hs.fontSize) * 1.6 : null,
        gap: hb && rb ? +(rb.top - hb.bottom).toFixed(1) : null,
        railW: rb ? +rb.width.toFixed(1) : null,
        railL: rb ? +rb.left.toFixed(1) : null,
        railH: rb ? +rb.height.toFixed(1) : null,
        railOverflowX: rail ? getComputedStyle(rail).overflowX : null,
        railVOverflow: rail ? rail.scrollHeight - rail.clientHeight : null,
        note: (zone.querySelector('.fs-rail__note') || {}).textContent || null,
        n: items.length,
        cards: items.map((item) => {
          const card = item.querySelector('.fs-wcard');
          if (!card) return null;
          const r = card.getBoundingClientRect();
          const cs = getComputedStyle(card);
          const el = (sel) => card.querySelector(sel);
          const box = (sel) => {
            const node = el(sel);
            if (!node) return null;
            const b = node.getBoundingClientRect();
            return { top: +(b.top - r.top).toFixed(1),
                     left: +(b.left - r.left).toFixed(1),
                     h: +b.height.toFixed(1) };
          };
          return {
            cls: card.className,
            w: +r.width.toFixed(1), left: +r.left.toFixed(1),
            pad: cs.padding, radius: cs.borderRadius,
            clipped: card.scrollHeight > card.clientHeight + 1
              || card.scrollWidth > card.clientWidth + 1,
            identity: (el('.fs-wcard__identity') || {}).textContent || '',
            identitySize: el('.fs-wcard__identity')
              ? getComputedStyle(el('.fs-wcard__identity')).fontSize : null,
            badge: (el('.fs-wcard__badge') || {}).textContent || '',
            context: (el('.fs-wcard__context') || {}).textContent || '',
            copy: (el('.fs-wcard__copy') || {}).textContent || '',
            figures: [...card.querySelectorAll('.fs-wcard__figure')].map((f) => ({
              label: f.querySelector('.fs-wcard__figlabel').textContent.trim(),
              value: f.querySelector('.fs-wcard__figvalue').textContent.trim(),
              cents: f.querySelector('.fs-wcard__figvalue').dataset.exactCents,
            })),
            footLabel: (el('.fs-wcard__footlabel') || {}).textContent || '',
            footValue: (el('.fs-wcard__footvalue') || {}).textContent || '',
            headBox: box('.fs-wcard__head'),
            figBox: box('.fs-wcard__figures'),
            footBox: box('.fs-wcard__foot'),
          };
        }),
      };
    }),
  };
`;

await withPage({ port: 9432, origin: process.env.FS_TEST_ORIGIN },
  async ({ evaluate, setViewport }) => {
    await setViewport(390, 844);
    await ENTER({ evaluate });

    let m = await evaluate(READ_STATUS);

    /* ══════════════════════════════════════════════════════════════════════
     * §2 · THE FOUR RAILS, AND WHAT EACH ONE ANSWERS
     * ════════════════════════════════════════════════════════════════════ */

    section('§2 · Status carries the four locked rails');

    check('Status draws exactly four rails', m.zones.length === 4,
      `${m.zones.length}`);
    const headings = m.zones.map((z) => (z.heading || '').split('·')[0].trim());
    const EXPECTED = ['ACTION REQUIRED', 'WAITING', 'LIVE', 'COMPLETED'];
    check('the rail names are the locked ones, in order',
      EXPECTED.every((name, i) => (headings[i] || '').startsWith(name)),
      headings.join(' / '));

    const [action, waiting, live, completed] = m.zones;

    section('§3 · every rail is populated from real lifecycle records');

    check('ACTION REQUIRED carries a real item', action.n >= 1,
      `${action.n} — ${action.note || ''}`);
    check('WAITING carries a real item', waiting.n >= 1,
      `${waiting.n} — ${waiting.note || ''}`);
    check('LIVE carries the accepted live-week Matchup', live.n >= 1,
      `${live.n} — ${live.note || ''}`);
    check('COMPLETED carries the settled Matchups', completed.n >= 2,
      `${completed.n}`);

    /* ══════════════════════════════════════════════════════════════════════
     * §6 / §7 · WHOSE DECISION IT IS
     * ════════════════════════════════════════════════════════════════════ */

    section('§6 · ACTION REQUIRED says what is being asked, and offers the ask');

    const incoming = action.cards[0];
    check('it names the opponent', /vs \S/.test(incoming.identity),
      incoming.identity);
    check('it names the market and the week', /WK \d+/.test(incoming.context)
      && /Moneyline|Spread|Total/.test(incoming.context), incoming.context);
    check('it states the terms as fixed or floating',
      /FIXED|FLOATING/.test(incoming.context), incoming.context);
    check('it shows both stakes and the pot',
      incoming.figures.some((f) => /you/i.test(f.label))
      && incoming.figures.some((f) => /them/i.test(f.label))
      && incoming.figures.some((f) => /pot/i.test(f.label)),
      incoming.figures.map((f) => f.label).join(','));
    check('every money figure carries the served exact cents',
      incoming.figures.every((f) => f.cents !== undefined && f.cents !== ''),
      JSON.stringify(incoming.figures));
    check('it says in words what is being asked of this GM',
      /sent you a .* Matchup\.$/.test(incoming.copy.trim()), incoming.copy);

    const controls = await evaluate(`
      const zone = [...document.querySelectorAll('#panel-action .fs-railsec')][0];
      const card = zone.querySelector('.fs-wcard');
      card.click();
      return new Promise((resolve) => setTimeout(() => {
        const sheet = document.getElementById('fs-sheet');
        const buttons = sheet
          ? [...sheet.querySelectorAll('[data-respond]')] : [];
        resolve({
          opened: Boolean(sheet),
          controls: buttons.map((b) => b.dataset.respond),
          challengeIds: [...new Set(buttons.map((b) => b.dataset.challengeId))],
          minHeight: buttons.length
            ? Math.min(...buttons.map((b) => Math.round(
                b.getBoundingClientRect().height))) : null,
          words: buttons.map((b) => b.textContent.trim()),
        });
      }, 700));
    `);
    check('opening it offers the governed responses',
      controls.controls.includes('accept') && controls.controls.includes('decline')
      && controls.controls.includes('counter'),
      controls.controls.join(','));
    check('each control names the challenge it would act on',
      controls.challengeIds.length === 1 && /^\d+$/.test(controls.challengeIds[0]),
      controls.challengeIds.join(','));
    check('the controls clear the governed touch floor',
      controls.minHeight !== null && controls.minHeight >= TOUCH_FLOOR,
      `${controls.minHeight}px`);

    await evaluate(`
      const close = document.querySelector('#fs-sheet [data-fs-close]');
      if (close) close.click();
      1;
    `);
    await wait(600);

    section('§7 · WAITING says who is being waited on, and offers nothing');

    const outgoing = waiting.cards[0];
    check('it names the opponent', /vs \S/.test(outgoing.identity),
      outgoing.identity);
    check('it names the market, terms and week',
      /FIXED|FLOATING/.test(outgoing.context) && /WK \d+/.test(outgoing.context),
      outgoing.context);
    check('it shows the stake', outgoing.figures.some(
      (f) => /you/i.test(f.label) && /\d/.test(f.value)),
      JSON.stringify(outgoing.figures));
    check('it says it is waiting on the opponent',
      /^Waiting for .* to respond\.$/.test(outgoing.copy.trim()), outgoing.copy);

    const noControls = await evaluate(`
      const zone = [...document.querySelectorAll('#panel-action .fs-railsec')][1];
      zone.querySelector('.fs-wcard').click();
      return new Promise((resolve) => setTimeout(() => {
        const sheet = document.getElementById('fs-sheet');
        resolve({
          controls: sheet
            ? [...sheet.querySelectorAll('[data-respond]')].map((b) => b.dataset.respond)
            : null,
          note: sheet && sheet.querySelector('[data-respond-state]')
            ? sheet.querySelector('[data-respond-state]').textContent.trim() : null,
        });
      }, 700));
    `);
    check('a wager this GM cannot answer offers no response control',
      Array.isArray(noControls.controls) && noControls.controls.length === 0,
      JSON.stringify(noControls.controls));
    check('and says why instead', Boolean(noControls.note), noControls.note);

    await evaluate(`
      const close = document.querySelector('#fs-sheet [data-fs-close]');
      if (close) close.click();
      1;
    `);
    await wait(600);

    section('§8 · LIVE reports the accepted wager without inventing a score');

    const liveCard = live.cards[0];
    check('it names the opponent', /vs \S/.test(liveCard.identity),
      liveCard.identity);
    check('it reports the accepted state', /ACCEPTED|LIVE/i.test(liveCard.badge),
      liveCard.badge);
    check('it says the Matchup is live in words',
      /live/i.test(liveCard.copy), liveCard.copy);
    check('it carries a real stake', liveCard.figures.some(
      (f) => /you/i.test(f.label) && Number(f.cents) > 0),
      JSON.stringify(liveCard.figures));
    check('it reports no settled outcome while unsettled',
      !liveCard.figures.some((f) => /net/i.test(f.label)),
      liveCard.figures.map((f) => f.label).join(','));

    section('§9 · COMPLETED reports the result and the credits');

    const OUTCOMES = ['WON', 'LOST', 'PUSH', 'VOID', 'SETTLED'];
    check('every completed card carries a settled outcome word',
      completed.cards.every((c) => OUTCOMES.includes(c.badge.trim())),
      [...new Set(completed.cards.map((c) => c.badge.trim()))].join(','));
    check('every completed card reports the credits it moved',
      completed.cards.every((c) => c.figures.some((f) => /net/i.test(f.label))),
      'Net present on all');
    check('the credit figure carries the served exact cents',
      completed.cards.every((c) => c.figures
        .filter((f) => /net/i.test(f.label))
        .every((f) => f.cents !== undefined && f.cents !== '')),
      'exact cents present');
    check('every completed card names its week',
      completed.cards.every((c) => /WK \d+/.test(c.context)),
      completed.cards.map((c) => c.context.match(/WK \d+/)).join(','));

    /* ══════════════════════════════════════════════════════════════════════
     * §10 · PARALLEL CONSTRUCTION — one object, four states
     * ════════════════════════════════════════════════════════════════════ */

    section('§10 · a card is the same object on every rail');

    const everyCard = m.zones.flatMap((z) => z.cards).filter(Boolean);
    check('every rail drew at least one card to compare',
      m.zones.every((z) => z.cards.filter(Boolean).length > 0),
      m.zones.map((z) => z.n).join(','));

    const first = everyCard[0];
    check('every card is the same shell',
      everyCard.every((c) => c.cls.includes('fs-wcard--lifecycle')),
      [...new Set(everyCard.map((c) => c.cls.replace(/is-\w+/g, '').trim()))].join(' | '));
    check('every card is the same width',
      everyCard.every((c) => near(c.w, first.w)),
      [...new Set(everyCard.map((c) => c.w))].join(','));
    check('every card has the same padding',
      everyCard.every((c) => c.pad === first.pad),
      [...new Set(everyCard.map((c) => c.pad))].join(' | '));
    check('every card has the same corner radius',
      everyCard.every((c) => c.radius === first.radius),
      [...new Set(everyCard.map((c) => c.radius))].join(' | '));
    check('the heading row sits in the same place on every card',
      everyCard.every((c) => c.headBox && near(c.headBox.top, first.headBox.top)
        && near(c.headBox.left, first.headBox.left)),
      [...new Set(everyCard.map((c) => c.headBox && c.headBox.top))].join(','));
    check('the opponent is set in one typography everywhere',
      new Set(everyCard.map((c) => c.identitySize)).size === 1,
      [...new Set(everyCard.map((c) => c.identitySize))].join(' | '));
    check('the figure row sits at the same left edge on every card',
      everyCard.every((c) => c.figBox && near(c.figBox.left, first.figBox.left)),
      [...new Set(everyCard.map((c) => c.figBox && c.figBox.left))].join(','));
    check('the footer sits at the same left edge on every card',
      everyCard.every((c) => c.footBox && near(c.footBox.left, first.footBox.left)),
      [...new Set(everyCard.map((c) => c.footBox && c.footBox.left))].join(','));
    check('no card clips its own content',
      everyCard.every((c) => !c.clipped),
      everyCard.filter((c) => c.clipped).length + ' clipped');

    section('§10 · the rails themselves agree');

    check('every rail is the same width',
      m.zones.every((z) => near(z.railW, m.zones[0].railW)),
      m.zones.map((z) => z.railW).join(' / '));
    check('every rail shares one left edge',
      m.zones.every((z) => near(z.railL, m.zones[0].railL)),
      m.zones.map((z) => z.railL).join(' / '));
    check('every heading-to-rail gap is the same',
      m.zones.every((z) => near(z.gap, m.zones[0].gap)),
      m.zones.map((z) => z.gap).join(' / '));
    check('every rail heading shares one typography',
      new Set(m.zones.map((z) => `${z.headSize}/${z.headWeight}/${z.headTrack}`)).size === 1,
      m.zones.map((z) => z.headSize).join(' / '));
    check('no rail heading wraps',
      m.zones.every((z) => z.headWrapped === false),
      m.zones.map((z) => `${z.heading}:${z.headWrapped}`).join(' '));

    section('§11 · each state carries its own treatment, from one palette');

    const accents = m.zones.map((z) => {
      const c = z.cards.find(Boolean);
      return (c.cls.match(/is-(action|waiting|live|done)\b/) || [])[1] || null;
    });
    check('the four rails draw four distinct state accents',
      new Set(accents).size === 4, accents.join(' / '));
    check('and each accent is one the shell already governs',
      accents.every((a) => ['action', 'waiting', 'live', 'done'].includes(a)),
      accents.join(' / '));

    /* ══════════════════════════════════════════════════════════════════════
     * §12 / §16 · THE APP-SHELL VIEWPORT POR
     * ════════════════════════════════════════════════════════════════════ */

    for (const vp of VIEWPORTS) {
      section(`§16 · ${vp.width}x${vp.height} — ${vp.label}`);
      await setViewport(vp.width, vp.height);
      await ENTER({ evaluate });
      m = await evaluate(READ_STATUS);

      check('Status is actually laid out at this size',
        m.zones.length === 4 && m.zones.every((z) => z.railW > 0),
        m.zones.map((z) => z.railW).join(' / '));
      check('the document does not scroll sideways',
        m.docSW <= m.docCW + 1, `${m.docSW} vs ${m.docCW}`);
      check('the tab does not scroll sideways',
        m.panelSW <= m.panelCW + 1, `${m.panelSW} vs ${m.panelCW}`);
      check('the tab does not overflow its own box vertically',
        m.panelVOverflow <= 1, `${m.panelVOverflow}`);
      check('the bottom navigation stays visible and hit-testable',
        Boolean(m.nav && m.nav.onScreen && m.nav.reachable),
        JSON.stringify(m.nav));
      check('every rail contains its own overflow',
        m.zones.every((z) => /auto|scroll/.test(String(z.railOverflowX))
          && z.railVOverflow <= 1),
        m.zones.map((z) => `${z.railOverflowX}:${z.railVOverflow}`).join(' '));
      check('no rail heading wraps at this size',
        m.zones.every((z) => z.headWrapped === false),
        m.zones.map((z) => z.headWrapped).join(','));

      const cards = m.zones.flatMap((z) => z.cards).filter(Boolean);
      check('no card clips its own content at this size',
        cards.every((c) => !c.clipped),
        `${cards.filter((c) => c.clipped).length} clipped of ${cards.length}`);
      check('no state card is wider than its peers at this size',
        new Set(cards.map((c) => Math.round(c.w))).size === 1,
        [...new Set(cards.map((c) => Math.round(c.w)))].join(','));
      check('no card widens its rail at this size',
        m.zones.every((z) => near(z.railW, m.zones[0].railW)),
        m.zones.map((z) => z.railW).join(' / '));
    }
  });

finish();
