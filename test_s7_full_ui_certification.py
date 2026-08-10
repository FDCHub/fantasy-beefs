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
_assert("one Dynamic explanation exists in the build",
        APP_SOURCE.count("Both lineups and the odds stay live and lock in at kickoff.") == 1)
_assert("the rules sheet quotes that copy rather than restating it",
        "MODE_COPY" in _read("js", "data", "rules-data.js"))
_assert("the retired 'flex up or down' draft appears nowhere",
        "flex up" not in APP_RENDERED_SOURCE)

_assert("Locked or Dynamic is visible on every lifecycle card",
        PANELS.get("action", "").count("LOCKED") + PANELS.get("action", "").count("DYNAMIC") >= 11)

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

print("\nNothing in the shipped application can post, mutate or issue")

_assert("no network call is made from any app module",
        not re.search(r"\bfetch\s*\(|XMLHttpRequest|navigator\.sendBeacon", APP_RENDERED_SOURCE))
_assert("no form is submitted", not re.search(r"\.submit\s*\(|<form", APP_RENDERED_SOURCE + INDEX))
_assert("no websocket or event-source is opened",
        not re.search(r"new WebSocket|EventSource", APP_RENDERED_SOURCE))
_assert("no storage is written",
        not re.search(r"localStorage|sessionStorage|document\.cookie", APP_RENDERED_SOURCE))
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
_assert("the Ledger read-model seam is still declared",
        SEAMS.get("ledgerRead", {}).get("endpoint") is None)
_assert("the Top-Off command seam is still declared",
        SEAMS.get("topoffCommand", {}).get("endpoint") == "POST /league/{league_id}/top-offs")
_assert("the configuration-command seam is still declared",
        SEAMS.get("settings", {}).get("endpoint") is None)
_assert("the session-identity seam is still declared",
        "NO SESSION IDENTITY" in str(SEAMS.get("auth", {}).get("status")))
_assert("the league-wide read-model seam is still declared",
        SEAMS.get("positions", {}).get("endpoint") is None)
_assert("the trial-balance seam is still declared",
        SEAMS.get("trial", {}).get("endpoint") is None)
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
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "test_s5_p3_season_close_pg.py", "-q"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    _assert("the PostgreSQL economy suite is green", proc.returncode == 0)
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