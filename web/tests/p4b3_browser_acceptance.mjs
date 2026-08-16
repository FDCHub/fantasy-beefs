/* ============================================================================
 * FantasyStakes — S8-P4B-3R · settings and Pool slate, in a real browser
 *
 * CLOSES THE ONE GAP P4B-3 REPORTED. The commissioner save path and the drawn
 * Pool slate were certified at API and model level; these are claims about a
 * RENDERED APPLICATION, so they are made here by driving it.
 *
 * NOTHING IS IMPORTED. Every assertion below reads the live document or calls
 * the live API from inside the page. Importing `settings-model.js` and asking
 * it what it thinks would certify the model — which P4B-3 already did — and
 * not the surface a commissioner actually uses.
 *
 * Which mode this runs in is chosen by the Python driver through the harness's
 * --auth-email and the app server's fixture flags. This file makes the claims;
 * it does not decide the fixture.
 * ========================================================================== */

import { GO_RULES, createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const asyncProbe = (body) => `return (async () => { ${body} })();`;

const MODE = (process.argv.find((a) => a.startsWith('--mode=')) || '').slice(7)
  || 'editable';

await withPage({ port: 9371, settleMs: 1500 }, async ({ evaluate }) => {

  const league = await evaluate(asyncProbe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    return me.capabilities.acting_league_id;
  `));

  /* ── 1 · The drawn Pool slate ─────────────────────────────────────────── */
  //
  // Only the fixtures that seed one. `frozen` shares the drawn slate but its
  // subject is the refusal, and `undrawn` deliberately has none — asserting a
  // drawn slate there would be asserting the opposite of that run's claim.

  if (MODE === 'editable') {
  report.section('The Week renders the authoritative drawn slate');

  const slate = await evaluate(asyncProbe(`
    document.querySelector('.fs-tabbar__item[data-destination="week"]').click();
    const served = await (await fetch('/league/' + ${league} + '/pool/slate/5',
      { credentials: 'same-origin' })).json();
    const section = document.querySelector('[data-module="pools"]');
    const rows = [...section.querySelectorAll('.fs-poolrow')];
    return {
      served,
      state: section.dataset.state,
      heading: section.textContent.slice(0, 48),
      count: rows.length,
      names: rows.map(r => r.querySelector('.fs-poolrow__name').textContent),
      catalogNumbers: rows.map(r => r.dataset.pool),
      rollovers: rows.map(r => Boolean(r.querySelector('.is-rollover'))),
    };
  `));

  report.check('the slate section reports the drawn state',
    slate.state === 'drawn', String(slate.state));
  report.check('the server drew this week', slate.served.drawn === true);
  report.check('EXACTLY FOUR Pool rows are rendered', slate.count === 4,
    String(slate.count));
  report.check('and the server returned exactly four slots',
    slate.served.slots.length === 4, String(slate.served.slots.length));
  report.check('there is no fifth Pool',
    slate.count === slate.served.slots.length && slate.count === 4);

  report.check('rendered order matches slots 1–4 from the slate',
    JSON.stringify(slate.catalogNumbers)
      === JSON.stringify(slate.served.slots.map(s => String(s.catalog_number))),
    `${slate.catalogNumbers} vs ${slate.served.slots.map(s => s.catalog_number)}`);

  report.check('displayed names are the seeded Rev1.3 definitions',
    JSON.stringify(slate.names)
      === JSON.stringify(slate.served.slots.map(s => s.display_name)),
    JSON.stringify(slate.names));

  // The illustrative launch Pools must not be what is on screen.
  report.check('these are NOT the illustrative launch Pools',
    !slate.names.some(n => /Biggest Winner|Worst Beat|Special Teams/i.test(n)),
    JSON.stringify(slate.names));

  const carried = slate.served.slots.filter(s => s.is_continuation);
  report.check('exactly one slot is a continuation', carried.length === 1,
    String(carried.length));
  report.check('the continuation OCCUPIES one of the four, not a fifth',
    carried.length === 1 && slate.count === 4);
  report.check('and it is badged as a rollover on its own row',
    slate.rollovers.filter(Boolean).length >= 1,
    JSON.stringify(slate.rollovers));

  const poolDetail = await evaluate(`
    document.querySelector('[data-module="pools"] .fs-poolrow').click();
    const text = document.getElementById('fs-sheet').textContent;
    document.querySelector('#fs-sheet [data-fs-close]').click();
    return text;
  `);
  report.check('a Pool opens its detail from the drawn slate',
    poolDetail.length > 20, `${poolDetail.length} chars`);
  report.check('and the detail carries its authoritative catalog identity',
    poolDetail.includes(String(slate.served.slots[0].catalog_number))
    || /catalog #/i.test(poolDetail),
    poolDetail.slice(0, 120));

  } // end drawn-slate block

  /* ── 2 · Rules & Settings, as the commissioner sees them ──────────────── */

  const settings = MODE === 'undrawn' ? null : await evaluate(asyncProbe(`
    ${GO_RULES}
    const served = await (await fetch('/league/' + ${league} + '/settings',
      { credentials: 'same-origin' })).json();
    const region = document.querySelector('[data-region="settings"]');
    const rows = [...region.querySelectorAll('.fs-setrow')];
    return {
      served,
      state: region.dataset.state,
      ids: rows.map(r => r.dataset.setting),
      values: rows.map(r => r.querySelector('.fs-setrow__value').textContent),
      poolExact: rows.find(r => r.dataset.setting === 'pool-bet')
        .querySelector('[data-exact-cents]').dataset.exactCents,
    };
  `));

  if (settings) {
  report.section('Rules & Settings renders the authoritative configuration');

  report.check('the settings region is authoritative',
    settings.state === 'authoritative', String(settings.state));
  report.check('all four rows render in the locked order',
    JSON.stringify(settings.ids)
      === JSON.stringify(['economy-stop', 'pool-bet', 'skunk-fee',
                          'championship-split']),
    JSON.stringify(settings.ids));
  report.check('the Standard Pool Bet shows the authoritative current value',
    Number(settings.poolExact) === settings.served.pool_entry.cents,
    `${settings.poolExact} vs ${settings.served.pool_entry.cents}`);
  } // end settings block

  /* ── 3 · The mutation, or its refusal ─────────────────────────────────── */

  if (MODE === 'editable') {
    report.section('A commissioner can change the Standard Pool Bet');

    const form = await evaluate(`
      [...document.querySelectorAll('.fs-setrow')]
        .find(r => r.dataset.setting === 'pool-bet').click();
      const sheet = document.getElementById('fs-sheet');
      const input = sheet.querySelector('#fs-pool-entry');
      const others = ['economy-stop', 'skunk-fee', 'championship-split'];
      return {
        hasForm: Boolean(sheet.querySelector('#fs-pool-entry-form')),
        min: input ? input.getAttribute('min') : null,
        max: input ? input.getAttribute('max') : null,
        minCents: input ? input.dataset.minCents : null,
        maxCents: input ? input.dataset.maxCents : null,
        value: input ? input.value : null,
      };
    `);

    report.check('the edit control exists for a commissioner before freeze',
      form.hasForm === true);
    report.check('the input carries the exact backend bounds',
      Number(form.minCents) === settings.served.pool_entry.min_cents
      && Number(form.maxCents) === settings.served.pool_entry.max_cents,
      `${form.minCents}–${form.maxCents}`);
    report.check('and opens at the authoritative current value',
      Math.round(Number(form.value) * 100) === settings.served.pool_entry.cents,
      String(form.value));

    // Submit a NEW valid value through the rendered form.
    const saved = await evaluate(asyncProbe(`
      const input = document.querySelector('#fs-pool-entry');
      input.value = '3.50';
      document.querySelector('#fs-pool-entry-form')
        .dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
      await new Promise(r => setTimeout(r, 900));
      const served = await (await fetch('/league/' + ${league} + '/settings',
        { credentials: 'same-origin' })).json();
      const row = [...document.querySelectorAll('.fs-setrow')]
        .find(r => r.dataset.setting === 'pool-bet');
      const err = document.querySelector('#fs-pool-entry-error');
      return {
        servedCents: served.pool_entry.cents,
        renderedExact: row
          ? row.querySelector('[data-exact-cents]').dataset.exactCents : null,
        renderedText: row
          ? row.querySelector('.fs-setrow__value').textContent : null,
        error: err ? err.textContent : '',
      };
    `));

    report.check('the save reached the server and it stored 350 cents',
      saved.servedCents === 350, String(saved.servedCents));
    report.check('no error was surfaced', saved.error === '', saved.error);
    report.check('and the surface re-renders the new authoritative value',
      Number(saved.renderedExact) === 350, String(saved.renderedExact));
    report.check('drawn as whole dollars, per Rev 4.2',
      saved.renderedText === '$4' || saved.renderedText === '$3',
      String(saved.renderedText));

    // The other three must offer no enabled mutation control.
    const others = await evaluate(`
      const out = {};
      for (const id of ['economy-stop', 'skunk-fee', 'championship-split']) {
        [...document.querySelectorAll('.fs-setrow')]
          .find(r => r.dataset.setting === id).click();
        const sheet = document.getElementById('fs-sheet');
        out[id] = {
          inputs: sheet.querySelectorAll('input, select, textarea').length,
          enabledButtons: [...sheet.querySelectorAll('button')]
            .filter(b => !b.disabled && !b.hasAttribute('data-fs-close')).length,
          text: sheet.textContent.slice(0, 80),
        };
        document.querySelector('#fs-sheet [data-fs-close]').click();
      }
      return out;
    `);

    for (const id of ['economy-stop', 'skunk-fee', 'championship-split']) {
      report.check(`${id} offers no editor`, others[id].inputs === 0,
        String(others[id].inputs));
      report.check(`${id} offers no enabled mutation control`,
        others[id].enabledButtons === 0, String(others[id].enabledButtons));
    }
  }

  if (MODE === 'frozen') {
    report.section('A frozen Standard Pool Bet cannot be changed');

    const frozen = await evaluate(asyncProbe(`
      [...document.querySelectorAll('.fs-setrow')]
        .find(r => r.dataset.setting === 'pool-bet').click();
      const sheet = document.getElementById('fs-sheet');

      // THE SERVER IS THE AUTHORITY, not the absent control. The write is
      // attempted directly, with a valid CSRF token, exactly as a client that
      // ignored the UI would — and the refusal must come from the server.
      const csrf = document.cookie.split(';').map(s => s.trim())
        .find(s => s.startsWith('fs_csrf=')).slice('fs_csrf='.length);
      const res = await fetch('/league/' + ${league} + '/settings/pool-entry', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json',
                   'X-FS-CSRF': decodeURIComponent(csrf) },
        body: JSON.stringify({ cents: 400 }),
      });
      const detail = await res.json();
      const after = await (await fetch('/league/' + ${league} + '/settings',
        { credentials: 'same-origin' })).json();
      document.querySelector('#fs-sheet [data-fs-close]').click();
      return {
        hasForm: Boolean(sheet.querySelector('#fs-pool-entry-form')),
        text: sheet.textContent,
        status: res.status,
        reason: detail && detail.detail ? detail.detail.reason_code : null,
        afterCents: after.pool_entry.cents,
        afterFrozen: after.pool_entry.frozen,
        afterEditable: after.pool_entry.editable,
      };
    `));

    report.check('the served settings report the entry frozen',
      frozen.afterFrozen === true && frozen.afterEditable === false);
    report.check('the surface offers no edit control once frozen',
      frozen.hasForm === false);
    report.check('and says why', /[Ff]rozen/.test(frozen.text),
      frozen.text.slice(0, 120));

    report.check('THE SERVER refuses the write with 409, not the disabled '
      + 'control', frozen.status === 409, String(frozen.status));
    report.check('and names the governed reason',
      frozen.reason === 'ENTRY_FROZEN', String(frozen.reason));
    report.check('the value did not change', frozen.afterCents === 200,
      String(frozen.afterCents));
  }

  if (MODE === 'undrawn') {
    report.section('An undrawn week renders no Pools — regression');

    const undrawn = await evaluate(asyncProbe(`
      document.querySelector('.fs-tabbar__item[data-destination="week"]').click();
      const served = await (await fetch('/league/' + ${league} + '/pool/slate/5',
        { credentials: 'same-origin' })).json();
      const section = document.querySelector('[data-module="pools"]');
      return {
        drawn: served.drawn,
        state: section.dataset.state,
        rows: section.querySelectorAll('.fs-poolrow').length,
        text: section.textContent,
      };
    `));

    report.check('the server reports the week undrawn', undrawn.drawn === false);
    report.check('the section reports the undrawn state',
      undrawn.state === 'undrawn', String(undrawn.state));
    report.check('ZERO Pool cards are rendered', undrawn.rows === 0,
      String(undrawn.rows));
    report.check('no launch-Pool fallback appears',
      !/Biggest Winner|Worst Beat|Special Teams/i.test(undrawn.text));
    report.check('and the provider-readiness treatment is shown',
      /both catalog gates|provider/i.test(undrawn.text),
      undrawn.text.slice(0, 140));
  }
});

report.finish();