"""
auth/allocation_gate.py — season-allocation gate.

B2 Group 1 relocation. get_buyin_gate and get_buyin_enforcement_active were
moved here from the retired payment module and renamed to
get_season_allocation_gate and get_allocation_enforcement_active.

B2 Group 2 retarget. get_season_allocation_gate no longer reads
User.buy_in_paid — it now gates on the existence of a SeasonAllocation row
for (league_id, team_id, config.ALLOCATION_SEASON). Only that final check
changed; every early-return branch is exactly as it was.

The lookup is SEASON-QUALIFIED, and that qualification is load-bearing: a GM
holding only a prior-season allocation must still be blocked. An unqualified
existence check would let last season's row open this season's gate.

User.buy_in_paid is deliberately NOT removed from the schema — it survives as
DEBT-3 and is simply no longer consulted here.

B2 payment removal. The commissioner-facing setter was relocated here as
set_allocation_enforcement_active. It previously lived in the retired payment
module and wrote an audit row through that module's private _log helper; that
module no longer exists in the MVP, and the audit write went with it. The
setter's product behaviour — writing League.buyin_enforcement_active and
returning the stored value — is unchanged.

League.buyin_enforcement_active keeps its historical column name. It is the
season-allocation enforcement flag; it does not mean a buy-in was paid.
Renaming the column is deferred to a controlled post-MVP migration.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from db.schema import League, LeagueCommissioner, SeasonAllocation, Team, User
from db.deps import get_db
from auth.jwt_auth import get_current_gm


def get_allocation_enforcement_active(league_id: int, db: Session) -> bool:
    """Reads League.buyin_enforcement_active. False (inactive) if the
    league doesn't exist — same fail-open posture as an unconfigured stop."""
    league = db.query(League).filter(League.id == league_id).first()
    return bool(league.buyin_enforcement_active) if league else False


def set_allocation_enforcement_active(
    league_id:    int,
    active:       bool,
    db:           Session,
    performer_id: Optional[int] = None,
) -> bool:
    """
    Commissioner-facing setter. Flips League.buyin_enforcement_active.
    Takes effect on the very next request — get_season_allocation_gate reads
    this column fresh on every call and nothing caches it.

    Relocated from the retired payment module during the B2 payment removal.
    The audit write that accompanied it there is gone with that module;
    performer_id is retained in the signature so callers and their tests are
    unchanged, and so a future audit surface can record it without another
    signature change.
    """
    league = db.query(League).filter(League.id == league_id).first()
    if not league:
        raise ValueError(f"League {league_id} not found")

    league.buyin_enforcement_active = active
    db.commit()
    return league.buyin_enforcement_active


# ── FastAPI dependency — buy-in gate ─────────────────────────────────────────

def get_season_allocation_gate(
    current_user: User    = Depends(get_current_gm),
    db:           Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency — blocks GMs from betting/beefs until their season
    allocation exists for config.ALLOCATION_SEASON (B2 Group 2).
    Commissioner always bypasses.
    Gate is inactive unless the league's commissioner has explicitly turned
    on League.buyin_enforcement_active (B2, Finding 5.3) — independent of
    LeagueTreasury entirely.

    The SeasonAllocation lookup is qualified by league, team AND
    config.ALLOCATION_SEASON. A GM whose only allocation row belongs to a
    prior season is still blocked.
    """
    if current_user.role == "commissioner":
        return current_user

    # Find the team's league via the team's league_id
    if current_user.team_id is None:
        return current_user

    team = db.query(Team).filter(Team.id == current_user.team_id).first()
    if not team:
        return current_user

    league = db.query(League).filter(League.id == team.league_id).first()
    if not league or not league.buyin_enforcement_active:
        return current_user  # enforcement off — gate inactive by explicit choice

    allocation = (
        db.query(SeasonAllocation)
        .filter(
            SeasonAllocation.league_id == team.league_id,
            SeasonAllocation.team_id   == current_user.team_id,
            SeasonAllocation.season    == config.ALLOCATION_SEASON,
        )
        .first()
    )
    if not allocation:
        raise HTTPException(
            status_code = status.HTTP_402_PAYMENT_REQUIRED,
            detail      = "Season allocation required before placing bets or issuing challenges",
        )

    return current_user


# ── League-scoped commissioner authority ─────────────────────────────────────
#
# Authorization is decided by a LeagueCommissioner row for (league_id, user_id).
# The global User.role == "commissioner" is retained as defence in depth but is
# NEVER sufficient on its own: a global commissioner with no row for the league
# is denied. Team ownership grants nothing — commissioner authority is
# deliberately independent of User.team_id.


def is_league_commissioner(user_id: int, league_id: int, db: Session) -> bool:
    """True iff a LeagueCommissioner row exists for exactly this pair.

    Pure lookup: no role inspection, no team traversal, no fallback. One user
    may be authorized for many leagues and one league may have many
    commissioners; this answers only the single pair asked about.
    """
    return (
        db.query(LeagueCommissioner)
        .filter(
            LeagueCommissioner.league_id == league_id,
            LeagueCommissioner.user_id == user_id,
        )
        .first()
        is not None
    )


def require_league_commissioner(
    league_id:    int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_gm),
) -> User:
    """FastAPI dependency — authenticated commissioner authorized for THIS league.

    `league_id` binds to the route's own path parameter, so the authority check
    is against the league actually being acted on, not one supplied separately.

    Response ordering, stated explicitly because it is a security decision:
      401  unauthenticated / inactive — from get_current_gm, unchanged.
      403  authenticated but not authorized for this league. Returned BEFORE
           any downstream route work, so an unauthorized caller cannot use the
           guarded route to learn whether a league id exists.

    THE ACTUAL PROPERTY (R-C1 correction): league-scoped authorization runs
    before downstream route work, preventing an unauthorized caller from using
    that route to distinguish league existence.

    An earlier version of this docstring claimed a 404 was reachable after
    successful authorization for an absent league. That was false. Authority is
    a LeagueCommissioner row whose league_id carries a foreign key to
    leagues.id, so a row for a nonexistent league is structurally impossible —
    a caller can never be authorized for a league that does not exist. No such
    404 path is claimed here, because none is established by code or test.
    """
    if not is_league_commissioner(current_user.id, league_id, db):
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "Commissioner access required for this league",
        )
    return current_user
