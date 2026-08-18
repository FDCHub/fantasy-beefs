"""RC2-CHAMP-1 — FantasyStakes Championship scoring and frozen podium.

The live Standings read model answers "who is winning FantasyStakes right now?"
and deliberately owns no lifecycle. RC2 adds a separate championship lifecycle:
regular-season competitive results are frozen immediately before the Yahoo
postseason, while postseason FantasyStakes play may continue moving Credits.

This module therefore SNAPSHOTS the already-certified competitive read model at
the regular-season boundary instead of trying to reconstruct a historical wallet
or re-price old wagers. The snapshot is only permitted when every regular-season
FantasyStakes matchup and prop-pool occurrence is terminal and before any
postseason competitive result can contaminate the live competitive net.

Championship Score is exactly the frozen competitive result:

    matchup_net + prop_pool_net

Wallet balance, opening allocations, top-offs, reserve movements and other
noncompetitive Credit movements are outside that read model and therefore outside
Championship Score by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import groupby

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Session, relationship

from db.schema import Base, BeefChallenge, Bet, League, PoolEconomicEvent, PoolInstance, Team
from reports.standings_read_model import league_standings


REASON_LEAGUE_NOT_FOUND = "FS_CHAMPIONSHIP_LEAGUE_NOT_FOUND"
REASON_BOUNDARY_UNAVAILABLE = "FS_CHAMPIONSHIP_BOUNDARY_UNAVAILABLE"
REASON_TOO_EARLY = "FS_CHAMPIONSHIP_TOO_EARLY"
REASON_REGULAR_VERSUS_OPEN = "FS_CHAMPIONSHIP_REGULAR_VERSUS_OPEN"
REASON_REGULAR_POOL_OPEN = "FS_CHAMPIONSHIP_REGULAR_POOL_OPEN"
REASON_POSTSEASON_CONTAMINATED = "FS_CHAMPIONSHIP_POSTSEASON_ALREADY_ACTIVE"
REASON_PARTIAL_SNAPSHOT = "FS_CHAMPIONSHIP_PARTIAL_SNAPSHOT"
REASON_NO_TEAMS = "FS_CHAMPIONSHIP_NO_TEAMS"


class FantasyStakesChampionshipError(ValueError):
    """A championship freeze or read was refused with a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


class FantasyStakesChampionshipFreeze(Base):
    """One immutable freeze marker per league-season.

    The marker owns the boundary. Score rows point to it and are insert-only.
    There is no reopen/reset protocol in FantasyStakes 1.0 RC2.
    """

    __tablename__ = "fantasystakes_championship_freeze"
    __table_args__ = (
        UniqueConstraint("league_id", "season", name="uq_fs_champ_freeze_league_season"),
        CheckConstraint("playoff_start_week > 0", name="ck_fs_champ_freeze_playoff_week"),
        CheckConstraint("scoring_through_week = playoff_start_week - 1",
                        name="ck_fs_champ_freeze_cutoff"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id", name="fk_fs_champ_freeze_league"),
                       nullable=False)
    season = Column(Integer, nullable=False)
    playoff_start_week = Column(Integer, nullable=False)
    scoring_through_week = Column(Integer, nullable=False)
    frozen_at = Column(DateTime(timezone=True), nullable=False)

    league = relationship("League")


class FantasyStakesChampionshipScore(Base):
    """One team's immutable score inside one FantasyStakes Championship freeze."""

    __tablename__ = "fantasystakes_championship_score"
    __table_args__ = (
        UniqueConstraint("freeze_id", "team_id", name="uq_fs_champ_score_freeze_team"),
        UniqueConstraint("league_id", "season", "team_id",
                         name="uq_fs_champ_score_league_season_team"),
        CheckConstraint(
            "championship_score_cents = matchup_net_cents + prop_pool_net_cents",
            name="ck_fs_champ_score_sum"),
        Index("ix_fs_champ_score_league_season", "league_id", "season"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    freeze_id = Column(Integer,
                       ForeignKey("fantasystakes_championship_freeze.id",
                                  name="fk_fs_champ_score_freeze"),
                       nullable=False)
    league_id = Column(Integer, ForeignKey("leagues.id", name="fk_fs_champ_score_league"),
                       nullable=False)
    season = Column(Integer, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", name="fk_fs_champ_score_team"),
                     nullable=False)
    matchup_net_cents = Column(BigInteger, nullable=False)
    prop_pool_net_cents = Column(BigInteger, nullable=False)
    championship_score_cents = Column(BigInteger, nullable=False)

    freeze = relationship("FantasyStakesChampionshipFreeze")
    league = relationship("League")
    team = relationship("Team")


@dataclass(frozen=True)
class ChampionshipRow:
    team_id: int
    team_name: str
    owner: str
    matchup_net_cents: int
    prop_pool_net_cents: int
    championship_score_cents: int
    place: int
    tied: bool


@dataclass(frozen=True)
class ChampionshipSnapshot:
    league_id: int
    season: int
    playoff_start_week: int
    scoring_through_week: int
    frozen_at: datetime
    rows: tuple[ChampionshipRow, ...]


@dataclass(frozen=True)
class ChampionshipAward:
    """One paid team under the tied 60/30/10 podium rule."""

    team_id: int
    place: int
    championship_score_cents: int
    amount_cents: int
    tied: bool


def _teams(db: Session, league_id: int) -> list[Team]:
    return (db.query(Team).filter(Team.league_id == league_id)
            .order_by(Team.id).all())


def _existing_snapshot(db: Session, *, league_id: int, season: int
                       ) -> ChampionshipSnapshot | None:
    marker = (db.query(FantasyStakesChampionshipFreeze)
              .filter(FantasyStakesChampionshipFreeze.league_id == league_id,
                      FantasyStakesChampionshipFreeze.season == season)
              .first())
    if marker is None:
        return None

    teams = _teams(db, league_id)
    score_rows = (db.query(FantasyStakesChampionshipScore)
                  .filter(FantasyStakesChampionshipScore.freeze_id == marker.id)
                  .order_by(FantasyStakesChampionshipScore.championship_score_cents.desc(),
                            FantasyStakesChampionshipScore.team_id.asc())
                  .all())
    if len(score_rows) != len(teams) or {r.team_id for r in score_rows} != {t.id for t in teams}:
        raise FantasyStakesChampionshipError(
            REASON_PARTIAL_SNAPSHOT,
            f"league {league_id} season {season} has a championship freeze marker "
            f"but {len(score_rows)} score row(s) for {len(teams)} team(s). The "
            f"immutable snapshot is partial and is never repaired automatically.")

    team_by_id = {t.id: t for t in teams}
    ranked = _rank_rows(score_rows, team_by_id)
    return ChampionshipSnapshot(
        league_id=league_id,
        season=season,
        playoff_start_week=marker.playoff_start_week,
        scoring_through_week=marker.scoring_through_week,
        frozen_at=marker.frozen_at,
        rows=ranked,
    )


def _rank_rows(score_rows, team_by_id: dict[int, Team]) -> tuple[ChampionshipRow, ...]:
    ordered = sorted(score_rows,
                     key=lambda r: (-int(r.championship_score_cents), int(r.team_id)))
    result: list[ChampionshipRow] = []
    cursor = 0
    for score, grouped in groupby(ordered, key=lambda r: int(r.championship_score_cents)):
        group = list(grouped)
        place = cursor + 1
        tied = len(group) > 1
        for row in group:
            team = team_by_id[row.team_id]
            result.append(ChampionshipRow(
                team_id=row.team_id,
                team_name=team.team_name,
                owner=team.owner,
                matchup_net_cents=int(row.matchup_net_cents),
                prop_pool_net_cents=int(row.prop_pool_net_cents),
                championship_score_cents=int(score),
                place=place,
                tied=tied,
            ))
        cursor += len(group)
    return tuple(result)


def freeze_fantasystakes_championship(
    db: Session, *, league_id: int, now: datetime | None = None,
) -> ChampionshipSnapshot:
    """Freeze the regular-season FantasyStakes Championship standings.

    Does not commit. The caller owns the transaction.

    The League row is locked before state is inspected. A replay returns the
    immutable existing snapshot. A first freeze refuses until the provider says
    the playoff boundary has been reached, refuses while any regular-season
    scoring result remains open, and refuses if postseason economics have
    already changed the live competitive result.
    """
    now = now or datetime.now(timezone.utc)

    league = (db.query(League)
              .filter(League.id == league_id)
              .with_for_update(key_share=True)
              .first())
    if league is None:
        raise FantasyStakesChampionshipError(
            REASON_LEAGUE_NOT_FOUND, f"league {league_id} not found")

    existing = _existing_snapshot(db, league_id=league_id, season=league.season)
    if existing is not None:
        return existing

    if league.playoff_start_week is None:
        raise FantasyStakesChampionshipError(
            REASON_BOUNDARY_UNAVAILABLE,
            f"league {league_id} has no authoritative playoff_start_week; the "
            f"FantasyStakes Championship cutoff cannot be inferred.")
    cutoff = int(league.playoff_start_week)
    if cutoff <= 0:
        raise FantasyStakesChampionshipError(
            REASON_BOUNDARY_UNAVAILABLE,
            f"league {league_id} carries invalid playoff_start_week={cutoff}.")

    if league.provider_current_week is None or int(league.provider_current_week) < cutoff:
        raise FantasyStakesChampionshipError(
            REASON_TOO_EARLY,
            f"league {league_id} has not reached its Yahoo postseason boundary "
            f"(provider_current_week={league.provider_current_week!r}, "
            f"playoff_start_week={cutoff}). Refusing to freeze early.")

    teams = _teams(db, league_id)
    if not teams:
        raise FantasyStakesChampionshipError(
            REASON_NO_TEAMS, f"league {league_id} has no teams")

    # Every regular-season Versus wager that can change realized net must be
    # terminal before the score is frozen.
    open_versus = (db.query(Bet)
                   .join(BeefChallenge, Bet.beef_challenge_id == BeefChallenge.id)
                   .filter(BeefChallenge.league_id == league_id,
                           BeefChallenge.week < cutoff,
                           Bet.status == "pending")
                   .count())
    if open_versus:
        raise FantasyStakesChampionshipError(
            REASON_REGULAR_VERSUS_OPEN,
            f"{open_versus} regular-season FantasyStakes matchup wager(s) are "
            f"still unsettled; Championship Score is realized net only.")

    open_pools = (db.query(PoolInstance)
                  .filter(PoolInstance.league_id == league_id,
                          PoolInstance.season == league.season,
                          PoolInstance.week < cutoff,
                          PoolInstance.settled.is_(False))
                  .count())
    if open_pools:
        raise FantasyStakesChampionshipError(
            REASON_REGULAR_POOL_OPEN,
            f"{open_pools} regular-season FantasyStakes prop-pool occurrence(s) "
            f"are unsettled; Championship Score is realized net only.")

    # A late freeze must never snapshot a score after postseason competition has
    # already changed it. Pending Versus escrow is neutral in the certified live
    # read model, so only terminal postseason Versus results contaminate it.
    postseason_versus = (db.query(Bet)
                          .join(BeefChallenge, Bet.beef_challenge_id == BeefChallenge.id)
                          .filter(BeefChallenge.league_id == league_id,
                                  BeefChallenge.week >= cutoff,
                                  Bet.status.in_(("won", "lost", "push")))
                          .count())
    postseason_pool_events = (db.query(PoolEconomicEvent)
                               .filter(PoolEconomicEvent.league_id == league_id,
                                       PoolEconomicEvent.season == league.season,
                                       PoolEconomicEvent.week >= cutoff,
                                       PoolEconomicEvent.posting_id.isnot(None))
                               .count())
    if postseason_versus or postseason_pool_events:
        raise FantasyStakesChampionshipError(
            REASON_POSTSEASON_CONTAMINATED,
            f"postseason FantasyStakes economics already exist "
            f"(settled matchup bets={postseason_versus}, pool postings="
            f"{postseason_pool_events}). The regular-season championship "
            f"snapshot must be frozen before postseason results can move the "
            f"competitive ledger.")

    live = league_standings(db, league_id=league_id)
    marker = FantasyStakesChampionshipFreeze(
        league_id=league_id,
        season=league.season,
        playoff_start_week=cutoff,
        scoring_through_week=cutoff - 1,
        frozen_at=now,
    )
    db.add(marker)
    db.flush()

    for row in live.rows:
        db.add(FantasyStakesChampionshipScore(
            freeze_id=marker.id,
            league_id=league_id,
            season=league.season,
            team_id=row.team_id,
            matchup_net_cents=int(row.versus_net_cents),
            prop_pool_net_cents=int(row.pool_net_cents),
            championship_score_cents=int(row.net_cents),
        ))
    db.flush()

    snapshot = _existing_snapshot(db, league_id=league_id, season=league.season)
    if snapshot is None:  # pragma: no cover - marker was just inserted
        raise FantasyStakesChampionshipError(
            REASON_PARTIAL_SNAPSHOT, "championship snapshot disappeared after insert")
    return snapshot


def get_fantasystakes_championship(
    db: Session, *, league_id: int, season: int | None = None,
) -> ChampionshipSnapshot | None:
    """Return the frozen championship snapshot, or None while the chase is live."""
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise FantasyStakesChampionshipError(
            REASON_LEAGUE_NOT_FOUND, f"league {league_id} not found")
    effective = league.season if season is None else int(season)
    return _existing_snapshot(db, league_id=league_id, season=effective)


def tied_championship_distribution(
    total_cents: int,
    rows: tuple[ChampionshipRow, ...] | list[ChampionshipRow],
    split: tuple[int, int, int] = (60, 30, 10),
) -> tuple[ChampionshipAward, ...]:
    """Apply the RC2 tied-podium rule to a fixed FantasyStakes Championship Pot.

    The three ordinal prize slots are calculated in integer cents. As in the
    existing championship arithmetic, any percentage-flooring remainder is
    assigned to the first ordinal slot so the full pot is conserved. If a tie
    occupies multiple slots, those slot amounts are pooled and split equally
    across every tied GM. Any indivisible cent remainder in that equal split is
    assigned by ascending canonical team id solely for arithmetic determinism.
    """
    if isinstance(total_cents, bool) or not isinstance(total_cents, int) or total_cents < 0:
        raise ValueError("total_cents must be a non-negative integer")
    if len(split) != 3 or any(isinstance(p, bool) or not isinstance(p, int) or p < 0
                              for p in split) or sum(split) != 100:
        raise ValueError("split must contain three non-negative integer percentages summing to 100")
    if not rows:
        raise ValueError("rows must contain at least one championship team")
    if len({r.team_id for r in rows}) != len(rows):
        raise ValueError("rows contain duplicate team ids")

    ordered = sorted(rows, key=lambda r: (-r.championship_score_cents, r.team_id))

    slot_amounts = [total_cents * pct // 100 for pct in split]
    slot_amounts[0] += total_cents - sum(slot_amounts)

    awards: list[ChampionshipAward] = []
    cursor = 0
    for score, grouped in groupby(ordered, key=lambda r: r.championship_score_cents):
        group = list(grouped)
        place = cursor + 1
        first_slot = cursor
        last_slot = min(cursor + len(group), len(slot_amounts))
        prize_pool = sum(slot_amounts[first_slot:last_slot]) if first_slot < len(slot_amounts) else 0
        if prize_pool:
            base, remainder = divmod(prize_pool, len(group))
            by_team = sorted(group, key=lambda r: r.team_id)
            for i, row in enumerate(by_team):
                awards.append(ChampionshipAward(
                    team_id=row.team_id,
                    place=place,
                    championship_score_cents=int(score),
                    amount_cents=base + (1 if i < remainder else 0),
                    tied=len(group) > 1,
                ))
        cursor += len(group)
        if cursor >= len(ordered) or cursor >= 3 and prize_pool == 0:
            # No later group can occupy a paid ordinal slot.
            if cursor >= 3:
                break

    if sum(a.amount_cents for a in awards) != total_cents:
        raise AssertionError("championship distribution failed to conserve the pot")
    return tuple(sorted(awards, key=lambda a: (a.place, a.team_id)))
