"""
Governed Pool claim READ MODEL — WP6C.

WHAT THIS EXISTS TO PREVENT. Before WP6C the product's Pool pick control read the
legacy three-pot `POOL_BET_TYPES` list and posted a `PoolBetPick`, while the
Rev1.3 settlement engine resolved winners from `pool_claim` rows it never wrote.
A GM could pick, be told it worked, and hold nothing the engine could pay. Wiring
the WRITE alone would not have closed that: a browser cannot offer a governed
claim without knowing which OCCURRENCE it is claiming and which SUBJECTS that
occurrence admits, and if it guessed either, the write would be refused or —
worse — accepted against the wrong occurrence.

So this module answers exactly the three questions the pick surface has to ask,
and answers them from the same sources the certified engine uses:

    WHICH OCCURRENCES?   `pool_instance` for the league/season/week — the
                         persisted slate, never a composed one.
    WHICH SUBJECTS?      `betting.pool_subjects.league_weekly_structure`, the
                         census source, which is ALSO what
                         `pool_claims._validate_subject` checks a submission
                         against. One source, so the options a GM is offered and
                         the options the engine will accept cannot drift.
    WHEN DOES IT LOCK?   `betting.pool_claims.pool_lock_time`, the same
                         server-side moment `submit_claim` enforces. The browser
                         is TOLD the lock; it never decides it.

READ ONLY, AND DELIBERATELY SO. Nothing here draws a slate, writes a claim or
moves a cent. Drawing is an economic act owned by the weekly collection path; a
read route that drew on demand would let a GM advance their league's rotation by
refreshing a tab.

THE LOCK CAN BE UNKNOWABLE, AND THAT IS REPORTED, NOT GUESSED. `pool_lock_time`
falls back to the earliest kickoff of the week and raises
`ScheduleNotReadyError` when the schedule has not landed. A view that swallowed
that and reported `locked: false` would offer a pick the engine is certain to
refuse. Unknown therefore reports `locked: True` with a named reason: fail
closed, and say which closure it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from betting.pool_claims import pool_lock_time
from betting.pool_subjects import SCOPE_MATCHUP, SCOPE_TEAM, league_weekly_structure

#: `lock_unavailable_reason` when the week's schedule has no announced kickoff.
LOCK_SCHEDULE_NOT_READY = "SCHEDULE_NOT_READY"
#: …and when the definition's scope has no subject rule at all (POR §6.2).
SUBJECTS_UNSUPPORTED_SCOPE = "UNSUPPORTED_SCOPE"


@dataclass(frozen=True)
class SubjectOption:
    """One selectable outcome unit, with a name a GM can read.

    `subject_id` is the ONLY field the engine consumes; `label` exists so the
    browser never has to build a name from an identifier it does not own.
    """

    subject_id: int
    subject_type: str
    label: str


@dataclass(frozen=True)
class OccurrenceClaimView:
    """One governed occurrence as the pick surface needs to see it."""

    pool_instance_id: int
    slot: int
    definition_key: str
    scope: str | None
    settled: bool
    subjects: tuple[SubjectOption, ...]
    #: The viewing GM's own claim on this occurrence, or None. Never another
    #: GM's — a Pool is a blind prediction until it settles, and publishing the
    #: field's picks pre-lock would let a GM copy the room.
    my_subject_id: int | None
    #: How many GMs have claimed. A COUNT, not a roster: it fills the Pool
    #: card's "Entered" row without disclosing who picked what.
    claim_count: int
    lock_time: datetime | None
    locked: bool
    lock_unavailable_reason: str | None
    subjects_unavailable_reason: str | None

    @property
    def open_for_claims(self) -> bool:
        """Whether a submission could be accepted right now.

        The engine remains the authority — this is what the surface uses to
        decide whether to DRAW a control, and a control drawn wrongly is still
        refused server-side."""
        return (not self.settled and not self.locked
                and self.subjects_unavailable_reason is None)


def _subject_labels(db, *, league_id: int, week: int, scope: str,
                    subject_ids: tuple[int, ...]) -> dict[int, str]:
    """Human-readable names for the census's subject ids.

    A MATCHUP is named by BOTH participants, because POR §6.2 makes a matchup
    one subject rather than two team subjects, and a label naming one side would
    invite a GM to read it as that team.
    """
    from db.schema import Matchup, Team

    if scope == SCOPE_TEAM:
        rows = db.query(Team).filter(Team.id.in_(subject_ids)).all()
        return {t.id: t.team_name for t in rows}

    names = {t.id: t.team_name for t in
             db.query(Team).filter(Team.league_id == league_id).all()}
    out: dict[int, str] = {}
    for m in db.query(Matchup).filter(Matchup.id.in_(subject_ids)).all():
        home = names.get(m.home_team_id, f"team {m.home_team_id}")
        away = names.get(m.away_team_id, f"team {m.away_team_id}")
        out[m.id] = f"{home} vs {away}"
    return out


def _subjects_for_scope(db, *, league_id: int, week: int,
                        scope: str | None) -> tuple[tuple[SubjectOption, ...], str | None]:
    """The subjects one occurrence admits, or a named reason there are none.

    Built from `league_weekly_structure` — the CENSUS source — so the offer set
    is by construction the set `pool_claims._validate_subject` will accept.
    Enumerating teams and matchups here independently would be a second
    implementation of POR §6.2, free to disagree with the first.
    """
    if scope not in (SCOPE_TEAM, SCOPE_MATCHUP):
        return (), SUBJECTS_UNSUPPORTED_SCOPE

    structure = league_weekly_structure(db, league_id=league_id, week=week,
                                        scope=scope)
    ids = structure.considered_subject_ids
    labels = _subject_labels(db, league_id=league_id, week=week, scope=scope,
                             subject_ids=ids) if ids else {}
    return tuple(
        SubjectOption(subject_id=sid, subject_type=scope,
                      label=labels.get(sid, f"{scope.lower()} {sid}"))
        for sid in ids
    ), None


def week_claim_view(db, *, league_id: int, season: int, week: int,
                    viewer_team_id: int | None,
                    now: datetime | None = None,
                    ) -> tuple[OccurrenceClaimView, ...]:
    """Every governed occurrence of one week, ready for a pick surface.

    `viewer_team_id` is the AUTHENTICATED GM's team, resolved by the caller from
    the session. It is never taken from a query parameter: `my_subject_id` would
    otherwise disclose any GM's pick to anyone who could name their team id.
    """
    from betting.exceptions import ScheduleNotReadyError
    from db.schema import League, PoolClaim, PoolDefinition, PoolInstance

    now = now or datetime.now(timezone.utc)

    instances = (db.query(PoolInstance)
                 .filter(PoolInstance.league_id == league_id,
                         PoolInstance.season == season,
                         PoolInstance.week == week)
                 .order_by(PoolInstance.slot)
                 .all())
    if not instances:
        return ()

    # ONE LOCK MOMENT FOR THE WHOLE WEEK — POR §11, and the same call
    # `submit_claim` makes per submission. Computed once here because all four
    # occurrences share it; computing it per occurrence could not make them
    # differ, but it would imply they might.
    league = db.query(League).filter(League.id == league_id).first()
    lock_time: datetime | None
    lock_reason: str | None
    try:
        lock_time = pool_lock_time(db, league=league, week=week)
        lock_reason = None
    except ScheduleNotReadyError:
        lock_time = None
        lock_reason = LOCK_SCHEDULE_NOT_READY

    locked = (lock_time is None
              or now >= lock_time.astimezone(timezone.utc))

    definitions = {
        d.key: d for d in db.query(PoolDefinition).filter(
            PoolDefinition.key.in_([i.definition_key for i in instances])).all()
    }

    instance_ids = [i.id for i in instances]
    claims = (db.query(PoolClaim)
              .filter(PoolClaim.pool_instance_id.in_(instance_ids))
              .all())
    counts: dict[int, int] = {}
    mine: dict[int, int] = {}
    for claim in claims:
        counts[claim.pool_instance_id] = counts.get(claim.pool_instance_id, 0) + 1
        if viewer_team_id is not None and claim.team_id == viewer_team_id:
            mine[claim.pool_instance_id] = claim.selected_subject_id

    views: list[OccurrenceClaimView] = []
    for instance in instances:
        scope = getattr(definitions.get(instance.definition_key), "scope", None)
        subjects, subjects_reason = _subjects_for_scope(
            db, league_id=league_id, week=week, scope=scope)
        views.append(OccurrenceClaimView(
            pool_instance_id=instance.id,
            slot=instance.slot,
            definition_key=instance.definition_key,
            scope=scope,
            settled=bool(instance.settled),
            subjects=subjects,
            my_subject_id=mine.get(instance.id),
            claim_count=counts.get(instance.id, 0),
            lock_time=lock_time,
            locked=locked,
            lock_unavailable_reason=lock_reason,
            subjects_unavailable_reason=subjects_reason,
        ))
    return tuple(views)