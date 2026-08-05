"""
auth/allocation_gate.py — season-allocation gate.

B2 Group 1 relocation. get_buyin_gate and get_buyin_enforcement_active were
moved here from payments/stripe_connect.py and renamed to
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

The commissioner-facing setter (set_buyin_enforcement_active) is deferred to
Group 3 and still lives in payments/stripe_connect.py, because it writes the
StripeAuditLog via that module's private _log helper.
"""

from __future__ import annotations

import os
import sys

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from db.schema import League, SeasonAllocation, Team, User
from db.deps import get_db
from auth.jwt_auth import get_current_gm


def get_allocation_enforcement_active(league_id: int, db: Session) -> bool:
    """Reads League.buyin_enforcement_active. False (inactive) if the
    league doesn't exist — same fail-open posture as an unconfigured stop."""
    league = db.query(League).filter(League.id == league_id).first()
    return bool(league.buyin_enforcement_active) if league else False


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
