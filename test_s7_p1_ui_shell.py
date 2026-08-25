#!/usr/bin/env python3
"""
test_s7_p1_ui_shell.py — Sprint 7 Package 1: shared UI shell + global components.

Two halves, both required:

  1. STRUCTURAL, in Python. Assertions the browser cannot make for us and that
     must hold in the source itself — the layout contract that keeps the
     persistent bottom navigation out from over the content, the four-column
     strip grid, the upper-left close control, the exact disclaimer string,
     and the absence of superseded Rev4.1 copy.

  2. BEHAVIOURAL, in Node. The shipped ES modules are executed directly by
     `web/tests/ui_component_tests.mjs` — the display formatter's rounding, the
     exact-cents guarantee, the strip's four-cell rule, one disclaimer per tab,
     and five reachable destinations. Testing the real modules is the point:
     a Python reimplementation of the formatter could agree with itself while
     disagreeing with what the app draws.

No database is involved. No protocol module is imported.

USAGE:
    python test_s7_p1_ui_shell.py
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# This suite reports on typography — the middot, the em dash, and the U+2212
# minus sign that money figures use. On a Windows console defaulting to cp1252
# those characters would raise UnicodeEncodeError mid-run and report a green
# suite as a crash. Print them as text, and never let the console encoding
# decide whether the tests passed.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")

# ── The application under certification (WP5) ────────────────────────────────
#
# Run through `test_s7_full_ui_certification.py`, an application is already
# running and `FS_TEST_ORIGIN` already names it — this is then a no-op. Run
# DIRECTLY, as the RUNBOOK's fast-feedback tiers tell a developer to, this
# starts one, because since S8-P1 the shell asks who is acting before it draws
# anything and a static file server answers 404 to that. Without this the suite
# certifies the sign-in gate and dies dereferencing a control the application
# would have rendered.
from test_support_s7_harness import ensure_authenticated_app  # noqa: E402

ensure_authenticated_app()

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _read(*parts: str) -> str:
    with open(os.path.join(WEB, *parts), encoding="utf-8") as fh:
        return fh.read()


def _rule(css: str, selector: str) -> str:
    """Return every declaration block whose selector list contains `selector`
    as a whole selector, concatenated.

    All matching blocks, not the first: `body` appears both in `html, body` and
    in its own rule, and a check against only the first would silently test the
    wrong declarations.
    """
    pattern = re.compile(
        r"(?:^|\}|\*/)\s*([^{}@/]*?)\s*\{([^{}]*)\}",
        re.MULTILINE | re.DOTALL,
    )
    blocks = [
        match.group(2)
        for match in pattern.finditer(css)
        if selector in [s.strip() for s in match.group(1).split(",")]
    ]
    return "\n".join(blocks)


def _strip_comments(source: str) -> str:
    """Remove comments so copy assertions test what the app RENDERS.

    A comment recording that a string is superseded must not itself trip the
    check that the string is gone.
    """
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)   # CSS and JS block
    source = re.sub(r"<!--.*?-->", " ", source, flags=re.DOTALL)  # HTML
    source = re.sub(r"^\s*//.*$", " ", source, flags=re.MULTILINE)  # JS line
    return source


# ── Files ────────────────────────────────────────────────────────────────────

print("\nPackage 1 ships the shared shell as real, served assets")

EXPECTED_FILES = [
    "index.html",
    "styles/tokens.css",
    "styles/shell.css",
    "styles/components.css",
    "js/credits.js",
    "js/components.js",
    "js/nav.js",
    "js/shell.js",
    "js/demo-state.js",
    "tests/ui_component_tests.mjs",
]

for relative in EXPECTED_FILES:
    _assert(
        f"web/{relative} exists",
        os.path.isfile(os.path.join(WEB, *relative.split("/"))),
    )

INDEX = _read("index.html")
SHELL_CSS = _read("styles", "shell.css")
COMPONENTS_CSS = _read("styles", "components.css")
TOKENS_CSS = _read("styles", "tokens.css")
COMPONENTS_JS = _read("js", "components.js")
DEMO_JS = _read("js", "demo-state.js")

# Every shipped source, with comments removed: copy assertions must test what
# the app renders, not what its documentation discusses.
ALL_WEB_RENDERED = _strip_comments("\n".join(
    _read(*relative.split("/"))
    for relative in EXPECTED_FILES
    if not relative.startswith("tests/")
))


# ── The app renders ──────────────────────────────────────────────────────────

print("\nThe app document is complete and mounts the shell")

_assert("index.html declares a document type", INDEX.lstrip().lower().startswith("<!doctype html>"))
_assert("the app is titled FantasyStakes", "<title>FantasyStakes</title>" in INDEX)
_assert("all three stylesheets are linked", all(
    f'href="./styles/{name}.css"' in INDEX for name in ("tokens", "shell", "components")
))
_assert("the shell script is an ES module", 'type="module" src="./js/shell.js"' in INDEX)

for mount_point in ("fs-app", "fs-mast", "fs-panels", "fs-tabbar", "fs-overlay", "fs-sheet"):
    _assert(f"mount point #{mount_point} is present", f'id="{mount_point}"' in INDEX)

_assert("the navigation is a tablist", 'role="tablist"' in INDEX)
_assert("the sheet is a modal dialog", 'role="dialog"' in INDEX and 'aria-modal="true"' in INDEX)


# ── Mobile viewport and safe areas ───────────────────────────────────────────

print("\nMobile viewport and safe-area behaviour")

_assert("the viewport opts into the display cutout", "viewport-fit=cover" in INDEX)
_assert("the status bar is themed to the app background", 'name="theme-color"' in INDEX)
_assert("the app frame is capped to a phone width",
        "--fs-app-max-width" in TOKENS_CSS)
_assert("safe-area insets are resolved as tokens",
        "env(safe-area-inset-top" in TOKENS_CSS and "env(safe-area-inset-bottom" in TOKENS_CSS)

app_rule = _rule(SHELL_CSS, ".fs-app")
_assert("the app frame respects the top safe area", "padding-top: var(--fs-safe-top)" in app_rule)
_assert("the app frame tracks the dynamic viewport", "100dvh" in app_rule)
_assert("the app frame keeps a static viewport fallback", "100vh" in app_rule)


# ── The persistent navigation cannot cover content ───────────────────────────

print("\nThe persistent bottom navigation does not cover tab content")

tabbar_rule = _rule(SHELL_CSS, ".fs-tabbar")
_assert("the navigation exists", bool(tabbar_rule))
_assert(
    "the navigation stays in normal flow — it is never taken out of it",
    not re.search(r"position:\s*(fixed|absolute|sticky)", tabbar_rule),
    "position: fixed/absolute/sticky would let the nav overlay content",
)
_assert(
    "the navigation reserves its own height",
    "flex: 0 0 auto" in tabbar_rule,
)
_assert(
    "the navigation clears the home indicator",
    "var(--fs-safe-bottom)" in tabbar_rule,
)
_assert(
    "no rule anywhere positions the navigation out of flow",
    not re.search(r"\.fs-tabbar[^{]*\{[^}]*position:\s*(fixed|absolute|sticky)", SHELL_CSS),
)

_assert("the shell is a single flex column", "flex-direction: column" in app_rule)

panels_rule = _rule(SHELL_CSS, ".fs-panels")
panel_rule = _rule(SHELL_CSS, ".fs-panel")
_assert("the panel host takes the space left over", "flex: 1 1 auto" in panels_rule)
_assert(
    "the panel host may shrink below its content — min-height:0",
    "min-height: 0" in panels_rule,
    "without this the column overflows and pushes the nav off screen",
)
_assert("panels may shrink below their content", "min-height: 0" in panel_rule)
# Package 1 shipped one shared `.fs-panel__scroll`, which no tab ended up using:
# each built its own scroll region instead. Package 5 removed the unused class,
# so the contract is asserted against the FIVE regions that really exist — which
# is what it was always protecting, and now covers every tab rather than none.
SCROLL_REGIONS = {
    ".fs-zones": _read("styles", "components.css"),      # League
    ".fs-rails": _read("styles", "tabs.css"),            # Action
    ".fs-lscroll": _read("styles", "ledger.css"),        # Ledger
    ".fs-wkscroll": _read("styles", "ledger.css"),       # The Week
    ".fs-rulescroll": _read("styles", "rules.css"),      # Rules & Settings
}
for _selector, _css in SCROLL_REGIONS.items():
    _region = _rule(_css, _selector)
    _assert(f"{_selector}: the scrolling region is inside the panel",
            "overflow-y: auto" in _region or "flex: 1 1 auto" in _region)
    _assert(f"{_selector}: the scrolling region may shrink", "min-height: 0" in _region)
_assert("the document itself never scrolls", "overflow: hidden" in _rule(SHELL_CSS, "body"))


# ── Four-cell strip ──────────────────────────────────────────────────────────

print("\nThe shared four-cell summary strip")

strip_rule = _rule(COMPONENTS_CSS, ".fs-strip")
value_rule = _rule(COMPONENTS_CSS, ".fs-strip__value")
def _alias_resolves(alias: str, target: str) -> bool:
    """Whether `tokens.css` defines `alias` as exactly `var(target)`.

    Whitespace-tolerant: the canonical block aligns its values in a column, so
    a literal substring match would pin the indentation rather than the alias.
    """
    return re.search(
        rf"{re.escape(alias)}\s*:\s*var\(\s*{re.escape(target)}\s*\)\s*;",
        TOKENS_CSS,
    ) is not None


# UIRECON WAVE 1 — the metric cell reads the canonical `--fs-c-*` aliases.
# Each alias resolves to the token this suite used to name directly, so the
# claims are unchanged; what changed is that a shared primitive names one
# answer instead of choosing between the Rev 4.2 and Rev 4.3 scales. The
# resolution itself is asserted below rather than taken on trust.
label_rule = _rule(COMPONENTS_CSS, ".fs-strip__label")
_assert(
    "the strip is a four-column grid of equal widths",
    "grid-template-columns: repeat(4, minmax(0, 1fr))" in strip_rule,
)
_assert("the strip is a grid", "display: grid" in strip_rule)
_assert("strip values are tabular figures that do not reflow",
        "tabular-nums" in value_rule)
_assert("strip values are monospace money",
        "var(--fs-c-font-number)" in value_rule
        and _alias_resolves("--fs-c-font-number", "--fs-font-money"))
_assert("Rev4.2 strip values take the stronger weight",
        "var(--fs-c-weight-number)" in value_rule
        and _alias_resolves("--fs-c-weight-number", "--fs-weight-strong"))
_assert("strip values are centred", "text-align: center" in value_rule)
_assert("strip labels read as secondary",
        "var(--fs-c-text-muted)" in label_rule
        and _alias_resolves("--fs-c-text-muted", "--fs-r43-secondary"))
# The three properties the metric-cell primitive exists to guarantee.
_assert("strip labels are centred, in the top row",
        "text-align: center" in label_rule and "flex: 0 0 auto" in label_rule)
_assert("strip labels can never wrap", "white-space: nowrap" in label_rule)
_assert("the strip value centres on both axes",
        "align-items: center" in value_rule
        and "justify-content: center" in value_rule
        and "flex: 1 1 auto" in value_rule)
_assert(
    "the strip declares no icon slot",
    ".fs-strip__icon" not in COMPONENTS_CSS,
)


# ── Credits disclaimer ───────────────────────────────────────────────────────

print("\nThe Credits disclaimer")

DISCLAIMER = "VIRTUAL CREDITS · $ IS DISPLAY ONLY · NO CASH VALUE"

_assert(
    "the approved string appears verbatim in the component source",
    f"'{DISCLAIMER}'" in COMPONENTS_JS,
    DISCLAIMER,
)
_assert(
    "it is defined exactly once, as a constant",
    COMPONENTS_JS.count(DISCLAIMER) == 1,
    f"count {COMPONENTS_JS.count(DISCLAIMER)}",
)
_assert("the disclaimer has a style of its own", ".fs-disclaimer" in COMPONENTS_CSS)


# ── Universal close control ──────────────────────────────────────────────────

# THE OWNER RULING PUTS THIS UPPER-LEFT, and it supersedes Rev 4.3 FINAL POR
# §25. The assertions below previously pinned upper-right in both directions —
# `right` present and `left` absent — which is exactly what a superseded rule
# looks like from the inside. They now pin the ruling instead: upper-left,
# with its own band, and no surface allowed to opt out.
print("\nThe universal close control is upper-left")

close_rule = _rule(COMPONENTS_CSS, ".fs-sheet__close")
_assert("the close control is positioned", "position: absolute" in close_rule)
_assert("it is anchored to the top", re.search(r"top:\s*[^;]+;", close_rule) is not None)
_assert("it is anchored to the left",
        re.search(r"(^|;)\s*left:\s*[^;]+;", close_rule) is not None)
_assert(
    "and the right anchor is explicitly released, not merely omitted",
    re.search(r"right:\s*auto", close_rule) is not None,
)
_close_bodies = re.findall(r"\.fs-sheet__close[^{]*\{([^}]*)\}", COMPONENTS_CSS)
_right_values = [m.strip().lower() for body in _close_bodies
                 for m in re.findall(r"(?:^|;)\s*right:\s*([^;]+)", body)]
_assert(
    "no rule anywhere moves the close control back to the right",
    all(value == "auto" for value in _right_values),
    ", ".join(_right_values) or "no right declaration",
)
# THE CONTROL HAS ITS OWN BAND rather than sharing the title's line, so nothing
# can run under it whether or not a given sheet carries a title. That is a
# stronger guarantee than the title-side inset it replaces.
_sheet_padding = re.search(r"padding:\s*(\d+)px", _rule(COMPONENTS_CSS, ".fs-sheet"))
_assert(
    "the sheet reserves a band above its content for the close control",
    _sheet_padding is not None and int(_sheet_padding.group(1)) >= 52,
    _sheet_padding.group(0) if _sheet_padding else "no top padding",
)


# ── Scroll / snap primitives ─────────────────────────────────────────────────

print("\nScroll and snap primitives for later tabs")

rail_rule = _rule(COMPONENTS_CSS, ".fs-rail")
_assert("the horizontal rail snaps", "scroll-snap-type: x mandatory" in rail_rule)
_assert("the rail scrolls horizontally only", "overflow-x: auto" in rail_rule)
_assert("rail items are snap targets",
        "scroll-snap-align: start" in _rule(COMPONENTS_CSS, ".fs-rail > .fs-rail__item"))
_assert("the vertical list snaps",
        "scroll-snap-type: y" in _rule(COMPONENTS_CSS, ".fs-vsnap"))
_assert(
    "equal-billing zones share height at flex:1 1 0",
    "flex: 1 1 0" in _rule(COMPONENTS_CSS, ".fs-zones > .fs-zone"),
)


# ── Rev4.3 locked copy, and superseded Rev4.1/4.2 copy ───────────────────────

print("\nRev4.3 locked global copy")

# WP3B RE-POINTED THIS SECTION AT REV 4.3. Two of these assertions asserted
# copy the governing POR has since replaced: the Rev 4.2 lockup line, and the
# Rev 4.2-era rule that no `Wrap Up` label may appear anywhere. Rev 4.3 §2 locks
# a different tagline and §3 makes `Wrap Up` a required primary label — so the
# second assertion now runs in the opposite direction and checks that the label
# is PRESENT and correctly spelled. Neither claim is loosened.
_assert(
    "the masthead tagline is the locked Rev 4.3 primary product tagline",
    "Real odds. Fantasy stakes. More ways to win." in DEMO_JS,
)
_assert(
    "the superseded Rev4.2 lockup line appears nowhere in the app",
    "FANTASY LEAGUES · VIRTUAL STAKES" not in ALL_WEB_RENDERED,
)
_assert(
    "the league identity is the league name alone",
    "CULV APPRECIATION SOCIETY" in DEMO_JS,
)
_assert(
    "the superseded tagline OUR THING · YOUR LEAGUE appears nowhere in the app",
    "OUR THING" not in ALL_WEB_RENDERED,
)
_assert(
    "the superseded · Fantasy Sportsbook suffix appears nowhere in the app",
    "Fantasy Sportsbook" not in ALL_WEB_RENDERED,
)
_assert(
    "Wrap Up is a primary navigation label (Rev 4.3 §3)",
    "'Wrap Up'" in _read("js", "nav.js"),
)

DELTA_SPEC = os.path.join(ROOT, "spec", "SPEC_Mobile_UI_UX_Rev4_2_Global_Delta.md")
_assert("the Rev4.2 global delta is recorded in spec/", os.path.isfile(DELTA_SPEC))
if os.path.isfile(DELTA_SPEC):
    delta = open(DELTA_SPEC, encoding="utf-8").read()
    _assert("the delta records the approved disclaimer verbatim", DISCLAIMER in delta)
    for term in ["ML", "Spread", "O/U", "odds", "Challenge", "stake", "pot", "bets", "wagering"]:
        _assert(
            f"betting vocabulary is retained, not sanitised: {term}",
            re.search(rf"(^|[\s`|]){re.escape(term)}([\s`|.,]|$)", delta) is not None,
        )


# ── The POR artifact is untouched ────────────────────────────────────────────

print("\nThe Rev4.1 canonical prototype is not disturbed by Sprint 7")

REV41_SHA = "b2ab382f775086df469487fe5ad637757eb070e6794e8e1d8551264bd5129b88"
for artifact in ("spec/FantasyStakes_UIUX_Prototype_Rev4_1.html", "tools/prototype/index.html"):
    path = os.path.join(ROOT, *artifact.split("/"))
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest() if os.path.isfile(path) else ""
    _assert(f"{artifact} still hashes to the recorded Rev4.1 artifact", digest == REV41_SHA, digest)


# ── The shell is served ──────────────────────────────────────────────────────

print("\nThe shell is served by the existing application")

MAIN = open(os.path.join(ROOT, "api", "main.py"), encoding="utf-8").read()
_assert("the web shell is mounted", 'app.mount("/app"' in MAIN)
_assert("the mount is static assets only", "StaticFiles(directory=_WEB_DIR" in MAIN)
_assert(
    "the mount resolves independently of the working directory",
    "_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))" in MAIN,
)
_assert("the existing /tools mount is untouched",
        'app.mount("/tools", StaticFiles(directory="tools"), name="tools")' in MAIN)


# ── Behavioural suite, in Node ───────────────────────────────────────────────

print("\nBehavioural component suite (Node — executes the shipped ES modules)")

def _run_node_suite(script: str, label: str) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(
            f"node is available to run {script}",
            False,
            "install Node, or run the script directly where Node is available",
        )
        return
    # Node writes UTF-8. Without saying so, Python decodes it with the console
    # codepage, and on Windows every middot, em dash and minus sign in the
    # suite's own output arrives as mojibake. Packages 2-4 already say so; this
    # brings Package 1's harness into line.
    proc = subprocess.run(
        [node, os.path.join(WEB, "tests", script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    sys.stdout.write(proc.stdout)
    if proc.stderr.strip():
        sys.stdout.write(proc.stderr)
    passed = proc.stdout.count("[PASS]")
    failed = proc.stdout.count("[FAIL]")
    _assert(
        label,
        proc.returncode == 0 and failed == 0,
        f"{passed} PASS / {failed} FAIL, exit {proc.returncode}",
    )


_run_node_suite("ui_component_tests.mjs", "the component suite is green")


# ── Layout suite, in a real browser ──────────────────────────────────────────

print("\nShell layout suite (headless Chrome — measured geometry)")

_run_node_suite("e2e_shell.mjs", "the browser layout suite is green")


# ── Result ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")