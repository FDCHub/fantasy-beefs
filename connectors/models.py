from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class NormalizedPlayer:
    name: str
    position: str  # QB | RB | WR | TE | FLEX | K | DEF


@dataclass
class NormalizedRoster:
    team_id:    int
    team_name:  str
    owner:      str
    email:      str
    players:    list[NormalizedPlayer]
    week_score: float


@dataclass
class NormalizedMatchup:
    week:  int
    home:  NormalizedRoster
    away:  NormalizedRoster

    @property
    def winner(self) -> NormalizedRoster:
        return self.home if self.home.week_score >= self.away.week_score else self.away

    @property
    def loser(self) -> NormalizedRoster:
        return self.away if self.home.week_score >= self.away.week_score else self.home

    @property
    def margin(self) -> float:
        return round(abs(self.home.week_score - self.away.week_score), 2)


@dataclass
class NormalizedLeague:
    season:   int
    week:     int
    matchups: list[NormalizedMatchup]

    @property
    def teams(self) -> list[NormalizedRoster]:
        result = []
        for m in self.matchups:
            result.append(m.home)
            result.append(m.away)
        return result

    @property
    def highest_scorer(self) -> NormalizedRoster:
        return max(self.teams, key=lambda t: t.week_score)

    @property

    def lowest_scorer(self) -> NormalizedRoster:
        return min(self.teams, key=lambda t: t.week_score)
