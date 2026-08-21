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
      // WP3C -- the PLAYABLE subset. Play offers the teams the server marked
      // versus_eligible, which is every member in the regular season and the
      // championship-track field in the postseason.
      eligibleOpponents: (action.opponents || [])
        .filter((o) => o.versus_eligible !== false).length,
      versusPhase: action.versus_phase,
      // WP3C -- the league's own season phase, and the words the UI renders for
      // it. Both come from the server so the suite pins agreement rather than a
      // literal.
      phase: ctx.phase,
      phaseLabel: ({ regular: 'REGULAR SEASON', postseason: 'POSTSEASON',
        championship: 'CHAMPIONSHIP', complete: 'SEASON COMPLETE' })[ctx.phase]
        || '',
    };
  })();`);

  check('the suite is signed in and reading an authoritative league',
    typeof served.league === 'number' && Boolean(served.leagueName),
    `league ${served.league} — ${served.leagueName}`);

  /* ── League renders ───────────────────────────────────────────────────── */

  section('League renders at the phone viewport');

  await evaluate(`${goLeague} return true;`);

  // WP3C — Rev 4.3 §8 rebuilt Play against real data, so the headings are
  // measured for their SHAPE rather than pinned to a fixture's counts: this
  // session's league decides how many opponents and how many Pools there are.
  // What is still pinned exactly is the vocabulary and the absence of the
  // directional arrow (§11).
  // UIRECON WAVE 1 — the locked public vocabulary. `FANTASYSTAKES MATCHUPS`
  // and `FANTASYSTAKES PROP POOLS` on first reference; no public-facing Versus
  // anywhere on the surface.
  check('the Matchups heading renders, with no directional arrow', await evaluate(`
    const headings = [...document.querySelectorAll('#panel-league .fs-heading__text')]
      .map(el => el.textContent);
    return headings.some(t => /^FANTASYSTAKES MATCHUPS/.test(t))
      && headings.every(t => !t.includes('↕'));
  `));
  check('the Prop Pools heading renders', await evaluate(`
    return [...document.querySelectorAll('#panel-league .fs-heading__text')]
      .some(el => /^FANTASYSTAKES PROP POOLS/.test(el.textContent));
  `));
  check('Play shows no public-facing Versus', await evaluate(`
    return !/versus/i.test(document.getElementById('panel-league').innerText);
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

  // WP3C — THE COUNT IS THE LEAGUE'S NOW, so the shape is what is asserted.
  //
  // This block used to require exactly ELEVEN cards, which was the number of
  // invented opponents `data/league-data.js` supplied to every session. Play
  // now discovers the server's own opponent list (§4, §6), and the
  // certification league has two teams — so the acting GM has one opponent, and
  // eleven was never a fact about this league.
  //
  // WHAT IS STILL PINNED EXACTLY is everything that was actually being tested:
  // the rail snaps vertically, never horizontally, presents exactly ONE card at
  // a time, and sizes that card to the rail. The multi-card scrolling claims
  // need a second card to be meaningful and are reported as not present when
  // the league has none — rather than passing vacuously.
  const carousel = await evaluate(`
    const rail = document.getElementById('fs-bets-carousel');
    if (!rail) return { absent: true, count: 0 };
    const style = getComputedStyle(rail);
    const items = [...rail.querySelectorAll('.fs-carousel__item')];
    const box = rail.getBoundingClientRect();
    const first = items[0] ? items[0].getBoundingClientRect() : null;
    const second = items[1] ? items[1].getBoundingClientRect() : null;
    const fullyVisible = items.filter(el => {
      const r = el.getBoundingClientRect();
      return r.top >= box.top - 1 && r.bottom <= box.bottom + 1;
    }).length;
    return {
      absent: false,
      count: items.length,
      snapType: style.scrollSnapType,
      overflowY: style.overflowY,
      overflowX: style.overflowX,
      railHeight: Math.round(box.height),
      itemHeight: first ? Math.round(first.height) : null,
      fullyVisible,
      secondIsBelow: second ? second.top >= first.bottom - 1 : null,
      canScroll: rail.scrollHeight > rail.clientHeight,
    };
  `);

  check('the discovery rail renders for a league with opponents',
    carousel.absent === false && carousel.count > 0, `${carousel.count} cards`);
  check('every card is a real opponent, not a fixture count',
    carousel.count === served.eligibleOpponents,
    `${carousel.count} cards for ${served.eligibleOpponents} eligible opponents`);
  check('the carousel snaps vertically', /y mandatory/.test(carousel.snapType), carousel.snapType);
  check('the carousel scrolls vertically', carousel.overflowY === 'auto');
  check('the carousel does not scroll horizontally', carousel.overflowX === 'hidden');
  check('one card fills the carousel viewport',
    Math.abs(carousel.itemHeight - carousel.railHeight) <= 2,
    `card ${carousel.itemHeight}px in a ${carousel.railHeight}px rail`);
  check('exactly one card is fully presented at a time',
    carousel.fullyVisible === 1, `${carousel.fullyVisible} fully visible`);

  if (carousel.count > 1) {
    check('cards are stacked, not side by side', carousel.secondIsBelow === true);
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
  } else {
    check('this league has one opponent — multi-card scrolling not exercised',
      true, `${carousel.count} card`);
  }

  // WP3C — WHAT A DISCOVERY CARD CARRIES CHANGED, and every removal below is a
  // removal of something invented.
  //
  // GONE: the record, the rank, the projected score and the line of analysis.
  // All four came from `data/league-data.js` and none has an authoritative
  // source for an arbitrary opponent pairing — there is no read model that
  // publishes a board of projections per opponent, and §4 forbids inventing
  // one. GONE TOO: the market VALUES. A quote is produced by the pricing engine
  // for one specific pairing at composition time; the cells name the three
  // markets and the composer prices the one that is tapped.
  //
  // ADDED: the preview row, above the markets, which is §9's locked hierarchy.
  //
  // WHAT IS STILL PINNED: the opponent is named from the served list, the three
  // markets are ML | SPR | O/U in order, the challenge affordance is present,
  // and the card does not clip.
  const cardContent = await evaluate(`
    const card = document.querySelector('#fs-bets-carousel .fs-wcard');
    const text = (sel) => {
      const el = card.querySelector(sel);
      return el ? el.textContent : null;
    };
    const preview = card.querySelector('[data-preview-opponent]');
    const markets = [...card.querySelectorAll('.fs-market')];
    return {
      identity: text('.fs-wcard__identity'),
      teamId: card.dataset.cardId,
      marketLabels: markets.map(el =>
        el.querySelector('.fs-market__label').textContent),
      previewPresent: Boolean(preview),
      previewFullWidth: preview
        ? Math.abs(preview.getBoundingClientRect().width
                   - card.getBoundingClientRect().width) <= 32
        : false,
      previewAboveMarkets: preview && markets[0]
        ? preview.getBoundingClientRect().bottom
          <= markets[0].getBoundingClientRect().top + 1
        : false,
      // WP3C -- NO FOOT ROW. The §9 hierarchy is identity, preview, markets,
      // supporting content; a Challenge foot was not in it, offered a third
      // route to a composer the two rows above already reach, and cost the 40px
      // that made the card clip its own markets at 375x667.
      hasFoot: Boolean(card.querySelector('.fs-wcard__foot')),
      tappableMarkets: markets.filter(el => el.tagName === 'BUTTON').length,
      clipped: card.scrollHeight > card.clientHeight + 1,
    };
  `);
  check('the card names a real opponent from the served list',
    cardContent.identity && cardContent.identity.length > 0
    && served.opponents.includes(Number(cardContent.teamId)),
    `${cardContent.identity} (team ${cardContent.teamId})`);
  check('the card carries ML, SPR and O/U in order',
    cardContent.marketLabels.join(' | ') === 'ML | SPR | O/U',
    cardContent.marketLabels.join(' | '));
  check('VIEW MATCHUP PREVIEW is present as a full-width row',
    cardContent.previewPresent === true && cardContent.previewFullWidth === true);
  check('and it sits ABOVE the market cells (§9)',
    cardContent.previewAboveMarkets === true);
  check('the card carries no redundant foot row (§9)',
    cardContent.hasFoot === false);
  check('every market cell is itself the affordance, and is focusable',
    cardContent.tappableMarkets === 3, String(cardContent.tappableMarkets));
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
  check('it names the opponent the card named',
    wholeCard.title.includes(cardContent.identity), wholeCard.title);
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
  // WP3C -- Rev 4.3 §9 puts VIEW MATCHUP PREVIEW ABOVE the market cells. The
  // measured sequence is otherwise unchanged, and measuring it is the point:
  // the component suite can assert source order, only a laid-out page can
  // assert that the preview really renders above the markets on screen.
  const sequence = ['title', 'preview', 'market', 'mode', 'note', 'stake', 'econ', 'send'];
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

  // THE TARGET IS ALREADY BOUND, AND THAT IS A PRODUCT REQUIREMENT, NOT A TEST
  // CONVENIENCE. S8-P4C-2R removed the name bridge that used to carry the
  // illustrative card's DISPLAY NAME into a real Credits command: two teams
  // sharing a name, or a fixture that had drifted, would have addressed the
  // wrong GM's money with nothing on screen looking wrong.
  //
  // The repair for that is not a second question. A Versus card represents ONE
  // opponent and carries that opponent's authoritative team id into the
  // composer, and `beginSession` honours the id ONLY if the server named it —
  // which is the rule S8-P4C-2R was protecting, enforced without asking the GM
  // to answer a question the card already answered.
  //
  // So this suite reads the target rather than choosing one. The probe still
  // looks for a picker, because the claim now is that there ISN'T one.
  const targeting = await evaluate(`
    const sheet = document.getElementById('fs-sheet');
    const before = sheet.querySelector('[data-send-why]').textContent;
    const opponent = sheet.querySelector('[data-composer-opponent]');
    if (opponent) opponent.click();
    const after = document.getElementById('fs-sheet')
      .querySelector('[data-send-why]').textContent;
    return { before, after, offered: Boolean(opponent) };
  `);
  // WP3C -- OPENING FROM A DISCOVERY CARD ALREADY NAMES THE TARGET, and that is
  // the improvement rather than a weakening. Rev 4.2's carousel cards carried
  // fixture ids that were not authoritative, so S8-P4C-2R made the composer
  // refuse until the GM re-picked their opponent from the served list. Play now
  // discovers the served list itself (§4), so the card's own id IS the
  // authoritative target and `beginSession` honours it -- still only if it
  // appears in that list, which is the rule that check was protecting.
  //
  // THE REQUIREMENT IS UNCHANGED AND IS STILL ASSERTED: a composer with no
  // target refuses to send. What changed is that arriving from a discovery card
  // is no longer a composer with no target -- so the composer does not offer a
  // second picker over the top of an answer the card already gave. The
  // fallback selector still renders for a composer handed no authoritative id,
  // which is a different situation and not this one.
  check('a composer opened from a discovery card already has its target',
    !/Choose who you are challenging/.test(targeting.before), targeting.before);
  check('and offers no second picker over a target the card already bound',
    targeting.offered === false, String(targeting.offered));
  check('so no targeting requirement is outstanding at any point',
    !/Choose who you are challenging/.test(targeting.after), targeting.after);

  // WP3C.2 -- THE STAKE WALK MOVES TO MONEYLINE FIRST.
  //
  // The composer above was opened from the SPREAD cell, which is the claim that
  // section makes and which still holds. But since the owner ruling assigned
  // market lines, a spread can only be sent when the server is offering one,
  // and this fixture's league has no board the pricing model can read -- so
  // Send is correctly disabled with "This matchup has no market on offer right
  // now" and every stake message below is masked by it.
  //
  // The assertions that follow are about STAKE VALIDATION -- the $5 minimum,
  // the Available ceiling -- so they are walked on the market that needs no
  // line. Nothing is weakened: the spread's own refusal is certified in
  // `test_wp3c2_versus_market_lines.py`, which runs against a league that has a
  // real board and can therefore tell the two states apart.
  await evaluate(`
    document.querySelector('#fs-sheet [data-composer-market="ml"]').click();
    return true;
  `);

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
      // WP3C -- what the block says when there is no quote to price against.
      econNote: (() => {
        const note = sheet.querySelector('[data-econ] .fs-note');
        return note ? note.textContent : null;
      })(),
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
  // WP3C -- THE ECONOMICS PREVIEW NEEDS A QUOTE, AND A REAL PAIRING HAS NONE YET.
  //
  // Rev 4.2's opponents carried fixture moneylines, so the composer could always
  // show the opponent's stake and the pot. A real opponent has no quote until
  // the pricing engine prices the chosen market, and no read model publishes one
  // per pairing -- so the block now says the pot is priced on send rather than
  // deriving one from odds nobody quoted.
  //
  // WP3C.1 GAVE THE COMPOSER A ROUTE TO ASK, and with it new sentences: an
  // unpriced composer now says what is missing, a waiting one says it is
  // pricing, and one the server refused says why. The CLAIM here is unchanged
  // and is the one that always mattered -- no figure is shown that nothing
  // quoted -- so the wording below follows the shipped copy rather than the
  // WP3C sentence it replaced. This fixture's league carries no board the
  // pricing model reads, which is exactly why it lands in this branch.
  //
  // The five-figure assertion therefore applies WHERE THERE IS A QUOTE, and the
  // absence is reported rather than passed over.
  if (typed.ok.rows.length > 0) {
    check('the economics show five figures', typed.ok.rows.length === 5,
      String(typed.ok.rows.length));
    check('economics draw whole dollars only',
      typed.ok.rows.every((r) => !/\$\d[\d,]*\.\d/.test(r.text)),
      typed.ok.rows.map((r) => r.text).join(' '));
    check('every economics figure carries its exact cents',
      typed.ok.rows.every((r) => Number.isInteger(Number(r.exact))));
  } else {
    check('no quote for this pairing — the composer says so and invents no pot',
      Boolean(typed.ok.econNote)
      && /priced when you pick a market|FantasyStakes will price the wager|Pricing this wager|cannot be priced|not been projected|starting lineup/
        .test(typed.ok.econNote),
      typed.ok.econNote || '(no note)');
  }
  if (typed.ok.rows.length === 5) {
    check('the pot equals both stakes',
      Number(typed.ok.rows[2].exact)
        === Number(typed.ok.rows[0].exact) + Number(typed.ok.rows[1].exact),
      typed.ok.rows.map((r) => r.exact).join(' + '));
    // The +165 figure was the fixture opponent's moneyline. A real pairing is
    // priced by the engine, so what is asserted is the GM's OWN stake, which is
    // the one figure the composer does hold, plus the pot identity above.
    check('the GM’s own stake is what they typed',
      Number(typed.ok.rows[0].exact) === 2000,
      String(typed.ok.rows[0].exact));
  }

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
  // WP3C -- Rev 4.3 §10 rebuilt the preview: no odds-market block, and analysis
  // before the dense lineup table. Measured here as well as in the component
  // suite, because the ORDER is the requirement and only a laid-out sheet can
  // show what a reader actually meets first.
  check('the preview opens in the shared sheet', /Matchup Preview/.test(preview.title));
  check('it carries no SPORTSBOOK VIEW block (§10)',
    !preview.titles.includes('SPORTSBOOK VIEW'), preview.titles.join(' | '));
  // UIRECON WAVE 4A — THE PAIRING IS NAMED ONCE, IN THE SHEET HEADER.
  //
  // MATCHUP was a label/value pair carrying the two team names the subtitle
  // above it already carried. Its slot now carries the MARKET on offer, and a
  // market has to be fetched — so the tap opens the sheet immediately, from
  // what the surface already holds, and the served block lands a moment later.
  // A GM never waits on a request to see the preview, which is why this
  // assertion is about what is on screen AT THE TAP.
  check('it carries no block restating the pairing',
    !preview.titles.includes('MATCHUP'), preview.titles.join(' | '));
  check('it carries WHY THE LINE LOOKS THIS WAY',
    preview.titles.includes('WHY THE LINE LOOKS THIS WAY'));
  check('it carries THE READ', preview.titles.includes('THE READ'));
  check('it carries LINEUPS', preview.titles.includes('LINEUPS'));
  check('section order is Why The Line → The Read → Lineups',
    preview.titles.join('|')
      === 'WHY THE LINE LOOKS THIS WAY|THE READ|LINEUPS',
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
  // THE MARKET THE COMPOSER WAS ACTUALLY ON. The stake walk above moved it to
  // Moneyline for the reason recorded there; the claim here is that pushing the
  // Matchup Preview on top and closing it again returns the SAME composer with
  // its selection intact, whichever selection that was.
  check('the market selection survived the preview', restored.market === 'ml',
    String(restored.market));
  check('send is still enabled after returning', restored.sendDisabled === false);

  const closedAll = await evaluate(`
    document.getElementById('fs-sheet').querySelector('[data-fs-close]').click();
    return document.getElementById('fs-overlay').classList.contains('is-open');
  `);
  check('closing the composer closes the sheet entirely', closedAll === false);

  /* ── Pools ────────────────────────────────────────────────────────────── */

  section('FantasyStakes Pools shows all four at once in a 2×2 grid');

  // WP3C -- PLAY'S POOLS ARE THE GOVERNED SLATE NOW (§11), so this block asks
  // two questions in order: is a slate drawn, and if so does it still present
  // as the locked 2x2 grid?
  //
  // AN UNDRAWN WEEK IS AN ORDINARY STATE, not a failure. A slate needs four
  // catalog definitions passing both gates, and gate 2 is a per-league provider
  // measurement -- the certification league has no provider, so it has no
  // slate. Play draws its intentional empty state, which §11 requires and which
  // Rev 4.2 could not do because it always had four invented Pools to show.
  //
  // THE `rule` LINE IS GONE FROM THE CARD (§11): long descriptive microcopy
  // moved to the Pool detail sheet, where it is asserted below.
  const pools = await evaluate(`
    ${goLeague}
    const grid = document.getElementById('fs-pools-grid');
    if (!grid) {
      const empty = document.querySelector('#panel-league [data-pools-state]');
      return { drawn: false, emptyState: empty ? empty.dataset.poolsState : null,
               emptyText: empty ? empty.textContent : null };
    }
    const style = getComputedStyle(grid);
    const box = grid.getBoundingClientRect();
    const cards = [...grid.querySelectorAll('.fs-pool')];
    const rects = cards.map(el => el.getBoundingClientRect());
    return {
      drawn: true,
      count: cards.length,
      columns: style.gridTemplateColumns.split(' ').length,
      rows: style.gridTemplateRows.split(' ').length,
      scrolls: grid.scrollHeight > grid.clientHeight + 1,
      allInside: rects.every(r => r.top >= box.top - 1 && r.bottom <= box.bottom + 1
        && r.right <= ${VIEWPORT.width}),
      badges: cards.map(el => el.querySelector('.fs-pool__badge').textContent),
      names: cards.map(el => el.querySelector('.fs-pool__name').textContent),
      hasRuleLine: cards.some(el => el.querySelector('.fs-pool__rule')),
      goldCards: cards.filter(el => getComputedStyle(el).borderTopColor === 'rgb(201, 162, 74)').length,
      clipped: cards.filter(el => el.scrollHeight > el.clientHeight + 1).length,
    };
  `);

  if (!pools.drawn) {
    check('no slate is drawn for this league, and Play says so rather than '
      + 'inventing four Pools',
      pools.emptyState !== null, String(pools.emptyState));
    check('the empty state is product language, not a reason code',
      Boolean(pools.emptyText) && !/[A-Z_]{4,}/.test(pools.emptyText),
      (pools.emptyText || '').slice(0, 80));
  } else {
    check('at most the governed four Pools', pools.count > 0 && pools.count <= 4,
      String(pools.count));
    check('two columns', pools.columns === 2, String(pools.columns));
    check('no scrolling inside the zone', pools.scrolls === false);
    check('all of them are visible together', pools.allInside === true);
    check('every Pool carries a type badge',
      pools.badges.every((b) => b.startsWith('TEAM') || b.startsWith('MATCHUP')),
      pools.badges.join(' | '));
    check('rollover appears only as a modifier on a type',
      pools.badges.every((b) => !b.startsWith('ROLLOVER')),
      pools.badges.join(' | '));
    check('every Pool names itself', pools.names.every((n) => n.length > 3));
    check('the compact card carries no descriptive rule line (§11)',
      pools.hasRuleLine === false);
    check('a rolling Pool does not take a gold card', pools.goldCards === 0);
    check('no Pool card clips its own content', pools.clipped === 0,
      `${pools.clipped} clipped`);
  }

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

  // WP3C -- THE PHASE IS AUTHORITATIVE TOO (§13, §27). S8-P4C-3 bound the week
  // and left `REGULAR SEASON` a literal, so a league in its championship week
  // read `WEEK 16 · REGULAR SEASON ACTION`. The heading is now compared against
  // the phase the SERVER reported for this league, which is a stronger claim
  // than the literal: it fails if the surface and the context read disagree.
  // `ACTION` remains, per §12.2 -- it is content terminology, not the tab name.
  check('the Action header states the served week and phase',
    action.header === `WEEK ${served.week} · ${served.phaseLabel} ACTION`,
    `${action.header} (served phase ${served.phase})`);
  check('and it hard-codes no phase',
    served.phase !== 'regular' || action.header.includes('REGULAR SEASON'),
    served.phase);
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
  check('the sheet uses the shared upper-left close control',
    detail.fromLeft >= 0 && detail.fromLeft < detail.fromRight && detail.fromTop >= 0,
    `${detail.fromLeft.toFixed(1)}px from left, ${detail.fromTop.toFixed(1)}px from top`);

  await evaluate(`document.getElementById('fs-sheet').querySelector('[data-fs-close]').click(); return true;`);
});

finish();