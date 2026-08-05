"""
economy/season_allocation.py — B2 season allocation (money path).

Replaces the Stripe-mediated buy-in with a commissioner-activated, whole-
league allocation. Activating a league writes one SeasonAllocation row and
one three-leg ledger posting per team, all inside ONE transaction with ONE
top-level commit.

SEASON AUTHORITY
    The allocation season is config.ALLOCATION_SEASON, referenced explicitly
    at every write, every query and every state-machine lookup — no alias, no
    local rebinding, so the authority is visible at each site. Never from a
    request body, never from the calendar year, never from an unqualified row
    lookup.

    It is deliberately NOT config.CURRENT_SEASON: that constant is the
    projection-data year, pinned to 2025 until 2026 projections are seeded,
    and is consumed by five engines that must keep reading 2025. Allocation
    season is a separate concept with its own setting.

TRANSACTION
    Every SeasonAllocation insert and every ledger.post() in one activation
    runs against THE SAME session inside ONE enclosing transaction.
    ledger.post() is always given session=db explicitly — omitting it would
    make post() open its own SessionLocal and commit internally, placing the
    postings outside this transaction and destroying the rollback guarantee.
    Any uniqueness, validation or posting error rolls back every allocation
    row AND every ledger entry from that activation; no partial state remains.

TRANSACTION OWNERSHIP (decided, not open)
    activate_season_allocation() TAKES OWNERSHIP of the supplied session's
    transaction. It commits on the create path and rolls back on every other
    terminal path — replay, every domain refusal, and every unexpected error.
    No caller may pass a session carrying uncommitted work it expects to
    survive this call or to control itself.

COMMIT COUNT (decided)
    At most one commit: exactly one on the create path, zero on the replay
    path, zero on every error path.

ISOLATION (decided)
    The caller's isolation level is inherited deliberately. READ COMMITTED is
    RETAINED ON PURPOSE. Elevating to REPEATABLE READ would make behavior
    strictly worse: a race loser's snapshot would pin before the winner
    commits, so it would still see no rows, take the create path, and die on
    the unique index — converting a benign replay into an IntegrityError. It
    is also not reliably settable at that point, because
    get_league_economy_stop() has already opened the transaction.

STATE MACHINE — FIVE states, evaluated inside the transaction before any write
    no rows        -> create the complete allocation atomically
    complete+match -> return the existing result; nothing posted, nothing mutated
    partial        -> PartialAllocationError; no mutation
    conflicting    -> ConflictingAllocationError; no mutation
    no teams       -> NoTeamsError; no mutation

    This state machine IS the idempotency mechanism.
    uq_season_allocation_league_team_season is the FINAL RACE GUARD only —
    its violation is never used as the idempotency path.

    OBSERVED RACE BEHAVIOR (evidence, not aspiration): under genuine overlap
    the loser has been observed taking the UNIQUE-CONSTRAINT path only. The
    concurrent replay-loser path — a second activation reading after the
    winner commits and returning created=False — has NOT been observed under
    contention and is NOT claimed to be proven. Sequential replay is proven
    separately, by test scenario (g).

CONSERVATION
    Each posting is exactly three legs summing to zero in integer cents:
        ("world",              -stop.buyin_cents)
        (f"wallet:{team_id}",   stop.wallet_cents)
        (f"reserve:{team_id}",  stop.reserve_cents)
    Zero-sum is guaranteed upstream by economy_config's import-time invariant
    wallet_cents + reserve_cents == buyin_cents; it is never recomputed or
    rounded here. "world" is exempt from the ledger's non-negative balance
    guard, so debiting it from zero is legal — the same structure Door 1 used.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from db.schema import SeasonAllocation, Team
from payments.economy_config import EconomyStop, get_league_economy_stop
from ledger.ledger import post as ledger_post

DOOR = "season_allocation"


# ── Errors ────────────────────────────────────────────────────────────────────

class SeasonAllocationError(ValueError):
    """Base for every season-allocation domain refusal. Subclasses are
    distinct types so tests assert on type, never on message text."""


class PartialAllocationError(SeasonAllocationError):
    """The league already has SOME allocation rows for this season but not a
    complete set — some teams have a row and some do not, or a row exists for
    a team that is not in the league. Inconsistent: refused without mutation.
    Never repaired automatically; a partial set means something already went
    wrong and silently completing it would paper over that."""


class ConflictingAllocationError(SeasonAllocationError):
    """An existing row's stored snapshot disagrees with the league's current
    economy stop. Refused without mutation — reposting against a different
    stop would split one season's allocation across two stops."""


class NoTeamsError(SeasonAllocationError):
    """The league has no teams, so there is nothing to allocate. Refused
    rather than recorded as a vacuously 'complete' activation, which would
    permanently poison the state machine: every team added later would read
    as partial and could never be allocated."""


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SeasonAllocationResult:
    """What one activation (or one idempotent replay) produced.

    created distinguishes the two success paths: True means this call wrote
    the rows and postings; False means a complete, matching allocation already
    existed and this call wrote nothing at all. On the replay path posting_ids
    is empty — not because the postings are unknown, but because this call
    made none.
    """
    league_id:         int
    season:            int
    team_ids:          tuple[int, ...]
    buyin_cents:       int
    wallet_cents:      int
    reserve_cents:     int
    total_buyin_cents: int
    created:           bool
    posting_ids:       tuple[uuid.UUID, ...]


def _result(
    league_id: int,
    team_ids: tuple[int, ...],
    stop: EconomyStop,
    created: bool,
    posting_ids: tuple[uuid.UUID, ...],
) -> SeasonAllocationResult:
    return SeasonAllocationResult(
        league_id         = league_id,
        season            = config.ALLOCATION_SEASON,
        team_ids          = team_ids,
        buyin_cents       = stop.buyin_cents,
        wallet_cents      = stop.wallet_cents,
        reserve_cents     = stop.reserve_cents,
        total_buyin_cents = stop.buyin_cents * len(team_ids),
        created           = created,
        posting_ids       = posting_ids,
    )


# ── Activation ────────────────────────────────────────────────────────────────

def activate_season_allocation(league_id: int, db: Session) -> SeasonAllocationResult:
    """
    Activate the season allocation for every team in `league_id`, for
    config.ALLOCATION_SEASON. Whole-league operation: all teams or none.

    Season is NOT a parameter — it is read from config so no caller can
    activate a season other than the live one.

    Returns a SeasonAllocationResult. Raises PartialAllocationError,
    ConflictingAllocationError or NoTeamsError on an inconsistent league,
    having mutated nothing. On any error — domain, uniqueness or posting —
    the transaction is rolled back, so neither allocation rows nor ledger
    entries from this call survive.

    The caller supplies the session; this function owns the transaction on it
    and issues the single commit.
    """
    try:
        stop = get_league_economy_stop(league_id, db)

        # order_by(Team.id) is LOAD-BEARING, not tidiness (R-8). It fixes the
        # order in which concurrent activations of the same league insert
        # rows, so they acquire the unique index's locks in the SAME order and
        # QUEUE behind one another instead of deadlocking. Remove it and two
        # overlapping activations can each hold the lock the other needs, and
        # Postgres will abort one with a deadlock rather than the clean
        # IntegrityError the race guard is designed to produce. Do not drop
        # or reorder this clause.
        teams = (
            db.query(Team)
            .filter(Team.league_id == league_id)
            .order_by(Team.id)
            .all()
        )
        team_ids = tuple(t.id for t in teams)
        if not team_ids:
            raise NoTeamsError(
                f"League {league_id} has no teams — nothing to allocate for "
                f"season {config.ALLOCATION_SEASON}. Refusing to record an "
                f"empty activation."
            )

        existing = (
            db.query(SeasonAllocation)
            .filter(
                SeasonAllocation.league_id == league_id,
                SeasonAllocation.season    == config.ALLOCATION_SEASON,
            )
            .all()
        )

        if existing:
            # ── Already-allocated paths. None of these writes anything. ──
            by_team = {row.team_id: row for row in existing}
            present = set(by_team)
            expected = set(team_ids)

            if present != expected:
                missing = sorted(expected - present)
                extra   = sorted(present - expected)
                raise PartialAllocationError(
                    f"League {league_id} has an INCOMPLETE season allocation for "
                    f"season {config.ALLOCATION_SEASON}: {len(present)} of "
                    f"{len(expected)} league "
                    f"teams have rows. Teams present: {sorted(present)}. "
                    f"Teams absent: {missing}. "
                    f"Rows for teams not in this league: {extra}. "
                    f"Refusing to mutate — a partial allocation means something "
                    f"already went wrong and must be investigated, not completed."
                )

            conflicts = [
                (
                    row.team_id,
                    (row.buyin_cents, row.wallet_cents, row.reserve_cents),
                )
                for row in existing
                if (row.buyin_cents, row.wallet_cents, row.reserve_cents)
                != (stop.buyin_cents, stop.wallet_cents, stop.reserve_cents)
            ]
            if conflicts:
                raise ConflictingAllocationError(
                    f"League {league_id}'s stored "
                    f"season-{config.ALLOCATION_SEASON} allocation "
                    f"disagrees with its current economy stop. Current stop "
                    f"(buyin, wallet, reserve) = "
                    f"({stop.buyin_cents}, {stop.wallet_cents}, {stop.reserve_cents}). "
                    f"Stored, by team: {conflicts}. Refusing to mutate — "
                    f"reposting would split one season across two stops."
                )

            # Complete and matching — the idempotent replay. Nothing posted,
            # nothing mutated. Roll back so this branch leaves the session in
            # the SAME terminal posture as every other non-create path (R-2):
            # without it the function would have three postures on one session
            # — commit, rollback, and neither — and a caller could not write
            # correct code against that. Only the read transaction opened by
            # the checks above is discarded; there is nothing else to lose.
            db.rollback()
            return _result(league_id, team_ids, stop, created=False, posting_ids=())

        # ── No rows: create the complete allocation atomically. ──
        posting_ids: list[uuid.UUID] = []
        for team_id in team_ids:
            db.add(SeasonAllocation(
                league_id     = league_id,
                team_id       = team_id,
                season        = config.ALLOCATION_SEASON,
                buyin_cents   = stop.buyin_cents,
                wallet_cents  = stop.wallet_cents,
                reserve_cents = stop.reserve_cents,
            ))
            # Three legs, integer cents, summing to zero by economy_config's
            # import-time invariant. session=db keeps these entries inside THIS
            # transaction; post() does not commit on the session-provided path.
            posting_ids.append(ledger_post(
                [
                    ("world",                  -stop.buyin_cents),
                    (f"wallet:{team_id}",       stop.wallet_cents),
                    (f"reserve:{team_id}",      stop.reserve_cents),
                ],
                door    = DOOR,
                session = db,
            ))

        # Force the INSERTs (and therefore
        # uq_season_allocation_league_team_season, the final race guard) to be
        # evaluated inside this transaction rather than at commit time.
        db.flush()

        # THE single top-level commit — reached only after every row and every
        # posting for every team has succeeded.
        db.commit()

        return _result(league_id, team_ids, stop, created=True, posting_ids=tuple(posting_ids))

    except Exception:
        # Covers domain refusals (which wrote nothing anyway), IntegrityError
        # from the race guard, and any ledger posting error. Every allocation
        # row and every ledger entry from this call is discarded together.
        db.rollback()
        raise
