/* ============================================================================
 * FantasyStakes — WP3D.1 · the sign-in gate, rendered · component tests
 *
 * Run directly:   node web/tests/wp3d1_component_tests.mjs
 * Or through:     python test_wp3d1_yahoo_auth.py
 *
 * THE GATE IS DRIVEN AGAINST A SERVER ANSWER THIS SUITE CHOOSES. `buildGate()`
 * renders from whatever `/auth/methods` last said, and the two answers that
 * matter — production and development — cannot both be true of one running
 * server. Setting the answer directly is the only way to render both in one
 * pass, and the failure-reason branches need a URL that a real sign-in would
 * have to fail to produce.
 * ========================================================================== */

import { readFileSync } from 'node:fs';

const failures = [];

function check(label, condition, detail = '') {
  const mark = condition ? 'PASS' : 'FAIL';
  console.log(`  [${mark}] ${label}${detail ? ` — ${detail}` : ''}`);
  if (!condition) failures.push(label);
}

function section(title) {
  console.log(`\n${title}`);
}

/* ── A DOM and a location, because the gate reads both ──────────────────── */

let CURRENT_URL = 'https://stakes.example/app/index.html';
const REPLACED = [];

globalThis.window = {
  get location() {
    const url = new URL(CURRENT_URL);
    return { search: url.search, pathname: url.pathname, hash: url.hash };
  },
  history: {
    replaceState(_state, _title, url) {
      REPLACED.push(url);
      CURRENT_URL = new URL(url, CURRENT_URL).toString();
    },
  },
};
globalThis.document = undefined;

const { authMethods, buildGate } = await import('../js/auth-view.js');

/** Set what the server last said, without a server. */
function setMethods(next) {
  Object.assign(authMethods(), next);
}

/* ── A · the production gate ─────────────────────────────────────────────── */

section('A · The production gate collects no credential');

setMethods({ yahoo: true, password: false, unavailable_reason: null });
CURRENT_URL = 'https://stakes.example/app/index.html';
let gate = buildGate();

check('it offers Sign in with Yahoo', gate.includes('>Sign in with Yahoo</a>'));
check('as a real anchor to the server-side start route',
  gate.includes('href="/auth/yahoo/start"'), 'navigation, not fetch');
check('carrying the primary-action treatment',
  gate.includes('fs-btn--gold'));
check('and an accessible role so it announces as an action',
  gate.includes('role="button"'));

check('THERE IS NO PASSWORD INPUT', !/type="password"/.test(gate));
check('there is no email input either', !/type="email"/.test(gate));
check('no input of any kind is rendered', !/<input/.test(gate), 'zero inputs');
check('no form is rendered', !/<form/.test(gate));
check('and no development sign-in is offered',
  !gate.includes('Development sign-in'));

check('no forgot-password link', !/forgot/i.test(gate));
check('no password reset', !/reset/i.test(gate));
check('no account-creation form', !/sign\s*up|create account|register/i.test(gate));

check('the product keeps its own name and lockup',
  gate.includes('Fantasy') && gate.includes('Stakes'));
check('it does not imitate a Yahoo sign-in page',
  !/yahoo\.com\/(login|config)/i.test(gate)
  && !/enter your yahoo password/i.test(gate));
check('no Yahoo logo or image is used',
  !/<img|\.svg|\.png/i.test(gate));
check('the supporting copy says what Yahoo is for',
  gate.includes('Connect securely with your Yahoo account'));
check('and states that FantasyStakes never sees the password',
  gate.includes('FantasyStakes never sees your Yahoo password'));
check('no endorsement is claimed',
  !/official|partner|approved|powered by/i.test(gate));
check('the virtual-Credits note survives',
  gate.includes('no cash value'));

/* ── B · the development gate ────────────────────────────────────────────── */

section('B · The development gate adds a local sign-in, clearly labelled');

setMethods({ yahoo: true, password: true, unavailable_reason: null });
gate = buildGate();

check('Sign in with Yahoo is still the primary action',
  gate.includes('>Sign in with Yahoo</a>'));
check('the local sign-in appears', gate.includes('Development sign-in'));
check('collapsed behind a disclosure rather than presented as an equal',
  gate.includes('<details') && gate.includes('<summary'));
check('it says plainly that it is not production',
  gate.includes('Not available in production'));
check('and names what production uses instead',
  gate.includes('Production authentication is Sign in with Yahoo'));
check('the password field exists only here',
  (gate.match(/type="password"/g) || []).length === 1);
check('its submit is NOT the gold primary — Yahoo is',
  !/fs-gate__submit[^>]*fs-btn--gold/.test(gate)
  && gate.includes('fs-gate__submit'));

/* ── C · a deployment that cannot sign anyone in ─────────────────────────── */

section('C · A misconfigured production process says so, and offers nothing');

setMethods({ yahoo: false, password: false,
  unavailable_reason: 'Sign-in is temporarily unavailable. Please try again shortly.' });
gate = buildGate();

check('no Yahoo action is offered', !gate.includes('/auth/yahoo/start'));
check('no password form appears in its place', !/<input/.test(gate));
check('the state is stated in product language',
  gate.includes('Sign-in is temporarily unavailable'));
check('and names no configuration variable',
  !/FS_YAHOO|CLIENT_ID|CLIENT_SECRET|env/i.test(gate));

/* ── D · returning from a failed sign-in ─────────────────────────────────── */

section('D · Every callback reason becomes a sentence, and leaves the URL');

const REASONS = [
  ['cancelled', /cancelled/i],
  ['state_invalid', /could not be verified/i],
  ['sign_in_expired', /took too long/i],
  ['exchange_failed', /could not complete/i],
  ['identity_token_invalid', /could not complete/i],
  ['identity_unavailable', /identify your account/i],
  ['replay_detected', /could not be verified/i],
  ['provider_unreachable', /could not be reached/i],
  ['sign_in_unavailable', /temporarily unavailable/i],
];

setMethods({ yahoo: true, password: false, unavailable_reason: null });
for (const [reason, pattern] of REASONS) {
  CURRENT_URL = `https://stakes.example/app/index.html?auth=${reason}`;
  REPLACED.length = 0;
  const drawn = buildGate();
  check(`${reason} renders a sentence`, pattern.test(drawn),
    (drawn.match(/id="fs-gate-error"[^>]*>([^<]*)/) || [])[1] || '(none)');
  // THE SENTENCE, NOT THE PAGE. `cancelled` is both a reason code and an
  // ordinary English word, so scanning the whole gate for the code's letters
  // would fail on copy that is exactly right. What must never appear is a
  // MACHINE token — an underscored code, a status, an OAuth term — and that is
  // what is checked, inside the error element itself.
  const sentence = (drawn.match(/id="fs-gate-error"[^>]*>([^<]*)/) || ['', ''])[1];
  check('  · and no code, status or internal term is shown',
    !/_/.test(sentence)
    && !/token|oauth|oidc|http|endpoint|4\d\d|5\d\d/i.test(sentence),
    sentence);
  check('  · the reason is stripped from the address bar',
    REPLACED.length === 1 && !REPLACED[0].includes('auth='),
    REPLACED[0] || '(not replaced)');
  check('  · and the Yahoo action is offered again',
    drawn.includes('>Sign in with Yahoo</a>'));
}

CURRENT_URL = 'https://stakes.example/app/index.html?auth=<script>alert(1)</script>';
REPLACED.length = 0;
const hostile = buildGate();
check('an unrecognised reason falls back to a safe sentence',
  /could not be completed/i.test(hostile));
check('and is never echoed into the page',
  !hostile.includes('<script>alert'), 'escaped and discarded');

CURRENT_URL = 'https://stakes.example/app/index.html';
REPLACED.length = 0;
const clean = buildGate();
check('an ordinary visit shows no error at all',
  /id="fs-gate-error"[^>]*><\/p>/.test(clean));
check('and rewrites no history', REPLACED.length === 0);

/* ── E · the source, audited ─────────────────────────────────────────────── */

section('E · The browser holds no authority and no credential');

const src = (name) => readFileSync(
  new URL(`../js/${name}`, import.meta.url), 'utf8');
const codeOnly = (t) => t
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/^\s*\/\/.*$/gm, ' ');

const GATE = codeOnly(src('auth-view.js'));
const SESSION = codeOnly(src('session.js'));

for (const forbidden of ['client_secret', 'clientSecret', 'id_token',
  'access_token', 'refresh_token', 'grant_type', 'code_verifier',
  'code_challenge', 'get_token', 'localStorage', 'sessionStorage']) {
  check(`the gate never touches ${forbidden}`, !GATE.includes(forbidden));
  check(`  · nor does the session module`, !SESSION.includes(forbidden));
}

check('the gate never exchanges anything — it navigates',
  !/fetch\(['"`]\/auth\/yahoo/.test(GATE));
check('it reads the available methods from the server',
  GATE.includes("apiFetch('/auth/methods')"));
check('and cannot enable the local sign-in itself',
  GATE.includes('if (!METHODS.password)')
  && !/METHODS\.password\s*=\s*true/.test(GATE));
check('a failed methods read assumes the PRODUCTION surface',
  /catch\s*{\s*METHODS = \{ yahoo: true, password: false/.test(
    GATE.replace(/\s+/g, ' ')), 'fails closed');

console.log(`\n${'='.repeat(52)}`);
if (failures.length) {
  console.log(`${failures.length} ASSERTION(S) FAILED`);
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
console.log('All assertions PASSED');
