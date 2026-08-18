"""RC2 FantasyStakes Championship API surface."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.jwt_auth import User, get_current_gm
from auth.allocation_gate import require_league_commissioner
from db.deps import get_db
from db.schema import League, Team
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
from economy.championship_result_correction import (
    CorrectedPoolResult, CorrectedVersusResult, apply_result_correction,
)
from reports.championship_corrections import (
    ChampionshipCorrectionError, corrections_for, record_authoritative_result,
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


def _require_member(db: Session, *, league_id: int, user: User) -> int:
    """Return the caller's team id only when it belongs to this league.

    Championship reads expose league-wide standings, so they use the same
    membership boundary as the certified RC1 standings surface. Refuse before
    reading league state; an authenticated GM from another league gets 403.
    """
    team_id = getattr(user, "team_id", None)
    if team_id is None:
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": "Authenticated user owns no team in this league.",
        })
    team = (db.query(Team.id)
            .filter(Team.id == int(team_id), Team.league_id == league_id)
            .first())
    if team is None:
        raise HTTPException(status_code=403, detail={
            "reason_code": "not_a_league_member",
            "message": "Authenticated user owns no team in this league.",
        })
    return int(team_id)


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
    gm: User = Depends(get_current_gm),
):
    _require_member(db, league_id=league_id, user=gm)
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
    gm: User = Depends(get_current_gm),
):
    acting_team_id = _require_member(db, league_id=league_id, user=gm)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail="league not found")
    frozen = get_fantasystakes_championship(db, league_id=league_id)
    if frozen is not None:
        return {
            "status": "FINAL",
            "league_id": league_id,
            "season": frozen.season,
            "acting_team_id": acting_team_id,
            "scoring_through_week": frozen.scoring_through_week,
            "frozen_at": frozen.frozen_at.isoformat(),
            "rows": [_row_dict(r) for r in frozen.rows],
        }

    live = league_standings(db, league_id=league_id, acting_team_id=acting_team_id)
    rows = []
    ordered = live.overall
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
        "acting_team_id": acting_team_id,
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


class ResultCorrectionRequest(BaseModel):
    """Names the CONTEST and its corrected authoritative RESULT. Never an amount.

    There is deliberately no cents field, no score field, and no generic
    championship edit endpoint. The commissioner states what the result actually
    was; the Credits are derived from posted ledger state and, for prop pools,
    from the same certified even-split allocator ordinary settlement uses.

    `admit_late_settlement` is the other half of the lifecycle: an eligible
    contest whose ORDINARY settlement landed after the freeze already has correct
    economics, so it is admitted to the Championship without any corrective
    posting. That path takes no corrected result because nothing is being
    restated.
    """

    competition_type: str = Field(..., pattern="^(versus|prop_pool)$")
    contest_ref: int = Field(..., ge=1)
    reason: str = Field(..., min_length=3, max_length=500)
    correction_key: str = Field(..., min_length=3, max_length=200)
    #: True  -> admit an eligible contest that settled normally after the freeze.
    #: False -> restate a settled contest to `corrected_result`.
    admit_late_settlement: bool = False
    #: Versus: {"outcome": "winner", "winner_team_id": N} or {"outcome": "push"}
    #: Prop pool: {"winner_team_ids": [N, ...]}
    corrected_result: dict | None = None


@router.post("/corrections")
def record_championship_correction(
    league_id: int,
    req: ResultCorrectionRequest,
    db: Session = Depends(get_db),
    comm: User = Depends(require_league_commissioner),
):
    """Admit or restate an eligible regular-season result after the freeze."""
    source = f"commissioner:{comm.id}"
    try:
        if req.admit_late_settlement:
            result = record_authoritative_result(
                db, league_id=league_id, competition_type=req.competition_type,
                contest_ref=req.contest_ref, reason=req.reason, source=source,
                correction_key=req.correction_key)
        else:
            if not req.corrected_result:
                raise HTTPException(
                    status_code=422,
                    detail="corrected_result is required unless "
                           "admit_late_settlement is true")
            if req.competition_type == "versus":
                payload = CorrectedVersusResult(
                    outcome=str(req.corrected_result.get("outcome", "")),
                    winner_team_id=(
                        int(req.corrected_result["winner_team_id"])
                        if req.corrected_result.get("winner_team_id") is not None
                        else None),
                )
            else:
                payload = CorrectedPoolResult(
                    winner_team_ids=tuple(
                        int(t) for t in
                        req.corrected_result.get("winner_team_ids", ())),
                )
            result = apply_result_correction(
                db, league_id=league_id, competition_type=req.competition_type,
                contest_ref=req.contest_ref, corrected_result=payload,
                reason=req.reason, source=source,
                correction_key=req.correction_key)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except ChampionshipCorrectionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "league_id": result.league_id,
        "season": result.season,
        "competition_type": result.competition_type,
        "contest_ref": result.contest_ref,
        "scoring_week": result.scoring_week,
        "replayed": result.replayed,
        "total_delta_cents": result.total_delta_cents,
        "rows": [
            {"team_id": r.team_id, "revision": r.revision,
             "previous_net_cents": r.previous_net_cents,
             "corrected_net_cents": r.corrected_net_cents,
             "delta_cents": r.delta_cents}
            for r in result.rows
        ],
    }


@router.get("/corrections")
def list_championship_corrections(
    league_id: int,
    db: Session = Depends(get_db),
    gm: User = Depends(get_current_gm),
):
    _require_member(db, league_id=league_id, user=gm)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail="league not found")
    rows = corrections_for(db, league_id=league_id, season=int(league.season))
    return {
        "league_id": league_id,
        "season": int(league.season),
        "corrections": [
            {"team_id": r.team_id, "competition_type": r.competition_type,
             "contest_ref": r.contest_ref, "scoring_week": r.scoring_week,
             "revision": r.revision, "previous_net_cents": r.previous_net_cents,
             "corrected_net_cents": r.corrected_net_cents,
             "delta_cents": r.delta_cents, "reason": r.reason,
             "source": r.source}
            for r in rows
        ],
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
