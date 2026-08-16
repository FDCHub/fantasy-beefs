/* ============================================================================
 * FantasyStakes — WP3C.1 · the authoritative Versus quote · browser suite
 *
 * Run through:  python test_wp3c1_versus_quote.py
 *
 * THE REAL APPLICATION, THE REAL ROUTE, THE REAL SESSION. The component suite
 * drives the composer against a stub and can prove what the composer DOES with
 * an answer; it cannot prove that the answer a GM's browser actually receives
 * from `/league/{id}/versus/quote` is the one that reaches the screen. That is
 * the claim WP3C.1 §15 asks for, and it needs a page, a cookie and a server.
 *
 * HOW THE NETWORK IS CONTROLLED. `window.fetch` is wrapped, per section, to do
 * one of three things to quote traffic and NOTHING to anything else:
 *
 *   record   pass through and keep the served body verbatim, so the DOM can be
 *            compared against the exact integers the server sent rather than
 *            against a second request that Monte Carlo need not answer the
 *            same way;
 *   park     hold responses so the suite decides the ORDER they resolve in,
 *            which is the only way to make a stale answer arrive late on
 *            purpose;
 *   tamper   return a body whose figures are deliberately INCONSISTENT with
 *            each other — a pot that is not the two stakes added up. A
 *            renderer draws it as sent. Anything that recomputes disagrees,
 *            and disagreeing is the failure.
 *
 * The wrapper is a network condition, not a product stub: the composer, the
 * command module, the CSRF header and the route are all the shipped ones.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

/** Give the debounce, the request and the redraw time to complete. */
const SETTLE = `await new Promise((r) => setTimeout(r, 700));`;

/**
 * Install the recording fetch wrapper.
 *
 * Everything the page asks for still goes to the server. Quote traffic is
 * additionally cloned into `window.__fsQuote`, so an assertion can name the
 * exact body this page received.
 */
const RECORD = `
  window.__fsQuote = { requests: [], responses: [], writes: [] };
  if (!window.__fsRealFetch) window.__fsRealFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    if (url.includes('/versus/quote')) {
      window.__fsQuote.requests.push(JSON.parse(init.body));
    }
    if (url.includes('/beef/challenge') || url.includes('/beef/counter')) {
      window.__fsQuote.writes.push({ url, body: JSON.parse(init.body) });
    }
    const res = await window.__fsRealFetch(input, init);
    if (url.includes('/versus/quote')) {
      const copy = res.clone();
      window.__fsQuote.responses.push({
        status: copy.status, body: await copy.json().catch(() => null),
      });
    }
    return res;
  };
`;

/** Open the composer for a given opponent team id, from the Play card. */
const openFor = (teamId) => `
  // ANY OPEN SHEET IS DISMISSED FIRST. The overlay covers the tab bar, so a
  // section that inherits a composer from the one before it would otherwise
  // click straight into the scrim and measure the sheet it meant to replace.
  const stale = document.querySelector('#fs-sheet [data-fs-close]');
  if (stale && document.getElementById('fs-overlay').classList.contains('is-open')) {
    stale.click();
    await new Promise((r) => setTimeout(r, 200));
  }
  document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
  const card = document.querySelector(
    '#panel-league [data-card-action="challenge"][data-card-id="${teamId}"]');
  if (!card) return { opened: false };
  card.click();
`;

/** Read the composer's economics block, whatever state it is in. */
const READ_ECON = `
  const sheet = document.getElementById('fs-sheet');
  const econ = sheet.querySelector('[data-econ]');
  const node = econ ? econ.querySelector('[data-quote-state]') : null;
  return {
    open: document.getElementById('fs-overlay').classList.contains('is-open'),
    state: node ? node.dataset.quoteState : null,
    text: econ ? econ.textContent.trim() : '',
    cents: econ ? [...econ.querySelectorAll('[data-exact-cents]')]
      .map((el) => Number(el.dataset.exactCents)) : [],
    labels: econ ? [...econ.querySelectorAll('.fs-econ__label')]
      .map((el) => el.textContent) : [],
    values: econ ? [...econ.querySelectorAll('.fs-econ__value')]
      .map((el) => el.textContent) : [],
  };
`;

/** Type a stake the way a GM does — a real input event on the real field. */
const typeStake = (dollars) => `
  // BLOCK-SCOPED, so a section may type more than once without redeclaring.
  {
    const field = document.getElementById('fs-stake-input');
    field.value = '${dollars}';
    field.dispatchEvent(new Event('input', { bubbles: true }));
  }
`;

await withPage({ port: 9457 }, async ({ evaluate, reload }) => {

  /* ── Who the server says is here ──────────────────────────────────────── */

  const served = await evaluate(`return (async () => {
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    const league = me.capabilities.acting_league_id;
    const action = await (await fetch('/league/' + league + '/action/me',
      { credentials: 'same-origin' })).json();
    const ctx = await (await fetch('/league/' + league + '/context/me',
      { credentials: 'same-origin' })).json();
    return {
      league,
      week: ctx.current_week,
      opponents: action.opponents.map((o) => ({ id: o.team_id, name: o.team_name })),
    };
  })();`);

  const priceable = served.opponents.find((o) => o.name === 'The Braintrust');
  const unpriceable = served.opponents.find((o) => o.name === 'No Lineup');

  section('Fixture · the league offers one priceable and one unpriceable target');
  check('the session is bound to a league that states a week',
    typeof served.league === 'number' && served.week === 5,
    `league ${served.league}, week ${served.week}`);
  check('a fully rostered opponent is offered', Boolean(priceable),
    priceable ? `#${priceable.id}` : 'absent');
  check('and one with no starting lineup, so the refusal path is reachable',
    Boolean(unpriceable), unpriceable ? `#${unpriceable.id}` : 'absent');

  // Without both, every claim below would be vacuous rather than false. The
  // three checks above have already recorded the failure; stopping here keeps
  // the run from reporting a page of green that measured nothing.
  if (!priceable || !unpriceable) return;

  /* ── A · nothing is priced before there is enough to price ────────────── */

  section('§15A · No economics before there is enough to quote');

  const idle = await evaluate(`return (async () => {
    ${RECORD}
    ${openFor(priceable.id)}
    ${SETTLE}
    ${READ_ECON}
  })();`);

  check('the composer opens', idle.open === true);
  check('and shows no figure at all — no market chosen, no stake typed',
    idle.state === 'idle' && idle.cents.length === 0,
    `${idle.state}, ${idle.cents.length} figures`);
  check('it says what is missing rather than showing a blank',
    /Pick a market and enter a stake/.test(idle.text), idle.text.slice(0, 80));
  check('and NOTHING was asked of the pricing route',
    (await evaluate('return window.__fsQuote.requests.length;')) === 0);

  const marketOnly = await evaluate(`return (async () => {
    document.querySelector('#fs-sheet [data-composer-market="ml"]').click();
    ${SETTLE}
    ${READ_ECON}
  })();`);
  check('a market alone still prices nothing',
    marketOnly.cents.length === 0 && marketOnly.state === 'idle',
    `${marketOnly.state}, ${marketOnly.cents.length} figures`);
  check('and still nothing was asked',
    (await evaluate('return window.__fsQuote.requests.length;')) === 0);

  /* ── B/C · the quote, and the figures it puts on screen ───────────────── */

  section('§15B/C · A stake completes the inputs, and the SERVER answers');

  const ready = await evaluate(`return (async () => {
    ${typeStake('20')}
    ${SETTLE}
    const dom = (() => { ${READ_ECON} })();
    return { dom, net: window.__fsQuote };
  })();`);

  check('exactly one quote was requested', ready.net.requests.length === 1,
    `${ready.net.requests.length} requests`);
  const req = ready.net.requests[0] || {};
  check('carrying the chosen opponent, the authoritative week and the market',
    req.opponent_team_id === priceable.id && req.week === served.week
    && req.bet_type === 'straight' && req.challenge_mode === 'locked',
    JSON.stringify(req));
  check('and the GM’s own stake, in the same units the write path takes',
    req.amount === 20, String(req.amount));
  check('the server priced it', ready.net.responses[0]
    && ready.net.responses[0].status === 200,
    ready.net.responses[0] ? String(ready.net.responses[0].status) : 'none');

  const body = (ready.net.responses[0] || {}).body || {};
  check('the surface shows the priced state',
    ready.dom.state === 'ready', String(ready.dom.state));
  check('with the five governed rows, in the certified order',
    ready.dom.labels.join(' | ')
      === 'Your stake | Opponent stake | Pot | You win | You lose',
    ready.dom.labels.join(' | '));
  check('EVERY displayed figure is the exact integer the server sent',
    ready.dom.cents.length === 5
    && ready.dom.cents[0] === body.your_stake_cents
    && ready.dom.cents[1] === body.opponent_stake_cents
    && ready.dom.cents[2] === body.pot_cents
    && ready.dom.cents[3] === body.win_cents
    && ready.dom.cents[4] === body.lose_cents,
    `${JSON.stringify(ready.dom.cents)} vs served `
    + `${JSON.stringify([body.your_stake_cents, body.opponent_stake_cents,
      body.pot_cents, body.win_cents, body.lose_cents])}`);
  check('the anchor stake shown is the one the GM typed',
    body.your_stake_cents === 2000, String(body.your_stake_cents));
  check('and the served odds are a real price, not even money',
    body.anchor_odds !== body.derived_odds
    && body.anchor_moneyline !== -110,
    `${body.anchor_moneyline} / ${body.derived_moneyline}`);

  /* ── D/E/F · every quote-sensitive change drops the old price ─────────── */

  section('§15D/E/F · Changing an input retires the price it was for');

  const stakeChanged = await evaluate(`return (async () => {
    ${typeStake('55')}
    // READ IMMEDIATELY. The claim is that the previous pot is not left on
    // screen beside the new stake even for a frame, so this must not wait.
    const instant = (() => { ${READ_ECON} })();
    ${SETTLE}
    const after = (() => { ${READ_ECON} })();
    return { instant, after, net: window.__fsQuote };
  })();`);

  check('D · the old figures vanish the moment the stake does',
    stakeChanged.instant.cents.length === 0
    && stakeChanged.instant.state !== 'ready',
    `${stakeChanged.instant.state}, ${stakeChanged.instant.cents.length} figures`);
  check('and a fresh quote is requested for the new stake',
    stakeChanged.net.requests.length === 2
    && stakeChanged.net.requests[1].amount === 55,
    JSON.stringify(stakeChanged.net.requests.map((r) => r.amount)));
  check('which the surface then draws, again to the cent',
    stakeChanged.after.state === 'ready'
    && stakeChanged.after.cents[0]
       === stakeChanged.net.responses[1].body.your_stake_cents
    && stakeChanged.after.cents[0] === 5500,
    JSON.stringify(stakeChanged.after.cents));

  const marketChanged = await evaluate(`return (async () => {
    document.querySelector('#fs-sheet [data-composer-market="ou"]').click();
    const instant = (() => { ${READ_ECON} })();
    ${SETTLE}
    const after = (() => { ${READ_ECON} })();
    return { instant, after, net: window.__fsQuote };
  })();`);

  check('E · changing the market retires the price too',
    marketChanged.instant.cents.length === 0,
    `${marketChanged.instant.state}, ${marketChanged.instant.cents.length} figures`);
  // WP3C.2 ADDED A FOURTH LEGITIMATE OUTCOME. A total now has an authoritative
  // line but still needs the GM to pick Over or Under, so the honest state
  // immediately after switching to O/U is IDLE — nothing has been chosen yet
  // and nothing is asked of the server. The claim is unchanged and is the one
  // that always mattered: whatever is drawn is a state the server or the
  // composer can justify, and never the previous market's figures.
  check('and whatever the server then says is what is drawn',
    (marketChanged.after.state === 'ready'
     && marketChanged.after.cents.length === 5)
    || (marketChanged.after.state !== 'ready'
        && marketChanged.after.cents.length === 0),
    `${marketChanged.after.state} — ${marketChanged.after.text.slice(0, 90)}`);

  // Back to a market that prices, so the opponent claim starts from a price.
  await evaluate(`return (async () => {
    document.querySelector('#fs-sheet [data-composer-market="ml"]').click();
    ${SETTLE}
    return true;
  })();`);

  const opponentChanged = await evaluate(`return (async () => {
    const before = (() => { ${READ_ECON} })();
    document.querySelector(
      '#fs-sheet [data-composer-opponent="${unpriceable.id}"]').click();
    const instant = (() => { ${READ_ECON} })();
    ${SETTLE}
    const after = (() => { ${READ_ECON} })();
    return { before, instant, after };
  })();`);

  check('F · the price for the previous opponent goes the instant they do',
    opponentChanged.before.cents.length === 5
    && opponentChanged.instant.cents.length === 0,
    `${opponentChanged.before.cents.length} → ${opponentChanged.instant.cents.length}`);

  /* ── H · the refusal is a product sentence ────────────────────────────── */

  section('§15H · A refusal is rendered as product language');

  check('the unpriceable opponent is refused, on screen',
    opponentChanged.after.state === 'refused',
    `${opponentChanged.after.state} — ${opponentChanged.after.text.slice(0, 90)}`);
  check('in a sentence a GM can act on',
    /starting lineup/i.test(opponentChanged.after.text),
    opponentChanged.after.text.slice(0, 120));
  check('with no reason code, status or internal identifier on screen',
    !/roster_unavailable|409|home_starters|Traceback|Error:/
      .test(opponentChanged.after.text),
    opponentChanged.after.text.slice(0, 120));
  check('and no figure beside it — a refusal prices nothing',
    opponentChanged.after.cents.length === 0);

  /* ── G · a stale answer cannot overwrite a newer one ──────────────────── */

  await reload();

  section('§15G · A late answer for an abandoned stake is discarded');

  const stale = await evaluate(`return (async () => {
    ${RECORD}
    // PARK QUOTE RESPONSES. Each is resolved by hand below, so the ORDER they
    // arrive in is the suite's choice rather than the network's luck.
    const parked = [];
    window.__fsParked = parked;
    const passthrough = window.fetch;
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (!url.includes('/versus/quote')) return passthrough(input, init);
      const res = await passthrough(input, init);
      return new Promise((release) => {
        parked.push({ body: JSON.parse(init.body), release: () => release(res) });
      });
    };

    ${openFor(priceable.id)}
    await new Promise((r) => setTimeout(r, 400));
    document.querySelector('#fs-sheet [data-composer-market="ml"]').click();
    await new Promise((r) => setTimeout(r, 200));

    ${typeStake('20')}
    await new Promise((r) => setTimeout(r, 400));
    ${typeStake('90')}
    await new Promise((r) => setTimeout(r, 400));

    const parkedStakes = parked.map((p) => p.body.amount);

    // FOUND BY THE STAKE THEY WERE ASKED FOR, not by arrival order. Which
    // request the server answers first is exactly the thing this section
    // refuses to depend on, so the suite must not depend on it either.
    const abandoned = parked.find((p) => p.body.amount === 20);
    const current = parked.find((p) => p.body.amount === 90);

    // THE NEWER ONE LANDS FIRST, then the abandoned one arrives late.
    if (abandoned && current) {
      current.release();
      await new Promise((r) => setTimeout(r, 400));
      const afterNew = (() => { ${READ_ECON} })();
      abandoned.release();
      await new Promise((r) => setTimeout(r, 500));
      const afterStale = (() => { ${READ_ECON} })();
      return { parkedStakes, afterNew, afterStale };
    }
    return { parkedStakes, afterNew: null, afterStale: null };
  })();`);

  check('two quotes really were in flight at once',
    stale.parkedStakes.length >= 2,
    JSON.stringify(stale.parkedStakes));
  if (stale.afterNew) {
    check('the newer answer is drawn when it lands',
      stale.afterNew.state === 'ready' && stale.afterNew.cents[0] === 9000,
      `${stale.afterNew.state}, ${JSON.stringify(stale.afterNew.cents)}`);
    check('and the abandoned $20 answer, arriving late, CHANGES NOTHING',
      stale.afterStale.state === 'ready' && stale.afterStale.cents[0] === 9000,
      `${stale.afterStale.state}, ${JSON.stringify(stale.afterStale.cents)}`);
    check('the $20 pot never reappears under the $90 stake',
      stale.afterStale.cents.every((c, i) => c === stale.afterNew.cents[i]),
      `${JSON.stringify(stale.afterNew.cents)} → ${JSON.stringify(stale.afterStale.cents)}`);
  }

  /* ── I · the page renders the server's figures, it does not derive them ─ */

  await reload();

  section('§15I · The page is a renderer — a deliberately inconsistent quote '
    + 'is drawn AS SENT');

  const tampered = await evaluate(`return (async () => {
    if (!window.__fsRealFetch) window.__fsRealFetch = window.fetch.bind(window);
    // A BODY NO PRICING MODEL WOULD PRODUCE. The pot is not the two stakes
    // added up and the win is not the opponent's stake. Every figure is a
    // distinct, recognisable integer, so whichever one the page draws names
    // exactly which field it read.
    window.__fsTampered = {
      your_stake_cents: 1111, opponent_stake_cents: 2222,
      pot_cents: 7777, win_cents: 4444, lose_cents: 5555,
      anchor_odds: 3.5, derived_odds: 1.4,
      anchor_moneyline: 250, derived_moneyline: -250, is_ceiling: false,
      league_id: ${served.league}, acting_team_id: 0,
      opponent_team_id: ${priceable.id}, week: ${served.week},
      market: 'straight', mode: 'locked',
    };
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (!url.includes('/versus/quote')) return window.__fsRealFetch(input, init);
      return new Response(JSON.stringify(window.__fsTampered), {
        status: 200, headers: { 'Content-Type': 'application/json' } });
    };

    ${openFor(priceable.id)}
    await new Promise((r) => setTimeout(r, 400));
    document.querySelector('#fs-sheet [data-composer-market="ml"]').click();
    await new Promise((r) => setTimeout(r, 200));
    ${typeStake('11')}
    ${SETTLE}
    ${READ_ECON}
  })();`);

  check('the pot shown is the SERVED pot, not the two stakes added up',
    tampered.cents[2] === 7777, String(tampered.cents[2]));
  check('the win shown is the SERVED win, not derived from the odds',
    tampered.cents[3] === 4444, String(tampered.cents[3]));
  check('the opponent stake is the SERVED one, not the moneyline applied',
    tampered.cents[1] === 2222, String(tampered.cents[1]));
  check('even the GM’s OWN stake is read back from the server',
    tampered.cents[0] === 1111, String(tampered.cents[0]));
  check('and the loss is the served figure too',
    tampered.cents[4] === 5555, String(tampered.cents[4]));
  check('no arithmetic combination of the served figures appears anywhere',
    !/3333|9999|6666|1100/.test(tampered.text), tampered.text.slice(0, 140));

  /* ── J · nothing illustrative stands in for a price ───────────────────── */

  await reload();

  section('§15J · When the route refuses, NOTHING illustrative appears');

  const refused = await evaluate(`return (async () => {
    if (!window.__fsRealFetch) window.__fsRealFetch = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (!url.includes('/versus/quote')) return window.__fsRealFetch(input, init);
      return new Response(JSON.stringify({ detail: {
        reason_code: 'projections_unavailable',
        message: 'This matchup cannot be priced yet — projections for this '
          + 'week have not landed.' } }), {
        status: 409, headers: { 'Content-Type': 'application/json' } });
    };

    ${openFor(priceable.id)}
    await new Promise((r) => setTimeout(r, 400));
    document.querySelector('#fs-sheet [data-composer-market="ml"]').click();
    await new Promise((r) => setTimeout(r, 200));
    ${typeStake('20')}
    ${SETTLE}
    const dom = (() => { ${READ_ECON} })();
    return { dom, sheet: document.getElementById('fs-sheet').textContent };
  })();`);

  check('the refusal is drawn', refused.dom.state === 'refused',
    `${refused.dom.state} — ${refused.dom.text.slice(0, 80)}`);
  check('and NO figure is shown in its place', refused.dom.cents.length === 0,
    JSON.stringify(refused.dom.cents));
  check('no illustrative moneyline appears on the sheet',
    !/[+−-]1(10|05|20|50)\b/.test(refused.sheet),
    (refused.sheet.match(/[+−-]1(10|05|20|50)\b/) || [''])[0]);
  check('no Rev 4.2 fixture opponent name survives',
    !/CULV Destroyers|Gridiron Goodfellas|Bada Bing|Sunday Gravy/
      .test(refused.sheet));
  check('and the refusal explains itself in product language',
    /project(ed|ions)/i.test(refused.dom.text)
    && !/projections_unavailable|409/.test(refused.dom.text),
    refused.dom.text.slice(0, 120));

  /* ── K/L · the write path is untouched by any of this ─────────────────── */

  await reload();

  section('§15K/L · Send still issues through the write command, and the '
    + 'quote is not part of it');

  const sent = await evaluate(`return (async () => {
    ${RECORD}
    // THE WRITE IS INTERCEPTED AND NOT PERFORMED. What is being certified is
    // WHAT the page asks for, and a real issue would post escrow this suite has
    // no business creating. The request is recorded, then refused.
    const recording = window.fetch;
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input.url;
      if (url.includes('/beef/challenge')) {
        window.__fsQuote.writes.push({ url, body: JSON.parse(init.body) });
        return new Response(JSON.stringify({ detail: 'not sent by the suite' }),
          { status: 409, headers: { 'Content-Type': 'application/json' } });
      }
      return recording(input, init);
    };

    ${openFor(priceable.id)}
    await new Promise((r) => setTimeout(r, 400));
    document.querySelector('#fs-sheet [data-composer-market="ml"]').click();
    await new Promise((r) => setTimeout(r, 200));
    ${typeStake('20')}
    ${SETTLE}
    const priced = (() => { ${READ_ECON} })();

    const send = document.querySelector('#fs-sheet [data-composer-send]');
    const enabled = Boolean(send) && !send.disabled;
    if (enabled) send.click();
    await new Promise((r) => setTimeout(r, 600));
    return { priced, enabled, net: window.__fsQuote };
  })();`);

  check('the wager is priced before Send is offered',
    sent.priced.state === 'ready' && sent.enabled === true,
    `${sent.priced.state}, send ${sent.enabled ? 'enabled' : 'disabled'}`);
  check('K · Send posts to the WRITE route, not to the quote route',
    sent.net.writes.length === 1
    && sent.net.writes[0].url.includes('/beef/challenge'),
    sent.net.writes.length ? sent.net.writes[0].url : 'nothing was posted');

  const write = (sent.net.writes[0] || {}).body || {};
  const quoted = (sent.net.responses[sent.net.responses.length - 1] || {}).body || {};
  check('carrying the GM’s own inputs and the authoritative target',
    write.challenged_team_id === priceable.id && write.week === served.week
    && write.bet_type === 'straight' && write.amount === 20,
    JSON.stringify(write));
  check('L · and NOT ONE economic figure from the quote',
    !('opponent_stake_cents' in write) && !('pot_cents' in write)
    && !('win_cents' in write) && !('anchor_odds' in write)
    && !('derived_odds' in write) && !('anchor_moneyline' in write),
    Object.keys(write).join(', '));
  check('no served integer is smuggled through under another name',
    !Object.values(write).includes(quoted.pot_cents)
    && !Object.values(write).includes(quoted.opponent_stake_cents),
    `served pot ${quoted.pot_cents}, opponent ${quoted.opponent_stake_cents}`);
  check('so the server re-prices the wager it is asked to write',
    Object.keys(write).every((k) => !/odds|moneyline|pot|payout|win_/.test(k)),
    Object.keys(write).join(', '));
});

finish('WP3C.1 AUTHORITATIVE VERSUS QUOTE — BROWSER');
