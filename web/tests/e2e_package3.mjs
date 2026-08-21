/* ============================================================================
 * FantasyStakes — Sprint 7 Package 3 · The Week and Ledger layout tests
 *
 * Run directly:   node web/tests/e2e_package3.mjs
 * Or through:     python test_s7_p3_week_ledger.py
 *
 * Measured geometry and real interaction in headless Chrome at 390×844. The
 * questions this suite answers cannot be answered from source: does the week
 * switch actually change what is drawn, do all three modules fit a phone
 * without pushing the navigation off, does the Current Settle card really do
 * nothing when tapped, and does the reconciliation on screen add up to the
 * figure on screen.
 * ========================================================================== */

import { VIEWPORT, createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

await withPage({ port: 9337 }, async ({ evaluate }) => {
  const goWeek = `document.querySelector('.fs-tabbar__item[data-destination="week"]').click();`;
  const goLedger = `document.querySelector('.fs-tabbar__item[data-destination="ledger"]').click();`;

  /* ── WP5 · what this suite measures now ─────────────────────────────────
   *
   * The Week's Yahoo module was bound to the provider in S8-P4C-3. Its cards
   * are now the league's real matchups, so the illustrative six — and the
   * em-dash moneylines on five of them — are no longer what is drawn. The
   * assertions read the served matchups instead of the fixture's numbers.
   */
  const served = await evaluate(`return (async () => {
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const league = me.capabilities.acting_league_id;
    const ctx = await (await fetch('/league/' + league + '/context/me',
      { credentials: 'same-origin' })).json();
    // WeekStateOut, not a bare array — the week carries an empty flag and its
    // matchups underneath, because "the provider stated no matchups" is a
    // successful read and not an absence.
    const state = ctx.week_resolved
      ? await (await fetch('/league/' + league + '/week/' + ctx.current_week + '/matchups',
          { credentials: 'same-origin' })).json()
      : { matchups: [] };
    // The GM's own Versus wagers falling in THIS week — the same filter
    // versusBody() applies to the Action read model, so the Bets module can be
    // checked against the server rather than against a fixture count.
    const action = await (await fetch('/league/' + league + '/action/me',
      { credentials: 'same-origin' })).json();
    const thisWeek = Object.values(action.sections || {})
      .flat()
      .filter((c) => c.week === ctx.current_week).length;
    window.__wp5ServedThisWeek = Math.min(thisWeek, 4);

    return {
      league,
      week: ctx.current_week,
      actingTeamName: ctx.acting_team_name,
      matchups: (state.matchups || []).length,
      versusThisWeek: window.__wp5ServedThisWeek,
    };
  })();`);

  check('the suite is signed in and reading an authoritative league',
    typeof served.league === 'number' && served.matchups > 0,
    `league ${served.league}, ${served.matchups} matchup(s) in week ${served.week}`);

  /* ── The Week renders ─────────────────────────────────────────────────── */

  section('The Week renders as a three-module dashboard at the phone viewport');

  await evaluate(`${goWeek} return true;`);

  const head = await evaluate(`
    const panel = document.getElementById('panel-week');
    const opts = [...panel.querySelectorAll('[data-week]')];
    return {
      // Read the three parts in DOM order: the switch has no whitespace between
      // its children, so joining them is what shows the line the GM reads.
      text: [...panel.querySelector('.fs-wkswitch').children]
        .map(el => el.textContent.trim()).join(' · '),
      sub: panel.querySelector('.fs-wkhead__sub').textContent,
      weeks: opts.map(el => el.dataset.week),
      selected: opts.filter(el => el.classList.contains('is-selected')).map(el => el.dataset.week),
      tappable: opts.every(el => el.tagName === 'BUTTON'),
      bodyText: panel.textContent,
      strips: panel.querySelectorAll('.fs-strip').length,
      disclaimers: panel.querySelectorAll('.fs-disclaimer').length,
      modules: panel.querySelectorAll('[data-module]').length,
    };
  `);
  check('the week switch reads WEEK 4 · REGULAR SEASON · WEEK 5',
    head.text === 'WEEK 4 · REGULAR SEASON · WEEK 5', head.text);
  check('both weeks are tappable controls', head.tappable === true);
  // WP3D — `Official` removed. Rev 4.3 §23 permits a statement of source and
  // not a claim of standing; the provenance the wording carried is unchanged.
  check('the subtitle names the source without claiming official standing',
    head.sub === 'Yahoo matchups + FantasyStakes action', head.sub);
  check('the current week is selected by default',
    head.selected.length === 1 && head.selected[0] === '5', head.selected.join(','));
  check('there is no FIRST KICKOFF clock', !/FIRST KICKOFF/i.test(head.bodyText));
  check('there is no Preview / Results / Review selector',
    !/Results/i.test(head.bodyText) || !/Review/i.test(head.bodyText));
  check('The Week carries no four-cell strip', head.strips === 0, String(head.strips));
  check('and therefore no Credits disclaimer', head.disclaimers === 0, String(head.disclaimers));
  check('exactly three modules', head.modules === 3, String(head.modules));

  const overflow = await evaluate(`
    return {
      doc: document.documentElement.scrollWidth,
      inner: window.innerWidth,
      widest: Math.max(...[...document.querySelectorAll('#panel-week *')]
        .map(el => Math.round(el.getBoundingClientRect().right))),
    };
  `);
  check('The Week does not scroll the page horizontally',
    overflow.doc <= overflow.inner, `${overflow.doc}px vs ${overflow.inner}px`);
  check('no element extends past the viewport',
    overflow.widest <= VIEWPORT.width, `widest right edge ${overflow.widest}px`);

  const modules = await evaluate(`
    const panel = document.getElementById('panel-week');
    return [...panel.querySelectorAll('[data-module]')].map(el => ({
      id: el.dataset.module,
      heading: el.querySelector('.fs-heading__text').textContent,
      right: Math.round(el.getBoundingClientRect().right),
      clipped: el.scrollWidth > el.clientWidth + 1,
    }));
  `);
  check('the modules are Yahoo, Bets and Pools',
    modules.map(m => m.id).join(',') === 'yahoo,bets,pools',
    modules.map(m => m.id).join(','));
  // WP3C -- Rev 4.3 §11 removed the redundant directional arrow from every
  // swipe heading. The wording is otherwise unchanged and still pinned exactly.
  check('the Yahoo module names official Yahoo matchups',
    modules[0].heading === 'YAHOO LEAGUE MATCHUPS · SWIPE', modules[0].heading);
  // UIRECON WAVE 4B — one heading grammar for all three: NAME · SWIPE. The
  // derived count named a viewport cap that a one-card carousel makes
  // meaningless, and only this module ever carried one. The cap itself is
  // unchanged; what went is a heading that described it.
  check('the Bets module carries the shared heading grammar',
    modules[1].heading === 'FANTASYSTAKES MATCHUPS · SWIPE', modules[1].heading);
  check('no rail heading carries a directional arrow',
    modules.every((m) => !m.heading.includes('↕')),
    modules.map((m) => m.heading).join(' | '));
  // GOVERNED REVISION, S8-P4B-3. Which Pools a week has is the authoritative
  // SLATE's answer now, not a fixed frontend list. The Rev1.3 selector needs
  // four definitions passing BOTH catalog gates, and gate 2 is a per-league,
  // per-provider source measurement the certification environment does not
  // satisfy — so this week is legitimately undrawn and the module names itself
  // without a count. The four-slot contract is certified against a DRAWN slate
  // in test_s8_p4b3_settings_pool.py.
  // UIRECON WAVE 4B — the Pools module carries the same grammar as its two
  // peers now, drawn or not. A count in one section's heading and not the
  // others' was the last thing distinguishing three identical statements.
  check('the Pools module carries the shared heading grammar',
    modules[2].heading === 'FANTASYSTAKES PROP POOLS · SWIPE',
    modules[2].heading);
  check('no module clips its own content', modules.every(m => !m.clipped));

  /* ── Yahoo module ─────────────────────────────────────────────────────── */

  section('Yahoo matchups read as official fixtures, not wagers');

  const yahoo = await evaluate(`
    const zone = document.querySelector('[data-module="yahoo"]');
    const cards = [...zone.querySelectorAll('.fs-wcard')];
    return {
      count: cards.length,
      badges: cards.map(c => c.querySelector('.fs-wcard__badge').textContent),
      first: cards[0].querySelector('.fs-wcard__identity').textContent,
      snap: getComputedStyle(zone.querySelector('.fs-rescar')).scrollSnapType,
      scrolls: getComputedStyle(zone.querySelector('.fs-rescar')).overflowX,
      anyChallenge: cards.some(c => /Challenge/.test(c.textContent)),
      interactiveMarkets: zone.querySelectorAll('[data-market]').length,
      // WP5: counted, not dereferenced. A provider matchup draws NO market row
      // at all, so Sprint 7's unconditional querySelector(...).textContent hit
      // null on the first card and killed the suite.
      marketCells: zone.querySelectorAll('.fs-market').length,
      invented: [...zone.querySelectorAll('.fs-market__value')]
        .map(el => el.textContent.trim())
        .filter(v => v && v !== '—').length,
    };
  `);
  check('the Yahoo module draws exactly the served matchups',
    yahoo.count === served.matchups, `${yahoo.count} vs ${served.matchups} served`);
  check('every card is badged YAHOO', yahoo.badges.every(b => b === 'YAHOO'));
  check('the viewer’s own matchup leads the carousel',
    yahoo.first.includes(served.actingTeamName), yahoo.first);
  // UIRECON WAVE 4B — THE AXIS CHANGED AND THE CLAIM DID NOT. What this pair
  // has always asserted is that the module presents one card at a time and
  // snaps rather than drifting. The rail is horizontal now because a vertical
  // one had to be capped in pixels to bound it, and that cap went stale against
  // Rev 4.3's taller cards; items exactly one viewport wide need no cap.
  check('the carousel snaps', yahoo.snap === 'x mandatory', yahoo.snap);
  check('the carousel is what scrolls', yahoo.scrolls === 'auto', yahoo.scrolls);
  check('no Yahoo card offers a challenge', yahoo.anyChallenge === false);
  check('Yahoo market cells are not tappable', yahoo.interactiveMarkets === 0);
  // THE REQUIREMENT, PRESERVED AND STRENGTHENED. Sprint 7 checked that five of
  // six illustrative cards drew an em-dash rather than a manufactured
  // moneyline. `providerMatchupCard` now draws no market row whatsoever,
  // because the provider corpus carries no betting lines and deriving one from
  // fantasy points would be inventing a line. "Nothing is invented" is the
  // claim either way, and no market row satisfies it more completely than an
  // em-dash did.
  check('a provider matchup invents no betting line',
    yahoo.invented === 0,
    `${yahoo.marketCells} market cell(s), ${yahoo.invented} carrying a value`);

  /* ── WP5 · the Matchup Preview, and where it is reachable ──────────────────
   *
   * SPRINT 7 TAPPED A YAHOO CARD AND EXPECTED A PREVIEW. In the bound product a
   * provider matchup card carries NO tap affordance: `providerMatchupCard` sets
   * `tapAction: ''`, and `bindWeek` binds the preview lookup only in demo mode
   * ("THE FIXTURE LOOKUPS ARE DEMO-ONLY").
   *
   * THAT IS DELIBERATE AND IT IS ALSO A REAL CAPABILITY GAP. The preview's four
   * sections are Sportsbook View, Starting Lineups & Projections, Why The Line
   * Looks This Way and The Read — sportsbook analysis the provider gateway does
   * not capture. Opening it over a served matchup would mean manufacturing all
   * four, which is the one thing this build consistently refuses. Drawing no
   * affordance is the honest option, and it is reported as a product gap rather
   * than certified away.
   *
   * SO THE CLAIM IS SPLIT, AND NEITHER HALF IS DROPPED:
   *   · production — a provider card offers no preview and opens no sheet;
   *   · the preview itself — still certified in the shared sheet, driven
   *     through the real modules, so the four sections, the source banner and
   *     the upper-left close control remain browser-certified rather than
   *     demoted to a source check.
   */
  const notTappable = await evaluate(`
    const card = document.querySelector('[data-module="yahoo"] .fs-wcard');
    card.click();
    return {
      sheetOpened: document.getElementById('fs-overlay').classList.contains('is-open'),
      tapAffordances: document.querySelectorAll(
        '[data-module="yahoo"] [data-card-action]').length,
      foot: card.querySelector('.fs-wcard__footvalue')
        ? card.querySelector('.fs-wcard__footvalue').textContent.trim() : '',
    };
  `);
  check('a served provider matchup offers no preview affordance',
    notTappable.tapAffordances === 0 && notTappable.foot === '',
    `${notTappable.tapAffordances} affordance(s), foot "${notTappable.foot}"`);
  check('and tapping it opens nothing rather than an invented analysis',
    notTappable.sheetOpened === false);

  const preview = await evaluate(`return (async () => {
    const { previewSheet } = await import('/app/js/preview.js');
    const { yahooMatchups } = await import('/app/js/data/week-data.js');
    const { CURRENT_WEEK } = await import('/app/js/data/week-data.js');
    window.FantasyStakes.openSheet(previewSheet(yahooMatchups(CURRENT_WEEK)[1]));
    const sheet = document.getElementById('fs-sheet');
    return {
      open: document.getElementById('fs-overlay').classList.contains('is-open'),
      banner: sheet.querySelector('.fs-srcbanner')
        ? sheet.querySelector('.fs-srcbanner').textContent : '',
      titles: [...sheet.querySelectorAll('.fs-prev__title')].map(el => el.textContent),
      text: sheet.textContent,
      closes: sheet.querySelectorAll('[data-fs-close]').length,
    };
  })();`);
  check('the Matchup Preview opens in the shared sheet', preview.open === true);
  // WP3D — see the recorded reason in package3_component_tests.mjs. The banner
  // is retired; a Yahoo-backed session gets the exact contractual attribution
  // instead, and this fixture's league is not Yahoo-backed, so it gets neither.
  check('the preview claims no official standing for a Yahoo fixture',
    !preview.banner && !/official\s+yahoo/i.test(preview.text),
    String(preview.banner));
  // WP3C -- Rev 4.3 §10: no odds-market block, and analysis before the dense
  // lineup table. Same rebuild the package 2 suite measures; asserted here on
  // the Yahoo-sourced preview as well, because both open the same sheet.
  // UIRECON WAVE 4A — THE MATCHUP BLOCK IS GONE, AND NOTHING REPLACES IT HERE.
  //
  // That block was a label/value pair naming the two teams, which the sheet
  // subtitle already carried — one fact stated twice, and the duplicate was the
  // one a GM read first. Its slot now carries the MARKET on offer, which is the
  // thing the three modules below it explain.
  //
  // A YAHOO FIXTURE HAS NO MARKET ON OFFER, so on this preview that slot is
  // correctly empty and the sheet is the three analysis modules alone. The
  // priced FantasyStakes preview, which does carry one, is asserted on the
  // four-section order in test_uirecon_wave4.py.
  check('the preview carries the three shared analysis sections in the §10 order',
    preview.titles.join('|')
      === 'WHY THE LINE LOOKS THIS WAY|THE READ|LINEUPS',
    preview.titles.join('|'));
  check('and no block restates the pairing the sheet header already names',
    !preview.titles.includes('MATCHUP'), preview.titles.join('|'));
  check('and it carries no odds-market block',
    !preview.titles.includes('SPORTSBOOK VIEW'));
  check('it says this is not a FantasyStakes wager',
    /not a FantasyStakes wager/.test(preview.text));
  check('it explains the unquoted moneyline rather than deriving one',
    /No moneyline is quoted/.test(preview.text));
  check('it uses the one shared upper-left close control', preview.closes === 1);

  await evaluate(`document.querySelector('#fs-sheet [data-fs-close]').click(); return true;`);

  /* ── Bets and Pools modules ───────────────────────────────────────────── */

  section('The Bets and Pools modules reuse the Package 2 grammars');

  const bets = await evaluate(`
    const zone = document.querySelector('[data-module="bets"]');
    const cards = [...zone.querySelectorAll('.fs-wcard')];
    return {
      count: cards.length,
      lifecycle: cards.every(c => c.classList.contains('fs-wcard--lifecycle')),
      tappable: cards.every(c => c.dataset.cardAction === 'wager'),
      // FIXED/FLOATING is the product's vocabulary for the mode on a card; the
      // engine's LOCKED/DYNAMIC names it in the detail sheet. See action.js
      // modeLabel().
      haveMode: cards.every(c => /FIXED|FLOATING/.test(c.textContent)),
      exact: cards.every(c => c.querySelectorAll('[data-exact-cents]').length >= 3),
      servedThisWeek: window.__wp5ServedThisWeek,
    };
  `);
  // WP5 — AT MOST FOUR, AND NEVER INVENTED. Sprint 7 asserted exactly four
  // because the illustrative week always had four. UIRECON Wave 4B retired the
  // heading that advertised the cap and kept the cap itself in
  // `week.BETS_SHOWN`, which is where the real claim always lived: at most
  // four, and "the shortfall is never made up by inventing a wager that no
  // protocol record supports".
  check('the Bets module shows at most the four the heading presents',
    bets.count <= 4, `${bets.count} card(s)`);
  check('and invents no wager when the bound week holds fewer',
    bets.count === bets.servedThisWeek,
    `${bets.count} drawn vs ${bets.servedThisWeek} served for week ${served.week}`);
  check('they use the Package 2 lifecycle card', bets.lifecycle === true);
  check('each opens the shared wager detail', bets.tappable === true);
  check('Fixed or Floating stays visible on every card', bets.haveMode === true);
  check('every card keeps exact cents behind its money', bets.exact === true);

  // The detail grammar is certified where a card exists. A bound week with no
  // Versus wagers is a legitimate state, and it is reported rather than
  // silently skipped — an unrun check must not read as a passing one.
  if (bets.count > 0) {
    const betSheet = await evaluate(`
      document.querySelector('[data-module="bets"] .fs-wcard').click();
      const sheet = document.getElementById('fs-sheet');
      const text = sheet.textContent;
      document.querySelector('#fs-sheet [data-fs-close]').click();
      return { text };
    `);
    check('the wager detail is the Package 2 grammar, not a new one',
      /Protocol state/.test(betSheet.text) && /Response card/.test(betSheet.text));
  } else {
    check('the wager detail grammar is certified on the Action tab instead',
      true, `week ${served.week} holds no Versus wager — covered by `
            + 'e2e_package2.mjs and test_s8_p4c2_action_browser.py');
  }

  const pools = await evaluate(`
    const zone = document.querySelector('[data-module="pools"]');
    const rows = [...zone.querySelectorAll('.fs-poolrow')];
    const rail = zone.querySelector('.fs-rescar');
    const items = rail ? [...rail.querySelectorAll(':scope > .fs-rescar__item')] : [];
    return {
      count: rows.length,
      badges: rows.map(r => r.querySelector('.fs-poolrow__badge').textContent),
      names: rows.map(r => r.querySelector('.fs-poolrow__name').textContent),
      allVisible: rows.every(r => r.getBoundingClientRect().height > 0),
      sharesTheWrapCarousel: Boolean(rail),
      oneCardWide: items.length === 0 || items.every(
        (i) => Math.abs(i.getBoundingClientRect().width - rail.clientWidth) <= 1),
      scrollsVertically: rail ? rail.scrollHeight > rail.clientHeight + 1 : false,
    };
  `);
  // GOVERNED REVISION, S8-P4B-3 — and the claim it replaces is the important
  // one: production must NOT fall back to the four illustrative launch Pools.
  // An undrawn week renders none, which is exactly what is asserted here.
  check('an undrawn week renders no Pools rather than the launch four',
    pools.count === 0 || pools.count === 4, String(pools.count));
  // UIRECON WAVE 4B — THE POOLS MODULE IS THE SAME CAROUSEL AS ITS TWO PEERS.
  // It was the one Wrap section built differently: a flat column of buttons
  // beside two carousels, for a third thing a GM reads exactly the same way.
  // The rows survive inside it — an OPEN Pool has a pick to make rather than a
  // result to report — and the claim underneath both versions of this check is
  // the same one: the module never becomes a scroller of its own inside the tab.
  check('the module shares the one Wrap carousel',
    pools.sharesTheWrapCarousel === true);
  check('and presents exactly one card at a time', pools.oneCardWide === true);
  check('the module does not scroll vertically',
    pools.scrollsVertically === false);
  check('every Pool carries a subject-type badge',
    pools.badges.every(b => /^(TEAM|MATCHUP)/.test(b)), pools.badges.join(' | '));
  check('rollover appears only as a modifier on a type',
    pools.badges.every(b => !/^ROLLOVER/.test(b)), pools.badges.join(' | '));
  check('every Pool names itself', pools.names.every(n => n.length > 0));

  // GOVERNED REVISION, S8-P4B-3. Opening a Pool needs a Pool to open, and an
  // undrawn week has none. The claim is not dropped: the Pool detail sheet and
  // its catalog number are certified against a DRAWN slate in
  // test_s8_p4b3_settings_pool.py, where the fixture provides one.
  const poolSheetText = await evaluate(`
    const row = document.querySelector('[data-module="pools"] .fs-poolrow');
    if (!row) return null;
    row.click();
    const text = document.getElementById('fs-sheet').textContent;
    document.querySelector('#fs-sheet [data-fs-close]').click();
    return text;
  `);
  check('a Pool opens the shared Pool detail with its catalog number',
    poolSheetText === null || /catalog #/.test(poolSheetText),
    poolSheetText === null ? 'no Pools drawn in this session' : 'opened');

  /* ── Week switching ───────────────────────────────────────────────────── */

  section('The week switch changes the presentation, with no mode selector');

  const past = await evaluate(`
    document.querySelector('#panel-week [data-week="4"]').click();
    const panel = document.getElementById('panel-week');
    const opts = [...panel.querySelectorAll('[data-week]')];
    const cards = [...panel.querySelectorAll('[data-module="yahoo"] .fs-wcard')];
    return {
      selected: opts.filter(el => el.classList.contains('is-selected')).map(el => el.dataset.week),
      cards: cards.length,
      final: cards.filter(c => /FINAL/.test(c.textContent)).length,
      pregame: cards.filter(c => /PREGAME/.test(c.textContent)).length,
      betsHeading: panel.querySelector('[data-module="bets"] .fs-heading__text').textContent,
      betsText: panel.querySelector('[data-module="bets"]').textContent,
      betsCount: panel.querySelectorAll('[data-module="bets"] .fs-wcard').length,
      poolStates: [...panel.querySelectorAll('.fs-poolrow__state')].map(el => el.textContent),
      strips: panel.querySelectorAll('.fs-strip').length,
      modules: panel.querySelectorAll('[data-module]').length,
    };
  `);
  check('the past week becomes the selection',
    past.selected.length === 1 && past.selected[0] === '4', past.selected.join(','));
  // WP5 — SAME TREATMENT S8-P4B-3 ALREADY GAVE THE POOL ROWS BELOW. A bound
  // league has provider matchups only for the weeks its provider actually
  // stated; the certification fixture states one. The claim is the
  // PRESENTATION rule — a past week's matchups are settled, never pregame —
  // and it is asserted over whatever that week really holds rather than over
  // the illustrative six.
  check('every past matchup presents as settled',
    past.final === past.cards,
    `${past.final} of ${past.cards}`
    + (past.cards === 0 ? ' — the provider stated no matchups for this week' : ''));
  check('no past matchup still presents as pregame', past.pregame === 0);
  // Locked copy, identical on both weeks. UIRECON Wave 4B replaced `4 SHOWN`
  // with the shared NAME · SWIPE grammar the other two Wrap sections use; the
  // claim here is unchanged and is the one the next assertion holds to — the
  // heading is the same on every week, and a week holding three settled wagers
  // still shows three rather than gaining a fabricated fourth.
  check('the locked bets heading is unchanged on a past week',
    past.betsHeading === 'FANTASYSTAKES MATCHUPS · SWIPE', past.betsHeading);
  // The claim in the heading comment above, asserted rather than restated: a
  // week draws the wagers it really has and never gains a fabricated one.
  check('the past week draws only the wagers it really has',
    past.betsCount <= 4, `${past.betsCount} card(s)`);
  check('past bets show their result',
    past.betsCount === 0 || /WON|LOST/.test(past.betsText),
    past.betsCount === 0
      ? 'no Versus wager settled in this week — the result grammar is certified '
        + 'on the Action tab’s completed rail'
      : 'result shown');
  // GOVERNED REVISION, S8-P4B-3. These read a PAST week's settled Pool rows.
  // Production now reads the authoritative slate per week, and the
  // certification environment has no drawn slate for any week — gate 2 is a
  // per-league, per-provider source measurement it does not satisfy. The
  // rollover and winner presentations are certified against a drawn, settled
  // fixture slate in test_s8_p4b3_settings_pool.py; here the claim is that an
  // undrawn past week fabricates nothing.
  check('a Pool that found no qualifier says it rolled forward',
    past.poolStates.length === 0
    || past.poolStates.some(s => /rolled to Week 5/i.test(s)),
    past.poolStates.join(' | ') || 'no Pools drawn for this week');
  check('a settled Pool names its winner',
    past.poolStates.length === 0
    || past.poolStates.some(s => /Won by/i.test(s)),
    past.poolStates.join(' | ') || 'no Pools drawn for this week');
  check('the past week still carries no strip', past.strips === 0);
  check('the past week still has exactly three modules', past.modules === 3);

  const back = await evaluate(`
    document.querySelector('#panel-week [data-week="5"]').click();
    const panel = document.getElementById('panel-week');
    const cards = [...panel.querySelectorAll('[data-module="yahoo"] .fs-wcard')];
    return {
      selected: [...panel.querySelectorAll('[data-week].is-selected')].map(el => el.dataset.week),
      cards: cards.length,
      pregame: cards.filter(c => /PREGAME/.test(c.textContent)).length,
      final: cards.filter(c => /FINAL/.test(c.textContent)).length,
    };
  `);
  check('switching back restores the current week',
    back.selected.join(',') === '5', back.selected.join(','));
  // WP5: the presentation rule, over the matchups the week really has. The
  // illustrative card foots a live matchup PREGAME; `providerMatchupCard` foots
  // it IN PROGRESS, because a served matchup that is not `finalized_at` may
  // already be underway and calling that "pregame" would be a claim about the
  // clock the provider never made. The claim here is the one the week switch
  // owes: nothing still presents as settled.
  check('the current week is no longer presented as settled',
    back.cards > 0 && back.final === 0,
    `${back.final} final of ${back.cards} card(s)`);

  /* ── Navigation on The Week ───────────────────────────────────────────── */

  section('The Week fits the shell without displacing the navigation');

  const weekNav = await evaluate(`
    const bar = document.querySelector('.fs-tabbar').getBoundingClientRect();
    const panel = document.querySelector('.fs-panel.is-active').getBoundingClientRect();
    return { barTop: bar.top, barBottom: bar.bottom, panelBottom: panel.bottom,
             viewport: window.innerHeight };
  `);
  check('the panel ends at or above the navigation',
    weekNav.panelBottom <= weekNav.barTop + 0.5,
    `panel ${weekNav.panelBottom.toFixed(1)} vs nav ${weekNav.barTop.toFixed(1)}`);
  check('the navigation is fully on screen',
    weekNav.barBottom <= weekNav.viewport + 0.5);

  /* ── Ledger ───────────────────────────────────────────────────────────── */

  section('The Ledger header, strips and disclaimer');

  await evaluate(`${goLedger} return true;`);

  const ledgerHead = await evaluate(`
    const panel = document.getElementById('panel-ledger');
    const topoff = panel.querySelector('[data-topoff]');
    const strip = panel.querySelector('.fs-strip').getBoundingClientRect();
    const t = topoff.getBoundingClientRect();
    return {
      title: panel.querySelector('.fs-tabhead__title').textContent,
      sub: panel.querySelector('.fs-tabhead__sub').textContent,
      topoffText: topoff.textContent,
      topoffAboveStrip: t.bottom <= strip.top + 1,
      topoffHeight: Math.round(t.height),
      topoffWidth: Math.round(t.width),
      topoffFont: parseFloat(getComputedStyle(topoff).fontSize),
      topoffFilled: getComputedStyle(topoff).backgroundColor !== 'rgba(0, 0, 0, 0)',
      topoffBordered: parseFloat(getComputedStyle(topoff).borderTopWidth) > 0,
      topoffUnderlined: getComputedStyle(topoff).textDecorationLine.includes('underline'),
      disclaimers: panel.querySelectorAll('.fs-disclaimer').length,
      strips: panel.querySelectorAll('.fs-strip').length,
    };
  `);
  check('the title is FANTASYSTAKES LEDGER',
    ledgerHead.title === 'FANTASYSTAKES LEDGER', ledgerHead.title);
  check('the subtitle is My Week 5 · Regular Season',
    ledgerHead.sub === 'My Week 5 · Regular Season', ledgerHead.sub);
  check('Request Top-Off is in the header area, above the strip',
    ledgerHead.topoffAboveStrip === true);
  // What the POR fixes is that this reads as TEXT, not that its hit box is
  // small: small type, no fill, no border, underlined, and narrow. Package 5
  // padded the hit area to a phone-usable target without touching any of that,
  // so the box height is no longer the thing worth asserting — and the target
  // size is asserted in its own right below.
  check('Request Top-Off is a small text control, not a large button',
    ledgerHead.topoffFont <= 11 && !ledgerHead.topoffFilled
    && !ledgerHead.topoffBordered && ledgerHead.topoffUnderlined
    && ledgerHead.topoffWidth <= 130,
    `${ledgerHead.topoffFont}px, filled=${ledgerHead.topoffFilled}, ` +
    `bordered=${ledgerHead.topoffBordered}, ${ledgerHead.topoffWidth}px wide`);
  check('and its tap target is usable on a phone',
    ledgerHead.topoffHeight >= 32,
    `${ledgerHead.topoffWidth}×${ledgerHead.topoffHeight}px`);
  check('the Credits disclaimer appears exactly once',
    ledgerHead.disclaimers === 1, String(ledgerHead.disclaimers));
  check('the Ledger carries its two approved strips',
    ledgerHead.strips === 2, String(ledgerHead.strips));

  const strips = await evaluate(`
    const read = (id) => [...document.querySelectorAll('#' + id + ' .fs-strip__cell')]
      .map(cell => ({
        label: cell.querySelector('.fs-strip__label').textContent,
        value: cell.querySelector('.fs-strip__value').textContent,
        exact: cell.querySelector('[data-exact-cents]')
          ? cell.querySelector('[data-exact-cents]').dataset.exactCents
          : (cell.querySelector('.fs-strip__value').dataset.exactCents || null),
      }));
    return { week: read('fs-strip-ledger'), season: read('fs-strip-season') };
  `);
  // GOVERNED REVISION, S8-P4B-2R — Held only. This suite now drives the
  // PRODUCTION build against the P4B-1 authoritative fixture, so these are
  // posted ledger figures rather than prototype constants.
  //
  //   Available $65, In Play $28, Min Left $10 — KEEP EXACT. Unchanged,
  //   and now proven end-to-end from economy/current_settle.py.
  //
  //   Held $25 -> $0 — REVISE EXACT. P4B-0 established that the reachable
  //   path (beefs/beef_engine.py) uses a soft reservation and posts no
  //   challenge escrow, so no ChallengeFundingLeg exists and
  //   held_open_challenges_cents is structurally 0. P4C activates the Spec-2
  //   successor, after which this becomes a non-zero SUBSET of In Play.
  //
  // WP5 — AND P4C DID EXACTLY THAT, WHICH IS WHY THESE CONSTANTS WENT STALE.
  // S8-P4C-1 cut the application over to the funded challenge lifecycle, so the
  // fixture's $25 Anchor stake now genuinely leaves the wallet at issue:
  // Available $65 -> $40, In Play $28 -> $53, Held $0 -> $25. That package
  // updated `test_support_rev42_fixture.FIXTURE_EXPECTED` and its own suites and
  // left this one behind, where the drift stayed invisible because the suite was
  // already failing for the harness reason.
  //
  // THE CONSTANTS ARE GONE FOR GOOD. The strip is now checked against the
  // Ledger read model this session actually served, which is a stronger claim
  // than any triple of numbers: it fails if the strip and
  // `GET /league/{id}/ledger/me` ever disagree, and it cannot go stale again.
  const ledger = await evaluate(`return (async () => {
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const r = await fetch('/league/' + me.capabilities.acting_league_id + '/ledger/me',
      { credentials: 'same-origin' });
    return await r.json();
  })();`);

  const weekExpected = [
    ['Available', ledger.available_cents],
    ['In Play', ledger.in_play_cents],
    ['Held', ledger.held_open_challenges_cents],
    ['Min Left', ledger.weekly_min_live_cents],
  ];
  for (const [i, [label, cents]] of weekExpected.entries()) {
    check(`week strip cell ${i + 1} is ${label}, as the Ledger served it`,
      strips.week[i].label === label
      && strips.week[i].value === `$${Math.round(cents / 100)}`,
      `${strips.week[i].label} ${strips.week[i].value} vs served $${cents / 100}`);
    check(`${label} keeps its exact cents`,
      Number(strips.week[i].exact) === cents,
      `${strips.week[i].exact} vs served ${cents}`);
  }

  // GOVERNED REVISION, S8-P4B-2R — two cells.
  //
  //   Season Adj +$32 -> unresolved. P3 proved season winnings has no
  //   authoritative source. Two of the cell's three components ARE sourced,
  //   which is the trap: printing +$8 would put a partial subtotal under a
  //   label meaning the whole, and $0 would assert a zero nobody measured.
  //
  //   Settle −$45 -> −$69. Moves by exactly the unsourced +$24 that is
  //   no longer invented. Asserted exactly, not loosely.
  //
  //   Bet Record and Play Net are P4C-owned domains, untouched.
  // UIRECON WAVE 1 — the labels are held to one line at 320px and carry the
  // locked vocabulary. The FIGURES are unchanged and are still the claim.
  const seasonExpected = [['Bet Record', '14–7'], ['Play Net', '+$126'],
    ['Season Adj', '—'], ['Settle', '−$69']];
  for (const [i, [label, value]] of seasonExpected.entries()) {
    check(`My Season cell ${i + 1} is ${label} ${value}`,
      strips.season[i].label === label && strips.season[i].value === value,
      `${strips.season[i].label} ${strips.season[i].value}`);
  }

  const seasonLabel = await evaluate(`
    const el = document.querySelector('#panel-ledger .fs-seasonlabel');
    const sub = document.querySelector('#panel-ledger .fs-tabhead__sub');
    const a = getComputedStyle(el), b = getComputedStyle(sub);
    return {
      text: el.textContent,
      sameFont: a.fontSize === b.fontSize && a.fontWeight === b.fontWeight
        && a.color === b.color,
      classes: el.className,
    };
  `);
  check('the second strip is labelled My Season', seasonLabel.text === 'My Season');
  check('it uses the same subtitle typography as My Week 5',
    seasonLabel.sameFont === true, seasonLabel.classes);

  /* ── Ledger reconciliation ────────────────────────────────────────────── */

  section('The reconciliation on screen adds up to the figure on screen');

  const sections = await evaluate(`
    const panel = document.getElementById('panel-ledger');
    const secs = [...panel.querySelectorAll('.fs-lsec')];
    return secs.map(s => ({
      number: s.dataset.section,
      title: s.querySelector('.fs-lsec__title').textContent,
      elevated: s.classList.contains('is-elevated'),
      rows: [...s.querySelectorAll('.fs-lrow')].map(r => ({
        label: r.querySelector('.fs-lrow__label').textContent.replace('↳', '').trim(),
        cents: r.querySelector('[data-exact-cents]')
          ? Number(r.querySelector('[data-exact-cents]').dataset.exactCents) : null,
        level: r.className.includes('is-level1') ? 1 : 0,
        total: r.classList.contains('is-total'),
      })),
    }));
  `);
  // UIRECON WAVE 2 — Current Settle is section 4, built by the same
  // `ledgerSection()` as the three that explain into it. Four numbered
  // sections, one construction.
  check('the Ledger has four numbered sections', sections.length === 4, String(sections.length));
  check('they are Advances, Wagering Summary, Season Adjustments and Current Settle',
    sections.map(s => s.title).join(' | ')
      === 'FANTASYSTAKES ADVANCES | WAGERING SUMMARY | SEASON ADJUSTMENTS + WINNINGS'
        + ' | CURRENT SETTLE',
    sections.map(s => s.title).join(' | '));
  check('the Wagering Summary is the elevated section',
    sections[1].elevated === true && !sections[0].elevated && !sections[2].elevated);

  const find = (sec, label) => sec.rows.find(r => r.label === label);
  const adv = sections[0];
  const regular = find(adv, 'Regular Season Minimum Stakes');
  const playoffs = find(adv, 'Playoffs / Championship Stakes');
  const opening = find(adv, 'Season-Opening FantasyStakes');
  const added = find(adv, 'Added Stakes');
  const totalStakes = find(adv, 'Total Virtual Stakes');

  check('$140 + $80 reconciles to $220 on screen',
    regular.cents + playoffs.cents === opening.cents,
    `${regular.cents} + ${playoffs.cents} = ${opening.cents}`);
  check('$220 + $40 reconciles to $260 on screen',
    opening.cents + added.cents === totalStakes.cents,
    `${opening.cents} + ${added.cents} = ${totalStakes.cents}`);
  check('the two components are indented beneath Season-Opening',
    regular.level === 1 && playoffs.level === 1);
  check('Added Stakes is NOT indented beneath Season-Opening',
    added.level === 0);
  check('Season-Opening itself is a top-level row', opening.level === 0);

  const groups = await evaluate(`
    const sec = document.querySelector('[data-section="2"]');
    const out = {};
    for (const g of sec.querySelectorAll('.fs-lgroup')) {
      const head = g.querySelector('.fs-lgroup__head').textContent;
      // Header-level figures only. The supporting rows inside an expansion also
      // carry exact cents, and pulling them in here would add the detail to the
      // total it is detail OF.
      out[head] = [...g.querySelectorAll('.fs-lrow > [data-exact-cents], .fs-lexp__head > [data-exact-cents]')]
        .map(el => ({
          label: el.parentElement.querySelector('.fs-lrow__label')
            .textContent.replace('›', '').trim(),
          cents: Number(el.dataset.exactCents),
        }));
    }
    return out;
  `);
  const versus = groups['MATCHUP ACTIVITY'];
  check('184 − 78 reconciles to 106 on screen',
    versus[0].cents + versus[1].cents === versus[2].cents,
    `${versus[0].cents} + ${versus[1].cents} = ${versus[2].cents}`);
  const poolGroup = groups['PROP POOL ACTIVITY'];
  check('45 − 25 reconciles to 20 on screen',
    poolGroup[0].cents + poolGroup[1].cents === poolGroup[2].cents,
    `${poolGroup[0].cents} + ${poolGroup[1].cents} = ${poolGroup[2].cents}`);
  const posGroup = groups['CURRENT WAGER POSITION'];
  check('65 + 28 + 90 reconciles to 183 on screen',
    posGroup[0].cents + posGroup[1].cents + posGroup[2].cents === posGroup[3].cents,
    `${posGroup[0].cents} + ${posGroup[1].cents} + ${posGroup[2].cents} = ${posGroup[3].cents}`);

  const adjRows = sections[2].rows;
  const weeklyMin = find(sections[2], 'Weekly Min · out of circulation');
  const skunk = find(sections[2], 'Skunk Fees');
  const netAdj = find(sections[2], 'Net Adjustments + Winnings');
  const winnings = await evaluate(`
    const el = document.querySelector('[data-expand="season-winnings"] .fs-lrow__value');
    return Number(el.dataset.exactCents);
  `);
  check('8 + 0 + 24 reconciles to 32 on screen',
    weeklyMin.cents + skunk.cents + winnings === netAdj.cents,
    `${weeklyMin.cents} + ${skunk.cents} + ${winnings} = ${netAdj.cents}`);
  check('Points Champion and Playoff Champion are pending',
    adjRows.filter(r => /Champion/.test(r.label)).length === 2);

  const settle = await evaluate(`
    const card = document.getElementById('fs-current-settle');
    const rows = [...card.querySelectorAll('.fs-settle__row')].map(r => ({
      label: r.querySelector('.fs-settle__label').textContent,
      cents: Number(r.querySelector('[data-exact-cents]').dataset.exactCents),
    }));
    const total = Number(card.querySelector('.fs-settle__total').dataset.exactCents);
    return {
      rows, total,
      drawn: card.querySelector('.fs-settle__total').textContent,
      isButton: card.tagName === 'BUTTON' || card.querySelectorAll('button').length > 0,
      hasAction: Boolean(card.dataset.cardAction),
      tappable: card.classList.contains('is-tappable'),
      cursor: getComputedStyle(card).cursor,
      text: card.textContent,
    };
  `);
  check('the card shows its three inputs', settle.rows.length === 3, String(settle.rows.length));
  check('the three inputs reconcile to the drawn total on screen',
    settle.rows.reduce((s, r) => s + r.cents, 0) === settle.total,
    `${settle.rows.map(r => r.cents).join(' + ')} = ${settle.total}`);
  check('Current Settle draws as −$69', settle.drawn === '−$69', settle.drawn);
  check('Total Virtual Stakes is shown as a subtraction',
    settle.rows[0].cents === -26000, String(settle.rows[0].cents));
  check('the card matches the My Season strip figure',
    String(settle.total) === '-6900', String(settle.total));

  section('The Current Settle card is inert, and promises no other page');

  check('the card contains no button', settle.isButton === false);
  check('the card carries no tap action', settle.hasAction === false);
  check('the card is not marked tappable', settle.tappable === false);
  // The BODY is inert. The section header above it is a disclosure toggle
  // like every other section's, which is the one control Wave 2 added and the
  // one this block is not about: what must never happen is the reconciliation
  // itself presenting as a door to somewhere else.
  check('the card does not present as clickable', settle.cursor !== 'pointer', settle.cursor);
  check('there is no View Full Reconciliation on the card',
    !/View Full Reconciliation/i.test(settle.text));

  const clicked = await evaluate(`
    document.getElementById('fs-current-settle').click();
    return document.getElementById('fs-overlay').classList.contains('is-open');
  `);
  check('tapping the card opens nothing', clicked === false);

  const anywhere = await evaluate(`
    return /View Full Reconciliation/i.test(document.getElementById('panel-ledger').textContent);
  `);
  check('there is no View Full Reconciliation anywhere on the tab', anywhere === false);

  /* ── Ledger interactions and layout ───────────────────────────────────── */

  section('Supporting detail expands as an audit surface');

  const expanded = await evaluate(`
    // WP3C -- THE SECTION OPENS FIRST. Rev 4.3 §14.2 put the three accounting
    // sections behind their own disclosure so the top of Account answers its
    // four questions without scrolling past forty rows. The row-level expander
    // this block tests now lives inside one, so reaching it means opening the
    // section — which is itself the §14.2 requirement that collapsed detail
    // stays REACHABLE rather than removed, and is asserted below.
    const holder = document.querySelector('[data-expand="versus-wins"]');
    const section = holder.closest('[data-disclosure]');
    const sectionToggle = section ? section.querySelector('[data-lsec-toggle]') : null;
    const sectionHiddenBefore = section
      ? holder.getBoundingClientRect().height === 0 : false;
    if (sectionToggle && !section.classList.contains('is-open')) sectionToggle.click();
    const sectionAria = sectionToggle
      ? sectionToggle.getAttribute('aria-expanded') : null;
    const head = holder.querySelector('.fs-lexp__head');
    const before = holder.querySelector('.fs-lexp__body').getBoundingClientRect().height;
    head.click();
    const after = holder.querySelector('.fs-lexp__body').getBoundingClientRect().height;
    const rows = [...holder.querySelectorAll('.fs-lexp__row [data-exact-cents]')]
      .map(el => Number(el.dataset.exactCents));
    const headerCents = Number(head.querySelector('[data-exact-cents]').dataset.exactCents);
    return { before, after, rows, headerCents, aria: head.getAttribute('aria-expanded'),
             sectionHiddenBefore, sectionAria };
  `);
  check('the section is collapsed until asked (§14.2)',
    expanded.sectionHiddenBefore === true);
  check('opening it is announced to assistive tech',
    expanded.sectionAria === 'true', String(expanded.sectionAria));
  check('and the detail inside is fully reachable, not removed',
    expanded.rows.length > 0, `${expanded.rows.length} supporting rows`);
  check('the row is collapsed until asked', expanded.before === 0);
  check('expanding reveals the supporting rows', expanded.after > 0);
  check('the expansion is announced to assistive tech', expanded.aria === 'true');
  check('the supporting rows add up to the row they expand',
    expanded.rows.reduce((s, c) => s + c, 0) === expanded.headerCents,
    `${expanded.rows.join(' + ')} = ${expanded.headerCents}`);

  const topoffSheet = await evaluate(`
    document.querySelector('#panel-ledger [data-topoff]').click();
    const sheet = document.getElementById('fs-sheet');
    const text = sheet.textContent;
    const closes = sheet.querySelectorAll('[data-fs-close]').length;
    document.querySelector('#fs-sheet [data-fs-close]').click();
    return { text, closes };
  `);
  check('Request Top-Off opens the shared sheet',
    /Request Top-Off/.test(topoffSheet.text));
  check('it is read-only and names the governed command',
    topoffSheet.text.includes('POST /league/{league_id}/top-offs'));
  check('it implements no parallel top-off path',
    /implements no top-off path of its own/.test(topoffSheet.text));
  check('it uses the one shared close control', topoffSheet.closes === 1);

  section('The Ledger fits the phone and keeps the navigation reachable');

  const ledgerLayout = await evaluate(`
    const panel = document.getElementById('panel-ledger');
    const bar = document.querySelector('.fs-tabbar').getBoundingClientRect();
    const p = panel.getBoundingClientRect();
    return {
      doc: document.documentElement.scrollWidth,
      inner: window.innerWidth,
      widest: Math.max(...[...panel.querySelectorAll('*')]
        .map(el => Math.round(el.getBoundingClientRect().right))),
      panelBottom: p.bottom,
      barTop: bar.top,
      barBottom: bar.bottom,
      viewport: window.innerHeight,
      clipped: [...panel.querySelectorAll('.fs-lsec, .fs-settle')]
        .filter(el => el.scrollWidth > el.clientWidth + 1).length,
    };
  `);
  check('the Ledger does not scroll the page horizontally',
    ledgerLayout.doc <= ledgerLayout.inner,
    `${ledgerLayout.doc}px vs ${ledgerLayout.inner}px`);
  check('no Ledger element extends past the viewport',
    ledgerLayout.widest <= VIEWPORT.width, `widest right edge ${ledgerLayout.widest}px`);
  check('no section clips its own content',
    ledgerLayout.clipped === 0, `${ledgerLayout.clipped} clipped`);
  check('the panel ends at or above the navigation',
    ledgerLayout.panelBottom <= ledgerLayout.barTop + 0.5,
    `panel ${ledgerLayout.panelBottom.toFixed(1)} vs nav ${ledgerLayout.barTop.toFixed(1)}`);
  check('the navigation is fully on screen',
    ledgerLayout.barBottom <= ledgerLayout.viewport + 0.5);

  const money = await evaluate(`
    const panel = document.getElementById('panel-ledger');
    const figures = [...panel.querySelectorAll('[data-exact-cents]')];
    return {
      count: figures.length,
      allInteger: figures.every(el => Number.isSafeInteger(Number(el.dataset.exactCents))),
      anyCentsDrawn: /\\$\\d+\\.\\d\\d/.test(panel.textContent),
    };
  `);
  check('every money figure carries its exact cents',
    money.count >= 20, String(money.count));
  check('every exact value is an integer number of cents', money.allInteger === true);
  check('nothing is drawn with cents under the whole-dollar rule',
    money.anyCentsDrawn === false);
});

finish();