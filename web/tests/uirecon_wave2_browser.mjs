/* ============================================================================
 * FantasyStakes — UIRECON Wave 2 · shell, Standings, Play, Account · browser
 *
 * Run directly:   node web/tests/uirecon_wave2_browser.mjs
 * Or through:     python test_uirecon_wave2.py
 *
 * WAVE 2 RECONCILED FOUR SURFACES against the locked marketing POR, and every
 * one of them is a parallel-construction claim rather than a styling one:
 *
 *   THE HEADER    one account cluster — DEMO badge, account control, gear —
 *                 with Sign Out moved out of the chrome and into the sheet the
 *                 account control opens, and a wordmark that is finally the
 *                 loudest thing in the masthead.
 *
 *   STANDINGS     the championship explanation demoted from a gold callout to
 *                 supporting body text under CHAMPIONSHIP CHASE · WEEK n.
 *
 *   PLAY          Net Winnings means net winnings — no rank, no standings
 *                 position, no context of any kind in that cell — and the two
 *                 section titles sit the same distance from their content.
 *
 *   ACCOUNT       Current Settle is section 4, built by the same
 *                 `ledgerSection()` as the three sections that explain into it.
 *
 * WHAT IS MEASURED RATHER THAN ASSUMED. Whether four sections are really one
 * construction is a question about rendered header heights, number treatments
 * and toggle affordances — not about whether one function was called. Whether
 * two section gaps are identical is a question about two rectangles. Both are
 * browser questions, and both are asked here as comparisons BETWEEN peers so
 * the assertion pins the rule rather than this build's pixel values.
 *
 * AND THE WAVE 1 APP-SHELL POR STILL HOLDS. Wave 2 grows the wordmark, which
 * costs masthead height, and that height comes off the panel. The shell clauses
 * are re-asserted at the end of every viewport for exactly that reason.
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

const near = (a, b, tol = 1) => Math.abs(a - b) <= tol;

const READY = `
  return new Promise((resolve) => {
    const deadline = Date.now() + 8000;
    const poll = () => {
      const mounted = document.querySelector('.fs-tabbar__item')
        && document.querySelector('#panel-league .fs-strip__cell');
      if (mounted || Date.now() > deadline) return resolve(Boolean(mounted));
      setTimeout(poll, 100);
    };
    poll();
  });
`;

await withPage({ port: 9441 }, async ({ evaluate, setViewport }) => {
  for (const vp of VIEWPORTS) {
    await setViewport(vp.width, vp.height);
    const at = `${vp.width}x${vp.height}`;
    check(`the application mounted — ${at}`, await evaluate(READY) === true);

    /* ── 1 · The header account cluster ──────────────────────────────────── */

    section(`Header account cluster — ${at} (${vp.label})`);

    const head = await evaluate(`
      const hit = (a, b) => !(a.right <= b.left + 1 || b.right <= a.left + 1
        || a.bottom <= b.top + 1 || b.bottom <= a.top + 1);
      const cluster = document.querySelector('.fs-mast__cluster');
      const chip = document.querySelector('.fs-mast__cluster > .fs-source');
      const acct = document.getElementById('fs-account');
      const gear = document.getElementById('fs-gear');
      const word = document.querySelector('.fs-mast__word');
      const r = (el) => {
        const b = el.getBoundingClientRect();
        return { l: Math.round(b.left), r: Math.round(b.right),
                 t: Math.round(b.top), b: Math.round(b.bottom),
                 w: Math.round(b.width), h: Math.round(b.height) };
      };
      return {
        clusterPresent: Boolean(cluster),
        // THE ORDER IS THE POR'S: chip, then account, then gear. Asserted from
        // the DOM rather than from geometry, because that is what a screen
        // reader and the tab order follow.
        order: cluster
          ? [...cluster.querySelectorAll('.fs-source, #fs-account, #fs-gear')]
            .map((el) => el.id || el.className.split(' ')[0])
          : [],
        chip: chip ? r(chip) : null,
        acct: acct ? r(acct) : null,
        gear: gear ? r(gear) : null,
        // No hit area may sit on top of another's.
        overlapChipGear: (chip && gear) ? hit(chip.getBoundingClientRect(),
          gear.getBoundingClientRect()) : null,
        overlapAcctGear: (acct && gear) ? hit(acct.getBoundingClientRect(),
          gear.getBoundingClientRect()) : null,
        overlapChipAcct: (chip && acct) ? hit(chip.getBoundingClientRect(),
          acct.getBoundingClientRect()) : null,
        // The account control names the acting GM, and the name is the primary
        // text of the cluster.
        who: acct ? (acct.querySelector('.fs-ident__who') || {}).textContent : null,
        whoColor: acct ? getComputedStyle(
          acct.querySelector('.fs-ident__who')).color : null,
        whoWeight: acct ? getComputedStyle(
          acct.querySelector('.fs-ident__who')).fontWeight : null,
        acctLabel: acct ? acct.getAttribute('aria-label') : null,
        acctPopup: acct ? acct.getAttribute('aria-haspopup') : null,
        gearLabel: gear ? gear.getAttribute('aria-label') : null,
        // The persistent Sign Out must be gone from the chrome entirely.
        signOutInChrome: Boolean(document.querySelector('.fs-mast #fs-signout')),
        legacyIdentRow: Boolean(document.querySelector('.fs-ident__out')),
        // The wordmark: bigger than every other type in the shell, and whole.
        wordSize: Math.round(parseFloat(getComputedStyle(word).fontSize)),
        wordClips: word.scrollWidth > word.clientWidth + 1,
        wordLines: Math.round(word.getBoundingClientRect().height
          / parseFloat(getComputedStyle(word).fontSize)),
        tabTitleSize: (() => {
          const t = document.querySelector('.fs-tabhead__title');
          return t ? Math.round(parseFloat(getComputedStyle(t).fontSize)) : null;
        })(),
        mast: Math.round(
          document.querySelector('.fs-mast').getBoundingClientRect().height),
      };
    `);

    check(`the account cluster is one group — ${at}`, head.clusterPresent === true);
    check(`in the locked order: chip, account, gear — ${at}`,
      head.order.join(' > ') === 'fs-source > fs-account > fs-gear',
      head.order.join(' > '));
    check(`the account control names the acting GM — ${at}`,
      typeof head.who === 'string' && head.who.trim().length > 0, head.who);
    check(`the name is the cluster's primary text — ${at}`,
      Number(head.whoWeight) >= 600, `${head.whoColor} ${head.whoWeight}`);
    check(`the account control announces that it opens something — ${at}`,
      head.acctPopup === 'dialog' && /account/i.test(head.acctLabel || ''),
      `${head.acctPopup} · ${head.acctLabel}`);
    check(`the gear means Settings — ${at}`, head.gearLabel === 'Settings',
      String(head.gearLabel));
    check(`no persistent Sign Out survives in the chrome — ${at}`,
      head.signOutInChrome === false && head.legacyIdentRow === false);
    check(`no two cluster controls overlap — ${at}`,
      head.overlapChipGear === false && head.overlapAcctGear === false
      && head.overlapChipAcct === false,
      `chip/gear ${head.overlapChipGear} acct/gear ${head.overlapAcctGear}`);
    check(`the gear keeps its 44px target — ${at}`,
      head.gear.h >= 44 && head.gear.w >= 24, `${head.gear.w}x${head.gear.h}`);
    check(`the account control keeps a 44px target — ${at}`,
      head.acct.h >= 44, `${head.acct.h}`);
    // THE WORDMARK IS THE LOUDEST TYPE IN THE SHELL. Asserted against the tab
    // title rather than against a number, so the claim survives a later change
    // to either scale.
    //
    // 320px IS A MEASURED EXCEPTION, AND IT IS STATED RATHER THAN SKIPPED. The
    // lockup there is 135px — what is left after the masthead's gutter, its
    // gap, and a meta column capped at the width the provider chip needs to
    // render untruncated. `FantasyStakes` needs 131px at 20px and 138px at
    // 21px, so 20px is the largest size that fits whole, and the page title's
    // floor is 22px under Rev 4.3 §5.1. The inversion is therefore a property
    // of the width, not of this wave: it existed before at 18px against the
    // same 23px title, and Wave 2 narrows it. What is asserted at 320 is that
    // the brand is bigger than it was and still whole.
    if (vp.width >= 375) {
      check(`the wordmark outranks the page title — ${at}`,
        head.wordSize >= head.tabTitleSize,
        `word ${head.wordSize} vs title ${head.tabTitleSize}`);
    } else {
      check(`the wordmark is at its largest whole-fitting size — ${at}`,
        head.wordSize >= 20 && head.wordClips === false,
        `word ${head.wordSize} (pre-Wave-2 was 18)`);
    }
    check(`and it is whole and on one line — ${at}`,
      head.wordClips === false && head.wordLines <= 1,
      `clips ${head.wordClips}, ${head.wordLines} line(s)`);
    check(`the masthead stays within its certified ceiling — ${at}`,
      head.mast <= (vp.width <= 320 ? 90 : 80), `${head.mast}px`);

    /* ── 2 · The account sheet holds Sign Out ────────────────────────────── */

    const sheet = await evaluate(`
      document.getElementById('fs-account').click();
      const host = document.getElementById('fs-sheet');
      const out = {
        opened: Boolean(host && host.querySelector('#fs-signout')),
        title: host ? (host.querySelector('.fs-sheet__title') || {}).textContent : null,
        // The account sheet must not become a second door to Settings.
        duplicatesSettings: host
          ? /rules|league settings|commissioner controls|economy configuration/i
            .test(host.textContent) : null,
        signOutHeight: (() => {
          const b = host && host.querySelector('#fs-signout');
          return b ? Math.round(b.getBoundingClientRect().height) : null;
        })(),
      };
      const close = document.querySelector('#fs-overlay [data-fs-close]');
      if (close) close.click();
      return out;
    `);

    check(`the account control opens a sheet holding Sign out — ${at}`,
      sheet.opened === true);
    check(`the sheet is the Account sheet — ${at}`, sheet.title === 'Account',
      String(sheet.title));
    check(`it does not duplicate Settings — ${at}`,
      sheet.duplicatesSettings === false);
    check(`Sign out is a full target inside it — ${at}`,
      sheet.signOutHeight >= 44, String(sheet.signOutHeight));

    /* ── 3 · Standings: supporting text, not a peer card ─────────────────── */

    section(`Standings hierarchy — ${at}`);

    const st = await evaluate(`
      { const t = document.querySelector('.fs-tabbar__item[data-destination="standings"]');
        if (t) t.click(); }
      const panel = document.getElementById('panel-standings');
      const sub = panel.querySelector('.fs-tabhead__sub');
      const ex = panel.querySelector('.fs-st__explainer');
      const firstTable = panel.querySelector('.fs-st');
      const es = getComputedStyle(ex);
      const head = panel.querySelector('.fs-tabhead');
      return {
        subText: sub ? sub.textContent.trim() : null,
        exText: ex ? ex.textContent.trim() : null,
        // A CARD HAS A GROUND, AN EDGE AND A RADIUS. Body text has none.
        bg: es.backgroundColor,
        border: es.borderLeftWidth + '/' + es.borderTopWidth,
        radius: es.borderTopLeftRadius,
        padding: es.paddingTop + '/' + es.paddingLeft,
        colour: es.color,
        // It hangs off the same margin as the heading it supports.
        exLeft: ex ? Math.round(ex.getBoundingClientRect().left) : null,
        headLeft: head ? Math.round(head.getBoundingClientRect().left
          + parseFloat(getComputedStyle(head).paddingLeft)) : null,
        // Order: subheading, then explainer, then standings.
        orderOk: Boolean(sub && ex && firstTable)
          && sub.getBoundingClientRect().bottom <= ex.getBoundingClientRect().top + 1
          && ex.getBoundingClientRect().bottom <= firstTable.getBoundingClientRect().top + 1,
        tableHeadings: [...panel.querySelectorAll('.fs-st__heading')]
          .map((h) => h.textContent),
        title: (panel.querySelector('.fs-tabhead__title') || {}).textContent,
      };
    `);

    check(`the subheading is CHAMPIONSHIP CHASE with the week — ${at}`,
      /^CHAMPIONSHIP CHASE/.test(st.subText || '')
      && /Week \d+/.test(st.subText || ''), String(st.subText));
    /* FINAL POR UI-2 §26 renamed the concept. The claim is unchanged — the
     * explanation is KEPT, it is body text, and it sits above the tables — but
     * `Championship Score` became `FantasyStakes Score`, because §8 gave the
     * figure a third term and §26 states the identity in the reader's own
     * column names. Both spellings are admissible so a legacy surface still
     * satisfies it; what is asserted is that the explanation is there. */
    check(`the championship explanation is kept — ${at}`,
      /FantasyStakes Score/.test(st.exText || '')
      || /Championship Score/.test(st.exText || ''),
      (st.exText || '').slice(0, 60));
    check(`  · and it states the scoring identity — ${at}`,
      /Matchups \+ Prop Pools/.test(st.exText || ''),
      (st.exText || '').slice(0, 90));
    check(`it is body text, with no card ground — ${at}`,
      st.bg === 'rgba(0, 0, 0, 0)' || st.bg === 'transparent', st.bg);
    check(`no card edge and no radius — ${at}`,
      st.border === '0px/0px' && st.radius === '0px',
      `${st.border} r${st.radius}`);
    check(`and no card padding — ${at}`, st.padding === '0px/0px', st.padding);
    check(`it hangs off the same margin as its heading — ${at}`,
      near(st.exLeft, st.headLeft, 1), `${st.exLeft} vs ${st.headLeft}`);
    check(`the order is heading, supporting text, then standings — ${at}`,
      st.orderOk === true);
    check(`the championship is not named twice — ${at}`,
      !st.tableHeadings.includes(st.title),
      `${st.title} | ${st.tableHeadings.join(' | ')}`);

    /* ── 4 · Play: strip semantics and section spacing ───────────────────── */

    section(`Play strip and section spacing — ${at}`);

    const play = await evaluate(`
      { const t = document.querySelector('.fs-tabbar__item[data-destination="league"]');
        if (t) t.click(); }
      const panel = document.getElementById('panel-league');
      const cells = [...panel.querySelectorAll('.fs-strip__cell')].map((c) => {
        const l = c.querySelector('.fs-strip__label');
        const v = c.querySelector('.fs-strip__value');
        const cr = c.getBoundingClientRect();
        const lr = l.getBoundingClientRect();
        const vr = v.getBoundingClientRect();
        return {
          label: l.textContent,
          value: v.textContent,
          w: Math.round(cr.width * 10) / 10,
          labelLines: Math.round(lr.height / parseFloat(getComputedStyle(l).lineHeight)),
          labelDx: Math.round(((lr.left + lr.width / 2) - (cr.left + cr.width / 2)) * 10) / 10,
          valueDx: Math.round(((vr.left + vr.width / 2) - (cr.left + cr.width / 2)) * 10) / 10,
          // The context span is the exact mechanism a rank was drawn with.
          hasContext: Boolean(c.querySelector('.fs-strip__context')),
        };
      });
      const zones = [...panel.querySelectorAll('.fs-zone')].map((z) => {
        const h = z.querySelector('.fs-heading');
        const body = z.querySelector('.fs-carousel, .fs-pools, .fs-emptyzone');
        return {
          title: h ? h.querySelector('.fs-heading__text').textContent : null,
          gap: (h && body)
            ? Math.round((body.getBoundingClientRect().top
              - h.getBoundingClientRect().bottom) * 10) / 10 : null,
          titleSize: h ? getComputedStyle(h.querySelector('.fs-heading__text')).fontSize : null,
          titleWeight: h ? getComputedStyle(h.querySelector('.fs-heading__text')).fontWeight : null,
          titleColor: h ? getComputedStyle(h.querySelector('.fs-heading__text')).color : null,
          marginBottom: h ? getComputedStyle(h).marginBottom : null,
        };
      });
      return { cells, zones };
    `);

    const net = play.cells[0];

    check(`the Play strip is four cells — ${at}`, play.cells.length === 4);
    check(`the first cell is Net Winnings — ${at}`, /^Net/.test(net.label), net.label);
    // THE WHOLE OF WAVE 2'S PLAY SEMANTICS, IN ONE ASSERTION: the cell carries a
    // figure and nothing else. A rank was drawn through `.fs-strip__context`,
    // and a rank is what must never come back.
    check(`Net Winnings carries no context of any kind — ${at}`,
      net.hasContext === false && !/\d(st|nd|rd|th)\b/.test(net.value),
      `${net.label} = ${net.value}`);
    check(`no strip cell carries context — ${at}`,
      play.cells.every((c) => c.hasContext === false));
    check(`labels stay on one line — ${at}`,
      play.cells.every((c) => c.labelLines <= 1),
      play.cells.map((c) => `${c.label}:${c.labelLines}`).join(' '));
    check(`cells are equal width — ${at}`,
      play.cells.every((c) => near(c.w, play.cells[0].w)),
      play.cells.map((c) => c.w).join('/'));
    check(`labels and values are both centred — ${at}`,
      play.cells.every((c) => near(c.labelDx, 0) && near(c.valueDx, 0)));

    check(`Play has two titled sections — ${at}`, play.zones.length === 2,
      play.zones.map((z) => z.title).join(' | '));
    check(`they are Matchups and Prop Pools — ${at}`,
      /MATCHUPS/.test(play.zones[0].title) && /PROP POOLS/.test(play.zones[1].title),
      play.zones.map((z) => z.title).join(' | '));
    check(`both titles share one treatment — ${at}`,
      play.zones[0].titleSize === play.zones[1].titleSize
      && play.zones[0].titleWeight === play.zones[1].titleWeight
      && play.zones[0].titleColor === play.zones[1].titleColor,
      `${play.zones[0].titleSize}/${play.zones[0].titleWeight}`);
    check(`and one title-to-content gap — ${at}`,
      near(play.zones[0].gap, play.zones[1].gap),
      play.zones.map((z) => `${z.title}:${z.gap}`).join(' '));
    check(`the gap is real, not zero as it was pre-reconciliation — ${at}`,
      play.zones.every((z) => z.gap > 0),
      play.zones.map((z) => z.gap).join('/'));
    check(`and it comes from one declaration — ${at}`,
      play.zones[0].marginBottom === play.zones[1].marginBottom,
      `${play.zones[0].marginBottom} / ${play.zones[1].marginBottom}`);

    /* ── 5 · Account: four sections, one construction ────────────────────── */

    section(`Account sections 1–4 — ${at}`);

    const acct = await evaluate(`
      { const t = document.querySelector('.fs-tabbar__item[data-destination="ledger"]');
        if (t) t.click(); }
      const panel = document.getElementById('panel-ledger');
      const sections = [...panel.querySelectorAll('.fs-lsec')];
      const read = (s) => {
        const head = s.querySelector('[data-lsec-toggle]');
        const num = s.querySelector('.fs-lsec__num');
        const title = s.querySelector('.fs-lsec__title');
        const chev = s.querySelector('.fs-lsec__chev');
        const cs = getComputedStyle(s);
        const hs = getComputedStyle(head);
        const ts = getComputedStyle(title);
        const ns = getComputedStyle(num);
        return {
          number: num ? num.textContent.trim() : null,
          title: title ? title.textContent.trim() : null,
          headH: Math.round(head.getBoundingClientRect().height),
          headMinH: hs.minHeight,
          headPad: hs.paddingTop + '/' + hs.paddingBottom,
          // A long title legitimately wraps at a narrow width and makes its own
          // header taller. That is content, not construction, so the rendered
          // heights are compared only among headers whose titles occupy the
          // same number of lines — and the STRUCTURE (min-height, padding) is
          // compared across all four unconditionally.
          // Derived from the FONT SIZE, not from the computed line-height:
          // that resolves to "normal", which parses to NaN and made this read
          // null for every section. One line is anything under 1.8em.
          // (No backticks in this comment — it lives in a template literal.)
          titleLines: title.getBoundingClientRect().height
            < parseFloat(ts.fontSize) * 1.8 ? 1 : 2,
          titleSize: ts.fontSize, titleWeight: ts.fontWeight,
          numSize: ns.fontSize, numColor: ns.color,
          border: cs.borderTopWidth + ' ' + cs.borderTopStyle,
          radius: cs.borderTopLeftRadius,
          padding: cs.paddingTop,
          hasChevron: Boolean(chev),
          isDisclosure: s.hasAttribute('data-disclosure'),
          toggleIsButton: head.tagName === 'BUTTON',
          aria: head.getAttribute('aria-expanded'),
          open: s.classList.contains('is-open'),
          gapAbove: null,
        };
      };
      const out = sections.map(read);
      for (let i = 1; i < sections.length; i += 1) {
        out[i].gapAbove = Math.round(sections[i].getBoundingClientRect().top
          - sections[i - 1].getBoundingClientRect().bottom);
      }
      // The reconciliation itself must survive intact.
      const settle = document.getElementById('fs-current-settle');
      const rows = settle
        ? [...settle.querySelectorAll('.fs-settle__row')].map((r) => Number(
          r.querySelector('[data-exact-cents]').dataset.exactCents)) : [];
      const total = settle
        ? Number(settle.querySelector('.fs-settle__total').dataset.exactCents) : null;
      // Toggling section 4 must behave exactly like toggling section 1.
      //
      // FINAL POR UI-6 §30 — SECTION 4 NOW STARTS CLOSED like its three
      // siblings, so the round trip runs OPEN-then-CLOSE rather than
      // close-then-reopen. The affordance under test is identical; only the
      // state it starts from moved, and the snapshots are named for what they
      // actually capture rather than for the old starting state.
      const t4 = sections[3].querySelector('[data-lsec-toggle]');
      const snap = () => ({
        open: sections[3].classList.contains('is-open'),
        aria: t4.getAttribute('aria-expanded'),
        bodyH: Math.round(
          sections[3].querySelector('.fs-lsec__body').getBoundingClientRect().height),
      });
      t4.click();
      const afterOpen = snap();
      t4.click();
      const afterClose = snap();
      return { sections: out, rows, total, afterOpen, afterClose,
               settleInside: settle ? Boolean(settle.closest('.fs-lsec')) : null };
    `);

    const S = acct.sections;

    check(`Account has four sections — ${at}`, S.length === 4,
      S.map((s) => `${s.number}:${s.title}`).join(' | '));
    check(`they are numbered 1 to 4 in order — ${at}`,
      S.map((s) => s.number).join('') === '1234', S.map((s) => s.number).join(''));
    check(`section 4 is CURRENT SETTLE — ${at}`,
      S[3].title === 'CURRENT SETTLE', String(S[3].title));
    check(`Current Settle lives inside it — ${at}`, acct.settleInside === true);

    // PARALLEL CONSTRUCTION, MEASURED PROPERTY BY PROPERTY. Each of these is
    // one of the things the brief names: header height, number treatment, title
    // typography, expand/collapse affordance, border, spacing.
    check(`all four headers share one minimum height — ${at}`,
      S.every((s) => s.headMinH === S[0].headMinH), S.map((s) => s.headMinH).join(' '));
    check(`headers whose titles fit one line render identically — ${at}`,
      (() => {
        const oneLine = S.filter((s) => s.titleLines <= 1);
        return oneLine.length >= 2 && oneLine.every((s) => near(s.headH, oneLine[0].headH));
      })(),
      S.map((s) => `${s.number}:${s.headH}(${s.titleLines}L)`).join(' '));
    check(`all four header paddings are identical — ${at}`,
      S.every((s) => s.headPad === S[0].headPad), S.map((s) => s.headPad).join(' '));
    check(`all four title typographies are identical — ${at}`,
      S.every((s) => s.titleSize === S[0].titleSize
        && s.titleWeight === S[0].titleWeight),
      S.map((s) => `${s.titleSize}/${s.titleWeight}`).join(' '));
    check(`all four number treatments are identical — ${at}`,
      S.every((s) => s.numSize === S[0].numSize && s.numColor === S[0].numColor),
      S.map((s) => s.numSize).join(' '));
    check(`all four borders are identical — ${at}`,
      S.every((s) => s.border === S[0].border && s.radius === S[0].radius),
      S.map((s) => `${s.border} r${s.radius}`).join(' | '));
    check(`all four paddings are identical — ${at}`,
      S.every((s) => s.padding === S[0].padding), S.map((s) => s.padding).join(' '));
    check(`the spacing between sections is one value — ${at}`,
      S.slice(1).every((s) => near(s.gapAbove, S[1].gapAbove)),
      S.slice(1).map((s) => s.gapAbove).join('/'));
    check(`all four carry a chevron and a real toggle button — ${at}`,
      S.every((s) => s.hasChevron && s.toggleIsButton && s.isDisclosure));

    /* ── FINAL POR UI-6 §30 — ALL FOUR ACCOUNT CARDS START CLOSED ─────────
     *
     * §14.2 used to except section 4 so Current Settle needed no tap, and this
     * block asserted that exception. §30 removed it: the four cards are one
     * set and open the same way, because a single card that behaves
     * differently from its three identical-looking siblings reads as a bug
     * rather than as an affordance.
     *
     * THE CLAIM THAT MATTERS IS UNCHANGED AND IS STILL ASSERTED: the four are
     * real disclosures, they start in a known state, and each one opens and
     * closes. Only the expected starting state moved, and it moved for all
     * four together. That is why the disclosure round-trip below is now run on
     * section 4 from CLOSED rather than from open — the same affordance,
     * exercised from the state it actually starts in.
     *
     * This assertion was left behind by the run that implemented §30 and is
     * replaced here rather than relaxed. */
    check(`all four sections start collapsed — ${at}`,
      S.every((s) => s.open === false && s.aria === 'false'),
      S.map((s) => s.aria).join(' '));
    check(`section 4 opens like any other section — ${at}`,
      acct.afterOpen.open === true && acct.afterOpen.aria === 'true'
      && acct.afterOpen.bodyH > 0,
      JSON.stringify(acct.afterOpen));
    check(`and collapses again — ${at}`,
      acct.afterClose.open === false && acct.afterClose.aria === 'false'
      && acct.afterClose.bodyH === 0,
      JSON.stringify(acct.afterClose));

    check(`the reconciliation still shows its three inputs — ${at}`,
      acct.rows.length === 3, String(acct.rows.length));
    check(`and they still sum to the drawn total — ${at}`,
      acct.rows.reduce((s, n) => s + n, 0) === acct.total,
      `${acct.rows.join(' + ')} = ${acct.total}`);

    /* ── 6 · The Wave 1 app-shell POR still holds ────────────────────────── */

    section(`App-shell POR after Wave 2 — ${at}`);

    const shell = await evaluate(`
      const PANELS = ['standings', 'league', 'action', 'week', 'ledger'];
      const doc = document.documentElement;
      const bar = document.querySelector('.fs-tabbar');
      const br = bar.getBoundingClientRect();
      const unreachable = [];
      for (const item of bar.querySelectorAll('.fs-tabbar__item')) {
        const r = item.getBoundingClientRect();
        const el = document.elementFromPoint(
          Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2));
        if (!el || !bar.contains(el)) unreachable.push(item.dataset.destination);
      }
      const panels = [];
      for (const id of PANELS) {
        { const t = document.querySelector(
            '.fs-tabbar__item[data-destination="' + id + '"]');
          if (t) t.click(); }
        const p = document.getElementById('panel-' + id);
        panels.push({
          id,
          h: p.scrollWidth - p.clientWidth,
          v: p.scrollHeight - p.clientHeight,
          clearsNav: p.getBoundingClientRect().bottom <= br.top + 1,
        });
      }
      return {
        docH: doc.scrollWidth - doc.clientWidth,
        navVisible: br.height > 0 && br.top >= -1
          && br.bottom <= window.innerHeight + 1,
        unreachable, panels,
      };
    `);

    check(`the document never scrolls sideways — ${at}`, shell.docH <= 0,
      String(shell.docH));
    check(`the bottom navigation stays in the viewport — ${at}`,
      shell.navVisible === true);
    check(`every tab is still hit-testable — ${at}`,
      shell.unreachable.length === 0, shell.unreachable.join(',') || 'all five');
    check(`no tab scrolls horizontally — ${at}`,
      shell.panels.every((p) => p.h <= 1),
      shell.panels.map((p) => `${p.id}:${p.h}`).join(' '));
    check(`no tab overflows vertically — ${at}`,
      shell.panels.every((p) => p.v <= 1),
      shell.panels.map((p) => `${p.id}:${p.v}`).join(' '));
    check(`every tab clears the bottom navigation — ${at}`,
      shell.panels.every((p) => p.clearsNav));
  }
});

finish();
