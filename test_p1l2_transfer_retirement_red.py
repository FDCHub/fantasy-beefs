"""P1-L2 RED — BAB<->waiver transfer retirement (T4). Fails against 77fd23c.
Target: retired transfer REJECTS (exact ValueError) and moves nothing."""
import os, sys, tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'p1l2_xfer.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import Base, engine, SessionLocal, League, Team, Wallet, FaabWallet
from ledger.ledger import balance_of, trial_balance, create_ledger_table, LedgerEntry
from wallet.faab_wallet import transfer

Base.metadata.create_all(engine); create_ledger_table()
_RETIRED_MSG = ("BAB-to-waiver transfers are retired under the four-bucket "
                "economy and are no longer supported.")
_failures: list[str] = []

def _assert(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not condition: _failures.append(label)

def _make(name, bet, waiver):
    with SessionLocal() as db:
        lg = League(season=2025, name=f"P1L2 {name}", projection_source="fantasypros")
        db.add(lg); db.flush()
        t = Team(league_id=lg.id, team_name=f"P1L2 {name}", owner=name, email=f"{name}@p1l2.com")
        db.add(t); db.flush()
        db.add(Wallet(team_id=t.id, balance=bet))
        db.add(FaabWallet(team_id=t.id, league_id=lg.id, waiver_balance=waiver))
        db.commit(); return t.id

def _bal(tid):
    with SessionLocal() as db:
        w = db.query(Wallet).filter(Wallet.team_id == tid).first()
        fw = db.query(FaabWallet).filter(FaabWallet.team_id == tid).first()
        return w.balance, fw.waiver_balance

def _ledger_count():
    with SessionLocal() as db:
        return db.query(LedgerEntry).count()

def _run_retired(tid, frm, to):
    raised = False; rtype = None; rmsg = ""
    with SessionLocal() as db:
        try:
            transfer(tid, frm, to, 25.00, db); db.commit()
        except ValueError as e:
            raised = True; rtype = type(e).__name__; rmsg = str(e); db.rollback()
        except Exception as e:
            rtype = type(e).__name__; rmsg = str(e); db.rollback()
    return raised, rtype, rmsg

print("=" * 52); print("P1-L2 RED — transfer retirement (T4)"); print("=" * 52)

# ── T4a: bet -> waiver ──────────────────────────────────────────────────────
tbw = _make("BW", 100.0, 100.0)
bet_b, waiver_b = _bal(tbw); tb_b = trial_balance(); lc_b = _ledger_count()
wallet_led_b = balance_of(f"wallet:{tbw}"); world_led_b = balance_of("world")
r_a, rt_a, rm_a = _run_retired(tbw, "bet", "waiver")
bet_a, waiver_a = _bal(tbw); tb_a = trial_balance(); lc_a = _ledger_count()
wallet_led_a = balance_of(f"wallet:{tbw}"); world_led_a = balance_of("world")

_assert("T4a: retired bet->waiver rejects with exact ValueError",
        r_a and rm_a == _RETIRED_MSG,
        f"raised={r_a}, type={rt_a!r}, msg={rm_a!r}; expected ValueError {_RETIRED_MSG!r} "
        f"(transfer today succeeds and mutates)")
_assert("T4a: retired bet->waiver leaves both balances unchanged",
        bet_a == bet_b and waiver_a == waiver_b,
        f"before=({bet_b}, {waiver_b}); after=({bet_a}, {waiver_a}); "
        f"expected unchanged (mutates faab_wallet.py:663/:664 today)")
_assert("T4a: retired bet->waiver adds no ledger entries",
        lc_a == lc_b, f"LedgerEntry count before={lc_b}, after={lc_a}; expected unchanged")
_assert("T4a: relevant ledger-account balances unchanged",
        wallet_led_a == wallet_led_b and world_led_a == world_led_b,
        f"wallet:{tbw} before={wallet_led_b}, after={wallet_led_a}; "
        f"world before={world_led_b}, after={world_led_a}; expected unchanged")

# ── T4b: waiver -> bet ──────────────────────────────────────────────────────
twb = _make("WB", 100.0, 100.0)
bet2_b, waiver2_b = _bal(twb); lc2_b = _ledger_count()
wallet2_led_b = balance_of(f"wallet:{twb}"); world2_led_b = balance_of("world")
r_b, rt_b, rm_b = _run_retired(twb, "waiver", "bet")
bet2_a, waiver2_a = _bal(twb); lc2_a = _ledger_count()
wallet2_led_a = balance_of(f"wallet:{twb}"); world2_led_a = balance_of("world")

_assert("T4b: retired waiver->bet rejects with exact ValueError",
        r_b and rm_b == _RETIRED_MSG,
        f"raised={r_b}, type={rt_b!r}, msg={rm_b!r}; expected ValueError {_RETIRED_MSG!r}")
_assert("T4b: retired waiver->bet leaves both balances unchanged",
        bet2_a == bet2_b and waiver2_a == waiver2_b,
        f"before=({bet2_b}, {waiver2_b}); after=({bet2_a}, {waiver2_a}); "
        f"expected unchanged (mutates faab_wallet.py:677/:679 today)")
_assert("T4b: retired waiver->bet adds no ledger entries",
        lc2_a == lc2_b, f"LedgerEntry count before={lc2_b}, after={lc2_a}; expected unchanged")
_assert("T4b: relevant ledger-account balances unchanged",
        wallet2_led_a == wallet2_led_b and world2_led_a == world2_led_b,
        f"wallet:{twb} before={wallet2_led_b}, after={wallet2_led_a}; "
        f"world before={world2_led_b}, after={world2_led_a}; expected unchanged")

print("\n" + "=" * 52)
if _failures:
    print(f"RED PHASE OK — {len(_failures)} target assertion(s) FAILED (expected)")
    for f in _failures: print(f"  - {f}")
    sys.exit(1)
else:
    print("All PASSED — NOT red. Investigate.")