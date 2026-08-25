"""
Weekly Minimum lifecycle — release and expiry (S5-P1 §2, §4).

    activation   season_issuance -> min_reserve:{team}        (season_allocation)
    release      min_reserve:{team} -> min:{team}:{week}      once per team/week
    spend        min:{team}:{week} -> escrow / pool           min-first, then wallet

WEEK CLOSE HAS TWO DESTINATIONS, ONE PER ERA (WP-4). The era is resolved from
`ruleset.is_final_por` for the league-SEASON, which is stamped once at activation
and never updated in place, so a season's Weekly Minimum cannot go one way in
Week 3 and the other way in Week 9.

    RULESET_LEGACY     min:{team}:{week} -> expired_min:{team}
                       then expired_min:{team} -> wallet:{team} at season close

    RULESET_FINAL_POR  min:{team}:{week}
                           -> fantasystakes_championship:{league}:{season}

WHY THE LEGACY MOVE COSTS THE GM NOTHING AND THE FINAL POR MOVE COSTS THEM
EXACTLY ONCE. Under the legacy era both endpoints are settlement-relevant GM
asset accounts, so Current Settle moves by zero — the GM had not lost the money,
it had merely left circulation. Under the Final POR the credit leg is a
LEAGUE-level pot that is deliberately outside the GM asset set, so the same
posting reduces that GM's asset position by exactly the swept amount, once and
permanently. No second consequence follows it: no Wallet credit, no
`expired_min:` row, no receivable, no Skunk, and no FantasyStakes Score term.
The forfeiture IS the whole consequence.

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
    DOOR_WEEKLY_MINIMUM_SWEEP,
    EVENT_WEEKLY_MINIMUM_EXPIRY,
    EVENT_WEEKLY_MINIMUM_RELEASE,
    EVENT_WEEKLY_MINIMUM_SWEEP,
    DuplicateEconomyEvent,
    expired_min_account,
    fantasystakes_championship_account,
    gm_week_key,
    min_account,
    min_reserve_account,
    record_event,
)
from ledger.ledger import _balance_of_in_session, post as ledger_post
from ruleset import is_final_por

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


#: Where an unspent Weekly Minimum went at week close. Reported so a caller,
#: a read model and an auditor can all name the destination without re-deriving
#: the era or guessing from an account string.
DESTINATION_EXPIRED_MIN = "expired_min"
DESTINATION_FS_CHAMPIONSHIP_POT = "fantasystakes_championship_pot"


@dataclass(frozen=True)
class ExpiryResult:
    league_id: int
    season: int
    week: int
    team_id: int
    expired_cents: int
    replayed: bool
    #: `DESTINATION_EXPIRED_MIN` or `DESTINATION_FS_CHAMPIONSHIP_POT`. Defaulted
    #: so the two savepoint-replay construction sites below, which post nothing
    #: and therefore have no destination to report, stay unchanged.
    destination: str = DESTINATION_EXPIRED_MIN

    @property
    def swept_to_championship(self) -> bool:
        return self.destination == DESTINATION_FS_CHAMPIONSHIP_POT


def is_release_week(league, week: int) -> bool:
    """Whether `week` is a governed regular-season week for this league.

    Postseason weeks release nothing: the Weekly Minimum is a regular-season
    obligation, and releasing into a playoff week would hand a GM spendable
    Credits the season model never allocated for it."""
    return week < playoff_start_week(league)


def weekly_minimum_cents(db, league_id: int) -> int:
    """The league's governed weekly amount.

    ONE RESOLUTION, SHARED WITH THE ALLOCATION THAT FUNDED IT.
    `resolve_allocation_terms` is the same function `season_allocation` used to
    decide how much `min_reserve:{team}` was issued, so the amount released each
    week and the reserve it is released from cannot disagree. A configured league
    is issued `weekly x regular_season_week_count` and releases `weekly`, which
    is what makes the release EXHAUSTION-BOUNDED: the reserve empties after
    exactly as many weeks as it was funded for, with no week count written here.

    A LEAGUE THAT CONFIGURED NOTHING IS UNCHANGED. `weekly_bet_minimum_cents` is
    None on the legacy path and the five certified stops keep governing through
    the same `weekly_min_cents` field they always did.

    THE ALTERNATIVE WOULD HAVE BEEN A HYBRID ECONOMY. Reading the legacy stop
    here while the allocation funded from the configuration would release $10 a
    week out of a reserve funded at $25 a week — a league issued fourteen weeks
    of Weekly Minimum would find it lasted thirty-five, which is not either
    economy and is nobody's product.
    """
    from db.schema import League
    from payments.economy_config import (
        get_league_economy_stop, resolve_allocation_terms,
    )

    league = db.query(League).filter(League.id == league_id).first()
    if league is not None:
        terms = resolve_allocation_terms(db, league_id=league_id,
                                         season=league.season)
        if terms.weekly_bet_minimum_cents is not None:
            return int(terms.weekly_bet_minimum_cents)
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
    """Close one team's Weekly Minimum for one week. Does NOT commit.

    The destination is the league-season's era (WP-4): the FantasyStakes
    Championship Pot under `RULESET_FINAL_POR`, `expired_min:` under
    `RULESET_LEGACY`. See the module docstring for why each is right for its
    era. Everything else about this function is identical in both.

    The amount is whatever `min:{team}:{week}` still holds. Cents already spent
    into escrow left that account when they were spent, so committed money is
    structurally unreachable here rather than filtered out — which is what
    makes "full Minimum consumed" sweep exactly zero without a special case.

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

    # ── The era decides the destination, and it decides it once ─────────────
    #
    # Resolved per league-SEASON, not per week. The stamp is written inside the
    # activation transaction and `stamp_ruleset` refuses to restamp a season
    # with a different version, so every week of a season closes the same way.
    sweep = is_final_por(db, league_id=league_id, season=season)
    if sweep:
        event_type = EVENT_WEEKLY_MINIMUM_SWEEP
        door = DOOR_WEEKLY_MINIMUM_SWEEP
        credit_account = fantasystakes_championship_account(league_id, season)
        destination = DESTINATION_FS_CHAMPIONSHIP_POT
    else:
        event_type = EVENT_WEEKLY_MINIMUM_EXPIRY
        door = DOOR_WEEKLY_MINIMUM_EXPIRY
        credit_account = expired_min_account(team_id)
        destination = DESTINATION_EXPIRED_MIN

    key = gm_week_key(event_type, league_id, season, week, team_id)

    db.flush()
    remaining = max(0, _balance_of_in_session(db, min_account(team_id, week)))

    # THE AMOUNT IS THE BALANCE, WHICH IS WHAT MAKES THE TWO EVENT KEYS SAFE
    # TOGETHER. Sweep and expiry carry different event types and therefore
    # different keys, so neither collides with the other. The one path on which
    # a league could reach both is a season that closed weeks unstamped (era
    # LEGACY, absence being a governed state) and was only later stamped Final
    # POR — `stamp_ruleset` permits that, since there is no row to contradict.
    # Re-closing such a week finds `min:{team}:{week}` already emptied by the
    # legacy expiry, so `remaining` is 0, the sweep posts nothing, and the
    # cents cannot be counted into the pot a second time. Conservation is held
    # by the balance, not by an assumption about which keys exist.
    posting_id = None
    if remaining > 0:
        posting_id = ledger_post(
            [(min_account(team_id, week), -remaining),
             (credit_account, remaining)],
            door=door, session=db,
        )
    record_event(db, event_key=key, league_id=league_id, season=season,
                 week=week, team_id=team_id,
                 event_type=event_type,
                 amount_cents=remaining, posting_id=posting_id, now=now)

    return ExpiryResult(league_id=league_id, season=season, week=week,
                        team_id=team_id, expired_cents=remaining,
                        replayed=False, destination=destination)


def expire_week(db, *, league_id: int, week: int,
                now: datetime | None = None) -> tuple[ExpiryResult, ...]:
    """Canonical Week Close for every team. Does NOT commit.

    Per-team savepoints, same rationale as `release_week`. The destination is
    per-season, so the replay rows below report the same one the posting rows
    do — a caller must not read a replayed team as having gone the other way."""
    from db.schema import League

    league = db.query(League).filter(League.id == league_id).first()
    destination = DESTINATION_EXPIRED_MIN
    if league is not None and is_final_por(db, league_id=league_id,
                                           season=league.season):
        destination = DESTINATION_FS_CHAMPIONSHIP_POT

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
                expired_cents=0, replayed=True, destination=destination))
    db.flush()
    return tuple(results)