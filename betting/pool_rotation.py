"""
Weekly Pool slate selector — build_week_slate. Step 7.

Product authority : spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_4.md §4, §4.2, §11
Implementation    : spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_1.md §E

PURE. No Session, no ORM, no I/O, no randomness, no clock. Given the same
inputs it returns the same slate in every process, on every machine, forever.

================================================================================
ORDERING COMPATIBILITY CONTRACT — READ BEFORE CHANGING ANYTHING BELOW
================================================================================
Selection order is a SHA-256 digest RANKING, not a PRNG shuffle. For each
candidate definition the digest is computed over this exact serialization:

    payload = json.dumps(
        {
            "definition_key": <str>,
            "league_id":      <int>,
            "rotation_cycle": <int>,
            "season":         <int>,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    digest = hashlib.sha256(payload).digest()

Candidates are ordered by RAW DIGEST BYTES ascending, then catalog_number
ascending, then definition_key ascending.

Types are load-bearing: the ints stay ints and the key stays str, because
json.dumps renders 2026 and "2026" differently and the digest would change.
Raw digest bytes are compared, never the hexdigest string.

WEEK IS DELIBERATELY NOT IN THE DIGEST. A cycle has ONE ordering; successive
weeks consume successive entries from it. Putting week in the digest would
reshuffle the ordering every week and destroy the no-repeat guarantee's
meaning.

Python's builtin hash() is FORBIDDEN — it is salted per process, so it produces
a different ordering in every run. repr(), pickle, object identity and
locale-sensitive formatting are forbidden for the same class of reason.

THIS IS A CONTRACT, NOT AN IMPLEMENTATION DETAIL. Changing the serialization —
the key names, the key order, the separators, the ascii flag, the field types,
or the tie-breakers — makes every historical cycle ordering unreproducible and
breaks audit reconstruction. A past week's slate could no longer be shown to
have followed the rules.
================================================================================

CARRIED-KEY SUBTRACTION IS MANDATORY AND HAPPENS BEFORE RANKING. POR §4 states
it as a selection rule: "The selector excludes carried definitions from the
same-week fresh candidate pool." The week-level unique constraint is a
persistence BACKSTOP, not control flow — an IntegrityError raised mid-flush
leaves a SHORT SLATE, which violates "exactly 4 active Pools per fantasy week".

THE SELECTOR SIGNALS A RESET; IT NEVER PERFORMS ONE. §E line 157 reads
`if len(pool) < slots and phase = REGULAR:`. A pure function cannot increment a
cycle or write an audit row, so it returns reset_required=True together with the
context §C3's audit row needs. Reaching a rotation boundary is a NORMAL,
EXPECTED state — unlike a null formula reaching the evaluator, which is a bug —
so it is a returned value, not a raised exception. Conflating the two by raising
for both would make a routine boundary indistinguishable from a defect.

MID-SEASON ELIGIBILITY IS THE CALLER'S DECISION. This function ranks exactly the
eligible set it is handed. Whether that set was snapshotted at season open or
queried live is unresolved product policy and is deliberately not baked in here.

================================================================================
SCOPE COMPOSITION — POR Rev 1.4 §4.2, ADOPTED 2026-08-21
================================================================================
The normal four-Pool REGULAR-phase weekly slate is **3 TEAM + 1 MATCHUP**.

Before Rev 1.4 the selector imposed no composition at all: it ranked the whole
eligible set and took the top four, and because 29 of the 64 runtime-eligible
definitions are MATCHUP-scoped, an unconstrained digest ordering produced weeks
that were mostly matchup-vs-matchup contests. That was an accident of the hash,
not a product decision, and the owner ruled the mix explicitly.

THE COMPOSITION DECIDES MEMBERSHIP. THE RANKING STILL DECIDES ORDER.
Nothing in the ORDERING COMPATIBILITY CONTRACT above changes: the digest
serialization, the raw-bytes comparison, the catalog_number / definition_key
tie-breakers and the carried-key subtraction are all untouched, and every
historical cycle ordering remains reproducible. What Rev 1.4 adds is a quota on
how many fresh slots each scope receives; WHICH definitions fill those slots is
still the same ranking over the same candidate set, and the slots themselves are
still laid out in global rank order so a slate reads exactly as it always did.

DEFICITS, NOT A FIXED CUT. Continuations are placed first and are never
displaced — each holds a live pot — so the quota is expressed against what the
carries have ALREADY contributed:

    deficit(scope) = max(0, target(scope) - carried(scope))

and fresh slots are handed out in the mix's declared order, which is why
`DEFAULT_SCOPE_MIX` is an ordered tuple rather than a mapping. Because the
targets sum to the slot count, the deficits sum to at least the fresh-slot count
in every carry configuration, so the allocation is total and the order only ever
decides which deficit gets TRIMMED when carries have over-filled the other
scope. That trim is deterministic, which is the whole point of pinning it.

CROSS-SCOPE FALLBACK, because "exactly 4 active Pools per fantasy week" (POR §4)
is the stronger invariant. A scope that cannot fill its share from its own
unused candidates does not shorten the slate and does not force a cycle reset:
the shortfall is taken from the other scope's remaining candidates through the
SAME ranking. A reset is still signalled only when the TOTAL unused eligible set
cannot fill the total fresh slots — the composition is a preference about shape,
never a second exhaustion condition.

THE REGULAR PHASE ONLY, AND ONLY AT THE GOVERNED SLOT COUNT. The postseason
subset is fixed and the championship round is themed (WP1B §12); imposing a
scope quota there would fight the theme. And a caller asking for a slot count the
mix was not written for gets the pre-Rev-1.4 pure ranking rather than a silently
rescaled quota nobody ruled on.

THE MIX IS CATALOG DATA. `spec/pool_catalog_rev1_4.json` carries
`weekly_slate_composition`, and `betting.pool_catalog.load_catalog` refuses any
catalog whose block disagrees with `DEFAULT_SCOPE_MIX` below. The constant lives
here so the pure selector stays pure — no I/O, no catalog read — and the load-
time check is what stops the artifact and the code from drifting apart.
================================================================================
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Sequence

PHASE_REGULAR = "REGULAR"
PHASE_POSTSEASON = "POSTSEASON"

DEFAULT_SLOT_COUNT = 4

SCOPE_TEAM = "TEAM"
SCOPE_MATCHUP = "MATCHUP"

#: POR Rev 1.4 §4.2 — the governed scope composition of the normal weekly
#: slate, as an ORDERED tuple. The order is the priority in which fresh-slot
#: deficits are satisfied (see the module contract), so it is part of the rule
#: and not an incidental way of writing a mapping down.
#: `spec/pool_catalog_rev1_4.json::weekly_slate_composition` carries the same
#: figures and `betting.pool_catalog.load_catalog` refuses a catalog that
#: disagrees with this constant.
DEFAULT_SCOPE_MIX: tuple[tuple[str, int], ...] = (
    (SCOPE_TEAM, 3),
    (SCOPE_MATCHUP, 1),
)

REASON_TOO_MANY_CONTINUATIONS = "TOO_MANY_CONTINUATIONS"
REASON_DUPLICATE_CONTINUATION = "DUPLICATE_CONTINUATION"
REASON_DUPLICATE_ELIGIBLE = "DUPLICATE_ELIGIBLE"
REASON_UNKNOWN_PHASE = "UNKNOWN_PHASE"
REASON_INVALID_SLOT_COUNT = "INVALID_SLOT_COUNT"
#: A candidate reached a composed draw carrying no scope. Not a product state —
#: `pool_gates.selectable_definitions` reads `pool_definition.scope` for every
#: row it returns — so it is refused rather than defaulted, because defaulting
#: would silently file every unscoped definition under one scope and quietly
#: change the mix.
REASON_MISSING_SCOPE = "MISSING_SCOPE"


class PoolRotationError(ValueError):
    """Selector-domain exception family. `reason` names the violated invariant."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


@dataclass(frozen=True)
class EligibleDefinition:
    """A definition the CALLER has already decided is eligible. The selector
    makes no eligibility decision of its own — it neither reads
    dependency_state nor filters blocked definitions.

    `scope` is the catalog's own TEAM/MATCHUP value and is what POR Rev 1.4
    §4.2's composition is computed over. It defaults to None so that a caller
    who wants the pre-Rev-1.4 pure ranking — every unit test of the ORDERING
    CONTRACT itself, for one — can keep constructing candidates without it; a
    COMPOSED draw refuses a None scope rather than guessing (REASON_MISSING_SCOPE).
    """

    definition_key: str
    catalog_number: int
    scope: str | None = None


@dataclass(frozen=True)
class Continuation:
    """A rollover carried into this week. prior_slot is explicit rather than
    inferred from list position, because POR §4 places continuations first and
    their relative order must be reproducible from persisted data alone.

    `scope` is carried for the same reason it is carried on
    `EligibleDefinition`: POR Rev 1.4 §4.2 computes each scope's fresh quota as
    a DEFICIT against what the continuations already occupy, so a composed draw
    cannot be made without knowing what a carry is. None is refused in a
    composed draw rather than defaulted (REASON_MISSING_SCOPE)."""

    definition_key: str
    prior_slot: int
    scope: str | None = None


@dataclass(frozen=True)
class SlateEntry:
    slot: int
    definition_key: str
    is_continuation: bool
    prior_slot: int | None = None


@dataclass(frozen=True)
class ResetContext:
    """Everything §C3's pool_rotation_cycle audit row needs, handed back so the
    caller can write it: league, season, cycle, opening week, eligible-set size
    at open (POR §4 line 119)."""

    league_id: int
    season: int
    exhausted_cycle: int
    opened_week: int
    eligible_set_size: int
    fresh_slots_required: int
    fresh_candidates_available: int


@dataclass(frozen=True)
class SlateResult:
    slate: tuple[SlateEntry, ...]
    reset_required: bool
    reset_context: ResetContext | None = None


def digest_for(definition_key: str, league_id: int, season: int,
               rotation_cycle: int) -> bytes:
    """The pinned serialization. See the module contract above. Any change here
    is a breaking change to historical audit reconstruction."""
    payload = json.dumps(
        {
            "definition_key": str(definition_key),
            "league_id": int(league_id),
            "rotation_cycle": int(rotation_cycle),
            "season": int(season),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).digest()


def rank_definitions(candidates: Iterable[EligibleDefinition], *, league_id: int,
                     season: int, rotation_cycle: int) -> tuple[EligibleDefinition, ...]:
    """Deterministic ranking: raw digest bytes ASC, catalog_number ASC,
    definition_key ASC. The sort key is total (definition_key is unique), so the
    caller's input order cannot influence the result.

    Public because it is the unit that makes carried-key subtraction provable:
    a test can rank the UN-subtracted candidate set and show that the carried
    key would otherwise have been drawn."""
    return tuple(sorted(
        candidates,
        key=lambda d: (
            digest_for(d.definition_key, league_id, season, rotation_cycle),
            d.catalog_number,
            d.definition_key,
        ),
    ))


def fresh_allocation(scope_mix: Sequence[tuple[str, int]],
                     carried_scopes: Sequence[str],
                     fresh_slots: int) -> tuple[tuple[str, int], ...]:
    """How many FRESH slots each scope receives — POR Rev 1.4 §4.2.

    Public because the allocation is the whole of the new rule and a test that
    could only observe it through a finished slate would be testing the ranking
    at the same time. Given the mix, the scopes the continuations already
    occupy, and the number of fresh slots left, this returns the per-scope
    fresh quota in the mix's declared order.

    THE DEFICIT, NOT THE TARGET. A continuation is not displaceable, so a week
    carrying two MATCHUP pots has already overshot a target of one and the
    MATCHUP deficit is zero — the mix describes the SLATE, not the draw.

    IT IS TOTAL WHENEVER THE TARGETS SUM TO THE SLOT COUNT, which the caller
    has already checked. sum(max(0, t - c)) >= sum(t - c) = slot_count -
    carried = fresh_slots, so the quotas always cover the fresh slots and the
    declared order only decides which deficit is trimmed when a carry has
    over-filled another scope.
    """
    remaining = int(fresh_slots)
    allocation: list[tuple[str, int]] = []
    for scope, target in scope_mix:
        if remaining <= 0:
            allocation.append((scope, 0))
            continue
        deficit = max(0, int(target) - carried_scopes.count(scope))
        take = min(deficit, remaining)
        allocation.append((scope, take))
        remaining -= take
    return tuple(allocation)


def _compose(ranked: Sequence[EligibleDefinition],
             allocation: Sequence[tuple[str, int]],
             fresh_slots: int) -> tuple[EligibleDefinition, ...]:
    """Pick the fresh draws for one week under a scope allocation.

    MEMBERSHIP HERE, ORDER AT THE END. Each scope takes its quota off the top
    of its own slice of the SAME global ranking; any quota a scope cannot fill
    falls through to whatever the ranking offers next, whatever its scope,
    because a short slate is the worse outcome (POR §4). The result is then
    re-sorted into global rank order, so the composition changes WHICH four
    definitions a week draws and never the order in which they occupy slots.
    """
    order = {d.definition_key: i for i, d in enumerate(ranked)}
    by_scope: dict[str, list[EligibleDefinition]] = {}
    for d in ranked:
        by_scope.setdefault(d.scope, []).append(d)

    picked: list[EligibleDefinition] = []
    for scope, quota in allocation:
        picked.extend(by_scope.get(scope, ())[:quota])

    if len(picked) < fresh_slots:
        # CROSS-SCOPE FALLBACK. One or both scopes ran out of unused
        # candidates. The slate is still filled to its governed size from the
        # remaining ranking, in rank order, which keeps the fallback as
        # deterministic as the draw it is standing in for.
        taken = {d.definition_key for d in picked}
        for d in ranked:
            if len(picked) >= fresh_slots:
                break
            if d.definition_key not in taken:
                picked.append(d)
                taken.add(d.definition_key)

    return tuple(sorted(picked[:fresh_slots],
                        key=lambda d: order[d.definition_key]))


def build_week_slate(*, league_id: int, season: int, week: int,
                     rotation_cycle: int, phase: str,
                     eligible: Sequence[EligibleDefinition],
                     continuations: Sequence[Continuation] = (),
                     used_fresh_keys: Iterable[str] = (),
                     slot_count: int = DEFAULT_SLOT_COUNT,
                     scope_mix: Sequence[tuple[str, int]] | None
                     = DEFAULT_SCOPE_MIX) -> SlateResult:
    """Build one week's slate — §E lines 148-165.

    `week` is carried into the output for labelling ONLY; it is never part of
    the digest.

    `used_fresh_keys` is the set of definition keys already consumed as FRESH
    draws in this rotation_cycle. A continuation is not a fresh use (POR §4
    line 116), so the caller must not include carried keys here.

    `scope_mix` is POR Rev 1.4 §4.2's governed composition and defaults to it:
    a caller who does nothing gets the ruled 3 TEAM + 1 MATCHUP slate, and
    opting OUT is the thing that has to be written down. Pass None for the
    pre-Rev-1.4 pure ranking — which is what the ORDERING CONTRACT's own unit
    tests want, since a composition would confound the property they measure.
    """
    if phase not in (PHASE_REGULAR, PHASE_POSTSEASON):
        raise PoolRotationError(
            REASON_UNKNOWN_PHASE,
            f"phase must be {PHASE_REGULAR!r} or {PHASE_POSTSEASON!r}, "
            f"got {phase!r}",
        )
    if slot_count < 1:
        raise PoolRotationError(
            REASON_INVALID_SLOT_COUNT,
            f"slot_count must be >= 1, got {slot_count}",
        )

    continuations = tuple(continuations)
    carried_keys = [c.definition_key for c in continuations]
    if len(set(carried_keys)) != len(carried_keys):
        raise PoolRotationError(
            REASON_DUPLICATE_CONTINUATION,
            f"continuations carry a duplicate definition_key: {carried_keys}",
        )
    if len(continuations) > slot_count:
        # Neither §E nor the POR defines this case. It is an upstream invariant
        # violation — more carries than a week has slots means settlement
        # produced an impossible state — so it raises rather than silently
        # truncating a carry, which would strand a live pot.
        raise PoolRotationError(
            REASON_TOO_MANY_CONTINUATIONS,
            f"{len(continuations)} continuations exceed {slot_count} slots; "
            f"upstream invariant violation (neither §E nor the POR defines "
            f"this case, so it is refused rather than truncated).",
        )

    eligible = tuple(eligible)
    eligible_keys = [d.definition_key for d in eligible]
    if len(set(eligible_keys)) != len(eligible_keys):
        raise PoolRotationError(
            REASON_DUPLICATE_ELIGIBLE,
            "eligible set carries a duplicate definition_key",
        )

    # 1 — continuations first, ordered by prior_slot ASC then definition_key ASC.
    ordered_carries = sorted(continuations,
                             key=lambda c: (c.prior_slot, c.definition_key))
    slate = [
        SlateEntry(slot=i, definition_key=c.definition_key,
                   is_continuation=True, prior_slot=c.prior_slot)
        for i, c in enumerate(ordered_carries, start=1)
    ]

    fresh_slots = slot_count - len(ordered_carries)
    if fresh_slots == 0:
        return SlateResult(slate=tuple(slate), reset_required=False)

    # 2 — subtract BEFORE ranking: carried keys, then keys already used fresh
    #     in this cycle. Order of the two subtractions is irrelevant; that they
    #     happen before selection is not.
    carried_set = set(carried_keys)
    used_set = set(used_fresh_keys)
    candidates = [d for d in eligible
                  if d.definition_key not in carried_set
                  and d.definition_key not in used_set]

    # 3 — reset signalling, §E line 157. REGULAR only; the postseason subset is
    #     fixed and does not cycle.
    if len(candidates) < fresh_slots and phase == PHASE_REGULAR:
        return SlateResult(
            slate=(),
            reset_required=True,
            reset_context=ResetContext(
                league_id=league_id,
                season=season,
                exhausted_cycle=rotation_cycle,
                opened_week=week,
                eligible_set_size=len(eligible),
                fresh_slots_required=fresh_slots,
                fresh_candidates_available=len(candidates),
            ),
        )
    if len(candidates) < fresh_slots:
        raise PoolRotationError(
            REASON_INVALID_SLOT_COUNT,
            f"{phase} phase has {len(candidates)} candidates for "
            f"{fresh_slots} fresh slots and does not cycle.",
        )

    # 4 — rank, then consume in rank order.
    ranked = rank_definitions(candidates, league_id=league_id, season=season,
                              rotation_cycle=rotation_cycle)

    # 4a — POR Rev 1.4 §4.2 composition, when it applies. It governs the
    #      REGULAR phase at the governed slot count and nothing else: the
    #      postseason subset is fixed and themed, and a slot count the mix was
    #      not written for gets the pre-Rev-1.4 ranking rather than a rescaled
    #      quota no owner ruled on.
    composed = (scope_mix is not None
                and phase == PHASE_REGULAR
                and sum(int(n) for _, n in scope_mix) == slot_count)
    if composed:
        unscoped = [d.definition_key for d in ranked if not d.scope]
        unscoped += [c.definition_key for c in ordered_carries if not c.scope]
        if unscoped:
            raise PoolRotationError(
                REASON_MISSING_SCOPE,
                f"a composed draw needs every candidate's catalog scope; "
                f"{len(unscoped)} carry none: {sorted(unscoped)[:5]}. "
                f"POR Rev 1.4 §4.2 — the quota is computed per scope, so an "
                f"unscoped definition cannot be placed without inventing one.",
            )
        allocation = fresh_allocation(scope_mix,
                                      [c.scope for c in ordered_carries],
                                      fresh_slots)
        ranked = _compose(ranked, allocation, fresh_slots)

    for offset, d in enumerate(ranked[:fresh_slots]):
        slate.append(SlateEntry(slot=len(ordered_carries) + 1 + offset,
                                definition_key=d.definition_key,
                                is_continuation=False, prior_slot=None))

    return SlateResult(slate=tuple(slate), reset_required=False)
