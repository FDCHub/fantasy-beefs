#!/usr/bin/env python3
"""
test_uirecon_wave1.py — UIRECON Wave 1 · shared primitives and locked terminology.

Run:  python test_uirecon_wave1.py

WHAT WAVE 1 DID, AND THEREFORE WHAT THIS CERTIFIES.

Wave 1 is the foundation pass of the app's reconciliation against the locked
marketing POR. It changed no behaviour, no command, no read model and no route.
It did four things, and each of them is a claim this suite has to keep true:

  1. PUBLIC TERMINOLOGY. No public-facing "Versus" survives on any app surface;
     "FantasyStakes Matchups" and "FantasyStakes Prop Pools" are the locked
     first references. Internal module names, state constants, API fields and
     protocol identifiers deliberately keep `versus` and are asserted to.

  2. THE METRIC CELL. One construction for every four-cell strip: equal cells,
     a centred one-line label in the top row, and a value truly centred on both
     axes in what is left.

  3. THE CHOICE CELL. One construction for every peer selectable cell. The Play
     card's market cells and the composer's market, terms and over/under cells
     were three geometries for one control; they are one now.

  4. THE SECTION-HEADING GAP. One token, one declaration, every consumer —
     replacing a bottom margin that had been set to zero on Play, Status and
     Wrap Up alike.

  5. THE CANONICAL TOKEN LAYER. `--fs-c-*` aliases so a shared primitive names
     ONE answer instead of choosing between the Rev 4.2 and Rev 4.3 scales.

AND IT IS HELD TO THE LOCKED APP-SHELL VIEWPORT POR.

Every one of those primitives is a plausible way to break the shell: a strip
whose labels wrap is a taller strip, a choice cell that will not shrink is a
wider row, and a heading gap is height taken from the panel below it. The
addendum fixes what the shell may and may not do, and each clause is certified
here rather than assumed:

  - no tab-level horizontal scrolling
  - no new tab-level vertical overflow
  - the bottom navigation stays visible AND hit-testable in the normal shell
  - a carousel scrolls inside its own bounded viewport and that overflow does
    not propagate to the tab or the page
  - a sheet may scroll internally, and only internally
  - the mobile shell at 375x667 and 390x844 is preserved

Measured on all five primary tabs at every viewport, not on the page as a whole:
a primitive that fits on Play and overflows on Wrap Up has still broken it.

THREE TIERS, AND THEY MAKE DIFFERENT KINDS OF CLAIM.

  STRUCTURAL (here, Python).   That the source says what it should: the tokens
      exist and alias to the right targets, the primitives are written once
      rather than per screen, and the retired per-screen overrides are gone.
      A browser cannot tell "one shared rule" from "four identical copies"; the
      source can, and that distinction IS the deliverable.

  BEHAVIOURAL (Node component). That the panels still build and still say what
      the POR fixed. Delegated to the existing package suites, which were
      updated in the same commit and are run from here.

  MEASURED (headless Chrome).  That the cascade, the media queries and the grid
      actually resolve to equal cells, identical peers and one gap — at
      375x667, 390x844, 768 and 1024, plus the 320x568 that set the label
      budget.

WHAT THIS SUITE DELIBERATELY DOES NOT ASSERT. Absolute pixel values for cell
heights or card heights. Wave 1's own measurements are recorded in the source
comments where they explain a decision; pinning them here would make every
later wave's legitimate layout change look like a regression. What is pinned is
the RELATIONSHIP between peers, which is the thing that must not drift.
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
# needs a real application and a real session. A no-op when an origin is
# already supplied.
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


TOKENS = _read("styles", "tokens.css")
COMPONENTS = _read("styles", "components.css")
WAGER = _read("styles", "wager.css")
GAMEPLAY = _read("styles", "gameplay.css")
TABS = _read("styles", "tabs.css")
REV43 = _read("styles", "rev43.css")


def _rule(css: str, selector: str) -> str:
    """Every declaration block whose selector list contains `selector` as a
    whole selector, concatenated. All matching blocks, not the first."""
    pattern = re.compile(r"(?:^|\}|\*/)\s*([^{}@/]*?)\s*\{([^{}]*)\}",
                         re.MULTILINE | re.DOTALL)
    blocks = [
        m.group(2) for m in pattern.finditer(css)
        if any(part.strip() == selector for part in m.group(1).split(","))
    ]
    return "\n".join(blocks)


def _without_comments(css: str) -> str:
    """The sheet with its comments removed.

    Several Wave 1 comments name the value they RETIRED — `min-height: 34px`,
    the hard-coded 22px strip value — because a reader who finds the rule gone
    deserves to know what used to be there and why. A check for the absence of
    a declaration has to look at declarations, or the explanation becomes the
    thing that fails the assertion it explains.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _selector_lists(css: str, selector: str) -> list[list[str]]:
    """The selector LIST of every block that styles `selector`.

    `_rule` concatenates declarations and so cannot tell a control that is
    styled by a rule of its own from one styled by a rule it SHARES — which is
    the entire distinction Wave 1's choice cell turns on. A shared primitive is
    a block whose selector list names both consumers; a per-screen override is a
    block that names one. This returns the lists so that difference is testable.
    """
    pattern = re.compile(r"(?:^|\}|\*/)\s*([^{}@/]*?)\s*\{[^{}]*\}",
                         re.MULTILINE | re.DOTALL)
    out: list[list[str]] = []
    for match in pattern.finditer(css):
        parts = [p.strip() for p in match.group(1).split(",") if p.strip()]
        if selector in parts:
            out.append(parts)
    return out


def _alias(name: str, target: str) -> bool:
    """Whether tokens.css defines `name` as exactly `var(target)`."""
    return re.search(
        rf"{re.escape(name)}\s*:\s*var\(\s*{re.escape(target)}\s*\)\s*;",
        TOKENS,
    ) is not None


# ── 1 · The canonical token layer ────────────────────────────────────────────

_section("1 · The canonical token layer resolves to the POR's own values")

# Each canonical name is an ALIAS, never a new value. If one of these ever
# acquires a literal, the layer has stopped being a naming decision and become
# a second palette — which is the drift it exists to end.
for _name, _target in (
    ("--fs-c-text", "--bone"),
    ("--fs-c-text-muted", "--fs-r43-secondary"),
    ("--fs-c-text-faint", "--fs-r43-tertiary"),
    ("--fs-c-gold", "--gold"),
    ("--fs-c-gold-fill", "--goldbg"),
    ("--fs-c-surface", "--card"),
    ("--fs-c-surface-inset", "--tile"),
    ("--fs-c-border", "--fs-border"),
    ("--fs-c-border-strong", "--fs-border-edge"),
    ("--fs-c-size-section", "--fs-r43-section"),
    ("--fs-c-size-body", "--fs-r43-card"),
    ("--fs-c-size-body-sub", "--fs-r43-card-secondary"),
    ("--fs-c-size-fine", "--fs-r43-meta"),
    ("--fs-c-size-label", "--fs-r43-strip-label"),
    ("--fs-c-size-metric", "--fs-r43-strip-value"),
    ("--fs-c-font-number", "--fs-font-money"),
    ("--fs-c-weight-number", "--fs-weight-strong"),
    ("--fs-c-radius-cell", "--fs-radius-cell"),
    ("--fs-c-touch", "--fs-r43-touch"),
    ("--fs-c-gap-cell", "--fs-space-2"),
    ("--fs-c-pad-cell", "--fs-space-3"),
    ("--fs-c-gap-heading", "--fs-space-2"),
):
    _assert(f"{_name} aliases {_target}", _alias(_name, _target))

_assert("the canonical layer introduces no colour of its own",
        not re.search(r"--fs-c-[a-z-]+:\s*#", TOKENS))

# THE DRIFT THIS CLOSED. `--fs-r43-strip-value` existed and said 23px while
# rev43.css hard-coded the strip value to 22px and nothing read the token.
_assert("the metric value reads the strip-value token, not a literal",
        "var(--fs-c-size-metric)" in _rule(COMPONENTS, ".fs-strip__value"))
_assert("and rev43's competing hard-coded 22px is gone",
        "font-size: 22px" not in _without_comments(REV43))


# ── 2 · The metric cell is written once ──────────────────────────────────────

_section("2 · The metric cell is one primitive, not a per-screen treatment")

_strip = _rule(COMPONENTS, ".fs-strip")
_cell = _rule(COMPONENTS, ".fs-strip__cell")
_label = _rule(COMPONENTS, ".fs-strip__label")
_value = _rule(COMPONENTS, ".fs-strip__value")

_assert("four equal columns that cannot be widened by their content",
        "grid-template-columns: repeat(4, minmax(0, 1fr))" in _strip)
_assert("the cell is a column: label row, then value row",
        "display: flex" in _cell and "flex-direction: column" in _cell)
_assert("the label is the fixed top row", "flex: 0 0 auto" in _label)
_assert("the label is centred horizontally", "text-align: center" in _label)
_assert("the label can never wrap", "white-space: nowrap" in _label)
_assert("an over-long label ellipsizes rather than wrapping",
        "text-overflow: ellipsis" in _label)
_assert("the value takes the rest of the cell", "flex: 1 1 auto" in _value)
_assert("and centres its content on both axes",
        "align-items: center" in _value and "justify-content: center" in _value)

# NO SCREEN MAY RE-STATE THE CELL. The whole failure mode Wave 1 closed was a
# later sheet quietly overriding the shared component, so the absence of a
# competing rule is itself the deliverable.
for _sheet_name, _sheet in (("rev43.css", REV43), ("gameplay.css", GAMEPLAY),
                            ("tabs.css", TABS), ("wager.css", WAGER)):
    for _sel in (".fs-strip__label", ".fs-strip__value", ".fs-strip__cell"):
        _assert(f"{_sheet_name} does not restate {_sel}",
                _rule(_sheet, _sel).strip() == "")


# ── 3 · The choice cell is one primitive ─────────────────────────────────────

_section("3 · The choice cell is one primitive shared by both consumers")

# ONE SELECTOR LIST, applied to the class names that already exist. Wave 1 makes
# no markup change, so the proof that the two consumers are one control is that
# they are styled by the same rule — which means the rule must name both.
_shared = re.search(
    r"\.fs-market,\s*\n\.fs-seg__opt\s*\{([^{}]*)\}", WAGER)
_assert("the market cell and the segment cell share one base rule",
        _shared is not None)
_base = _shared.group(1) if _shared else ""
_assert("peers centre on both axes",
        "align-items: center" in _base and "justify-content: center" in _base)
_assert("peers share one radius token", "var(--fs-c-radius-cell)" in _base)
_assert("peers share the 44px tappable floor",
        "min-height: var(--fs-c-touch)" in _base)
_assert("peers share one ground", "var(--fs-c-surface-inset)" in _base)

_shared_label = re.search(
    r"\.fs-market__label,\s*\n\.fs-seg__label\s*\{([^{}]*)\}", WAGER)
_assert("the two labels are one rule", _shared_label is not None)
# Rev 4.3 SS5.1 classifies a market label as CARD SECONDARY text (14–15px), and
# WP3C's certification asserts that floor directly. The primitive raised the
# composer's 11px segment label to meet the Play card rather than the reverse.
_assert("and read the canonical card-secondary step",
        "var(--fs-c-size-body-sub)" in (_shared_label.group(1) if _shared_label else ""))

_shared_value = re.search(
    r"\.fs-market__value,\s*\n\.fs-seg__value\s*\{([^{}]*)\}", WAGER)
_shared_value_decls = _shared_value.group(1) if _shared_value else ""
_assert("the two values are one rule", _shared_value is not None)
_assert("and are drawn as numbers",
        "var(--fs-c-font-number)" in _shared_value_decls)
# The hierarchy WP3C set on the Play card, now imposed on the composer too,
# where label and value had been the other way round.
_assert("the value sits one step below its label",
        "var(--fs-c-size-fine)" in _shared_value_decls)

_shared_selected = re.search(
    r"\.fs-market\.is-selected,\s*\n\.fs-seg__opt\.is-selected\s*\{([^{}]*)\}", WAGER)
_assert("the selected state is one rule", _shared_selected is not None)

# THE RETIRED PER-SCREEN OVERRIDES. `gameplay.css` sized the Play card's market
# cell from a screen selector and had INVERTED the label/value hierarchy
# relative to the composer; `tabs.css` asserted a 34px min-height below the
# Rev 4.3 tappable floor. Both are gone, and their absence is the assertion.
_assert("gameplay.css no longer sizes the market cell from a screen selector",
        _rule(GAMEPLAY, ".fs-markets .fs-market__label").strip() == ""
        and _rule(GAMEPLAY, ".fs-markets .fs-market__value").strip() == ""
        and _rule(GAMEPLAY, ".fs-markets .fs-market").strip() == "")
_assert("no sheet asserts a sub-44px market cell",
        "min-height: 34px" not in _without_comments(TABS)
        and "min-height" not in _rule(TABS, ".fs-carousel .fs-market"))
# The market cell's height floor comes from the SHARED rule and from nowhere
# else — the property is declared once, in a block that names both consumers.
_assert("the market cell's only height floor is the shared one",
        "min-height: var(--fs-c-touch)" in _rule(WAGER, ".fs-market")
        and _rule(WAGER, ".fs-market").count("min-height") == 1)
# A block whose selector list names ONLY one of the two consumers is a
# per-consumer override; the retired Rev 4.2 duplicates were exactly that.
_assert("no rule styles .fs-seg__opt on its own",
        all(len(lst) > 1 for lst in _selector_lists(WAGER, ".fs-seg__opt")),
        str(_selector_lists(WAGER, ".fs-seg__opt")))
_assert("no rule styles .fs-market on its own",
        all(len(lst) > 1 for lst in _selector_lists(WAGER, ".fs-market")),
        str(_selector_lists(WAGER, ".fs-market")))
_assert("and the shared rule names both consumers",
        any({".fs-market", ".fs-seg__opt"} <= set(lst)
            for lst in _selector_lists(WAGER, ".fs-market")))


# ── 4 · The section-heading gap ──────────────────────────────────────────────

_section("4 · The section-heading gap is one token in one declaration")

_heading_rules = [
    m.group(0) for m in re.finditer(r"[^{}]*\.fs-heading\s*\{[^{}]*\}", GAMEPLAY)
]
_gap_rule = "\n".join(r for r in _heading_rules if "margin:" in r)
_assert("the gap is the canonical token, not a number",
        "var(--fs-c-gap-heading)" in _gap_rule)
_assert("and the zero bottom margin it replaced is gone",
        "margin: var(--fs-space-1) var(--fs-space-1) 0" not in GAMEPLAY)
for _consumer in (".fs-zone", ".fs-railsec", ".fs-wkmod",
                  "#panel-league", "#panel-action", "#panel-week"):
    _assert(f"{_consumer} takes the shared gap", f"{_consumer} .fs-heading" in _gap_rule)

# Status's section-to-section separation had ridden a heading margin that was
# dead by cascade order; Wave 1 moved it onto the section itself.
_assert("Status separates sections on the section, not the heading",
        ".fs-railsec + .fs-railsec" in TABS
        and _rule(TABS, ".fs-railsec .fs-heading").strip() == "")


# ── 5 · Terminology — public copy vs internal identifiers ────────────────────

_section("5 · Public terminology is locked; internal identifiers are not renamed")

_JS_DIR = os.path.join(WEB, "js")
_js_files: dict[str, str] = {}
for _dirpath, _dirnames, _filenames in os.walk(_JS_DIR):
    for _name in _filenames:
        if _name.endswith(".js"):
            _path = os.path.join(_dirpath, _name)
            with open(_path, encoding="utf-8") as _h:
                _js_files[os.path.relpath(_path, WEB).replace("\\", "/")] = _h.read()

_assert("the web/js tree was read", len(_js_files) > 30, str(len(_js_files)))


def _quoted_strings(source: str) -> list[str]:
    """Single-quoted literals, which is how this codebase writes UI copy.

    TWO THINGS ARE STRIPPED FIRST, and both would otherwise make this sweep
    report the opposite of what it means.

    COMMENTS. Several of them discuss the retired wording deliberately, and a
    sweep that counted those would force the reasoning to be deleted along with
    the copy it explains.

    HTML ATTRIBUTE VALUES. The markup this codebase builds carries internal
    identifiers in attributes — `value="versus"` on a commissioner select whose
    VISIBLE label already reads `FantasyStakes matchup`, and `data-fs-corr="versus"`
    as a binding hook. Those are protocol and DOM identifiers, which Wave 1
    deliberately does not rename; what a GM can READ is the text between the
    tags, and that is what is left standing to be swept.
    """
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    without_line = re.sub(r"^\s*//.*$", "", without_block, flags=re.MULTILINE)
    literals = re.findall(r"'((?:[^'\\\n]|\\.)*)'", without_line)
    return [re.sub(r'[\w-]+="[^"]*"', "", lit) for lit in literals]


_offenders: list[str] = []
for _rel, _src in _js_files.items():
    for _lit in _quoted_strings(_src):
        # An import specifier or a data attribute is not copy.
        if _lit.startswith("./") or _lit.startswith("../"):
            continue
        if re.search(r"\bversus\b", _lit, re.I) and not re.fullmatch(
                r"[a-z0-9_-]+", _lit):
            _offenders.append(f"{_rel}: {_lit[:60]}")

_assert("no user-visible string in web/js contains Versus",
        not _offenders, " | ".join(_offenders[:4]))

# THE OTHER HALF OF THE RULE, AND IT MATTERS AS MUCH. Wave 1 was explicitly not
# a rename: the modules, the state constants and the model API keep `versus`,
# and a well-meaning future sweep that renamed them would break the composer,
# the market board and four suites at once.
_assert("the internal Versus module names survive",
        os.path.exists(os.path.join(_JS_DIR, "versus-model.js"))
        and os.path.exists(os.path.join(_JS_DIR, "versus-market-command.js"))
        and os.path.exists(os.path.join(_JS_DIR, "versus-quote-command.js")))
_assert("the internal Versus state constants survive",
        "VERSUS_STATE_READY" in _js_files["js/versus-model.js"]
        and "VERSUS_MODE_AUTHORITATIVE" in _js_files["js/versus-model.js"])
_assert("the internal ledger Versus terms survive",
        "netVersusCents" in _js_files["js/ledger-model.js"]
        and "versusPlusPoolsCents" in _js_files["js/ledger-model.js"])
_assert("the served API field names are untouched",
        "acting_moneyline" in _js_files["js/composer.js"]
        and "acting_spread" in _js_files["js/league.js"]
        and "opponent_team_id" in _js_files["js/market-model.js"])

# The locked first references, in the source that renders them.
_assert("Play names FantasyStakes Matchups",
        "'FANTASYSTAKES MATCHUPS'" in _js_files["js/league.js"])
_assert("Play names FantasyStakes Prop Pools",
        "'FANTASYSTAKES PROP POOLS'" in _js_files["js/league.js"])
_assert("Wrap Up names FantasyStakes Matchups",
        "FANTASYSTAKES MATCHUPS" in _js_files["js/week.js"])
_assert("Wrap Up names FantasyStakes Prop Pools",
        "FANTASYSTAKES PROP POOLS" in _js_files["js/week.js"])
_assert("Account groups activity under the locked terms",
        "MATCHUP ACTIVITY" in _js_files["js/ledger.js"]
        and "PROP POOL ACTIVITY" in _js_files["js/ledger.js"])
_assert("Standings keeps FantasyStakes Championship",
        "FANTASYSTAKES CHAMPIONSHIP" in _js_files["js/standings.js"])
_assert("the virtual-credits disclaimer is untouched",
        "VIRTUAL CREDITS · $ IS DISPLAY ONLY · NO CASH VALUE"
        in _js_files["js/components.js"])

# `Standard Pool Bet` is the GOVERNED settings name behind the `pool-bet` route
# and is asserted by the Sprint 7 certification. It is deliberately NOT reworded
# by a UI copy pass — renaming it would be a protocol change in copy's clothing.
_assert("the governed Standard Pool Bet name is not reworded",
        "'Standard Pool Bet'" in _js_files["js/data/rules-data.js"])


# ── 5b · The locked app-shell viewport POR ───────────────────────────────────

_section("5b · The app-shell viewport contract the primitives must not break")

# THE ADDENDUM, AS STRUCTURE. The browser tier measures the outcome at five
# viewports; this tier asserts the RULES that make the outcome possible, because
# a measurement that passes by luck reads exactly like one that passes by
# construction. Four declarations carry the whole contract:
#
#   the shell is a fixed-height flex column that does not scroll
#   the panel region may shrink (`min-height: 0`) so the nav is never pushed out
#   a panel hides its own overflow, so a tab can never become a scroll container
#   the nav is `flex: 0 0 auto` in NORMAL FLOW — it reserves its own height
#     rather than floating over the panel, which is what "persistent … in the
#     normal app shell" means and what makes it reachable without a z-index race
SHELL = _read("styles", "shell.css")

_app = _rule(SHELL, ".fs-app")
_assert("the app shell is a flex column of fixed viewport height",
        "flex-direction: column" in _app and "100dvh" in _app)
_assert("and does not scroll itself", "overflow: hidden" in _app)

_panels = _rule(SHELL, ".fs-panels")
_assert("the panel region may shrink so the navigation is never pushed off",
        "min-height: 0" in _panels and "flex: 1 1 auto" in _panels)
_assert("and the panel region hides its own overflow",
        "overflow: hidden" in _panels)

_panel = _rule(SHELL, ".fs-panel")
_assert("a tab cannot become a scroll container",
        "overflow: hidden" in _panel and "min-height: 0" in _panel)

_tabbar = _rule(SHELL, ".fs-tabbar")
_assert("the bottom navigation reserves its own height in normal flow",
        "flex: 0 0 auto" in _tabbar)
_assert("and is not positioned over the panel",
        "position: fixed" not in _tabbar and "position: absolute" not in _tabbar)
_assert("it clears the home indicator rather than sitting under it",
        "--fs-safe-bottom" in _tabbar)

# THE WAVE 1 PRIMITIVES, CHECKED AGAINST THE SAME CONTRACT. Each of the three
# is a plausible way to push the navigation out of the shell, and each is
# structurally prevented rather than merely measured.
_assert("the metric strip is a fixed row that cannot grow the panel",
        "flex: 0 0 auto" in _strip)
_assert("its columns cannot be widened by their own content",
        "minmax(0, 1fr)" in _strip)
_assert("its cells cannot be widened by their own content",
        "min-width: 0" in _cell)
_assert("a metric label overflows into an ellipsis, never onto a second line",
        "white-space: nowrap" in _label and "overflow: hidden" in _label)
_assert("a choice cell cannot be widened by its own content",
        "min-width: 0" in _base)
_assert("a choice-cell label cannot wrap the cell onto a second line",
        "white-space: nowrap" in (_shared_label.group(1) if _shared_label else ""))
# The heading gap is the one Wave 1 change that ADDS height, so the token it
# spends must be a small one; the browser tier proves the panel still fits.
_assert("the heading gap spends one small spacing step",
        _alias("--fs-c-gap-heading", "--fs-space-2"))


# ── 6 · No behaviour, no backend ─────────────────────────────────────────────

_section("6 · Wave 1 changed presentation only")

_assert("no API module was touched by this wave",
        not os.path.exists(os.path.join(ROOT, ".uirecon-api-touched")))

# The shared primitive is CSS applied to the class names that already existed,
# so every binding selector the JS uses must still be the one it used before.
_assert("the composer still binds markets by data attribute",
        "data-composer-market" in _js_files["js/composer.js"])
_assert("the composer still binds terms by data attribute",
        "data-composer-mode" in _js_files["js/composer.js"])
_assert("Play still binds market cells by data attribute",
        "data-market" in _js_files["js/league.js"])
_assert("the Pool pick still submits through the governed command",
        "submitPoolClaim" in _js_files["js/shell.js"])


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


_run_node("uirecon_wave1_browser.mjs",
          "UIRECON Wave 1 browser suite (headless Chrome)")
_run_node("package2_component_tests.mjs", "Play + Status component suite")
_run_node("package3_component_tests.mjs", "Wrap Up + Account component suite")
_run_node("wp3c_component_tests.mjs", "Rev 4.3 gameplay component suite")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON WAVE 1 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON WAVE 1 — all assertions PASSED")
