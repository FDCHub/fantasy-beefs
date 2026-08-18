"""RC2 — boundary gate between championship scoring and postseason action.

The first governed postseason FantasyStakes action automatically freezes the
regular-season Championship Score if it has not already been frozen. The freeze
is staged in the caller's transaction and commits atomically with that first
postseason action. If any regular-season result is still unsettled, the freeze
fails closed and postseason action remains blocked.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from db.schema import League
from reports.championship_read_model import (
    FantasyStakesChampionshipError,
    FantasyStakesChampionshipFreeze,
    freeze_fantasystakes_championship,
)

REASON_CHAMPIONSHIP_NOT_FROZEN = "FS_CHAMPIONSHIP_NOT_FROZEN"
REASON_BOUNDARY_UNAVAILABLE = "FS_CHAMPIONSHIP_BOUNDARY_UNAVAILABLE"
REASON_LEAGUE_NOT_FOUND = "FS_CHAMPIONSHIP_LEAGUE_NOT_FOUND"


class ChampionshipScoringGateError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


def require_championship_frozen_for_postseason(
    db: Session, *, league_id: int, week: int,
) -> None:
    """Permit regular season; atomically establish the freeze for postseason.

    No commit occurs here. The money-moving caller owns the transaction. This
    makes the cutoff automatic without allowing a postseason result to land
    before the regular-season score snapshot exists.
    """
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise ChampionshipScoringGateError(
            REASON_LEAGUE_NOT_FOUND, f"league {league_id} not found")
    if league.playoff_start_week is None:
        raise ChampionshipScoringGateError(
            REASON_BOUNDARY_UNAVAILABLE,
            f"league {league_id} has no authoritative playoff_start_week; "
            f"postseason championship-scoring status cannot be determined.")

    cutoff = int(league.playoff_start_week)
    if int(week) < cutoff:
        return

    frozen = (db.query(FantasyStakesChampionshipFreeze.id)
              .filter(FantasyStakesChampionshipFreeze.league_id == league_id,
                      FantasyStakesChampionshipFreeze.season == league.season)
              .first())
    if frozen is not None:
        return

    try:
        freeze_fantasystakes_championship(db, league_id=league_id)
    except FantasyStakesChampionshipError as exc:
        raise ChampionshipScoringGateError(
            REASON_CHAMPIONSHIP_NOT_FROZEN,
            f"week {week} is postseason for league {league_id}, but the "
            f"regular-season FantasyStakes Championship cannot yet be frozen: "
            f"{exc}. Postseason FantasyStakes economic activity is refused."
        ) from exc
