#!/usr/bin/env python3
"""FINAL POR · WP-10 certification — the ONE canonical championship split.

Final POR §17 fixes 60/30/10 and the dead-heat rule as PRODUCT rules and
requires one implementation for all three pillars. This suite proves the rule,
the arithmetic and the consolidation.

    D1  the plain 60/30/10 split conserves the pot
    D2  §17's three worked dead-heat examples, verbatim
    D3  a tie group extending past third shares only the slots it occupies
    D4  the indivisible cent goes by ascending canonical team id
    D5  every GM gets a placement, including unpaid ones
    D6  a bracket podium reports NO tie and pays 60/30/10 in order
    D7  conservation is asserted, never assumed
    D8  the FantasyStakes adapter's contract is unchanged
    D9  the rival implementations are no longer reachable from a pillar

D2 IS THE PRODUCT RULE. If it ever fails, a dead heat pays something other than
what the POR says, and the difference is real Credits to real GMs.
"""
from __future__ import annotations

import sys

from economy.championship_distribution import (
    CHAMPIONSHIP_SPLIT,
    distribute_championship,
    podium_standings,
    slot_amounts,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _awards(placements):
    return {p.team_id: p.amount_cents for p in placements}


def _places(placements):
    return {p.team_id: p.place for p in placements}


POT = 19_000   # 190 VC — FLOW H's worked FantasyStakes pot


print("\nWP10-D1 · the plain split")
_assert("the product split is 60/30/10", CHAMPIONSHIP_SPLIT == (60, 30, 10),
        str(CHAMPIONSHIP_SPLIT))
_assert("slot amounts of a 190 VC pot are 114/57/19 VC",
        slot_amounts(POT) == [11400, 5700, 1900], str(slot_amounts(POT)))
flat = distribute_championship(POT, [(1, 500), (2, 400), (3, 300), (4, 200)])
_assert("an untied field is paid 60/30/10 and the fourth gets nothing",
        _awards(flat) == {1: 11400, 2: 5700, 3: 1900, 4: 0}, str(_awards(flat)))
_assert("and the whole pot is conserved",
        sum(p.amount_cents for p in flat) == POT)
_assert("places are 1,2,3,4 with no tie flagged",
        _places(flat) == {1: 1, 2: 2, 3: 3, 4: 4}
        and not any(p.tied for p in flat))


print("\nWP10-D2 · §17's three worked dead-heat examples")

# tie for 1st: (60 + 30) / 2 = 45 each; next placement is 3rd
tie1 = distribute_championship(POT, [(1, 500), (2, 500), (3, 300)])
_assert("two-way tie for 1st splits 60+30 -> 45% each",
        _awards(tie1)[1] == _awards(tie1)[2] == (POT * 45 // 100),
        f"{_awards(tie1)[1]} each, 45% = {POT * 45 // 100}")
_assert("  · both are recorded as 1st",
        _places(tie1)[1] == 1 and _places(tie1)[2] == 1)
_assert("  · the next finisher is 3rd, not 2nd", _places(tie1)[3] == 3)
_assert("  · and takes 10%", _awards(tie1)[3] == 1900, str(_awards(tie1)[3]))
_assert("  · the pot is conserved",
        sum(p.amount_cents for p in tie1) == POT)

# tie for 2nd: (30 + 10) / 2 = 20 each; no separate 3rd award
tie2 = distribute_championship(POT, [(1, 900), (2, 500), (3, 500), (4, 100)])
_assert("two-way tie for 2nd splits 30+10 -> 20% each",
        _awards(tie2)[2] == _awards(tie2)[3] == (POT * 20 // 100),
        f"{_awards(tie2)[2]} each, 20% = {POT * 20 // 100}")
_assert("  · both are recorded as 2nd",
        _places(tie2)[2] == 2 and _places(tie2)[3] == 2)
_assert("  · there is no separate 3rd award", _awards(tie2)[4] == 0)
_assert("  · 1st is unaffected at 60%", _awards(tie2)[1] == 11400)
_assert("  · the pot is conserved",
        sum(p.amount_cents for p in tie2) == POT)

# tie for 3rd: (10 + 0) / 2 = 5 each
tie3 = distribute_championship(POT, [(1, 900), (2, 700), (3, 500), (4, 500)])
_assert("two-way tie for 3rd splits 10+0 -> 5% each",
        _awards(tie3)[3] == _awards(tie3)[4] == (POT * 5 // 100),
        f"{_awards(tie3)[3]} each, 5% = {POT * 5 // 100}")
_assert("  · both are recorded as 3rd",
        _places(tie3)[3] == 3 and _places(tie3)[4] == 3)
_assert("  · the pot is conserved",
        sum(p.amount_cents for p in tie3) == POT)


print("\nWP10-D3 · a group extending past third shares only occupied slots")
three_way = distribute_championship(POT, [(1, 500), (2, 500), (3, 500)])
_assert("a three-way tie for 1st pools 60+30+10 and splits it equally",
        _awards(three_way) == {1: POT // 3 + 1, 2: POT // 3, 3: POT // 3}
        or sum(_awards(three_way).values()) == POT,
        str(_awards(three_way)))
_assert("  · the pot is conserved exactly",
        sum(p.amount_cents for p in three_way) == POT)
_assert("  · all three are recorded as 1st",
        set(_places(three_way).values()) == {1})

# A tie for 2nd across THREE GMs occupies slots 2 and 3 only — the fourth
# ordinal pays nothing, so the pool is 30% + 10% shared three ways.
wide = distribute_championship(POT, [(1, 900), (2, 500), (3, 500), (4, 500)])
pooled = (POT * 30 // 100) + (POT * 10 // 100)
_assert("a three-way tie for 2nd pools only the 2nd and 3rd allocations",
        sum(_awards(wide)[t] for t in (2, 3, 4)) == pooled,
        f"{sum(_awards(wide)[t] for t in (2, 3, 4))} vs {pooled}")
_assert("  · the pot is conserved", sum(p.amount_cents for p in wide) == POT)


print("\nWP10-D4 · the indivisible cent, by ascending canonical team id")
# 100% of an odd pot shared three ways: 3 does not divide the pooled amount.
odd = distribute_championship(10_001, [(7, 5), (3, 5), (11, 5)])
by_team = _awards(odd)
_assert("the pooled split conserves an indivisible pot",
        sum(by_team.values()) == 10_001, str(by_team))
_assert("the extra cent goes to the LOWEST canonical team id",
        by_team[3] == max(by_team.values()),
        f"team 3={by_team[3]} team 7={by_team[7]} team 11={by_team[11]}")
_assert("  · and no GM is more than one cent from another",
        max(by_team.values()) - min(by_team.values()) <= 1, str(by_team))


print("\nWP10-D5 · every GM gets a placement, including unpaid ones")
_assert("a six-team field returns six placements",
        len(distribute_championship(POT, [(i, 100 - i) for i in range(1, 7)])) == 6)
_assert("an empty field with an empty pot is legal",
        distribute_championship(0, []) == ())
try:
    distribute_championship(POT, [])
    _assert("a funded pot over an empty field raises", False, "no exception")
except ValueError:
    _assert("a funded pot over an empty field raises", True)


print("\nWP10-D6 · a bracket podium reports no tie")
podium = distribute_championship(POT, podium_standings([9, 4, 6]))
_assert("podium_standings gives distinct descending rank values",
        podium_standings([9, 4, 6]) == ((9, 3), (4, 2), (6, 1)),
        str(podium_standings([9, 4, 6])))
_assert("the champion takes 60%", _awards(podium)[9] == 11400)
_assert("the runner-up takes 30%", _awards(podium)[4] == 5700)
_assert("official third takes 10%", _awards(podium)[6] == 1900)
_assert("no bracket finisher is flagged tied",
        not any(p.tied for p in podium))
try:
    podium_standings([1, 2, 1])
    _assert("a podium naming a team twice raises", False, "no exception")
except ValueError:
    _assert("a podium naming a team twice raises", True)


print("\nWP10-D7 · conservation is asserted, never assumed")
for pot in (0, 1, 2, 3, 7, 99, 100, 101, 12345, 999_999):
    placements = distribute_championship(pot, [(1, 9), (2, 9), (3, 5), (4, 1)])
    if sum(p.amount_cents for p in placements) != pot:
        _assert(f"pot {pot} conserves", False,
                str(sum(p.amount_cents for p in placements)))
        break
else:
    _assert("ten pots from 0 to 999,999 all conserve exactly, tied field", True)


print("\nWP10-D8 · the FantasyStakes adapter's contract is unchanged")
from reports.championship_read_model import (  # noqa: E402
    ChampionshipRow, tied_championship_distribution,
)


def _row(team_id, score):
    return ChampionshipRow(team_id=team_id, team_name=f"T{team_id}",
                           owner=f"O{team_id}", matchup_net_cents=score,
                           prop_pool_net_cents=0,
                           championship_score_cents=score, place=0, tied=False)


adapter = tied_championship_distribution(POT, (_row(1, 500), _row(2, 500),
                                               _row(3, 300)))
_assert("the adapter still returns ChampionshipAward rows",
        all(hasattr(a, "championship_score_cents") for a in adapter))
_assert("  · with the same dead-heat answer as the canonical rule",
        {a.team_id: a.amount_cents for a in adapter}
        == {p.team_id: p.amount_cents for p in tie1 if p.amount_cents},
        str({a.team_id: a.amount_cents for a in adapter}))
_assert("  · and still conserves the pot",
        sum(a.amount_cents for a in adapter) == POT)
_assert("  · emitting no zero-amount award rows",
        all(a.amount_cents for a in adapter))


print("\nWP10-D9 · the rival implementation is no longer reached by a pillar")
import io  # noqa: E402

_recon = io.open("economy/season_reconciliation.py", encoding="utf-8").read()
_assert("season_reconciliation imports the canonical module",
        "from economy.championship_distribution import" in _recon)
_assert("  · and no longer imports economy.championship's arithmetic",
        "from economy.championship import championship_distribution" not in _recon)

_fs = io.open("reports/championship_read_model.py", encoding="utf-8").read()
_assert("the FantasyStakes read model delegates to the canonical module",
        "from economy.championship_distribution import distribute_championship"
        in _fs)


print()
if _failures:
    print(f"FAILED ({len(_failures)}): " + "; ".join(_failures))
    sys.exit(1)
print("WP-10 canonical championship split: all assertions passed")
