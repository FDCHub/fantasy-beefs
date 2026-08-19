#!/usr/bin/env python3
"""DEMO D2.3 — the provider-aware lock resolver, certified before it is used.

    python test_d23_lock_resolver.py
    DATABASE_URL=postgresql://.../fs_d23_test python test_d23_lock_resolver.py

THIS SEAM IS THE ONLY PRODUCTION CHANGE THE DEMO WORK MAKES, so it is certified
on its own before any gameplay is rebuilt on top of it. The question it has to
answer is narrow and total:

    can anything that is not the showcase demo league obtain the demo clock?

Every answer below is driven against real League rows — a Yahoo league, an
unbound league, a league merely NAMED the demo league, a demo league that is not
the showcase, and a hand-edited key with "showcase" in it but outside the demo
namespace.

AND THE OTHER DIRECTION: a production league's lock must be BYTE-IDENTICAL to
`_nfl_lock_time(league.season, week)`, including its `ScheduleNotReadyError`.
The seam must be invisible to everyone but the demo.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

_TMP = tempfile.mkdtemp(prefix="d23-")
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "sqlite:///" + os.path.join(_TMP, "d23.db").replace(os.sep, "/"))
os.environ.setdefault("JWT_SECRET_KEY", "d23-lock-resolver")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAIL: list = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAIL.append(label)


def section(t: str) -> None:
    print(f"\n{t}")


from fastapi.testclient import TestClient  # noqa: E402

import api.main_rc2 as entry  # noqa: E402

with TestClient(entry.app):
    pass

from sqlalchemy import text  # noqa: E402

from betting.exceptions import ScheduleNotReadyError  # noqa: E402
from betting.lock_resolver import (  # noqa: E402
    DEMO_LOCKED, DEMO_OPEN, is_demo_scheduled_league, lock_time_for_league,
    lock_time_for_teams,
)
from betting.pool_engine import _nfl_lock_time  # noqa: E402
from db.schema import League, NflSchedule, SessionLocal, Team, engine  # noqa: E402

print("=" * 74)
print(f"D2.3 — PROVIDER-AWARE LOCK RESOLVER  ({engine.dialect.name})")
print("=" * 74)

REAL_KICKOFF = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)

LEAGUES = {}
with SessionLocal() as db:
    db.add(NflSchedule(season=2026, week=5, home_team="NFL-H", away_team="NFL-A",
                       kickoff_utc=REAL_KICKOFF.replace(tzinfo=None)))
    specs = {
        "yahoo":            dict(provider="yahoo",
                                 provider_league_key="461.l.900001"),
        "unbound":          dict(provider=None, provider_league_key=None),
        "named_demo":       dict(provider="yahoo",
                                 provider_league_key="461.l.900002",
                                 name="FantasyStakes Demo League"),
        "demo_not_showcase": dict(provider="demo",
                                  provider_league_key="demo.l.900003"),
        "showcase_word_only": dict(provider="yahoo",
                                   provider_league_key="showcase.l.900004"),
        "demo_key_no_ns":   dict(provider="demo",
                                 provider_league_key="showcase-900005"),
        "showcase":         dict(provider="demo",
                                 provider_league_key="demo.l.showcase.900006"),
    }
    for label, kw in specs.items():
        kw.setdefault("name", f"League {label}")
        lg = League(season=2026, projection_source="fantasypros",
                    provider_current_week=11, **kw)
        db.add(lg)
        db.flush()
        LEAGUES[label] = lg.id
        team = Team(league_id=lg.id, team_name=f"{label}-t1", owner="o",
                    email=f"{label}@d23.test")
        db.add(team)
        db.flush()
        LEAGUES[f"{label}_team"] = team.id
    db.commit()


# ── 1 · only the showcase is demo-scheduled ─────────────────────────────────

section("1 · Exactly one binding shape gets the demo clock")

with SessionLocal() as db:
    for label in ("yahoo", "unbound", "named_demo", "demo_not_showcase",
                  "showcase_word_only", "demo_key_no_ns"):
        lg = db.query(League).filter(League.id == LEAGUES[label]).first()
        check(f"{label} is NOT demo-scheduled", not is_demo_scheduled_league(lg))
    lg = db.query(League).filter(League.id == LEAGUES["showcase"]).first()
    check("the showcase IS demo-scheduled", is_demo_scheduled_league(lg))
    check("  · and a None league is not", not is_demo_scheduled_league(None))


# ── 2 · production behaviour is unchanged ───────────────────────────────────

section("2 · A production league's lock is byte-identical to _nfl_lock_time")

with SessionLocal() as db:
    direct = _nfl_lock_time(2026, 5)
    for label in ("yahoo", "unbound", "named_demo", "demo_not_showcase",
                  "showcase_word_only", "demo_key_no_ns"):
        lg = db.query(League).filter(League.id == LEAGUES[label]).first()
        check(f"{label}: seam == _nfl_lock_time",
              lock_time_for_league(lg, 5) == direct, str(direct))

    # The error path must survive too: an unloaded week still raises.
    for label in ("yahoo", "demo_not_showcase"):
        lg = db.query(League).filter(League.id == LEAGUES[label]).first()
        raised = False
        try:
            lock_time_for_league(lg, 9)
        except ScheduleNotReadyError:
            raised = True
        check(f"{label}: an unloaded week still raises ScheduleNotReadyError",
              raised)

    # And a showcase does NOT raise for the same unloaded week.
    lg = db.query(League).filter(League.id == LEAGUES["showcase"]).first()
    ok = True
    try:
        lock_time_for_league(lg, 9)
    except ScheduleNotReadyError:
        ok = False
    check("the showcase does not need the NFL schedule at all", ok)


# ── 3 · the demo clock is the demo's own current week ───────────────────────

section("3 · The demo clock is wall-clock independent")

with SessionLocal() as db:
    lg = db.query(League).filter(League.id == LEAGUES["showcase"]).first()
    check("a played week is LOCKED", lock_time_for_league(lg, 5) == DEMO_LOCKED)
    check("the live week is OPEN", lock_time_for_league(lg, 11) == DEMO_OPEN)
    check("a future week is OPEN", lock_time_for_league(lg, 14) == DEMO_OPEN)
    check("  · the boundary is provider_current_week itself",
          lock_time_for_league(lg, 10) == DEMO_LOCKED
          and lock_time_for_league(lg, 11) == DEMO_OPEN)

    # Advancing the demo's own week moves the boundary — and nothing else does.
    lg.provider_current_week = 13
    db.flush()
    check("advancing the demo week re-locks the weeks behind it",
          lock_time_for_league(lg, 11) == DEMO_LOCKED
          and lock_time_for_league(lg, 13) == DEMO_OPEN)
    lg.provider_current_week = 11
    db.flush()

    # No stored schedule means no calendar dependence.
    check("the demo lock consults no NflSchedule row",
          lock_time_for_league(lg, 5) == DEMO_LOCKED
          and lock_time_for_league(lg, 11) == DEMO_OPEN)
    check("  · and a showcase with no current week fails closed",
          lock_time_for_league(
              type("L", (), {"provider": "demo",
                             "provider_league_key": "demo.l.showcase.x",
                             "provider_current_week": None,
                             "season": 2026})(), 11) == DEMO_LOCKED)


# ── 4 · team-based resolution cannot be tricked ─────────────────────────────

section("4 · Resolving by team id fails to the production path")

with SessionLocal() as db:
    direct = _nfl_lock_time(2026, 5)
    check("showcase teams resolve to the demo clock",
          lock_time_for_teams(db, team_ids=(LEAGUES["showcase_team"],),
                              season=2026, week=11) == DEMO_OPEN)
    check("yahoo teams resolve to the NFL clock",
          lock_time_for_teams(db, team_ids=(LEAGUES["yahoo_team"],),
                              season=2026, week=5) == direct)
    # A MIXED PAIR MUST NOT INHERIT THE DEMO CLOCK.
    check("a mixed showcase/Yahoo pair falls back to the NFL clock",
          lock_time_for_teams(
              db, team_ids=(LEAGUES["showcase_team"], LEAGUES["yahoo_team"]),
              season=2026, week=5) == direct)
    check("an unknown team id falls back to the NFL clock",
          lock_time_for_teams(db, team_ids=(999999,), season=2026, week=5)
          == direct)
    check("an empty team set falls back to the NFL clock",
          lock_time_for_teams(db, team_ids=(), season=2026, week=5) == direct)


# ── 4a · the caller's season is honoured, not the league's ──────────────────

section("4a · The caller's season wins — LOCK_SEASON is not the league season")

# THE REGRESSION THIS CATCHES. `beef_engine` asks about LOCK_SEASON, which
# `config.py` documents as independent of the league's own season. A resolver
# that substituted `league.season` broke `test_beef_starters.py`, whose league
# is season 2025 while LOCK_SEASON is 2026.
with SessionLocal() as db:
    db.add(NflSchedule(season=2025, week=5, home_team="OLD-H",
                       away_team="OLD-A",
                       kickoff_utc=datetime(2025, 10, 5, 17, 0)))
    db.commit()

with SessionLocal() as db:
    lg = db.query(League).filter(League.id == LEAGUES["yahoo"]).first()
    check("an explicit season is used instead of league.season",
          lock_time_for_league(lg, 5, season=2025) == _nfl_lock_time(2025, 5),
          f"league.season={lg.season}")
    check("  · and differs from the league-season answer",
          _nfl_lock_time(2025, 5) != _nfl_lock_time(2026, 5))
    check("omitting the season falls back to league.season",
          lock_time_for_league(lg, 5) == _nfl_lock_time(lg.season, 5))
    check("lock_time_for_teams carries the caller's season through",
          lock_time_for_teams(db, team_ids=(LEAGUES["yahoo_team"],),
                              season=2025, week=5) == _nfl_lock_time(2025, 5))


# ── 5 · the global NFL schedule is never written ────────────────────────────

section("5 · No demo path creates or mutates a global schedule row")

with SessionLocal() as db:
    before = db.execute(text(
        # NO COALESCE TO A STRING. PostgreSQL rejects coalescing a timestamp with
        # '' (InvalidDatetimeFormat); SQLite accepts it silently. Compare the
        # raw values instead, which both dialects return identically.
        "SELECT count(*), MIN(kickoff_utc) FROM nfl_schedule")).fetchone()

with SessionLocal() as db:
    lg = db.query(League).filter(League.id == LEAGUES["showcase"]).first()
    for week in range(1, 18):
        lock_time_for_league(lg, week)
        lock_time_for_teams(db, team_ids=(LEAGUES["showcase_team"],),
                            season=2026, week=week)

with SessionLocal() as db:
    after = db.execute(text(
        # NO COALESCE TO A STRING. PostgreSQL rejects coalescing a timestamp with
        # '' (InvalidDatetimeFormat); SQLite accepts it silently. Compare the
        # raw values instead, which both dialects return identically.
        "SELECT count(*), MIN(kickoff_utc) FROM nfl_schedule")).fetchone()
check("nfl_schedule is byte-identical after every demo lock read",
      tuple(before) == tuple(after), f"{tuple(before)} -> {tuple(after)}")

src = open("betting/lock_resolver.py", encoding="utf-8").read()
check("the resolver never writes anything",
      not any(k in src for k in ("db.add", "db.commit", "INSERT", "UPDATE",
                                 "DELETE")))
check("  · and never imports NflSchedule", "NflSchedule" not in src)


# ── 6 · the sentinels cannot be mistaken for fixtures ───────────────────────

section("6 · The demo sentinels are unmistakably synthetic")

check("the locked sentinel is absurdly historic", DEMO_LOCKED.year == 1901)
check("the open sentinel is absurdly future", DEMO_OPEN.year == 2999)
check("  · so neither sits in the real NFL kickoff band _nfl_lock_time validates",
      DEMO_LOCKED.year < 1990 and DEMO_OPEN.year > 2100)


print("\n" + "=" * 74)
if FAIL:
    print(f"D2.3 LOCK RESOLVER — {len(FAIL)} FAILED")
    for f in FAIL:
        print(f"  · {f}")
    sys.exit(1)
print(f"PASS: lock resolver certified on {engine.dialect.name}")
