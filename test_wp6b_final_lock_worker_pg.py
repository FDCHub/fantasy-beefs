#!/usr/bin/env python3
"""
test_wp6b_final_lock_worker_pg.py — WP6B · the production Dynamic Final Lock
worker.

THE QUESTION THIS SUITE ANSWERS:

    DOES A RUNNING FANTASYSTAKES SYSTEM PRICE A HANDSHAKEN DYNAMIC WAGER WITH NO
    HUMAN DOING ANYTHING, AT THE GOVERNED TIME, EXACTLY ONCE?

WP6 proved `economy.dynamic_challenge.run_final_lock` certified and CALLERLESS:
a GM could issue and handshake a Dynamic challenge through the product and then
watch both sides' escrow sit forever. This suite certifies `workers.final_lock`,
the scheduled system process that calls it, and it certifies the worker ONLY —
every economic rule it exercises was already certified by
`test_p3_d2_dynamic_final_lock_pg.py` and is asserted here to prove the worker
did not disturb it, not to re-establish it.

WHAT IS PRODUCTION HERE AND WHAT IS FIXTURE. Challenges are created and
handshaken through the real HTTP routes by authenticated GMs. Final Lock is
driven by `workers.final_lock.run_once`, which is the deployed entry point —
`Procfile`'s `final_lock` process and `railway.final_lock.toml` both invoke the
same module. Nothing in this suite calls `run_final_lock` directly, because a
suite that did would be certifying the engine again rather than its caller.
League seeding, rosters, projections and the kickoff schedule are fixture, as in
WP6; no production route ingests them.

TIME IS CONTROLLED, NEVER SLEPT ON. Every worker invocation is given an explicit
`now`, computed from the same kickoff `_nfl_lock_time` will return, so "too
early", "due" and "late" are exact positions relative to the governed instant
rather than races against the wall clock.

THE ACTOR RULE IS ASSERTED, NOT ASSUMED. §1 proves no HTTP surface was added and
that the worker is reachable only as a process — Rev 9 §5.5's "not an end user,
not a GM, not a commissioner, not reachable from any HTTP route" is a
requirement on this package, and WP6 explicitly refused to manufacture a pass by
violating it.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp6b-suite-secret")
os.environ.pop("ANTHROPIC_API_KEY", None)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP6B worker suite cannot run:\n  {e}")
    sys.exit(2)

import threading  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import config  # noqa: E402
import providers.yahoo.transport as yahoo_transport  # noqa: E402
from api.main import app  # noqa: E402
from db.schema import (  # noqa: E402
    Bet, BeefChallenge, ChallengeFinalLock, ChallengeFinalLockClaim,
    NflSchedule, SessionLocal,
)
from ledger.ledger import LedgerEntry, balance_of, trial_balance  # noqa: E402
from providers.fixtures.replay import FixtureTransport  # noqa: E402
from test_support_wp2bc_league import (  # noqa: E402
    FROZEN_NOW, LEAGUE_ID, TEAM_COUNT, seed_economic_league, snapshot_for,
)
from test_support_wp6b import (  # noqa: E402
    COMM_EMAIL, PASSWORD, gm_email, seed_wp6b_fixture, week_kickoff,
)

# THE WORKER UNDER CERTIFICATION. Imported after the harness bound the test
# database, exactly as every other engine import in these suites is.
import workers.final_lock as flw  # noqa: E402


class _FixtureLiveTransport(FixtureTransport):
    league_number = yahoo_transport.YahooLiveTransport.league_number

    def __init__(self, *a, **kw) -> None:
        super().__init__(frozen_now=FROZEN_NOW)


yahoo_transport.YahooLiveTransport = _FixtureLiveTransport

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}{f' — {detail}' if detail else ''}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}\n" + "─" * min(len(title), 78))


WEEK = 1
#: Large enough that the Derived ceiling and the Final-Lock refund are both
#: tens of cents rather than single ones, and small enough that one GM can fund
#: an Anchor AND an opponent's ceiling out of a single week's $10 minimum.
ANCHOR = 3.00
KICKOFF = week_kickoff(WEEK)
TOO_EARLY = KICKOFF - timedelta(hours=1)
DUE = KICKOFF
LATE = KICKOFF + timedelta(days=7)

ROOT = os.path.dirname(os.path.abspath(__file__))

print("=" * 78)
print("WP6B — PRODUCTION DYNAMIC FINAL LOCK WORKER CERTIFICATION")
print("=" * 78)


def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def bearer(email: str) -> dict:
    r = client().post("/auth/login",
                      data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def anchor_acct(cid: int) -> str:
    return f"escrow:challenge:{cid}:anchor"


def derived_acct(cid: int) -> str:
    return f"escrow:challenge:{cid}:derived"


def escrow_pair(cid: int) -> tuple[int, int]:
    return balance_of(anchor_acct(cid)), balance_of(derived_acct(cid))


def spendable(team_id: int, week: int = 1) -> int:
    """A GM's own funds, across BOTH accounts a Handshake may draw them from.

    THE REFUND DOES NOT NECESSARILY LAND IN THE WALLET, and asserting that it
    does would be asserting a funding shape rather than a conservation law.
    `_reverse` returns money to its ORIGINAL funding sources through Spec 2's
    strict reverse-leg machinery, and the Handshake funds min-first — so a
    ceiling funded out of the Weekly Minimum is refunded back into the Weekly
    Minimum. Summing both is what makes "the opponent got its Credits back" a
    statement about the GM rather than about one account.
    """
    return balance_of(f"wallet:{team_id}") + balance_of(f"min:{team_id}:{week}")


def entry_count() -> int:
    with SessionLocal() as db:
        n = db.query(LedgerEntry).count()
        db.rollback()
    return n


def claims_for(cid: int) -> list[ChallengeFinalLockClaim]:
    with SessionLocal() as db:
        rows = (db.query(ChallengeFinalLockClaim)
                .filter(ChallengeFinalLockClaim.challenge_id == cid).all())
        db.expunge_all()
        db.rollback()
    return rows


def bets_for(cid: int) -> list[Bet]:
    with SessionLocal() as db:
        rows = db.query(Bet).filter(Bet.beef_challenge_id == cid).all()
        db.expunge_all()
        db.rollback()
    return rows


def final_lock_row(cid: int):
    with SessionLocal() as db:
        row = (db.query(ChallengeFinalLock)
               .filter(ChallengeFinalLock.challenge_id == cid).first())
        db.expunge_all()
        db.rollback()
    return row


def outcome_for(result, cid: int):
    return next((o for o in result.outcomes if o.challenge_id == cid), None)


# ══════════════════════════════════════════════════════════════════════════════
# §1 · THE GOVERNING ACTOR RULE, AND THE PRODUCTION WIRING
# ══════════════════════════════════════════════════════════════════════════════

_section("§1 · Rev 9 §5.5 actor rule and the production invocation path")

_routes = sorted({getattr(rt, "path", "") for rt in app.routes})
_lock_routes = [p for p in _routes
                if any(k in p.lower() for k in ("final", "lock", "dynamic"))]
_assert("§1: NO HTTP route exposes Final Lock — not for a GM, not for a "
        "commissioner, not for anyone", _lock_routes == [], str(_lock_routes))

with open(os.path.join(ROOT, "workers", "final_lock.py"), encoding="utf-8") as fh:
    _worker_src = fh.read()
_assert("§1: the worker module defines no route, router or ASGI app — it is a "
        "process, and a process is the only thing Rev 9 §5.5 permits",
        not any(tok in _worker_src for tok in
                ("APIRouter", "@app.", "FastAPI", "add_api_route")),
        "worker source declares an HTTP surface")

_assert("§1: nothing in api/ imports the worker, so no request can reach it",
        not any("workers.final_lock" in open(os.path.join(ROOT, "api", f),
                                             encoding="utf-8").read()
                for f in os.listdir(os.path.join(ROOT, "api"))
                if f.endswith(".py")))

# THE CALLER NOW EXISTS. This is the exact walk WP6 §12 ran to prove it did not.
_callers = []
for _dp, _dn, _fn in os.walk(ROOT):
    _dn[:] = [d for d in _dn if d not in (".git", "__pycache__", "node_modules")]
    for f in _fn:
        if not f.endswith(".py") or f.startswith("test_"):
            continue
        if f == "dynamic_challenge.py":
            continue
        try:
            with open(os.path.join(_dp, f), encoding="utf-8") as fh:
                txt = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        if "run_final_lock" in txt or "acquire_final_lock_claim" in txt:
            _callers.append(os.path.relpath(os.path.join(_dp, f), ROOT)
                            .replace("\\", "/"))
_assert("§1: run_final_lock now HAS a production caller, and exactly one",
        _callers == ["workers/final_lock.py"], str(_callers))

with open(os.path.join(ROOT, "Procfile"), encoding="utf-8") as fh:
    _procfile = fh.read()
_assert("§1: the deployment declares the worker as its own process type",
        "final_lock: python -m workers.final_lock --loop" in _procfile,
        _procfile.strip().replace("\n", " | "))
_assert("§1: and a Railway service definition exists for it",
        os.path.exists(os.path.join(ROOT, "railway.final_lock.toml")))
_assert("§1: `python -m workers.final_lock` is a real entry point",
        os.path.exists(os.path.join(ROOT, "workers", "__init__.py"))
        and "if __name__ == \"__main__\":" in _worker_src)

_assert("§1: the worker reuses the GOVERNED timing helper rather than "
        "recomputing kickoff",
        flw._nfl_lock_time is __import__(
            "betting.pool_engine", fromlist=["_nfl_lock_time"])._nfl_lock_time
        and flw._nfl_lock_time is __import__(
            "beefs.beef_engine", fromlist=["_nfl_lock_time"])._nfl_lock_time,
        "worker/beef_engine/pool_engine must share one kickoff function")


# ══════════════════════════════════════════════════════════════════════════════
# §2 · FIXTURE, AND FIVE HANDSHAKEN DYNAMIC CHALLENGES
# ══════════════════════════════════════════════════════════════════════════════

_section("§2 · fixture and five handshaken Dynamic challenges (FIXTURE-ONLY "
         "seeding; challenges through the product)")

tdb.reset()

with SessionLocal() as db:
    league, teams = seed_economic_league(db)
    db.commit()

with SessionLocal() as db:
    team_ids, _comm_id = seed_wp6b_fixture(db, team_count=TEAM_COUNT,
                                           league_id=LEAGUE_ID)
    db.commit()

T1, T2, T3, T4, T5, T6 = team_ids
hdr = bearer(COMM_EMAIL)
gm = {i: bearer(gm_email(i)) for i in range(2, TEAM_COUNT + 1)}
# The commissioner is also the GM of team 1 and wagers as one. `/beef/*` guards
# on team OWNERSHIP, never on role — S8-P4C-1R settled that holding the role is
# not a way of being a participant — so this is the ordinary owner path.
GM_OF = {T1: hdr, T2: gm[2], T3: gm[3], T4: gm[4], T5: gm[5], T6: gm[6]}

# FIXTURE-ONLY — week 1 matchups from the offline corpus. `_create_bet` resolves
# each side's Matchup, so Final Lock cannot write Bet rows for a week the
# provider has never described.
from providers.yahoo.persist import refresh_league_week  # noqa: E402

with SessionLocal() as db:
    refresh_league_week(db, snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW),
                                         WEEK), now=FROZEN_NOW)
    db.commit()

r = client().post(f"/league/{LEAGUE_ID}/season-allocation", headers=hdr)
_assert("§2: season allocation runs through the production route",
        r.status_code == 200, f"{r.status_code} {r.text[:160]}")
r = client().post(f"/league/{LEAGUE_ID}/week/{WEEK}/open", headers=hdr)
_assert("§2: Week Open releases the Weekly Minimum",
        r.status_code == 200, f"{r.status_code} {r.text[:160]}")


def handshake(issuer: int, opponent: int, week: int = WEEK) -> tuple[int, dict]:
    """Issue and handshake ONE Dynamic challenge through the production routes."""
    resp = client().post("/beef/challenge", headers=GM_OF[issuer], json={
        "challenger_team_id": issuer, "challenged_team_id": opponent,
        "week": week, "bet_type": "straight", "amount": ANCHOR,
        "challenge_mode": "dynamic"})
    assert resp.status_code == 201, f"issue {issuer}->{opponent}: {resp.text}"
    cid = resp.json()["challenge_id"]
    resp = client().post("/beef/respond", headers=GM_OF[opponent],
                         json={"challenge_id": cid, "accept": True})
    assert resp.status_code == 200, f"handshake {cid}: {resp.text}"
    out = dict(resp.json())
    # The frozen model HASH is not on the wire — the response carries the
    # version id only. It is read from the challenge row, which is where the
    # Handshake froze it and where Final Lock will read it back from.
    with SessionLocal() as db:
        ch = db.query(BeefChallenge).filter(BeefChallenge.id == cid).one()
        out["model_config_hash"] = ch.dynamic_model_config_hash
        db.rollback()
    return cid, out


# A DESCENDING RING, and the direction is a funding constraint rather than a
# preference. The fixture's projections rise with team ordinal, and the Derived
# ceiling is `floor(anchor / p_issuer × p_opponent)` — so an UNDERDOG issuer
# demands a ceiling several times its own anchor from the favourite, and one
# week's $10 minimum cannot fund two of those. Issuing favourite-to-underdog
# keeps every ceiling small enough that each GM can be both an issuer and an
# opponent inside one week, which is what lets five challenges coexist.
A, hs_a = handshake(T6, T5)      # the main timing / economics subject
B, hs_b = handshake(T5, T4)      # the concurrency race
C, hs_c = handshake(T4, T3)      # stale-claim recovery
D, hs_d = handshake(T3, T2)      # deterministic failure and rollback
E, hs_e = handshake(T2, T1)      # the late-lock subject; untouched until §10
ALL = (A, B, C, D, E)

_assert("§2: five Dynamic challenges handshook through POST /beef/challenge "
        "and POST /beef/respond", len(set(ALL)) == 5, str(ALL))
_assert("§2: every one funded BOTH sides' maximum exposure into per-side escrow",
        all(all(v > 0 for v in escrow_pair(c)) for c in ALL),
        str({c: escrow_pair(c) for c in ALL}))
_assert("§2: each issuer's Anchor escrow equals the anchor stake exactly",
        all(balance_of(anchor_acct(c)) == int(ANCHOR * 100) for c in ALL),
        str({c: balance_of(anchor_acct(c)) for c in ALL}))
_assert("§2: each opponent funded its full Derived CEILING",
        all(balance_of(derived_acct(c)) == hs["opponent_ceiling_cents"]
            for c, hs in ((A, hs_a), (B, hs_b), (C, hs_c), (D, hs_d), (E, hs_e))),
        str({c: balance_of(derived_acct(c)) for c in ALL}))
_assert("§2: NOT ONE Bet row exists yet — the Derived side is priced at Final "
        "Lock", all(len(bets_for(c)) == 0 for c in ALL),
        str({c: len(bets_for(c)) for c in ALL}))
_assert("§2: and no Final-Lock claim has ever been taken",
        all(claims_for(c) == [] for c in ALL))
_assert("§2: trial balance zero after five handshakes",
        trial_balance() == 0, str(trial_balance()))

print(f"     kickoff (governed, from _nfl_lock_time) = {KICKOFF.isoformat()}")

_section("§2b · a SECOND league, with its own handshaken Dynamic challenge")

# A REAL SECOND LEAGUE, not a second challenge wearing a different label. League
# isolation is only meaningfully tested against a league the worker could
# plausibly have swept: same season, same week, same governed kickoff (the NFL
# schedule is league-agnostic), different league id.
L2 = 20
L2_COMM = "wp6b-l2-comm@x.test"
L2_GM = "wp6b-l2-gm@x.test"

with SessionLocal() as db:
    from auth.jwt_auth import hash_password
    from db.schema import (
        League, LeagueCommissioner, Matchup, Player, Projection, Roster, Team,
        User, Wallet,
    )
    db.add(League(id=L2, season=config.LOCK_SEASON,
                  name="WP6B Isolation League", projection_source="fantasypros",
                  season_final_week=17, playoff_start_week=15))
    db.flush()
    l2_teams = []
    for ordinal in (1, 2):
        t = Team(league_id=L2, team_name=f"WP6B-L2 Team {ordinal}",
                 owner=f"L2 Owner {ordinal}",
                 email=f"wp6b-l2-team{ordinal}@example.invalid")
        db.add(t)
        db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        l2_teams.append(t)
    db.flush()
    # Team 1 is deliberately the stronger side, so it can issue at a small
    # Derived ceiling exactly as league 19's ring does.
    for idx, t in enumerate(l2_teams):
        for j in range(9):
            p = Player(name=f"WP6B-L2-T{idx + 1}-P{j}", position="WR",
                       nfl_team="KC")
            db.add(p)
            db.flush()
            db.add(Roster(team_id=t.id, player_id=p.id))
            db.add(Projection(player_id=p.id, week=WEEK,
                              season=config.CURRENT_SEASON, source="fantasypros",
                              projected_points=10.3 - idx * 0.3 + j * 0.5,
                              actual_points=15.0 - idx * 1.4 + j * 0.4))
    db.add(Matchup(league_id=L2, week=WEEK, home_team_id=l2_teams[0].id,
                   away_team_id=l2_teams[1].id, home_score=0.0, away_score=0.0))
    pw = hash_password(PASSWORD)
    c2 = User(email=L2_COMM, hashed_password=pw, team_id=l2_teams[0].id,
              role="commissioner")
    db.add(c2)
    db.add(User(email=L2_GM, hashed_password=pw, team_id=l2_teams[1].id,
                role="gm"))
    db.flush()
    db.add(LeagueCommissioner(league_id=L2, user_id=c2.id, source="bootstrap"))
    db.commit()
    L2A, L2B = l2_teams[0].id, l2_teams[1].id

hdr2, gm2 = bearer(L2_COMM), bearer(L2_GM)
r = client().post(f"/league/{L2}/season-allocation", headers=hdr2)
_assert("§2b: the second league allocates through the production route",
        r.status_code == 200, f"{r.status_code} {r.text[:160]}")
r = client().post(f"/league/{L2}/week/{WEEK}/open", headers=hdr2)
_assert("§2b: and opens its week", r.status_code == 200,
        f"{r.status_code} {r.text[:160]}")

GM_OF[L2A], GM_OF[L2B] = hdr2, gm2
X, hs_x = handshake(L2A, L2B)
_assert("§2b: a Dynamic challenge is handshaken in the SECOND league, at the "
        "same week and the same governed kickoff",
        all(v > 0 for v in escrow_pair(X)) and not bets_for(X),
        f"challenge {X}: {escrow_pair(X)}")


# ══════════════════════════════════════════════════════════════════════════════
# §3 · TIMING — TOO EARLY IS NOT A LOCK, AND IS NOT A CLAIM EITHER
# ══════════════════════════════════════════════════════════════════════════════

_section("§3 · too early → no lock (and no claim taken)")

EVERY = ALL + (X,)
_escrow_before = {c: escrow_pair(c) for c in EVERY}
_entries_before = entry_count()

_early = flw.run_once(worker_id="worker-early", now=TOO_EARLY)
_assert("§3: the worker DISCOVERS every challenge awaiting Final Lock, across "
        "both leagues", _early.examined == 6, _early.summary())
_assert("§3: and locks none of them, because the earliest covered kickoff has "
        "not arrived",
        all(o.status == flw.NOT_DUE for o in _early.outcomes), _early.summary())
_assert("§3: the due time it reports IS the governed kickoff, to the second",
        all(o.due_at == KICKOFF for o in _early.outcomes),
        str({o.challenge_id: str(o.due_at) for o in _early.outcomes}))
_assert("§3: NO execution claim was taken — an early claim would hold the "
        "execution right for the full TTL against the worker that arrives on "
        "time", all(claims_for(c) == [] for c in EVERY))
_assert("§3: no Bet rows, no frozen results", all(not bets_for(c) for c in EVERY)
        and all(final_lock_row(c) is None for c in EVERY))
_assert("§3: not one ledger entry was written",
        entry_count() == _entries_before, f"{entry_count()} vs {_entries_before}")
_assert("§3: every escrow balance is byte-identical",
        {c: escrow_pair(c) for c in EVERY} == _escrow_before)

_section("§3b · no governed kickoff → no lock (fail-closed, not fire-now)")

with SessionLocal() as db:
    db.query(NflSchedule).filter(NflSchedule.season == config.LOCK_SEASON,
                                 NflSchedule.week == WEEK).delete()
    db.commit()

_blind = flw.run_once(worker_id="worker-blind", now=LATE)
_assert("§3b: with the week's schedule absent the worker refuses to answer "
        "'due', even long after the real kickoff",
        all(o.status == flw.SCHEDULE_NOT_READY for o in _blind.outcomes),
        _blind.summary())
_assert("§3b: and still takes no claim and posts nothing",
        all(claims_for(c) == [] for c in EVERY)
        and entry_count() == _entries_before)

with SessionLocal() as db:
    db.add(NflSchedule(season=config.LOCK_SEASON, week=WEEK,
                       home_team=f"WP6B-H{WEEK}", away_team=f"WP6B-A{WEEK}",
                       kickoff_utc=KICKOFF.replace(tzinfo=None)))
    db.commit()

_section("§3c · --dry-run reports dueness and claims nothing")

_dry = flw.run_once(worker_id="worker-dry", now=DUE, dry_run=True)
_assert("§3c: at the governed instant a dry run reports every challenge DUE",
        all(o.status == flw.DUE for o in _dry.outcomes), _dry.summary())
_assert("§3c: and it is genuinely read-only — no claim, no entry",
        all(claims_for(c) == [] for c in EVERY)
        and entry_count() == _entries_before)

# The opponent's Action card as it stands BEFORE anything is priced, kept for
# the UI-impact comparison in §12.


def _card_for(headers: dict, cid: int):
    resp = client().get(f"/league/{LEAGUE_ID}/action/me", headers=headers)
    assert resp.status_code == 200, f"{resp.status_code} {resp.text[:200]}"
    for cards in resp.json()["sections"].values():
        for c in cards:
            if c["challenge_id"] == cid:
                return c
    return None


_pre_lock_card = _card_for(GM_OF[T5], A)
_assert("§3c: the opponent's Action card for the unpriced challenge is "
        "readable", _pre_lock_card is not None)


# ══════════════════════════════════════════════════════════════════════════════
# §4 · DUE → THE WORKER LOCKS, WITH NO USER ACTION
# ══════════════════════════════════════════════════════════════════════════════

_section("§4 · due → the worker locks (challenge A), system-side")

_funds_before = {t: spendable(t, WEEK) for t in team_ids}
_a_anchor_before, _a_derived_before = escrow_pair(A)
_a_ceiling = hs_a["opponent_ceiling_cents"]
_a_issuer_ceiling = hs_a["issuer_ceiling_cents"]

# ONE challenge at a time, so the untouched controls stay untouched: `--league`
# scopes discovery, and `sweep_challenge` is the same code path `run_once`
# drives per challenge.
_res_a = flw.sweep_challenge(A, worker_id="worker-1", now=DUE)

_assert("§4: the worker LOCKED challenge A", _res_a.status == flw.LOCKED,
        f"{_res_a.status} — {_res_a.detail}")
_assert("§4: no GM, commissioner or HTTP request was involved — the only actor "
        "was the system worker",
        _res_a.status == flw.LOCKED and _lock_routes == [])

_fl_a = final_lock_row(A)
_assert("§4: an immutable ChallengeFinalLock result exists",
        _fl_a is not None and _fl_a.id == _res_a.final_lock_id)
_assert("§4: it records the model FROZEN AT HANDSHAKE, not the active one",
        _fl_a.executed_model_version_id == hs_a["model_version_id"]
        and _fl_a.executed_model_config_hash == hs_a["model_config_hash"],
        f"{_fl_a.executed_model_version_id}/{_fl_a.executed_model_config_hash}")
_assert("§4: it records the projection dataset the worker actually read",
        _fl_a.projection_source_id == "fantasypros"
        and _fl_a.projection_dataset_version == f"{config.CURRENT_SEASON}-w{WEEK}",
        f"{_fl_a.projection_source_id} / {_fl_a.projection_dataset_version}")

_claim_a = claims_for(A)
_assert("§4: exactly one claim row exists, owned by this worker and completed",
        len(_claim_a) == 1 and _claim_a[0].status == "completed"
        and _claim_a[0].claimed_by == "worker-1"
        and _claim_a[0].final_lock_id == _fl_a.id
        and _claim_a[0].attempt_count == 1,
        f"{_claim_a[0].status} by {_claim_a[0].claimed_by} "
        f"attempt {_claim_a[0].attempt_count}" if _claim_a else "no claim")


# ══════════════════════════════════════════════════════════════════════════════
# §5 · ECONOMIC PROOFS ON THE LOCKED CHALLENGE
# ══════════════════════════════════════════════════════════════════════════════

_section("§5 · Anchor and Derived Bet state, exposure, ceiling, migration")

_bets_a = {b.id: b for b in bets_for(A)}
_anchor_bet = _bets_a.get(_res_a.anchor_bet_id)
_derived_bet = _bets_a.get(_res_a.derived_bet_id)

_assert("§5 (3): Final Lock produced exactly TWO Bet rows — one Anchor, one "
        "Derived", len(_bets_a) == 2 and _anchor_bet is not None
        and _derived_bet is not None, str(sorted(_bets_a)))
_assert("§5 (3): both are pending, and the challenge points at them",
        _anchor_bet.status == "pending" and _derived_bet.status == "pending",
        f"{_anchor_bet.status}/{_derived_bet.status}")

with SessionLocal() as db:
    _ch_a = db.query(BeefChallenge).filter(BeefChallenge.id == A).one()
    _linked = sorted(x for x in (_ch_a.challenger_bet_id, _ch_a.challenged_bet_id)
                     if x is not None)
    _resp_status = _ch_a.response_status
    db.rollback()
_assert("§5 (3): the challenge row links BOTH Bet rows",
        _linked == sorted([_anchor_bet.id, _derived_bet.id]), str(_linked))
_assert("§5 (3): and no new response_status was invented for 'final locked'",
        _resp_status == "accepted", str(_resp_status))

_anchor_stake = round(_anchor_bet.amount * 100)
_derived_stake = round(_derived_bet.amount * 100)
_assert("§5 (4): the ANCHOR stake is the issuer's fixed commitment, unmoved by "
        "the final odds", _anchor_stake == _a_issuer_ceiling == int(ANCHOR * 100),
        f"{_anchor_stake} vs ceiling {_a_issuer_ceiling}")
_assert("§5 (4): the DERIVED stake equals the frozen result's derived_final",
        _derived_stake == _fl_a.derived_final_cents,
        f"{_derived_stake} vs {_fl_a.derived_final_cents}")
_assert("§5 (5): THE ISSUER CEILING IS PRESERVED — the anchor never repriced",
        _fl_a.anchor_cents == _a_issuer_ceiling == _a_anchor_before,
        f"{_fl_a.anchor_cents} / {_a_issuer_ceiling} / {_a_anchor_before}")
_assert("§5 (5): and the opponent's exposure NEVER GREW past its ceiling",
        _fl_a.derived_final_cents <= _a_ceiling,
        f"{_fl_a.derived_final_cents} <= {_a_ceiling}")
_assert("§5 (5): the refund is exactly the ceiling minus the final derived "
        "stake, and only the Derived side refunded",
        _fl_a.derived_refund_cents == _a_ceiling - _fl_a.derived_final_cents,
        f"{_fl_a.derived_refund_cents} vs "
        f"{_a_ceiling - _fl_a.derived_final_cents}")

_assert("§5 (6): the per-side challenge escrow accounts are DRAINED",
        escrow_pair(A) == (0, 0), str(escrow_pair(A)))
_assert("§5 (6): and the Credits arrived in the two Bet escrow accounts, "
        "per-side identity intact",
        balance_of(f"escrow:{_anchor_bet.id}") == _anchor_stake
        and balance_of(f"escrow:{_derived_bet.id}") == _derived_stake,
        f"{balance_of(f'escrow:{_anchor_bet.id}')}/"
        f"{balance_of(f'escrow:{_derived_bet.id}')}")

_issuer_team, _opp_team = T6, T5
_credits_before = (_a_anchor_before + _a_derived_before
                   + _funds_before[_issuer_team] + _funds_before[_opp_team])
_credits_after = (balance_of(anchor_acct(A)) + balance_of(derived_acct(A))
                  + balance_of(f"escrow:{_anchor_bet.id}")
                  + balance_of(f"escrow:{_derived_bet.id}")
                  + spendable(_issuer_team, WEEK) + spendable(_opp_team, WEEK))
_assert("§5 (7): NO Credits were created or destroyed — every cent that was in "
        "this challenge's escrow is still in escrow or back with the GM who "
        "funded it", _credits_after == _credits_before,
        f"{_credits_after} vs {_credits_before}")
_assert("§5 (7): the refund went to the OPPONENT, and the ISSUER received "
        "nothing — the Anchor never reprices",
        spendable(_opp_team, WEEK)
        == _funds_before[_opp_team] + _fl_a.derived_refund_cents
        and spendable(_issuer_team, WEEK) == _funds_before[_issuer_team],
        f"opp {_funds_before[_opp_team]} -> {spendable(_opp_team, WEEK)}; "
        f"iss {_funds_before[_issuer_team]} -> {spendable(_issuer_team, WEEK)}")
_assert("§5 (8): TRIAL BALANCE IS ZERO after the worker ran",
        trial_balance() == 0, str(trial_balance()))

_section("§5b · league / challenge isolation")

_untouched = (B, C, D, E, X)
_assert("§5b (12): every other challenge's escrow — including the SECOND "
        "league's — is byte-identical to before the worker ran",
        {c: escrow_pair(c) for c in _untouched}
        == {c: _escrow_before[c] for c in _untouched},
        str({c: escrow_pair(c) for c in _untouched}))
_assert("§5b (12): none of them acquired a claim, a Bet or a frozen result",
        all(claims_for(c) == [] and not bets_for(c) and final_lock_row(c) is None
            for c in _untouched))
_assert("§5b (12): every GM's funds except the two participants' are unchanged",
        all(spendable(t, WEEK) == _funds_before[t]
            for t in team_ids if t not in (_issuer_team, _opp_team)),
        str({t: spendable(t, WEEK) for t in team_ids}))


# ══════════════════════════════════════════════════════════════════════════════
# §6 · ALREADY LOCKED → NO DUPLICATE MOVEMENT
# ══════════════════════════════════════════════════════════════════════════════

_section("§6 · a repeat worker run creates no duplicate Bets or postings")

_entries_after_a = entry_count()
_funds_after_a = {t: spendable(t, WEEK) for t in team_ids}

# A DRY RUN, so this section measures DISCOVERY and nothing else. A live sweep
# here would price B through E as a side effect and every later section would be
# asserting against a league that had already been swept.
_again = flw.run_once(worker_id="worker-1", now=DUE, league_id=LEAGUE_ID,
                      dry_run=True)
_assert("§6 (9): challenge A is no longer discovered — a committed frozen "
        "result is what 'already locked' means — and the league filter excludes "
        "the second league's challenge entirely",
        outcome_for(_again, A) is None and outcome_for(_again, X) is None
        and sorted(o.challenge_id for o in _again.outcomes) == sorted([B, C, D, E]),
        str(sorted(o.challenge_id for o in _again.outcomes)))

# AND THE ENGINE'S OWN SUPPRESSION, reached directly rather than filtered out
# beforehand — the discovery filter must not be the ONLY thing preventing a
# second execution.
_replay = flw.sweep_challenge(A, worker_id="worker-9", now=DUE)
_assert("§6 (9): driving the locked challenge again returns the ORIGINAL "
        "committed result", _replay.status == flw.REPLAYED
        and _replay.final_lock_id == _fl_a.id,
        f"{_replay.status} — {_replay.detail}")
_assert("§6 (9): still exactly two Bet rows, and one frozen result",
        len(bets_for(A)) == 2 and len(claims_for(A)) == 1)
_assert("§6 (9): NOT ONE new ledger entry was written",
        entry_count() == _entries_after_a,
        f"{entry_count()} vs {_entries_after_a}")
_assert("§6 (9): and not one wallet moved",
        {t: spendable(t, WEEK) for t in team_ids} == _funds_after_a)
_assert("§6 (9): the claim is still owned by the ORIGINAL worker — a replay is "
        "not a reclaim",
        claims_for(A)[0].claimed_by == "worker-1"
        and claims_for(A)[0].attempt_count == 1,
        f"{claims_for(A)[0].claimed_by} attempt "
        f"{claims_for(A)[0].attempt_count}")


# ══════════════════════════════════════════════════════════════════════════════
# §7 · CONCURRENCY — EXACTLY ONE WORKER WINS THE CLAIM
# ══════════════════════════════════════════════════════════════════════════════

_section("§7 · overlapping worker instances (challenge B)")

_RACERS = 4
# The barrier's party count is the RACER count exactly. Every thread blocks on it
# until the last one arrives, so all four attempt the claim inside the same
# instant rather than politely queueing behind whichever started first — which
# would prove serial execution, not exclusion.
_barrier = threading.Barrier(_RACERS)
_race: list = []
_race_lock = threading.Lock()


def _racer(name: str) -> None:
    _barrier.wait()
    try:
        out = flw.sweep_challenge(B, worker_id=name, now=DUE)
    except Exception as exc:                                   # noqa: BLE001
        out = flw.ChallengeOutcome(B, None, None, "exception",
                                   f"{type(exc).__name__}: {exc}")
    with _race_lock:
        _race.append(out)


_threads = [threading.Thread(target=_racer, args=(f"racer-{i}",))
            for i in range(_RACERS)]
for t in _threads:
    t.start()
for t in _threads:
    t.join(timeout=300)
_assert("§7 (10): every racer finished — none deadlocked on the claim",
        len(_race) == _RACERS and not any(t.is_alive() for t in _threads),
        f"{len(_race)}/{_RACERS} returned")

_winners = [o for o in _race if o.status == flw.LOCKED]
_losers = [o for o in _race if o.status != flw.LOCKED]
_assert("§7 (10): four workers raced the same challenge and EXACTLY ONE locked "
        "it", len(_winners) == 1,
        str(sorted((o.status for o in _race))))
_assert("§7 (10): every loser refused honestly — not owned, or the committed "
        "result replayed — and none reported a new success",
        all(o.status in (flw.NOT_OWNED, flw.REPLAYED) for o in _losers),
        str([(o.status, o.detail[:60]) for o in _losers]))
_assert("§7 (10): exactly ONE claim row exists for the challenge — "
        "UNIQUE(challenge_id) is the mutex, and no second row was minted",
        len(claims_for(B)) == 1, str(len(claims_for(B))))
_assert("§7 (10): exactly ONE frozen result and TWO Bet rows — no double lock",
        final_lock_row(B) is not None and len(bets_for(B)) == 2,
        str(len(bets_for(B))))
_assert("§7 (10): challenge B's per-side escrow is drained exactly once",
        escrow_pair(B) == (0, 0), str(escrow_pair(B)))
_assert("§7 (10): trial balance still zero after the race",
        trial_balance() == 0, str(trial_balance()))

_fl_b = final_lock_row(B)
_bets_b = {b.id: b for b in bets_for(B)}
_migrated_b = sum(balance_of(f"escrow:{bid}") for bid in _bets_b)
_assert("§7 (10): and the pot migrated ONCE, not four times",
        _migrated_b == _fl_b.anchor_cents + _fl_b.derived_final_cents,
        f"{_migrated_b} vs {_fl_b.anchor_cents + _fl_b.derived_final_cents}")


# ══════════════════════════════════════════════════════════════════════════════
# §8 · STALE-CLAIM RECOVERY
# ══════════════════════════════════════════════════════════════════════════════

_section("§8 · stale-claim recovery (challenge C)")

_c_escrow_before = escrow_pair(C)

# A DEAD WORKER'S CLAIM: taken at kickoff, never completed. This is precisely
# the Rev 9 §5.7 "crash after the claim commits" state — the claim survives at
# `claimed` and NO money moved, because Phase 1 posts nothing by construction.
_stale_moment = DUE
_ttl = flw.dyn.FINAL_LOCK_CLAIM_TTL
with SessionLocal() as db:
    db.execute(text(
        "INSERT INTO challenge_final_lock_claims "
        "  (challenge_id, status, claimed_by, claimed_at, claim_expires_at, "
        "   attempt_count, created_at) "
        "VALUES (:cid, 'claimed', 'dead-worker', :t, :exp, 1, :t)"),
        {"cid": C, "t": _stale_moment, "exp": _stale_moment + _ttl})
    db.commit()

# Inside the TTL: due, but owned by someone else.
_live_claim = flw.sweep_challenge(C, worker_id="worker-fresh",
                                  now=_stale_moment + timedelta(minutes=1))
_assert("§8: the challenge is DUE, yet while the dead worker's claim is still "
        "live another worker refuses to execute",
        _live_claim.status == flw.NOT_OWNED,
        f"{_live_claim.status} — {_live_claim.detail[:80]}")
_assert("§8: and nothing moved while it backed off",
        escrow_pair(C) == _c_escrow_before and not bets_for(C)
        and final_lock_row(C) is None)

# Past the TTL: the claim is stale and reclaimable.
_recovered = flw.sweep_challenge(C, worker_id="worker-fresh",
                                 now=_stale_moment + _ttl + timedelta(minutes=1))
_assert("§8: once the 15-minute TTL has passed the next worker RECLAIMS in "
        "place and completes the lock", _recovered.status == flw.LOCKED,
        f"{_recovered.status} — {_recovered.detail}")

_claim_c = claims_for(C)[0]
_assert("§8: the reclaim happened IN PLACE — still one row, never a second",
        len(claims_for(C)) == 1)
_assert("§8: with the audit trail Rev 9 §5.6 requires — new owner, previous "
        "owner recorded, attempt_count incremented",
        _claim_c.claimed_by == "worker-fresh"
        and _claim_c.previous_claimed_by == "dead-worker"
        and _claim_c.attempt_count == 2
        and _claim_c.status == "completed",
        f"{_claim_c.previous_claimed_by} -> {_claim_c.claimed_by}, "
        f"attempt {_claim_c.attempt_count}, {_claim_c.status}")
_assert("§8: the recovered execution produced the normal result: two Bets, "
        "drained escrow, zero trial balance",
        len(bets_for(C)) == 2 and escrow_pair(C) == (0, 0)
        and trial_balance() == 0)


# ══════════════════════════════════════════════════════════════════════════════
# §9 · DETERMINISTIC FAILURE ROLLS BACK CLEANLY
# ══════════════════════════════════════════════════════════════════════════════

_section("§9 · failure rolls back cleanly and releases the claim (challenge D)")

_d_escrow_before = escrow_pair(D)
_entries_pre_d = entry_count()
_funds_pre_d = {t: spendable(t, WEEK) for t in team_ids}

# THE FROZEN MODEL IS MADE UNREPRODUCIBLE. Rev 9: the Handshake-frozen model is
# never substituted, so Final Lock must refuse — "no simulation, no Adjustment,
# no refund, no migration, no frozen result". A hash the registry cannot
# reproduce is the cleanest deterministic instance of that, and it fails INSIDE
# Phase 2, after the claim is committed, which is exactly where a rollback has
# something to roll back.
with SessionLocal() as db:
    ch_d = db.query(BeefChallenge).filter(BeefChallenge.id == D).one()
    _real_hash = ch_d.dynamic_model_config_hash
    ch_d.dynamic_model_config_hash = "0" * 64
    db.commit()

_fail = flw.sweep_challenge(D, worker_id="worker-fail", now=DUE)
_assert("§9 (11): the worker reports the refusal instead of crashing the sweep",
        _fail.status == flw.FAILED
        and "ModelIntegrityError" in _fail.detail, f"{_fail.status} — "
        f"{_fail.detail[:120]}")
_assert("§9 (11): NOTHING was posted — escrow is exactly as the Handshake left "
        "it", escrow_pair(D) == _d_escrow_before,
        f"{escrow_pair(D)} vs {_d_escrow_before}")
_assert("§9 (11): no Bet row, no frozen result",
        not bets_for(D) and final_lock_row(D) is None)
_assert("§9 (11): not one ledger entry, not one wallet moved",
        entry_count() == _entries_pre_d
        and {t: spendable(t, WEEK) for t in team_ids} == _funds_pre_d,
        f"{entry_count()} vs {_entries_pre_d}")

_claim_d = claims_for(D)[0]
_assert("§9 (11): the claim was RELEASED deliberately rather than left to "
        "expire — status failed, with the reason recorded",
        _claim_d.status == "failed"
        and "ModelIntegrityError" in (_claim_d.failure_reason or ""),
        f"{_claim_d.status}: {(_claim_d.failure_reason or '')[:80]}")
_assert("§9 (11): trial balance is untouched by the failure",
        trial_balance() == 0, str(trial_balance()))

# AND THE FAILURE IS RECOVERABLE: a released claim is reclaimable at once, so
# repairing the cause lets the very next sweep finish the job.
with SessionLocal() as db:
    ch_d = db.query(BeefChallenge).filter(BeefChallenge.id == D).one()
    ch_d.dynamic_model_config_hash = _real_hash
    db.commit()

_repaired = flw.sweep_challenge(D, worker_id="worker-after-fail", now=DUE)
_assert("§9 (11): with the cause repaired the next worker reclaims the failed "
        "claim immediately — no 15-minute wait for a released one",
        _repaired.status == flw.LOCKED, f"{_repaired.status} — {_repaired.detail}")
_assert("§9 (11): and the recovered run is a normal one",
        len(bets_for(D)) == 2 and escrow_pair(D) == (0, 0)
        and claims_for(D)[0].status == "completed"
        and claims_for(D)[0].attempt_count == 2
        and trial_balance() == 0,
        f"attempt {claims_for(D)[0].attempt_count}")


# ══════════════════════════════════════════════════════════════════════════════
# §10 · A LATE WORKER STILL LOCKS
# ══════════════════════════════════════════════════════════════════════════════

_section("§10 · late invocation follows the existing governed behaviour "
         "(challenge E)")

_e_escrow_before = escrow_pair(E)
_e_ceiling = hs_e["opponent_ceiling_cents"]
_e_issuer, _e_opponent = T2, T1
_e_opp_funds_before = spendable(_e_opponent, WEEK)
_e_iss_funds_before = spendable(_e_issuer, WEEK)

# THE PROJECTIONS MOVE BETWEEN HANDSHAKE AND FINAL LOCK, which is the entire
# premise of Dynamic mode: "the model version, each side's maximum exposure and
# the escrow ceiling freeze at the Handshake — the final ODDS do not" (Rev 9 §0).
# The opponent's week deteriorates by 5%, as a real projection feed moves it
# across a week, so the issuer's win probability RISES and the re-derived Derived
# stake comes in below the frozen ceiling. Nothing else in this suite can produce
# a nonzero refund: an unchanged lineup re-derives to precisely the ceiling by
# construction (Rev 9 §3, "no 'No Change' refund artifact").
#
# A GENTLE MOVE, DELIBERATELY. Ruling starters out outright drives the
# simulation to a unanimous verdict, and `adjust_escrow` refuses `p == 1.0` as
# out of range — a correct refusal, but a refusal, and this section is about the
# refund path rather than the guard.
with SessionLocal() as db:
    from db.schema import Projection, Roster
    _moved_ids = [r.player_id for r in db.query(Roster)
                  .filter(Roster.team_id == _e_opponent).all()]
    for p in (db.query(Projection)
              .filter(Projection.player_id.in_(_moved_ids),
                      Projection.week == WEEK,
                      Projection.season == config.CURRENT_SEASON).all()):
        p.projected_points = round((p.projected_points or 0.0) * 0.95, 2)
    db.commit()

_late = flw.sweep_challenge(E, worker_id="worker-late", now=LATE)
_assert("§10: a worker arriving a week after kickoff LOCKS — the certified "
        "engine has no lateness branch, and inventing one here would strand "
        "escrow it was willing to resolve",
        _late.status == flw.LOCKED, f"{_late.status} — {_late.detail}")

_fl_e = final_lock_row(E)
_assert("§10: with the ordinary result: two Bets, drained per-side escrow, "
        "issuer ceiling preserved",
        len(bets_for(E)) == 2 and escrow_pair(E) == (0, 0)
        and _fl_e.anchor_cents == hs_e["issuer_ceiling_cents"],
        f"{_fl_e.anchor_cents} vs {hs_e['issuer_ceiling_cents']}")

_section("§10a · the worker priced the LIVE lineup, and the refund proves it")

_assert("§10a: the worker read the lineup as it stood AT FINAL LOCK, not as it "
        "stood at the Handshake — the re-derived Derived stake came in BELOW "
        "the frozen ceiling",
        _fl_e.derived_final_cents < _e_ceiling,
        f"{_fl_e.derived_final_cents} < {_e_ceiling}")
_assert("§10a: so the opponent received a REAL Derived refund, exactly the "
        "ceiling minus the final stake",
        _fl_e.derived_refund_cents > 0
        and _fl_e.derived_refund_cents == _e_ceiling - _fl_e.derived_final_cents,
        f"{_fl_e.derived_refund_cents} vs "
        f"{_e_ceiling - _fl_e.derived_final_cents}")
_assert("§10a: and it went back to the OPPONENT, into the very accounts the "
        "Handshake drew it from — Spec 2's reverse legs return money to its "
        "original funding sources, not to a wallet by default",
        spendable(_e_opponent, WEEK)
        == _e_opp_funds_before + _fl_e.derived_refund_cents,
        f"{_e_opp_funds_before} -> {spendable(_e_opponent, WEEK)} "
        f"(refund {_fl_e.derived_refund_cents})")
_assert("§10a: and NOT to the issuer, whose own funds are untouched",
        spendable(_e_issuer, WEEK) == _e_iss_funds_before,
        f"{_e_iss_funds_before} -> {spendable(_e_issuer, WEEK)}")
_assert("§10a: THE ISSUER REFUNDED NOTHING — the Anchor is a fixed commitment "
        "and does not reprice on odds",
        _fl_e.anchor_cents == _e_escrow_before[0]
        == hs_e["issuer_ceiling_cents"],
        f"{_fl_e.anchor_cents} / {_e_escrow_before[0]}")
_assert("§10a: the ceiling was never exceeded, and every cent is accounted for",
        _fl_e.derived_final_cents + _fl_e.derived_refund_cents
        == _e_escrow_before[1] == _e_ceiling,
        f"{_fl_e.derived_final_cents} + {_fl_e.derived_refund_cents} vs "
        f"{_e_escrow_before[1]}")
_assert("§10a: trial balance still zero", trial_balance() == 0,
        str(trial_balance()))

_section("§10b · league 19 is fully priced, and league 20 was never touched")

_drained = flw.run_once(worker_id="worker-final", now=LATE,
                        league_id=LEAGUE_ID)
_assert("§10b: every Dynamic challenge in league 19 has been priced — the "
        "worker finds nothing left to do there",
        _drained.examined == 0, _drained.summary())
_assert("§10b: five challenges, five frozen results, ten Bet rows",
        all(final_lock_row(c) is not None for c in ALL)
        and sum(len(bets_for(c)) for c in ALL) == 10,
        str({c: len(bets_for(c)) for c in ALL}))
_assert("§10b: no league-19 Dynamic escrow remains",
        all(escrow_pair(c) == (0, 0) for c in ALL),
        str({c: escrow_pair(c) for c in ALL}))
_assert("§10b (12): and after SEVEN worker invocations against league 19, the "
        "second league's challenge is exactly as its Handshake left it — no "
        "claim, no Bet, no frozen result, escrow untouched",
        escrow_pair(X) == _escrow_before[X] and claims_for(X) == []
        and not bets_for(X) and final_lock_row(X) is None,
        f"{escrow_pair(X)} vs {_escrow_before[X]}")

_section("§10c · an unscoped sweep prices the second league, and only it")

_l19_bets = sum(len(bets_for(c)) for c in ALL)
_all_leagues = flw.run_once(worker_id="worker-all", now=LATE)
_assert("§10c (12): with no league filter the worker discovers exactly the one "
        "remaining challenge and locks it",
        _all_leagues.examined == 1 and outcome_for(_all_leagues, X).status
        == flw.LOCKED, _all_leagues.summary())
_assert("§10c (12): league 19's ten Bet rows are unchanged by it",
        sum(len(bets_for(c)) for c in ALL) == _l19_bets == 10,
        str(sum(len(bets_for(c)) for c in ALL)))
_assert("§10c: trial balance zero across the whole run",
        trial_balance() == 0, str(trial_balance()))

with SessionLocal() as db:
    _open_challenge_escrow = db.execute(text(
        "SELECT account, SUM(amount_cents) FROM ledger_entries "
        "WHERE account LIKE 'escrow:challenge:%' GROUP BY account "
        "HAVING SUM(amount_cents) <> 0")).fetchall()
    db.rollback()
_assert("§10c: not one `escrow:challenge:*` account holds a balance — the "
        "class of account WP6 found stranded is empty, in both leagues",
        _open_challenge_escrow == [], str(_open_challenge_escrow))


# ══════════════════════════════════════════════════════════════════════════════
# §11 · THE CLI IS THE DEPLOYED ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

_section("§11 · `python -m workers.final_lock` behaves as deployed")

_rc = flw.main(["--dry-run", "--league", str(LEAGUE_ID)])
_assert("§11: a one-shot dry run over a fully-priced league exits 0",
        _rc == 0, str(_rc))
_rc = flw.main(["--league", str(LEAGUE_ID)])
_assert("§11: a one-shot sweep with nothing to do exits 0", _rc == 0, str(_rc))
_assert("§11: and it moved nothing", trial_balance() == 0
        and all(escrow_pair(c) == (0, 0) for c in ALL))

_loops = flw.run_forever(interval_seconds=1, league_id=LEAGUE_ID,
                         worker_id="worker-loop", max_sweeps=2)
_assert("§11: the resident --loop mode sweeps and returns cleanly",
        _loops == 0, str(_loops))
_assert("§11: two resident sweeps over a priced league still moved nothing",
        trial_balance() == 0 and sum(len(bets_for(c)) for c in ALL) == 10)


# ══════════════════════════════════════════════════════════════════════════════
# §12 · UI AND AUTH IMPACT — READ-ONLY, AND NO NEW CONTROL
# ══════════════════════════════════════════════════════════════════════════════

_section("§12 · the Action tab reflects Final Lock, and offers no control over "
         "it")


_iss_card = _card_for(GM_OF[_issuer_team], A)
_opp_card = _card_for(GM_OF[_opp_team], A)

_assert("§12: both participants' Action cards for the locked challenge exist",
        _iss_card is not None and _opp_card is not None)
_assert("§12: the card reports that Final Lock OCCURRED",
        _iss_card["final_locked"] is True and _opp_card["final_locked"] is True,
        f"{_iss_card['final_locked']}/{_opp_card['final_locked']}")
_assert("§12: the OPPONENT's own stake is the priced Derived stake, not the "
        "zero the Dynamic proposal quotes",
        _opp_card["your_stake_cents"] == _fl_a.derived_final_cents
        == _derived_stake > 0,
        f"{_opp_card['your_stake_cents']} vs {_fl_a.derived_final_cents}")
_assert("§12: the ISSUER's own stake is the fixed Anchor",
        _iss_card["your_stake_cents"] == _fl_a.anchor_cents,
        f"{_iss_card['your_stake_cents']} vs {_fl_a.anchor_cents}")
_assert("§12: both viewers see the SAME pot, and it is the two final stakes",
        _iss_card["pot_cents"] == _opp_card["pot_cents"]
        == _fl_a.anchor_cents + _fl_a.derived_final_cents,
        f"{_iss_card['pot_cents']} / {_opp_card['pot_cents']}")
_assert("§12: the odds shown are the FINAL-LOCK odds, not the superseded "
        "Handshake quote",
        _iss_card["your_moneyline"] == _fl_a.issuer_moneyline
        and _opp_card["your_moneyline"] == _fl_a.opponent_moneyline
        and _iss_card["your_odds"] == _anchor_bet.odds
        and _opp_card["your_odds"] == _derived_bet.odds,
        f"{_iss_card['your_moneyline']}/{_opp_card['your_moneyline']} vs "
        f"{_fl_a.issuer_moneyline}/{_fl_a.opponent_moneyline}")
_assert("§12: NO card offers a Final-Lock control to anyone — the read model "
        "reports the event and exposes no command for it",
        all("lock" not in ctrl.lower()
            for c in (_iss_card, _opp_card) for ctrl in c["controls"]),
        f"{_iss_card['controls']} / {_opp_card['controls']}")

# AND THE PRE-FINAL-LOCK RENDERING IS UNCHANGED. A ceiling, no Derived stake and
# the Handshake quote is the behaviour S8-P4C-2 certified for a handshaken
# Dynamic card, and it must survive this package untouched — the new field only
# reports a state that could not previously exist.
_assert("§12: BEFORE Final Lock the card was unchanged from what S8-P4C-2 "
        "certified — `final_locked` false, ceiling reported, no Derived stake "
        "quoted, Handshake odds shown",
        _pre_lock_card["final_locked"] is False
        and _pre_lock_card["derived_ceiling_cents"] == _a_ceiling
        and _pre_lock_card["your_stake_cents"] == 0
        and _pre_lock_card["pot_cents"] is None,
        f"final_locked={_pre_lock_card['final_locked']}, "
        f"ceiling={_pre_lock_card['derived_ceiling_cents']}, "
        f"stake={_pre_lock_card['your_stake_cents']}, "
        f"pot={_pre_lock_card['pot_cents']}")
_assert("§12: and `derived_repriced` — the Handshake flag — is untouched by "
        "this package, before and after",
        _pre_lock_card["derived_repriced"] is True
        and _opp_card["derived_repriced"] is True)


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 78)
if _failures:
    print(f"WP6B WORKER SUITE — {len(_failures)} FAILURE(S)")
    for f in _failures:
        print(f"  FAIL  {f}")
    print("=" * 78)
    tdb.teardown()
    sys.exit(1)
print("WP6B WORKER SUITE — ALL ASSERTIONS PASS")
print("The Dynamic Final Lock engine now has a production system caller: it "
      "fires at the")
print("governed kickoff, exactly once, with no GM or commissioner involved.")
print("=" * 78)
tdb.teardown()