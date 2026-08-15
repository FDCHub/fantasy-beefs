"""Why is this week stuck? — answered as a PURE READ, without settling anything.

WP2 §23-§24. The WP1E recon found that a fail-closed Pool settlement persisted
nothing about its refusal, so the only way to learn why a week would not settle
was to RUN SETTLEMENT AGAIN. That is a money path used as a diagnostic, and it is
the wrong tool twice over: it takes locks, it may post for a sibling occurrence
that has since become settleable, and an operator investigating an incident
should never have to.

THIS MODULE RE-DERIVES THE ANSWER AND POSTS NOTHING. It calls the same pure
classifier settlement calls — `betting.pool_census.classify_pool` — with the same
census and the same subject facts, and reports the classification instead of
acting on it. `require_settleable` is deliberately NOT called: raising is the
settlement path's job, and a report that raised would be unable to describe the
second stuck Pool after describing the first.

WHAT IT IMPORTS, AND WHAT IT DOES NOT. `betting.pool_catalog`,
`betting.pool_subjects` and `betting.pool_census` — the catalog, the census and
the pure classifier, none of which can move a cent. It imports nothing from
`ledger/`, `economy/` or `betting.pool_settlement`, so the provider layer's money
isolation is unchanged and C-15's static scan is unaffected.

THE STAT SOURCE IS INJECTED. Building one requires knowing which provider the
league is bound to, which is a composition question; this module answers a
provider-neutral one and takes the source as a parameter. That is the same shape
`betting.pool_funding.collect_weekly_entries` uses for its championship state and
resolver, and for the same reason.

IT NAMES NO REMEDY BEYOND RETRY. Every classification it can report is either
settleable-now or one of the four fail-closed states, and WP1E rules that none of
those is terminal. So the report says WHAT IS TRUE and whether the ordinary path
would settle it — never that a Pool should be voided, refunded or swept.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from providers.incident import (
    REASON_RESULTS_NOT_READY,
    is_data_incomplete,
    is_retryable,
    last_provider_refresh,
)


@dataclass(frozen=True)
class PoolDiagnosis:
    """One unsettled Pool occurrence, and why the ordinary path refuses it."""

    pool_instance_id: int
    definition_key: str
    slot: int
    week: int
    classification: str
    settleable: bool
    retryable: bool | None
    data_incomplete: bool
    subjects_considered: int
    subjects_evaluated: int
    subjects_claiming: int | None
    unevaluable_subject_ids: tuple[int, ...] = field(default_factory=tuple)
    detail: str = ""


@dataclass(frozen=True)
class WeekDiagnosis:
    """One league-week's provider and settlement state, as a read."""

    league_id: int
    season: int
    week: int
    provider: str | None
    provider_current_week: int | None
    last_provider_refresh: str | None
    matchups_total: int
    matchups_finalized: int
    week_final: bool
    unfinalized_matchup_ids: tuple[int, ...]
    open_provider_conflicts: int
    pools_total: int
    pools_settled: int
    pools: tuple[PoolDiagnosis, ...] = field(default_factory=tuple)
    #: Set when the week cannot be diagnosed at Pool level at all — typically
    #: because the week is not final, so the finality gate would refuse before
    #: any classification ran. Named rather than left as an empty `pools` list,
    #: which would read as "nothing is stuck".
    blocked_reason: str | None = None

    @property
    def all_settled(self) -> bool:
        return self.pools_total > 0 and self.pools_settled == self.pools_total


def diagnose_week(db, *, league, week: int, stat_source=None) -> WeekDiagnosis:
    """Describe one league-week's provider and Pool state. Writes nothing.

    `stat_source` may be None — a caller whose provider is unreachable still
    wants the finality, freshness and conflict picture, and gets it, with the
    Pool level reported as blocked rather than guessed at.

    THE FINALITY GATE IS CONSULTED, NOT REIMPLEMENTED. `week_finality` is the
    certified census whose one predicate is `finalized_at IS NOT NULL`; a second
    opinion about "final" here is exactly how two definitions of it drift apart.
    """
    from betting.finality_gate import week_finality
    from db.schema import PoolInstance, ProviderConflict

    census = week_finality(db, league_id=league.id, week=week)
    conflicts = (db.query(ProviderConflict)
                 .filter(ProviderConflict.league_id == league.id,
                         ProviderConflict.resolved_at.is_(None))
                 .count())
    refreshed: datetime | None = last_provider_refresh(db, league_id=league.id)

    instances = (db.query(PoolInstance)
                 .filter(PoolInstance.league_id == league.id,
                         PoolInstance.season == league.season,
                         PoolInstance.week == week)
                 .order_by(PoolInstance.slot)
                 .all())
    settled_count = sum(1 for i in instances if i.settled)
    unsettled = [i for i in instances if not i.settled]

    blocked: str | None = None
    pools: tuple[PoolDiagnosis, ...] = ()

    if not census.is_final:
        # The finality gate refuses inside the engine before any classification
        # runs, so classifying here would report a state settlement never
        # reaches. Named, so "no stuck Pools listed" cannot be misread as "no
        # Pools are stuck".
        blocked = REASON_RESULTS_NOT_READY
    elif unsettled and stat_source is None:
        blocked = "provider_unavailable"
    elif unsettled:
        pools = tuple(_diagnose_instance(db, league=league, week=week,
                                         instance=instance,
                                         stat_source=stat_source)
                      for instance in unsettled)

    return WeekDiagnosis(
        league_id=league.id,
        season=league.season,
        week=week,
        provider=league.provider,
        provider_current_week=league.provider_current_week,
        last_provider_refresh=refreshed.isoformat() if refreshed else None,
        matchups_total=census.matchups_total,
        matchups_finalized=census.matchups_finalized,
        week_final=census.is_final,
        unfinalized_matchup_ids=tuple(census.unfinalized_matchup_ids),
        open_provider_conflicts=conflicts,
        pools_total=len(instances),
        pools_settled=settled_count,
        pools=pools,
        blocked_reason=blocked,
    )


def _diagnose_instance(db, *, league, week: int, instance,
                       stat_source) -> PoolDiagnosis:
    """Classify ONE unsettled occurrence without settling it."""
    from betting.pool_catalog import spec_from_row
    from betting.pool_census import classify_pool
    from betting.pool_subjects import league_weekly_structure
    from db.schema import PoolDefinition

    row = (db.query(PoolDefinition)
           .filter(PoolDefinition.key == instance.definition_key).first())
    if row is None:
        return PoolDiagnosis(
            pool_instance_id=instance.id,
            definition_key=instance.definition_key, slot=instance.slot,
            week=week, classification="DEFINITION_NOT_FOUND",
            settleable=False, retryable=False, data_incomplete=False,
            subjects_considered=0, subjects_evaluated=0, subjects_claiming=None,
            detail=(f"pool_instance {instance.id} names definition "
                    f"{instance.definition_key!r}, which is not in the catalog."))

    spec = spec_from_row(row)
    structure = league_weekly_structure(db, league_id=league.id, week=week,
                                        scope=spec.scope)
    subjects = stat_source.subjects_for(
        league_id=league.id, season=league.season, week=week,
        structure=structure)
    outcome = classify_pool(spec, structure, subjects)

    return PoolDiagnosis(
        pool_instance_id=instance.id,
        definition_key=instance.definition_key,
        slot=instance.slot,
        week=week,
        classification=outcome.classification,
        settleable=outcome.settles,
        retryable=(None if outcome.settles
                   else is_retryable(outcome.classification)),
        data_incomplete=is_data_incomplete(outcome.classification),
        subjects_considered=outcome.census.subjects_considered,
        subjects_evaluated=outcome.census.subjects_evaluated,
        subjects_claiming=outcome.census.subjects_claiming,
        unevaluable_subject_ids=tuple(int(i)
                                      for i in outcome.unevaluable_subject_ids),
        detail=("the ordinary settlement path would settle this occurrence"
                if outcome.settles else
                f"the ordinary settlement path refuses this occurrence as "
                f"{outcome.classification}; obtain the authoritative provider "
                f"data and run settlement again. No FantasyStakes 1.0 path "
                f"converts this into a terminal state."),
    )
