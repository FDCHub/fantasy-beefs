"""P1-L2 RED — mock create_bet_topup issues no BAB (mock-no-credit). Fails against 77fd23c.
Target (hardened mock): mock creates ONE pending FaabTransaction, credits nothing.
Current defect: mock branch calls wm_deposit, credits the wallet, marks 'applied'."""
import os, sys, tempfile

# Force MOCK_MODE: STRIPE_SECRET_KEY must be unset BEFORE importing wallet.faab_wallet.
os.environ.pop("STRIPE_SECRET_KEY", None)
_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'p1l2_mock.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import (Base, engine, SessionLocal, League, Team, Wallet,
                       FaabWallet, Transaction, FaabTransaction)
from wallet.faab_wallet import create_bet_topup, MOCK_MODE

Base.metadata.create_all(engine)
_failures: list[str] = []

def _assert(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not condition: _failures.append(label)

def _make():
    with SessionLocal() as db:
        lg = League(season=2025, name="P1L2 mock", projection_source="fantasypros")
        db.add(lg); db.flush()
        t = Team(league_id=lg.id, team_name="P1L2 mock", owner="R1", email="r1@p1l2.com")
        db.add(t); db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        db.add(FaabWallet(team_id=t.id, league_id=lg.id, waiver_balance=0.0))
        db.commit()
        return t.id

def _state(tid):
    with SessionLocal() as db:
        w = db.query(Wallet).filter(Wallet.team_id == tid).first()
        wallet_tx = db.query(Transaction).filter(Transaction.wallet_id == w.id).count()
        faab_rows = db.query(FaabTransaction).filter(FaabTransaction.team_id == tid).all()
        return w.balance, wallet_tx, faab_rows

print("=" * 52); print("P1-L2 RED — mock create_bet_topup no-credit"); print("=" * 52)

_assert("SETUP: MOCK_MODE is active for this test",
        MOCK_MODE is True,
        f"MOCK_MODE={MOCK_MODE}; expected True (STRIPE_SECRET_KEY unset at import)")

tid = _make()
bal_b, wtx_b, faab_b = _state(tid)

with SessionLocal() as db:
    result = create_bet_topup(tid, 25.00, db)   # mock branch

bal_a, wtx_a, faab_a = _state(tid)

_assert("MOCK: create_bet_topup does not mutate Wallet.balance (no BAB issued)",
        bal_a == bal_b,
        f"Wallet.balance before={bal_b}, after={bal_a}; expected unchanged "
        f"(current mock branch calls wm_deposit at faab_wallet.py:420)")
_assert("MOCK: create_bet_topup writes no wallet Transaction row",
        wtx_a == wtx_b,
        f"wallet Transaction count before={wtx_b}, after={wtx_a}; expected unchanged")
_assert("MOCK: create_bet_topup creates exactly one FaabTransaction",
        len(faab_a) == len(faab_b) + 1,
        f"FaabTransaction count before={len(faab_b)}, after={len(faab_a)}; expected +1")
if faab_a:
    newest = faab_a[-1]
    _assert("MOCK: the FaabTransaction is status='pending'",
            newest.status == "pending",
            f"status={newest.status!r}; expected 'pending' (current mock marks it 'applied')")
    _assert("MOCK: the FaabTransaction has applied_at=None (not yet approved)",
            newest.applied_at is None,
            f"applied_at={newest.applied_at!r}; expected None (current mock sets applied_at=_now())")
    _assert("MOCK: the returned result reports status 'pending', not 'applied'",
            result.status == "pending",
            f"result.status={result.status!r}; expected 'pending'")
else:
    _assert("MOCK: a FaabTransaction exists to inspect", False, "no FaabTransaction row found")

print("\n" + "=" * 52)
if _failures:
    print(f"RED PHASE OK — {len(_failures)} target assertion(s) FAILED (expected)")
    for f in _failures: print(f"  - {f}")
    sys.exit(1)
else:
    print("All PASSED — NOT red. Investigate.")