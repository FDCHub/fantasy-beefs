#!/usr/bin/env python3
"""
test_uirecon_rev14_status.py — UIRECON Rev 1.4 · Status's four lifecycle carousels.

Run:  python test_uirecon_rev14_status.py
Against a running demo application (the browser tier):
      FS_TEST_ORIGIN=http://127.0.0.1:8000 python test_uirecon_rev14_status.py

WHAT REV 1.4 DID.

  WAVE 5 FILLED ALL FOUR RAILS AND THEN THERE WAS NOWHERE TO PUT THEM. Status's
  four rails are the FantasyStakes lifecycle — what needs my decision, what am I
  waiting on, what is live, what just finished — and Wave 5 finally gave every
  one of them a real record. Measured immediately afterwards at 390x844, those
  four sections stacked to 929px of content inside a 534px viewport, and each
  rail's items were a fixed 216px inside a 366px rail: one card and half of the
  next. A GM meeting Status for the first time saw two lifecycle states and had
  to discover that the other two existed.

  The half card is the defect, not the scrolling. It reads as a rendering fault
  rather than as an invitation to swipe, and it spends a third of the rail on a
  card nobody can read.

WHY THE FIX IS A RULE AND NOT A SMALLER NUMBER.

  Re-tuning 216px is how the peek went stale in the first place — it was right
  for the Rev 4.2 card and wrong the moment Rev 4.3 grew the type. An item that
  is exactly 100% of its rail's width cannot show a partial neighbour at any
  card height, at any viewport width, ever: one item fills the rail by
  construction and `scroll-snap-stop: always` parks the swipe on the next one.
  That is the mechanism Wrap Up's result carousels already use. §2 below asserts
  the rule is what is written, and that the constants it replaced are gone.

WHY THE COUNT MOVED INTO THE HEADING, AND WHERE IT COMES FROM.

  A carousel shows one card, so the heading is now the only place a GM learns
  how many are behind it. `LABEL: N` is the same sentence four times, and N is
  `sectionCount` — the server's own tally from `/league/{id}/action/me` — and
  never the length of what this client happened to draw. §1 asserts the surface
  cannot count for itself; §5 makes a real browser prove the four headings, the
  four `data-rail-count` attributes, the rendered cards and the served counts
  are four descriptions of one set of wagers.

WHERE THE VERTICAL ROOM CAME FROM, AND WHERE IT DID NOT.

  Not the type scale. Rev 4.3 §5.1 fixes the section step at 18–20px and card
  primary at 16–17px, and shrinking those would trade a defect a GM can see for
  one they cannot read. What gave way is leading, padding and ROW COUNT: the
  card's five stacked rows became four, with the foot moved beside the figures
  where there was already horizontal room. §3 asserts the type scale survived.

WHY THIS SUITE DOES NOT ASK GIT WHAT CHANGED.

  `test_uirecon_wave5.py` proves its blast radius with `git diff --name-only`,
  which is exactly right for a wave that owns the tree. Rev 1.4 was built
  alongside other work in one working tree, so a diff would report other
  people's files and the assertion would fail for a reason that has nothing to
  do with Status. §4 asserts the same containment by CONTENT instead — the
  carousel geometry and the density both exist in exactly one stylesheet, and
  neither the shared card shell nor the wager sheet nor the Rev 4.3 gameplay
  sheet learned anything about Status. That is a stronger claim than "these
  paths are unmodified", because it also fails if someone re-states the rule
  somewhere else later.
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
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _without_comments(source: str) -> str:
    """JavaScript or CSS with its comments removed.

    Every assertion below is about what the BUILD does. A rule quoted in a
    comment — and this repository quotes a great many of them, deliberately —
    would otherwise satisfy an assertion that no rule satisfies.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


_action_js = _read("web", "js", "action.js")
_action_model_js = _read("web", "js", "action-model.js")
_tabs_css = _read("web", "styles", "tabs.css")

_action_code = _without_comments(_action_js)
_tabs_rules = _without_comments(_tabs_css)


# ── §1 · The heading grammar, and whose number it is ────────────────────────

_section("§1 · every rail heading reads `LABEL · N · SWIPE`, and N is the server's")

# FINAL POR §28 — THE LOCKED CATEGORY NAMES CHANGED, SO THIS LIST DID.
#
# `WAITING` / `LIVE` / `COMPLETED` named three different kinds of thing.
# The Final POR names all four rails by the ACTION each one holds. The
# assertion's INTENT is unchanged — the four words are stated once, in a
# frozen map, and nothing assembles a heading per rail — so only the words
# themselves are replaced.
for _rail in ("ACTION REQUIRED", "PENDING ACTION", "LOCKED ACTION",
              "RESOLVED ACTION"):
    _assert(f"the rail `{_rail}` keeps its locked word", _rail in _action_code)

_assert("the four words are stated once, as a frozen map",
        "const RAIL_WORDS = Object.freeze({" in _action_code)
_assert("and one expression builds every heading from them",
        "return `${word} · ${sectionCount(rail)} · ${SWIPE_WORD}`;"
        in _action_code)
_assert("the affordance is the same word Play and Wrap Up use",
        "import { SWIPE_WORD }" in _action_code)
_assert("no heading is assembled by a per-rail switch any more",
        "case 'waiting': return `" not in _action_code)

# THE SURFACE MAY NOT COUNT FOR ITSELF. `sectionCount` is the only counting
# call in this file; a `.length` on the rendered cards would agree today and
# would hide the disagreement on the day it mattered.
_assert("the count is `sectionCount` and nothing else",
        "sectionCards(rail).length" not in _action_code
        and "cards.length}" not in _action_code)
_assert("the section also states its count to the DOM, from the same call",
        'data-rail-count="${sectionCount(rail)}"' in _action_code)

# AND `sectionCount` IS THE SERVED TALLY, not the served rows re-counted.
_assert("in production `sectionCount` returns the server's own tally",
        "return SERVED.counts[section] || 0;" in _without_comments(_action_model_js))
_assert("an unbound or failed read counts zero rather than guessing",
        "if (MODE !== ACTION_MODE_AUTHORITATIVE || !SERVED) return 0;"
        in _without_comments(_action_model_js))

# THE COMPLETED HEADING GAVE UP THE FIXTURE SEASON RECORD.
_assert("COMPLETED no longer carries a season record in its heading",
        "SEASON`" not in _action_code and "COMPLETED ·" not in _action_code)
_assert("but the record itself is still drawn, in the strip's own cell",
        "seasonRecordLabel()" in _action_code)


# ── §2 · The carousel is a rule, not a pixel constant ───────────────────────

_section("§2 · one card at a time is expressed as a rule, not as a width")

_assert("the rail is marked as a carousel by the surface that draws it",
        "fs-rail--carousel" in _action_code)
_assert("and the geometry is not written in JavaScript",
        not re.search(r"\d+px", _action_code))

_assert("an item is exactly one rail wide",
        re.search(r"\.fs-rail--carousel > \.fs-rail__item,?[^{]*\{[^}]*"
                  r"flex:\s*0 0 100%", _tabs_rules, flags=re.S) is not None)
_assert("a swipe parks on the next card rather than carrying past it",
        "scroll-snap-stop: always" in _tabs_rules)
_assert("the rail is the scroll container, and snaps mandatorily",
        "overflow-x: auto" in _without_comments(_read("web", "styles", "components.css"))
        and "scroll-snap-type: x mandatory"
        in _without_comments(_read("web", "styles", "components.css")))

# THE CONSTANTS THAT PRODUCED THE HALF CARD ARE GONE, not merely overridden.
_assert("the 216px rail item is gone", "216px" not in _tabs_rules)
_assert("and the 132px card floor with it", "132px" not in _tabs_rules)

_assert("the rail cannot widen the column it sits in",
        re.search(r"\.fs-rail--carousel\s*\{[^}]*min-width:\s*0",
                  _tabs_rules, flags=re.S) is not None)
_assert("and it never draws a scrollbar for the swipe",
        "scrollbar-width: none"
        in _without_comments(_read("web", "styles", "components.css")))


# ── §3 · The density was spent on space, not on legibility ─────────────────

_section("§3 · the type scale survived the density pass")

_STATUS_RULES = _tabs_rules[_tabs_rules.index("fs-rail--carousel"):]

_assert("the §5.1 section step is not reduced for Status",
        "--fs-r43-section" not in _STATUS_RULES
        or "font-size: var(--fs-r43-section)" in _STATUS_RULES)
_assert("the card's primary type keeps its size; only its leading is spent",
        re.search(r"\.fs-wcard__identity\s*\{\s*line-height:[^}]*\}",
                  _STATUS_RULES) is not None
        and not re.search(r"\.fs-wcard__identity\s*\{[^}]*font-size",
                          _STATUS_RULES, flags=re.S))
_assert("no Status rule drops below the §5.1 metadata floor of 12px",
        all(int(px) >= 12 for px in re.findall(r"font-size:\s*(\d+)px",
                                               _STATUS_RULES)),
        ", ".join(re.findall(r"font-size:\s*(\d+)px", _STATUS_RULES)) or "none")

# FOUR ROWS, NOT FIVE. The height came from removing a row, which is why the
# card is a grid and the foot has a row of its own to share.
_assert("the card became a grid so the foot could move beside the figures",
        re.search(r"\.fs-wcard--lifecycle\s*\{[^}]*display:\s*grid",
                  _STATUS_RULES, flags=re.S) is not None)
_assert("the foot and the figures share one row",
        _STATUS_RULES.count("grid-row: 3;") == 2)
_assert("and the foot's divider went with the row it used to divide",
        re.search(r"\.fs-wcard__foot\s*\{[^}]*border-top:\s*0",
                  _STATUS_RULES, flags=re.S) is not None)

# THE TOUCH FLOOR IS RESTATED, NOT ASSUMED. The padding above it is now small
# enough that a one-line card could otherwise fall under it.
_assert("the tappable card still declares the governed touch floor",
        "min-height: var(--fs-r43-touch)" in _STATUS_RULES)


# ── §4 · Containment, asserted by content rather than by git ───────────────

_section("§4 · the change lives in the Status surface and nowhere else")

_SHARED = {
    "web/styles/wager.css": "the shared wager-card stylesheet",
    "web/styles/gameplay.css": "the Rev 4.3 gameplay sheet",
    "web/styles/components.css": "the container primitives",
    "web/styles/ledger.css": "Wrap Up's own carousel",
    "web/styles/standings.css": "Standings",
}
for _path, _what in _SHARED.items():
    _assert(f"{_what} knows nothing about the Status carousel",
            "fs-rail--carousel" not in _read(*_path.split("/")))

_assert("the shared card shell was not taught about Status either",
        "fs-rail--carousel" not in _read("web", "js", "wagercard.js")
        and "railsec" not in _read("web", "js", "wagercard.js"))

# THE READ MODEL IS UNTOUCHED BY A LAYOUT CHANGE — it neither knows nor needs
# to know that a rail became a carousel.
_assert("the Action read model says nothing about rails or carousels",
        not re.search(r"carousel|fs-rail",
                      _read("reports", "action_read_model.py")))

_assert("the geometry is stated in exactly one stylesheet",
        sum("fs-rail--carousel" in _read("web", "styles", name)
            for name in os.listdir(os.path.join(WEB, "styles"))
            if name.endswith(".css")) == 1)


# ── Node tier ───────────────────────────────────────────────────────────────

def _run_node(script: str, label: str) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    if not os.environ.get("FS_TEST_ORIGIN"):
        print(f"  [SKIP] {label} — set FS_TEST_ORIGIN to a running demo app")
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


_run_node("uirecon_rev14_status_browser.mjs",
          "UIRECON Rev 1.4 browser suite (headless Chrome, seeded showcase, "
          "320x568 / 375x667 / 390x844 / 768x1024 / 1024x768)")


# ── Result ─────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON REV 1.4 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON REV 1.4 — ALL PASSED")
