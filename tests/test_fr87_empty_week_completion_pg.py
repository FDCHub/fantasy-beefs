"""
test_fr87_empty_week_completion_pg.py — FR-8.7-BUG-1, empty-week completion (PostgreSQL).

A week that reaches Phase-2 with zero pending bets must complete to COMPLETED
through the shared guarded completion block (settlement_engine.py 746-780), not
strand as CLAIMED.

Asserts the FIXED behavior from the start (11 assertions):
   1. first empty-week settle_week raises nothing
   2. it returns a SettlementReport
   3. report totals are zero
   4. the durable week_settlements row exists
   5. status == "COMPLETED"
   6. settled is True
   7. settled_at is not None
   8. recovery_token is None
   9. an ordinary retry raises nothing
  10. the retry returns already_settled is True
  11. the retry creates no second week_settlements row

Against CURRENT code this fails RED at assertions 5-10: the early return at
settlement_engine.py 509-511 leaves the row CLAIMED (5-8 fail), and the retry
takes the Phase-1 conflict path, reads CLAIMED with no token (guard 4a, line
394), and raises the manual-recovery ValueError (9-10 fail). After the fix
(remove the 509-511 early return so an empty pending falls through the empty
513-518 setup -> zero-iteration loop -> shared completion 746-780), the SAME
unchanged assertions pass GREEN.

Runs on real PostgreSQL via the 6a harness: the empty-week path necessarily
passes through the line-435 SELECT ... FOR UPDATE, which SQLite cannot parse.

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Harness FIRST. setup_postgres_test_db() applies its safety guards, sets
# DATABASE_URL to the disposable test DB, and imports+binds db.schema INTERNALLY.
# No project module may be imported before this call, or the engine would bind to
# the wrong database. Only test_support_postgres is safe at module top.
from test_support_postgres import setup_postgres_test_db

# Exit-2 harness/config error path stays BEFORE main()/teardown: if setup fails
# (e.g. missing/unsafe TEST_DATABASE_URL) NOTHING was created, so nothing to tear down.
try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] FR-8.7 empty-week suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work lives here so teardown protection begins the instant setup
    succeeds. Project imports are INSIDE this function: setup already created the
    schema, so if any import raised, teardown still runs via the caller's finally."""
    from datetime import datetime

    from db.schema import (
        Base, engine, SessionLocal,
        League, Team, Matchup, NflSchedule, WeekSettlement,
    )
    from betting.settlement_engine import settle_week, SettlementReport
    from betting.per_bet_lock import LOCK_SEASON
    from config import CURRENT_SEASON as SEASON

    # Fixed future kickoff literal — matches the existing suite's FUTURE_KO
    # (settlement_engine's empty-week path does not depend on lock timing; this
    # keeps the NflSchedule row consistent with the rest of the suite).
    FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)

    _WEEK = 1

    # ── League ────────────────────────────────────────────────────────────────
    with SessionLocal() as _db:
        league = League(season=SEASON, name="FR-8.7 Empty Week Test League",
                        projection_source="fantasypros")
        _db.add(league)
        _db.commit()
        LEAGUE_ID = league.id

    # ── Two Teams (Matchup.home_team_id / away_team_id are non-null FKs to
    # teams.id — both must exist before the Matchup insert). Distinct emails:
    # Team.email is non-null unique. No Wallet is seeded: the empty-week path
    # places no bets and credits no wallet. ─────────────────────────────────────
    with SessionLocal() as _db:
        home = Team(league_id=LEAGUE_ID, team_name="Empty Home", owner="home",
                    email="empty-home@fr87test.com")
        away = Team(league_id=LEAGUE_ID, team_name="Empty Away", owner="away",
                    email="empty-away@fr87test.com")
        _db.add(home)
        _db.add(away)
        _db.commit()
        HOME_ID = home.id
        AWAY_ID = away.id

    # ── Matchup + NflSchedule for (LEAGUE_ID, _WEEK). Makes the week real enough
    # for settle_week to claim it and reach Phase-2 — but NO bets are placed, so
    # settle_week's pending query returns empty. That empty-pending state is the
    # path under test. week_settlements is NOT pre-inserted; settle_week's own
    # Phase-1 claim (351-360) creates it. ───────────────────────────────────────
    with SessionLocal() as _db:
        _db.add(Matchup(league_id=LEAGUE_ID, week=_WEEK,
                        home_team_id=HOME_ID, away_team_id=AWAY_ID,
                        home_score=0.0, away_score=0.0))
        _db.add(NflSchedule(season=LOCK_SEASON, week=_WEEK,
                            home_team="KC", away_team="PHI",
                            kickoff_utc=FUTURE_KO))
        _db.commit()

    # ── First empty-week settlement ────────────────────────────────────────────
    first_raised = None
    report1 = None
    with SessionLocal() as db:
        try:
            report1 = settle_week(_WEEK, db, league_id=LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001 — a raise on the first call is a failure
            first_raised = exc

    # 1. first call raises nothing
    _assert(
        "1: first empty-week call raises nothing",
        first_raised is None,
        detail=f"raised {type(first_raised).__name__}: {first_raised}" if first_raised else "",
    )
    # 2. returns a SettlementReport
    _assert(
        "2: first call returns a SettlementReport",
        isinstance(report1, SettlementReport),
        detail=f"got {type(report1).__name__}",
    )
    # 3. report totals are zero
    _assert(
        "3: report totals are zero",
        isinstance(report1, SettlementReport)
        and report1.total_bets == 0
        and report1.bets_won == 0
        and report1.bets_lost == 0
        and report1.total_staked == 0.0
        and report1.total_payout == 0.0,
        detail=(
            f"total_bets={getattr(report1, 'total_bets', '?')} "
            f"total_staked={getattr(report1, 'total_staked', '?')} "
            f"total_payout={getattr(report1, 'total_payout', '?')}"
        ),
    )

    # ── Durable row after the first call (fresh session) ───────────────────────
    with SessionLocal() as db:
        ws = (
            db.query(WeekSettlement)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK)
            .first()
        )

    # 4. durable row exists
    _assert(
        "4: durable week_settlements row exists",
        ws is not None,
        detail="no row found for (LEAGUE_ID, _WEEK)",
    )
    # 5. status == "COMPLETED"   (RED on current code: stays CLAIMED)
    _assert(
        "5: status == COMPLETED",
        ws is not None and ws.status == "COMPLETED",
        detail=f"status={getattr(ws, 'status', '<none>')!r}",
    )
    # 6. settled is True         (RED on current code: stays False)
    _assert(
        "6: settled is True",
        ws is not None and ws.settled is True,
        detail=f"settled={getattr(ws, 'settled', '<none>')}",
    )
    # 7. settled_at is not None   (RED on current code: stays NULL)
    _assert(
        "7: settled_at is not None",
        ws is not None and ws.settled_at is not None,
        detail=f"settled_at={getattr(ws, 'settled_at', '<none>')}",
    )
    # 8. recovery_token is None
    _assert(
        "8: recovery_token is None",
        ws is not None and ws.recovery_token is None,
        detail=f"recovery_token={getattr(ws, 'recovery_token', '<none>')!r}",
    )

    # ── Ordinary retry (fresh session) ─────────────────────────────────────────
    retry_raised = None
    report2 = None
    with SessionLocal() as db:
        try:
            report2 = settle_week(_WEEK, db, league_id=LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001 — a raise on retry is the RED failure
            retry_raised = exc

    # 9. retry raises nothing    (RED on current code: raises manual-recovery ValueError)
    _assert(
        "9: ordinary retry raises nothing",
        retry_raised is None,
        detail=f"raised {type(retry_raised).__name__}: {retry_raised}" if retry_raised else "",
    )
    # 10. retry returns already_settled is True   (RED on current code: no report, it raised)
    _assert(
        "10: retry returns already_settled is True",
        isinstance(report2, SettlementReport) and report2.already_settled is True,
        detail=(
            f"already_settled={getattr(report2, 'already_settled', '<none>')}"
            if report2 is not None else "no report (retry raised)"
        ),
    )

    # ── No second week_settlements row after retry (fresh session) ─────────────
    with SessionLocal() as db:
        ws_count = (
            db.query(WeekSettlement)
            .filter_by(league_id=LEAGUE_ID, week=_WEEK)
            .count()
        )
    # 11. retry creates no second row
    _assert(
        "11: retry creates no second week_settlements row (exactly one)",
        ws_count == 1,
        detail=f"row count={ws_count}",
    )


if __name__ == "__main__":
    try:
        main(tdb)
    finally:
        tdb.teardown()

    print()
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED")
        for label in _failures:
            print(f"  - {label}")
        sys.exit(1)
    print("RESULT: all empty-week completion assertions PASSED")
