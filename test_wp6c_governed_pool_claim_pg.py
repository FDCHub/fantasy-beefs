#!/usr/bin/env python3
"""
test_wp6c_governed_pool_claim_pg.py — WP6C · the Pool pick cutover.

THE QUESTION THIS SUITE ANSWERS:

    DOES THE POOL PICK A GM ACTUALLY MAKES PRODUCE A TICKET THE REV1.3
    SETTLEMENT ENGINE WILL PAY?

Before WP6C the answer was no, and the failure was silent. `POST /pool/pick`
wrote a `PoolBetPick` — the legacy three-pot prediction model — and answered
200. `betting/pool_settlement.settle_pool_instance` resolves winners from
`pool_claim` rows via `claims_for_instance`. The two tables never met. A GM
could pick, see their selection, watch the week settle, and receive nothing,
because as far as the engine was concerned nobody had entered.

WHAT THIS SUITE REFUSES TO DO, and the refusal is the point: it never calls
`betting.pool_claims.submit_claim` itself. WP6's own §6.3 had to, and labelled
it "ENGINE DEMONSTRATION, not a lifecycle pass", precisely because no product
path reached the engine. Every claim below is created by an authenticated GM
posting to the production route, and the payout in §9 is produced by the
production settlement route reading those claims. If the cutover were reverted,
§2 would find zero claims and §9 would pay nobody — there is no direct engine
call propping either up.

THE ONLY SUBSTITUTION IS THE TRANSPORT, exactly as WP2B, WP2B-C, WP2B-D and WP6
do: `YahooLiveTransport` is pointed at the offline recorded corpus. Routes,
authorization, the census, the engines and the ledger are production.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp6c-suite-secret")

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP6C suite cannot run:\n  {e}")
    sys.exit(2)

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402
import providers.yahoo.transport as yahoo_transport  # noqa: E402
from api.main import app  # noqa: E402
from auth.jwt_auth import hash_password  # noqa: E402
from db.schema import (  # noqa: E402
    League, LeagueCommissioner, Player, PoolBetPick, PoolClaim, PoolInstance,
    PoolPot, PoolPrediction, Projection, Roster, SessionLocal, Team, User,
    Wallet,
)
from ledger.ledger import balance_of, trial_balance  # noqa: E402
from providers.fixtures.replay import FixtureTransport  # noqa: E402
from test_support_wp2bc_league import (  # noqa: E402
    FROZEN_NOW, LEAGUE_ID, SEASON, TEAM_COUNT, seed_economic_league,
    snapshot_for,
)


class _FixtureLiveTransport(FixtureTransport):
    """The offline corpus transport, wearing the live transport's class API."""

    league_number = yahoo_transport.YahooLiveTransport.league_number

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(frozen_now=FROZEN_NOW)


yahoo_transport.YahooLiveTransport = _FixtureLiveTransport

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * min(len(title), 78))


PASSWORD = "wp6c-password"
COMM_EMAIL = "wp6c-comm@x.test"
OTHER_LEAGUE_ID = 77
OTHER_EMAIL = "wp6c-outsider@x.test"

print("=" * 78)
print("WP6C — GOVERNED POOL CLAIM CUTOVER")
print("=" * 78)


def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def bearer(email: str) -> dict:
    r = client().post("/auth/login",
                      data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def claim_rows() -> list[tuple]:
    """Every governed claim, as comparable tuples. The mutation witness."""
    with SessionLocal() as db:
        rows = [(c.pool_instance_id, c.team_id, c.selected_subject_type,
                 c.selected_subject_id)
                for c in db.query(PoolClaim).order_by(PoolClaim.id).all()]
        db.rollback()
    return rows


def legacy_rows() -> tuple[int, int]:
    """(`pool_bet_pick`, `pool_prediction`) counts — the legacy models."""
    with SessionLocal() as db:
        counts = (db.query(PoolBetPick).count(), db.query(PoolPrediction).count())
        db.rollback()
    return counts


# ══════════════════════════════════════════════════════════════════════════════
# §0 · BOOTSTRAP — fixture-only, exactly as WP6 declares it
# ══════════════════════════════════════════════════════════════════════════════

_section("§0 · bootstrap and governed Pool collection")

tdb.reset()

with SessionLocal() as db:
    league, teams = seed_economic_league(db)
    db.commit()
    team_ids = [t.id for t in teams]

with SessionLocal() as db:
    for idx, team_id in enumerate(team_ids):
        for j in range(9):
            player = Player(name=f"WP6C-T{idx + 1}-P{j}", position="WR",
                            nfl_team="KC")
            db.add(player)
            db.flush()
            db.add(Roster(team_id=team_id, player_id=player.id))
            db.add(Projection(
                player_id=player.id, week=1, season=config.CURRENT_SEASON,
                source="fantasypros",
                projected_points=10.0 + idx * 1.5 + j * 0.5,
                actual_points=9.0 + idx * 1.4 + j * 0.4))
    db.flush()

    pw = hash_password(PASSWORD)
    comm = User(email=COMM_EMAIL, hashed_password=pw, team_id=team_ids[0],
                role="commissioner")
    db.add(comm)
    for ordinal in range(2, TEAM_COUNT + 1):
        db.add(User(email=f"wp6c-gm{ordinal}@x.test", hashed_password=pw,
                    team_id=team_ids[ordinal - 1], role="gm"))
    db.flush()
    db.add(LeagueCommissioner(league_id=LEAGUE_ID, user_id=comm.id,
                              source="bootstrap"))

    # A SECOND LEAGUE, so cross-league isolation is tested against a real other
    # league rather than against a nonexistent id — a 404 for "no such league"
    # would prove nothing about isolation.
    other = League(id=OTHER_LEAGUE_ID, season=SEASON, name="WP6C Other League",
                   season_final_week=17, playoff_start_week=15)
    db.add(other)
    db.flush()
    outsider_team = Team(league_id=OTHER_LEAGUE_ID, team_name="Outsiders",
                         owner="Owner X", email="wp6c-out@example.invalid")
    db.add(outsider_team)
    db.flush()
    db.add(Wallet(team_id=outsider_team.id, balance=0.0))
    db.add(User(email=OTHER_EMAIL, hashed_password=pw,
                team_id=outsider_team.id, role="gm"))
    db.commit()
    OUTSIDER_TEAM = outsider_team.id

hdr = bearer(COMM_EMAIL)
gm = {i: bearer(f"wp6c-gm{i}@x.test") for i in range(2, TEAM_COUNT + 1)}
outsider = bearer(OTHER_EMAIL)

T1, T2, T3, T4, T5, T6 = team_ids

r = client().post(f"/league/{LEAGUE_ID}/season-allocation", headers=hdr)
_assert("§0: season allocation runs", r.status_code == 200,
        f"{r.status_code} {r.text[:160]}")
r = client().post(f"/league/{LEAGUE_ID}/week/1/open", headers=hdr)
_assert("§0: week 1 opens", r.status_code == 200,
        f"{r.status_code} {r.text[:160]}")

# The catalog and the provider-support measurement, exactly as WP6 §3 performs
# them: a slate cannot be drawn until four definitions pass BOTH gates, and gate
# 2 is a per-league measurement of what the provider payload actually carried.
import io  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402

import scripts.bootstrap_pool_catalog as bootstrap  # noqa: E402

with redirect_stdout(io.StringIO()):
    _boot = bootstrap.main([])
_assert("§0: the canonical Pool catalog loads", _boot == 0, str(_boot))

r = client().post(f"/league/{LEAGUE_ID}/pool/activate?week=1", headers=hdr)
_assert("§0: Pool support is measured through the production route",
        r.status_code == 200, f"{r.status_code} {r.text[:160]}")

# FIXTURE-ONLY, and WP6 §3 declares the identical step: the corpus observes at a
# frozen 2025 instant and gate 2 fails closed beyond 24 hours. This supplies the
# `measured_at` a live provider would have supplied. No gate rule is changed.
from providers.yahoo.identity import build_team_identity_resolver  # noqa: E402
from providers.yahoo.pool_source import measure_league_activation  # noqa: E402

with SessionLocal() as db:
    measure_league_activation(
        db, league_id=LEAGUE_ID,
        snapshot=snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 1),
        resolver=build_team_identity_resolver(db, league_id=LEAGUE_ID),
        measured_at=datetime.now(timezone.utc))
    db.commit()

r = client().post(f"/league/{LEAGUE_ID}/pool/collect/1", headers=hdr)
_assert("§0: governed Pool collection opens four funded occurrences",
        r.status_code == 200 and len(r.json().get("instance_ids") or []) == 4,
        f"{r.status_code} {r.text[:160]}")

with SessionLocal() as db:
    INSTANCES = {i.definition_key: i.id for i in db.query(PoolInstance)
                 .filter(PoolInstance.league_id == LEAGUE_ID,
                         PoolInstance.week == 1).all()}
    db.rollback()
RANK_KEY = "most_passing_yards"
RANK_ID = INSTANCES[RANK_KEY]

_assert("§0: the ledger opens balanced", trial_balance() == 0)


# ══════════════════════════════════════════════════════════════════════════════
# §1 · THE LEGACY PATH IS CLOSED
# ══════════════════════════════════════════════════════════════════════════════

_section("§1 · legacy Pool pick writes are closed for a governed league")

# THE BLOCKER, RESTATED AS A STANDING GUARD. Before WP6C the mounted pick route
# called `submit_pool_pick`, which wrote a row nothing settles. It is not merely
# unreferenced now — it refuses, for any league carrying Rev1.3 state, at the
# engine's own entry point, so a future scheduler or script cannot reopen the
# path the route just closed.
from betting.pool_engine import submit_pool_pick  # noqa: E402
from betting.pool_legacy_guard import LegacyPoolPathRefused  # noqa: E402

_before_legacy = legacy_rows()
with SessionLocal() as db:
    try:
        submit_pool_pick(league_id=LEAGUE_ID, team_id=T2,
                         bet_type="biggest_winner", pick_team_id=T1, week=1,
                         db=db)
        _refused = False
    except LegacyPoolPathRefused:
        _refused = True
    db.rollback()
_assert("§1: the legacy pick engine REFUSES a Rev1.3-governed league",
        _refused is True)
_assert("§1: and wrote nothing", legacy_rows() == _before_legacy,
        str(legacy_rows()))

status = client().post("/pool/predict", headers=gm[2], json={
    "league_id": LEAGUE_ID, "team_id": T2, "predicted_team_id": T1, "week": 1})
_assert("§1: the other legacy pick surface, /pool/predict, fails closed too",
        status.status_code == 409, f"{status.status_code}")
_assert("§1: and wrote no prediction row", legacy_rows() == _before_legacy,
        str(legacy_rows()))

# WHAT IS CALLED, not what is mentioned. The route's docstrings NAME the legacy
# function to explain what was cut over, so a substring search would report the
# opposite of the truth. This reads the call graph, exactly as
# test_s8_p4c4_pool_certification.py checks the ownership guards.
import ast  # noqa: E402

_pool_routes_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "api", "pool_routes.py"),
                        encoding="utf-8").read()
_called = {n.func.id for n in ast.walk(ast.parse(_pool_routes_src))
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
_assert("§1: the mounted pick route no longer CALLS the legacy engine",
        "submit_pool_pick" not in _called)
_assert("§1: it calls the certified governed one",
        "submit_claim" in _called)


# ══════════════════════════════════════════════════════════════════════════════
# §2 · THE PRODUCT PATH WRITES A GOVERNED CLAIM
# ══════════════════════════════════════════════════════════════════════════════

_section("§2 · an authenticated GM's pick creates a governed PoolClaim")

r = client().get(f"/pool/week/1?league_id={LEAGUE_ID}", headers=gm[2])
_assert("§2: a GM reads the week's governed occurrences through the product",
        r.status_code == 200 and len(r.json().get("pools") or []) == 4,
        f"{r.status_code} {r.text[:160]}")
week_view = r.json() if r.status_code == 200 else {}
_rank_view = next((p for p in week_view.get("pools", [])
                   if p["definition_key"] == RANK_KEY), {})

_assert("§2: the read offers the subjects the occurrence admits, and no others",
        sorted(s["subject_id"] for s in _rank_view.get("subjects", []))
        == sorted(team_ids),
        str([s["subject_id"] for s in _rank_view.get("subjects", [])]))
_assert("§2: a MATCHUP-scope occurrence offers MATCHUP subjects, not teams",
        all(s["subject_type"] == "MATCHUP" for s in next(
            (p for p in week_view["pools"] if p["scope"] == "MATCHUP"),
            {"subjects": []})["subjects"]))
_assert("§2: the GM holds no claim yet", _rank_view.get("my_subject_id") is None)
_assert("§2: and the week is open for claims",
        _rank_view.get("open_for_claims") is True
        and week_view.get("locked") is False, str(week_view.get("locked")))

_before = claim_rows()
_before_legacy = legacy_rows()
_wallets_before = {t: balance_of(f"wallet:{t}") for t in team_ids}

r = client().post("/pool/pick", headers=gm[2], json={
    "league_id": LEAGUE_ID, "team_id": T2, "week": 1,
    "pool_instance_id": RANK_ID, "subject_id": T1})
_assert("§2: the Pool pick control the product posts returns success",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
pick = r.json() if r.status_code == 200 else {}

_after = claim_rows()
_assert("§2: EXACTLY ONE governed PoolClaim was created",
        len(_after) == len(_before) + 1, f"{len(_before)} → {len(_after)}")
_assert("§2: it belongs to the correct team and the correct occurrence",
        (RANK_ID, T2, "TEAM", T1) in _after, str(_after))
_assert("§2: the subject_id is exact",
        pick.get("selected_subject_id") == T1
        and pick.get("selected_subject_type") == "TEAM", str(pick)[:160])
_assert("§2: NO legacy prediction row was written by the product path",
        legacy_rows() == _before_legacy == (0, 0), str(legacy_rows()))

_assert("§2: the confirmation reflects the persisted selection back",
        (next(p for p in pick["week"]["pools"]
              if p["pool_instance_id"] == RANK_ID)["my_subject_id"] == T1))
_assert("§2: and the occurrence now reports one entry",
        (next(p for p in pick["week"]["pools"]
              if p["pool_instance_id"] == RANK_ID)["claim_count"] == 1))

_assert("§2: the claim moved ZERO Credits",
        all(balance_of(f"wallet:{t}") == _wallets_before[t] for t in team_ids)
        and balance_of(f"pool:{LEAGUE_ID}") == 600,
        str(balance_of(f"pool:{LEAGUE_ID}")))
_assert("§2: and the trial balance is unchanged", trial_balance() == 0)

# ONE GM'S PICK IS THEIR OWN. A Pool is a blind prediction until it settles.
r = client().get(f"/pool/week/1?league_id={LEAGUE_ID}", headers=gm[3])
_assert("§2: another GM's read does NOT disclose that pick",
        next(p for p in r.json()["pools"]
             if p["pool_instance_id"] == RANK_ID)["my_subject_id"] is None)
_assert("§2: though the entry COUNT is visible to the league",
        next(p for p in r.json()["pools"]
             if p["pool_instance_id"] == RANK_ID)["claim_count"] == 1)


# ══════════════════════════════════════════════════════════════════════════════
# §3 · AUTHORITY AND LEAGUE ISOLATION
# ══════════════════════════════════════════════════════════════════════════════

_section("§3 · authority, impersonation and league isolation")


def _refusal(label: str, headers, body: dict, expected) -> None:
    """Post a refused pick and prove it changed nothing at all."""
    before, before_legacy = claim_rows(), legacy_rows()
    before_tb = trial_balance()
    resp = client().post("/pool/pick", headers=headers, json=body)
    ok = (resp.status_code in expected if isinstance(expected, (set, tuple))
          else resp.status_code == expected)
    _assert(label, ok, f"status {resp.status_code}: {resp.text[:130]}")
    _assert(f"{label} — with ZERO mutation",
            claim_rows() == before and legacy_rows() == before_legacy
            and trial_balance() == before_tb == 0)
    return resp


_refusal("§3: an ordinary GM cannot submit for ANOTHER team", gm[3],
         {"league_id": LEAGUE_ID, "team_id": T2, "week": 1,
          "pool_instance_id": RANK_ID, "subject_id": T1}, 403)

# THE COMMISSIONER GAINS NO IMPERSONATION AUTHORITY. `assert_wagering_team_owner`
# carries no role exemption, and WP6C did not add one — a Pool pick is a
# competitive choice, not an administrative act.
_refusal("§3: a COMMISSIONER cannot submit as another GM", hdr,
         {"league_id": LEAGUE_ID, "team_id": T2, "week": 1,
          "pool_instance_id": RANK_ID, "subject_id": T1}, 403)

_refusal("§3: a GM of ANOTHER league cannot claim this league's occurrence",
         outsider,
         {"league_id": LEAGUE_ID, "team_id": OUTSIDER_TEAM, "week": 1,
          "pool_instance_id": RANK_ID, "subject_id": T1}, 409)

# …and not by relabelling the request either: the occurrence is the authority on
# which league and week it belongs to.
_refusal("§3: nor by naming their OWN league on this league's occurrence",
         outsider,
         {"league_id": OTHER_LEAGUE_ID, "team_id": OUTSIDER_TEAM, "week": 1,
          "pool_instance_id": RANK_ID, "subject_id": T1}, 409)

_refusal("§3: a STALE occurrence — right league, wrong week — is refused",
         gm[2],
         {"league_id": LEAGUE_ID, "team_id": T2, "week": 2,
          "pool_instance_id": RANK_ID, "subject_id": T1}, 409)

anon = client().post("/pool/pick", json={
    "league_id": LEAGUE_ID, "team_id": T2, "week": 1,
    "pool_instance_id": RANK_ID, "subject_id": T1})
_assert("§3: an unauthenticated pick is refused",
        anon.status_code in (401, 403), str(anon.status_code))

r = client().get(f"/pool/week/1?league_id={LEAGUE_ID}", headers=outsider)
_assert("§3: and an outsider cannot even READ this league's Pool week",
        r.status_code == 403, str(r.status_code))


# ══════════════════════════════════════════════════════════════════════════════
# §4 · INVALID SUBJECT
# ══════════════════════════════════════════════════════════════════════════════

_section("§4 · invalid subject")

resp = _refusal("§4: a subject outside the league is refused", gm[3],
                {"league_id": LEAGUE_ID, "team_id": T3, "week": 1,
                 "pool_instance_id": RANK_ID, "subject_id": OUTSIDER_TEAM}, 409)
_assert("§4: and the refusal names the governed reason",
        (resp.json().get("detail") or {}).get("reason_code") == "INVALID_SUBJECT",
        str(resp.json())[:140])

_refusal("§4: a subject id that exists nowhere is refused", gm[3],
         {"league_id": LEAGUE_ID, "team_id": T3, "week": 1,
          "pool_instance_id": RANK_ID, "subject_id": 999_999}, 409)

# A TEAM ID IS NOT A MATCHUP ID. The scopes are separate namespaces, and a
# MATCHUP-scope occurrence must not accept one of its participants as a subject
# — POR §6.2: a matchup is one subject, never its two teams.
_matchup_view = next(p for p in week_view["pools"] if p["scope"] == "MATCHUP")
_refusal("§4: a TEAM id offered to a MATCHUP-scope occurrence is refused", gm[3],
         {"league_id": LEAGUE_ID, "team_id": T3, "week": 1,
          "pool_instance_id": _matchup_view["pool_instance_id"],
          "subject_id": T1}, 409)


# ══════════════════════════════════════════════════════════════════════════════
# §5 · DUPLICATE SUBMISSION
# ══════════════════════════════════════════════════════════════════════════════

_section("§5 · duplicate submission is governed, and stays one claim")

r = client().post("/pool/pick", headers=gm[2], json={
    "league_id": LEAGUE_ID, "team_id": T2, "week": 1,
    "pool_instance_id": RANK_ID, "subject_id": T1})
_assert("§5: resubmitting the SAME subject succeeds", r.status_code == 200,
        f"{r.status_code} {r.text[:140]}")
_assert("§5: … and is idempotent — still exactly one claim for that GM",
        sum(1 for c in claim_rows() if c[0] == RANK_ID and c[1] == T2) == 1,
        str([c for c in claim_rows() if c[0] == RANK_ID]))

r = client().post("/pool/pick", headers=gm[2], json={
    "league_id": LEAGUE_ID, "team_id": T2, "week": 1,
    "pool_instance_id": RANK_ID, "subject_id": T3})
_assert("§5: changing the pick before lock succeeds and REPLACES in place",
        r.status_code == 200 and r.json().get("replaced") is True,
        f"{r.status_code} {str(r.json())[:140]}")
_assert("§5: still exactly one claim, now carrying the new subject",
        [c for c in claim_rows() if c[0] == RANK_ID and c[1] == T2]
        == [(RANK_ID, T2, "TEAM", T3)],
        str([c for c in claim_rows() if c[0] == RANK_ID]))
_assert("§5: and no Credits moved for any of it", trial_balance() == 0)

# Restored to the winning subject for §9.
r = client().post("/pool/pick", headers=gm[2], json={
    "league_id": LEAGUE_ID, "team_id": T2, "week": 1,
    "pool_instance_id": RANK_ID, "subject_id": T1})
_assert("§5: and back again", r.status_code == 200)


# ══════════════════════════════════════════════════════════════════════════════
# §6 · THE LOCK
# ══════════════════════════════════════════════════════════════════════════════

_section("§6 · a late claim is refused, with zero mutation")

# The lock is the week's SHARED moment and the server owns it. Pinning
# `PoolPot.lock_time` into the past is how an operator-set lock reaches the
# engine — `pool_lock_time` prefers it over the derived kickoff — so this
# exercises the real boundary rather than a patched clock.
with SessionLocal() as db:
    pot = (db.query(PoolPot).filter(PoolPot.league_id == LEAGUE_ID,
                                    PoolPot.week == 1).first())
    _had_pot = pot is not None
    if pot is None:
        pot = PoolPot(league_id=LEAGUE_ID, week=1)
        db.add(pot)
    _saved_lock = pot.lock_time
    pot.lock_time = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()

r = client().get(f"/pool/week/1?league_id={LEAGUE_ID}", headers=gm[4])
_assert("§6: the read reports the week LOCKED once the moment has passed",
        r.json().get("locked") is True
        and all(not p["open_for_claims"] for p in r.json()["pools"]),
        str(r.json().get("locked")))

resp = _refusal("§6: a claim after the lock is refused", gm[4],
                {"league_id": LEAGUE_ID, "team_id": T4, "week": 1,
                 "pool_instance_id": RANK_ID, "subject_id": T1}, 409)
_assert("§6: and the refusal names the governed reason",
        (resp.json().get("detail") or {}).get("reason_code") == "WINDOW_CLOSED",
        str(resp.json())[:140])

with SessionLocal() as db:
    pot = (db.query(PoolPot).filter(PoolPot.league_id == LEAGUE_ID,
                                    PoolPot.week == 1).first())
    pot.lock_time = _saved_lock
    db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# §7 · THE REST OF THE FIELD PICKS
# ══════════════════════════════════════════════════════════════════════════════

_section("§7 · the rest of the field picks, through the product")

# T3 backs the same subject as T2; T4 and T5 back a different one. That split is
# what makes §9 able to tell a winner from a loser without asserting who wins.
for team, header, subject in ((T3, gm[3], T1), (T4, gm[4], T2), (T5, gm[5], T2)):
    r = client().post("/pool/pick", headers=header, json={
        "league_id": LEAGUE_ID, "team_id": team, "week": 1,
        "pool_instance_id": RANK_ID, "subject_id": subject})
    _assert(f"§7: team {team} claims subject {subject}", r.status_code == 200,
            f"{r.status_code} {r.text[:130]}")

CLAIMED = {T2: T1, T3: T1, T4: T2, T5: T2}
_assert("§7: four governed claims stand on the occurrence, one per GM",
        sorted((c[1], c[3]) for c in claim_rows() if c[0] == RANK_ID)
        == sorted(CLAIMED.items()),
        str([c for c in claim_rows() if c[0] == RANK_ID]))
_assert("§7: no legacy row exists anywhere", legacy_rows() == (0, 0),
        str(legacy_rows()))
_assert("§7: the whole claim phase moved zero Credits",
        trial_balance() == 0 and balance_of(f"pool:{LEAGUE_ID}") == 600,
        str(balance_of(f"pool:{LEAGUE_ID}")))


# ══════════════════════════════════════════════════════════════════════════════
# §8 · RESULTS ARRIVE
# ══════════════════════════════════════════════════════════════════════════════

_section("§8 · provider ingest and matchup finality")

r = client().post("/admin/tuesday-sync", headers=hdr,
                  json={"league_id": LEAGUE_ID, "week": 1, "mock_mode": True})
_assert("§8: the production weekly automation route runs", r.status_code == 200,
        f"{r.status_code} {r.text[:200]}")

# A SETTLED OCCURRENCE ACCEPTS NO FURTHER CLAIMS — proved in §9 after settlement.


# ══════════════════════════════════════════════════════════════════════════════
# §9 · SETTLEMENT PAYS THE REAL CLAIM
# ══════════════════════════════════════════════════════════════════════════════

_section("§9 · the production settlement route pays the product's own claims")

_wallets_pre = {t: balance_of(f"wallet:{t}") for t in team_ids}

r = client().post(f"/league/{LEAGUE_ID}/pool/settle/1", headers=hdr)
_assert("§9: week 1 Pool settlement succeeds through the production route",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
ps = r.json() if r.status_code == 200 else {}
by_key = {s["definition_key"]: s for s in ps.get("settled", [])}
_win = by_key.get(RANK_KEY, {})

_paid = sorted(_win.get("winning_team_ids") or [])

# THE WINNING SUBJECT IS INFERRED FROM THE PAYOUT, NOT ASSERTED IN ADVANCE. This
# suite must not encode which team wins week 1 of the corpus — that is the
# census's answer and hard-coding it would turn a data change into a mystery
# failure. What IS asserted is far stronger than an identity: that settlement
# partitioned the field EXACTLY along the subject lines the GMs' own product
# picks drew.
_winner_subjects = {CLAIMED[t] for t in _paid}
_assert("§9: the occurrence settled on a determined winning subject, and every "
        "paid GM had claimed the same one",
        _win.get("classification") == "CLAIMS_PRESENT"
        and len(_winner_subjects) == 1, f"{_paid} → {_winner_subjects}")

_subject = next(iter(_winner_subjects), None)
_expected_winners = sorted(t for t, s in CLAIMED.items() if s == _subject)
_expected_losers = sorted(t for t, s in CLAIMED.items() if s != _subject)

_assert("§9: there is at least one winning ticket AND at least one losing one, "
        "so this proves both directions",
        bool(_expected_winners) and bool(_expected_losers),
        f"winners={_expected_winners} losers={_expected_losers}")

# THE CRITICAL ASSERTION. The engine's winner set is exactly the set of GMs
# whose PRODUCT-SUBMITTED claim named the winning subject — every one of them,
# and nobody else. Nothing in this suite called the claim engine; the tickets
# being paid here came from `POST /pool/pick`.
_assert("§9: settlement consumed the REAL claims — the winners are exactly the "
        "GMs whose product pick named the winning subject",
        _paid == _expected_winners, f"{_paid} vs {_expected_winners}")

_pot = _win.get("pot_cents", 0)
_base, _rem = divmod(_pot, len(_expected_winners)) if _expected_winners else (0, 0)
_expected_pay = {t: _base + (1 if i < _rem else 0)
                 for i, t in enumerate(_expected_winners)}

_assert("§9: each winning GM received the exact §6.3 allocation",
        all(balance_of(f"wallet:{t}") - _wallets_pre[t] == _expected_pay[t]
            for t in _expected_winners),
        str({t: balance_of(f"wallet:{t}") - _wallets_pre[t]
             for t in _expected_winners}))
_assert("§9: every cent of the pot was distributed",
        sum(_expected_pay.values()) == _pot == _win.get("distributed_cents"),
        f"{sum(_expected_pay.values())} vs {_pot}")
_assert("§9: a LOSING GM received nothing",
        all(balance_of(f"wallet:{t}") == _wallets_pre[t]
            for t in _expected_losers),
        str({t: balance_of(f"wallet:{t}") - _wallets_pre[t]
             for t in _expected_losers}))
_assert("§9: and a GM who never picked received nothing",
        balance_of(f"wallet:{T6}") == _wallets_pre[T6])
_assert("§9: trial balance zero after settlement", trial_balance() == 0)

# ZERO-WINNER ROLLOVER IS UNCHANGED. No GM claimed the MATCHUP occurrences, so
# the subject layer's own outcome must still be what it was before the cutover.
#
# FOUND BY OUTCOME, NOT BY KEY — POR Rev 1.4 §4.2. This read
# `by_key["matchups_with_zero_total_turnovers"]`, which assumed WHICH definition
# the digest would put in a MATCHUP slot. The weekly scope composition is now a
# governed 3 TEAM + 1 MATCHUP, so that slot went to #95
# `matchups_where_neither_team_threw_an_interception` and the lookup returned an
# empty dict — a passing rollover reported as a missing one.
#
# The claim was never about a particular contest. It is that an occurrence
# NOBODY CLAIMED rolls its whole pot forward instead of paying, so it is asserted
# over the served classification. That is also the stronger statement: it holds
# for every unclaimed occurrence in the week rather than for one hand-picked key,
# and it cannot be silently defeated by a future rotation ruling.
_zeroes = [s for s in ps.get("settled", [])
           if s.get("classification") == "ZERO_ELIGIBLE_CLAIMS"]
_assert("§9: the week drew at least one occurrence nobody claimed, so the "
        "rollover path is genuinely exercised",
        bool(_zeroes),
        str([s.get("definition_key") for s in ps.get("settled", [])]))
_assert("§9: a zero-eligible-claims occurrence still rolls over, not pays",
        bool(_zeroes) and all(
            z.get("distributed_cents") == 0
            and z.get("rolled_over_cents") == z.get("pot_cents")
            for z in _zeroes),
        str(_zeroes)[:220])
_assert("§9: no occurrence paid out more than its pot",
        all(s["distributed_cents"] <= s["pot_cents"]
            for s in ps.get("settled", [])))

_wallets_post = {t: balance_of(f"wallet:{t}") for t in team_ids}
dup = client().post(f"/league/{LEAGUE_ID}/pool/settle/1", headers=hdr)
_assert("§9 (retry): a DUPLICATE settlement replays", dup.status_code == 200
        and all(s["replayed"] for s in dup.json().get("settled", [])),
        f"{dup.status_code}")
_assert("§9 (retry): and creates NO duplicate payout",
        all(balance_of(f"wallet:{t}") == _wallets_post[t] for t in team_ids)
        and trial_balance() == 0)

resp = _refusal("§9: a claim on a SETTLED occurrence is refused", gm[6],
                {"league_id": LEAGUE_ID, "team_id": T6, "week": 1,
                 "pool_instance_id": RANK_ID, "subject_id": T1}, 409)
_assert("§9: and the refusal names the governed reason",
        (resp.json().get("detail") or {}).get("reason_code")
        == "INSTANCE_SETTLED", str(resp.json())[:140])


# ══════════════════════════════════════════════════════════════════════════════
# §10 · THE BLOCKER IS CLEARED
# ══════════════════════════════════════════════════════════════════════════════

_section("§10 · WP6 blocker 2, cleared")

# SELF-AUDIT BY CALL GRAPH. A substring search would match this very assertion's
# own prose, so the needle is the parsed call set — the same technique §1 uses.
_this_calls = {n.func.id for n in ast.walk(ast.parse(
    open(os.path.abspath(__file__), encoding="utf-8").read()))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
_assert("§10: this suite never calls the claim engine itself — every claim it "
        "settled was created by a GM posting to the production route",
        "submit_claim" not in _this_calls, str(sorted(_this_calls))[:120])
_assert("§10: and the product's Pool pick surface produced payable tickets",
        len([c for c in claim_rows() if c[0] == RANK_ID]) == 4
        and _win.get("distributed_cents", 0) > 0)

print("\n" + "=" * 78)
if _failures:
    print(f"WP6C SUITE — FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("WP6C SUITE — ALL ASSERTIONS PASSED")