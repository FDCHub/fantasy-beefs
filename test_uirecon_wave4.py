#!/usr/bin/env python3
"""
test_uirecon_wave4.py — UIRECON Wave 4 · preview lineups and wrap results.

Run:  python test_uirecon_wave4.py

WHAT WAVE 4 DID.

  4A · THE MATCHUP PREVIEW HAD NOTHING TO PREVIEW. `previewSheet()` drew a
       five-column split table over `m.yourStarters` / `m.opponentStarters`, and
       no caller ever supplied either — the League card's preview button built
       its sheet from an object whose starter arrays are empty by construction.
       A GM about to spend Credits opened a panel showing two empty columns, a
       redundant MATCHUP block restating the two names already in the sheet
       subtitle, and a narrative whose every branch took its "nothing is bound"
       path. The demo behind it seeds nine starters and a projection per player
       per week, and the PRICER READS EXACTLY THOSE ROWS. The gap was never the
       data. It was that nothing read it.

       `reports/matchup_preview_read_model.py` reads it now, and the sheet
       reports what it is given: lineups, totals, and a WHY THE LINE / THE READ
       written from the served figures.

  4B · THREE THINGS A GM READS THE SAME WAY, BUILT THREE WAYS. Wrap Up carried
       a vertical snap carousel for Yahoo, the same carousel at a different
       fixed height for wagers, and no carousel at all for Prop Pools. Both caps
       were pixel values measured against Rev 4.2 card sizes, so Rev 4.3's
       taller cards turned the deliberate peek at the next card's title into
       half a visible card. One `resultSection()` builds all three now, over a
       horizontal rail whose items are each exactly one viewport wide — a rule
       with no number in it to go stale.

WHAT THIS SUITE WILL NOT LET PASS.

  A READ PATH THAT WRITES. §15 forbids Wave 4 from touching wager commands,
  claim commands, settlement, ledger posting, the simulation or odds algorithms,
  eligibility, economics or Yahoo storage policy. §2 below reads the two new
  backend modules for any mutation at all, and §3 proves the preview CONSUMES
  the existing pricing output rather than recomputing a board of its own.

  A WINNER THE SURFACE INVENTED. `betting/pool_settlement` computes
  `winning_subject_ids` and never persists them. §5 proves they are recovered
  from what settlement WROTE — the winner-distribution posting and the claims it
  paid — and §7 checks that recovery against real settled PostgreSQL rows.
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

# THE BROWSER TIER NEEDS A PRICED PAIRING. An unseeded league refuses every
# quote, and a preview measured against a refusal would certify the
# graceful-degradation path while claiming to certify the served one.
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

    Wave 1 learned this the hard way: an absence check that scans raw source
    matches the comment explaining why the thing is absent, so the guard passes
    only while nobody documents it. Both comment forms are stripped for JS and
    the `#` form for Python.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    source = re.sub(r"^\s*//.*$", "", source, flags=re.M)
    source = re.sub(r"^\s*#.*$", "", source, flags=re.M)
    return source


def _code_only(source: str) -> str:
    """Python source with its comments AND its docstrings removed.

    A module docstring is not a comment, so every "this module never calls
    X" guard below would otherwise be defeated by the paragraph explaining
    why it never calls X — the same trap `_without_comments` was written
    for, one level up. Triple-quoted strings go first, so the `#` pass
    cannot chew a `#` that lives inside prose.
    """
    source = re.sub(r'""".*?"""', "", source, flags=re.S)
    source = re.sub(r"'''.*?'''", "", source, flags=re.S)
    return re.sub(r"^\s*#.*$", "", source, flags=re.M)


# ── §1 · The public terminology is unchanged ────────────────────────────────

_section("§1 · Wave 1–3 terminology survives Wave 4")

_week_js = _read("web", "js", "week.js")

for _term, _label in (
    ("FANTASYSTAKES MATCHUPS", "the wager section keeps its locked public name"),
    ("FANTASYSTAKES PROP POOLS", "the Pool section keeps its locked public name"),
    ("YAHOO LEAGUE MATCHUPS", "the Yahoo section keeps its locked public name"),
):
    _assert(_label, _term in _week_js)

# The locked headings are exactly these three, and `· SCROLL` is the shared
# suffix — §12 names all three verbatim.
_HEADINGS = [
    "YAHOO LEAGUE MATCHUPS · SCROLL",
    "FANTASYSTAKES MATCHUPS · SCROLL",
    "FANTASYSTAKES PROP POOLS · SCROLL",
]
for _h in _HEADINGS:
    _assert(f"the heading `{_h}` is stated verbatim", _h in _week_js)

# `4 SHOWN` described a viewport cap a one-card carousel makes meaningless. The
# CAP itself must survive — dropping it would change how many wagers Wrap Up
# reports, which is a product change and not a heading change.
_assert("the four-card cap survives the heading change",
        "BETS_SHOWN" in _week_js and "slice(0, BETS_SHOWN)" in _week_js)
_assert("no heading advertises a count any more",
        "SHOWN · SCROLL" not in _week_js)

for _forbidden in ("Bets", "Beefs", "Beef Challenge", "Prop Bet"):
    _assert(f"the retired term `{_forbidden}` is not surfaced",
            f">{_forbidden}<" not in _week_js)


# ── §2 · Every new backend module is READ-ONLY ──────────────────────────────

_section("§2 · §15 the new backend work writes nothing")

_MUTATIONS = ("db.add(", "db.add_all(", "db.commit()", "db.delete(", "db.flush()",
              "db.merge(", "INSERT ", "UPDATE ", "DELETE ", "session.add(")

for _mod in ("reports/matchup_preview_read_model.py",
             "betting/pool_result_view.py"):
    _src = _code_only(_read(*_mod.split("/")))
    _hits = [m for m in _MUTATIONS if m in _src]
    _assert(f"{_mod} performs no mutation", not _hits, ", ".join(_hits))
    _assert(f"{_mod} issues no write SQL",
            not re.search(r"text\(\s*[\"'](?!\s*SELECT)", _src, re.I))

# §15's list of systems Wave 4 may not modify. Anything in it that this branch
# touched is a scope breach regardless of how correct the change looks.
_FROZEN = [
    "beefs/beef_engine.py",
    "beefs/proposal_lifecycle.py",
    "economy/challenge_funding.py",
    "betting/pool_claims.py",
    "betting/pool_settlement.py",
    "betting/settlement_engine.py",
    "betting/pool_engine.py",
]

def _wave4_changed_files() -> list[str]:
    """The files WAVE 4 changed — not the files this branch changed.

    Diffing against `master` would flag every wagering module the branch
    has legitimately touched across the earlier sprints, so the guard
    would fail forever and mean nothing. Wave 4 is the working tree, plus
    — once it is committed — the commit that carries its name.
    """
    def _git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True, check=False).stdout

    files = set(_git("diff", "--name-only", "HEAD").split())
    subject = _git("log", "-1", "--format=%s").strip()
    if subject.startswith("UIRECON Wave 4"):
        files |= set(_git("show", "--name-only", "--format=", "HEAD").split())
    return sorted(files)


#: Frozen modules a LATER wave was explicitly authorised to change, and the one
#: change each was authorised to make. An entry here is not a hole in the guard:
#: the wave that owns it pins what the change may contain, and this list exists
#: so the exception has to be WRITTEN DOWN rather than discovered as a silent
#: pass. Wave 4's own scope is unchanged — nothing below was touched by ad5aca0.
_AUTHORISED_LATER = {
    # UIRECON Wave 4 demo matchup visibility reconciliation. `issue_challenge`
    # never filled `beef_challenges.league_id`, so every matchup the showcase
    # played was a wager no league owned and the Action read model — which
    # filters by league, correctly — reported none of them. The authorised
    # change is the league derivation and the same-league refusal, and
    # `test_uirecon_wave4_demo_visibility.py` asserts it is ONLY that: no odds,
    # stake, payout or economic expression may be added to that file.
    "beefs/beef_engine.py",
    # FINAL POR WP-5 — league-level minted championship pots. Four sites moved
    # terminal Prop Pool money by naming `championship:{league}` as a literal;
    # §13 makes a terminal remainder a FantasyStakes Championship Pot addition,
    # so all four now ask one resolver,
    # `economy.championship_pots.terminal_pool_destination`, which answers by
    # ruleset era. The authorised change is the DESTINATION of an already
    # existing posting and nothing else: no new sweep, no new trigger, no
    # amount recomputed, and the legacy era resolves the identical account it
    # always did. `test_finalpor_wp5_pot_architecture.py` F8 pins it — it
    # requires the literal to be absent from this module, requires the resolver
    # to be imported, and posts a real remainder end to end under both eras.
    "betting/pool_settlement.py",
}

try:
    _breach = sorted((set(_FROZEN) - _AUTHORISED_LATER)
                     & set(_wave4_changed_files()))
    _assert("no frozen wagering, settlement or ledger module was touched",
            not _breach, ", ".join(_breach))
except Exception as _exc:                                  # pragma: no cover
    _assert("the frozen-module check could run", False, str(_exc))


# ── §3 · The preview CONSUMES the pricing output ────────────────────────────

_section("§3 · §4 the preview reuses the existing pricing, and re-derives none")

_prev_src = _code_only(_read("reports", "matchup_preview_read_model.py"))

_assert("the read model never calls the pricing engine itself",
        "compute_market_board" not in _prev_src)
_assert("the read model runs no simulation",
        "simulate" not in _prev_src and "monte" not in _prev_src.lower())
_assert("the board is supplied by the caller, not fetched",
        "board=None" in _prev_src or "board: " in _prev_src)

# THE ONLY ARITHMETIC IS ON THE INPUT. Summing the projections the read model
# was handed is reporting its own input; anything that produced a LINE would be
# a second odds model.
_assert("no line, spread or total is computed here",
        not re.search(r"\b(spread|total|moneyline)\s*=\s*[^\n]*[-+*/]", _prev_src))

_api_src = _read("api", "main.py")
_assert("the preview route reuses the board the quote route uses",
        "_market_board_or_refuse" in _api_src)
_assert("the preview route reuses the same eligibility field",
        "_versus_subject_field" in _api_src)


# ── §4 · The preview surface reports; it does not calculate ─────────────────

_section("§4 · §7–§8 the narrative is written from served numbers")

_narr = _without_comments(_read("web", "js", "narrative.js"))
_assert("a served-number formatter exists", "function servedNumber" in _narr)
_assert("a served-percent formatter exists", "function servedPercent" in _narr)
_assert("WHY THE LINE has a served path", "whyTheLineFromPreview" in _narr)
_assert("THE READ has a served path", "theReadFromPreview" in _narr)

_prev_js = _without_comments(_read("web", "js", "preview.js"))
_assert("the preview sheet takes a served view",
        "previewSheet(m, ctx" in _prev_js)
_assert("the redundant MATCHUP block is gone",
        "'MATCHUP'" not in _prev_js and '"MATCHUP"' not in _prev_js)
# SUPERSEDED BY REV 1.4 LANE C, AND THE RULE IS UNCHANGED. Wave 4A's parallel
# construction was two `lineupTable()` calls stacked one above the other; §L1
# replaced them with one comparison matrix whose two team cells are drawn by
# `teamCell()`. The assertion is the same assertion — one function draws both
# sides, so neither can acquire a figure or an emphasis the other lacks — and it
# names the function that does it now.
_assert("both teams are drawn by one function",
        _prev_js.count("teamCell(") >= 3)      # one definition, two calls

# THE BINDER HOLDS WHAT IT WAS SERVED AND NOTHING ELSE. A single rounding call,
# a Math.* or a reduce() in this file would mean a figure on screen that no
# server row states — which is the whole failure mode Wave 4 exists to close.
_model = _code_only(_without_comments(_read("web", "js", "preview-model.js")))
for _op, _why in (("toFixed", "rounds a figure"),
                  ("Math.", "calculates"),
                  ("reduce(", "aggregates"),
                  ("parseFloat", "reinterprets a served figure")):
    _assert(f"the preview binder never {_why} ({_op})", _op not in _model)
_assert("the preview binder does not price anything",
        "moneyline =" not in _model and "spread =" not in _model)


# ── §5 · The Prop Pool winner is recovered, never recomputed ────────────────

_section("§5 · §14 the settled Pool reports what settlement wrote")

_pool_src = _code_only(_read("betting", "pool_result_view.py"))
_assert("the winner comes from the winner-distribution posting",
        "WINNER_DISTRIBUTION" in _pool_src and "posting_id" in _pool_src)
_assert("the payout comes from the ledger, not from a share calculation",
        "ledger_entries" in _pool_src)
_assert("the Pool is never re-evaluated",
        "settle_pool" not in _pool_src and "evaluate" not in _pool_src)
_assert("a Pool nobody won says so rather than guessing",
        "no_result" in _pool_src)

_action_src = _code_only(_read("reports", "action_read_model.py"))
_assert("a settled wager's outcome is the row's own status",
        "bet.status" in _action_src and "outcome" in _action_src)
_assert("no wager is re-settled in the read model",
        "settle_week" not in _action_src)


# ── §6 · One section builder, one card shell ────────────────────────────────

_section("§6 · §11–§12 the three Wrap sections are one construction")

_wk = _without_comments(_week_js)
_assert("a single section builder exists", "function resultSection(" in _wk)
_assert("all three sections use it", _wk.count("resultSection({") >= 4)
_assert("a single result-card shell exists", "function resultCard(" in _wk)
_assert("the pixel-capped vertical carousel is gone", "fs-vcar" not in _wk)

_ledger_css = _without_comments(_read("web", "styles", "ledger.css"))
_assert("the stale carousel height cap is gone from the stylesheet",
        "fs-vcar" not in _ledger_css)
_assert("the rail is horizontal and snaps", "scroll-snap-type: x" in _ledger_css)
_assert("one item is exactly one viewport wide",
        "flex: 0 0 100%" in _ledger_css)
_assert("the rail parks on a card, never between two",
        "scroll-snap-stop: always" in _ledger_css)
_assert("no pixel height caps the rail",
        not re.search(r"\.fs-rescar[^{]*\{[^}]*max-height", _ledger_css, re.S))


# ── §7 · The read models, against real data ─────────────────────────────────

_section("§7 · the read models answer from rows, not from arithmetic")


def _pg_url() -> str | None:
    """A disposable PostgreSQL, if the operator has one running.

    NEVER the live database — `TEST_DATABASE_URL` is the repo's own name for a
    throwaway. Absent one, this block reports itself SKIPPED rather than quietly
    certifying SQLite and calling it PostgreSQL.
    """
    return os.environ.get("UIRECON_WAVE4_PG_URL") or os.environ.get(
        "TEST_DATABASE_URL")


def _read_model_checks() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = _pg_url()
    if not url:
        print("  [SKIP] PostgreSQL read-model checks — set TEST_DATABASE_URL "
              "to a disposable database to run them")
        return

    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        from db.schema import PoolInstance
        from betting.pool_result_view import pool_result

        settled = (db.query(PoolInstance)
                   .filter(PoolInstance.settled.is_(True))
                   .order_by(PoolInstance.id).limit(8).all())
        if not settled:
            print("  [SKIP] no settled Pool occurrence in this database")
            return
        _assert("settled Pool occurrences are available to read",
                len(settled) > 0, f"{len(settled)} occurrence(s)")

        for inst in settled:
            view = pool_result(db, instance=inst, viewer_team_id=None)
            _assert(f"occurrence {inst.id} reports the engine's own "
                    f"classification verbatim",
                    view.classification == inst.settlement_classification,
                    f"{view.classification!r}")
            # A distribution that paid must name winners; one that paid nothing
            # must name none. Anything else means the derivation invented a set.
            if view.distributed_cents > 0:
                _assert(f"occurrence {inst.id} — a paid Pool names its winners",
                        len(view.winning_subject_ids) > 0,
                        str(view.winning_subject_ids))
            else:
                _assert(f"occurrence {inst.id} — an unpaid Pool names none",
                        len(view.winning_subject_ids) == 0,
                        str(view.winning_subject_ids))

        # THE VIEWER'S OWN RESULT AGREES WITH THE LEDGER. A GM the distribution
        # credited must read `won`; one it did not must not.
        from db.schema import PoolClaim
        inst = settled[0]
        claims = (db.query(PoolClaim)
                  .filter(PoolClaim.pool_instance_id == inst.id).all())
        for claim in claims[:6]:
            v = pool_result(db, instance=inst, viewer_team_id=claim.team_id)
            paid = v.my_return_cents > 0
            _assert(f"team {claim.team_id} on occurrence {inst.id} — the "
                    f"reported result matches the ledger",
                    (v.my_result == "won") == paid,
                    f"{v.my_result} / {v.my_return_cents}c")

        # NOTHING WAS WRITTEN BY READING. The two read models are called above;
        # a dirty session afterwards would mean one of them mutated state.
        _assert("reading a settled Pool leaves the session clean",
                not db.new and not db.dirty and not db.deleted,
                f"new={len(db.new)} dirty={len(db.dirty)} del={len(db.deleted)}")
    finally:
        db.close()
        engine.dispose()


try:
    _read_model_checks()
except Exception as _exc:                                   # pragma: no cover
    _assert("the PostgreSQL read-model checks could run", False, repr(_exc))


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


_run_node("uirecon_wave4_browser.mjs",
          "UIRECON Wave 4 browser suite (headless Chrome)")


# ── Result ───────────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
if _failures:
    print(f"UIRECON WAVE 4 — {len(_failures)} FAILED")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("UIRECON WAVE 4 — ALL PASSED")
