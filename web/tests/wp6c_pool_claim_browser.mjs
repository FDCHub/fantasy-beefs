/* ============================================================================
 * FantasyStakes — WP6C · the Pool pick, driven from the Rev 4.2 interface
 *
 * WHY THIS RUNS IN A BROWSER, AND WHY THE ROUTE SUITE IS NOT ENOUGH.
 * `p4c4_pool_pick_browser.mjs` proves the ROUTE behaves from a real session; it
 * composes its request with `fetch`. That cannot answer the question WP6C
 * actually has to answer, which is whether a GM WITH A MOUSE can produce a
 * governed claim. Before the cutover the Rev 4.2 Pool sheet had no pick control
 * at all — its Entry note read "binds to the Pool engine when the session seam
 * lands" — while the only shipped control that did post lived in the legacy
 * shell and wrote a row settlement never reads.
 *
 * So this drives the interface: open the Pool, choose the subject, press the
 * button, and then ask the SERVER whether a claim exists. The last step is the
 * one that matters. A confirmation the page drew for itself is exactly the
 * failure mode WP6C exists to remove, so the pass condition is never the button
 * text alone — it is the authoritative read agreeing with it.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const asyncProbe = (body) => `return (async () => { ${body} })();`;

/**
 * Poll for a selector rather than sleeping a fixed interval.
 *
 * The shell draws after an async identity read and several authoritative
 * fetches, and how long that takes varies with the session — the commissioner
 * run issues reads a GM's does not. A fixed wait that suits one is a flake in
 * the other, and a flake here would read as a Pool defect.
 */
const WAIT_HELPER = `
  let el = null;
  const wait = async (sel, timeout = 6000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const found = document.querySelector(sel);
      if (found) return found;
      await new Promise((r) => setTimeout(r, 100));
    }
    return null;
  };
`;
const waitFor = (selector) => `el = await wait(${JSON.stringify(selector)});`;

await withPage({ port: 9392, settleMs: 1800 }, async ({ evaluate }) => {

  const identity = await evaluate(asyncProbe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    return { league: me.capabilities.acting_league_id,
             team: me.capabilities.acting_team_id };
  `));

  const ctx = await evaluate(asyncProbe(`
    const c = await (await fetch('/league/' + ${identity.league} + '/context/me',
      { credentials: 'same-origin' })).json();
    return { week: c.week_resolved ? c.current_week : null };
  `));

  const authoritative = async () => evaluate(asyncProbe(`
    const r = await fetch('/league/' + ${identity.league} + '/pool/slate/' + ${ctx.week},
      { credentials: 'same-origin' });
    const b = await r.json();
    return b.slots.map((s) => ({ id: s.pool_instance_id,
                                 mine: s.my_subject_id, entered: s.entered }));
  `));

  report.section('The governed Pool pick, from the Rev 4.2 interface');

  report.check('the session names an acting team and an authoritative week',
    typeof identity.team === 'number' && typeof ctx.week === 'number',
    `team ${identity.team}, week ${ctx.week}`);

  const before = await authoritative();
  report.check('the week has a drawn slate and the GM holds no claim yet',
    before.length > 0 && before.every((s) => s.mine === null),
    JSON.stringify(before));

  /* ── Open the Pool ──────────────────────────────────────────────────────── */

  // THE WEEK TAB, which is where the AUTHORITATIVE slate is drawn. The League
  // tab's Pool zone still renders the POR's illustrative cards; those carry no
  // occurrence, so the control correctly refuses to appear on them and this
  // suite would be certifying the wrong surface.
  const opened = await evaluate(asyncProbe(`
    ${WAIT_HELPER}
    ${waitFor('.fs-tabbar__item[data-destination="week"]')}
    if (!el) return { opened: false, reason: 'no week tab', options: [] };
    el.click();
    ${waitFor('#panel-week .fs-poolrow')}
    if (!el) return { opened: false, reason: 'no Pool row rendered', options: [] };
    el.click();
    ${waitFor('#fs-poolpick-form')}
    const form = el;
    return {
      opened: Boolean(form),
      instance: form ? Number.parseInt(form.dataset.instance, 10) : null,
      options: form
        ? [...form.querySelectorAll('#fs-poolpick option')]
            .map((o) => o.value).filter(Boolean)
        : [],
      buttonText: form ? form.querySelector('#fs-poolpick-save').textContent : '',
      held: (document.querySelector('#fs-poolpick-held') || {}).textContent || null,
    };
  `));

  report.check('opening a Pool from The Week shows a pick control',
    opened.opened === true, JSON.stringify(opened).slice(0, 160));
  report.check('the control names the governed occurrence it would claim',
    Number.isInteger(opened.instance)
      && before.some((s) => s.id === opened.instance),
    String(opened.instance));
  report.check('and offers the subjects the occurrence admits',
    opened.options.length > 0, `${opened.options.length} options`);
  report.check('the button invites a first pick',
    opened.buttonText === 'Submit pick', opened.buttonText);
  report.check('and the GM is shown they hold no pick yet',
    opened.held === '—', String(opened.held));

  /* ── Choose a subject and submit ────────────────────────────────────────── */

  const CHOSEN = Number.parseInt(opened.options[0], 10);

  const submitted = await evaluate(asyncProbe(`
    const form = document.querySelector('#fs-poolpick-form');
    const select = form.querySelector('#fs-poolpick');
    select.value = '${CHOSEN}';
    form.querySelector('#fs-poolpick-save').click();
    // Long enough for the write AND the authoritative re-read the shell issues
    // afterwards; a shorter wait would race the confirmation rather than
    // observe it.
    await new Promise((r) => setTimeout(r, 1200));
    const err = document.querySelector('#fs-poolpick-error');
    return {
      error: err ? err.textContent.trim() : null,
      button: (document.querySelector('#fs-poolpick-save') || {}).textContent || '',
      held: (document.querySelector('#fs-poolpick-held') || {}).textContent || null,
    };
  `));

  report.check('the submission raises no refusal in the interface',
    !submitted.error, submitted.error || 'no error shown');
  report.check('the GM receives a normal confirmation',
    submitted.button === 'Pick recorded', submitted.button);

  /* ── And the confirmation is TRUE ───────────────────────────────────────── */

  const after = await authoritative();
  const claimed = after.find((s) => s.id === opened.instance) || {};

  report.check('a governed claim now exists on that exact occurrence, for that '
    + 'exact subject',
    claimed.mine === CHOSEN, `my_subject_id=${claimed.mine} chose ${CHOSEN}`);
  report.check('the occurrence counts exactly one entry',
    claimed.entered === 1, String(claimed.entered));
  report.check('and no OTHER occurrence was claimed by the same press',
    after.filter((s) => s.mine !== null).length === 1,
    JSON.stringify(after));

  /* ── The selection is reflected back on reopening ───────────────────────── */

  const reopened = await evaluate(asyncProbe(`
    ${WAIT_HELPER}
    document.querySelector('[data-fs-close]')?.click();
    await new Promise((r) => setTimeout(r, 300));
    ${waitFor('#panel-week .fs-poolrow')}
    if (!el) return { held: null, selected: null, button: 'no row' };
    el.click();
    ${waitFor('#fs-poolpick-form')}
    const held = document.querySelector('#fs-poolpick-held');
    const select = document.querySelector('#fs-poolpick');
    const save = document.querySelector('#fs-poolpick-save');
    return {
      held: held ? held.textContent.trim() : null,
      selected: select ? Number.parseInt(select.value, 10) : null,
      button: save ? save.textContent : '',
    };
  `));

  report.check('reopening the Pool shows the GM their recorded pick',
    Boolean(reopened.held), String(reopened.held));
  report.check('with that subject preselected',
    reopened.selected === CHOSEN, String(reopened.selected));
  report.check('and the button now offers a CHANGE rather than a first pick',
    reopened.button === 'Change pick', reopened.button);

  /* ── Nothing about this moved money ─────────────────────────────────────── */

  const drawn = await evaluate(
    "return document.querySelectorAll('#panel-week .fs-poolrow').length;");
  report.check('the four-slot Pool presentation is unchanged by the cutover',
    drawn === before.length, `${drawn} rows`);
});

report.finish();
