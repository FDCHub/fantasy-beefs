/* ============================================================================
 * FantasyStakes — Sprint 7 Package 2 · League and Action layout tests
 *
 * Run directly:   node web/tests/e2e_package2.mjs
 * Or through:     python test_s7_p2_league_action.py
 *
 * Measured geometry and real interaction in headless Chrome at 390×844. The
 * questions this suite answers cannot be answered from source: does one
 * matchup card actually fill the carousel, do both tap paths reach the same
 * composer, does closing the preview give the composer back with the stake
 * still in it, and does anything overflow the phone.
 * ========================================================================== */

import { VIEWPORT, createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

await withPage({ port: 9335 }, async ({ evaluate }) => {
  const goLeague = `document.querySelector('.fs-tabbar__item[data-destination="league"]').click();`;
  const goAction = `document.querySelector('.fs-tabbar__item[data-destination="action"]').click();`;

  /* ── League renders ───────────────────────────────────────────────────── */

  section('League renders at the phone viewport');

  await evaluate(`${goLeague} return true;`);

  check('the locked Bets heading renders', await evaluate(`
    return [...document.querySelectorAll('#panel-league .fs-heading__text')]
      .some(el => el.textContent === 'FANTASYSTAKES BETS · 11 OPPONENTS · SWIPE ↕');
  `));
  check('the locked Pools heading renders', await evaluate(`
    return [...document.querySelectorAll('#panel-league .fs-heading__text')]
      .some(el => el.textContent === 'FANTASYSTAKES POOLS · 4 THIS WEEK');
  `));
  check('the league identity renders', await evaluate(`
    return document.querySelector('#panel-league .fs-tabhead__title').textContent
      === 'CULV APPRECIATION SOCIETY';
  `));
  check('the week context renders', await evaluate(`
    return document.querySelector('#panel-league .fs-tabhead__sub').textContent
      === 'Week 5 · Regular Season';
  `));

  const overflow = await evaluate(`
    return {
      doc: document.documentElement.scrollWidth,
      inner: window.innerWidth,
      widest: Math.max(...[...document.querySelectorAll('#panel-league *')]
        .map(el => Math.round(el.getBoundingClientRect().right))),
    };
  `);
  check('League does not scroll the page horizontally',
    overflow.doc <= overflow.inner, `${overflow.doc}px vs ${overflow.inner}px`);
  check('no League element extends past the viewport',
    overflow.widest <= VIEWPORT.width, `widest right edge ${overflow.widest}px`);

  /* ── The vertical carousel ────────────────────────────────────────────── */

  section('FantasyStakes Bets is a vertical carousel, one card at a time');

  const carousel = await evaluate(`
    const rail = document.getElementById('fs-bets-carousel');
    const style = getComputedStyle(rail);
    const items = [...rail.querySelectorAll('.fs-carousel__item')];
    const box = rail.getBoundingClientRect();
    const first = items[0].getBoundingClientRect();
    const second = items[1].getBoundingClientRect();
    const fullyVisible = items.filter(el => {
      const r = el.getBoundingClientRect();
      return r.top >= box.top - 1 && r.bottom <= box.bottom + 1;
    }).length;
    return {
      count: items.length,
      snapType: style.scrollSnapType,
      overflowY: style.overflowY,
      overflowX: style.overflowX,
      railHeight: Math.round(box.height),
      itemHeight: Math.round(first.height),
      fullyVisible,
      secondIsBelow: second.top >= first.bottom - 1,
      canScroll: rail.scrollHeight > rail.clientHeight,
    };
  `);

  check('eleven matchup cards', carousel.count === 11, String(carousel.count));
  check('the carousel snaps vertically', /y mandatory/.test(carousel.snapType), carousel.snapType);
  check('the carousel scrolls vertically', carousel.overflowY === 'auto');
  check('the carousel does not scroll horizontally', carousel.overflowX === 'hidden');
  check('cards are stacked, not side by side', carousel.secondIsBelow === true);
  check('one card fills the carousel viewport',
    Math.abs(carousel.itemHeight - carousel.railHeight) <= 2,
    `card ${carousel.itemHeight}px in a ${carousel.railHeight}px rail`);
  check('exactly one card is fully presented at a time',
    carousel.fullyVisible === 1, `${carousel.fullyVisible} fully visible`);
  check('the remaining opponents are reachable by scrolling', carousel.canScroll === true);

  const scrolled = await evaluate(`
    const rail = document.getElementById('fs-bets-carousel');
    rail.scrollTop = rail.clientHeight;
    const box = rail.getBoundingClientRect();
    const items = [...rail.querySelectorAll('.fs-carousel__item')];
    const visible = items.filter(el => {
      const r = el.getBoundingClientRect();
      return r.top >= box.top - 1 && r.bottom <= box.bottom + 1;
    });
    const idx = items.indexOf(visible[0]);
    rail.scrollTop = 0;
    return { count: visible.length, idx };
  `);
  check('scrolling advances to the next single card',
    scrolled.count === 1 && scrolled.idx === 1, `card index ${scrolled.idx}`);

  const cardContent = await evaluate(`
    const card = document.querySelector('#fs-bets-carousel .fs-wcard');
    return {
      identity: card.querySelector('.fs-wcard__identity').textContent,
      context: card.querySelector('.fs-wcard__context').textContent,
      markets: [...card.querySelectorAll('.fs-market')].map(el =>
        el.querySelector('.fs-market__label').textContent + ' ' +
        el.querySelector('.fs-market__value').textContent),
      figures: [...card.querySelectorAll('.fs-wcard__figure')].map(el => el.textContent),
      copy: card.querySelector('.fs-wcard__copy').textContent,
      foot: card.querySelector('.fs-wcard__footvalue').textContent,
      clipped: card.scrollHeight > card.clientHeight + 1,
    };
  `);
  check('the card names both teams', /Your Team vs CULV Destroyers/.test(cardContent.identity));
  check('the card carries records and ranks', /7–0/.test(cardContent.context));
  check('the card carries ML, SPR and O/U',
    cardContent.markets.length === 3 && cardContent.markets[0].startsWith('ML'),
    cardContent.markets.join(' | '));
  check('the card carries the projected score',
    cardContent.figures.some((f) => /Projected/.test(f)), cardContent.figures.join(' | '));
  check('the card carries a line of analysis', cardContent.copy.length > 10);
  check('the card carries a challenge affordance', /Challenge/.test(cardContent.foot));
  check('the card does not clip its own content', cardContent.clipped === false);

  /* ── Both tap paths reach one composer ────────────────────────────────── */

  section('Card tap and market tap reach the same composer');

  const wholeCard = await evaluate(`
    document.querySelector('#fs-bets-carousel .fs-wcard').click();
    const sheet = document.getElementById('fs-sheet');
    return {
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      title: sheet.querySelector('.fs-sheet__title').textContent,
      selected: [...sheet.querySelectorAll('[data-composer-market]')]
        .filter(el => el.getAttribute('aria-pressed') === 'true').length,
      stake: sheet.querySelector('[data-composer-stake]').value,
      sendDisabled: sheet.querySelector('[data-composer-send]').disabled,
    };
  `);
  check('a whole-card tap opens the composer', wholeCard.open === true);
  check('it names the opponent', /CULV Destroyers/.test(wholeCard.title), wholeCard.title);
  check('no market is selected on a whole-card tap',
    wholeCard.selected === 0, `${wholeCard.selected} selected`);
  check('the composer opens at $0', wholeCard.stake === '0', wholeCard.stake);
  check('send opens disabled', wholeCard.sendDisabled === true);

  const noIntermediate = await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    return {
      hasSelector: Boolean(sheet.querySelector('[data-composer-market]')),
      hasStake: Boolean(sheet.querySelector('[data-composer-stake]')),
      hasSend: Boolean(sheet.querySelector('[data-composer-send]')),
    };
  `);
  check('the same sheet holds the market selector, the stake and send — no ' +
    'intermediate market-selection sheet',
    noIntermediate.hasSelector && noIntermediate.hasStake && noIntermediate.hasSend);

  await evaluate(`document.querySelector('#fs-sheet [data-fs-close]').click(); return true;`);

  const marketTap = await evaluate(`
    const card = document.querySelector('#fs-bets-carousel .fs-wcard');
    card.querySelector('[data-market="spread"]').click();
    const sheet = document.getElementById('fs-sheet');
    const pressed = [...sheet.querySelectorAll('[data-composer-market]')]
      .filter(el => el.getAttribute('aria-pressed') === 'true');
    return {
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      selectedCount: pressed.length,
      selected: pressed.length ? pressed[0].dataset.composerMarket : null,
      stake: sheet.querySelector('[data-composer-stake]').value,
      sheets: document.querySelectorAll('#fs-sheet').length,
    };
  `);
  check('a market tap opens the composer', marketTap.open === true);
  check('it preselects exactly that market',
    marketTap.selectedCount === 1 && marketTap.selected === 'spread', String(marketTap.selected));
  check('the stake is still $0 after a market tap', marketTap.stake === '0');
  check('one tap opens one composer, not two', marketTap.sheets === 1);

  /* ── Composer order and mode copy ─────────────────────────────────────── */

  section('The composer renders in the required order');

  const order = await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    const y = (sel) => {
      const el = sheet.querySelector(sel);
      return el ? el.getBoundingClientRect().top : null;
    };
    return {
      title: y('.fs-sheet__title'),
      market: y('[data-composer-market]'),
      preview: y('[data-composer-preview]'),
      mode: y('[data-composer-mode]'),
      note: y('[data-mode-note]'),
      stake: y('.fs-stake__label'),
      econ: y('[data-econ]'),
      send: y('[data-composer-send]'),
    };
  `);
  const sequence = ['title', 'market', 'preview', 'mode', 'note', 'stake', 'econ', 'send'];
  for (let i = 1; i < sequence.length; i += 1) {
    check(
      `${sequence[i]} sits below ${sequence[i - 1]}`,
      order[sequence[i]] !== null && order[sequence[i]] > order[sequence[i - 1]],
      `${order[sequence[i - 1]]} → ${order[sequence[i]]}`,
    );
  }

  const modeCopy = await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    const locked = sheet.querySelector('[data-mode-note]').textContent;
    sheet.querySelector('[data-composer-mode="dynamic"]').click();
    const dynamic = document.getElementById('fs-sheet')
      .querySelector('[data-mode-note]').textContent;
    document.getElementById('fs-sheet')
      .querySelector('[data-composer-mode="locked"]').click();
    return { locked, dynamic };
  `);
  check('Locked explains frozen terms and Yahoo non-interference',
    /captured now/.test(modeCopy.locked) && /never touch them/.test(modeCopy.locked));
  check('Locked names Refresh & Relock', /Refresh & Relock/.test(modeCopy.locked));
  check('Dynamic states the issuer stake stays put', /stake stays put/.test(modeCopy.dynamic));
  check('Dynamic states the derived stake can only come down',
    /come down \(never up, never past the max set now\)/.test(modeCopy.dynamic));
  check('Dynamic never says a stake can rise', !/flex up|can go up/i.test(modeCopy.dynamic));

  /* ── Stake, validation and economics ──────────────────────────────────── */

  section('Stake entry drives economics and the send control');

  const typed = await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    const input = sheet.querySelector('[data-composer-stake]');
    const set = (v) => {
      input.value = v;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const read = () => ({
      disabled: sheet.querySelector('[data-composer-send]').disabled,
      why: sheet.querySelector('[data-send-why]').textContent,
      rows: [...sheet.querySelectorAll('.fs-econ__value')].map(el => ({
        text: el.textContent, exact: el.getAttribute('data-exact-cents'),
      })),
    });
    set('1'); const tooSmall = read();
    set('20'); const ok = read();
    set('200'); const tooBig = read();
    set('20'); const back = read();
    return { tooSmall, ok, tooBig, back };
  `);
  check('a $1 stake keeps send disabled', typed.tooSmall.disabled === true);
  check('the reason names the $5 minimum',
    /minimum stake is \$5/.test(typed.tooSmall.why), typed.tooSmall.why);
  check('a $20 stake enables send', typed.ok.disabled === false);
  check('a stake beyond Available disables send again', typed.tooBig.disabled === true);
  check('the reason names the available figure',
    /\$65 available/.test(typed.tooBig.why), typed.tooBig.why);
  check('the economics show five figures', typed.ok.rows.length === 5, String(typed.ok.rows.length));
  check('economics draw whole dollars only',
    typed.ok.rows.every((r) => !/\$\d[\d,]*\.\d/.test(r.text)),
    typed.ok.rows.map((r) => r.text).join(' '));
  check('every economics figure carries its exact cents',
    typed.ok.rows.every((r) => Number.isInteger(Number(r.exact))));
  check('the pot equals both stakes',
    Number(typed.ok.rows[2].exact) === Number(typed.ok.rows[0].exact) + Number(typed.ok.rows[1].exact),
    typed.ok.rows.map((r) => r.exact).join(' + '));
  check('a $20 stake at +165 meets $33',
    Number(typed.ok.rows[0].exact) === 2000 && Number(typed.ok.rows[1].exact) === 3300);

  /* ── Preview preserves composer state ─────────────────────────────────── */

  section('Matchup Preview opens over the composer and returns it intact');

  const preview = await evaluate(`
    document.getElementById('fs-sheet').querySelector('[data-composer-preview]').click();
    const sheet = document.getElementById('fs-sheet');
    const titles = [...sheet.querySelectorAll('.fs-prev__title')].map(el => el.textContent);
    return {
      title: sheet.querySelector('.fs-sheet__title').textContent,
      titles,
      closeCount: sheet.querySelectorAll('[data-fs-close]').length,
      composerGone: sheet.querySelector('[data-composer-stake]') === null,
    };
  `);
  check('the preview opens in the shared sheet', /Matchup Preview/.test(preview.title));
  check('it carries SPORTSBOOK VIEW', preview.titles.includes('SPORTSBOOK VIEW'));
  check('it carries STARTING LINEUPS & PROJECTIONS',
    preview.titles.includes('STARTING LINEUPS & PROJECTIONS'));
  check('it carries WHY THE LINE LOOKS THIS WAY',
    preview.titles.includes('WHY THE LINE LOOKS THIS WAY'));
  check('it carries THE READ', preview.titles.includes('THE READ'));
  check('section order is Sportsbook → Lineups → Why The Line → The Read',
    preview.titles.join('|') ===
      'SPORTSBOOK VIEW|STARTING LINEUPS & PROJECTIONS|WHY THE LINE LOOKS THIS WAY|THE READ',
    preview.titles.join(' | '));
  check('the preview replaces the composer view while it is open',
    preview.composerGone === true);
  check('it has exactly one close control', preview.closeCount === 1);

  const restored = await evaluate(`
    document.getElementById('fs-sheet').querySelector('[data-fs-close]').click();
    const sheet = document.getElementById('fs-sheet');
    const pressed = [...sheet.querySelectorAll('[data-composer-market]')]
      .filter(el => el.getAttribute('aria-pressed') === 'true');
    return {
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      title: sheet.querySelector('.fs-sheet__title').textContent,
      stake: sheet.querySelector('[data-composer-stake]').value,
      market: pressed.length ? pressed[0].dataset.composerMarket : null,
      sendDisabled: sheet.querySelector('[data-composer-send]').disabled,
    };
  `);
  check('closing the preview returns to the composer', restored.open === true &&
    /CULV Destroyers/.test(restored.title));
  check('the stake survived the preview', restored.stake === '20', restored.stake);
  check('the market selection survived the preview', restored.market === 'spread');
  check('send is still enabled after returning', restored.sendDisabled === false);

  const closedAll = await evaluate(`
    document.getElementById('fs-sheet').querySelector('[data-fs-close]').click();
    return document.getElementById('fs-overlay').classList.contains('is-open');
  `);
  check('closing the composer closes the sheet entirely', closedAll === false);

  /* ── Pools ────────────────────────────────────────────────────────────── */

  section('FantasyStakes Pools shows all four at once in a 2×2 grid');

  const pools = await evaluate(`
    ${goLeague}
    const grid = document.getElementById('fs-pools-grid');
    const style = getComputedStyle(grid);
    const box = grid.getBoundingClientRect();
    const cards = [...grid.querySelectorAll('.fs-pool')];
    const rects = cards.map(el => el.getBoundingClientRect());
    return {
      count: cards.length,
      columns: style.gridTemplateColumns.split(' ').length,
      rows: style.gridTemplateRows.split(' ').length,
      scrolls: grid.scrollHeight > grid.clientHeight + 1,
      allInside: rects.every(r => r.top >= box.top - 1 && r.bottom <= box.bottom + 1
        && r.right <= ${VIEWPORT.width}),
      badges: cards.map(el => el.querySelector('.fs-pool__badge').textContent),
      names: cards.map(el => el.querySelector('.fs-pool__name').textContent),
      rules: cards.map(el => el.querySelector('.fs-pool__rule').textContent),
      goldCards: cards.filter(el => getComputedStyle(el).borderTopColor === 'rgb(201, 162, 74)').length,
      clipped: cards.filter(el => el.scrollHeight > el.clientHeight + 1).length,
    };
  `);
  check('four Pools', pools.count === 4, String(pools.count));
  check('two columns', pools.columns === 2, String(pools.columns));
  check('two rows', pools.rows === 2, String(pools.rows));
  check('no scrolling inside the zone', pools.scrolls === false);
  check('all four are visible together', pools.allInside === true);
  check('every Pool carries a type badge',
    pools.badges.every((b) => b.startsWith('TEAM') || b.startsWith('MATCHUP')),
    pools.badges.join(' | '));
  check('rollover appears only as a modifier on a type',
    pools.badges.every((b) => !b.startsWith('ROLLOVER')) &&
    pools.badges.some((b) => b.endsWith('· ROLLOVER')),
    pools.badges.join(' | '));
  check('every Pool names itself', pools.names.every((n) => n.length > 3));
  check('every Pool states its deterministic rule', pools.rules.every((r) => r.length > 3));
  check('a rolling Pool does not take a gold card', pools.goldCards === 0);
  check('no Pool card clips its own content', pools.clipped === 0, `${pools.clipped} clipped`);

  /* ── Action ───────────────────────────────────────────────────────────── */

  section('Action renders four single-row lifecycle rails');

  await evaluate(`${goAction} return true;`);

  const action = await evaluate(`
    const panel = document.getElementById('panel-action');
    const rails = [...panel.querySelectorAll('[data-rail]')];
    return {
      header: panel.querySelector('.fs-tabhead__title').textContent,
      railCount: rails.length,
      headings: rails.map(r => r.querySelector('.fs-heading__text').textContent),
      counts: rails.map(r => r.querySelectorAll('.fs-rail__item').length),
      singleRow: rails.map(r => {
        const items = [...r.querySelectorAll('.fs-rail__item')];
        const tops = new Set(items.map(el => Math.round(el.getBoundingClientRect().top)));
        return tops.size === 1;
      }),
      horizontal: rails.map(r => getComputedStyle(r.querySelector('.fs-rail')).overflowX),
      strip: [...panel.querySelectorAll('.fs-strip__value')].map(el => el.textContent.trim()),
      // Content inside a horizontal rail is SUPPOSED to extend past the fold —
      // that is what makes it scrollable. Only elements outside a scroller are
      // held to the viewport, plus the rails' own boxes.
      widest: Math.max(...[...panel.querySelectorAll('*')]
        .filter(el => !el.closest('.fs-rail'))
        .map(el => Math.round(el.getBoundingClientRect().right))),
      railsWithin: [...panel.querySelectorAll('.fs-rail')]
        .every(el => Math.round(el.getBoundingClientRect().right) <= ${VIEWPORT.width}),
      docWidth: document.documentElement.scrollWidth,
    };
  `);

  check('the Action header is the locked wording',
    action.header === 'WEEK 5 · REGULAR SEASON ACTION', action.header);
  check('exactly four rails', action.railCount === 4, String(action.railCount));
  check('rail headings match the locked wording',
    action.headings.join(' | ') ===
      'ACTION REQUIRED 2 | WAITING 2 | LIVE 4 | COMPLETED · 14–7 SEASON',
    action.headings.join(' | '));
  check('the rails hold 2, 2, 4 and 3 cards',
    action.counts.join(',') === '2,2,4,3', action.counts.join(','));
  check('every rail is a single row', action.singleRow.every(Boolean));
  check('every rail scrolls horizontally',
    action.horizontal.every((o) => o === 'auto'), action.horizontal.join(' '));
  check('the strip carries the four locked figures',
    action.strip.join(' | ') === '14–7 | $129 | +$129 | +$20', action.strip.join(' | '));
  check('Action does not scroll the page horizontally',
    action.docWidth <= VIEWPORT.width, `${action.docWidth}px`);
  check('no Action element outside a rail extends past the viewport',
    action.widest <= VIEWPORT.width, `widest right edge ${action.widest}px`);
  check('every rail box itself fits the viewport', action.railsWithin === true);

  const grammar = await evaluate(`
    const panel = document.getElementById('panel-action');
    const cards = [...panel.querySelectorAll('.fs-wcard')];
    return {
      total: cards.length,
      allShared: cards.every(el => el.classList.contains('fs-wcard--lifecycle')),
      haveIdentity: cards.every(el => el.querySelector('.fs-wcard__identity')),
      haveContext: cards.every(el => el.querySelector('.fs-wcard__context')),
      haveStakes: cards.every(el => el.querySelectorAll('.fs-wcard__figure').length >= 3),
      // textContent, so the label reads as authored — the uppercase is CSS.
      completedHaveNet: [...panel.querySelectorAll('[data-rail="completed"] .fs-wcard')]
        .every(el => el.textContent.includes('Net')),
      modeShown: cards.every(el =>
        /LOCKED|DYNAMIC/.test(el.querySelector('.fs-wcard__context').textContent)),
      clipped: cards.filter(el => el.scrollHeight > el.clientHeight + 1).length,
      exact: cards.every(el => el.querySelectorAll('[data-exact-cents]').length >= 3),
    };
  `);
  check('every Action card uses the shared wager-card grammar',
    grammar.allShared === true, `${grammar.total} cards`);
  check('every card names its opponent', grammar.haveIdentity === true);
  check('every card carries market and mode context', grammar.haveContext === true);
  check('Locked or Dynamic is visible on every card, not in fine print',
    grammar.modeShown === true);
  check('every card carries both stakes and the pot', grammar.haveStakes === true);
  check('completed cards add the net result', grammar.completedHaveNet === true);
  check('every card keeps exact cents behind its money', grammar.exact === true);
  check('no Action card clips its own content', grammar.clipped === 0, `${grammar.clipped} clipped`);

  /* ── Navigation still reachable ───────────────────────────────────────── */

  section('The bottom navigation stays reachable on both tabs');

  for (const [id, click] of [['league', goLeague], ['action', goAction]]) {
    const nav = await evaluate(`
      ${click}
      const bar = document.querySelector('.fs-tabbar').getBoundingClientRect();
      const panel = document.querySelector('.fs-panel.is-active').getBoundingClientRect();
      const items = [...document.querySelectorAll('.fs-tabbar__item')]
        .map(el => el.getBoundingClientRect());
      return {
        barTop: bar.top, barBottom: bar.bottom, panelBottom: panel.bottom,
        viewport: window.innerHeight,
        allItemsVisible: items.every(r => r.right <= ${VIEWPORT.width} && r.left >= 0),
        smallestTarget: Math.min(...items.map(r => Math.round(r.height))),
      };
    `);
    check(`${id}: the panel ends at or above the navigation`,
      nav.panelBottom <= nav.barTop + 0.5,
      `panel ${nav.panelBottom.toFixed(1)} vs nav ${nav.barTop.toFixed(1)}`);
    check(`${id}: the navigation is fully on screen`,
      nav.barBottom <= nav.viewport + 0.5);
    check(`${id}: all five destinations remain within the viewport`,
      nav.allItemsVisible === true);
  }

  /* ── Tapping an Action card ───────────────────────────────────────────── */

  section('An Action card opens its detail in the shared sheet');

  const detail = await evaluate(`
    ${goAction}
    document.querySelector('[data-rail="live"] .fs-wcard').click();
    const sheet = document.getElementById('fs-sheet');
    const close = sheet.querySelector('[data-fs-close]');
    const s = sheet.getBoundingClientRect();
    const c = close.getBoundingClientRect();
    return {
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      body: sheet.textContent,
      fromRight: s.right - c.right,
      fromLeft: c.left - s.left,
      fromTop: c.top - s.top,
    };
  `);
  check('the card opens a sheet', detail.open === true);
  check('the sheet shows the persisted protocol state, not a rail name',
    /Protocol state/.test(detail.body) && /accepted/.test(detail.body));
  check('the sheet names the Response Card', /Response card/.test(detail.body));
  check('the sheet uses the shared upper-right close control',
    detail.fromRight >= 0 && detail.fromRight < detail.fromLeft && detail.fromTop >= 0,
    `${detail.fromRight.toFixed(1)}px from right, ${detail.fromTop.toFixed(1)}px from top`);

  await evaluate(`document.getElementById('fs-sheet').querySelector('[data-fs-close]').click(); return true;`);
});

finish();