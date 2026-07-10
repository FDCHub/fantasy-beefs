"""
test_bet_funded_retirement.py — B2, Finding 5.4 (pre-cleared, no Opus round):
get_bet_funded() removed from all six live betting/challenge endpoints;
get_buyin_gate() is now the sole gate on each.

Covers (per the spec's Section 5, item 4):
  1. Structural: all six endpoints resolve get_buyin_gate in their FastAPI
     dependency tree; none resolve get_bet_funded anymore (introspects the
     actual route.dependant graph, not just source text).
  2. get_buyin_gate() still blocks an unpaid GM (HTTP 402) when a league's
     buy-in enforcement is active (League.buyin_enforcement_active, B2
     Finding 5.3) — unchanged existing behavior.
  3. A GM whose FaabWallet is frozen (bet_frozen=1) can now place a bet,
     provided their BAB ledger wallet is actually funded — proving the
     FAAB-freeze layer no longer blocks anything.
  4. An underfunded BAB ledger wallet is still correctly rejected — but now
     by the ledger's own funded-balance guard (HTTP 400 / ValueError chain),
     not by get_bet_funded's HTTP 402.

Uses a temp SQLite DB so prod is never touched. DATABASE_URL is set before
any project import touches db/schema.py.
"""

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_bet_funded_retirement.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.pop("STRIPE_SECRET_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from db.schema import (
    Base, engine, SessionLocal,
    League, Team, User, Wallet, FaabWallet,
    Matchup, Player, Roster,
)
from auth.jwt_auth import get_current_gm, hash_password
from db.deps import get_db
from wallet.faab_wallet import set_freeze
from payments.stripe_connect import set_buyin_enforcement_active
from ledger.ledger import post as ledger_post, create_ledger_table, balance_of

import api.main as api_main
from api.main import app, get_buyin_gate

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── DB bootstrap ──────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)
create_ledger_table()

client = TestClient(app)


def _override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


def _set_current_user(user_id: int) -> None:
    def _fake_get_current_gm():
        with SessionLocal() as db:
            return db.query(User).filter(User.id == user_id).first()
    app.dependency_overrides[get_current_gm] = _fake_get_current_gm


# ── Fixture: one league, two teams (t1 bets, t2 is the opponent) ──────────────

with SessionLocal() as db:
    league = League(season=2025, name="B2-5.4 Test League", projection_source="fantasypros")
    db.add(league)
    db.flush()

    t1 = Team(league_id=league.id, team_name="Bettor Team", owner="Bettor", email="bettor@t.com")
    t2 = Team(league_id=league.id, team_name="Opponent Team", owner="Opponent", email="opp@t.com")
    db.add_all([t1, t2])
    db.flush()

    for team, nfl_team in ((t1, "KC"), (t2, "PHI")):
        for i in range(9):
            p = Player(name=f"{team.team_name}-P{i}", position="WR", nfl_team=nfl_team)
            db.add(p); db.flush()
            db.add(Roster(team_id=team.id, player_id=p.id))

    wallet1 = Wallet(team_id=t1.id, balance=1000.0)
    wallet2 = Wallet(team_id=t2.id, balance=1000.0)
    db.add_all([wallet1, wallet2])

    matchup = Matchup(league_id=league.id, week=1,
                       home_team_id=t1.id, away_team_id=t2.id,
                       home_score=0.0, away_score=0.0)
    db.add(matchup)

    # User.team_id is unique — one user per team. Starts unpaid for Item 2's
    # blocked-GM proof; flipped to paid before Item 3.
    user1 = User(email="gm1@t.com", hashed_password=hash_password("x"),
                 team_id=t1.id, role="gm", buy_in_paid=0)
    db.add(user1)

    db.commit()
    league_id  = league.id
    t1_id      = t1.id
    t2_id      = t2.id
    wallet1_id = wallet1.id
    matchup_id = matchup.id
    user1_id   = user1.id


# ── ITEM 1: structural — all six routes resolve get_buyin_gate, none resolve get_bet_funded ──

print("\nItem 1: all six endpoints' dependency trees resolve get_buyin_gate, not get_bet_funded")

def _collect_dependency_callables(dependant, seen=None):
    if seen is None:
        seen = set()
    if id(dependant) in seen:
        return set()
    seen.add(id(dependant))
    calls = set()
    if dependant.call is not None:
        calls.add(dependant.call)
    for sub in dependant.dependencies:
        calls |= _collect_dependency_callables(sub, seen)
    return calls


try:
    from wallet.faab_wallet import get_bet_funded as _retired_get_bet_funded
except ImportError:
    _retired_get_bet_funded = None
_assert("get_bet_funded still exists in wallet/faab_wallet.py (not deleted, just unwired)", _retired_get_bet_funded is not None)

_six_paths = {
    ("POST", "/bets/place"),
    ("POST", "/bets/straight"),
    ("POST", "/bets/spread"),
    ("POST", "/bets/over_under"),
    ("POST", "/bets/prop"),
    ("POST", "/beef/challenge"),
}
_found_paths = set()

for route in app.routes:
    methods = getattr(route, "methods", None)
    path = getattr(route, "path", None)
    if not methods or path is None:
        continue
    for method in methods:
        if (method, path) in _six_paths:
            _found_paths.add((method, path))
            deps = _collect_dependency_callables(route.dependant)
            _assert(f"{method} {path}: depends on get_buyin_gate", get_buyin_gate in deps)
            if _retired_get_bet_funded is not None:
                _assert(f"{method} {path}: does NOT depend on get_bet_funded", _retired_get_bet_funded not in deps)

_assert("all six endpoints found and checked", _found_paths == _six_paths, f"missing: {_six_paths - _found_paths}")


# ── ITEM 2: get_buyin_gate still blocks an unpaid GM (unchanged behavior) ─────

print("\nItem 2: unpaid GM is still blocked with HTTP 402 (get_buyin_gate unchanged)")

# B2, Finding 5.3 (built after this test was first written): get_buyin_gate()
# now activates via League.buyin_enforcement_active, not LeagueTreasury —
# activate it explicitly here so this scenario still exercises the
# "blocked" path (default is False/inactive).
with SessionLocal() as db:
    set_buyin_enforcement_active(league_id, True, db)

_set_current_user(user1_id)
resp_unpaid = client.post("/bets/straight", json={
    "matchup_id": matchup_id, "wallet_id": wallet1_id,
    "picked_team_id": t1_id, "amount": 10.0, "week": 1,
})
_assert("unpaid GM blocked with HTTP 402", resp_unpaid.status_code == 402, f"got {resp_unpaid.status_code}: {resp_unpaid.text}")


# ── ITEM 3: FAAB-frozen GM can now place a bet, provided BAB wallet is funded ──

print("\nItem 3: FAAB-frozen GM (bet_frozen=1) can now bet, provided the BAB ledger wallet is funded")

with SessionLocal() as db:
    user1 = db.query(User).filter(User.id == user1_id).first()
    user1.buy_in_paid = 1  # flip to paid — this scenario tests the FAAB layer, not the buy-in layer

    fw = FaabWallet(team_id=t1_id, league_id=league_id)
    db.add(fw)
    db.commit()
    set_freeze(t1_id, True, db)
    fw_check = db.query(FaabWallet).filter(FaabWallet.team_id == t1_id).first()
_assert("fixture check — FaabWallet is actually frozen (bet_frozen=1)", fw_check.bet_frozen == 1, f"got {fw_check.bet_frozen}")

# Fund t1's BAB ledger wallet — Finding 5.1's known gap (no code path funds
# ledger wallets yet) means this is a test-only stand-in, same as prior
# sessions' ledger-conversion tests.
ledger_post(
    [("world", -100_000_00), (f"wallet:{t1_id}", 100_000_00)],
    door="buy_in_paid",
)

_set_current_user(user1_id)
resp_frozen_ok = client.post("/bets/straight", json={
    "matchup_id": matchup_id, "wallet_id": wallet1_id,
    "picked_team_id": t1_id, "amount": 10.0, "week": 1,
})
_assert(
    "FAAB-frozen GM's bet succeeds (201) — no longer blocked by the retired gate",
    resp_frozen_ok.status_code == 201,
    f"got {resp_frozen_ok.status_code}: {resp_frozen_ok.text}",
)
_assert("wallet:t1 ledger balance debited by the bet", balance_of(f"wallet:{t1_id}") == 100_000_00 - 1000, f"got {balance_of(f'wallet:{t1_id}')}")


# ── ITEM 4: underfunded BAB ledger wallet is still rejected — by the ledger, not the gate ──

print("\nItem 4: an underfunded BAB ledger wallet is still rejected (by the ledger guard, not get_bet_funded)")

with SessionLocal() as db:
    t3 = Team(league_id=league_id, team_name="Underfunded Team", owner="Poor", email="poor@t.com")
    db.add(t3)
    db.flush()
    for i in range(9):
        p = Player(name=f"UF-P{i}", position="WR", nfl_team="SF")
        db.add(p); db.flush()
        db.add(Roster(team_id=t3.id, player_id=p.id))
    wallet3 = Wallet(team_id=t3.id, balance=1000.0)
    db.add(wallet3)
    matchup2 = Matchup(league_id=league_id, week=2, home_team_id=t3.id, away_team_id=t2_id,
                        home_score=0.0, away_score=0.0)
    db.add(matchup2)
    user_uf = User(email="uf@t.com", hashed_password=hash_password("x"),
                    team_id=t3.id, role="gm", buy_in_paid=1)
    db.add(user_uf)
    db.commit()
    t3_id = t3.id
    wallet3_id = wallet3.id
    matchup2_id = matchup2.id
    user_uf_id = user_uf.id

# Deliberately NOT funding wallet:{t3_id} in the ledger — it stays at 0.
_set_current_user(user_uf_id)
resp_underfunded = client.post("/bets/straight", json={
    "matchup_id": matchup2_id, "wallet_id": wallet3_id,
    "picked_team_id": t3_id, "amount": 10.0, "week": 2,
})
_assert(
    "underfunded bet rejected with HTTP 400 (ledger's InsufficientFundsError), not 402",
    resp_underfunded.status_code == 400,
    f"got {resp_underfunded.status_code}: {resp_underfunded.text}",
)
_assert("wallet:t3 ledger balance still 0 — nothing partially posted", balance_of(f"wallet:{t3_id}") == 0, f"got {balance_of(f'wallet:{t3_id}')}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
