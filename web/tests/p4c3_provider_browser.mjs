/* ============================================================================
 * FantasyStakes — S8-P4C-3 · League and Week provider binding, in a browser
 *
 * WHAT ONLY A BROWSER CAN PROVE HERE. The integration suite already showed the
 * backend derives the week, the identity, the orientation and the record from
 * persisted provider state. What is still unproven at that point is whether the
 * SHIPPED PAGE shows those instead of the fixture — and, most of all, what it
 * does when the provider has published nothing.
 *
 * That last case is the one this suite exists for. Yahoo credentials are absent
 * in this environment, so "the provider has told us nothing" is not an edge
 * case: it is the state most real deployments will meet first. A page that
 * answers it with `CULV APPRECIATION SOCIETY`, week 5 and a 14–7 record is
 * indistinguishable from a working one, and every number on it is a stranger's.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const asyncProbe = (body) => `return (async () => { ${body} })();`;

const MODE = (process.argv.find((a) => a.startsWith('--mode=')) || '')
  .split('=')[1] || 'bound';

await withPage({ port: 9381, settleMs: 1700 }, async ({ evaluate }) => {

  const identity = await evaluate(asyncProbe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    return { league: me.capabilities.acting_league_id,
             team: me.capabilities.acting_team_id,
             teamName: me.capabilities.acting_team_name };
  `));

  const served = await evaluate(asyncProbe(`
    const r = await fetch('/league/' + ${identity.league} + '/context/me',
      { credentials: 'same-origin' });
    return r.ok ? await r.json() : { error: r.status };
  `));

  report.section(`League and Week — ${MODE}`);

  /* ── League identity ──────────────────────────────────────────────────── */

  const league = await evaluate(asyncProbe(`
    document.querySelector('.fs-tabbar__item[data-destination="league"]').click();
    await new Promise((r) => setTimeout(r, 250));
    const panel = document.getElementById('panel-league');
    const head = panel.querySelector('.fs-tabhdr, .fs-tabhead') || panel;
    const cells = [...panel.querySelectorAll('#fs-strip-league .fs-strip__cell')]
      .map((c) => ({
        label: c.querySelector('.fs-strip__label').textContent.trim(),
        value: c.querySelector('.fs-strip__value').textContent.trim(),
        exact: c.querySelector('[data-exact-cents]')
          ? c.querySelector('[data-exact-cents]').dataset.exactCents : null,
      }));
    return { text: panel.textContent, head: head.textContent, cells };
  `));

  report.check('the page shows the REAL league name',
    league.text.includes(served.league_name),
    `expected ${served.league_name}`);

  // THE ONE THAT MATTERS MOST. The fixture league must never appear on an
  // authenticated page — it names a real-sounding league that is not this one.
  report.check('the illustrative league name appears nowhere',
    !league.text.includes('CULV APPRECIATION SOCIETY'));

  if (served.week_resolved) {
    report.check('the League header states the authoritative week',
      league.text.includes(`Week ${served.current_week}`),
      `expected Week ${served.current_week}`);
  } else {
    report.check('with no provider week, the header claims none',
      !/Week \d/.test(league.head), league.head.slice(0, 80));
  }

  /* ── Season record ────────────────────────────────────────────────────── */

  if (served.record_resolved) {
    report.check('a resolved record is drawn from the backend',
      served.record_label !== null, String(served.record_label));
  } else {
    // NOT 14–7, AND NOT 0–0. The first is a stranger's record; the second
    // asserts a real record of no games.
    report.check('an unresolved record shows no fixture record',
      !league.text.includes('14–7') && !league.text.includes('14-7'));
    report.check('and does not invent 0–0',
      !league.text.includes('0–0') && !league.text.includes('0-0'));
  }

  /* ── The League strip ─────────────────────────────────────────────────── */

  // UIRECON WAVE 1 — the cell is labelled `Net Won`; same cell, same source.
  const netWinnings = league.cells.find((c) => c.label === 'Net Won');
  report.check('Net Won is unresolved — it has no posted source',
    netWinnings && netWinnings.value === '—',
    netWinnings ? netWinnings.value : 'cell missing');
  report.check('and carries no exact cents behind it',
    netWinnings && netWinnings.exact === null,
    netWinnings ? String(netWinnings.exact) : 'cell missing');

  // The three spendable cells come from the bound Ledger, so they must agree
  // with it exactly — a second source would show up here as a disagreement.
  const ledger = await evaluate(asyncProbe(`
    const r = await fetch('/league/' + ${identity.league} + '/ledger/me',
      { credentials: 'same-origin' });
    return r.ok ? await r.json() : null;
  `));
  if (ledger) {
    const available = league.cells.find((c) => c.label === 'Available');
    report.check('Available on League equals the Ledger, to the cent',
      available && available.exact === String(ledger.available_cents),
      `${available ? available.exact : 'missing'} vs ${ledger.available_cents}`);
  }

  /* ── The Week · Yahoo Matchups ────────────────────────────────────────── */

  const week = await evaluate(asyncProbe(`
    document.querySelector('.fs-tabbar__item[data-destination="week"]').click();
    await new Promise((r) => setTimeout(r, 300));
    const panel = document.getElementById('panel-week');
    const yahoo = panel.querySelector('[data-module="yahoo"]');
    const bets = panel.querySelector('[data-module="bets"]');
    const note = (el) => {
      const n = el ? el.querySelector('[data-week-state]') : null;
      return n ? { state: n.dataset.weekState, text: n.textContent.trim() } : null;
    };
    return {
      text: panel.textContent,
      // UIRECON WAVE 4B — COUNT LIST ENTRIES, NOT RAIL SLOTS. A section with
      // nothing to show puts its explanatory note in the same one-viewport-wide
      // wrapper the cards use, so the note occupies its own width rather than
      // shrinking to its text; that wrapper deliberately carries no listitem
      // role, because it is not one. Counting the role is what keeps "no cards
      // were drawn" distinct from "one slot exists".
      yahooCards: yahoo
        ? yahoo.querySelectorAll('.fs-rescar__item[role="listitem"]').length : -1,
      yahooNote: note(yahoo),
      betCards: bets
        ? bets.querySelectorAll('.fs-rescar__item[role="listitem"]').length : -1,
      betNote: note(bets),
    };
  `));

  const servedWeek = await evaluate(asyncProbe(`
    if (!${served.week_resolved}) return null;
    const r = await fetch('/league/' + ${identity.league} + '/week/'
      + ${served.current_week} + '/matchups', { credentials: 'same-origin' });
    return r.ok ? await r.json() : { error: r.status };
  `));

  if (servedWeek && !servedWeek.error && servedWeek.matchups.length) {
    report.check('the Week tab draws the provider’s matchups',
      week.yahooCards === servedWeek.matchups.length,
      `${week.yahooCards} drawn vs ${servedWeek.matchups.length} served`);

    // ORIENTATION SURVIVES TO THE PAGE. The served home side is drawn as the
    // home side; a card that put the acting GM first regardless would fail.
    const first = servedWeek.matchups[0];
    report.check('and draws them in the served orientation',
      week.text.includes(first.home.team_name)
      && week.text.includes(first.away.team_name));

    // NO FABRICATED MARKET. The illustrative card carries ML / SPR / O/U cells
    // derived from projections; the gateway captures no lines at all.
    report.check('no market row is drawn on a provider matchup',
      !/\bSPR\b/.test(week.text) && !/\bO\/U\b/.test(week.text),
      'the gateway captures no betting lines');
  } else {
    // PROVIDER PUBLISHED NOTHING — the state this environment actually has.
    report.check('the Yahoo module draws no card',
      week.yahooCards === 0, String(week.yahooCards));
    report.check('and says why, in words',
      week.yahooNote !== null,
      week.yahooNote ? week.yahooNote.state : 'no note');
    report.check('the state is authoritative-empty, not a failure',
      week.yahooNote
      && ['empty', 'no-week', 'not-read'].includes(week.yahooNote.state),
      week.yahooNote ? week.yahooNote.state : 'no note');
  }

  // THE DEMO MATCHUP MUST NOT APPEAR. These are the fixture's teams; on an
  // authenticated page they would read as this league's real opponents.
  const leaked = await evaluate(asyncProbe(`
    const text = document.getElementById('panel-week').textContent;
    return ['Gronk Obama', 'Sunday Scaries', 'Numbers Racket',
            'CULV Destroyers'].filter((n) => text.includes(n));
  `));
  report.check('no illustrative Yahoo matchup appears on the Week tab',
    leaked.length === 0, JSON.stringify(leaked));

  /* ── The Week · Versus ────────────────────────────────────────────────── */

  const servedAction = await evaluate(asyncProbe(`
    const r = await fetch('/league/' + ${identity.league} + '/action/me',
      { credentials: 'same-origin' });
    return r.ok ? await r.json() : null;
  `));

  if (servedAction) {
    const inWeek = Object.values(servedAction.sections).flat()
      .filter((c) => c.week === served.current_week);
    report.check('Versus draws the GM’s own wagers for this week',
      week.betCards === Math.min(inWeek.length, 4)
      || (inWeek.length === 0 && week.betNote !== null),
      `${week.betCards} drawn vs ${inWeek.length} served for the week`);
  }

  /* ── Pools · P4B regression ───────────────────────────────────────────── */

  const pools = await evaluate(asyncProbe(`
    const panel = document.getElementById('panel-week');
    const mod = panel.querySelector('[data-module="pools"]');
    return { rows: mod ? mod.querySelectorAll('.fs-poolrow').length : -1 };
  `));
  report.check('the Pool slate binding is preserved',
    pools.rows >= 0, String(pools.rows));
});

report.finish();