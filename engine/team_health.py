"""TeamHealthAssembler: assembles SeasonSimulator output into three-horizon TeamHealth.

Imports WeekResult from engine.season_sim — does NOT redefine it.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from dataclasses import dataclass, replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.provider import LeagueConfig, PlayerProj, RosterState
from engine.season_sim import WeekResult


@dataclass
class TeamHealth:
    team_id:               int
    this_week:             WeekResult | None
    rest_of_season:        list[WeekResult]
    playoffs:              list[WeekResult]
    weakest_position:      str
    bye_clusters:          list[int]        # week numbers where 3+ players are on bye
    future_weakness_flags: list[str]        # positions at risk heading into playoffs


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _weakest_position(players: list[PlayerProj]) -> str:
    """Return the position with the lowest mean projected_pts.

    Skips positions with no players. Uses max(count, 1) as denominator
    to guard against ZeroDivisionError on empty buckets.
    """
    pos_pts: dict[str, list[float]] = defaultdict(list)
    for p in players:
        pos_pts[p.position].append(p.projected_pts)

    pos_means = {
        pos: sum(pts) / max(len(pts), 1)
        for pos, pts in pos_pts.items()
        if pts  # skip positions with zero players
    }
    if not pos_means:
        return ""
    return min(pos_means, key=lambda pos: pos_means[pos])


def _bye_clusters(roster: RosterState) -> list[int]:
    """Return the week number if 3 or more roster players are on bye (projected_pts == 0.0).

    The current implementation checks only the snapshot week in the supplied RosterState.
    Post-MVP upgrade: iterate over multi-week roster projections when the provider
    exposes per-week player data across the full remaining schedule.
    """
    bye_count = sum(1 for p in roster.players if p.projected_pts == 0.0)
    return [roster.week] if bye_count >= 3 else []


def _future_weakness_flags(
    players: list[PlayerProj],
    rest_of_season: list[WeekResult],
    playoffs: list[WeekResult],
) -> list[str]:
    """Return positions whose mean projected_pts is at risk heading into playoffs.

    Trigger: if the team's mean point_margin in playoff weeks drops more than 20%
    below the regular-season mean, the overall scoring decline is real enough to
    flag positional culprits.

    Attribution: positions whose mean projected_pts in the current roster snapshot
    falls below 80% of the overall per-position mean are flagged as contributors.

    Returns [] when there is insufficient data (< 1 week in either horizon) or when
    ros_mean is near zero (ratio undefined), or when the playoff drop is within
    tolerance.

    Post-MVP upgrade: replace the point_margin proxy with per-position per-week
    projection data once the provider stores multi-week snapshots.
    """
    if not rest_of_season or not playoffs:
        return []

    ros_mean    = sum(r.point_margin for r in rest_of_season) / len(rest_of_season)
    playoff_mean = sum(r.point_margin for r in playoffs)     / len(playoffs)

    if abs(ros_mean) < 1.0:
        return []  # ratio undefined near zero

    if playoff_mean >= ros_mean * 0.8:
        return []  # drop within tolerance

    # Identify positions below 80% of overall position mean in current roster
    pos_pts: dict[str, list[float]] = defaultdict(list)
    for p in players:
        pos_pts[p.position].append(p.projected_pts)

    pos_means = {
        pos: sum(pts) / max(len(pts), 1)
        for pos, pts in pos_pts.items()
        if pts
    }
    if not pos_means:
        return []

    overall_mean = sum(pos_means.values()) / len(pos_means)
    if overall_mean <= 0:
        return []

    return sorted(pos for pos, mean in pos_means.items() if mean < overall_mean * 0.8)


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

class TeamHealthAssembler:

    def assemble(
        self,
        team_id: int,
        week_results: list[WeekResult],
        roster: RosterState,
        config: LeagueConfig,
        current_week: int,
    ) -> TeamHealth:
        """Assemble SeasonSimulator output into a three-horizon TeamHealth.

        current_week is passed explicitly — it is NOT read from config.
        """
        # 1. this_week: the result whose week matches current_week (None if absent)
        this_week = next((r for r in week_results if r.week == current_week), None)

        # 2. rest_of_season: all regular-season results (week < playoff_start_week)
        rest_of_season = [r for r in week_results if r.week < config.playoff_start_week]

        # 3. playoffs: weeks >= playoff_start_week, confidence further discounted by 0.6
        #    (seeding and field composition are unknown — compound that uncertainty here)
        playoffs = [
            replace(r, confidence=round(r.confidence * 0.6, 4))
            for r in week_results
            if r.week >= config.playoff_start_week
        ]

        # 4–6. Diagnostics derived from the current roster snapshot
        weakest_position      = _weakest_position(roster.players)
        bye_clusters          = _bye_clusters(roster)
        future_weakness_flags = _future_weakness_flags(roster.players, rest_of_season, playoffs)

        return TeamHealth(
            team_id               = team_id,
            this_week             = this_week,
            rest_of_season        = rest_of_season,
            playoffs              = playoffs,
            weakest_position      = weakest_position,
            bye_clusters          = bye_clusters,
            future_weakness_flags = future_weakness_flags,
        )


# ---------------------------------------------------------------------------
# Acceptance test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from data.provider import LeagueConfig, PlayerProj, RosterState
    from engine.season_sim import WeekResult
    from odds.monte_carlo import HALF_PPR

    # ── Test roster (week=1 snapshot) ────────────────────────────────────────
    #
    # Three players have projected_pts=0.0 → bye cluster on week 1.
    # TE1 has the lowest position mean (4.0) → weakest_position = "TE".
    #
    # Position means (for future_weakness_flags trigger check):
    #   QB   = (25.0 + 0.0) / 2 = 12.50
    #   RB   = (20.0 + 15.0 + 0.0) / 3 = 11.67
    #   WR   = (18.0 + 12.0 + 0.0) / 3 = 10.00
    #   TE   =  4.0 / 1 =  4.00   ← weakest
    #   FLEX = 10.0 / 1 = 10.00
    #   K    =  8.0 / 1 =  8.00
    #   DEF  =  7.5 / 1 =  7.50
    #   overall mean = (12.5 + 11.67 + 10.0 + 4.0 + 10.0 + 8.0 + 7.5) / 7 = 9.10
    #   80% threshold = 7.28  → only TE (4.0) falls below

    players = [
        PlayerProj(player_id=1,  name="QB1",     position="QB",   injury_status=None, projected_pts=25.0),
        PlayerProj(player_id=2,  name="RB1",     position="RB",   injury_status=None, projected_pts=20.0),
        PlayerProj(player_id=3,  name="RB2",     position="RB",   injury_status=None, projected_pts=15.0),
        PlayerProj(player_id=4,  name="WR1",     position="WR",   injury_status=None, projected_pts=18.0),
        PlayerProj(player_id=5,  name="WR2",     position="WR",   injury_status=None, projected_pts=12.0),
        PlayerProj(player_id=6,  name="TE1",     position="TE",   injury_status=None, projected_pts=4.0),
        PlayerProj(player_id=7,  name="Flex",    position="FLEX", injury_status=None, projected_pts=10.0),
        PlayerProj(player_id=8,  name="Kicker",  position="K",    injury_status=None, projected_pts=8.0),
        PlayerProj(player_id=9,  name="Defense", position="DEF",  injury_status=None, projected_pts=7.5),
        PlayerProj(player_id=10, name="RB_bye",  position="RB",   injury_status=None, projected_pts=0.0),
        PlayerProj(player_id=11, name="WR_bye",  position="WR",   injury_status=None, projected_pts=0.0),
        PlayerProj(player_id=12, name="QB_bye",  position="QB",   injury_status=None, projected_pts=0.0),
    ]

    roster = RosterState(team_id=1, team_name="Test Team", week=1, players=players)

    config = LeagueConfig(
        league_id=1,
        season=2024,
        n_teams=10,
        playoff_start_week=4,
        n_playoff_teams=6,
        scoring=HALF_PPR,
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1},
    )

    # ── Week results ─────────────────────────────────────────────────────────
    #
    # Regular season (weeks 1-3): positive margins → mean = (10+5-2)/3 = 4.33
    # Playoffs (weeks 4-5): negative margins → mean = (-15-20)/2 = -17.5
    # Drop: -17.5 < 4.33 * 0.8 = 3.47 → playoff drop triggers future_weakness_flags
    #
    # Playoff confidence after × 0.6: 0.6 × 0.6 = 0.36

    week_results = [
        WeekResult(week=1, win_prob=0.60, point_margin=+10.0, opponent_team_id=2, confidence=1.0),
        WeekResult(week=2, win_prob=0.55, point_margin=+5.0,  opponent_team_id=3, confidence=1.0),
        WeekResult(week=3, win_prob=0.45, point_margin=-2.0,  opponent_team_id=4, confidence=0.8),
        WeekResult(week=4, win_prob=0.30, point_margin=-15.0, opponent_team_id=5, confidence=0.6),
        WeekResult(week=5, win_prob=0.25, point_margin=-20.0, opponent_team_id=6, confidence=0.6),
    ]

    assembler = TeamHealthAssembler()
    health = assembler.assemble(
        team_id=1,
        week_results=week_results,
        roster=roster,
        config=config,
        current_week=1,
    )

    print(f"TeamHealth for team {health.team_id}")
    print(f"  this_week       : week={health.this_week.week if health.this_week else None}")
    print(f"  rest_of_season  : {len(health.rest_of_season)} weeks -> "
          f"{[r.week for r in health.rest_of_season]}")
    print(f"  playoffs        : {len(health.playoffs)} weeks -> "
          f"{[(r.week, r.confidence) for r in health.playoffs]}")
    print(f"  weakest_position: {health.weakest_position!r}")
    print(f"  bye_clusters    : {health.bye_clusters}")
    print(f"  future_weakness : {health.future_weakness_flags}")

    # --- this_week ---
    assert health.this_week is not None, "this_week must not be None"
    assert health.this_week.week == 1, f"Expected this_week.week=1, got {health.this_week.week}"
    print("\n  [PASS] this_week.week == 1")

    # --- rest_of_season: all weeks < playoff_start_week (4) ---
    assert len(health.rest_of_season) == 3, (
        f"Expected 3 rest_of_season weeks (1,2,3), got {len(health.rest_of_season)}"
    )
    assert {r.week for r in health.rest_of_season} == {1, 2, 3}
    print("  [PASS] rest_of_season = weeks 1, 2, 3")

    # --- playoffs: weeks >= 4, confidence × 0.6 ---
    assert len(health.playoffs) == 2, (
        f"Expected 2 playoff weeks (4,5), got {len(health.playoffs)}"
    )
    assert {r.week for r in health.playoffs} == {4, 5}
    EXPECTED_PLAYOFF_CONF = round(0.6 * 0.6, 4)
    assert all(r.confidence == EXPECTED_PLAYOFF_CONF for r in health.playoffs), (
        f"All playoff confidences must be {EXPECTED_PLAYOFF_CONF}, "
        f"got {[r.confidence for r in health.playoffs]}"
    )
    print(f"  [PASS] playoffs = weeks 4, 5; confidence = {EXPECTED_PLAYOFF_CONF}")

    # --- weakest_position ---
    assert health.weakest_position == "TE", (
        f"Expected weakest_position='TE', got {health.weakest_position!r}"
    )
    print("  [PASS] weakest_position == 'TE'")

    # --- bye_clusters ---
    assert health.bye_clusters == [1], (
        f"Expected bye_clusters=[1] (3 players on bye in week 1), got {health.bye_clusters}"
    )
    print("  [PASS] bye_clusters == [1]")

    # --- future_weakness_flags ---
    assert "TE" in health.future_weakness_flags, (
        f"Expected 'TE' in future_weakness_flags, got {health.future_weakness_flags}"
    )
    print(f"  [PASS] 'TE' in future_weakness_flags (flags: {health.future_weakness_flags})")

    print("\nAll acceptance tests passed.")
