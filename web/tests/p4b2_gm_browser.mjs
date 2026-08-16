/* ============================================================================
 * FantasyStakes — S8-P4B-2 · the ordinary-GM session, in a browser
 *
 * THE SESSION MOST OF THE PRODUCT WILL BE. A GM may read their own Ledger and
 * may not read the league's positions or reconciliation — /ledger/positions and
 * /ledger/reconciliation answer 403, correctly, because they are commissioner
 * surfaces. That is a capability state, not an error, and the whole point of
 * this suite is the NEGATIVE claim it makes about it: the prototype's money
 * must not appear anywhere in its place.
 * ========================================================================== */

import { GO_RULES, createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const asyncProbe = (body) => `return (async () => { ${body} })();`;

await withPage({ port: 9363, settleMs: 1400 }, async ({ evaluate }) => {

  report.section('The session is a GM with authoritative context and no authority');

  const identity = await evaluate(asyncProbe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    return {
      leagues: me.capabilities.commissioner_league_ids,
      actingLeague: me.capabilities.acting_league_id,
      ambiguous: me.capabilities.acting_context_ambiguous,
    };
  `));

  report.check('the GM holds no commissioner authority',
    identity.leagues.length === 0, JSON.stringify(identity.leagues));
  report.check('but the server still names their acting league',
    typeof identity.actingLeague === 'number', String(identity.actingLeague));
  report.check('with no ambiguity', identity.ambiguous === false);

  /* ── The GM's own Ledger is real ──────────────────────────────────────── */

  report.section('The GM’s own Ledger is authoritative, to the cent');

  const ledger = await evaluate(asyncProbe(`
    document.querySelector('.fs-tabbar__item[data-destination="ledger"]').click();
    const served = await (await fetch('/league/' + ${identity.actingLeague}
      + '/ledger/me', { credentials: 'same-origin' })).json();
    const cell = (id, i) => {
      const c = document.querySelectorAll('#' + id + ' .fs-strip__cell')[i];
      const v = c.querySelector('[data-exact-cents]');
      return {
        label: c.querySelector('.fs-strip__label').textContent,
        value: c.querySelector('.fs-strip__value').textContent,
        exact: v ? v.dataset.exactCents : null,
      };
    };
    const settle = document.querySelector('#fs-current-settle .fs-settle__total');
    return {
      served,
      week: [0, 1, 2, 3].map((i) => cell('fs-strip-ledger', i)),
      season: [0, 1, 2, 3].map((i) => cell('fs-strip-season', i)),
      settleExact: settle ? Number(settle.dataset.exactCents) : null,
    };
  `));

  // REVISED BY S8-P4C-1, AND HELD IS WHY. P4B certified this strip against a
  // fixture whose challenges posted no money, so Held drew $0 and In Play saw
  // only bet escrow. The application now issues through the funded lifecycle:
  // the fixture's open $25 challenge really escrows, so Held draws the Rev 4.2
  // figure at last — and In Play grows by the same $25, because Held is a
  // SUBSET of it rather than a term beside it. Available falls by $25 for the
  // same single reason: the stake left the wallet.
  //
  // Weekly Min Left is UNCHANGED at $10, and that is deliberate. Funding is
  // min-first, so the fixture issues its challenge in week 6 where there is no
  // released minimum to consume — this cell belongs to a different claim and
  // P4C-1 had no business moving it.
  //
  // Current Settle below is unchanged at −$69: the money moved between two
  // asset terms, so the total cannot move. That is the check that this whole
  // revision is a reallocation and not a gain.
  const WEEK = [['Available', '$40', '4000'], ['In Play', '$53', '5300'],
                ['Held', '$25', '2500'], ['Weekly Min Left', '$10', '1000']];
  for (const [i, [label, value, exact]] of WEEK.entries()) {
    report.check(`My Week ${label} draws ${value}`,
      ledger.week[i].label === label && ledger.week[i].value === value
      && ledger.week[i].exact === exact,
      `${ledger.week[i].label} ${ledger.week[i].value} (${ledger.week[i].exact})`);
  }

  report.check('Awards / Adj. uses the unresolved treatment, not a number',
    ledger.season[2].label === 'Awards / Adj.' && ledger.season[2].value === '—',
    `${ledger.season[2].label} ${ledger.season[2].value}`);
  report.check('and carries no exact-cents behind it — nothing was invented',
    ledger.season[2].exact === null, String(ledger.season[2].exact));

  report.check('Current Settle draws −$69',
    ledger.season[3].value === '−$69', ledger.season[3].value);

  // THE CHAIN, END TO END, IN ONE DOCUMENT.
  report.check('served /ledger/me is exactly −6900',
    ledger.served.current_settle_cents === -6900,
    String(ledger.served.current_settle_cents));
  report.check('the strip carries exactly −6900',
    ledger.season[3].exact === '-6900', ledger.season[3].exact);
  report.check('and the Current Settle card agrees',
    ledger.settleExact === -6900, String(ledger.settleExact));

  // AND HELD IS INSIDE IN PLAY, not added to it — the served figures have to
  // agree with that or the strip is quietly double-counting the GM's own money.
  report.check('Held is a subset of In Play in the served figures',
    ledger.served.held_open_challenges_cents > 0
    && ledger.served.held_open_challenges_cents < ledger.served.in_play_cents,
    `held ${ledger.served.held_open_challenges_cents}, `
    + `in_play ${ledger.served.in_play_cents}`);

  report.check('the served terms are the drawn terms',
    ledger.served.available_cents === 4000
    && ledger.served.in_play_cents === 5300
    && ledger.served.held_open_challenges_cents === 2500
    && ledger.served.min_reserve_cents === 9000
    && ledger.served.expired_min_cents === 800
    && ledger.served.season_advance_cents === 22000
    && ledger.served.topoff_issued_cents === 4000,
    JSON.stringify(ledger.served));

  /* ── The commissioner surfaces are unavailable, not illustrative ──────── */

  report.section('Commissioner surfaces are unavailable, and leak nothing');

  const commish = await evaluate(asyncProbe(`
    ${GO_RULES}
    const league = ${identity.actingLeague};
    const positions = await fetch('/league/' + league + '/ledger/positions',
      { credentials: 'same-origin' });
    const recon = await fetch('/league/' + league + '/ledger/reconciliation',
      { credentials: 'same-origin' });
    const area = document.getElementById('fs-commissioner');
    const sections = [...area.querySelectorAll('[data-commissioner]')];
    return {
      positionsStatus: positions.status,
      reconStatus: recon.status,
      cards: document.querySelectorAll('#fs-gm-cards .fs-gmcard').length,
      money: area.querySelectorAll('[data-exact-cents]').length,
      unavailable: sections.filter(s => s.dataset.state === 'unavailable').length,
      sectionCount: sections.length,
      names: /Gravy|Braintrust|Destroyers|Goodfellas/i.test(area.textContent),
      explains: /commissioner authority/i.test(area.textContent),
      closes: area.querySelectorAll('[data-closes]').length,
    };
  `));

  report.check('the server refuses positions to a GM',
    commish.positionsStatus === 403, String(commish.positionsStatus));
  report.check('and refuses the reconciliation',
    commish.reconStatus === 403, String(commish.reconStatus));
  report.check('no GM cards are rendered', commish.cards === 0,
    String(commish.cards));
  report.check('NO money is rendered anywhere in the commissioner area',
    commish.money === 0, `${commish.money} figures`);
  report.check('every commissioner section declares itself unavailable',
    commish.unavailable === commish.sectionCount && commish.sectionCount === 3,
    `${commish.unavailable}/${commish.sectionCount}`);
  report.check('no prototype GM name appears', commish.names === false);
  report.check('no closes marker offers a league figure to believe',
    commish.closes === 0);
  report.check('and the surface explains that authority is required',
    commish.explains === true);
});

report.finish();