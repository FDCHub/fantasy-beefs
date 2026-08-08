"""FastAPI router for /war-room decision-engine endpoints.

POST /war-room/evaluate  --  evaluate a candidate roster move against current TeamHealth

No math lives here. Route calls engine methods and serialises results.
"""
from __future__ import annotations

import dataclasses
import os
import sys
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.provider import MockProvider, PlayerProj, RosterState
from db.deps import get_db
from db.schema import Player, Projection, Roster
from engine.decision_value import evaluate_move
from engine.season_sim import SeasonSimulator
from engine.team_health import TeamHealthAssembler

router = APIRouter(prefix="/war-room", tags=["war-room"])

_provider  = MockProvider()
_simulator = SeasonSimulator()
_assembler = TeamHealthAssembler()


# ── Request schema ─────────────────────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    team_id:            int
    move_type:          str                    # "waiver_add" | "trade" | "hold"
    week:               int        = 1
    add_player_id:      Optional[int]       = None
    drop_player_id:     Optional[int]       = None
    give_player_ids:    Optional[list[int]] = None
    receive_player_ids: Optional[list[int]] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _lookup_player_proj(player_id: int, week: int, db: Session) -> PlayerProj:
    """Build a PlayerProj from DB Player + Projection rows.

    Bypasses RawProj because the DB stores projected_points (total),
    not the individual raw stats that RawProj requires.
    Falls back to 0.0 projected_pts if no projection row exists for the week.
    """
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")

    proj = (
        db.query(Projection)
        .filter(
            Projection.player_id == player_id,
            Projection.week      == week,
            Projection.season    == 2024,
        )
        .order_by(Projection.id.desc())
        .first()
    )

    return PlayerProj(
        player_id     = player_id,
        name          = player.name,
        position      = player.position,
        injury_status = proj.injury_status if proj else None,
        projected_pts = proj.projected_points if proj else 0.0,
    )


def _apply_move(req: EvaluateRequest, roster: RosterState, db: Session) -> RosterState:
    """Return a new RosterState with the requested move applied.

    Replicates RosterStateEngine.apply_move logic but accepts PlayerProj
    directly from the DB instead of going through RawProj -> to_player_proj,
    since the DB does not store the raw per-stat fields RawProj requires.
    """
    players = list(roster.players)

    if req.move_type == "hold":
        pass

    elif req.move_type == "waiver_add":
        if req.add_player_id is None or req.drop_player_id is None:
            raise HTTPException(
                status_code=400,
                detail="waiver_add requires both add_player_id and drop_player_id",
            )
        players = [p for p in players if p.player_id != req.drop_player_id]
        if len(players) == len(roster.players):
            raise HTTPException(
                status_code=400,
                detail=f"drop_player_id {req.drop_player_id} not found on roster",
            )
        players.append(_lookup_player_proj(req.add_player_id, req.week, db))

    elif req.move_type == "trade":
        if not req.give_player_ids or not req.receive_player_ids:
            raise HTTPException(
                status_code=400,
                detail="trade requires both give_player_ids and receive_player_ids",
            )
        give_set = set(req.give_player_ids)
        missing  = give_set - {p.player_id for p in players}
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"give_player_ids not found on roster: {sorted(missing)}",
            )
        players = [p for p in players if p.player_id not in give_set]
        for pid in req.receive_player_ids:
            players.append(_lookup_player_proj(pid, req.week, db))

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown move_type {req.move_type!r}. Expected 'waiver_add', 'trade', or 'hold'.",
        )

    return RosterState(
        team_id   = roster.team_id,
        team_name = roster.team_name,
        week      = roster.week,
        players   = players,
    )


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/evaluate")
def evaluate(req: EvaluateRequest, db: Session = Depends(get_db)) -> dict:
    """Evaluate a candidate roster move and return a DecisionValue.

    Runs TeamHealth simulation twice — before and after the move —
    then diffs the results into win_prob_delta, playoff_odds_delta,
    champ_odds_delta, weekly_deltas, verdict, and confidence.
    """
    try:
        league        = _provider.get_league(1)
        schedule      = _provider.get_schedule(1)
        before_roster = _provider.get_roster(req.team_id, req.week)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    before_results = _simulator.simulate(
        req.team_id, before_roster, schedule, league, req.week, db,
    )
    before_health = _assembler.assemble(
        req.team_id, before_results, before_roster, league, req.week,
    )

    after_roster = _apply_move(req, before_roster, db)

    after_results = _simulator.simulate(
        req.team_id, after_roster, schedule, league, req.week, db,
    )
    after_health = _assembler.assemble(
        req.team_id, after_results, after_roster, league, req.week,
    )

    result = evaluate_move(before_health, after_health)
    return dataclasses.asdict(result)


@router.get("/free-agents")
def free_agents(
    team_id:  int           = Query(..., description="Requesting team — used for context"),
    position: Optional[str] = Query(default=None, description="QB | RB | WR | TE | K | DEF"),
    week:     int           = Query(default=1, ge=1, le=17),
    db:       Session       = Depends(get_db),
) -> list:
    """Return free agents (players with no roster entry) sorted by projected points."""
    rostered_ids = db.query(Roster.player_id).subquery()

    q = (
        db.query(Player, Projection)
        .outerjoin(
            Projection,
            (Projection.player_id == Player.id)
            & (Projection.week    == week)
            & (Projection.season  == 2024),
        )
        .filter(Player.id.notin_(rostered_ids))
    )

    if position:
        q = q.filter(Player.position == position.upper())

    rows = (
        q.order_by(Projection.projected_points.desc())
        .limit(50)
        .all()
    )

    return [
        {
            "player_id":        player.id,
            "name":             player.name,
            "position":         player.position,
            "projected_points": proj.projected_points if proj else 0.0,
        }
        for player, proj in rows
    ]
