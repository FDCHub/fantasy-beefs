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
