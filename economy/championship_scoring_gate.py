"""RC2 — boundary gate between championship-scoring and postseason action.

Regular-season FantasyStakes competition feeds the live competitive read model.
At the Yahoo postseason boundary that result is snapshotted as Championship
Score. Postseason FantasyStakes play remains economic activity but must never be
allowed to happen BEFORE the snapshot, or the live read model would already
contain non-championship results when it froze.

This module owns only that ordering rule. It does not decide whether a GM is
postseason-eligible, whether a wager is affordable, or whether a Pool definition
is postseason-enabled; those existing gates remain authoritative for those
questions.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from db.schema import League
from reports.championship_read_model import FantasyStakesChampionshipFreeze

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
    """Permit regular-season action; require the snapshot for postseason action.

    Pure read, no commit, no lock. The money-moving caller already owns whatever
    transaction/serialization its domain requires. This gate merely proves the
    prerequisite exists before that caller is allowed to proceed.
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
    if frozen is None:
        raise ChampionshipScoringGateError(
            REASON_CHAMPIONSHIP_NOT_FROZEN,
            f"week {week} is postseason for league {league_id} "
            f"(playoff_start_week={cutoff}), but the regular-season "
            f"FantasyStakes Championship standings have not been frozen. "
            f"Refusing postseason FantasyStakes economic activity until the "
            f"championship snapshot is final.")
