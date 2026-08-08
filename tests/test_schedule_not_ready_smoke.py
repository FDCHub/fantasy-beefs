"""
test_schedule_not_ready_smoke.py — Smoke test for ScheduleNotReadyError wiring
across get_pending_challenges(), get_pool_week(), and submit_pool_pick().

Three cases, all keyed on week 99 (unused elsewhere in this temp DB — no
NflSchedule rows are ever inserted here, so _nfl_lock_time() raises
ScheduleNotReadyError cleanly for any week/season queried):

  1. get_pending_challenges() threads schedule_not_ready=True onto the
     ChallengeOut for a challenge in an unready week, and does NOT auto-expire
     that challenge (status stays "pending").
  2. get_pool_week() raises ValueError mentioning "schedule isn't ready" for
     an unready week.
  3. submit_pool_pick() raises the same for an unready week.

Uses a temp SQLite DB so prod is never touched. DATABASE_URL is set before
any project imports, matching test_beef_starters.py's pattern.
"""

import os
import sys
import tempfile

# ── Must set DATABASE_URL before any project import touches db/schema.py ──────
_TMP_DIR = tempfile.mkdtemp()
_DB_PATH = os.path.join(_TMP_DIR, "test_schedule_not_ready_smoke.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from db.schema import Base, engine, SessionLocal, BeefChallenge, League, Team, Wallet
from beefs.beef_engine import get_pending_challenges
from betting.pool_engine import get_pool_week, submit_pool_pick
from config import LOCK_SEASON

UNUSED_WEEK = 99  # no NflSchedule rows loaded for this week anywhere in this DB

# ── Helpers (same style as test_beef_starters.py) ─────────────────────────────

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


# ── DB bootstrap ──────────────────────────────────────────────────────────────

Base.metadata.create_all(engine)

with SessionLocal() as _db:
    league = League(season=LOCK_SEASON, name="Test League", projection_source="fantasypros")
    _db.add(league)
    _db.flush()

    t1 = Team(league_id=league.id, team_name="Team Alpha", owner="Alice", email="alice@t.com")
    t2 = Team(league_id=league.id, team_name="Team Beta",  owner="Bob",   email="bob@t.com")
    _db.add_all([t1, t2])
    _db.flush()

    _db.add(Wallet(team_id=t1.id, balance=1000.0))
    _db.add(Wallet(team_id=t2.id, balance=1000.0))

    # Directly-constructed BeefChallenge — NOT via issue_challenge(), since
    # issue_challenge() itself now calls _nfl_lock_time() and would raise
    # ScheduleNotReadyError -> ValueError before ever creating this row, for
    # the same reason this test wants to exercise downstream (get_pending_
    # challenges is the function under test here, not issue_challenge).
    challenge = BeefChallenge(
        challenger_team_id   = t1.id,
        challenged_team_id   = t2.id,
        week                 = UNUSED_WEEK,
        bet_type             = "straight",
        amount               = 10.0,
        challenger_odds      = 1.91,
        challenged_odds      = 1.91,
        challenger_moneyline = -110,
        challenged_moneyline = -110,
        status               = "pending",
        expires_at           = datetime.now(timezone.utc) + timedelta(hours=24),
    )
    _db.add(challenge)
    _db.commit()

    league_id    = league.id
    t1_id, t2_id = t1.id, t2.id
    challenge_id = challenge.id

# No NflSchedule rows are ever inserted into this DB — week 99 (and every
# other week/season) is unloaded by construction.


# ── CASE 1: get_pending_challenges() flag threading ───────────────────────────

print("\nCase 1: get_pending_challenges() threads schedule_not_ready and does not auto-expire")
with SessionLocal() as db:
    results = get_pending_challenges(t1_id, db)
    match = [c for c in results if c.challenge_id == challenge_id]
    _assert("challenge is returned by get_pending_challenges", len(match) == 1, f"got {len(match)} matches")
    if match:
        out = match[0]
        _assert("schedule_not_ready is True", out.schedule_not_ready is True, f"got {out.schedule_not_ready!r}")
        _assert("ChallengeOut.status is pending/countered, not expired",
                out.status in ("pending", "countered"), f"got {out.status!r}")

    row = db.query(BeefChallenge).filter(BeefChallenge.id == challenge_id).first()
    _assert("BeefChallenge row status unchanged (not auto-expired)",
            row.status in ("pending", "countered"), f"got {row.status!r}")


# ── CASE 2: get_pool_week() halts cleanly ─────────────────────────────────────

print("\nCase 2: get_pool_week() raises ValueError for an unready week")
with SessionLocal() as db:
    raised    = False
    error_msg = ""
    try:
        get_pool_week(league_id, UNUSED_WEEK, db)
    except ValueError as e:
        raised    = True
        error_msg = str(e)
    except Exception as e:
        error_msg = f"WRONG EXCEPTION TYPE: {type(e).__name__}: {e}"

    _assert("get_pool_week raises ValueError", raised, error_msg)
    _assert("message contains 'schedule isn't ready'", "schedule isn't ready" in error_msg, error_msg)


# ── CASE 3: submit_pool_pick() halts cleanly ──────────────────────────────────

print("\nCase 3: submit_pool_pick() raises ValueError for an unready week")
with SessionLocal() as db:
    raised    = False
    error_msg = ""
    try:
        submit_pool_pick(league_id, t1_id, "biggest_winner", None, UNUSED_WEEK, db)
    except ValueError as e:
        raised    = True
        error_msg = str(e)
    except Exception as e:
        error_msg = f"WRONG EXCEPTION TYPE: {type(e).__name__}: {e}"

    _assert("submit_pool_pick raises ValueError", raised, error_msg)
    _assert("message contains 'schedule isn't ready'", "schedule isn't ready" in error_msg, error_msg)


# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n{'='*52}")
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("All assertions PASSED")
