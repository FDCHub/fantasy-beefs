/* ============================================================================
 * FantasyStakes — WP3C.2 · authoritative Versus market lines · browser suite
 *
 * Run through:  python test_wp3c2_versus_market_lines.py
 *
 * THE REAL PAGE, THE REAL BOARD ROUTE, THE REAL SIMULATION. The component suite
 * proves the composer renders whatever board it is handed. Only this tier can
 * prove the board a GM's browser actually receives from
 * `GET /league/{id}/versus/board` is the board that reaches the screen, that the
 * spread sign survives the trip, and that the wager the page finally posts
 * carries the line the page drew.
 *
 * THE NETWORK IS RECORDED, NOT FAKED, except where a section is explicitly
 * about what happens when the server disagrees with the page. Every figure
 * asserted below is compared against the response this page received.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

const SETTLE = 'await new Promise((r) => setTimeout(r, 700));';

/** Record board, quote and write traffic without altering any of it. */
const RECORD = `
  window.__fs = { boards: [], quotes: [], writes: [] };
  if (!window.__fsReal) window.__fsReal = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    if (url.includes('/beef/challenge')) {
      window.__fs.writes.push({ url, body: JSON.parse(init.body) });
    }
    const res = await window.__fsReal(input, init);
    if (url.includes('/versus/board')) {
      window.__fs.boards.push(await res.clone().json().catch(() => null));
    }
    if (url.includes('/versus/quote')) {
      window.__fs.quotes.push({
        status: res.status,
        request: JSON.parse(init.body),
        body: await res.clone().json().catch(() => null),
      });
    }
    return res;
  };
`;

/** Dismiss any open sheet, then open the composer from a Play card. */
const openFor = (teamId) => `
  {
    const stale = document.querySelector('#fs-sheet [data-fs-close]');
    if (stale && document.getElementById('fs-overlay').classList.contains('is-open')) {
      stale.click();
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
  document.querySelector(
    '#panel-league [data-card-action="challenge"][data-card-id="${teamId}"]').click();
`;

const READ_ECON = `
  const econ = document.querySelector('#fs-sheet [data-econ]');
  const node = econ ? econ.querySelector('[data-quote-state]') : null;
  return {
    state: node ? node.dataset.quoteState : null,
    text: econ ? econ.textContent.trim() : '',
    cents: econ ? [...econ.querySelectorAll('[data-exact-cents]')]
      .map((el) => Number(el.dataset.exactCents)) : [],
  };
`;

const typeStake = (dollars) => `
  {
    const field = document.getElementById('fs-stake-input');
    field.value = '${dollars}';
    field.dispatchEvent(new Event('input', { bubbles: true }));
  }
`;

await withPage({ port: 9463 }, async ({ evaluate, reload, setViewport }) => {

  /* ── What the server offers ───────────────────────────────────────────── */

  const served = await evaluate(`return (async () => {
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const league = me.capabilities.acting_league_id;
    const ctx = await (await fetch('/league/' + league + '/context/me',
      { credentials: 'same-origin' })).json();
    const board = await (await fetch(
      '/league/' + league + '/versus/board?week=' + ctx.current_week,
      { credentials: 'same-origin' })).json();
    return { league, week: ctx.current_week, board,
             actingTeamId: me.capabilities.acting_team_id };
  })();`);

  const priced = served.board.markets.find((m) => m.available);
  const unpriced = served.board.markets.find((m) => !m.available);

  section('Board · the server offers a real, signed market');

  check('the board serves for the authoritative week',
    served.board.week === served.week, String(served.board.week));
  check('with a priceable pairing', Boolean(priced),
    priced ? priced.opponent_name : 'none');
  check('and an unpriceable one, so both card states are reachable',
    Boolean(unpriced), unpriced ? unpriced.opponent_name : 'none');

  if (!priced || !unpriced) return;

  check('the spread sits on a half point and is not a hooked pick’em',
    (priced.spread_line * 2) % 1 === 0, String(priced.spread_line));
  check('the total sits on a half point and is a real fantasy score',
    (priced.total_line * 2) % 1 === 0 && priced.total_line > 50,
    String(priced.total_line));
  check('the acting side’s displayed spread is the canonical line negated',
    priced.acting_spread === -priced.spread_line,
    `canonical ${priced.spread_line} → shown ${priced.acting_spread}`);
  check('the moneyline and the spread agree about who the favourite is',
    (priced.acting_moneyline < 0) === (priced.acting_spread < 0),
    `${priced.acting_moneyline} / ${priced.acting_spread}`);

  /* ── §12 · the Play card ──────────────────────────────────────────────── */

  section('§12 · The Play card draws the served board');

  const cards = await evaluate(`return (async () => {
    ${RECORD}
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    const panel = document.getElementById('panel-league');
    return [...panel.querySelectorAll('[data-card-action="challenge"]')].map((c) => ({
      id: Number(c.dataset.cardId),
      labels: [...c.querySelectorAll('.fs-market__label')].map((e) => e.textContent),
      values: [...c.querySelectorAll('.fs-market__value')].map((e) => e.textContent),
      order: [...c.children].map((e) => e.className.split(' ')[0]),
      headOrder: [...c.querySelector('.fs-wcard__head')
        .querySelectorAll('.fs-wcard__identity, .fs-wcard__context')]
        .map((e) => e.className.split(' ')[0]),
      clipped: c.scrollHeight > c.clientHeight + 1,
    }));
  })();`);

  const pricedCard = cards.find((c) => c.id === priced.opponent_team_id);
  const unpricedCard = cards.find((c) => c.id === unpriced.opponent_team_id);

  check('the locked market order survives',
    pricedCard.labels.join(' | ') === 'ML | SPR | O/U',
    pricedCard.labels.join(' | '));
  check('the card hierarchy is still identity → preview → markets',
    pricedCard.order.join(' → ')
      === 'fs-wcard__head → fs-previewrow → fs-markets',
    pricedCard.order.join(' → '));
  check('and the head still reads opponent, then owner',
    pricedCard.headOrder.join(' → ')
      === 'fs-wcard__identity → fs-wcard__context',
    pricedCard.headOrder.join(' → '));
  check('ML shows the SERVED moneyline for the acting team',
    pricedCard.values[0] === String(priced.acting_moneyline),
    `${pricedCard.values[0]} vs served ${priced.acting_moneyline}`);
  check('SPR shows the SERVED sportsbook spread, sign and all',
    pricedCard.values[1].replace('−', '-')
      === (priced.acting_spread > 0 ? `+${Math.abs(priced.acting_spread).toFixed(1)}`
        : `-${Math.abs(priced.acting_spread).toFixed(1)}`),
    `${pricedCard.values[1]} vs served ${priced.acting_spread}`);
  check('O/U shows the SERVED total',
    pricedCard.values[2] === priced.total_line.toFixed(1),
    `${pricedCard.values[2]} vs served ${priced.total_line}`);
  check('an unpriceable card shows three dashes, not three zeroes',
    unpricedCard.values.every((v) => v === '—'),
    unpricedCard.values.join(' | '));
  check('and no card clips its own content at this size',
    cards.every((c) => !c.clipped));

  /* ── §13 · the spread composer ────────────────────────────────────────── */

  section('§13 · The spread composer states the market in words');

  const spread = await evaluate(`return (async () => {
    ${openFor(priced.opponent_team_id)}
    await new Promise((r) => setTimeout(r, 400));
    document.querySelector('#fs-sheet [data-composer-market="spread"]').click();
    await new Promise((r) => setTimeout(r, 250));
    const sheet = document.getElementById('fs-sheet');
    const detail = sheet.querySelector('[data-market-detail="spread"]');
    const cells = [...sheet.querySelectorAll('.fs-seg--market .fs-seg__value')]
      .map((e) => e.textContent);
    ${typeStake('20')}
    ${SETTLE}
    const econ = (() => { ${READ_ECON} })();
    return {
      cells,
      detail: detail ? detail.textContent : null,
      exactLine: detail ? detail.querySelector('[data-exact-line]').dataset.exactLine : null,
      hasLineInput: Boolean(sheet.querySelector('input[data-composer-line], [data-composer-line]')),
      econ,
      net: window.__fs,
    };
  })();`);

  check('the composer’s own market cells match the card',
    spread.cells[1] === pricedCard.values[1]
    && spread.cells[2] === pricedCard.values[2],
    spread.cells.join(' | '));
  check('the detail row carries the exact served display line',
    Number(spread.exactLine) === priced.acting_spread,
    `${spread.exactLine} vs ${priced.acting_spread}`);
  check('and says which team is giving the points',
    /gives [\d.]+ points to /.test(spread.detail), spread.detail);
  check('there is no free-form line field anywhere',
    spread.hasLineInput === false);

  const spreadQuote = spread.net.quotes[spread.net.quotes.length - 1];
  check('the quote request asserted the CANONICAL line, not the display one',
    spreadQuote.request.line === priced.spread_line,
    `sent ${spreadQuote.request.line}, canonical ${priced.spread_line}`);
  check('the server accepted it and priced the spread',
    spreadQuote.status === 200, String(spreadQuote.status));
  check('and the price it returned is for that same line',
    spreadQuote.body.line === priced.spread_line
    && spreadQuote.body.display_line === priced.acting_spread,
    `${spreadQuote.body.line} / ${spreadQuote.body.display_line}`);
  check('the economics drawn are the served integers, to the cent',
    spread.econ.state === 'ready'
    && spread.econ.cents[0] === spreadQuote.body.your_stake_cents
    && spread.econ.cents[1] === spreadQuote.body.opponent_stake_cents
    && spread.econ.cents[2] === spreadQuote.body.pot_cents,
    JSON.stringify(spread.econ.cents));

  /* ── §14 · the over/under composer ────────────────────────────────────── */

  section('§14 · A total is not priced until the GM picks a side');

  const ou = await evaluate(`return (async () => {
    document.querySelector('#fs-sheet [data-composer-market="ou"]').click();
    await new Promise((r) => setTimeout(r, 250));
    const sheet = document.getElementById('fs-sheet');
    const detail = sheet.querySelector('[data-market-detail="ou"]');
    const before = (() => { ${READ_ECON} })();
    // READ NOW, NOT AT RETURN. These are live DOM nodes and the sides are
    // clicked further down; capturing the ELEMENT and reading its disabled
    // flag at the end would report the state after a side was chosen, which
    // is the opposite of what this section claims.
    const sendDisabled = sheet.querySelector('[data-composer-send]').disabled;
    const why = sheet.querySelector('[data-send-why]').textContent;
    const sides = [...sheet.querySelectorAll('[data-composer-side]')].map((b) => ({
      side: b.dataset.composerSide,
      pressed: b.getAttribute('aria-pressed'),
      height: Math.round(b.getBoundingClientRect().height),
    }));
    const quotesBefore = window.__fs.quotes.length;
    ${SETTLE}
    const stillIdle = (() => { ${READ_ECON} })();

    document.querySelector('#fs-sheet [data-composer-side="over"]').click();
    ${SETTLE}
    const afterOver = (() => { ${READ_ECON} })();
    document.querySelector('#fs-sheet [data-composer-side="under"]').click();
    const instant = (() => { ${READ_ECON} })();
    ${SETTLE}
    const afterUnder = (() => { ${READ_ECON} })();
    return {
      detail: detail ? detail.textContent : null,
      exactLine: detail ? detail.querySelector('[data-exact-line]').dataset.exactLine : null,
      before, stillIdle, sides, quotesBefore, sendDisabled, why,
      afterOver, instant, afterUnder,
      net: window.__fs,
    };
  })();`);

  check('the total shown is the served total',
    Number(ou.exactLine) === priced.total_line,
    `${ou.exactLine} vs ${priced.total_line}`);
  check('both sides are offered and NEITHER is pre-selected',
    ou.sides.length === 2
    && ou.sides.every((s) => s.pressed === 'false'),
    JSON.stringify(ou.sides.map((s) => `${s.side}:${s.pressed}`)));
  check('each side is a real 44px tap target',
    ou.sides.every((s) => s.height >= 44),
    ou.sides.map((s) => s.height).join(','));
  check('Send is disabled until a side is chosen',
    ou.sendDisabled === true && /Over or Under/i.test(ou.why), ou.why);
  check('nothing is priced while no side is held',
    ou.stillIdle.cents.length === 0, ou.stillIdle.state);
  check('and no quote was even requested for an unsided total',
    ou.net.quotes.length > ou.quotesBefore
      ? ou.net.quotes[ou.quotesBefore].request.side !== null : true,
    'no sideless request');

  const overQ = ou.net.quotes.find((q) => q.request.side === 'over');
  const underQ = ou.net.quotes.find((q) => q.request.side === 'under');
  check('choosing Over prices the wager',
    ou.afterOver.state === 'ready' && Boolean(overQ),
    ou.afterOver.state);
  check('against the served total, asserted back',
    overQ.request.line === priced.total_line
    && overQ.body.line === priced.total_line,
    `${overQ.request.line} / ${overQ.body.line}`);
  check('switching to Under retires the Over price instantly',
    ou.instant.cents.length === 0, ou.instant.state);
  check('and prices the OTHER side of the same total',
    ou.afterUnder.state === 'ready'
    && underQ.body.line === overQ.body.line
    && underQ.body.anchor_moneyline !== overQ.body.anchor_moneyline,
    `over ${overQ.body.anchor_moneyline} vs under ${underQ.body.anchor_moneyline}`);
  check('the displayed figures are the Under quote’s own cents',
    ou.afterUnder.cents[2] === underQ.body.pot_cents,
    `${ou.afterUnder.cents[2]} vs ${underQ.body.pot_cents}`);

  /* ── §16 · the unavailable market ─────────────────────────────────────── */

  section('§16 · An unpriceable market says so, and shows no figure');

  const gap = await evaluate(`return (async () => {
    ${openFor(unpriced.opponent_team_id)}
    await new Promise((r) => setTimeout(r, 400));
    document.querySelector('#fs-sheet [data-composer-market="spread"]').click();
    await new Promise((r) => setTimeout(r, 250));
    const sheet = document.getElementById('fs-sheet');
    const detail = sheet.querySelector('[data-market-detail]');
    ${typeStake('20')}
    ${SETTLE}
    return {
      detail: detail ? detail.textContent : null,
      kind: detail ? detail.dataset.marketDetail : null,
      hasLine: Boolean(sheet.querySelector('[data-exact-line]')),
      sendDisabled: sheet.querySelector('[data-composer-send]').disabled,
      econ: (() => { ${READ_ECON} })(),
      sheetText: sheet.textContent,
    };
  })();`);

  check('the composer states why there is no market',
    gap.kind === 'unavailable' && /starting lineup/i.test(gap.detail || ''),
    gap.detail);
  check('with no line drawn at all', gap.hasLine === false);
  check('no zero, no PK and no EVEN stand in for a line',
    !/\bPK\b|\bEVEN\b/.test(gap.sheetText)
    && !/SPR\s*0\.0|O\/U\s*0\.0/.test(gap.sheetText));
  check('Send is disabled', gap.sendDisabled === true);
  check('and no economics are shown', gap.econ.cents.length === 0);

  /* ── §10 · what the page finally posts ────────────────────────────────── */

  await reload();

  section('§10 · The wager posted carries the line the page drew');

  const sent = await evaluate(`return (async () => {
    ${RECORD}
    const recording = window.fetch;
    // THE WRITE IS RECORDED AND REFUSED. What is certified is WHAT the page
    // asks for; issuing it would post escrow this suite has no business
    // creating, and the server-side parity is proven by the Python tier.
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (url.includes('/beef/challenge')) {
        window.__fs.writes.push({ url, body: JSON.parse(init.body) });
        return new Response(JSON.stringify({ detail: 'not sent by the suite' }),
          { status: 409, headers: { 'Content-Type': 'application/json' } });
      }
      return recording(input, init);
    };

    ${openFor(priced.opponent_team_id)}
    await new Promise((r) => setTimeout(r, 400));
    document.querySelector('#fs-sheet [data-composer-market="spread"]').click();
    await new Promise((r) => setTimeout(r, 250));
    ${typeStake('20')}
    ${SETTLE}
    const priceState = (() => { ${READ_ECON} })();
    const send = document.querySelector('#fs-sheet [data-composer-send]');
    const enabled = !send.disabled;
    if (enabled) send.click();
    await new Promise((r) => setTimeout(r, 600));

    document.querySelector('#fs-sheet [data-composer-market="ou"]').click();
    await new Promise((r) => setTimeout(r, 250));
    document.querySelector('#fs-sheet [data-composer-side="under"]').click();
    ${SETTLE}
    const s2 = document.querySelector('#fs-sheet [data-composer-send]');
    if (!s2.disabled) s2.click();
    await new Promise((r) => setTimeout(r, 600));
    return { priceState, enabled, net: window.__fs };
  })();`);

  check('the spread is priced before Send is offered',
    sent.priceState.state === 'ready' && sent.enabled === true,
    `${sent.priceState.state}, send ${sent.enabled}`);
  check('two wagers were posted, to the WRITE route',
    sent.net.writes.length === 2
    && sent.net.writes.every((w) => w.url.includes('/beef/challenge')),
    String(sent.net.writes.length));

  const spreadWrite = sent.net.writes.find((w) => w.body.bet_type === 'spread');
  const ouWrite = sent.net.writes.find((w) => w.body.bet_type === 'over_under');
  check('the spread wager carries the CANONICAL line, unchanged',
    spreadWrite && spreadWrite.body.line === priced.spread_line,
    spreadWrite ? String(spreadWrite.body.line) : 'not posted');
  check('and no side, because a spread has none',
    spreadWrite.body.side === null);
  check('the total wager carries the served total and the chosen side',
    ouWrite && ouWrite.body.line === priced.total_line
    && ouWrite.body.side === 'under',
    ouWrite ? `${ouWrite.body.line} ${ouWrite.body.side}` : 'not posted');
  check('neither carries a single economic figure from the quote',
    sent.net.writes.every((w) => !('pot_cents' in w.body)
      && !('opponent_stake_cents' in w.body) && !('anchor_odds' in w.body)
      && !('anchor_moneyline' in w.body)),
    Object.keys(spreadWrite.body).join(', '));
  check('DISPLAYED == QUOTED == SUBMITTED for the spread',
    Number(spread.exactLine) === -spreadWrite.body.line
    && sent.net.quotes.some((q) => q.request.line === spreadWrite.body.line),
    `shown ${spread.exactLine}, submitted ${spreadWrite.body.line}`);

  /* ── §12 · a market that moved ────────────────────────────────────────── */

  await reload();

  section('§27 · A market that moves is refused, not silently repriced');

  const refused = await evaluate(`return (async () => {
    ${RECORD}
    // A STALE ASSERTION, WHICH IS WHAT A MOVED MARKET LOOKS LIKE FROM THE
    // SERVER'S SIDE. The board the page drew is shifted on its way OUT, in the
    // quote request only — so the page is asserting a line the authority does
    // not currently offer, exactly as it would if projections had refreshed
    // between the board read and the keystroke. Nothing about the response is
    // faked: the refusal below is the route's own.
    const recording = window.fetch;
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (!url.includes('/versus/quote')) return recording(input, init);
      const body = JSON.parse(init.body);
      if (typeof body.line === 'number') body.line += 2;
      return recording(input, { ...init, body: JSON.stringify(body) });
    };

    ${openFor(priced.opponent_team_id)}
    await new Promise((r) => setTimeout(r, 400));
    document.querySelector('#fs-sheet [data-composer-market="spread"]').click();
    await new Promise((r) => setTimeout(r, 250));
    ${typeStake('20')}
    ${SETTLE}
    const econ = (() => { ${READ_ECON} })();
    return { econ, net: window.__fs };
  })();`);

  const movedQuote = refused.net.quotes[refused.net.quotes.length - 1];
  check('the page asserted a line the authority is not offering',
    movedQuote && movedQuote.request.line === priced.spread_line + 2,
    movedQuote ? String(movedQuote.request.line) : 'no quote');
  check('the server REFUSED it rather than pricing a market it does not offer',
    movedQuote.status === 409
    && movedQuote.body.detail.reason_code === 'market_moved',
    `${movedQuote.status} ${JSON.stringify(movedQuote.body.detail)}`);
  check('and the composer shows the refusal, not stale economics',
    refused.econ.state === 'refused' && refused.econ.cents.length === 0,
    refused.econ.text.slice(0, 100));
  check('in product language, with no reason code on screen',
    !/market_moved|409/.test(refused.econ.text), refused.econ.text.slice(0, 100));

  /* ── §18 · the Preview is still analysis ──────────────────────────────── */

  await reload();

  section('§18 · Matchup Preview did not become a second market');

  const preview = await evaluate(`return (async () => {
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    document.querySelector('#panel-league [data-preview-opponent]').click();
    await new Promise((r) => setTimeout(r, 400));
    const sheet = document.getElementById('fs-sheet');
    return {
      titles: [...sheet.querySelectorAll('.fs-prev__title')].map((e) => e.textContent),
      hasMarkets: Boolean(sheet.querySelector('.fs-market, [data-market], [data-composer-side]')),
      text: sheet.textContent,
    };
  })();`);

  // UIRECON WAVE 4A — MATCHUP BECAME ON OFFER, and the order is otherwise the
  // one this suite locked. The old first block was a label/value pair naming the
  // two teams, which the sheet subtitle already carried — two statements of one
  // fact, and the second of them was the one a GM read first. That slot now
  // carries the MARKET the GM is being offered, which is the thing the analysis
  // below it explains and the thing the sheet could not previously name.
  check('the locked analysis order is intact',
    preview.titles.join(' → ')
      === 'ON OFFER → WHY THE LINE LOOKS THIS WAY → THE READ → LINEUPS',
    preview.titles.join(' → '));
  check('and it carries no market cells and no Over/Under control',
    preview.hasMarkets === false);
  check('nor a sportsbook terms block',
    !/SPORTSBOOK/i.test(preview.text));

  /* ── §31 · phone geometry ─────────────────────────────────────────────── */

  section('§31 · The market figures did not cost the card its fit');

  for (const [width, height] of [[375, 667], [390, 844], [430, 932],
    [320, 568]]) {
    await setViewport(width, height);
    const m = await evaluate(`
      document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
      const panel = document.getElementById('panel-league');
      const cards = [...panel.querySelectorAll('.fs-wcard')];
      return {
        docW: document.documentElement.scrollWidth,
        innerW: window.innerWidth,
        clipped: cards.filter((c) => c.scrollHeight > c.clientHeight + 1).length,
        truncated: [...panel.querySelectorAll('.fs-market__value')]
          .filter((v) => v.scrollWidth > v.clientWidth + 1).length,
      };
    `);
    check(`${width}: the page does not scroll horizontally`,
      m.docW <= m.innerW, `${m.docW} vs ${m.innerW}`);
    check(`${width}: no market value is clipped by its own cell`,
      m.truncated === 0, `${m.truncated} truncated`);
    if (width >= 375) {
      check(`${width}: no wager card clips its own content`,
        m.clipped === 0, `${m.clipped} clipping`);
    } else {
      // 320x568 belongs to WP3E. Measured for information so the carry-forward
      // carries a number rather than an assumption.
      check(`${width}: measured below the certified set — ${m.clipped} clipping`,
        true, 'reported, not gated');
    }
  }

  await setViewport(390, 844);
});

finish('WP3C.2 AUTHORITATIVE VERSUS MARKET LINES — BROWSER');
