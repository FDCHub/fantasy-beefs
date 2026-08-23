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

THE "CLOSED POT" RULE IS LEGACY-ERA DOCTRINE AND IS SCOPED AS SUCH. Under
`RULESET_LEGACY` the pot's only funding source is the per-GM contribution frozen
here, and top-offs, Weekly Minimum returns, pool remainders, wallet remnants and
postseason play never fund it. Under `RULESET_FINAL_POR` the pot is deliberately
OPEN and grows during the season: WP-4 sweeps each unspent Weekly Minimum into it
at week close. The per-GM contribution architecture in this module is itself
retired for Final POR seasons by WP-5; nothing here is deleted, because the
contributions already posted under the legacy era are real and still read.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Session, relationship

from db.schema import Base, League
from economy.economy_events import (
    fantasystakes_championship_account, reserve_account,
)
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
#: WP-5 — the per-GM contribution model is retired for RULESET_FINAL_POR.
REASON_RETIRED_ERA = "FS_CHAMPIONSHIP_ALLOCATION_RETIRED_ERA"


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
    """The league-season FantasyStakes Championship Pot.

    DELEGATES rather than re-spelling the name. WP-4 gave this pot a second
    writer (the Week-Close Weekly Minimum sweep) in a module that must not
    import this one, so the literal moved to `economy.economy_events`, which is
    where every shared account name lives. Same string, one definition."""
    return fantasystakes_championship_account(league_id, season)


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

    # ── FINAL POR · WP-5 — THE PER-GM CONTRIBUTION MODEL IS RETIRED ──────────
    #
    # This function advances `reserve:{team}` to every GM and immediately
    # commits it into the pot, which is the per-GM prepaid architecture §11
    # replaces: it makes the pot's size scale with the field and makes its
    # existence every GM's debt. Under the Final POR the FantasyStakes
    # Championship Pot is MINTED at Weekly Minimum x Regular-Season Weeks by
    # `economy.championship_pots.mint_fantasystakes_base_pot`, at activation,
    # with no GM leg at all.
    #
    # REFUSES RATHER THAN NO-OPS, and rather than being deleted. Running it on a
    # Final POR season would double the pot — once minted, once contributed —
    # and open a real obligation against every GM for the second half. Deleting
    # it would strand every legacy season that still needs to READ the
    # allocation rows it wrote. Refusing is the only behaviour that is safe for
    # both eras.
    from ruleset import is_final_por

    if is_final_por(db, league_id=league_id, season=season):
        raise ValueError(
            f"[{REASON_RETIRED_ERA}] league {league_id} season {season} is "
            f"governed by the Final POR, whose FantasyStakes Championship Pot "
            f"is a minted league-level allocation (Weekly Minimum x "
            f"Regular-Season Weeks), not a per-GM contribution. Refusing to "
            f"advance a per-GM championship reserve into it.")

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
        posting_id = ledger_post(
            [(issuance_account(league_id, season), -contribution),
             (reserve_account(team_id), contribution)],
            door=DOOR_FS_CHAMPIONSHIP_ALLOCATION,
            session=db,
        )
        posting_ids.append(posting_id)

        # The funded-balance guard reads posted state. Flush this first posting
        # into the still-uncommitted transaction so the commitment debit sees
        # the newly advanced reserve. A later error rolls both postings back.
        db.flush()

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
