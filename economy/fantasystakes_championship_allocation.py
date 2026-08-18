"""RC2-CHAMP-ECON — FantasyStakes Championship contribution and fixed pot.

This module is deliberately additive to the existing Yahoo Championship reserve.
The existing ``LeagueSeasonEconomyConfig.championship_contribution_cents`` remains
the Yahoo Championship contribution. RC2 adds a second independently editable
FantasyStakes Championship contribution which defaults to the Yahoo amount.

The FantasyStakes contribution is first advanced to the GM's championship
reserve under the governed Season-Opening Allocation door. That positive,
GM-keyed leg is what makes the contribution part of the GM's posted season
advance. A second balanced posting immediately commits exactly that contribution
from the reserve into the isolated FantasyStakes Championship Pot. Both postings
and the allocation row live in one caller-owned transaction.

The FantasyStakes Championship Pot is CLOSED after activation: its only normal
funding source is the per-GM contribution frozen here. Top-offs, Weekly Minimum
shortfalls/returns, pool remainders, wallet remnants and postseason play never
fund this pot.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Session, relationship

from db.schema import Base, League
from economy.economy_events import reserve_account
from economy.league_economy_config import (
    DEFAULT_CHAMPIONSHIP_CONTRIBUTION_CENTS,
    MAX_CHAMPIONSHIP_CONTRIBUTION_CENTS,
    MIN_CHAMPIONSHIP_CONTRIBUTION_CENTS,
    EconomyConfigError,
    REASON_NOT_WHOLE_CREDITS,
    REASON_OUT_OF_RANGE,
    read_draft as read_economy_draft,
)
from ledger.ledger import SEASON_ALLOCATION_DOOR, post as ledger_post

CENTS_PER_CREDIT = 100
DOOR_FS_CHAMPIONSHIP_ALLOCATION = SEASON_ALLOCATION_DOOR
DOOR_FS_CHAMPIONSHIP_COMMITMENT = "fantasystakes_championship_commitment"
DOOR_FS_CHAMPIONSHIP_DISTRIBUTION = "fantasystakes_championship_distribution"

REASON_FROZEN = "FS_CHAMPIONSHIP_CONFIG_FROZEN"
REASON_PARTIAL = "FS_CHAMPIONSHIP_ALLOCATION_PARTIAL"
REASON_CONFLICT = "FS_CHAMPIONSHIP_ALLOCATION_CONFLICT"
REASON_NO_TEAMS = "FS_CHAMPIONSHIP_ALLOCATION_NO_TEAMS"


class FantasyStakesChampionshipConfig(Base):
    """One league-season's editable-then-frozen FantasyStakes contribution."""
    __tablename__ = "fantasystakes_championship_config"
    __table_args__ = (
        UniqueConstraint("league_id", "season", name="uq_fs_champ_config_league_season"),
        CheckConstraint(
            "contribution_cents BETWEEN 100 AND 100000",
            name="ck_fs_champ_config_contribution"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    season = Column(Integer, nullable=False)
    contribution_cents = Column(Integer, nullable=False)
    frozen_at = Column(DateTime(timezone=True), nullable=True)
    league = relationship("League")


class FantasyStakesChampionshipAllocation(Base):
    """One GM's immutable contribution to the fixed league-season FS pot."""
    __tablename__ = "fantasystakes_championship_allocation"
    __table_args__ = (
        UniqueConstraint("league_id", "season", "team_id",
                         name="uq_fs_champ_alloc_league_season_team"),
        CheckConstraint("contribution_cents > 0", name="ck_fs_champ_alloc_positive"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    season = Column(Integer, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    contribution_cents = Column(Integer, nullable=False)
    # The posting id is the GM-attributed Season-Opening Allocation posting.
    # The paired commitment posting is in the same transaction and is
    # independently identifiable by its dedicated door + reserve/pot accounts.
    posting_id = Column(Uuid, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
    league = relationship("League")


@dataclass(frozen=True)
class FantasyStakesChampionshipConfigView:
    league_id: int
    season: int
    yahoo_championship_contribution_cents: int
    fantasystakes_championship_contribution_cents: int
    configured: bool
    frozen: bool

    @property
    def contributions_match(self) -> bool:
        return (self.yahoo_championship_contribution_cents
                == self.fantasystakes_championship_contribution_cents)


@dataclass(frozen=True)
class FantasyStakesChampionshipAllocationResult:
    league_id: int
    season: int
    team_ids: tuple[int, ...]
    contribution_per_gm_cents: int
    pot_cents: int
    created: bool
    posting_ids: tuple[uuid.UUID, ...]


def pot_account(league_id: int, season: int) -> str:
    return f"fantasystakes_championship:{league_id}:{season}"


def issuance_account(league_id: int, season: int) -> str:
    return f"season_issuance:{league_id}:{season}"


def _validate_contribution(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EconomyConfigError(REASON_OUT_OF_RANGE,
                                 "FantasyStakes Championship contribution must be integer cents")
    if not (MIN_CHAMPIONSHIP_CONTRIBUTION_CENTS <= value
            <= MAX_CHAMPIONSHIP_CONTRIBUTION_CENTS):
        raise EconomyConfigError(REASON_OUT_OF_RANGE,
                                 "FantasyStakes Championship contribution is outside the governed range")
    if value % CENTS_PER_CREDIT:
        raise EconomyConfigError(REASON_NOT_WHOLE_CREDITS,
                                 "FantasyStakes Championship contribution must be whole Credits")
    return int(value)


def _row(db: Session, *, league_id: int, season: int):
    return (db.query(FantasyStakesChampionshipConfig)
            .filter(FantasyStakesChampionshipConfig.league_id == league_id,
                    FantasyStakesChampionshipConfig.season == season)
            .one_or_none())


def read_config(db: Session, *, league_id: int, season: int | None = None
                ) -> FantasyStakesChampionshipConfigView:
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise EconomyConfigError("ECONOMY_CONFIG_MISSING_INPUT", f"league {league_id} not found")
    effective = league.season if season is None else int(season)
    economy = read_economy_draft(db, league_id=league_id, season=effective)
    row = _row(db, league_id=league_id, season=effective)
    fs_amount = (row.contribution_cents if row is not None
                 else economy.championship_contribution_cents)
    if fs_amount is None:
        fs_amount = DEFAULT_CHAMPIONSHIP_CONTRIBUTION_CENTS
    return FantasyStakesChampionshipConfigView(
        league_id=league_id,
        season=effective,
        yahoo_championship_contribution_cents=int(economy.championship_contribution_cents),
        fantasystakes_championship_contribution_cents=int(fs_amount),
        configured=row is not None,
        frozen=bool(row is not None and row.frozen_at is not None),
    )


def set_contribution(db: Session, *, league_id: int, contribution_cents: int,
                     season: int | None = None
                     ) -> FantasyStakesChampionshipConfigView:
    """Set the FS contribution independently before activation. Does not commit."""
    value = _validate_contribution(contribution_cents)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise EconomyConfigError("ECONOMY_CONFIG_MISSING_INPUT", f"league {league_id} not found")
    effective = league.season if season is None else int(season)
    row = _row(db, league_id=league_id, season=effective)
    if row is not None and row.frozen_at is not None:
        raise EconomyConfigError(REASON_FROZEN,
                                 f"FantasyStakes Championship contribution froze at {row.frozen_at}")
    if row is None:
        row = FantasyStakesChampionshipConfig(
            league_id=league_id, season=effective, contribution_cents=value)
        db.add(row)
    else:
        row.contribution_cents = value
    db.flush()
    return read_config(db, league_id=league_id, season=effective)


def freeze_config(db: Session, *, league_id: int, season: int,
                  now: datetime | None = None) -> FantasyStakesChampionshipConfig:
    """Freeze FS contribution; absent explicit edit defaults to Yahoo amount."""
    now = now or datetime.now(timezone.utc)
    row = _row(db, league_id=league_id, season=season)
    if row is None:
        economy = read_economy_draft(db, league_id=league_id, season=season)
        row = FantasyStakesChampionshipConfig(
            league_id=league_id,
            season=season,
            contribution_cents=_validate_contribution(
                int(economy.championship_contribution_cents)),
        )
        db.add(row)
        db.flush()
    if row.frozen_at is None:
        row.frozen_at = now
        db.flush()
    return row


def allocation_state(db: Session, *, league_id: int, season: int,
                     team_ids: tuple[int, ...], contribution_cents: int):
    rows = (db.query(FantasyStakesChampionshipAllocation)
            .filter(FantasyStakesChampionshipAllocation.league_id == league_id,
                    FantasyStakesChampionshipAllocation.season == season)
            .order_by(FantasyStakesChampionshipAllocation.team_id)
            .all())
    if not rows:
        return "empty", rows
    present = {r.team_id for r in rows}
    expected = set(team_ids)
    if present != expected:
        return "partial", rows
    if any(int(r.contribution_cents) != int(contribution_cents) for r in rows):
        return "conflict", rows
    return "complete", rows


def stage_allocation(db: Session, *, league_id: int, season: int,
                     team_ids: tuple[int, ...], contribution_cents: int,
                     now: datetime | None = None
                     ) -> FantasyStakesChampionshipAllocationResult:
    """Stage the fixed pot inside the caller's activation transaction. No commit.

    For each GM the transaction has two balanced postings:

      1. season_issuance -> reserve:{team} under ``season_allocation``.
         This is the posted, GM-attributed additional season advance.
      2. reserve:{team} -> fantasystakes_championship:{league}:{season}
         under the RC2-only commitment door. This commits the contribution to
         the isolated pot while leaving the existing Yahoo reserve balance
         untouched after the pair completes.
    """
    if not team_ids:
        raise ValueError(f"[{REASON_NO_TEAMS}] league {league_id} has no teams")
    contribution = _validate_contribution(contribution_cents)
    state, rows = allocation_state(
        db, league_id=league_id, season=season, team_ids=team_ids,
        contribution_cents=contribution)
    if state == "partial":
        raise ValueError(f"[{REASON_PARTIAL}] incomplete FantasyStakes Championship allocation")
    if state == "conflict":
        raise ValueError(f"[{REASON_CONFLICT}] stored FantasyStakes Championship contribution differs")
    if state == "complete":
        return FantasyStakesChampionshipAllocationResult(
            league_id=league_id, season=season, team_ids=team_ids,
            contribution_per_gm_cents=contribution,
            pot_cents=contribution * len(team_ids),
            created=False, posting_ids=())

    now = now or datetime.now(timezone.utc)
    posting_ids: list[uuid.UUID] = []
    for team_id in team_ids:
        # Step 1: attribute the additional Season-Opening Allocation to this GM.
        posting_id = ledger_post(
            [(issuance_account(league_id, season), -contribution),
             (reserve_account(team_id), contribution)],
            door=DOOR_FS_CHAMPIONSHIP_ALLOCATION,
            session=db,
        )
        posting_ids.append(posting_id)

        # Step 2: commit exactly the newly advanced amount into the isolated FS
        # pot. The prior posting has been flushed into this same transaction, so
        # the reserve has sufficient funds; rollback removes both postings.
        ledger_post(
            [(reserve_account(team_id), -contribution),
             (pot_account(league_id, season), contribution)],
            door=DOOR_FS_CHAMPIONSHIP_COMMITMENT,
            session=db,
        )

        db.add(FantasyStakesChampionshipAllocation(
            league_id=league_id,
            season=season,
            team_id=team_id,
            contribution_cents=contribution,
            posting_id=posting_id,
            created_at=now,
        ))
    db.flush()
    return FantasyStakesChampionshipAllocationResult(
        league_id=league_id, season=season, team_ids=team_ids,
        contribution_per_gm_cents=contribution,
        pot_cents=contribution * len(team_ids),
        created=True, posting_ids=tuple(posting_ids))
