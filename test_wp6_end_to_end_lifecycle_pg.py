#!/usr/bin/env python3
"""
test_wp6_end_to_end_lifecycle_pg.py — WP6 · end-to-end product lifecycle.

THE QUESTION THIS SUITE ANSWERS, and the only one it answers:

    CAN A LEAGUE COMPLETE THE FANTASYSTAKES GAME LIFECYCLE THROUGH THE RUNNING
    PRODUCT?

Not "is each engine correct" — Sprints 4-8 and WP1-WP6A certified that, engine by
engine. This drives ONE synthetic league from season-opening allocation to the
attempted Season Close using the PRODUCTION HTTP SURFACE, an authenticated
commissioner and five authenticated GMs, real PostgreSQL, the real ledger, and
the recorded provider corpus. Where a lifecycle step has a production entry
point, this suite uses it. Where a step has NONE, the suite says so, in those
words, and does not substitute an engine import to manufacture a green run —
that substitution is the exact defect WP5 and WP6A were created to remove, and
performing it here would hide two more instances of it.

THE ONLY SUBSTITUTION IS THE TRANSPORT. `providers.yahoo.transport.YahooLiveTransport`
is pointed at `FixtureTransport`, exactly as WP2B, WP2B-C, WP2B-D and the Sprint 6
certification do, so the run is offline and needs no credentials. Everything
else — routes, authorization, assembly, identity resolution, stat source,
census, engines, ledger — is production.

WHAT THE RUN FOUND. Every lifecycle capability up to Season Close is reachable
and correct through the product, with TWO exceptions that are certified-but-
unwired. They are recorded here as first-class results rather than as skipped
tests, because a suite that quietly stepped around them would be asserting the
opposite of what is true:

  BLOCKER 1 — DYNAMIC FINAL LOCK (lifecycle step 14).
      `economy.dynamic_challenge.run_final_lock` is certified by
      test_p3_d2_dynamic_final_lock_pg.py and has NO non-test caller: no route,
      no scheduler, no worker. §12 proves a Dynamic wager can be issued and
      handshaken through the product — the UI's own command layer offers the
      mode — and then cannot be priced, so both sides' escrow is stranded. §15
      then watches Season Close refuse at `escrow_resolved`, permanently: this
      is the blocker that actually stops the lifecycle.

      THE REPAIR IS NOT A ROUTE, and this suite deliberately does not add one.
      SIMULATION_ENGINE_MODULE_SPEC_Rev9 §"Actor class" is explicit: Final Lock
      is "the same scheduled system worker/process class that acquires fresh
      claims. Not an end user, not a GM, not a commissioner, not reachable from
      any HTTP route." It fires at the challenge's earliest covered kickoff. The
      missing production surface is therefore a KICKOFF-TIME SCHEDULED TRIGGER,
      which is new infrastructure and outside a certification package.

  BLOCKER 2 — GOVERNED POOL CLAIM SUBMISSION (lifecycle step 19).
      `betting.pool_claims.submit_claim` is certified by the S4 suites and has
      no non-test caller. The Pool pick control the UI actually posts —
      `POST /pool/pick` — writes the LEGACY prediction model, which the Rev1.3
      settlement engine never reads: §6 shows that route returning 200 while
      `pool_claims` stays empty. No GM can hold a winning ticket, so lifecycle
      step 19 — "Pool winner settlement succeeds" — is unreachable through the
      product, and every pot with a real winner rolls over instead of paying.

Both are the WP5 shape exactly: a certified engine with no caller. Neither is an
engine defect, and §6.3 demonstrates that for BLOCKER 2 by calling the certified
claim path directly and then watching the SAME production settlement route pay a
real winner in §8 — the engine is sound; only the admission path is absent.

WHAT IS *NOT* A BLOCKER, and is called out so the report cannot overstate the
finding: §15 shows two occurrences still carrying a live rollover at the end of
the run, which independently bars the `pool_rollover` prerequisite. Both are
`ZERO_ELIGIBLE_CLAIMS` — the SUBJECT layer, where no matchup satisfied the
predicate — so no GM claim could have changed them and BLOCKER 2 is not their
cause. Such a pot rolls forward to `season_final_week` and sweeps to Championship
under POR §5. This league's final week is 17; a two-week certification fixture
never reaches it. That is a property of the fixture, not a defect.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)
os.environ.setdefault("JWT_SECRET_KEY", "wp6-suite-secret")
# The wrap-up chain falls back to a template when no model is reachable; make
# that deterministic rather than dependent on whoever's key is in the shell.
os.environ.pop("ANTHROPIC_API_KEY", None)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP6 lifecycle suite cannot run:\n  {e}")
    sys.exit(2)

from datetime import datetime, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402
import providers.yahoo.transport as yahoo_transport  # noqa: E402
from api.main import app  # noqa: E402
from auth.jwt_auth import hash_password  # noqa: E402
from db.schema import (  # noqa: E402
    Bet, EconomyEvent, League, LeagueCommissioner, Matchup, Player, PoolClaim,
    PoolInstance, Projection, Roster, SessionLocal, Team, User, Wallet,
)
from ledger.ledger import balance_of, trial_balance  # noqa: E402
from providers.fixtures.replay import FixtureTransport  # noqa: E402
from test_support_wp2bc_league import (  # noqa: E402
    FROZEN_NOW, LEAGUE_ID, LEAGUE_KEY, SEASON, TEAM_COUNT,
    seed_economic_league, snapshot_for,
)

# ── THE ONE SUBSTITUTION ──────────────────────────────────────────────────────
# Patched on the MODULE, not on `api.main._pool_settlement_transport`, so every
# production consumer of the live transport — the Pool activation route, the
# Pool settlement route AND `notifications.tuesday_sync`, which constructs its
# own — is served from the corpus by one seam.
#
# A CLASS, NOT A LAMBDA. `tuesday_sync._step_sync_players` calls the CLASS
# method `YahooLiveTransport.league_number(...)`, which is pure string parsing
# over the compound key and needs no credentials. Carrying the real
# implementation across keeps that call honest instead of stubbing it.
class _FixtureLiveTransport(FixtureTransport):
    """The offline corpus transport, wearing the live transport's class API."""

    league_number = yahoo_transport.YahooLiveTransport.league_number

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(frozen_now=FROZEN_NOW)


yahoo_transport.YahooLiveTransport = _FixtureLiveTransport

_failures: list[str] = []
_ledger: list[tuple] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * min(len(title), 78))


def _record(step: str, surface: str, actor: str, result: str,
            persisted: str = "", ledger: str = "", retry: str = "") -> None:
    """The PRODUCTION-INTERFACE RULE ledger the brief requires: for every
    lifecycle capability, what surface was used, by whom, with what effect."""
    _ledger.append((step, surface, actor, result, persisted, ledger, retry))


PASSWORD = "wp6-password"
COMM_EMAIL = "wp6-comm@x.test"

#: Small by necessity, and the necessity is the economy itself: Week Open
#: releases exactly $10 of Weekly Minimum per GM per week, so a wager the GM
#: cannot source from it would be refused for funding reasons and would prove
#: nothing about the lifecycle.
LOCKED_STAKE = 2.00
LOCKED_COUNTER = 3.00
DYNAMIC_ANCHOR = 1.00

WEEKLY_MIN_CENTS = 14_000 // 14      # $10 — one governed week's release
OPENING_MIN_RESERVE = 14_000
OPENING_CHAMPIONSHIP = 8_000
OPENING_TOTAL = 22_000

print("=" * 78)
print("WP6 — END-TO-END PRODUCT LIFECYCLE CERTIFICATION")
print("=" * 78)


def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def bearer(email: str) -> dict:
    r = client().post("/auth/login",
                      data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ══════════════════════════════════════════════════════════════════════════════
# §0 · ENVIRONMENT, CORPUS AND THE PUBLICATION-SAFE IDENTITY
# ══════════════════════════════════════════════════════════════════════════════

_section("§0 · environment, corpus integrity, publication-safe identity")

from providers.fixtures.record import payload_sha256  # noqa: E402
from providers.fixtures.replay import DEFAULT_CORPUS_DIR, load_corpus  # noqa: E402

corpus = load_corpus()
mine = {k: v for k, v in corpus.items() if k.startswith("yahoo_wp2bc")}

_assert("§0: the six-team synthetic corpus is present",
        len(mine) == 17, f"{len(mine)} fixtures")
_assert("§0: every fixture declares provenance SYNTHETIC",
        all(f.provenance == "SYNTHETIC" for f in mine.values()))
_assert("§0: every payload's recomputed SHA-256 matches its manifest",
        all(payload_sha256(f.payload) == f.declared_sha256
            for f in mine.values()))
_assert("§0: the league identity is the publication-safe one",
        LEAGUE_KEY == "999.l.100001"
        and all(f.league_key == LEAGUE_KEY for f in mine.values()))

_leaked = []
for _name in sorted(os.listdir(DEFAULT_CORPUS_DIR)):
    if not _name.startswith("yahoo_wp2bc"):
        continue
    with open(os.path.join(DEFAULT_CORPUS_DIR, _name), encoding="utf-8") as fh:
        if "488800" in fh.read():
            _leaked.append(_name)
_assert("§0: NO real Yahoo league identifier appears in any fixture",
        not _leaked, str(_leaked))

_assert("§0: the transport in use is the offline fixture one",
        getattr(yahoo_transport.YahooLiveTransport(), "is_fixture_transport",
                False) is True)
_assert("§0: the ledger opens balanced", trial_balance() == 0)


# ══════════════════════════════════════════════════════════════════════════════
# §1 · BOOTSTRAP — declared FIXTURE-ONLY setup
# ══════════════════════════════════════════════════════════════════════════════
#
# EVERY ACTION IN THIS SECTION IS FIXTURE-ONLY AND IS LISTED AS SUCH IN THE
# REPORT. Each one exists because the product genuinely exposes no self-serve
# path for it in this baseline — there is no league-creation route, no
# onboarding/OAuth flow, no first-commissioner grant that does not already
# require a commissioner, and no roster/projection ingestion route. RUNBOOK §6.3
# records the onboarding gap as known and deliberate post-MVP scope.

_section("§1 · bootstrap (FIXTURE-ONLY — no product path exists for these)")

tdb.reset()

with SessionLocal() as db:
    league, teams = seed_economic_league(db)
    db.commit()
    team_ids = [t.id for t in teams]

with SessionLocal() as db:
    # FIXTURE-ONLY 4 — rosters and projections. The odds model reads Roster +
    # Projection; the provider corpus carries provider-side roster entries and
    # stat lines, which is a different table and a different purpose. No
    # production route ingests projections.
    for idx, team_id in enumerate(team_ids):
        for j in range(9):
            player = Player(name=f"WP6-T{idx + 1}-P{j}", position="WR",
                            nfl_team="KC")
            db.add(player)
            db.flush()
            db.add(Roster(team_id=team_id, player_id=player.id))
            for wk in (1, 2):
                db.add(Projection(
                    player_id=player.id, week=wk, season=config.CURRENT_SEASON,
                    source="fantasypros",
                    projected_points=10.0 + idx * 1.5 + j * 0.5,
                    actual_points=9.0 + idx * 1.4 + j * 0.4))
    db.flush()

    # FIXTURE-ONLY 5/6 — user accounts and the FIRST league commissioner.
    pw = hash_password(PASSWORD)
    comm = User(email=COMM_EMAIL, hashed_password=pw, team_id=team_ids[0],
                role="commissioner")
    db.add(comm)
    for ordinal in range(2, TEAM_COUNT + 1):
        db.add(User(email=f"wp6-gm{ordinal}@x.test", hashed_password=pw,
                    team_id=team_ids[ordinal - 1], role="gm"))
    db.flush()
    db.add(LeagueCommissioner(league_id=LEAGUE_ID, user_id=comm.id,
                              source="bootstrap"))
    db.commit()

_assert("§1: six teams exist, each with a wallet at zero",
        len(team_ids) == TEAM_COUNT
        and all(balance_of(f"wallet:{t}") == 0 for t in team_ids),
        str(team_ids))

hdr = bearer(COMM_EMAIL)
gm = {i: bearer(f"wp6-gm{i}@x.test") for i in range(2, TEAM_COUNT + 1)}

T1, T2, T3, T4, T5, T6 = team_ids

r = client().get("/auth/me", headers=hdr)
_assert("§1 (step 3): commissioner authority is real and league-scoped",
        r.status_code == 200 and r.json().get("role") == "commissioner",
        f"{r.status_code} {r.text[:120]}")
_record("3 commissioner authority", "GET /auth/me", "commissioner",
        f"{r.status_code}", "LeagueCommissioner(source=bootstrap)", "none", "n/a")

# A GM must NOT hold commissioner powers — proven on a real lifecycle route.
r = client().post(f"/league/{LEAGUE_ID}/week/1/open", headers=gm[2])
_assert("§1: an ordinary GM cannot run a commissioner lifecycle action",
        r.status_code == 403, str(r.status_code))



# ══════════════════════════════════════════════════════════════════════════════
# §2 · SEASON-OPENING ALLOCATION — the 220-Credit proof
# ══════════════════════════════════════════════════════════════════════════════

_section("§2 · season-opening allocation (steps 4, 5) — the 220-Credit proof")

r = client().post(f"/league/{LEAGUE_ID}/season-allocation", headers=hdr)
_assert("§2 (step 4): season allocation runs through the production route",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
alloc = r.json() if r.status_code == 200 else {}

_assert("§2 (step 5): Weekly Minimum Reserve is exactly 140 Credits",
        alloc.get("min_reserve_cents") == OPENING_MIN_RESERVE,
        str(alloc.get("min_reserve_cents")))
_assert("§2 (step 5): Championship Reserve is exactly 80 Credits",
        alloc.get("reserve_cents") == OPENING_CHAMPIONSHIP,
        str(alloc.get("reserve_cents")))
_assert("§2 (step 5): the total obligation is exactly 220 Credits",
        alloc.get("buyin_cents") == OPENING_TOTAL == 22_000,
        str(alloc.get("buyin_cents")))
_assert("§2 (step 5): 140 + 80 = 220 — the parts are the whole",
        OPENING_MIN_RESERVE + OPENING_CHAMPIONSHIP == OPENING_TOTAL)
_assert("§2 (step 5): every one of the six GMs was allocated",
        sorted(alloc.get("team_ids") or []) == sorted(team_ids)
        and alloc.get("total_buyin_cents") == OPENING_TOTAL * TEAM_COUNT,
        str(alloc.get("total_buyin_cents")))

_assert("§2 (step 5): WALLET IS ZERO at opening — nothing is spendable yet",
        all(balance_of(f"wallet:{t}") == 0 for t in team_ids),
        str([balance_of(f"wallet:{t}") for t in team_ids]))
_assert("§2 (step 5): each GM's Weekly Minimum Reserve holds exactly 14000 cents",
        all(balance_of(f"min_reserve:{t}") == OPENING_MIN_RESERVE
            for t in team_ids),
        str([balance_of(f"min_reserve:{t}") for t in team_ids]))
_assert("§2 (step 5): each GM's Championship Reserve holds exactly 8000 cents",
        all(balance_of(f"reserve:{t}") == OPENING_CHAMPIONSHIP
            for t in team_ids),
        str([balance_of(f"reserve:{t}") for t in team_ids]))
_assert("§2: trial balance is zero after issuance",
        trial_balance() == 0, str(trial_balance()))

again = client().post(f"/league/{LEAGUE_ID}/season-allocation", headers=hdr)
_assert("§2 (retry): a repeated allocation succeeds and creates nothing",
        again.status_code == 200 and again.json().get("created") is False,
        f"{again.status_code} created={again.json().get('created')}")
_assert("§2 (retry): NO duplicate issuance — reserves are unchanged",
        all(balance_of(f"min_reserve:{t}") == OPENING_MIN_RESERVE
            and balance_of(f"reserve:{t}") == OPENING_CHAMPIONSHIP
            for t in team_ids))
_record("4/5 season allocation", "POST /league/{id}/season-allocation",
        "commissioner", "200 created=true",
        "SeasonAllocation + 6 GM allocation rows",
        "min_reserve 14000, reserve 8000, wallet 0 per GM",
        "200 created=false, posts nothing")


# ══════════════════════════════════════════════════════════════════════════════
# §3 · POOL CATALOG AND PROVIDER SUPPORT MEASUREMENT
# ══════════════════════════════════════════════════════════════════════════════

_section("§3 · Pool catalog and measured provider support (steps 6, 7)")

import io  # noqa: E402
from contextlib import redirect_stdout  # noqa: E402

import scripts.bootstrap_pool_catalog as bootstrap  # noqa: E402

with redirect_stdout(io.StringIO()):
    _boot = bootstrap.main([])
    _boot_check = bootstrap.main(["--check"])
_assert("§3 (step 6): the canonical Pool catalog loads (deployment action)",
        _boot == 0 and _boot_check == 0, f"{_boot}/{_boot_check}")

from db.schema import PoolDefinition  # noqa: E402

with SessionLocal() as db:
    _defs = db.query(PoolDefinition).count()
    db.rollback()
_assert("§3 (step 6): the runtime catalog carries the governed definitions",
        _defs == 80, str(_defs))

r = client().post(f"/league/{LEAGUE_ID}/pool/activate?week=1", headers=hdr)
_assert("§3 (step 7): Pool support is MEASURED through the production route",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
act = r.json() if r.status_code == 200 else {}
_assert("§3 (step 7): support is measured from what the payload ACTUALLY "
        "carried, not from what the vocabulary allows",
        sorted(act.get("supported_stats") or [])
        == ["fumbles_lost", "interceptions_thrown", "matchup_away_score",
            "matchup_home_score", "passing_yards"],
        str(act.get("supported_stats")))
_assert("§3 (step 7): twelve definitions become ready on that measurement",
        act.get("definitions_ready") == 12, str(act.get("definitions_ready")))
_assert("§3: at the corpus's frozen instant the measurement is already STALE, "
        "so the readiness gate is proven FAIL-CLOSED before it is re-stamped",
        act.get("eligible_this_phase") == 0
        and act.get("sufficient_for_slate") is False,
        f"eligible={act.get('eligible_this_phase')}")
_record("6/7 catalog + provider support", "POST /league/{id}/pool/activate",
        "commissioner", "200",
        "PoolSourceSupport rows; 12 definitions ready", "none",
        "re-measurable, last measurement wins")

# FIXTURE-ONLY 7 — replay-clock re-stamp. The corpus observes at a frozen 2025
# instant and gate 2 fails closed beyond 24 hours, which the assertion above has
# just proven. This supplies the measured_at a live provider would have supplied
# and changes no gate rule.
from providers.yahoo.identity import build_team_identity_resolver  # noqa: E402
from providers.yahoo.pool_source import measure_league_activation  # noqa: E402

with SessionLocal() as db:
    measure_league_activation(
        db, league_id=LEAGUE_ID,
        snapshot=snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 1),
        resolver=build_team_identity_resolver(db, league_id=LEAGUE_ID),
        measured_at=datetime.now(timezone.utc))
    db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# §4 · WEEK 1 OPEN — the Weekly Minimum is released
# ══════════════════════════════════════════════════════════════════════════════

_section("§4 · Week 1 Open (steps 8, 9) — the Weekly Minimum is released")

r = client().post(f"/league/{LEAGUE_ID}/week/1/open", headers=hdr)
_assert("§4 (step 8): Week Open succeeds through the production route",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
wk1 = r.json() if r.status_code == 200 else {}
_assert("§4 (step 9): every GM received exactly one week's minimum",
        wk1.get("total_released_cents") == WEEKLY_MIN_CENTS * TEAM_COUNT
        and all(t["cents"] == WEEKLY_MIN_CENTS for t in wk1.get("teams", [])),
        str(wk1.get("total_released_cents")))
_assert("§4 (step 9): the released Credits are spendable, and the reserve fell "
        "by exactly what was released",
        all(balance_of(f"min:{t}:1") == WEEKLY_MIN_CENTS for t in team_ids)
        and all(balance_of(f"min_reserve:{t}")
                == OPENING_MIN_RESERVE - WEEKLY_MIN_CENTS for t in team_ids),
        str([balance_of(f"min:{t}:1") for t in team_ids]))

dup = client().post(f"/league/{LEAGUE_ID}/week/1/open", headers=hdr)
_assert("§4 (retry): a DUPLICATE Week Open is safe and replays",
        dup.status_code == 200 and dup.json().get("already_open") is True,
        f"{dup.status_code} {dup.json().get('already_open')}")
_assert("§4 (retry): and released nothing a second time",
        all(balance_of(f"min:{t}:1") == WEEKLY_MIN_CENTS for t in team_ids))
_assert("§4: trial balance zero", trial_balance() == 0)
_record("8/9 Week Open + weekly minimum", "POST /league/{id}/week/1/open",
        "commissioner", "200", "6 weekly-minimum release events",
        f"min:{{team}}:1 = {WEEKLY_MIN_CENTS} each",
        "200 already_open=true, posts nothing")


# ══════════════════════════════════════════════════════════════════════════════
# §5 · WEEKLY POOL COLLECTION
# ══════════════════════════════════════════════════════════════════════════════

_section("§5 · weekly Pool collection (step 15)")

r = client().post(f"/league/{LEAGUE_ID}/pool/collect/1", headers=hdr)
_assert("§5 (step 15): governed Pool collection runs through the route",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
coll = r.json() if r.status_code == 200 else {}
_assert("§5 (step 15): all six GMs were charged exactly once, at the governed "
        "100-cent entry",
        coll.get("teams_charged") == TEAM_COUNT
        and coll.get("weekly_entry_cents") == 100
        and coll.get("total_cents") == 600, str(coll))
_assert("§5 (step 15): four occurrences were opened and funded evenly",
        len(coll.get("instance_ids") or []) == 4
        and coll.get("per_pool_share_cents") == 150,
        str(coll.get("instance_ids")))

dup = client().post(f"/league/{LEAGUE_ID}/pool/collect/1", headers=hdr)
_assert("§5 (retry): a DUPLICATE collection is REFUSED, not double-charged",
        dup.status_code == 409, f"{dup.status_code} {dup.text[:160]}")
_assert("§5 (retry): and the pool account is unchanged by the refusal",
        balance_of(f"pool:{LEAGUE_ID}") == 600,
        str(balance_of(f"pool:{LEAGUE_ID}")))
_assert("§5: trial balance zero", trial_balance() == 0)
_record("15 Pool collection", "POST /league/{id}/pool/collect/1",
        "commissioner", "200", "4 PoolInstance rows",
        f"pool:{LEAGUE_ID} = 600", "409 ALREADY_COLLECTED, zero mutation")


# ══════════════════════════════════════════════════════════════════════════════
# §6 · GOVERNED POOL CLAIMS — BLOCKER 2
# ══════════════════════════════════════════════════════════════════════════════

_section("§6 · governed Pool claim submission (step 19) — BLOCKER 2")

_routes = sorted({getattr(x, "path", "") for x in app.routes})

r = client().get(f"/league/{LEAGUE_ID}/pool/slate/1", headers=gm[2])
_assert("§6: a GM can READ the week's governed slate",
        r.status_code == 200 and len(r.json().get("slots") or []) == 4,
        f"{r.status_code}")

r = client().post("/pool/pick", headers=gm[2], json={
    "league_id": LEAGUE_ID, "team_id": T2, "bet_type": "biggest_winner",
    "pick": T1, "week": 1})
_assert("§6.1: the Pool pick control the UI posts to returns 200 …",
        r.status_code == 200, f"{r.status_code} {r.text[:160]}")
with SessionLocal() as db:
    _claims = db.query(PoolClaim).count()
    db.rollback()
_assert("§6.1 BLOCKER 2: … and writes ZERO governed claims. It targets the "
        "LEGACY prediction model, which the Rev1.3 settlement engine never "
        "reads", _claims == 0, str(_claims))

_claim_routes = [p for p in _routes
                 if "claim" in p.lower() or p.endswith("/pool/pick")]
_assert("§6.2 BLOCKER 2: no GOVERNED claim route is mounted anywhere — the "
        "only pick surface in the product is the legacy one",
        _claim_routes == ["/pool/pick"], str(_claim_routes))
_record("19 governed Pool claim", "NONE — /pool/pick writes the legacy model",
        "GM", "BLOCKED", "pool_claims stays empty", "none", "n/a")

# 6.3 — THE ENGINE IS NOT THE PROBLEM. Called directly, the certified claim path
# makes the SAME production settlement route pay a real winner in §8. This is
# labelled an ENGINE DEMONSTRATION, not a lifecycle pass, and the report says so.
from betting.pool_claims import submit_claim  # noqa: E402

with SessionLocal() as db:
    _rank_id = (db.query(PoolInstance)
                .filter(PoolInstance.league_id == LEAGUE_ID,
                        PoolInstance.week == 1,
                        PoolInstance.definition_key == "most_passing_yards")
                .one().id)
    db.rollback()

with SessionLocal() as db:
    for _c in (T2, T3, T4, T5):
        submit_claim(db, pool_instance_id=_rank_id, team_id=_c, subject_id=T1)
    db.commit()
with SessionLocal() as db:
    _n = db.query(PoolClaim).filter(
        PoolClaim.pool_instance_id == _rank_id).count()
    db.rollback()
_assert("§6.3 (ENGINE DEMONSTRATION, not a lifecycle pass): the certified "
        "claim path records four claims and moves no money",
        _n == 4 and trial_balance() == 0, f"{_n} claims")


# ══════════════════════════════════════════════════════════════════════════════
# §7 · WEEK 1 RESULTS — provider ingest through the automation route
# ══════════════════════════════════════════════════════════════════════════════

_section("§7 · week 1 results arrive: provider ingest (steps 16, 17)")

r = client().post("/admin/tuesday-sync", headers=hdr,
                  json={"league_id": LEAGUE_ID, "week": 1, "mock_mode": True})
_assert("§7 (step 16): the production weekly automation route runs",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
_sync = r.json() if r.status_code == 200 else {}
_steps = {s.get("step"): s for s in _sync.get("steps", [])}

_assert("§7 (step 16): Yahoo roster/player-stat data is read through the "
        "PROVIDER GATEWAY and persisted",
        (_steps.get("refresh_scores") or {}).get("success") is True,
        str(_steps.get("refresh_scores"))[:200])

with SessionLocal() as db:
    w1_final = [m.finalized_at is not None for m in
                db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID,
                                         Matchup.week == 1).all()]
    db.rollback()
_assert("§7 (step 17): matchup finality is governed by a PERSISTED "
        "finalized_at, not by a status string",
        len(w1_final) == 3 and all(w1_final), f"final={w1_final}")

# THE OFFLINE-ONLY STEPS ARE NAMED, NOT HIDDEN. Two of the nine sync steps build
# their own live Yahoo query and fail closed without credentials, and a third
# refuses on the accepted B6 issuance-ledger grounds. All three refuse rather
# than inventing data, and none is on the economic path this lifecycle needs.
_offline = sorted(k for k, v in _steps.items() if not v.get("success"))
print(f"     steps that fail closed offline (expected): {_offline}")
_assert("§7: the offline refusals are exactly the three known ones, and the "
        "economic steps are not among them",
        set(_offline) <= {"sync_players", "capture_roster_slots",
                          "apply_topups"}, str(_offline))
_record("16/17 provider ingest + finality", "POST /admin/tuesday-sync",
        "commissioner", "200",
        "3 Matchup rows with finalized_at set", "none (ingest moves no money)",
        "re-runnable; gateway refuses post-final contradiction")


# ══════════════════════════════════════════════════════════════════════════════
# §8 · POOL SETTLEMENT, ZERO-WINNER AND ROLLOVER
# ══════════════════════════════════════════════════════════════════════════════

_section("§8 · Pool settlement, zero-winner and rollover (steps 19, 20)")

r = client().post(f"/league/{LEAGUE_ID}/pool/settle/1", headers=hdr)
_assert("§8: week 1 Pool settlement succeeds through the route",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
ps = r.json() if r.status_code == 200 else {}
by_key = {s["definition_key"]: s for s in ps.get("settled", [])}

_assert("§8: all four occurrences were resolved",
        len(ps.get("settled", [])) == 4 and ps.get("all_settled") is True,
        str(len(ps.get("settled", []))))

_win = by_key.get("most_passing_yards", {})
_assert("§8 (step 19, reached ONLY via the §6.3 engine demonstration): a "
        "governed Pool DOES pay its winners once claims exist — the settlement "
        "engine is sound and only the admission path is missing",
        _win.get("distributed_cents") == 150
        and len(_win.get("winning_team_ids") or []) == 4,
        str(_win))
_assert("§8 (step 19): the §6.3 even split conserves the pot exactly",
        _win.get("distributed_cents", 0) + _win.get("rolled_over_cents", 0)
        + _win.get("swept_to_championship_cents", 0) == _win.get("pot_cents"),
        str(_win))

_zero = by_key.get("matchups_with_zero_total_turnovers", {})
_assert("§8 (step 20): a genuine ZERO_ELIGIBLE_CLAIMS outcome rolls over "
        "rather than paying anyone",
        _zero.get("classification") == "ZERO_ELIGIBLE_CLAIMS"
        and _zero.get("distributed_cents") == 0
        and _zero.get("rolled_over_cents") == 150, str(_zero))
_assert("§8 (step 20): no occurrence paid out more than its pot",
        all(s["distributed_cents"] <= s["pot_cents"]
            for s in ps.get("settled", [])))

_wallets_pool = {t: balance_of(f"wallet:{t}") for t in team_ids}
dup = client().post(f"/league/{LEAGUE_ID}/pool/settle/1", headers=hdr)
_assert("§8 (retry): a DUPLICATE Pool settlement is safe and replays",
        dup.status_code == 200
        and all(s["replayed"] for s in dup.json().get("settled", [])),
        f"{dup.status_code}")
_assert("§8 (retry): NO duplicate Pool payout",
        all(balance_of(f"wallet:{t}") == _wallets_pool[t] for t in team_ids)
        and trial_balance() == 0)
_record("19/20 Pool settlement + rollover",
        "POST /league/{id}/pool/settle/1", "commissioner", "200",
        "4 PoolInstance settled; 3 carrying rollover",
        "winner pot 150 split across 4 GMs",
        "200 replayed=true, zero further movement")


# ══════════════════════════════════════════════════════════════════════════════
# §9 · WEEK 1 CLOSE — Skunk and Weekly Minimum expiry
# ══════════════════════════════════════════════════════════════════════════════

_section("§9 · Week 1 Close: Skunk + expiry (steps 21-25, 28)")

from economy.economy_events import (  # noqa: E402
    EVENT_SKUNK_ASSESSMENT, receivable_account, skunk_account,
)

r = client().post(f"/league/{LEAGUE_ID}/week/1/close", headers=hdr)
_assert("§9 (step 21): Week Close succeeds through the route",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
close1 = r.json() if r.status_code == 200 else {}

sk = close1.get("skunk") or {}
_assert("§9 (step 22): the Skunk is assessed AUTOMATICALLY inside Week Close — "
        "there is deliberately no separate 'assess Skunk' action",
        sk.get("assessed") is True and sk.get("classification") == "ASSESSED",
        str(sk)[:200])
_assert("§9 (step 23): exactly ONE Skunk outcome, with both teams NAMED",
        len(sk.get("entries") or []) == 1
        and sk["entries"][0]["team_name"]
        and sk["entries"][0]["opponent_team_name"],
        str(sk.get("entries"))[:200])

e = sk["entries"][0]
_assert("§9 (step 23): the skunked team is the week's WORST loss — team 3, "
        "87.0 against 131.75 — not the narrower defeat in another game",
        e["team_id"] == T3 and e["opponent_team_id"] == T4
        and e["score"] == 87.0 and e["opponent_score"] == 131.75,
        f"{e['team_id']} {e['score']} vs {e['opponent_team_id']} "
        f"{e['opponent_score']}")
_assert("§9 (step 23): the exact point differential is 44.75, to the cent of a "
        "point, and it equals the two scores printed beside it",
        round(e["margin"], 2) == 44.75
        and round(e["opponent_score"] - e["score"], 2) == round(e["margin"], 2),
        str(e["margin"]))

_assert("§9 (step 24): the $10 Skunk posts once, as a receivable against the "
        "skunked GM",
        sk.get("amount_cents") == 1000 and e["cents"] == 1000
        and balance_of(receivable_account(T3)) == -1000,
        str(balance_of(receivable_account(T3))))
_assert("§9 (step 24): and the league's Skunk pot received exactly $10",
        balance_of(skunk_account(LEAGUE_ID)) == 1000,
        str(balance_of(skunk_account(LEAGUE_ID))))
_assert("§9 (step 24): no other GM carries a Skunk obligation",
        all(balance_of(receivable_account(t)) == 0
            for t in team_ids if t != T3))
_assert("§9 (step 24): the Skunk is LEDGER-ONLY — it debited no wallet",
        all(balance_of(f"wallet:{t}") == _wallets_pool[t] for t in team_ids))

_assert("§9 (step 25): the UNUSED Weekly Minimum expired for every GM",
        close1.get("total_expired_cents", 0) > 0
        and all(balance_of(f"min:{t}:1") == 0 for t in team_ids),
        str(close1.get("total_expired_cents")))
_assert("§9 (step 25): and it moved to expired_min, not into a wallet",
        sum(balance_of(f"expired_min:{t}") for t in team_ids)
        == close1.get("total_expired_cents"),
        str([balance_of(f"expired_min:{t}") for t in team_ids]))

with SessionLocal() as db:
    _n_sk = (db.query(EconomyEvent)
             .filter(EconomyEvent.league_id == LEAGUE_ID,
                     EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT).count())
    db.rollback()
_assert("§9: exactly one Skunk assessment event exists", _n_sk == 1, str(_n_sk))

_rec_before = balance_of(receivable_account(T3))
_pot_before = balance_of(skunk_account(LEAGUE_ID))
_exp_before = {t: balance_of(f"expired_min:{t}") for t in team_ids}
dup = client().post(f"/league/{LEAGUE_ID}/week/1/close", headers=hdr)
_assert("§9 (step 28): a DUPLICATE Week Close is safe and reports the replay",
        dup.status_code == 200 and dup.json().get("already_closed") is True
        and (dup.json().get("skunk") or {}).get("replayed") is True,
        f"{dup.status_code}")
_assert("§9 (step 28): NO duplicate economic movement — Skunk, pot and expiry "
        "are all unchanged",
        balance_of(receivable_account(T3)) == _rec_before == -1000
        and balance_of(skunk_account(LEAGUE_ID)) == _pot_before == 1000
        and all(balance_of(f"expired_min:{t}") == _exp_before[t]
                for t in team_ids))
with SessionLocal() as db:
    _n_sk2 = (db.query(EconomyEvent)
              .filter(EconomyEvent.league_id == LEAGUE_ID,
                      EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT).count())
    db.rollback()
_assert("§9 (step 28): a duplicate Skunk is impossible", _n_sk2 == 1,
        str(_n_sk2))
_assert("§9: trial balance zero", trial_balance() == 0, str(trial_balance()))
_record("21-25/28 Week Close + Skunk", "POST /league/{id}/week/1/close",
        "commissioner", "200",
        "1 SKUNK_ASSESSMENT event; 6 expiry events",
        f"skunk pot 1000; receivable(team {T3}) -1000; expired_min funded",
        "200 already_closed=true, skunk replayed=true, zero movement")


# ══════════════════════════════════════════════════════════════════════════════
# §10 · THE READS — Ledger and The Week
# ══════════════════════════════════════════════════════════════════════════════

_section("§10 · Ledger and The Week reflect the result (steps 26, 27)")

r = client().get(f"/league/{LEAGUE_ID}/ledger/positions", headers=hdr)
_assert("§10 (step 26): the Ledger read model serves every GM's position",
        r.status_code == 200 and len(r.json()) == TEAM_COUNT,
        f"{r.status_code}")

r = client().get(f"/league/{LEAGUE_ID}/ledger/reconciliation", headers=hdr)
_assert("§10 (step 26): the league's own accounting RECONCILES — two "
        "independent routes to the same number agree",
        r.status_code == 200 and r.json().get("reconciles") is True,
        f"{r.status_code} {r.text[:240]}")

r = client().get(f"/league/{LEAGUE_ID}/ledger/me", headers=gm[3])
_assert("§10 (step 26): a GM sees their OWN position, carrying the expired "
        "minimum this week produced",
        r.status_code == 200 and r.json().get("expired_min_cents", 0) > 0,
        f"{r.status_code} {r.text[:200]}")

r = client().get(f"/league/{LEAGUE_ID}/week/1/matchups", headers=gm[2])
_assert("§10 (step 27): The Week serves the Yahoo matchups, marked final",
        r.status_code == 200 and len(r.json().get("matchups", [])) == 3
        and all(m["final"] for m in r.json().get("matchups", [])),
        f"{r.status_code}")

r = client().get(f"/league/{LEAGUE_ID}/week/1/skunk", headers=gm[2])
_assert("§10 (step 27): SKUNK OF THE WEEK is readable by an ordinary GM and "
        "matches what the close reported",
        r.status_code == 200 and r.json()["entries"][0]["team_id"] == T3
        and round(r.json()["entries"][0]["margin"], 2) == 44.75
        and r.json()["amount_cents"] == 1000, f"{r.status_code}")

r = client().get(f"/league/{LEAGUE_ID}/pool/slate/1", headers=gm[2])
_assert("§10 (step 27): The Week's Pool slate shows the settled occurrences",
        r.status_code == 200
        and all(s["settled"] for s in r.json().get("slots", [])),
        f"{r.status_code}")

r = client().get(f"/league/{LEAGUE_ID}/action/me", headers=gm[2])
_assert("§10 (step 27): the Action read model is served to the GM",
        r.status_code == 200, f"{r.status_code} {r.text[:160]}")
_record("26/27 Ledger + The Week",
        "GET ledger/positions, ledger/reconciliation, ledger/me, "
        "week/1/matchups, week/1/skunk, pool/slate/1, action/me",
        "commissioner + GM", "200 x7", "reads only", "none", "pure reads")


# ══════════════════════════════════════════════════════════════════════════════
# §11 · WEEK 2 OPENS — the schedule is published, and GMs wager
# ══════════════════════════════════════════════════════════════════════════════

_section("§11 · week 2 opens; Versus locked lifecycle (steps 10, 11, 12, 13)")

r = client().post(f"/league/{LEAGUE_ID}/week/2/open", headers=hdr)
_assert("§11: week 2 opens and releases its own minimum",
        r.status_code == 200
        and r.json().get("total_released_cents")
        == WEEKLY_MIN_CENTS * TEAM_COUNT,
        f"{r.status_code} {r.text[:160]}")

# FIXTURE-ONLY 8 — the NOT_FINAL week-2 scoreboard: the schedule as it stands
# DURING the week, before any game is final. This is the state a live league is
# in while its GMs are wagering, and the product has no action that produces it
# — a real league has simply not finished playing. The corpus carries it as a
# named payload whose SCORES ARE IDENTICAL to the final one, so an
# implementation watching scores rather than finality could not pass §12's
# negative.
from providers.yahoo.persist import refresh_league_week  # noqa: E402

with SessionLocal() as db:
    refresh_league_week(
        db, snapshot_for(FixtureTransport(frozen_now=FROZEN_NOW), 2,
                         scoreboard_id="yahoo_wp2bc_scoreboard_w2_pending"),
        now=FROZEN_NOW)
    db.commit()

with SessionLocal() as db:
    w2_final = [m.finalized_at is not None for m in
                db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID,
                                         Matchup.week == 2).all()]
    db.rollback()
_assert("§11: week 2's fixtures are published and NONE is final — the state a "
        "league is actually in while wagering",
        len(w2_final) == 3 and not any(w2_final), str(w2_final))

r = client().post("/beef/challenge", headers=gm[2], json={
    "challenger_team_id": T2, "challenged_team_id": T3, "week": 2,
    "bet_type": "straight", "amount": LOCKED_STAKE, "challenge_mode": "locked"})
_assert("§11 (step 10): a GM creates a Versus challenge through the product",
        r.status_code == 201, f"{r.status_code} {r.text[:200]}")
ch = r.json() if r.status_code == 201 else {}
CH = ch.get("challenge_id")
_assert("§11 (step 13): the issuer's Anchor is REAL escrow at issue, not a soft "
        "reservation",
        balance_of(f"escrow:challenge:{CH}") == int(LOCKED_STAKE * 100),
        str(balance_of(f"escrow:challenge:{CH}")))
_assert("§11 (step 13): and it was sourced from the issuer's spendable minimum",
        balance_of(f"min:{T2}:2") == WEEKLY_MIN_CENTS - int(LOCKED_STAKE * 100),
        str(balance_of(f"min:{T2}:2")))

r = client().post("/beef/counter", headers=gm[3],
                  json={"challenge_id": CH, "countered_amount": LOCKED_COUNTER})
_assert("§11 (step 11): the recipient may COUNTER, and the counter is accepted",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
_assert("§11 (step 11): a counter MOVES NO MONEY (Spec 2 §10)",
        balance_of(f"escrow:challenge:{CH}") == int(LOCKED_STAKE * 100),
        str(balance_of(f"escrow:challenge:{CH}")))

r = client().post("/beef/respond", headers=gm[3],
                  json={"challenge_id": CH, "accept": True})
_assert("§11: the countered proposal cannot be accepted by the COUNTERER — a "
        "counter hands the decision back to the issuer",
        r.status_code == 403, str(r.status_code))

r = client().post("/beef/respond", headers=gm[2],
                  json={"challenge_id": CH, "accept": True})
_assert("§11 (step 12): challenge acceptance succeeds",
        r.status_code == 200, f"{r.status_code} {r.text[:250]}")
acc = r.json() if r.status_code == 200 else {}
_anchor_bet = acc.get("anchor_bet_id")
_derived_bet = acc.get("derived_bet_id")

# ACCEPTANCE MIGRATES the pooled challenge escrow into PER-BET escrow, which is
# what makes each side's exposure attributable at settlement. Asserting on the
# per-bet accounts asserts on where the money actually is.
_assert("§11 (step 13): BOTH sides are funded, in per-bet escrow, at the "
        "COUNTERED stake",
        balance_of(f"escrow:{_anchor_bet}") == int(LOCKED_COUNTER * 100) == 300
        and balance_of(f"escrow:{_derived_bet}") == int(LOCKED_COUNTER * 100),
        f"anchor={balance_of(f'escrow:{_anchor_bet}')}, "
        f"derived={balance_of(f'escrow:{_derived_bet}')}")
_assert("§11 (step 13): and the pooled challenge escrow is fully migrated, not "
        "double-counted", balance_of(f"escrow:challenge:{CH}") == 0,
        str(balance_of(f"escrow:challenge:{CH}")))

with SessionLocal() as db:
    _bet_rows = [(b.id, b.status) for b in
                 db.query(Bet).filter(Bet.beef_challenge_id == CH).all()]
    _bet_ids = sorted(i for i, _ in _bet_rows)
    db.rollback()
_assert("§11 (step 13): acceptance created exactly two pending wagers",
        len(_bet_rows) == 2 and all(s == "pending" for _, s in _bet_rows),
        str(_bet_rows))
_assert("§11: no GM went negative funding the wager",
        all(balance_of(f"wallet:{t}") >= 0 for t in team_ids)
        and balance_of(f"min:{T2}:2") >= 0 and balance_of(f"min:{T3}:2") >= 0)
_assert("§11: trial balance zero across the whole negotiation",
        trial_balance() == 0, str(trial_balance()))
_record("10/11/12/13 Versus locked",
        "POST /beef/challenge -> /beef/counter -> /beef/respond",
        "GM(T2) issue, GM(T3) counter, GM(T2) accept", "201 / 200 / 200",
        f"BeefChallenge {CH}; Bet {_bet_ids} pending",
        f"escrow:{_anchor_bet} = 300, escrow:{_derived_bet} = 300",
        "counterer refused (403); terminal-state retry idempotent")


# ══════════════════════════════════════════════════════════════════════════════
# §12 · DYNAMIC MODE — issue, handshake … and BLOCKER 1
# ══════════════════════════════════════════════════════════════════════════════

_section("§12 · Dynamic mode and Final Lock (step 14) — BLOCKER 1")

r = client().post("/beef/challenge", headers=gm[4], json={
    "challenger_team_id": T4, "challenged_team_id": T5, "week": 2,
    "bet_type": "straight", "amount": DYNAMIC_ANCHOR,
    "challenge_mode": "dynamic"})
_assert("§12 (step 14): a DYNAMIC challenge can be issued through the product — "
        "the mode is offered by the UI's own command layer",
        r.status_code == 201, f"{r.status_code} {r.text[:200]}")
DYN = r.json().get("challenge_id") if r.status_code == 201 else None

r = client().post("/beef/respond", headers=gm[5],
                  json={"challenge_id": DYN, "accept": True})
_assert("§12 (step 14): the Dynamic HANDSHAKE succeeds through /beef/respond",
        r.status_code == 200, f"{r.status_code} {r.text[:260]}")
hs = r.json() if r.status_code == 200 else {}

anchor_acct = f"escrow:challenge:{DYN}:anchor"
derived_acct = f"escrow:challenge:{DYN}:derived"
anchor_bal, derived_bal = balance_of(anchor_acct), balance_of(derived_acct)

_assert("§12: the Handshake funded BOTH sides' maximum exposure into per-side "
        "escrow", anchor_bal > 0 and derived_bal > 0,
        f"anchor={anchor_bal}, derived={derived_bal}")
_assert("§12: the issuer's Anchor escrow equals the anchor stake exactly",
        anchor_bal == int(DYNAMIC_ANCHOR * 100), str(anchor_bal))
_assert("§12: the opponent funded its full Derived CEILING, which is the "
        "protocol's maximum-exposure freeze",
        derived_bal == hs.get("opponent_ceiling_cents"),
        f"{derived_bal} vs ceiling {hs.get('opponent_ceiling_cents')}")
with SessionLocal() as db:
    _dyn_bets = db.query(Bet).filter(Bet.beef_challenge_id == DYN).count()
    db.rollback()
_assert("§12: the Handshake creates NO Bet rows — the Derived side is priced at "
        "Final Lock, and that absence is the protocol, not a gap",
        _dyn_bets == 0, str(_dyn_bets))

# ── THE BLOCKER ITSELF ───────────────────────────────────────────────────────
_lock_routes = [p for p in _routes
                if any(k in p.lower() for k in ("final", "lock", "dynamic"))]
_assert("§12 BLOCKER 1: there is NO production route that can run Final Lock",
        _lock_routes == [], str(_lock_routes))

import economy.dynamic_challenge as _dyn_mod  # noqa: E402

_assert("§12 BLOCKER 1: run_final_lock exists and is certified …",
        callable(getattr(_dyn_mod, "run_final_lock", None)))

_ROOT = os.path.dirname(os.path.abspath(__file__))
_callers = []
for _dirpath, _dirnames, _filenames in os.walk(_ROOT):
    _dirnames[:] = [d for d in _dirnames
                    if d not in (".git", "__pycache__", "node_modules")]
    for _fn in _filenames:
        if not _fn.endswith(".py") or _fn.startswith("test_"):
            continue
        if _fn == "dynamic_challenge.py":
            continue
        try:
            with open(os.path.join(_dirpath, _fn), encoding="utf-8") as _fh:
                _txt = _fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        if "run_final_lock" in _txt or "acquire_final_lock_claim" in _txt:
            _callers.append(os.path.relpath(os.path.join(_dirpath, _fn), _ROOT))
_assert("§12 BLOCKER 1: … and NOTHING in the product calls it — no route, no "
        "scheduler, no worker, no management command",
        _callers == [], str(_callers))

_assert("§12 BLOCKER 1: so a handshaken Dynamic wager's escrow is STRANDED — "
        "both sides' Credits are held with no product path to price them",
        anchor_bal + derived_bal > 0,
        f"{anchor_bal + derived_bal} cents held on challenge {DYN}")
_record("14 Dynamic Final Lock", "NONE — no production surface exists",
        "n/a (Rev9 §Actor class: scheduled system worker, at kickoff)",
        "BLOCKED", f"challenge {DYN} handshaken; 0 Bet rows",
        f"{anchor_bal + derived_bal} cents stranded in per-side escrow", "n/a")

from betting.pool_season_boundary import season_final_week  # noqa: E402
from economy.season_close_orchestrator import (  # noqa: E402
    SeasonClosePreconditionError, verify_preconditions,
)

with SessionLocal() as db:
    _lg = db.query(League).filter(League.id == LEAGUE_ID).one()
    _step = None
    try:
        verify_preconditions(db, league_id=LEAGUE_ID,
                             final_week=season_final_week(_lg))
    except SeasonClosePreconditionError as exc:
        _step = exc.step
    db.rollback()
_assert("§12 BLOCKER 1: and Season Close is consequently refused — the stranded "
        "escrow is a permanent close-prerequisite failure",
        _step in ("versus_terminal", "escrow_resolved"), f"step={_step!r}")
_assert("§12: trial balance is still zero — the blocker STRANDS Credits, it "
        "does not lose them", trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
# §13 · WEEK 2 POOL COLLECTION AND THE FINALITY NEGATIVE
# ══════════════════════════════════════════════════════════════════════════════

_section("§13 · week 2 collection; settlement before finality is refused "
         "(step 11)")

r = client().post(f"/league/{LEAGUE_ID}/pool/collect/2", headers=hdr)
_assert("§13: week 2's Pools are collected — the engine's own guard allowed "
        "this only because week 1 is fully settled",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")

_pool_before = balance_of(f"pool:{LEAGUE_ID}")
_tb_before = trial_balance()
_wallets_before = {t: balance_of(f"wallet:{t}") for t in team_ids}
_expired_before = {t: balance_of(f"expired_min:{t}") for t in team_ids}
_min2_before = {t: balance_of(f"min:{t}:2") for t in team_ids}

r = client().post(f"/league/{LEAGUE_ID}/pool/settle/2", headers=hdr)
_assert("§13 (step 11): Pool settlement BEFORE finality is REFUSED with 409",
        r.status_code == 409, f"{r.status_code} {r.text[:200]}")
_detail = (r.json().get("detail") or {}) if r.status_code == 409 else {}
_assert("§13 (step 11): and the governed reason code is RESULTS_NOT_READY",
        _detail.get("reason_code") == "RESULTS_NOT_READY", str(_detail)[:180])
_assert("§13 (step 11): the refusal names WHICH games are unfinalized",
        len(_detail.get("unfinalized_matchup_ids") or []) == 3,
        str(_detail)[:200])

r = client().post(f"/league/{LEAGUE_ID}/week/2/close", headers=hdr)
_assert("§13 (step 11): Week Close before finality is refused with 409 too",
        r.status_code == 409, f"{r.status_code} {r.text[:200]}")
_assert("§13 (step 11): with the same governed reason code",
        (r.json().get("detail") or {}).get("reason_code")
        == "RESULTS_NOT_READY", str(r.json())[:180])

_assert("§13 (step 11): ZERO MUTATION — the pool account is untouched by both "
        "refusals", balance_of(f"pool:{LEAGUE_ID}") == _pool_before,
        str(_pool_before))
_assert("§13 (step 11): ZERO MUTATION — no wallet moved",
        all(balance_of(f"wallet:{t}") == _wallets_before[t] for t in team_ids))
_assert("§13 (step 11): ZERO MUTATION — the refused close expired no weekly "
        "minimum, so the week is not PARTLY closed",
        all(balance_of(f"expired_min:{t}") == _expired_before[t]
            for t in team_ids)
        and all(balance_of(f"min:{t}:2") == _min2_before[t]
                for t in team_ids))
_assert("§13 (step 11): trial balance untouched",
        trial_balance() == _tb_before == 0, str(trial_balance()))
_record("11 finality negative",
        "POST /league/{id}/pool/settle/2 and /week/2/close", "commissioner",
        "409 RESULTS_NOT_READY (both)", "no state change", "no posting",
        "safely retryable once results are final")


# ══════════════════════════════════════════════════════════════════════════════
# §14 · WEEK 2 RESULTS — settlement, close, and the continuation proof
# ══════════════════════════════════════════════════════════════════════════════

_section("§14 · week 2 settles and closes — continuation (steps 18, 29)")

r = client().post("/admin/tuesday-sync", headers=hdr,
                  json={"league_id": LEAGUE_ID, "week": 2, "mock_mode": True})
_assert("§14: week 2's final results ingest through the production route",
        r.status_code == 200, f"{r.status_code} {r.text[:160]}")
_steps2 = {s.get("step"): s for s in (r.json().get("steps", [])
                                      if r.status_code == 200 else [])}

with SessionLocal() as db:
    _w2_final = [m.finalized_at is not None for m in
                 db.query(Matchup).filter(Matchup.league_id == LEAGUE_ID,
                                          Matchup.week == 2).all()]
    db.rollback()
_assert("§14: week 2 is now economically final by persisted finalized_at",
        len(_w2_final) == 3 and all(_w2_final), str(_w2_final))

_assert("§14 (step 18): Versus settlement ran on the same production run",
        (_steps2.get("settle_bets") or {}).get("success") is True,
        str(_steps2.get("settle_bets"))[:200])

with SessionLocal() as db:
    _statuses = sorted(b.status for b in
                       db.query(Bet).filter(Bet.id.in_(_bet_ids)).all())
    db.rollback()
_assert("§14 (step 18): both legs of the accepted wager reached a TERMINAL "
        "state", len(_statuses) == 2
        and all(s in ("won", "lost", "push") for s in _statuses),
        str(_statuses))
_assert("§14 (step 18): every escrow account for the wager is drained — "
        "nothing is left stranded",
        balance_of(f"escrow:challenge:{CH}") == 0
        and balance_of(f"escrow:{_anchor_bet}") == 0
        and balance_of(f"escrow:{_derived_bet}") == 0,
        f"anchor={balance_of(f'escrow:{_anchor_bet}')}, "
        f"derived={balance_of(f'escrow:{_derived_bet}')}")
_assert("§14: no GM holds a negative balance after settlement",
        all(balance_of(f"wallet:{t}") >= 0 for t in team_ids),
        str({t: balance_of(f"wallet:{t}") for t in team_ids}))

_wallets_post = {t: balance_of(f"wallet:{t}") for t in team_ids}
dup = client().post(f"/league/{LEAGUE_ID}/settle/2", headers=hdr)
_assert("§14 (retry): a DUPLICATE Versus settlement through the commissioner "
        "route is safe", dup.status_code == 200,
        f"{dup.status_code} {dup.text[:160]}")
_assert("§14 (retry): it reports the week already settled and moves nothing",
        dup.json().get("already_settled") is True
        and all(balance_of(f"wallet:{t}") == _wallets_post[t]
                for t in team_ids), str(dup.json())[:160])

r = client().post(f"/league/{LEAGUE_ID}/pool/settle/2", headers=hdr)
_assert("§14 (step 29): the SAME route that refused before finality now settles "
        "week 2", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
ps2 = r.json() if r.status_code == 200 else {}
_assert("§14 (step 20): the week 1 carry was CONSUMED as a continuation — a "
        "carried pot is larger than a fresh week's even share",
        any(s["pot_cents"] > 150 for s in ps2.get("settled", [])),
        str([s["pot_cents"] for s in ps2.get("settled", [])]))

r = client().post(f"/league/{LEAGUE_ID}/week/2/close", headers=hdr)
_assert("§14 (step 29): week 2 closes, so the lifecycle CONTINUES rather than "
        "closing one isolated week",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
close2 = r.json() if r.status_code == 200 else {}
_assert("§14 (step 29): week 2 assessed its OWN Skunk",
        (close2.get("skunk") or {}).get("assessed") is True,
        str(close2.get("skunk"))[:180])
_assert("§14 (step 29): and expired week 2's minimum for every GM",
        all(balance_of(f"min:{t}:2") == 0 for t in team_ids)
        and close2.get("total_expired_cents", 0) > 0)

with SessionLocal() as db:
    _n_sk3 = (db.query(EconomyEvent)
              .filter(EconomyEvent.league_id == LEAGUE_ID,
                      EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT).count())
    db.rollback()
_assert("§14: two governed weeks, two Skunk assessments — one per week, never "
        "two for one", _n_sk3 == 2, str(_n_sk3))

r = client().get(f"/league/{LEAGUE_ID}/lifecycle", headers=hdr)
_assert("§14: the lifecycle read agrees the current week is open, closed and "
        "Skunk-assessed",
        r.status_code == 200 and r.json()["week"]["week"] == 2
        and r.json()["week"]["opened"] is True
        and r.json()["week"]["closed"] is True
        and r.json()["week"]["skunk_assessed"] is True,
        str(r.json().get("week"))[:220])
_assert("§14: trial balance zero after two full weeks",
        trial_balance() == 0, str(trial_balance()))
_record("18/29 week 2 settlement, close and continuation",
        "POST /admin/tuesday-sync, /league/{id}/settle/2, pool/settle/2, "
        "week/2/close", "commissioner", "200 x4",
        "week 2 final, settled, closed; second Skunk",
        "per-bet escrow drained; carry consumed; second expiry",
        "all four are idempotent")


# ══════════════════════════════════════════════════════════════════════════════
# §15 · SEASON CLOSE — prerequisites and the attempt
# ══════════════════════════════════════════════════════════════════════════════

_section("§15 · season-close prerequisites and the attempt (steps 30-37)")

r = client().post(f"/league/{LEAGUE_ID}/season/close", headers=hdr)
_season_close_status = r.status_code
try:
    _season_close_body = r.json()
except ValueError:
    _season_close_body = {}
_close_step = ((_season_close_body.get("detail") or {}).get("reason_code")
               if _season_close_status != 200 else None)

print(f"     season close -> {_season_close_status} "
      f"{str(_season_close_body)[:240]}")

_assert("§15 (steps 30-37): SEASON CLOSE IS REFUSED — the lifecycle cannot "
        "complete through the product", _season_close_status == 409,
        str(_season_close_status))
_assert("§15: the refusal is a GOVERNED, NAMED prerequisite",
        _close_step in ("versus_terminal", "escrow_resolved", "pool_rollover"),
        str(_close_step))
_assert("§15: and the refusal moved no money",
        trial_balance() == 0, str(trial_balance()))

_pending_dyn = balance_of(anchor_acct) + balance_of(derived_acct)
_assert("§15: BLOCKER 1's stranded Dynamic escrow is still held, and is a "
        "permanent bar to `escrow_resolved`",
        _pending_dyn > 0, f"{_pending_dyn} cents on challenge {DYN}")

# WHY EACH SURVIVING ROLLOVER SURVIVES, attributed rather than lumped together.
# The distinction decides whether `pool_rollover` is a BLOCKER consequence or a
# property of a two-week synthetic season, and the report must not confuse them:
#
#   ZERO_ELIGIBLE_CLAIMS  no SUBJECT qualified. No GM claim could have changed
#                         this, so BLOCKER 2 is NOT its cause. Such a pot rolls
#                         forward until `season_final_week`, where POR §5 sweeps
#                         it to Championship — week 17 for this league, which a
#                         real season reaches and a two-week fixture does not.
#
#   CLAIMS_PRESENT        a winner existed and no GM held a winning ticket.
#                         With no production claim route, no GM COULD hold one,
#                         so this rollover IS a BLOCKER 2 consequence.
print("\n     surviving rollover, by cause:")
with SessionLocal() as db:
    _rows = (db.query(PoolInstance)
             .filter(PoolInstance.league_id == LEAGUE_ID,
                     PoolInstance.rollover_cents > 0)
             .order_by(PoolInstance.week, PoolInstance.slot).all())
    _live = [(i.week, i.slot, i.definition_key, i.rollover_cents,
              i.settlement_classification) for i in _rows]
    _final_week = season_final_week(
        db.query(League).filter(League.id == LEAGUE_ID).one())
    db.rollback()
for _wk, _slot, _key, _cents, _cls in _live:
    _cause = ("SUBJECT-layer zero — no claim could have changed it; sweeps at "
              f"season_final_week {_final_week}"
              if _cls == "ZERO_ELIGIBLE_CLAIMS"
              else "zero winning TICKETS — no GM could claim (BLOCKER 2)")
    print(f"       w{_wk} slot{_slot} {_key} = {_cents} cents  [{_cls}] {_cause}")

_assert("§15: live rollover remains, which independently bars `pool_rollover`",
        len(_live) > 0, f"{len(_live)} occurrence(s)")
_assert("§15: and every surviving rollover here is SUBJECT-layer zero, so it "
        "is a property of a two-week synthetic season — it would sweep to "
        "Championship at season_final_week — NOT a blocker consequence",
        all(_cls == "ZERO_ELIGIBLE_CLAIMS" for *_, _cls in _live),
        str([(k, c) for _, _, k, _, c in _live]))

r = client().post(f"/league/{LEAGUE_ID}/season/close", headers=hdr)
_assert("§15 (step 37): a REPEATED Season Close is safe — same refusal, still "
        "no movement",
        r.status_code == _season_close_status and trial_balance() == 0,
        f"{r.status_code}")
_record("30-37 Season Close", "POST /league/{id}/season/close", "commissioner",
        f"409 {_close_step}", "no state change", "no posting",
        "409 again, zero mutation")

for _unreached in (
        "32 Skunk season distribution/reconciliation",
        "33 Championship Reserve 60/30/10",
        "34 expired Weekly Minimum reconciliation",
        "35 Current Settle / final balances"):
    _record(_unreached, "POST /league/{id}/season/close", "commissioner",
            f"NOT REACHED — blocked upstream at {_close_step}", "-", "-", "-")


# ══════════════════════════════════════════════════════════════════════════════
# §16 · INVARIANTS THAT MUST HOLD REGARDLESS
# ══════════════════════════════════════════════════════════════════════════════

_section("§16 · economic invariants and league isolation (steps 36, 38)")

_assert("§16 (step 36): the global trial balance is ZERO at the end of the run",
        trial_balance() == 0, str(trial_balance()))
_assert("§16: no GM holds a negative wallet",
        all(balance_of(f"wallet:{t}") >= 0 for t in team_ids),
        str({t: balance_of(f"wallet:{t}") for t in team_ids}))
_assert("§16: no GM holds a negative Weekly Minimum reserve",
        all(balance_of(f"min_reserve:{t}") >= 0 for t in team_ids))
_assert("§16: no GM's Championship Reserve was touched by weekly play",
        all(balance_of(f"reserve:{t}") == OPENING_CHAMPIONSHIP
            for t in team_ids),
        str([balance_of(f"reserve:{t}") for t in team_ids]))
_assert("§16: two governed weeks consumed exactly two weeks of reserve",
        all(balance_of(f"min_reserve:{t}")
            == OPENING_MIN_RESERVE - 2 * WEEKLY_MIN_CENTS for t in team_ids),
        str([balance_of(f"min_reserve:{t}") for t in team_ids]))

with SessionLocal() as db:
    other = League(name="WP6 Isolation League", season=SEASON,
                   season_final_week=17, playoff_start_week=15)
    db.add(other)
    db.flush()
    o_team = Team(league_id=other.id, team_name="Other T1", owner="O",
                  email="wp6-other1@x.test")
    db.add(o_team)
    db.flush()
    db.add(Wallet(team_id=o_team.id, balance=0.0))
    o_user = User(email="wp6-other-comm@x.test",
                  hashed_password=hash_password(PASSWORD),
                  team_id=o_team.id, role="commissioner")
    db.add(o_user)
    db.flush()
    db.add(LeagueCommissioner(league_id=other.id, user_id=o_user.id,
                              source="bootstrap"))
    db.commit()
    OTHER_ID, OTHER_TEAM = other.id, o_team.id

o_hdr = bearer("wp6-other-comm@x.test")

_assert("§16 (step 38): a FOREIGN commissioner cannot close this league's week",
        client().post(f"/league/{LEAGUE_ID}/week/1/close",
                      headers=o_hdr).status_code == 403)
_assert("§16 (step 38): nor collect its Pools",
        client().post(f"/league/{LEAGUE_ID}/pool/collect/1",
                      headers=o_hdr).status_code == 403)
_assert("§16 (step 38): nor close its season",
        client().post(f"/league/{LEAGUE_ID}/season/close",
                      headers=o_hdr).status_code == 403)
_assert("§16 (step 38): nor read its accounting",
        client().get(f"/league/{LEAGUE_ID}/ledger/reconciliation",
                     headers=o_hdr).status_code == 403)
_assert("§16 (step 38): and this league's economics never touched the other",
        balance_of(skunk_account(OTHER_ID)) == 0
        and balance_of(f"pool:{OTHER_ID}") == 0
        and balance_of(f"wallet:{OTHER_TEAM}") == 0)

with SessionLocal() as db:
    _foreign_events = (db.query(EconomyEvent)
                       .filter(EconomyEvent.league_id == OTHER_ID).count())
    _mine_events = (db.query(EconomyEvent)
                    .filter(EconomyEvent.league_id == LEAGUE_ID).count())
    db.rollback()
_assert("§16 (step 38): every economy event is league-scoped",
        _foreign_events == 0 and _mine_events > 0,
        f"other={_foreign_events}, mine={_mine_events}")
_assert("§16 (step 36): trial balance is STILL zero with two leagues present",
        trial_balance() == 0, str(trial_balance()))


# ══════════════════════════════════════════════════════════════════════════════
# THE PRODUCTION-INTERFACE LEDGER
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 78)
print("PRODUCTION-INTERFACE LEDGER — surface used for every lifecycle step")
print("=" * 78)
for _step_, _surface, _actor, _result, _persisted, _led, _retry in _ledger:
    print(f"\n  {_step_}")
    print(f"    surface   : {_surface}")
    print(f"    actor     : {_actor}")
    print(f"    result    : {_result}")
    if _persisted:
        print(f"    persisted : {_persisted}")
    if _led:
        print(f"    ledger    : {_led}")
    if _retry:
        print(f"    retry     : {_retry}")

tdb.teardown()

print("\n" + "=" * 78)
if _failures:
    print(f"WP6 LIFECYCLE SUITE — FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("WP6 LIFECYCLE SUITE — every assertion PASSED")
print()
print("  A passing run does NOT mean the lifecycle completes. It means the run")
print("  behaved exactly as this suite states, INCLUDING the two blockers it")
print("  asserts:")
print("    BLOCKER 1  Dynamic Final Lock has no production trigger  (step 14)")
print("    BLOCKER 2  governed Pool claims have no production route (step 19)")
print("  Season Close is consequently refused, so the answer to WP6's question")
print("  is NO. See the WP6 report for the exact step and technical reason.")
print("=" * 78)
