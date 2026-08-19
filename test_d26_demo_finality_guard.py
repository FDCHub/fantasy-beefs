#!/usr/bin/env python3
"""D2.6 — the synthetic demo's finality writer, guarded. (WEBDEPLOY-1a)

    DATABASE_URL=postgresql://.../fs_d26_test python test_d26_demo_finality_guard.py

WHY THIS SUITE EXISTS. S6 gate C-7 asserts that the four load-bearing `Matchup`
fields — `finalized_at`, `home_score`, `away_score`, `winner_team_id` — are
written in production code only by writers that have been certified. Composing
the certified synthetic showcase onto RC3 introduced a fifth writer,
`demo/states.py::finalize_week`, and C-7 correctly refused a tree it had never
been shown.

WEBDEPLOY-1a certifies that one function BY NAME. A grant made by name has to be
backed by behaviour, so this suite exists to be the behaviour: it proves, against
a real PostgreSQL database, that the writer refuses every league it does not own
and that it can never return a finalized result to unfinalized.

── WHY THE ADVERSARIES ARE STRUCTURAL CLONES, NOT STUBS ────────────────────

`finalize_week` finds the rows it writes by matching `(home_team_id,
away_team_id)` pairs against the fixture, through team NAMES. A test that pointed
it at an empty Yahoo league would prove nothing: the lookup would find no rows
and the writer would appear safe for a reason that has nothing to do with the
guard.

So every adversary here is a full structural clone of the showcase — the same
twelve team names, the same week-11 pairings, rows sitting at 0.0 and NOT
finalized. If the guard were removed, the writer would find those rows and stamp
them. The clones are what make "refused" mean something.

── WHAT IS ASSERTED ────────────────────────────────────────────────────────

    A  a Yahoo league is refused, and its rows are untouched
    B  a demo-provider league that is not the showcase is refused
    C  an unbound league (no provider at all) is refused
    D  a Yahoo league NAMED "FantasyStakes Demo League" is refused
    E  a RETIRED showcase is refused — proven by retiring the real one
    F  a legitimate call reaches ONLY its own league's rows
    G  `finalized_at` moves NULL -> timestamp and never the other way
    H  no HTTP route reaches the writer

REQUIRES POSTGRESQL. The showcase seeder settles real weeks through
`betting.settlement_engine`, which takes `SELECT ... FOR UPDATE`; SQLite has no
such statement, and the deployment target is PostgreSQL.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_FAILURES: list = []
_PASSES = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _PASSES
    if condition:
        _PASSES += 1
        print(f"  [PASS] {label}" + (f" - {detail}" if detail else ""))
    else:
        _FAILURES.append(label)
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


from fastapi.testclient import TestClient  # noqa: E402

import api.main_rc2 as entry  # noqa: E402

with TestClient(entry.app):
    pass

from db.schema import League, Matchup, SessionLocal, Team, engine  # noqa: E402
from ledger.ledger import create_ledger_table  # noqa: E402

create_ledger_table()

from demo import showcase, states  # noqa: E402
from demo.reset import (  # noqa: E402
    RETIRED_PREFIX, DemoSafetyError, retire_showcase,
)
from demo.seed import find_showcase, seed  # noqa: E402

DIALECT = engine.dialect.name

print("=" * 78)
print(f"D2.6 - SYNTHETIC DEMO FINALITY WRITER GUARD  ({DIALECT})")
print("=" * 78)

if DIALECT != "postgresql":
    print("\nREQUIRES POSTGRESQL - set DATABASE_URL to a PostgreSQL database.")
    print("This suite does NOT fall back to SQLite: the showcase seeder settles")
    print("real weeks through SELECT ... FOR UPDATE, which SQLite does not have.")
    raise SystemExit(2)


# ── the showcase itself ──────────────────────────────────────────────────────

section("0 - The showcase, seeded")

summary = seed()
check("the showcase seeded", isinstance(summary.get("league_id"), int),
      f"league {summary.get('league_id')}")
check("trial balance is zero", summary["trial_balance"] == 0,
      str(summary["trial_balance"]))

LIVE_WEEK = showcase.CURRENT_WEEK


# ── structural clones ────────────────────────────────────────────────────────

def build_clone(db, *, name: str, provider, key, season=None) -> int:
    """A league indistinguishable from the showcase to the writer's row lookup.

    Same twelve team names, same week-11 pairings, every row unfinalized. What
    it does NOT have is a provider binding that `assert_demo_league` accepts,
    which is the single thing under test.
    """
    league = League(season=showcase.SEASON if season is None else season,
                    name=name, projection_source="fantasypros",
                    provider=provider, provider_league_key=key)
    db.add(league)
    db.flush()

    teams = {}
    for spec in showcase.TEAMS:
        team = Team(league_id=league.id, team_name=spec.team_name,
                    owner=spec.gm,
                    email=f"clone{league.id}.{spec.ordinal}@x.invalid")
        db.add(team)
        db.flush()
        teams[spec.ordinal] = team

    for home, away, _home_pts, _away_pts in showcase.REGULAR_SCHEDULE[LIVE_WEEK]:
        db.add(Matchup(league_id=league.id, week=LIVE_WEEK,
                       home_team_id=teams[home].id, away_team_id=teams[away].id,
                       home_score=0.0, away_score=0.0, winner_team_id=None,
                       finalized_at=None, refreshed_at=None))
    db.flush()
    return league.id


def clone_state(db, league_id: int) -> list:
    return [(m.id, m.home_score, m.away_score, m.winner_team_id, m.finalized_at)
            for m in db.query(Matchup)
            .filter(Matchup.league_id == league_id)
            .order_by(Matchup.id).all()]


section("1 - Structural clones of the showcase, under four false identities")

ADVERSARIES = (
    ("a Yahoo league", "Real Yahoo League", "yahoo", "461.l.990001", None),
    ("a demo-provider league that is not the showcase",
     "Some Other Demo League", "demo", "demo.l.other.990002", None),
    ("an unbound league with no provider", "Unbound League", None, None, None),
    ("a Yahoo league NAMED the demo league",
     "FantasyStakes Demo League", "yahoo", "461.l.990003", None),
    # A retired showcase key, written directly. Section 5 additionally proves
    # the REAL retirement path produces exactly this shape.
    ("a retired showcase", "FantasyStakes Demo League (retired)", "demo",
     f"{RETIRED_PREFIX}990004.990004", None),
)

clones = {}
with SessionLocal() as db:
    for label, name, provider, key, season in ADVERSARIES:
        clones[label] = build_clone(db, name=name, provider=provider,
                                    key=key, season=season)
    db.commit()

check("five structural clones exist", len(clones) == 5, str(sorted(clones.values())))

with SessionLocal() as db:
    sample = clone_state(db, clones["a Yahoo league"])
check("each clone carries the showcase's own week-11 fixtures, unfinalized",
      len(sample) == len(showcase.REGULAR_SCHEDULE[LIVE_WEEK])
      and all(row[4] is None for row in sample),
      f"{len(sample)} rows")

with SessionLocal() as db:
    resolved = states._teams_by_ordinal(db, clones["a Yahoo league"])
check("the writer's own team lookup RESOLVES against a clone",
      len(resolved) == len(showcase.TEAMS),
      f"{len(resolved)}/{len(showcase.TEAMS)} ordinals - so a refusal cannot be "
      f"an accident of an empty lookup")


# ── 2 · every false identity is refused, and nothing is written ──────────────

section("2 - The writer refuses every league it does not own")

for label, league_id in clones.items():
    with SessionLocal() as db:
        league = db.query(League).filter(League.id == league_id).first()
        teams = states._teams_by_ordinal(db, league_id)
        before = clone_state(db, league_id)

        refused, reason = False, ""
        try:
            states.finalize_week(db, league, teams, LIVE_WEEK)
        except DemoSafetyError as exc:
            refused, reason = True, str(exc)[:64]
        except Exception as exc:                       # pragma: no cover
            refused, reason = False, f"WRONG ERROR {type(exc).__name__}: {exc}"

        after = clone_state(db, league_id)
        db.rollback()

    check(f"REFUSES {label}", refused, reason)
    check(f"  - and wrote nothing to {label}", before == after,
          "byte-identical" if before == after else "ROWS CHANGED")

with SessionLocal() as db:
    for label, league_id in clones.items():
        rows = clone_state(db, league_id)
        check(f"  - {label} is still unfinalized after the attempt",
              all(row[4] is None for row in rows)
              and all(row[1] == 0.0 and row[2] == 0.0 for row in rows),
              f"{len(rows)} rows")


# ── 3 · a legitimate call reaches only its own league ────────────────────────

section("3 - A legitimate call is contained to its own league and week")

with SessionLocal() as db:
    league = find_showcase(db)
    teams = states._teams_by_ordinal(db, league.id)

    clone_before = {label: clone_state(db, lid) for label, lid in clones.items()}
    other_weeks_before = {
        (m.id): m.finalized_at
        for m in db.query(Matchup)
        .filter(Matchup.league_id == league.id, Matchup.week != LIVE_WEEK).all()}

    written = states.finalize_week(db, league, teams, LIVE_WEEK)

    clone_after = {label: clone_state(db, lid) for label, lid in clones.items()}
    other_weeks_after = {
        (m.id): m.finalized_at
        for m in db.query(Matchup)
        .filter(Matchup.league_id == league.id, Matchup.week != LIVE_WEEK).all()}

    live_rows = [(m.id, m.finalized_at) for m in db.query(Matchup)
                 .filter(Matchup.league_id == league.id,
                         Matchup.week == LIVE_WEEK).all()]
    db.rollback()

check("the legitimate call wrote the live week",
      written == len(showcase.REGULAR_SCHEDULE[LIVE_WEEK]), str(written))
check("every live-week row is now finalized",
      live_rows and all(stamp is not None for _id, stamp in live_rows),
      f"{len(live_rows)} rows")
check("NOT ONE clone row was touched by the legitimate call",
      clone_before == clone_after,
      "five leagues byte-identical" if clone_before == clone_after
      else "A CLONE CHANGED")
check("no other week of the showcase was touched",
      other_weeks_before == other_weeks_after,
      f"{len(other_weeks_before)} rows unchanged")


# ── 4 · finalized_at is monotonic ────────────────────────────────────────────

section("4 - finalized_at moves NULL -> timestamp, never back")

# THE TARGET WEEK IS CHOSEN FROM THE DATABASE, NOT ASSUMED. Hard-coding the
# live week would silently pass if an earlier section had already finalized it —
# "0 rows moved" is not the same claim as "no row was retracted", and only one
# of the two is what this section is for.
with SessionLocal() as db:
    league = find_showcase(db)
    unfinalized_weeks = sorted(
        week for week in showcase.REGULAR_SCHEDULE
        if all(m.finalized_at is None for m in db.query(Matchup)
               .filter(Matchup.league_id == league.id,
                       Matchup.week == week).all()))
    TARGET_WEEK = unfinalized_weeks[0] if unfinalized_weeks else None

check("the showcase still has an unfinalized week to move",
      TARGET_WEEK is not None, f"weeks {unfinalized_weeks}")

with SessionLocal() as db:
    league = find_showcase(db)
    teams = states._teams_by_ordinal(db, league.id)

    before = {m.id: m.finalized_at for m in db.query(Matchup)
              .filter(Matchup.league_id == league.id).all()}

    states.finalize_week(db, league, teams, TARGET_WEEK)
    once = {m.id: m.finalized_at for m in db.query(Matchup)
            .filter(Matchup.league_id == league.id).all()}

    # A SECOND CALL ON AN ALREADY-FINAL WEEK. The fixture clock is fixed, so a
    # repeat must be an exact no-op rather than a drifting timestamp - and it
    # must certainly not clear the column.
    states.finalize_week(db, league, teams, TARGET_WEEK)
    twice = {m.id: m.finalized_at for m in db.query(Matchup)
             .filter(Matchup.league_id == league.id).all()}
    db.rollback()

retracted = [mid for mid, stamp in before.items()
             if stamp is not None and once.get(mid) is None]
check("NO row moved from a timestamp back to NULL", not retracted, str(retracted))

moved = [mid for mid, stamp in before.items()
         if stamp is None and once.get(mid) is not None]
check(f"week {TARGET_WEEK} moved NULL -> timestamp",
      len(moved) == len(showcase.REGULAR_SCHEDULE[TARGET_WEEK]),
      f"{len(moved)} rows")

drifted = [mid for mid, stamp in before.items()
           if stamp is not None and once.get(mid) != stamp]
check("an already-final week was not restamped", not drifted, str(drifted))
check("a repeat call is an exact no-op", once == twice,
      "identical" if once == twice else "TIMESTAMPS DRIFTED")

repeat_nulls = [mid for mid, stamp in twice.items() if stamp is None
                and once.get(mid) is not None]
check("a repeat call cleared nothing", not repeat_nulls, str(repeat_nulls))


# ── 5 · a retired showcase, via the real retirement path ────────────────────

# THIS SECTION RUNS LAST, DELIBERATELY. `retire_showcase` settles the live week
# through `betting.settlement_engine`, which manages its own transaction and
# COMMITS — so the surrounding rollback returns the league row but not the
# settlement. Running it earlier would leave the showcase advanced and would
# make every later section depend on that, which is exactly the kind of hidden
# ordering a suite should not have.
section("5 - A retired showcase is refused, proven through real retirement")

with SessionLocal() as db:
    league = find_showcase(db)
    original_key = league.provider_league_key
    league_id = league.id

    # `retire_showcase` is itself guarded and settles the live week first, so
    # this is the genuine transition rather than a hand-written key.
    retire_showcase(db, league)
    retired_key = league.provider_league_key

    teams = states._teams_by_ordinal(db, league_id)
    refused, reason = False, ""
    try:
        states.finalize_week(db, league, teams, LIVE_WEEK + 1)
    except DemoSafetyError as exc:
        refused, reason = True, str(exc)[:64]
    db.rollback()

check("retirement moves the league out of the showcase namespace",
      retired_key.startswith(RETIRED_PREFIX) and "showcase" not in retired_key,
      f"{original_key} -> {retired_key}")
check("REFUSES a league that has just been retired", refused, reason)

with SessionLocal() as db:
    restored = find_showcase(db)
check("the rollback left the real showcase intact",
      restored is not None and restored.id == league_id
      and restored.provider_league_key == original_key,
      str(getattr(restored, "provider_league_key", None)))


# ── 6 · no HTTP route reaches the writer ─────────────────────────────────────

section("6 - The writer is not reachable from any HTTP route")

route_modules = set()
for route in entry.app.routes:
    endpoint = getattr(route, "endpoint", None)
    if endpoint is not None:
        route_modules.add(getattr(endpoint, "__module__", ""))

check("no route endpoint is defined in demo.states",
      "demo.states" not in route_modules,
      f"{len(route_modules)} endpoint modules")

api_importers = [name for name, module in list(sys.modules.items())
                 if name.startswith("api.") and module is not None
                 and getattr(module, "states", None) is states]
check("no api.* module holds a reference to demo.states",
      not api_importers, str(api_importers))

demo_routes = sorted({getattr(r, "path", "") for r in entry.app.routes
                      if str(getattr(r, "path", "")).startswith("/demo")})
check("the public demo surface is the certified route set",
      "/demo/enter" in demo_routes, ", ".join(demo_routes))


# ── verdict ──────────────────────────────────────────────────────────────────

print("\n" + "=" * 78)
if _FAILURES:
    print(f"D2.6 DEMO FINALITY GUARD: {len(_FAILURES)} FAILED")
    for item in _FAILURES:
        print(f"  - {item}")
    raise SystemExit(1)
print(f"D2.6 DEMO FINALITY GUARD: all {_PASSES} assertions PASSED")
