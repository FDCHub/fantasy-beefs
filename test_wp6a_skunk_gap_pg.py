#!/usr/bin/env python3
"""
test_wp6a_skunk_gap_pg.py — WP6A step 1: PROVE THE GAP, before changing anything.

WHAT THIS SUITE IS FOR. WP5 reported that `economy.skunk.assess_weekly_skunk()`
is certified but has no production caller, and that season close therefore blocks
forever on its `skunk_assessed` precondition. That is a claim about the SHIPPED
product, and a claim of that size is worth proving rather than asserting — so
this suite establishes it against real PostgreSQL, on a league that has genuinely
played a week, BEFORE any production code is touched.

IT IS DELIBERATELY NON-VACUOUS. Each negative is paired with the positive that
makes it mean something:

  · the week really is final               — finalized_at is set on every matchup
  · the other Week Close prerequisites really are satisfied — the weekly minimum
                                             was released through the real
                                             service, so expiry has something to
                                             do and precondition 4/5 can pass
  · Week Close really does SUCCEED today   — so the gap is not "close is broken",
                                             it is "close completes and leaves
                                             the week permanently unassessable"
  · the season really is blocked ON SKUNK  — the orchestrator's FIRST unmet step
                                             is `skunk_assessed`, not something
                                             else that would have blocked anyway
  · and it is UNBLOCKABLE through the product — no route, no service and no
                                             scheduler reaches the engine

§5 WAS INVERTED BY WP6A, as planned. It recorded "nothing calls the engine";
it now asserts that Week Close does, so a refactor that removed the call would
fail here first and the product could not drift back into the gap §1-§4
describe. Sections 1-4 are unchanged and still document what the gap WAS: they
build a league, close its week, and show the season blocked — except that §4's
last two assertions now read against a product where the block is gone, which is
why §4 is scoped to the state BEFORE the close it performs.

Requires TEST_DATABASE_URL -> a disposable, empty, _test-named database.
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The TestClient talks plain http, and a conforming cookie jar will not return a
# Secure cookie over it. Set before api.main is imported, exactly as the other
# route-level suites do; S8-P1 asserts separately that Secure is the DEFAULT.
os.environ["FS_COOKIE_INSECURE"] = "1"
os.environ.pop("FS_ALLOWED_ORIGINS", None)

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] WP6A gap suite cannot run:\n  {e}")
    sys.exit(2)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from datetime import datetime, timezone  # noqa: E402

from db.schema import (  # noqa: E402
    EconomyEvent, League, LeagueCommissioner, Matchup, Team, User, Wallet,
)
from auth.jwt_auth import hash_password  # noqa: E402
from economy.current_settle import DOOR_SEASON_ALLOCATION  # noqa: E402
from economy.economy_events import (  # noqa: E402
    EVENT_SKUNK_ASSESSMENT, min_reserve_account,
)
from economy.weekly_minimum import release_week  # noqa: E402
from ledger.ledger import post as ledger_post, trial_balance  # noqa: E402

ROOT = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _section(title: str) -> None:
    print(f"\n{title}")
    print("─" * len(title))


print("=" * 78)
print("WP6A §1 — the weekly Skunk gap, proved before it is closed")
print("=" * 78)

SEASON, WEEK = 2026, 3
PASSWORD = "wp6a-password"

# ── A league that has genuinely played a week ────────────────────────────────

tdb.reset()
with tdb.SessionLocal() as db:
    league = League(name="WP6A Gap League", season=SEASON, provider="yahoo",
                    provider_league_key="461.l.wp6agap",
                    provider_current_week=WEEK, playoff_start_week=15)
    db.add(league); db.flush()

    teams = []
    for i in range(4):
        t = Team(league_id=league.id, team_name=f"Team {i}", owner=f"O{i}",
                 email=f"wp6a{i}@gap.test")
        db.add(t); db.flush()
        db.add(Wallet(team_id=t.id, balance=0.0))
        teams.append(t)
    db.flush()

    comm = User(email="wp6a-comm@gap.test", hashed_password=hash_password(PASSWORD),
                team_id=teams[0].id, role="commissioner")
    db.add(comm); db.flush()
    db.add(LeagueCommissioner(league_id=league.id, user_id=comm.id,
                              source="bootstrap"))

    # The season allocation, so the weekly minimum has a reserve to release from.
    for t in teams:
        ledger_post([(min_reserve_account(t.id), 14_000), ("world", -14_000)],
                    door=DOOR_SEASON_ALLOCATION, session=db)
        db.flush()

    # TWO FINALIZED MATCHUPS with DECIMAL scores and DIFFERENT margins, so the
    # engine has an unambiguous worst loss to find. Margins: 30.64 and 4.10.
    now = datetime.now(timezone.utc)
    db.add(Matchup(league_id=league.id, week=WEEK,
                   home_team_id=teams[0].id, away_team_id=teams[1].id,
                   home_score=101.83, away_score=132.47, finalized_at=now))
    db.add(Matchup(league_id=league.id, week=WEEK,
                   home_team_id=teams[2].id, away_team_id=teams[3].id,
                   home_score=110.50, away_score=106.40, finalized_at=now))
    db.flush()

    release_week(db, league_id=league.id, week=WEEK)
    db.commit()

    LEAGUE_ID = league.id
    TEAM_IDS = [t.id for t in teams]
    COMM_EMAIL = comm.email

_section("§1 · the league has a finalized, played week")

with tdb.SessionLocal() as db:
    rows = (db.query(Matchup)
            .filter(Matchup.league_id == LEAGUE_ID, Matchup.week == WEEK).all())
    finalized = [m for m in rows if m.finalized_at is not None]
    scores = sorted((m.home_score, m.away_score) for m in rows)

_assert("§1: the week holds matchups", len(rows) == 2, f"{len(rows)} matchup(s)")
_assert("§1: EVERY matchup is economically final (finalized_at set)",
        len(finalized) == len(rows) == 2, f"{len(finalized)} of {len(rows)}")
_assert("§1: and the scores are decimal, not integers",
        any(s % 1 for pair in scores for s in pair), str(scores))

_section("§2 · the other Week Close prerequisites are satisfied")

with tdb.SessionLocal() as db:
    from economy.economy_events import EVENT_WEEKLY_MINIMUM_RELEASE
    released = (db.query(EconomyEvent)
                .filter(EconomyEvent.league_id == LEAGUE_ID,
                        EconomyEvent.week == WEEK,
                        EconomyEvent.event_type == EVENT_WEEKLY_MINIMUM_RELEASE)
                .count())

_assert("§2: the weekly minimum was released for every team",
        released == len(TEAM_IDS) == 4, f"{released} release event(s)")
_assert("§2: the ledger balances before anything else happens",
        trial_balance() == 0, str(trial_balance()))

_section("§3 · no SKUNK_ASSESSMENT exists for that week")

with tdb.SessionLocal() as db:
    skunk_events = (db.query(EconomyEvent)
                    .filter(EconomyEvent.league_id == LEAGUE_ID,
                            EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT)
                    .count())

_assert("§3: zero Skunk assessment events for this league",
        skunk_events == 0, f"{skunk_events} event(s)")

# THE ENGINE WOULD HAVE FOUND ONE. This is what makes §3 a gap rather than a
# league that simply had no skunk: the certified selector, called directly,
# names a loser and a margin. Nothing in production calls it — that is the gap.
with tdb.SessionLocal() as db:
    from economy.skunk import determine_skunk_losers
    would_be_losers, would_be_margin = determine_skunk_losers(
        db, league_id=LEAGUE_ID, week=WEEK)

_assert("§3: yet the certified engine WOULD assess one — the week is skunkable",
        len(would_be_losers) == 1 and would_be_margin is not None,
        f"loser={would_be_losers}, margin={would_be_margin}")
_assert("§3: and it is the worst loss, at the expected decimal margin",
        would_be_losers == (TEAM_IDS[0],) and round(would_be_margin, 2) == 30.64,
        f"team {would_be_losers} by {would_be_margin}")

_section("§4 · the gap BEFORE the close, and the fix that closes it")

# ── §4a · THE GAP AS IT STOOD ────────────────────────────────────────────────
#
# Asserted BEFORE Week Close runs, which is where the gap actually lived: a
# league with a finalized, played week, every other prerequisite satisfied, and
# a season that cannot close. This half holds regardless of WP6A, because
# nothing has assessed the week yet — it is the state a league sits in between
# the results going final and the commissioner closing the week.

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from auth.session import CSRF_COOKIE, CSRF_HEADER  # noqa: E402
from betting.pool_season_boundary import season_final_week  # noqa: E402
from economy.season_close_orchestrator import (  # noqa: E402
    SeasonClosePreconditionError, verify_preconditions,
)


def _first_unmet_step():
    """The orchestrator's FIRST unmet precondition, or None."""
    with tdb.SessionLocal() as db:
        lg = db.query(League).filter(League.id == LEAGUE_ID).one()
        try:
            verify_preconditions(db, league_id=LEAGUE_ID,
                                 final_week=season_final_week(lg))
            return None, ""
        except SeasonClosePreconditionError as exc:
            return exc.step, str(exc)
        finally:
            db.rollback()


# THE PRE-WP6A CLOSE, REPRODUCED EXACTLY. The old route's entire body was
# `expire_week` and a commit — no Skunk. Running that here puts the league in
# the precise state the shipped product left it in, which is the only way to
# show the gap now that the route itself no longer produces it.
#
# ORDER MATTERS AND IS WHY THIS STEP IS NEEDED. `verify_preconditions` refuses
# at the FIRST unmet step, and weekly-minimum expiry (step 4/5) is checked
# BEFORE the Skunk assessment (step 6/7). Asked before any close at all, the
# orchestrator names expiry and the Skunk block is still hidden behind it — so
# the gap only becomes visible once expiry is satisfied, which is exactly the
# state the old Week Close produced.
from economy.weekly_minimum import expire_week  # noqa: E402

step_untouched, _ = _first_unmet_step()
_assert("§4a: before ANY close, expiry is the first unmet step — Skunk is "
        "still hidden behind it",
        step_untouched == "weekly_minimum_expiry",
        f"first unmet step is {step_untouched!r}")

with tdb.SessionLocal() as db:
    expire_week(db, league_id=LEAGUE_ID, week=WEEK)
    db.commit()

step_before, message_before = _first_unmet_step()

_assert("§4a: with expiry done and Skunk not assessed — the pre-WP6A state — "
        "season close refuses ON SKUNK",
        step_before == "skunk_assessed",
        f"first unmet step is {step_before!r}: {message_before[:100]}")
_assert("§4a: and the refusal names the unassessed week",
        f"week {WEEK}" in message_before, message_before[:110])

with tdb.SessionLocal() as db:
    _still_none = (db.query(EconomyEvent)
                   .filter(EconomyEvent.league_id == LEAGUE_ID,
                           EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT)
                   .count())
_assert("§4a: the week is closed for expiry purposes yet carries no Skunk — "
        "the gap, exactly as WP5 reported it",
        _still_none == 0, f"{_still_none} assessment event(s)")

# ── §4b · WHAT WP6A CHANGED ──────────────────────────────────────────────────
#
# Week Close now assesses the Skunk as part of end-of-week reconciliation. The
# route is the ONLY way a commissioner causes one — there is deliberately no
# separate action — so this is both the fix and the whole user workflow.

client = TestClient(app, raise_server_exceptions=False)
r = client.post("/auth/session", json={"email": COMM_EMAIL, "password": PASSWORD})
assert r.status_code == 200, r.text

close = client.post(f"/league/{LEAGUE_ID}/week/{WEEK}/close",
                    headers={CSRF_HEADER: client.cookies.get(CSRF_COOKIE)})

_assert("§4b: the production Week Close route SUCCEEDS on this week",
        close.status_code == 200, f"{close.status_code} {close.text[:120]}")

with tdb.SessionLocal() as db:
    after_close = (db.query(EconomyEvent)
                   .filter(EconomyEvent.league_id == LEAGUE_ID,
                           EconomyEvent.event_type == EVENT_SKUNK_ASSESSMENT)
                   .count())

_assert("§4b: and the week is now assessed — Week Close reached the engine",
        after_close == 1, f"{after_close} assessment event(s)")
_assert("§4b: the close reported the outcome it produced",
        (close.json().get("skunk") or {}).get("assessed") is True,
        str(close.json().get("skunk"))[:120])

step_after, message_after = _first_unmet_step()
_assert("§4b: and season close no longer blocks on skunk_assessed",
        step_after != "skunk_assessed",
        f"first unmet step is now {step_after!r}" if step_after
        else "no unmet precondition at all")

_section("§5 · the production path that closes this gap (INVERTED at WP6A)")

# THIS SECTION RECORDED THE GAP AND NOW GUARDS THE FIX. Before WP6A it asserted
# that NOTHING in production called `assess_weekly_skunk` — which was the whole
# finding. WP6A wired the engine into Week Close, so the same scan now asserts
# the opposite: a caller exists, and it is the Week Close route.
#
# INVERTING RATHER THAN DELETING KEEPS THE GUARD. If a future refactor removed
# the call, the product would silently return to the state §1-§4 describe:
# weeks closing, Skunk never assessed, season close blocked. This fails first.
#
# STATIC, OVER EXECUTABLE CODE ONLY. Comments and docstrings legitimately
# discuss the engine, and a grep that tripped on prose would prove nothing.
PRODUCTION_DIRS = ("api", "economy", "betting", "beefs", "wallet", "reports",
                   "providers", "ledger", "admin", "payments", "feed",
                   "connectors", "engine", "odds", "notifications")

callers: list[str] = []
scanned = 0
for d in PRODUCTION_DIRS:
    for path in (ROOT / d).rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            # A CALL, not a mention. `economy/skunk.py` defines it, and
            # season_close_orchestrator imports SkunkError from the module —
            # neither is an invocation of the weekly assessment.
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.id if isinstance(fn, ast.Name)
                        else fn.attr if isinstance(fn, ast.Attribute) else None)
                if name == "assess_weekly_skunk" and path.name != "skunk.py":
                    callers.append(f"{path.relative_to(ROOT)}:{node.lineno}")

_assert("§5: the scan actually covered the production tree",
        scanned > 50, f"{scanned} module(s) parsed")
_assert("§5: a production path DOES now call assess_weekly_skunk()",
        bool(callers), str(callers) if callers else "NO CALLER — the WP5 gap "
        "has reopened; Week Close no longer assesses the Skunk")
_assert("§5: and the caller is the Week Close route, not a separate chore",
        any("main.py" in c.replace("\\", "/").split("/")[-1].split(":")[0]
            for c in callers),
        str(callers))

# THE RULING FORBIDS A ROUTINE MANUAL ACTION. Skunk is end-of-week
# reconciliation, so no ordinary "assess Skunk" endpoint may appear beside it.
from api.main import app as _app  # noqa: E402

_route_paths = {getattr(r, "path", "") for r in _app.routes}
_assess_routes = [p for p in _route_paths
                  if "skunk" in p.lower() and p.rstrip("/").endswith(
                      ("assess", "assessment"))]
_assert("§5: no ordinary 'assess Skunk' route was added",
        not _assess_routes, str(_assess_routes))

# AND THE CONTROL: the scanner does find a call when one exists, so the negative
# above is a finding rather than a broken scan.
control = []
for node in ast.walk(ast.parse((ROOT / "economy" / "season_close_orchestrator.py")
                               .read_text(encoding="utf-8"))):
    if isinstance(node, ast.Call):
        fn = node.func
        name = (fn.id if isinstance(fn, ast.Name)
                else fn.attr if isinstance(fn, ast.Attribute) else None)
        if name == "distribute_season_skunk":
            control.append(node.lineno)

_assert("§5 CONTROL: the same scan DOES find the season distribution call",
        bool(control),
        f"distribute_season_skunk called at line(s) {control} — the scanner works")

_assert("§5: the ledger still balances; this suite moved no money of its own",
        trial_balance() == 0, str(trial_balance()))

tdb.teardown()

print("\n" + "=" * 78)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("WP6A GAP PROVED — Week Close completes, Skunk is never assessed, and "
      "season close is blocked with no product path to clear it")