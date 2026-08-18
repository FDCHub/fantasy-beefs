"""RC2 — commissioner-defined FantasyStakes Championship funding.

This is additive to the existing Yahoo Championship economy. RC1's
`championship_contribution_cents` remains the Yahoo Championship contribution;
this module adds an independently editable FantasyStakes Championship
contribution that DEFAULTS to the Yahoo amount and freezes at season activation.

The FantasyStakes Championship Pot is deliberately CLOSED after activation. Its
only funding source is the per-GM contribution frozen here. No Top-Off, Weekly
Minimum expiry/return, Pool remainder, wallet balance or season-close sweep may
post to this account.

WHY A COMPANION TABLE IN RC2. The existing LeagueSeasonEconomyConfig is already
a certified, frozen record used by RC1 and its migration. Reinterpreting or
adding a mandatory column to historical rows would turn every pre-RC2 season
into a partial configuration. A separate league-season record lets RC2 add the
new independent input without rewriting one historical Credit or making an old
row mean something new.

ABSENCE HAS TWO DIFFERENT, SAFE MEANINGS:

* before activation, no row means "use the Yahoo Championship contribution as
  the setup default";
* on replay of a season that already has RC1 SeasonAllocation rows but no RC2
  championship rows, no row means "legacy season — do not backfill".

The season-allocation orchestrator decides which state it is in under its League
lock and calls `fund_for_new_activation` only on the create path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Integer,
    UniqueConstraint, Uuid,
)
from sqlalchemy.orm import Session, relationship

from db.schema import Base, League, Team
from economy.league_economy_config import (
    CENTS_PER_CREDIT,
    MAX_CHAMPIONSHIP_CONTRIBUTION_CENTS,
    MIN_CHAMPIONSHIP_CONTRIBUTION_CENTS,
    EconomyConfigError,
    read_draft,
    read_frozen,
    _validate_one,
)
from ledger.ledger import post as ledger_post


REASON_ALREADY_FROZEN = "FS_CHAMPIONSHIP_CONFIG_FROZEN"
REASON_PARTIAL_ALLOCATION = "FS_CHAMPIONSHIP_ALLOCATION_PARTIAL"
REASON_ALLOCATION_CONFLICT = "FS_CHAMPIONSHIP_ALLOCATION_CONFLICT"
REASON_CONFIG_MISSING = "FS_CHAMPIONSHIP_CONFIG_MISSING"

FS_CHAMPIONSHIP_ALLOCATION_DOOR = "fantasystakes_championship_allocation"


class FantasyStakesChampionshipConfig(Base):
    """One league-season's independent FS Championship contribution.

    NULL `frozen_at` is an explicit commissioner edit still open for change.
    A missing row before activation means the setup default mirrors the Yahoo
    Championship contribution; activation materializes and freezes that default.
    """

    __tablename__ = "fantasystakes_championship_config"
    __table_args__ = (
        UniqueConstraint("league_id", "season", name="uq_fs_champ_config_league_season"),
        CheckConstraint(
            "contribution_cents BETWEEN 100 AND 100000",
            name="ck_fs_champ_config_contribution"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id", name="fk_fs_champ_config_league"),
                       nullable=False)
    season = Column(Integer, nullable=False)
    contribution_cents = Column(Integer, nullable=False)
    frozen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    league = relationship("League")


class FantasyStakesChampionshipAllocation(Base):
    """One GM's immutable contribution to the fixed FS Championship Pot."""

    __tablename__ = "fantasystakes_championship_allocation"
    __table_args__ = (
        UniqueConstraint("league_id", "season", "team_id",
                         name="uq_fs_champ_alloc_league_season_team"),
        CheckConstraint("contribution_cents > 0", name="ck_fs_champ_alloc_positive"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id", name="fk_fs_champ_alloc_league"),
                       nullable=False)
    season = Column(Integer, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", name="fk_fs_champ_alloc_team"),
                     nullable=False)
    contribution_cents = Column(Integer, nullable=False)
    ledger_posting_id = Column(Uuid, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))

    league = relationship("League")
    team = relationship("Team")


@dataclass(frozen=True)
class FantasyStakesChampionshipDraft:
    league_id: int
    season: int
    contribution_cents: int
    configured: bool
    frozen: bool


@dataclass(frozen=True)
class FantasyStakesChampionshipFunding:
    league_id: int
    season: int
    contribution_per_gm_cents: int
    team_count: int
    pot_cents: int
    posting_ids: tuple[uuid.UUID, ...]
    created: bool


def fs_championship_account(league_id: int) -> str:
    """The fixed league-season-independent account namespace for one league.

    League season close makes it zero before a later season can be activated,
    matching the existing championship/skunk account lifecycle. The allocation
    rows and ledger events carry the season identity for audit.
    """
    return f"fs_championship:{league_id}"


def fs_championship_issuance_account(league_id: int, season: int) -> str:
    return f"fs_championship_issuance:{league_id}:{season}"


def _validate(value) -> int:
    return _validate_one(
        value,
        field="fantasystakes_championship_contribution_cents",
        minimum=MIN_CHAMPIONSHIP_CONTRIBUTION_CENTS,
        maximum=MAX_CHAMPIONSHIP_CONTRIBUTION_CENTS,
    )


def read_draft_contribution(
    db: Session, *, league_id: int, season: int | None = None,
) -> FantasyStakesChampionshipDraft:
    """Read explicit FS config, or mirror Yahoo contribution as setup default."""
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise EconomyConfigError("ECONOMY_CONFIG_MISSING_INPUT",
                                 f"league {league_id} not found")
    effective = league.season if season is None else int(season)
    row = (db.query(FantasyStakesChampionshipConfig)
           .filter(FantasyStakesChampionshipConfig.league_id == league_id,
                   FantasyStakesChampionshipConfig.season == effective)
           .first())
    if row is not None:
        return FantasyStakesChampionshipDraft(
            league_id=league_id,
            season=effective,
            contribution_cents=int(row.contribution_cents),
            configured=True,
            frozen=row.frozen_at is not None,
        )

    yahoo = read_draft(db, league_id=league_id, season=effective)
    return FantasyStakesChampionshipDraft(
        league_id=league_id,
        season=effective,
        contribution_cents=int(yahoo.championship_contribution_cents),
        configured=False,
        frozen=False,
    )


def set_draft_contribution(
    db: Session, *, league_id: int, contribution_cents: int,
    season: int | None = None,
) -> FantasyStakesChampionshipDraft:
    """Store an independent pre-activation FS contribution. Does not commit."""
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise EconomyConfigError("ECONOMY_CONFIG_MISSING_INPUT",
                                 f"league {league_id} not found")
    effective = league.season if season is None else int(season)
    value = _validate(contribution_cents)

    row = (db.query(FantasyStakesChampionshipConfig)
           .filter(FantasyStakesChampionshipConfig.league_id == league_id,
                   FantasyStakesChampionshipConfig.season == effective)
           .first())
    if row is not None and row.frozen_at is not None:
        raise EconomyConfigError(
            REASON_ALREADY_FROZEN,
            f"league {league_id} season {effective} froze its FantasyStakes "
            f"Championship contribution at {row.contribution_cents} cents and "
            f"it cannot be edited after season activation.")
    if row is None:
        row = FantasyStakesChampionshipConfig(
            league_id=league_id,
            season=effective,
            contribution_cents=value,
        )
        db.add(row)
    else:
        row.contribution_cents = value
    db.flush()
    return read_draft_contribution(db, league_id=league_id, season=effective)


def _contribution_for_activation(
    db: Session, *, league_id: int, season: int,
) -> tuple[FantasyStakesChampionshipConfig, int]:
    """Materialize/freeze the explicit or mirrored default. Does not commit."""
    now = datetime.now(timezone.utc)
    row = (db.query(FantasyStakesChampionshipConfig)
           .filter(FantasyStakesChampionshipConfig.league_id == league_id,
                   FantasyStakesChampionshipConfig.season == season)
           .first())

    if row is None:
        # Prefer the frozen Yahoo economy row when the parent activation has
        # already frozen it in this transaction; fall back to the draft-shaped
        # read only for the unconfigured legacy economy path.
        yahoo = read_frozen(db, league_id=league_id, season=season)
        yahoo_amount = (int(yahoo.championship_contribution_cents)
                        if yahoo is not None
                        else int(read_draft(db, league_id=league_id,
                                            season=season).championship_contribution_cents))
        row = FantasyStakesChampionshipConfig(
            league_id=league_id,
            season=season,
            contribution_cents=_validate(yahoo_amount),
            frozen_at=now,
        )
        db.add(row)
        db.flush()
        return row, int(row.contribution_cents)

    value = _validate(row.contribution_cents)
    if row.frozen_at is None:
        row.frozen_at = now
        db.flush()
    return row, value


def fund_for_new_activation(
    db: Session, *, league_id: int, season: int, team_ids: list[int] | tuple[int, ...],
) -> FantasyStakesChampionshipFunding:
    """Freeze and fund the fixed FS Championship Pot inside parent activation.

    ONLY FOR THE PARENT SEASON-ALLOCATION CREATE PATH. Does not commit. The
    caller already holds the League activation lock and commits this work in the
    same transaction as the ordinary SeasonAllocation rows.

    Every team gets one additive allocation row and one balanced posting from a
    dedicated FS Championship issuance source to the shared fixed pot. The
    existing SeasonAllocation, Weekly Minimum reserve, Yahoo Championship
    reserve and Top-Off cap anchor remain byte-for-byte their RC1 meanings.
    """
    expected = tuple(sorted(int(t) for t in team_ids))
    if not expected:
        raise EconomyConfigError(REASON_PARTIAL_ALLOCATION,
                                 "cannot fund a FantasyStakes Championship for zero teams")

    existing = (db.query(FantasyStakesChampionshipAllocation)
                .filter(FantasyStakesChampionshipAllocation.league_id == league_id,
                        FantasyStakesChampionshipAllocation.season == season)
                .order_by(FantasyStakesChampionshipAllocation.team_id)
                .all())
    if existing:
        raise EconomyConfigError(
            REASON_PARTIAL_ALLOCATION,
            f"new season activation for league {league_id} season {season} found "
            f"pre-existing FantasyStakes Championship allocation rows. Refusing "
            f"to mix a new parent allocation with existing fixed-pot funding.")

    _, contribution = _contribution_for_activation(
        db, league_id=league_id, season=season)

    posting_ids: list[uuid.UUID] = []
    for team_id in expected:
        posting_id = ledger_post(
            [
                (fs_championship_issuance_account(league_id, season), -contribution),
                (fs_championship_account(league_id), contribution),
            ],
            door=FS_CHAMPIONSHIP_ALLOCATION_DOOR,
            session=db,
        )
        posting_ids.append(posting_id)
        db.add(FantasyStakesChampionshipAllocation(
            league_id=league_id,
            season=season,
            team_id=team_id,
            contribution_cents=contribution,
            ledger_posting_id=posting_id,
        ))

    db.flush()
    return FantasyStakesChampionshipFunding(
        league_id=league_id,
        season=season,
        contribution_per_gm_cents=contribution,
        team_count=len(expected),
        pot_cents=contribution * len(expected),
        posting_ids=tuple(posting_ids),
        created=True,
    )


def validate_replay_or_legacy(
    db: Session, *, league_id: int, season: int, team_ids: list[int] | tuple[int, ...],
) -> FantasyStakesChampionshipFunding | None:
    """Validate RC2 companion state on parent activation replay.

    None means a genuine legacy/pre-RC2 season: parent SeasonAllocation exists
    but neither FS config nor FS allocation rows exist, so RC2 does NOT backfill
    a new championship into an already-activated season.
    """
    expected = tuple(sorted(int(t) for t in team_ids))
    config_row = (db.query(FantasyStakesChampionshipConfig)
                  .filter(FantasyStakesChampionshipConfig.league_id == league_id,
                          FantasyStakesChampionshipConfig.season == season)
                  .first())
    rows = (db.query(FantasyStakesChampionshipAllocation)
            .filter(FantasyStakesChampionshipAllocation.league_id == league_id,
                    FantasyStakesChampionshipAllocation.season == season)
            .order_by(FantasyStakesChampionshipAllocation.team_id)
            .all())

    if config_row is None and not rows:
        return None
    if config_row is None or config_row.frozen_at is None:
        raise EconomyConfigError(
            REASON_CONFIG_MISSING,
            f"league {league_id} season {season} has FantasyStakes Championship "
            f"allocation state without one frozen contribution config.")

    present = tuple(r.team_id for r in rows)
    if present != expected:
        raise EconomyConfigError(
            REASON_PARTIAL_ALLOCATION,
            f"league {league_id} season {season} has FS Championship allocations "
            f"for teams {list(present)}, expected {list(expected)}. Refusing to "
            f"repair or backfill a partially funded fixed pot.")

    contribution = _validate(config_row.contribution_cents)
    conflicts = [(r.team_id, r.contribution_cents) for r in rows
                 if int(r.contribution_cents) != contribution]
    if conflicts:
        raise EconomyConfigError(
            REASON_ALLOCATION_CONFLICT,
            f"league {league_id} season {season} froze FS Championship "
            f"contribution={contribution} cents but allocation rows disagree: "
            f"{conflicts}.")

    return FantasyStakesChampionshipFunding(
        league_id=league_id,
        season=season,
        contribution_per_gm_cents=contribution,
        team_count=len(rows),
        pot_cents=contribution * len(rows),
        posting_ids=tuple(r.ledger_posting_id for r in rows),
        created=False,
    )
