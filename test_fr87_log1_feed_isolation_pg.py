"""
test_fr87_log1_feed_isolation_pg.py — FR-8.7-LOG-1 (PostgreSQL).

Feed logging must not convert a committed settlement into a reported failure, and
must not run on settle_week's economic/report session. This test proves the
FIXED behavior; it is RED against current HEAD (feed logging still runs on the
settlement session at settlement_engine.py:782 and a feed failure propagates).

Instrumentation (not a mock): the REAL log_settlement_events is WRAPPED so that
_PHASE["feed"] is True only while its genuine body runs. do_orm_execute and
after_begin listeners on sqlalchemy.orm.Session, both gated on _PHASE["feed"],
count statements per session and identify the settlement session by `is`
comparison on the Session object — NEVER by connection (the pool hands both
sessions the same DBAPI connection after the economic commit, which would give a
false clean read). A before_flush listener forces a mid-batch feed failure by
raising while FeedEvent rows are staged — the real body still runs; only its
flush is made to fail.

Binding assertion: settlement-session statement count during the feed phase == 0,
on BOTH the success path and the forced-failure path.
Liveness assertion: the feed session's statement count during that phase > 0.

Requires TEST_DATABASE_URL — a dedicated, empty, _test-named, non-Railway
PostgreSQL database (see test_support_postgres guards).
"""

import logging
import os
import sys

from sqlalchemy import event
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── module-level instrumentation state ───────────────────────────────────────
_PHASE = {"feed": False}                 # True only while the real feed body runs
_COUNTS = {"settlement": 0, "feed": 0}   # per-phase statement counts
_SETTLEMENT_SESSION = {"obj": None}      # the Session passed to settle_week
_FORCE_FEED_FAILURE = {"on": False}      # forced mid-batch feed failure toggle
_FEED_ENTERED = {"on": False}            # did the feed block run at all this scenario
_REAL_LOG = {"fn": None}                 # the genuine log_settlement_events

_failures: list[str] = []

# ── Harness FIRST project import ──────────────────────────────────────────────
from test_support_postgres import setup_postgres_test_db

import datetime as _dt
#: S6 §8 — the instant this suite's fixture weeks are declared economically
#: final at. Fixed rather than now(): a fixture's finality must not drift with
#: the wall clock, and Matchup.finalized_at is the ONLY signal the shared
#: settlement gate reads. Stating it makes the completed-week premise these
#: scenarios always relied on explicit instead of implicit.
_FIXTURE_FINAL_AT = _dt.datetime(2025, 12, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)


try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] FR-8.7-LOG-1 suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _reset_instrumentation() -> None:
    _COUNTS["settlement"] = 0
    _COUNTS["feed"] = 0
    _FEED_ENTERED["on"] = False
    _SETTLEMENT_SESSION["obj"] = None
    _FORCE_FEED_FAILURE["on"] = False


class _ListHandler(logging.Handler):
    """Captures LogRecords so we can assert on RENDERED text (record.getMessage())."""
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def main(tdb) -> None:
    from datetime import datetime

    from db.schema import (
        SessionLocal, League, Team, Player, Roster, Wallet,
        Matchup, NflSchedule, WeekSettlement, FeedEvent, Bet,
    )
    import betting.settlement_engine as settlement_engine
    from betting.settlement_engine import settle_week, SettlementReport
    from beefs.beef_engine import issue_challenge, respond_to_challenge
    from betting.per_bet_lock import LOCK_SEASON
    from config import CURRENT_SEASON as SEASON
    from ledger.ledger import trial_balance

    # ── WRAP the real log_settlement_events (never replace/mock) ──────────────
    _REAL_LOG["fn"] = settlement_engine.log_settlement_events

    def _wrapped_log(settled, session):
        _FEED_ENTERED["on"] = True
        _PHASE["feed"] = True
        try:
            return _REAL_LOG["fn"](settled, session)
        finally:
            _PHASE["feed"] = False

    settlement_engine.log_settlement_events = _wrapped_log

    # ── Session listeners — gated on _PHASE["feed"], settlement session by `is` ──
    def _count(session) -> None:
        if not _PHASE["feed"]:
            return
        if session is _SETTLEMENT_SESSION["obj"]:
            _COUNTS["settlement"] += 1
        else:
            _COUNTS["feed"] += 1

    def _on_do_orm_execute(orm_execute_state):
        _count(orm_execute_state.session)

    def _on_after_begin(session, transaction, connection):
        _count(session)

    def _on_before_flush(session, flush_context, instances):
        if (_PHASE["feed"] and _FORCE_FEED_FAILURE["on"]
                and any(isinstance(o, FeedEvent) for o in session.new)):
            raise RuntimeError("FR-8.7-LOG-1 forced feed failure (test injection)")

    event.listen(Session, "do_orm_execute", _on_do_orm_execute)
    event.listen(Session, "after_begin", _on_after_begin)
    event.listen(Session, "before_flush", _on_before_flush)

    # ── capture the settlement engine's error log ─────────────────────────────
    _cap = _ListHandler()
    _cap.setLevel(logging.ERROR)
    eng_logger = logging.getLogger("betting.settlement_engine")
    eng_logger.addHandler(_cap)
    eng_logger.setLevel(logging.ERROR)

    FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)
    _FUND_CENTS = 100_000_00

    # ── per-scenario clean slate: reset(), clear instrumentation, and re-create
    # the League (reset() TRUNCATEs leagues too, so it must be re-seeded after).
    # RESTART IDENTITY makes the new league id deterministic (1) each scenario. ──
    def _reset_and_new_league() -> int:
        tdb.reset()
        _reset_instrumentation()
        _cap.records.clear()
        with SessionLocal() as _db:
            lg = League(season=SEASON, name="FR-8.7-LOG-1 Test League",
                        projection_source="fantasypros")
            _db.add(lg)
            _db.commit()
            return lg.id

    # ── fixture helpers (modeled on test_beef_settlement_escrow_close_pg.py) ───
    def _make_team(name: str, nfl_team: str) -> int:
        from ledger.ledger import post as ledger_post
        with SessionLocal() as db:
            team = Team(league_id=LEAGUE_ID, team_name=f"LOG1 {name}", owner=name,
                        email=f"{name}@log1test.com")
            db.add(team)
            db.flush()
            for i in range(9):
                p = Player(name=f"{name}-P{i}", position="WR", nfl_team=nfl_team)
                db.add(p)
                db.flush()
                db.add(Roster(team_id=team.id, player_id=p.id))
            db.add(Wallet(team_id=team.id, balance=1000.0))
            db.commit()
            tid = team.id
        ledger_post([("world", -_FUND_CENTS), (f"wallet:{tid}", _FUND_CENTS)], door="buy_in_paid")
        return tid

    def _seed_matchup(week, ta, tb, sa, sb, na, nb) -> None:
        with SessionLocal() as db:
            db.add(Matchup(league_id=LEAGUE_ID, week=week, home_team_id=ta, away_team_id=tb,
                           home_score=sa, away_score=sb,
                           # S6 §8 — a COMPLETED week, stated explicitly.
                           finalized_at=_FIXTURE_FINAL_AT))
            db.add(NflSchedule(season=LOCK_SEASON, week=week, home_team=na, away_team=nb,
                               kickoff_utc=FUTURE_KO))
            db.commit()

    def _accept_beef(challenger, challenged, week, amount) -> None:
        with SessionLocal() as db:
            out = issue_challenge(challenger, challenged, week=week, bet_type="straight",
                                  amount=amount, db=db)
            respond_to_challenge(out.challenge_id, accept=True, db=db)

    def _build_two_settled_beefs(week: int) -> None:
        # Two beef pairs in one week; both resolve to a winner (scores differ) so
        # log_settlement_events writes one "challenge_settled" event per pair.
        a = _make_team(f"A{week}", "KC")
        b = _make_team(f"B{week}", "PHI")
        c = _make_team(f"C{week}", "SF")
        d = _make_team(f"D{week}", "DAL")
        _seed_matchup(week, a, b, 150.0, 90.0, "KC", "PHI")
        _seed_matchup(week, c, d, 140.0, 88.0, "SF", "DAL")
        _accept_beef(a, b, week, 10.0)
        _accept_beef(c, d, week, 10.0)

    def _feed_count() -> int:
        # Settlement feed events only. The beef-acceptance fixture also writes
        # 'challenge_issued' / 'challenge_accepted' events; those are not what
        # log_settlement_events produces and must not be counted here.
        with SessionLocal() as db:
            return (db.query(FeedEvent)
                      .filter(FeedEvent.event_type == "challenge_settled")
                      .count())

    def _week_row(week):
        with SessionLocal() as db:
            return db.query(WeekSettlement).filter_by(league_id=LEAGUE_ID, week=week).first()

    def _rendered_records():
        return [r.getMessage() for r in _cap.records if r.levelno >= logging.ERROR]

    # ═══ SCENARIO 1 — success path ═══════════════════════════════════════════
    print("\nSCENARIO 1 — success: feed runs on a separate session; settlement session idle during feed")
    LEAGUE_ID = _reset_and_new_league()
    _build_two_settled_beefs(week=1)

    raised = None
    report = None
    with SessionLocal() as db:
        _SETTLEMENT_SESSION["obj"] = db
        try:
            report = settle_week(1, db, league_id=LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001
            raised = exc
    _SETTLEMENT_SESSION["obj"] = None

    _assert("S1: settle_week raised nothing", raised is None,
            detail=f"{type(raised).__name__}: {raised}" if raised else "")
    _assert("S1: returns a SettlementReport", isinstance(report, SettlementReport),
            detail=f"got {type(report).__name__}")
    _assert("S1: feed block was entered", _FEED_ENTERED["on"] is True)
    _assert("S1 [BINDING]: settlement-session statements during feed == 0",
            _COUNTS["settlement"] == 0, detail=f"got {_COUNTS['settlement']}")
    _assert("S1 [LIVENESS]: feed-session statements during feed > 0",
            _COUNTS["feed"] > 0, detail=f"got {_COUNTS['feed']}")
    _assert("S1: exactly one feed row per settled challenge (2), no duplicates",
            _feed_count() == 2, detail=f"got {_feed_count()}")
    ws1 = _week_row(1)
    _assert("S1: week COMPLETED / settled / settled_at set / token NULL",
            ws1 is not None and ws1.status == "COMPLETED" and ws1.settled is True
            and ws1.settled_at is not None and ws1.recovery_token is None,
            detail=(f"status={getattr(ws1,'status',None)!r} settled={getattr(ws1,'settled',None)} "
                    f"settled_at={getattr(ws1,'settled_at',None)} token={getattr(ws1,'recovery_token',None)!r}"))
    _assert("S1: ledger trial_balance zero", trial_balance() == 0, detail=f"got {trial_balance()}")

    # ═══ SCENARIO 2 — forced mid-batch feed failure ══════════════════════════
    print("\nSCENARIO 2 — forced feed failure: settlement committed, feed rolled back, no misreport")
    LEAGUE_ID = _reset_and_new_league()
    _build_two_settled_beefs(week=1)
    _FORCE_FEED_FAILURE["on"] = True

    raised2 = None
    report2 = None
    with SessionLocal() as db:
        _SETTLEMENT_SESSION["obj"] = db
        try:
            report2 = settle_week(1, db, league_id=LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001
            raised2 = exc
    _SETTLEMENT_SESSION["obj"] = None

    _assert("S2: settle_week raised nothing despite feed failure", raised2 is None,
            detail=f"{type(raised2).__name__}: {raised2}" if raised2 else "")
    _assert("S2: returns a valid SettlementReport", isinstance(report2, SettlementReport),
            detail=f"got {type(report2).__name__}")
    _assert("S2 [BINDING]: settlement-session statements during feed == 0",
            _COUNTS["settlement"] == 0, detail=f"got {_COUNTS['settlement']}")
    _assert("S2 [LIVENESS]: feed-session statements during feed > 0",
            _COUNTS["feed"] > 0, detail=f"got {_COUNTS['feed']}")
    _assert("S2: zero feed_events rows after the mid-batch failure",
            _feed_count() == 0, detail=f"got {_feed_count()}")
    ws2 = _week_row(1)
    _assert("S2: week still COMPLETED / settled / settled_at set / token NULL",
            ws2 is not None and ws2.status == "COMPLETED" and ws2.settled is True
            and ws2.settled_at is not None and ws2.recovery_token is None,
            detail=(f"status={getattr(ws2,'status',None)!r} settled={getattr(ws2,'settled',None)} "
                    f"settled_at={getattr(ws2,'settled_at',None)} token={getattr(ws2,'recovery_token',None)!r}"))
    _assert("S2: ledger trial_balance zero", trial_balance() == 0, detail=f"got {trial_balance()}")
    _errs = _rendered_records()
    _assert("S2: exactly one ERROR log emitted", len(_errs) == 1, detail=f"got {len(_errs)}: {_errs}")
    _assert("S2: the error log's rendered text names week and league_id",
            len(_errs) == 1 and "1" in _errs[0] and str(LEAGUE_ID) in _errs[0],
            detail=f"rendered={_errs[0]!r}" if _errs else "no record")

    # ═══ SCENARIO 3 — empty week never enters the feed block ══════════════════
    print("\nSCENARIO 3 — empty week: no settled challenges, feed block never entered, no feed rows")
    LEAGUE_ID = _reset_and_new_league()

    raised3 = None
    report3 = None
    with SessionLocal() as db:
        _SETTLEMENT_SESSION["obj"] = db
        try:
            report3 = settle_week(1, db, league_id=LEAGUE_ID)
        except Exception as exc:  # noqa: BLE001
            raised3 = exc
    _SETTLEMENT_SESSION["obj"] = None

    _assert("S3: settle_week raised nothing", raised3 is None,
            detail=f"{type(raised3).__name__}: {raised3}" if raised3 else "")
    _assert("S3: returns a SettlementReport", isinstance(report3, SettlementReport),
            detail=f"got {type(report3).__name__}")
    _assert("S3: feed block was NEVER entered on an empty week",
            _FEED_ENTERED["on"] is False, detail=f"_FEED_ENTERED={_FEED_ENTERED['on']}")
    _assert("S3: zero feed_events rows", _feed_count() == 0, detail=f"got {_feed_count()}")
    ws3 = _week_row(1)
    _assert("S3: empty week COMPLETED / settled",
            ws3 is not None and ws3.status == "COMPLETED" and ws3.settled is True,
            detail=f"status={getattr(ws3,'status',None)!r} settled={getattr(ws3,'settled',None)}")


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
    print("RESULT: all FR-8.7-LOG-1 isolation assertions PASSED")
