"""
test_fr87_prelock_validation_sqlite.py — FR-8.7 Test 6c.

SQLite pre-lock validation of settle_week()'s Phase-1 conflict path.

settle_week() claims a (league_id, week) via INSERT ... ON CONFLICT DO NOTHING
RETURNING id, commits, and — on the conflict (losing) path — reads the existing
row's status and recovery_token to decide whether to proceed. Four of those
decisions terminate BEFORE the Phase-2 SELECT ... FOR UPDATE at line 435, so they
are reachable on SQLite, which cannot parse FOR UPDATE.

Four scenarios, one per pre-lock outcome that terminates before the lock:

  6c-1  COMPLETED              -> idempotent SettlementReport(already_settled=True)
  6c-2  CLAIMED, token NULL    -> ValueError (fail closed: no recovery_token)
  6c-4  CLAIMED, token wrong   -> ValueError (fail closed: token mismatch)
  6c-5  status='<unknown>'     -> ValueError (fail closed: unexpected status)

Out of scope (Test 6d, PostgreSQL): guard 1's fresh-claim path, guard 4b's
matching-token recovery fall-through, and anything at or past line 435 — all of
which reach or require the FOR UPDATE lock.

Each fail-closed assertion checks BOTH the ValueError type AND a distinguishing
substring of the message, so a test proves its own guard fired and not a
neighbouring one. Substrings avoid the em-dash (U+2014) in the source messages to
stay robust against character-encoding drift.

Uses a temp SQLite DB so prod is never touched. DATABASE_URL is set before any
project import so every engine and session binds to the temp DB at import time.
Requires SQLite >= 3.35 for ON CONFLICT-target upsert + RETURNING (verified 3.50.4).
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_fr87_prelock_validation.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone

from db.schema import Base, engine, SessionLocal, League, WeekSettlement
from betting.settlement_engine import settle_week, SettlementReport

# ── Assertion harness (matches test_beef_settlement_escrow_close_pg.py) ───────
_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        msg = f"  FAIL  {label}" + (f" — {detail}" if detail else "")
        print(msg)
        _failures.append(label)


# ── Constants ────────────────────────────────────────────────────────────────
_LEAGUE_ID = 1
_WEEK = 14


def _prepare_schema() -> None:
    """Create all tables once, and seed the single League row the FK needs."""
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(League).filter_by(id=_LEAGUE_ID).first() is None:
            # Minimal League row so week_settlements.league_id FK resolves.
            db.add(League(id=_LEAGUE_ID, season=2026, name="Test League"))
            db.commit()


def _reset_week_settlements() -> None:
    """Delete every week_settlements row so each scenario starts clean.

    The SQLite harness has no TRUNCATE ... RESTART IDENTITY; a plain delete is
    sufficient here because the tests key off (league_id, week), not off id.
    """
    with SessionLocal() as db:
        db.query(WeekSettlement).delete()
        db.commit()


def _seed_row(status: str, recovery_token: str | None) -> None:
    """Insert one week_settlements row in the target lifecycle state."""
    with SessionLocal() as db:
        db.add(
            WeekSettlement(
                league_id=_LEAGUE_ID,
                week=_WEEK,
                settled=(status == "COMPLETED"),
                settled_at=datetime.now(timezone.utc) if status == "COMPLETED" else None,
                status=status,
                recovery_token=recovery_token,
            )
        )
        db.commit()


# ── 6c-1 — COMPLETED -> idempotent no-op, no raise ───────────────────────────
def scenario_completed_is_idempotent() -> None:
    print("6c-1: COMPLETED row -> idempotent already_settled report, no raise")
    _reset_week_settlements()
    _seed_row(status="COMPLETED", recovery_token=None)

    raised = None
    report = None
    with SessionLocal() as db:
        try:
            report = settle_week(_WEEK, db, league_id=_LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001 — a raise here is itself the failure
            raised = exc

    _assert(
        "6c-1a: no exception raised on COMPLETED",
        raised is None,
        detail=f"raised {type(raised).__name__}: {raised}" if raised else "",
    )
    _assert(
        "6c-1b: returns a SettlementReport",
        isinstance(report, SettlementReport),
        detail=f"got {type(report).__name__}",
    )
    _assert(
        "6c-1c: already_settled is True",
        isinstance(report, SettlementReport) and report.already_settled is True,
        detail=f"already_settled={getattr(report, 'already_settled', '<none>')}",
    )
    _assert(
        "6c-1d: no bets or payouts implied (counts and money zeroed)",
        isinstance(report, SettlementReport)
        and report.total_bets == 0
        and report.total_payout == 0.0,
        detail=(
            f"total_bets={getattr(report, 'total_bets', '?')} "
            f"total_payout={getattr(report, 'total_payout', '?')}"
        ),
    )


# ── 6c-2 — CLAIMED, no recovery_token -> ValueError (fail closed) ────────────
def scenario_claimed_no_token_fails_closed() -> None:
    print("6c-2: CLAIMED row, recovery_token NULL, none supplied -> ValueError")
    _reset_week_settlements()
    _seed_row(status="CLAIMED", recovery_token=None)

    raised = None
    with SessionLocal() as db:
        try:
            settle_week(_WEEK, db, league_id=_LEAGUE_ID)  # recovery_token defaults None
        except Exception as exc:  # noqa: BLE001
            raised = exc

    _assert(
        "6c-2a: raises ValueError",
        isinstance(raised, ValueError),
        detail=f"raised {type(raised).__name__ if raised else '<nothing>'}",
    )
    _assert(
        "6c-2b: message identifies the no-recovery_token guard",
        isinstance(raised, ValueError)
        and "no recovery_token was supplied" in str(raised),
        detail=f"message: {raised}",
    )


# ── 6c-4 — CLAIMED, mismatched token -> ValueError (fail closed) ─────────────
def scenario_claimed_wrong_token_fails_closed() -> None:
    print("6c-4: CLAIMED row, token set, mismatched token supplied -> ValueError")
    _reset_week_settlements()
    _seed_row(status="CLAIMED", recovery_token="the-real-token")

    raised = None
    with SessionLocal() as db:
        try:
            settle_week(_WEEK, db, league_id=_LEAGUE_ID, recovery_token="a-wrong-token")
        except Exception as exc:  # noqa: BLE001
            raised = exc

    _assert(
        "6c-4a: raises ValueError",
        isinstance(raised, ValueError),
        detail=f"raised {type(raised).__name__ if raised else '<nothing>'}",
    )
    _assert(
        "6c-4b: message identifies the token-mismatch guard",
        isinstance(raised, ValueError)
        and "does not match the row's token" in str(raised),
        detail=f"message: {raised}",
    )


# ── 6c-5 — unknown status -> ValueError (fail closed) ────────────────────────
def scenario_unknown_status_fails_closed() -> None:
    print("6c-5: row with unexpected status -> ValueError (fail-closed)")
    _reset_week_settlements()
    # A non-NULL, non-lifecycle string. Must be a string, not NULL: the source
    # renders it via {existing_status!r}, and a NULL would instead route through
    # the CLAIMED/COMPLETED branches' NULL handling rather than this guard.
    _seed_row(status="BANANA", recovery_token=None)

    raised = None
    with SessionLocal() as db:
        try:
            settle_week(_WEEK, db, league_id=_LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001
            raised = exc

    _assert(
        "6c-5a: raises ValueError",
        isinstance(raised, ValueError),
        detail=f"raised {type(raised).__name__ if raised else '<nothing>'}",
    )
    _assert(
        "6c-5b: message identifies the fail-closed unexpected-status guard",
        isinstance(raised, ValueError)
        and "has unexpected status=" in str(raised)
        and "refusing to settle (fail-closed)" in str(raised),
        detail=f"message: {raised}",
    )
    _assert(
        "6c-5c: message reflects the offending status value",
        isinstance(raised, ValueError) and "'BANANA'" in str(raised),
        detail=f"message: {raised}",
    )


def main() -> None:
    try:
        _prepare_schema()
    except Exception as exc:  # noqa: BLE001 — schema/harness failure, not an assertion failure
        print(f"HARNESS ERROR during schema preparation: {type(exc).__name__}: {exc}")
        sys.exit(2)

    scenario_completed_is_idempotent()
    scenario_claimed_no_token_fails_closed()
    scenario_claimed_wrong_token_fails_closed()
    scenario_unknown_status_fails_closed()

    print()
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for label in _failures:
            print(f"  - {label}")
        sys.exit(1)
    print("RESULT: all pre-lock validation assertions PASSED")


if __name__ == "__main__":
    main()
