/* ============================================================================
 * FantasyStakes — WP4 · an ordinary GM sees no lifecycle controls
 *
 * THE SAME PAGE, A DIFFERENT SESSION. This is the negative half of the
 * commissioner suite and it runs the identical build — only the signed-in
 * identity differs, which is what makes the difference attributable to
 * authority rather than to a second code path.
 *
 * AND HIDING IS NOT THE SECURITY. The last section fires each governed command
 * straight at the API from the GM's own page, with their session cookie and a
 * correctly-echoed CSRF token, and asserts every one is refused server-side.
 * A build that merely omitted the buttons would pass the DOM assertions and
 * fail these.
 * ========================================================================== */

import { GO_RULES, createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const probe = (body) => `return (async () => { ${body} })();`;

/** POST the way the shipped client does — session cookie plus the CSRF echo. */
const post = (path) => probe(`
  const csrf = document.cookie.split('; ').find((c) => c.startsWith('fs_csrf='));
  const headers = {};
  if (csrf) headers['X-FS-CSRF'] = decodeURIComponent(csrf.split('=')[1]);
  const r = await fetch('${path}', {
    method: 'POST', credentials: 'same-origin', headers,
  });
  let payload = null;
  try { payload = await r.json(); } catch (e) { payload = null; }
  return { status: r.status, payload, csrfSent: Boolean(csrf) };
`);

await withPage({ port: 9402, settleMs: 2000 }, async ({ evaluate }) => {

  const identity = await evaluate(probe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    return { league: me.capabilities.acting_league_id,
             commissionerOf: me.capabilities.commissioner_league_ids || [] };
  `));

  report.section('The signed-in session is an ordinary GM');

  report.check('the session names an acting league',
    typeof identity.league === 'number', String(identity.league));
  report.check('and holds NO commissioner authority for it',
    !identity.commissionerOf.includes(identity.league),
    `commissioner of ${JSON.stringify(identity.commissionerOf)}`);

  /* ── No actionable control is drawn ───────────────────────────────────── */

  report.section('No actionable lifecycle control is drawn');

  const view = await evaluate(probe(`
    ${GO_RULES}
    ${'await new Promise((r) => setTimeout(r, 400));'}
    const region = document.getElementById('fs-lifecycle');
    return {
      present: Boolean(region),
      state: region ? region.dataset.state : null,
      // ACROSS THE WHOLE DOCUMENT, not just this region — a control that leaked
      // onto another panel would still be a control this session must not have.
      actions: document.querySelectorAll('[data-lifecycle-action]').length,
      buttons: region ? region.querySelectorAll('button').length : 0,
      text: region ? region.textContent.trim() : '',
      // A DISABLED CONTROL IS STILL A CONTROL. The scope asks that a
      // non-commissioner not SEE actionable controls, and a greyed
      // "Close the season" is an invitation to wonder what they are missing.
      disabledControls: document.querySelectorAll(
        '[data-lifecycle-action][disabled]').length,
    };
  `));

  report.check('the region still renders — a blank space would read as a fault',
    view.present === true);
  report.check('and says this session is not the commissioner',
    view.state === 'not-commissioner', String(view.state));
  report.check('ZERO lifecycle controls exist anywhere in the document',
    view.actions === 0, `${view.actions} control(s)`);
  report.check('not even disabled ones', view.disabledControls === 0,
    `${view.disabledControls} disabled control(s)`);
  report.check('no button of any kind is offered in the region',
    view.buttons === 0, `${view.buttons} button(s)`);
  report.check('it explains who operates the lifecycle instead',
    /commissioner/i.test(view.text), view.text.slice(0, 90));
  report.check('and it shows no lifecycle state it was never told',
    !/(Ready|Not measured|Insufficient|week \d)/.test(view.text),
    view.text.slice(0, 90));

  /* ── The read model itself is refused ─────────────────────────────────── */

  report.section('The lifecycle read is refused for this session');

  const read = await evaluate(probe(`
    const r = await fetch('/league/${identity.league}/lifecycle',
      { credentials: 'same-origin' });
    let payload = null;
    try { payload = await r.json(); } catch (e) { payload = null; }
    return { status: r.status, payload };
  `));

  report.check('GET /league/{id}/lifecycle refuses an ordinary GM',
    read.status === 403, `status ${read.status}`);

  /* ── Authorization is the API's, not the UI's ─────────────────────────── */

  report.section('Every governed command is refused server-side');

  const week = 5;
  const calls = [
    ['pool activate', `/league/${identity.league}/pool/activate?week=${week}`],
    ['week open', `/league/${identity.league}/week/${week}/open`],
    ['pool collect', `/league/${identity.league}/pool/collect/${week}`],
    ['pool settle', `/league/${identity.league}/pool/settle/${week}`],
    ['week close', `/league/${identity.league}/week/${week}/close`],
    ['season close', `/league/${identity.league}/season/close`],
  ];

  for (const [label, path] of calls) {
    const result = await evaluate(post(path));

    // THE TOKEN REACHED THE REQUEST. Without this the refusals prove nothing:
    // a missing CSRF token is also a 403, and every check below would pass
    // against a route with no authority guard whatsoever.
    report.check(`${label}: the CSRF token was read and sent`,
      result.csrfSent === true);
    report.check(`${label}: refused with 403 for a non-commissioner`,
      result.status === 403,
      `status ${result.status}: ${JSON.stringify(result.payload).slice(0, 90)}`);
    report.check(`${label}: and it is an AUTHORITY refusal, not a CSRF one`,
      !JSON.stringify(result.payload || {}).toLowerCase().includes('csrf'),
      JSON.stringify(result.payload).slice(0, 90));
  }

  /* ── Nothing leaked into the page afterwards ──────────────────────────── */

  const after = await evaluate(probe(`
    const region = document.getElementById('fs-lifecycle');
    return {
      actions: document.querySelectorAll('[data-lifecycle-action]').length,
      results: document.querySelectorAll('[data-lifecycle-result]').length,
      state: region ? region.dataset.state : null,
    };
  `));

  report.check('the refused commands left no control behind',
    after.actions === 0, `${after.actions} control(s)`);
  report.check('and no success or refusal banner',
    after.results === 0, `${after.results} result line(s)`);
  report.check('the region is unchanged', after.state === 'not-commissioner',
    String(after.state));
});

report.finish();
