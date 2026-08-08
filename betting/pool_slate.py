"""
Weekly slate persistence — POR Rev1.3 §4/§5, Scope §C2/§C3/§E/§F.

Exactly FOUR active Pool occurrences per fantasy week. Not three, not a variable
count.

THIS MODULE IS THE IMPURE HALF; betting/pool_rotation.py IS THE PURE HALF. The
selector ranks and signals; this module reads state, performs the reset the
selector only signals, and writes rows. Keeping them apart is what lets the
ranking contract — a SHA-256 digest ordering pinned to an exact serialization —
be tested with no database and reproduced for any historical cycle.

ROLLOVER CONTINUATIONS OCCUPY SLOTS, THEY DO NOT SIT BESIDE THE SLATE (§F). A
continuation takes slot 1..n with its carried cents already in `pot_cents`, and
fresh draws fill what remains. Four rollovers is a valid slate with zero fresh
draws.

A CONTINUATION IS NOT A FRESH USE (POR §4 line 116). `used_fresh_keys` is built
from instances with `origin_instance_id IS NULL` only. Counting a continuation
as a fresh use would exhaust the cycle faster than the rules say and trigger
resets that should not happen; the partial unique index would also then forbid
exactly what the reset rule permits.

THE NO-REPEAT INVARIANT IS PROVED BY A CONSTRAINT, NOT BY THIS CODE. The
carried-key subtraction below happens before ranking because POR §4 states it as
a selection rule, but `uq_pool_instance_cycle_fresh` is what makes the invariant
unfalsifiable. An ordering heuristic can be correct on every observed input and
still permit a violation; a partial unique index cannot.

MONEY IS NOT MOVED HERE. Slate creation writes `pot_cents` only as the carried
balance of a continuation, which is a column transfer inside
`pool:{league_id}` — the ledger balance is unchanged because the money never
left. Funding is betting/pool_funding.py's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from betting.pool_rotation import (
    Continuation,
    build_week_slate,
    DEFAULT_SLOT_COUNT,
)
from betting.pool_gates import selectable_definitions
from betting.pool_season_boundary import PHASE_REGULAR

REASON_INSUFFICIENT_ELIGIBLE = "INSUFFICIENT_ELIGIBLE_DEFINITIONS"


class PoolSlateError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


@dataclass(frozen=True)
class SlateBuildResult:
    instances: tuple            # tuple[PoolInstance]
    rotation_cycle: int
    reset_performed: bool
    carried_count: int
    fresh_count: int


def current_rotation_cycle(db, *, league_id: int, season: int) -> int:
    """The league-season's open cycle, opening cycle 1 if none exists.

    The cycle number lives in `pool_rotation_cycle` rather than being derived
    from instances, because §C3 requires one audit row per cycle OPEN and the
    open itself is the fact being recorded. Deriving it from instances would
    make cycle 1 unrecordable — nothing has been drawn yet at the moment it
    opens."""
    from db.schema import PoolRotationCycle

    row = (db.query(PoolRotationCycle)
           .filter(PoolRotationCycle.league_id == league_id,
                   PoolRotationCycle.season == season)
           .order_by(PoolRotationCycle.rotation_cycle.desc())
           .first())
    return row.rotation_cycle if row else 1


def _open_cycle(db, *, league_id: int, season: int, rotation_cycle: int,
                opened_week: int, eligible_set_size: int) -> None:
    """Write the §C3 audit row for a cycle open. Idempotent by constraint.

    `uq_pool_rotation_cycle_open` makes a duplicate open impossible, so a
    replayed slate build cannot double-record a reset. POR §4: "Every reset is
    auditable — one row recording league, season, cycle, opening week, and
    eligible-set size at open."
    """
    from db.schema import PoolRotationCycle

    existing = (db.query(PoolRotationCycle)
                .filter(PoolRotationCycle.league_id == league_id,
                        PoolRotationCycle.season == season,
                        PoolRotationCycle.rotation_cycle == rotation_cycle)
                .first())
    if existing is not None:
        return
    db.add(PoolRotationCycle(
        league_id=league_id, season=season, rotation_cycle=rotation_cycle,
        opened_week=opened_week, eligible_set_size=eligible_set_size,
        opened_at=datetime.now(timezone.utc),
    ))
    db.flush()


def pending_continuations(db, *, league_id: int, season: int, week: int):
    """Instances from earlier weeks still holding a live carry.

    Reads `rollover_cents > 0` on SETTLED instances only. An unsettled instance
    has not had its rollover determined, and treating one as a carry would
    invent a continuation from a Pool that never resolved."""
    from db.schema import PoolInstance

    return (db.query(PoolInstance)
            .filter(PoolInstance.league_id == league_id,
                    PoolInstance.season == season,
                    PoolInstance.week < week,
                    PoolInstance.settled.is_(True),
                    PoolInstance.rollover_cents > 0)
            .order_by(PoolInstance.week, PoolInstance.slot)
            .all())


def used_fresh_keys(db, *, league_id: int, season: int,
                    rotation_cycle: int) -> set[str]:
    """Definition keys already consumed as FRESH draws in this cycle.

    `origin_instance_id IS NULL` is the whole filter and it is load-bearing: a
    continuation is one instance persisting, not a second draw (POR §4)."""
    from db.schema import PoolInstance

    rows = (db.query(PoolInstance.definition_key)
            .filter(PoolInstance.league_id == league_id,
                    PoolInstance.season == season,
                    PoolInstance.rotation_cycle == rotation_cycle,
                    PoolInstance.phase == PHASE_REGULAR,
                    PoolInstance.origin_instance_id.is_(None))
            .all())
    return {r[0] for r in rows}


def build_and_persist_slate(db, *, league, season: int, week: int, phase: str,
                            provider: str,
                            slot_count: int = DEFAULT_SLOT_COUNT,
                            ) -> SlateBuildResult:
    """Draw and persist one week's four occurrences. Does NOT commit.

    Runs entirely inside the caller's transaction so the slate and the weekly
    funding that follows it commit together or not at all — a funded week with
    no slate, or a slate with no funding, are both states no reader could act
    on.
    """
    from db.schema import PoolInstance

    league_id = league.id
    rotation_cycle = current_rotation_cycle(db, league_id=league_id,
                                            season=season)

    eligible = selectable_definitions(db, league_id=league_id,
                                      provider=provider, phase=phase)

    carries = pending_continuations(db, league_id=league_id, season=season,
                                    week=week)
    continuations = tuple(
        Continuation(definition_key=c.definition_key, prior_slot=c.slot)
        for c in carries
    )

    used = used_fresh_keys(db, league_id=league_id, season=season,
                           rotation_cycle=rotation_cycle)

    result = build_week_slate(
        league_id=league_id, season=season, week=week,
        rotation_cycle=rotation_cycle, phase=phase,
        eligible=eligible, continuations=continuations,
        used_fresh_keys=used, slot_count=slot_count,
    )

    reset_performed = False
    if result.reset_required:
        # THE SELECTOR SIGNALS; THIS PERFORMS. POR §4: a cycle resets only at
        # the draw that cannot be satisfied — not at a week boundary and not on
        # a schedule.
        rotation_cycle += 1
        reset_performed = True
        _open_cycle(db, league_id=league_id, season=season,
                    rotation_cycle=rotation_cycle, opened_week=week,
                    eligible_set_size=len(eligible))
        result = build_week_slate(
            league_id=league_id, season=season, week=week,
            rotation_cycle=rotation_cycle, phase=phase,
            eligible=eligible, continuations=continuations,
            # A fresh cycle has consumed nothing. Carrying `used` across the
            # boundary would leave the new cycle born exhausted.
            used_fresh_keys=(), slot_count=slot_count,
        )
        if result.reset_required:
            # Two resets for one draw means the eligible set genuinely cannot
            # fill a slate. POR §4.1: technical validity requires at least four
            # fully supported eligible definitions. Refuse loudly rather than
            # publish a short slate, which would violate "exactly 4 per week".
            raise PoolSlateError(
                REASON_INSUFFICIENT_ELIGIBLE,
                f"league {league_id} season {season} week {week}: "
                f"{len(eligible)} definitions pass BOTH gates, which cannot "
                f"fill {slot_count - len(continuations)} fresh slots even after "
                f"a cycle reset. POR §4.1 requires at least {slot_count} fully "
                f"supported eligible definitions for one week's slate.",
            )
    else:
        # Records the opening of cycle 1 (and re-entry is a no-op by constraint).
        _open_cycle(db, league_id=league_id, season=season,
                    rotation_cycle=rotation_cycle, opened_week=week,
                    eligible_set_size=len(eligible))

    carry_by_key = {c.definition_key: c for c in carries}
    instances: list = []
    for entry in result.slate:
        origin = carry_by_key.get(entry.definition_key) if entry.is_continuation \
            else None
        carried_cents = 0
        if origin is not None:
            carried_cents = int(origin.rollover_cents or 0)
            # The carry is CONSUMED into the continuation in this same
            # transaction. Leaving it set would let the next week's
            # pending_continuations() find it again and mint a second
            # continuation from one pot — Scope §H scenario 10g.
            origin.rollover_cents = 0

        instance = PoolInstance(
            league_id=league_id, season=season, week=week, phase=phase,
            rotation_cycle=rotation_cycle,
            definition_key=entry.definition_key, slot=entry.slot,
            pot_cents=carried_cents, rollover_cents=0,
            origin_instance_id=origin.id if origin is not None else None,
            settled=False, distributed_cents=0,
        )
        db.add(instance)
        instances.append(instance)

    db.flush()
    return SlateBuildResult(
        instances=tuple(instances),
        rotation_cycle=rotation_cycle,
        reset_performed=reset_performed,
        carried_count=len(continuations),
        fresh_count=len(result.slate) - len(continuations),
    )