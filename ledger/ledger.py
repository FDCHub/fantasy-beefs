"""
ledger/ledger.py — L1 ledger primitive (Session L2 build).

Builds the certified L1 ledger law into real code for the first time.
No stored balance column anywhere — every balance is derived from
ledger_entries via SUM(amount_cents). Every dollar amount in this file
is an integer number of cents; no float ever represents money here.

This is the primitive, built and proven in isolation. Nothing wires
into it yet — beefs/beef_engine.py, betting/bet_engine.py, and
wallet/wallet_manager.py are untouched and still use direct balance
mutation. Migrating them onto this primitive is a separate, later
session (L3), not this one.

Public API:
    from ledger.ledger import post, balance_of, trial_balance, create_ledger_table
    posting_id = post([("wallet:t7", -500), ("escrow:42", 500)], door="wager_placed")
    balance_of("wallet:t7")   -> int (cents)
    trial_balance()           -> int (cents, must always be 0)

    from ledger.ledger import lock_funding_scopes          # P1-L7
    lock_funding_scopes(db, 7, 3)   -> [3, 7]  (ascending; held to db's commit)

P1-L7 note: a balance is an aggregate and cannot be locked. The serialization
mutex for a team-season funding scope is the EXISTENCE of that scope's `wallets`
row, taken FOR UPDATE by lock_funding_scopes() before the balance read that
precedes a posting. See that function for grain, ordering, and fail-closed rules.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Session, declarative_base

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import engine, SessionLocal

# ── B6 canonical issuance door ────────────────────────────────────────────────
#
# The ONE door under which an approved BAB Top-Off issues Credits. Defined here,
# beside the guard it modifies, and imported by the issuance module rather than
# re-spelled as a literal at the call site.
#
# FAILURE MODE IF THE LITERAL IS WRONG — loud, never silent. The exemption in
# _run_checks_and_write() activates on this EXACT string and nothing else. A
# mistyped or alternate door leaves bab_issuance:* fully guarded, so a valid
# issuance posted under the wrong literal is REFUSED with InsufficientFundsError
# (the issuance account starts at zero and the debit would take it negative).
# Importing the constant is therefore about not having to debug that refusal —
# it is not what makes the guard safe. Nothing is silently accepted either way.
#
# This door is limited to approved eligible BAB Top-Off issuance. It is NOT a
# generic mint, an opening-allocation door, a correction door, a refund door, or
# a waiver door. Its only legal posting shape is the two legs
#   ("bab_issuance:{league_id}:{season}", -T), ("wallet:{team_id}", +T).
APPROVED_BAB_TOPOFF_DOOR = "approved_bab_topoff"

# ── S5-P1 canonical season-opening issuance door ──────────────────────────────
#
# A SECOND door-bound exemption, over a SEPARATE account namespace. Owner
# ruling, S5-P1: the season-opening allocation advances Credits from
# `season_issuance:{league_id}:{season}`, never from `bab_issuance:*`.
#
# WHY A SEPARATE NAMESPACE RATHER THAN BROADENING THE TOP-OFF ONE. B6 fixed that
# exemption to ONE door and proved it BY NAME: assertion (e) of
# test_b6_group_a_ledger_pg.py enumerates "season_allocation" as a door that
# must NOT be exempt on bab_issuance:*, and asserts it raises, writes nothing and
# leaves the issuance balance untouched. Broadening the Top-Off exemption would
# have required deleting an accepted assertion. A distinct namespace leaves
# every one of those assertions true and unmodified — the paragraph above still
# holds verbatim, including "an opening-allocation door".
#
# The two sources stay independently derivable from posted ledger state, which
# is what lets S5-P2/P3's Current Settle count the two obligations separately:
#     season_issuance:{league_id}:{season}   season-opening advance
#     bab_issuance:{league_id}:{season}      approved Top-Off issuance
#
# THE EXEMPTION IS DOOR-BOUND, NOT PREFIX-BOUND — the same rule B6 established,
# and the reason there is no generic "any issuance-looking account" branch. Under
# any other door a season_issuance:* debit stays fully guarded and MUST fail.
# This door is limited to the season-opening allocation. It is NOT a generic
# mint, a Top-Off source, a correction door, a refund door, or a waiver door.
# Its only legal posting shape is the three legs
#   ("season_issuance:{league_id}:{season}", -B),
#   ("min_reserve:{team_id}", +M), ("reserve:{team_id}", +R)   with M + R == B.
SEASON_ALLOCATION_DOOR = "season_allocation"

#: (door, account prefix) pairs that may debit from a zero balance. Kept as an
#: explicit table so adding a third issuance source is a visible, reviewable
#: edit rather than a condition quietly appended to a chain of `or`s. A prefix
#: appearing here grants nothing on its own — the DOOR must match too.
_ISSUANCE_EXEMPTIONS: tuple[tuple[str, str], ...] = (
    (APPROVED_BAB_TOPOFF_DOOR, "bab_issuance:"),
    (SEASON_ALLOCATION_DOOR,   "season_issuance:"),
)


def _is_exempt_issuance(door: str, account: str) -> bool:
    """Whether this (door, account) pair is a governed issuance exemption.

    Both halves must match one row of the table. A `season_issuance:*` debit
    under the Top-Off door, or a `bab_issuance:*` debit under the allocation
    door, matches nothing and stays fully guarded — which is the property the
    discriminating tests assert in both directions."""
    return any(door == exempt_door and account.startswith(prefix)
               for exempt_door, prefix in _ISSUANCE_EXEMPTIONS)


# Separate declarative base from db.schema's — this table is defined here,
# in isolation, specifically so db/schema.py (an existing, shared file)
# never needs to be touched by this session. Base.metadata.create_all()
# below only ever creates/inspects THIS one table; it does not interact
# with db.schema.Base's own metadata or any of its tables at all.
_LedgerBase = declarative_base()


class LedgerEntry(_LedgerBase):
    """
    One row per side of one posting. No stored balance anywhere — an
    account's balance is always SUM(amount_cents) WHERE account = :account,
    computed on demand by balance_of()/trial_balance().
    """
    __tablename__ = "ledger_entries"

    # This table carried NO index of any kind before B6 — not even on
    # posting_id. Both reads below are on the approval hot path and both would
    # otherwise be sequential scans that grow with every posting the platform
    # ever makes, forever.
    #
    #   posting_id      provenance lookup: given a FaabTransaction's
    #                   ledger_posting_id, fetch that posting's legs. Deliberately
    #                   NON-UNIQUE — every leg of one posting shares the value.
    #   (door, account) cap-consumption read: sum governed issuance for one
    #                   wallet account under one door. Column order matters —
    #                   door is the low-cardinality discriminator and leads, so
    #                   the index also serves door-only scans.
    __table_args__ = (
        Index("ix_ledger_entries_posting_id",   "posting_id"),
        Index("ix_ledger_entries_door_account", "door", "account"),
        # SPEC 2 / Ruling 1 — the leg's link up to its balanced batch.
        Index("ix_ledger_entries_batch_id", "batch_id"),
    )

    # SQLite only grants ROWID autoincrement to a column that compiles as
    # exactly INTEGER; BigInteger compiles to BIGINT there and silently gets
    # no autoincrement. Postgres keeps the real bigint PK via the variant.
    id           = Column(Integer().with_variant(BigInteger, "postgresql"), primary_key=True, autoincrement=True)
    account      = Column(String, nullable=False)
    # Signed integer cents. Positive = credit, negative = debit. Integer
    # cents ONLY — no float representation of money anywhere in this file
    # or its callers.
    amount_cents = Column(BigInteger, nullable=False)
    # Groups every entry in one atomic posting together.
    posting_id   = Column(Uuid, nullable=False)
    # Audit trail — which door produced this entry.
    door         = Column(String, nullable=False)
    # SPEC 2 / Foundation Correction Plan Ruling 1 — this leg's LedgerPostingBatch.
    #
    # NULLABLE, AND THAT IS THE COMPATIBILITY CONTRACT: every posting made
    # without an explicit protocol event — which is every caller in the tree
    # today — leaves it NULL and behaves exactly as before. Only a caller that
    # supplies a governing event gets a batch.
    #
    # NO ForeignKey, deliberately. LedgerPostingBatch lives on db.schema's
    # declarative base and this table lives on _LedgerBase below; a FK across
    # two metadatas is not expressible here. Same reasoning B6 §4.7 recorded for
    # FaabTransaction.ledger_posting_id. The link is by value.
    #
    # IT CARRIES NO UNIQUENESS. Ruling 1 is explicit that idempotency authority
    # lives on ProtocolEvent.event_id and that LedgerEntry must not become a
    # second event home. Many legs share one batch — that is the whole point.
    batch_id     = Column(Integer, nullable=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class LedgerImbalanceError(ValueError):
    """Raised when a posting's entries do not sum to exactly zero. Nothing is written."""


class InsufficientFundsError(ValueError):
    """Raised when a posting would take a debited account's balance below zero.
    The whole posting is rejected — nothing partial is ever written."""


class AlreadySettledError(ValueError):
    """Raised when a wager_settled posting targets an escrow account whose
    balance is already 0 — that bet has already been settled once."""


class WalletMutexMissingError(ValueError):
    """P1-L7 — raised when the Wallet row serving as a funding scope's
    serialization mutex does not exist, so no row could be locked.

    FAIL-CLOSED, AND THAT IS THE WHOLE POINT. Wallet-row EXISTENCE is the mutex
    (see lock_funding_scopes below). A `SELECT … FOR UPDATE` matching zero rows
    is not an error in SQL — it succeeds and locks nothing. Were that allowed to
    pass, the caller would proceed to read a balance and post money believing it
    held a mutex it never acquired, and the serialization guarantee would vanish
    silently on exactly the scope that lacked a row. Refusing here converts an
    absent mutex from a silent hole into a loud refusal.

    Subclasses ValueError deliberately. beefs/beef_engine.issue_challenge already
    raises a plain ValueError for this same condition ("No wallet found for team
    N") and API routes map ValueError to a 4xx; a bare RuntimeError here would
    turn an already-handled condition into a 500. P1-L7 changes no user-visible
    behaviour except removing races, so the exception family is preserved.
    """


def create_ledger_table() -> None:
    """Create ledger_entries if it doesn't exist yet. Additive, safe to call
    repeatedly — does not touch or inspect any other table."""
    _LedgerBase.metadata.create_all(engine)


def _balance_of_in_session(db: Session, account: str) -> int:
    """Same query as balance_of(), but reusing an already-open session/
    transaction — used by post() so its funded-balance and once-only-
    settlement reads are part of the SAME transaction as the write below,
    not a separate earlier query that a concurrent posting could race past.

    EXPORTED entry point (FR-7.12): funds-check sites that read a balance
    immediately before a write in the SAME request transaction import this
    instead of balance_of() so the pre-check sees the same data the write
    will. The leading underscore is retained for continuity, but this is a
    supported cross-module import (see FR-7.12 §4). No caller precondition
    beyond ordinary autoflush, which is the codebase-wide default."""
    result = db.execute(
        text("SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries WHERE account = :account"),
        {"account": account},
    ).scalar()
    return int(result)


def balance_of(account: str) -> int:
    """
    Returns the current balance of `account` in integer cents.
    0 for an account with no entries yet — an unfunded wallet is a valid
    state (e.g. before Door 1 posts), not an error.
    """
    with SessionLocal() as db:
        return _balance_of_in_session(db, account)


def lock_funding_scopes(db: Session, *team_ids: int) -> list[int]:
    """P1-L7 — acquire the Wallet-row mutex for one or more team-season funding
    scopes, inside the CALLER's transaction, in ascending team_id order.

    THE MUTEX IS THE ROW'S EXISTENCE, NOT ITS VALUE (Foundation Correction Plan
    §4, OPR-5). Ledger balances are aggregates — SUM(amount_cents) over
    ledger_entries — and an aggregate is not a lockable object. There is nothing
    for `FOR UPDATE` to hold. So the funding scope borrows a lockable proxy: the
    one `wallets` row that scope owns. `Wallet.balance` is NOT consulted here and
    is NOT authoritative for anything (P1-L2/P1-L3B made it a display mirror);
    this function neither reads nor writes it. The row is used purely as a named
    object two transactions can contend for.

    GRAIN. `wallets.team_id` is UNIQUE NOT NULL, so there is at most one row per
    team. A Team belongs to exactly one League (`teams.league_id`) and a League
    carries exactly one `season`, so a team_id already encodes (team, season) —
    the row grain and the team-season funding scope coincide exactly. §4's
    requirement is "at least as coarse as the funding scope"; equal satisfies it,
    with no over-serialization to spend.

    EXISTENCE IS FAIL-CLOSED, NOT ASSUMED. `UNIQUE(team_id)` guarantees the "at
    most one" half structurally. The "at least one" half has no schema
    constraint — Wallet rows are created by the seed paths, and a Team with no
    Wallet is representable. A `SELECT … FOR UPDATE` matching no row locks
    nothing and raises nothing, which would let a caller believe it was
    serialized when it was not. Missing row therefore raises
    WalletMutexMissingError and the caller's transaction never reaches its
    balance read. That is the smallest correction that makes the mutex
    un-silenceable without a schema redesign; a structural existence constraint
    (deferred FK teams→wallets, or a trigger) is a migration and belongs to
    whichever package next reshapes these tables, not to a behavioural fix.

    LOCK ORDER — ASCENDING team_id, ALWAYS. team_ids are de-duplicated and
    sorted, so the acquisition order is a property of the SET of scopes, never of
    the caller's argument order, and never of a challenger/challenged or
    proposer/recipient role. Two transactions locking {7, 3} and {3, 7} both take
    3 then 7 and queue; they cannot hold one lock each and wait on the other.
    Passing the ids in "wrong" order is therefore not a bug a caller can commit —
    the primitive owns the ordering, which is why it is one shared function
    rather than duplicated `.with_for_update()` calls at each site.

    RANK RELATIVE TO OTHER LOCKS. Where a path also locks a BeefChallenge row
    (beefs/proposal_lifecycle._lock_challenge, and the future P1-L4 orchestrator
    per SPEC 2 §8), the challenge row is taken FIRST and wallets after. No
    current path takes a Wallet lock before a challenge lock, so no inversion
    exists to inherit; P1-L4 must preserve that rank.

    TRANSACTION-LOCAL BY CONSTRUCTION. The lock lives on `db`'s transaction and
    is released by that transaction's commit or rollback — there is no unlock
    call and this function never commits, flushes, or rolls back. The caller must
    therefore hold `db` open through the balance read AND the posting the lock
    protects; a caller that commits between them has released the mutex and is
    back to the unprotected read-then-post race this exists to close.

    `.with_for_update()` renders `FOR UPDATE` on Postgres and is a documented
    no-op on SQLite (its dialect emits no FOR UPDATE clause), which is why the
    ORM construct is used rather than raw SQL — the same reason every existing
    lock site in this tree uses it. Real row-lock behaviour is therefore only
    provable on Postgres, and the P1-L7 concurrency suite is Postgres-only.

    `populate_existing()` is load-bearing for the same reason recorded in
    proposal_lifecycle._lock_challenge: without it, a Wallet already in this
    session's identity map is returned from cache, and a read "under the lock"
    could be a snapshot taken before the lock was granted.

    Returns the ascending team_id list actually locked — the acquisition order,
    for callers and tests that need to assert it.
    """
    from db.schema import Wallet

    ordered = sorted({int(team_id) for team_id in team_ids})
    for team_id in ordered:
        row = (
            db.query(Wallet)
            .filter(Wallet.team_id == team_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if row is None:
            raise WalletMutexMissingError(
                f"No Wallet row exists for team {team_id}, so the funding-scope "
                f"mutex for wallet:{team_id} could not be acquired. Refusing to "
                f"read a balance or post money unserialized. Nothing was written."
            )
    return ordered


def _to_cents(amount: float) -> int:
    """Dollars (float) -> integer cents, for funds-check comparisons that must
    happen in the same integer-cents space as balance_of()/_balance_of_in_session().

    Single home (FR-7.12 §3): api/main.py imports this instead of defining its
    own copy. beefs/beef_engine.py keeps its own pre-existing _to_cents() (used
    by the out-of-scope wager_placed posting) — see FR-7.12 §7. Exported
    alongside balance_of()."""
    return round(amount * 100)


def _dollars_to_cents(dollars: float) -> int:
    """Exact dollars -> cents. Rejects (never rounds) an amount that isn't
    a whole number of cents — e.g. 10.005 is a bad request, not silently
    rounded to 1000 or 1001 cents.

    Promoted to the money-path's shared home (FR-7.50 §3) from its original
    single site in api/pool_routes.py. Callers: api/pool_routes.py (unchanged
    behavior), beefs/beef_engine.py's issue_challenge()/counter_challenge(),
    and betting/bet_engine.py's _place_bet() — each validating a stake at
    entry before its MIN_BET check. Dependency surface is stdlib Decimal only
    (FR-7.50 §3, q5), so the move is clean. Raises ValueError on a sub-cent
    stake; callers let it propagate (never catch/round/coerce)."""
    cents = Decimal(str(dollars)) * 100
    if cents != cents.to_integral_value():
        raise ValueError(
            f"{dollars} is not a whole number of cents — amounts must be "
            f"in exact dollars-and-cents (at most two decimal places)"
        )
    return int(cents)


def trial_balance() -> int:
    """
    Sum of amount_cents across every ledger entry, all accounts, all doors.
    Must always be exactly 0 — this is the continuous integrity check
    referenced throughout the L1 spec and the Launch Gate register.
    """
    with SessionLocal() as db:
        result = db.execute(
            text("SELECT COALESCE(SUM(amount_cents), 0) FROM ledger_entries")
        ).scalar()
        return int(result)


def _open_posting_batch(
    db: Session,
    posting_id: uuid.UUID,
    door: str,
    protocol_event_id: int,
) -> int:
    """SPEC 2 / Ruling 1 — create this posting's LedgerPostingBatch and return
    its id, so every leg written below can link to it.

    One ProtocolEvent may own several batches: Locked acceptance produces three
    balanced ones (true-up, Anchor migration, Derived funding) under a single
    challenge_accept event. So this creates a batch per post() call and never
    de-duplicates by event — de-duplication is the event's own job, one tier up.

    Imported here rather than at module import time only for symmetry with the
    rest of this file's local reads; db.schema is already a module-level import,
    so there is no cycle either way.
    """
    from db.schema import LedgerPostingBatch

    batch = LedgerPostingBatch(
        posting_id        = posting_id,
        protocol_event_id = protocol_event_id,
        door              = door,
    )
    db.add(batch)
    db.flush()          # flush, not commit — the caller still owns the transaction
    return batch.id


def _run_checks_and_write(
    db: Session,
    entries: list[tuple[str, int]],
    door: str,
    posting_id: uuid.UUID,
    now: datetime,
    batch_id: int | None = None,
) -> None:
    """
    Runs checks (b) and (c) and writes (d) — see post()'s docstring for the
    full check semantics and ordering rationale. Shared by both of post()'s
    paths (its own session, or a caller-supplied one) so the checks and the
    write behave identically either way; does not commit — the caller (post())
    decides who owns and commits the transaction.
    """
    # (c) MS-L1-5.2 — once-only settlement guard, wager_settled doors only.
    # Deliberately checked BEFORE (b) below, for wager_settled postings
    # only: an escrow account already at 0 will ALWAYS also fail (b)'s
    # generic funded-balance test (debiting anything from a zero balance
    # is negative by definition), so if (b) ran first a repeated
    # settlement attempt would surface as a generic InsufficientFundsError
    # and this more specific, more diagnostic AlreadySettledError would
    # never actually be reachable. Checking (c) first for this one door
    # gives the caller the correct, specific reason without weakening (b)
    # — every other debited account in this same posting, and every
    # other door, still goes through the unmodified check below.
    if door == "wager_settled":
        escrow_debits = [a for a, amt in entries if amt < 0 and a.startswith("escrow:")]
        for escrow_account in escrow_debits:
            current = _balance_of_in_session(db, escrow_account)
            if current == 0:
                raise AlreadySettledError(
                    f"{escrow_account!r} is already at 0 cents — this bet has "
                    f"already been settled. Posting rejected, nothing written."
                )

    # (b) MS-L1-5.1 — funded-balance guard, every door, every debited account,
    # except "world" and "receivable:*" — see docstring above for why these
    # two are exempt (unbounded external/IOU accounts, not real pools) — and
    # except "bab_issuance:*" UNDER THE CANONICAL TOP-OFF DOOR ONLY (B6).
    for account, amount in entries:
        if amount < 0 and account != "world" and not account.startswith("receivable:"):
            # B6 — DOOR-BOUND exemption. bab_issuance:{league_id}:{season} is a
            # league-season issuance account: it starts at zero and is debited
            # negative by exactly the Credits that league has put into
            # circulation this season, so its debit balance IS the tally. Under
            # the generic guard the very first top-off would raise
            # InsufficientFundsError.
            #
            # The door is half of the condition, not decoration. The account
            # prefix ALONE is deliberately insufficient: were the exemption
            # keyed on the prefix, any future caller could mint unbacked
            # Credits from bab_issuance:* through any door it liked. Under
            # every other door a bab_issuance:* debit stays fully guarded and
            # MUST fail — that is asserted directly by the Group A suite.
            #
            # "world" and "receivable:*" behaviour is untouched above, and the
            # ten other production post() call sites pass neither this door nor
            # this prefix, so none of them changes behaviour.
            # S5-P1 widened this from one hardcoded pair to the explicit
            # _ISSUANCE_EXEMPTIONS table. The RULE is unchanged and the Top-Off
            # behaviour is byte-identical: both halves must match, so a prefix
            # alone still grants nothing under any door.
            if _is_exempt_issuance(door, account):
                continue

            current = _balance_of_in_session(db, account)
            if current + amount < 0:
                raise InsufficientFundsError(
                    f"Posting for door {door!r} would take {account!r} to "
                    f"{current + amount} cents (current {current}, debit {amount}) "
                    f"— insufficient funds. Posting rejected, nothing written."
                )

    # (d) All checks passed — write every entry under the same posting_id,
    # in this one transaction. Commits together or not at all.
    for account, amount in entries:
        db.add(LedgerEntry(
            account=account,
            amount_cents=amount,
            posting_id=posting_id,
            door=door,
            batch_id=batch_id,       # None on every unlinked (legacy) posting
            created_at=now,
        ))


def post(
    entries: list[tuple[str, int]],
    door: str,
    session: Session | None = None,
    protocol_event_id: int | None = None,
) -> uuid.UUID:
    """
    Atomically write one posting — a balanced set of ledger entries sharing
    one new posting_id — after three checks, in order, all before any write:

      a. entries must sum to exactly zero (LedgerImbalanceError if not).
      b. MS-L1-5.1 — for every account being debited (negative amount_cents)
         in this posting, its balance after this posting must not go
         negative (InsufficientFundsError if it would). Applies to every
         door, not just wager placement — EXCEPT "world" and "receivable:*"
         accounts, which represent capital flowing into/out of the ledger
         from outside it (real bank/Stripe transactions, or IOUs owed by a
         team) and are not bounded pools. Door 1 (buy_in_paid) debits
         "world" from 0, and Door 2 (buy_in_tab) debits "receivable:{team}"
         from 0 — both go negative by design, not by error. Every other
         account (wallet:*, escrow:*, reserve:*, championship, skunk) is a
         real accumulated pool and stays fully guarded.

         B6 adds a THIRD exemption that is DOOR-BOUND rather than
         account-bound: "bab_issuance:*" is exempt only when door ==
         APPROVED_BAB_TOPOFF_DOOR. That account is a league-season issuance
         tally which starts at 0 and is debited negative by exactly the
         Credits issued. Under ANY other door a "bab_issuance:*" debit is
         fully guarded and raises InsufficientFundsError exactly as before.
         Unlike "world" and "receivable:*", the prefix alone grants nothing.
      c. MS-L1-5.2 — if door == "wager_settled", every escrow:* account
         being debited must have a nonzero CURRENT balance before this
         posting applies (AlreadySettledError if it's already 0 — this
         bet has already been settled).

    Implementation note: for door == "wager_settled" specifically, (c) is
    evaluated before (b) in code — an escrow account already at 0 always
    also fails (b)'s generic test, so checking (b) first would make (c)
    unreachable and a repeated settlement would surface as a generic
    InsufficientFundsError instead of the more specific AlreadySettledError.
    Every other debited account, and every other door, is unaffected.

    session=None (default): post() opens its own SessionLocal(), runs all
    checks and the write against it, and commits internally before
    returning — this is the original L2 behavior, unchanged.

    session=<a Session>: post() runs the exact same checks (same ordering,
    same exemptions) and the same write against the CALLER's session
    instead of opening its own, and does NOT call commit() — the caller
    owns and commits (or rolls back) that transaction. This lets a caller
    like beefs/beef_engine.py's respond_to_challenge() — which commits
    once, covering both sides of an accepted beef plus a challenge status
    flip, as one atomic unit — post through the ledger as part of that
    same atomic unit instead of the ledger silently committing early on
    its own and breaking that atomicity. Because it's the same session,
    the funded-balance and once-only-settlement reads also see any of the
    caller's own uncommitted writes earlier in that same transaction.

    Either way, (b) and (c) read balances inside the same transaction as
    the write (not as separate earlier queries), and — on Postgres, and
    only on the session=None path where post() opens its own connection —
    that transaction runs at REPEATABLE READ, so a concurrent posting
    against the same account can't land between the check and the commit
    and produce a stale read (same pattern already used in
    beefs/beef_engine.py's respond_to_challenge()). On the session=provided
    path, isolation level is the caller's responsibility — the caller
    already owns the transaction and may already have set its own
    isolation level before ever calling post().

    Returns the new posting_id either way — on the session=None path only
    after a successful commit; on the session=provided path, once the
    entries are written to that session (still uncommitted).

    protocol_event_id (SPEC 2 / Foundation Correction Plan Ruling 1): OPTIONAL
    AND TRAILING. Omitted — which is every caller in the tree today — this
    function behaves exactly as it always has: no batch row is created, and
    every LedgerEntry carries batch_id NULL. Supplied, it names the already-
    persisted ProtocolEvent governing this posting; a LedgerPostingBatch is
    created for this posting_id and every leg links to it.

    SAFE BY INVENTORY, NOT BY ASSERTION. A complete AST inventory of all 94
    call sites at HEAD (11 production, 83 test) found a maximum of ONE
    positional argument anywhere — `entries` — with `door` and `session` always
    passed by keyword. No caller can bind this new fourth parameter positionally,
    so no existing call changes meaning. Re-run that inventory before any future
    signature change (Foundation Correction Plan, OPR-2).

    THIS FUNCTION NEVER CREATES A ProtocolEvent. Ruling 1 makes the event the
    idempotency authority, and minting one as a side effect of an ordinary
    posting would hand out identities nobody asked for and defeat the
    de-duplication it exists to provide. The caller creates the event; this
    records the posting against it.

    A protocol_event_id REQUIRES session. On the session=None path post() opens
    its own connection and commits internally, so the event row would live in a
    different transaction from the batch that references it — the FK could fail,
    or worse, succeed against a row that later rolled back. Refused outright
    rather than papered over; every money path in this codebase passes
    session=db already.
    """
    total = sum(amount for _, amount in entries)
    if total != 0:
        raise LedgerImbalanceError(
            f"Posting for door {door!r} does not balance: entries sum to "
            f"{total} cents, not zero. Entries: {entries}"
        )

    if protocol_event_id is not None and session is None:
        raise ValueError(
            "post(protocol_event_id=...) requires an explicit session: the "
            "batch that references the event must be written inside the same "
            "transaction as the event itself. Pass session=db."
        )

    posting_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    if session is not None:
        batch_id = (
            _open_posting_batch(session, posting_id, door, protocol_event_id)
            if protocol_event_id is not None else None
        )
        _run_checks_and_write(session, entries, door, posting_id, now, batch_id)
        return posting_id

    with SessionLocal() as db:
        # Elevated isolation for Postgres only — see docstring above.
        # Only applies here, where post() opens its own connection.
        if db.get_bind().dialect.name != "sqlite":
            db.connection(execution_options={"isolation_level": "REPEATABLE READ"})

        _run_checks_and_write(db, entries, door, posting_id, now)
        db.commit()

    return posting_id
