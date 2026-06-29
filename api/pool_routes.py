"""FastAPI router for /pool Mode 3 weekly pool endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.deps import get_db
from betting.pool_engine import (
    setup_pool_config,
    get_pool_config,
    collect_weekly_entries,
    submit_worst_beat_prediction,
    get_pool_predictions,
    settle_pool,
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
def create_pool_config(req: PoolConfigRequest, db: Session = Depends(get_db)) -> PoolConfigOut:
    try:
        return setup_pool_config(
            league_id           = req.league_id,
            weekly_entry        = req.weekly_entry,
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
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/collect", response_model=PoolEntryResult)
def collect_entries(req: CollectEntriesRequest, db: Session = Depends(get_db)) -> PoolEntryResult:
    try:
        return collect_weekly_entries(league_id=req.league_id, week=req.week, db=db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/predict", response_model=PoolPredictionOut)
def submit_prediction(req: PredictionRequest, db: Session = Depends(get_db)) -> PoolPredictionOut:
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
def settle_weekly_pool(req: SettleRequest, db: Session = Depends(get_db)) -> PoolSettlementResult:
    try:
        return settle_pool(league_id=req.league_id, week=req.week, db=db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
