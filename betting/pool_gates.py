"""
Two-gate selector enforcement — POR Rev1.3 §1.2, Scope §C7.4.

    selectable == definition_runtime_eligible AND league_activation_ready

THE SELECTOR REQUIRES BOTH, AND EACH GATE ALONE IS A KNOWN FAILURE MODE. Scope
§H names three discriminating controls, and each catches a different plausible
shortcut:

    18a  a selector filtering on `dependency_state` draws the 13
         source-incomplete definitions, which are ENABLED yet gate-1 ineligible
    18b  a selector honouring only gate 1 draws all 64 while the environment
         supplies nothing
    18g  a selector treating restored provider access as full gate-2
         satisfaction draws before any source population was verified

All three pass the naive test and fail here, which is why both gates are read
explicitly below rather than folded into one boolean at the query layer.

GATE 1 IS PERSISTENT; GATE 2 IS TRANSIENT AND SCOPED. Gate 1 lives on
`pool_definition` because it is a property of the definition. Gate 2 lives on
`pool_league_activation`, keyed by league, provider and definition, with a
measurement timestamp — §C1.1 forbids storing it on the catalog, because a
provider outage written into a product artifact is a fact with no scope and no
age.

STALE IS NOT-READY (§C1.1, binding). A measurement older than the staleness
window is treated as false, not as its last known value. A readiness signal that
never expires is a readiness signal that survives the outage it was supposed to
detect. The ABSENCE of a row is likewise not-ready: readiness must be
affirmatively measured, never inferred from silence.

64 IS A CEILING, NOT A FORECAST (§1.2, binding, and conformance 46). Nothing in
this module hardcodes 64 or any other post-access count. `selectable_definitions`
computes the set from the two gates, whatever that yields — any value from 0 to
64 is possible and the count is measured, never asserted in advance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from betting.pool_rotation import EligibleDefinition
from betting.pool_season_boundary import PHASE_POSTSEASON, PHASE_REGULAR

#: How long a gate-2 measurement stays usable. Beyond this the measurement is
#: treated as false. Chosen to be shorter than one fantasy week so a slate is
#: never built on readiness measured for a different week's data state.
DEFAULT_READINESS_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class GateDecision:
    """Why one definition is or is not selectable. Returned for EVERY candidate,
    including the ones that pass, so an operator asking "why did this week draw
    only two Pools?" gets an answer per definition instead of a count."""

    definition_key: str
    catalog_number: int
    #: The catalog's own TEAM/MATCHUP value, carried so the selector can apply
    #: POR Rev 1.4 §4.2's scope composition without a second read of
    #: `pool_definition`. Gate evaluation itself never looks at it.
    scope: str | None
    gate1_definition_runtime_eligible: bool
    gate2_league_activation_ready: bool
    block_reasons: tuple[str, ...]

    @property
    def selectable(self) -> bool:
        return (self.gate1_definition_runtime_eligible
                and self.gate2_league_activation_ready)


def _gate2_for(db, *, league_id: int, provider: str,
               definition_keys: Sequence[str], now: datetime,
               max_age: timedelta) -> dict[str, tuple[bool, tuple[str, ...]]]:
    """Read the gate-2 carrier and apply the staleness rule."""
    from db.schema import PoolLeagueActivation

    rows = (db.query(PoolLeagueActivation)
            .filter(PoolLeagueActivation.league_id == league_id,
                    PoolLeagueActivation.provider == provider,
                    PoolLeagueActivation.definition_key.in_(list(definition_keys)))
            .all())

    out: dict[str, tuple[bool, tuple[str, ...]]] = {}
    for row in rows:
        reasons = tuple(row.league_activation_block_reasons or ())
        measured = row.measured_at
        if measured is not None and measured.tzinfo is None:
            # SQLite returns naive datetimes; Postgres returns aware ones.
            # Normalise before comparing or the subtraction raises and the
            # staleness rule silently never runs.
            measured = measured.replace(tzinfo=timezone.utc)
        if measured is None or (now - measured) > max_age:
            out[row.definition_key] = (
                False,
                reasons + (f"STALE_MEASUREMENT measured_at={measured}",),
            )
            continue
        out[row.definition_key] = (bool(row.league_activation_ready), reasons)
    return out


def gate_decisions(db, *, league_id: int, provider: str, phase: str,
                   now: datetime | None = None,
                   max_age: timedelta = DEFAULT_READINESS_MAX_AGE,
                   ) -> tuple[GateDecision, ...]:
    """Evaluate both gates for every seeded definition in the league's phase."""
    from db.schema import PoolDefinition

    now = now or datetime.now(timezone.utc)
    rows = db.query(PoolDefinition).order_by(PoolDefinition.catalog_number).all()

    phase_filtered = []
    for row in rows:
        if phase == PHASE_REGULAR and not row.regular_season_eligible:
            continue
        if phase == PHASE_POSTSEASON:
            # POR §8 / §C1 — `postseason_eligible` is NULL until the approved
            # 32-subset is supplied, and "a null must be treated as NOT YET
            # ELIGIBLE, never as false-by-default and never as true." So the
            # postseason draws nothing today. That is the recorded blocker, not
            # a defect, and it is emphatically not an invitation to substitute
            # the regular-season set.
            if row.postseason_eligible is not True:
                continue
        phase_filtered.append(row)

    gate2 = _gate2_for(db, league_id=league_id, provider=provider,
                       definition_keys=[r.key for r in phase_filtered],
                       now=now, max_age=max_age)

    decisions: list[GateDecision] = []
    for row in phase_filtered:
        reasons: list[str] = []
        gate1 = bool(row.definition_runtime_eligible)
        if not gate1:
            reasons.append(row.definition_block_reason
                           or f"GATE1_INELIGIBLE dependency_state="
                              f"{row.dependency_state}")
        # A product-blocked definition can never be selectable. It is already
        # gate-1 false in the governed catalog, but the check is explicit here
        # so conformance 19 does not depend on catalog data being right.
        if row.dependency_state == "BLOCKED":
            gate1 = False
            reasons.append(f"PRODUCT_BLOCKED {row.blocked_reason}")

        ready, gate2_reasons = gate2.get(
            row.key, (False, ("NO_READINESS_MEASUREMENT",)))
        if not ready:
            reasons.extend(gate2_reasons or ("GATE2_NOT_READY",))

        decisions.append(GateDecision(
            definition_key=row.key,
            catalog_number=row.catalog_number,
            scope=row.scope,
            gate1_definition_runtime_eligible=gate1,
            gate2_league_activation_ready=ready,
            block_reasons=tuple(reasons),
        ))
    return tuple(decisions)


def selectable_definitions(db, *, league_id: int, provider: str, phase: str,
                           now: datetime | None = None,
                           max_age: timedelta = DEFAULT_READINESS_MAX_AGE,
                           ) -> tuple[EligibleDefinition, ...]:
    """The definitions the selector may draw from, in catalog-number order.

    Returns the pure selector's own input type, so betting/pool_rotation.py
    keeps making no eligibility decision of its own — it ranks exactly the set
    it is handed, which is what lets it stay pure and deterministic."""
    return tuple(
        EligibleDefinition(definition_key=d.definition_key,
                           catalog_number=d.catalog_number,
                           scope=d.scope)
        for d in gate_decisions(db, league_id=league_id, provider=provider,
                                phase=phase, now=now, max_age=max_age)
        if d.selectable
    )


def record_activation_measurement(db, *, league_id: int, provider: str,
                                  definition_key: str, ready: bool,
                                  block_reasons: Sequence[str] = (),
                                  measured_at: datetime | None = None) -> None:
    """Upsert one gate-2 measurement. Does not commit.

    Every write carries `measured_at` — there is no path that records readiness
    without stamping when it was measured, because an unstamped measurement
    cannot be aged and would therefore never go stale."""
    from db.schema import PoolLeagueActivation

    measured_at = measured_at or datetime.now(timezone.utc)
    row = (db.query(PoolLeagueActivation)
           .filter(PoolLeagueActivation.league_id == league_id,
                   PoolLeagueActivation.provider == provider,
                   PoolLeagueActivation.definition_key == definition_key)
           .first())
    if row is None:
        row = PoolLeagueActivation(league_id=league_id, provider=provider,
                                   definition_key=definition_key)
        db.add(row)
    row.league_activation_ready = bool(ready)
    row.league_activation_block_reasons = list(block_reasons) or None
    row.measured_at = measured_at
    db.flush()