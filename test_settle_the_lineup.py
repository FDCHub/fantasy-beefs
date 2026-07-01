"""
test_settle_the_lineup.py  —  Pure-logic tests for _lineup_winner().

No database. No API calls. Hand-built in-memory fixtures only.
Tests the settlement logic directly, not the DB query layer.

Scenarios:
  1. Clean win on count       — A beats more projections than B
  2. Tie resolved by diff     — count tied, A has higher sum(actual - projected)
  3. Full push                — count tied AND differential tied
  4. Missing-data exclusion   — one player with projected_points=None on A's side
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dataclasses import dataclass
from betting.settlement_engine import LineupPlayer, _lineup_winner

WEEK = 7   # arbitrary — only matters for warning messages

# ── Helpers ───────────────────────────────────────────────────────────────────

def _p(name: str, actual: float, projected: float | None) -> LineupPlayer:
    return LineupPlayer(
        player_id        = hash(name) % 10_000,
        player_name      = name,
        actual_points    = actual,
        projected_points = projected,
    )


def _assert(scenario: str, result: str, expected: str) -> None:
    ok = result == expected
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {scenario}")
    if not ok:
        print(f"         expected={expected!r}  got={result!r}")


# ── Scenario 1: Clean win on count ────────────────────────────────────────────
# Team A: 5 of 9 starters beat projection
# Team B: 3 of 9 starters beat projection
# Expected: 'a' wins (no tiebreaker needed)

team_a_s1 = [
    _p("A-QB",  30.0, 22.0),   # beats (+8)
    _p("A-RB1", 18.0, 12.0),   # beats (+6)
    _p("A-RB2",  9.0, 10.0),   # loses (−1)
    _p("A-WR1", 15.0, 11.0),   # beats (+4)
    _p("A-WR2",  7.0,  9.0),   # loses (−2)
    _p("A-WR3", 14.0, 13.0),   # beats (+1)
    _p("A-TE",   4.0,  8.0),   # loses (−4)
    _p("A-FLEX",12.0, 10.0),   # beats (+2)
    _p("A-K",    6.0,  7.0),   # loses (−1)
]

team_b_s1 = [
    _p("B-QB",  20.0, 25.0),   # loses (−5)
    _p("B-RB1", 14.0, 11.0),   # beats (+3)
    _p("B-RB2", 10.0, 13.0),   # loses (−3)
    _p("B-WR1", 18.0, 15.0),   # beats (+3)
    _p("B-WR2",  5.0,  8.0),   # loses (−3)
    _p("B-WR3",  9.0, 10.0),   # loses (−1)
    _p("B-TE",  11.0,  9.0),   # beats (+2)
    _p("B-FLEX", 6.0,  8.0),   # loses (−2)
    _p("B-K",    8.0,  9.0),   # loses (−1)
]
# A beats: 5  B beats: 3  → A wins on count

# ── Scenario 2: Tie resolved by differential ──────────────────────────────────
# Both teams: 4 of 9 starters beat projection
# A total diff = +5.0,  B total diff = +1.0  → A wins on tiebreaker

team_a_s2 = [
    _p("A-QB",  25.0, 20.0),   # beats (+5)
    _p("A-RB1", 15.0, 12.0),   # beats (+3)
    _p("A-RB2",  8.0, 10.0),   # loses (−2)
    _p("A-WR1", 16.0, 14.0),   # beats (+2)
    _p("A-WR2",  6.0,  9.0),   # loses (−3)
    _p("A-WR3", 12.0, 10.0),   # beats (+2)
    _p("A-TE",   4.0,  8.0),   # loses (−4)
    _p("A-FLEX", 7.0,  9.0),   # loses (−2)
    _p("A-K",    5.0,  7.0),   # loses (−2)
]
# A: count=4, diff = 5+3−2+2−3+2−4−2−2 = -1   wait let me recalculate
# 5+3-2+2-3+2-4-2-2 = 5+3=8, 8-2=6, 6+2=8, 8-3=5, 5+2=7, 7-4=3, 3-2=1, 1-2=-1
# Hmm that gives -1. Let me fix so A diff > B diff clearly.

team_a_s2 = [
    _p("A-QB",  30.0, 20.0),   # beats (+10)
    _p("A-RB1", 15.0, 12.0),   # beats (+3)
    _p("A-RB2",  9.0, 11.0),   # loses  (−2)
    _p("A-WR1", 14.0, 10.0),   # beats  (+4)
    _p("A-WR2",  6.0,  8.0),   # loses  (−2)
    _p("A-WR3", 11.0,  9.0),   # beats  (+2)
    _p("A-TE",   5.0,  8.0),   # loses  (−3)
    _p("A-FLEX", 7.0, 10.0),   # loses  (−3)
    _p("A-K",    5.0,  7.0),   # loses  (−2)
]
# A: beats QB, RB1, WR1, WR3 → count=4; diff = 10+3−2+4−2+2−3−3−2 = +7

team_b_s2 = [
    _p("B-QB",  22.0, 20.0),   # beats (+2)
    _p("B-RB1", 11.0,  9.0),   # beats (+2)
    _p("B-RB2",  8.0, 10.0),   # loses (−2)
    _p("B-WR1", 14.0, 12.0),   # beats (+2)
    _p("B-WR2",  6.0,  8.0),   # loses (−2)
    _p("B-WR3", 10.0,  8.0),   # beats (+2)
    _p("B-TE",   4.0,  7.0),   # loses (−3)
    _p("B-FLEX", 6.0,  9.0),   # loses (−3)
    _p("B-K",    5.0,  8.0),   # loses (−3)
]
# B: beats QB, RB1, WR1, WR3 → count=4; diff = 2+2−2+2−2+2−3−3−3 = −5
# A diff=+7 > B diff=−5 → A wins tiebreaker

# ── Scenario 3: Full push ─────────────────────────────────────────────────────
# Both count=4, both diff=0.0 exactly → push

team_a_s3 = [
    _p("A-QB",  25.0, 20.0),   # beats (+5)
    _p("A-RB1", 10.0,  8.0),   # beats (+2)
    _p("A-RB2",  8.0, 10.0),   # loses (−2)
    _p("A-WR1", 14.0, 11.0),   # beats (+3)
    _p("A-WR2",  6.0,  7.0),   # loses (−1)
    _p("A-WR3", 12.0, 10.0),   # beats (+2)
    _p("A-TE",   4.0, 11.0),   # loses (−7)
    _p("A-FLEX", 9.0, 11.0),   # loses (−2)
    _p("A-K",    6.0,  6.0),   # loses  (0)  — equal, not a beat
]
# A: count=4 (QB, RB1, WR1, WR3); diff = 5+2−2+3−1+2−7−2+0 = 0

team_b_s3 = [
    _p("B-QB",  22.0, 18.0),   # beats (+4)
    _p("B-RB1", 12.0, 10.0),   # beats (+2)
    _p("B-RB2",  7.0,  9.0),   # loses (−2)
    _p("B-WR1", 15.0, 11.0),   # beats (+4)
    _p("B-WR2",  5.0,  7.0),   # loses (−2)
    _p("B-WR3", 11.0,  9.0),   # beats (+2)
    _p("B-TE",   3.0,  9.0),   # loses (−6)
    _p("B-FLEX", 8.0, 10.0),   # loses (−2)
    _p("B-K",    5.0,  5.0),   # loses  (0)  — equal
]
# B: count=4 (QB, RB1, WR1, WR3); diff = 4+2−2+4−2+2−6−2+0 = 0
# count tied (4=4), diff tied (0=0) → push

# ── Scenario 4: Missing-data exclusion ───────────────────────────────────────
# A's FLEX starter has projected_points=None → excluded from A's count + diff
# Remaining A starters: 8 players, 4 beat projection
# B starters: 9 players, 3 beat projection → A wins (4 > 3)
# Also confirms: warning is printed and settlement doesn't crash

team_a_s4 = [
    _p("A-QB",  28.0, 22.0),   # beats (+6)
    _p("A-RB1", 14.0, 12.0),   # beats (+2)
    _p("A-RB2",  9.0, 11.0),   # loses (−2)
    _p("A-WR1", 15.0, 13.0),   # beats (+2)
    _p("A-WR2",  6.0,  8.0),   # loses (−2)
    _p("A-WR3", 11.0,  9.0),   # beats (+2)
    _p("A-TE",   4.0,  7.0),   # loses (−3)
    _p("A-FLEX", 0.0, None),    # projected=None → EXCLUDED (warning expected)
    _p("A-K",    5.0,  6.0),   # loses (−1)
]
# A: 8 eligible (FLEX excluded); beats = QB, RB1, WR1, WR3 → count=4

team_b_s4 = [
    _p("B-QB",  20.0, 22.0),   # loses (−2)
    _p("B-RB1", 14.0, 12.0),   # beats (+2)
    _p("B-RB2",  9.0, 11.0),   # loses (−2)
    _p("B-WR1", 15.0, 13.0),   # beats (+2)
    _p("B-WR2",  6.0,  8.0),   # loses (−2)
    _p("B-WR3",  8.0, 10.0),   # loses (−2)
    _p("B-TE",  10.0,  9.0),   # beats (+1)
    _p("B-FLEX", 7.0,  8.0),   # loses (−1)
    _p("B-K",    5.0,  6.0),   # loses (−1)
]
# B: 9 eligible; beats = RB1, WR1, TE → count=3
# A count=4 > B count=3 → A wins (even with one player excluded)


# ── Run tests ─────────────────────────────────────────────────────────────────

def main() -> None:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

    print("\ntest_settle_the_lineup.py")
    print("=" * 50)
    failures = 0

    # 1 — clean win on count
    print("\nScenario 1: Clean win on count")
    r1 = _lineup_winner(team_a_s1, team_b_s1, WEEK)
    _assert("A beats 5/9, B beats 3/9 → A wins", r1, "a")
    if r1 != "a":
        failures += 1

    # 2 — tie resolved by differential
    print("\nScenario 2: Tie resolved by differential")
    r2 = _lineup_winner(team_a_s2, team_b_s2, WEEK)
    _assert("Both 4/9, A diff=+7 B diff=-5 → A wins on tiebreaker", r2, "a")
    if r2 != "a":
        failures += 1

    # 3 — full push
    print("\nScenario 3: Full push")
    r3 = _lineup_winner(team_a_s3, team_b_s3, WEEK)
    _assert("Both 4/9, both diff=0.0 → push", r3, "push")
    if r3 != "push":
        failures += 1

    # 4 — missing-data exclusion (warning output expected below)
    print("\nScenario 4: Missing-data exclusion (one player with projected=None)")
    r4 = _lineup_winner(team_a_s4, team_b_s4, WEEK)
    _assert("A has 4/8 eligible, B has 3/9 → A wins (FLEX excluded with warning)", r4, "a")
    if r4 != "a":
        failures += 1

    print()
    print("=" * 50)
    if failures == 0:
        print("All 4 scenarios PASSED.")
    else:
        print(f"{failures} scenario(s) FAILED.")
    print()
    return failures


if __name__ == "__main__":
    sys.exit(main())
