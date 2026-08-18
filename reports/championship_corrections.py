"""RC2 — authoritative post-freeze corrections to eligible regular-season results.

THE RULE THIS IMPLEMENTS. Championship scoring ends with the final Yahoo
regular-season week, but a contest that BELONGS to that window still counts when
its authoritative result lands late, and an authoritative correction to such a
contest must reach the final Championship Score. Neither is new postseason
competition, so neither reopens eligibility.

TWO CONCEPTS THAT WERE PREVIOUSLY ONE
--------------------------------------
    ELIGIBILITY  is immutable and is a property of the CONTEST: its scoring week
                 against `playoff_start_week`. Decided once, never revisited. A
                 postseason contest never becomes eligible; an eligible contest
                 never stops being eligible.

    RESULT       is authoritative-but-correctable. It may land late, and it may
                 be restated by a governed correction.

The freeze closes eligibility and the field. It does NOT close results. That is
the FROZEN / FINAL distinction: FROZEN means "no new competition counts"; FINAL
means "every eligible result is in".

WHY THE DELTA IS A TIME-BOUNDED LEDGER READ AND NOT A NUMBER SOMEBODY TYPES
---------------------------------------------------------------------------
A team's competitive contribution from one contest, evaluated at time T, is

    contribution(T) = Σ(spend-account legs ≤ T) + Σ(that contest's escrow ≤ T)

— the same two terms the certified live read model uses, scoped to one contest.
The escrow term is why an unsettled wager is not a loss. Therefore

    delta = contribution(now) − contribution(frozen_at)
          = Σ(legs created AFTER frozen_at)

for both term families together. The freeze timestamp IS the baseline, so no
baseline table is needed and the arithmetic telescopes: recording a correction
twice recomputes the same cumulative number rather than adding a second time.

THE AMOUNT IS NEVER SUPPLIED BY A CALLER. It is read out of postings that the
governed settlement engines already made. A commissioner names the CONTEST; the
Credits are whatever the ledger says they are.

WHAT THIS MODULE DELIBERATELY CANNOT DO
---------------------------------------
Move money. It records the championship consequence of economics that already
happened. There is no door here, no posting, and no wallet adjustment — a
correction after payout fails closed rather than clawing anything back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer,
    String, UniqueConstraint, Uuid, text,
)
from sqlalchemy.orm import Session, relationship

from db.schema import Base, BeefChallenge, Bet, League, PoolEconomicEvent, PoolInstance, Wallet
from economy.economy_events import wallet_account

COMPETITION_VERSUS = "versus"
COMPETITION_PROP_POOL = "prop_pool"
COMPETITION_TYPES = (COMPETITION_VERSUS, COMPETITION_PROP_POOL)

REASON_NOT_FROZEN = "FS_CORRECTION_CHAMPIONSHIP_NOT_FROZEN"
REASON_UNKNOWN_CONTEST = "FS_CORRECTION_CONTEST_NOT_FOUND"
REASON_NOT_ELIGIBLE = "FS_CORRECTION_CONTEST_NOT_ELIGIBLE"
REASON_TEAM_NOT_IN_FIELD = "FS_CORRECTION_TEAM_NOT_IN_FUNDED_FIELD"
REASON_ALREADY_PAID = "FS_CORRECTION_CHAMPIONSHIP_ALREADY_PAID"
REASON_BAD_COMPETITION_TYPE = "FS_CORRECTION_UNKNOWN_COMPETITION_TYPE"


class ChampionshipCorrectionError(ValueError):
    """A correction was refused with a stable reason code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


class FantasyStakesChampionshipCorrection(Base):
    """One team's authoritative post-freeze result movement in one contest.

    APPEND-ONLY. A restatement writes a new row with the next `revision`; no row
    is ever updated or deleted, so the original freeze snapshot and every prior
    revision remain readable exactly as recorded.

    `corrected_net_cents` is CUMULATIVE post-freeze movement for the pair, not an
    increment. `delta_cents` is the increment against the previous revision, and
    the CHECK below keeps the two consistent by construction.
    """

    __tablename__ = "fantasystakes_championship_correction"
    __table_args__ = (
        # The caller's key is claimed once PER TEAM, because one correction to
        # one contest restates a result for each GM in it. Replay is detected on
        # the key alone; this pair is the structural backstop.
        UniqueConstraint("correction_key", "team_id",
                         name="uq_fs_champ_correction_key_team"),
        UniqueConstraint("league_id", "season", "competition_type", "contest_ref",
                         "team_id", "revision",
                         name="uq_fs_champ_correction_revision"),
        CheckConstraint("delta_cents = corrected_net_cents - previous_net_cents",
                        name="ck_fs_champ_correction_delta"),
        CheckConstraint("revision > 0", name="ck_fs_champ_correction_revision"),
        CheckConstraint("scoring_week > 0", name="ck_fs_champ_correction_week"),
        CheckConstraint("competition_type IN ('versus','prop_pool')",
                        name="ck_fs_champ_correction_type"),
        Index("ix_fs_champ_correction_league_season", "league_id", "season"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    freeze_id = Column(Integer,
                       ForeignKey("fantasystakes_championship_freeze.id",
                                  name="fk_fs_champ_correction_freeze"),
                       nullable=False)
    league_id = Column(Integer, ForeignKey("leagues.id",
                                           name="fk_fs_champ_correction_league"),
                       nullable=False)
    season = Column(Integer, nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id",
                                         name="fk_fs_champ_correction_team"),
                     nullable=False)
    #: 'versus' or 'prop_pool'. The competition this contest belongs to.
    competition_type = Column(String, nullable=False)
    #: beef_challenges.id for Versus, pool_instance.id for a prop pool. The
    #: identifier of the contest itself — never a free-form label.
    contest_ref = Column(Integer, nullable=False)
    #: The contest's own scoring week. Proven < playoff_start_week before any
    #: row is written, which is what makes eligibility immutable.
    scoring_week = Column(Integer, nullable=False)
    revision = Column(Integer, nullable=False)
    previous_net_cents = Column(BigInteger, nullable=False)
    corrected_net_cents = Column(BigInteger, nullable=False)
    delta_cents = Column(BigInteger, nullable=False)
    reason = Column(String, nullable=False)
    source = Column(String, nullable=False)
    correction_key = Column(String, nullable=False)
    #: The corrective ledger posting, when this correction MOVED Credits. NULL
    #: for an admission of a late ordinary settlement, whose economics the
    #: settlement engine already posted under its own door.
    posting_id = Column(Uuid, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)

    freeze = relationship("FantasyStakesChampionshipFreeze")
    league = relationship("League")
    team = relationship("Team")


@dataclass(frozen=True)
class CorrectionRow:
    team_id: int
    competition_type: str
    contest_ref: int
    scoring_week: int
    revision: int
    previous_net_cents: int
    corrected_net_cents: int
    delta_cents: int
    reason: str
    source: str
    correction_key: str


@dataclass(frozen=True)
class CorrectionResult:
    league_id: int
    season: int
    competition_type: str
    contest_ref: int
    scoring_week: int
    rows: tuple[CorrectionRow, ...]
    replayed: bool

    @property
    def total_delta_cents(self) -> int:
        return sum(r.delta_cents for r in self.rows)


# ── Contest resolution ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Contest:
    competition_type: str
    contest_ref: int
    scoring_week: int
    #: Ledger accounts that identify this contest's postings. For Versus these
    #: are the two `escrow:{bet_id}` accounts; a prop pool is identified by its
    #: recorded economic-event posting ids instead.
    escrow_accounts: tuple[str, ...]
    posting_ids: tuple[str, ...]
    team_ids: tuple[int, ...]
    resolved: bool


def _versus_contest(db: Session, league_id: int, contest_ref: int) -> _Contest:
    challenge = (db.query(BeefChallenge)
                 .filter(BeefChallenge.id == contest_ref,
                         BeefChallenge.league_id == league_id)
                 .first())
    if challenge is None:
        raise ChampionshipCorrectionError(
            REASON_UNKNOWN_CONTEST,
            f"no FantasyStakes matchup {contest_ref} in league {league_id}. A "
            f"correction names a governed GM-versus-GM challenge; a legacy "
            f"single-GM wager has no challenge and is not FantasyStakes "
            f"competition, so it can never be corrected into the Championship.")

    bet_ids = [b for b in (challenge.challenger_bet_id, challenge.challenged_bet_id)
               if b is not None]
    rows = (db.query(Bet.id, Wallet.team_id)
            .join(Wallet, Bet.wallet_id == Wallet.id)
            .filter(Bet.id.in_(bet_ids) if bet_ids else False,
                    Bet.beef_challenge_id == challenge.id)
            .all()) if bet_ids else []
    team_ids = tuple(sorted({int(r[1]) for r in rows}))
    resolved = bool(bet_ids) and all(
        (db.query(Bet.status).filter(Bet.id == b).scalar() in ("won", "lost", "push"))
        for b in bet_ids)
    return _Contest(
        competition_type=COMPETITION_VERSUS,
        contest_ref=int(challenge.id),
        scoring_week=int(challenge.week),
        escrow_accounts=tuple(f"escrow:{int(r[0])}" for r in rows),
        posting_ids=(),
        team_ids=team_ids,
        resolved=resolved,
    )


def _pool_contest(db: Session, league_id: int, contest_ref: int) -> _Contest:
    instance = (db.query(PoolInstance)
                .filter(PoolInstance.id == contest_ref,
                        PoolInstance.league_id == league_id)
                .first())
    if instance is None:
        raise ChampionshipCorrectionError(
            REASON_UNKNOWN_CONTEST,
            f"no FantasyStakes prop-pool occurrence {contest_ref} in league "
            f"{league_id}.")
    events = (db.query(PoolEconomicEvent.posting_id)
              .filter(PoolEconomicEvent.pool_instance_id == instance.id,
                      PoolEconomicEvent.posting_id.isnot(None))
              .all())
    return _Contest(
        competition_type=COMPETITION_PROP_POOL,
        contest_ref=int(instance.id),
        scoring_week=int(instance.week),
        escrow_accounts=(),
        # BOTH TEXTUAL FORMS. `Uuid` renders as 32 hex characters on SQLite and
        # as a dashed uuid on PostgreSQL, and this comparison is raw SQL, so
        # matching one form only would silently find nothing on the other
        # dialect. Emitting both keeps the read dialect-safe without teaching
        # this module which database it is on.
        posting_ids=tuple({form
                           for r in events
                           for form in (str(r[0]), getattr(r[0], "hex", str(r[0])))}),
        team_ids=(),
        resolved=bool(instance.settled),
    )


def resolve_contest(db: Session, *, league_id: int, competition_type: str,
                    contest_ref: int) -> _Contest:
    if competition_type == COMPETITION_VERSUS:
        return _versus_contest(db, league_id, int(contest_ref))
    if competition_type == COMPETITION_PROP_POOL:
        return _pool_contest(db, league_id, int(contest_ref))
    raise ChampionshipCorrectionError(
        REASON_BAD_COMPETITION_TYPE,
        f"competition_type must be one of {COMPETITION_TYPES}, got "
        f"{competition_type!r}. FantasyStakes competition is GM-versus-GM "
        f"matchups and prop pools; nothing else can be corrected into the "
        f"Championship.")


# ── The delta, read out of the ledger ────────────────────────────────────────

def post_freeze_net_cents(db: Session, *, team_id: int, contest: _Contest,
                          frozen_at: datetime, doors: tuple[str, ...]) -> int:
    """This team's cumulative competitive movement in `contest` since the freeze.

    Both families of leg carry the same time filter, for the reason in the module
    docstring: contribution(T) is the spend-account sum plus the held escrow, so
    the difference between two instants is simply every leg written between them.

    A prop pool has no per-GM escrow; its postings are named directly by the
    `pool_economic_event` rows the Pool engine already writes, which is the same
    provenance `assert_pool_conservation` relies on.
    """
    db.flush()
    params: dict[str, object] = {
        "wallet": wallet_account(team_id),
        "min_pattern": f"min:{team_id}:%",
        "frozen_at": frozen_at,
    }
    door_ph = ", ".join(f":d{i}" for i in range(len(doors)))
    params.update({f"d{i}": d for i, d in enumerate(doors)})

    if contest.competition_type == COMPETITION_VERSUS:
        if not contest.escrow_accounts:
            return 0
        acct_ph = ", ".join(f":a{i}" for i in range(len(contest.escrow_accounts)))
        params.update({f"a{i}": a for i, a in enumerate(contest.escrow_accounts)})
        # (a) this GM's spend legs inside postings that touch this contest's
        #     escrow — the money that reached or left their wallet.
        clauses = ["((account = :wallet OR account LIKE :min_pattern) "
                   "AND posting_id IN (SELECT posting_id FROM ledger_entries "
                   f"                  WHERE account IN ({acct_ph})))"]
        # (b) this GM's OWN escrow inside the contest. An escrow account belongs
        #     to exactly one bet and that bet to one GM, so the opponent's escrow
        #     is never added here.
        own = _own_escrow_accounts(db, team_id, contest.escrow_accounts)
        if own:
            own_ph = ", ".join(f":o{i}" for i in range(len(own)))
            params.update({f"o{i}": a for i, a in enumerate(own)})
            clauses.append(f"account IN ({own_ph})")
        sql = (
            "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
            f"WHERE door IN ({door_ph}) AND created_at > :frozen_at "
            f"AND ({' OR '.join(clauses)})"
        )
        return int(db.execute(text(sql), params).scalar() or 0)

    if not contest.posting_ids:
        return 0
    post_ph = ", ".join(f":p{i}" for i in range(len(contest.posting_ids)))
    params.update({f"p{i}": p for i, p in enumerate(contest.posting_ids)})
    sql = (
        "SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries "
        f"WHERE door IN ({door_ph}) AND created_at > :frozen_at "
        "AND (account = :wallet OR account LIKE :min_pattern) "
        f"AND posting_id IN ({post_ph})"
    )
    return int(db.execute(text(sql), params).scalar() or 0)


def _own_escrow_accounts(db: Session, team_id: int,
                         accounts: tuple[str, ...]) -> tuple[str, ...]:
    """The subset of `accounts` whose bet belongs to this team's wallet."""
    if not accounts:
        return ()
    bet_ids = [int(a.split(":", 1)[1]) for a in accounts
               if a.split(":", 1)[1].isdigit()]
    if not bet_ids:
        return ()
    rows = (db.query(Bet.id)
            .join(Wallet, Bet.wallet_id == Wallet.id)
            .filter(Bet.id.in_(bet_ids), Wallet.team_id == team_id)
            .all())
    return tuple(f"escrow:{int(r[0])}" for r in rows)


# ── Public API ───────────────────────────────────────────────────────────────

def correction_totals(db: Session, *, league_id: int, season: int
                      ) -> dict[int, tuple[int, int]]:
    """Net recorded correction delta per team, split (matchup, prop_pool).

    Summing `delta_cents` across every revision telescopes to the latest
    cumulative value per (contest, team), which is why the corrected score is a
    plain addition rather than a per-contest reduction.

    SPLIT BY COMPETITION so the corrected row stays internally consistent: a
    championship row reports a matchup component and a prop-pool component that
    add to its score, and a correction has to land in the one it came from.
    """
    db.flush()
    rows = (db.query(FantasyStakesChampionshipCorrection.team_id,
                     FantasyStakesChampionshipCorrection.competition_type,
                     FantasyStakesChampionshipCorrection.delta_cents)
            .filter(FantasyStakesChampionshipCorrection.league_id == league_id,
                    FantasyStakesChampionshipCorrection.season == season)
            .all())
    totals: dict[int, tuple[int, int]] = {}
    for team_id, competition_type, delta in rows:
        versus, pool = totals.get(int(team_id), (0, 0))
        if competition_type == COMPETITION_VERSUS:
            versus += int(delta)
        else:
            pool += int(delta)
        totals[int(team_id)] = (versus, pool)
    return totals


def corrections_for(db: Session, *, league_id: int, season: int
                    ) -> tuple[CorrectionRow, ...]:
    """Every correction row, oldest first. The audit trail, unmodified."""
    rows = (db.query(FantasyStakesChampionshipCorrection)
            .filter(FantasyStakesChampionshipCorrection.league_id == league_id,
                    FantasyStakesChampionshipCorrection.season == season)
            .order_by(FantasyStakesChampionshipCorrection.id.asc())
            .all())
    return tuple(CorrectionRow(
        team_id=int(r.team_id), competition_type=r.competition_type,
        contest_ref=int(r.contest_ref), scoring_week=int(r.scoring_week),
        revision=int(r.revision), previous_net_cents=int(r.previous_net_cents),
        corrected_net_cents=int(r.corrected_net_cents),
        delta_cents=int(r.delta_cents), reason=r.reason, source=r.source,
        correction_key=r.correction_key) for r in rows)


def _competitive_doors(competition_type: str) -> tuple[str, ...]:
    from reports.standings_read_model import POOL_DOORS, VERSUS_DOORS

    return VERSUS_DOORS if competition_type == COMPETITION_VERSUS else POOL_DOORS


def record_authoritative_result(
    db: Session, *, league_id: int, competition_type: str, contest_ref: int,
    reason: str, source: str, correction_key: str,
    now: datetime | None = None,
) -> CorrectionResult:
    """Admit an eligible regular-season contest's authoritative result post-freeze.

    Does not commit; the caller owns the transaction. MOVES NO CREDITS.

    One entry point serves BOTH a result that lands late and a restatement of one
    already counted, because they are the same fact: this contest's authoritative
    competitive net has moved since the freeze. The caller names the CONTEST and
    never an amount.
    """
    from economy.fantasystakes_championship_settlement import (
        FantasyStakesChampionshipDistributionRun,
    )
    from reports.championship_read_model import (
        FantasyStakesChampionshipFreeze, funded_championship_field,
    )

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise ChampionshipCorrectionError(
            REASON_UNKNOWN_CONTEST, f"league {league_id} not found")
    season = int(league.season)

    marker = (db.query(FantasyStakesChampionshipFreeze)
              .filter(FantasyStakesChampionshipFreeze.league_id == league_id,
                      FantasyStakesChampionshipFreeze.season == season)
              .first())
    if marker is None:
        raise ChampionshipCorrectionError(
            REASON_NOT_FROZEN,
            f"league {league_id} season {season} has no frozen FantasyStakes "
            f"Championship. Before the freeze an eligible result needs no "
            f"correction: it is already inside the live competitive read model.")

    # PAYOUT IS THE POINT OF NO RETURN. RC2 builds no automatic economic
    # reversal, which is the ruling `ProviderConflict` and the settlement
    # recovery path already make elsewhere in this tree. A correction arriving
    # after the pot has been distributed is refused so a human resolves it,
    # rather than this function inventing a clawback nobody authorized.
    paid = (db.query(FantasyStakesChampionshipDistributionRun)
            .filter(FantasyStakesChampionshipDistributionRun.league_id == league_id,
                    FantasyStakesChampionshipDistributionRun.season == season)
            .one_or_none())
    if paid is not None:
        raise ChampionshipCorrectionError(
            REASON_ALREADY_PAID,
            f"league {league_id} season {season} distributed its FantasyStakes "
            f"Championship Pot at {paid.distributed_at}. RC2 performs no "
            f"automatic clawback and no re-payment; this correction is refused "
            f"and requires governed administrative recovery. Nothing was "
            f"recorded and no Credits moved.")

    contest = resolve_contest(db, league_id=league_id,
                              competition_type=competition_type,
                              contest_ref=contest_ref)

    # ELIGIBILITY IS IMMUTABLE AND IS THE CONTEST'S OWN SCORING WEEK. A
    # postseason contest can never be corrected into the Championship, and no
    # correction can move a contest across the boundary.
    if contest.scoring_week >= int(marker.playoff_start_week):
        raise ChampionshipCorrectionError(
            REASON_NOT_ELIGIBLE,
            f"{contest.competition_type} contest {contest.contest_ref} has "
            f"scoring week {contest.scoring_week}, on or after this league's "
            f"playoff_start_week={marker.playoff_start_week}. It is postseason "
            f"FantasyStakes play and is permanently outside the Championship "
            f"scoring window.")

    field = funded_championship_field(db, league_id=league_id, season=season)
    if not field:
        raise ChampionshipCorrectionError(
            REASON_NOT_FROZEN,
            f"league {league_id} season {season} has no funded championship "
            f"field; there is nothing a correction could apply to.")

    doors = _competitive_doors(contest.competition_type)
    # A matchup reaches its two GMs; a prop pool reaches the whole funded field.
    teams = contest.team_ids if contest.team_ids else tuple(sorted(field))
    outside = sorted(t for t in teams if t not in field)
    if outside:
        raise ChampionshipCorrectionError(
            REASON_TEAM_NOT_IN_FIELD,
            f"{contest.competition_type} contest {contest.contest_ref} involves "
            f"team(s) {outside} outside the funded FantasyStakes Championship "
            f"field. The funded field is immutable; a correction may restate a "
            f"result but may never enlarge the field.")

    already = (db.query(FantasyStakesChampionshipCorrection)
               .filter(FantasyStakesChampionshipCorrection.correction_key
                       == correction_key)
               .count())
    if already:
        return CorrectionResult(
            league_id=league_id, season=season,
            competition_type=contest.competition_type,
            contest_ref=contest.contest_ref, scoring_week=contest.scoring_week,
            rows=tuple(r for r in corrections_for(db, league_id=league_id,
                                                  season=season)
                       if r.correction_key == correction_key),
            replayed=True)

    written: list[CorrectionRow] = []
    for team_id in teams:
        corrected = post_freeze_net_cents(
            db, team_id=team_id, contest=contest,
            frozen_at=marker.frozen_at, doors=doors)
        prior = (db.query(FantasyStakesChampionshipCorrection)
                 .filter(FantasyStakesChampionshipCorrection.league_id == league_id,
                         FantasyStakesChampionshipCorrection.season == season,
                         FantasyStakesChampionshipCorrection.competition_type
                         == contest.competition_type,
                         FantasyStakesChampionshipCorrection.contest_ref
                         == contest.contest_ref,
                         FantasyStakesChampionshipCorrection.team_id == team_id)
                 .order_by(FantasyStakesChampionshipCorrection.revision.desc())
                 .first())
        previous = int(prior.corrected_net_cents) if prior is not None else 0
        revision = (int(prior.revision) + 1) if prior is not None else 1
        delta = corrected - previous
        if delta == 0:
            # Nothing moved for this GM. A zero-delta revision is audit noise,
            # not an audit fact, so none is written.
            continue
        db.add(FantasyStakesChampionshipCorrection(
            freeze_id=marker.id, league_id=league_id, season=season,
            team_id=team_id, competition_type=contest.competition_type,
            contest_ref=contest.contest_ref, scoring_week=contest.scoring_week,
            revision=revision, previous_net_cents=previous,
            corrected_net_cents=corrected, delta_cents=delta,
            reason=reason, source=source, correction_key=correction_key,
            created_at=now))
        written.append(CorrectionRow(
            team_id=team_id, competition_type=contest.competition_type,
            contest_ref=contest.contest_ref, scoring_week=contest.scoring_week,
            revision=revision, previous_net_cents=previous,
            corrected_net_cents=corrected, delta_cents=delta, reason=reason,
            source=source, correction_key=correction_key))
    db.flush()
    return CorrectionResult(
        league_id=league_id, season=season,
        competition_type=contest.competition_type,
        contest_ref=contest.contest_ref, scoring_week=contest.scoring_week,
        rows=tuple(written), replayed=False)


def unresolved_eligible_contests(db: Session, *, league_id: int, season: int,
                                 playoff_start_week: int) -> tuple[str, ...]:
    """Eligible regular-season contests whose authoritative result is not in yet.

    THE FINAL GATE. FROZEN closes eligibility; this is what closes RESULTS. The
    predicate for a matchup is the certified one — `Matchup.finalized_at` through
    `betting.finality_gate` — plus the wager actually being settled, because an
    economically final scoreboard with an unsettled wager has still moved no
    Credits and produced no competitive net.
    """
    from betting.finality_gate import week_finality

    db.flush()
    open_versus = (db.query(BeefChallenge.id, BeefChallenge.week)
                   .join(Bet, Bet.beef_challenge_id == BeefChallenge.id)
                   .filter(BeefChallenge.league_id == league_id,
                           BeefChallenge.week < playoff_start_week,
                           Bet.status == "pending")
                   .distinct().all())
    open_pools = (db.query(PoolInstance.id, PoolInstance.week)
                  .filter(PoolInstance.league_id == league_id,
                          PoolInstance.season == season,
                          PoolInstance.week < playoff_start_week,
                          PoolInstance.settled.is_(False))
                  .all())

    blockers = [f"versus challenge {int(cid)} (week {int(w)}) has an unsettled wager"
                for cid, w in open_versus]
    blockers += [f"prop-pool occurrence {int(pid)} (week {int(w)}) is unsettled"
                 for pid, w in open_pools]

    weeks = sorted({int(w) for _, w in open_versus} |
                   {int(w) for _, w in open_pools} |
                   {int(w) for (w,) in db.query(BeefChallenge.week)
                    .filter(BeefChallenge.league_id == league_id,
                            BeefChallenge.week < playoff_start_week)
                    .distinct().all()})
    for week in weeks:
        census = week_finality(db, league_id=league_id, week=week)
        if not census.is_final:
            blockers.append(
                f"week {week} has {len(census.unfinalized_matchup_ids)} matchup(s) "
                f"with finalized_at IS NULL")
    return tuple(blockers)
