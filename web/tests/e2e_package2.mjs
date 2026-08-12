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

  /* ── WP5 · what this suite measures now ─────────────────────────────────
   *
   * SPRINT 7 WROTE THESE ASSERTIONS AGAINST THE ILLUSTRATIVE BUILD, where every
   * tab drew `web/js/data/*`. Sprint 8 bound Action, The Week, the Ledger and
   * Rules & Settings to the server, so the fixture's own numbers — twelve GMs,
   * rails of 2/2/4/3, a 14–7 record — are no longer what a signed-in GM sees,
   * and pinning them certified a build that no longer ships.
   *
   * WHAT IS PINNED NOW: the structure, the locked copy, the geometry, and
   * AGREEMENT WITH THE AUTHORITATIVE READ MODEL. Where a count used to be a
   * literal it is now compared against `/league/{id}/action/me` — which is a
   * stronger claim than the literal ever made, because it fails if the UI and
   * the server ever disagree rather than only if the fixture changes.
   *
   * THE LEAGUE TAB IS STILL ILLUSTRATIVE and its assertions are untouched; only
   * its identity heading comes from the bound league.
   */
  const served = await evaluate(`return (async () => {
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const league = me.capabilities.acting_league_id;
    const ctx = await (await fetch('/league/' + league + '/context/me',
      { credentials: 'same-origin' })).json();
    const action = await (await fetch('/league/' + league + '/action/me',
      { credentials: 'same-origin' })).json();
    const ledger = await (await fetch('/league/' + league + '/ledger/me',
      { credentials: 'same-origin' })).json();
    return {
      league,
      leagueName: ctx.league_name,
      week: ctx.current_week,
      availableCents: ledger.available_cents,
      // The server decides the sections; the rail ids are the same vocabulary.
      counts: Object.fromEntries(
        Object.entries(action.sections || {}).map(([k, v]) => [k, v.length])),
      opponents: (action.opponents || []).map((o) => o.team_id),
    };
  })();`);

  check('the suite is signed in and reading an authoritative league',
    typeof served.league === 'number' && Boolean(served.leagueName),
    `league ${served.league} — ${served.leagueName}`);

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
  // WP5: the heading is the BOUND league's name. It was the fixture's
  // `CULV APPRECIATION SOCIETY` until S8-P4B-2 bound `leagueName()`; asserting
  // the served name keeps the requirement — the tab identifies the league the
  // GM is actually in — and stops pinning a constant the product no longer uses.
  check('the league identity renders, and it is the bound league',
    await evaluate(`
      return document.querySelector('#panel-league .fs-tabhead__title').textContent;
    `) === served.leagueName, served.leagueName);
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
  // REVISED BY WP5, FOLLOWING S8-P4C-2R2. The two phrases pinned here —
  // "stake stays put" and "come down (never up, never past the max set now)" —
  // carried the economics AND the timing clause that P4C-2R2 corrected on
  // explicit authorisation ("at kickoff" understated when Final Lock fires).
  // That package revised the component suite and left these two behind, where
  // the drift stayed invisible because this suite was already red.
  //
  // The CLAIM is the economics, and it is unchanged: the Anchor is fixed, only
  // the Derived side moves, it moves DOWN only, and it is bounded. Asserted in
  // three parts rather than as one quotation, exactly as the component suite
  // now does, so a future rewording cannot silently drop one of them.
  check('Dynamic states the issuer’s own stake is fixed',
    /Anchor Stake stays fixed/i.test(modeCopy.dynamic), modeCopy.dynamic);
  check('Dynamic states the derived stake can only come down',
    /Derived Stake may come down/i.test(modeCopy.dynamic), modeCopy.dynamic);
  check('and that the movement is bounded by a ceiling',
    /never above the acceptance ceiling/i.test(modeCopy.dynamic), modeCopy.dynamic);
  check('Dynamic never says a stake can rise',
    !/flex up|can go up|may rise/i.test(modeCopy.dynamic));

  /* ── Stake, validation and economics ──────────────────────────────────── */

  section('Stake entry drives economics and the send control');

  // WP5 — THE TARGET IS CHOSEN FIRST, AND THAT IS A PRODUCT REQUIREMENT, NOT A
  // TEST CONVENIENCE. S8-P4C-2R removed the name bridge that used to carry the
  // illustrative card's DISPLAY NAME into a real Credits command: two teams
  // sharing a name, or a fixture that had drifted, would have addressed the
  // wrong GM's money with nothing on screen looking wrong. The composer now
  // asks, and Send stays disabled until it is answered.
  //
  // So this suite answers it. Sprint 7 never had to, which is why the stake
  // assertions below reported "Choose who you are challenging." instead of the
  // stake reasons — the composer was refusing for the right reason and the
  // suite was reading it as a stake failure.
  const targeting = await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    const before = sheet.querySelector('[data-send-why]').textContent;
    const opponent = sheet.querySelector('[data-composer-opponent]');
    if (opponent) opponent.click();
    const after = document.getElementById('fs-sheet')
      .querySelector('[data-send-why]').textContent;
    return { before, after, offered: Boolean(opponent) };
  `);
  check('the composer requires an authoritative target before it will send',
    targeting.offered === true && /Choose who you are challenging/.test(targeting.before),
    targeting.before);
  check('and choosing one clears that requirement',
    !/Choose who you are challenging/.test(targeting.after), targeting.after);

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
  // WP5: the ceiling is the GM's OWN Available, read from the bound Ledger
  // rather than from the prototype's $65. Comparing against the served figure
  // is a stronger claim than the literal: it fails if the composer and the
  // Ledger ever disagree about what this GM can spend.
  check('the reason names the available figure, and it is the served one',
    typed.tooBig.why.includes(`$${Math.round(served.availableCents / 100)} available`),
    `${typed.tooBig.why} (served $${served.availableCents / 100})`);
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

  // WP5 — the composer's title BEFORE the round trip. Sprint 7 pinned the
  // illustrative opponent's name here, but since S8-P4C-2R the composer names
  // the AUTHORITATIVE target the GM selected, which is the whole point of that
  // change. The requirement is that the same composer comes back, so the title
  // is captured and compared rather than asserted against a constant.
  const composerTitleBefore = await evaluate(`
    return document.getElementById('fs-sheet').querySelector('.fs-sheet__title').textContent;
  `);

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
  check('closing the preview returns to the composer',
    restored.open === true && restored.title === composerTitleBefore,
    `${composerTitleBefore} → ${restored.title}`);
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
      railIds: rails.map(r => r.dataset.rail),
      counts: rails.map(r => r.querySelectorAll('.fs-rail__item').length),
      // WP5: an EMPTY rail is a real state for a bound league and is trivially
      // one row. Sprint 7 required exactly one distinct top offset, which
      // reported an empty rail as multi-row — the opposite of the claim.
      singleRow: rails.map(r => {
        const items = [...r.querySelectorAll('.fs-rail__item')];
        const tops = new Set(items.map(el => Math.round(el.getBoundingClientRect().top)));
        return tops.size <= 1;
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
    action.header === `WEEK ${served.week} · REGULAR SEASON ACTION`, action.header);
  check('exactly four rails', action.railCount === 4, String(action.railCount));

  // WP5 — THE LOCKED ORDER AND WORDING, WITHOUT THE FIXTURE'S COUNTS. Sprint 7
  // pinned "ACTION REQUIRED 2 | WAITING 2 | LIVE 4 | COMPLETED · 14–7 SEASON",
  // which fixed the four headings AND the illustrative league's tallies in one
  // string. The heading grammar is the requirement; the tallies belong to
  // whatever league is bound.
  check('the four rails are in the locked order',
    action.railIds.join(',') === 'action,waiting,live,completed',
    action.railIds.join(','));
  check('rail headings keep the locked wording',
    action.headings[0].startsWith('ACTION REQUIRED')
    && action.headings[1].startsWith('WAITING')
    && action.headings[2].startsWith('LIVE')
    && action.headings[3].startsWith('COMPLETED'),
    action.headings.join(' | '));

  // AND THE COUNTS AGREE WITH THE SERVER. This replaces the literal 2,2,4,3
  // with a cross-check the literal could never make: the rendered rails and
  // `/league/{id}/action/me` must describe the same wagers.
  check('every rail holds exactly the wagers the server served',
    action.railIds.every((id, i) => action.counts[i] === served.counts[id]),
    `rendered ${action.counts.join(',')} vs served `
    + action.railIds.map((id) => served.counts[id]).join(','));

  check('every rail is a single row', action.singleRow.every(Boolean));
  check('every rail scrolls horizontally',
    action.horizontal.every((o) => o === 'auto'), action.horizontal.join(' '));
  // The strip's SHAPE is the locked requirement — four cells, and only four.
  // Its figures are the bound league's and are certified against the read model
  // by test_s8_p4c2_action.py rather than pinned to the prototype's here.
  check('the strip carries exactly four cells',
    action.strip.length === 4, action.strip.join(' | '));
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
      // WP5: the card says FIXED or FLOATING. modeLabel() in action.js chose
      // plain words over the engine's names deliberately — a GM should be able
      // to tell the two apart without knowing what an Anchor is — so the
      // requirement (ruling section 4: the distinction is visible before a GM
      // acts, not in fine print) is met in the product's vocabulary rather than
      // the engine's. LOCKED/DYNAMIC still names the mode in the detail sheet.
      modeShown: cards.every(el =>
        /FIXED|FLOATING/.test(el.querySelector('.fs-wcard__context').textContent)),
      modeContexts: cards.map(el => el.querySelector('.fs-wcard__context').textContent),
      clipped: cards.filter(el => el.scrollHeight > el.clientHeight + 1).length,
      exact: cards.every(el => el.querySelectorAll('[data-exact-cents]').length >= 3),
    };
  `);
  // A BOUND LEAGUE MAY HOLD FEW WAGERS, AND ZERO IS A REAL ANSWER — but a
  // grammar claim over an empty set is vacuous, so the suite says which it made.
  check('the Action tab drew the wagers the server served',
    grammar.total === Object.values(served.counts).reduce((a, b) => a + b, 0),
    `${grammar.total} card(s)`);

  check('every Action card uses the shared wager-card grammar',
    grammar.allShared === true, `${grammar.total} cards`);
  check('every card names its opponent', grammar.haveIdentity === true);
  check('every card carries market and mode context', grammar.haveContext === true);
  check('the Fixed/Floating distinction is on every card, not in fine print',
    grammar.total > 0 && grammar.modeShown === true,
    grammar.modeContexts.join(' | ') || 'no cards to check');
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

  // WP5 — THE CARD IS FOUND, NOT ASSUMED. Sprint 7 clicked
  // `[data-rail="live"] .fs-wcard`, which existed because the illustrative
  // league always had four live wagers. A bound league need not, and the
  // hard-coded selector turned an empty rail into a null-dereference that
  // killed the suite mid-run — taking every assertion after it with it.
  //
  // The claim was never "the LIVE rail specifically": it is that tapping an
  // Action card opens its detail in the shared sheet, showing persisted
  // protocol state. So the suite takes whichever card the bound league has.
  const detail = await evaluate(`
    ${goAction}
    const card = document.querySelector('#panel-action [data-rail] .fs-wcard');
    if (!card) return { noCards: true };
    card.click();
    const sheet = document.getElementById('fs-sheet');
    const close = sheet.querySelector('[data-fs-close]');
    const s = sheet.getBoundingClientRect();
    const c = close.getBoundingClientRect();
    return {
      noCards: false,
      rail: card.closest('[data-rail]').dataset.rail,
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      body: sheet.textContent,
      fromRight: s.right - c.right,
      fromLeft: c.left - s.left,
      fromTop: c.top - s.top,
    };
  `);
  check('the bound league has at least one Action card to open',
    detail.noCards === false,
    detail.noCards ? 'no wagers in any rail — the tap path is uncertified'
                   : `from the ${detail.rail} rail`);
  check('the card opens a sheet', detail.open === true);
  // THE PERSISTED STATE, whatever it is. Sprint 7 asserted `accepted` because
  // the illustrative LIVE rail always held accepted wagers. The requirement is
  // that the sheet reports the PROTOCOL's own state rather than the display
  // name of the rail the card was sitting in — so the label must be there and
  // the value must come from the lifecycle's vocabulary, not the rail's.
  const PROTOCOL_STATES =
    /Protocol state\s*(offered|countered|accepted|declined|expired|settled|withdrawn|retired)/i;
  check('the sheet shows the persisted protocol state, not a rail name',
    PROTOCOL_STATES.test((detail.body || '').replace(/\s+/g, ' ')),
    (detail.body || '').replace(/\s+/g, ' ').slice(0, 140));
  check('the sheet names the Response Card', /Response card/.test(detail.body || ''));
  check('the sheet uses the shared upper-right close control',
    detail.fromRight >= 0 && detail.fromRight < detail.fromLeft && detail.fromTop >= 0,
    `${detail.fromRight.toFixed(1)}px from right, ${detail.fromTop.toFixed(1)}px from top`);

  await evaluate(`document.getElementById('fs-sheet').querySelector('[data-fs-close]').click(); return true;`);
});

finish();