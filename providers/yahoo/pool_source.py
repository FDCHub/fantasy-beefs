"""Pool provider integration — the accepted PoolStatSource boundary (§13, §14).

THE SPRINT 4 POOL ENGINE IS NOT REDESIGNED. This module implements the existing
`betting.pool_subjects.PoolStatSource` protocol and produces the existing
`Subject` / `TeamFrame` / `StatComponent` shapes. Nothing downstream of the
boundary changes, and nothing here knows what a Pool pays out.

THE VOCABULARY IS AUTHORITATIVE FOR STAT IDENTITY (§13).
`spec/pool_stat_vocabulary_rev1_0.json` already carries `yahoo_stat_id` for
every stat Yahoo sources, and this module reads THAT rather than hardcoding ids.
Three consequences follow directly from the artifact and are not choices made
here:

  * `pass_attempts` and `completions` carry yahoo_stat_id = null
    (UNMAPPED_PENDING_GAME_STAT_CATEGORIES). They can never be reported
    supported, which also makes the derived `opportunities` unavailable — and
    that is precisely why 13 catalog definitions are source-incomplete today.
  * `made_field_goal_distance` is UNSUPPORTED_BY_YAHOO_FANTASY_FEED and is
    never mapped at all.
  * The five field-goal bracket counters ARE mapped, so the derived
    `field_goals_made` becomes available whenever all five are present.

SUPPORT IS MEASURED FROM THE PAYLOAD, NOT FROM THE ARTIFACT (§13, C-12). The
vocabulary says which Yahoo stat id CARRIES passing yards. It does not say
whether THIS response contained it. `supported_stats()` answers from the bytes
in hand, so a feed that stopped delivering a category reports it unsupported the
same week rather than the week someone notices.

A MISSING STAT IS UNEVALUABLE, NEVER 0.0. Two independent guards:
`providers.yahoo.parse` omits a stat whose value did not parse rather than
zeroing it, and coverage below is asserted affirmatively per team frame. The
Pool engine's own §C7.3 rule then does the rest.

STARTER/BENCH FOLLOWS THE POOL DEFINITION AND THE WEEKLY SELECTED SLOT. The slot
written into each StatComponent is the provider's `selected_position.position`
for that week. `display_position` is NEVER used as eligibility truth (§13) — it
travels in `eligible_positions` and is handed to StatComponent.position, which
is what betting/pool_subjects.py's FLEX rule reads for the OCCUPANT's actual
position. The two are kept in the two fields the accepted engine already
distinguishes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Mapping, Sequence

from betting.pool_catalog import VOCABULARY_PATH, load_vocabulary
from betting.pool_subjects import (
    SCOPE_MATCHUP,
    SCOPE_TEAM,
    StatComponent,
    Subject,
    TeamFrame,
    WeeklyStructure,
    derivable_coverage,
    is_active_starter,
)
from providers.base import ProviderWeek

PROVIDER = "yahoo"

#: Source families that come from the weekly player stats feed. Only these carry
#: a yahoo_stat_id worth mapping; FANTASY_POINTS arrives on player_points and
#: LEAGUE_MATCHUP on the matchup row, both handled separately below.
_PLAYER_STAT_FAMILY = "YAHOO_WEEKLY_PLAYER_STATS"


@dataclass(frozen=True)
class YahooStatMap:
    """The governed Yahoo stat id -> canonical name mapping.

    `unmapped` records the canonical names the artifact declares Yahoo-sourced
    but leaves with a null stat id. Carried rather than dropped so a caller
    asking "why is opportunities unsupported?" gets an answer from the mapping
    itself instead of from a code comment.
    """

    by_stat_id: Mapping[str, str]
    unmapped: frozenset[str]
    unsupported: frozenset[str]

    def canonical_for(self, stat_id: str) -> str | None:
        return self.by_stat_id.get(str(stat_id))


@lru_cache(maxsize=1)
def load_yahoo_stat_map(path: str = VOCABULARY_PATH) -> YahooStatMap:
    """Read the authoritative vocabulary and extract the Yahoo id mapping.

    Deliberately a SEPARATE reader from betting.pool_catalog.load_vocabulary
    rather than an extension of it. `StatVocabulary` is accepted Sprint 4
    product surface consumed by the pure evaluator; adding a provider-specific
    field to it would push a Yahoo concern across a boundary Scope §C7 exists to
    keep clean. Both read the same file, so neither can drift from the artifact.
    """
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    by_stat_id: dict[str, str] = {}
    unmapped: set[str] = set()
    unsupported: set[str] = set()

    for entry in raw.get("stats", ()):
        name = entry["canonical_name"]
        family = entry.get("source_family")
        if family == "UNSUPPORTED":
            unsupported.add(name)
            continue
        if family != _PLAYER_STAT_FAMILY:
            continue
        stat_id = entry.get("yahoo_stat_id")
        if stat_id is None:
            # Declared Yahoo-sourced but with no id yet. NOT a defect here —
            # the artifact records it as pending game stat_categories access.
            unmapped.add(name)
            continue
        key = str(stat_id)
        if key in by_stat_id and by_stat_id[key] != name:
            raise ValueError(
                f"vocabulary maps Yahoo stat id {key} to both "
                f"{by_stat_id[key]!r} and {name!r}; one provider stat cannot be "
                f"two canonical operands.")
        by_stat_id[key] = name

    return YahooStatMap(by_stat_id=by_stat_id, unmapped=frozenset(unmapped),
                        unsupported=frozenset(unsupported))


class YahooProviderStatSource:
    """A PoolStatSource over one normalized provider week snapshot.

    Constructed from a `ProviderWeek` and bound to a Session, mirroring the
    accepted `LocalRecordedStatSource.bind()` shape so both adaptors are used
    the same way by betting/pool_settlement.py.
    """

    def __init__(self, snapshot: ProviderWeek, *,
                 stat_map: YahooStatMap | None = None) -> None:
        self._snapshot = snapshot
        self._map = stat_map or load_yahoo_stat_map()
        self._db = None
        self._resolver = None

        # Index the snapshot once. A per-subject scan would be O(teams x
        # players) on every settlement.
        self._stats_by_player: dict[str, object] = {
            s.player_key: s for s in snapshot.player_stats}
        self._roster_by_team: dict[str, list] = {}
        for entry in snapshot.roster_entries:
            self._roster_by_team.setdefault(entry.team_key, []).append(entry)

    def bind(self, db, resolver) -> "YahooProviderStatSource":
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
        because the vocabulary says Yahoo could supply it.
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
            # kicking_points shares Projection.actual_points as its source in
            # the artifact; both are the same measured fact for the player.
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
                    # An ungoverned Yahoo stat id. Dropped rather than passed
                    # through: betting.pool_catalog refuses an ungoverned
                    # operand outright, and smuggling one across the boundary
                    # would surface as that refusal much later.
                    continue
                values[canonical] = float(value)
            if stats.fantasy_points is not None:
                values["player_fantasy_points"] = float(stats.fantasy_points)
                values["kicking_points"] = float(stats.fantasy_points)

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

def measure_league_activation(db, *, league_id: int, snapshot: ProviderWeek,
                              resolver, definition_keys: Sequence[str] | None = None,
                              provider: str = PROVIDER,
                              measured_at: datetime | None = None) -> dict:
    """Measure gate-2 readiness per definition from the PAYLOAD, and record it.

    REUSES THE ACCEPTED GATE MODEL. Writes through
    `betting.pool_gates.record_activation_measurement` into
    `PoolLeagueActivation`, the existing carrier. No parallel gate is created,
    and `betting.pool_gates` continues to own the staleness rule.

    RESTORED CONNECTIVITY IS NOT READINESS (§14, and Scope §H control 18g). A
    definition is ready only when every one of its `required_stats` is in the
    set this snapshot ACTUALLY MEASURED. Reaching Yahoo successfully and
    receiving a payload with no stat categories in it measures nothing, and
    produces `ready=False` with the missing stats named.

    `measured_at` DEFAULTS TO THE SNAPSHOT'S OBSERVED INSTANT, not to the wall
    clock. Under fixture replay that is the manifest's frozen `replay_now`, so
    the 24-hour staleness window can be exercised deterministically.
    """
    from betting.pool_catalog import spec_from_row
    from betting.pool_gates import record_activation_measurement
    from db.schema import PoolDefinition

    stamp = measured_at or snapshot.observed_at
    if stamp is None:
        raise ValueError(
            "readiness measurement requires an observed instant. An unstamped "
            "measurement cannot be aged and would therefore never go stale, "
            "which is the failure mode Scope §C1.1 makes binding.")

    source = YahooProviderStatSource(snapshot).bind(db, resolver)
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
            # Scope §C1.1 makes binding against. The governed catalog carries
            # one such definition today (most_diverse_touchdown_production,
            # required_stats_resolved = false); affirming it would let a
            # restored-connectivity run draw a Pool the provider cannot
            # evaluate.
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
