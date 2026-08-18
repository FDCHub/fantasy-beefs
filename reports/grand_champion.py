"""RC2 Grand Champion recognition.

Grand Champion is an unfunded season-ending recognition based only on the Yahoo
Championship podium and the FantasyStakes Championship podium. Regular-season
Points Champion / Skunk recognition is intentionally outside this calculation.

Component championship ties remain an explicit owner-rule gap. This module will
not invent how 3/2/1 points should be assigned inside a tied component podium.
"""
from __future__ import annotations

from dataclasses import dataclass

POINTS_BY_PLACE = {1: 3, 2: 2, 3: 1}
REASON_COMPONENT_TIE_UNRESOLVED = "GRAND_CHAMPION_COMPONENT_TIE_UNRESOLVED"


class GrandChampionError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


@dataclass(frozen=True)
class ChampionshipFinish:
    team_id: int
    place: int


@dataclass(frozen=True)
class GrandChampionRow:
    team_id: int
    yahoo_points: int
    fantasystakes_points: int

    @property
    def combined_points(self) -> int:
        return self.yahoo_points + self.fantasystakes_points


@dataclass(frozen=True)
class GrandChampionResult:
    rows: tuple[GrandChampionRow, ...]
    champion_team_ids: tuple[int, ...]

    @property
    def co_champions(self) -> bool:
        return len(self.champion_team_ids) > 1


def _validate_component(name: str, finishes: tuple[ChampionshipFinish, ...]) -> None:
    podium = [f for f in finishes if f.place in POINTS_BY_PLACE]
    places = [f.place for f in podium]
    if len(places) != len(set(places)):
        raise GrandChampionError(
            REASON_COMPONENT_TIE_UNRESOLVED,
            f"{name} podium contains a tie. RC2 POR has not yet ruled how a tied "
            f"component championship contributes 3/2/1 Grand Champion points.")


def calculate_grand_champion(
    *, yahoo_finishes: tuple[ChampionshipFinish, ...],
    fantasystakes_finishes: tuple[ChampionshipFinish, ...],
) -> GrandChampionResult:
    """Combine untied component podiums using 3/2/1; equal totals are co-champions."""
    _validate_component("Yahoo Championship", yahoo_finishes)
    _validate_component("FantasyStakes Championship", fantasystakes_finishes)

    yahoo = {f.team_id: POINTS_BY_PLACE.get(f.place, 0) for f in yahoo_finishes}
    fs = {f.team_id: POINTS_BY_PLACE.get(f.place, 0) for f in fantasystakes_finishes}
    team_ids = sorted(set(yahoo) | set(fs))
    rows = tuple(sorted(
        (GrandChampionRow(team_id=t, yahoo_points=yahoo.get(t, 0),
                          fantasystakes_points=fs.get(t, 0)) for t in team_ids),
        key=lambda r: (-r.combined_points, r.team_id)))
    if not rows:
        return GrandChampionResult(rows=(), champion_team_ids=())
    high = rows[0].combined_points
    champions = tuple(r.team_id for r in rows if r.combined_points == high)
    return GrandChampionResult(rows=rows, champion_team_ids=champions)
