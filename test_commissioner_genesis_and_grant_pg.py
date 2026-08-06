"""
test_commissioner_genesis_and_grant_pg.py — commissioner genesis CLI and the
league-scoped grant route.

GENESIS (scripts/bootstrap_league_commissioner.py)
  1. first genesis succeeds and writes exactly one row with source="bootstrap"
     and assigned_by_user_id NULL;
  2. second genesis for the same league refuses, EVEN WITH A DIFFERENT USER;
  3. repeating the identical invocation refuses;
  4. genesis for another league succeeds independently;
  5. nonexistent league refuses; nonexistent user refuses; inactive user
     refuses;
  6. every refusal leaves zero new rows;
  7. CONCURRENCY: two threads racing genesis on one league produce exactly one
     success, one refusal, and exactly one authority row.

GRANT ROUTE (POST /league/{league_id}/commissioners)
  8-20. authorization, provenance, target validation, duplicate contract,
        concurrency, and proof that no money path is touched.

Requires TEST_DATABASE_URL pointing at a dedicated, empty, _test-named,
non-Railway PostgreSQL database. No production system is contacted.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Genesis/grant suite cannot run:\n  {e}")
    sys.exit(2)

from fastapi import HTTPException
from fastapi.testclient import TestClient

from db.schema import (
    SessionLocal, League, LeagueCommissioner, SeasonAllocation, Team, User,
    Wallet, FaabTransaction,
)
from ledger.ledger import LedgerEntry
from auth.jwt_auth import get_current_user, hash_password
import api.main as api_main
from api.main import app
from scripts.bootstrap_league_commissioner import (
    bootstrap_first_commissioner, GenesisRefused,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


client = TestClient(app)
_current = {"id": None}


def _as_user(user_id: int) -> None:
    _current["id"] = user_id

    def _override():
        # Faithful to production get_current_user, which filters
        # is_active == 1 and raises 401 otherwise. An override that returned
        # the row regardless would silently bypass the inactive-user check and
        # make this suite prove less than it claims.
        with SessionLocal() as db:
            u = (db.query(User)
                 .filter(User.id == _current["id"], User.is_active == 1)
                 .first())
            if u is None:
                raise HTTPException(status_code=401,
                                    detail="User not found or inactive")
            return u

    app.dependency_overrides[get_current_user] = _override


def _mk_league(name: str) -> int:
    with SessionLocal() as db:
        lg = League(season=2025, name=name, projection_source="fantasypros")
        db.add(lg); db.commit(); return lg.id


def _mk_team(league_id: int, name: str) -> int:
    with SessionLocal() as db:
        t = Team(league_id=league_id, team_name=name, owner=name,
                 email=f"{name}@gg.test")
        db.add(t); db.commit(); return t.id


def _mk_user(email: str, role: str = "gm", team_id=None, active: int = 1) -> int:
    with SessionLocal() as db:
        u = User(email=email, hashed_password=hash_password("x"),
                 team_id=team_id, role=role, is_active=active)
        db.add(u); db.commit(); return u.id


def _rows(league_id: int):
    with SessionLocal() as db:
        return (db.query(LeagueCommissioner)
                .filter(LeagueCommissioner.league_id == league_id)
                .order_by(LeagueCommissioner.id).all())


def _money_snapshot():
    with SessionLocal() as db:
        return (db.query(LedgerEntry).count(),
                db.query(SeasonAllocation).count(),
                db.query(FaabTransaction).count(),
                db.query(Wallet).count())


_MONEY_BEFORE = _money_snapshot()


# ── GENESIS ──────────────────────────────────────────────────────────────────

print("\nItem 1-3: genesis creates only the FIRST commissioner")

lg1 = _mk_league("Genesis league 1")
u1 = _mk_user("genesis1@gg.test")
u2 = _mk_user("genesis2@gg.test", role="commissioner")

rec = bootstrap_first_commissioner(lg1, u1)
_assert("genesis succeeded", isinstance(rec.get("authority_row_id"), int), f"got {rec}")
_assert("source is 'bootstrap'", rec["source"] == "bootstrap", f"got {rec['source']}")
_assert("assigned_by_user_id is NULL for genesis",
        rec["assigned_by_user_id"] is None, f"got {rec['assigned_by_user_id']}")
_assert("created_at populated", rec["created_at"] is not None)
_assert("exactly one authority row for the league", len(_rows(lg1)) == 1,
        f"got {len(_rows(lg1))}")

_ref = None
try:
    bootstrap_first_commissioner(lg1, u2)      # DIFFERENT user
except GenesisRefused as e:
    _ref = e
_assert("second genesis REFUSED even with a different user",
        _ref is not None, f"got {_ref}")
_assert("refusal names the grant route as the correct path",
        _ref is not None and "commissioners" in str(_ref), f"{str(_ref)[:80]}")
_assert("refused genesis added no row", len(_rows(lg1)) == 1, f"got {len(_rows(lg1))}")

_ref2 = None
try:
    bootstrap_first_commissioner(lg1, u1)      # identical invocation
except GenesisRefused as e:
    _ref2 = e
_assert("repeating the identical genesis REFUSED (not idempotent success)",
        _ref2 is not None)
_assert("still exactly one authority row", len(_rows(lg1)) == 1)


print("\nItem 4-6: independence, and every refusal writes nothing")

lg2 = _mk_league("Genesis league 2")
rec2 = bootstrap_first_commissioner(lg2, u1)
_assert("genesis for a DIFFERENT league succeeds independently",
        rec2["league_id"] == lg2 and rec2["user_id"] == u1, f"got {rec2}")
_assert("same user may be first commissioner of two leagues",
        len(_rows(lg1)) == 1 and len(_rows(lg2)) == 1)

with SessionLocal() as db:
    _total_before = db.query(LeagueCommissioner).count()

for label, lid, uid in (
    ("nonexistent league refused", 999_999, u1),
    ("nonexistent user refused",   _mk_league("Genesis league 3"), 999_999),
):
    _r = None
    try:
        bootstrap_first_commissioner(lid, uid)
    except GenesisRefused as e:
        _r = e
    _assert(label, _r is not None, f"got {_r}")

lg4 = _mk_league("Genesis league 4")
u_inactive = _mk_user("inactive@gg.test", active=0)
_r = None
try:
    bootstrap_first_commissioner(lg4, u_inactive)
except GenesisRefused as e:
    _r = e
_assert("inactive user refused", _r is not None, f"got {_r}")

with SessionLocal() as db:
    _total_after = db.query(LeagueCommissioner).count()
_assert("every refusal left the table unchanged",
        _total_before == _total_after, f"{_total_before} -> {_total_after}")


print("\nItem 7: CONCURRENT genesis on one league — exactly one winner")

lg_race = _mk_league("Genesis race league")
ru1 = _mk_user("race1@gg.test")
ru2 = _mk_user("race2@gg.test")
_results: list[tuple[str, object]] = []
_barrier = threading.Barrier(2)


def _attempt(uid: int):
    _barrier.wait()
    try:
        _results.append(("ok", bootstrap_first_commissioner(lg_race, uid)))
    except GenesisRefused as e:
        _results.append(("refused", str(e)))
    except Exception as e:                      # any other failure is a defect
        _results.append(("error", f"{type(e).__name__}: {e}"))


_threads = [threading.Thread(target=_attempt, args=(u,)) for u in (ru1, ru2)]
for t in _threads: t.start()
for t in _threads: t.join()

_oks = [r for r in _results if r[0] == "ok"]
_refs = [r for r in _results if r[0] == "refused"]
_errs = [r for r in _results if r[0] == "error"]
_assert("both concurrent attempts finished", len(_results) == 2, f"got {_results}")
_assert("exactly ONE genesis succeeded", len(_oks) == 1, f"ok={len(_oks)} refused={len(_refs)} err={len(_errs)}")
_assert("the loser was REFUSED, not crashed", len(_refs) == 1 and len(_errs) == 0,
        f"errors={_errs}")
_assert("exactly ONE authority row exists for the raced league",
        len(_rows(lg_race)) == 1, f"got {len(_rows(lg_race))}")
_assert("the surviving row is one of the two racers",
        _rows(lg_race)[0].user_id in (ru1, ru2))


# ── GRANT ROUTE ──────────────────────────────────────────────────────────────

print("\nItem 8-13: grant-route authorization")

lga = _mk_league("Grant league A")
lgb = _mk_league("Grant league B")
_mk_team(lga, "GA1"); _mk_team(lgb, "GB1")

comm_a    = _mk_user("g_comm_a@gg.test", role="commissioner")
comm_b    = _mk_user("g_comm_b@gg.test", role="commissioner")
comm_gm   = _mk_user("g_comm_gm@gg.test", role="gm")        # authority, role=gm
glob_only = _mk_user("g_global@gg.test", role="commissioner")  # role, no row
plain_gm  = _mk_user("g_plain@gg.test", role="gm")
target1   = _mk_user("g_target1@gg.test", role="gm")
target2   = _mk_user("g_target2@gg.test", role="gm")
target_x  = _mk_user("g_targetx@gg.test", role="gm")
target_inactive = _mk_user("g_inactive@gg.test", active=0)

bootstrap_first_commissioner(lga, comm_a)
bootstrap_first_commissioner(lgb, comm_b)
with SessionLocal() as db:
    db.add(LeagueCommissioner(league_id=lga, user_id=comm_gm,
                              source="local_grant", assigned_by_user_id=comm_a))
    db.commit()


def _grant(caller: int, league_id: int, target: int):
    _as_user(caller)
    return client.post(f"/league/{league_id}/commissioners", json={"user_id": target})


r = _grant(comm_a, lga, target1)
_assert("authorized League A commissioner grants in League A (201)",
        r.status_code == 201, f"got {r.status_code}: {r.text[:100]}")
_body = r.json() if r.status_code == 201 else {}
_assert("response league_id correct", _body.get("league_id") == lga, f"got {_body}")
_assert("response user_id is the TARGET", _body.get("user_id") == target1, f"got {_body}")
_assert("source is 'local_grant'", _body.get("source") == "local_grant", f"got {_body}")
_assert("assigned_by_user_id is the CALLER",
        _body.get("assigned_by_user_id") == comm_a, f"got {_body}")
_assert("created_at is non-null", bool(_body.get("created_at")), f"got {_body}")

r = _grant(comm_gm, lga, target2)
_assert("caller with authority row but global role 'gm' SUCCEEDS (201)",
        r.status_code == 201, f"got {r.status_code}: {r.text[:100]}")

r = _grant(glob_only, lga, target_x)
_assert("global commissioner with NO authority row denied 403",
        r.status_code == 403, f"got {r.status_code}")

r = _grant(comm_a, lgb, target_x)
_assert("League A commissioner granting in League B denied 403",
        r.status_code == 403, f"got {r.status_code}")

r = _grant(plain_gm, lga, target_x)
_assert("ordinary GM denied 403", r.status_code == 403, f"got {r.status_code}")

with SessionLocal() as db:
    db.query(User).filter(User.id == comm_gm).update({"is_active": 0})
    db.commit()
r = _grant(comm_gm, lga, target_x)
_assert("inactive caller denied under existing auth behaviour",
        r.status_code in (401, 403, 500), f"got {r.status_code}")
with SessionLocal() as db:
    db.query(User).filter(User.id == comm_gm).update({"is_active": 1})
    db.commit()


print("\nItem 9-13: target validation")

r = _grant(comm_a, lga, 999_999)
_assert("nonexistent target user -> 404", r.status_code == 404, f"got {r.status_code}")

r = _grant(comm_a, lga, target_inactive)
_assert("inactive target rejected (400)", r.status_code == 400, f"got {r.status_code}")

with SessionLocal() as db:
    _t1 = db.query(User).filter(User.id == target1).first()
    _assert("target needed NO team", _t1.team_id is None, f"got {_t1.team_id}")
    _assert("target needed NO global commissioner role",
            _t1.role == "gm", f"got {_t1.role}")

r = _grant(comm_b, lgb, target1)   # target1 already commissions League A
_assert("target already commissioned elsewhere may be granted here (201)",
        r.status_code == 201, f"got {r.status_code}: {r.text[:100]}")
_assert("target1 now administers two leagues",
        len([x for x in _rows(lga) if x.user_id == target1]) == 1
        and len([x for x in _rows(lgb) if x.user_id == target1]) == 1)


print("\nItem 14-15: duplicate contract — 409, provenance never rewritten")

_orig = [x for x in _rows(lga) if x.user_id == target1][0]
_orig_snap = (_orig.id, _orig.source, _orig.assigned_by_user_id, _orig.created_at)

r = _grant(comm_gm, lga, target1)   # different granter, same pair
_assert("duplicate grant returns 409", r.status_code == 409, f"got {r.status_code}")

_after = [x for x in _rows(lga) if x.user_id == target1]
_assert("still exactly one row for that pair", len(_after) == 1, f"got {len(_after)}")
_a = _after[0]
_assert("duplicate did NOT rewrite the row id", _a.id == _orig_snap[0])
_assert("duplicate did NOT rewrite source", _a.source == _orig_snap[1], f"got {_a.source}")
_assert("duplicate did NOT rewrite assigned_by_user_id — provenance preserved",
        _a.assigned_by_user_id == _orig_snap[2],
        f"got {_a.assigned_by_user_id}, original {_orig_snap[2]}")
_assert("duplicate did NOT rewrite created_at",
        _a.created_at == _orig_snap[3])


print("\nItem 16: CONCURRENT duplicate grant — exactly one row")

race_target = _mk_user("g_racetarget@gg.test")
_gr: list[int] = []
_gbar = threading.Barrier(2)


def _grant_race():
    _gbar.wait()
    c = TestClient(app)
    _gr.append(c.post(f"/league/{lga}/commissioners",
                      json={"user_id": race_target}).status_code)


_as_user(comm_a)
_gt = [threading.Thread(target=_grant_race) for _ in range(2)]
for t in _gt: t.start()
for t in _gt: t.join()

_assert("both concurrent grants returned", len(_gr) == 2, f"got {_gr}")
_assert("exactly ONE 201 and ONE 409 — no 500",
        sorted(_gr) == [201, 409], f"got {sorted(_gr)}")
_assert("exactly one authority row for the raced pair",
        len([x for x in _rows(lga) if x.user_id == race_target]) == 1)


print("\nItem 17-20: provenance cannot be spoofed; no money path touched")

_as_user(comm_a)
_spoof = client.post(f"/league/{lga}/commissioners", json={
    "user_id": _mk_user("g_spoof@gg.test"),
    "source": "bootstrap",
    "assigned_by_user_id": 999_999,
    "league_id": lgb,
    "created_at": "1999-01-01T00:00:00",
})
_assert("request carrying extra provenance fields still succeeds (extras ignored)",
        _spoof.status_code == 201, f"got {_spoof.status_code}: {_spoof.text[:100]}")
_sb = _spoof.json()
_assert("spoofed source IGNORED — server forced 'local_grant'",
        _sb["source"] == "local_grant", f"got {_sb['source']}")
_assert("spoofed assigned_by_user_id IGNORED — server forced the caller",
        _sb["assigned_by_user_id"] == comm_a, f"got {_sb['assigned_by_user_id']}")
_assert("spoofed league_id IGNORED — server used the PATH league",
        _sb["league_id"] == lga, f"got {_sb['league_id']}")

with SessionLocal() as db:
    _srcs = {r.source for r in db.query(LeagueCommissioner).all()}
_assert("the grant route can never create a yahoo_sync row",
        "yahoo_sync" not in _srcs, f"sources present: {sorted(_srcs)}")
_assert("every non-genesis row is 'local_grant'",
        _srcs <= {"bootstrap", "local_grant"}, f"got {sorted(_srcs)}")

_MONEY_AFTER = _money_snapshot()
_assert("NO ledger entry, allocation, faab transaction or wallet was created "
        "by genesis or grants",
        _MONEY_AFTER == _MONEY_BEFORE, f"{_MONEY_BEFORE} -> {_MONEY_AFTER}")


app.dependency_overrides.clear()
tdb.teardown()

print(f"\n{'=' * 60}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
