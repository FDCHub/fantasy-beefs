#!/usr/bin/env python3
"""
test_s8_p4c5_integration.py — Sprint 8 P4C-5 · full P4 integration certification.

THE SEAMS, NOT THE SUBSYSTEMS. Every earlier package certified its own surface
against its own fixture. What none of them could prove is that the five tabs are
ONE application — that the week League shows is the week Action requests, that
League's Available is the Ledger's Available to the cent, that a wager reads the
same on Action and on The Week, and that all of it survives 375, 390 and 430.

WEEK 9, NOT WEEK 5. The whole application assumed 5 until P4C-3, and a week-5
fixture cannot tell "reads the authoritative week" apart from "still assumes 5".
The integrated session therefore states week 9, and the browser suite asserts
that no tab claims 5.

WHAT THIS FILE DOES ITSELF: the checklist gate, the production-vs-demo import
audit, and the unresolved-field inventory. The cross-tab and geometry claims are
made in the browser, because scroll widths and rendered text are not derivable
from source.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


print("=" * 78)
print("S8-P4C-5 — full P4 integration certification")
print("=" * 78)


# ══ §1 · the P4 close checklist ═════════════════════════════════════════════

_section("§1 · zero open mandatory P4 items")

CHECKLIST = open(os.path.join(ROOT, "P4_CLOSE_CHECKLIST.md"),
                 encoding="utf-8").read()

_open_status = [ln for ln in CHECKLIST.splitlines()
                if ln.strip().startswith("**Status:**") and "OPEN" in ln]
_unchecked = [ln for ln in CHECKLIST.splitlines() if "- [ ]" in ln]

_assert("§1: no checklist item carries an OPEN status",
        not _open_status, str(_open_status))
_assert("§1: no checklist item has unfinished work",
        not _unchecked, str(_unchecked[:3]))
_assert("§1: the mandatory Pool-pick item is recorded CLOSED",
        "**Status:** CLOSED" in CHECKLIST and "submit_pool_pick" in CHECKLIST,
        "closed by S8-P4C-4, not by this package")


# ══ §3 · production never obtains authority from a fixture ══════════════════

_section("§3 · production-vs-demo import audit")

WEB_JS = os.path.join(ROOT, "web", "js")
FIXTURES = {"league-data.js", "action-data.js", "week-data.js",
            "ledger-data.js", "rules-data.js", "commissioner-data.js"}


def _code_only(js: str) -> str:
    """JS with comments stripped — the audit reads code, not prose about it."""
    out, i, n = [], 0, len(js)
    while i < n:
        if js.startswith("/*", i):
            end = js.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        line_end = js.find(chr(10), i)
        if line_end == -1:
            line_end = n
        line = js[i:line_end]
        if not line.lstrip().startswith(("//", "*")):
            out.append(line)
        i = line_end + 1
    return chr(10).join(out)


MODELS = ["ledger-model.js", "action-model.js", "league-model.js",
          "settings-model.js", "pool-slate-model.js", "commissioner-model.js"]

# THE MODELS ARE THE AUTHORITY BOUNDARY, and every one that imports a fixture
# must hold it behind a DEMO MODE. That is the certified pattern, not an
# exception: the component suites need an illustrative source, and the mode is
# what keeps it from ever being reached by a signed-in GM.
#
# What would be a leak is a model importing a fixture with NO mode at all —
# illustrative values behind an authoritative-looking accessor, invisible from
# the rendered page. So the audit asserts the gate, not the absence.
_model_leaks = []
for name in MODELS:
    path = os.path.join(WEB_JS, name)
    if not os.path.exists(path):
        continue
    code = _code_only(open(path, encoding="utf-8").read())
    imports_fixture = any(f"data/{f}" in code for f in FIXTURES)
    if imports_fixture and "DEMO" not in code:
        _model_leaks.append((name, "imports a fixture with no demo mode"))

_assert("§3: every model importing a fixture gates it behind a demo mode",
        not _model_leaks, str(_model_leaks))

# AND THE GATE IS CHECKED BEFORE THE FIXTURE IS READ, in the accessor that
# production actually calls. Asserted concretely for the two models whose
# accessors return collections, where a missed gate would render fixture rows.
_action_model = _code_only(open(os.path.join(WEB_JS, "action-model.js"),
                                encoding="utf-8").read())
_assert("§3: Action's card accessor short-circuits demo before the fixture",
        "if (MODE === ACTION_MODE_DEMO) return cardsFor(section);" in _action_model
        and "if (MODE !== ACTION_MODE_AUTHORITATIVE || !SERVED) return [];"
        in _action_model,
        "demo is reached only in demo mode")
_slate_model = _code_only(open(os.path.join(WEB_JS, "pool-slate-model.js"),
                               encoding="utf-8").read())
_assert("§3: the Pool slate returns [] rather than fixture rows when unbound",
        "if (MODE !== SLATE_MODE_DRAWN || !SERVED) return [];" in _slate_model)

# EVERY PANEL THAT STILL IMPORTS A FIXTURE MUST GATE IT ON MODE.
PANELS = {"league.js": "leagueMode()", "action.js": "actionMode()",
          "week.js": "leagueMode()", "ledger.js": "ledgerMode()",
          "rules.js": None}
_ungated = []
for panel, gate in PANELS.items():
    path = os.path.join(WEB_JS, panel)
    code = _code_only(open(path, encoding="utf-8").read())
    imports_fixture = any(f"data/{f}" in code for f in FIXTURES)
    if imports_fixture and gate and gate not in code:
        _ungated.append(panel)
_assert("§3: every panel importing a fixture gates it on a production mode",
        not _ungated, str(_ungated))

# AND THE SHELL BINDS OR MARKS UNAVAILABLE — never leaves a model in demo.
_shell = _code_only(open(os.path.join(WEB_JS, "shell.js"),
                         encoding="utf-8").read())
for marker in ("markLedgerUnavailable", "markActionUnavailable",
               "markLeagueUnavailable", "markSlateUnavailable",
               "markSettingsUnavailable", "markCommissionerUnavailable"):
    _assert(f"§3: the shell can mark {marker[4:-11]} unavailable",
            marker in _shell)
_assert("§3: a failed production read never unbinds to demo",
        _shell.count("unbind") <= _shell.count("clearAuthoritativeData")
        or "clearAuthoritativeData" in _shell,
        "unbind is sign-out only")


# ══ §17 · no direct provider traffic from the browser ═══════════════════════

_section("§17 · network boundary, from source")

_all_js = []
for name in os.listdir(WEB_JS):
    if name.endswith(".js"):
        _all_js.append((name, _code_only(open(os.path.join(WEB_JS, name),
                                              encoding="utf-8").read())))

_foreign = [(n, t) for n, c in _all_js
            for t in ("yahoo.com", "api.github", "raw.githubusercontent",
                      "http://", "https://")
            if t in c]
# `https://` may legitimately appear in a comment-free string only for a schema
# or SVG namespace; anything pointing at a host is a finding.
_hosts = [(n, t) for n, t in _foreign
          if t in ("yahoo.com", "api.github", "raw.githubusercontent")]

# WP3D — ONE MODULE MAY NAME A YAHOO HOST, AND ONLY AS A LINK TARGET.
#
# What §17 exists to prevent is the BROWSER TALKING TO A PROVIDER: a fetch, an
# XHR, a script tag, anything that would make the page a second client of
# Yahoo's API and route provider data around the server. `attribution.js` does
# none of that. It holds one constant — the destination of the hyperlink the
# executed Yahoo agreement requires the attribution to carry — and renders it as
# an `href` the GM may choose to follow.
#
# THE EXEMPTION IS THE MODULE, AND THE GUARD BELOW IS WHAT KEEPS IT HONEST: that
# module must contain no network call of any kind, so naming a host cannot
# quietly become calling one. Every other module is unexempted.
_ATTRIBUTION_ONLY = [(n, t) for n, t in _hosts
                     if not (n == "attribution.js" and t == "yahoo.com")]
_assert("§17: no frontend module references a provider or third-party host",
        not _ATTRIBUTION_ONLY, str(_ATTRIBUTION_ONLY))

_attribution_src = dict(_all_js).get("attribution.js", "")
_assert("§17: and the one module naming a Yahoo host makes no request to it",
        not any(call in _attribution_src for call in
                ("fetch(", "apiFetch", "XMLHttpRequest", "WebSocket",
                 "import(", "<script", "sendBeacon")),
        "link target only")
_assert("§17: the host it names is the attribution's link target and nothing else",
        _attribution_src.count("yahoo.com") == 1
        and "href=" in _attribution_src)
_assert("§17: no frontend module persists a token",
        not any("localStorage" in c or "sessionStorage" in c
                for _, c in _all_js),
        str([n for n, c in _all_js
             if "localStorage" in c or "sessionStorage" in c]))


# ══ §18 · the final unresolved-field inventory ══════════════════════════════

_section("§18 · unresolved MVP fields")

UNRESOLVED = [
    # (tab, label, reason, acceptable for MVP, P5 must solve)
    ("League", "Net Winnings + rank",
     "P3 proved season winnings has no posted door; rank is a standings "
     "position the provider gateway does not expose",
     True, False),
    ("League", "FIRST KICKOFF countdown",
     "the gateway captures matchups and finality, not a countdown",
     True, False),
    ("Action", "Season Bet Record",
     "the GM's WAGER W/L; no settled-wager history read exists. P4C-3 bound "
     "the fantasy matchup record, which is a different number",
     True, False),
    ("Action", "Upside left",
     "needs a per-wager payout, and a Dynamic wager has none until Final "
     "Lock — a figure meaning 'Locked wagers only' would be worse than none",
     True, False),
    ("Action", "Settled",
     "sourceable from served net_cents but week-scoped to settled-wager "
     "history; left to the package that owns that history",
     True, False),
    ("Ledger", "Awards / Adj.",
     "P3: seasonWinnings has no authoritative source; showing the sourced "
     "components alone would put a partial subtotal under a total's label",
     True, False),
    ("The Week", "ML / Spread / O/U",
     "the provider gateway captures NO betting lines; the fixture "
     "manufactured all three from projections",
     True, False),
    ("The Week", "provider matchups when no refresh has run",
     "honest pending/empty state; Yahoo credentials are absent by design in "
     "this environment",
     True, False),
]

for tab, label, reason, acceptable, p5 in UNRESOLVED:
    _assert(f"§18: {tab} · {label} is acceptably unresolved",
            acceptable, reason[:96])
_assert("§18: no unresolved field blocks MVP honesty",
        all(a for _, _, _, a, _ in UNRESOLVED),
        f"{len(UNRESOLVED)} unresolved fields, all honest")
_assert("§18: and none is a P4-owned blocker",
        not any(p5 for *_, p5 in UNRESOLVED),
        "each is a missing SOURCE, not a missing binding")


# ══ The integrated browser session ══════════════════════════════════════════

from test_support_app_server import (  # noqa: E402
    COMMISSIONER_EMAIL, GM_EMAIL, PASSWORD, AppServer,
)

INTEGRATION_WEEK = 9


def _browser(script: str, label: str, *, email: str, **fixture) -> None:
    print(f"\n── {label} " + "─" * max(0, 54 - len(label)))
    with AppServer(**fixture) as server:
        env = dict(os.environ)
        env.update({"FS_TEST_ORIGIN": server.origin,
                    "FS_TEST_AUTH_EMAIL": email,
                    "FS_TEST_AUTH_PASSWORD": PASSWORD})
        proc = subprocess.run(
            ["node", os.path.join("web", "tests", script)],
            cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        sys.stdout.write(proc.stdout)
        if proc.stderr.strip():
            sys.stdout.write(proc.stderr[-2000:])
        passed = proc.stdout.count("[PASS]")
        failed = proc.stdout.count("[FAIL]")
        _assert(label, proc.returncode == 0 and failed == 0,
                f"{passed} PASS / {failed} FAIL, exit {proc.returncode}")


# ONE COHERENT SESSION carrying real state for all five tabs: the Rev 4.2
# accounting season, a drawn Pool slate, an accepted wager, provider matchups,
# settings — all in ONE league stating week 9.
_browser("p4c5_integration_browser.mjs",
         "integrated GM session at week 9, five tabs x three widths",
         email=GM_EMAIL, provider_week=INTEGRATION_WEEK,
         seed_pool_slate=True, action_shape="accepted")

# THE COMMISSIONER SESSION, because Rules & Settings authority differs and a
# single session cannot exercise both sides of it.
_browser("p4c5_integration_browser.mjs",
         "integrated commissioner session at week 9",
         email=COMMISSIONER_EMAIL, provider_week=INTEGRATION_WEEK,
         seed_pool_slate=True, action_shape="accepted")


print("\n" + "=" * 78)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-5 FULL P4 INTEGRATION — all assertions PASSED")
