/* ============================================================================
 * FantasyStakes — sign-in gate and acting-identity presentation
 * Sprint 8 Package 1
 *
 * TWO SMALL SURFACES, ONE RULE: neither decides anything. The gate collects a
 * password and hands it to the session module; the identity block draws what
 * `/auth/me` said. Nothing here derives authority, and nothing here holds a
 * credential — the password is read out of the form field, passed to `login()`
 * and never written anywhere, not even to a local variable that outlives the
 * call.
 *
 * WHY THE APPLICATION IS GATED AT ALL, GIVEN THE TABS STILL DRAW ILLUSTRATIVE
 * DATA. Because the alternative is worse. Sprint 8 binds these surfaces to a
 * specific GM's real position; a shell that renders before anyone is named
 * would have to decide what to show in the meantime, and every honest answer
 * to that is a second, unauthenticated rendering path — exactly the bypass the
 * certification suite now forbids. Gating first means the binding packages
 * have one path to bind.
 *
 * THE ERROR MESSAGE IS DELIBERATELY VAGUE. The server does not say whether an
 * email exists, and neither does this: "check your details" for both a wrong
 * password and an unknown address, so the form cannot be used to enumerate
 * which GMs have accounts.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import { ApiError, currentIdentity, login, logout } from './session.js';

/* ── The gate ───────────────────────────────────────────────────────────── */

/**
 * Markup for the sign-in gate.
 *
 * `autocomplete` is set so a password manager fills this correctly, and
 * `type="password"` so the value is never rendered. The form is a real form
 * with a submit button, so Enter works and assistive tech announces it as one.
 *
 * @returns {string}
 */
export function buildGate() {
  return (
    '<div class="fs-gate__inner">' +
      '<div class="fs-gate__lockup">' +
        '<div class="fs-mast__word">' +
          '<span class="fs-word-a">Fantasy</span><span class="fs-word-b">Stakes</span>' +
        '</div>' +
        '<div class="fs-gate__tagline">SIGN IN TO YOUR LEAGUE</div>' +
      '</div>' +

      '<form class="fs-gate__form" id="fs-gate-form" novalidate>' +
        '<label class="fs-gate__label" for="fs-gate-email">Email</label>' +
        '<input class="fs-gate__input" id="fs-gate-email" name="email" type="email" ' +
          'autocomplete="username" autocapitalize="none" autocorrect="off" ' +
          'spellcheck="false" required>' +

        '<label class="fs-gate__label" for="fs-gate-password">Password</label>' +
        '<input class="fs-gate__input" id="fs-gate-password" name="password" ' +
          'type="password" autocomplete="current-password" required>' +

        // aria-live so a failure is announced, not merely drawn.
        '<p class="fs-gate__error" id="fs-gate-error" role="alert" aria-live="polite"></p>' +

        '<button class="fs-btn fs-btn--gold fs-gate__submit" id="fs-gate-submit" ' +
          'type="submit">Sign in</button>' +
      '</form>' +

      '<p class="fs-gate__note">Virtual Credits · $ is display only · no cash value</p>' +
    '</div>'
  );
}

/**
 * Bind the gate's form.
 *
 * NO SUCCESS CALLBACK, DELIBERATELY. A successful `login()` changes identity,
 * and the shell re-renders from the identity subscription in `session.js`.
 * Handing this function a second way to trigger that would give the
 * application two paths into the same transition — one for a voluntary sign-in
 * and one for everything else — and only one of them would get exercised.
 *
 * @param {HTMLElement} root the gate container
 */
export function bindGate(root) {
  const form = root.querySelector('#fs-gate-form');
  const errorEl = root.querySelector('#fs-gate-error');
  const submit = root.querySelector('#fs-gate-submit');
  if (!form || !errorEl || !submit) return;

  let inFlight = false;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (inFlight) return;

    const email = /** @type {HTMLInputElement} */ (form.querySelector('#fs-gate-email')).value.trim();
    const passwordField = /** @type {HTMLInputElement} */ (form.querySelector('#fs-gate-password'));

    errorEl.textContent = '';
    if (!email || !passwordField.value) {
      errorEl.textContent = 'Enter your email and password.';
      return;
    }

    inFlight = true;
    submit.disabled = true;
    submit.textContent = 'Signing in…';

    try {
      await login(email, passwordField.value);
      // Cleared on the success path too. The field is about to be detached,
      // but clearing it is one line and means the value is not sitting in a
      // live DOM node while the application mounts.
      passwordField.value = '';
    } catch (error) {
      passwordField.value = '';
      if (error instanceof ApiError && error.status === 401) {
        errorEl.textContent = 'Those details were not recognised. Check them and try again.';
      } else if (error instanceof ApiError && error.status === 403) {
        errorEl.textContent = 'That request was refused. Reload the page and try again.';
      } else {
        errorEl.textContent = 'Could not reach the league server. Try again in a moment.';
      }
      passwordField.focus();
    } finally {
      inFlight = false;
      submit.disabled = false;
      submit.textContent = 'Sign in';
    }
  });
}

/* ── Acting identity ────────────────────────────────────────────────────── */

/**
 * The masthead identity block: who is acting, and how to stop.
 *
 * The team name is shown when the account is bound to one and the email when
 * it is not, because an unbound account is a real state the server can report
 * and inventing a team name for it would be a lie in the one place the GM
 * checks who they are.
 *
 * The commissioner badge follows `is_commissioner` from the server. It is a
 * LABEL — it grants nothing, and S8-P2 will narrow what the role means
 * server-side without this file changing.
 *
 * @returns {string}
 */
export function buildIdentityBlock() {
  const identity = currentIdentity();
  if (!identity) return '';

  const caps = identity.capabilities || {};
  const who = identity.team_name || identity.email || 'Signed in';
  const badge = caps.is_commissioner
    ? '<span class="fs-ident__badge">COMMISSIONER</span>'
    : '';

  return (
    '<div class="fs-ident">' +
      `<span class="fs-ident__who">${escapeHtml(who)}</span>` +
      badge +
      '<button type="button" class="fs-ident__out" id="fs-signout">Sign out</button>' +
    '</div>'
  );
}

/**
 * Bind the sign-out control.
 *
 * Like the gate, no callback: `logout()` drops identity — in a `finally`, so a
 * failed call still signs the GM out locally — and the shell's subscription
 * takes it from there.
 *
 * @param {HTMLElement} root element containing the identity block
 */
export function bindIdentityBlock(root) {
  const button = root.querySelector('#fs-signout');
  if (!button) return;

  button.addEventListener('click', async () => {
    button.disabled = true;
    await logout();
  });
}