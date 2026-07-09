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
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Uuid, text
from sqlalchemy.orm import Session, declarative_base

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import engine, SessionLocal

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
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class LedgerImbalanceError(ValueError):
    """Raised when a posting's entries do not sum to exactly zero. Nothing is written."""


class InsufficientFundsError(ValueError):
    """Raised when a posting would take a debited account's balance below zero.
    The whole posting is rejected — nothing partial is ever written."""


class AlreadySettledError(ValueError):
    """Raised when a wager_settled posting targets an escrow account whose
    balance is already 0 — that bet has already been settled once."""


def create_ledger_table() -> None:
    """Create ledger_entries if it doesn't exist yet. Additive, safe to call
    repeatedly — does not touch or inspect any other table."""
    _LedgerBase.metadata.create_all(engine)


def _balance_of_in_session(db: Session, account: str) -> int:
    """Same query as balance_of(), but reusing an already-open session/
    transaction — used by post() so its funded-balance and once-only-
    settlement reads are part of the SAME transaction as the write below,
    not a separate earlier query that a concurrent posting could race past."""
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


def _run_checks_and_write(
    db: Session,
    entries: list[tuple[str, int]],
    door: str,
    posting_id: uuid.UUID,
    now: datetime,
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
    # two are exempt (unbounded external/IOU accounts, not real pools).
    for account, amount in entries:
        if amount < 0 and account != "world" and not account.startswith("receivable:"):
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
            created_at=now,
        ))


def post(
    entries: list[tuple[str, int]],
    door: str,
    session: Session | None = None,
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
    """
    total = sum(amount for _, amount in entries)
    if total != 0:
        raise LedgerImbalanceError(
            f"Posting for door {door!r} does not balance: entries sum to "
            f"{total} cents, not zero. Entries: {entries}"
        )

    posting_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    if session is not None:
        _run_checks_and_write(session, entries, door, posting_id, now)
        return posting_id

    with SessionLocal() as db:
        # Elevated isolation for Postgres only — see docstring above.
        # Only applies here, where post() opens its own connection.
        if db.get_bind().dialect.name != "sqlite":
            db.connection(execution_options={"isolation_level": "REPEATABLE READ"})

        _run_checks_and_write(db, entries, door, posting_id, now)
        db.commit()

    return posting_id
