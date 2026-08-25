"""RC2 — boundary gate between championship scoring and postseason action.

LEGACY-ERA ONLY. RETIRED FOR `RULESET_FINAL_POR` SEASONS BY WP-8.

── WHAT IT DOES UNDER THE LEGACY ERA ───────────────────────────────────────

The first governed postseason FantasyStakes action automatically freezes the
regular-season Championship Score if it has not already been frozen. The freeze
is staged in the caller's transaction and commits atomically with that first
postseason action. If any regular-season result is still unsettled, the freeze
fails closed and postseason action remains blocked.

── AND WHY THE FINAL POR HAS NO SUCH GATE ──────────────────────────────────

§18 removes the playoff boundary from the FantasyStakes Championship: scoring
runs THROUGH the postseason, so there is no moment at which a regular-season
score needs snapshotting and nothing for a postseason action to be blocked
behind. A Final POR season therefore passes this gate unconditionally, and
`freeze_fantasystakes_championship` refuses it outright — the two together are
what make the retirement real rather than merely unused.

The lifecycle a Final POR season runs instead is LIVE → FINAL → PAID, in
`economy.fantasystakes_lifecycle`, derived from posted state with no snapshot
row anywhere in it.

NOT DELETED, because every legacy season on every deployment was frozen by this
gate and its snapshot is still read to settle one.
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

    # ── FINAL POR · WP-8 — THERE IS NO BOUNDARY TO GATE ─────────────────────
    #
    # §18: FantasyStakes scoring runs through the postseason. Nothing is frozen
    # at the playoff boundary, so there is no snapshot for a postseason action
    # to be blocked behind and nothing here to establish. Returning before the
    # `playoff_start_week` requirement below is deliberate: that requirement
    # exists only to locate the boundary, and a Final POR season does not need
    # one located.
    from ruleset import is_final_por

    if is_final_por(db, league_id=league_id, season=league.season):
        return

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
