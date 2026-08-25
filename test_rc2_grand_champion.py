#!/usr/bin/env python3
"""RC2 Grand Champion certification."""
from __future__ import annotations

import sys
from fractions import Fraction

from reports.grand_champion import ChampionshipFinish, calculate_grand_champion

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def F(team_id: int, place: int) -> ChampionshipFinish:
    return ChampionshipFinish(team_id=team_id, place=place)


print("\nRC2-GC-1 · untied component scoring")
result = calculate_grand_champion(
    yahoo_finishes=(F(1, 1), F(2, 2), F(3, 3)),
    fantasystakes_finishes=(F(2, 1), F(1, 2), F(4, 3)),
)
rows = {row.team_id: row for row in result.rows}
_assert("3/2/1 applies independently to both championships",
        rows[1].yahoo_points == 3 and rows[1].fantasystakes_points == 2
        and rows[2].yahoo_points == 2 and rows[2].fantasystakes_points == 3,
        str(result.rows))
_assert("equal highest combined scores produce co-Grand Champions",
        result.champion_team_ids == (1, 2) and result.co_champions,
        str(result.champion_team_ids))


print("\nRC2-GC-2 · tied component point pooling")
first_tie = calculate_grand_champion(
    yahoo_finishes=(F(1, 1), F(2, 1), F(3, 3)),
    fantasystakes_finishes=(),
)
rows = {row.team_id: row for row in first_tie.rows}
_assert("two-way tie for first splits 3+2 equally",
        rows[1].yahoo_points == Fraction(5, 2)
        and rows[2].yahoo_points == Fraction(5, 2)
        and rows[3].yahoo_points == 1,
        str(first_tie.rows))

second_tie = calculate_grand_champion(
    yahoo_finishes=(F(1, 1), F(2, 2), F(3, 2)),
    fantasystakes_finishes=(),
)
rows = {row.team_id: row for row in second_tie.rows}
_assert("two-way tie for second splits 2+1 equally",
        rows[2].yahoo_points == Fraction(3, 2)
        and rows[3].yahoo_points == Fraction(3, 2),
        str(second_tie.rows))

three_first = calculate_grand_champion(
    yahoo_finishes=(F(1, 1), F(2, 1), F(3, 1)),
    fantasystakes_finishes=(),
)
rows = {row.team_id: row for row in three_first.rows}
_assert("three-way tie for first splits all six component points equally",
        all(rows[t].yahoo_points == 2 for t in (1, 2, 3)),
        str(three_first.rows))

four_first = calculate_grand_champion(
    yahoo_finishes=(F(1, 1), F(2, 1), F(3, 1), F(4, 1)),
    fantasystakes_finishes=(),
)
rows = {row.team_id: row for row in four_first.rows}
_assert("tie extending beyond third shares only six available component points",
        all(rows[t].yahoo_points == Fraction(3, 2) for t in (1, 2, 3, 4))
        and sum(row.yahoo_points for row in rows.values()) == 6,
        str(four_first.rows))


print("\nRC2-GC-3 · combined tied championships")
combined = calculate_grand_champion(
    yahoo_finishes=(F(1, 1), F(2, 1), F(3, 3)),
    fantasystakes_finishes=(F(3, 1), F(1, 2), F(2, 3)),
)
rows = {row.team_id: row for row in combined.rows}
_assert("fractional component points combine exactly without rounding",
        rows[1].combined_points == Fraction(9, 2)
        and rows[2].combined_points == Fraction(7, 2)
        and rows[3].combined_points == 4,
        str(combined.rows))
_assert("Grand Champion is highest exact combined score",
        combined.champion_team_ids == (1,), str(combined.champion_team_ids))


print("\nRC2-GC-4 · malformed component protection")
try:
    calculate_grand_champion(
        yahoo_finishes=(F(1, 1), F(2, 1), F(3, 2)),
        fantasystakes_finishes=(),
    )
except ValueError:
    overlap_rejected = True
else:
    overlap_rejected = False
_assert("overlapping place after a tie is rejected", overlap_rejected)

try:
    calculate_grand_champion(
        yahoo_finishes=(F(1, 1), F(1, 2)),
        fantasystakes_finishes=(),
    )
except ValueError:
    duplicate_rejected = True
else:
    duplicate_rejected = False
_assert("duplicate team in one component is rejected", duplicate_rejected)


print(f"\n{'=' * 64}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for failure in _failures:
        print(f"  - {failure}")
    sys.exit(1)

print("PASS: RC2 Grand Champion certification")


# ── RC2 A3.2 · the locked FantasyStakes Championship Score tiebreaker ────────
#
# Step 1 scores the component finishes 3/2/1 with exact fractional pooling for a
# tied component. Step 2 breaks a tie on combined points using the authoritative
# FantasyStakes CHAMPIONSHIP SCORE — the frozen realized-net figure, never a
# wallet balance. Step 3 keeps a surviving tie as a real co-championship.
#
# The tiebreak is a SECOND STEP, not a second score: it is applied only to GMs
# already level on points, and it must never reorder anyone else.

print("\nGC-TIE · the FantasyStakes Championship Score tiebreaker")

# The owner's worked example.
#   A: Yahoo 2nd (2) + FantasyStakes 1st (3) = 5, Championship Score +84
#   B: Yahoo 1st (3) + FantasyStakes 2nd (2) = 5, Championship Score +63
_tie = calculate_grand_champion(
    yahoo_finishes=(ChampionshipFinish(2, 1), ChampionshipFinish(1, 2),
                    ChampionshipFinish(3, 3)),
    fantasystakes_finishes=(ChampionshipFinish(1, 1), ChampionshipFinish(2, 2),
                            ChampionshipFinish(3, 3)),
    fantasystakes_scores={1: 8_400, 2: 6_300, 3: 100})
_assert("both candidates really are level on Grand Champion points",
        {r.team_id: str(r.combined_points) for r in _tie.rows if r.team_id in (1, 2)}
        == {1: "5", 2: "5"},
        str({r.team_id: str(r.combined_points) for r in _tie.rows}))
_assert("the higher FantasyStakes Championship Score wins outright",
        _tie.champion_team_ids == (1,) and not _tie.co_champions,
        str(_tie.champion_team_ids))
_assert("and the result records that the tiebreak decided it",
        _tie.tiebreak_used is True)

# Step 3 — level on points AND level on score is a real co-championship.
_still = calculate_grand_champion(
    yahoo_finishes=(ChampionshipFinish(2, 1), ChampionshipFinish(1, 2),
                    ChampionshipFinish(3, 3)),
    fantasystakes_finishes=(ChampionshipFinish(1, 1), ChampionshipFinish(2, 2),
                            ChampionshipFinish(3, 3)),
    fantasystakes_scores={1: 8_400, 2: 8_400, 3: 100})
_assert("equal points and equal Championship Score are co-Grand Champions",
        _still.champion_team_ids == (1, 2) and _still.co_champions,
        str(_still.champion_team_ids))
_assert("a tie the tiebreak did not resolve is not reported as resolved",
        _still.tiebreak_used is False)

# The tiebreak must be irrelevant when nobody is level.
_clear = calculate_grand_champion(
    yahoo_finishes=(ChampionshipFinish(1, 1), ChampionshipFinish(2, 2),
                    ChampionshipFinish(3, 3)),
    fantasystakes_finishes=(ChampionshipFinish(1, 1), ChampionshipFinish(2, 2),
                            ChampionshipFinish(3, 3)),
    fantasystakes_scores={1: 0, 2: 999_999, 3: 500_000})
_assert("a clear points winner wins despite the lowest Championship Score",
        _clear.champion_team_ids == (1,), str(_clear.champion_team_ids))
_assert("no tiebreak is reported when none was needed",
        _clear.tiebreak_used is False)

# Step 1 is untouched: fractional pooling still governs component ties.
_frac = calculate_grand_champion(
    yahoo_finishes=(ChampionshipFinish(1, 1), ChampionshipFinish(2, 1),
                    ChampionshipFinish(3, 3)),
    fantasystakes_finishes=(ChampionshipFinish(1, 1), ChampionshipFinish(2, 2),
                            ChampionshipFinish(3, 3)),
    fantasystakes_scores={1: 100, 2: 100, 3: 100})
_assert("a tied component finish still pools 3+2 into exact halves",
        {r.team_id: str(r.yahoo_points) for r in _frac.rows if r.team_id in (1, 2)}
        == {1: "5/2", 2: "5/2"},
        str({r.team_id: str(r.yahoo_points) for r in _frac.rows}))
_assert("fractional totals survive the tiebreak step",
        all(isinstance(r.combined_points, Fraction) for r in _frac.rows))

# Absent scores decide nothing — the previous behaviour, not a guess.
_blind = calculate_grand_champion(
    yahoo_finishes=(ChampionshipFinish(2, 1), ChampionshipFinish(1, 2),
                    ChampionshipFinish(3, 3)),
    fantasystakes_finishes=(ChampionshipFinish(1, 1), ChampionshipFinish(2, 2),
                            ChampionshipFinish(3, 3)))
_assert("without authoritative scores a tie stays a co-championship",
        _blind.champion_team_ids == (1, 2) and _blind.tiebreak_used is False,
        str(_blind.champion_team_ids))

# The score is carried for explanation only and never enters the points.
_assert("the Championship Score never becomes points",
        all(r.combined_points == r.yahoo_points + r.fantasystakes_points
            for r in _tie.rows))


# The summary above runs before this file's later sections, so a failure added
# after it would print and still exit 0. This is the real gate.
print("")
print("=" * 64)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for _f in _failures:
        print(f"  - {_f}")
    sys.exit(1)
print("PASS: RC2 Grand Champion certification (including the Championship Score tiebreaker)")
