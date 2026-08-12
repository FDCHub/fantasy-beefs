#!/usr/bin/env python3
"""
test_s7_full_ui_certification.py — Sprint 7 · full-application certification.

THE ENTRY POINT FOR SPRINT 7. It answers one question: is the five-tab Rev 4.2
application internally consistent, protocol-safe and ready to hand to Sprint 8?

It does NOT restate the four package suites. Those own their own packages and
are run here as gates; what this file adds is the set of claims that are true
only ACROSS packages, and that no single package suite is in a position to make:

  · every tab draws the same locked global copy;
  · the strip/disclaimer matrix is the POR's, tab by tab;
  · one wager grammar and one market vocabulary span League, Action and Week;
  · one Pool catalog spans League, The Week and the rules;
  · ONE Current Settle formula spans the Ledger and the commissioner;
  · no surface in the shipped application can post, mutate or issue;
  · no superseded Rev4.1 copy and no payment path survives anywhere;
  · no stale implementation placeholder survives anywhere.

Then it runs the browser certification, which measures three phone viewports and
the accessibility basics in a real headless Chrome.

USAGE:
    python test_s7_full_ui_certification.py
"""

from __future__ import annotations

import atexit
import glob
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")

_failures: list[str] = []
_exclusions: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _exclude(label: str, reason: str) -> None:
    """An environmental exclusion. NOT a pass and NOT a failure — the suite could
    not run here, and saying so is the only honest answer."""
    print(f"  [SKIP] {label} — {reason}")
    _exclusions.append(f"{label} ({reason})")


def _read(*parts: str) -> str:
    with open(os.path.join(WEB, *parts), encoding="utf-8") as fh:
        return fh.read()


def _read_root(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(source: str) -> str:
    """Remove comments so copy assertions test what the app RENDERS. A comment
    recording that something is superseded must not trip the check that it is
    gone."""
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.DOTALL)
    source = re.sub(r"^\s*//.*$", " ", source, flags=re.MULTILINE)
    return source


_NODE = shutil.which("node")


# ── The application under certification (S8-P1) ──────────────────────────────
#
# WHY THIS APPEARS IN A SPRINT 7 SUITE. Until S8-P1 the browser suites were
# served by the harness's own static file server, which was exactly right for
# certifying markup. P1 changed what the shell IS: it now asks /auth/me who is
# acting before it draws anything, and a static server answers 404 to that. The
# Sprint 7 assertions did not become wrong — the thing they measure stopped
# being reachable without a server and a session.
#
# So the suites now run against the REAL application on a disposable database,
# signed in as a seeded GM. That is a strictly STRONGER certification than the
# one it replaces: every Sprint 7 claim is now measured on the build a GM will
# actually load, rather than on the same modules served by a stub.
#
# The FS_TEST_* variables are read by web/tests/browser-harness.mjs. They are
# set in os.environ rather than passed to each subprocess call because this file
# runs Python package suites which themselves run node suites, and the
# environment is inherited by that whole chain.
from test_support_app_server import (  # noqa: E402
    GM_EMAIL as _CERT_GM_EMAIL,
    PASSWORD as _CERT_PASSWORD,
    AppServer,
)

_APP_SERVER = AppServer().start()
atexit.register(_APP_SERVER.stop)

os.environ["FS_TEST_ORIGIN"] = _APP_SERVER.origin
os.environ["FS_TEST_AUTH_EMAIL"] = _CERT_GM_EMAIL
os.environ["FS_TEST_AUTH_PASSWORD"] = _CERT_PASSWORD


APP_JS = sorted(glob.glob(os.path.join(WEB, "js", "**", "*.js"), recursive=True))
APP_SOURCE = "\n".join(open(p, encoding="utf-8").read() for p in APP_JS)
APP_RENDERED_SOURCE = _strip_comments(APP_SOURCE)
APP_CSS = "\n".join(
    open(p, encoding="utf-8").read()
    for p in sorted(glob.glob(os.path.join(WEB, "styles", "*.css")))
)
INDEX = _read("index.html")


# ── The five tabs, as the browser would build them ───────────────────────────

_PROBE = """
const base = %s;
const shell = await import(base + 'shell.js');
const nav = await import(base + 'nav.js');
const components = await import(base + 'components.js');
const ledgerModel = await import(base + 'ledger-model.js');
const commish = await import(base + 'commissioner-model.js');
const leagueData = await import(base + 'data/league-data.js');
const weekData = await import(base + 'data/week-data.js');
const rulesData = await import(base + 'data/rules-data.js');
const wagerModel = await import(base + 'wager-model.js');
const week = await import(base + 'week.js');
const ledger = await import(base + 'ledger.js');
const action = await import(base + 'action.js');
const rules = await import(base + 'rules.js');

week.resetWeek();
const panels = {};
for (const d of nav.NAV_DESTINATIONS) panels[d.id] = shell.buildPanelContent(d.id);

console.log(JSON.stringify({
  destinations: nav.NAV_DESTINATIONS.map((d) => ({ id: d.id, label: d.label, panelId: d.panelId })),
  panels,
  disclaimerText: components.CREDITS_DISCLAIMER,
  disclaimerCounts: Object.fromEntries(
    Object.entries(panels).map(([k, v]) => [k, components.countDisclaimers(v)])),
  stripCounts: Object.fromEntries(
    Object.entries(panels).map(([k, v]) => [k, (v.match(/class="fs-strip"/g) || []).length])),
  markets: wagerModel.MARKETS,
  modeCopy: wagerModel.MODE_COPY,
  leaguePools: leagueData.POOLS.map((p) => ({ n: p.catalogNumber, name: p.name, rule: p.rule, scope: p.scope })),
  weekPools: weekData.weekPools(weekData.CURRENT_WEEK).map((p) => ({ n: p.catalogNumber, name: p.name, rule: p.rule, scope: p.scope })),
  rulesPoolsPerWeek: rulesData.POOLS_PER_WEEK,
  gmLedger: ledgerModel.reconciliation(),
  currentSettleTerms: ledgerModel.CURRENT_SETTLE_TERMS,
  backend: ledgerModel.backendEquivalent(),
  commishPositions: commish.gmPositions(),
  league: commish.leagueReconciliation(),
  seams: {
    ledgerRead: ledgerModel.LEDGER_READ_SEAM,
    topoffCommand: ledgerModel.TOPOFF_COMMAND_SEAM,
    settings: rulesData.SETTINGS_SEAM,
    auth: commish.COMMISSIONER_AUTH_SEAM,
    positions: commish.LEAGUE_POSITIONS_SEAM,
    trial: commish.TRIAL_BALANCE_SEAM,
  },
  betsHeading: week.BETS_HEADING,
  ledgerTitle: ledger.LEDGER_TITLE,
  actionHeader: action.ACTION_HEADER,
  rulesTitle: rules.RULES_TITLE,
  legalLine: rulesData.LEGAL_LINE,
}));
"""


def _probe() -> dict:
    if _NODE is None:
        return {}
    url = "file:///" + os.path.join(WEB, "js").replace("\\", "/").lstrip("/") + "/"
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", _PROBE % json.dumps(url)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    if proc.returncode != 0:
        print(proc.stderr[:2000])
        return {}
    return json.loads(proc.stdout)


APP = _probe()
PANELS = APP.get("panels", {})
ALL_PANELS = "\n".join(PANELS.values())


# ── 1 · Package gates ────────────────────────────────────────────────────────

print("\nSprint 7 package suites")


def _run_suite(script: str, label: str) -> None:
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    _assert(label, proc.returncode == 0 and failed == 0,
            f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")


_assert("node is available", _NODE is not None)
_assert("the five tabs build", len(PANELS) == 5, str(len(PANELS)))

_run_suite("test_s7_p1_ui_shell.py", "Package 1 — shared shell and global components")
_run_suite("test_s7_p2_league_action.py", "Package 2 — League and Action")
_run_suite("test_s7_p3_week_ledger.py", "Package 3 — The Week and Ledger")
_run_suite("test_s7_p4_rules_commissioner.py", "Package 4 — Rules, Settings and commissioner")


# ── 2 · Global POR copy, on every tab ────────────────────────────────────────

print("\nLocked global copy, certified across all five tabs")

_assert("the masthead tagline is the Rev 4.2 tagline",
        "FANTASY LEAGUES · VIRTUAL STAKES" in _strip_comments(_read("js", "demo-state.js")))
_assert("the league identity is the league name alone",
        "CULV APPRECIATION SOCIETY" in _strip_comments(_read("js", "demo-state.js")))
_assert("the superseded OUR THING · YOUR LEAGUE appears nowhere",
        "OUR THING" not in APP_RENDERED_SOURCE and "OUR THING" not in INDEX)
_assert("the superseded Fantasy Sportsbook lockup appears nowhere",
        "Fantasy Sportsbook" not in APP_RENDERED_SOURCE)
_assert("the Credits disclaimer string is the approved one",
        APP.get("disclaimerText") == "VIRTUAL CREDITS · $ IS DISPLAY ONLY · NO CASH VALUE",
        str(APP.get("disclaimerText")))

DESTINATIONS = APP.get("destinations", [])
_assert("the navigation is the five locked destinations in order",
        [d["label"] for d in DESTINATIONS]
        == ["League", "Action", "Ledger", "The Week", "Rules & Settings"],
        " · ".join(d["label"] for d in DESTINATIONS))

print("\nThe strip and disclaimer matrix is the POR's, tab by tab")

# League, Action and Ledger summarise a position. The Week and Rules & Settings
# do not, so they take no strip — and the disclaimer appears only under one.
EXPECTED = {
    "league": (1, 1), "action": (1, 1), "ledger": (2, 1), "week": (0, 0), "rules": (0, 0),
}
for tab, (strips, disclaimers) in EXPECTED.items():
    _assert(f"{tab}: {strips} strip(s)",
            APP.get("stripCounts", {}).get(tab) == strips,
            str(APP.get("stripCounts", {}).get(tab)))
    _assert(f"{tab}: {disclaimers} disclaimer(s)",
            APP.get("disclaimerCounts", {}).get(tab) == disclaimers,
            str(APP.get("disclaimerCounts", {}).get(tab)))
_assert("the Ledger's second strip is its approved My Season strip",
        'id="fs-strip-season"' in PANELS.get("ledger", ""))
_assert("no tab carries a disclaimer without a strip above it",
        all(APP["disclaimerCounts"][t] == 0 or APP["stripCounts"][t] > 0 for t in EXPECTED))

print("\nLocked tab copy")
for label, value in (("Action header", APP.get("actionHeader")),
                     ("Ledger title", APP.get("ledgerTitle")),
                     ("Rules title", APP.get("rulesTitle")),
                     ("The Week bets heading", APP.get("betsHeading"))):
    _assert(f"{label} is present and locked", bool(value), str(value))
_assert("the Action header is the locked wording",
        APP.get("actionHeader") == "WEEK 5 · REGULAR SEASON ACTION")
_assert("the Ledger title is the locked wording",
        APP.get("ledgerTitle") == "FANTASYSTAKES LEDGER")
_assert("the Rules title is the locked wording",
        APP.get("rulesTitle") == "RULES & SETTINGS")
_assert("The Week's bets heading is the locked viewport treatment",
        APP.get("betsHeading") == "FANTASYSTAKES BETS · 4 SHOWN · SWIPE ↕")
_assert("the legal line is exact and lives on Rules & Settings only",
        APP.get("legalLine") == "© 2026 Fraser D. Coleman. All Rights Reserved. FantasyStakes™."
        and PANELS.get("rules", "").count('id="fs-legal"') == 1
        and sum("All Rights Reserved" in v for k, v in PANELS.items() if k != "rules") == 0)


# ── 3 · Cross-tab component consistency ──────────────────────────────────────

print("\nOne wager grammar spans League, Action and The Week")

MARKETS = APP.get("markets", [])
_assert("three markets, persisted as the lifecycle's own values",
        [m["persisted"] for m in MARKETS] == ["straight", "spread", "over_under"],
        ", ".join(m["persisted"] for m in MARKETS))
_assert("the display labels are ML, Spread and O/U",
        [m["label"] for m in MARKETS] == ["ML", "Spread", "O/U"])

for tab in ("league", "action", "week"):
    _assert(f"{tab} renders the shared wager card",
            'class="fs-wcard' in PANELS.get(tab, ""))
_assert("the lifecycle card is shared by Action and The Week",
        "fs-wcard--lifecycle" in PANELS.get("action", "")
        and "fs-wcard--lifecycle" in PANELS.get("week", ""))
_assert("a completed wager keeps the card identity of the live one",
        "fs-wcard--lifecycle" in PANELS.get("action", "")
        and "WON" in PANELS.get("action", "") and "LOST" in PANELS.get("action", ""))

MODE_COPY = APP.get("modeCopy", {})
_assert("one Locked explanation exists in the build",
        APP_SOURCE.count("Terms freeze the moment you send this.") == 1,
        str(APP_SOURCE.count("Terms freeze the moment you send this.")))
# GOVERNED REVISION, WP5, FOLLOWING S8-P4C-2R2. This pinned the Dynamic
# headline "Both lineups and the odds stay live and lock in at kickoff." That
# sentence was CORRECTED on explicit authorisation: GE-901 / AP-212 fire Final
# Lock immediately before the earliest covered kickoff across EITHER lineup, so
# "at kickoff" invited a GM to picture their own Sunday start while a covered
# Thursday starter had already locked the wager. P4C-2R2 revised the copy and
# the component suites; this assertion was left pinned to the superseded phrase
# and went unnoticed because the suite it lives in was already failing.
#
# THE REQUIREMENT IS "EXACTLY ONE", NOT "THIS WORDING" — one explanation of each
# mode in the build, so the rules sheet and the composer cannot drift apart. The
# wording itself is owned by test_s8_p4c2r2_final_lock_copy.py, which certifies
# the trigger the sentence describes.
_assert("one Dynamic explanation exists in the build",
        APP_SOURCE.count(
            "Lineups and odds stay live until Final Lock, just before the "
            "first ") == 1,
        "the single governed Dynamic headline")
_assert("the rules sheet quotes that copy rather than restating it",
        "MODE_COPY" in _read("js", "data", "rules-data.js"))
_assert("the retired 'flex up or down' draft appears nowhere",
        "flex up" not in APP_RENDERED_SOURCE)

# GOVERNED REVISION, WP5. This counted the engine's own words, LOCKED and
# DYNAMIC, on the Action panel. `action.js modeLabel()` draws FIXED or FLOATING
# instead — a deliberate choice recorded in that function: "a GM should be able
# to tell the two apart without knowing what an Anchor is". The engine's names
# still label the mode inside the detail sheet.
#
# THE REQUIREMENT IS RULING §4 — the Locked/Dynamic distinction is visible on
# the card, before a GM acts, rather than in fine print. That is unchanged and
# is what is asserted; only the vocabulary it looks for is the product's.
_LIFECYCLE_CARDS = PANELS.get("action", "").count("fs-wcard--lifecycle")
_MODE_LABELS = (PANELS.get("action", "").count("FIXED")
                + PANELS.get("action", "").count("FLOATING"))
_assert("Locked or Dynamic is visible on every lifecycle card",
        _LIFECYCLE_CARDS > 0 and _MODE_LABELS >= _LIFECYCLE_CARDS,
        f"{_MODE_LABELS} mode label(s) across {_LIFECYCLE_CARDS} lifecycle card(s)")

print("\nA Yahoo fixture never presents as a FantasyStakes wager")

_assert("Yahoo cards are badged as fixtures", ">YAHOO<" in PANELS.get("week", ""))
_assert("no Yahoo card offers a challenge affordance",
        "Challenge" not in PANELS.get("week", ""))
_assert("the preview states the Yahoo source context",
        "OFFICIAL YAHOO FANTASY MATCHUP" in _read("js", "preview.js"))
_assert("and says it is not a FantasyStakes wager",
        "not a FantasyStakes wager" in _read("js", "preview.js"))

print("\nOne Pool catalog spans League, The Week and the rules")

league_pools = APP.get("leaguePools", [])
week_pools = APP.get("weekPools", [])
_assert("League and The Week show the same four Pool definitions",
        [(p["n"], p["name"], p["rule"]) for p in league_pools]
        == [(p["n"], p["name"], p["rule"]) for p in week_pools])
_assert("there are exactly four, as the rules state",
        len(league_pools) == 4 == APP.get("rulesPoolsPerWeek"))
_assert("every subject scope is one of the two the catalog defines",
        {p["scope"] for p in league_pools} <= {"TEAM", "MATCHUP"})
_assert("rollover is never a subject scope",
        all(p["scope"] in ("TEAM", "MATCHUP") for p in week_pools))
_assert("one Pool detail sheet serves both tabs",
        "poolSheet" in _read("js", "week.js") and "export function poolSheet" in _read("js", "league.js"))

print("\nONE Current Settle model spans the Ledger and the commissioner")

gm = APP.get("gmLedger", {})
positions = APP.get("commishPositions", [])
league = APP.get("league", {})
you = next((p for p in positions if p["teamId"] == "you"), {})

_assert("Current Settle takes exactly three terms",
        len(APP.get("currentSettleTerms", [])) == 3)
_assert("the activity nets are not among them",
        "netVersusCents" not in APP.get("currentSettleTerms", [])
        and "netPoolsCents" not in APP.get("currentSettleTerms", []))
_assert("the Ledger's own figure reconciles",
        gm.get("currentSettleCents")
        == gm.get("position", {}).get("wageringPositionCents", 0)
        + gm.get("adjustments", {}).get("netAdjustmentsCents", 0)
        - gm.get("advances", {}).get("totalVirtualStakesCents", 0) == -4500)
_assert("the backend assets/obligations grouping agrees to the cent",
        APP.get("backend", {}).get("currentSettleCents") == gm.get("currentSettleCents"))
_assert("the commissioner's view of that GM is the same figure",
        you.get("currentSettleCents") == gm.get("currentSettleCents"),
        f"{you.get('currentSettleCents')} vs {gm.get('currentSettleCents')}")
_assert("every GM uses the same formula",
        all(p["currentSettleCents"] == p["wageringPositionCents"] + p["netAdjustmentsCents"]
            - p["totalVirtualStakesCents"] for p in positions))
_assert("the league roll-up is an aggregation of those same figures",
        league.get("sumOfGmSettlesCents") == league.get("aggregateSettleCents")
        and league.get("closes") is True)
_assert("only one module computes Current Settle",
        APP_SOURCE.count("export function currentSettleCents") == 1)
_assert("the commissioner imports it rather than redefining it",
        "currentSettleCents" in _read("js", "commissioner-model.js")
        and "from './ledger-model.js'" in _read("js", "commissioner-model.js"))
_assert("pending holds are excluded from settlement, not counted as liabilities",
        league.get("exceptions", {}).get("pendingOfferHolds", {}).get("settlementLiability") is False)


# ── 4 · Protocol safety ──────────────────────────────────────────────────────
#
# GOVERNED REVISION, S8-P1. Sprint 7 certified that the application made NO
# network call, submitted NO form and wrote NO storage. Those were the right
# invariants for a build with no session: an application that could not reach
# the server could not misuse it, and the assertions said so in the simplest
# checkable way.
#
# P1 makes all three false BY DESIGN. The application must now call the server,
# must submit a sign-in form, and must be reachable through a cookie. Leaving
# the assertions in place would fail a correct build; deleting them would
# retire the protection they provided and leave nothing in its place.
#
# So each is replaced by the invariant it was standing in for. Sprint 7 did not
# actually care that `fetch(` was absent — it cared that no surface could reach
# the protocol unaccountably. That property is still checkable, and the
# replacements below are strictly more specific about it than counting the
# absence of a keyword ever was.
#
#   WAS  no network call is made from any app module
#   NOW  exactly one module makes network calls, and every other module
#        reaches the server through it
#
#   WAS  no form is submitted
#   NOW  every form is enumerated and governed (gate + Pool Bet)
#
#   WAS  no storage is written
#   NOW  no credential enters script-readable persistent storage: no
#        localStorage, no sessionStorage, and document.cookie is READ (for the
#        CSRF token) and never written
#
# The behavioural half of these claims — that the cookie is genuinely
# unreadable, that a request bypassing the client seam is refused — cannot be
# established by reading source, and is certified in a real browser by
# test_s8_p1_browser.py.

print("\nThe application reaches the protocol through one authenticated door")

_NETWORK_CALL = r"\bfetch\s*\(|XMLHttpRequest|navigator\.sendBeacon"

_NETWORK_MODULES = sorted(
    os.path.basename(p) for p in APP_JS
    if re.search(_NETWORK_CALL, _strip_comments(open(p, encoding="utf-8").read()))
)
_assert("exactly one module in the application makes network calls",
        _NETWORK_MODULES == ["session.js"], str(_NETWORK_MODULES))

# Every other module must therefore go through it. This is what makes "no
# illustrative UI path can bypass the authenticated client" a fact about the
# code rather than a convention someone has to remember.
_CALLERS = sorted(
    os.path.basename(p) for p in APP_JS
    if re.search(r"from ['\"]\./session\.js['\"]",
                 _strip_comments(open(p, encoding="utf-8").read()))
)
_assert("the modules that need the server import that one door",
        set(_CALLERS) >= {"auth-view.js", "shell.js"}, str(_CALLERS))

_assert("no websocket or event-source is opened",
        not re.search(r"new WebSocket|EventSource", APP_RENDERED_SOURCE))

_FORMS = re.findall(r"<form\b[^>]*", APP_RENDERED_SOURCE + INDEX)
# GOVERNED REVISION, S8-P4B-3. P1 replaced "no form is submitted" with "the
# only form is the sign-in gate", because at that point authentication was the
# application's only write. The B2 ruling then made Standard Pool Bet the one
# governed settings mutation in MVP, so a second form is correct — and the
# invariant's substance is unchanged: EVERY form is enumerated, and each is
# either the sign-in gate or a governed, authenticated, server-authorised
# mutation. A form that is neither is what this still refuses.
_GOVERNED_FORMS = {"fs-gate-form", "fs-pool-entry-form"}
_assert("every form in the application is enumerated and governed",
        len(_FORMS) == len(_GOVERNED_FORMS)
        and all(any(name in f for f in _FORMS) for name in _GOVERNED_FORMS),
        str(_FORMS))
_assert("the mutating form targets the governed command, not the legacy route",
        "/settings/pool-entry" in APP_SOURCE
        and "'/pool/config'" not in APP_SOURCE)

print("\nNo browser credential enters script-readable storage")

_assert("no module writes localStorage",
        not re.search(r"localStorage\s*(\.|\[)", APP_RENDERED_SOURCE), "localStorage is used")
_assert("no module writes sessionStorage",
        not re.search(r"sessionStorage\s*(\.|\[)", APP_RENDERED_SOURCE), "sessionStorage is used")

# document.cookie appears exactly once, in a READ. The session token is
# HttpOnly and unreachable; what is read is the CSRF token, which authenticates
# nothing on its own. An assignment would be a different matter entirely, so
# the check is specifically for one.
_assert("no module WRITES document.cookie",
        not re.search(r"document\.cookie\s*=", APP_RENDERED_SOURCE))
_assert("document.cookie is read only in the one network module",
        sorted(os.path.basename(p) for p in APP_JS
               if "document.cookie" in _strip_comments(open(p, encoding="utf-8").read()))
        == ["session.js"])
_assert("no token or password is held in a module-scoped variable",
        not re.search(r"(?i)\b(let|var|const)\s+\w*(token|password|jwt)\w*\s*=\s*['\"]",
                      APP_RENDERED_SOURCE))

_assert("no protocol module is imported into the web app",
        not re.search(r"from ['\"](\.\./)+(economy|ledger|beefs|betting|wallet|api|payments)/",
                      APP_SOURCE))

print("\nNo payment processing anywhere in the application")

# Source citations are provenance, not product copy, and one of them names the
# addendum that REMOVED Stripe — a scan that tripped on the record of the removal
# would be punishing the evidence. The scan runs over everything else.
PAYMENT_SCAN = re.sub(r"source:\s*'[^']*'", " ",
                      APP_RENDERED_SOURCE + INDEX + APP_CSS)
for banned in ("Stripe", "PayPal", "Apple Pay", "credit card", "debit card",
               "payment method", "billing address", "billing information",
               "checkout", "routing number", "card number", "cvv"):
    _assert(f"no {banned!r} in the shipped app",
            not re.search(banned, PAYMENT_SCAN, re.I), banned)
_assert("the only Stripe reference left is the citation of its removal",
        APP_RENDERED_SOURCE.count("Stripe") == 1
        and "Stripe Removal Addendum" in APP_RENDERED_SOURCE)
_assert("Credits are declared to carry no cash value",
        "NO CASH VALUE" in APP_SOURCE)
_assert("the Stripe removal is still asserted by its own regression suite",
        os.path.isfile(os.path.join(ROOT, "test_stripe_removal_regression.py")))

print("\nBetting vocabulary survives")
RENDERED_COPY = APP_RENDERED_SOURCE + ALL_PANELS
for term in ("wager", "bets", "stake", "pot", "ML", "Spread", "O/U", "Locked", "Dynamic",
             "odds", "Challenge"):
    _assert(f"the vocabulary keeps {term!r}",
            re.search(rf"\b{re.escape(term)}\b", RENDERED_COPY, re.I) is not None, term)

print("\nWhole dollars are display only; exact cents are underneath")

_assert("one module performs the rounding",
        APP_SOURCE.count("export function roundCentsToWholeDollars") == 1)
_assert("it refuses a non-integer input",
        "must be an exact integer number of cents" in _read("js", "credits.js"))
_assert("no panel draws a figure with cents",
        not re.search(r"\$\d+\.\d\d", ALL_PANELS))
_assert("every panel that draws money carries exact cents",
        all(len(re.findall(r'data-exact-cents="-?\d+"', PANELS[t])) > 0
            for t in ("league", "action", "ledger", "week", "rules")))
_assert("every exact-cents value in the app is an integer",
        all(float(v) == int(v) for v in re.findall(r'data-exact-cents="(-?\d+)"', ALL_PANELS)))


# ── 5 · Stale implementation artifacts ───────────────────────────────────────

print("\nNo stale implementation artifacts survive in the application")

for marker in ("TODO", "FIXME", "XXX", "HACK"):
    _assert(f"no {marker} marker in web/",
            marker not in APP_SOURCE + APP_CSS + INDEX, marker)
_assert("no copy promises a later Sprint 7 package",
        "later Sprint 7 package" not in APP_SOURCE,
        "Sprint 7 is complete; a promise of a later Sprint 7 package cannot be kept")
_assert("no panel claims its content is built later",
        not re.search(r"built in a later", ALL_PANELS))
_assert("the Package 1 panel scaffolding is gone",
        "mountPanelContent" not in APP_SOURCE and "fs-panel__scroll" not in APP_CSS)
_assert("every destination is built by its own module, with no placeholder branch",
        "no panel content defined" in _read("js", "shell.js")
        and "buildRulesPanel()" in _read("js", "shell.js"))

# Seam documentation is NOT a stale placeholder. Each of these describes a real,
# named integration boundary and must survive this pass.
SEAMS = APP.get("seams", {})
# GOVERNED REVISION, S8-P3. These three seams recorded that no read model
# existed. P3 built all three, so `endpoint is None` would now fail a correct
# build. What each seam must still record is that the SURFACE is not yet bound
# — the tabs below still draw illustrative figures until P4 — and, for the
# trial balance, that it deliberately stayed global.
_assert("the Ledger read-model seam names its route and is not yet bound",
        SEAMS.get("ledgerRead", {}).get("endpoint")
        == "GET /league/{league_id}/ledger/me"
        and "NOT YET BOUND" in str(SEAMS.get("ledgerRead", {}).get("status")))
_assert("the Top-Off command seam is still declared",
        SEAMS.get("topoffCommand", {}).get("endpoint") == "POST /league/{league_id}/top-offs")
# GOVERNED REVISION, S8-P4: the B2 ruling made Standard Pool Bet mutable, so
# the seam now names one command — and must still record that the other three
# rows are read-only, which is the substance of that ruling.
_assert("the settings seam names the one governed command",
        SEAMS.get("settings", {}).get("endpoint")
        == "PUT /league/{league_id}/settings/pool-entry")
_assert("and records that the other three rows stay read-only",
        sorted(SEAMS.get("settings", {}).get("readOnly", []))
        == ["championship-split", "economy-stop", "skunk-fee"])
# S8-P1 narrowed this one. The session half is closed — the app has an
# authenticated identity — while the decision-command half is not, and the
# assertion now checks exactly that split rather than the old blanket claim.
# Reporting the seam as closed because authentication landed would claim a
# working decision path that does not exist.
_assert("the session-identity half of the commissioner seam is closed",
        "SESSION IDENTITY EXISTS" in str(SEAMS.get("auth", {}).get("status")))
_assert("and the decision-command half is still declared open",
        "NOT YET BOUND" in str(SEAMS.get("auth", {}).get("status"))
        and bool(SEAMS.get("auth", {}).get("missing")))
_assert("the league-wide read-model seam names its route and is not yet bound",
        SEAMS.get("positions", {}).get("endpoint")
        == "GET /league/{league_id}/ledger/positions"
        and "NOT YET BOUND" in str(SEAMS.get("positions", {}).get("status")))
# S8-P3R: the global invariant is BACKEND-ONLY. Not a deficiency — an
# authority boundary, because no platform-operator tier exists to hold an HTTP
# surface for it. The commissioner's question is a LEAGUE question and has its
# own answer, which the seam must name so P4 binds that and not this.
_assert("the trial-balance seam declares no endpoint and says it is backend-only",
        SEAMS.get("trial", {}).get("endpoint") is None
        and "BACKEND-ONLY" in str(SEAMS.get("trial", {}).get("status")))
_assert("the trial balance stayed GLOBAL and says what it does not prove",
        "global" in str(SEAMS.get("trial", {}).get("scope")).lower()
        and "league" in str(SEAMS.get("trial", {}).get("doesNotProve")).lower())
_assert("and it points the commissioner at League Reconciliation instead",
        SEAMS.get("trial", {}).get("commissionerSurface")
        == "GET /league/{league_id}/ledger/reconciliation")
_assert("no route anywhere in the API serves the global invariant",
        not re.search(r'@app\.get\("[^"]*(integrity|trial[-_]balance)',
                      _read_root("api", "main.py")))
_assert("the four seams are tracked independently, not as one blocker",
        len({json.dumps(SEAMS.get(k), sort_keys=True)
             for k in ("settings", "auth", "positions", "trial")}) == 4)


# ── 6 · Browser certification ────────────────────────────────────────────────

print("\nFull-application browser certification (headless Chrome, three viewports)")

if _NODE is None:
    _assert("node is available to run the browser certification", False)
else:
    proc = subprocess.run(
        [_NODE, os.path.join(WEB, "tests", "e2e_certification.mjs")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write(proc.stderr)
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    _assert("the browser certification is green",
            proc.returncode == 0 and failed == 0,
            f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")


# ── 7 · Protocol regressions ─────────────────────────────────────────────────

print("\nProtocol regressions (DB-free)")

# Run each in its own process. These suites share a module-level fixture that
# writes to the local development database, and importing several into one
# pytest process makes a later import collide with an earlier one's rows. That
# is a pre-existing property of the repository's test set, not of this UI work,
# and it is worked around here rather than by deleting anyone's database.
SCRIPT_SUITES = [
    ("test_economy_config.py", "the certified economy stops still hold"),
    ("test_pool_catalog_invariants.py", "the Pool catalog invariants still hold"),
    ("test_s4_pool_catalog_unit.py", "the Pool catalog unit suite is green"),
]
for script, label in SCRIPT_SUITES:
    proc = subprocess.run([sys.executable, os.path.join(ROOT, script)],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=ROOT)
    body = proc.stdout
    ok = proc.returncode == 0 and "[FAIL]" not in body and "FAILED" not in body
    _assert(label, ok, f"exit {proc.returncode}")

proc = subprocess.run(
    [sys.executable, "-m", "pytest", "test_s4_pool_engine_unit.py", "-q"],
    capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
_assert("the Pool engine unit suite is green",
        proc.returncode == 0, proc.stdout.strip().splitlines()[-1] if proc.stdout else "")

# Script-style, like several suites in this repository: pytest collects nothing
# from it and exits 5, so it is run as the script it is.
proc = subprocess.run(
    [sys.executable, os.path.join(ROOT, "test_stripe_removal_regression.py")],
    capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
_assert("the Stripe removal regression is green",
        proc.returncode == 0 and "[FAIL]" not in proc.stdout,
        f"exit {proc.returncode}")

# PostgreSQL-backed certification is out of reach without a database URL. That
# is an environmental exclusion: it is neither a pass nor an implementation
# failure, and reporting it as either would be false.
if os.environ.get("TEST_DATABASE_URL"):
    # WP5 — RUN AS THE SCRIPT IT IS, not through pytest. This suite guards its
    # own environment and calls `sys.exit(2)` AT IMPORT when the database is not
    # a disposable empty `_test` one. Under pytest that exit happens during
    # collection, which pytest reports as INTERNALERROR — so the assertion
    # failed whenever a database WAS supplied, and passed only by never running.
    # The Stripe regression a few lines above is invoked as a script for exactly
    # this reason and carries the same note.
    #
    # THE SUITE ALSO NEEDS ITS OWN EMPTY DATABASE, which `run_pg_suites.py`
    # provides when it is the caller. Here the operator's TEST_DATABASE_URL is
    # used as given; a non-empty one produces the harness's own refusal, which
    # is reported rather than being mistaken for a season-close failure.
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "test_s5_p3_season_close_pg.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    if proc.returncode == 2:
        _exclude("the PostgreSQL economy suite",
                 "the supplied TEST_DATABASE_URL is not an empty disposable "
                 "database; run it through run_pg_suites.py")
    else:
        _assert("the PostgreSQL economy suite is green",
                proc.returncode == 0 and "[FAIL]" not in proc.stdout,
                f"exit {proc.returncode}")
else:
    _exclude("PostgreSQL-backed protocol suites",
             "TEST_DATABASE_URL is not set in this environment")


# ── Result ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _exclusions:
    print(f"ENVIRONMENTAL EXCLUSIONS: {len(_exclusions)}")
    for e in _exclusions:
        print(f"  - {e}")
    print()

if _failures:
    print(f"CERTIFICATION FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("SPRINT 7 CERTIFIED — all assertions PASSED")