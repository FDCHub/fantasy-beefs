"""P1-L2 — legacy bet top-up is RETIRED and credits nothing.

WHAT THIS SUITE WAS, AND WHY IT CHANGED (WP5).

It began as a RED spec against 77fd23c: `create_bet_topup`'s mock branch called
`wm_deposit`, credited the wallet and marked the row 'applied', so the target was
"create ONE pending FaabTransaction, credit nothing" and the suite exited 1 on
purpose while that defect stood.

THE DEFECT WAS NOT FIXED — THE WHOLE PATH WAS RETIRED. B6 replaced legacy bet
top-ups with the governed issuance service behind
`POST /league/{league_id}/top-offs`, and `create_bet_topup` now refuses outright
with `TopUpsUnavailableError`. So the RED target became unreachable: there is no
longer a pending FaabTransaction to inspect, because there is no longer a
request-creation path at all.

Left as it was, this suite died on an uncaught `TopUpsUnavailableError` — a
crash that read as a broken test rather than as the retirement working.

THE ECONOMIC PROPERTY IS UNCHANGED AND IS STILL ASSERTED HERE: calling the
legacy entry point issues NO Credits. It is now proved the stronger way — the
call is refused, and nothing at all is written — which is the same shape
`test_p1l2_transfer_retirement_red.py` uses for the retired transfer path.

REPLACEMENT COVERAGE for the governed path this refusal points at:
    test_b6_group_e_issuance_pg.py        balanced issuance on approval
    test_commissioner_genesis_and_grant_pg.py  who may approve
    test_s8_p3_read_models.py             what the approved issuance reports
"""
import os, sys, tempfile

# Stripe is removed from the MVP; STRIPE_SECRET_KEY is irrelevant and unset here.
os.environ.pop("STRIPE_SECRET_KEY", None)
_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'p1l2_mock.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import (Base, engine, SessionLocal, League, Team, Wallet,
                       FaabWallet, Transaction, FaabTransaction)
from ledger.ledger import create_ledger_table, trial_balance
from wallet.faab_wallet import TopUpsUnavailableError, create_bet_topup

Base.metadata.create_all(engine)
create_ledger_table()
_failures: list[str] = []


def _assert(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not condition:
        _failures.append(label)


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


print("=" * 60)
print("P1-L2 — legacy bet top-up is retired and issues nothing")
print("=" * 60)

_assert("SETUP: no payment rail exists — create_bet_topup has a single path",
        not hasattr(__import__("wallet.faab_wallet", fromlist=["x"]), "MOCK_MODE"),
        "MOCK_MODE still defined; Stripe removal incomplete")

tid = _make()
bal_b, wtx_b, faab_b = _state(tid)
tb_b = trial_balance()

raised = None
with SessionLocal() as db:
    try:
        create_bet_topup(tid, 25.00, db)
    except TopUpsUnavailableError as exc:      # noqa: PERF203 — one call, one catch
        raised = exc

bal_a, wtx_a, faab_a = _state(tid)

_assert("RETIRED: create_bet_topup refuses rather than creating a request",
        raised is not None,
        "expected TopUpsUnavailableError; the legacy request path is retired")
_assert("RETIRED: and the refusal names the governed replacement",
        raised is not None and "/top-offs" in str(raised),
        str(raised)[:120] if raised else "no exception raised")
_assert("RETIRED: the refusal states that nothing was written",
        raised is not None and "Nothing was written" in str(raised),
        str(raised)[:120] if raised else "no exception raised")

# THE ORIGINAL RED TARGET, kept verbatim in substance: no Credits are issued.
_assert("NO CREDIT: Wallet.balance is unchanged (no BAB issued)",
        bal_a == bal_b, f"before={bal_b}, after={bal_a}")
_assert("NO CREDIT: no wallet Transaction row was written",
        wtx_a == wtx_b, f"before={wtx_b}, after={wtx_a}")
# STRONGER THAN THE ORIGINAL. The RED target allowed exactly ONE pending
# FaabTransaction. The retired path writes none at all, which is a superset of
# "credits nothing" — there is no request row to approve later either.
_assert("NO CREDIT: not even a pending FaabTransaction is created",
        len(faab_a) == len(faab_b) == 0,
        f"before={len(faab_b)}, after={len(faab_a)}")
_assert("NO CREDIT: the ledger is untouched and still balances",
        trial_balance() == tb_b == 0, f"{tb_b} -> {trial_balance()}")

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("P1-L2 LEGACY TOP-UP RETIREMENT — all assertions PASSED")