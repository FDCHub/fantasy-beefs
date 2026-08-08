"""
Weekly Pool funding — POR Rev1.3 §6.1, Owner Rulings R1 and R3.

THE CONTRIBUTION IS LEAGUE-LEVEL AND WEEKLY. It is not a fee charged per Pool,
and it is NOT charged when a Prediction pick is submitted. Owner Ruling R3:
"Funding is league-level. A pick creates a claim, not funding." A GM who makes
no pick simply has no winning claim — no refund, no void, no participation
minimum. The stale GE-1031/GE-1035 participation-minimum Void is not
implemented here and must not be.

THE DIVISOR IS FOUR, AND THE REMAINDER GOES TO CHAMPIONSHIP EXACTLY ONCE.

    share_cents     = total_cents // 4
    remainder_cents = total_cents %  4   -> championship:{league_id}

The legacy `// 3` divisor and the remainder-to-Special-Teams behavior are
implementation debt and are forbidden going forward (§6.1). §6.1's remainder and
§6.3's remainder are DIFFERENT REMAINDERS and must never be collapsed: this one
divides the league contribution across occurrences and credits the championship;
§6.3 divides a pot among winning GMs and NEVER credits the championship.

TWO POSTINGS, TWO CAUSES, ONE TRANSACTION. Collection and the division remainder
are separate economic causes (per the S4-P1 instruction that distinct causes stay
distinct), so each gets its own posting and its own event row. They commit
together, so no reader can observe a collected week whose remainder has not yet
landed.

INSUFFICIENT FUNDS FAILS THE WHOLE WEEK, ATOMICALLY. Every wallet debit is one
leg of ONE posting, so the ledger's funded-balance guard rejects the posting
outright if any wallet cannot cover its entry. There is no partially funded
week, no partially funded Pool, and no negative wallet — not because this
function checks for those, but because the failure happens before a single leg
is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text

from betting.pool_season_boundary import phase_for_week
from betting.pool_slate import build_and_persist_slate
from ledger.ledger import lock_funding_scopes, post as ledger_post

#: POR §6.1 — bounded 100 <= x <= 500, default 100.
GOVERNED_MIN_WEEKLY_ENTRY_CENTS = 100
GOVERNED_MAX_WEEKLY_ENTRY_CENTS = 500
GOVERNED_DEFAULT_WEEKLY_ENTRY_CENTS = 100

#: POR §4 — exactly four active Pools per fantasy week.
ACTIVE_POOLS_PER_WEEK = 4

DOOR_WEEKLY_COLLECTION = "pool_weekly_collection"
DOOR_DIVISION_REMAINDER = "pool_division_remainder"

EVENT_WEEKLY_COLLECTION = "WEEKLY_COLLECTION"
EVENT_DIVISION_REMAINDER = "WEEKLY_DIVISION_REMAINDER"


class PoolFundingError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_ALREADY_COLLECTED = "ALREADY_COLLECTED"
REASON_PRIOR_WEEK_UNSETTLED = "PRIOR_WEEK_UNSETTLED"
REASON_ENTRY_OUT_OF_BOUNDS = "ENTRY_OUT_OF_BOUNDS"
REASON_ENTRY_FROZEN = "ENTRY_FROZEN"
REASON_NO_TEAMS = "NO_TEAMS"
REASON_NO_WALLET = "NO_WALLET"


@dataclass(frozen=True)
class WeeklyCollectionResult:
    league_id: int
    season: int
    week: int
    weekly_entry_cents: int
    teams_charged: int
    total_cents: int
    per_pool_share_cents: int
    remainder_to_championship_cents: int
    rotation_cycle: int
    instance_ids: tuple[int, ...]


# ── Governed weekly entry ─────────────────────────────────────────────────────

def configure_pool_weekly_entry(db, *, league_id: int, cents: int) -> int:
    """Set the Rev1.3 league-level weekly contribution. Does not commit.

    REFUSES AFTER THE FREEZE POINT. POR §6.1 freezes the contribution at the
    season freeze point; `pool_weekly_entry_frozen_at` is written by the first
    weekly collection and is never returned to NULL. Allowing a change after
    the freeze would let a mid-season edit retroactively disagree with pots
    already collected under the old value."""
    from db.schema import PoolConfig

    if not (GOVERNED_MIN_WEEKLY_ENTRY_CENTS <= cents
            <= GOVERNED_MAX_WEEKLY_ENTRY_CENTS):
        raise PoolFundingError(
            REASON_ENTRY_OUT_OF_BOUNDS,
            f"weekly entry {cents} cents is outside the governed bound "
            f"{GOVERNED_MIN_WEEKLY_ENTRY_CENTS}.."
            f"{GOVERNED_MAX_WEEKLY_ENTRY_CENTS} (POR §6.1).",
        )

    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    if cfg is None:
        cfg = PoolConfig(league_id=league_id)
        db.add(cfg)
    if cfg.pool_weekly_entry_frozen_at is not None:
        raise PoolFundingError(
            REASON_ENTRY_FROZEN,
            f"league {league_id} froze its weekly Pool contribution at "
            f"{cfg.pool_weekly_entry_frozen_at.isoformat()} "
            f"({cfg.pool_weekly_entry_cents} cents). POR §6.1 fixes it at the "
            f"season freeze point.",
        )
    cfg.pool_weekly_entry_cents = cents
    db.flush()
    return cents


def resolve_weekly_entry_cents(db, *, league_id: int) -> int:
    """The governed contribution for this league, defaulting to 100 (§6.1).

    A NULL column means "never configured", which reads as the governed default
    rather than as zero. A zero contribution would fund nothing and settle four
    empty pots without ever failing."""
    from db.schema import PoolConfig

    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    cents = getattr(cfg, "pool_weekly_entry_cents", None) if cfg else None
    if cents is None:
        cents = GOVERNED_DEFAULT_WEEKLY_ENTRY_CENTS
    if not (GOVERNED_MIN_WEEKLY_ENTRY_CENTS <= cents
            <= GOVERNED_MAX_WEEKLY_ENTRY_CENTS):
        raise PoolFundingError(
            REASON_ENTRY_OUT_OF_BOUNDS,
            f"league {league_id} carries weekly entry {cents} cents, outside "
            f"the governed §6.1 bound.",
        )
    return int(cents)


# ── Weekly collection ─────────────────────────────────────────────────────────

def _claim_week(db, *, league_id: int, week: int) -> None:
    """Claim the week atomically BEFORE any economic work — Scope §G.

    THE SAME CLAIM THE LEGACY ENGINE USES, AND DELIBERATELY THE SAME ROW. Two
    engines writing two different week claims would let both collect the same
    week. `pool_pots` stays the week container (§C4), so one claim governs.

    Modelled on WeekSettlement's INSERT ... ON CONFLICT with one deliberate
    difference, which is a money-path property rather than a style choice: this
    does NOT commit. `entries_collected` is read outside this transaction as
    evidence that every team was actually charged, so committing the claim early
    would publish that evidence before a cent moved.

    IS NOT TRUE, not `= FALSE`: `entries_collected` is nullable, and `= FALSE`
    evaluates to NULL against a NULL column and would silently refuse the claim
    on any legacy row carrying NULL. Required truth table:
        TRUE -> refuse    FALSE -> claim    NULL -> claim
    """
    claimed = db.execute(
        text("""
            INSERT INTO pool_pots
                (league_id, week, entries_collected, worst_beat_rollover_cents, settled)
            VALUES (:league_id, :week, TRUE, 0, FALSE)
            ON CONFLICT (league_id, week) DO UPDATE
               SET entries_collected = TRUE
             WHERE pool_pots.entries_collected IS NOT TRUE
            RETURNING id
        """),
        {"league_id": league_id, "week": week},
    ).fetchone()
    if claimed is None:
        raise PoolFundingError(
            REASON_ALREADY_COLLECTED,
            f"Pool entries already collected for league {league_id} week {week}",
        )


def _record_event(db, *, league_id: int, season: int, week: int,
                  instance_id: int | None, event_type: str,
                  posting_id, amount_cents: int, now: datetime) -> None:
    """Write the event-keyed idempotency row in the posting's own transaction.

    The uniqueness constraint is the guard; this insert is what arms it. A
    replay collides here and the whole retry rolls back harmlessly."""
    from db.schema import PoolEconomicEvent

    db.add(PoolEconomicEvent(
        league_id=league_id, season=season, week=week,
        pool_instance_id=instance_id, event_type=event_type,
        posting_id=posting_id, amount_cents=amount_cents, created_at=now,
    ))
    db.flush()


def collect_weekly_entries(db, *, league_id: int, week: int,
                           provider: str = "yahoo") -> WeeklyCollectionResult:
    """Collect one week's league-level contribution and fund the four Pools.

    Order is load-bearing and follows Scope §E:

        1. claim the week atomically            (before any economic work)
        2. refuse if any earlier week is unsettled
        3. build and persist the four-occurrence slate
        4. lock every wallet in a stable order  (P1-L7 serialization)
        5. one posting debiting every wallet, crediting pool:{league_id}
        6. one posting moving the indivisible remainder to championship
        7. divide the share across the four occurrences
        8. commit

    Steps 3 through 7 are one transaction. A crash anywhere before the commit
    leaves no slate, no postings, no funded pots and no week claim — the whole
    week is simply un-collected, which is a state the next attempt handles.
    """
    from db.schema import League, PoolConfig, PoolPot, Team, Wallet

    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise PoolFundingError(REASON_NO_TEAMS, f"League {league_id} not found")
    season = league.season
    now = datetime.now(timezone.utc)

    _claim_week(db, league_id=league_id, week=week)

    # Refuse to collect a new week while ANY earlier week is unsettled — not
    # just the immediately preceding one. A preceding-week-only check would miss
    # week W-2 sitting unsettled while W-1 settled, leaving that stale money in
    # pool:{league_id} and polluting every later conservation check.
    unsettled_prior = (db.query(PoolPot)
                       .filter(PoolPot.league_id == league_id,
                               PoolPot.week < week,
                               PoolPot.settled.is_(False))
                       .first())
    if unsettled_prior is not None:
        raise PoolFundingError(
            REASON_PRIOR_WEEK_UNSETTLED,
            f"cannot collect week {week} for league {league_id} — week "
            f"{unsettled_prior.week} is not yet settled.",
        )

    entry_cents = resolve_weekly_entry_cents(db, league_id=league_id)

    teams = (db.query(Team).filter(Team.league_id == league_id)
             .order_by(Team.id).all())
    if not teams:
        raise PoolFundingError(REASON_NO_TEAMS,
                               f"No teams found in league {league_id}")

    phase = phase_for_week(league, week)
    slate = build_and_persist_slate(db, league=league, season=season, week=week,
                                    phase=phase, provider=provider)

    # P1-L7 — take every wallet row FOR UPDATE in ascending team order before
    # the balance reads inside the posting. Ascending order is what prevents two
    # concurrent collections deadlocking against each other.
    lock_funding_scopes(db, *[t.id for t in teams])

    for team in teams:
        if db.query(Wallet).filter(Wallet.team_id == team.id).first() is None:
            raise PoolFundingError(
                REASON_NO_WALLET,
                f"Team {team.id} in league {league_id} has no wallet — every "
                f"team must have one before a week can be collected.",
            )

    total_cents = entry_cents * len(teams)

    # ── Posting 1: the collection itself ─────────────────────────────────────
    # Every wallet debit is a leg of ONE posting, so the funded-balance guard
    # refuses the whole week if any single wallet is short. That is what makes
    # "no partially funded week" a property of the ledger rather than a promise
    # this function makes.
    legs = [(f"wallet:{team.id}", -entry_cents) for team in teams]
    legs.append((f"pool:{league_id}", total_cents))
    collection_posting = ledger_post(legs, door=DOOR_WEEKLY_COLLECTION,
                                     session=db)
    _record_event(db, league_id=league_id, season=season, week=week,
                  instance_id=None, event_type=EVENT_WEEKLY_COLLECTION,
                  posting_id=collection_posting, amount_cents=total_cents,
                  now=now)

    # ── Division across the four active funded occurrences (§6.1) ────────────
    share_cents = total_cents // ACTIVE_POOLS_PER_WEEK
    remainder_cents = total_cents % ACTIVE_POOLS_PER_WEEK

    if remainder_cents:
        # ONCE, and to the championship — never absorbed by an occurrence and
        # never routed to Special Teams.
        remainder_posting = ledger_post(
            [(f"pool:{league_id}", -remainder_cents),
             (f"championship:{league_id}", remainder_cents)],
            door=DOOR_DIVISION_REMAINDER, session=db,
        )
        _record_event(db, league_id=league_id, season=season, week=week,
                      instance_id=None, event_type=EVENT_DIVISION_REMAINDER,
                      posting_id=remainder_posting,
                      amount_cents=remainder_cents, now=now)

    for instance in slate.instances:
        # A continuation already carries its prior pot; this week's share is
        # added to it (§F), never substituted for it.
        instance.pot_cents = int(instance.pot_cents or 0) + share_cents

    pot = (db.query(PoolPot)
           .filter(PoolPot.league_id == league_id, PoolPot.week == week).one())
    pot.entries_collected = True
    pot.settled = False
    pot.total_pot_cents = total_cents

    db.flush()
    return WeeklyCollectionResult(
        league_id=league_id, season=season, week=week,
        weekly_entry_cents=entry_cents, teams_charged=len(teams),
        total_cents=total_cents, per_pool_share_cents=share_cents,
        remainder_to_championship_cents=remainder_cents,
        rotation_cycle=slate.rotation_cycle,
        instance_ids=tuple(i.id for i in slate.instances),
    )


def freeze_weekly_entry(db, *, league_id: int, entry_cents: int) -> None:
    """Stamp the freeze point after a successful first collection.

    Separate from `collect_weekly_entries` so the freeze is written by the
    caller that owns the commit, and so a collection that rolls back leaves the
    contribution unfrozen — freezing a value whose collection never landed would
    lock in a number no pot was ever funded at."""
    from db.schema import PoolConfig

    cfg = db.query(PoolConfig).filter(PoolConfig.league_id == league_id).first()
    if cfg is None:
        cfg = PoolConfig(league_id=league_id)
        db.add(cfg)
    if cfg.pool_weekly_entry_frozen_at is None:
        cfg.pool_weekly_entry_cents = entry_cents
        cfg.pool_weekly_entry_frozen_at = datetime.now(timezone.utc)
        db.flush()