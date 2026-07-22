"""P1-L2 RED — confirm_topup owns the sole commit (sole-commit). Fails against 77fd23c.
Target (hardened): deposit() does NOT commit; confirm_topup's commit is the ONLY one on
the passed session, persisting wallet credit + deposit audit row + pending->applied together.
Current defect: deposit() self-commits at :148 AND confirm_topup commits at :558 -> 2 commits.

Direct commit-count spy on the passed session (both functions commit the same session).
No fault injection, no cross-session probe, no import-alias patching."""
import os, sys, tempfile
from unittest import mock

os.environ.pop("STRIPE_SECRET_KEY", None)
_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'p1l2_solecommit.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import (Base, engine, SessionLocal, League, Team, Wallet,
                       FaabWallet, FaabTransaction, Transaction)
from wallet.faab_wallet import confirm_topup, _log_tx

Base.metadata.create_all(engine)
_failures: list[str] = []

def _assert(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not condition: _failures.append(label)

def _make_pending():
    """Team + wallets + a pending topup_bet FaabTransaction (as real-mode create would leave it)."""
    with SessionLocal() as db:
        lg = League(season=2025, name="P1L2 sole", projection_source="fantasypros")
        db.add(lg); db.flush()
        t = Team(league_id=lg.id, team_name="P1L2 sole", owner="R1", email="r1@p1l2.com")
        db.add(t); db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(FaabWallet(team_id=t.id, league_id=lg.id, waiver_balance=0.0))
        tx = _log_tx(db, lg.id, t.id, "topup_bet", 25.00,
                     wallet_from="stripe", wallet_to="bet", status="pending",
                     note="pending for sole-commit test")
        db.commit()
        return t.id, tx.id

print("=" * 52); print("P1-L2 RED — confirm_topup sole-commit boundary"); print("=" * 52)

tid, tx_id = _make_pending()

# Spy on THIS session's commit only, during confirm_topup. Both deposit() and
# confirm_topup() call commit() on this same passed session, so the count is the
# ownership contract: 2 today (deposit self-commits + confirm commits), 1 once hardened.
with SessionLocal() as db:
    with mock.patch.object(db, "commit", wraps=db.commit) as commit_spy:
        result = confirm_topup(tx_id, db)
    commit_count = commit_spy.call_count

_assert("confirm_topup owns exactly one commit boundary",
        commit_count == 1,
        f"commit count={commit_count}; expected 1 "
        f"(current deposit() commits internally at :148 and confirm_topup commits again at :558)")

# Final-state assertions: after confirm_topup, all three are persisted together.
with SessionLocal() as db:
    w = db.query(Wallet).join(Team, Wallet.team_id == Team.id).filter(Team.id == tid).first()
    faab = db.query(FaabTransaction).filter(FaabTransaction.id == tx_id).first()
    wallet_tx = db.query(Transaction).filter(Transaction.wallet_id == w.id).count()

_assert("after confirm_topup, wallet credit is persisted",
        w.balance == 25.00,
        f"Wallet.balance={w.balance}; expected 25.00")
_assert("after confirm_topup, exactly one deposit audit row is persisted",
        wallet_tx == 1,
        f"wallet Transaction count={wallet_tx}; expected 1")
_assert("after confirm_topup, Top-Off row is 'applied'",
        faab.status == "applied",
        f"FaabTransaction.status={faab.status!r}; expected 'applied'")
_assert("after confirm_topup, applied_at is populated",
        faab.applied_at is not None,
        f"applied_at={faab.applied_at!r}; expected a timestamp")

print("\n" + "=" * 52)
if _failures:
    print(f"RED PHASE OK — {len(_failures)} target assertion(s) FAILED (expected)")
    for f in _failures: print(f"  - {f}")
    sys.exit(1)
else:
    print("All PASSED — NOT red. Investigate.")