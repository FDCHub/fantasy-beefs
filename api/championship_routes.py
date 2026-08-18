"""RC2 FantasyStakes Championship API surface."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.jwt_auth import User, get_current_gm, require_league_commissioner
from db.deps import get_db
from db.schema import League
from economy.fantasystakes_championship_allocation import (
    read_config, set_contribution,
)
from economy.rc2_season_activation import (
    RC2SeasonActivationError,
    activate_fantasystakes_championship_stage,
)
from economy.fantasystakes_championship_settlement import (
    settle_fantasystakes_championship,
)
from reports.championship_read_model import (
    FantasyStakesChampionshipError,
    freeze_fantasystakes_championship,
    get_fantasystakes_championship,
)
from reports.standings_read_model import league_standings

router = APIRouter(prefix="/league/{league_id}/championship", tags=["championship"])


class ContributionRequest(BaseModel):
    contribution_cents: int = Field(..., ge=100, le=100_000)


def _row_dict(row) -> dict:
    return {
        "team_id": row.team_id,
        "team_name": row.team_name,
        "owner": row.owner,
        "matchup_net_cents": row.matchup_net_cents,
        "prop_pool_net_cents": row.prop_pool_net_cents,
        "championship_score_cents": row.championship_score_cents,
        "place": row.place,
        "tied": row.tied,
    }


@router.get("/config")
def championship_config(
    league_id: int,
    db: Session = Depends(get_db),
    _gm: User = Depends(get_current_gm),
):
    view = read_config(db, league_id=league_id)
    return {
        "league_id": view.league_id,
        "season": view.season,
        "yahoo_championship_contribution_cents": view.yahoo_championship_contribution_cents,
        "fantasystakes_championship_contribution_cents": view.fantasystakes_championship_contribution_cents,
        "defaults_match": view.contributions_match,
        "configured": view.configured,
        "frozen": view.frozen,
    }


@router.put("/config")
def update_championship_config(
    league_id: int,
    req: ContributionRequest,
    db: Session = Depends(get_db),
    _comm: User = Depends(require_league_commissioner),
):
    try:
        view = set_contribution(
            db, league_id=league_id, contribution_cents=req.contribution_cents)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "league_id": view.league_id,
        "season": view.season,
        "yahoo_championship_contribution_cents": view.yahoo_championship_contribution_cents,
        "fantasystakes_championship_contribution_cents": view.fantasystakes_championship_contribution_cents,
        "defaults_match": view.contributions_match,
        "configured": view.configured,
        "frozen": view.frozen,
    }


@router.post("/activate")
def activate_championship_economy(
    league_id: int,
    db: Session = Depends(get_db),
    _comm: User = Depends(require_league_commissioner),
):
    try:
        result = activate_fantasystakes_championship_stage(league_id, db)
    except RC2SeasonActivationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "league_id": result.league_id,
        "season": result.season,
        "team_ids": list(result.team_ids),
        "weekly_plus_yahoo_per_gm_cents": result.weekly_plus_yahoo_per_gm_cents,
        "fantasystakes_championship_per_gm_cents": result.fantasystakes_championship_per_gm_cents,
        "season_opening_allocation_per_gm_cents": result.season_opening_allocation_per_gm_cents,
        "fantasystakes_championship_pot_cents": result.fantasystakes_championship_pot_cents,
        "created": result.created,
    }


@router.get("")
def championship_chase(
    league_id: int,
    db: Session = Depends(get_db),
    _gm: User = Depends(get_current_gm),
):
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail="league not found")
    frozen = get_fantasystakes_championship(db, league_id=league_id)
    if frozen is not None:
        return {
            "status": "FINAL",
            "league_id": league_id,
            "season": frozen.season,
            "scoring_through_week": frozen.scoring_through_week,
            "frozen_at": frozen.frozen_at.isoformat(),
            "rows": [_row_dict(r) for r in frozen.rows],
        }

    live = league_standings(db, league_id=league_id)
    rows = []
    ordered = live.overall
    cursor = 0
    last_score = None
    last_place = 0
    for index, row in enumerate(ordered, start=1):
        score = int(row.net_cents)
        if score != last_score:
            last_place = index
            last_score = score
        rows.append({
            "team_id": row.team_id,
            "team_name": row.team_name,
            "owner": row.owner,
            "matchup_net_cents": row.versus_net_cents,
            "prop_pool_net_cents": row.pool_net_cents,
            "championship_score_cents": row.net_cents,
            "place": last_place,
            "tied": sum(1 for r in ordered if r.net_cents == row.net_cents) > 1,
        })
    return {
        "status": "LIVE",
        "league_id": league_id,
        "season": league.season,
        "scoring_through_week": None,
        "playoff_start_week": league.playoff_start_week,
        "rows": rows,
    }


@router.post("/freeze")
def freeze_championship(
    league_id: int,
    db: Session = Depends(get_db),
    _comm: User = Depends(require_league_commissioner),
):
    try:
        result = freeze_fantasystakes_championship(db, league_id=league_id)
        db.commit()
    except FantasyStakesChampionshipError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "status": "FINAL",
        "league_id": league_id,
        "season": result.season,
        "scoring_through_week": result.scoring_through_week,
        "frozen_at": result.frozen_at.isoformat(),
        "rows": [_row_dict(r) for r in result.rows],
    }


@router.post("/settle")
def settle_championship(
    league_id: int,
    db: Session = Depends(get_db),
    _comm: User = Depends(require_league_commissioner),
):
    try:
        result = settle_fantasystakes_championship(db, league_id=league_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "league_id": result.league_id,
        "season": result.season,
        "pot_cents": result.pot_cents,
        "replayed": result.replayed,
        "awards": [
            {"team_id": a.team_id, "place": a.place,
             "championship_score_cents": a.championship_score_cents,
             "amount_cents": a.amount_cents, "tied": a.tied}
            for a in result.awards
        ],
    }
