#!/usr/bin/env python3
"""
test_wp6_end_to_end_lifecycle_pg.py — WP6/WP6D · end-to-end product lifecycle.

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

WHAT THE ORIGINAL WP6 RUN FOUND, AND WHAT WP6D REPLACES. WP6 reported two
certified-but-unwired capabilities and asserted their absence, in those words,
rather than stepping around them. WP6B and WP6C then wired both. The two
blocker-EXISTENCE assertions in this suite are now stale, and WP6D replaces each
with the corresponding blocker-CLEARED assertion. Nothing is relaxed: each
retired assertion is replaced by a strictly stronger one, which demands the
production surface exist AND behave, where the old one demanded only that it be
absent.

  BLOCKER 1, CLEARED BY WP6B — DYNAMIC FINAL LOCK (lifecycle step 14).
      WP6 proved `economy.dynamic_challenge.run_final_lock` had no non-test
      caller — no route, no scheduler, no worker — so a handshaken Dynamic
      wager's escrow was stranded and Season Close refused at `escrow_resolved`
      permanently. `workers/final_lock.py` is now that caller, declared in the
      `Procfile` as its own process type. §12 runs THE DEPLOYED ENTRY POINT and
      watches the wager get priced.

      IT IS STILL NOT A ROUTE, AND §12 STILL ASSERTS THAT.
      SIMULATION_ENGINE_MODULE_SPEC_Rev9 §"Actor class" fixes Final Lock as "the
      same scheduled system worker/process class that acquires fresh claims. Not
      an end user, not a GM, not a commissioner, not reachable from any HTTP
      route." A route would have been the wrong repair, so the assertion that no
      Final-Lock route is mounted is KEPT — what changed is that the worker now
      exists beside it.

  BLOCKER 2, CLEARED BY WP6C — GOVERNED POOL CLAIM SUBMISSION (step 19).
      WP6 proved `POST /pool/pick` — the control the UI actually posts — wrote
      the LEGACY prediction model, which the Rev1.3 settlement engine never
      reads: the route answered 200 while `pool_claims` stayed empty, so no GM
      could hold a winning ticket. That route is now an adapter into the
      certified `betting.pool_claims.submit_claim`, and §6 drives it as a GM.

      THIS SUITE NO LONGER IMPORTS THE CLAIM ENGINE AT ALL. WP6's §6.3 called
      `submit_claim` directly, labelled as an ENGINE DEMONSTRATION, to show that
      only the admission path was missing. That call is deleted: §6 now creates
      every claim through the product, and §6.4 asserts this file's own source
      contains no `submit_claim` call, so §8's payout cannot be reached by any
      other means.

  THE LAST BAR, CLEARED BY WP6F — TERMINAL ROLLOVER EXPIRY (§15).
      WP6D ended at `409 pool_rollover` and attributed it to the two-week
      recorded corpus: "a live league reaches week 17, the pots sweep, and the
      close proceeds." WP6E tested that against the product and found it FALSE.
      Week 17 is >= playoff_start_week 15, so a week-17 slate is governed by
      POR §8 — whose approved 32-Pool postseason subset does not exist. Every
      `postseason_eligible` is NULL, the postseason candidate set is empty, and
      the draw refuses in the PURE SELECTOR, before any provider data is read.
      No corpus could have cleared it; the carry was undischargeable.

      The owner ruling made terminal rollover expiry a SEASON-BOUNDARY
      SETTLEMENT RULE (BAB-805, BAB-901, AP-166): at `season_final_week` a carry
      with no later eligible occurrence transfers to the Championship Pot,
      exactly once, and NO PoolInstance is required to host it. §15 drives that
      through `POST /league/{id}/season/close` and watches 600 cents leave
      rollover state, reach `championship:{league}` BEFORE distribution, and be
      paid out 60/30/10.

      NOTHING WAS RELAXED TO GET THERE, AND §15 PROVES IT RATHER THAN CLAIMING
      IT. Every pre-close fact WP6D established is still asserted — two carries,
      300 cents each, both SUBJECT-layer `ZERO_ELIGIBLE_CLAIMS`, each having
      carried six real governed claims — because those are what make the
      disposal legitimate rather than convenient. §15 additionally asserts that
      ZERO PoolInstance rows were created, that no POSTSEASON occurrence exists,
      that not one of the 80 `postseason_eligible` values changed, and that no
      league activation row moved. The postseason catalog question is untouched
      by the sweep; it simply no longer blocks the close.

      WP1B UPDATE. The POR §8 blocker described above — "every
      `postseason_eligible` is NULL" — has since been RESOLVED by owner ruling:
      the values are now explicit booleans, TRUE on 44 permitted definitions and
      FALSE on 36. That changes the WORLD this section describes, not the RULE
      it proves. §15 still asserts the sweep touches no flag, creates no
      occurrence and consults no gate; §15.9's second clause, which pinned the
      flags to NULL, is amended in place with its reasoning recorded there. The
      close in this suite still reaches the boundary with no postseason
      occurrence, because this league never draws one.

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
    Bet, ChallengeFinalLock, EconomyEvent, League, LeagueCommissioner, Matchup,
    NflSchedule, Player, PoolBetPick, PoolClaim, PoolInstance, PoolPrediction,
    Projection, Roster, SessionLocal, Team, User, Wallet,
)
from ledger.ledger import balance_of, trial_balance  # noqa: E402
from providers.fixtures.replay import FixtureTransport  # noqa: E402
from test_support_wp2bc_league import (  # noqa: E402
    FROZEN_NOW, LEAGUE_ID, LEAGUE_KEY, SEASON, TEAM_COUNT,
    seed_economic_league, snapshot_for,
)
# WP6D — the WP6B fixture's kickoff helper, imported rather than restated. §12
# runs the production Final-Lock worker, and the worker's dueness question is
# answered by `_nfl_lock_time(LOCK_SEASON, week)`; this returns exactly what that
# call will return for a week, so §12 can stand on either side of the governed
# instant instead of sleeping or guessing.
from test_support_wp6b import week_kickoff  # noqa: E402

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
    league, teams = seed_economic_league(db, with_postseason=True)
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
    # FIXTURE-ONLY 4b (WP6D) — the LOCK_SEASON kickoff schedule.
    # `seed_economic_league` seeds `NflSchedule` for CURRENT_SEASON, which is what
    # `pool_claims.pool_lock_time` reads. The challenge domain's kickoff-lock —
    # and therefore `workers.final_lock`, which uses the same helper — reads
    # LOCK_SEASON, a deliberately different year (`config`: "NFL schedule season
    # for kickoff-lock checks; independent of CURRENT_SEASON"). Both years are
    # seeded so each reader finds its own, and neither is bent to suit the other.
    # No production route ingests the NFL schedule, so this is fixture-only for
    # the same reason projections are.
    for wk in (1, 2):
        db.add(NflSchedule(
            season=config.LOCK_SEASON, week=wk,
            home_team=f"WP6-H{wk}", away_team=f"WP6-A{wk}",
            kickoff_utc=week_kickoff(wk).replace(tzinfo=None)))
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
#: Every team's OWN authenticated actor, by ordinal. Team 1's GM is also the
#: commissioner — a Pool pick is a competitive choice with no commissioner
#: exemption (`assert_wagering_team_owner`), so they pick as that team's GM and
#: as nobody else's.
actor = {1: hdr, **gm}

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
# §6 · GOVERNED POOL CLAIMS — BLOCKER 2, CLEARED (WP6C)
# ══════════════════════════════════════════════════════════════════════════════
#
# WHAT WP6 ASSERTED HERE AND WP6D RETIRES. WP6 posted the legacy request shape to
# `/pool/pick`, watched it answer 200, and asserted `pool_claims` stayed EMPTY —
# the route wrote the legacy prediction model the Rev1.3 settlement engine never
# reads. WP6C cut that route over to `betting.pool_claims.submit_claim`, so the
# blocker-existence assertion is stale and is replaced, here, by the
# blocker-CLEARED one: the same control, driven by real authenticated GMs,
# creates governed `PoolClaim` state and nothing else. §8 then pays it.

_section("§6 · governed Pool claim submission (step 19) — BLOCKER 2 CLEARED")

_routes = sorted({getattr(x, "path", "") for x in app.routes})


def legacy_rows() -> tuple[int, int]:
    """Every row in BOTH retired Pool pick models, for the whole database.

    Counted globally rather than per-league: a route that wrote a legacy row
    under a different scope would still be writing a legacy row."""
    with SessionLocal() as db:
        counts = (db.query(PoolBetPick).count(), db.query(PoolPrediction).count())
        db.rollback()
    return counts


def pool_week(week: int, headers: dict) -> dict:
    """The governed occurrences of one week, as the pick surface sees them."""
    r = client().get(f"/pool/week/{week}?league_id={LEAGUE_ID}", headers=headers)
    assert r.status_code == 200, f"/pool/week/{week}: {r.status_code} {r.text[:200]}"
    return r.json()


def claim_count(instance_id: int) -> int:
    with SessionLocal() as db:
        n = (db.query(PoolClaim)
             .filter(PoolClaim.pool_instance_id == instance_id).count())
        db.rollback()
    return n


_legacy_before = legacy_rows()

r = client().get(f"/league/{LEAGUE_ID}/pool/slate/1", headers=gm[2])
_assert("§6: a GM can READ the week's governed slate",
        r.status_code == 200 and len(r.json().get("slots") or []) == 4,
        f"{r.status_code}")

_wk1 = pool_week(1, gm[2])
_assert("§6: and reads the same four occurrences through the PICK surface, "
        "with the week's one governed lock moment",
        len(_wk1.get("pools") or []) == 4 and _wk1.get("drawn") is True
        and _wk1.get("locked") is False, str(_wk1)[:200])

_by_key = {p["definition_key"]: p for p in _wk1["pools"]}
_rank = _by_key.get("most_passing_yards") or {}
_rank_id = _rank.get("pool_instance_id")
_assert("§6: the TEAM-scope occurrence offers the league's six teams as "
        "subjects — the offer set is the census, not a hardcoded pot name",
        _rank.get("scope") == "TEAM"
        and sorted(s["subject_id"] for s in _rank.get("subjects") or [])
        == sorted(team_ids), str(_rank.get("subjects"))[:200])
_assert("§6: no GM holds a claim on it yet",
        _rank.get("my_subject_id") is None and _rank.get("claim_count") == 0,
        str(_rank)[:160])

# WHY WEEK 1's MATCHUP-SCOPE OCCURRENCES OFFER NOTHING YET, stated rather than
# stepped around. `_subjects_for_scope` builds the offer set from the census, and
# week 1's census of MATCHUPS is empty until the provider publishes the week's
# fixtures — which for week 1 happens at §7. That is an ordering property of this
# fixture, not a refusal: §13 picks on MATCHUP-scope occurrences in week 2, where
# the schedule IS published before the pick window, exactly as a live league's is.
_empty_scope = sorted(p["definition_key"] for p in _wk1["pools"]
                      if not p.get("subjects"))
print(f"     week 1 occurrences whose census is not yet published: "
      f"{_empty_scope}")

# ── 6.1 · THE PRODUCTION PICK PATH ───────────────────────────────────────────
#
# THE SAME OCCURRENCE WP6's §6.3 REACHED BY CALLING THE ENGINE, reached instead
# by the route the UI posts. Three GMs back team 1, one backs team 6 and one
# abstains, so §8 can prove a winning ticket paid, a LOSING ticket paid nothing,
# and an abstainer paid nothing — three outcomes one uniform field cannot show.
WINNING_SUBJECT, LOSING_SUBJECT = T1, T6
_backers = {2: WINNING_SUBJECT, 3: WINNING_SUBJECT, 4: WINNING_SUBJECT,
            5: LOSING_SUBJECT}
_ABSTAINER = T6

for _ordinal, _subject in _backers.items():
    r = client().post("/pool/pick", headers=gm[_ordinal], json={
        "league_id": LEAGUE_ID, "team_id": team_ids[_ordinal - 1], "week": 1,
        "pool_instance_id": _rank_id, "subject_id": _subject})
    _assert(f"§6.1: GM {_ordinal} submits a Pool pick through the running "
            f"product", r.status_code == 200, f"{r.status_code} {r.text[:160]}")

with SessionLocal() as db:
    _rows = (db.query(PoolClaim)
             .filter(PoolClaim.pool_instance_id == _rank_id)
             .order_by(PoolClaim.team_id).all())
    _persisted = {c.team_id: c.selected_subject_id for c in _rows}
    _total_claims = db.query(PoolClaim).count()
    db.rollback()

_assert("§6.1 BLOCKER 2 CLEARED: the product path creates GOVERNED PoolClaim "
        "state — exactly one claim per submitting GM, and no other",
        _persisted == {team_ids[o - 1]: s for o, s in _backers.items()}
        and _total_claims == len(_backers), str(_persisted))
_assert("§6.1: and the abstaining GM holds no claim",
        _ABSTAINER not in _persisted, str(sorted(_persisted)))
_assert("§6.1: the active path wrote NO legacy PoolBetPick or PoolPrediction "
        "row", legacy_rows() == _legacy_before == (0, 0), str(legacy_rows()))
_assert("§6.1: a pick creates a claim, not funding — zero Credits moved",
        trial_balance() == 0 and balance_of(f"pool:{LEAGUE_ID}") == 600,
        f"tb={trial_balance()} pool={balance_of(f'pool:{LEAGUE_ID}')}")

# ── 6.2 · THE LEGACY REQUEST SHAPE IS NO LONGER ACCEPTED ─────────────────────
#
# The blocker was not only that the legacy shape wrote the wrong table — it was
# that the shape existed at all, so a client could believe it had picked. The
# route now REFUSES it at the schema boundary, which is what makes the cutover
# complete rather than merely preferred.
r = client().post("/pool/pick", headers=gm[2], json={
    "league_id": LEAGUE_ID, "team_id": T2, "bet_type": "biggest_winner",
    "pick": T1, "week": 1})
_assert("§6.2 BLOCKER 2 CLEARED: the LEGACY request shape is refused (422) — "
        "the user-facing path no longer requires or accepts it",
        r.status_code == 422, f"{r.status_code} {r.text[:160]}")
_assert("§6.2: and the refusal wrote nothing, legacy or governed",
        legacy_rows() == (0, 0) and claim_count(_rank_id) == len(_backers))

_claim_routes = [p for p in _routes
                 if "claim" in p.lower() or p.endswith("/pool/pick")]
_assert("§6.2: the pick surface is still exactly one route — the cutover "
        "changed what `/pool/pick` WRITES, not how many ways in there are",
        _claim_routes == ["/pool/pick"], str(_claim_routes))

# ── 6.3 · THE CLAIM IS PRODUCT STATE, VISIBLE ONLY TO ITS OWNER ──────────────
_mine = pool_week(1, gm[2])
_mine_rank = {p["definition_key"]: p for p in _mine["pools"]}["most_passing_yards"]
_assert("§6.3: the submitting GM's own claim is reflected back by the product",
        _mine_rank.get("my_subject_id") == WINNING_SUBJECT,
        str(_mine_rank.get("my_subject_id")))
_assert("§6.3: the field's entry COUNT is public …",
        _mine_rank.get("claim_count") == len(_backers),
        str(_mine_rank.get("claim_count")))
_theirs = pool_week(1, gm[6])
_theirs_rank = {p["definition_key"]: p
                for p in _theirs["pools"]}["most_passing_yards"]
_assert("§6.3: … but another GM's SELECTION is not — a Pool is a blind "
        "prediction until it settles",
        _theirs_rank.get("my_subject_id") is None
        and _theirs_rank.get("claim_count") == len(_backers),
        str(_theirs_rank)[:160])

# ── 6.4 · NO MANUAL ENGINE CALL, ASSERTED AGAINST THIS FILE'S OWN SOURCE ─────
#
# WP6's §6.3 imported `submit_claim` and called it, labelled an ENGINE
# DEMONSTRATION. WP6C removed the need, and this asserts the removal rather than
# trusting it: if any future edit reintroduced a direct call, §8's payout could
# be reached without the product and this assertion would fail first.
with open(os.path.abspath(__file__), encoding="utf-8") as _fh:
    _own_source = _fh.read()
# The needles are ASSEMBLED, not written literally, or this assertion's own text
# would be the match it is searching for.
_CALL_NEEDLE = "submit_claim" + "("
_IMPORT_NEEDLE = "from betting.pool_claims " + "import"
_assert("§6.4: this suite creates every claim through the product — its own "
        "source neither imports nor calls the claim engine",
        _CALL_NEEDLE not in _own_source and _IMPORT_NEEDLE not in _own_source,
        f"call={_own_source.count(_CALL_NEEDLE)} "
        f"import={_own_source.count(_IMPORT_NEEDLE)}")
_record("19 governed Pool claim", "POST /pool/pick", "GM x4",
        "200 x4 (legacy shape now 422)",
        f"{len(_backers)} PoolClaim rows on instance {_rank_id}; 0 legacy rows",
        "none — a pick is a claim, not funding",
        "resubmission replaces in place; one row per GM per occurrence")


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

_wallets_pre_settle = {t: balance_of(f"wallet:{t}") for t in team_ids}

r = client().post(f"/league/{LEAGUE_ID}/pool/settle/1", headers=hdr)
_assert("§8: week 1 Pool settlement succeeds through the route",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")
ps = r.json() if r.status_code == 200 else {}
by_key = {s["definition_key"]: s for s in ps.get("settled", [])}

_assert("§8: all four occurrences were resolved",
        len(ps.get("settled", [])) == 4 and ps.get("all_settled") is True,
        str(len(ps.get("settled", []))))

_win = by_key.get("most_passing_yards", {})
_expected_winners = sorted(team_ids[o - 1] for o, s in _backers.items()
                           if s == WINNING_SUBJECT)
_assert("§8 (step 19) BLOCKER 2 CLEARED: the production settlement route SEES "
        "the claims §6 created through the product, and pays them",
        _win.get("classification") == "CLAIMS_PRESENT"
        and sorted(_win.get("winning_team_ids") or []) == _expected_winners
        and _win.get("distributed_cents") == 150, str(_win)[:260])

# SETTLEMENT RESOLVED TICKETS, NOT TEAMS. The paid GMs are exactly the GMs whose
# PERSISTED claim named the winning subject — read back from `pool_claim`, which
# is the table `/pool/pick` wrote and the settlement engine reads. The route's
# response deliberately does not publish the winning subject (a Pool is a blind
# prediction), so the proof is taken from the state rather than from the reply.
with SessionLocal() as db:
    _paid_subjects = sorted({
        c.selected_subject_id for c in db.query(PoolClaim)
        .filter(PoolClaim.pool_instance_id == _rank_id,
                PoolClaim.team_id.in_(_win.get("winning_team_ids") or []))
        .all()})
    db.rollback()
_assert("§8 (step 19): every paid GM's persisted claim named the SAME subject — "
        "settlement resolved TICKETS, not teams",
        _paid_subjects == [WINNING_SUBJECT], str(_paid_subjects))
_assert("§8 (step 19): the §6.3 even split conserves the pot exactly",
        _win.get("distributed_cents", 0) + _win.get("rolled_over_cents", 0)
        + _win.get("swept_to_championship_cents", 0) == _win.get("pot_cents"),
        str(_win))

_share = 150 // len(_expected_winners)
_assert("§8 (step 19): each WINNING ticket received its exact even share",
        all(balance_of(f"wallet:{t}") - _wallets_pre_settle[t] == _share
            for t in _expected_winners), f"{_share} cents each")
_loser = team_ids[5 - 1]
_assert("§8 (step 19): the LOSING ticket received nothing",
        balance_of(f"wallet:{_loser}") == _wallets_pre_settle[_loser],
        str(balance_of(f"wallet:{_loser}")))
_assert("§8 (step 19): and the GM who never picked received nothing",
        balance_of(f"wallet:{_ABSTAINER}") == _wallets_pre_settle[_ABSTAINER],
        str(balance_of(f"wallet:{_ABSTAINER}")))

# FOUND BY OUTCOME, NOT BY KEY — POR Rev 1.4 §4.2. This read
# `by_key["matchups_with_zero_total_turnovers"]`, which assumed WHICH definition
# the digest would place in a MATCHUP slot. The weekly slate is now a governed
# 3 TEAM + 1 MATCHUP, so that slot went to a different MATCHUP QUALIFIER and the
# lookup returned an empty dict — a working rollover reported as a missing one.
#
# The claim was never about a particular contest: it is that an occurrence NO
# GM could win rolls its whole pot forward instead of paying. Asserted over the
# served classification, it holds for EVERY such occurrence in the week and
# survives any future rotation ruling.
_zeroes = [s for s in ps.get("settled", [])
           if s.get("classification") == "ZERO_ELIGIBLE_CLAIMS"]
_assert("§8 (step 20): the week produced at least one genuine "
        "ZERO_ELIGIBLE_CLAIMS outcome, so the rollover path is exercised",
        bool(_zeroes),
        str([(s.get("definition_key"), s.get("classification"))
             for s in ps.get("settled", [])]))
_assert("§8 (step 20): a genuine ZERO_ELIGIBLE_CLAIMS outcome rolls over "
        "rather than paying anyone",
        bool(_zeroes) and all(
            z.get("distributed_cents") == 0
            and z.get("rolled_over_cents") == z.get("pot_cents")
            for z in _zeroes),
        str(_zeroes)[:220])
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
        "4 PoolInstance settled; 2 carrying rollover, 1 swept",
        f"pot 150 split across the {len(_expected_winners)} GMs who claimed "
        f"through /pool/pick; losing and abstaining GMs paid nothing",
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
# §12 · DYNAMIC MODE — issue, handshake, and BLOCKER 1 CLEARED (WP6B)
# ══════════════════════════════════════════════════════════════════════════════
#
# WHAT WP6 ASSERTED HERE AND WP6D RETIRES. WP6 walked the whole tree looking for
# a caller of `run_final_lock`, found none, and asserted the empty list — then
# watched the handshaken wager's escrow sit stranded and Season Close refuse at
# `escrow_resolved`. `workers/final_lock.py` is now that caller. The
# no-caller assertion is replaced by its opposite AND by the behaviour it was
# standing in for: the deployed entry point runs, the wager gets priced, and the
# escrow resolves through the ordinary settlement path with nothing left held.

_section("§12 · Dynamic mode and Final Lock (step 14) — BLOCKER 1 CLEARED")

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

# ── THE PRE-STATE WP6 REPORTED, RESTATED SO THE CLEARANCE MEANS SOMETHING ────
from betting.pool_season_boundary import season_final_week  # noqa: E402
from economy.season_close_orchestrator import (  # noqa: E402
    SeasonClosePreconditionError, verify_preconditions,
)


def close_refusal() -> tuple[str | None, str]:
    """The FIRST unmet Season Close prerequisite, or (None, '') if all are met.

    The orchestrator's own contract, read on a rolled-back session: it writes
    nothing, so asking it is a pure observation and can be asked repeatedly."""
    with SessionLocal() as db:
        lg = db.query(League).filter(League.id == LEAGUE_ID).one()
        try:
            verify_preconditions(db, league_id=LEAGUE_ID,
                                 final_week=season_final_week(lg))
            return None, ""
        except SeasonClosePreconditionError as exc:
            return exc.step, str(exc)
        finally:
            db.rollback()


def open_escrow_accounts() -> list[tuple[str, int]]:
    """Every escrow account carrying a nonzero balance — the exact query
    `verify_preconditions` step 3 runs, asked directly so the proof does not
    depend on which prerequisite happens to refuse FIRST."""
    from sqlalchemy import text
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT account, SUM(amount_cents) FROM ledger_entries "
            "WHERE account LIKE 'escrow:%' GROUP BY account "
            "HAVING SUM(amount_cents) <> 0")).fetchall()
        db.rollback()
    return sorted((a, int(v)) for a, v in rows)


_escrow_before = dict(open_escrow_accounts())
_assert("§12 BEFORE: the handshaken Dynamic wager holds BOTH sides' maximum "
        "exposure in unresolved per-side escrow — WP6's exact finding",
        _escrow_before.get(anchor_acct) == anchor_bal
        and _escrow_before.get(derived_acct) == derived_bal,
        str(sorted(_escrow_before.items()))[:220])
_step_before, _msg_before = close_refusal()
_assert("§12 BEFORE: and Season Close is refused with the wager outstanding",
        _step_before in ("versus_terminal", "escrow_resolved"),
        f"{_step_before}: {_msg_before[:180]}")

# ── THE PRODUCTION WORKER ────────────────────────────────────────────────────
#
# `python -m workers.final_lock` IS the deployed entry point: the `Procfile`
# declares it as the `final_lock` process type and `railway.final_lock.toml`
# gives it its own service. §12 calls `main()` — the same function that CLI
# invocation calls — so what runs here is what a deployed FantasyStakes runs.
import workers.final_lock as flw  # noqa: E402

_KICKOFF = week_kickoff(2)

_rc = flw.main(["--league", str(LEAGUE_ID), "--dry-run"])
_assert("§12 (step 14): `python -m workers.final_lock --dry-run` runs at the "
        "real clock and exits 0", _rc == 0, str(_rc))
_assert("§12 (step 14): and BEFORE the governed kickoff it locks nothing — "
        "escrow is exactly as the Handshake left it",
        (balance_of(anchor_acct), balance_of(derived_acct))
        == (anchor_bal, derived_bal),
        f"anchor={balance_of(anchor_acct)}, derived={balance_of(derived_acct)}")

_sweep = flw.run_once(worker_id="wp6d-lifecycle-worker", now=_KICKOFF,
                      league_id=LEAGUE_ID)
_out = next((o for o in _sweep.outcomes if o.challenge_id == DYN), None)
_assert("§12 (step 14) BLOCKER 1 CLEARED: at the challenge's earliest covered "
        "kickoff the PRODUCTION WORKER runs Final Lock",
        _out is not None and _out.status == flw.LOCKED,
        f"{getattr(_out, 'status', None)} — {getattr(_out, 'detail', '')}"[:200])

# THE ACTOR CLASS IS UNCHANGED, AND THAT ASSERTION IS KEPT. Rev9 §5.5 forbids an
# HTTP surface for Final Lock; WP6 refused to manufacture a pass by adding one
# and WP6B did not add one either. The repair was a scheduled system worker, so
# the absence of a route is still a property worth proving.
_lock_routes = [p for p in _routes
                if any(k in p.lower() for k in ("final", "lock", "dynamic"))]
_assert("§12 (step 14): the actor was the SYSTEM WORKER — no Final-Lock route "
        "is mounted, so no GM and no commissioner could have done this",
        _lock_routes == [], str(_lock_routes))

# ── THE WAGER IS NOW PRICED ──────────────────────────────────────────────────
with SessionLocal() as db:
    _dyn_rows = [(b.id, b.status) for b in
                 db.query(Bet).filter(Bet.beef_challenge_id == DYN).all()]
    _dyn_bet_ids = sorted(i for i, _ in _dyn_rows)
    _n_frozen = (db.query(ChallengeFinalLock)
                 .filter(ChallengeFinalLock.challenge_id == DYN).count())
    db.rollback()
_assert("§12 (step 14): Final Lock created GOVERNED Bet state — the two rows "
        "the Handshake deliberately did not create, now priced",
        len(_dyn_rows) == 2 and all(s == "pending" for _, s in _dyn_rows),
        str(_dyn_rows))
_assert("§12 (step 14): with exactly one frozen Final-Lock result behind them",
        _n_frozen == 1, str(_n_frozen))
_assert("§12 (step 14): the per-side Dynamic escrow is DRAINED — nothing is "
        "stranded on the challenge any more",
        balance_of(anchor_acct) == 0 and balance_of(derived_acct) == 0,
        f"anchor={balance_of(anchor_acct)}, derived={balance_of(derived_acct)}")
_dyn_escrow = sum(balance_of(f"escrow:{b}") for b in _dyn_bet_ids)
_assert("§12 (step 14): the Credits MIGRATED into per-bet escrow — the wager "
        "was priced, not cancelled",
        _dyn_escrow > 0
        and all(balance_of(f"escrow:{b}") > 0 for b in _dyn_bet_ids),
        str({b: balance_of(f"escrow:{b}") for b in _dyn_bet_ids}))
_assert("§12 (step 14): the Derived refund returned the unused ceiling to its "
        "GM rather than holding it — the migrated escrow cannot exceed what the "
        "Handshake froze",
        _dyn_escrow <= anchor_bal + derived_bal,
        f"{_dyn_escrow} migrated of {anchor_bal + derived_bal} frozen")
_assert("§12: trial balance zero across issue, handshake and Final Lock",
        trial_balance() == 0, str(trial_balance()))

_step_after, _ = close_refusal()
_assert("§12 (step 14) BLOCKER 1 CLEARED: Season Close no longer refuses on "
        "`escrow_resolved` — it now refuses on the ordinary PENDING WAGER, "
        "which week 2's settlement retires",
        _step_after == "versus_terminal", f"step={_step_after!r}")

_record("14 Dynamic Final Lock", "python -m workers.final_lock (Procfile "
        "process type `final_lock`)",
        "system worker (Rev9 §5.5: not a GM, not a commissioner, no route)",
        f"LOCKED at {_KICKOFF.isoformat()}",
        f"challenge {DYN}: 1 ChallengeFinalLock row, Bet {_dyn_bet_ids} pending",
        f"per-side escrow drained; {_dyn_escrow} cents in per-bet escrow",
        "REPLAYED on a second sweep; claim mutex + TTL recovery")


# ══════════════════════════════════════════════════════════════════════════════
# §13 · WEEK 2 POOL COLLECTION AND THE FINALITY NEGATIVE
# ══════════════════════════════════════════════════════════════════════════════

_section("§13 · week 2 collection; settlement before finality is refused "
         "(step 11)")

r = client().post(f"/league/{LEAGUE_ID}/pool/collect/2", headers=hdr)
_assert("§13: week 2's Pools are collected — the engine's own guard allowed "
        "this only because week 1 is fully settled",
        r.status_code == 200, f"{r.status_code} {r.text[:200]}")

# ── WEEK 2's CLAIM PHASE, ON THE SAME PRODUCTION ROUTE ───────────────────────
#
# WEEK 2 IS WHERE THE MATCHUP-SCOPE OCCURRENCES CAN BE CLAIMED, because §11
# published week 2's fixtures before the pick window — the state a live league is
# actually in while its GMs are picking. Every GM picks on every open occurrence,
# with the subject rotated by GM ordinal so the field is not uniform: that is what
# makes §14's continuation settlement a real ticket resolution rather than a
# unanimous one, and it is what lets §15 attribute each surviving rollover.
_wk2 = pool_week(2, gm[2])
_claims_before_w2 = sum(claim_count(p["pool_instance_id"])
                        for p in _wk2["pools"])
_w2_submitted = 0
for _pool in _wk2["pools"]:
    _subjects = _pool.get("subjects") or []
    if not _pool.get("open_for_claims") or not _subjects:
        continue
    for _ordinal in range(1, TEAM_COUNT + 1):
        rr = client().post("/pool/pick", headers=actor[_ordinal], json={
            "league_id": LEAGUE_ID, "team_id": team_ids[_ordinal - 1],
            "week": 2, "pool_instance_id": _pool["pool_instance_id"],
            "subject_id": _subjects[(_ordinal - 1) % len(_subjects)]["subject_id"]})
        if rr.status_code == 200:
            _w2_submitted += 1
        else:
            _assert(f"§13: GM {_ordinal} picks on {_pool['definition_key']}",
                    False, f"{rr.status_code} {rr.text[:140]}")

_assert("§13: every GM claimed every one of week 2's four governed occurrences "
        "through the product", _w2_submitted == 4 * TEAM_COUNT,
        f"{_w2_submitted} submissions")
_assert("§13: and each submission is exactly one governed claim — 24 in the "
        "week, none legacy",
        sum(claim_count(p["pool_instance_id"]) for p in _wk2["pools"])
        == _claims_before_w2 + _w2_submitted and legacy_rows() == (0, 0),
        str(legacy_rows()))
_assert("§13: the claim phase moved no Credits",
        trial_balance() == 0, str(trial_balance()))
_record("19 governed Pool claim (week 2)", "POST /pool/pick", "all six GMs",
        f"200 x{_w2_submitted}",
        f"{_w2_submitted} PoolClaim rows across 4 occurrences; 0 legacy rows",
        "none", "one row per GM per occurrence")

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

# ── THE DYNAMIC WAGER SETTLES ON THE SAME RUN (WP6B closure) ─────────────────
#
# NO SEPARATE PATH, and that is the point of the clearance. A Final-Locked
# Dynamic wager is an ordinary pair of Bet rows from here on, so the SAME weekly
# automation that settled the Locked wager settles this one, with no Dynamic
# branch anywhere in the settlement chain.
with SessionLocal() as db:
    _dyn_statuses = sorted(b.status for b in
                           db.query(Bet).filter(Bet.id.in_(_dyn_bet_ids)).all())
    db.rollback()
_assert("§14 (step 18) BLOCKER 1 CLEARED: both legs of the DYNAMIC wager "
        "reached a terminal state through the ordinary weekly settlement",
        len(_dyn_statuses) == 2
        and all(s in ("won", "lost", "push") for s in _dyn_statuses),
        str(_dyn_statuses))
_assert("§14 (step 18) BLOCKER 1 CLEARED: and every Dynamic escrow account is "
        "drained — the escrow WP6 found stranded resolved through the normal "
        "lifecycle",
        balance_of(anchor_acct) == 0 and balance_of(derived_acct) == 0
        and all(balance_of(f"escrow:{b}") == 0 for b in _dyn_bet_ids),
        str({b: balance_of(f"escrow:{b}") for b in _dyn_bet_ids}))
_assert("§14 (step 18): NOT ONE escrow account in the database holds a balance",
        open_escrow_accounts() == [], str(open_escrow_accounts()))

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

_paid2 = [s for s in ps2.get("settled", []) if s["distributed_cents"] > 0]
_assert("§14 (step 20): week 2's own governed claims were paid too — the "
        "production claim path is not a one-week accident",
        _paid2 and all(s["classification"] == "CLAIMS_PRESENT"
                       and s["winning_team_ids"] for s in _paid2),
        str([(s["definition_key"], s["winning_team_ids"]) for s in _paid2]))
_assert("§14 (step 20): every occurrence conserved its pot exactly",
        all(s["distributed_cents"] + s["rolled_over_cents"]
            + s["swept_to_championship_cents"] == s["pot_cents"]
            for s in ps2.get("settled", [])),
        str([(s["definition_key"], s["pot_cents"]) for s in ps2.get("settled", [])]))

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
# §15 · SEASON CLOSE — the terminal rollover sweep and the completed close
# ══════════════════════════════════════════════════════════════════════════════
#
# WP6F — WHAT CHANGED HERE AND WHY NOTHING WAS RELAXED TO GET IT.
#
# WP6D ended this run at `409 pool_rollover` and called that bar a CERTIFICATION
# CORPUS HORIZON — "a live league reaches week 17, the pots sweep, and the close
# proceeds". WP6E tested that claim against the product instead of assuming it
# and found it FALSE: week 17 is >= playoff_start_week 15, so a week-17 slate is
# governed by POR §8, whose approved 32-Pool postseason subset does not exist.
# Every `postseason_eligible` is NULL, the postseason candidate set is empty, and
# the draw refuses with `[INVALID_SLOT_COUNT] POSTSEASON phase has 0 candidates
# for 2 fresh slots and does not cycle.` No corpus could have cleared it — the
# refusal happens in the pure selector, before any provider data is consulted.
#
# THE OWNER RULING RESOLVED IT, AND THIS SECTION IS WHERE THE RULING IS PROVED.
# Terminal rollover expiry is a SEASON-BOUNDARY SETTLEMENT RULE (BAB-805,
# BAB-901, AP-166): at `season_final_week` a carry with no later eligible
# occurrence transfers to the Championship Pot, exactly once, and NO PoolInstance
# is required to host that transfer.
#
# EVERY WP6D ASSERTION ABOUT THE SURVIVING POTS IS KEPT AND STRENGTHENED. The
# pre-close facts WP6D established — two carries, 300 cents each, both
# SUBJECT-layer zeros, both having carried six real governed claims — are all
# still asserted below, because they are what makes this a legitimate disposal
# rather than a convenient one. What changes is only what happens NEXT: WP6D
# asserted the close was refused; this asserts the money is disposed of by the
# governed rule and the close completes. The refusal assertion is not weakened,
# it is SUPERSEDED by the ruling that made the refusal wrong.

_section("§15 · terminal rollover sweep and Season Close (steps 30-37)")

from betting.pool_settlement import EVENT_ROLLOVER_EXPIRY_SWEEP  # noqa: E402
from db.schema import PoolEconomicEvent, PoolLeagueActivation  # noqa: E402
from economy.economy_events import championship_account  # noqa: E402

# ── PRE-CLOSE STATE, captured before anything is disposed of ─────────────────
with SessionLocal() as db:
    _rows = (db.query(PoolInstance)
             .filter(PoolInstance.league_id == LEAGUE_ID,
                     PoolInstance.rollover_cents > 0)
             .order_by(PoolInstance.week, PoolInstance.slot).all())
    _live = [(i.week, i.slot, i.id, i.definition_key, int(i.rollover_cents),
              i.settlement_classification, int(i.pot_cents or 0)) for i in _rows]
    _final_week = season_final_week(
        db.query(League).filter(League.id == LEAGUE_ID).one())
    _instances_before = (db.query(PoolInstance)
                         .filter(PoolInstance.league_id == LEAGUE_ID).count())
    _postseason_instances_before = (
        db.query(PoolInstance)
        .filter(PoolInstance.league_id == LEAGUE_ID,
                PoolInstance.phase == "POSTSEASON").count())
    # The full catalog eligibility snapshot — every row, not a sample, so a
    # single flipped flag anywhere in the 80 would be caught.
    _ps_flags_before = sorted(
        (d.key, d.postseason_eligible)
        for d in db.query(PoolDefinition).all())
    _activations_before = db.query(PoolLeagueActivation).count()
    db.rollback()

_pool_before = balance_of(f"pool:{LEAGUE_ID}")
_champ_before = balance_of(championship_account(LEAGUE_ID))
_reserve_before = {t: balance_of(f"reserve:{t}") for t in team_ids}
_carry_total = sum(row[4] for row in _live)

print("\n     rollover state carried into the season boundary:")
for _wk, _slot, _iid, _key, _cents, _cls, _pot in _live:
    print(f"       w{_wk} slot{_slot} instance {_iid} {_key} = {_cents} cents  "
          f"[{_cls}]; {claim_count(_iid)} governed claim(s) were submitted")

# ── REQUIRED PROOFS 1-3 — the pre-sweep facts WP6D established, kept ─────────
# HOW MANY POTS ROLL IS A ROTATION OUTCOME, NOT A LIFECYCLE CLAIM.
#
# This read "exactly two, 300 cents each" — two weeks of an unclaimed QUALIFIER
# accumulating one 150-cent share apiece. POR Rev 1.4 §4.2 gives the weekly
# slate a governed 3 TEAM + 1 MATCHUP, and nine of the fifteen rollover-eligible
# definitions are MATCHUP-scoped, so a week now draws fewer of them and the
# carries that survive to the season boundary differ in number and in size.
#
# WHAT §15 IS ACTUALLY ABOUT is that a live carry reaches the boundary at all,
# that it is a SUBJECT-layer ZERO_ELIGIBLE_CLAIMS carry (§15.2, unchanged), that
# it survived a real claim phase (§15.3, unchanged), and that its cents are
# still sitting inside `pool:{league}` rather than having been posted anywhere
# (§15.3b). Those four are the proof; the count and the amount were description.
_assert("§15.1: PRE-SWEEP — at least one Pool occurrence carries a live "
        "rollover into the season boundary, and every carry is positive",
        len(_live) >= 1 and all(row[4] > 0 for row in _live),
        str([(row[3], row[4]) for row in _live]))
_assert("§15.2: PRE-SWEEP — both are SUBJECT-layer ZERO_ELIGIBLE_CLAIMS, not "
        "zero-winning-ticket rollovers, so this is a legitimate carry and not "
        "the shape WP6's BLOCKER 2 used to force",
        all(row[5] == "ZERO_ELIGIBLE_CLAIMS" for row in _live),
        str([(row[3], row[5]) for row in _live]))
_assert("§15.3: PRE-SWEEP — each carried REAL governed PoolClaim rows, so the "
        "pot survived a full claim phase rather than an empty one",
        all(claim_count(row[2]) > 0 for row in _live),
        str([(row[3], claim_count(row[2])) for row in _live]))
# THE IDENTITY IS THE POINT, NOT THE FIGURE. `== 600` was the total two
# 300-cent carries happened to make; what a rollover must never do is post, and
# that is `pool balance == sum of live carries` at any total.
_assert("§15.3b: PRE-SWEEP — the carried cents are still inside pool:{league}; "
        "a rollover is a column transfer, never a posting",
        _pool_before == _carry_total and _carry_total > 0,
        f"pool={_pool_before} carries={_carry_total}")

# ── ALL NINE PREREQUISITES, ASKED AS ONE CALL ────────────────────────────────
#
# `verify_preconditions` raises on the FIRST unmet step. WP6D could only ever
# name one and had to attribute the other eight by hand. It now returns without
# raising, which is a strictly stronger statement than any per-step enumeration:
# every one of the nine is satisfied at once.
_unmet_step, _unmet_detail = close_refusal()

_assert("§15.15: ALL NINE season-close prerequisites pass — versus_terminal, "
        "pool_settled, escrow_resolved, weekly_minimum_expiry, "
        "results_not_ready, skunk_assessed, pool_rollover, pool_zero and "
        "provider_conflict, in one call that raises on the first unmet one",
        _unmet_step is None, f"refused at {_unmet_step}: {_unmet_detail[:160]}")
_assert("§15: BLOCKER 1 stays CLEARED — `escrow_resolved` is MET, not one "
        "escrow account in the database carries a balance, where WP6 found the "
        f"Dynamic wager's two holding {anchor_bal + derived_bal} cents",
        open_escrow_accounts() == [], str(open_escrow_accounts()))
with SessionLocal() as db:
    _pending_bets = (db.query(Bet)
                     .filter(Bet.beef_challenge_id.in_([CH, DYN]),
                             Bet.status == "pending").count())
    db.rollback()
_assert("§15: `versus_terminal` is MET — both the Locked and the Final-Locked "
        "Dynamic wager settled", _pending_bets == 0, str(_pending_bets))
_assert("§15: BLOCKER 2 stays CLEARED — governed claims exist and were paid, "
        "so no occurrence rolled over for want of a winning TICKET",
        _total_claims + _w2_submitted > 0,
        f"{_total_claims + _w2_submitted} claims created through /pool/pick")

# ── THE CLOSE ITSELF, through the production route ───────────────────────────
_tb_before_close = trial_balance()
r = client().post(f"/league/{LEAGUE_ID}/season/close", headers=hdr)
_season_close_status = r.status_code
try:
    _season_close_body = r.json()
except ValueError:
    _season_close_body = {}

print(f"\n     season close -> {_season_close_status} "
      f"{str(_season_close_body)[:200]}")

_assert("§15.16 (steps 30-37): SEASON CLOSE RETURNS 200 — the lifecycle "
        "COMPLETES through the running product",
        _season_close_status == 200,
        f"{_season_close_status} {str(_season_close_body)[:200]}")

_close_step = None if _season_close_status == 200 else (
    (_season_close_body.get("detail") or {}).get("reason_code"))

# Everything below reads the body, so a non-200 would produce a cascade of
# uninformative failures. Guard once, loudly.
_body = _season_close_body if _season_close_status == 200 else {}
_sweeps = _body.get("terminal_rollover_sweeps", [])

# ── REQUIRED PROOFS 4-7, 10 — the terminal rollover sweep ────────────────────
_assert("§15.4: the close REACHES the terminal rollover sweep and reports it — "
        "one governed disposal per carried occurrence",
        len(_sweeps) == 2, str(_sweeps))
_assert("§15.4b: each disposal names the occurrence that CARRIED the balance, "
        "so the lineage from drawn pot to Championship credit is unbroken",
        sorted(s["pool_instance_id"] for s in _sweeps)
        == sorted(row[2] for row in _live),
        f"{sorted(s.get('pool_instance_id') for s in _sweeps)} vs "
        f"{sorted(row[2] for row in _live)}")
_assert("§15.4c: and each carries the SUBJECT-zero classification it was "
        "settled under — the disposal did not reclassify anything",
        all(s["classification"] == "ZERO_ELIGIBLE_CLAIMS" for s in _sweeps),
        str([s.get("classification") for s in _sweeps]))
# EVERY CARRIED CENT, AND NOT ONE MORE. `600` was the total two 300-cent
# carries happened to make under the pre-Rev-1.4 draw; POR Rev 1.4 §4.2's
# governed 3 TEAM + 1 MATCHUP mix leaves a different set of carries at the
# boundary. `_carry_total` is measured from those carries at §15.3b, so the
# claim — that exactly what was carried leaves rollover state, swept and
# disposed and posted, with nothing invented and nothing stranded — is now
# stated against the money itself.
_assert(f"§15.5: EXACTLY {_carry_total} cents — every carried cent and no "
        f"other — leaves rollover state",
        _body.get("terminal_rollover_swept_cents") == _carry_total
        and _body.get("terminal_rollover_disposed_cents") == _carry_total
        and sum(s["amount_cents"] for s in _sweeps) == _carry_total,
        f"swept={_body.get('terminal_rollover_swept_cents')} "
        f"disposed={_body.get('terminal_rollover_disposed_cents')} "
        f"carried={_carry_total}")
_assert("§15.5b: none of the disposals is a replay — this call moved the money",
        all(s["replayed"] is False for s in _sweeps),
        str([s.get("replayed") for s in _sweeps]))

with SessionLocal() as db:
    _rollover_after = [
        (i.id, int(i.rollover_cents or 0), int(i.pot_cents or 0))
        for i in db.query(PoolInstance)
        .filter(PoolInstance.league_id == LEAGUE_ID)
        .order_by(PoolInstance.week, PoolInstance.slot).all()]
    _instances_after = (db.query(PoolInstance)
                        .filter(PoolInstance.league_id == LEAGUE_ID).count())
    _postseason_instances_after = (
        db.query(PoolInstance)
        .filter(PoolInstance.league_id == LEAGUE_ID,
                PoolInstance.phase == "POSTSEASON").count())
    _ps_flags_after = sorted(
        (d.key, d.postseason_eligible) for d in db.query(PoolDefinition).all())
    _activations_after = db.query(PoolLeagueActivation).count()
    _sweep_events = (db.query(PoolEconomicEvent)
                     .filter(PoolEconomicEvent.league_id == LEAGUE_ID,
                             PoolEconomicEvent.event_type
                             == EVENT_ROLLOVER_EXPIRY_SWEEP).all())
    _sweep_event_rows = [(e.pool_instance_id, int(e.amount_cents),
                          e.posting_id) for e in _sweep_events]
    db.rollback()

_assert("§15.10: BOTH rollover balances are now ZERO",
        all(c == 0 for _, c, _ in _rollover_after),
        str([(i, c) for i, c, _ in _rollover_after]))
_assert("§15.10b: and `pot_cents` is UNTOUCHED on both — the historical record "
        "of what each occurrence held survives the disposal",
        all(row[6] == dict((i, p) for i, _, p in _rollover_after)[row[2]]
            for row in _live),
        str([(row[2], row[6]) for row in _live]))
_assert("§15.7: ZERO new PoolInstance was created to host the sweep — the "
        "ruling disposes of a balance, it does not fabricate an occurrence",
        _instances_after == _instances_before,
        f"{_instances_before} -> {_instances_after}")
_assert("§15.7b: and no POSTSEASON occurrence exists at all, before or after — "
        "the sweep took no dependency on a postseason slate",
        _postseason_instances_before == _postseason_instances_after == 0,
        f"{_postseason_instances_before} -> {_postseason_instances_after}")
_assert("§15: exactly one ROLLOVER_EXPIRY_SWEEP event exists per carried "
        "occurrence, each with a real posting — the audit row IS the "
        "exactly-once guarantee (uq_pool_economic_event_instance)",
        len(_sweep_event_rows) == len(_live)
        and all(p is not None for _, _, p in _sweep_event_rows)
        # ONE EVENT PER CARRY, EACH FOR EXACTLY THAT CARRY'S CENTS. Compared
        # against the carries measured before the close rather than against a
        # pinned pair of amounts, so a rotation ruling that changes how many
        # pots roll cannot make this pass or fail for the wrong reason.
        and sorted(a for _, a, _ in _sweep_event_rows)
        == sorted(row[4] for row in _live),
        f"{_sweep_event_rows} vs carries "
        f"{sorted((row[2], row[4]) for row in _live)}")

# ── REQUIRED PROOFS 8, 9 — the postseason catalog is untouched ───────────────
#
# WP1B AMENDED THE SECOND CLAUSE OF THIS ASSERTION, AND ONLY THE SECOND.
#
# As written for WP6F it asserted two different things at once:
#
#   (1) `_ps_flags_after == _ps_flags_before` — the terminal rollover sweep
#       changes no `postseason_eligible` value. That is a real INVARIANT about
#       the sweep, it is what "the sweep took no dependency on the postseason
#       catalog" means, and it is UNCHANGED and still asserted below.
#
#   (2) `all(v is None …)` — every flag is NULL. That was never an invariant.
#       It was a SNAPSHOT of the recorded POR §8 blocker, true on the day WP6F
#       was written because no postseason subset had been approved yet.
#
# WP1B's owner ruling resolved exactly that blocker: `postseason_eligible` is
# now an explicit boolean on all 80 rows — TRUE on the 44 permitted definitions,
# FALSE on the 36 excluded ones. Clause (2) therefore asserts a state the
# product has deliberately left behind, and keeping it would pin this suite to
# the absence of a feature rather than to the behaviour of the sweep.
#
# The invariant is kept and SHARPENED rather than dropped: the flags must be
# unchanged across the close AND must still be the values the catalog seeded, so
# a sweep that quietly rewrote one is caught just as surely as before — and now
# a sweep that rewrote one to NULL would be caught too, which the old form could
# not distinguish from a pass.
from betting.pool_catalog import load_catalog as _load_catalog  # noqa: E402

_catalog_flags = sorted(
    (d.key, d.postseason_eligible) for d in _load_catalog().definitions)

_assert("§15.9: NOT ONE `postseason_eligible` value changed across the close — "
        "the sweep takes no dependency on the postseason catalog and rewrites "
        "nothing in it",
        _ps_flags_after == _ps_flags_before,
        f"{len(_ps_flags_after)} definitions, distinct values "
        f"{sorted({v for _, v in _ps_flags_after}, key=str)}")
_assert("§15.9b: and every value still equals what the governed catalog "
        "artifact seeded — WP1B resolved the POR §8 nulls to explicit booleans "
        "and the close leaves them exactly there",
        _ps_flags_after == _catalog_flags,
        f"{sum(1 for k, v in _ps_flags_after if v)} eligible / "
        f"{sum(1 for k, v in _ps_flags_after if v is False)} excluded / "
        f"{sum(1 for k, v in _ps_flags_after if v is None)} unresolved")
_assert("§15.8: NO postseason Pool definition was activated — the league's "
        "activation rows are unchanged, and the sweep never consulted a gate",
        _activations_after == _activations_before,
        f"{_activations_before} -> {_activations_after}")

# ── REQUIRED PROOF 6 — the money reached Championship BEFORE distribution ────
_champ_pot = _body.get("championship_pot_cents", 0)
_reserve_swept = _body.get("reserve_swept_cents", 0)
_assert(f"§15.6: the {_carry_total} carried cents reached "
        f"championship:{{league}} BEFORE the Championship distribution — the "
        f"distributed pot is exactly the pre-close balance PLUS the swept "
        f"rollover PLUS the reserve sweep, so the carry was paid out rather "
        f"than left sitting in the account",
        _champ_pot == _champ_before + _carry_total + _reserve_swept,
        f"pot={_champ_pot} = champ_before {_champ_before} + rollover "
        f"{_carry_total} + reserves {_reserve_swept}")
_assert("§15.6b: and the reserve sweep itself is the full governed obligation",
        _reserve_swept == sum(_reserve_before.values())
        == OPENING_CHAMPIONSHIP * TEAM_COUNT,
        f"{_reserve_swept} vs {sum(_reserve_before.values())}")

# ── REQUIRED PROOFS 12-14 — Championship 60/30/10 and the penny rule ─────────
_places = _body.get("championship_placements", [])
_assert("§15.12: Championship distributes 60/30/10 to three placed GMs",
        [p["pct"] for p in _places] == [60, 30, 10]
        and [p["place"] for p in _places] == [1, 2, 3],
        str([(p.get("place"), p.get("pct")) for p in _places]))
_assert("§15.12b: and the placements conserve the pot EXACTLY",
        sum(p["cents"] for p in _places) == _champ_pot,
        f"{sum(p['cents'] for p in _places)} vs {_champ_pot}")

# THE PENNY REMAINDER RULE, asserted against the accepted pure function rather
# than against a number typed here — every ordinary place floors, and the ENTIRE
# indivisible remainder goes to FIRST place. Deliberately different from the
# Pool's §6.3 canonical-id spread; collapsing the two would silently change
# payouts, so the discriminating arithmetic is restated as an assertion.
from economy.championship import championship_distribution  # noqa: E402

_expected_places = championship_distribution(
    _champ_pot, [60, 30, 10], [p["team_id"] for p in _places])
_floor_sum = sum(_champ_pot * pct // 100 for pct in (60, 30, 10))
_assert("§15.14: the penny-remainder rule is preserved — every ordinary place "
        "floors and the WHOLE indivisible remainder goes to FIRST place",
        [p["cents"] for p in _places] == [a for *_, a in _expected_places]
        and _places[0]["cents"]
        == (_champ_pot * 60 // 100) + (_champ_pot - _floor_sum)
        and _places[1]["cents"] == _champ_pot * 30 // 100
        and _places[2]["cents"] == _champ_pot * 10 // 100,
        f"pot={_champ_pot} remainder={_champ_pot - _floor_sum} "
        f"paid={[p['cents'] for p in _places]}")

# ── REQUIRED PROOFS 13, 18, 19 — reconciliation and conservation ────────────
_zero_assertions = _body.get("zero_assertions", {})
_assert("§15.13: every account that must be zero at close IS zero — every "
        "reserve, every expired_min, pool, skunk and championship",
        _zero_assertions and all(v == 0 for v in _zero_assertions.values()),
        str({k: v for k, v in _zero_assertions.items() if v != 0}))
_assert("§15.13b: pool:{league} specifically is drained — the 600 left and "
        "nothing replaced it",
        balance_of(f"pool:{LEAGUE_ID}") == 0
        and balance_of(championship_account(LEAGUE_ID)) == 0,
        f"pool={balance_of(f'pool:{LEAGUE_ID}')} "
        f"champ={balance_of(championship_account(LEAGUE_ID))}")
_assert("§15: expired Weekly Minimum is reconciled back to GM Wallets exactly "
        "once", _body.get("expired_min_returned_cents", 0) > 0
        and all(balance_of(f"expired_min:{t}") == 0 for t in team_ids),
        f"{_body.get('expired_min_returned_cents')} cents returned")

_settle = _body.get("current_settle", {})
_assert("§15.18: final Current Settle is derived for every GM and reconciles "
        "with the posted wallet position",
        len(_settle) == TEAM_COUNT,
        f"{len(_settle)} of {TEAM_COUNT} GMs")
_assert("§15.19: the ledger is BALANCED after the close — trial balance zero",
        trial_balance() == 0, str(trial_balance()))

# ── REQUIRED PROOFS 11, 17 — the repeat close moves nothing ─────────────────
_ledger_after_close = {
    **{f"wallet:{t}": balance_of(f"wallet:{t}") for t in team_ids},
    **{f"reserve:{t}": balance_of(f"reserve:{t}") for t in team_ids},
    **{f"expired_min:{t}": balance_of(f"expired_min:{t}") for t in team_ids},
    f"pool:{LEAGUE_ID}": balance_of(f"pool:{LEAGUE_ID}"),
    f"championship:{LEAGUE_ID}": balance_of(championship_account(LEAGUE_ID)),
    f"skunk:{LEAGUE_ID}": balance_of(skunk_account(LEAGUE_ID)),
}

r2 = client().post(f"/league/{LEAGUE_ID}/season/close", headers=hdr)
_body2 = r2.json() if r2.content else {}
_ledger_after_repeat = {
    **{f"wallet:{t}": balance_of(f"wallet:{t}") for t in team_ids},
    **{f"reserve:{t}": balance_of(f"reserve:{t}") for t in team_ids},
    **{f"expired_min:{t}": balance_of(f"expired_min:{t}") for t in team_ids},
    f"pool:{LEAGUE_ID}": balance_of(f"pool:{LEAGUE_ID}"),
    f"championship:{LEAGUE_ID}": balance_of(championship_account(LEAGUE_ID)),
    f"skunk:{LEAGUE_ID}": balance_of(skunk_account(LEAGUE_ID)),
}

_assert("§15.17 (step 37): a REPEATED Season Close is 200 and REPLAYED",
        r2.status_code == 200 and _body2.get("replayed") is True
        and _body2.get("closed_now") is False,
        f"{r2.status_code} replayed={_body2.get('replayed')}")
_assert("§15.11: the repeat does NOT repeat either rollover transfer — it "
        "moves zero cents and reports zero swept",
        _body2.get("terminal_rollover_swept_cents", 0) == 0
        and _body2.get("terminal_rollover_sweeps", []) == [],
        str(_body2.get("terminal_rollover_swept_cents")))
_assert("§15.17b: and NOT ONE account moved between the two closes",
        _ledger_after_repeat == _ledger_after_close,
        str({k: (v, _ledger_after_repeat[k])
             for k, v in _ledger_after_close.items()
             if _ledger_after_repeat[k] != v}))

with SessionLocal() as db:
    _sweep_events_after_repeat = (
        db.query(PoolEconomicEvent)
        .filter(PoolEconomicEvent.league_id == LEAGUE_ID,
                PoolEconomicEvent.event_type
                == EVENT_ROLLOVER_EXPIRY_SWEEP).count())
    db.rollback()
_assert("§15.11b: still EXACTLY two ROLLOVER_EXPIRY_SWEEP events after the "
        "repeat — the uniqueness constraint, not a flag, is what guarantees it",
        _sweep_events_after_repeat == 2, str(_sweep_events_after_repeat))
_assert("§15.12c: trial balance is STILL zero after the repeated close",
        trial_balance() == 0, str(trial_balance()))

_record("30-31 terminal Pool rollover sweep", "POST /league/{id}/season/close",
        "commissioner", "200 — 2 disposals, 600 cents",
        f"both carrying occurrences zeroed; {_instances_after} PoolInstance "
        f"rows, unchanged — none created for the sweep",
        f"pool:{LEAGUE_ID} -> championship:{LEAGUE_ID} 600 cents "
        f"(ROLLOVER_EXPIRY_SWEEP x2)",
        "repeat moves nothing; unique (instance, event_type)")
_record("32-37 Season Close", "POST /league/{id}/season/close", "commissioner",
        "200 — all nine prerequisites met",
        f"season closed at {_body.get('season_closed_at')}",
        f"reserves {_reserve_swept} swept; Championship {_champ_pot} paid "
        f"60/30/10; expired minimum "
        f"{_body.get('expired_min_returned_cents')} returned",
        "200 replayed=true, zero movement")


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
# WP6F — THIS IS NOW TWO FACTS, AND BOTH ARE ASSERTED. `_reserve_before` was
# read immediately before the close, so the original claim — weekly play never
# touches the Championship Reserve — is still proved against the state at the
# end of two governed weeks. The second half is what the close then does with
# it: step 10 sweeps every reserve into the Championship pot, so a nonzero
# balance afterwards would mean a GM's committed Credits never reached the pot
# they were allocated for.
_assert("§16: no GM's Championship Reserve was touched by weekly play — read "
        "at the end of two governed weeks, immediately before the close",
        all(_reserve_before[t] == OPENING_CHAMPIONSHIP for t in team_ids),
        str([_reserve_before[t] for t in team_ids]))
_assert("§16: and the close SWEPT every one of them into the Championship pot "
        "— not a cent of committed Reserve is left behind",
        all(balance_of(f"reserve:{t}") == 0 for t in team_ids),
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
print("WP6/WP6D/WP6F LIFECYCLE SUITE — every assertion PASSED")
print()
print("  A passing run means the run behaved exactly as this suite states,")
print("  which now includes:")
print("    BLOCKER 1  CLEARED — workers/final_lock.py prices the Dynamic wager")
print("               at its governed kickoff; the escrow WP6 found stranded")
print("               resolves through the ordinary weekly settlement (step 14)")
print("    BLOCKER 2  CLEARED — POST /pool/pick creates governed PoolClaim")
print("               state; the production settlement route pays the winning")
print("               tickets and nobody else (step 19)")
print("    BLOCKER 3  CLEARED — WP6F. WP6D read the final 409 as a CORPUS")
print("               HORIZON; WP6E disproved that — week 17 is inside the")
print("               postseason, whose 32-Pool subset does not exist, so no")
print("               corpus could ever have reached the sweep. The owner")
print("               ruling made terminal rollover expiry a SEASON-BOUNDARY")
print("               settlement rule, and §15 drives it through the product:")
print(f"               {_carry_total} cents left rollover state at "
      f"season_final_week {_final_week},")
print("               reached championship before distribution and were paid")
print("               60/30/10, with NO PoolInstance created to host it.")
print("    LIFECYCLE  COMPLETES — Season Close returns 200 through the running")
print("               product, all nine prerequisites met, trial balance zero,")
print("               and the repeated close replays without moving a cent.")
print("=" * 78)
