#!/usr/bin/env python3
"""
test_uirecon_rev14_wrap.py — UIRECON Rev 1.4 · the Wrap Up result carousels.

Run:  python test_uirecon_rev14_wrap.py

WHAT REV 1.4 FINISHED.

  WAVE 4B STOPPED AT THE ITEM WRAPPER. It made Wrap Up's three modules one
  construction — one `resultSection()`, one horizontal snap rail, one item —
  and everything outside the item agreed: same heading, same gap, same width,
  same scroll. INSIDE it, FANTASYSTAKES PROP POOLS still drew the `.fs-poolrow`
  button it had drawn as a flat column: a 9px corner where the two rails above
  turned 12px, a 1px left edge under their 3px, and its own inset. Three rails
  that measured identically, holding two visibly different components — the
  "three things a GM reads the same way, built three ways" defect one level
  further in than the wave that named it looked.

  The outer box of a result item is one stylesheet rule now, naming both
  presentations at once, fed from custom properties declared on the rail. There
  is no second place to tune, so the two cannot drift apart; what goes INSIDE
  the box is still each presentation's own, because a row with one line to say
  is not a card with four.

  THE GOLD LEFT EDGE CAME OFF. `.fs-wcard.is-done` paints its left border gold,
  and on Play and the Action rails that earns its place: four rails of cards sit
  at four different stages at once and the edge says which. On Wrap Up every
  card has stopped moving — the tab exists to report what happened — so the mark
  distinguished nothing and read as a gold rule beside a badge already saying
  WON. Nothing replaces it: no second ornament, no tinted fill. The card returns
  to the hairline every other result item carries.

WHAT THIS SUITE WILL NOT LET PASS.

  A PINNED PIXEL. Every geometry claim here is an AGREEMENT between things
  measured in the same layout — rail against rail, card against card, item
  against the rail holding it. The stale `max-height` that started this whole
  line of work was a pixel value that was correct the day it was written; a
  suite that pins one certifies only that nobody has redesigned the card yet.

  A RULE THAT IS WRITTEN BUT NOT WINNING. §2 below is the only part that reads
  source, and it reads it for the SHAPE of the rule — one selector covering both
  presentations — not for its effect. Every claim about what a GM sees is made
  by `getComputedStyle` on a card the application actually mounted, so a
  declaration that lost the cascade fails exactly as loudly as one never
  written.

  A GOLD EDGE REMOVED BY DELETING THE TOKEN. The browser tier puts the finished
  state on a real Wrap Up card and asks the cascade what it paints, then asks
  the SAME question of a Play card and requires the answer there to still be
  gold. Removing the accent product-wide is a different change from the one
  Rev 1.4 asked for, and this refuses to certify it as the same thing.
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

# THE SAME APPLICATION WAVE 4 CERTIFIES AGAINST. A drawn Pool slate is what puts
# four cards on the third rail, and four is what makes the one-card rule
# measurable at all: a rail holding a single item can never expose a second one,
# so a suite run without the slate would pass §2 by having nothing to fail with.
ensure_authenticated_app(seed_pool_slate=True, action_shape="full",
                         seed_priceable_versus=True)

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
    """The code, with its prose removed.

    Wave 1 learned this the hard way and Wave 4 carried the lesson: an absence
    check that scans raw source matches the comment explaining why the thing is
    absent, so the guard passes only while nobody documents it. This file's
    §1–§2 are absence and shape checks over CSS and JS, both of which use the
    two comment forms stripped here.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


# ── §1 · The three locked names are still the three locked names ────────────

_section("§1 · the headings Rev 1.4 may not change")

_week_js = _read("web", "js", "week.js")

for _h in (
    "YAHOO LEAGUE MATCHUPS · SCROLL",
    "FANTASYSTAKES MATCHUPS · SCROLL",
    "FANTASYSTAKES PROP POOLS · SCROLL",
):
    _assert(f"the heading `{_h}` is stated verbatim", _h in _week_js)

# A geometry pass has no business changing what the sections ARE. If Rev 1.4
# had needed a fourth rail or a different builder, that would be a product
# change wearing a layout change's clothes.
_wk = _without_comments(_week_js)
_assert("one section builder still draws all three",
        "function resultSection(" in _wk and _wk.count("resultSection({") >= 4)
_assert("the item wrapper is still the section builder's, not each module's",
        _wk.count("fs-rescar__item") >= 2)


# ── §2 · The outer shell is ONE rule, not a value repeated ──────────────────

_section("§2 · the shell is expressed as a rule, not as three agreeing copies")

_css = _read("web", "styles", "ledger.css")
_css_code = _without_comments(_css)

# THE SHAPE OF THE FIX IS THE POINT. Both presentations named in one selector is
# what makes drift impossible; the same declarations written twice would measure
# identically today and diverge the first time one of them is touched.
_shell = re.search(
    r"\.fs-rescar__item\s*>\s*\.fs-wcard\s*,\s*"
    r"\.fs-rescar__item\s*>\s*\.fs-poolrow\s*\{([^}]*)\}", _css_code, re.S)
_assert("one selector sets the outer box of both presentations",
        _shell is not None)
if _shell:
    _body = _shell.group(1)
    for _prop in ("border-radius", "border-left-width", "padding"):
        _assert(f"the shared shell states its {_prop}", _prop in _body)
    # Fed from the rail's own properties, so the shell has ONE definition and
    # the rule below it is a consumer rather than a second opinion.
    _assert("the shell reads the rail's declared geometry",
            _body.count("var(--fs-res-") >= 3, _body.strip().replace("\n", " "))

_assert("the rail declares the shell it hands down",
        all(t in _css_code for t in
            ("--fs-res-radius:", "--fs-res-edge:", "--fs-res-pad:")))

# CONTAINMENT IS A DECLARATION, and it is the one that separates a carousel from
# a strip that happens to scroll: without it a flick past the last card chains
# into the week column and moves the page instead.
_assert("the scroll is contained to the rail",
        "overscroll-behavior-x: contain" in _css_code)
_assert("the rail hides its own scrollbar",
        "scrollbar-width: none" in _css_code
        and "::-webkit-scrollbar" in _css_code)

# NO PIXEL HEIGHT ANYWHERE NEAR THE RAIL. This is the defect the whole line of
# work exists to remove, and re-introducing one under a new name would be the
# quietest possible way to bring it back.
_assert("no height cap has crept back onto the rail",
        not re.search(r"\.fs-rescar[^{]*\{[^}]*(max-height|height:\s*\d)",
                      _css_code, re.S))

# The gold edge is suppressed for the Wrap Up Matchups section SPECIFICALLY —
# the accent itself still belongs to Play and Action, where it distinguishes
# four live rails from one another.
_gold_off = re.search(
    r"\.fs-wkmod\[data-module=\"bets\"\][^{]*\.fs-wcard\.is-done\s*\{([^}]*)\}",
    _css_code, re.S)
_assert("the gold edge is turned off for the Wrap Up Matchups section",
        _gold_off is not None)
if _gold_off:
    _assert("and it is turned off by returning to the shared border colour",
            "border-left-color" in _gold_off.group(1)
            and "gold" not in _gold_off.group(1),
            _gold_off.group(1).strip())
    _assert("nothing is put on the other side in its place",
            not re.search(r"border-right|box-shadow", _gold_off.group(1)))

# THE ACCENT SURVIVES WHERE IT MEANS SOMETHING. `wager.css` is the card grammar
# and Rev 1.4 does not own it; a fix that reached in and deleted the lifecycle
# accent would have changed Play and all four Action rails as a side effect.
_wager_css = _read("web", "styles", "wager.css")
_assert("the lifecycle accent is untouched in the card grammar",
        "is-done { border-left-color: var(--gold); }" in _wager_css)


# ── §3 · The Account half is NOT this pass's ────────────────────────────────

_section("§3 · the Account tab's own gold edge is left where it was")

# STATED AS AN ASSERTION SO IT CANNOT BE DONE BY ACCIDENT. The same instruction
# applies to the WAGERING SUMMARY card on Account, and it is a different pass's
# to make. Removing it here would silently take a surface this suite does not
# certify — and the pass that owns it would then find its work already done and
# have nothing to verify.
_assert("the Account section's gold edge is still present for its own pass",
        "box-shadow: inset 2px 0 0 var(--gold)" in _css_code)


# ── Node tier ───────────────────────────────────────────────────────────────

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


_run_node("uirecon_rev14_wrap_browser.mjs",
          "UIRECON Rev 1.4 Wrap Up carousels (headless Chrome, five viewports)")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON REV 1.4 WRAP — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON REV 1.4 WRAP — ALL PASSED")
