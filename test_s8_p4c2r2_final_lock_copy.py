#!/usr/bin/env python3
"""
test_s8_p4c2r2_final_lock_copy.py — Sprint 8 P4C-2R2 · Dynamic Final Lock copy.

ONE CLAIM, MADE TWO WAYS. GE-901 / AP-212 fix Final Lock immediately before the
EARLIEST scheduled NFL kickoff involving any player in EITHER final Yahoo
starting lineup covered by the wager. This suite certifies that the governed
trigger really behaves that way, and — against the same rule — that the copy a
GM reads is truthful about it.

WHY THE COPY NEEDS A TEST AT ALL. Two wordings have already been wrong here, and
neither was wrong in a way a reader would notice:

    "at kickoff"                          (S8-P4C-2)  — invites a GM to picture
                                                        their own Sunday matchup
    "when the first of YOUR players ..."  (S8-P4C-2R) — right day, wrong owner:
                                                        the earliest covered
                                                        player may be the
                                                        OPPONENT's

Both understate how soon the opponent's stake is fixed, on the one card where
the timing is the product. A wording assertion is the only thing that catches
that class of error, because every one of them renders perfectly.

THE ADVERSARIAL CASE IS THE POINT. GM A's earliest covered starter plays Sunday;
GM B's plays Thursday. Final Lock must fire THURSDAY — on the opponent's player
— and the copy must remain true for the GM whose own players all play Sunday.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p4c2r2.db')}"

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


def _code_only(js: str) -> str:
    """A JS source with its comments removed.

    BECAUSE THE PROSE EXPLAINS THE VERY MISTAKES IT DOCUMENTS. Both superseded
    wordings are quoted at their sites so the next reader knows why they went;
    a plain substring scan would find those quotations and report the fix as
    absent. Comments are stripped for the same reason P4B moved its Python
    scans onto the AST — there is no JS parser here.
    """
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


print("=" * 74)
print("S8-P4C-2R2 — Dynamic Final Lock copy")
print("=" * 74)


# ══ §4 · the governed trigger, adversarially ════════════════════════════════

_section("§4 · earliest covered kickoff across EITHER lineup")

from sqlalchemy import text  # noqa: E402

from db.schema import Base, NflSchedule, SessionLocal, engine  # noqa: E402
from betting.per_bet_lock import LOCK_SEASON, is_bet_locked_for_gm  # noqa: E402

Base.metadata.create_all(engine)

WEEK = 5
# Real kickoffs only — `_is_real_kickoff` rejects the 05:00-08:00 UTC band that
# placeholder rows occupy, and a placeholder would prove nothing about timing.
THURSDAY = datetime(2026, 10, 1, 0, 20, tzinfo=timezone.utc)   # Thu night game
SUNDAY = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)     # Sun afternoon

# GM A's covered starters are all on Sunday teams; GM B's earliest is Thursday.
A_TEAMS = ["KC", "SF"]
B_TEAMS = ["PHI", "DAL"]

with SessionLocal() as db:
    db.add_all([
        NflSchedule(season=LOCK_SEASON, week=WEEK, home_team="PHI",
                    away_team="DAL", kickoff_utc=THURSDAY),
        NflSchedule(season=LOCK_SEASON, week=WEEK, home_team="KC",
                    away_team="SF", kickoff_utc=SUNDAY),
    ])
    db.commit()

# BETWEEN THE TWO KICKOFFS. Thursday's game has started; Sunday's has not.
BETWEEN = THURSDAY + timedelta(hours=2)

with engine.connect() as conn:
    a_alone = is_bet_locked_for_gm(conn, A_TEAMS, WEEK, BETWEEN,
                                   season=LOCK_SEASON)
    b_alone = is_bet_locked_for_gm(conn, B_TEAMS, WEEK, BETWEEN,
                                   season=LOCK_SEASON)
    # THE WAGER COVERS BOTH LINEUPS, so the trigger reads the union — which is
    # exactly what "any player in either final starting lineup" means.
    covered = is_bet_locked_for_gm(conn, A_TEAMS + B_TEAMS, WEEK, BETWEEN,
                                   season=LOCK_SEASON)

_assert("§4: GM A's own lineup has NOT kicked off yet",
        a_alone.locked is False, f"{a_alone.locked}, {a_alone.reason}")
_assert("§4: GM B's lineup HAS — their Thursday starter is playing",
        b_alone.locked is True and b_alone.reason == "in_progress",
        f"{b_alone.locked}, {b_alone.reason}")
_assert("§4: so the covered wager is LOCKED on the opponent's player",
        covered.locked is True and covered.reason == "in_progress",
        f"{covered.locked}, {covered.reason}")

# AND THE CONVERSE, so the first result is not just "always locked". Before
# Thursday, nothing has kicked off and the wager is open.
with engine.connect() as conn:
    before = is_bet_locked_for_gm(conn, A_TEAMS + B_TEAMS, WEEK,
                                  THURSDAY - timedelta(hours=1),
                                  season=LOCK_SEASON)
_assert("§4: before the EARLIEST covered kickoff the wager is still open",
        before.locked is False, f"{before.locked}, {before.reason}")

_assert("§4: the trigger is the earliest across either lineup, not the GM's own",
        covered.locked and not a_alone.locked,
        "GM A would have had until Sunday if only their own lineup counted")


# ══ §1 · the Action card's Dynamic copy ═════════════════════════════════════

_section("§1 · the Action card tells the truth in that case")

_action_src = open(os.path.join(ROOT, "web", "js", "action.js"),
                   encoding="utf-8").read()
_action_code = _code_only(_action_src)

_assert("§1: the copy names Final Lock",
        "at Final Lock" in _action_code)
_assert("§1: and the earliest COVERED player's game, whoever owns them",
        "first covered player" in _action_code)

# THE THREE FALSEHOODS, BY NAME. Each renders perfectly and each misdescribes
# the protocol, so each is checked for rather than assumed absent.
_assert("§1: it does not claim the GM's OWN first player triggers it",
        "first of your players" not in _action_code
        and "your first player" not in _action_code,
        "the earliest covered player may be the opponent's")
_assert("§1: it does not point at the fantasy matchup's kickoff",
        "at kickoff" not in _action_code)
_assert("§1: it does not imply acceptance reprices",
        not re.search(r"accept\w*\s+(re)?prices", _action_code, re.I))
_assert("§1: it does not imply both sides float",
        not re.search(r"both sides\s+(float|move|re-?price)", _action_code, re.I))

# AND IT STILL SAYS THE TWO THINGS THAT MAKE DYNAMIC DYNAMIC.
_assert("§1: the opponent's stake is the side that may change",
        "Your opponent’s stake is set" in _action_code)
_assert("§1: and the GM's own does not move",
        "Yours does not move." in _action_code)


# ══ §2 · the sheet placeholders ═════════════════════════════════════════════

_section("§2 · the unpriced Derived side")

_assert("§2: the placeholder names Final Lock",
        "'Set at Final Lock'" in _action_code, "no owner implied")
_assert("§2: the superseded placeholder is gone",
        "Set when your first player takes the field" not in _action_code)
_assert("§2: and it is never a number",
        "$0" not in _action_code and "0.00" not in _action_code,
        "no zero, no projection")


# ══ §3 · the composer's governing product copy ══════════════════════════════

_section("§3 · MODE_COPY, corrected on authorisation")

_model_src = open(os.path.join(ROOT, "web", "js", "wager-model.js"),
                  encoding="utf-8").read()
_model_code = _code_only(_model_src)

_assert("§3: the Dynamic copy no longer says 'lock in at kickoff'",
        "lock in at kickoff" not in _model_code)
_assert("§3: it names Final Lock and the first covered player's game",
        "Final Lock" in _model_code and "first " in _model_code
        and "covered player" in _model_code)

# THE SUBSTANTIVE EXPLANATION IS PRESERVED. The correction was to the timing
# clause; a rewrite that also dropped the Anchor/Derived asymmetry or the
# ceiling would have changed the product rather than corrected it.
_assert("§3: the Anchor is still described as fixed",
        re.search(r"Anchor Stake stays fixed", _model_code))
_assert("§3: the Derived side still only comes DOWN",
        "may come down" in _model_code)
_assert("§3: and the acceptance ceiling is still stated",
        "ceiling" in _model_code)
_assert("§3: the Locked explanation is untouched",
        "not repriced on acceptance" in _model_code)


# ══ Consistency ═════════════════════════════════════════════════════════════

_section("Both surfaces describe one trigger")

for name, code in (("action.js", _action_code),
                   ("wager-model.js", _model_code)):
    _assert(f"{name}: says 'covered player', never 'your player'",
            "covered player" in code and "your player" not in code.lower(),
            "neutral as to whose lineup supplies the earliest kickoff")


print("\n" + "=" * 74)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4C-2R2 FINAL LOCK COPY — all assertions PASSED")