"""
test_league_economy_stop.py — Session B1-12, retargeted by the B2 Stripe removal:
dependency on LeagueTreasury is fully removed. The stop now lives on
League.economy_stop_weekly_min_cents, read via
payments.economy_config.get_league_economy_stop(), independent of
LeagueTreasury entirely.

Covers:
  1. get_league_economy_stop() resolves the default for a league with NO LeagueTreasury
     row at all, using the default stop.
  2. set_league_economy_stop() + get_league_economy_stop() together: a
     non-default stop selection is honored end-to-end, independent of
     LeagueTreasury.
  3. set_league_economy_stop() rejects a weekly_min_cents value that
     doesn't match one of the five stops — raises ValueError, no
     partial write.

Uses a temp SQLite DB so prod is never touched.
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_league_economy_stop.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
# Stripe is removed from the MVP; no payment env var participates in this test.

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.schema import Base, engine, SessionLocal, League, LeagueTreasury, Team
from payments.economy_config import (
    ECONOMY_STOPS,
    DEFAULT_STOP,
    set_league_economy_stop,
    get_league_economy_stop,
)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── DB bootstrap ──────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)
_assert("no payment rail is importable (Stripe removed from the MVP)",
        __import__("importlib").util.find_spec("payments.stripe_connect") is None,
        "payments.stripe_connect still importable")


def _make_league_and_team(name: str) -> tuple[int, int]:
    with SessionLocal() as db:
        league = League(season=2025, name=f"B1-12 Test League {name}", projection_source="fantasypros")
        db.add(league)
        db.flush()
        team = Team(league_id=league.id, team_name=f"Team {name}", owner=f"Owner {name}", email=f"{name}@t.com")
        db.add(team)
        db.commit()
        return league.id, team.id


# ── ITEM 1: the stop resolver works with NO LeagueTreasury row at all ─────

print("\nItem 1: the default stop resolves for a league with zero LeagueTreasury rows")

league_id1, team_id1 = _make_league_and_team("no_treasury")

with SessionLocal() as db:
    treasury_count = db.query(LeagueTreasury).filter(LeagueTreasury.league_id == league_id1).count()
_assert("confirmed: zero LeagueTreasury rows exist for this league", treasury_count == 0, f"got {treasury_count}")

raised_no_treasury = False
try:
    with SessionLocal() as db:
        stop1 = get_league_economy_stop(league_id1, db)
except Exception as e:
    raised_no_treasury = True
    print(f"    unexpected exception: {e}")
_assert("get_league_economy_stop() did NOT raise despite no LeagueTreasury row", not raised_no_treasury)

if not raised_no_treasury:
    _assert("default stop used: buyin_cents == 22000", stop1.buyin_cents == DEFAULT_STOP.buyin_cents, f"got {stop1.buyin_cents}")
    _assert("default stop used: wallet_cents == 14000", stop1.wallet_cents == DEFAULT_STOP.wallet_cents, f"got {stop1.wallet_cents}")
    _assert("default stop used: reserve_cents == 8000", stop1.reserve_cents == DEFAULT_STOP.reserve_cents, f"got {stop1.reserve_cents}")
    _assert("default stop's weekly_min is 1000", DEFAULT_STOP.weekly_min_cents == 1000, f"got {DEFAULT_STOP.weekly_min_cents}")


# ── ITEM 2: set_league_economy_stop() — non-default stop honored end-to-end ──

print("\nItem 2: setting a non-default stop (weekly_min=2000) is honored end-to-end, independent of LeagueTreasury")

league_id2, team_id2 = _make_league_and_team("non_default_stop")

with SessionLocal() as db:
    treasury_count2 = db.query(LeagueTreasury).filter(LeagueTreasury.league_id == league_id2).count()
_assert("confirmed: zero LeagueTreasury rows exist for this league either", treasury_count2 == 0, f"got {treasury_count2}")

with SessionLocal() as db:
    matched_stop = set_league_economy_stop(league_id2, 2000, db)
_assert("set_league_economy_stop returns the matched stop", matched_stop.weekly_min_cents == 2000, f"got {matched_stop.weekly_min_cents}")

with SessionLocal() as db:
    stop_now = get_league_economy_stop(league_id2, db)
_assert("get_league_economy_stop reflects the write", stop_now.weekly_min_cents == 2000, f"got {stop_now.weekly_min_cents}")

with SessionLocal() as db:
    stop2 = get_league_economy_stop(league_id2, db)

_assert("weekly_min=2000 stop: buyin_cents == 44000", stop2.buyin_cents == 44000, f"got {stop2.buyin_cents}")
_assert("weekly_min=2000 stop: wallet_cents == 28000", stop2.wallet_cents == 28000, f"got {stop2.wallet_cents}")
_assert("weekly_min=2000 stop: reserve_cents == 16000", stop2.reserve_cents == 16000, f"got {stop2.reserve_cents}")
_assert("wallet + reserve == buyin for this stop", stop2.wallet_cents + stop2.reserve_cents == stop2.buyin_cents,
        f"got {stop2.wallet_cents} + {stop2.reserve_cents} vs {stop2.buyin_cents}")


# ── ITEM 3: set_league_economy_stop() rejects a non-matching weekly_min_cents ──

print("\nItem 3: set_league_economy_stop() rejects a value that doesn't match one of the five stops")

league_id3, _team_id3 = _make_league_and_team("bad_stop")

with SessionLocal() as db:
    before = db.query(League).filter(League.id == league_id3).first()
    stop_before = before.economy_stop_weekly_min_cents
_assert("league's stop selector starts unset (NULL)", stop_before is None, f"got {stop_before}")

raised_bad_stop = False
try:
    with SessionLocal() as db:
        set_league_economy_stop(league_id3, 1200, db)  # not one of 500/1000/1500/2000/2500
except ValueError:
    raised_bad_stop = True
_assert("ValueError raised for weekly_min_cents=1200 (not a certified stop)", raised_bad_stop)

with SessionLocal() as db:
    after = db.query(League).filter(League.id == league_id3).first()
    stop_after = after.economy_stop_weekly_min_cents
_assert("no partial write — league's stop selector still NULL after the rejected call", stop_after is None, f"got {stop_after}")


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
