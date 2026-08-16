/* ============================================================================
 * FantasyStakes — S8-P4B-2 · the commissioner accounting surface, in a browser
 *
 * WHY THIS SUITE EXISTS. The Sprint 7 browser suites sign in as an ordinary GM,
 * and once the shell binds real data those sessions correctly receive 403 from
 * the commissioner read models. The claims that then have nowhere to live —
 * card count, card geometry, card values, the reconciliation aggregate, and the
 * cross-surface equality between a GM's own Ledger and the commissioner's view
 * of that same GM — are NOT dropped. They moved here, to the session that can
 * actually make them.
 *
 * The harness signs in as the seeded league commissioner via --auth-email, so
 * production authorization is untouched: this suite holds real authority
 * because the fixture granted it a LeagueCommissioner row, not because
 * anything was loosened for testing.
 * ========================================================================== */

import { GO_RULES, createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const asyncProbe = (body) => `return (async () => { ${body} })();`;

await withPage({ port: 9361, settleMs: 1400 }, async ({ evaluate }) => {

  /* ── The session really is a commissioner ─────────────────────────────── */

  report.section('The session holds real league commissioner authority');

  const identity = await evaluate(asyncProbe(`
    const res = await fetch('/auth/me', { credentials: 'same-origin' });
    const me = await res.json();
    return {
      leagues: me.capabilities.commissioner_league_ids,
      actingLeague: me.capabilities.acting_league_id,
      actingTeam: me.capabilities.acting_team_id,
      ambiguous: me.capabilities.acting_context_ambiguous,
    };
  `));

  report.check('the server grants commissioner authority for exactly one league',
    identity.leagues.length === 1, JSON.stringify(identity.leagues));
  report.check('and names an authoritative acting league',
    typeof identity.actingLeague === 'number', String(identity.actingLeague));
  report.check('with no ambiguity to guess through',
    identity.ambiguous === false);

  /* ── A · Top-Off requests ─────────────────────────────────────────────── */
  //
  // MOVED HERE FROM THE GM SESSION (S8-P4B-2R). Requests carry amounts, so an
  // unauthorised session must not see the illustrative list — the GM suite now
  // certifies that absence. The grammar claims themselves are unchanged and
  // live here, where a commissioner can actually see them.

  report.section('Top-Off requests render for a commissioner');

  const requests = await evaluate(`
    ${GO_RULES}
    const section = document.querySelector('[data-commissioner="topoffs"]');
    const rows = [...section.querySelectorAll('.fs-req')];
    return {
      state: section.dataset.state || 'demo',
      count: rows.length,
      states: [...new Set([...section.querySelectorAll('.fs-reqgroup')]
        .map(g => g.dataset.state))],
      controlsDisabled: (() => {
        const pending = section.querySelector('[data-state="pending"] .fs-req');
        if (!pending) return null;
        pending.click();
        const controls = [...document.querySelectorAll('#fs-sheet [data-decide]')];
        const all = controls.length > 0 && controls.every(c => c.disabled === true);
        document.querySelector('#fs-sheet [data-fs-close]').click();
        return { count: controls.length, all };
      })(),
    };
  `);

  report.check('the section is not in the unavailable state',
    requests.state !== 'unavailable', requests.state);
  report.check('requests render for a commissioner', requests.count > 0,
    String(requests.count));
  report.check('all four presentation states appear',
    requests.states.join(',') === 'pending,approved,rejected,cancelled',
    requests.states.join(','));
  report.check('every decision control is disabled — no decision is transmitted',
    requests.controlsDisabled && requests.controlsDisabled.count === 3
    && requests.controlsDisabled.all === true,
    JSON.stringify(requests.controlsDisabled));

  /* ── B · GM ledger cards, from the response ───────────────────────────── */

  report.section('GM ledger cards bind from /ledger/positions');

  const cards = await evaluate(asyncProbe(`
    ${GO_RULES}
    const res = await fetch('/league/' + ${identity.actingLeague}
      + '/ledger/positions', { credentials: 'same-origin' });
    const served = await res.json();
    const section = document.querySelector('[data-commissioner="gm-cards"]');
    const drawn = [...document.querySelectorAll('#fs-gm-cards .fs-gmcard')];
    return {
      status: res.status,
      servedCount: served.length,
      drawnCount: drawn.length,
      heading: section.querySelector('.fs-sec__title, .fs-heading__title, h2, .fs-sechead__title')
        ? section.textContent.slice(0, 60) : section.textContent.slice(0, 60),
      state: section.dataset.state,
      cols: new Set(drawn.map(c => Math.round(c.getBoundingClientRect().left))).size,
      clipped: drawn.filter(c => c.scrollWidth > c.clientWidth + 1).length,
      settles: drawn.map(c => Number(
        c.querySelector('.fs-gmcard__settle').dataset.exactCents)),
      servedSettles: served.map(p => p.current_settle_cents),
      labels: drawn.length
        ? [...drawn[0].querySelectorAll('.fs-gmcard__label')].map(e => e.textContent)
        : [],
      anyCents: /\\$\\d+\\.\\d\\d/.test(document.getElementById('fs-gm-cards').textContent),
    };
  `));

  report.check('the commissioner may read the positions', cards.status === 200,
    String(cards.status));
  report.check('the section is in authoritative mode',
    cards.state === 'authoritative', cards.state);
  report.check('THE CARD COUNT COMES FROM THE RESPONSE, not from a constant',
    cards.drawnCount === cards.servedCount,
    `${cards.drawnCount} drawn vs ${cards.servedCount} served`);
  report.check('the heading carries that same dynamic count',
    cards.heading.includes(`· ${cards.servedCount} ·`), cards.heading);
  report.check('every card carries the served Current Settle, in order',
    JSON.stringify(cards.settles) === JSON.stringify(cards.servedSettles),
    `${JSON.stringify(cards.settles)} vs ${JSON.stringify(cards.servedSettles)}`);
  report.check('the Rev 4.2 card grammar is preserved',
    cards.labels.join('/') === 'Available/In Play/Held', cards.labels.join('/'));
  report.check('no card clips its own content', cards.clipped === 0);
  report.check('nothing is drawn with cents', cards.anyCents === false);

  /* ── The seeded GM's card is the seeded GM's own figure ───────────────── */

  report.section('The commissioner sees the GM’s own figure, to the cent');

  const cross = await evaluate(asyncProbe(`
    const league = ${identity.actingLeague};
    const positions = await (await fetch('/league/' + league + '/ledger/positions',
      { credentials: 'same-origin' })).json();
    const gravy = positions.find(p => p.team_name === 'Gravy Train');
    const card = [...document.querySelectorAll('#fs-gm-cards .fs-gmcard')]
      .find(c => c.querySelector('.fs-gmcard__name').textContent === 'Gravy Train');
    return {
      served: gravy ? gravy.current_settle_cents : null,
      drawn: card ? Number(card.querySelector('.fs-gmcard__settle').dataset.exactCents) : null,
    };
  `));

  report.check('the seeded GM’s served position is exactly −6900',
    cross.served === -6900, String(cross.served));
  report.check('and the commissioner card draws exactly that',
    cross.drawn === -6900, String(cross.drawn));

  /* ── C · League reconciliation ────────────────────────────────────────── */

  report.section('League reconciliation binds from /ledger/reconciliation');

  const league = await evaluate(asyncProbe(`
    const res = await fetch('/league/' + ${identity.actingLeague}
      + '/ledger/reconciliation', { credentials: 'same-origin' });
    const served = await res.json();
    const sec = document.querySelector('[data-commissioner="reconciliation"]');
    const total = sec.querySelector('.fs-lrow.is-total [data-exact-cents]');
    const closes = sec.querySelector('[data-closes]');
    return {
      status: res.status,
      state: sec.dataset.state || 'authoritative',
      servedCount: served.position_count,
      servedSettle: served.sum_of_gm_settles_cents,
      servedReconciles: served.reconciles,
      drawnTotal: total ? Number(total.dataset.exactCents) : null,
      closes: closes ? closes.dataset.closes : null,
      hasIntegrityBlock: Boolean(sec.querySelector('.fs-integrity')),
    };
  `));

  report.check('the commissioner may read the reconciliation',
    league.status === 200, String(league.status));
  report.check('the server reports the league reconciles',
    league.servedReconciles === true);
  report.check('the drawn league figure is the served sum of GM positions',
    league.drawnTotal === league.servedSettle,
    `${league.drawnTotal} vs ${league.servedSettle}`);
  report.check('the surface states that the league closes',
    league.closes === 'true', String(league.closes));

  /* ── No global integrity call, from anywhere ──────────────────────────── */

  report.section('No global trial-balance endpoint is called or reachable');

  const integrity = await evaluate(asyncProbe(`
    const probes = ['/ledger/integrity', '/ledger/trial-balance',
                    '/league/' + ${identity.actingLeague} + '/ledger/integrity'];
    const codes = {};
    for (const p of probes) {
      codes[p] = (await fetch(p, { credentials: 'same-origin' })).status;
    }
    return codes;
  `));

  report.check('every global-integrity spelling is absent from the API',
    Object.values(integrity).every((c) => c === 404 || c === 405),
    JSON.stringify(integrity));
  report.check('and the commissioner surface still explains the invariant '
    + 'without claiming to have checked it',
    league.hasIntegrityBlock === true);
});

report.finish();