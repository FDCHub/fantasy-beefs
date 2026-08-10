#!/usr/bin/env python3
"""
test_s8_p4b1_fixture.py — Sprint 8 P4B-1 · the authoritative Rev 4.2 fixture.

WHAT THIS PROVES, AND WHY IT RUNS BEFORE ANY UI CHANGES. P4B-2 will point the
Rev 4.2 Ledger at real posted state, and the browser suites will then assert
money that came from this fixture. If the fixture were wrong, every one of
those assertions would be wrong in the same direction and would still agree
with each other — so the fixture has to be proven on its own, against the
backend, before a single renderer consumes it.

TWO INDEPENDENT ROUTES TO THE SAME POSITION. The seeded season is checked
against `economy.current_settle.current_settle()` directly AND through
`GET /league/{id}/ledger/me` on a real server. A mistake in the read model or
the route would show as a disagreement between them; a mistake in the fixture
would show as both disagreeing with the expectation map.

IT ALSO PROVES WHAT WAS *NOT* DONE. Held is 0 because no `ChallengeFundingLeg`
exists on the reachable path, and there is no season-winnings door. Both are
asserted as absences, because "we did not fabricate this" is exactly the kind
of claim that decays silently.
"""

from __future__ import annotations

import os
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP_DIR, 's8p4b1.db')}"
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from db.schema import (
    Base, ChallengeFundingLeg, League, LeagueCommissioner, SessionLocal, Team,
    User, engine,
)
from auth.jwt_auth import hash_password
from economy.current_settle import current_settle
from ledger.ledger import create_ledger_table, trial_balance
from payments.economy_config import get_league_economy_stop
from test_support_rev42_fixture import (
    DEFERRED_TO_P4C, EXPECTATION_MAP, FIXTURE_EXPECTED, FIXTURE_OPENING_SPLIT,
    _seed_accounting_fixture,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")


# ── Seed, in-process, through the same function the app server uses ──────────

Base.metadata.create_all(engine)
create_ledger_table()

PASSWORD = "sprint8-password"
GM_EMAIL, COMM_EMAIL = "gm@fixture.test", "comm@fixture.test"
SEASON = 2026

with SessionLocal() as db:
    league = League(name="Fixture League", season=SEASON)
    db.add(league); db.flush()

    gm_team = Team(team_name="Gravy Train", owner="A. Gm",
                   email=GM_EMAIL, league_id=league.id)
    comm_team = Team(team_name="The Braintrust", owner="A. Commissioner",
                     email=COMM_EMAIL, league_id=league.id)
    db.add_all([gm_team, comm_team]); db.flush()

    hashed = hash_password(PASSWORD)
    db.add_all([
        User(email=GM_EMAIL, hashed_password=hashed, team_id=gm_team.id, role="gm"),
        User(email=COMM_EMAIL, hashed_password=hashed, team_id=comm_team.id,
             role="commissioner"),
    ])
    db.flush()
    comm_user = db.query(User).filter(User.email == COMM_EMAIL).first()
    db.add(LeagueCommissioner(league_id=league.id, user_id=comm_user.id,
                              source="bootstrap"))
    db.flush()

    _seed_accounting_fixture(db, league, gm_team, comm_team)
    db.commit()

    LEAGUE_ID, GM_TEAM_ID = league.id, gm_team.id


print("=" * 68)
print("S8-P4B-1 — authoritative Rev 4.2 accounting fixture")
print("=" * 68)


# ── 1 · The fixture produces the expected position ───────────────────────────

_section("1 · current_settle() produces the expectation map's figures")

with SessionLocal() as db:
    settle = current_settle(db, team_id=GM_TEAM_ID, league_id=LEAGUE_ID,
                            season=SEASON)

DIRECT = {
    "wallet_cents": settle.wallet_cents,
    "weekly_min_live_cents": settle.weekly_min_live_cents,
    "min_reserve_cents": settle.min_reserve_cents,
    "expired_min_cents": settle.expired_min_cents,
    "in_play_cents": settle.in_play_cents,
    "receivable_cents": settle.receivable_cents,
    "assets_cents": settle.assets_cents,
    "season_advance_cents": settle.season_advance_cents,
    "topoff_issued_cents": settle.topoff_issued_cents,
    "obligations_cents": settle.obligations_cents,
    "current_settle_cents": settle.current_settle_cents,
}

for field, expected in sorted(DIRECT.items()):
    _assert(f"{field} == {FIXTURE_EXPECTED[field]}",
            expected == FIXTURE_EXPECTED[field],
            f"got {expected}")

_assert("the position's own arithmetic closes",
        settle.assets_cents - settle.obligations_cents
        == settle.current_settle_cents)
_assert("and it is the authoritative −$69, not the illustrative −$45",
        settle.current_settle_cents == -6_900,
        str(settle.current_settle_cents))

_assert("the whole seeded ledger conserves",
        trial_balance() == 0, f"imbalance {trial_balance()}")


# ── 2 · Held is zero, and nothing was fabricated to make it so ───────────────

_section("2 · Held is 0 because no reachable path creates challenge escrow")

from economy.challenge_escrow_view import team_open_challenge_escrow_cents  # noqa: E402

with SessionLocal() as db:
    held = team_open_challenge_escrow_cents(db, GM_TEAM_ID)
    leg_count = db.query(ChallengeFundingLeg).count()

_assert("held_open_challenges_cents is 0", held == 0, str(held))
_assert("NO ChallengeFundingLeg row was fabricated", leg_count == 0,
        f"{leg_count} legs exist")
_assert("so Held is a structural zero, not a coincidence of this fixture",
        held == 0 and leg_count == 0)


# ── 3 · No season-winnings accounting was invented ───────────────────────────

_section("3 · No season-winnings door or account was invented")

from sqlalchemy import text  # noqa: E402

with SessionLocal() as db:
    doors = {r[0] for r in db.execute(
        text("SELECT DISTINCT door FROM ledger_entries")).fetchall()}
    accounts = {r[0] for r in db.execute(
        text("SELECT DISTINCT account FROM ledger_entries")).fetchall()}

GOVERNED_DOORS = {
    "season_allocation", "approved_bab_topoff", "weekly_minimum_release",
    "weekly_minimum_expiry", "wager_placed", "wager_settled",
}
_assert("every door used is a governing production door",
        doors <= GOVERNED_DOORS, f"unexpected: {sorted(doors - GOVERNED_DOORS)}")
_assert("no award/winnings door was opened",
        not any("award" in d or "winning" in d for d in doors), str(sorted(doors)))
_assert("no award/winnings account exists",
        not any("award" in a or "winning" in a for a in accounts),
        str(sorted(a for a in accounts if "award" in a or "winning" in a)))
_assert("the GM's gain sits in the wallet, where the accounting puts it",
        settle.wallet_cents == 5_500)


# ── 4 · The opening split comes from the Economy Stop ────────────────────────

_section("4 · The season-opening split is the Stop's, not the live balance")

with SessionLocal() as db:
    stop = get_league_economy_stop(LEAGUE_ID, db)

_assert("the Stop's weekly-minimum reserve leg is $140",
        stop.min_reserve_cents == FIXTURE_OPENING_SPLIT["min_reserve_leg_cents"],
        str(stop.min_reserve_cents))
_assert("the Stop's championship reserve leg is $80",
        stop.reserve_cents == FIXTURE_OPENING_SPLIT["reserve_leg_cents"],
        str(stop.reserve_cents))
_assert("the two legs reconcile to the POSTED advance",
        stop.min_reserve_cents + stop.reserve_cents == settle.season_advance_cents,
        f"{stop.min_reserve_cents} + {stop.reserve_cents} "
        f"vs {settle.season_advance_cents}")

# The defect this guards against: binding the opening leg to the LIVE reserve
# balance, which has fallen to $90 as the weekly minimum released.
_assert("the live reserve balance is NOT the opening leg — they differ",
        settle.min_reserve_cents != stop.min_reserve_cents,
        f"live {settle.min_reserve_cents} vs opening {stop.min_reserve_cents}")


# ── 5 · The same figures arrive through the HTTP read model ──────────────────

_section("5 · GET /league/{id}/ledger/me reports the same position")

from fastapi.testclient import TestClient  # noqa: E402
from api.main import app  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)
r = client.post("/auth/session", json={"email": GM_EMAIL, "password": PASSWORD})
_assert("the fixture GM can sign in", r.status_code == 200, r.text[:120])

me = client.get("/auth/me").json()
_assert("/auth/me reports authoritative acting league context",
        me["capabilities"]["acting_league_id"] == LEAGUE_ID,
        str(me["capabilities"].get("acting_league_id")))
_assert("and the acting team", me["capabilities"]["acting_team_id"] == GM_TEAM_ID)
_assert("and does not report the context as ambiguous",
        me["capabilities"]["acting_context_ambiguous"] is False)

body = client.get(f"/league/{LEAGUE_ID}/ledger/me").json()

for field, expected in sorted(FIXTURE_EXPECTED.items()):
    _assert(f"HTTP {field} == {expected}", body.get(field) == expected,
            f"got {body.get(field)}")

_assert("every monetary field crossed the boundary as an integer",
        all(isinstance(v, int) for k, v in body.items() if k.endswith("_cents")))
_assert("the HTTP figure equals the direct call exactly",
        body["current_settle_cents"] == settle.current_settle_cents)


# ── 6 · The expectation map is internally honest ─────────────────────────────

_section("6 · The expectation map matches what the fixture actually produces")

STATUSES = {"KEEP EXACT", "REVISE EXACT", "UNRESOLVED"}
_assert("every row carries a governed status",
        all(row[4] in STATUSES for row in EXPECTATION_MAP),
        str([row[4] for row in EXPECTATION_MAP if row[4] not in STATUSES]))

_assert("every row carries a written reason",
        all(len(row[5]) > 20 for row in EXPECTATION_MAP))

# A KEEP EXACT row must actually be unchanged; a REVISE EXACT row must actually
# have changed. A map that said otherwise would be worse than no map.
bad_keep = [r[0] for r in EXPECTATION_MAP if r[4] == "KEEP EXACT" and r[2] != r[3]]
bad_revise = [r[0] for r in EXPECTATION_MAP
              if r[4] == "REVISE EXACT" and r[2] == r[3]]
_assert("KEEP EXACT rows really are unchanged", bad_keep == [], str(bad_keep))
_assert("REVISE EXACT rows really did change", bad_revise == [], str(bad_revise))

_assert("exactly two rows are revised, and they are Held and Current Settle",
        sorted(r[0] for r in EXPECTATION_MAP if r[4] == "REVISE EXACT")
        == ["Current Settle", "Held"])
_assert("exactly one row is unresolved, and it is Awards / Adj.",
        [r[0] for r in EXPECTATION_MAP if r[4] == "UNRESOLVED"] == ["Awards / Adj."])
_assert("an UNRESOLVED row carries no seeded number",
        all(r[3] is None for r in EXPECTATION_MAP if r[4] == "UNRESOLVED"))

# Every sourced row's seeded value must be what the backend produced.
MAP_TO_FIELD = {
    "Wallet": "wallet_cents", "Weekly Min Left": "weekly_min_live_cents",
    "Available": "available_cents", "In Play": "in_play_cents",
    "Held": "held_open_challenges_cents",
    "Weekly Reserve Not Released": "min_reserve_cents",
    "Weekly Min Out of Circulation": "expired_min_cents",
    "Skunk Fees": "receivable_cents",
    "Season Opening": "season_advance_cents",
    "Added Stakes / Top-Off": "topoff_issued_cents",
    "Current Settle": "current_settle_cents",
}
drift = [cell for cell, field in MAP_TO_FIELD.items()
         if next(r[3] for r in EXPECTATION_MAP if r[0] == cell) != body[field]]
_assert("every mapped cell's seeded value equals the served value",
        drift == [], str(drift))

_assert("the P4C-deferred cells are named and none is accounting",
        len(DEFERRED_TO_P4C) >= 3
        and all(len(d[1]) > 10 for d in DEFERRED_TO_P4C))


# ── Deferred ─────────────────────────────────────────────────────────────────

_section("Carried forward")
print("  [P4C]   Spec-2 activation. `economy/challenge_funding.py` is built and "
      "tested but fenced from the live application; `beefs/beef_engine.py` "
      "being reachable today is NOT a ruling that it is the final MVP path. "
      "P4C must reconcile/activate the approved Proposal Lifecycle for the "
      "live Action surface before MVP certification — after which Held becomes "
      "a non-zero subset of In Play and this fixture's Held row is revisited.")
print("  [P5]    Season allocation and Top-Off approval take row locks SQLite "
      "cannot execute, so this fixture posts under their doors directly. The "
      "services' locking behaviour is certified on PostgreSQL, not here.")


print("\n" + "=" * 68)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("S8-P4B-1 FIXTURE — all assertions PASSED")
