"""
test_league_commissioner_authority_pg.py — league-scoped commissioner authority.

Covers, on real PostgreSQL:

  MIGRATION
    1. runs on an empty database and creates the table with every named
       constraint;
    2. runs on a database that already holds users and leagues, preserving both;
    3. runs TWICE (the R-5 ruling) and the second run reports nothing done;
    4. drops nothing and backfills no authority row.

  MODEL CONSTRAINTS
    5. duplicate (league_id, user_id) is rejected;
    6. an invalid `source` value is rejected;
    7. assigned_by_user_id may be NULL.

  AUTHORIZATION
    8. same-league commissioner succeeds;
    9. cross-league commissioner is denied 403;
   10. ordinary GM denied 403;
   11. global commissioner with NO authority row denied 403;
   12. many-to-many: two commissioners on one league, one commissioner across
       two leagues;
   13. nonexistent league: 403 for an unauthorized caller (authorization
       precedes resource disclosure), and the route is reachable only once
       authorized;
   14. activation succeeds and is idempotent for co-commissioners.

  R-H1 REVERSE GATE PROOF
   15. enforcement ON + buy_in_paid=1 + NO qualifying SeasonAllocation -> 402.
       The legacy column cannot authorize access by itself.

Requires TEST_DATABASE_URL pointing at a dedicated, empty, _test-named,
non-Railway PostgreSQL database. No production system is contacted.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Commissioner-authority suite cannot run:\n  {e}")
    sys.exit(2)

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient

import config
from db.schema import (
    Base, engine, SessionLocal, League, LeagueCommissioner, SeasonAllocation,
    Team, User,
)
from db.deps import get_db
from auth.jwt_auth import get_current_user, hash_password
import api.main as api_main
from api.main import app

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        _failures.append(label)


client = TestClient(app)
_current = {"id": None}


def _set_current_user(user_id: int) -> None:
    _current["id"] = user_id

    def _override():
        with SessionLocal() as db:
            return db.query(User).filter(User.id == _current["id"]).first()

    app.dependency_overrides[get_current_user] = _override


def _mk_league(name: str) -> int:
    with SessionLocal() as db:
        lg = League(season=2025, name=name, projection_source="fantasypros")
        db.add(lg)
        db.commit()
        return lg.id


def _mk_team(league_id: int, name: str) -> int:
    with SessionLocal() as db:
        t = Team(league_id=league_id, team_name=name, owner=name,
                 email=f"{name}@auth.test")
        db.add(t)
        db.commit()
        return t.id


def _mk_user(email: str, role: str, team_id=None) -> int:
    with SessionLocal() as db:
        u = User(email=email, hashed_password=hash_password("x"),
                 team_id=team_id, role=role)
        db.add(u)
        db.commit()
        return u.id


def _grant(league_id: int, user_id: int, source="local_grant", by=None) -> None:
    with SessionLocal() as db:
        db.add(LeagueCommissioner(league_id=league_id, user_id=user_id,
                                  source=source, assigned_by_user_id=by))
        db.commit()


# ── ITEM 1-4: MIGRATION ──────────────────────────────────────────────────────

print("\nItem 1-4: migration on empty DB, on populated DB, and run twice")

# The harness already built every table from the models, so drop just this one
# to recreate the genuine "already-deployed database missing the table" case.
LeagueCommissioner.__table__.drop(engine, checkfirst=True)
_assert("precondition: league_commissioners absent before migration",
        "league_commissioners" not in inspect(engine).get_table_names())

# Populate users and leagues FIRST so the migration is proven non-destructive
# against existing data, not just against an empty schema.
_pre_league = _mk_league("Pre-existing league")
_pre_user = _mk_user("preexisting@auth.test", "gm")
with SessionLocal() as db:
    _pre_counts = (db.query(League).count(), db.query(User).count())

from db.migrations import migrate_league_commissioners as _mig

_run1 = _mig.run_migration()
_assert("migration run 1 created the table", _run1["table_created"] is True,
        f"got {_run1}")
_assert("league_commissioners now exists",
        "league_commissioners" in inspect(engine).get_table_names())

_insp = inspect(engine)
_uq = {u["name"] for u in _insp.get_unique_constraints("league_commissioners")}
_fk = {f["name"] for f in _insp.get_foreign_keys("league_commissioners")}
_ck = {c["name"] for c in _insp.get_check_constraints("league_commissioners")}
_assert("named unique constraint present",
        "uq_league_commissioner_league_user" in _uq, f"got {_uq}")
_assert("named source check constraint present",
        "ck_league_commissioner_source" in _ck, f"got {_ck}")
_assert("all three named foreign keys present",
        {"fk_league_commissioner_league", "fk_league_commissioner_user",
         "fk_league_commissioner_assigned_by"} <= _fk, f"got {_fk}")

with SessionLocal() as db:
    _post_counts = (db.query(League).count(), db.query(User).count())
    _authority_rows = db.query(LeagueCommissioner).count()
_assert("existing leagues and users preserved by the migration",
        _pre_counts == _post_counts, f"{_pre_counts} -> {_post_counts}")
_assert("migration BACKFILLED NOTHING — zero authority rows",
        _authority_rows == 0, f"got {_authority_rows}")

_run2 = _mig.run_migration()
_assert("migration run 2 reports table already present",
        _run2["table_created"] is False, f"got {_run2}")
_assert("migration run 2 added no constraints",
        _run2["constraints_added"] == [], f"got {_run2['constraints_added']}")
with SessionLocal() as db:
    _assert("second run still backfilled nothing",
            db.query(LeagueCommissioner).count() == 0)
    _assert("second run preserved leagues and users",
            (db.query(League).count(), db.query(User).count()) == _pre_counts)


# ── ITEM 5-7: MODEL CONSTRAINTS ──────────────────────────────────────────────

print("\nItem 5-7: duplicate rejection, source constraint, nullable assigner")

_lg_c = _mk_league("Constraint league")
_u_c = _mk_user("constraint@auth.test", "commissioner")
_grant(_lg_c, _u_c)

_dupe_raised = False
try:
    _grant(_lg_c, _u_c)
except IntegrityError:
    _dupe_raised = True
_assert("duplicate (league_id, user_id) rejected by the unique constraint",
        _dupe_raised)

_bad_source_raised = False
try:
    _grant(_lg_c, _mk_user("badsource@auth.test", "gm"), source="totally_made_up")
except IntegrityError:
    _bad_source_raised = True
_assert("invalid source value rejected by the check constraint", _bad_source_raised)

with SessionLocal() as db:
    _row = (db.query(LeagueCommissioner)
            .filter(LeagueCommissioner.league_id == _lg_c,
                    LeagueCommissioner.user_id == _u_c).first())
_assert("assigned_by_user_id may be NULL", _row.assigned_by_user_id is None)
_assert("created_at is populated", _row.created_at is not None)
_assert("source stored as given", _row.source == "local_grant", f"got {_row.source}")

for _src in ("yahoo_sync", "bootstrap"):
    _ok = True
    try:
        _grant(_lg_c, _mk_user(f"{_src}@auth.test", "gm"), source=_src)
    except IntegrityError:
        _ok = False
    _assert(f"accepted source value {_src!r} is permitted", _ok)


# ── ITEM 8-14: ROUTE AUTHORIZATION ───────────────────────────────────────────

print("\nItem 8-14: league-scoped authorization on POST /league/{id}/season-allocation")

league_a = _mk_league("League A")
league_b = _mk_league("League B")
for _n in ("A1", "A2"):
    _mk_team(league_a, _n)
for _n in ("B1", "B2"):
    _mk_team(league_b, _n)

comm_a   = _mk_user("comm_a@auth.test", "commissioner")
comm_a2  = _mk_user("comm_a2@auth.test", "commissioner")   # co-commissioner of A
comm_b   = _mk_user("comm_b@auth.test", "commissioner")
comm_ab  = _mk_user("comm_ab@auth.test", "commissioner")   # both leagues
comm_none = _mk_user("comm_none@auth.test", "commissioner")  # global role, no row
plain_gm = _mk_user("gm@auth.test", "gm")

_grant(league_a, comm_a)
_grant(league_a, comm_a2, by=comm_a)
_grant(league_b, comm_b)
_grant(league_a, comm_ab)
_grant(league_b, comm_ab)


def _activate(user_id: int, league_id: int):
    _set_current_user(user_id)
    return client.post(f"/league/{league_id}/season-allocation")


_r = _activate(comm_a, league_a)
_assert("League A commissioner CAN activate League A", _r.status_code == 200,
        f"got {_r.status_code}: {_r.text[:90]}")
_assert("activation created the allocation", _r.json().get("created") is True,
        f"got {_r.json()}")

_r = _activate(comm_a, league_b)
_assert("League A commissioner CANNOT activate League B (403)",
        _r.status_code == 403, f"got {_r.status_code}: {_r.text[:90]}")

_r = _activate(comm_b, league_b)
_assert("League B commissioner CAN activate League B", _r.status_code == 200,
        f"got {_r.status_code}: {_r.text[:90]}")

_r = _activate(plain_gm, league_a)
_assert("ordinary GM denied 403", _r.status_code == 403, f"got {_r.status_code}")
_r = _activate(plain_gm, league_b)
_assert("ordinary GM denied on the other league too", _r.status_code == 403,
        f"got {_r.status_code}")

_r = _activate(comm_none, league_a)
_assert("GLOBAL commissioner with NO authority row denied 403 — role alone is "
        "never sufficient", _r.status_code == 403, f"got {_r.status_code}")

_r = _activate(comm_a2, league_a)
_assert("co-commissioner of League A also authorized", _r.status_code == 200,
        f"got {_r.status_code}: {_r.text[:90]}")
_assert("co-commissioner activation is IDEMPOTENT — created=false, nothing reposted",
        _r.json().get("created") is False, f"got {_r.json()}")

_r = _activate(comm_ab, league_a)
_assert("commissioner of two leagues authorized for League A",
        _r.status_code == 200, f"got {_r.status_code}")
_r = _activate(comm_ab, league_b)
_assert("commissioner of two leagues authorized for League B",
        _r.status_code == 200, f"got {_r.status_code}")

_MISSING = 999_999
_r = _activate(comm_a, _MISSING)
_assert("nonexistent league: unauthorized caller gets 403, NOT 404 — league ids "
        "cannot be probed", _r.status_code == 403, f"got {_r.status_code}")
with SessionLocal() as db:
    db.add(LeagueCommissioner(league_id=league_a, user_id=plain_gm,
                              source="local_grant"))
    db.commit()
_r = _activate(plain_gm, league_a)
_assert("a GM granted explicit league authority IS authorized — authority is "
        "independent of role and team ownership", _r.status_code == 200,
        f"got {_r.status_code}: {_r.text[:90]}")

with SessionLocal() as db:
    _assert("no duplicate authority rows exist anywhere",
            db.query(LeagueCommissioner).count()
            == db.query(LeagueCommissioner.league_id, LeagueCommissioner.user_id)
                 .distinct().count())


# ── ITEM 15: R-H1 REVERSE GATE PROOF ─────────────────────────────────────────

print("\nItem 15: R-H1 — buy_in_paid=1 alone CANNOT open the gate (402)")

lg_h1 = _mk_league("R-H1 league")
tm_h1 = _mk_team(lg_h1, "H1team")
gm_h1 = _mk_user("rh1@auth.test", "gm", team_id=tm_h1)

with SessionLocal() as db:
    lg = db.query(League).filter(League.id == lg_h1).first()
    lg.buyin_enforcement_active = True
    u = db.query(User).filter(User.id == gm_h1).first()
    u.buy_in_paid = 1
    db.commit()

with SessionLocal() as db:
    _enf = db.query(League).filter(League.id == lg_h1).first().buyin_enforcement_active
    _paid = db.query(User).filter(User.id == gm_h1).first().buy_in_paid
    _alloc = (db.query(SeasonAllocation)
              .filter(SeasonAllocation.league_id == lg_h1,
                      SeasonAllocation.team_id == tm_h1,
                      SeasonAllocation.season == config.ALLOCATION_SEASON).count())
_assert("R-H1 precondition: enforcement is ACTIVE", bool(_enf) is True, f"got {_enf}")
_assert("R-H1 precondition: buy_in_paid == 1", _paid == 1, f"got {_paid}")
_assert("R-H1 precondition: NO qualifying SeasonAllocation exists",
        _alloc == 0, f"got {_alloc} rows")

from auth.allocation_gate import get_season_allocation_gate
from fastapi import HTTPException

_status = None
with SessionLocal() as db:
    _u = db.query(User).filter(User.id == gm_h1).first()
    try:
        get_season_allocation_gate(current_user=_u, db=db)
    except HTTPException as e:
        _status = e.status_code

_assert("R-H1: the gate REJECTS with 402 despite buy_in_paid=1",
        _status == 402, f"got {_status}")

# Complementary direction, retained: a valid allocation passes with buy_in_paid=0.
with SessionLocal() as db:
    from payments.economy_config import DEFAULT_STOP
    db.add(SeasonAllocation(league_id=lg_h1, team_id=tm_h1,
                            season=config.ALLOCATION_SEASON,
                            buyin_cents=DEFAULT_STOP.buyin_cents,
                            min_reserve_cents=DEFAULT_STOP.min_reserve_cents,
                            reserve_cents=DEFAULT_STOP.reserve_cents))
    u = db.query(User).filter(User.id == gm_h1).first()
    u.buy_in_paid = 0
    db.commit()

_passed = False
with SessionLocal() as db:
    _u = db.query(User).filter(User.id == gm_h1).first()
    try:
        get_season_allocation_gate(current_user=_u, db=db)
        _passed = True
    except HTTPException:
        _passed = False
_assert("R-H1 complement: a valid allocation PASSES with buy_in_paid=0 — the "
        "allocation alone is what authorizes", _passed)


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
