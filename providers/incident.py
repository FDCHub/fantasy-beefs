"""Provider incidents — one operator vocabulary, and where a refusal is recorded.

WP2 §23-§26. THE GAP THIS CLOSES, stated as the WP1E recon found it: a
fail-closed Pool settlement persisted NOTHING about its own refusal. The
classification, the census counts and the unevaluable subject ids lived only on
`WeekSettlementResult.refused` and in the HTTP response, so an operator asking
"why is this Pool stuck?" had to RERUN SETTLEMENT to find out — running a money
path to read a diagnostic.

── WHAT THIS MODULE IS, AND THE CHOICE IS DELIBERATE ────────────────────────

A NAMED TAXONOMY plus a STRUCTURED EMITTER, and NO NEW SCHEMA.

WP2 §26 requires the smallest safe architecture and requires the choice to be
explicit, so here it is. Three durable stores already exist and none of them
fits: `ProviderConflict` records a CONTRADICTION between the provider and frozen
state, which is a different fact from "the feed has not caught up";
`EconomyEvent` records that money moved, and §26 forbids using it when nothing
economic happened; `TuesdaySyncRun` records one scheduled job's steps and no
route runs inside one. Inventing a fourth table is a schema decision this package
does not own — §53 requires it be reported and ruled on first.

So a provider refusal is emitted as a STRUCTURED LOG RECORD and returned to the
caller in the HTTP body, and the SAME payload feeds both. Retention is a
Production Operations dependency and is reported as one; what WP2 owes Ops is a
signal with every field §24 names, and that is what this produces.

THE OTHER HALF OF THE ANSWER IS A READ, NOT A LOG. `providers/diagnosis.py`
re-derives why each unsettled Pool is stuck as a PURE READ, so the question can
be answered without rerunning settlement at all. Between them the requirement is
met without persisting anything new: the log says what happened when, the read
says what is true now.

── ONE VOCABULARY, REUSED (§25) ─────────────────────────────────────────────

Every name below ALREADY EXISTS somewhere in the system — as a
`ProviderIdentityError.reason`, a Pool classification, a season-close step name
or a podium refusal code — and is imported or restated here as a constant so
routes, logs and reports can only spell it one way. NOTHING NEW IS COINED. A
synonym would be worse than no taxonomy at all: an operator grepping for
`INCOMPLETE_FIELD` must find every occurrence of that condition.

── RETRYABILITY IS A PROPERTY OF THE REASON, NOT A GUESS ────────────────────

`RETRYABLE_REASONS` is the set for which "obtain the authoritative data and run
the ordinary path again" is the whole remedy. `NON_RETRYABLE_REASONS` is the set
where retrying changes nothing because the fault is in configuration or in an
evaluator.

NEITHER SET CONTAINS A TERMINAL CLASSIFICATION, AND `TERMINAL_REASONS` IS EMPTY
BY RULING. WP1E is explicit: missing or incomplete provider data is not proof
that no winner exists, so no amount of repetition, elapsed time or finality
converts a fail-closed Pool into a settled one. There is no code path here that
could mark anything terminal, and the empty frozenset is the mechanical
statement of that.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

#: The one logger every provider incident is emitted on. Named so a deployment
#: can route it without matching on message text.
LOGGER = logging.getLogger("fantasystakes.provider.incident")

#: The stable event name every record carries, so a log pipeline can select
#: incidents without parsing prose.
EVENT = "provider_incident"


# ── Named reasons (§25) — every one already exists elsewhere ──────────────────

#: Transport / access. `provider_unavailable` is the code the Pool routes have
#: returned since WP2A; `provider_credentials_missing` names the
#: ProviderCredentialError case that used to fall inside it.
REASON_PROVIDER_UNAVAILABLE = "provider_unavailable"
REASON_PROVIDER_CREDENTIALS_MISSING = "provider_credentials_missing"
REASON_PROVIDER_PARSE_FAILED = "provider_parse_failed"

#: Identity. The route-level code the season-close path already emits, and the
#: three `ProviderIdentityError.reason` values beneath it.
REASON_PROVIDER_IDENTITY_UNRESOLVED = "provider_identity_unresolved"
REASON_NO_PROVIDER_IDENTITY = "no_provider_identity"

#: Conflict. The season-close precondition step name, unchanged.
REASON_PROVIDER_CONFLICT = "provider_conflict"

#: Finality. `betting.finality_gate.ResultsNotReadyError.reason`, unchanged.
REASON_RESULTS_NOT_READY = "RESULTS_NOT_READY"

#: Pool fail-closed classifications — `betting/pool_errors.py`, unchanged.
REASON_NO_SUBJECTS = "NO_SUBJECTS"
REASON_NO_EVALUABLE_SUBJECTS = "NO_EVALUABLE_SUBJECTS"
REASON_INCOMPLETE_FIELD = "INCOMPLETE_FIELD"
REASON_INVARIANT_VIOLATION = "INVARIANT_VIOLATION"

#: Postseason. The championship-track insufficiency reason and the podium
#: refusal code, both unchanged.
REASON_BRACKET_CLASSIFICATION_ABSENT = "BRACKET_CLASSIFICATION_ABSENT"
REASON_PODIUM_STATE_UNKNOWN = "PODIUM_STATE_UNKNOWN"

#: Demo scope. The one genuinely new name in this module, because the condition
#: is genuinely new: a Demo-only action was aimed at a league that is not a Demo
#: league.
REASON_NOT_A_DEMO_LEAGUE = "not_a_demo_league"


#: Retry — with authoritative data in hand — is the entire remedy for these.
RETRYABLE_REASONS: frozenset[str] = frozenset({
    REASON_PROVIDER_UNAVAILABLE,
    REASON_PROVIDER_PARSE_FAILED,
    REASON_RESULTS_NOT_READY,
    REASON_NO_SUBJECTS,
    REASON_NO_EVALUABLE_SUBJECTS,
    REASON_INCOMPLETE_FIELD,
    REASON_BRACKET_CLASSIFICATION_ABSENT,
    REASON_PODIUM_STATE_UNKNOWN,
})

#: Retrying changes nothing: the fault is in configuration, in a binding, or in
#: an evaluator. An operator told to "wait for the data" here would wait forever.
NON_RETRYABLE_REASONS: frozenset[str] = frozenset({
    REASON_PROVIDER_CREDENTIALS_MISSING,
    REASON_PROVIDER_IDENTITY_UNRESOLVED,
    REASON_NO_PROVIDER_IDENTITY,
    REASON_PROVIDER_CONFLICT,
    REASON_INVARIANT_VIOLATION,
    REASON_NOT_A_DEMO_LEAGUE,
})

#: EMPTY BY OWNER RULING (WP1E), and it is a frozenset rather than a comment so
#: the claim is checkable. No provider condition converts a published Pool into
#: a terminal one in FantasyStakes 1.0 — not repetition, not elapsed time, not
#: finality, and not a commissioner. There is no terminal recovery, refund or
#: void, and there is nothing here to add one to.
TERMINAL_REASONS: frozenset[str] = frozenset()

#: Reasons that mean AUTHORITATIVE DATA IS CURRENTLY INCOMPLETE OR UNKNOWN
#: (§24, last bullet). Distinct from retryability: `provider_unavailable` is
#: retryable because the feed is down, while `INCOMPLETE_FIELD` is retryable
#: because the feed answered and left a gap. An operator needs to know which.
DATA_INCOMPLETE_REASONS: frozenset[str] = frozenset({
    REASON_NO_SUBJECTS,
    REASON_NO_EVALUABLE_SUBJECTS,
    REASON_INCOMPLETE_FIELD,
    REASON_RESULTS_NOT_READY,
    REASON_BRACKET_CLASSIFICATION_ABSENT,
    REASON_PODIUM_STATE_UNKNOWN,
})


def is_retryable(reason: str) -> bool | None:
    """True, False, or None for a reason this taxonomy does not classify.

    NONE IS A REAL ANSWER AND IS NOT False. An unclassified reason means nobody
    has decided whether waiting helps, and reporting False would tell an
    operator to escalate a condition that may simply need the feed to catch up.
    """
    if reason in RETRYABLE_REASONS:
        return True
    if reason in NON_RETRYABLE_REASONS:
        return False
    return None


def is_data_incomplete(reason: str) -> bool:
    """Whether this reason means authoritative provider data is missing today."""
    return reason in DATA_INCOMPLETE_REASONS


#: WP2 §50 — the HTTP shape of each named provider refusal. NOT A NEW
#: VOCABULARY: the reason code is what a client matches on and is unchanged;
#: this only decides which governed status carries it, in one place instead of
#: at each route.
#:
#: 409 IS FOR "THIS LEAGUE IS NOT SET UP FOR THAT", 502/503 FOR "THE PROVIDER
#: DID NOT ANSWER", and the distinction is the one an operator acts on. An
#: unresolved identity answered 502 would send someone to look at Yahoo's
#: status page over a binding that was never made; a genuine outage answered
#: 409 would tell a caller to change a request that was correct.
#:
#: NOTHING HERE IS EVER 500. A governed refusal is a decision the system made
#: correctly, and dressing it as a server fault is what made WP2B-D's
#: RESULTS_NOT_READY unactionable before it was mapped.
_HTTP_STATUS: dict[str, int] = {
    REASON_PROVIDER_UNAVAILABLE: 502,
    REASON_PROVIDER_PARSE_FAILED: 502,
    REASON_PROVIDER_CREDENTIALS_MISSING: 503,
    REASON_PROVIDER_IDENTITY_UNRESOLVED: 409,
    REASON_NO_PROVIDER_IDENTITY: 409,
    REASON_PROVIDER_CONFLICT: 409,
    REASON_NOT_A_DEMO_LEAGUE: 409,
    REASON_RESULTS_NOT_READY: 409,
    REASON_NO_SUBJECTS: 409,
    REASON_NO_EVALUABLE_SUBJECTS: 409,
    REASON_INCOMPLETE_FIELD: 409,
    REASON_INVARIANT_VIOLATION: 409,
    REASON_BRACKET_CLASSIFICATION_ABSENT: 409,
    REASON_PODIUM_STATE_UNKNOWN: 409,
}


def http_status_for(reason: str, default: int = 502) -> int:
    """The governed HTTP status for a named provider refusal.

    `default` is 502 rather than 500 deliberately: an unclassified provider
    failure is still a provider failure, and answering 500 would tell a client
    the fault is in FantasyStakes.
    """
    return _HTTP_STATUS.get(reason, default)


def reason_for_exception(exc: Exception) -> str:
    """Map a provider or Pool exception to its NAMED reason.

    READ OFF THE EXCEPTION WHERE IT CARRIES ONE. `ProviderIdentityError.reason`,
    `ResultsNotReadyError.reason` and `PoolSettlementRefusedError.classification`
    are the engines' own vocabulary and are passed through rather than restated,
    which is the same discipline the season-close route already uses for
    `SeasonClosePreconditionError.step`.
    """
    from providers.errors import (
        ProviderConflictError,
        ProviderCredentialError,
        ProviderIdentityError,
        ProviderParseError,
        ProviderTransportError,
    )

    classification = getattr(exc, "classification", None)
    if isinstance(classification, str) and classification:
        return classification
    if isinstance(exc, ProviderCredentialError):
        return REASON_PROVIDER_CREDENTIALS_MISSING
    if isinstance(exc, ProviderConflictError):
        return REASON_PROVIDER_CONFLICT
    if isinstance(exc, ProviderIdentityError):
        return REASON_PROVIDER_IDENTITY_UNRESOLVED
    if isinstance(exc, ProviderParseError):
        return REASON_PROVIDER_PARSE_FAILED
    if isinstance(exc, ProviderTransportError):
        return REASON_PROVIDER_UNAVAILABLE
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason:
        return reason
    return REASON_PROVIDER_UNAVAILABLE


# ── The incident record (§24) ─────────────────────────────────────────────────

@dataclass(frozen=True)
class ProviderIncident:
    """Everything §24 requires an operator be able to determine, and no more.

    THE FIELD LIST IS A CLOSED SET ON PURPOSE. §26 forbids persisting raw
    provider payloads, and the surest way to keep one out of a log is for the
    record to have nowhere to put it. `detail` is a bounded human string built
    from an exception's own message; there is no dict, no payload and no
    headers field, so a caller cannot pass a token through by accident.
    """

    provider: str
    league_id: int
    season: int | None
    week: int | None
    operation: str
    reason: str
    retryable: bool | None
    data_incomplete: bool
    occurred_at: str
    #: The most recent instant any matchup row for this league was refreshed by
    #: a provider, ISO-8601, or None where none ever was. THE ANSWER TO "is the
    #: feed alive at all?" and the one field that distinguishes "the provider
    #: has never spoken about this league" from "it spoke an hour ago and left
    #: a gap".
    last_provider_refresh: str | None = None
    #: The provider's own current week, where it has stated one.
    provider_current_week: int | None = None
    pool_instance_id: int | None = None
    definition_key: str | None = None
    #: Bounded, non-sensitive diagnostic prose.
    detail: str = ""
    #: Census counts for a Pool refusal. Scalars only.
    subjects_considered: int | None = None
    subjects_evaluated: int | None = None
    unevaluable_subject_ids: tuple[int, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return asdict(self)


#: The longest `detail` an incident carries. Long enough for a named refusal's
#: own message, short enough that no payload fragment survives being pasted in.
MAX_DETAIL = 400


def build_incident(*, provider: str, league_id: int, operation: str,
                   reason: str, season: int | None = None,
                   week: int | None = None,
                   pool_instance_id: int | None = None,
                   definition_key: str | None = None,
                   detail: str = "",
                   last_provider_refresh: datetime | None = None,
                   provider_current_week: int | None = None,
                   subjects_considered: int | None = None,
                   subjects_evaluated: int | None = None,
                   unevaluable_subject_ids=(),
                   occurred_at: datetime | None = None) -> ProviderIncident:
    """Assemble one incident. Pure — no session, no log, no side effect."""
    stamp = occurred_at or datetime.now(timezone.utc)
    return ProviderIncident(
        provider=provider or "",
        league_id=int(league_id),
        season=season,
        week=week,
        operation=operation,
        reason=reason,
        retryable=is_retryable(reason),
        data_incomplete=is_data_incomplete(reason),
        occurred_at=stamp.isoformat(),
        last_provider_refresh=(last_provider_refresh.isoformat()
                               if last_provider_refresh else None),
        provider_current_week=provider_current_week,
        pool_instance_id=pool_instance_id,
        definition_key=definition_key,
        detail=str(detail)[:MAX_DETAIL],
        subjects_considered=subjects_considered,
        subjects_evaluated=subjects_evaluated,
        unevaluable_subject_ids=tuple(int(i) for i in unevaluable_subject_ids),
    )


def emit(incident: ProviderIncident) -> dict:
    """Log one incident as structured JSON and return its payload.

    RETURNS THE PAYLOAD SO THE ROUTE CAN SEND THE SAME OBJECT IT LOGGED. Two
    hand-built dictionaries — one for the operator, one for the client — is how
    a diagnostic and its report start disagreeing about what happened.

    Logged at WARNING, not ERROR: a governed provider refusal is a correct
    decision the system made, and grading it as an error would train operators
    to ignore the level that means something is broken.
    """
    payload = incident.as_dict()
    LOGGER.warning(
        "%s reason=%s provider=%s league=%s week=%s operation=%s retryable=%s %s",
        EVENT, incident.reason, incident.provider, incident.league_id,
        incident.week, incident.operation, incident.retryable,
        json.dumps(payload, sort_keys=True, default=str),
        extra={EVENT: payload},
    )
    return payload


def record(**kwargs) -> dict:
    """Build and emit in one call. The shape routes use."""
    return emit(build_incident(**kwargs))


# ── Provider freshness (§24) ──────────────────────────────────────────────────

def last_provider_refresh(db, *, league_id: int,
                          week: int | None = None) -> datetime | None:
    """The most recent instant a provider refresh touched this league's matchups.

    READ FROM `Matchup.refreshed_at`, which the gateway stamps on every persist
    and is explicitly allowed to move even on a post-final no-op refresh. That
    makes it the one column that answers "when did the feed last speak", and it
    is exactly why §9 exempts it from the post-final freeze.

    None means no provider refresh has ever persisted a matchup for this league
    — which is a materially different situation from a stale one, and a caller
    that substituted "a long time ago" would erase the difference.
    """
    from sqlalchemy import func

    from db.schema import Matchup

    query = db.query(func.max(Matchup.refreshed_at)).filter(
        Matchup.league_id == league_id)
    if week is not None:
        query = query.filter(Matchup.week == week)
    return query.scalar()
