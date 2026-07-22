"""P1-L2 RED — /wallet/deposit route retirement (T6). Fails against 77fd23c.
Target: HTTP 410 + exact body + deprecated flag + ZERO side effects."""
import os, sys, tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 'p1l2_deproute.db')}"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from db.schema import Base, engine, SessionLocal, League, Team, Wallet, User, Transaction
from db.deps import get_db
from auth.jwt_auth import get_current_gm
from api.main import app

Base.metadata.create_all(engine)
_EXPECTED_DETAIL = ("Direct wallet deposits are retired. BAB wallet credits "
                    "require a confirmed top-up event.")
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
    lg = League(season=2025, name="P1L2 deproute", projection_source="fantasypros")
    db.add(lg); db.flush()
    t = Team(league_id=lg.id, team_name="P1L2 deproute", owner="R1", email="r1@p1l2.com")
    db.add(t); db.flush(); _TID = t.id
    db.add(Wallet(team_id=t.id, balance=100.0))
    u = User(email="r1@p1l2.com", hashed_password="x", role="gm", is_active=1, team_id=t.id)
    db.add(u); db.commit(); _UID = u.id
    _WID = db.query(Wallet).filter(Wallet.team_id == t.id).first().id

def _fake_get_current_gm():
    with SessionLocal() as db:
        return db.query(User).filter(User.id == _UID).first()

app.dependency_overrides[get_current_gm] = _fake_get_current_gm
client = TestClient(app)

def _bal_and_audit():
    with SessionLocal() as db:
        w = db.query(Wallet).filter(Wallet.team_id == _TID).first()
        aud = db.query(Transaction).filter(Transaction.wallet_id == _WID).count()
        return w.balance, aud

print("=" * 52); print("P1-L2 RED — /wallet/deposit retirement (T6)"); print("=" * 52)

try:
    bal_b, aud_b = _bal_and_audit()

    resp = client.post("/wallet/deposit", json={"wallet_id": _WID, "amount": 25.00})

    bal_a, aud_a = _bal_and_audit()
    try: body = resp.json()
    except Exception: body = {"<non-json>": resp.text}

    _assert("T6: /wallet/deposit returns HTTP 410", resp.status_code == 410,
            f"status={resp.status_code}, body={body}; expected 410 (route calls live wm_deposit -> 200 today)")
    _assert("T6: returns the exact retirement detail",
            body.get("detail") == _EXPECTED_DETAIL,
            f"detail={body.get('detail')!r}; expected {_EXPECTED_DETAIL!r}")
    _dep = None
    for r in app.routes:
        if getattr(r, "path", None) == "/wallet/deposit" and "POST" in getattr(r, "methods", set()):
            _dep = getattr(r, "deprecated", None)
    _assert("T6: /wallet/deposit route metadata deprecated is True", _dep is True,
            f"route.deprecated={_dep!r}; expected True")
    _assert("T6: no Wallet.balance mutation", bal_a == bal_b,
            f"balance before={bal_b}, after={bal_a}; expected unchanged (current route credits via wm_deposit)")
    _assert("T6: no Transaction audit row added", aud_a == aud_b,
            f"audit count before={aud_b}, after={aud_a}; expected unchanged")
finally:
    app.dependency_overrides.clear()

print("\n" + "=" * 52)
if _failures:
    print(f"RED PHASE OK — {len(_failures)} target assertion(s) FAILED (expected)")
    for f in _failures: print(f"  - {f}")
    sys.exit(1)
else:
    print("All PASSED — NOT red. Investigate.")