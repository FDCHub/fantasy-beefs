"""
test_ledger.py — Unit tests for ledger/ledger.py (Session L2 build).

One test per door from the certified L1 spec, plus the guard-specific
tests (funded-balance, once-only-settlement, imbalance rejection, and
Door 4's N=0/N=1 edge cases). Every door test asserts trial_balance() == 0
immediately after posting.

Uses a temp SQLite DB so prod is never touched. DATABASE_URL is set before
any project imports to guarantee all engines and sessions point at the
temp DB — same pattern as test_beef_starters.py.
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_ledger.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ledger.ledger import (
    post,
    balance_of,
    trial_balance,
    create_ledger_table,
    LedgerEntry,
    LedgerImbalanceError,
    InsufficientFundsError,
    AlreadySettledError,
)
from db.schema import SessionLocal

# ── Helpers (same style as test_beef_starters.py) ─────────────────────────────

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── DB bootstrap ──────────────────────────────────────────────────────────────

create_ledger_table()


# ── Door 1: buy-in paid — debit world, credit wallet + reserve ────────────────

print("\nDoor 1: buy-in paid — debit world, credit wallet + reserve")
post([("world", -100_00), ("wallet:t1", 60_00), ("reserve:t1", 40_00)], door="buy_in_paid")
_assert("wallet:t1 credited $60.00",   balance_of("wallet:t1") == 60_00,  f"got {balance_of('wallet:t1')}")
_assert("reserve:t1 credited $40.00",  balance_of("reserve:t1") == 40_00, f"got {balance_of('reserve:t1')}")
_assert("world debited $100.00",       balance_of("world") == -100_00,   f"got {balance_of('world')}")
_assert("trial_balance is 0 after Door 1", trial_balance() == 0, f"got {trial_balance()}")


# ── Door 2: buy-in tab — debit receivable, credit wallet + reserve, ───────────
# then a second posting clears the receivable.

print("\nDoor 2: buy-in tab — debit receivable, credit wallet + reserve, then clear it")
post([("receivable:t2", -100_00), ("wallet:t2", 60_00), ("reserve:t2", 40_00)], door="buy_in_tab")
_assert("wallet:t2 credited $60.00 (on tab)",  balance_of("wallet:t2") == 60_00,  f"got {balance_of('wallet:t2')}")
_assert("reserve:t2 credited $40.00 (on tab)", balance_of("reserve:t2") == 40_00, f"got {balance_of('reserve:t2')}")
_assert("receivable:t2 shows the $100.00 owed", balance_of("receivable:t2") == -100_00, f"got {balance_of('receivable:t2')}")
_assert("trial_balance is 0 after Door 2 (tab)", trial_balance() == 0, f"got {trial_balance()}")

post([("world", -100_00), ("receivable:t2", 100_00)], door="receivable_clear")
_assert("receivable:t2 cleared to 0",           balance_of("receivable:t2") == 0, f"got {balance_of('receivable:t2')}")
_assert("trial_balance is 0 after receivable_clear", trial_balance() == 0, f"got {trial_balance()}")


# ── Door 3: wager placed — debit wallet, credit escrow ────────────────────────

print("\nDoor 3: wager placed — debit wallet, credit escrow")
post([("world", -500_00), ("wallet:t3", 500_00)], door="buy_in_paid")  # fund t3 first
post([("wallet:t3", -100_00), ("escrow:100", 100_00)], door="wager_placed")
_assert("wallet:t3 debited $100.00",  balance_of("wallet:t3") == 400_00, f"got {balance_of('wallet:t3')}")
_assert("escrow:100 credited $100.00", balance_of("escrow:100") == 100_00, f"got {balance_of('escrow:100')}")
_assert("trial_balance is 0 after Door 3", trial_balance() == 0, f"got {trial_balance()}")


# ── Door 4: wager settled — odd split, $100 / 3 winners (floor + remainder) ───

print("\nDoor 4: wager settled — $100 pot / 3 winners, proves floor+remainder math")
post([("world", -100_00), ("wallet:tmp4", 100_00)], door="buy_in_paid")
post([("wallet:tmp4", -100_00), ("escrow:200", 100_00)], door="wager_placed")

pot = 100_00
n_winners = 3
share = pot // n_winners       # 3333
remainder = pot - share * n_winners  # 1
post(
    [
        ("escrow:200", -pot),
        ("wallet:tA", share),
        ("wallet:tB", share),
        ("wallet:tC", share),
        ("championship", remainder),
    ],
    door="wager_settled",
)
_assert("escrow:200 drained to 0",          balance_of("escrow:200") == 0, f"got {balance_of('escrow:200')}")
_assert("each winner got the floored share", balance_of("wallet:tA") == 3333 and balance_of("wallet:tB") == 3333 and balance_of("wallet:tC") == 3333)
_assert("championship absorbed the 1-cent remainder", balance_of("championship") == 1, f"got {balance_of('championship')}")
_assert("trial_balance is 0 after Door 4 (odd split)", trial_balance() == 0, f"got {trial_balance()}")


# ── Door 5: shortfall sweep — debit wallet, credit championship ───────────────

print("\nDoor 5: shortfall sweep — debit wallet, credit championship")
post([("world", -200_00), ("wallet:t5", 200_00)], door="buy_in_paid")
championship_before = balance_of("championship")
post([("wallet:t5", -50_00), ("championship", 50_00)], door="shortfall_sweep")
_assert("wallet:t5 debited $50.00",  balance_of("wallet:t5") == 150_00, f"got {balance_of('wallet:t5')}")
_assert("championship credited $50.00", balance_of("championship") == championship_before + 50_00)
_assert("trial_balance is 0 after Door 5", trial_balance() == 0, f"got {trial_balance()}")


# ── Door 6: fine/skunk — debit world, credit skunk ────────────────────────────

print("\nDoor 6: fine/skunk — debit world, credit skunk")
post([("world", -10_00), ("skunk", 10_00)], door="fine")
_assert("skunk credited $10.00", balance_of("skunk") == 10_00, f"got {balance_of('skunk')}")
_assert("trial_balance is 0 after Door 6", trial_balance() == 0, f"got {trial_balance()}")


# ── Door 7: championship payout — debit championship, credit world ───────────

print("\nDoor 7: championship payout — debit championship, credit world")
championship_before = balance_of("championship")
world_before = balance_of("world")
post([("championship", -championship_before), ("world", championship_before)], door="championship_payout")
_assert("championship drained to 0", balance_of("championship") == 0, f"got {balance_of('championship')}")
_assert("world credited the payout", balance_of("world") == world_before + championship_before)
_assert("trial_balance is 0 after Door 7", trial_balance() == 0, f"got {trial_balance()}")


# ── MS-L1-5.1: funded-balance guard ───────────────────────────────────────────

print("\nMS-L1-5.1: funded-balance guard — debit below current balance must reject")
post([("world", -10_00), ("wallet:t_guard1", 10_00)], door="buy_in_paid")
tb_before = trial_balance()
raised = False
try:
    post([("wallet:t_guard1", -20_00), ("escrow:999", 20_00)], door="wager_placed")
except InsufficientFundsError:
    raised = True
_assert("InsufficientFundsError raised for over-debit", raised)
_assert("trial_balance unchanged after the rejected posting", trial_balance() == tb_before, f"before={tb_before} after={trial_balance()}")
_assert("wallet:t_guard1 balance unchanged", balance_of("wallet:t_guard1") == 10_00, f"got {balance_of('wallet:t_guard1')}")


# ── MS-L1-5.2: once-only settlement guard ─────────────────────────────────────

print("\nMS-L1-5.2: once-only settlement guard — repeat settlement must reject")
post([("world", -10_00), ("wallet:t_guard2", 10_00)], door="buy_in_paid")
post([("wallet:t_guard2", -10_00), ("escrow:300", 10_00)], door="wager_placed")
settlement_entries = [("escrow:300", -10_00), ("wallet:t_guard2b", 10_00)]
post(settlement_entries, door="wager_settled")
_assert("first settlement succeeds, escrow:300 drained", balance_of("escrow:300") == 0, f"got {balance_of('escrow:300')}")

tb_before_repeat = trial_balance()
raised = False
try:
    post(settlement_entries, door="wager_settled")
except AlreadySettledError:
    raised = True
_assert("AlreadySettledError raised on repeat settlement", raised)
_assert("trial_balance unchanged after the rejected repeat", trial_balance() == tb_before_repeat, f"before={tb_before_repeat} after={trial_balance()}")


# ── Deliberate imbalance ───────────────────────────────────────────────────────

print("\nDeliberate imbalance: entries that do not sum to zero must reject")
tb_before_imbalance = trial_balance()
raised = False
try:
    post([("world", -10_00), ("wallet:t_imbalance", 5_00)], door="buy_in_paid")  # off by $5
except LedgerImbalanceError:
    raised = True
_assert("LedgerImbalanceError raised for non-zero-sum entries", raised)
_assert("trial_balance unchanged after the rejected imbalance", trial_balance() == tb_before_imbalance, f"before={tb_before_imbalance} after={trial_balance()}")
_assert("wallet:t_imbalance was never created", balance_of("wallet:t_imbalance") == 0)


# ── Door 4, N=0: zero winners, entire pot sweeps to championship ─────────────

print("\nDoor 4, N=0: zero winners — entire pot sweeps to championship, no winner lines")
post([("world", -75_00), ("wallet:tmp4b", 75_00)], door="buy_in_paid")
post([("wallet:tmp4b", -75_00), ("escrow:201", 75_00)], door="wager_placed")
championship_before_n0 = balance_of("championship")
post([("escrow:201", -75_00), ("championship", 75_00)], door="wager_settled")
_assert("escrow:201 drained to 0", balance_of("escrow:201") == 0, f"got {balance_of('escrow:201')}")
_assert("championship absorbed the full pot (N=0)", balance_of("championship") == championship_before_n0 + 75_00)
_assert("trial_balance is 0 after Door 4 (N=0)", trial_balance() == 0, f"got {trial_balance()}")


# ── Door 4, N=1: one winner takes the full pot, no remainder line ────────────

print("\nDoor 4, N=1: one winner — full pot, no zero-value championship row")
post([("world", -80_00), ("wallet:tmp4c", 80_00)], door="buy_in_paid")
post([("wallet:tmp4c", -80_00), ("escrow:202", 80_00)], door="wager_placed")
posting_id_n1 = post([("escrow:202", -80_00), ("wallet:tSolo", 80_00)], door="wager_settled")
_assert("escrow:202 drained to 0", balance_of("escrow:202") == 0, f"got {balance_of('escrow:202')}")
_assert("sole winner got the full $80.00", balance_of("wallet:tSolo") == 80_00, f"got {balance_of('wallet:tSolo')}")
_assert("trial_balance is 0 after Door 4 (N=1)", trial_balance() == 0, f"got {trial_balance()}")

with SessionLocal() as _db:
    n1_rows = _db.query(LedgerEntry).filter(LedgerEntry.posting_id == posting_id_n1).all()
    zero_rows = [r for r in n1_rows if r.amount_cents == 0]
_assert("exactly 2 rows written for the N=1 posting (no remainder row)", len(n1_rows) == 2, f"got {len(n1_rows)}")
_assert("no zero-amount row exists in the N=1 posting", len(zero_rows) == 0, f"got {len(zero_rows)}")


# ── session-provided path: caller owns the transaction ────────────────────────

print("\nSession-provided path: post() writes into the caller's session, caller commits")
tb_before_session_commit = trial_balance()
with SessionLocal() as _caller_db:
    posting_id_session = post(
        [("world", -30_00), ("wallet:t_session1", 30_00)],
        door="buy_in_paid",
        session=_caller_db,
    )
    _caller_db.commit()
_assert("posting_id returned on session-provided path", posting_id_session is not None)
_assert("wallet:t_session1 credited after caller's own commit", balance_of("wallet:t_session1") == 30_00, f"got {balance_of('wallet:t_session1')}")
_assert("trial_balance reflects it after caller's own commit", trial_balance() == tb_before_session_commit, f"before={tb_before_session_commit} after={trial_balance()}")

print("\nSession-provided path: post() must NOT commit internally — rollback proves it")
tb_before_rollback_test = trial_balance()
with SessionLocal() as _caller_db2:
    post(
        [("world", -40_00), ("wallet:t_session2", 40_00)],
        door="buy_in_paid",
        session=_caller_db2,
    )
    _caller_db2.rollback()
_assert("wallet:t_session2 balance is 0 after caller rolled back (never committed)", balance_of("wallet:t_session2") == 0, f"got {balance_of('wallet:t_session2')}")
_assert("trial_balance unchanged after the rolled-back posting", trial_balance() == tb_before_rollback_test, f"before={tb_before_rollback_test} after={trial_balance()}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
