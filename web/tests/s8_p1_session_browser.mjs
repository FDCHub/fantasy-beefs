/* ============================================================================
 * FantasyStakes — S8-P1 session behaviour in a real browser
 * Sprint 8 Package 1
 *
 * WHY THIS SUITE EXISTS SEPARATELY FROM THE PYTHON ONE. The Python suite drives
 * the API with a scripted HTTP client, which will do whatever it is told —
 * including attaching cookies a real browser would refuse and ignoring rules a
 * real browser enforces. The claims Sprint 8 actually rests on are claims about
 * a BROWSER: that HttpOnly means the page cannot read the token, that the
 * session survives a navigation, that signing out empties the view. None of
 * those can be established by a client that has no cookie jar policy, no
 * document, and no script context.
 *
 * It is driven by test_s8_p1_browser.py, which starts a real FastAPI process on
 * a disposable database and passes its origin in. The page and the API are the
 * SAME origin, which is the deployment shape (`app.mount("/app", ...)`) and
 * therefore the shape the CSRF and CORS design assumes.
 *
 * USAGE (via the Python driver, not directly):
 *     node web/tests/s8_p1_session_browser.mjs --origin=http://127.0.0.1:PORT
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

function arg(name, fallback = null) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : fallback;
}

const ORIGIN = arg('origin');
const GM_EMAIL = arg('gm-email', 'gm@example.test');
const COMM_EMAIL = arg('commissioner-email', 'commissioner@example.test');
const PASSWORD = arg('password', 'sprint8-password');

if (!ORIGIN) {
  console.log('  [FAIL] --origin was not supplied');
  process.exit(1);
}

const report = createReporter();

/**
 * The harness evaluates each expression inside a plain (non-async) arrow and
 * awaits whatever it returns. A probe that needs `await` therefore has to
 * supply its own async scope rather than relying on the wrapper's.
 *
 * @param {string} body statements ending in a `return`
 * @returns {string} an expression the harness can evaluate
 */
const asyncProbe = (body) => `return (async () => { ${body} })();`;

/** Fill the gate and submit it, then let the shell re-render. */
const signIn = (email) => `
  const form = document.getElementById('fs-gate-form');
  document.getElementById('fs-gate-email').value = ${JSON.stringify(email)};
  document.getElementById('fs-gate-password').value = ${JSON.stringify(PASSWORD)};
  form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
  return new Promise((ok) => setTimeout(ok, 700));
`;

await withPage({ origin: ORIGIN, path: '/app/index.html', settleMs: 1200 },
               async ({ evaluate, reload }) => {

  /* ── 1 · A signed-out page shows the gate and holds no league state ────── */

  report.section('A signed-out page shows the gate and holds no league state');

  report.check('the sign-in gate is rendered',
    await evaluate(`
      const gate = document.getElementById('fs-gate');
      return !gate.hidden && !!gate.querySelector('#fs-gate-form');
    `));

  report.check('the application panels are empty',
    await evaluate(`return document.getElementById('fs-panels').innerHTML.trim() === '';`));

  report.check('the bottom navigation is empty',
    await evaluate(`return document.getElementById('fs-tabbar').innerHTML.trim() === '';`));

  report.check('no league or GM figure is present anywhere in the document',
    await evaluate(`
      const text = document.body.innerText;
      return !/CULV|Current Settle|Weekly Minimum|Skunk/i.test(text);
    `),
    'a signed-out page must not have rendered a league');

  report.check('no acting identity is claimed',
    await evaluate(`return document.querySelectorAll('.fs-ident').length === 0;`));

  /* ── 2 · Nothing is stored where a script could read it ────────────────── */

  report.section('The browser holds no script-readable credential');

  report.check('localStorage is empty',
    await evaluate(`return window.localStorage.length === 0;`),
    await evaluate(`return JSON.stringify(Object.keys(window.localStorage));`));

  report.check('sessionStorage is empty',
    await evaluate(`return window.sessionStorage.length === 0;`),
    await evaluate(`return JSON.stringify(Object.keys(window.sessionStorage));`));

  /* ── 3 · Signing in mounts the application ─────────────────────────────── */

  report.section('Signing in mounts the application for the named GM');

  await evaluate(signIn(GM_EMAIL));

  report.check('the gate is dismissed',
    await evaluate(`return document.getElementById('fs-gate').hidden === true;`));

  report.check('the five destinations are mounted',
    await evaluate(`return document.querySelectorAll('.fs-tabbar__item').length === 5;`));

  report.check('the acting identity is shown in the masthead',
    await evaluate(`
      const el = document.querySelector('.fs-ident__who');
      return !!el && el.textContent.trim().length > 0;
    `),
    await evaluate(`
      const el = document.querySelector('.fs-ident__who');
      return el ? el.textContent.trim() : '(absent)';
    `));

  report.check('a GM gets no commissioner badge',
    await evaluate(`return document.querySelectorAll('.fs-ident__badge').length === 0;`));

  report.check('the identity shown is the one the server reports',
    await evaluate(asyncProbe(`
      const res = await fetch('/auth/me', { credentials: 'same-origin' });
      const me = await res.json();
      const shown = document.querySelector('.fs-ident__who').textContent.trim();
      return shown === (me.team_name || me.email);
    `)));

  /* ── 4 · The token is genuinely unreachable from script ────────────────── */

  report.section('The session token is unreachable from script');

  const cookieText = await evaluate(`return document.cookie;`);

  report.check('the session cookie is not visible to document.cookie',
    !cookieText.includes('fs_session'), cookieText);

  report.check('no JWT is visible to document.cookie',
    !/eyJ[A-Za-z0-9_-]{8,}\./.test(cookieText), cookieText);

  report.check('the CSRF cookie IS visible — the page must echo it',
    cookieText.includes('fs_csrf'), cookieText);

  report.check('localStorage is still empty after signing in',
    await evaluate(`return window.localStorage.length === 0;`),
    await evaluate(`return JSON.stringify(Object.keys(window.localStorage));`));

  report.check('sessionStorage is still empty after signing in',
    await evaluate(`return window.sessionStorage.length === 0;`),
    await evaluate(`return JSON.stringify(Object.keys(window.sessionStorage));`));

  /* ── 5 · The CSRF gate is real, in a real browser ──────────────────────── */

  report.section('A mutation that bypasses the client seam is refused');

  // The point of this check: it is not asserting that the app behaves, it is
  // asserting that MISBEHAVING does not work. A raw same-origin fetch carries
  // the cookie automatically and omits the CSRF header — exactly the shape of
  // a request that skipped the authenticated client.
  report.check('a raw fetch with the cookie but no CSRF header is refused 403',
    await evaluate(asyncProbe(`
      const res = await fetch('/auth/promote', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: ${JSON.stringify(GM_EMAIL)}, role: 'gm' }),
      });
      return res.status === 403;
    `)));

  report.check('and the same request with the token gets past CSRF to authorization',
    await evaluate(asyncProbe(`
      const token = document.cookie.split(';').map(s => s.trim())
        .find(s => s.startsWith('fs_csrf='));
      const res = await fetch('/auth/promote', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json',
                   'X-FS-CSRF': decodeURIComponent(token.slice('fs_csrf='.length)) },
        body: JSON.stringify({ email: ${JSON.stringify(GM_EMAIL)}, role: 'gm' }),
      });
      // 403 for the GM's LACK OF ROLE is the correct outcome and is a
      // different refusal from the CSRF one — what matters is that the reason
      // moved from the token to the authority.
      const body = await res.json();
      return res.status === 403 && /[Cc]ommissioner/.test(body.detail || '');
    `)),
    'the refusal should now be about authority, not about CSRF');

  /* ── 6 · The session survives a reload ─────────────────────────────────── */

  report.section('The session survives a navigation');

  await reload();

  report.check('the application mounts again without a second sign-in',
    await evaluate(`
      return document.getElementById('fs-gate').hidden === true
        && document.querySelectorAll('.fs-tabbar__item').length === 5;
    `));

  /* ── 7 · Signing out empties the view and the cookie jar ───────────────── */

  report.section('Signing out ends the session and empties the view');

  await evaluate(`
    document.getElementById('fs-signout').click();
    return new Promise((ok) => setTimeout(ok, 700));
  `);

  report.check('the gate is shown again',
    await evaluate(`return document.getElementById('fs-gate').hidden === false;`));

  report.check('the panels are emptied, not merely hidden',
    await evaluate(`return document.getElementById('fs-panels').innerHTML.trim() === '';`));

  report.check('the navigation is emptied',
    await evaluate(`return document.getElementById('fs-tabbar').innerHTML.trim() === '';`));

  report.check('the CSRF cookie is gone from the browser',
    await evaluate(`return !document.cookie.includes('fs_csrf');`),
    await evaluate(`return document.cookie || '(empty)';`));

  report.check('the server no longer recognises the session',
    await evaluate(asyncProbe(`
      const res = await fetch('/auth/me', { credentials: 'same-origin' });
      return res.status === 401;
    `)));

  /* ── 8 · Capability presentation follows the server ────────────────────── */

  report.section('Capability presentation follows the server, not the client');

  await evaluate(signIn(COMM_EMAIL));

  report.check('a commissioner is badged as one',
    await evaluate(`return document.querySelectorAll('.fs-ident__badge').length === 1;`));

  report.check('the badge follows /auth/me rather than anything held locally',
    await evaluate(asyncProbe(`
      const res = await fetch('/auth/me', { credentials: 'same-origin' });
      const me = await res.json();
      const badged = document.querySelectorAll('.fs-ident__badge').length === 1;
      return badged === (me.capabilities.is_commissioner === true);
    `)));

  report.check('the league authority list came from the server',
    await evaluate(asyncProbe(`
      const res = await fetch('/auth/me', { credentials: 'same-origin' });
      const me = await res.json();
      return Array.isArray(me.capabilities.commissioner_league_ids)
        && me.capabilities.commissioner_league_ids.length === 1;
    `)));

  /* ── 9 · One door for the network ──────────────────────────────────────── */

  report.section('The application reaches the network through one module only');

  report.check('no page script wrote a cookie',
    await evaluate(`
      // document.cookie's setter is the only way a page can write one. If the
      // app had used it, this probe would be pointless — so the check is that
      // the only cookie present is the one the SERVER set.
      const names = document.cookie.split(';').map(s => s.trim().split('=')[0]).filter(Boolean);
      return names.every((n) => n === 'fs_csrf');
    `),
    await evaluate(`return document.cookie || '(empty)';`));
});

report.finish();