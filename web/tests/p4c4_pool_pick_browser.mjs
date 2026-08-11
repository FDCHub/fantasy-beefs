/* ============================================================================
 * FantasyStakes — S8-P4C-4 · Pool pick authority, from the browser
 *
 * WHY THIS RUNS IN A BROWSER AT ALL. The integration suite already proved the
 * route refuses. What it cannot prove is that the refusal survives the path a
 * real client takes: a same-origin request carrying the session cookie and the
 * double-submit CSRF token, issued from the loaded application. A guard that
 * worked under TestClient and was bypassed by, say, an exempted origin would
 * pass there and fail here.
 *
 * AND THE SECOND HALF MATTERS AS MUCH. A refusal that left the page showing a
 * selection would tell a GM their pick had been recorded when it had not. Every
 * negative below re-reads the authoritative state afterwards and asserts it is
 * unchanged.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const report = createReporter();
const asyncProbe = (body) => `return (async () => { ${body} })();`;

/**
 * Post to the API the way the shipped client does — same origin, session
 * cookie, CSRF header read back out of the script-readable cookie.
 */
const post = (path, body) => asyncProbe(`
  const csrf = document.cookie.split('; ')
    .find((c) => c.startsWith('fs_csrf='));
  const headers = { 'Content-Type': 'application/json' };
  // X-FS-CSRF is what auth/session.py reads and what the shipped client sends.
  // An almost-right header name produces a 403 that LOOKS like an ownership
  // refusal, and every negative below would then pass against a route with no
  // ownership guard at all -- so csrfSent is returned and asserted.
  if (csrf) headers['X-FS-CSRF'] = decodeURIComponent(csrf.split('=')[1]);
  const r = await fetch('${path}', {
    method: 'POST', credentials: 'same-origin', headers,
    body: JSON.stringify(${JSON.stringify(body)}),
  });
  let payload = null;
  try { payload = await r.json(); } catch (e) { payload = null; }
  return { status: r.status, payload, csrfSent: Boolean(csrf) };
`);

await withPage({ port: 9391, settleMs: 1600 }, async ({ evaluate }) => {

  const identity = await evaluate(asyncProbe(`
    const me = await (await fetch('/auth/me', { credentials: 'same-origin' })).json();
    return { league: me.capabilities.acting_league_id,
             team: me.capabilities.acting_team_id,
             commissionerOf: me.capabilities.commissioner_league_ids };
  `));

  const roster = await evaluate(asyncProbe(`
    const r = await fetch('/league/' + ${identity.league} + '/action/me',
      { credentials: 'same-origin' });
    const b = await r.json();
    return b.opponents.map((o) => o.team_id);
  `));

  const OTHER = roster[0];
  const WEEK = 1;

  report.section('Pool pick authority, from the loaded application');

  report.check('the session names an acting team',
    typeof identity.team === 'number', String(identity.team));
  report.check('and another team in the league to aim at',
    typeof OTHER === 'number' && OTHER !== identity.team, String(OTHER));

  /* ── The negative: picking for someone else ───────────────────────────── */

  const before = await evaluate(asyncProbe(`
    const r = await fetch('/pool/week/${WEEK}?league_id=' + ${identity.league},
      { credentials: 'same-origin' });
    return r.ok ? JSON.stringify(await r.json()) : 'unavailable:' + r.status;
  `));

  const foreign = await evaluate(post('/pool/pick', {
    league_id: 0, team_id: 0, bet_type: 'biggest_winner', pick: 0, week: WEEK,
  }));

  const asOther = await evaluate(post('/pool/pick', {
    league_id: identity.league, team_id: OTHER,
    bet_type: 'biggest_winner', pick: OTHER, week: WEEK,
  }));

  // THE TOKEN REACHED THE REQUEST. Without this the refusals below prove
  // nothing: a missing CSRF token is also a 403, and every negative would pass
  // against a route with no ownership guard whatsoever.
  report.check('the CSRF token was read and sent', asOther.csrfSent === true);
  report.check('so a refusal is not a CSRF refusal',
    !JSON.stringify(asOther.payload || {}).toLowerCase().includes('csrf'),
    JSON.stringify(asOther.payload).slice(0, 110));

  report.check('submitting a Pool pick for ANOTHER team is refused',
    asOther.status === 403,
    `status ${asOther.status}: ${JSON.stringify(asOther.payload).slice(0, 110)}`);

  // THE SIGNED-IN USER IS THE COMMISSIONER IN THE COMMISSIONER RUN, and an
  // ordinary GM in the other. Neither may pick for someone else — the run label
  // says which identity produced this result.
  report.check('and it is an OWNERSHIP refusal, naming the team',
    JSON.stringify(asOther.payload || {}).toLowerCase().includes('own'),
    JSON.stringify(asOther.payload).slice(0, 110));

  const after = await evaluate(asyncProbe(`
    const r = await fetch('/pool/week/${WEEK}?league_id=' + ${identity.league},
      { credentials: 'same-origin' });
    return r.ok ? JSON.stringify(await r.json()) : 'unavailable:' + r.status;
  `));

  report.check('the authoritative Pool state is byte-identical afterwards',
    after === before,
    after === before ? 'unchanged' : 'STATE CHANGED ON A REFUSED PICK');

  report.check('a cross-league pick is refused too',
    foreign.status === 403 || foreign.status === 404,
    `status ${foreign.status}`);

  /* ── The positive: picking for your own team ──────────────────────────── */

  const own = await evaluate(post('/pool/pick', {
    league_id: identity.league, team_id: identity.team,
    bet_type: 'biggest_winner', pick: identity.team, week: WEEK,
  }));

  // NOT ASSERTED AS 200. This fixture may have no Pool week drawn, in which
  // case the engine refuses for a POOL reason (400/404) rather than an
  // authority one. What must never happen is a 403: the GM owns this team, and
  // an ownership refusal here would mean the repair had disabled them.
  report.check('a GM is never refused OWNERSHIP of their own team’s pick',
    own.status !== 403,
    `status ${own.status}: ${JSON.stringify(own.payload).slice(0, 110)}`);

  /* ── No optimistic selection survives a refusal ───────────────────────── */

  const leaked = await evaluate(asyncProbe(`
    document.querySelector('.fs-tabbar__item[data-destination="week"]').click();
    await new Promise((r) => setTimeout(r, 250));
    const panel = document.getElementById('panel-week');
    return [...panel.querySelectorAll('.fs-poolrow')]
      .filter((el) => el.getAttribute('aria-pressed') === 'true'
        || el.classList.contains('is-selected')).length;
  `));
  report.check('no Pool row is left showing a selection the server refused',
    leaked === 0, String(leaked));
});

report.finish();