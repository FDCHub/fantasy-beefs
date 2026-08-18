"""RC2 season activation extension for the FantasyStakes Championship Pot.

RC1's season allocation remains immutable and unchanged. RC2 adds one recoverable,
idempotent stage after the base allocation: freeze the independently editable
FantasyStakes Championship contribution and fund the fixed pot. Gameplay may
regard RC2 activation as complete only when both stages exist.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from db.schema import League, SeasonAllocation, Team
from economy.fantasystakes_championship_allocation import (
    FantasyStakesChampionshipAllocationResult,
    allocation_state,
    freeze_config,
    stage_allocation,
)


class RC2SeasonActivationError(ValueError):
    pass


@dataclass(frozen=True)
class RC2SeasonActivationResult:
    league_id: int
    season: int
    team_ids: tuple[int, ...]
    weekly_plus_yahoo_per_gm_cents: int
    fantasystakes_championship_per_gm_cents: int
    season_opening_allocation_per_gm_cents: int
    fantasystakes_championship_pot_cents: int
    created: bool


def activate_fantasystakes_championship_stage(
    league_id: int, db: Session
) -> RC2SeasonActivationResult:
    """Freeze/fund the RC2 FantasyStakes Championship stage. Owns transaction.

    The RC1/base SeasonAllocation must already be complete. This makes the RC2
    extension recoverable without mutating or reopening the certified RC1
    allocation rows. A failed second stage is visible and retryable; it never
    causes a second base allocation or a duplicate championship contribution.
    """
    try:
        league = (db.query(League)
                  .filter(League.id == league_id)
                  .with_for_update(key_share=True)
                  .first())
        if league is None:
            raise RC2SeasonActivationError(f"league {league_id} not found")
        season = int(league.season)
        teams = (db.query(Team).filter(Team.league_id == league_id)
                 .order_by(Team.id).all())
        team_ids = tuple(t.id for t in teams)
        if not team_ids:
            raise RC2SeasonActivationError("league has no teams")

        base_rows = (db.query(SeasonAllocation)
                     .filter(SeasonAllocation.league_id == league_id,
                             SeasonAllocation.season == season)
                     .order_by(SeasonAllocation.team_id).all())
        if {r.team_id for r in base_rows} != set(team_ids):
            raise RC2SeasonActivationError(
                "base Season-Opening Allocation is not complete; activate the base economy first")
        base_amounts = {int(r.buyin_cents) for r in base_rows}
        if len(base_amounts) != 1:
            raise RC2SeasonActivationError(
                "base Season-Opening Allocation differs across GMs")
        base_per_gm = base_amounts.pop()

        cfg = freeze_config(db, league_id=league_id, season=season)
        contribution = int(cfg.contribution_cents)
        state, _ = allocation_state(
            db, league_id=league_id, season=season, team_ids=team_ids,
            contribution_cents=contribution)
        if state == "partial":
            raise RC2SeasonActivationError(
                "FantasyStakes Championship allocation is partial; refusing automatic repair")
        if state == "conflict":
            raise RC2SeasonActivationError(
                "FantasyStakes Championship allocation conflicts with frozen contribution")

        staged: FantasyStakesChampionshipAllocationResult = stage_allocation(
            db, league_id=league_id, season=season, team_ids=team_ids,
            contribution_cents=contribution)
        db.commit()
        return RC2SeasonActivationResult(
            league_id=league_id,
            season=season,
            team_ids=team_ids,
            weekly_plus_yahoo_per_gm_cents=base_per_gm,
            fantasystakes_championship_per_gm_cents=contribution,
            season_opening_allocation_per_gm_cents=base_per_gm + contribution,
            fantasystakes_championship_pot_cents=contribution * len(team_ids),
            created=staged.created,
        )
    except Exception:
        db.rollback()
        raise
