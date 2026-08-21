/* ============================================================================
 * FantasyStakes — S8-P4C-5 · full P4 integration, in a real browser
 *
 * THE SEAMS, NOT THE SUBSYSTEMS. Every earlier package proved its own surface.
 * What none of them could prove is that the five tabs are ONE application: that
 * the week League shows is the week Action requests, that the Available on
 * League is the Available the Ledger totals, and that a wager reads the same on
 * Action and on The Week. Those are the claims here, and each is asserted by
 * comparing two SURFACES against the same served value rather than against a
 * constant.
 *
 * THE FIXTURE IS DELIBERATELY NOT WEEK 5. The whole application assumed 5 until
 * P4C-3, and a week-5 fixture cannot distinguish "reads the authoritative week"
 * from "still assumes 5". The adversarial session runs week 9.
 *
 * GEOMETRY IS MEASURED, NEVER INSPECTED. Fifteen combinations — five tabs at
 * 375, 390 and 430 — are rendered and measured in the real browser: document
 * scroll width against viewport width, bottom-nav visibility, header and strip
 * clipping. CSS reasoning cannot produce those numbers.
 * ========================================================================== */

import { GO_RULES, createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const asyncProbe = (body) => `return (async () => { ${body} })();`;

// WP3B — Rev 4.3 §3 replaced the five destinations, and `standings` joins the
// sweep as the new default landing tab. `rules` stays in the list because its
// panel still exists and still has to hold up at every viewport; it is reached
// through the gear menu now rather than the tab bar, which is what `go` below
// accounts for.
const TABS = ['standings', 'league', 'action', 'ledger', 'week', 'rules'];
const WIDTHS = [375, 390, 430];

await withPage({ port: 9401, settleMs: 1800 }, async ({ evaluate, setViewport }) => {

  /* ── The one session, and what the server says about it ───────────────── */

  const served = await evaluate(asyncProbe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const league = me.capabilities.acting_league_id;
    const get = async (p) => {
      const r = await fetch(p, { credentials: 'same-origin' });
      return r.ok ? await r.json() : { __status: r.status };
    };
    const context = await get('/league/' + league + '/context/me');
    const week = context.current_week;
    return {
      league,
      team: me.capabilities.acting_team_id,
      teamName: me.capabilities.acting_team_name,
      context,
      ledger: await get('/league/' + league + '/ledger/me'),
      action: await get('/league/' + league + '/action/me'),
      slate: await get('/league/' + league + '/pool/slate/' + week),
      matchups: await get('/league/' + league + '/week/' + week + '/matchups'),
    };
  `));

  report.section('§4 · one authoritative league and week, everywhere');

  report.check('the session has an authoritative current week',
    served.context.week_resolved === true,
    String(served.context.current_week));
  report.check('and it is NOT the historical hard-coded 5',
    served.context.current_week !== 5,
    `week ${served.context.current_week}`);

  const WEEK = served.context.current_week;

  /* ── Cross-tab identity ───────────────────────────────────────────────── */

  const identity = await evaluate(asyncProbe(`
    const text = {};
    for (const t of ${JSON.stringify(TABS)}) {
      // WP3B: Rules & Settings is reached through the gear menu (Rev 4.3 §3.1).
      if (t === 'rules') { ${GO_RULES} }
      else document.querySelector('.fs-tabbar__item[data-destination="' + t + '"]').click();
      await new Promise((r) => setTimeout(r, 220));
      text[t] = document.getElementById('panel-' + t).textContent;
    }
    return text;
  `));

  // THE LEAGUE NAME IS THE SAME STRING WHEREVER IT APPEARS.
  const naming = TABS.filter((t) => identity[t].includes(served.context.league_name));
  report.check('the real league name appears on the tabs that name a league',
    naming.length >= 1, `named on: ${naming.join(', ')}`);
  report.check('the illustrative league never appears on any tab',
    !TABS.some((t) => identity[t].includes('CULV APPRECIATION SOCIETY')),
    TABS.filter((t) => identity[t].includes('CULV')).join(',') || 'none');

  // THE WEEK IS THE SAME NUMBER WHEREVER IT APPEARS, and week 5 must appear
  // nowhere as a week label now that the league says otherwise.
  report.check(`League states week ${WEEK}`,
    identity.league.includes('Week ' + WEEK), 'League header');
  report.check(`Action states week ${WEEK}`,
    identity.action.includes('WEEK ' + WEEK), 'Action header');
  const stale = TABS.filter((t) => /WEEK\s*5\b/i.test(identity[t])
    || /Week\s*5\b/.test(identity[t]));
  report.check('no tab still claims Week 5', stale.length === 0,
    stale.join(',') || 'none');

  // THE ACTING TEAM IS NAMED IN THE MASTHEAD IDENTITY BLOCK, not in a panel —
  // that is where P1 put it, and looking for it inside a tab was asking the
  // wrong element.
  const mastText = await evaluate(asyncProbe(`
    return document.getElementById('fs-mast').textContent;
  `));
  report.check('the masthead names the acting team authoritatively',
    served.teamName === null || mastText.includes(served.teamName),
    `${served.teamName} in masthead`);

  /* ── Cross-tab money, in exact cents ──────────────────────────────────── */

  report.section('§5 · exact-cent agreement across tabs');

  const money = await evaluate(asyncProbe(`
    const read = (panel, strip) => {
      document.querySelector('.fs-tabbar__item[data-destination="' + panel + '"]').click();
      return null;
    };
    const cells = (id) => [...document.querySelectorAll('#' + id + ' .fs-strip__cell')]
      .map((c) => ({
        label: c.querySelector('.fs-strip__label').textContent.trim(),
        value: c.querySelector('.fs-strip__value').textContent.trim(),
        exact: c.querySelector('[data-exact-cents]')
          ? c.querySelector('[data-exact-cents]').dataset.exactCents : null,
      }));
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 220));
    const leagueCells = cells('fs-strip-league');
    document.querySelector('.fs-tabbar__item[data-destination="ledger"]').click();
    await new Promise((r) => setTimeout(r, 220));
    const ledgerCells = cells('fs-strip-ledger');
    const settle = document.querySelector('#fs-current-settle .fs-settle__total');
    document.querySelector('.fs-tabbar__item[data-destination="action"]').click();
    await new Promise((r) => setTimeout(r, 220));
    const actionCells = cells('fs-strip-action');
    return {
      leagueCells, ledgerCells, actionCells,
      settleExact: settle ? Number(settle.dataset.exactCents) : null,
    };
  `));

  const cell = (list, label) => list.find((c) => c.label === label);

  // LEAGUE vs THE SERVED LEDGER — exact cents, not formatted dollars.
  const leagueAvailable = cell(money.leagueCells, 'Available');
  report.check('League Available equals the served Ledger, to the cent',
    leagueAvailable && leagueAvailable.exact === String(served.ledger.available_cents),
    `${leagueAvailable ? leagueAvailable.exact : 'missing'} vs ${served.ledger.available_cents}`);

  // UIRECON WAVE 1 — the cell is labelled `Min Left`; same cell, same source.
  const leagueMin = cell(money.leagueCells, 'Min Left');
  report.check('League Min Left equals the served figure',
    leagueMin && leagueMin.exact === String(served.ledger.weekly_min_live_cents),
    `${leagueMin ? leagueMin.exact : 'missing'} vs ${served.ledger.weekly_min_live_cents}`);

  const leagueWallet = cell(money.leagueCells, 'Wallet');
  report.check('League Wallet equals the served wallet',
    leagueWallet && leagueWallet.exact === String(served.ledger.wallet_cents),
    `${leagueWallet ? leagueWallet.exact : 'missing'} vs ${served.ledger.wallet_cents}`);

  // LEDGER vs THE SAME SERVED FIGURES.
  const ledgerAvailable = cell(money.ledgerCells, 'Available');
  report.check('Ledger Available equals the served figure',
    ledgerAvailable && ledgerAvailable.exact === String(served.ledger.available_cents),
    `${ledgerAvailable ? ledgerAvailable.exact : 'missing'}`);
  report.check('and therefore League and Ledger agree with each other',
    leagueAvailable && ledgerAvailable
    && leagueAvailable.exact === ledgerAvailable.exact,
    `${leagueAvailable ? leagueAvailable.exact : '?'} vs ${ledgerAvailable ? ledgerAvailable.exact : '?'}`);

  const held = cell(money.ledgerCells, 'Held');
  const inPlay = cell(money.ledgerCells, 'In Play');
  report.check('Held is a memo SUBSET of In Play, not a term beside it',
    held && inPlay && Number(held.exact) <= Number(inPlay.exact),
    `held ${held ? held.exact : '?'} <= in play ${inPlay ? inPlay.exact : '?'}`);
  report.check('Current Settle still uses FULL In Play',
    served.ledger.assets_cents
      === served.ledger.wallet_cents + served.ledger.weekly_min_live_cents
       + served.ledger.min_reserve_cents + served.ledger.expired_min_cents
       + served.ledger.in_play_cents,
    'assets exclude Held entirely');
  report.check('and the drawn Current Settle is the served one',
    money.settleExact === served.ledger.current_settle_cents,
    `${money.settleExact} vs ${served.ledger.current_settle_cents}`);

  // ACTION — Bet this week, scoped to the authoritative week.
  // UIRECON WAVE 1 — `Bet this week` is labelled `Staked`; same cell, same source.
  const betThisWeek = cell(money.actionCells, 'Staked');
  const committed = Object.values(served.action.sections || {}).flat()
    .filter((c) => c.week === WEEK && !c.settled
      && ['offered', 'countered', 'accepted'].includes(c.protocol_state))
    .reduce((sum, c) => sum + (c.your_stake_cents || 0), 0);
  report.check(`Action "Bet this week" is week ${WEEK}'s committed stake`,
    betThisWeek && betThisWeek.exact === String(committed),
    `${betThisWeek ? betThisWeek.exact : 'missing'} vs ${committed}`);

  /* ── Cross-tab wager identity ─────────────────────────────────────────── */

  report.section('§6 · one wager, read the same on Action and The Week');

  const live = Object.values(served.action.sections || {}).flat()
    .filter((c) => c.week === WEEK);

  if (live.length) {
    const subject = live[0];
    const rendered = await evaluate(asyncProbe(`
      const out = {};
      for (const t of ['action', 'week']) {
        document.querySelector('.fs-tabbar__item[data-destination="' + t + '"]').click();
        await new Promise((r) => setTimeout(r, 250));
        out[t] = document.getElementById('panel-' + t).textContent;
      }
      return out;
    `));
    report.check('the opponent reads the same on both tabs',
      rendered.action.includes(subject.opponent_name)
      && rendered.week.includes(subject.opponent_name),
      subject.opponent_name);
    const modeWord = subject.mode === 'dynamic' ? 'FLOATING' : 'FIXED';
    report.check(`its mode reads ${modeWord} on both`,
      rendered.action.includes(modeWord) && rendered.week.includes(modeWord),
      `${subject.mode} -> ${modeWord}`);
    report.check('and The Week does not reconstruct a different wager',
      rendered.week.includes(subject.opponent_name),
      'Versus reads the same Action contract');
  } else {
    report.check('DISCLOSED · no wager exists for this week to cross-check',
      true, 'reported rather than silently skipped');
  }

  /* ── Cross-tab Pool identity ──────────────────────────────────────────── */

  report.section('§7 · one weekly Pool slate');

  const pools = await evaluate(asyncProbe(`
    const out = {};
    for (const t of ['league', 'week']) {
      document.querySelector('.fs-tabbar__item[data-destination="' + t + '"]').click();
      await new Promise((r) => setTimeout(r, 250));
      const panel = document.getElementById('panel-' + t);
      out[t] = {
        rows: panel.querySelectorAll('.fs-poolrow').length,
        cards: panel.querySelectorAll('.fs-zone--pools .fs-wcard').length,
        text: panel.textContent,
      };
    }
    return out;
  `));

  const drawn = served.slate && served.slate.drawn;
  if (drawn) {
    report.check('the backend served exactly four slots',
      served.slate.slots.length === 4, String(served.slate.slots.length));
    report.check('slots are 1-4 only',
      JSON.stringify(served.slate.slots.map((s) => s.slot).sort()) === '[1,2,3,4]',
      JSON.stringify(served.slate.slots.map((s) => s.slot)));
    report.check('The Week draws exactly the served slots, no fifth',
      pools.week.rows === served.slate.slots.length,
      `${pools.week.rows} drawn vs ${served.slate.slots.length} served`);
    // CATALOG IDENTITY, not a display invention.
    const first = served.slate.slots[0];
    report.check('and the Pool identity is the backend catalog name',
      pools.week.text.includes(first.display_name || first.definition_key),
      first.display_name || first.definition_key);
  } else {
    report.check('an undrawn week draws ZERO Pool rows',
      pools.week.rows === 0, String(pools.week.rows));
    report.check('and no launch-four fallback appears',
      pools.week.rows === 0 && pools.league.cards === 0,
      `week ${pools.week.rows}, league ${pools.league.cards}`);
  }

  /* ── §14 · geometry, 5 tabs x 3 widths ────────────────────────────────── */

  report.section('§14 · 375 / 390 / 430 across all five tabs');

  const GEOMETRY = [];
  for (const width of WIDTHS) {
    await setViewport(width, 667);
    for (const tab of TABS) {
      const m = await evaluate(asyncProbe(`
        ${tab === 'rules'
          ? GO_RULES
          : `document.querySelector('.fs-tabbar__item[data-destination="${tab}"]').click();`}
        await new Promise((r) => setTimeout(r, 260));
        const doc = document.documentElement;
        const panel = document.getElementById('panel-${tab}');
        const nav = document.getElementById('fs-tabbar');
        const navRect = nav ? nav.getBoundingClientRect() : null;
        const strip = panel.querySelector('.fs-strip');
        const head = panel.querySelector('.fs-heading__text, .fs-tabhdr__title');
        // UIRECON WAVE 4B — THE SCROLL CONTAINER IS AN ANCESTOR, NOT ALWAYS
        // THE PARENT. This looked at el.parentElement alone, which was enough
        // while Wrap Up's carousel scrolled VERTICALLY: stacked items never
        // reached past the right edge, so nothing off-screen had a scrolling
        // grandparent. A horizontal rail puts cards 2..N genuinely off-screen
        // by design, and their parent is the item wrapper rather than the rail.
        // The claim is unchanged — nothing escapes the region that scrolls it —
        // and the walk is what makes it true of a region two levels up.
        const inAScroller = (el) => {
          for (let p = el.parentElement; p; p = p.parentElement) {
            const ox = getComputedStyle(p).overflowX;
            if (ox === 'auto' || ox === 'scroll') return true;
            if (p === panel) return false;
          }
          return false;
        };
        const overflowing = [...panel.querySelectorAll('*')].filter((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.right > doc.clientWidth + 1 && !inAScroller(el);
        }).length;
        return {
          viewport: doc.clientWidth,
          scrollWidth: doc.scrollWidth,
          bodyScrollWidth: document.body.scrollWidth,
          navVisible: Boolean(navRect) && navRect.height > 0
            && navRect.bottom <= window.innerHeight + 1,
          navBottom: navRect ? Math.round(navRect.bottom) : null,
          stripCells: strip ? strip.querySelectorAll('.fs-strip__cell').length : 0,
          stripClipped: strip
            ? strip.scrollWidth > strip.clientWidth + 1 : false,
          headerClipped: head
            ? head.scrollWidth > head.clientWidth + 1 : false,
          rails: panel.querySelectorAll('.fs-rail, .fs-rescar, .fs-zone').length,
          overflowing,
        };
      `));
      const pageOverflow = m.scrollWidth > m.viewport + 1;
      GEOMETRY.push({ width, tab, ...m, pageOverflow });

      report.check(`${tab} @${width}: no page-level horizontal overflow`,
        !pageOverflow, `scrollWidth ${m.scrollWidth} vs viewport ${m.viewport}`);
      report.check(`${tab} @${width}: bottom nav visible and on-screen`,
        m.navVisible, `nav bottom ${m.navBottom}`);
      report.check(`${tab} @${width}: header not clipped`,
        !m.headerClipped);
      report.check(`${tab} @${width}: no element escapes its scroll container`,
        m.overflowing === 0, `${m.overflowing} overflowing`);
    }
  }
  await setViewport(375, 667);

  // WP3B: six destinations now — the five primary tabs plus Rules & Settings,
  // which keeps its panel and its geometry claim after losing its tab position.
  report.check('all eighteen tab/viewport combinations were measured',
    GEOMETRY.length === TABS.length * WIDTHS.length, String(GEOMETRY.length));
  report.check('every strip that exists keeps four cells',
    GEOMETRY.filter((g) => g.stripCells > 0).every((g) => g.stripCells === 4),
    JSON.stringify(GEOMETRY.filter((g) => g.stripCells > 0)
      .map((g) => `${g.tab}@${g.width}:${g.stripCells}`)));

  /* ── §13 · global POR ─────────────────────────────────────────────────── */

  report.section('§13 · global UI POR');

  const por = await evaluate(asyncProbe(`
    const nav = [...document.querySelectorAll('.fs-tabbar__item')]
      .map((el) => el.textContent.trim());
    const out = { nav, mast: document.getElementById('fs-mast').textContent,
                  disclaimers: {}, decimals: {} };
    for (const t of ${JSON.stringify(TABS)}) {
      // WP3B: Rules & Settings is reached through the gear menu (Rev 4.3 §3.1).
      if (t === 'rules') { ${GO_RULES} }
      else document.querySelector('.fs-tabbar__item[data-destination="' + t + '"]').click();
      await new Promise((r) => setTimeout(r, 220));
      const panel = document.getElementById('panel-' + t);
      out.disclaimers[t] = (panel.textContent.match(
        /VIRTUAL CREDITS · \\$ IS DISPLAY ONLY · NO CASH VALUE/g) || []).length;
      out.decimals[t] = (panel.textContent.match(/\\$\\d+\\.\\d\\d/g) || []).length;
    }
    return out;
  `));

  report.check('the five destinations are the locked ones',
    por.nav.length === 5, JSON.stringify(por.nav));
  // WP3B — Rev 4.3 §2 locks a new primary product tagline in place of the
  // Rev 4.2 lockup line, and §2.1 strips the revision and byline from the
  // masthead. Both are asserted here, exactly.
  report.check('the masthead carries the locked Rev 4.3 product tagline',
    /Real odds\. Fantasy stakes\. More ways to win\./.test(por.mast),
    por.mast.slice(0, 120));
  report.check('the masthead carries no revision or engineering byline',
    !/Rev\s*4\./.test(por.mast) && !/Fraser/.test(por.mast),
    por.mast.slice(0, 120));
  report.check('the disclaimer appears at most once per tab',
    Object.values(por.disclaimers).every((n) => n <= 1),
    JSON.stringify(por.disclaimers));
  report.check('no decimal dollars are presented anywhere',
    Object.values(por.decimals).every((n) => n === 0),
    JSON.stringify(por.decimals));

  /* ── §17 · network boundary ───────────────────────────────────────────── */

  report.section('§17 · the browser talks only to this application');

  const network = await evaluate(asyncProbe(`
    const entries = performance.getEntriesByType('resource').map((e) => e.name);
    const origin = location.origin;
    const foreign = entries.filter((u) => !u.startsWith(origin)
      && !u.startsWith('data:') && !u.startsWith('blob:'));
    return {
      total: entries.length,
      foreign,
      yahoo: entries.filter((u) => /yahoo/i.test(u)),
      storage: {
        local: Object.keys(localStorage).length,
        session: Object.keys(sessionStorage).length,
      },
    };
  `));

  report.check('every request went to this application origin',
    network.foreign.length === 0, JSON.stringify(network.foreign.slice(0, 3)));
  report.check('no direct Yahoo call was made from the browser',
    network.yahoo.length === 0, JSON.stringify(network.yahoo));
  report.check('and no token is persisted in browser storage',
    network.storage.local === 0 && network.storage.session === 0,
    JSON.stringify(network.storage));

  /* ── §19 · no console errors attributable to the app ──────────────────── */

  const errors = await evaluate(asyncProbe(`
    return (window.__fsErrors || []).length;
  `));
  report.check('no uncaught application error was recorded', errors === 0,
    String(errors));
});

report.finish();
