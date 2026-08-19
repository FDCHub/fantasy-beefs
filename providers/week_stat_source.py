"""The provider-neutral PoolStatSource over one normalized week snapshot.

WP2 EXTRACTED THIS FROM `providers/yahoo/pool_source.py`, WHERE ALL OF IT BUT
ONE THING WAS ALREADY NEUTRAL. The class read `ProviderWeek`, produced the
accepted `Subject` / `TeamFrame` / `StatComponent` shapes, applied the §13
starter rule and the §C7.3 coverage rule — none of which is a Yahoo concern. The
ONE Yahoo-specific input is the translation from the provider's own stat
identifiers to the governed canonical vocabulary, and that is now an injected
`CanonicalStatMap` rather than a hardcoded reader.

    Yahoo   stat ids ("4", "6", "18")     -> YahooStatMap  (the vocabulary's
                                              yahoo_stat_id column)
    Demo    canonical names               -> DemoStatMap   (identity, validated
                                              against the same vocabulary)

THE ENGINE IS THE SAME OBJECT IN BOTH CASES. That is the property WP2 needs: a
Demo Pool is settled by the code that settles a Yahoo Pool, with a different
dictionary in front of it, so there is no second evaluation path to certify and
none to drift.

THE SPRINT 4 POOL ENGINE IS NOT REDESIGNED. This module implements the existing
`betting.pool_subjects.PoolStatSource` protocol. Nothing downstream of the
boundary changes, and nothing here knows what a Pool pays out.

SUPPORT IS MEASURED FROM THE PAYLOAD, NOT FROM THE ARTIFACT (§13, C-12). The
vocabulary says which provider stat id CARRIES passing yards. It does not say
whether THIS response contained it. `supported_stats()` answers from the facts
in hand, so a feed that stopped delivering a category reports it unsupported the
same week rather than the week someone notices.

A MISSING STAT IS UNEVALUABLE, NEVER 0.0. Coverage is asserted affirmatively per
team frame, and a started player the feed never reported withdraws the whole
frame's coverage. The Pool engine's own §C7.3 rule then does the rest.

STARTER/BENCH FOLLOWS THE POOL DEFINITION AND THE WEEKLY SELECTED SLOT. The slot
written into each StatComponent is the provider's selected position for that
week. Display/eligibility position is NEVER used as slot truth (§13) — it
travels in `eligible_positions` and is handed to StatComponent.position, which
is what betting/pool_subjects.py's FLEX rule reads for the OCCUPANT's actual
position. The two are kept in the two fields the accepted engine already
distinguishes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from betting.pool_subjects import (
    SCOPE_MATCHUP,
    SCOPE_TEAM,
    StatComponent,
    Subject,
    TeamFrame,
    WeeklyStructure,
    derivable_coverage,
    is_active_starter,
    normalize_component,
)
from providers.base import ProviderWeek


class CanonicalStatMap(Protocol):
    """Translate one provider stat identifier to a governed canonical name.

    Returning None means "this provider stat is not in the governed vocabulary",
    and the value is DROPPED rather than passed through: betting.pool_catalog
    refuses an ungoverned operand outright, and smuggling one across the
    boundary would surface as that refusal much later and somewhere else.
    """

    def canonical_for(self, stat_id: str) -> str | None:
        ...


class ProviderWeekStatSource:
    """A PoolStatSource over one normalized provider week snapshot.

    Constructed from a `ProviderWeek` plus the provider's own stat map, and
    bound to a Session, mirroring the accepted `LocalRecordedStatSource.bind()`
    shape so every adaptor is used the same way by betting/pool_settlement.py.
    """

    #: Overridden by each provider subclass. Reported by readiness measurement
    #: and by provider incident records so a stuck league names the provider
    #: that answered rather than a default.
    provider: str = ""

    def __init__(self, snapshot: ProviderWeek, *,
                 stat_map: CanonicalStatMap) -> None:
        self._snapshot = snapshot
        self._map = stat_map
        self._db = None
        self._resolver = None

        # Index the snapshot once. A per-subject scan would be O(teams x
        # players) on every settlement.
        self._stats_by_player: dict[str, object] = {
            s.player_key: s for s in snapshot.player_stats}
        self._roster_by_team: dict[str, list] = {}
        for entry in snapshot.roster_entries:
            self._roster_by_team.setdefault(entry.team_key, []).append(entry)

    def bind(self, db, resolver) -> "ProviderWeekStatSource":
        """Attach the Session and the team identity resolver.

        The resolver is required, not optional: mapping a provider team key to
        an internal team id is the one thing this adaptor cannot do alone, and
        S6-R1 forbids the obvious shortcut of matching on the team name that
        happens to be sitting in the DTO.
        """
        self._db = db
        self._resolver = resolver
        return self

    # ── Support surface (§13, C-12) ───────────────────────────────────────────

    def supported_stats(self) -> frozenset[str]:
        """Canonical stats THIS SNAPSHOT actually carries.

        Computed from the union of stat ids present across every player stat
        record, plus fantasy points where reported, plus the matchup scores,
        then expanded by the governed derived formulas. Nothing is advertised
        because the vocabulary says the provider could supply it.
        """
        present_ids: set[str] = set()
        has_points = False
        for stats in self._snapshot.player_stats:
            present_ids |= set(stats.stat_ids_present)
            if stats.fantasy_points is not None:
                has_points = True

        canonical = {
            name for name in
            (self._map.canonical_for(sid) for sid in present_ids)
            if name is not None
        }
        if has_points:
            # kicking_points shares the player's measured fantasy points as its
            # source in the artifact; both are the same measured fact.
            canonical.update({"player_fantasy_points", "kicking_points"})
        if self._snapshot.matchups:
            canonical.update({"matchup_home_score", "matchup_away_score"})

        return derivable_coverage(canonical)

    def unavailable_stats(self) -> frozenset[str]:
        """Canonical stats the vocabulary knows about but this feed cannot give.

        The complement of `supported_stats` over the governed canonical set.
        Reported by readiness measurement so a block reason names the stat
        rather than saying "not ready".
        """
        from betting.pool_catalog import load_vocabulary

        vocab = load_vocabulary()
        return frozenset(vocab.canonical) - self.supported_stats()

    # ── PoolStatSource ────────────────────────────────────────────────────────

    def subjects_for(self, *, league_id: int, season: int, week: int,
                     structure: WeeklyStructure) -> tuple[Subject, ...]:
        """Build the subject field for the census the caller supplies.

        `structure` is the CENSUS and comes from
        betting.pool_subjects.league_weekly_structure — the roster of record and
        the schedule, never this stat feed (§C9, C-14). This method answers only
        with FACTS for the subjects it was handed; a subject it cannot evaluate
        is returned with no coverage, which the Pool engine classifies as
        unevaluable. It is never dropped, because a dropped subject would shrink
        the evaluated count and the census alongside it.
        """
        if structure.scope == SCOPE_TEAM:
            return tuple(
                Subject(subject_id=team_id, subject_type=SCOPE_TEAM,
                        frames=(self._team_frame(team_id, week),))
                for team_id in structure.considered_subject_ids
            )

        if structure.scope != SCOPE_MATCHUP:
            raise ValueError(
                f"scope {structure.scope!r} has no subject rule; "
                f"betting.pool_subjects owns that ruling and this adaptor does "
                f"not invent one.")

        from db.schema import Matchup

        subjects: list[Subject] = []
        for matchup_id in structure.considered_subject_ids:
            row = (self._db.query(Matchup)
                   .filter(Matchup.id == matchup_id).first())
            if row is None:
                continue
            home = self._team_frame(row.home_team_id, week,
                                    score=row.home_score)
            away = self._team_frame(row.away_team_id, week,
                                    score=row.away_score)
            subjects.append(Subject(subject_id=matchup_id,
                                    subject_type=SCOPE_MATCHUP,
                                    frames=(home, away)))
        return tuple(subjects)

    # ── Frame construction ────────────────────────────────────────────────────

    def _team_key_for(self, team_id: int) -> str | None:
        for key in getattr(self._resolver, "known_keys", ()):
            if self._resolver.to_internal(key) == team_id:
                return key
        return None

    def _team_frame(self, team_id: int, week: int,
                    score: float | None = None) -> TeamFrame:
        team_key = self._team_key_for(team_id)
        entries = self._roster_by_team.get(team_key or "", [])

        components: list[StatComponent] = []
        #: Stat ids the feed delivered for THIS team's starters. Union, because
        #: a category a kicker legitimately lacks is a component-level
        #: structural omission (§C7.3), not a gap in ingestion.
        delivered_ids: set[str] = set()
        every_starter_measured = bool(entries)
        points_complete = bool(entries)

        for entry in entries:
            # SLOT decides starter/bench, and it is the provider's WEEKLY
            # selected position. `position` carries the player's actual
            # eligibility, which is what the accepted FLEX rule reads for the
            # occupant. §13 forbids the two being conflated, and they are two
            # fields here for exactly that reason.
            probe = StatComponent(
                values={}, slot=entry.slot,
                position=(entry.eligible_positions[0]
                          if entry.eligible_positions else None))
            if not is_active_starter(probe):
                continue

            stats = self._stats_by_player.get(entry.player_key)
            if stats is None:
                # A STARTED PLAYER WITH NO STATS RECORD AT ALL. Not zero — the
                # feed never spoke about this player, so the team's numbers are
                # unknown. Coverage is withdrawn for the whole frame rather than
                # this component being silently skipped, which would let a
                # partially-ingested team settle as though it were complete.
                every_starter_measured = False
                points_complete = False
                continue

            delivered_ids |= set(stats.stat_ids_present)
            if stats.fantasy_points is None:
                points_complete = False

            values: dict[str, float] = {}
            for stat_id, value in stats.values.items():
                canonical = self._map.canonical_for(stat_id)
                if canonical is None:
                    # An ungoverned provider stat id. Dropped rather than passed
                    # through: betting.pool_catalog refuses an ungoverned
                    # operand outright, and smuggling one across the boundary
                    # would surface as that refusal much later.
                    continue
                values[canonical] = float(value)
            if stats.fantasy_points is not None:
                values["player_fantasy_points"] = float(stats.fantasy_points)
                values["kicking_points"] = float(stats.fantasy_points)

            # ── PDS1 — MATERIALIZE THE GOVERNED DERIVED OPERANDS ─────────────
            #
            # §C7.2 has two halves and only one used to be wired here.
            # `derivable_coverage` below expands the COVERAGE set, so a frame
            # carrying rush_attempts and receptions correctly reported that it
            # covers `touches`. Nothing materialized the VALUE, and
            # `betting/pool_shapes.py` reads an operand as
            # `values.get(name, 0.0)` — so `subject_value` passed the coverage
            # gate on honest coverage and then summed a key that was never
            # there, scoring every subject 0.0.
            #
            # That was a wrong-winner defect, not a cosmetic one: a CLOSED_SUM
            # over a derived operand tied the entire field at zero and
            # EVEN_SPLIT divided the pot across every GM in the league, and a
            # CLOSED_RATIO computed 0/0 and refused a week it had the data to
            # settle.
            #
            # The formulas are NOT restated here. `normalize_component` reads
            # them from the governed vocabulary artifact, is the single
            # implementation of that math, and already gives an explicitly
            # supplied canonical value precedence over a derived one — so a
            # provider that reports `touches` itself still wins.
            values, _ = normalize_component(values)

            components.append(StatComponent(
                values=values, slot=entry.slot,
                position=(entry.eligible_positions[0]
                          if entry.eligible_positions else None)))

        covered: set[str] = set()
        if every_starter_measured and components:
            covered = {
                name for name in
                (self._map.canonical_for(sid) for sid in delivered_ids)
                if name is not None
            }
            if points_complete:
                covered.update({"player_fantasy_points", "kicking_points"})
            # Expand by the governed derived formulas — coverage of the inputs
            # IS coverage of the derived operand, which is the accepted Sprint 4
            # rule (betting.pool_subjects.derivable_coverage).
            covered = set(derivable_coverage(covered))

        if score is not None:
            covered.update({"matchup_home_score", "matchup_away_score"})

        return TeamFrame(team_id=team_id, components=tuple(components),
                         covered_stats=frozenset(covered), score=score)


# ── Gate-2 readiness measurement (§14, C-13) ──────────────────────────────────

def measure_activation(db, *, league_id: int, source: ProviderWeekStatSource,
                       provider: str, observed_at: datetime | None,
                       definition_keys: Sequence[str] | None = None,
                       measured_at: datetime | None = None) -> dict:
    """Measure gate-2 readiness per definition from the PAYLOAD, and record it.

    REUSES THE ACCEPTED GATE MODEL. Writes through
    `betting.pool_gates.record_activation_measurement` into
    `PoolLeagueActivation`, the existing carrier. No parallel gate is created,
    and `betting.pool_gates` continues to own the staleness rule.

    RESTORED CONNECTIVITY IS NOT READINESS (§14, and Scope §H control 18g). A
    definition is ready only when every one of its `required_stats` is in the
    set this snapshot ACTUALLY MEASURED. Reaching the provider successfully and
    receiving a payload with no stat categories in it measures nothing, and
    produces `ready=False` with the missing stats named.

    `measured_at` DEFAULTS TO THE SNAPSHOT'S OBSERVED INSTANT, not to the wall
    clock. Under fixture replay that is the manifest's frozen `replay_now`, so
    the 24-hour staleness window can be exercised deterministically.

    THE MEASUREMENT IS RECORDED UNDER THE PROVIDER THAT MADE IT. Gate 2 rows are
    keyed (league, provider, definition), so a Demo league's readiness cannot be
    read as a Yahoo league's and vice versa.
    """
    from betting.pool_catalog import spec_from_row
    from betting.pool_gates import record_activation_measurement
    from db.schema import PoolDefinition

    stamp = measured_at or observed_at
    if stamp is None:
        raise ValueError(
            "readiness measurement requires an observed instant. An unstamped "
            "measurement cannot be aged and would therefore never go stale, "
            "which is the failure mode Scope §C1.1 makes binding.")

    supported = source.supported_stats()

    query = db.query(PoolDefinition)
    if definition_keys is not None:
        query = query.filter(PoolDefinition.key.in_(list(definition_keys)))
    rows = query.order_by(PoolDefinition.catalog_number).all()

    outcome: dict[str, tuple[bool, tuple[str, ...]]] = {}
    for row in rows:
        spec = spec_from_row(row)
        required = tuple(spec.required_stats)
        reasons: tuple[str, ...] = ()

        if not required or not spec.required_stats_resolved:
            # NOT READY, AND NOT VACUOUSLY READY. A definition whose required
            # stats are unresolved has nothing for the provider to have
            # measured, so `all required stats are supported` is TRUE by
            # vacuity — and a measurement that passes because there was nothing
            # to measure is exactly "readiness inferred from silence", which
            # Scope §C1.1 makes binding against.
            ready = False
            reasons = (
                f"REQUIRED_STATS_UNRESOLVED resolved="
                f"{spec.required_stats_resolved} count={len(required)}"
                + (f" reason={spec.required_stats_unresolved_reason}"
                   if spec.required_stats_unresolved_reason else ""),
            )
            record_activation_measurement(
                db, league_id=league_id, provider=provider,
                definition_key=row.key, ready=ready, block_reasons=reasons,
                measured_at=stamp)
            outcome[row.key] = (ready, reasons)
            continue

        missing = tuple(sorted(s for s in required if s not in supported))
        ready = not missing
        if missing:
            reasons = (f"PROVIDER_STAT_UNAVAILABLE {','.join(missing)}",)
        record_activation_measurement(
            db, league_id=league_id, provider=provider,
            definition_key=row.key, ready=ready, block_reasons=reasons,
            measured_at=stamp)
        outcome[row.key] = (ready, reasons)

    return {
        "measured_at": stamp,
        "supported_stats": sorted(supported),
        "definitions": outcome,
        "ready_count": sum(1 for ready, _ in outcome.values() if ready),
    }
