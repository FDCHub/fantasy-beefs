"""P1-L2 RED — /faab/transfer route retirement (T5). Fails against 77fd23c.
Target: HTTP 410 + exact body + deprecated flag + ZERO side effects
(no ledger entry, no float mutation, no FaabTransaction row, no freeze-state
change: bet_frozen AND updated_at unchanged)."""
import os, sys, tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'p1l2_route.db')}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from db.schema import (Base, engine, SessionLocal, League, Team, Wallet,
                       FaabWallet, User, FaabTransaction)
from ledger.ledger import balance_of, trial_balance, create_ledger_table, LedgerEntry
from db.deps import get_db
from auth.jwt_auth import get_current_gm
from api.main import app

Base.metadata.create_all(engine); create_ledger_table()
_EXPECTED_DETAIL = ("BAB-to-waiver transfers are retired under the four-bucket "
                    "economy and are no longer supported.")
_failures: list[str] = []

def _assert(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not condition: _failures.append(label)

def _override_get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

app.dependency_overrides[get_db] = _override_get_db

with SessionLocal() as db:
    lg = League(season=2025, name="P1L2 route", projection_source="fantasypros")
    db.add(lg); db.flush()
    t = Team(league_id=lg.id, team_name="P1L2 route", owner="R1", email="r1@p1l2.com")
    db.add(t); db.flush(); _TID = t.id
    db.add(Wallet(team_id=t.id, balance=100.0))
    db.add(FaabWallet(team_id=t.id, league_id=lg.id, waiver_balance=100.0))
    u = User(email="r1@p1l2.com", hashed_password="x", role="gm", is_active=1, team_id=t.id)
    db.add(u); db.commit(); _UID = u.id

def _fake_get_current_gm():
    with SessionLocal() as db:
        return db.query(User).filter(User.id == _UID).first()

app.dependency_overrides[get_current_gm] = _fake_get_current_gm
client = TestClient(app)

def _state():
    """Full FAAB state a zero-side-effect retirement must leave untouched:
    both balances + both freeze fields (bet_frozen, updated_at)."""
    with SessionLocal() as db:
        w = db.query(Wallet).filter(Wallet.team_id == _TID).first()
        fw = db.query(FaabWallet).filter(FaabWallet.team_id == _TID).first()
        return w.balance, fw.waiver_balance, fw.bet_frozen, fw.updated_at

def _counts():
    with SessionLocal() as db:
        return (db.query(LedgerEntry).count(),
                db.query(FaabTransaction).count())

print("=" * 52); print("P1-L2 RED — /faab/transfer route retirement (T5)"); print("=" * 52)

try:
    bet_b, waiver_b, frozen_b, updated_b = _state()
    tb_b = trial_balance()
    led_b, faabtx_b = _counts()
    wallet_led_b = balance_of(f"wallet:{_TID}")
    world_led_b = balance_of("world")

    resp = client.post("/faab/transfer", json={
        "team_id": _TID, "from_wallet": "waiver", "to_wallet": "bet", "amount": 25.00})

    bet_a, waiver_a, frozen_a, updated_a = _state()
    tb_a = trial_balance()
    led_a, faabtx_a = _counts()
    wallet_led_a = balance_of(f"wallet:{_TID}")
    world_led_a = balance_of("world")

    try: body = resp.json()
    except Exception: body = {"<non-json>": resp.text}

    _assert("T5: /faab/transfer returns HTTP 410", resp.status_code == 410,
            f"status={resp.status_code}, body={body}; expected 410 "
            f"(route calls live faab_transfer -> 200 today)")
    _assert("T5: returns the exact retirement detail",
            body.get("detail") == _EXPECTED_DETAIL,
            f"detail={body.get('detail')!r}; expected {_EXPECTED_DETAIL!r}")
    _dep = None
    for r in app.routes:
        if getattr(r, "path", None) == "/faab/transfer" and "POST" in getattr(r, "methods", set()):
            _dep = getattr(r, "deprecated", None)
    _assert("T5: /faab/transfer route metadata deprecated is True", _dep is True,
            f"route.deprecated={_dep!r}; expected True")
    _assert("T5: no float balance mutation",
            bet_a == bet_b and waiver_a == waiver_b,
            f"before=({bet_b}, {waiver_b}); after=({bet_a}, {waiver_a}); expected unchanged")
    _assert("T5: no ledger entries added", led_a == led_b,
            f"LedgerEntry count before={led_b}, after={led_a}; expected unchanged")
    _assert("T5: relevant ledger-account balances unchanged",
            wallet_led_a == wallet_led_b and world_led_a == world_led_b,
            f"wallet before={wallet_led_b}, after={wallet_led_a}; "
            f"world before={world_led_b}, after={world_led_a}")
    _assert("T5: no FaabTransaction audit row added", faabtx_a == faabtx_b,
            f"FaabTransaction count before={faabtx_b}, after={faabtx_a}; expected unchanged")
    _assert("T5: no freeze-flag change (bet_frozen unchanged)", frozen_a == frozen_b,
            f"bet_frozen before={frozen_b}, after={frozen_a}; expected unchanged")
    _assert("T5: no freeze-timestamp change (updated_at unchanged)", updated_a == updated_b,
            f"updated_at before={updated_b}, after={updated_a}; expected unchanged")
    _assert("T5: trial balance unchanged (guard)", tb_a == tb_b,
            f"trial_balance before={tb_b}, after={tb_a}; expected unchanged")
finally:
    app.dependency_overrides.clear()

print("\n" + "=" * 52)
if _failures:
    print(f"RED PHASE OK — {len(_failures)} target assertion(s) FAILED (expected)")
    for f in _failures: print(f"  - {f}")
    sys.exit(1)
else:
    print("All PASSED — NOT red. Investigate.")
