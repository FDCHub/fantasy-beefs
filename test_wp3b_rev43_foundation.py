#!/usr/bin/env python3
"""
test_wp3b_rev43_foundation.py — WP3B · the Rev 4.3 application foundation.

Three halves, all required, in the shape this repository's UI suites use:

  1. STRUCTURAL, in Python. Assertions the browser cannot make for us and that
     must hold in the SOURCE itself — that the frontend contains no economic
     arithmetic, that the readability scale exists as reusable tokens rather
     than per-card patches, that the Rev 4.2 stylesheets were not rewritten, and
     that the governing specification files are untouched.

  2. BEHAVIOURAL, in Node. `web/tests/wp3b_component_tests.mjs` executes the
     shipped ES modules directly. A Python reimplementation of the standings
     selection or the freeze rule could agree with itself while disagreeing with
     what the app draws.

  3. MEASURED, in headless Chrome. `web/tests/wp3b_browser.mjs` drives the real
     application at four viewports. Whether five labels fit a bar, whether a
     44px target is really 44px after the cascade, and whether the gear really
     reaches Rules & Settings are not source questions.

WHAT THIS SUITE IS GUARDING AGAINST. Not a wrong number — WP3B computes almost
nothing. The risks are: a second economic engine appearing in JavaScript; the
locked navigation drifting; a standings table ranked on Wallet; a commissioner
surface offered to a member; and an activation reachable by accident. Each has
its own section below.

USAGE:
    python test_wp3b_rev43_foundation.py
"""

from __future__ import annotations

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

# The shell asks who is acting before it draws anything, so the browser tier
# needs a real application and a real session. Same harness the Sprint 7 suites
# use; a no-op when this file is run through the full certification.
from test_support_s7_harness import ensure_authenticated_app  # noqa: E402

ensure_authenticated_app()

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


def _read(*parts: str) -> str:
    with open(os.path.join(WEB, *parts), encoding="utf-8") as fh:
        return fh.read()


def _read_root(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _strip_comments(source: str) -> str:
    """Remove comments so source assertions test what the app DOES.

    A comment explaining why a formula is absent must not itself trip the check
    that the formula is absent.
    """
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.DOTALL)
    source = re.sub(r"^\s*//.*$", " ", source, flags=re.MULTILINE)
    return source


NAV_JS = _read("js", "nav.js")
STANDINGS_JS = _read("js", "standings.js")
STANDINGS_MODEL_JS = _read("js", "standings-model.js")
ECONOMY_JS = _read("js", "economy.js")
ECONOMY_MODEL_JS = _read("js", "economy-model.js")
ECONOMY_COMMAND_JS = _read("js", "economy-command.js")
MENU_JS = _read("js", "menu.js")
SHELL_JS = _read("js", "shell.js")
TOKENS_CSS = _read("styles", "tokens.css")
REV43_CSS = _read("styles", "rev43.css")
INDEX_HTML = _read("index.html")

WP3B_JS = {
    "standings.js": STANDINGS_JS,
    "standings-model.js": STANDINGS_MODEL_JS,
    "economy.js": ECONOMY_JS,
    "economy-model.js": ECONOMY_MODEL_JS,
    "economy-command.js": ECONOMY_COMMAND_JS,
    "menu.js": MENU_JS,
}


# ── 1 · The frontend authority boundary — Rev 4.3 §28, WP3B §34 ──────────────

_section("1 · No second economic engine exists in JavaScript")

def _code_only(source: str) -> str:
    """Source with comments and string literals removed.

    Prose may legitimately contain a `*` or a `/`, and a CSS class or a URL
    path is not arithmetic — scanning them would make this check meaningless in
    both directions.
    """
    return re.sub(r"'[^'\n]*'|\"[^\"\n]*\"|`[^`]*`", "''",
                  _strip_comments(source)).replace("*/", "")


# THE STRONGEST FORM OF THIS CLAIM IS STRUCTURAL, and it is checkable: every
# module WP3B adds except one contains no arithmetic at all. Each derived figure
# is read from the served body. A reader can verify the claim by searching the
# files; this asserts it so it stays true.
for name, source in WP3B_JS.items():
    if name == "economy.js":
        continue
    _assert(f"{name}: contains no multiplication", "*" not in _code_only(source))
    _assert(f"{name}: contains no division",
            not re.search(r"(?<![/*])/(?![/*])", _code_only(source)))

# `economy.js` HAS EXACTLY TWO OPERATIONS, AND BOTH ARE THE DOLLARS/CENTS
# BOUNDARY. They are named individually so a third could not appear unnoticed:
# one turns a typed whole-Credit figure into the exact cents the API takes, the
# other turns served cents back into a number for an input's value. Neither is
# economics — `credits.js` owns display rounding and the server owns every
# derived figure.
_econ_code = _code_only(ECONOMY_JS)
_assert("economy.js multiplies exactly once, at the input boundary",
        _econ_code.count("*") == 1 and "Math.round(dollars * 100)" in ECONOMY_JS,
        f"{_econ_code.count('*')} occurrences")
_assert("economy.js divides exactly once, at the output boundary",
        len(re.findall(r"(?<![/*])/(?![/*])", _econ_code)) == 1
        and "Math.round(cents / 100)" in ECONOMY_JS,
        f"{len(re.findall(r'(?<![/*])/(?![/*])', _econ_code))} occurrences")

_assert("no WP3B module derives an allocation, reserve or settle figure",
        not re.search(r"(allocation|reserve|settle|payout)\s*=\s*[^;]*[*/]",
                      " ".join(_strip_comments(s) for s in WP3B_JS.values()),
                      re.I))
_assert("the standings model re-sorts nothing — the server's order is drawn",
        ".sort(" not in _strip_comments(STANDINGS_MODEL_JS)
        and ".sort(" not in _strip_comments(STANDINGS_JS))
_assert("no WP3B module imports a protocol module",
        not re.search(r"from ['\"](\.\./)+(economy|ledger|beefs|betting|wallet|api)/",
                      " ".join(WP3B_JS.values())))
_assert("every network call goes through session.js, the app's one door",
        all("fetch(" not in _strip_comments(s).replace("apiFetch(", "")
            for s in WP3B_JS.values()))


_section("2 · Standings never ranks on Wallet — Rev 4.3 §7.1")

_assert("no standings module mentions a wallet",
        not re.search(r"wallet", STANDINGS_JS + STANDINGS_MODEL_JS, re.I))
_assert("the ranking figure is read from the served row, never recomputed",
        "return Number(row.net_cents)" in STANDINGS_MODEL_JS)
_assert("the rank itself is the server's, not an index",
        "Number(row.rank)" in STANDINGS_MODEL_JS
        and not re.search(r"rank:\s*(i|index)\s*\+\s*1", STANDINGS_MODEL_JS))

READ_MODEL = _read_root("reports", "standings_read_model.py")
_assert("the backend read model exists",
        os.path.isfile(os.path.join(ROOT, "reports", "standings_read_model.py")))
_assert("it derives Overall from the two competitive nets, not from a balance",
        "self.versus_net_cents + self.pool_net_cents" in READ_MODEL)
_assert("it composes the certified position read rather than re-attributing",
        "league_positions(db, league_id=league_id)" in READ_MODEL)
_assert("it sums BOTH spend accounts, so min-funded spend is not missed",
        "account = :wallet OR account LIKE :min_pattern" in READ_MODEL)
_assert("its door sets are imported from the modules that own the doors",
        "from betting.pool_funding import" in READ_MODEL
        and "from economy.challenge_funding import" in READ_MODEL
        and "from economy.dynamic_challenge import" in READ_MODEL)
_assert("no noncompetitive door is in either competitive set",
        not re.search(r"(VERSUS_DOORS|POOL_DOORS)[^)]*"
                      r"(season_allocation|approved_bab_topoff|weekly_minimum|skunk)",
                      READ_MODEL, re.S))
_assert("the row type carries no accounting field",
        not re.search(r"^\s+(wallet|available|current_settle|obligations|"
                      r"season_advance|receivable)_?\w*:", READ_MODEL, re.M))


_section("3 · The readability foundation is reusable, not per-card patches")

for token, lo, hi in (("--fs-r43-page-title", 22, 24),
                      ("--fs-r43-section", 18, 20),
                      ("--fs-r43-card", 16, 17),
                      ("--fs-r43-card-secondary", 14, 15),
                      ("--fs-r43-meta", 12, 13),
                      ("--fs-r43-strip-label", 13, 14),
                      ("--fs-r43-strip-value", 22, 24),
                      ("--fs-r43-nav-label", 11, 12)):
    m = re.search(rf"{re.escape(token)}:\s*(\d+)px", TOKENS_CSS)
    _assert(f"{token} is declared inside {lo}–{hi}px",
            m is not None and lo <= int(m.group(1)) <= hi,
            m.group(1) + "px" if m else "absent")

_assert("the 44px touch minimum is a token, not a literal per rule",
        re.search(r"--fs-r43-touch:\s*44px", TOKENS_CSS) is not None)
_assert("the foundation publishes shared helper classes",
        all(c in REV43_CSS for c in (".fs-r43-page-title", ".fs-r43-section",
                                     ".fs-r43-card", ".fs-r43-secondary",
                                     ".fs-r43-meta", ".fs-r43-touch")))
_assert("secondary text contrast is raised rather than the palette redesigned",
        "--fs-r43-secondary:" in TOKENS_CSS and "--fs-r43-tertiary:" in TOKENS_CSS)

# THE REV 4.2 PALETTE IS UNTOUCHED. WP3B §9 says not to redesign it, and the
# check is exact: every POR colour token still holds its locked value.
for token, value in (("--bg", "#0c0a07"), ("--mast", "#12100c"),
                     ("--card", "#161309"), ("--gold", "#c9a24a"),
                     ("--bone", "#e8e2d2"), ("--green2", "#c0dd97"),
                     ("--red", "#f09595"), ("--amber", "#ef9f27")):
    _assert(f"the locked palette token {token} is unchanged",
            re.search(rf"{re.escape(token)}:\s*{re.escape(value)}", TOKENS_CSS)
            is not None, value)

_assert("the Rev 4.2 type tokens are left in place for the WP3C surfaces",
        "--fs-size-body:" in TOKENS_CSS and "--fs-size-title:" in TOKENS_CSS)
_assert("the Rev 4.3 sheet loads last, so it layers over Rev 4.2 rather than "
        "rewriting it",
        INDEX_HTML.index("rev43.css") > INDEX_HTML.index("components.css")
        and INDEX_HTML.index("rev43.css") > INDEX_HTML.index("rules.css"))


_section("4 · Accessibility hygiene — WP3B §10")

# READ OFF THE META TAG ITSELF. Scanning the whole file would trip on the
# comment beside it, which names the restriction it explains removing.
_VIEWPORT_META = re.search(r'<meta name="viewport" content="([^"]*)"', INDEX_HTML)
_assert("the document declares a viewport", _VIEWPORT_META is not None)
_VIEWPORT = _VIEWPORT_META.group(1) if _VIEWPORT_META else ""
_assert("pinch zoom is not disabled",
        "user-scalable=no" not in _VIEWPORT, _VIEWPORT)
_assert("the maximum scale is not capped",
        "maximum-scale" not in _VIEWPORT, _VIEWPORT)
_assert("viewport-fit=cover is retained for the safe areas",
        "viewport-fit=cover" in _VIEWPORT, _VIEWPORT)
_assert("the safe-area insets are still applied to the navigation",
        "--fs-safe-bottom" in REV43_CSS or "--fs-safe-bottom" in _read("styles", "shell.css"))
_assert("the navigation is never taken out of flow",
        not re.search(r"\.fs-tabbar\s*\{[^}]*position:\s*(fixed|absolute|sticky)",
                      REV43_CSS, re.S))


_section("5 · Locked language and product identity — Rev 4.3 §2")

DEMO_JS = _strip_comments(_read("js", "demo-state.js"))
_assert("the primary product tagline is exact",
        "'Real odds. Fantasy stakes. More ways to win.'" in DEMO_JS)
_assert("the masthead carries no revision field", "revision" not in DEMO_JS)
_assert("the masthead carries no author field", "author" not in DEMO_JS)
_assert("the shell renders no revision or byline",
        not re.search(r"MASTHEAD\.(revision|author)", SHELL_JS))

ALL_JS = "\n".join(
    open(os.path.join(dirpath, f), encoding="utf-8").read()
    for dirpath, _dirs, files in os.walk(os.path.join(WEB, "js"))
    for f in files if f.endswith(".js"))
RENDERED = _strip_comments(ALL_JS)
_assert("no user-visible copy cites a UI revision",
        not re.search(r"['\"][^'\"]*Rev\s*4\.\d", RENDERED),
        (re.search(r"['\"][^'\"]{0,40}Rev\s*4\.\d[^'\"]{0,20}", RENDERED)
         or [""])[0])
# SEAM REGISTERS ARE EXCLUDED, AND ONLY THEY ARE. `LEDGER_READ_SEAM` and its
# siblings deliberately name the backend computation behind a surface that is
# not yet bound; they are developer-facing constants that nothing renders, and
# the S8-P3 suite asserts their contents by name. The browser tier makes the
# stronger version of this claim against what is actually DRAWN on every
# primary tab — this is the source-level backstop for everything else.
_SEAMLESS = re.sub(r"^\s*(computation|serverAuthority|readModel|endpoint|"
                   r"commissionerSurface):.*$", " ", RENDERED, flags=re.M)
_assert("no user-visible copy cites a python module or a web/js path",
        not re.search(r"['\"][^'\"]*(\.py\b|web/js/)", _SEAMLESS),
        (re.search(r"['\"][^'\"]{0,60}(\.py\b|web/js/)", _SEAMLESS) or [""])[0])
_assert("no user-visible copy carries the FantasyBeefs product name",
        not re.search(r"FantasyBeefs", RENDERED, re.I))
_assert("no user-visible copy carries a FINAL POR marker",
        not re.search(r"FINAL POR", RENDERED, re.I))


_section("6 · The commissioner boundary — WP3B §17")

_assert("the economy capability defaults to false",
        re.search(r"let CAPABLE = false", ECONOMY_MODEL_JS) is not None)
_assert("editing requires BOTH capability and an unfrozen season",
        "economyCapability() && !isFrozen()" in ECONOMY_MODEL_JS)
_assert("activation additionally requires a derivable allocation",
        "isEditable() && perPlayerAllocationCents() !== null" in ECONOMY_MODEL_JS)
_assert("the capability is set from the server's own commissioner answer",
        "setEconomyCapability(holdsCommission)" in SHELL_JS)
_assert("the economy read is asked for only when the server says commissioner",
        re.search(r"if \(holdsCommission\) \{\s*try \{\s*bindEconomy", SHELL_JS)
        is not None)
_assert("the menu offers commissioner entries only when reachable",
        "if (economyReachable())" in MENU_JS)
_assert("sign-out drops the capability with the session",
        "unbindEconomy()" in SHELL_JS and "setEconomyHook(null)" in SHELL_JS)
_assert("sign-out drops the standings with the session",
        "unbindStandings()" in SHELL_JS)


_section("7 · Activation cannot happen by accident — Rev 4.3 §16.4")

_assert("the setup sheet's activate control only PUSHES a level",
        re.search(r"activate\.addEventListener\('click', \(\) => \{ api\.push",
                  ECONOMY_JS) is not None)
_assert("only the confirmation sheet calls activateSeason",
        ECONOMY_JS.count("activateSeason(") == 1
        and "activateSeason(HOOK.leagueId)" in ECONOMY_JS)
_assert("the save path cannot reach activation",
        not re.search(r"saveEconomyConfig[\s\S]{0,400}?activateSeason", ECONOMY_JS))
_assert("activation re-reads the configuration rather than assuming the freeze",
        "onActivated" in ECONOMY_JS and "readEconomyConfig(leagueId)" in SHELL_JS)
_assert("nothing is clamped before it is sent — the server owns every bound",
        not re.search(r"Math\.(min|max)\(", ECONOMY_JS + ECONOMY_COMMAND_JS))


_section("8 · Rules & Settings survives losing its tab — WP3B §20")

_assert("it is a secondary destination with a panel",
        "SECONDARY_DESTINATIONS" in NAV_JS and "panel-rules" in NAV_JS)
_assert("panel hosts are built for every destination, not only the five",
        "ALL_DESTINATIONS.map" in SHELL_JS)
_assert("panels are BUILT for every destination too",
        "ALL_DESTINATIONS.forEach" in SHELL_JS)
_assert("the transition covers secondary destinations, so tabs un-light",
        "ALL_DESTINATIONS.map" in NAV_JS)
_assert("the rules panel is still built by its own module, unrefactored",
        "buildRulesPanel()" in SHELL_JS and "bindRules(rulesPanel" in SHELL_JS)
_assert("the menu routes to the existing destination rather than rebuilding it",
        "data-menu-destination" in MENU_JS and "buildRulesPanel" not in MENU_JS)


_section("9 · The governing artifacts are untouched — WP3B §27")

for path in ("spec/FantasyStakes_UIUX_Prototype_Rev4_2_FINAL_POR.html",
             "spec/FantasyStakes_UIUX_Rev4_3_FINAL_POR.md",
             "docs/index.html"):
    proc = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", path],
                          cwd=ROOT, capture_output=True)
    _assert(f"{path} is unmodified", proc.returncode == 0)


# ── Node tiers ───────────────────────────────────────────────────────────────

def _run_node(script: str, label: str) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    print(f"\n{label}")
    proc = subprocess.run([node, os.path.join(WEB, "tests", script)],
                          cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip())
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_run_node("wp3b_component_tests.mjs", "WP3B component suite (Node)")
_run_node("wp3b_browser.mjs", "WP3B browser suite (headless Chrome)")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 66)
if _failures:
    print(f"WP3B REV 4.3 FOUNDATION — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3B REV 4.3 FOUNDATION — all assertions PASSED")
