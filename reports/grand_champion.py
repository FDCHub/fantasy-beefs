"""RC2 Grand Champion recognition.

Grand Champion is an unfunded season-ending recognition based only on the Yahoo
Championship podium and the FantasyStakes Championship podium. Regular-season
Points Champion / Skunk recognition is intentionally outside this calculation.

When a component championship contains a tie, the Grand Champion points for the
ordinal places occupied by that tied group are pooled and divided equally among
all GMs in the tie. This mirrors the locked FantasyStakes championship tied-podium
rule and preserves the total component points available.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

POINTS_BY_PLACE = {1: 3, 2: 2, 3: 1}


@dataclass(frozen=True)
class ChampionshipFinish:
    team_id: int
    place: int


@dataclass(frozen=True)
class GrandChampionRow:
    team_id: int
    yahoo_points: Fraction
    fantasystakes_points: Fraction

    @property
    def combined_points(self) -> Fraction:
        return self.yahoo_points + self.fantasystakes_points


@dataclass(frozen=True)
class GrandChampionResult:
    rows: tuple[GrandChampionRow, ...]
    champion_team_ids: tuple[int, ...]

    @property
    def co_champions(self) -> bool:
        return len(self.champion_team_ids) > 1


def _component_points(finishes: tuple[ChampionshipFinish, ...]) -> dict[int, Fraction]:
    """Return exact Grand Champion points for one component championship.

    Competition-style places are expected: a two-way tie for first is represented
    as places 1, 1 and the next finisher is place 3. A tied group beginning at
    place ``p`` occupies ordinal slots ``p .. p + group_size - 1``. Only the
    1st/2nd/3rd slots carry Grand Champion points; slots beyond third contribute
    zero. The occupied points are pooled and split equally across the tied group.
    """
    team_ids = [finish.team_id for finish in finishes]
    if len(team_ids) != len(set(team_ids)):
        raise ValueError("component championship contains duplicate team_id")
    if any(finish.place < 1 for finish in finishes):
        raise ValueError("component championship place must be >= 1")

    by_place: dict[int, list[int]] = {}
    for finish in finishes:
        by_place.setdefault(finish.place, []).append(finish.team_id)

    points: dict[int, Fraction] = {}
    occupied_until = 0
    for place in sorted(by_place):
        team_group = sorted(by_place[place])
        if place <= occupied_until:
            raise ValueError(
                "component championship places overlap a preceding tied group"
            )
        occupied_slots = range(place, place + len(team_group))
        pool = sum(POINTS_BY_PLACE.get(slot, 0) for slot in occupied_slots)
        share = Fraction(pool, len(team_group))
        for team_id in team_group:
            points[team_id] = share
        occupied_until = place + len(team_group) - 1

    return points


def calculate_grand_champion(
    *, yahoo_finishes: tuple[ChampionshipFinish, ...],
    fantasystakes_finishes: tuple[ChampionshipFinish, ...],
) -> GrandChampionResult:
    """Combine both component championships; equal totals are co-Grand Champions."""
    yahoo = _component_points(yahoo_finishes)
    fs = _component_points(fantasystakes_finishes)
    team_ids = sorted(set(yahoo) | set(fs))
    rows = tuple(
        sorted(
            (
                GrandChampionRow(
                    team_id=team_id,
                    yahoo_points=yahoo.get(team_id, Fraction(0, 1)),
                    fantasystakes_points=fs.get(team_id, Fraction(0, 1)),
                )
                for team_id in team_ids
            ),
            key=lambda row: (-row.combined_points, row.team_id),
        )
    )
    if not rows:
        return GrandChampionResult(rows=(), champion_team_ids=())
    high = rows[0].combined_points
    champions = tuple(row.team_id for row in rows if row.combined_points == high)
    return GrandChampionResult(rows=rows, champion_team_ids=champions)
