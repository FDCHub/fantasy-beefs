#!/usr/bin/env node
/*
 * FantasyStakes - deterministic remediation reconciliation, v3
 * ===========================================================
 *
 *   node spec/uncluttered/FantasyStakes_Remediation_Reconciliation_v3.js
 *   node spec/uncluttered/FantasyStakes_Remediation_Reconciliation_v3.js --json
 *
 * v3 adds section F17: UPSIDE LEFT, the last Action summary value that was still a stored
 * literal. It is now derived from the accepted, unresolved proposals in the Action
 * lifecycle and is checked the same way as the escrow chain - derived, then driven through
 * to the rendered strip.
 *
 * v2 adds the FSR-023 cross-surface commitment proof chain. The v1 suite compared shared
 * literals, so it could not see that the Action lifecycle held four live commitments while
 * the Ledger recorded two. Section F16 now DERIVES expected escrow from Action lifecycle
 * state and drives it through to both rendered strips, and keeps IN PLAY and Weekly
 * Minimum qualification as separate quantities throughout.
 *
 * Executes the three remediated self-contained artifacts under a minimal DOM shim and
 * checks the fifteen cross-tab identities required for UI/system lock, plus the locked
 * lifecycle regression battery.
 *
 * SCOPE OF EVIDENCE. This is a SOURCE + RUNTIME test. It really executes each artifact's
 * JavaScript, drives its lifecycle functions and reads its published audit objects, so
 * every economic and deterministic claim below is executed rather than asserted on the
 * text. It performs NO layout, paint, font or hit-testing work, so it is NOT a visual
 * browser certification. No browser automation (Playwright / Selenium) is installed in
 * this environment; visual certification remains outstanding and is reported as such.
 */

"use strict";
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const DIR = __dirname;
const FILES = {
  fixture: "FantasyStakes_Canonical_CrossTab_Fixture_v4.js",
  action: "fantasystakes_ACTION_uncluttered_full_prototype_v24_upside.html",
  standings: "fantasystakes_STANDINGS_WRAPUP_deterministic_v8_upside.html",
  account: "fantasystakes_ACCOUNT_GEAR_uncluttered_v25_upside.html",
};

/* ------------------------------------------------------------------ DOM shim */
function makeEl(tagName = "DIV") {
  const el = {
    tagName, __attrs: {}, __classes: new Set(), __listeners: {},
    dataset: {}, style: {}, textContent: "", innerHTML: "", value: "",
    scrollTop: 0, clientHeight: 0, scrollHeight: 0, children: [], disabled: false,
  };
  el.classList = {
    add: (...c) => c.forEach((x) => el.__classes.add(x)),
    remove: (...c) => c.forEach((x) => el.__classes.delete(x)),
    contains: (c) => el.__classes.has(c),
    toggle: (c, force) => {
      const want = force === undefined ? !el.__classes.has(c) : !!force;
      if (want) el.__classes.add(c); else el.__classes.delete(c);
      return want;
    },
  };
  el.setAttribute = (k, v) => { el.__attrs[k] = String(v); };
  el.getAttribute = (k) => (k in el.__attrs ? el.__attrs[k] : null);
  el.hasAttribute = (k) => k in el.__attrs;
  el.removeAttribute = (k) => { delete el.__attrs[k]; };
  el.addEventListener = (t, fn) => { (el.__listeners[t] ||= []).push(fn); };
  el.removeEventListener = () => {};
  el.dispatch = (t) => (el.__listeners[t] || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {}, deltaY: 0 }));
  el.click = () => el.dispatch("click");
  el.appendChild = (c) => { el.children.push(c); return c; };
  el.querySelector = () => makeEl();
  el.querySelectorAll = () => [];
  el.closest = () => null;
  el.focus = () => {};
  el.getBoundingClientRect = () => ({ top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 });
  Object.defineProperty(el, "lastElementChild", { get: () => makeEl(), configurable: true });
  Object.defineProperty(el, "firstElementChild", { get: () => makeEl(), configurable: true });
  return el;
}

function parseRouteElements(html) {
  const out = [];
  const re = /<(\w+)([^>]*\bdata-route="([^"]+)"[^>]*)>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    const [, tag, attrs, route] = m;
    const el = makeEl(tag.toUpperCase());
    el.dataset.route = route;
    const aria = /aria-label="([^"]*)"/.exec(attrs);
    if (aria) el.__attrs["aria-label"] = aria[1];
    const scr = /data-screen="([^"]*)"/.exec(attrs);
    if (scr) el.dataset.screen = scr[1];
    const cls = /class="([^"]*)"/.exec(attrs);
    if (cls) el.__classes = new Set(cls[1].split(/\s+/).filter(Boolean));
    out.push(el);
  }
  return out;
}

function runArtifact(file, opts = {}) {
  const full = path.join(DIR, file);
  const html = fs.readFileSync(full, "utf8");
  const routeEls = parseRouteElements(html);
  const byId = new Map();
  const getEl = (id) => { if (!byId.has(id)) byId.set(id, makeEl("DIV")); return byId.get(id); };
  const document = {
    documentElement: makeEl("HTML"), body: makeEl("BODY"),
    getElementById: getEl,
    querySelector: (s) => (s.includes("data-route") ? routeEls[0] || null : makeEl()),
    querySelectorAll: (s) => (s.includes("data-route") ? routeEls : []),
    createElement: (t) => makeEl(String(t).toUpperCase()),
    addEventListener: () => {},
  };
  const errors = [];
  const sandbox = {
    document,
    console: { log() {}, info() {}, warn() {}, error() {} },
    location: { search: opts.search || "", hash: opts.hash || "", href: "file:///" + full },
    history: { pushState() {}, replaceState() {} },
    navigator: { userAgent: "fs-reconciliation" },
    requestAnimationFrame: (fn) => { try { fn(0); } catch (e) { errors.push(e); } return 1; },
    cancelAnimationFrame: () => {},
    setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
    Date, Math, JSON, URLSearchParams, Intl, BigInt,
    getComputedStyle: () => ({ getPropertyValue: () => "" }),
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  sandbox.addEventListener = () => {}; sandbox.window.scrollTo = () => {};
  sandbox.scrollY = 0; sandbox.innerWidth = 390; sandbox.innerHeight = 844;
  vm.createContext(sandbox);
  const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  blocks.forEach((code, i) => {
    try { vm.runInContext(code, sandbox, { filename: `${file}#script${i + 1}` }); }
    catch (e) { errors.push({ block: i + 1, message: e.message }); }
  });
  const ev = (expr) => vm.runInContext(expr, sandbox);
  return { file, html, sandbox, errors, routeEls, getEl, ev };
}

/* Top-level `const` / `let` in a <script> live in the context's global lexical scope and
 * are therefore NOT properties of the sandbox object. Evaluating inside the same context
 * does reach them, so the bindings this suite inspects are hoisted onto `window` once,
 * up front, and read normally thereafter. */
function expose(art, names) {
  art.ev(names.map((n) => `try{window[${JSON.stringify(n)}]=${n}}catch(e){}`).join("\n"));
}

/* ------------------------------------------------------------------- checks */
const results = [];
let currentSection = "";
function section(name) { currentSection = name; }
function check(id, description, fn) {
  let pass = false, detail = "";
  try {
    const r = fn();
    if (r === true || r === undefined) { pass = true; }
    else if (r && typeof r === "object" && "pass" in r) { pass = !!r.pass; detail = r.detail || ""; }
    else { pass = false; detail = String(r); }
  } catch (e) { pass = false; detail = `threw: ${e.message}`; }
  results.push({ id, section: currentSection, description, pass, detail });
}
const eq = (a, b, what) => (a === b ? true : { pass: false, detail: `${what}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}` });

/* ------------------------------------------------------------------ execute */
const action = runArtifact(FILES.action);
const standings = runArtifact(FILES.standings);
const account = runArtifact(FILES.account);

expose(action, ["Resolver", "matchups", "DEMO_FIXTURE", "pills", "noActionModule", "betLabel", "poolReviewData",
  "poolPot", "derivedStakeCents", "fairValueAtLeast", "probabilityFromProjection", "fairMoneyline",
  "qualifies", "counterWasIs", "pendingModule", "actionOwner", "reissueChallenge", "lineup", "bench",
  "metrics", "GE603_BOUNDARY_CASES", "currentUserEntry"]);
expose(standings, ["Resolver"]);
expose(account, ["tx", "ACCTS", "FIXTURE", "ledgerRowsModel", "ledgerChronological", "leagueHtml",
  "balances", "inPlayTotal", "walletMovement", "AUTHORITY"]);

const A = action.sandbox, S = standings.sandbox, C = account.sandbox;
const actionAudit = A.__FS_DETERMINISM_AUDIT__;
const standingsAudit = S.__FS_STANDINGS_WRAP_AUDIT__;
const accountAudit = C.__FS_ACCOUNT_LEDGER_AUDIT__;
const gearAudit = C.__FS_GEAR_AUDIT__;

section("0 · Artifacts execute");
check("R0.1", "Action artifact executes with no runtime error", () => (action.errors.length ? { pass: false, detail: JSON.stringify(action.errors) } : true));
check("R0.2", "Standings + Wrap Up artifact executes with no runtime error", () => (standings.errors.length ? { pass: false, detail: JSON.stringify(standings.errors) } : true));
check("R0.3", "Account + Gear artifact executes with no runtime error", () => (account.errors.length ? { pass: false, detail: JSON.stringify(account.errors) } : true));
check("R0.4", "Action self-audit passes", () => (actionAudit && actionAudit.pass ? true : { pass: false, detail: JSON.stringify(actionAudit && actionAudit.failures) }));
check("R0.5", "Standings + Wrap Up self-audit passes", () => (standingsAudit && standingsAudit.pass ? true : { pass: false, detail: JSON.stringify(standingsAudit && standingsAudit.failures) }));
check("R0.6", "Account ledger self-audit passes", () => (accountAudit && accountAudit.pass ? true : { pass: false, detail: JSON.stringify(accountAudit && accountAudit.failures) }));
check("R0.7", "Gear self-audit passes", () => (gearAudit && gearAudit.pass ? true : { pass: false, detail: JSON.stringify(gearAudit && gearAudit.failures) }));

/* F1 -------------------------------------------------------------------- */
section("F1 · Shared canonical source");
const crypto = require("crypto");
const fixtureText = fs.readFileSync(path.join(DIR, FILES.fixture), "utf8");
const fixtureSha = crypto.createHash("sha256").update(fixtureText).digest("hex");
function inlineFixture(html) {
  const m = /<script data-canonical-fixture="([^"]+)" data-canonical-sha256="([0-9a-f]+)">\n([\s\S]*?)\n<\/script>/.exec(html);
  return m ? { name: m[1], declared: m[2], body: m[3] } : null;
}
check("F1.1", "All three artifacts inline a fixture block", () =>
  [action, standings, account].every((a) => inlineFixture(a.html)) || { pass: false, detail: "missing inline fixture" });
check("F1.2", "Inlined fixture is byte-identical to the standalone v2 file in all three artifacts", () => {
  const bad = [action, standings, account].filter((a) => inlineFixture(a.html).body !== fixtureText).map((a) => a.file);
  return bad.length ? { pass: false, detail: `differs in ${bad.join(", ")}` } : true;
});
check("F1.3", "Declared canonical SHA-256 matches the standalone fixture in all three artifacts", () => {
  const bad = [action, standings, account].filter((a) => inlineFixture(a.html).declared !== fixtureSha).map((a) => a.file);
  return bad.length ? { pass: false, detail: `declared sha mismatch in ${bad.join(", ")}` } : true;
});
check("F1.4", "All three artifacts report the same fixture version", () => {
  const vs = [A.FS_CANON.version, S.FS_CANON.version, C.FS_CANON.version];
  return new Set(vs).size === 1 ? true : { pass: false, detail: JSON.stringify(vs) };
});
check("F1.5", "Fixture version is FS_CANONICAL_CROSS_TAB_FIXTURE_V4", () => eq(A.FS_CANON.version, "FS_CANONICAL_CROSS_TAB_FIXTURE_V4", "version"));

/* F2 -------------------------------------------------------------------- */
section("F2 · Gear Season Allocation");
check("F2.1", "Weekly FantasyStakes Competition is T140.00", () => eq(gearAudit.config.economy.weeklyFantasyStakesCompetition, 14000, "weekly competition cents"));
check("F2.2", "FantasyStakes Championship is T80.00", () => eq(gearAudit.config.economy.fantasyStakesChampionship, 8000, "championship cents"));
check("F2.3", "Season Allocation is T220.00 and equals the two weighting components", () => {
  const e = gearAudit.config.economy;
  if (e.seasonAllocation !== 22000) return { pass: false, detail: `season allocation ${e.seasonAllocation}` };
  return eq(e.weeklyFantasyStakesCompetition + e.fantasyStakesChampionship, e.seasonAllocation, "weighting sum");
});
check("F2.4", "Account Sheet season contribution equals Gear Season Allocation", () => eq(accountAudit.metrics.seasonContribution, gearAudit.config.economy.seasonAllocation, "season contribution"));

/* F3 -------------------------------------------------------------------- */
section("F3 · Standard Prop Pool Entry");
const ledgerTx = C.tx;
const poolEntryTx = ledgerTx.filter((t) => t.type === "POOL_ENTRY");
check("F3.1", "Gear Standard Prop Pool Entry is T1.00", () => eq(gearAudit.config.economy.standardPoolEntry, 100, "gear pool entry"));
check("F3.2", "Action pool entry resolver is T1.00 in integer cents", () => eq(A.Resolver.poolEntryAmount(), 100, "action pool entry"));
check("F3.3", "Ledger posts exactly one Prop Pool entry of T1.00", () =>
  poolEntryTx.length === 1 && poolEntryTx[0].cents === 100 ? true : { pass: false, detail: `${poolEntryTx.length} entries: ${JSON.stringify(poolEntryTx.map((t) => t.cents))}` });
check("F3.4", "Gear, Action and Ledger agree on the entry amount", () => {
  const vs = [gearAudit.config.economy.standardPoolEntry, A.Resolver.poolEntryAmount(), poolEntryTx[0].cents];
  return new Set(vs).size === 1 ? true : { pass: false, detail: JSON.stringify(vs) };
});

/* F4 / F5 / F6 ---------------------------------------------------------- */
section("F4 · Current-week qualifying commitments");
const canon = A.FS_CANON;
const versusEscrowTx = ledgerTx.filter((t) => t.to === C.ACCTS.escrow);
const poolCommitTx = ledgerTx.filter((t) => t.to === C.ACCTS.pool);
const unresolvedVersus = versusEscrowTx.reduce((a, t) => a + t.cents, 0);
const unresolvedPool = poolCommitTx.reduce((a, t) => a + t.cents, 0);
check("F4.1", "Unresolved Versus escrow reconstructed from the Ledger is T80.00", () => eq(unresolvedVersus, 8000, "versus escrow"));
check("F4.2", "Unresolved Prop Pool commitment reconstructed from the Ledger is T1.00", () => eq(unresolvedPool, 100, "pool committed"));
check("F4.3", "Current-week committed capital is T81.00 (Versus + Pool)", () => eq(canon.action.inPlay, unresolvedVersus + unresolvedPool, "committed capital"));
check("F4.4", "The Prop Pool ticket is counted exactly once", () => eq(poolCommitTx.length, 1, "pool commitment postings"));

section("F5 · Weekly Minimum");
check("F5.1", "Weekly Minimum setting is T10.00", () => eq(canon.settings.weeklyMinimum, 1000, "weekly minimum"));
check("F5.2", "Account WEEKLY MIN remaining = max(T10 - qualifying commitments T41, 0) = T0", () => {
  if (canon.action.qualifyingCommitmentsThisWeek !== 4100) return { pass: false, detail: `qualifying ${canon.action.qualifyingCommitmentsThisWeek}` };
  const expected = Math.max(canon.settings.weeklyMinimum - canon.action.qualifyingCommitmentsThisWeek, 0);
  if (expected !== 0) return { pass: false, detail: `expected remaining ${expected}` };
  return eq(accountAudit.metrics.weeklyMinRemaining, expected, "account weekly min");
});
check("F5.3", "Action WEEKLY MIN equals Account WEEKLY MIN", () => eq(actionAudit.summary.weeklyMin, accountAudit.metrics.weeklyMinRemaining, "weekly min cross-tab"));

section("F6 · IN PLAY");
check("F6.1", "Account IN PLAY = unresolved Versus escrow + unresolved Pool capital = T81.00", () => {
  if (accountAudit.metrics.inPlay !== 8100) return { pass: false, detail: `account in play ${accountAudit.metrics.inPlay}` };
  return eq(accountAudit.metrics.inPlayVersusEscrow + accountAudit.metrics.inPlayPoolCommitted, accountAudit.metrics.inPlay, "in play components");
});
check("F6.2", "Action IN PLAY equals Account IN PLAY", () => eq(actionAudit.summary.inPlay, accountAudit.metrics.inPlay, "in play cross-tab"));
check("F6.3", "Canonical fixture IN PLAY equals both", () => {
  const vs = [canon.action.inPlay, actionAudit.summary.inPlay, accountAudit.metrics.inPlay];
  return new Set(vs).size === 1 ? true : { pass: false, detail: JSON.stringify(vs) };
});
check("F6.4", "Skunk Pot is NOT counted as IN PLAY", () =>
  !canon.inPlayAccounts.includes(C.ACCTS.skunkPot) ? true : { pass: false, detail: "Skunk Pot listed in inPlayAccounts" });
check("F6.5", "Wallet is NOT counted as IN PLAY", () =>
  !canon.inPlayAccounts.includes(C.ACCTS.wallet) ? true : { pass: false, detail: "Wallet listed in inPlayAccounts" });

/* F7 -------------------------------------------------------------------- */
section("F7 · Wallet");
const walletFromLedger = ledgerTx.reduce((b, t) => b + (t.to === C.ACCTS.wallet ? t.cents : 0) - (t.from === C.ACCTS.wallet ? t.cents : 0), 0);
check("F7.1", "Wallet reconstructed independently from the Ledger is T94.00", () => eq(walletFromLedger, 9400, "reconstructed wallet"));
check("F7.2", "Account Wallet equals the Ledger reconstruction", () => eq(accountAudit.metrics.wallet, walletFromLedger, "account wallet"));
check("F7.3", "Action Wallet equals the Ledger reconstruction", () => eq(actionAudit.summary.wallet, walletFromLedger, "action wallet"));
check("F7.4", "Wallet arithmetic still reconciles after the Prop Pool ticket is committed", () => {
  const opening = ledgerTx.filter((t) => t.type === "WEEKLY_RELEASE").reduce((a, t) => a + t.cents, 0);
  const settled = ledgerTx.filter((t) => ["MATCHUP_NET", "POOL_NET"].includes(t.type))
    .reduce((a, t) => a + (t.to === C.ACCTS.wallet ? t.cents : -t.cents), 0);
  const skunk = -ledgerTx.filter((t) => t.type === "SKUNK").reduce((a, t) => a + t.cents, 0);
  const committed = -(unresolvedVersus + unresolvedPool);
  const expected = opening + settled + skunk + committed;
  return eq(expected, walletFromLedger, "wallet build-up");
});

/* F8 -------------------------------------------------------------------- */
section("F8 · Skunk routing");
const skunkTx = ledgerTx.filter((t) => t.type === "SKUNK");
check("F8.1", "At least one Skunk Fee is posted", () => (skunkTx.length > 0 ? true : { pass: false, detail: "no skunk transactions" }));
check("F8.2", "Every Skunk Fee credits the governed Skunk Pot", () => {
  const bad = skunkTx.filter((t) => t.to !== C.ACCTS.skunkPot);
  return bad.length ? { pass: false, detail: `${bad.length} routed to ${JSON.stringify([...new Set(bad.map((t) => t.to))])}` } : true;
});
check("F8.3", "No Skunk Fee touches Settled Counterparties", () => {
  const bad = skunkTx.filter((t) => t.to === C.ACCTS.settled || t.from === C.ACCTS.settled);
  return bad.length ? { pass: false, detail: `${bad.length} touched Settled Counterparties` } : true;
});
check("F8.4", "Every Skunk Fee debits the assessed GM's Wallet", () => {
  const bad = skunkTx.filter((t) => t.from !== C.ACCTS.wallet);
  return bad.length ? { pass: false, detail: `${bad.length} not debited from Wallet` } : true;
});
check("F8.5", "Skunk Pot balance equals the posted Skunk contributions (T10.00)", () => {
  const potBal = ledgerTx.reduce((b, t) => b + (t.to === C.ACCTS.skunkPot ? t.cents : 0) - (t.from === C.ACCTS.skunkPot ? t.cents : 0), 0);
  if (potBal !== 1000) return { pass: false, detail: `skunk pot ${potBal}` };
  return eq(potBal, skunkTx.reduce((a, t) => a + t.cents, 0), "skunk pot vs postings");
});
check("F8.6", "Skunk impacts the FantasyStakes Score exactly once", () => {
  const skunkCents = -skunkTx.reduce((a, t) => a + t.cents, 0);
  const canonicalSkunk = canon.seasonThroughWeek10[canon.league.currentUserId].skunk * 100;
  return eq(skunkCents, canonicalSkunk, "skunk score contribution");
});
check("F8.7", "Skunk Pot is a distinct account from Wallet, escrow and pools", () => {
  const names = [C.ACCTS.wallet, C.ACCTS.escrow, C.ACCTS.pool, C.ACCTS.champ, C.ACCTS.weekly];
  return !names.includes(C.ACCTS.skunkPot) ? true : { pass: false, detail: "Skunk Pot collides with another account" };
});
check("F8.8", "Final Reconciliation does not double-count the Skunk", () => {
  const m = accountAudit.metrics;
  const expected = m.seasonContribution + m.fsScore;
  return eq(m.finalReconciliation, expected, "final reconciliation");
});

/* F9 -------------------------------------------------------------------- */
section("F9 · Score chain");
const ledgerMatch = ledgerTx.filter((t) => t.type === "MATCHUP_NET").reduce((a, t) => a + (t.to === C.ACCTS.wallet ? t.cents : -t.cents), 0);
const ledgerPool = ledgerTx.filter((t) => t.type === "POOL_NET").reduce((a, t) => a + (t.to === C.ACCTS.wallet ? t.cents : -t.cents), 0);
const ledgerSkunk = -skunkTx.reduce((a, t) => a + t.cents, 0);
check("F9.1", "Ledger score-bearing Matchups net is +T45.00", () => eq(ledgerMatch, 4500, "ledger matchups"));
check("F9.2", "Ledger score-bearing Prop Pools net is +T30.00", () => eq(ledgerPool, 3000, "ledger pools"));
check("F9.3", "Ledger score-bearing Skunk net is -T10.00", () => eq(ledgerSkunk, -1000, "ledger skunk"));
check("F9.4", "Ledger components sum to the Account FantasyStakes Score", () => eq(ledgerMatch + ledgerPool + ledgerSkunk, accountAudit.metrics.fsScore, "ledger -> account"));
check("F9.5", "Account FantasyStakes Score equals Standings FantasyStakes Score", () => eq(accountAudit.metrics.fsScore, standingsAudit.currentUser.scoreCents, "account -> standings"));
check("F9.6", "Standings score equals the sum of published Wrap Ups (checked in-artifact for all 12 teams)", () =>
  standingsAudit.pass ? true : { pass: false, detail: JSON.stringify(standingsAudit.failures) });
check("F9.7", "Non-score-bearing postings do not enter the score", () => {
  const nonScoring = ledgerTx.filter((t) => ["POOL_ENTRY", "VERSUS_ESCROW", "WEEKLY_RELEASE", "OPEN_WEEKLY", "OPEN_CHAMP"].includes(t.type));
  const leaked = nonScoring.filter((t) => t.to === C.ACCTS.settled || t.from === C.ACCTS.settled || t.to === C.ACCTS.skunkPot);
  return leaked.length ? { pass: false, detail: `${leaked.length} non-score-bearing postings reached a score-bearing account` } : true;
});

/* F10 ------------------------------------------------------------------- */
section("F10 · FSR-001 probability model preserved");
const matchupsA = A.Resolver.versusMatchups();
check("F10.1", "Exactly one simulation model is declared", () => eq(A.DEMO_FIXTURE.simulationModel.version, "FS_DEMO_MARGIN_NORMAL_V1", "model version"));
check("F10.2", "Shared sigma is 20.0 fantasy points", () => eq(A.DEMO_FIXTURE.simulationModel.sigmaFantasyPoints, 20.0, "sigma"));
check("F10.3", "Every matchup stamps the same model provenance", () => {
  const vs = new Set(matchupsA.map((m) => m.source.simulationModel));
  return vs.size === 1 && vs.has("FS_DEMO_MARGIN_NORMAL_V1") ? true : { pass: false, detail: JSON.stringify([...vs]) };
});
check("F10.4", "p is derived from the projected margin on every matchup", () => {
  const bad = matchupsA.filter((m) => Math.abs(m.p - A.probabilityFromProjection(Number(m.painProj), Number(m.oppProj))) > 1e-12);
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F10.5", "p is monotonic in projected margin across all 11 matchups", () => {
  const byMargin = [...matchupsA].sort((a, b) => a.margin - b.margin);
  for (let i = 1; i < byMargin.length; i++) if (byMargin[i].p + 1e-12 < byMargin[i - 1].p) return { pass: false, detail: `${byMargin[i - 1].opponent} -> ${byMargin[i].opponent}` };
  return true;
});
check("F10.6", "Moneyline is derived from p on every matchup", () => {
  const bad = matchupsA.filter((m) => m.ml !== A.fairMoneyline(m.p));
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F10.7", "Counter-board p is derived from the counter-board projections", () => {
  const bad = matchupsA.filter((m, i) => {
    const cPain = Number(m.painProj) + (i % 2 ? -0.9 : 1.1), cOpp = Number(m.oppProj) + ((i % 3) - 1) * 0.75;
    return Math.abs(m.counter.p - A.probabilityFromProjection(cPain, cOpp)) > 1e-12;
  });
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F10.8", "GE-603 holds on every matchup: Derived is the strict floor of Anchor x (1-p)/p", () => {
  const bad = matchupsA.filter((m) => m.derived !== A.derivedStakeCents(m.anchor, m.p) || A.fairValueAtLeast(m.anchor, m.p, m.derived + 1));
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});

/* F11 ------------------------------------------------------------------- */
section("F11 · Action integer-cent economics");
check("F11.1", "Anchor, Derived and Pot are integer cents on every matchup", () => {
  const bad = matchupsA.filter((m) => ![m.anchor, m.derived, m.pot, m.counter.anchor, m.counter.derived, m.counter.pot, m.wager.stake, m.wager.them, m.wager.pot].every(Number.isInteger));
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F11.2", "Pot is exactly Anchor + Derived with no residue", () => {
  const bad = matchupsA.filter((m) => m.pot !== m.anchor + m.derived);
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F11.3", "Epsilon flooring is gone from executable Action code", () => {
  // Comments are stripped first: the FSR-015 header documents the defect it replaced and
  // legitimately quotes the old epsilon formula.
  const code = [...action.html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
    .map((m) => m[1])
    .join("\n")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  const hits = [];
  if (/floorToCent/.test(code)) hits.push("floorToCent");
  if (/1e-9/.test(code)) hits.push("1e-9 epsilon");
  return hits.length ? { pass: false, detail: hits.join(", ") } : true;
});
check("F11.4", "Canonical case: Anchor T20.00 derives the expected cents for all 11 matchups", () => {
  const expected = { "Hank Williams": 740, "Dolly Parton": 1494, "Reba McEntire": 2192, "Willie Nelson": 715, "Johnny Cash": 3093, "Patsy Cline": 1292, "Waylon Jennings": 1914, "Loretta Lynn": 874, "George Strait": 3436, "Tammy Wynette": 1458, "Merle Haggard": 1378 };
  const bad = matchupsA.filter((m) => m.derived !== expected[m.opponent]);
  return bad.length ? { pass: false, detail: bad.map((m) => `${m.opponent} ${m.derived} != ${expected[m.opponent]}`).join("; ") } : true;
});
check("F11.5", "Underdog case: opponent Derived exceeds Anchor when p < 0.5", () => {
  const dogs = matchupsA.filter((m) => m.p < 0.5);
  if (!dogs.length) return { pass: false, detail: "no underdog matchup in the fixture" };
  const bad = dogs.filter((m) => !(m.derived > m.anchor));
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F11.6", "Cent-boundary battery: exact division floors exactly", () => {
  const cases = [[2000, 0.5, 2000], [2000, 0.25, 6000]];
  const bad = cases.filter(([a, p, x]) => A.derivedStakeCents(a, p) !== x);
  return bad.length ? { pass: false, detail: JSON.stringify(bad) } : true;
});
check("F11.7", "Cent-boundary battery: inexact division floors DOWN and never rounds up", () => {
  const cases = [[2000, 0.2, 7999], [2000, 0.4, 2999], [1000, 0.1, 8999], [2000, 0.8, 499], [2000, 0.6, 1333], [2500, 0.9, 277], [100, 0.3, 233], [1, 0.75, 0]];
  const bad = cases.filter(([a, p, x]) => A.derivedStakeCents(a, p) !== x);
  return bad.length ? { pass: false, detail: JSON.stringify(bad.map(([a, p, x]) => `anchor ${a} p ${p}: got ${A.derivedStakeCents(a, p)} want ${x}`)) } : true;
});
check("F11.8", "No off-by-one-cent regression against the previous release on canonical data", () => {
  // Previous release path: token units with epsilon flooring.
  const legacy = (anchorTokens, p) => Math.floor(((anchorTokens / p) * (1 - p) + 1e-9) * 100) / 100;
  const bad = matchupsA.filter((m) => Math.round(legacy(m.anchor / 100, m.p) * 100) !== m.derived);
  return bad.length ? { pass: false, detail: bad.map((m) => `${m.opponent}: legacy ${Math.round(legacy(m.anchor / 100, m.p) * 100)} vs ${m.derived}`).join("; ") } : true;
});
check("F11.9", "Pool pot is integer cents and equals entrants x entry", () => {
  const bad = A.poolReviewData.filter((raw) => {
    const pot = A.poolPot(raw);
    return !Number.isInteger(pot) || pot !== raw.entryRecords.length * A.Resolver.poolEntryAmount();
  });
  return bad.length ? { pass: false, detail: bad.map((r) => r.definitionKey).join(", ") } : true;
});

/* F12 ------------------------------------------------------------------- */
section("F12 · Ledger chronology and presentation");
const ledgerRows = C.ledgerRowsModel();
check("F12.1", "Rendered rows descend by real transaction date", () => {
  for (let i = 1; i < ledgerRows.length; i++) if (ledgerRows[i].t.iso > ledgerRows[i - 1].t.iso) return { pass: false, detail: `row ${i}: ${ledgerRows[i - 1].t.iso} then ${ledgerRows[i].t.iso}` };
  return true;
});
check("F12.2", "Same-date ordering is deterministic on posting sequence", () => {
  for (let i = 1; i < ledgerRows.length; i++) {
    const a = ledgerRows[i - 1].t, b = ledgerRows[i].t;
    if (a.iso === b.iso && b.seq >= a.seq) return { pass: false, detail: `${a.id} then ${b.id} on ${a.iso}` };
  }
  return true;
});
check("F12.3", "Transaction identity and immutability are preserved", () => {
  if (new Set(ledgerTx.map((t) => t.id)).size !== ledgerTx.length) return { pass: false, detail: "duplicate transaction id" };
  const frozen = ledgerTx.every((t) => Object.isFrozen(t));
  return frozen ? true : { pass: false, detail: "a transaction is not frozen" };
});
check("F12.4", "Every row keeps its description, date and double-entry route", () => {
  const bad = ledgerRows.filter((r) => !r.t.desc || !r.t.date || !r.t.from || !r.t.to);
  return bad.length ? { pass: false, detail: `${bad.length} rows incomplete` } : true;
});
check("F12.5", "One signed movement column, never the same amount on both sides", () =>
  !/>DEBIT</.test(account.html) && !/>CREDIT</.test(account.html) && /<span class="right">MOVEMENT<\/span>/.test(account.html.replace(/<span class="right">/g, '<span class="right">'))
    ? true
    : (/DEBIT/.test(account.html) ? { pass: false, detail: "DEBIT/CREDIT columns still rendered" } : true));
check("F12.6", "Movement column foots exactly to the Wallet balance", () => eq(ledgerRows.reduce((a, r) => a + r.movement, 0), walletFromLedger, "movement foot"));
check("F12.7", "Running Wallet balance ends at the Wallet balance", () => eq(ledgerRows[0].walletAfter, walletFromLedger, "running balance"));
check("F12.8", "Movement is reported only for transactions that touch the Wallet", () => {
  const bad = ledgerRows.filter((r) => r.movement !== 0 && r.t.from !== C.ACCTS.wallet && r.t.to !== C.ACCTS.wallet);
  return bad.length ? { pass: false, detail: `${bad.length} rows` } : true;
});
check("F12.9", "Underlying double-entry data is intact (every posting has both sides)", () => {
  const bad = ledgerTx.filter((t) => !t.from || !t.to || t.from === t.to);
  return bad.length ? { pass: false, detail: `${bad.length} malformed postings` } : true;
});

/* F13 ------------------------------------------------------------------- */
section("F13 · AVAILABLE gating");
check("F13.1", "AVAILABLE appears only where a wager can still be initiated", () => {
  const bad = A.matchups.filter((m) => A.pills(m).includes("AVAILABLE") && !(m.bet === "no" && m.game === "pregame"));
  return bad.length ? { pass: false, detail: bad.map((m) => `${m.opponent} (${m.bet}/${m.game})`).join(", ") } : true;
});
check("F13.2", "LIVE / OVER no-wager cards use a neutral closed treatment", () => {
  const targets = A.matchups.filter((m) => m.bet === "no" && m.game !== "pregame");
  if (!targets.length) return { pass: false, detail: "fixture has no LIVE/OVER no-wager card to test" };
  const bad = targets.filter((m) => !A.pills(m).includes("CLOSED"));
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F13.3", "LIVE / OVER no-wager cards expose no action controls", () => {
  const targets = A.matchups.filter((m) => m.bet === "no" && m.game !== "pregame");
  const bad = targets.filter((m) => /BUILD YOUR CHALLENGE|SEND CHALLENGE|data-life=/.test(A.noActionModule(m)));
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F13.4", "Terminal DECLINED / EXPIRED treatment is unchanged (O-3 untouched)", () =>
  A.betLabel.declined === "DECLINED" && A.betLabel.expired === "EXPIRED" ? true : { pass: false, detail: JSON.stringify(A.betLabel) });

/* F14 ------------------------------------------------------------------- */
section("F14 · Gear authority and season lock");
const AUTH = C.FS_CANON.settingsAuthority;
check("F14.1", "Every governed setting carries an authority classification", () => {
  const governed = ["weeklyFantasyStakesCompetition", "fantasyStakesChampionship", "seasonAllocation", "weeklyMinimum", "standardPropPoolEntry", "skunkFee", "unspentMinimumDestination", "matchupMarkets", "termsModes", "propPools"];
  const missing = governed.filter((k) => !AUTH.classification[k]);
  return missing.length ? { pass: false, detail: missing.join(", ") } : true;
});
check("F14.2", "Season Allocation is declared DERIVED", () => eq(AUTH.classification.seasonAllocation, "DERIVED", "season allocation authority"));
check("F14.3", "Season configuration is frozen at the first accepted wager (CFG-107)", () =>
  AUTH.seasonConfigurationFrozen && AUTH.frozenAt === "FIRST_ACCEPTED_WAGER" ? true : { pass: false, detail: JSON.stringify(AUTH) });
check("F14.4", "Season-fixed settings render a season-lock chip", () => {
  const html = C.leagueHtml();
  const n = (html.match(/LOCKED FOR 2026/g) || []).length;
  return n >= 9 ? true : { pass: false, detail: `${n} lock chips rendered` };
});
check("F14.5", "The DERIVED chip is rendered for Season Allocation", () =>
  /authChip derived">DERIVED</.test(C.leagueHtml()) ? true : { pass: false, detail: "no DERIVED chip" });
check("F14.6", "GM Gear view is read only and exposes no edit control", () => {
  if (AUTH.gmView !== "READ ONLY") return { pass: false, detail: `gmView ${AUTH.gmView}` };
  const html = C.leagueHtml();
  return !/<input|<select|contenteditable/.test(html) ? true : { pass: false, detail: "an edit control is rendered in League Settings" };
});
check("F14.7", "The authority basis cites CFG-107 and CFG-1003", () =>
  /CFG-107/.test(AUTH.basis) && /CFG-1003/.test(AUTH.basis) ? true : { pass: false, detail: AUTH.basis });

/* F15 ------------------------------------------------------------------- */
section("F15 · Locked lifecycle regression battery");
check("F15.1", "Filters partition the board as locked (opponents / challengers / pending / accepted)", () => {
  const counts = {};
  for (const f of ["opponents", "challengers", "pending", "accepted"]) {
    // `filter` is a lexical `let`, so it has to be assigned inside the artifact's context.
    counts[f] = action.ev(`filter=${JSON.stringify(f)}; matchups.filter(m=>qualifies(m)).length`);
  }
  action.ev('filter="opponents"');
  if (counts.opponents !== A.matchups.length) return { pass: false, detail: `opponents ${counts.opponents} of ${A.matchups.length}` };
  if (counts.challengers < 1) return { pass: false, detail: "no incoming challenge in the fixture" };
  if (counts.accepted < 1) return { pass: false, detail: "no accepted wager in the fixture" };
  return true;
});
check("F15.2", "Counter produces a Was -> Is comparison on the countered matchup", () => {
  const m = A.matchups.find((x) => x.bet === "countered");
  if (!m) return { pass: false, detail: "no countered matchup in the fixture" };
  const wasis = A.counterWasIs(m);
  return /WAS → IS/.test(wasis) && /ANCHOR/.test(wasis) && /DERIVED/.test(wasis) ? true : { pass: false, detail: "Was -> Is block incomplete" };
});
check("F15.3", "Accept / decline are offered only on a proposal awaiting this GM", () => {
  const bad = A.matchups.filter((m) => {
    if (!(m.bet === "pending" || m.bet === "countered")) return false;
    const html = A.pendingModule(m, m.bet === "countered");
    const offersRespond = /data-life="accept"/.test(html);
    return offersRespond !== (A.actionOwner(m) === A.DEMO_FIXTURE.league.currentUser);
  });
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F15.4", "No re-counter: a matchup whose counter is used offers no COUNTER control", () => {
  const bad = A.matchups.filter((m) => m.bet === "countered" && A.actionOwner(m) === A.DEMO_FIXTURE.league.currentUser && /data-life="counter"/.test(A.pendingModule(m, true)));
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F15.5", "Cancel is offered on this GM's own outgoing initial proposal only", () => {
  const outgoing = A.matchups.filter((m) => m.bet === "pending" && A.actionOwner(m) === m.opponent);
  if (!outgoing.length) return { pass: false, detail: "no outgoing pending proposal in the fixture" };
  const bad = outgoing.filter((m) => !/data-life="cancel"/.test(A.pendingModule(m)));
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F15.6", "Reissue is gated to this GM's own challenge in a pre-game matchup", () => {
  const m = A.matchups.find((x) => x.game !== "pregame" && x.challenge);
  if (!m) return true;
  const before = JSON.stringify(m.challenge && m.challenge.id);
  A.reissueChallenge(m);
  return eq(JSON.stringify(m.challenge && m.challenge.id), before, "reissue gate on non-pregame");
});
check("F15.7", "Prop Pools have zero preselection", () => {
  const bad = A.poolReviewData.filter((raw) => raw.userPick !== null || raw.entryRecords.some((e) => e.team === A.DEMO_FIXTURE.league.currentUser && e.pick !== null));
  return bad.length ? { pass: false, detail: bad.map((r) => r.definitionKey).join(", ") } : true;
});
check("F15.8", "Reset Pick control is present on an open pool", () =>
  /id="resetPoolBtn"/.test(action.html) ? true : { pass: false, detail: "no Reset Pick control" });
check("F15.9", "Lineup renders the full seven starter slots", () => {
  const m = A.matchups[0];
  const html = A.lineup(m);
  const missing = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"].filter((s) => !new RegExp(`>${s}<`).test(html));
  return missing.length ? { pass: false, detail: `missing ${missing.join(", ")}` } : true;
});
check("F15.10", "Bench rows are labelled BN", () => {
  const html = A.bench(A.matchups[0]);
  return /<div class="vspos">BN<\/div>/.test(html) ? true : { pass: false, detail: "no BN bench label" };
});
check("F15.11", "LIVE / OVER matchups expose no impossible action", () => {
  const bad = A.matchups.filter((m) => m.game !== "pregame" && (m.bet === "pending" || m.bet === "countered") && /data-life="accept"|data-life="counter"/.test(A.pendingModule(m, m.bet === "countered")));
  return bad.length ? { pass: false, detail: bad.map((m) => m.opponent).join(", ") } : true;
});
check("F15.12", "Proposal freeze: an accepted proposal keeps its own frozen economics", () => {
  const m = A.matchups.find((x) => x.bet === "wagered" && x.challenge && x.challenge.acceptedProposal);
  if (!m) return { pass: false, detail: "no accepted proposal in the fixture" };
  const ap = m.challenge.acceptedProposal;
  return ap.pot === ap.anchor + ap.derived ? true : { pass: false, detail: "accepted proposal economics inconsistent" };
});
check("F15.13", "Fixed and Dynamic terms modes are both represented", () => {
  const modes = new Set(A.matchups.map((m) => m.termsMode));
  return modes.has("FIXED") && modes.has("DYNAMIC") ? true : { pass: false, detail: JSON.stringify([...modes]) };
});
check("F15.14", "Combined Teams pool field uses the official Yahoo fantasy matchups", () => {
  const combined = A.Resolver.poolField("combined");
  return eq(combined.length, A.Resolver.officialYahooMatchups().length, "combined field size");
});

/* F16 ------------------------------------------------------------------- */
section("F16 \u00b7 FSR-023 cross-surface committed capital");

// The point of this section: expected escrow is DERIVED from Action lifecycle state,
// never read back from a stored total, and is then driven through the Ledger to both
// rendered strips. IN PLAY and Weekly Minimum qualification stay separate throughout.
const derived = action.ev("Resolver.commitmentTotals()");
const records = action.ev("Resolver.commitments()");
const heldVersus = records.filter((c) => c.kind === "VERSUS" && c.held);
const byOpp = Object.fromEntries(heldVersus.map((c) => [c.opponent, c]));
const EXPECT = {
  "Hank Williams": { cents: 2000, lifecycle: "ACCEPTED", qualifying: true },
  "Dolly Parton": { cents: 2000, lifecycle: "PENDING_OUTGOING", qualifying: false },
  "Reba McEntire": { cents: 2000, lifecycle: "COUNTER_PENDING", qualifying: false },
  "Loretta Lynn": { cents: 2000, lifecycle: "ACCEPTED", qualifying: true },
};
for (const [opp, exp] of Object.entries(EXPECT)) {
  check("F16." + opp.split(" ")[0], opp + ": escrow derived from lifecycle is T20.00 (" + exp.lifecycle + ")", () => {
    const c = byOpp[opp];
    if (!c) return { pass: false, detail: "no held commitment derived from Action lifecycle" };
    if (c.cents !== exp.cents) return { pass: false, detail: "derived " + c.cents + " != " + exp.cents };
    if (c.lifecycle !== exp.lifecycle) return { pass: false, detail: "lifecycle " + c.lifecycle + " != " + exp.lifecycle };
    if (c.role !== "ISSUER") return { pass: false, detail: "role " + c.role + " != ISSUER" };
    return true;
  });
}
check("F16.5", "Total Versus escrow derived from Action lifecycle is T80.00", () => eq(derived.versusEscrow, 8000, "derived versus escrow"));
check("F16.6", "Pool committed capital derived from Action pool state is T1.00", () => eq(derived.poolCommitted, 100, "derived pool committed"));
check("F16.7", "Derived IN PLAY is T81.00", () => eq(derived.inPlay, 8100, "derived in play"));
check("F16.8", "Account / Ledger escrow balances equal the derived IN PLAY", () => {
  const ledgerInPlay = accountAudit.metrics.inPlayVersusEscrow + accountAudit.metrics.inPlayPoolCommitted;
  if (ledgerInPlay !== derived.inPlay) return { pass: false, detail: "ledger " + ledgerInPlay + " != derived " + derived.inPlay };
  return eq(accountAudit.metrics.inPlay, derived.inPlay, "account in play");
});
check("F16.9", "Rendered Action IN PLAY strip reads T81", () => {
  const r = action.getEl("summaryInPlay").textContent;
  return r === "\u016681" ? true : { pass: false, detail: "rendered " + JSON.stringify(r) };
});
check("F16.10", "Rendered Account IN PLAY strip reads T81", () => {
  const r = account.getEl("escrowStrip").textContent;
  return r === "\u016681" ? true : { pass: false, detail: "rendered " + JSON.stringify(r) };
});
check("F16.11", "Qualifying weekly commitments derived from lifecycle are T41.00", () => eq(derived.qualifying, 4100, "derived qualifying"));
check("F16.12", "Weekly Min Remaining derived from qualifying commitments is T0, on both strips", () => {
  if (derived.weeklyMinRemaining !== 0) return { pass: false, detail: "derived " + derived.weeklyMinRemaining };
  const a = action.getEl("summaryWeeklyMin").textContent, c = account.getEl("weeklyStrip").textContent;
  return a === "\u01660" && c === "\u01660" ? true : { pass: false, detail: "action " + JSON.stringify(a) + " account " + JSON.stringify(c) };
});
check("F16.13", "Pending outgoing Dolly is committed but NOT qualifying", () => {
  const c = byOpp["Dolly Parton"];
  if (!c.held || c.cents !== 2000) return { pass: false, detail: "Dolly escrow not held" };
  return c.qualifying === false ? true : { pass: false, detail: "pending offer counted toward Weekly Minimum" };
});
check("F16.14", "Counter-pending Reba is committed but NOT qualifying, at the ORIGINAL Anchor", () => {
  const c = byOpp["Reba McEntire"];
  if (c.qualifying !== false) return { pass: false, detail: "counter-pending offer counted toward Weekly Minimum" };
  const m = action.ev("matchups.find(m=>m.opponent===\"Reba McEntire\")");
  const original = m.challenge.proposalHistory[0].anchor, active = m.challenge.activeProposal.anchor;
  if (original === active) return { pass: false, detail: "fixture no longer exercises a differing counter Anchor" };
  if (c.cents !== original) return { pass: false, detail: "escrow " + c.cents + " is not the original Anchor " + original };
  if (c.cents === active) return { pass: false, detail: "escrow wrongly follows the counter Anchor " + active };
  return true;
});
check("F16.15", "Accepted Hank IS qualifying", () => (byOpp["Hank Williams"].qualifying === true ? true : { pass: false, detail: "accepted wager excluded from qualification" }));
check("F16.16", "Accepted Loretta IS qualifying", () => (byOpp["Loretta Lynn"].qualifying === true ? true : { pass: false, detail: "accepted wager excluded from qualification" }));
check("F16.17", "Funded Pool ticket counted exactly once and IS qualifying", () => {
  const held = records.filter((c) => c.kind === "POOL" && c.held);
  if (held.length !== 1) return { pass: false, detail: held.length + " held pool tickets" };
  if (!held[0].qualifying) return { pass: false, detail: "funded pool ticket excluded from qualification" };
  return eq(poolEntryTx.length, 1, "ledger pool postings");
});
check("F16.18", "Wallet reconstructs from the Ledger to T94.00", () => eq(walletFromLedger, 9400, "wallet"));
check("F16.19", "Final Reconciliation remains T285.00", () => eq(accountAudit.metrics.finalReconciliation, 28500, "final reconciliation"));
check("F16.20", "FantasyStakes Score remains +T65.00", () => eq(accountAudit.metrics.fsScore, 6500, "score"));
check("F16.21", "Escrow transfers have no score impact", () => {
  const weekTx = ledgerTx.filter((t) => t.type === "VERSUS_ESCROW" || t.type === "POOL_ENTRY");
  const leaked = weekTx.filter((t) => t.to === C.ACCTS.settled || t.from === C.ACCTS.settled || t.to === C.ACCTS.skunkPot);
  if (leaked.length) return { pass: false, detail: leaked.length + " commitment postings reached a score-bearing account" };
  return eq(ledgerMatch + ledgerPool + ledgerSkunk, 6500, "score unchanged by commitments");
});
check("F16.22", "No Ledger posting describes a pending commitment as accepted", () => {
  const schedule = canon.currentWeekCommitments;
  const bad = ledgerTx.filter((t) => {
    const c = schedule.find((x) => x.desc === t.desc);
    return c && c.lifecycle !== "ACCEPTED" && /accepted/i.test(t.desc);
  });
  const dolly = ledgerTx.find((t) => t.type === "VERSUS_ESCROW" && /Dolly/.test(t.desc));
  if (!dolly) return { pass: false, detail: "no Dolly commitment posting found" };
  if (/accepted/i.test(dolly.desc)) return { pass: false, detail: "Dolly still reads: " + dolly.desc };
  return bad.length ? { pass: false, detail: bad.map((t) => t.desc).join("; ") } : true;
});
check("F16.23", "Every held Action commitment has exactly one matching Ledger posting", () => {
  const weekTx = ledgerTx.filter((t) => t.week === canon.league.currentWeek && (t.type === "VERSUS_ESCROW" || t.type === "POOL_ENTRY"));
  const held = records.filter((c) => c.held);
  if (weekTx.length !== held.length) return { pass: false, detail: weekTx.length + " postings for " + held.length + " held commitments" };
  const missing = [];
  for (const c of held) {
    const hits = c.kind === "POOL"
      ? weekTx.filter((t) => t.type === "POOL_ENTRY" && t.cents === c.cents)
      : weekTx.filter((t) => t.type === "VERSUS_ESCROW" && t.cents === c.cents && new RegExp(c.opponent.split(" ")[0], "i").test(t.desc));
    if (hits.length !== 1) missing.push((c.opponent || c.definitionKey) + ": " + hits.length + " postings");
  }
  return missing.length ? { pass: false, detail: missing.join("; ") } : true;
});
check("F16.24", "No Ledger escrow exists for a released or terminal Action state", () => {
  const terminal = records.filter((c) => ["DECLINED", "EXPIRED", "NONE", "PENDING_INCOMING", "NOT_ENTERED", "RESOLVED"].includes(c.lifecycle));
  const weekTx = ledgerTx.filter((t) => t.week === canon.league.currentWeek && t.type === "VERSUS_ESCROW");
  const bad = [];
  for (const c of terminal) {
    if (c.cents || c.held) { bad.push((c.opponent || c.definitionKey) + " holds " + c.cents); continue; }
    if (c.opponent && weekTx.some((t) => new RegExp(c.opponent.split(" ")[0], "i").test(t.desc))) {
      bad.push(c.opponent + " (" + c.lifecycle + ") still has a Ledger escrow posting");
    }
  }
  return bad.length ? { pass: false, detail: bad.join("; ") } : true;
});
check("F16.25", "Canonical schedule is a materialisation of the derived state, not an independent source", () => {
  const s = canon.currentWeekCommitments;
  const sv = s.filter((c) => c.kind === "VERSUS").reduce((a, c) => a + c.cents, 0);
  const sp = s.filter((c) => c.kind === "POOL").reduce((a, c) => a + c.cents, 0);
  const sq = s.filter((c) => c.qualifying).reduce((a, c) => a + c.cents, 0);
  if (sv !== derived.versusEscrow) return { pass: false, detail: "schedule versus " + sv + " != derived " + derived.versusEscrow };
  if (sp !== derived.poolCommitted) return { pass: false, detail: "schedule pool " + sp + " != derived " + derived.poolCommitted };
  if (sq !== derived.qualifying) return { pass: false, detail: "schedule qualifying " + sq + " != derived " + derived.qualifying };
  return true;
});
check("F16.26", "IN PLAY and Weekly Minimum qualification are genuinely different quantities here", () => {
  if (derived.qualifying >= derived.inPlay) return { pass: false, detail: "qualifying " + derived.qualifying + " not narrower than in play " + derived.inPlay };
  return eq(derived.inPlay - derived.qualifying, 4000, "value of the two excluded pending offers");
});
check("F16.27", "Total GM holdings conserve to T285.00 after the escrow restatement", () => {
  const b = account.ev("balances()");
  const holdings = b.wallet + b.weekly + b.escrow + b.champ + b.pool;
  if (holdings !== 28500) return { pass: false, detail: "holdings " + holdings };
  return eq(b.skunkPot, 1000, "Skunk Pot sits outside GM holdings");
});
check("F16.28", "Rendered Account WALLET strip reads T94", () => {
  const r = account.getEl("walletStrip").textContent;
  return r === "\u016694" ? true : { pass: false, detail: "rendered " + JSON.stringify(r) };
});
check("F16.29", "Rendered Action WALLET strip reads T94", () => {
  const r = action.getEl("summaryWallet").textContent;
  return r === "\u016694" ? true : { pass: false, detail: "rendered " + JSON.stringify(r) };
});
check("F16.30", "Action publishes its commitment detail for cross-surface inspection", () => {
  const pub = A.__FS_COMMITMENTS__;
  if (!pub) return { pass: false, detail: "no __FS_COMMITMENTS__" };
  if (pub.renderedInPlay !== 8100 || pub.renderedWeeklyMin !== 0) return { pass: false, detail: JSON.stringify(pub.totals) };
  return eq(pub.records.filter((c) => c.held).length, 5, "held commitment count");
});

/* F17 ------------------------------------------------------------------- */
section("F17 \u00b7 FSR-024 UPSIDE LEFT derived from accepted wagers");

const upside = action.ev("Resolver.upsideCommitments()");
const upBy = Object.fromEntries(upside.map((c) => [c.opponent, c]));
const accepted = action.ev("matchups.filter(m=>m.bet===\"wagered\").map(m=>({opponent:m.opponent,game:m.game,issuer:m.challenge.issuer,anchor:m.challenge.acceptedProposal.anchor,derived:m.challenge.acceptedProposal.derived}))");

check("F17.1", "Hank Williams upside = 740 cents (opponent Derived stake on an accepted wager)", () => {
  const c = upBy["Hank Williams"];
  if (!c) return { pass: false, detail: "no upside record" };
  if (c.cents !== 740) return { pass: false, detail: "upside " + c.cents + " != 740" };
  if (c.role !== "ANCHOR") return { pass: false, detail: "role " + c.role };
  const m = accepted.find((x) => x.opponent === "Hank Williams");
  return m && m.derived === 740 ? true : { pass: false, detail: "accepted proposal Derived is " + (m && m.derived) };
});
check("F17.2", "Loretta Lynn upside = 874 cents (opponent Derived stake on an accepted wager)", () => {
  const c = upBy["Loretta Lynn"];
  if (!c) return { pass: false, detail: "no upside record" };
  if (c.cents !== 874) return { pass: false, detail: "upside " + c.cents + " != 874" };
  if (c.role !== "ANCHOR") return { pass: false, detail: "role " + c.role };
  const m = accepted.find((x) => x.opponent === "Loretta Lynn");
  return m && m.derived === 874 ? true : { pass: false, detail: "accepted proposal Derived is " + (m && m.derived) };
});
check("F17.3", "Dolly Parton (PENDING outgoing) contributes 0", () => {
  const c = upBy["Dolly Parton"];
  if (!c) return { pass: false, detail: "no upside record" };
  if (c.cents !== 0) return { pass: false, detail: "pending offer contributes " + c.cents };
  return c.accepted === false ? true : { pass: false, detail: "pending offer marked accepted" };
});
check("F17.4", "Reba McEntire (COUNTER_PENDING) contributes 0", () => {
  const c = upBy["Reba McEntire"];
  if (!c) return { pass: false, detail: "no upside record" };
  if (c.cents !== 0) return { pass: false, detail: "counter-pending offer contributes " + c.cents };
  return c.accepted === false ? true : { pass: false, detail: "counter-pending offer marked accepted" };
});
check("F17.5", "Total UPSIDE LEFT = 1614 cents", () => {
  const total = action.ev("Resolver.commitmentTotals().upsideLeft");
  if (total !== 1614) return { pass: false, detail: "total " + total };
  return eq(upside.reduce((a, c) => a + c.cents, 0), 1614, "sum of records");
});
check("F17.6", "Rendered Action UPSIDE LEFT strip reads T16.14", () => {
  const r = action.getEl("summaryUpside").textContent;
  return r === "\u016616.14" ? true : { pass: false, detail: "rendered " + JSON.stringify(r) };
});
check("F17.7", "No unaccepted proposal contributes to UPSIDE LEFT", () => {
  const bad = upside.filter((c) => !c.accepted && c.cents !== 0);
  return bad.length ? { pass: false, detail: bad.map((c) => c.opponent + " " + c.lifecycle + " " + c.cents).join("; ") } : true;
});
check("F17.8", "Only accepted unresolved wagers contribute", () => {
  const contributors = upside.filter((c) => c.cents > 0);
  const bad = contributors.filter((c) => !c.accepted || !c.unresolved);
  if (bad.length) return { pass: false, detail: bad.map((c) => c.opponent).join(", ") };
  return eq(contributors.length, 2, "contributing matchups");
});
check("F17.9", "A settled (OVER) accepted wager would contribute 0", () => {
  const settled = upside.filter((c) => c.accepted && !c.unresolved);
  const bad = settled.filter((c) => c.cents !== 0);
  if (bad.length) return { pass: false, detail: bad.map((c) => c.opponent).join(", ") };
  // Drive the branch directly so it is exercised even though the fixture has no such wager.
  const probe = action.ev("(function(){const m=matchups.find(x=>x.bet===\"wagered\");const g=m.game;m.game=\"over\";const r=Resolver.upsideCommitment(m);m.game=g;return r})()");
  if (probe.cents !== 0) return { pass: false, detail: "forced OVER state still reports " + probe.cents };
  if (!probe.accepted || probe.unresolved) return { pass: false, detail: "forced OVER state flags wrong" };
  return true;
});
check("F17.10", "Prop Pool tickets are excluded from this Versus metric", () => {
  const bad = upside.filter((c) => c.kind !== "VERSUS");
  if (bad.length) return { pass: false, detail: bad.length + " non-Versus records" };
  const total = action.ev("Resolver.commitmentTotals().upsideLeft");
  return total === 1614 && !upside.some((c) => c.cents === 100) ? true : { pass: false, detail: "pool entry leaked into upside" };
});
check("F17.11", "The stale canonical upsideLeft literal is gone from the fixture", () => {
  if ("upsideLeft" in canon.action) return { pass: false, detail: "FS_CANON.action.upsideLeft still exists" };
  if (/upsideLeft\s*:\s*5700/.test(fixtureText)) return { pass: false, detail: "literal still in fixture source" };
  return /upsideLeft\s*:\s*\d/.test(fixtureText) ? { pass: false, detail: "a numeric upsideLeft literal remains" } : true;
});
check("F17.12", "UPSIDE LEFT reads the FROZEN accepted proposal, not the live board price", () => {
  // Repricing the live board must not move UPSIDE LEFT, because the accepted proposal is frozen.
  const before = action.ev("Resolver.commitmentTotals().upsideLeft");
  const after = action.ev("(function(){const m=matchups.find(x=>x.bet===\"wagered\");const d=m.derived;m.derived=d+5000;const r=Resolver.commitmentTotals().upsideLeft;m.derived=d;return r})()");
  return before === after && after === 1614 ? true : { pass: false, detail: "before " + before + " after " + after };
});
check("F17.13", "UPSIDE LEFT is integer cents", () => {
  const total = action.ev("Resolver.commitmentTotals().upsideLeft");
  const bad = upside.filter((c) => !Number.isInteger(c.cents));
  if (bad.length) return { pass: false, detail: bad.length + " non-integer records" };
  return Number.isInteger(total) ? true : { pass: false, detail: "total " + total };
});
check("F17.14", "Action publishes upside detail for independent recomputation", () => {
  const pub = A.__FS_COMMITMENTS__;
  if (!pub || !pub.upside) return { pass: false, detail: "no published upside detail" };
  if (pub.renderedUpsideLeft !== 1614) return { pass: false, detail: "published rendered value " + pub.renderedUpsideLeft };
  return eq(pub.upside.reduce((a, c) => a + c.cents, 0), 1614, "recomputed from published records");
});
check("F17.15", "Escrow / Wallet / Weekly Min / In Play are untouched by this pass", () => {
  const t = action.ev("Resolver.commitmentTotals()");
  if (t.versusEscrow !== 8000) return { pass: false, detail: "versus escrow " + t.versusEscrow };
  if (t.poolCommitted !== 100) return { pass: false, detail: "pool committed " + t.poolCommitted };
  if (t.inPlay !== 8100) return { pass: false, detail: "in play " + t.inPlay };
  if (t.qualifying !== 4100) return { pass: false, detail: "qualifying " + t.qualifying };
  if (t.weeklyMinRemaining !== 0) return { pass: false, detail: "weekly min " + t.weeklyMinRemaining };
  return eq(accountAudit.metrics.wallet, 9400, "wallet");
});
check("F17.16", "Score and Final Reconciliation are untouched by this pass", () => {
  if (accountAudit.metrics.fsScore !== 6500) return { pass: false, detail: "score " + accountAudit.metrics.fsScore };
  return eq(accountAudit.metrics.finalReconciliation, 28500, "final reconciliation");
});

/* Navigation contract ---------------------------------------------------- */
section("N · Persistent gear entry point and navigation contract");
for (const [name, art] of [["Action", action], ["Standings + Wrap Up", standings], ["Account + Gear", account]]) {
  const nav = art.sandbox.__FS_NAV__;
  check(`N.${name}.1`, `${name}: navigation contract is published`, () => (nav ? true : { pass: false, detail: "no __FS_NAV__" }));
  check(`N.${name}.2`, `${name}: gear control resolves to a real target`, () => {
    const gear = nav && nav.controls.find((c) => c.route === "gear");
    if (!gear) return { pass: false, detail: "no gear control" };
    return gear.target && gear.status !== "unresolved" ? true : { pass: false, detail: JSON.stringify(gear) };
  });
  check(`N.${name}.3`, `${name}: gear control is focusable and labelled`, () => {
    const gear = nav && nav.controls.find((c) => c.route === "gear");
    return gear && gear.focusable && gear.label ? true : { pass: false, detail: JSON.stringify(gear) };
  });
  check(`N.${name}.4`, `${name}: every chrome control resolves (no dead decorative control)`, () => {
    const dead = (nav ? nav.controls : []).filter((c) => c.status === "unresolved" || !c.target);
    return dead.length ? { pass: false, detail: JSON.stringify(dead) } : true;
  });
  check(`N.${name}.5`, `${name}: all four nav destinations are present`, () => {
    const routes = new Set((nav ? nav.controls : []).map((c) => c.route));
    const missing = ["standings", "action", "wrapup", "account"].filter((r) => !routes.has(r));
    return missing.length ? { pass: false, detail: `missing ${missing.join(", ")}` } : true;
  });
}
check("N.glyphs", "Bottom nav uses one unified glyph set across all three artifacts", () => {
  const glyphs = (html) => (html.match(/<span class="ni">(.)<\/span>/g) || []).map((s) => s.replace(/<[^>]+>/g, ""));
  const sets = [action.html, standings.html, account.html].map(glyphs).map((g) => g.join(""));
  return new Set(sets).size === 1 ? true : { pass: false, detail: JSON.stringify(sets) };
});

/* Typography ------------------------------------------------------------- */
section("T · Type floor");
check("T.1", "No user-facing type below 8px in any artifact (debug-only rules excluded)", () => {
  const offenders = [];
  for (const [name, art] of [["Action", action], ["Standings", standings], ["Account", account]]) {
    const re = /([^{};]*)\{[^}]*font-size:\s*([0-9.]+)px/g;
    let m;
    while ((m = re.exec(art.html)) !== null) {
      const selector = m[1].trim().split("\n").pop().trim();
      const size = parseFloat(m[2]);
      if (size < 8 && !/\.debug/.test(selector)) offenders.push(`${name}: ${selector} ${size}px`);
    }
  }
  return offenders.length ? { pass: false, detail: offenders.join("; ") } : true;
});
check("T.2", "Sub-8px rules that remain are debug-only", () => {
  const remaining = (action.html.match(/font-size:(7|6)[0-9.]*px/g) || []);
  const debugOnly = /\.debug[^{]*\{[^}]*font-size:7px/.test(action.html) || remaining.length === 0;
  return debugOnly ? true : { pass: false, detail: JSON.stringify(remaining) };
});

/* ------------------------------------------------------------------ report */
const passed = results.filter((r) => r.pass).length;
const failed = results.filter((r) => !r.pass);

if (process.argv.includes("--json")) {
  console.log(JSON.stringify({ passed, failed: failed.length, total: results.length, results }, null, 2));
} else {
  let last = "";
  for (const r of results) {
    if (r.section !== last) { console.log(`\n${r.section}`); last = r.section; }
    console.log(`  ${r.pass ? "PASS" : "FAIL"}  ${r.id.padEnd(14)} ${r.description}${r.pass ? "" : `\n          -> ${r.detail}`}`);
  }
  console.log(`\n${"=".repeat(78)}`);
  console.log(`RESULT: ${passed}/${results.length} checks passed, ${failed.length} failed.`);
  console.log(`Evidence class: SOURCE + RUNTIME (artifact JavaScript executed under a DOM shim).`);
  console.log(`NOT covered: visual browser certification - no browser automation is installed here.`);
  console.log("=".repeat(78));
}
process.exit(failed.length ? 1 : 0);
