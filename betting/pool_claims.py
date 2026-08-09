"""
Prediction claims — Owner Ruling R3, POR Rev1.3 §11 lock behavior.

A PICK IS A CLAIM, NOT A FUNDING TRANSACTION. Nothing in this module moves
money, and nothing in it can. Owner Ruling R3: "A pick creates a claim, not
funding." Zero or few picks do not void an occurrence, do not refund the weekly
contribution, and do not trigger any participation minimum — a GM who makes no
pick simply has no winning claim.

THE LOCK IS THE WEEK'S SHARED EARLIEST GOVERNED KICKOFF. All four occurrences
lock at one moment, computed server-side from the NFL schedule
(`MIN(kickoff_utc)`), never from a client-supplied time. A stale UI cannot
extend the window: the authoritative timestamp is read here, per submission,
and compared against the server clock.

ONE CLAIM PER GM PER OCCURRENCE IS ENFORCED BY A DATABASE CONSTRAINT. The
application check below is a diagnostic that produces a good error message; it
is NOT the enforcement. Two concurrent submissions both pass an application-level
"does one exist?" read, and only `uq_pool_claim_instance_gm` stops the second
from landing. That is why the insert goes through ON CONFLICT DO NOTHING and
treats "no row returned" as the duplicate signal, rather than trusting the
preceding SELECT.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text

from betting.pool_catalog import spec_from_row
from betting.pool_engine import _nfl_lock_time
from betting.pool_subjects import SCOPE_MATCHUP, SCOPE_TEAM


class PoolClaimError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(f"[{reason}] {message}")
        self.reason = reason


REASON_INSTANCE_NOT_FOUND = "INSTANCE_NOT_FOUND"
REASON_WINDOW_CLOSED = "WINDOW_CLOSED"
REASON_DUPLICATE_CLAIM = "DUPLICATE_CLAIM"
REASON_INVALID_SUBJECT = "INVALID_SUBJECT"
REASON_SELF_PICK_BLOCKED = "SELF_PICK_BLOCKED"
REASON_NOT_IN_LEAGUE = "NOT_IN_LEAGUE"
REASON_INSTANCE_SETTLED = "INSTANCE_SETTLED"


@dataclass(frozen=True)
class ClaimResult:
    claim_id: int
    pool_instance_id: int
    team_id: int
    selected_subject_type: str
    selected_subject_id: int
    replaced: bool


def pool_lock_time(db, *, league, week: int) -> datetime:
    """The week's single governed lock moment.

    Reads `PoolPot.lock_time` when an operator has pinned one, else the earliest
    kickoff for the season/week. One moment for the whole week, shared by all
    four occurrences — POR §11."""
    from db.schema import PoolPot

    pot = (db.query(PoolPot)
           .filter(PoolPot.league_id == league.id, PoolPot.week == week)
           .first())
    if pot is not None and pot.lock_time is not None:
        lock = pot.lock_time
        return lock if lock.tzinfo else lock.replace(tzinfo=timezone.utc)
    return _nfl_lock_time(league.season, week)


def _validate_subject(db, *, league_id: int, week: int, scope: str,
                      subject_id: int) -> None:
    """The selected subject must exist in the league's own weekly structure.

    A TEAM subject is one league team; a MATCHUP subject is one scheduled
    matchup of that week — POR §6.2. Validating here means a claim can never
    reference a subject the census will not contain, which would otherwise
    settle as a permanent non-winner with no explanation."""
    from db.schema import Matchup, Team

    if scope == SCOPE_TEAM:
        found = (db.query(Team)
                 .filter(Team.id == subject_id, Team.league_id == league_id)
                 .first())
        if found is None:
            raise PoolClaimError(
                REASON_INVALID_SUBJECT,
                f"team {subject_id} is not in league {league_id}")
    elif scope == SCOPE_MATCHUP:
        found = (db.query(Matchup)
                 .filter(Matchup.id == subject_id,
                         Matchup.league_id == league_id,
                         Matchup.week == week)
                 .first())
        if found is None:
            raise PoolClaimError(
                REASON_INVALID_SUBJECT,
                f"matchup {subject_id} is not scheduled in league "
                f"{league_id} week {week}")
    else:
        raise PoolClaimError(
            REASON_INVALID_SUBJECT,
            f"scope {scope!r} has no subject rule (POR §6.2)")


def submit_claim(db, *, pool_instance_id: int, team_id: int, subject_id: int,
                 replace: bool = False, now: datetime | None = None,
                 ) -> ClaimResult:
    """Record one GM's Prediction claim. Does not commit.

    `replace=False` (default) REFUSES a second claim from the same GM on the
    same occurrence. `replace=True` updates the existing row in place — a GM
    changing their mind before lock is normal product behavior, and it stays
    ONE row, so the one-claim-per-GM invariant holds either way.
    """
    from db.schema import League, PoolClaim, PoolDefinition, PoolInstance, Team

    now = now or datetime.now(timezone.utc)

    instance = (db.query(PoolInstance)
                .filter(PoolInstance.id == pool_instance_id).first())
    if instance is None:
        raise PoolClaimError(REASON_INSTANCE_NOT_FOUND,
                             f"pool instance {pool_instance_id} not found")

    # S4-P2-4 — a settled occurrence accepts no further claims, checked BEFORE
    # the lock so the refusal names the real reason.
    #
    # THE LOCK ALONE IS NOT THIS GUARD. They fail in different situations and
    # neither implies the other: the lock closes at first kickoff, but an
    # instance stays settleable for as long as the data takes to arrive, and a
    # week can be settled long after its lock. Without this check a claim
    # arriving after settlement would be accepted — moving no money, since a
    # claim never does — and would then sit permanently unpayable against a
    # distributed pot, contradicting the settlement's own recorded winner set.
    if instance.settled:
        raise PoolClaimError(
            REASON_INSTANCE_SETTLED,
            f"pool instance {pool_instance_id} settled at "
            f"{instance.settled_at.isoformat() if instance.settled_at else '?'} "
            f"({instance.settlement_classification}); it accepts no further "
            f"claims.")

    league = db.query(League).filter(League.id == instance.league_id).first()
    team = db.query(Team).filter(Team.id == team_id).first()
    if team is None or team.league_id != instance.league_id:
        raise PoolClaimError(
            REASON_NOT_IN_LEAGUE,
            f"team {team_id} is not in league {instance.league_id}")

    lock = pool_lock_time(db, league=league, week=instance.week)
    if now >= lock.astimezone(timezone.utc):
        # FIRST VALID COMMIT GOVERNS, and the boundary is server-side. A claim
        # arriving at or after the lock is refused even if the client believed
        # the window was open.
        raise PoolClaimError(
            REASON_WINDOW_CLOSED,
            f"pick window closed for week {instance.week} at "
            f"{lock.isoformat()}")

    row = (db.query(PoolDefinition)
           .filter(PoolDefinition.key == instance.definition_key).first())
    spec = spec_from_row(row)

    _validate_subject(db, league_id=instance.league_id, week=instance.week,
                      scope=spec.scope, subject_id=subject_id)

    # Self-pick is read from the definition's own metadata, never hardcoded.
    # All 80 active Rev1.3 definitions carry self_pick_rule ALLOWED (POR §2), so
    # this branch is currently unreachable — it exists because the rule is
    # metadata and a future definition may carry BLOCKED, and a missing check
    # would then silently permit a tank vector.
    if spec.self_pick_rule != "ALLOWED" and spec.scope == SCOPE_TEAM \
            and subject_id == team_id:
        raise PoolClaimError(
            REASON_SELF_PICK_BLOCKED,
            f"definition {spec.key!r} carries self_pick_rule "
            f"{spec.self_pick_rule!r}")

    existing = (db.query(PoolClaim)
                .filter(PoolClaim.pool_instance_id == pool_instance_id,
                        PoolClaim.team_id == team_id)
                .first())
    if existing is not None:
        if not replace:
            raise PoolClaimError(
                REASON_DUPLICATE_CLAIM,
                f"team {team_id} already claimed pool instance "
                f"{pool_instance_id}")
        existing.selected_subject_id = subject_id
        existing.selected_subject_type = spec.scope
        existing.submitted_at = now
        db.flush()
        return ClaimResult(claim_id=existing.id,
                           pool_instance_id=pool_instance_id, team_id=team_id,
                           selected_subject_type=spec.scope,
                           selected_subject_id=subject_id, replaced=True)

    # ON CONFLICT DO NOTHING, not a bare INSERT. The SELECT above is a
    # diagnostic; this is the enforcement. Under concurrency both callers see
    # `existing is None` and only one row lands — the loser gets no RETURNING
    # row and raises the same domain error as the sequential duplicate, rather
    # than an IntegrityError leaking out of the driver.
    inserted = db.execute(
        text("""
            INSERT INTO pool_claim
                (pool_instance_id, league_id, team_id, selected_subject_type,
                 selected_subject_id, submitted_at)
            VALUES (:instance_id, :league_id, :team_id, :subject_type,
                    :subject_id, :submitted_at)
            ON CONFLICT (pool_instance_id, team_id) DO NOTHING
            RETURNING id
        """),
        {"instance_id": pool_instance_id, "league_id": instance.league_id,
         "team_id": team_id, "subject_type": spec.scope,
         "subject_id": subject_id, "submitted_at": now},
    ).fetchone()
    if inserted is None:
        raise PoolClaimError(
            REASON_DUPLICATE_CLAIM,
            f"team {team_id} already claimed pool instance "
            f"{pool_instance_id} (lost the insert race)")

    return ClaimResult(claim_id=inserted[0], pool_instance_id=pool_instance_id,
                       team_id=team_id, selected_subject_type=spec.scope,
                       selected_subject_id=subject_id, replaced=False)


def claims_for_instance(db, *, pool_instance_id: int):
    """Every claim on one occurrence, ordered by the CANONICAL GM IDENTIFIER.

    Ordering here rather than at the payout site means the §6.3 allocation is
    handed an already-canonical sequence and cannot accidentally inherit
    database return order."""
    from db.schema import PoolClaim

    return (db.query(PoolClaim)
            .filter(PoolClaim.pool_instance_id == pool_instance_id)
            .order_by(PoolClaim.team_id)
            .all())