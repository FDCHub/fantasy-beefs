"""
reports/standings.py — regular-season standings order and the default
payout split.

B2 Group 1 relocation. DEFAULT_PAYOUT_SPLIT and _compute_standings_order
were moved here verbatim from the retired payment module so that consumers
of the standings order no longer have to import that module.
Behavior is unchanged.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import Matchup


DEFAULT_PAYOUT_SPLIT = [60, 30, 10]


def _compute_standings_order(league_id: int, db: Session) -> list[int]:
    """Return team IDs sorted by regular-season record (desc wins, desc PF)."""
    matchups = (
        db.query(Matchup)
        .filter(Matchup.league_id == league_id, Matchup.week <= 14)
        .all()
    )
    stats: dict[int, dict] = {}
    for m in matchups:
        for team_id, pf, pa in (
            (m.home_team_id, m.home_score, m.away_score),
            (m.away_team_id, m.away_score, m.home_score),
        ):
            if team_id not in stats:
                stats[team_id] = {"w": 0, "pf": 0.0}
            stats[team_id]["pf"] += pf
            if team_id == m.winner_team_id:
                stats[team_id]["w"] += 1
    return sorted(stats, key=lambda t: (-stats[t]["w"], -stats[t]["pf"]))
