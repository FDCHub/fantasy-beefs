"""FastAPI router for /bets Fantasybook bet-placement endpoints.

All eight POST endpoints follow the same pattern:
  1. Validate inputs (inside the bet engine)
  2. Run Monte Carlo simulation to derive fair odds
  3. Deduct stake, write Bet row + debit Transaction
  4. Return BetOut with status="pending"
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.deps import get_db
from betting.bet_engine import (
    BetResult,
    place_straight_bet,
    place_spread_bet,
    place_over_under,
    place_prop_bet,
    place_more_overs,
    place_closest_to_projection,
    place_position_group_wins,
    place_most_offensive_tds,
)

router = APIRouter(prefix="/bets", tags=["bets"])


# ── Request models ─────────────────────────────────────────────────────────────

class BetRequest(BaseModel):
    matchup_id:     int
    wallet_id:      int
    picked_team_id: int
    amount:         float
    week:           int


class SpreadBetRequest(BetRequest):
    spread: float


class OUBetRequest(BetRequest):
    total_line: float
    pick:       str   # "over" | "under"


class PropBetRequest(BetRequest):
    player_id: int | None = None
    position:  str | None = None


# ── Response model ─────────────────────────────────────────────────────────────

class BetOut(BaseModel):
    bet_id:      int
    bet_type:    str
    description: str
    amount:      float
    odds_dec:    float
    moneyline:   int
    win_prob:    float
    to_win:      float
    status:      str
    legs:        list | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/moneyline", response_model=BetOut, status_code=201)
def bet_moneyline(req: BetRequest, db: Session = Depends(get_db)) -> BetOut:
    """Pick a team to win outright."""
    try:
        result = place_straight_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BetOut(**result.__dict__)


@router.post("/spread", response_model=BetOut, status_code=201)
def bet_spread(req: SpreadBetRequest, db: Session = Depends(get_db)) -> BetOut:
    """Bet that the picked team covers the spread."""
    try:
        result = place_spread_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.spread, req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BetOut(**result.__dict__)


@router.post("/total", response_model=BetOut, status_code=201)
def bet_total(req: OUBetRequest, db: Session = Depends(get_db)) -> BetOut:
    """Bet the combined score is over/under a total line."""
    try:
        result = place_over_under(
            req.matchup_id, req.wallet_id, req.total_line,
            req.pick, req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BetOut(**result.__dict__)


@router.post("/prop", response_model=BetOut, status_code=201)
def bet_prop(req: PropBetRequest, db: Session = Depends(get_db)) -> BetOut:
    """Top projected starter vs top projected starter — pick which team's player scores more."""
    try:
        result = place_prop_bet(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BetOut(**result.__dict__)


@router.post("/more-overs", response_model=BetOut, status_code=201)
def bet_more_overs(req: BetRequest, db: Session = Depends(get_db)) -> BetOut:
    """Win if more of your starters beat their projections than opponent's."""
    try:
        result = place_more_overs(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BetOut(**result.__dict__)


@router.post("/closest-to-proj", response_model=BetOut, status_code=201)
def bet_closest_to_proj(req: BetRequest, db: Session = Depends(get_db)) -> BetOut:
    """Win if your lineup finishes nearer its projected total than opponent's."""
    try:
        result = place_closest_to_projection(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BetOut(**result.__dict__)


@router.post("/position-groups", response_model=BetOut, status_code=201)
def bet_position_groups(req: BetRequest, db: Session = Depends(get_db)) -> BetOut:
    """Win if your team wins more position group matchups: QB, RB, WR, TE."""
    try:
        result = place_position_group_wins(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BetOut(**result.__dict__)


@router.post("/most-tds", response_model=BetOut, status_code=201)
def bet_most_tds(req: BetRequest, db: Session = Depends(get_db)) -> BetOut:
    """Win if your starters score more offensive TDs than opponent's starters."""
    try:
        result = place_most_offensive_tds(
            req.matchup_id, req.wallet_id, req.picked_team_id,
            req.amount, req.week, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return BetOut(**result.__dict__)
