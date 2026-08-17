#!/usr/bin/env python3
"""
test_wp3e_fix2_keyboard_cards.py — WP3E-FIX2 · the keyboard-access gate.

WHAT THIS CLOSES.

  WP3E-FIX found, while certifying focus return on the new upper-left close
  control, that the Versus matchup card could not hold focus at all: it was a
  bare `<div class="fs-wcard is-tappable">` with a click handler. Tab skipped
  it, Enter did nothing, and the composer it opened had no opener to give focus
  back to. A pointer-only path to the product's central gameplay action.

  That defect is closed here, and the closing is DRIVEN rather than described —
  real key events on a real rendering, with activations counted so that "Enter
  works" cannot silently mean "Enter works twice".

WHAT THIS DELIBERATELY DID NOT DO. It did not make static cards tabbable to
satisfy a broad assertion. The reconciliation in §1 names every element with an
activation handler and reports which are controls and which are containers, and
only the controls were changed.

DATABASE. None of its own — the browser tiers run against disposable
application servers.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_app_server import (                              # noqa: E402
    AppServer, COMMISSIONER_EMAIL, GM_EMAIL, PASSWORD,
)

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


# ── 1 · The reconciliation, in source ────────────────────────────────────────

_section("1 · Interactive-card semantics, reconciled in source")

LEAGUE = _read("web", "js", "league.js")
WAGERCARD = _read("web", "js", "wagercard.js")
INTERACTION = _read("web", "js", "interaction.js")

_assert("the Versus card declares button semantics",
        'role="button" tabindex="0"' in LEAGUE)
_assert("and it carries an accessible name",
        'aria-label="${label}"' in LEAGUE and "Challenge ${escapeHtml" in LEAGUE)

# ONE ACTIVATION CONTRACT. The pointer path and the keyboard path must be the
# same function; two handlers is how a card comes to fire twice, or to behave
# differently under a tap than under a key.
_assert("activation goes through the shared onActivate contract",
        "onActivate(card, () => api.openComposer(" in LEAGUE)
_assert("and the old pointer-only binding is gone",
        "card.addEventListener('click'" not in LEAGUE)
_assert("onActivate is imported rather than re-implemented",
        "import { onActivate } from './interaction.js';" in LEAGUE)

# THE HELPER'S OWN GUARANTEES, pinned here because the card now depends on them.
_assert("the helper binds click and keydown to one handler",
        "el.addEventListener('click', handler)" in INTERACTION
        and "el.addEventListener('keydown'" in INTERACTION)
_assert("it honours Enter and Space",
        "'Enter'" in INTERACTION and "' '" in INTERACTION)
_assert("it prevents Space from scrolling the page, as a button would",
        "event.preventDefault()" in INTERACTION)
_assert("and a key pressed inside a nested control is left to that control",
        "if (event.target !== el) return;" in INTERACTION)

# NO STATIC CARD WAS MADE FOCUSABLE. `card()` is the plain container primitive;
# if it started emitting tabindex, every static surface would become a tab stop.
COMPONENTS = _read("web", "js", "components.js")
_assert("the plain card primitive is still not focusable",
        "tabindex" not in COMPONENTS.split("export function card(")[1][:400])

# THE ONE CARD THAT ALREADY HAD SEMANTICS still decides them the same way.
_assert("wager cards still take role=button only without nested controls",
        "tapAction && !nestedControls ? ' role=\"button\" tabindex=\"0\"' : ''"
        in WAGERCARD)


# ── 2 · The close-X POR, synchronized ────────────────────────────────────────

_section("2 · The governing POR now matches shipped behaviour")

POR = _read("spec", "FantasyStakes_UIUX_Rev4_3_FINAL_POR.md")
_assert("Rev 4.3 §25 specifies upper-left", "positioned **upper-left**" in POR)
_assert("no governing instruction says upper-right",
        "positioned **upper-right**" not in POR)
_assert("§26 no longer lists upper-left among retired concepts",
        "Upper-left close placement is **not** a retired concept" in POR)

DELTA = _read("spec", "SPEC_Mobile_UI_UX_Rev4_2_Global_Delta.md")
_assert("the Rev 4.2 delta is preserved as history",
        "The close **X** is always in the **upper-right**" in DELTA)
_assert("and is explicitly marked superseded and unusable",
        "SUPERSEDED — HISTORICAL RECORD ONLY" in DELTA
        and "Do not implement from this paragraph." in DELTA)

# NOTHING ELSE IN THE SPECIFICATION MOVED. The permission was narrow and the
# check is on the content, not only on the filename.
_diff = subprocess.run(["git", "diff", "-U0", "bc2de7b", "--", "spec/", "docs/"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace").stdout
_changed = [ln[1:] for ln in _diff.splitlines()
            if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
_OFF = (r"wager", r"credits?", r"settle\w*", r"escrow", r"Ledger", r"postseason",
        r"Yahoo", r"navigation", r"tab bar", r"odds", r"buy-?in", r"payout")
_off = [ln.strip() for ln in _changed
        if any(re.search(rf"\b{t}\b", ln.replace("FantasyStakes", ""), re.I)
               for t in _OFF)]
_assert("every changed specification line is about the close control",
        not _off, " | ".join(_off)[:200])


# ── 3 · Scope ────────────────────────────────────────────────────────────────

_section("3 · Scope discipline")

_touched = set(
    subprocess.run(["git", "diff", "--name-only", "bc2de7b"], cwd=ROOT,
                   capture_output=True, text=True).stdout.split()
) | set(
    subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                   cwd=ROOT, capture_output=True, text=True).stdout.split()
)

for forbidden in ("db/schema.py", "economy/", "ledger/", "betting/", "odds/",
                  "beefs/", "reports/", "providers/", "auth/", "api/",
                  "migrations/"):
    hits = sorted(f for f in _touched if f.startswith(forbidden))
    _assert(f"{forbidden} is untouched", not hits, ", ".join(hits))

for untouched in ("web/manifest.webmanifest", "web/service-worker.js",
                  "web/js/nav.js", "web/js/shell.js"):
    _assert(f"{untouched} is untouched", untouched not in _touched)

_nav = _read("web", "js", "nav.js")
_ids = re.findall(r"id:\s*'([a-z]+)'", _nav)
_assert("the five primary destinations keep their locked order",
        _ids[:5] == ["standings", "league", "action", "week", "ledger"],
        " -> ".join(_ids[:5]))


# ── 4 · The browser tiers ────────────────────────────────────────────────────

def _run_node(script: str, label: str, env_extra: dict) -> None:
    node = shutil.which("node")
    if node is None:
        _assert(f"{label} — node is available", False, "node not on PATH")
        return
    print(f"\n{label}")
    env = dict(os.environ)
    env.update(env_extra)
    proc = subprocess.run(
        [node, os.path.join(ROOT, "web", "tests", script)],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    print(proc.stdout.rstrip())
    if proc.stderr.strip():
        print(proc.stderr.rstrip()[-2000:])
    passes = proc.stdout.count("[PASS]")
    fails = proc.stdout.count("[FAIL]")
    _assert(f"{label} is green", proc.returncode == 0 and fails == 0,
            f"{passes} PASS / {fails} FAIL, exit {proc.returncode}")


_section("4 · Driven with real key events, in a real browser")

for mode, email in (("gm", GM_EMAIL), ("commissioner", COMMISSIONER_EMAIL)):
    with AppServer(seed_priceable_versus=True, seed_pool_slate=True) as server:
        _run_node("wp3e_fix2_keyboard.mjs",
                  f"WP3E-FIX2 keyboard suite — {mode}",
                  {"FS_TEST_ORIGIN": server.origin,
                   "FS_TEST_AUTH_EMAIL": email,
                   "FS_TEST_AUTH_PASSWORD": PASSWORD,
                   "FS_FIX2_MODE": mode})


# ── 5 · What was NOT automated ───────────────────────────────────────────────

_section("5 · Recorded as not automated in this environment")

for item in (
    "a real screen reader is not driven; the accessible name is asserted from "
    "the exposed aria-label rather than from announced speech",
    "physical Tab key traversal is approximated by the document's tab order "
    "rather than by the browser's own focus advance",
    "real touch events are approximated by the click path the browser "
    "synthesises for them",
):
    _assert(f"NOT AUTOMATED: {item}", True, "reported")


print("\n" + "=" * 66)
if _failures:
    print(f"WP3E-FIX2 KEYBOARD CARD ACCESS — {len(_failures)} FAILED")
    for f in _failures:
        print(f"  · {f}")
    sys.exit(1)
print("WP3E-FIX2 KEYBOARD CARD ACCESS — all assertions PASSED")
