"""Sprint 2B · component projection snapshots — the store and the read seam.

PROVIDER-NEUTRAL ON PURPOSE. Nothing here knows what BALLDONTLIE is. It knows
what a COMPONENT PROJECTION is — a bag of upstream forecast quantities for one
subject in one week, from one named provider — and how to store one without
losing the two facts that make it usable later: WHO it is about, and WHEN it was
observed. `providers/balldontlie/ingest.py` is the provider-shaped caller;
`providers/demo/` could add another tomorrow without touching this file.

── WHY IT NEVER GOES NEAR `projections.projected_points` ───────────────────

`Projection` holds one SCALAR per (player, week, season, source) — a league's
fantasy points, already scored. Twelve modules read it, and two of them price
money: `odds/monte_carlo.py` draws `Normal(projected_points, sigma)` around it,
and `betting/bet_engine.py` multiplies it by an injury factor. There is no
number in a BALLDONTLIE component projection that belongs in that column: the
components have not been through any league's rule set, and BALLDONTLIE's own
point total is scored under BALLDONTLIE's default format — feeding THAT to a
simulator that then applies a league's PPR delta double-converts it.

So this module reads and writes exactly one table, and the legacy path keeps
working unchanged. WP4's evaluator is what will turn components into a scalar,
under the rule set of the league asking.

── IDENTITY IS REQUIRED, NOT ATTEMPTED ─────────────────────────────────────

`persist_snapshot` takes a WP1 `CrossProviderResolution` and refuses anything
that is not RESOLVED. It does not fall back to a name, a team, a position or a
"closest match", because there is no such thing as a nearly-right subject for a
forecast that will price a wager. AMBIGUOUS, UNRESOLVED and CONFLICT each keep
their own named outcome all the way into the report, so an operator sees which
of the three happened without reading a log.

── APPEND-ONLY, AND WHY THAT IS THE PRODUCT DECISION ───────────────────────

A projection is a forecast that moves. BALLDONTLIE publishes NO point-in-time
history — Phase 0 measured `?date=2025-09-03` returning zero rows, and an
undated 2025 week-1 projection carrying a 2026 `collected_at`, which is a
backfill rather than what anyone could have known before kickoff. If this
product ever wants to answer "what did we believe on Thursday", these rows are
the only place that can hold it.

So nothing is ever overwritten. `observation_digest` is what keeps that from
becoming duplication: it hashes the subject, the week, the vocabulary version
and the normalized components — and NOT `captured_at` — so re-fetching an
unchanged projection produces the same digest, collides with the row already
stored, and writes nothing. A forecast that genuinely moved hashes differently
and lands beside its predecessor.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy.exc import IntegrityError

from providers.cross_identity import Outcome as IdentityOutcome
from providers.errors import ProviderIdentityError

__all__ = [
    "ComponentProjection",
    "PersistOutcome",
    "PersistReport",
    "PersistResult",
    "observation_digest",
    "persist_snapshot",
    "persist_snapshots",
    "select_snapshot",
    "select_week",
]


class PersistOutcome:
    """Every way one snapshot can end. Named, because a count is not a reason."""

    PERSISTED = "PERSISTED"
    #: The identical observation is already stored. Not an error — it is the
    #: normal result of re-running an ingestion whose provider has not moved.
    DUPLICATE = "DUPLICATE"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"
    CONFLICT = "CONFLICT"
    #: The row itself could not be stored — a bad payload, a database refusal.
    FAILED = "FAILED"

    #: The identity outcomes that refuse, mapped from WP1's vocabulary rather
    #: than restated, so the two cannot drift apart.
    FROM_IDENTITY = {
        IdentityOutcome.AMBIGUOUS: AMBIGUOUS,
        IdentityOutcome.UNRESOLVED: UNRESOLVED,
        IdentityOutcome.CONFLICT: CONFLICT,
    }


@dataclass(frozen=True)
class ComponentProjection:
    """One provider's forecast for one subject-week, normalized and unscored.

    `components` is the value map a scorer will read: every field of the
    provider's vocabulary, with an absent field carried as its zero, because
    that is what absence means in this provider's payload (Phase 0F-1).

    `components_present` is the RAW key set — what the payload literally carried.
    Both are stored. The zero-omission rule is MEASURED for
    `/fantasy/weekly_stats` and merely shares a namespace with
    `/fantasy/projections`, so keeping the raw presence means that question can
    be settled later from a stored row instead of a re-fetch that may no longer
    return the same forecast.
    """

    provider: str
    provider_player_key: str
    season: int
    week: int
    components: Mapping[str, float]
    components_present: tuple[str, ...] = ()
    nfl_team: str | None = None
    position: str | None = None
    provider_game_id: str | None = None
    provider_record_id: str | None = None
    #: When the PROVIDER says it observed this. Falls back to the capture
    #: instant only when the payload carries no stamp of its own.
    observed_at: datetime | None = None
    source_kind: str = "fantasy/projections"


def observation_digest(*, provider: str, provider_player_key: str, season: int,
                       week: int, vocabulary_version: str,
                       components: Mapping[str, float]) -> str:
    """The deterministic identity of one OBSERVATION.

    WHAT IS IN IT: the subject, the week, the vocabulary the components are
    written in, and the components themselves — sorted, and with every value
    rendered through `repr(float)` so 3 and 3.0 cannot hash apart.

    WHAT IS DELIBERATELY NOT IN IT: `captured_at`, `provenance` and every other
    fact about the FETCH rather than the FORECAST. Including the fetch time
    would give every refresh a new digest, every refresh would store a row, and
    an append-only table would fill with identical forecasts — which is exactly
    the duplication this exists to prevent.
    """
    payload = {
        "provider": str(provider),
        "provider_player_key": str(provider_player_key),
        "season": int(season),
        "week": int(week),
        "vocabulary_version": str(vocabulary_version),
        "components": {str(k): repr(float(v))
                       for k, v in sorted(components.items())},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PersistResult:
    """What happened to one snapshot, and why."""

    outcome: str
    provider: str
    provider_player_key: str
    player_id: int | None = None
    snapshot_id: int | None = None
    digest: str | None = None
    detail: str = ""

    @property
    def stored(self) -> bool:
        return self.outcome == PersistOutcome.PERSISTED


@dataclass
class PersistReport:
    """Named counts, and every non-persisted subject by name.

    THE REFUSALS ARE LISTED, NOT ONLY COUNTED. "3 unresolved" tells an operator
    that something is wrong; `unresolved: ['bdl.p.55512', ...]` tells them what
    to go and fix. A summary that only counts is a summary nobody can act on.
    """

    persisted: int = 0
    duplicate: int = 0
    ambiguous: int = 0
    unresolved: int = 0
    conflict: int = 0
    failed: int = 0
    results: list = field(default_factory=list)

    def record(self, result: PersistResult) -> PersistResult:
        attribute = {
            PersistOutcome.PERSISTED: "persisted",
            PersistOutcome.DUPLICATE: "duplicate",
            PersistOutcome.AMBIGUOUS: "ambiguous",
            PersistOutcome.UNRESOLVED: "unresolved",
            PersistOutcome.CONFLICT: "conflict",
            PersistOutcome.FAILED: "failed",
        }[result.outcome]
        setattr(self, attribute, getattr(self, attribute) + 1)
        self.results.append(result)
        return result

    def subjects(self, outcome: str) -> list:
        return [r.provider_player_key for r in self.results
                if r.outcome == outcome]

    def as_dict(self) -> dict:
        return {
            "persisted": self.persisted,
            "duplicate": self.duplicate,
            "ambiguous": self.ambiguous,
            "unresolved": self.unresolved,
            "conflict": self.conflict,
            "failed": self.failed,
            "ambiguous_subjects": self.subjects(PersistOutcome.AMBIGUOUS),
            "unresolved_subjects": self.subjects(PersistOutcome.UNRESOLVED),
            "conflict_subjects": self.subjects(PersistOutcome.CONFLICT),
            "failed_subjects": self.subjects(PersistOutcome.FAILED),
        }


def persist_snapshot(db, *, resolution, projection: ComponentProjection,
                     captured_at: datetime, provenance: str,
                     vocabulary_version: str | None = None) -> PersistResult:
    """Store one snapshot, or refuse with a named outcome. Never guesses.

    `resolution` is WP1's `CrossProviderResolution`. Anything but RESOLVED is
    refused here rather than downstream, because a projection stored against a
    subject we are not sure of is worse than no projection at all: it is a
    forecast that will be read with confidence.
    """
    from db.schema import ProviderComponentProjection

    vocabulary_version = (vocabulary_version
                          or ProviderComponentProjection.VOCABULARY_V1)

    if resolution is None or resolution.outcome != IdentityOutcome.RESOLVED:
        outcome = PersistOutcome.FROM_IDENTITY.get(
            getattr(resolution, "outcome", None), PersistOutcome.UNRESOLVED)
        return PersistResult(
            outcome=outcome, provider=projection.provider,
            provider_player_key=projection.provider_player_key,
            detail=(getattr(resolution, "detail", "")
                    or "no identity resolution was supplied for this subject"))

    player_id = resolution.canonical.player_id
    if player_id is None:
        return PersistResult(
            outcome=PersistOutcome.UNRESOLVED, provider=projection.provider,
            provider_player_key=projection.provider_player_key,
            detail="the resolution carries no canonical player id")

    # THE RESOLUTION AND THE PAYLOAD MUST BE ABOUT THE SAME SUBJECT. They come
    # from two different objects and a caller could pair them wrongly; a
    # projection filed against the wrong provider key would be undetectable
    # afterwards, because both halves would look internally consistent.
    if (resolution.provider_player_key
            and resolution.provider_player_key != projection.provider_player_key):
        return PersistResult(
            outcome=PersistOutcome.CONFLICT, provider=projection.provider,
            provider_player_key=projection.provider_player_key,
            player_id=player_id,
            detail=(f"the identity resolved to provider key "
                    f"{resolution.provider_player_key!r} but the projection "
                    f"carries {projection.provider_player_key!r}. One of the "
                    f"two is about a different player; refusing to guess "
                    f"which."))

    digest = observation_digest(
        provider=projection.provider,
        provider_player_key=projection.provider_player_key,
        season=projection.season, week=projection.week,
        vocabulary_version=vocabulary_version,
        components=projection.components)

    existing = (db.query(ProviderComponentProjection)
                .filter(ProviderComponentProjection.provider == projection.provider,
                        ProviderComponentProjection.player_id == player_id,
                        ProviderComponentProjection.season == projection.season,
                        ProviderComponentProjection.week == projection.week,
                        ProviderComponentProjection.observation_digest == digest)
                .first())
    if existing is not None:
        return PersistResult(
            outcome=PersistOutcome.DUPLICATE, provider=projection.provider,
            provider_player_key=projection.provider_player_key,
            player_id=player_id, snapshot_id=existing.id, digest=digest,
            detail="this exact observation is already stored; nothing written")

    # THE SELECT ABOVE IS AN OPTIMISATION, NOT THE GUARANTEE. Two workers
    # ingesting one week concurrently can both miss it and both insert; the
    # unique constraint is what settles that, and the loser must be told it lost
    # a DUPLICATE rather than that something FAILED. A savepoint is what lets
    # that be recoverable — the repository's own convention for exactly this
    # shape, in betting/pool_settlement.py and economy/weekly_minimum.py — so
    # the collision releases this one insert and leaves every sibling snapshot
    # already written in this transaction intact.
    savepoint = db.begin_nested()
    row = ProviderComponentProjection(
        provider=projection.provider,
        provider_player_key=projection.provider_player_key,
        player_id=player_id,
        season=int(projection.season),
        week=int(projection.week),
        provider_game_id=projection.provider_game_id,
        nfl_team=projection.nfl_team,
        position=projection.position,
        source_kind=projection.source_kind,
        provenance=provenance,
        provider_record_id=projection.provider_record_id,
        vocabulary_version=vocabulary_version,
        components={str(k): float(v) for k, v in projection.components.items()},
        components_present=sorted(projection.components_present),
        observation_digest=digest,
        observed_at=projection.observed_at or captured_at,
        captured_at=captured_at,
    )
    db.add(row)
    try:
        db.flush()
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        existing = (db.query(ProviderComponentProjection)
                    .filter(ProviderComponentProjection.provider
                            == projection.provider,
                            ProviderComponentProjection.player_id == player_id,
                            ProviderComponentProjection.season
                            == projection.season,
                            ProviderComponentProjection.week == projection.week,
                            ProviderComponentProjection.observation_digest
                            == digest)
                    .first())
        return PersistResult(
            outcome=PersistOutcome.DUPLICATE, provider=projection.provider,
            provider_player_key=projection.provider_player_key,
            player_id=player_id,
            snapshot_id=existing.id if existing is not None else None,
            digest=digest,
            detail="another writer stored this exact observation first; the "
                   "database refused the second copy and nothing was lost")
    return PersistResult(
        outcome=PersistOutcome.PERSISTED, provider=projection.provider,
        provider_player_key=projection.provider_player_key,
        player_id=player_id, snapshot_id=row.id, digest=digest,
        detail=f"snapshot stored for season {projection.season} "
               f"week {projection.week}")


def persist_snapshots(db, pairs: Iterable[tuple], *, captured_at: datetime,
                      provenance: str,
                      vocabulary_version: str | None = None) -> PersistReport:
    """`(resolution, projection)` pairs -> one report. Nothing is dropped.

    EVERY PAIR PRODUCES A RESULT. A subject that refuses is recorded with the
    reason it refused; a subject that is skipped silently is a subject nobody
    knows is missing, and a projection set that is quietly short is the shape of
    a provider outage.
    """
    report = PersistReport()
    for resolution, projection in pairs:
        try:
            result = persist_snapshot(
                db, resolution=resolution, projection=projection,
                captured_at=captured_at, provenance=provenance,
                vocabulary_version=vocabulary_version)
        except ProviderIdentityError as exc:
            result = PersistResult(
                outcome=PersistOutcome.FROM_IDENTITY.get(
                    exc.reason, PersistOutcome.UNRESOLVED),
                provider=projection.provider,
                provider_player_key=projection.provider_player_key,
                detail=str(exc))
        except Exception as exc:                               # noqa: BLE001
            result = PersistResult(
                outcome=PersistOutcome.FAILED, provider=projection.provider,
                provider_player_key=projection.provider_player_key,
                detail=f"{type(exc).__name__}: {exc}")
        report.record(result)
    return report


# ── the read seam Sprint 3 will consume ──────────────────────────────────────

def select_snapshot(db, *, provider: str, player_id: int, season: int,
                    week: int, as_of: datetime | None = None,
                    vocabulary_version: str | None = None):
    """THE snapshot for one subject-week, or None. Deterministic, always.

    The contract, in the order the filters apply:

        1. EXACT provider. There is no fallback to another provider's forecast,
           ever. Two providers disagreeing about a player is a fact worth
           knowing, and silently substituting one for the other destroys it.
        2. EXACT canonical subject. `player_id`, never a name or a provider key.
        3. EXACT season and week.
        4. WITH `as_of`: the latest snapshot observed AT OR BEFORE that instant —
           what was knowable then, which is the whole reason history is kept.
        5. WITHOUT `as_of`: the latest snapshot observed at all.
        6. TIE-BREAK: highest `id`. Two snapshots can share an `observed_at`
           when a provider stamps a batch with one time, and "the latest" must
           still mean one row rather than whichever the database happened to
           return first.

    AND NO FALLBACK TO `projections.projected_points`. If there is no component
    snapshot, this returns None and the caller decides. Reaching for the scalar
    would silently substitute a differently-scored number from a different
    provider under a different rule set, which is the single most dangerous
    thing this seam could do.
    """
    from db.schema import ProviderComponentProjection

    query = (db.query(ProviderComponentProjection)
             .filter(ProviderComponentProjection.provider == provider,
                     ProviderComponentProjection.player_id == player_id,
                     ProviderComponentProjection.season == int(season),
                     ProviderComponentProjection.week == int(week)))
    if vocabulary_version is not None:
        query = query.filter(
            ProviderComponentProjection.vocabulary_version == vocabulary_version)
    if as_of is not None:
        query = query.filter(ProviderComponentProjection.observed_at <= as_of)
    return (query.order_by(ProviderComponentProjection.observed_at.desc(),
                           ProviderComponentProjection.id.desc())
            .first())


def select_week(db, *, provider: str, season: int, week: int,
                player_ids: Sequence[int] | None = None,
                as_of: datetime | None = None) -> dict:
    """`{player_id: snapshot}` for a whole week, under the same contract.

    The bulk form of `select_snapshot`, for a caller pricing a slate rather than
    a player. It applies the identical selection rule per subject — same
    ordering, same tie-break, same refusal to substitute another provider — so a
    week priced in bulk and a player priced alone cannot disagree.
    """
    from db.schema import ProviderComponentProjection

    query = (db.query(ProviderComponentProjection)
             .filter(ProviderComponentProjection.provider == provider,
                     ProviderComponentProjection.season == int(season),
                     ProviderComponentProjection.week == int(week)))
    if player_ids is not None:
        query = query.filter(
            ProviderComponentProjection.player_id.in_(list(player_ids)))
    if as_of is not None:
        query = query.filter(ProviderComponentProjection.observed_at <= as_of)

    chosen: dict = {}
    for row in query.order_by(ProviderComponentProjection.observed_at.desc(),
                              ProviderComponentProjection.id.desc()).all():
        chosen.setdefault(row.player_id, row)
    return chosen


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
