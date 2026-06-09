"""FastAPI router for /health decision-engine endpoints.

GET /health/team/{team_id}     -- TeamHealth for one team
GET /health/league/{league_id} -- TeamHealth for all teams (power-ranking style)

No math lives here. Routes call engine methods and serialize results.
"""

from __future__ import annotations

import dataclasses
import os
import sys

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.provider import MockProvider
from db.deps import get_db
from engine.lineup_optimizer import LineupOptimizer
from engine.season_sim import SeasonSimulator
from engine.team_health import TeamHealthAssembler

router = APIRouter(prefix="/health", tags=["health"])

_provider = MockProvider()
_simulator = SeasonSimulator()
_assembler = TeamHealthAssembler()


def _serialize(health) -> dict:
    return dataclasses.asdict(health)


@router.get("/team/{team_id}")
def team_health(
    team_id: int,
    week: int = Query(default=1, ge=1, le=17),
    db: Session = Depends(get_db),
) -> dict:
    """Return three-horizon TeamHealth for one team."""
    try:
        league   = _provider.get_league(1)
        roster   = _provider.get_roster(team_id, week)
        schedule = _provider.get_schedule(1)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    week_results = _simulator.simulate(team_id, roster, schedule, league, week, db)
    health       = _assembler.assemble(team_id, week_results, roster, league, week)
    return _serialize(health)


@router.get("/team/{team_id}/lineup")
def team_lineup(
    team_id: int,
    week: int = Query(default=1, ge=1, le=17),
) -> dict:
    """Return the optimized starting lineup and bench for one team."""
    try:
        roster = _provider.get_roster(team_id, week)
        config = _provider.get_league(1)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    starters = LineupOptimizer().optimize(roster, config)
    starter_ids = {p.player_id for p in starters}
    bench = [p for p in roster.players if p.player_id not in starter_ids]

    def _fmt(p):
        return {
            "player_id":     p.player_id,
            "name":          p.name,
            "position":      p.position,
            "projected_pts": p.projected_pts,
            "injury_status": p.injury_status,
        }

    return {
        "team_id":   team_id,
        "team_name": roster.team_name,
        "week":      week,
        "starters":  [_fmt(p) for p in starters],
        "bench":     [_fmt(p) for p in bench],
    }


@router.get("/league/{league_id}")
def league_health(
    league_id: int,
    week: int = Query(default=1, ge=1, le=17),
    db: Session = Depends(get_db),
) -> list:
    """Return TeamHealth for every team in the league (power-ranking style)."""
    league   = _provider.get_league(league_id)
    schedule = _provider.get_schedule(league_id)

    results = []
    for team_id in range(1, league.n_teams + 1):
        try:
            roster = _provider.get_roster(team_id, week)
        except ValueError:
            continue
        week_results = _simulator.simulate(team_id, roster, schedule, league, week, db)
        health       = _assembler.assemble(team_id, week_results, roster, league, week)
        results.append(_serialize(health))
    return results
