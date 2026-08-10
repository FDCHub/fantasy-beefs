"""FastAPI router for /pool Mode 3 weekly pool endpoints."""
from __future__ import annotations

import dataclasses
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.deps import get_db
# require_commissioner is no longer imported: S8-P2 moved every commissioner
# route in this module to league-scoped authority, so a global-role import
# would only be an invitation to reintroduce the gap.
from auth.jwt_auth import assert_own_team, get_current_gm, User
from auth.allocation_gate import assert_league_commissioner
from ledger.ledger import _dollars_to_cents
from betting.pool_legacy_guard import (
    LegacyPoolPathRefused,
    assert_legacy_pool_path_allowed,
)
from betting.pool_engine import (
    setup_pool_config,
    get_pool_config,
    collect_weekly_entries,
    submit_worst_beat_prediction,
    get_pool_predictions,
    settle_pool,
    get_pool_week,
    submit_pool_pick,
    PoolConfigOut,
    PoolEntryResult,
    PoolPredictionOut,
    PoolSettlementResult,
)

router = APIRouter(prefix="/pool", tags=["pool"])


# ── Request models ────────────────────────────────────────────────────────────

class PoolConfigRequest(BaseModel):
    league_id:           int
    weekly_entry:        float
    worst_beat_rollover: bool = True


class CollectEntriesRequest(BaseModel):
    league_id: int
    week:      int


class PredictionRequest(BaseModel):
    league_id:         int
    team_id:           int
    predicted_team_id: int
    week:              int


class SettleRequest(BaseModel):
    league_id: int
    week:      int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/config", response_model=PoolConfigOut)
def create_pool_config(
    req:   PoolConfigRequest,
    db:    Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
) -> PoolConfigOut:
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    try:
        weekly_entry_cents = _dollars_to_cents(req.weekly_entry)
        return setup_pool_config(
            league_id           = req.league_id,
            weekly_entry_cents  = weekly_entry_cents,
            worst_beat_rollover = req.worst_beat_rollover,
            db                  = db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/config/{league_id}", response_model=PoolConfigOut)
def read_pool_config(league_id: int, db: Session = Depends(get_db)) -> PoolConfigOut:
    try:
        return get_pool_config(league_id=league_id, db=db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/collect", response_model=PoolEntryResult)
def collect_entries(
    req:   CollectEntriesRequest,
    db:    Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
) -> PoolEntryResult:
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    # S4-P2-1 — the mounted legacy economic surface. The guard also sits at the
    # engine function's own entry point; it is repeated here so the refusal
    # happens before the request ever reaches the legacy engine, and so the
    # reachable HTTP path is closed at the boundary the route owns.
    try:
        assert_legacy_pool_path_allowed(db, req.league_id, req.week)
        return collect_weekly_entries(league_id=req.league_id, week=req.week, db=db)
    except LegacyPoolPathRefused as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/predict", response_model=PoolPredictionOut)
def submit_prediction(
    req:         PredictionRequest,
    db:          Session = Depends(get_db),
    current_gm:  User    = Depends(get_current_gm),
) -> PoolPredictionOut:
    try:
        return submit_worst_beat_prediction(
            league_id         = req.league_id,
            team_id           = req.team_id,
            predicted_team_id = req.predicted_team_id,
            week              = req.week,
            db                = db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/predictions/{league_id}/{week}", response_model=list[PoolPredictionOut])
def read_predictions(
    league_id: int, week: int, db: Session = Depends(get_db)
) -> list[PoolPredictionOut]:
    try:
        return get_pool_predictions(league_id=league_id, week=week, db=db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/settle", response_model=PoolSettlementResult)
def settle_weekly_pool(
    req:   SettleRequest,
    db:    Session = Depends(get_db),
    current_user: User = Depends(get_current_gm),
) -> PoolSettlementResult:
    # S8-P2: the league is named by the request, so authority is checked
    # against THAT league rather than a global role.
    assert_league_commissioner(current_user, req.league_id, db)

    # S4-P2-1 — see collect_entries above.
    try:
        assert_legacy_pool_path_allowed(db, req.league_id, req.week)
        return settle_pool(league_id=req.league_id, week=req.week, db=db)
    except LegacyPoolPathRefused as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Pool Card endpoints (VP2 Section 1) ───────────────────────────────────────

class PoolPickRequest(BaseModel):
    league_id: int
    team_id:   int
    bet_type:  str
    pick:      Optional[int] = None  # picked team_id; null to reset
    week:      int


@router.get("/week/{week}")
def get_week_pool(
    week:      int,
    league_id: int = Query(..., description="League ID"),
    db:        Session = Depends(get_db),
) -> dict:
    """
    Return all 4 pool bets for the week with every GM's current pick state.
    lock_time is derived from PoolPot.lock_time if set, else computed from
    the NFL 2024 schedule formula (Thursday 8:20 PM ET per week).
    """
    if not 1 <= week <= 17:
        raise HTTPException(status_code=400, detail="week must be 1–17")
    try:
        result = get_pool_week(league_id=league_id, week=week, db=db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return dataclasses.asdict(result)


@router.post("/pick")
def submit_pick(
    req:        PoolPickRequest,
    db:         Session = Depends(get_db),
    current_gm: User    = Depends(get_current_gm),
) -> dict:
    """
    Upsert a GM's pick for one pool bet type.
    Self-pick is allowed only for biggest_winner; blocked for the other three.
    Rejected after the weekly lock_time (Thursday 8:20 PM ET by default).
    """
    assert_own_team(req.team_id, current_gm)
    try:
        result = submit_pool_pick(
            league_id    = req.league_id,
            team_id      = req.team_id,
            bet_type     = req.bet_type,
            pick_team_id = req.pick,
            week         = req.week,
            db           = db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return dataclasses.asdict(result)
