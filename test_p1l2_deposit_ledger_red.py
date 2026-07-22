"""P1-L2 RED (revised) — deposit primitive hardening (T2, T3). Fails against 77fd23c.
T1 deferred to VAL-10 (world->wallet reroute is not built in P1-L2).
Target-only; current defect in diagnostics. No ledger assertions —
P1-L2 hardens deposit() (strict cents + non-committing) but does NOT ledgerize it."""
import os, sys, tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'p1l2_dep.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import Base, engine, SessionLocal, League, Team, Wallet, Transaction
from wallet.wallet_manager import deposit

Base.metadata.create_all(engine)
_failures: list[str] = []

def _assert(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not condition: _failures.append(label)

def _make(name):
    with SessionLocal() as db:
        lg = League(season=2025, name=f"P1L2 {name}", projection_source="fantasypros")
        db.add(lg); db.flush()
        t = Team(league_id=lg.id, team_name=f"P1L2 {name}", owner=name, email=f"{name}@p1l2.com")
        db.add(t); db.flush()
        w = Wallet(team_id=t.id, balance=0.0); db.add(w); db.commit()
        return t.id, w.id

def _audit(wid):
    with SessionLocal() as db:
        return db.query(Transaction).filter(Transaction.wallet_id == wid).count()

print("=" * 52); print("P1-L2 RED (revised) — deposit hardening (T2, T3)"); print("=" * 52)

# ── T2: $12.345 rejected by strict cents validation, zero side effects ──────
# Target (hardened deposit): _dollars_to_cents rejects sub-cent BEFORE any mutation.
# Current defect: deposit() accepts 12.345, does round(0.0+12.345,2)=12.35, writes a Transaction.
_EXPECTED_MSG = ("12.345 is not a whole number of cents — amounts must be "
                 "in exact dollars-and-cents (at most two decimal places)")
tid2, wid2 = _make("D2")
aud2_b = _audit(wid2)
with SessionLocal() as p:
    col2_b = p.query(Wallet).filter(Wallet.id == wid2).first().balance

raised = False; rtype = None; rmsg = ""
with SessionLocal() as db:
    try:
        deposit(wid2, 12.345, db)
    except ValueError as e:
        raised = True; rtype = type(e).__name__; rmsg = str(e); db.rollback()
    except Exception as e:
        rtype = type(e).__name__; rmsg = str(e); db.rollback()

aud2_a = _audit(wid2)
with SessionLocal() as p:
    col2_a = p.query(Wallet).filter(Wallet.id == wid2).first().balance

_assert("T2: $12.345 raises ValueError with the exact rejection message",
        raised and rmsg == _EXPECTED_MSG,
        f"raised={raised}, type={rtype!r}, msg={rmsg!r}; expected ValueError {_EXPECTED_MSG!r} "
        f"(current deposit() accepts sub-cent and rounds to the column)")
_assert("T2: rejected deposit leaves Wallet.balance unchanged",
        col2_a == col2_b,
        f"Wallet.balance before={col2_b}, after={col2_a}; expected unchanged "
        f"(current deposit() writes round(0.0+12.345,2)=12.35)")
_assert("T2: rejected deposit writes no Transaction audit row",
        aud2_a == aud2_b,
        f"audit rows before={aud2_b}, after={aud2_a}; expected unchanged")

# ── T3: caller-owned transaction boundary; caller rollback undoes everything ──
# Target (hardened deposit): deposit() does NOT self-commit; caller rollback reverts
# the mirror mutation and the audit row.
# Current defect: deposit() commits at :148, so caller rollback cannot undo it.
tid3, wid3 = _make("D3")
aud3_b = _audit(wid3)

_cdb = SessionLocal()
try:
    deposit(wid3, 50.00, _cdb)          # cent-clean; target: stages in caller txn, no self-commit
    w_mid = _cdb.query(Wallet).filter(Wallet.id == wid3).first()
    col3_mid = w_mid.balance
    aud3_mid = _cdb.query(Transaction).filter(Transaction.wallet_id == wid3).count()
    _cdb.rollback()
finally:
    _cdb.close()

aud3_a = _audit(wid3)
with SessionLocal() as p:
    col3_a = p.query(Wallet).filter(Wallet.id == wid3).first().balance

_assert("T3: mirror mutation is visible in the caller's session before rollback",
        col3_mid == 50.0,
        f"caller-session Wallet.balance mid={col3_mid}; expected 50.0 (deposit staged the credit)")
_assert("T3: audit row is visible in the caller's session before rollback",
        aud3_mid == aud3_b + 1,
        f"caller-session audit count mid={aud3_mid}, baseline={aud3_b}; expected +1")
_assert("T3: caller rollback restores original Wallet.balance (deposit did not self-commit)",
        col3_a == 0.0,
        f"Wallet.balance after rollback={col3_a}; expected 0.0 "
        f"(current deposit() self-commits at wallet_manager.py:148, so rollback cannot undo it)")
_assert("T3: caller rollback removes the audit row",
        aud3_a == aud3_b,
        f"audit rows after rollback={aud3_a}, baseline={aud3_b}; expected unchanged")

print("\n" + "=" * 52)
if _failures:
    print(f"RED PHASE OK — {len(_failures)} target assertion(s) FAILED (expected)")
    for f in _failures: print(f"  - {f}")
    sys.exit(1)
else:
    print("All PASSED — NOT red. Investigate.")