"""
economy/season_close.py — B6 §9 season-close seam (§15 items 11-13).

SCOPE FENCE. This module provides EXACTLY THREE THINGS and nothing else:

    1. the read predicate is_season_closed() (§9.1);
    2. the smallest protected writer seam, close_season() (§9.2);
    3. once-only storage of the season-close timestamp in
       League.season_closed_at (§4.6).

It implements NONE of the following, and no future edit may quietly add them
here (§9.3):

    - settlement of any kind;
    - payout;
    - Pot distribution;
    - rollover handling;
    - archival;
    - close sequencing or close orchestration;
    - reopen behaviour, in any form;
    - routes — nothing in this module is registered in api/main.py;
    - notification of close.

It also writes NO audit record, NO ledger entry, NO Wallet row and NO
disclosure. §9.2 states plainly that B6 defines no audit table for this writer:
operator identity is RETURNED to the caller, for the caller to log.

THE COLUMN IS THE WHOLE RECORD
    NULL means open. Non-NULL means closed at that instant. There is no boolean,
    no enum and no status string (§4.6), so there is exactly one representation
    of "closed" and nothing that can disagree with it.

REOPENING IS PROHIBITED (invariant 33)
    No function in this module assigns None to season_closed_at. There is no
    reopen(), no clear(), no reset() and no equivalent by any other name. The
    prohibition is structural, not documentary: the only assignment to that
    column in this file is guarded by `is None`, so it can only ever run against
    an OPEN season.

SERIALIZATION (§6.4)
    close_season() takes the target League row FOR UPDATE as its FIRST database
    statement, in the same position activate_season_allocation() takes its lock
    (economy/season_allocation.py, "THE SERIALIZATION POINT"). That is what makes
    the close deterministic against an in-flight top-off approval, which per §8.2
    step 14 acquires the same League row lock and holds it through commit.

    FOR UPDATE, NOT FOR NO KEY UPDATE, and the difference is deliberate. §6.4
    assigns the season-close writer `League` row FOR UPDATE explicitly, while
    activation deliberately uses the weaker FOR NO KEY UPDATE so it does not
    block on unrelated FK-child inserts. The two conflict with each other in both
    directions — see the measured PostgreSQL 16 matrix at the activation lock
    site — so activation and close still serialize correctly against one another.
    Do not "harmonise" this to key_share=True: the season-close writer is not an
    FK-child inserter and has no reason to take the weaker mode.

TRANSACTION OWNERSHIP (decided, following the Group B precedent)
    close_season() TAKES OWNERSHIP of the supplied session's transaction. It
    commits on the initial-close path and rolls back on every other terminal
    path — the no-op replay, the conflict refusal, the unknown league, and any
    unexpected error. No caller may pass a session carrying uncommitted work it
    expects to survive this call.

COMMIT COUNT (decided)
    At most one commit: exactly one on the initial-close path, ZERO on the
    no-op replay path, ZERO on every error path. Nothing is retried
    automatically — a failure surfaces to the operator rather than being hidden
    behind a second attempt against a lock that has already released.

TIMESTAMP NORMALISATION IS LOAD-BEARING, NOT TIDINESS
    season_closed_at is a bare DateTime — TIMESTAMP WITHOUT TIME ZONE on
    PostgreSQL — matching every other B6 column (league_season_topoff_config,
    top_off_disclosure). A value read back from that column is therefore always
    NAIVE, while a caller is free to pass an AWARE datetime. In Python
    `aware == naive` is False rather than an error, so comparing them raw would
    misclassify a lawful equal-timestamp replay as a CONFLICT, and would do it
    silently. Every timestamp entering or leaving this module is normalised to
    naive UTC by _normalise() before it is stored, compared or returned.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from db.schema import League


# ── Read predicate (§9.1) ─────────────────────────────────────────────────────

def is_season_closed(league: League) -> bool:
    """True when this league's season is closed (§9.1).

    B6 READS this. B6 NEVER WRITES IT — close_season() below is the only writer.

    Pure by construction: no query, no write, no session. It reads one already-
    loaded attribute, so it works on a DETACHED League instance and cannot
    trigger a lazy load or emit SQL from inside a caller's transaction. Callers
    that need a guaranteed-fresh answer must load the League row themselves,
    under the appropriate lock — §8.2 step 14 does exactly that.
    """
    return league.season_closed_at is not None


# ── Errors ────────────────────────────────────────────────────────────────────

class SeasonCloseError(ValueError):
    """Base for every season-close domain refusal. Subclasses are distinct types
    so tests assert on type, never on message text."""


class LeagueNotFoundError(SeasonCloseError):
    """No League row exists for the supplied league_id. Refused rather than
    treated as a vacuous success: silently reporting a season closed for a
    league that does not exist would let an operator typo read as a completed
    close."""


class SeasonCloseConflictError(SeasonCloseError):
    """The season is already closed and a DIFFERENT closed_at was supplied
    (§9.2, once-only). Refused without mutation. The stored timestamp is the
    record of when the season actually closed; overwriting it with a second
    value would rewrite that fact, and choosing between the two is not a
    decision this writer is entitled to make."""


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SeasonCloseResult:
    """What one close (or one once-only replay) produced.

    closed_now distinguishes the two success paths: True means THIS call wrote
    the timestamp and committed; False means the season was already closed and
    this call wrote nothing at all.

    closed_at is naive UTC, exactly as committed to the column, so a caller can
    compare it against a later read without a tz-awareness mismatch.

    operator is ECHOED BACK, not persisted. §9.2 requires the writer to record
    operator identity IN ITS RETURN VALUE for the caller to log, and defines no
    audit table for it. On the replay path it is the operator of THIS call, not
    of the original close — that identity was never stored and cannot be
    invented here.

    season is config.ALLOCATION_SEASON, the money-event season, consistent with
    every other B6 write. It is reported, not stored: §4.6 puts the close
    timestamp on the League row itself.
    """
    league_id:  int
    season:     int
    closed_at:  datetime
    operator:   str
    closed_now: bool


def _normalise(moment: datetime) -> datetime:
    """A datetime as the bare DateTime column stores it: naive, in UTC.

    An AWARE input is converted to UTC and stripped. A NAIVE input is taken to
    be UTC already, which is the codebase-wide convention for these columns —
    every default in db/schema.py is `datetime.now(timezone.utc)` written into a
    bare DateTime, so what lands on disk is naive-UTC wall clock.

    Applied to the generated timestamp, to any caller-supplied timestamp and to
    the value read back from the column, so all three are directly comparable.
    See TIMESTAMP NORMALISATION in the module docstring for why a raw comparison
    is not merely untidy but silently wrong.
    """
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


# ── The single protected writer (§9.2) ────────────────────────────────────────

def close_season(
    league_id: int,
    operator: str,
    db: Session,
    closed_at: datetime | None = None,
) -> SeasonCloseResult:
    """Close the season for `league_id` by stamping League.season_closed_at.

    THE ONLY WRITER of that column (§9.2). No route exposes it, and it is not
    registered in api/main.py at all — it is callable by an operator or by a
    future close protocol, and by nothing else.

    ONCE-ONLY:
      - open season                        -> stamp it, commit once,
                                              closed_now=True
      - closed, closed_at omitted          -> no-op, return the STORED
                                              timestamp, closed_now=False
      - closed, closed_at equals stored    -> same no-op, closed_now=False
      - closed, closed_at differs          -> SeasonCloseConflictError

    `closed_at` is optional BECAUSE both of §9.2's sentences must hold at once.
    "A call against an already-closed season is a no-op returning the existing
    timestamp" and "writing a different timestamp is refused" can only both be
    true if the caller MAY supply a timestamp and MAY omit it: if this function
    always generated its own, every second call would carry a different value
    and the no-op branch would be unreachable.

    When omitted on the open path, ONE authoritative UTC timestamp is generated
    for the call and used for the assignment and the return value alike — never
    two separate now() reads, which would return a value that is not what was
    committed.

    Raises LeagueNotFoundError if no such league exists, and
    SeasonCloseConflictError on a conflicting replay. Both refuse having mutated
    nothing.

    The caller supplies the session; this function owns the transaction on it and
    issues the single commit. The League row is held FOR UPDATE from the first
    statement until that commit (or until the rollback that ends every other
    path), so a concurrent top-off approval either commits before the close or
    observes it at §8.2 step 14 and aborts.
    """
    # In-memory argument handling only — deliberately BEFORE the lock so a
    # malformed call costs no database work, and deliberately NOT a read: no
    # SQL may precede the row lock below.
    requested_at = _normalise(closed_at) if closed_at is not None else None

    try:
        # THE SERIALIZATION POINT (§6.4, §9.2). FIRST database statement of the
        # call — before season_closed_at is read and before anything is written,
        # so two concurrent closes of one league can never both observe an open
        # season and both stamp it. The loser blocks here; when the winner
        # commits, the loser re-reads the committed timestamp under READ
        # COMMITTED's fresh per-statement snapshot and resolves to the once-only
        # replay path instead of overwriting the record.
        #
        # FOR UPDATE, not FOR NO KEY UPDATE — see SERIALIZATION in the module
        # docstring. key_share=True is deliberately NOT passed.
        locked_league = (
            db.query(League)
            .filter(League.id == league_id)
            # The orchestrator loads this League before reaching the terminal
            # writer. Refresh it from the SELECT ... FOR UPDATE result rather
            # than reusing a stale identity-map value that may still say OPEN
            # after a concurrent close committed while this query waited.
            .populate_existing()
            .with_for_update()
            .first()
        )

        # A league_id that does not exist locks nothing. Unlike activation —
        # where a missing league falls through to NoTeamsError via the teams
        # query — there is no later check here that would catch it, so it is
        # named explicitly rather than allowed to read as a silent success.
        if locked_league is None:
            raise LeagueNotFoundError(
                f"League {league_id} does not exist. Refusing to report a "
                f"season close for a league that is not there."
            )

        # Read ONLY under the lock. A read taken before it could be stale by the
        # time the lock is granted, which is precisely the window a second
        # concurrent close would use to overwrite the record.
        stored = locked_league.season_closed_at
        stored = _normalise(stored) if stored is not None else None

        if stored is not None:
            # ── Already closed. NOTHING on this path writes. ──
            if requested_at is not None and requested_at != stored:
                raise SeasonCloseConflictError(
                    f"League {league_id}'s season {config.ALLOCATION_SEASON} is "
                    f"already closed at {stored.isoformat()}, and a DIFFERENT "
                    f"closed_at ({requested_at.isoformat()}) was supplied. "
                    f"Refusing to mutate — the stored timestamp is the record of "
                    f"when the season actually closed, and this writer is not "
                    f"entitled to overwrite it. Reopening is prohibited "
                    f"outright, so there is no corrective path here by design."
                )

            # The once-only replay: closed_at omitted, or equal to what is
            # stored. Roll back so this branch leaves the session in the SAME
            # terminal posture as every other non-writing path, following the
            # activation precedent (R-2) — only the read transaction opened by
            # the lock is discarded, and the lock releases with it.
            db.rollback()
            return SeasonCloseResult(
                league_id  = league_id,
                season     = config.ALLOCATION_SEASON,
                closed_at  = stored,
                operator   = operator,
                closed_now = False,
            )

        # ── Open season: stamp it. THE ONLY ASSIGNMENT TO THIS COLUMN IN THE
        # MODULE, and it is reachable only under `stored is None` — which is
        # what makes invariant 33 structural rather than a promise. ──
        effective_at = requested_at if requested_at is not None else _normalise(
            datetime.now(timezone.utc)
        )
        locked_league.season_closed_at = effective_at

        # Force the UPDATE to be issued inside this transaction rather than at
        # commit time, so any database-level failure surfaces here, under the
        # lock, and not from inside commit().
        db.flush()

        # THE single top-level commit. The League lock releases with it.
        db.commit()

        return SeasonCloseResult(
            league_id  = league_id,
            season     = config.ALLOCATION_SEASON,
            closed_at  = effective_at,
            operator   = operator,
            closed_now = True,
        )

    except Exception:
        # Covers the two domain refusals (neither of which wrote anything) and
        # any unexpected database error. The stamp from this call, if one was
        # staged at all, is discarded and the League lock releases with it. No
        # automatic retry: a failed close is reported to the operator, not
        # silently reattempted against a lock this call no longer holds.
        db.rollback()
        raise
