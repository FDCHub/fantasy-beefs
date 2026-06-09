"""SeasonSimulator: week loop wrapping the existing per-week Monte Carlo.

Calls simulate_scores() from odds/monte_carlo.py for each remaining matchup.
Do NOT rebuild the Monte Carlo — reuse it.

db is always injected from outside; SeasonSimulator never creates its own session.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.orm import Session

from data.provider import LeagueConfig, PlayerProj, RosterState, ScheduleEntry
from db.schema import Team
from engine.lineup_optimizer import LineupOptimizer  # reserved: full roster-state sim (post-MVP)
from odds.monte_carlo import simulate_scores


@dataclass
class WeekResult:
    week: int
    win_prob: float
    point_margin: float       # our_mean - opponent_mean (positive = projected win)
    opponent_team_id: int
    confidence: float         # 1.0 sharp / 0.8 moderate / 0.6 blurry; heat-map blur maps here


def _confidence(week: int, current_week: int, playoff_start_week: int) -> float:
    """Confidence for a projected week.

    Playoff weeks are always 0.6 — field composition and seeding are unknown.
    Regular weeks decay with forward distance: near-term is tight, far is wide.
    """
    if week >= playoff_start_week:
        return 0.6
    distance = week - current_week
    if distance <= 1:
        return 1.0
    if distance <= 3:
        return 0.8
    return 0.6


class SeasonSimulator:

    def simulate(
        self,
        team_id: int,
        roster: RosterState,
        schedule: list[ScheduleEntry],
        config: LeagueConfig,
        current_week: int,
        db: Session,
    ) -> list[WeekResult]:
        """Simulate all remaining matchups for team_id and return per-week results.

        Filters schedule to entries involving team_id at or after current_week,
        calls the existing per-week Monte Carlo for each, and returns WeekResults
        sorted by week.

        roster is accepted for forward compatibility (will feed LineupOptimizer once
        the full roster-state sim replaces the DB-bound _starters() path).
        """
        remaining = sorted(
            [
                e for e in schedule
                if (e.home_team_id == team_id or e.away_team_id == team_id)
                and e.week >= current_week
            ],
            key=lambda e: e.week,
        )

        results: list[WeekResult] = []
        for entry in remaining:
            is_home = entry.home_team_id == team_id
            opponent_team_id = entry.away_team_id if is_home else entry.home_team_id

            # YAHOO SWAP POINT: replace these DB lookups with YahooProvider.get_team()
            # calls when the OAuth + DB query layer is ready. The integer team IDs on
            # ScheduleEntry map 1-to-1 to Team.id in the seeded mock DB for now.
            home_orm = db.query(Team).filter_by(id=entry.home_team_id).first()
            away_orm = db.query(Team).filter_by(id=entry.away_team_id).first()

            if home_orm is None or away_orm is None:
                continue  # team not in DB — skip rather than crash

            home_scores, away_scores = simulate_scores(
                home_orm, away_orm, entry.week, db, scoring=config.scoring,
            )

            if is_home:
                win_prob     = float((home_scores > away_scores).mean())
                point_margin = float(home_scores.mean() - away_scores.mean())
            else:
                win_prob     = float((away_scores > home_scores).mean())
                point_margin = float(away_scores.mean() - home_scores.mean())

            results.append(WeekResult(
                week             = entry.week,
                win_prob         = round(win_prob, 4),
                point_margin     = round(point_margin, 2),
                opponent_team_id = opponent_team_id,
                confidence       = _confidence(entry.week, current_week, config.playoff_start_week),
            ))

        return results


# ---------------------------------------------------------------------------
# Acceptance test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from data.provider import LeagueConfig, RosterState, ScheduleEntry
    from db.schema import Base, seed_from_mock
    from odds.monte_carlo import HALF_PPR

    # Fresh in-memory SQLite — no filesystem dependency, always clean.
    # db is created here (test harness) and injected into the simulator.
    # The SeasonSimulator class itself never calls SessionLocal().
    mem_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(mem_engine)
    MemSession = sessionmaker(bind=mem_engine)

    with MemSession() as db:
        seed_from_mock(session=db)

        # Team 1 ("Mahomes Alone") is the subject team.
        #
        # Six-week schedule: team 1 as home team each week.
        # playoff_start_week=4 so weeks 4-6 are playoff weeks.
        # This lets us verify the playoff-override rule: week 4 has
        # distance=3 (would be 0.8 normally) but must be 0.6 as a playoff week.
        TEAM_ID = 1

        schedule = [
            ScheduleEntry(week=1, home_team_id=1, away_team_id=2),
            ScheduleEntry(week=2, home_team_id=1, away_team_id=3),
            ScheduleEntry(week=3, home_team_id=1, away_team_id=4),
            ScheduleEntry(week=4, home_team_id=1, away_team_id=5),  # playoff week
            ScheduleEntry(week=5, home_team_id=1, away_team_id=6),  # playoff week
            ScheduleEntry(week=6, home_team_id=1, away_team_id=7),  # playoff week
        ]

        config = LeagueConfig(
            league_id=1,
            season=2024,
            n_teams=10,
            playoff_start_week=4,
            n_playoff_teams=6,
            scoring=HALF_PPR,
            roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1},
        )

        roster = RosterState(team_id=TEAM_ID, team_name="Mahomes Alone", week=1, players=[])

        simulator = SeasonSimulator()
        results = simulator.simulate(
            team_id=TEAM_ID,
            roster=roster,
            schedule=schedule,
            config=config,
            current_week=1,
            db=db,
        )

        print("\nWeekResults:")
        for r in results:
            conf_label = {1.0: "sharp", 0.8: "moderate", 0.6: "blurry"}.get(r.confidence, "?")
            print(
                f"  week={r.week}  win_prob={r.win_prob:.4f}"
                f"  margin={r.point_margin:+.2f}"
                f"  opp={r.opponent_team_id}"
                f"  confidence={r.confidence} ({conf_label})"
            )

        # --- 6 WeekResult objects ---
        assert len(results) == 6, f"Expected 6 WeekResults, got {len(results)}"
        print("\n  [PASS] 6 WeekResult objects")

        # --- week 1 confidence == 1.0 ---
        wk1 = next(r for r in results if r.week == 1)
        assert wk1.confidence == 1.0, f"Week 1 confidence: expected 1.0, got {wk1.confidence}"
        print("  [PASS] week 1 confidence == 1.0")

        # --- week 6 confidence == 0.6 ---
        wk6 = next(r for r in results if r.week == 6)
        assert wk6.confidence == 0.6, f"Week 6 confidence: expected 0.6, got {wk6.confidence}"
        print("  [PASS] week 6 confidence == 0.6")

        # --- all win_prob in [0.0, 1.0] ---
        assert all(0.0 <= r.win_prob <= 1.0 for r in results), (
            f"win_prob out of range: {[r.win_prob for r in results]}"
        )
        print("  [PASS] all win_prob in [0.0, 1.0]")

        # --- playoff weeks have confidence == 0.6 ---
        playoff_results = [r for r in results if r.week >= config.playoff_start_week]
        assert len(playoff_results) > 0, "No playoff weeks in test schedule"
        assert all(r.confidence == 0.6 for r in playoff_results), (
            f"Playoff week confidences: {[r.confidence for r in playoff_results]} — all must be 0.6"
        )
        # Key case: week 4 distance=3 would normally be 0.8, playoff overrides to 0.6
        wk4 = next(r for r in results if r.week == 4)
        assert wk4.confidence == 0.6, (
            f"Playoff override failed: week 4 distance=3 should give 0.8 normally "
            f"but playoff forces 0.6, got {wk4.confidence}"
        )
        print(
            f"  [PASS] {len(playoff_results)} playoff weeks have confidence == 0.6"
            f" (week 4 playoff override: distance=3 -> 0.6, not 0.8)"
        )

        print("\nAll acceptance tests passed.")
