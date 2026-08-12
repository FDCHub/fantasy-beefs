"""
test_buyin_enforcement.py — B2, Finding 5.3: League.buyin_enforcement_active,
the commissioner-facing setter/getter, and get_buyin_gate()'s rewrite to
read it instead of LeagueTreasury.

Covers (per the spec's Section 4, Step 4):
  1. Enforcement off (the default) — gate inactive regardless of
     buy_in_paid, proven both via a direct get_buyin_gate() call and via
     one real HTTP round-trip (/bets/straight).
  2. Enforcement on + unpaid — HTTP 402 (existing behavior, unchanged).
  3. Enforcement on + paid — passes through (existing behavior, unchanged).
  4. Flag toggled mid-season — takes effect on the very next call, no
     stale state (no caching anywhere in the gate).
  5. The commissioner-only endpoint itself: non-commissioner gets 403;
     commissioner can flip it; GET reflects the current value.

Uses a temp SQLite DB so prod is never touched.
"""

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_buyin_enforcement.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.pop("STRIPE_SECRET_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from fastapi import HTTPException

from db.schema import (
    Base, engine, SessionLocal,
    League, LeagueCommissioner, Team, User, Wallet, Matchup, Player, Roster,
)
from auth.jwt_auth import get_current_gm, get_current_user, hash_password
from db.deps import get_db
from auth.allocation_gate import (
    get_season_allocation_gate as get_buyin_gate,
    set_allocation_enforcement_active as set_buyin_enforcement_active,
    get_allocation_enforcement_active as get_buyin_enforcement_active,
)
from ledger.ledger import post as ledger_post, create_ledger_table, balance_of

import api.main as api_main
from api.main import app

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
    def _fake_get_current_user():
        with SessionLocal() as db:
            return db.query(User).filter(User.id == user_id).first()
    # require_commissioner depends on get_current_user directly; get_buyin_gate's
    # own chain goes through get_current_gm. Override both so either path resolves
    # to the same fixed test user without needing a real JWT.
    app.dependency_overrides[get_current_gm]   = _fake_get_current_user
    app.dependency_overrides[get_current_user] = _fake_get_current_user


# ── Fixture: one league, one team, one GM (unpaid), one commissioner ──────────

with SessionLocal() as db:
    league = League(season=2025, name="B2-5.3 Test League", projection_source="fantasypros")
    db.add(league)
    db.flush()

    t1 = Team(league_id=league.id, team_name="Gate Test Team", owner="GM", email="gate_gm@t.com")
    t2 = Team(league_id=league.id, team_name="Opponent Team", owner="Opp", email="gate_opp@t.com")
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

    gm_unpaid = User(email="gate_gm_user@t.com", hashed_password=hash_password("x"),
                      team_id=t1.id, role="gm", buy_in_paid=0)
    comm = User(email="gate_comm@t.com", hashed_password=hash_password("x"),
                team_id=None, role="commissioner", buy_in_paid=0)
    db.add_all([gm_unpaid, comm])

    # WP5 — LEAGUE-SCOPED COMMISSIONER AUTHORITY. This fixture granted the
    # GLOBAL role="commissioner" and nothing else, which was sufficient when the
    # route checked a role. S8-P2 replaced that with league-scoped authority:
    # the global is_commissioner role is NOT the same question, and conflating
    # them is the exact confusion S8-P2 exists to remove. The route now refuses
    # correctly, so the FIXTURE is what was stale — this suite's subject is
    # buy-in enforcement, not who may act.
    #
    # The grant is the real one the product uses, so the 403 branch above still
    # proves what it always did: authority is required, and it is league-scoped.
    db.flush()
    db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                              source="bootstrap"))


    db.commit()
    league_id  = league.id
    t1_id      = t1.id
    wallet1_id = wallet1.id
    matchup_id = matchup.id
    gm_id      = gm_unpaid.id
    comm_id    = comm.id

# Fund the GM's BAB ledger wallet once — same test-only stand-in used
# throughout this session (no code path funds ledger wallets yet).
ledger_post([("world", -100_000_00), (f"wallet:{t1_id}", 100_000_00)], door="buy_in_paid")


# ── B2 gate retarget fixtures ────────────────────────────────────────────────
#
# The accepted B2 gate no longer reads User.buy_in_paid — it requires a
# SeasonAllocation row for (league, team, config.ALLOCATION_SEASON). These two
# helpers grant and revoke that row directly.
#
# The row is inserted rather than produced by activate_season_allocation()
# deliberately: the authoritative operation also posts the three-leg funding
# ledger entry, which would move wallet:{t1} and invalidate this file's
# existing ledger-balance assertions. The gate is NOT bypassed or patched —
# it still performs its own season-qualified lookup against a real row.
#
# buy_in_paid is still written alongside, so the suite keeps proving that the
# legacy column does not drive the decision either way.

import config as _config
from db.schema import SeasonAllocation as _SeasonAllocation
from payments.economy_config import DEFAULT_STOP as _STOP


def _grant_allocation(team_id: int, league_id: int) -> None:
    with SessionLocal() as db:
        exists = (
            db.query(_SeasonAllocation)
            .filter(_SeasonAllocation.league_id == league_id,
                    _SeasonAllocation.team_id == team_id,
                    _SeasonAllocation.season == _config.ALLOCATION_SEASON)
            .first()
        )
        if not exists:
            db.add(_SeasonAllocation(
                league_id     = league_id,
                team_id       = team_id,
                season        = _config.ALLOCATION_SEASON,
                buyin_cents   = _STOP.buyin_cents,
                min_reserve_cents  = _STOP.min_reserve_cents,
                reserve_cents = _STOP.reserve_cents,
            ))
            db.commit()


def _revoke_allocation(team_id: int, league_id: int) -> None:
    with SessionLocal() as db:
        db.query(_SeasonAllocation).filter(
            _SeasonAllocation.league_id == league_id,
            _SeasonAllocation.team_id == team_id,
            _SeasonAllocation.season == _config.ALLOCATION_SEASON,
        ).delete()
        db.commit()


def _bet_request():
    return {"matchup_id": matchup_id, "wallet_id": wallet1_id,
            "picked_team_id": t1_id, "amount": 10.0, "week": 1}


# ── ITEM 1: enforcement off (default) — gate inactive regardless of buy_in_paid ──

print("\nItem 1: enforcement off (default False) — gate inactive regardless of buy_in_paid")

with SessionLocal() as db:
    default_flag = db.query(League).filter(League.id == league_id).first().buyin_enforcement_active
_assert("league's buyin_enforcement_active defaults to False", default_flag is False, f"got {default_flag}")

with SessionLocal() as db:
    user = db.query(User).filter(User.id == gm_id).first()  # buy_in_paid == 0
    raised = False
    try:
        get_buyin_gate(current_user=user, db=db)
    except HTTPException:
        raised = True
_assert("direct call: unpaid GM passes when enforcement is off", not raised)

_grant_allocation(t1_id, league_id)
with SessionLocal() as db:
    user = db.query(User).filter(User.id == gm_id).first()
    user.buy_in_paid = 1
    db.commit()
    raised = False
    try:
        get_buyin_gate(current_user=user, db=db)
    except HTTPException:
        raised = True
_assert("direct call: allocated GM also passes when enforcement is off (same result either way)", not raised)

# Reset to unallocated/unpaid for the HTTP round-trip below
_revoke_allocation(t1_id, league_id)
with SessionLocal() as db:
    user = db.query(User).filter(User.id == gm_id).first()
    user.buy_in_paid = 0
    db.commit()

_set_current_user(gm_id)
resp_off = client.post("/bets/straight", json=_bet_request())
_assert(
    "HTTP: unpaid GM's bet succeeds (201) when enforcement is off",
    resp_off.status_code == 201,
    f"got {resp_off.status_code}: {resp_off.text}",
)


# ── ITEM 2 & 3: enforcement ON — unpaid blocked (402), paid passes ────────────

print("\nItem 2 & 3: enforcement ON — unpaid GM blocked (402), paid GM passes")

with SessionLocal() as db:
    active = set_buyin_enforcement_active(league_id, True, db, performer_id=comm_id)
_assert("set_buyin_enforcement_active returns True", active is True)

with SessionLocal() as db:
    flag_now = get_buyin_enforcement_active(league_id, db)
_assert("get_buyin_enforcement_active reflects the write", flag_now is True)

resp_on_unpaid = client.post("/bets/straight", json=_bet_request())
_assert(
    "HTTP: unpaid GM blocked with 402 once enforcement is on",
    resp_on_unpaid.status_code == 402,
    f"got {resp_on_unpaid.status_code}: {resp_on_unpaid.text}",
)

_grant_allocation(t1_id, league_id)
with SessionLocal() as db:
    user = db.query(User).filter(User.id == gm_id).first()
    user.buy_in_paid = 1
    db.commit()

resp_on_paid = client.post("/bets/straight", json=_bet_request())
_assert(
    "HTTP: allocated GM passes through (201) once enforcement is on",
    resp_on_paid.status_code == 201,
    f"got {resp_on_paid.status_code}: {resp_on_paid.text}",
)
_assert("wallet:t1 ledger balance debited by both successful bets so far ($10 in Item 1 + $10 here)", balance_of(f"wallet:{t1_id}") == 100_000_00 - 2000, f"got {balance_of(f'wallet:{t1_id}')}")


# ── ITEM 4: flag toggled mid-season takes effect immediately, no stale state ──

print("\nItem 4: toggling the flag takes effect on the very next call — no stale state")

_revoke_allocation(t1_id, league_id)
with SessionLocal() as db:
    user = db.query(User).filter(User.id == gm_id).first()
    user.buy_in_paid = 0  # back to unallocated/unpaid
    db.commit()

with SessionLocal() as db:
    set_buyin_enforcement_active(league_id, False, db)  # toggle OFF

# Fresh session, fresh call — must reflect the toggle immediately, no cache.
with SessionLocal() as db:
    user = db.query(User).filter(User.id == gm_id).first()
    raised = False
    try:
        get_buyin_gate(current_user=user, db=db)
    except HTTPException:
        raised = True
_assert("toggled OFF: unpaid GM passes immediately in a brand-new session", not raised)

with SessionLocal() as db:
    set_buyin_enforcement_active(league_id, True, db)  # toggle back ON

with SessionLocal() as db:
    user = db.query(User).filter(User.id == gm_id).first()
    raised = False
    try:
        get_buyin_gate(current_user=user, db=db)
    except HTTPException:
        raised = True
_assert("toggled back ON: unpaid GM blocked again immediately in a brand-new session", raised)


# ── ITEM 5: the commissioner-only endpoint itself ─────────────────────────────

print("\nItem 5: POST /payments/buyin-enforcement is commissioner-only")

with SessionLocal() as db:
    set_buyin_enforcement_active(league_id, False, db)  # reset for a clean read

_set_current_user(gm_id)  # non-commissioner
resp_forbidden = client.post("/payments/buyin-enforcement", json={"league_id": league_id, "active": True})
_assert("non-commissioner gets 403", resp_forbidden.status_code == 403, f"got {resp_forbidden.status_code}: {resp_forbidden.text}")

_set_current_user(comm_id)
resp_toggle = client.post("/payments/buyin-enforcement", json={"league_id": league_id, "active": True})
_assert("commissioner can flip it (200)", resp_toggle.status_code == 200, f"got {resp_toggle.status_code}: {resp_toggle.text}")
_assert("response reflects active=True", resp_toggle.json()["active"] is True, f"got {resp_toggle.json()}")

resp_read = client.get(f"/payments/buyin-enforcement/{league_id}")
_assert("GET reflects the current value (200, active=True)", resp_read.status_code == 200 and resp_read.json()["active"] is True, f"got {resp_read.status_code}: {resp_read.text}")

# Reset off, since the migration's ruled default is False for every league.
with SessionLocal() as db:
    set_buyin_enforcement_active(league_id, False, db)


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
