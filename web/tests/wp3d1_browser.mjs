/* ============================================================================
 * FantasyStakes — WP3D.1 · the sign-in gate, in a browser · browser suite
 *
 * Run through:  python test_wp3d1_yahoo_auth.py
 *
 * RUN TWICE, AGAINST TWO REAL SERVERS. `FS_WP3D1_MODE` names which:
 *
 *   development   a local process — Yahoo first, the local sign-in behind a
 *                 disclosure, and the app reachable through it
 *   production    `FS_ENV=production` with a complete Yahoo configuration —
 *                 the password routes REFUSE, and the page has no field
 *
 * WHY A BROWSER AND NOT THE COMPONENT TIER. The component tier proves the gate
 * renders correctly from an answer it was handed. Only this tier can prove the
 * page ASKS a real server what it accepts, draws that, and — in production —
 * cannot be talked into a password form by anything a browser can do: a query
 * parameter, a console call, or a stale page whose form is submitted anyway.
 *
 * NO INTERACTIVE YAHOO. The suite follows the redirect to the point where it
 * leaves for Yahoo and stops there; what happens after that is certified
 * server-side, against a deterministic Yahoo, in the Python tier.
 * ========================================================================== */

import { createReporter, withPage } from './browser-harness.mjs';

const { check, section, finish } = createReporter();

const MODE = process.env.FS_WP3D1_MODE || 'development';
const PRODUCTION = MODE === 'production';

await withPage({ port: 9481, path: '/app/index.html' },
  async ({ evaluate, reload }) => {

    console.log(`\n(mode: ${MODE})`);

    /* ── What this deployment says it accepts ─────────────────────────────── */

    section('§10/§24 · The server declares its logins, and the page obeys');

    const served = await evaluate(`return (async () => {
      const r = await fetch('/auth/methods', { credentials: 'same-origin' });
      return { status: r.status, body: await r.json() };
    })();`);

    check('the deployment declares its login methods',
      served.status === 200, String(served.status));
    check(`it reports the ${MODE} environment`,
      served.body.environment === MODE, served.body.environment);
    check('Sign in with Yahoo is offered', served.body.yahoo === true,
      String(served.body.yahoo));
    check(`the password login is ${PRODUCTION ? 'RETIRED' : 'available'}`,
      served.body.password === !PRODUCTION, String(served.body.password));
    check('and the declaration carries no client id, secret or redirect',
      !JSON.stringify(served.body).match(/dj0y|secret|redirect|http/i),
      JSON.stringify(served.body));

    /* ── The gate ─────────────────────────────────────────────────────────── */

    section('§12/§32/§33 · The sign-in surface');

    const gate = await evaluate(`
      const gate = document.getElementById('fs-gate');
      const link = gate.querySelector('#fs-gate-yahoo');
      const box = link ? link.getBoundingClientRect() : null;
      return {
        visible: !gate.hidden,
        text: gate.textContent,
        html: gate.innerHTML,
        passwordInputs: gate.querySelectorAll('input[type="password"]').length,
        allInputs: gate.querySelectorAll('input').length,
        forms: gate.querySelectorAll('form').length,
        link: link ? {
          tag: link.tagName,
          href: link.getAttribute('href'),
          label: link.textContent.trim(),
          tabbable: link.tabIndex >= 0,
          height: Math.round(box.height),
          width: Math.round(box.width),
          right: Math.round(box.right),
          images: link.querySelectorAll('img,svg').length,
        } : null,
        devPanel: gate.querySelectorAll('#fs-gate-dev').length,
        docW: document.documentElement.scrollWidth,
        innerW: window.innerWidth,
      };
    `);

    check('the gate is showing', gate.visible === true);
    check('the primary action reads exactly "Sign in with Yahoo"',
      gate.link && gate.link.label === 'Sign in with Yahoo',
      gate.link ? gate.link.label : '(absent)');
    check('it is a real anchor to the server-side start route',
      gate.link.tag === 'A' && gate.link.href === '/auth/yahoo/start',
      `${gate.link.tag} ${gate.link.href}`);
    check('keyboard-operable by default', gate.link.tabbable === true);
    check('and a real touch target', gate.link.height >= 44,
      `${gate.link.height}px`);
    check('it is understandable without an image', gate.link.images === 0,
      `${gate.link.images} images`);

    if (PRODUCTION) {
      check('PRODUCTION: there is no password input on the page',
        gate.passwordInputs === 0, String(gate.passwordInputs));
      check('PRODUCTION: there is no input of any kind',
        gate.allInputs === 0, String(gate.allInputs));
      check('PRODUCTION: there is no form',
        gate.forms === 0, String(gate.forms));
      check('PRODUCTION: no development sign-in is rendered',
        gate.devPanel === 0, String(gate.devPanel));
    } else {
      check('DEVELOPMENT: the local sign-in is offered, behind a disclosure',
        gate.devPanel === 1 && gate.passwordInputs === 1,
        `${gate.devPanel} panel, ${gate.passwordInputs} password field`);
      check('DEVELOPMENT: and it is labelled as not-production',
        /Not available in production/.test(gate.text));
    }

    check('no forgot-password anywhere', !/forgot/i.test(gate.text));
    check('no password reset anywhere', !/reset/i.test(gate.text));
    check('the product is still FantasyStakes',
      /FantasyStakes|Fantasy\s*Stakes/.test(gate.text.replace(/\s+/g, ' '))
      || gate.html.includes('fs-word-a'));
    check('the page does not imitate a Yahoo sign-in',
      !/enter your yahoo password/i.test(gate.text));
    check('no Yahoo endorsement is claimed',
      !/official yahoo|yahoo partner|powered by yahoo|yahoo-approved/i
        .test(gate.text));
    check('the copy explains what Yahoo is for',
      /Connect securely with your Yahoo account/.test(gate.text));
    check('and says FantasyStakes never sees the password',
      /never sees your Yahoo password/.test(gate.text));
    check('the page does not scroll horizontally',
      gate.docW <= gate.innerW, `${gate.docW} vs ${gate.innerW}`);

    /* ── Starting a sign-in ───────────────────────────────────────────────── */

    section('§3/§21 · Starting the flow leaves for Yahoo, server-side');

    const start = await evaluate(`return (async () => {
      const r = await fetch('/auth/yahoo/start',
        { credentials: 'same-origin', redirect: 'manual' });
      // A manual redirect is opaque to script, which is itself the point: the
      // page cannot read where it was sent, cannot read the state, and cannot
      // read the nonce. What it CAN observe is that it was a redirect.
      return { type: r.type, status: r.status,
               cookies: document.cookie };
    })();`);

    check('the start route answers with a redirect the page cannot read',
      start.type === 'opaqueredirect' || start.status === 0
      || (start.status >= 300 && start.status < 400),
      `${start.type} ${start.status}`);
    check('the transaction cookie is NOT readable from script',
      !/fs_yahoo_txn/.test(start.cookies), start.cookies || '(none)');

    /* ── §21 · what the browser holds ─────────────────────────────────────── */

    section('§21/§31 · The browser holds no credential and no authority');

    const audit = await evaluate(`
      const keys = [];
      try { for (let i = 0; i < localStorage.length; i += 1) keys.push('local:' + localStorage.key(i)); } catch (e) { keys.push('local:blocked'); }
      try { for (let i = 0; i < sessionStorage.length; i += 1) keys.push('session:' + sessionStorage.key(i)); } catch (e) { keys.push('session:blocked'); }
      return {
        storage: keys,
        cookies: document.cookie,
        bodyText: document.body.textContent,
        html: document.documentElement.innerHTML,
      };
    `);

    check('nothing is written to localStorage or sessionStorage',
      audit.storage.filter((k) => !k.endsWith(':blocked')).length === 0,
      audit.storage.join(', ') || 'empty');
    check('the session cookie is not script-readable',
      !/fs_session/.test(audit.cookies), audit.cookies || '(none)');
    for (const secret of ['client_secret', 'id_token', 'access_token',
      'refresh_token', 'Bearer ', 'dj0y']) {
      check(`no ${secret.trim()} anywhere in the delivered page`,
        !audit.html.includes(secret), 'clean');
    }

    /* ── §24 · production cannot be talked into a password ────────────────── */

    section('§24 · The production gate cannot be reopened from the browser');

    const forced = await evaluate(`return (async () => {
      const r = await fetch('/auth/session', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'gm@example.test',
                               password: 'sprint8-password' }),
      });
      let body = null;
      try { body = await r.json(); } catch (e) { body = null; }
      return { status: r.status, body };
    })();`);

    if (PRODUCTION) {
      check('a hand-rolled password POST is refused by the server',
        forced.status === 404, String(forced.status));
      check('and told the password was retired',
        (forced.body?.detail?.reason_code) === 'password_login_retired',
        JSON.stringify(forced.body).slice(0, 120));
      check('in product language, naming no configuration',
        /Yahoo/.test(JSON.stringify(forced.body))
        && !/FS_YAHOO|FS_ENV/.test(JSON.stringify(forced.body)));

      // A QUERY PARAMETER CANNOT CONJURE THE FORM. The decision is the
      // server's; nothing the address bar carries can change it.
      const smuggled = await evaluate(`return (async () => {
        window.history.replaceState({}, '',
          '/app/index.html?dev=1&password=1&FS_ENV=development');
        return true;
      })();`);
      void smuggled;
      await reload();
      const after = await evaluate(`
        const gate = document.getElementById('fs-gate');
        return { inputs: gate.querySelectorAll('input').length,
                 dev: gate.querySelectorAll('#fs-gate-dev').length };
      `);
      check('a query parameter does not conjure a password form',
        after.inputs === 0 && after.dev === 0,
        `${after.inputs} inputs, ${after.dev} dev panels`);
    } else {
      check('the local sign-in works in development',
        forced.status === 200, String(forced.status));
    }

    /* ── §32 · the gate at every phone width ──────────────────────────────── */

    section('§32 · The sign-in surface fits the phone');

    for (const width of [320, 375, 390, 430]) {
      const m = await evaluate(`
        return (async () => {
          // Measured by narrowing the gate's own container rather than
          // re-emulating: the harness's viewport helper reloads, and this
          // section only needs the CTA's box at each width.
          const gate = document.getElementById('fs-gate');
          gate.style.width = '${width}px';
          const link = gate.querySelector('#fs-gate-yahoo');
          const box = link ? link.getBoundingClientRect() : null;
          const result = {
            fits: box ? box.width <= ${width} + 1 : null,
            height: box ? Math.round(box.height) : null,
            truncated: link ? link.scrollWidth > link.clientWidth + 1 : null,
            overflow: gate.scrollWidth > ${width} + 1,
          };
          gate.style.width = '';
          return result;
        })();
      `);
      check(`${width}: the Yahoo action fits its column`, m.fits === true,
        String(m.fits));
      check(`${width}: its label is not truncated`, m.truncated === false,
        String(m.truncated));
      check(`${width}: it keeps a 44px target`, m.height >= 44,
        `${m.height}px`);
      check(`${width}: the gate does not overflow`, m.overflow === false);
    }
  });

finish('WP3D.1 YAHOO AUTHENTICATION — BROWSER');
