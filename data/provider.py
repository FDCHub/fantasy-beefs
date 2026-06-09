"""DataProvider seam for the Fantasy Beefs decision engine.

MockProvider reads from mock_league.py (repo root).
YahooProvider is a stub; fill when OAuth + DB query layer is ready.
"""

from __future__ import annotations

import random
import sys
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

# Allow running this file directly from repo root or from data/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from odds.monte_carlo import HALF_PPR, ScoringSettings  # noqa: E402  (after sys.path fix)
from mock_league import SCHEDULE, TEAMS  # noqa: E402


# ---------------------------------------------------------------------------
# Extended models for the decision engine
# (Do NOT modify connectors/models.py — those are used by live feed systems.)
# ---------------------------------------------------------------------------

@dataclass
class PlayerProj:
    player_id: int
    name: str
    position: str
    injury_status: str | None   # None | "questionable" | "doubtful" | "out" | "ir"
    projected_pts: float        # league-scoring-adjusted (from ProjectionEngine downstream)


@dataclass
class RosterState:
    team_id: int
    team_name: str
    week: int
    players: list[PlayerProj]


@dataclass
class ScheduleEntry:
    week: int
    home_team_id: int
    away_team_id: int


@dataclass
class LeagueConfig:
    league_id: int
    season: int
    n_teams: int
    playoff_start_week: int
    n_playoff_teams: int
    scoring: ScoringSettings
    roster_slots: dict[str, int]  # e.g. {"QB": 1, "RB": 2, ...}


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class DataProvider(ABC):

    @abstractmethod
    def get_league(self, league_id: int) -> LeagueConfig:
        """League settings: scoring rules, playoff config, roster slot rules."""

    @abstractmethod
    def get_roster(self, team_id: int, week: int) -> RosterState:
        """Full roster for a team as of a given week, with per-player projections."""

    @abstractmethod
    def get_schedule(self, league_id: int) -> list[ScheduleEntry]:
        """Full regular-season + playoff schedule."""

    @abstractmethod
    def get_projections(self, week: int) -> dict[int, PlayerProj]:
        """Projected stats for all rostered players this week, keyed by player_id."""


# ---------------------------------------------------------------------------
# MockProvider helpers
# ---------------------------------------------------------------------------

# Projection ranges (base, spread) by position for half-PPR scoring.
# Seeded from player_id + week — deterministic, not random at runtime.
_PROJ_RANGES: dict[str, tuple[float, float]] = {
    "QB":   (18.0, 14.0),
    "RB":   ( 6.0, 12.0),
    "WR":   ( 6.0, 12.0),
    "TE":   ( 4.0, 10.0),
    "FLEX": ( 6.0, 12.0),
    "K":    ( 5.0,  6.0),
    "DEF":  ( 4.0,  8.0),
}


def _make_player_id(team_id: int, roster_index: int) -> int:
    return team_id * 100 + roster_index


def _mock_projected_pts(player_id: int, position: str, week: int) -> float:
    rng = random.Random(player_id * 100 + week)
    base, spread = _PROJ_RANGES.get(position, (8.0, 10.0))
    return round(base + rng.random() * spread, 1)


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------

class MockProvider(DataProvider):
    """Reads from mock_league.py — deterministic, no DB or network required."""

    _SEASON = 2024
    _ROSTER_SLOTS: dict[str, int] = {
        "QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1,
    }

    def get_league(self, league_id: int) -> LeagueConfig:
        # mock_league.py has 10 teams; spec assumed 12 but findings override
        return LeagueConfig(
            league_id=league_id,
            season=self._SEASON,
            n_teams=len(TEAMS),
            playoff_start_week=15,
            n_playoff_teams=6,
            scoring=HALF_PPR,
            roster_slots=dict(self._ROSTER_SLOTS),
        )

    def get_roster(self, team_id: int, week: int) -> RosterState:
        team = next((t for t in TEAMS if t["id"] == team_id), None)
        if team is None:
            raise ValueError(f"team_id {team_id} not found in mock data")
        players = [
            PlayerProj(
                player_id=_make_player_id(team_id, i),
                name=p["name"],
                position=p["pos"],
                injury_status=None,
                projected_pts=_mock_projected_pts(_make_player_id(team_id, i), p["pos"], week),
            )
            for i, p in enumerate(team["roster"])
        ]
        return RosterState(team_id=team_id, team_name=team["name"], week=week, players=players)

    def get_schedule(self, league_id: int) -> list[ScheduleEntry]:
        # SCHEDULE is 0-indexed into TEAMS list; convert to actual team IDs
        entries: list[ScheduleEntry] = []
        for week_idx, pairs in enumerate(SCHEDULE):
            week = week_idx + 1
            for a_idx, b_idx in pairs:
                entries.append(ScheduleEntry(
                    week=week,
                    home_team_id=TEAMS[a_idx]["id"],
                    away_team_id=TEAMS[b_idx]["id"],
                ))
        return entries

    def get_projections(self, week: int) -> dict[int, PlayerProj]:
        result: dict[int, PlayerProj] = {}
        for team in TEAMS:
            for i, player in enumerate(team["roster"]):
                pid = _make_player_id(team["id"], i)
                result[pid] = PlayerProj(
                    player_id=pid,
                    name=player["name"],
                    position=player["pos"],
                    injury_status=None,
                    projected_pts=_mock_projected_pts(pid, player["pos"], week),
                )
        return result


# ---------------------------------------------------------------------------
# YahooProvider (stub)
# ---------------------------------------------------------------------------

class YahooProvider(DataProvider):
    # TODO: fill when OAuth + DB query layer is ready

    def get_league(self, league_id: int) -> LeagueConfig:
        raise NotImplementedError(
            "YahooProvider.get_league: not implemented — OAuth + DB query layer required"
        )

    def get_roster(self, team_id: int, week: int) -> RosterState:
        raise NotImplementedError(
            "YahooProvider.get_roster: not implemented — OAuth + DB query layer required"
        )

    def get_schedule(self, league_id: int) -> list[ScheduleEntry]:
        raise NotImplementedError(
            "YahooProvider.get_schedule: not implemented — OAuth + DB query layer required"
        )

    def get_projections(self, week: int) -> dict[int, PlayerProj]:
        raise NotImplementedError(
            "YahooProvider.get_projections: not implemented — OAuth + DB query layer required"
        )


# ---------------------------------------------------------------------------
# Acceptance test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    provider = MockProvider()

    # --- get_league ---
    league = provider.get_league(1)
    print(f"LeagueConfig:")
    print(f"  league_id={league.league_id}, season={league.season}, n_teams={league.n_teams}")
    print(f"  playoff_start_week={league.playoff_start_week}, n_playoff_teams={league.n_playoff_teams}")
    print(f"  scoring={league.scoring.scoring_type} (rec={league.scoring.rec_points})")
    print(f"  roster_slots={league.roster_slots}")
    assert isinstance(league, LeagueConfig), "get_league must return LeagueConfig"
    assert league.playoff_start_week == 15, f"Expected playoff_start_week=15, got {league.playoff_start_week}"
    print("  [PASS] get_league\n")

    # --- get_roster ---
    roster = provider.get_roster(1, 7)
    print(f"RosterState: team_id={roster.team_id}, name={roster.team_name!r}, week={roster.week}")
    for p in roster.players[:4]:
        print(f"  pid={p.player_id}  {p.name:<26} {p.position:<5} {p.projected_pts:>5} pts  injury={p.injury_status}")
    assert isinstance(roster, RosterState), "get_roster must return RosterState"
    assert len(roster.players) >= 1, "Roster must have at least one player"
    # determinism check: same call returns same result
    assert provider.get_roster(1, 7).players[0].projected_pts == roster.players[0].projected_pts
    print("  [PASS] get_roster\n")

    # --- get_schedule ---
    schedule = provider.get_schedule(1)
    print(f"Schedule: {len(schedule)} entries")
    for e in schedule[:3]:
        print(f"  week={e.week}: home={e.home_team_id} vs away={e.away_team_id}")
    assert len(schedule) >= 1, "Schedule must have at least one entry"
    wks = {e.week for e in schedule}
    assert 1 in wks and 15 in wks, "Schedule must include week 1 and playoff week 15"
    print("  [PASS] get_schedule\n")

    # --- get_projections ---
    projections = provider.get_projections(7)
    print(f"Projections: {len(projections)} players (week 7)")
    for pid, proj in list(projections.items())[:4]:
        print(f"  pid={pid}  {proj.name:<26} {proj.position:<5} {proj.projected_pts:>5} pts")
    assert isinstance(projections, dict), "get_projections must return dict"
    assert len(projections) > 0, "Projections must be non-empty"
    # determinism check: week 7 vs week 8 should differ
    proj_wk8 = provider.get_projections(8)
    first_pid = next(iter(projections))
    assert projections[first_pid].projected_pts != proj_wk8[first_pid].projected_pts, \
        "Projections should vary by week"
    print("  [PASS] get_projections\n")

    print("All acceptance tests passed.")