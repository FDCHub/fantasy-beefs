/* ============================================================================
 * FantasyStakes — sign-in gate and acting-identity presentation
 * Sprint 8 Package 1 · authentication cut over to Yahoo in WP3D.1
 *
 * TWO SMALL SURFACES, ONE RULE: neither decides anything. The gate starts a
 * Yahoo sign-in and draws what came back; the identity block draws what
 * `/auth/me` said. Nothing here derives authority.
 *
 * WHAT WP3D.1 REMOVED, AND WHY IT MATTERS THAT IT IS REMOVED RATHER THAN
 * HIDDEN. This file used to hold an email field, a password field and a
 * submit that posted both. Production authentication is now Yahoo's, so there
 * is no password to collect — and a credential form that merely stopped being
 * shown would still be a credential form one CSS rule away from returning.
 * The production surface has no password input at all, and the suite asserts
 * that by counting inputs rather than by reading a class name.
 *
 * FANTASYSTAKES NEVER SEES A YAHOO PASSWORD. The GM leaves for Yahoo, Yahoo
 * authenticates the Yahoo account by whatever method that account uses, and
 * the GM comes back with a FantasyStakes session. This page has no field that
 * could hold a Yahoo credential and never asks for one — which is also why it
 * must not imitate Yahoo's own sign-in page: a page that looks like Yahoo's is
 * exactly what a page collecting Yahoo passwords would look like.
 *
 * THE DEVELOPMENT SIGN-IN IS SERVER-DECLARED, NEVER CLIENT-CHOSEN. The gate
 * asks `/auth/methods` what this deployment accepts. A production process says
 * `password: false` and the form is not built; there is no query parameter, no
 * key sequence and no local flag that can conjure it, because the decision was
 * never the browser's to make — and the routes refuse it server-side anyway.
 * ========================================================================== */

import { escapeHtml } from './components.js';
import {
  ApiError, apiFetch, currentIdentity, login, logout,
} from './session.js';

/* ── Where a finished or failed Yahoo sign-in lands ─────────────────────── */

/**
 * Product language for every reason code the callback can hand back.
 *
 * ONE SENTENCE PER SITUATION, and none of them is a status code, an OAuth
 * error string, an endpoint or a token. The callback only ever puts a code
 * from its own fixed set into the URL; anything else falls to the last line,
 * so an unrecognised value cannot become copy.
 */
const SIGN_IN_MESSAGES = Object.freeze({
  cancelled: 'Sign-in was cancelled. You can try again whenever you like.',
  state_invalid: 'That sign-in could not be verified. Start again from here.',
  sign_in_expired: 'That sign-in took too long. Start again from here.',
  exchange_failed: 'Yahoo could not complete the sign-in. Try again.',
  identity_token_invalid: 'Yahoo could not complete the sign-in. Try again.',
  identity_unavailable: 'Yahoo did not return enough to identify your account.',
  replay_detected: 'That sign-in could not be verified. Start again from here.',
  provider_unreachable: 'Yahoo could not be reached just now. Try again in a moment.',
  sign_in_unavailable: 'Sign-in is temporarily unavailable. Please try again shortly.',
});

/**
 * The reason the last sign-in attempt failed, read from the URL and REMOVED.
 *
 * The query is stripped with `replaceState` as soon as it is read: a reason
 * code left in the address bar survives a refresh and re-announces a failure
 * the GM has already seen and already retried past.
 *
 * @returns {string|null}
 */
function takeSignInReason() {
  if (typeof window === 'undefined' || !window.location) return null;
  const params = new URLSearchParams(window.location.search);
  const reason = params.get('auth');
  if (!reason) return null;
  params.delete('auth');
  const query = params.toString();
  const url = window.location.pathname + (query ? `?${query}` : '')
    + window.location.hash;
  if (window.history && window.history.replaceState) {
    window.history.replaceState({}, '', url);
  }
  return reason;
}

/** What this deployment accepts as a login. Server-declared. */
let METHODS = { yahoo: true, password: false, unavailable_reason: null };

/**
 * Ask the server which logins it offers.
 *
 * A FAILED READ ASSUMES YAHOO AND NOTHING ELSE. If the server cannot be
 * reached, the safe presentation is the production one: offering a password
 * form on a guess would be offering a login this deployment may not have.
 *
 * @returns {Promise<object>}
 */
export async function loadAuthMethods() {
  try {
    const body = await apiFetch('/auth/methods');
    METHODS = {
      yahoo: body.yahoo !== false,
      password: body.password === true,
      unavailable_reason: body.unavailable_reason || null,
    };
  } catch {
    METHODS = { yahoo: true, password: false, unavailable_reason: null };
  }
  return METHODS;
}

/** The methods last read, for the gate and the suites. @returns {object} */
export function authMethods() {
  return METHODS;
}

/* ── The gate ───────────────────────────────────────────────────────────── */

/**
 * Markup for the sign-in gate.
 *
 * THE YAHOO ACTION IS A LINK, NOT A SCRIPTED BUTTON. `/auth/yahoo/start` is a
 * top-level navigation that ends at Yahoo, and an anchor is what a browser
 * already knows how to do with that: it is keyboard-operable, it is announced
 * as a link, it works before any script has run, and it needs no handler that
 * could fail. It reads as the primary action because it carries the primary
 * button's own class, not because of anything about Yahoo.
 *
 * NO LOGO IS REQUIRED TO UNDERSTAND IT. The label is words. Rev 4.3 §23 does
 * not permit a Yahoo mark here, and WP3D.1 §33 requires the action to be
 * comprehensible without an image — the two agree.
 *
 * @returns {string}
 */
export function buildGate() {
  const reason = takeSignInReason();
  const message = reason
    ? (SIGN_IN_MESSAGES[reason] || 'That sign-in could not be completed. Try again.')
    : '';

  const yahooBlock = METHODS.yahoo
    ? (
      '<a class="fs-btn fs-btn--gold fs-gate__yahoo" id="fs-gate-yahoo" '
        + 'href="/auth/yahoo/start" role="button">Sign in with Yahoo</a>'
      + '<p class="fs-gate__explain">Connect securely with your Yahoo account '
        + 'to access your FantasyStakes leagues. FantasyStakes never sees your '
        + 'Yahoo password.</p>'
    )
    : (
      '<p class="fs-gate__error" role="alert">'
      + escapeHtml(METHODS.unavailable_reason
        || 'Sign-in is temporarily unavailable. Please try again shortly.')
      + '</p>'
    );

  return (
    '<div class="fs-gate__inner">' +
      '<div class="fs-gate__lockup">' +
        '<div class="fs-mast__word">' +
          '<span class="fs-word-a">Fantasy</span><span class="fs-word-b">Stakes</span>' +
        '</div>' +
        '<div class="fs-gate__tagline">SIGN IN TO YOUR LEAGUE</div>' +
      '</div>' +

      // aria-live so a failed or cancelled return is announced, not merely drawn.
      '<p class="fs-gate__error" id="fs-gate-error" role="alert" aria-live="polite">'
      + escapeHtml(message) + '</p>' +

      yahooBlock +

      demoEntry() +

      devSignIn() +

      '<p class="fs-gate__note">Virtual Credits · $ is display only · no cash value</p>' +
    '</div>'
  );
}

/**
 * Wire "Try Demo" to the public entry route.
 *
 * BOUND SEPARATELY FROM THE SIGN-IN FORM, and before it. `bindGate` returns
 * early when the development sign-in form is absent — which it is on every
 * production build — so binding the demo control inside that path would have
 * left the button dead in exactly the deployment it exists for.
 *
 * The route needs no CSRF header: it carries no authority to abuse, takes no
 * parameters, and the session it issues is the one the visitor is asking for.
 *
 * @param {ParentNode} root
 */
export function bindDemoEntry(root) {
  const button = root.querySelector('#fs-gate-demo');
  if (!button) return;
  let inFlight = false;
  button.addEventListener('click', async () => {
    if (inFlight) return;
    inFlight = true;
    button.setAttribute('disabled', 'disabled');
    try {
      // THROUGH `session.js`, LIKE EVERY OTHER MODULE. A raw `fetch` here broke
      // the certified invariant that exactly one module in the application
      // makes network calls — `test_s7_full_ui_certification.py` caught it, and
      // it was right to: the one-door rule is what makes "no illustrative UI
      // path can bypass the authenticated client" a fact rather than a habit.
      await apiFetch('/demo/enter', { method: 'POST' });
      // A full reload, so the shell re-reads the session it now holds rather
      // than trying to reconcile a signed-out page into a signed-in one.
      window.location.assign('/app/index.html');
    } catch (error) {
      const el = root.querySelector('#fs-gate-error');
      if (el) {
        el.textContent = error instanceof ApiError
          ? 'The demo league is not available on this deployment yet.'
          : 'The demo could not be started. Please try again shortly.';
      }
    } finally {
      inFlight = false;
      button.removeAttribute('disabled');
    }
  });
}

/**
 * "Try Demo" — the way into the product without a Yahoo account.
 *
 * ── D1.1 · WHY THE GATE NEEDED THIS ──────────────────────────────────────
 *
 * Before this, the signed-out gate offered exactly one control: Sign in with
 * Yahoo. A prospective GM, a commissioner deciding whether to bring a league
 * across, or a Yahoo reviewer could not see the product at all without first
 * handing over an account. That is the opposite of what a demo is for.
 *
 * IT IS NOT A SIGN-IN AND IS NOT DRESSED AS ONE. Secondary styling, placed
 * below the Yahoo control, and it says plainly that what follows is sample
 * data — so nobody can arrive in the demo believing they are looking at their
 * own league.
 *
 * @returns {string}
 */
export function demoEntry() {
  return (
    '<button class="fs-btn fs-gate__demo" id="fs-gate-demo" type="button">'
      + 'Try Demo</button>'
    + '<p class="fs-gate__explain">Explore a sample league with fictional '
      + 'teams and results. No Yahoo account, no sign-in, nothing to connect.</p>'
  );
}

/**
 * The development sign-in, drawn ONLY where the server says it exists.
 *
 * IT IS LABELLED FOR WHAT IT IS. A developer running the app locally should be
 * in no doubt that this is not how a GM signs in, and a screenshot of it should
 * be unmistakable if it ever appears somewhere it should not.
 *
 * @returns {string}
 */
function devSignIn() {
  if (!METHODS.password) return '';
  return (
    '<details class="fs-gate__dev" id="fs-gate-dev">'
    + '<summary class="fs-gate__devsummary">Development sign-in</summary>'
    + '<p class="fs-gate__devnote">Not available in production. Production '
    + 'authentication is Sign in with Yahoo.</p>'
    + '<form class="fs-gate__form" id="fs-gate-form" novalidate>'
      + '<label class="fs-gate__label" for="fs-gate-email">Email</label>'
      + '<input class="fs-gate__input" id="fs-gate-email" name="email" type="email" '
        + 'autocomplete="username" autocapitalize="none" autocorrect="off" '
        + 'spellcheck="false" required>'
      + '<label class="fs-gate__label" for="fs-gate-password">Password</label>'
      + '<input class="fs-gate__input" id="fs-gate-password" name="password" '
        + 'type="password" autocomplete="current-password" required>'
      + '<p class="fs-gate__error" id="fs-gate-deverror" role="alert" '
        + 'aria-live="polite"></p>'
      + '<button class="fs-btn fs-gate__submit" id="fs-gate-submit" '
        + 'type="submit">Sign in</button>'
    + '</form>'
    + '</details>'
  );
}

/**
 * Bind the gate.
 *
 * The Yahoo action needs no binding — it is a link. What is bound is the
 * development form, and only when it was drawn.
 *
 * NO SUCCESS CALLBACK, DELIBERATELY. A successful sign-in changes identity, and
 * the shell re-renders from the identity subscription in `session.js`. Handing
 * this function a second way to trigger that would give the application two
 * paths into the same transition, and only one of them would get exercised.
 *
 * @param {HTMLElement} root the gate container
 */
export function bindGate(root) {
  bindDemoEntry(root);

  const form = root.querySelector('#fs-gate-form');
  if (!form) return;
  const errorEl = root.querySelector('#fs-gate-deverror');
  const submit = root.querySelector('#fs-gate-submit');
  if (!errorEl || !submit) return;

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
      if (error instanceof ApiError && error.status === 404) {
        // The server retired this route underneath a stale page.
        errorEl.textContent = 'This deployment uses Sign in with Yahoo.';
      } else if (error instanceof ApiError && error.status === 401) {
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
 * LABEL — it grants nothing.
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
 * WHAT SIGNING OUT MEANS, EXACTLY. It ends the FantasyStakes session and clears
 * this browser's identity. It does NOT sign the GM out of Yahoo, and the copy
 * does not claim it does: Yahoo owns that session, FantasyStakes cannot end it,
 * and telling a GM otherwise on a shared device would be dangerous.
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
