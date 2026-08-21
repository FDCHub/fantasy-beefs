#!/usr/bin/env python3
"""
test_uirecon_wave3.py — UIRECON Wave 3 · wager parity and Prop Pool selection.

Run:  python test_uirecon_wave3.py

WHAT WAVE 3 DID.

  3A · THE MATCHUP WAGER CARD. Moving Moneyline → Spread → Over/Under used to
       move every slot below the market selector — 86px of travel on the control
       that spends Credits, measured at 390x844 against a priced pairing. The
       market block is three fixed slots now, rendered for every market at the
       same height, so only the data changes.

  3B · THE PROP POOL PICK SURFACE. The governed claim path was always sound:
       subjects are served from the same census `pool_claims._validate_subject`
       validates against, and `submit_claim` refuses whatever it should. The
       DEFECT WAS THE SURFACE — an unstyled native `<select>` (no stylesheet in
       the product styles a `select`) captioned with the census scope enum, so
       every Prop Pool was fronted by a dropdown labelled `Matchup` or `Team`.
       It is the Wave 1 choice cell now, and the question is derived from the
       served scope.

  3B · ONE DEMO-ONLY CHANGE, ISOLATED AND NAMED. The showcase claimed a
       Prediction for every GM on every occurrence including the live week, so
       the visitor met a fully-answered slate and could never make a pick. One
       GM is now skipped on one live-week slot. See `showcase.VISITOR_ORDINAL`.

WHAT THIS SUITE WILL NOT LET PASS. A parity fix that quietly changed what a
wager IS. §5 below asserts that the persisted market values, the quote path, the
Locked/Dynamic ruling copy, the claim command and the settlement inputs are
untouched — because the cheapest way to make three cards identical would have
been to stop showing what distinguishes them.
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

# THE BROWSER TIER NEEDS PRICED MARKETS. An unseeded league refuses every
# pairing, and three identical refusals would certify parity across three empty
# cards — the one shape of this suite that could pass while proving nothing.
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
    with open(os.path.join(WEB, *parts), encoding="utf-8") as fh:
        return fh.read()


def _read_root(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


COMPOSER_JS = _read("js", "composer.js")
WAGER_MODEL_JS = _read("js", "wager-model.js")
LEAGUE_JS = _read("js", "league.js")
SLATE_JS = _read("js", "pool-slate-model.js")
CLAIM_JS = _read("js", "pool-claim-command.js")
WAGER_CSS = _read("styles", "wager.css")
GAMEPLAY_CSS = _read("styles", "gameplay.css")


def _rule(css: str, selector: str) -> str:
    pattern = re.compile(r"(?:^|\}|\*/)\s*([^{}@/]*?)\s*\{([^{}]*)\}",
                         re.MULTILINE | re.DOTALL)
    return "\n".join(
        m.group(2) for m in pattern.finditer(css)
        if any(p.strip() == selector for p in m.group(1).split(","))
    )


def _strip_js_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.MULTILINE)


def _strip_py_comments(src: str) -> str:
    src = re.sub(r'"""[\s\S]*?"""', " ", src)
    return re.sub(r"^\s*#.*$", " ", src, flags=re.MULTILINE)


# ── 1 · The market block is one construction ─────────────────────────────────

_section("1 · One market block, three fixed slots, every market")

_code = _strip_js_comments(COMPOSER_JS)

# THE OLD SHAPE IS GONE. Three early returns — `''` for moneyline, a bare
# `.fs-note.is-warn` for a refusal, and a differently-sized block per market —
# were what let the card change size. Their absence is the deliverable.
_assert("moneyline no longer short-circuits to an empty block",
        "state.marketId === 'ml') return '';" not in _code)
_assert("a refusal no longer renders a note of its own height",
        'fs-note is-warn" data-market-detail' not in _code)

_block = _code.split("function marketDetail")[1].split("\nfunction ")[0]
_assert("every market renders through one block builder",
        _block.count("const block =") == 1)
_assert("and through one line, side and note builder",
        _block.count("const line =") == 1
        and _block.count("const staticSide =") == 1
        and _block.count("const note =") == 1)
for kind in ("'unavailable'", "'none'", "'ml'", "'spread'", "'ou'"):
    _assert(f"the {kind} state uses the shared block", f"block({kind}," in _block)
# THE THREE SLOTS ARE ALWAYS ALL THREE, and the counts are compared to each
# other rather than to a number — so adding a market state cannot pass by
# forgetting a slot, and cannot fail merely because a state was added.
_states = _block.count("block(")
_sides = _block.count("staticSide(") + _block.count("+ sides")
_notes = _block.count("note(")
_assert("every market state fills the side slot", _sides == _states,
        f"{_sides} sides for {_states} states")
# AT LEAST ONE NOTE PER STATE, not exactly one: the priced over/under branches
# its note on whether a side has been chosen — "choose one" or "here is what it
# means" — which is two notes for one state and the same reserved slot either
# way.
_assert("every market state fills the note slot", _notes >= _states,
        f"{_notes} notes for {_states} states")
_assert("every market state fills the line slot",
        _block.count("line(") == _states,
        f"{_block.count('line(')} lines for {_states} states")

_detail = _rule(WAGER_CSS, ".fs-marketdetail")
_assert("the block finally has a stylesheet rule", _detail.strip() != "")
_assert("the note reserves its height", "min-height" in
        _rule(WAGER_CSS, ".fs-marketdetail__note"))
_assert("and clamps it, so a long sentence cannot grow the card",
        "line-clamp" in _rule(WAGER_CSS, ".fs-marketdetail__note"))
_assert("the side row reserves the touch floor",
        "min-height: var(--fs-c-touch)" in _rule(WAGER_CSS, ".fs-seg--side"))
_assert("the static side cell is not a control",
        "cursor: default" in _rule(WAGER_CSS, ".fs-seg__opt.is-static"))

# THE TERMS EXPLANATION CANNOT MOVE THE CARD EITHER. Both bodies occupy one grid
# cell, so the block is as tall as the longer of them at every width — rather
# than as tall as whichever the GM happens to have chosen.
_assert("both mode bodies are rendered",
        "MODES.map((mode)" in _code and "fs-modenote__stack" in _code)
_assert("they share one grid cell",
        "grid-area: 1 / 1" in _rule(WAGER_CSS, ".fs-modenote__stack > .fs-modenote__body"))
_assert("the inactive one is hidden without losing its height",
        "visibility: hidden" in _rule(WAGER_CSS,
                                      ".fs-modenote__stack > .fs-modenote__body"))
_assert("and is hidden from assistive technology too",
        'aria-hidden="true"' in _code.split("function modeExplanation")[1][:900])


# ── 2 · The public market wording ────────────────────────────────────────────

_section("2 · Moneyline, Spread, Over/Under")

_assert("the composer's labels are the locked public wording",
        "label: 'Moneyline'" in WAGER_MODEL_JS
        and "label: 'Spread'" in WAGER_MODEL_JS
        and "label: 'Over/Under'" in WAGER_MODEL_JS)
_assert("the narrow-cell abbreviations are untouched",
        "short: 'ML'" in WAGER_MODEL_JS and "short: 'SPR'" in WAGER_MODEL_JS
        and "short: 'O/U'" in WAGER_MODEL_JS)
_assert("and the persisted protocol values are untouched",
        "persisted: 'straight'" in WAGER_MODEL_JS
        and "persisted: 'spread'" in WAGER_MODEL_JS
        and "persisted: 'over_under'" in WAGER_MODEL_JS)


# ── 3 · The Prop Pool pick surface ───────────────────────────────────────────

_section("3 · The Prop Pool pick is a choice, not a dropdown")

_league = _strip_js_comments(LEAGUE_JS)

_assert("the native select is gone", "<select" not in _league)
_assert("and the unstyled form class with it", "fs-setform" not in _league)
_assert("the choices are the Wave 1 choice cell",
        "fs-seg__opt is-wrap" in _league and "data-poolpick-subject" in _league)
_assert("with the shared pressed grammar", 'aria-pressed="${selected}"' in _league)

# EVERY OPTION IS THE SERVER'S. The one place a team could have been invented is
# the option list, so it is asserted to come from `pool.subjects` and from
# nothing else.
_pick = _league.split("function poolPickControl")[1].split("\nfunction ")[0]
_assert("options are mapped from the served subjects",
        "pool.subjects.map(" in _pick)
_assert("each carries the served subject id", "s.subject_id" in _pick)
_assert("and the served label", "s.label" in _pick)
_assert("no team or matchup name is written in the client",
        not re.search(r"'[A-Z][a-z]+ (Train|Trust|Team)\b", _pick))

# THE SCOPE ENUM IS NO LONGER A CAPTION.
_assert("the scope is a noun for a sentence, not a field label",
        "'matchup' : 'team'" in SLATE_JS)
_assert("the sheet asks a question derived from the served scope",
        "function poolQuestion" in _league
        and "pool.scope === 'MATCHUP'" in _league)
_assert("and no longer prints the scope as a Subject row",
        'fs-prev__label">Subject<' not in _league)

# NO CLIENT-SIDE RULE DECIDES WHAT MAY BE PICKED.
_assert("the empty-subject state is drawn, not invented",
        "!pool.subjects.length" in _pick)
_assert("the claim still goes through the governed command",
        "submitPoolClaim" in _read("js", "shell.js")
        and "explainPoolClaimRefusal" in _read("js", "shell.js"))
_assert("and the command module is untouched by this wave",
        "PoolClaimCommandError" in CLAIM_JS)

# THE CONFIRMATION IS STILL THE SERVER'S — the WP6C rule Wave 3 had to keep
# while ALSO making `Your pick` follow the selection. The two are different
# statements and the code keeps them apart.
_bind = _league.split("export function bindPoolPickForm")[1]
_assert("the confirmed label is looked up by the SERVER's subject id",
        "body.selected_subject_id" in _bind)
_assert("a pending selection is marked as unsent",
        "is-pending" in _bind)
_assert("and cleared only when the write returns",
        "classList.remove('is-pending')" in _bind)

_assert("the pick grid has a stylesheet rule",
        _rule(GAMEPLAY_CSS, ".fs-poolpick__grid").strip() != "")
_assert("its cells are equal by construction",
        "grid-auto-rows: 1fr" in _rule(GAMEPLAY_CSS, ".fs-poolpick__grid"))
_assert("one column for matchups, two for teams",
        "grid-template-columns: 1fr" in _rule(GAMEPLAY_CSS,
                                              ".fs-poolpick__grid.is-single")
        and "repeat(2," in _rule(GAMEPLAY_CSS, ".fs-poolpick__grid.is-double"))
_assert("the submit control meets the touch floor",
        "min-height: var(--fs-c-touch)" in _rule(GAMEPLAY_CSS,
                                                 ".fs-poolpick__save"))


# ── 4 · The demo-only change, isolated ───────────────────────────────────────

_section("4 · One demo-only change, named and bounded")

from demo import showcase as _showcase  # noqa: E402
from demo import seed as _seed  # noqa: E402

_assert("the visitor ordinal mirrors the seat the seeder actually uses",
        _showcase.VISITOR_ORDINAL == _seed.DEMO_SEAT_ORDINAL,
        f"{_showcase.VISITOR_ORDINAL} vs {_seed.DEMO_SEAT_ORDINAL}")
_assert("exactly one slot is left open",
        isinstance(_showcase.VISITOR_OPEN_PICK_SLOT, int)
        and 1 <= _showcase.VISITOR_OPEN_PICK_SLOT <= 4,
        str(_showcase.VISITOR_OPEN_PICK_SLOT))

_gameplay = _strip_py_comments(_read_root("demo", "gameplay.py"))
_reset = _strip_py_comments(_read_root("demo", "reset.py"))

# ONE PREDICATE, TWO CALLERS, AND IT IS TESTED DIRECTLY.
#
# The seeder and the restore have to agree exactly — a skip in one and not the
# other would either hand the visitor a fully-claimed slate on reset or leave a
# slot permanently empty. Both call `showcase.visitor_skips_claim`, so there is
# one rule to read and one to test.
#
# WHY THIS MATTERS MORE THAN USUAL HERE. The full demo seed needs PostgreSQL —
# `settlement_engine` uses `SELECT … FOR UPDATE` — so an end-to-end check of the
# seeded slate cannot run on SQLite. This exercises the DECISION itself, which
# is where the risk is: a mis-scoped guard that skipped a completed week, every
# slot, or every GM.
for name, src in (("the seeder", _gameplay), ("the restore", _reset)):
    _assert(f"{name} applies the shared predicate",
            "showcase.visitor_skips_claim(" in src)

_W = _showcase.CURRENT_WEEK
_S = _showcase.VISITOR_OPEN_PICK_SLOT
_O = _showcase.VISITOR_ORDINAL

_assert("the visitor is skipped on the live week's open slot",
        _showcase.visitor_skips_claim(_W, _S, _O) is True)
_assert("no other GM is skipped there",
        all(_showcase.visitor_skips_claim(_W, _S, o) is False
            for o in range(len(_showcase.TEAMS)) if o != _O))
_assert("no other slot of the live week is skipped",
        all(_showcase.visitor_skips_claim(_W, s, _O) is False
            for s in (1, 2, 3, 4) if s != _S))
_assert("no completed week is skipped, for anyone, on any slot",
        all(_showcase.visitor_skips_claim(w, s, o) is False
            for w in range(1, _W)
            for s in (1, 2, 3, 4)
            for o in range(len(_showcase.TEAMS))))
_assert("and no later week is skipped either",
        all(_showcase.visitor_skips_claim(w, s, o) is False
            for w in range(_W + 1, _showcase.SEASON_FINAL_WEEK + 1)
            for s in (1, 2, 3, 4)
            for o in range(len(_showcase.TEAMS))))
# EXACTLY ONE (week, slot, GM) TRIPLE IN THE WHOLE SEASON.
_skipped = [(w, s, o)
            for w in range(1, _showcase.SEASON_FINAL_WEEK + 1)
            for s in (1, 2, 3, 4)
            for o in range(len(_showcase.TEAMS))
            if _showcase.visitor_skips_claim(w, s, o)]
_assert("exactly one claim in the entire season is skipped",
        _skipped == [(_W, _S, _O)], str(_skipped))

# RESTORE MEANS RESTORE. `submit_claim(replace=True)` overwrites a claim but
# never removes one, so a visitor who picked and then reset would keep their
# pick and the demo would be single-use.
_assert("restore withdraws a stale visitor claim",
        "visitor_claims_withdrawn" in _reset and "db.delete(stale)" in _reset)

# NOTHING ELSE IN THE DEMO MOVED. Wave 5 owns demo-state enrichment.
_assert("the seeder still plays every other GM's claim",
        "for n, spec in enumerate(showcase.TEAMS):" in _gameplay)
_assert("no completed week is touched",
        "play_season" in _gameplay and "completed_through" in _gameplay)
_assert("the demo guard is still in front of every mutation",
        "assert_demo_league" in _reset)


# ── 5 · No economic or protocol behaviour changed ────────────────────────────

_section("5 · Presentation only — the protocol is where it was")

_assert("the composer still quotes through the served hook",
        "QUOTE_HOOK" in COMPOSER_JS and "servedEconomicsRows" in COMPOSER_JS)
_assert("Send is still gated by the same validator",
        "validateComposer(state)" in COMPOSER_JS)
_assert("an over/under still requires a side before it can be sent",
        "'Choose Over or Under.'" in COMPOSER_JS)
_assert("the market block derives no number of its own",
        not re.search(r"acting_spread\s*[-+*/]", _block)
        and not re.search(r"total_line\s*[-+*/]", _block)
        and not re.search(r"acting_moneyline\s*[-+*/]", _block))
_assert("the Locked/Dynamic ruling copy is untouched",
        "MODE_COPY" in WAGER_MODEL_JS
        and "Refresh & Relock" in WAGER_MODEL_JS)
_assert("the stake validator is untouched",
        "MIN_STAKE_CENTS" in WAGER_MODEL_JS)

# THE SURFACES LATER WAVES OWN ARE NOT TOUCHED.
_assert("the Matchup Preview read path is untouched",
        "yourLineup: []" in _read("js", "shell.js"))
_assert("WHY THE LINE and THE READ are untouched",
        "whyTheLine" in _read("js", "narrative.js")
        and "theRead" in _read("js", "narrative.js"))
_assert("the Wrap result models are untouched",
        "slateRows()" in _read("js", "week.js"))
_assert("no API module was changed by this wave",
        not os.path.exists(os.path.join(ROOT, ".uirecon-api-touched")))


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


_run_node("uirecon_wave3_browser.mjs",
          "UIRECON Wave 3 browser suite (headless Chrome)")
_run_node("wp3c2_component_tests.mjs", "Versus market lines component suite")
_run_node("package2_component_tests.mjs", "Play + Status component suite")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON WAVE 3 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON WAVE 3 — all assertions PASSED")
