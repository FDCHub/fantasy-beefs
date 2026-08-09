"""
Weekly Minimum lifecycle — release and expiry (S5-P1 §2, §4).

    activation   season_issuance -> min_reserve:{team}        (season_allocation)
    release      min_reserve:{team} -> min:{team}:{week}      once per team/week
    spend        min:{team}:{week} -> escrow / pool           min-first, then wallet
    week close   min:{team}:{week} -> expired_min:{team}      once per team/week
    season end   expired_min:{team} -> ...                    S5-P3, NOT here

EVERY ONE OF THOSE MOVES IS BETWEEN SETTLEMENT-RELEVANT GM ASSET ACCOUNTS, so
each changes Current Settle by exactly zero. That is the property S5-P2 will
assert, and it is why expiry credits `expired_min:` rather than sweeping to
championship: the GM has not lost the money, it has merely left circulation.

RELEASE CANNOT EXCEED THE REMAINING RESERVE. A league that has released fourteen
weeks has an empty `min_reserve:` and the fifteenth release posts nothing rather
than driving the account negative. The ledger's funded-balance guard would
refuse it anyway — `min_reserve:` is a normal guarded account with no exemption
— but refusing here names the reason instead of surfacing a generic shortfall.

REGULAR SEASON ONLY. `playoff_start_week` governs, read through
betting.pool_season_boundary so Pool and economy agree on one boundary rather
than two that can drift.

EXPIRY CANNOT TOUCH COMMITTED MONEY. Cents already spent into escrow left
`min:{team}:{week}` at spend time — the balance is what remains, so escrow is
structurally out of reach rather than excluded by a filter that could be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from betting.pool_season_boundary import playoff_start_week
from economy.economy_events import (
    DOOR_WEEKLY_MINIMUM_EXPIRY,
    DOOR_WEEKLY_MINIMUM_RELEASE,
    EVENT_WEEKLY_MINIMUM_EXPIRY,
    EVENT_WEEKLY_MINIMUM_RELEASE,
    DuplicateEconomyEvent,
    expired_min_account,
    gm_week_key,
    min_account,
    min_reserve_account,
    record_event,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post

DEFAULT_WEEKLY_MINIMUM_CENTS = 1000


class WeeklyMinimumError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_NOT_APPLICABLE_WEEK = "NOT_APPLICABLE_WEEK"
REASON_INSUFFICIENT_RESERVE = "INSUFFICIENT_RESERVE"
REASON_LEAGUE_NOT_FOUND = "LEAGUE_NOT_FOUND"


@dataclass(frozen=True)
class ReleaseResult:
    league_id: int
    season: int
    week: int
    team_id: int
    released_cents: int
    replayed: bool


@dataclass(frozen=True)
class ExpiryResult:
    league_id: int
    season: int
    week: int
    team_id: int
    expired_cents: int
    replayed: bool


def is_release_week(league, week: int) -> bool:
    """Whether `week` is a governed regular-season week for this league.

    Postseason weeks release nothing: the Weekly Minimum is a regular-season
    obligation, and releasing into a playoff week would hand a GM spendable
    Credits the season model never allocated for it."""
    return week < playoff_start_week(league)


def weekly_minimum_cents(db, league_id: int) -> int:
    """The league's governed weekly amount, from its economy stop.

    Read from the league's stop rather than a constant so the five certified
    stops keep governing. `weekly_min_cents` is the stop field that has always
    meant this; the S5-P1 rename touched `wallet_cents` only."""
    from payments.economy_config import get_league_economy_stop

    return get_league_economy_stop(league_id, db).weekly_min_cents


def _locked_teams(db, league_id: int):
    """Teams in ascending id order, which is the deterministic lock order every
    multi-GM writer here uses. Two concurrent whole-league jobs therefore queue
    instead of each holding a row the other needs."""
    from db.schema import Team

    return (db.query(Team).filter(Team.league_id == league_id)
            .order_by(Team.id).all())


# ── Release ───────────────────────────────────────────────────────────────────

def release_weekly_minimum(db, *, league_id: int, team_id: int, week: int,
                           now: datetime | None = None) -> ReleaseResult:
    """Release one team's Weekly Minimum for one week. Does NOT commit.

    Posting, event row and the resulting balances are one transaction by
    construction — the caller's. A crash before its commit leaves nothing; a
    retry after it collides on the deterministic event key and is a no-op.
    """
    from db.schema import League

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise WeeklyMinimumError(REASON_LEAGUE_NOT_FOUND,
                                 f"league {league_id} not found")
    season = league.season

    if not is_release_week(league, week):
        raise WeeklyMinimumError(
            REASON_NOT_APPLICABLE_WEEK,
            f"week {week} is not a governed regular-season week for league "
            f"{league_id} (playoff_start_week={playoff_start_week(league)}); "
            f"no Weekly Minimum is released.")

    amount = weekly_minimum_cents(db, league_id)
    key = gm_week_key(EVENT_WEEKLY_MINIMUM_RELEASE, league_id, season, week,
                      team_id)

    reserve = max(0, _balance_of_in_session(db, min_reserve_account(team_id)))
    if reserve < amount:
        raise WeeklyMinimumError(
            REASON_INSUFFICIENT_RESERVE,
            f"team {team_id} has {reserve} cents left in "
            f"{min_reserve_account(team_id)} and cannot release {amount}. "
            f"Refusing rather than over-releasing the season allocation.")

    posting_id = ledger_post(
        [(min_reserve_account(team_id), -amount),
         (min_account(team_id, week), amount)],
        door=DOOR_WEEKLY_MINIMUM_RELEASE, session=db,
    )
    try:
        record_event(db, event_key=key, league_id=league_id, season=season,
                     week=week, team_id=team_id,
                     event_type=EVENT_WEEKLY_MINIMUM_RELEASE,
                     amount_cents=amount, posting_id=posting_id, now=now)
    except DuplicateEconomyEvent:
        # A concurrent worker won. Discard THIS transaction's posting by
        # signalling the caller to roll back its savepoint — the caller owns the
        # transaction, so raising is how the posting is undone. Returning a
        # "replayed" result here without unwinding would leave the duplicate
        # posting in the caller's transaction to be committed.
        raise

    return ReleaseResult(league_id=league_id, season=season, week=week,
                         team_id=team_id, released_cents=amount,
                         replayed=False)


def release_week(db, *, league_id: int, week: int,
                 now: datetime | None = None) -> tuple[ReleaseResult, ...]:
    """Release every team's Weekly Minimum for one week. Does NOT commit.

    Each team is released inside its own SAVEPOINT so a team that has already
    been released — by a partially-completed earlier run, or by a concurrent
    worker — is skipped without discarding the teams that succeeded. Same
    isolation pattern S4-P2 proved for per-instance Pool settlement, and for the
    same reason: one team's duplicate must not un-release the others.
    """
    results: list[ReleaseResult] = []
    for team in _locked_teams(db, league_id):
        savepoint = db.begin_nested()
        try:
            results.append(release_weekly_minimum(
                db, league_id=league_id, team_id=team.id, week=week, now=now))
            savepoint.commit()
        except DuplicateEconomyEvent:
            savepoint.rollback()
            results.append(ReleaseResult(
                league_id=league_id, season=0, week=week, team_id=team.id,
                released_cents=0, replayed=True))
    db.flush()
    return tuple(results)


# ── Expiry ────────────────────────────────────────────────────────────────────

def expire_weekly_minimum(db, *, league_id: int, team_id: int, week: int,
                          now: datetime | None = None) -> ExpiryResult:
    """Move one team's UNSPENT Weekly Minimum to `expired_min:`. No commit.

    The amount is whatever `min:{team}:{week}` still holds. Cents already spent
    into escrow left that account when they were spent, so committed money is
    structurally unreachable here rather than filtered out.

    A ZERO REMAINDER STILL RECORDS AN EVENT, with no posting. The week genuinely
    closed for that team, and recording it is what makes a later retry a no-op
    instead of re-examining a balance that may since have changed.
    """
    from db.schema import League

    now = now or datetime.now(timezone.utc)
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise WeeklyMinimumError(REASON_LEAGUE_NOT_FOUND,
                                 f"league {league_id} not found")
    season = league.season
    key = gm_week_key(EVENT_WEEKLY_MINIMUM_EXPIRY, league_id, season, week,
                      team_id)

    db.flush()
    remaining = max(0, _balance_of_in_session(db, min_account(team_id, week)))

    posting_id = None
    if remaining > 0:
        posting_id = ledger_post(
            [(min_account(team_id, week), -remaining),
             (expired_min_account(team_id), remaining)],
            door=DOOR_WEEKLY_MINIMUM_EXPIRY, session=db,
        )
    record_event(db, event_key=key, league_id=league_id, season=season,
                 week=week, team_id=team_id,
                 event_type=EVENT_WEEKLY_MINIMUM_EXPIRY,
                 amount_cents=remaining, posting_id=posting_id, now=now)

    return ExpiryResult(league_id=league_id, season=season, week=week,
                        team_id=team_id, expired_cents=remaining,
                        replayed=False)


def expire_week(db, *, league_id: int, week: int,
                now: datetime | None = None) -> tuple[ExpiryResult, ...]:
    """Canonical Week Close expiry for every team. Does NOT commit.

    Per-team savepoints, same rationale as `release_week`."""
    results: list[ExpiryResult] = []
    for team in _locked_teams(db, league_id):
        savepoint = db.begin_nested()
        try:
            results.append(expire_weekly_minimum(
                db, league_id=league_id, team_id=team.id, week=week, now=now))
            savepoint.commit()
        except DuplicateEconomyEvent:
            savepoint.rollback()
            results.append(ExpiryResult(
                league_id=league_id, season=0, week=week, team_id=team.id,
                expired_cents=0, replayed=True))
    db.flush()
    return tuple(results)