#!/usr/bin/env python3
"""
test_uirecon_wave2.py — UIRECON Wave 2 · shell, Standings, Play and Account.

Run:  python test_uirecon_wave2.py

WHAT WAVE 2 DID, AND THEREFORE WHAT THIS CERTIFIES.

Wave 2 is the surface pass that sits on Wave 1's primitives. It changed no
command, no read model, no route and no arithmetic; every edit is markup,
copy or CSS.

  1. THE HEADER. One account cluster in the locked order — DEMO badge, account
     control, settings gear. The persistent `Sign out` button is gone from the
     chrome and lives in the sheet the account control opens. The gear says
     Settings rather than Menu. The wordmark is a clear step above every other
     type in the shell.

  2. STANDINGS. The championship explanation keeps its words and loses its
     card: it is supporting body text under CHAMPIONSHIP CHASE · WEEK n, and
     the first table stopped repeating the tab's own title.

  3. PLAY. Net Winnings means net winnings — the dead `netWinningsRank` fixture
     is deleted, so there is no longer anything for a future edit to put back.

  4. ACCOUNT. Current Settle is section 4, built by the same `ledgerSection()`
     as the three sections that explain into it.

WHY THE STRUCTURAL TIER EXISTS ALONGSIDE THE BROWSER ONE. A browser can prove
four sections currently LOOK identical; it cannot prove they are one
construction rather than four that happen to agree today. The source can, and
that difference is the whole deliverable — so the rules are asserted here and
the rendered result is asserted in `uirecon_wave2_browser.mjs`.

WHAT IS DELIBERATELY NOT ASSERTED. Absolute pixel sizes for the wordmark or the
masthead. The wordmark's size is bounded by the lockup width, which is bounded
by the provider chip's untruncated width — a relationship, not a number. What
is pinned is that relationship, and the certified ceilings the shell already
had.
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

from test_support_s7_harness import ensure_authenticated_app  # noqa: E402

ensure_authenticated_app(seed_pool_slate=True, action_shape="full")

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
    with open(os.path.join(WEB, *parts), encoding="utf-8") as handle:
        return handle.read()


SHELL_JS = _read("js", "shell.js")
AUTH_JS = _read("js", "auth-view.js")
MENU_JS = _read("js", "menu.js")
LEDGER_JS = _read("js", "ledger.js")
LEAGUE_JS = _read("js", "league.js")
DEMO_JS = _read("js", "demo-state.js")
STANDINGS_MODEL_JS = _read("js", "standings-model.js")
STANDINGS_JS = _read("js", "standings.js")

TOKENS = _read("styles", "tokens.css")
REV43 = _read("styles", "rev43.css")
LEDGER_CSS = _read("styles", "ledger.css")
GAMEPLAY_CSS = _read("styles", "gameplay.css")
CHAMPIONSHIP_CSS = _read("styles", "championship.css")


def _rule(css: str, selector: str) -> str:
    pattern = re.compile(r"(?:^|\}|\*/)\s*([^{}@/]*?)\s*\{([^{}]*)\}",
                         re.MULTILINE | re.DOTALL)
    return "\n".join(
        m.group(2) for m in pattern.finditer(css)
        if any(p.strip() == selector for p in m.group(1).split(","))
    )


def _strip_comments(text: str) -> str:
    """Source with comments removed.

    Wave 2's comments name what they retired — the persistent Sign out, the
    `Menu` label, the bespoke settle card — so a reader who finds a rule gone
    knows what used to be there. An absence check has to look at code, or the
    explanation becomes the thing that fails the assertion it explains.
    """
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", without_block, flags=re.MULTILINE)


# ── 1 · The header account cluster ───────────────────────────────────────────

_section("1 · The header is one account cluster, and Sign Out is not in it")

_shell_code = _strip_comments(SHELL_JS)
_auth_code = _strip_comments(AUTH_JS)

_assert("the masthead builds one account cluster",
        "fs-mast__cluster" in _shell_code)
# THE ORDER IS THE POR'S, and it is asserted on the SOURCE because DOM order is
# what the tab sequence and a screen reader follow — a cluster that only looks
# right is not one.
_cluster = _shell_code.split("fs-mast__cluster")[1].split("</div>")[0] \
    if "fs-mast__cluster" in _shell_code else ""
_assert("the chip comes before the account control",
        _shell_code.index("sourceChip()") < _shell_code.index("buildIdentityBlock()"))
_assert("and the account control before the gear",
        _shell_code.index("buildIdentityBlock()") < _shell_code.index("menuButton()"))
_assert("the two-row meta layout is retired",
        "fs-mast__metarow" not in _shell_code
        and "fs-mast__metarow" not in _strip_comments(REV43))

_assert("the account control is a real button with a popup role",
        'class="fs-acct"' in _auth_code
        and 'id="fs-account"' in _auth_code
        and 'aria-haspopup="dialog"' in _auth_code)
_assert("it names the acting GM",
        "fs-ident__who" in _auth_code and "identity.team_name" in _auth_code)
_assert("the commissioner label survives inside it",
        "fs-ident__badge" in _auth_code)

# SIGN OUT MOVED; IT DID NOT DISAPPEAR. Both halves are asserted, because a
# reconciliation that lost the control would pass a test that only checked the
# masthead.
_assert("no persistent Sign Out is built into the masthead",
        "fs-ident__out" not in _auth_code)
_assert("Sign out lives in the account sheet",
        "accountSheet" in _auth_code
        and 'id="fs-signout"' in _auth_code.split("accountSheet")[1])
_assert("and still calls the same logout",
        "await logout();" in _auth_code)
_assert("the account control opens the shared sheet host",
        "api.openSheet" in _auth_code)

# NO SECOND DOOR TO SETTINGS. The gear owns Rules, League Settings, the
# commissioner surface and the economy configuration; the account sheet answers
# "who am I" and stops.
_sheet_src = _auth_code.split("export function accountSheet")[1].split(
    "export function bindAccountSheet")[0]
_assert("the account sheet does not duplicate Settings",
        not re.search(r"Rules|League Settings|Commissioner controls|Economy",
                      _sheet_src))

_assert("the gear means Settings",
        "export const MENU_TITLE = 'Settings';" in MENU_JS
        and 'aria-label="Settings"' in MENU_JS)
_assert("and it still routes to the same destinations",
        "menuEntries" in MENU_JS and "data-menu-destination" in MENU_JS)

# THE WORDMARK OUTRANKS THE PAGE TITLE, as a relationship between tokens rather
# than as a number.
_word = int(re.search(r"--fs-size-word:\s*(\d+)px", TOKENS).group(1))
_title = int(re.search(r"--fs-r43-page-title:\s*(\d+)px", TOKENS).group(1))
_assert("the wordmark is a clear step above the page title",
        _word > _title, f"{_word}px vs {_title}px")
_assert("and larger than it was before Wave 2", _word > 23, f"{_word}px")

# The cluster's shrink order is declared rather than left to the browser — the
# defect that cost the gear its 44px target when the cluster gained a third item.
_assert("the gear never shrinks",
        "flex: 0 0 auto" in _rule(REV43, ".fs-mast__cluster-end > .fs-gear"))
_assert("the account control and the gear never split apart",
        "flex-wrap: nowrap" in _rule(REV43, ".fs-mast__cluster-end"))
_assert("the meta column is capped to what its widest line needs",
        "max-width: 156px" in _rule(REV43, ".fs-mast__meta"))


# ── 2 · Standings hierarchy ──────────────────────────────────────────────────

_section("2 · The championship explanation is supporting text, not a card")

_ex = _rule(CHAMPIONSHIP_CSS, ".fs-st__explainer")
_assert("the explainer rule exists", _ex.strip() != "")
_assert("it has no card ground", "background" not in _ex)
_assert("no card edge", "border" not in _ex)
_assert("no card radius", "radius" not in _ex)
_assert("and no card padding", "padding" not in _ex)
_assert("it reads as muted secondary copy",
        "var(--fs-c-text-muted)" in _ex)
_assert("at the canonical fine step", "var(--fs-c-size-fine)" in _ex)
_assert("aligned to the same gutter as the tab header",
        "var(--fs-gutter)" in _ex)

# The explanation itself is kept, and kept in place: subheading, then this,
# then the standings.
_assert("the CHAMPIONSHIP CHASE subheading is kept",
        "'CHAMPIONSHIP CHASE'" in STANDINGS_JS)
_assert("the championship explanation is kept",
        "championshipExplainer" in STANDINGS_JS
        and "Championship Score is your net winnings" in STANDINGS_JS)
_assert("it is rendered between the subheading and the standings",
        STANDINGS_JS.index("championshipSubheading()")
        < STANDINGS_JS.index("championshipExplainer()")
        < STANDINGS_JS.index("fs-st__scroll"))
_assert("the championship is not named twice",
        "heading: 'OVERALL'" in STANDINGS_MODEL_JS
        and "FANTASYSTAKES CHAMPIONSHIP" not in STANDINGS_MODEL_JS)
_assert("and the tab still carries the locked title",
        "STANDINGS_TITLE = 'FANTASYSTAKES CHAMPIONSHIP'" in STANDINGS_JS)


# ── 3 · Play strip semantics and section spacing ─────────────────────────────

_section("3 · Net Winnings means net winnings, and the two sections match")

# THE FIXTURE IS GONE, WHICH IS THE POINT. Rev 4.3 §8.3 removed the rank from
# the cell and left the constant behind, so the next edit had a ready-made way
# to put it back. Deleting it makes the removal structural.
_assert("the illustrative rank fixture is deleted",
        "netWinningsRank" not in _strip_comments(DEMO_JS))
_assert("and net winnings itself is untouched",
        "netWinningsCents" in DEMO_JS)
_league_code = _strip_comments(LEAGUE_JS)
_strip_block = _league_code.split("id: 'fs-strip-league'")[1].split("});")[0]
_assert("no Play strip cell carries a context",
        "context:" not in _strip_block)
_assert("the strip is still four cells",
        _strip_block.count("{ label:") == 4, str(_strip_block.count("{ label:")))

# ONE GAP, ONE DECLARATION — the Wave 1 primitive, which Wave 2 applies rather
# than re-specifies. Both of Play's zones take it from the same rule.
_heading_rules = "\n".join(
    m.group(0) for m in re.finditer(r"[^{}]*\.fs-heading\s*\{[^{}]*\}", GAMEPLAY_CSS)
    if "margin:" in m.group(0))
_assert("the section gap is the canonical token",
        "var(--fs-c-gap-heading)" in _heading_rules)
_assert("and both Play zones read the same rule",
        ".fs-zone .fs-heading" in _heading_rules
        and "#panel-league .fs-heading" in _heading_rules)
_assert("the gap is more than the pre-reconciliation zero",
        "margin: var(--fs-space-1) var(--fs-space-1) 0" not in GAMEPLAY_CSS)


# ── 4 · Account section 4 ────────────────────────────────────────────────────

_section("4 · Current Settle is section 4, built like its three peers")

_ledger_code = _strip_comments(LEDGER_JS)

_assert("Current Settle renders through ledgerSection()",
        "currentSettleSection" in _ledger_code
        and "currentSettleCard" not in _ledger_code)
_settle_src = _ledger_code.split("function currentSettleSection")[1]
_assert("it is numbered 4", "number: '4'" in _settle_src)
_assert("and titled CURRENT SETTLE", "title: 'CURRENT SETTLE'" in _settle_src)
# §14.2 — the figure the tab exists to derive may not require expansion. Same
# affordance as its siblings; different starting state, for the reason the POR
# gives.
_assert("it opens by default, so the figure needs no tap",
        "open: true" in _settle_src)
_assert("the panel assembles four sections in order",
        re.search(r"advancesSection\(r\)\s*\+\s*\n?\s*wageringSection\(r\)\s*\+"
                  r"\s*\n?\s*adjustmentsSection\(r\)\s*\+\s*\n?\s*"
                  r"currentSettleSection\(r\)", _ledger_code) is not None)

# THE BESPOKE CARD IS RETIRED. Its absence is the deliverable: a `.fs-settle`
# rule that still drew a card would mean the block had been reparented without
# being reconciled.
_assert("the bespoke card treatment is gone",
        _rule(LEDGER_CSS, ".fs-settle").strip() == "")
_assert("and its bespoke heading with it",
        _rule(LEDGER_CSS, ".fs-settle__head").strip() == ""
        and _rule(GAMEPLAY_CSS, ".fs-settle__head").strip() == "")
_assert("the four sections share one spacing rule",
        ".fs-lsec + .fs-lsec" in LEDGER_CSS
        and ".fs-lscroll > .fs-settle" not in _strip_comments(LEDGER_CSS))

# EVERY FIGURE SURVIVED. This is presentation structure, not accounting.
_assert("the three input rows are unchanged",
        "Total Virtual Stakes" in _settle_src
        and "Wagering Position" in _settle_src
        and "Net Adjustments + Winnings" in _settle_src)
_assert("the result row and its exact cents survive",
        "fs-settle__total" in _settle_src
        and "data-exact-cents" in _settle_src)
_assert("the locating id survives", 'id="fs-current-settle"' in _settle_src)
_assert("the trust anchor stays at the foot, once",
        "LEDGER_TRUST_ANCHOR" in _settle_src
        and _ledger_code.count("LEDGER_TRUST_ANCHOR") == 2)
_assert("no arithmetic moved into the view",
        "currentSettleCents" in _settle_src
        and not re.search(r"currentSettleCents\s*[-+*/]", _settle_src))


# ── 5 · Nothing outside Wave 2's scope moved ─────────────────────────────────

_section("5 · Wave 2 changed presentation only")

# EACH MODULE STILL BINDS THE WAY IT ALREADY BOUND. Named per module rather
# than by a generic search for `data-`, which auth-view.js has never used — it
# binds by element id, and a check that did not know that would have been
# asserting nothing and then failing for the wrong reason.
_assert("Play still binds its markets and pools by data attribute",
        "data-market" in LEAGUE_JS and "data-pool" in LEAGUE_JS)
_assert("Account still binds its disclosures by data attribute",
        "data-disclosure" in LEDGER_JS and "data-lsec-toggle" in LEDGER_JS)
_assert("the shell still binds panels by destination",
        "data-destination" in SHELL_JS)
_assert("the account control and Sign out still bind by id",
        "querySelector('#fs-signout')" in AUTH_JS
        and "querySelector('#fs-account')" in AUTH_JS)

_assert("the composer market bindings are untouched",
        "data-composer-market" in _read("js", "composer.js")
        and "data-composer-mode" in _read("js", "composer.js"))
_assert("the Pool claim command is untouched",
        "submitPoolClaim" in SHELL_JS)
_assert("the Matchup Preview is untouched",
        "previewSheet" in _read("js", "preview.js"))
_assert("the ledger model is untouched",
        "currentSettleCents" in _read("js", "ledger-model.js"))
_assert("the standings read model still serves three tables",
        STANDINGS_MODEL_JS.count("key: '") == 3)


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


_run_node("uirecon_wave2_browser.mjs",
          "UIRECON Wave 2 browser suite (headless Chrome)")
_run_node("package2_component_tests.mjs", "Play + Status component suite")
_run_node("package3_component_tests.mjs", "Wrap Up + Account component suite")
_run_node("wp3b_component_tests.mjs", "Rev 4.3 shell component suite")
_run_node("wp3c_component_tests.mjs", "Rev 4.3 gameplay component suite")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON WAVE 2 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON WAVE 2 — all assertions PASSED")
