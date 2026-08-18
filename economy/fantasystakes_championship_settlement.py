"""RC2 FantasyStakes Championship Pot settlement.

The pot is fixed at season activation. Settlement pays the frozen regular-season
FantasyStakes podium 60/30/10 with the POR tie rule: occupied prize shares are
pooled and split equally among tied GMs. No competitive tiebreaker is invented.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, JSON, UniqueConstraint, Uuid
from sqlalchemy.orm import Session, relationship

from db.schema import Base, League
from economy.fantasystakes_championship_allocation import (
    DOOR_FS_CHAMPIONSHIP_DISTRIBUTION,
    FantasyStakesChampionshipAllocation,
    pot_account,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post
from reports.championship_read_model import (
    ChampionshipAward,
    get_fantasystakes_championship,
    tied_championship_distribution,
)


class FantasyStakesChampionshipDistributionRun(Base):
    __tablename__ = "fantasystakes_championship_distribution_run"
    __table_args__ = (
        UniqueConstraint("league_id", "season", name="uq_fs_champ_dist_league_season"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    season = Column(Integer, nullable=False)
    pot_cents = Column(BigInteger, nullable=False)
    posting_id = Column(Uuid, nullable=False, unique=True)
    awards_json = Column(JSON, nullable=False)
    distributed_at = Column(DateTime(timezone=True), nullable=False)
    league = relationship("League")


@dataclass(frozen=True)
class ChampionshipSettlementResult:
    league_id: int
    season: int
    pot_cents: int
    awards: tuple[ChampionshipAward, ...]
    posting_id: uuid.UUID
    replayed: bool


def _wallet(team_id: int) -> str:
    return f"wallet:{team_id}"


def _decode_awards(payload) -> tuple[ChampionshipAward, ...]:
    return tuple(ChampionshipAward(
        team_id=int(a["team_id"]),
        place=int(a["place"]),
        championship_score_cents=int(a["championship_score_cents"]),
        amount_cents=int(a["amount_cents"]),
        tied=bool(a["tied"]),
    ) for a in payload)


def settle_fantasystakes_championship(
    db: Session, *, league_id: int, now: datetime | None = None
) -> ChampionshipSettlementResult:
    """Distribute the fixed pot exactly once. Owns the supplied transaction."""
    now = now or datetime.now(timezone.utc)
    try:
        league = (db.query(League).filter(League.id == league_id)
                  .with_for_update(key_share=True).first())
        if league is None:
            raise ValueError(f"league {league_id} not found")
        season = int(league.season)

        existing = (db.query(FantasyStakesChampionshipDistributionRun)
                    .filter(FantasyStakesChampionshipDistributionRun.league_id == league_id,
                            FantasyStakesChampionshipDistributionRun.season == season)
                    .one_or_none())
        if existing is not None:
            db.rollback()
            return ChampionshipSettlementResult(
                league_id=league_id, season=season,
                pot_cents=int(existing.pot_cents),
                awards=_decode_awards(existing.awards_json),
                posting_id=existing.posting_id, replayed=True)

        snapshot = get_fantasystakes_championship(
            db, league_id=league_id, season=season)
        if snapshot is None:
            raise ValueError("FantasyStakes Championship standings are not frozen")

        allocations = (db.query(FantasyStakesChampionshipAllocation)
                       .filter(FantasyStakesChampionshipAllocation.league_id == league_id,
                               FantasyStakesChampionshipAllocation.season == season)
                       .all())
        team_ids = {r.team_id for r in allocations}
        expected_team_ids = {r.team_id for r in snapshot.rows}
        if team_ids != expected_team_ids:
            raise ValueError("FantasyStakes Championship allocation does not cover the frozen field")
        expected_pot = sum(int(r.contribution_cents) for r in allocations)
        account = pot_account(league_id, season)
        actual_pot = int(_balance_of_in_session(db, account))
        if actual_pot != expected_pot:
            raise ValueError(
                f"FantasyStakes Championship Pot is {actual_pot} cents; fixed funded amount is {expected_pot}")

        awards = tied_championship_distribution(expected_pot, snapshot.rows)
        legs = [(account, -expected_pot)] + [
            (_wallet(a.team_id), a.amount_cents) for a in awards if a.amount_cents
        ]
        posting_id = ledger_post(
            legs, door=DOOR_FS_CHAMPIONSHIP_DISTRIBUTION, session=db)
        payload = [
            {"team_id": a.team_id, "place": a.place,
             "championship_score_cents": a.championship_score_cents,
             "amount_cents": a.amount_cents, "tied": a.tied}
            for a in awards
        ]
        db.add(FantasyStakesChampionshipDistributionRun(
            league_id=league_id, season=season, pot_cents=expected_pot,
            posting_id=posting_id, awards_json=payload, distributed_at=now))
        db.flush()
        db.commit()
        return ChampionshipSettlementResult(
            league_id=league_id, season=season, pot_cents=expected_pot,
            awards=awards, posting_id=posting_id, replayed=False)
    except Exception:
        db.rollback()
        raise
