"""
test_b6_group_d_season_close_pg.py — B6 Package 3 Group D, §15 items 11-13: the
season-close seam (PostgreSQL).

SCOPE FENCE. This suite proves items 11-13 ONLY: the League.season_closed_at
column (§4.6), the is_season_closed() read predicate (§9.1), and the single
protected once-only writer close_season() (§9.2), including the League row lock
§6.4 requires of it.

It does NOT exercise, approximate or stub:
    - S1  creation after close        (needs the Group E service + Group F route)
    - S2  approval racing close       (Group E)
    - S7  rejection after close       (Group E/F)
    - S8  cancellation after close    (Group E/F)
    - AR1-AR4 authority-writer locks  (Group D items 14-17, not this package)
    - routes, migrations, Ledger or Wallet behaviour of any kind.
Nothing here imports economy/top_off.py, which does not exist.

Postgres only. Two of the claims cannot be made anywhere else: the row lock is
SELECT ... FOR UPDATE, which SQLite cannot parse, and the blocking proof reads
pg_blocking_pids() from a third connection. The column-shape assertions read
PostgreSQL's own catalog via inspect().

CONCURRENCY EVIDENCE IS DIRECT, NOT TIMED, following the accepted Group B
technique at test_b6_group_b_topoff_snapshot_pg.py (l1): a third connection asks
PostgreSQL whether the contender's backend is blocked BY the holder's backend.
No sleep is used as proof; the only bounded poll waits for that observable
database condition to appear and fails loudly if it never does.

COMMIT COUNTS ARE MEASURED, NOT INFERRED. Every scenario that claims "exactly
one commit" or "zero commits" attaches an after_commit listener to the very
Session it hands to close_season() and counts the events. A no-op that quietly
committed would otherwise look identical to one that did not.

WHY THE AWARE/NAIVE REPLAY (S9-1) IS NOT A CURIOSITY. season_closed_at is a bare
DateTime, so a value read back from it is naive, while a caller may hold an aware
one. `aware == naive` is False in Python rather than an error, so without
normalisation a lawful equal-timestamp replay would raise
SeasonCloseConflictError — silently, and only in production, where callers carry
aware timestamps. That scenario fails loudly if _normalise() is ever removed.

SCENARIOS:
    D-a    column shape: exists, timestamp, nullable, NULL on a fresh League,
           no CHECK and no index governing it
    D-b    is_season_closed() is a pure predicate: false/true, works detached,
           emits zero SQL
    D-c    first close: closed_now=True, committed value matches the result,
           operator and season preserved, exactly one commit
    S9-1   once-only replay: omitted closed_at, and equal closed_at (naive AND
           aware spellings) -> closed_now=False, zero commits, no mutation
    S9-2   conflicting closed_at -> SeasonCloseConflictError, zero commits,
           stored timestamp unchanged
    S9-3   reopening unavailable: no reopen/clear/reset export, no callable in
           the module assigns None to season_closed_at, and repeated writer
           calls never return the column to NULL
    D-d    row-lock proof: a conflicting uncommitted lock on the League row
           blocks close_season(), observed via pg_blocking_pids() from a third
           connection; it completes once released
    D-e    unknown league -> LeagueNotFoundError, zero commits, no mutation

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — setup_postgres_test_db() applies its guards, sets
# DATABASE_URL to the disposable test DB, and imports+binds db.schema
# INTERNALLY. No project module may be imported before this call.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] B6 Group D season-close suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection
    begins the instant setup succeeds."""
    import inspect as pyinspect
    import re
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import event, inspect, text

    from db.schema import SessionLocal, League
    import config

    import economy.season_close as sc
    from economy.season_close import (
        close_season,
        is_season_closed,
        LeagueNotFoundError,
        SeasonCloseConflictError,
        SeasonCloseResult,
    )

    SEASON   = config.ALLOCATION_SEASON
    OPERATOR = "operator:fraser"

    # ── helpers ───────────────────────────────────────────────────────────

    def seed_league(name: str = "Group D League") -> int:
        """One committed League row, season open (season_closed_at NULL)."""
        with SessionLocal() as db:
            lg = League(season=SEASON, name=name)
            db.add(lg)
            db.commit()
            return lg.id

    def close_once(league_id: int, operator: str = OPERATOR, **kw):
        """close_season() against its own short-lived session, for the setup
        steps whose commit count is not the thing under test."""
        with SessionLocal() as db:
            return close_season(league_id, operator, db=db, **kw)

    def stored_close(league_id: int):
        """season_closed_at as COMMITTED, read in its own session so the value
        can never be a writer's uncommitted state."""
        with SessionLocal() as db:
            return db.execute(
                text("SELECT season_closed_at FROM leagues WHERE id = :i"),
                {"i": league_id},
            ).scalar()

    class CommitCounter:
        """Counts real commits on ONE Session. after_commit fires per commit,
        so a no-op path that quietly committed cannot hide behind an unchanged
        row value."""

        def __init__(self, session):
            self.count = 0
            self._session = session
            event.listen(session, "after_commit", self._bump)

        def _bump(self, session):
            self.count += 1

        def stop(self):
            event.remove(self._session, "after_commit", self._bump)

    # ── D-a — column shape ────────────────────────────────────────────────
    print("\nD-a  column shape: leagues.season_closed_at (§4.6)")
    tdb.reset()
    insp = inspect(tdb.engine)
    cols = {c["name"]: c for c in insp.get_columns("leagues")}

    _assert("D-a leagues.season_closed_at exists",
            "season_closed_at" in cols, str(sorted(cols)))

    if "season_closed_at" in cols:
        col = cols["season_closed_at"]
        _assert("D-a it is a timestamp type",
                "TIMESTAMP" in str(col["type"]).upper(), str(col["type"]))
        # §4.6 — nullable BY DESIGN: NULL is the open season, so a NOT NULL here
        # would make "open" unrepresentable.
        _assert("D-a it is NULLABLE", col["nullable"] is True, str(col["nullable"]))
        _assert("D-a it carries no server default",
                col.get("default") is None, str(col.get("default")))
        _assert("D-a it is not a timezone-aware type (bare DateTime, B6 family)",
                "WITH TIME ZONE" not in str(col["type"]).upper(), str(col["type"]))

    # §4.6 specifies a bare nullable DateTime — no CHECK, no index. The Group B
    # CHECK on the multiplier must still be there; only this column is fenced.
    checks = insp.get_check_constraints("leagues")
    governing = [c for c in checks if "season_closed_at" in (c.get("sqltext") or "")]
    _assert("D-a NO check constraint governs season_closed_at",
            governing == [], str(governing))
    _assert("D-a the Group B multiplier CHECK is still present (not disturbed)",
            any(c.get("name") == "ck_leagues_topoff_multiplier_bps" for c in checks),
            str([c.get("name") for c in checks]))

    idx_on_col = [ix for ix in insp.get_indexes("leagues")
                  if "season_closed_at" in (ix.get("column_names") or [])]
    _assert("D-a NO index covers season_closed_at",
            idx_on_col == [], str(idx_on_col))

    lg_fresh = seed_league("fresh")
    _assert("D-a a freshly inserted League stores NULL",
            stored_close(lg_fresh) is None, repr(stored_close(lg_fresh)))

    # ── D-b — pure predicate ──────────────────────────────────────────────
    print("\nD-b  is_season_closed() is a pure predicate (§9.1)")
    tdb.reset()
    lg_b = seed_league("predicate")

    with SessionLocal() as db:
        obj_open = db.query(League).filter(League.id == lg_b).one()
        _assert("D-b fresh (NULL) League -> False",
                is_season_closed(obj_open) is False, repr(obj_open.season_closed_at))
        # Detach with attributes still loaded: the predicate must answer from
        # the instance alone, never by lazy-loading from a live session.
        db.expunge(obj_open)

    _assert("D-b it answers on a DETACHED instance (no session, no lazy load)",
            is_season_closed(obj_open) is False, "detached open league")

    close_once(lg_b)
    with SessionLocal() as db:
        obj_closed = db.query(League).filter(League.id == lg_b).one()
        db.expunge(obj_closed)

    _assert("D-b closed League -> True", is_season_closed(obj_closed) is True,
            repr(obj_closed.season_closed_at))
    _assert("D-b it answers on a DETACHED CLOSED instance",
            is_season_closed(obj_closed) is True, "detached closed league")

    # Zero SQL: count every statement the engine executes across the calls.
    # A predicate that queried — or that lazy-loaded — would register here.
    stmts: list[str] = []

    def _record(conn, cursor, statement, params, ctx, many):
        stmts.append(statement)

    event.listen(tdb.engine, "before_cursor_execute", _record)
    try:
        is_season_closed(obj_open)
        is_season_closed(obj_closed)
    finally:
        event.remove(tdb.engine, "before_cursor_execute", _record)

    _assert("D-b the predicate emitted ZERO SQL statements",
            stmts == [], f"{len(stmts)} statement(s): {stmts}")

    # ── D-c — first close ─────────────────────────────────────────────────
    print("\nD-c  first close writes once and commits once (§9.2)")
    tdb.reset()
    lg_c = seed_league("first close")
    before_c = stored_close(lg_c)

    with SessionLocal() as db:
        counter = CommitCounter(db)
        res_c = close_season(lg_c, OPERATOR, db=db)
        counter.stop()

    _assert("D-c the season was OPEN before the call", before_c is None, repr(before_c))
    _assert("D-c returns a SeasonCloseResult",
            isinstance(res_c, SeasonCloseResult), type(res_c).__name__)
    _assert("D-c closed_now is True", res_c.closed_now is True, str(res_c.closed_now))
    _assert("D-c the returned timestamp is non-NULL",
            res_c.closed_at is not None, repr(res_c.closed_at))
    _assert("D-c the returned timestamp EQUALS the committed database value",
            res_c.closed_at == stored_close(lg_c),
            f"result={res_c.closed_at!r} db={stored_close(lg_c)!r}")
    _assert("D-c operator identity is preserved in the result",
            res_c.operator == OPERATOR, repr(res_c.operator))
    _assert("D-c season is config.ALLOCATION_SEASON",
            res_c.season == SEASON, f"{res_c.season} vs {SEASON}")
    _assert("D-c league_id is preserved", res_c.league_id == lg_c, str(res_c.league_id))
    _assert("D-c EXACTLY ONE commit occurred", counter.count == 1, str(counter.count))
    _assert("D-c the result is immutable (frozen dataclass)",
            _raises_on_mutation(res_c), "expected FrozenInstanceError")

    with SessionLocal() as db:
        obj_c = db.query(League).filter(League.id == lg_c).one()
        _assert("D-c is_season_closed() is True afterwards",
                is_season_closed(obj_c) is True, repr(obj_c.season_closed_at))

    # Supplying an explicit timestamp on the OPEN path stores exactly that value.
    lg_c2 = seed_league("first close explicit")
    explicit = datetime(2026, 2, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)
    with SessionLocal() as db:
        counter2 = CommitCounter(db)
        res_c2 = close_season(lg_c2, OPERATOR, db=db, closed_at=explicit)
        counter2.stop()
    _assert("D-c an explicit closed_at is stored EXACTLY (microseconds intact)",
            stored_close(lg_c2) == explicit.replace(tzinfo=None),
            f"db={stored_close(lg_c2)!r}")
    _assert("D-c the explicit-timestamp close also commits exactly once",
            counter2.count == 1, str(counter2.count))
    _assert("D-c the explicit-timestamp close reports closed_now=True",
            res_c2.closed_now is True, str(res_c2.closed_now))

    # ── S9-1 — once-only replay ───────────────────────────────────────────
    print("\nS9-1  once-only replay: no-op, zero commits, no mutation (§9.2)")
    tdb.reset()
    lg_s1 = seed_league("replay")
    first = close_once(lg_s1)
    stamped = stored_close(lg_s1)

    # (i) closed_at OMITTED.
    with SessionLocal() as db:
        c1 = CommitCounter(db)
        rep1 = close_season(lg_s1, "operator:someone-else", db=db)
        c1.stop()

    _assert("S9-1 (omitted) returns the STORED timestamp",
            rep1.closed_at == stamped, f"{rep1.closed_at!r} vs {stamped!r}")
    _assert("S9-1 (omitted) closed_now is False", rep1.closed_now is False,
            str(rep1.closed_now))
    _assert("S9-1 (omitted) ZERO commits occurred", c1.count == 0, str(c1.count))
    _assert("S9-1 (omitted) the stored timestamp is UNCHANGED",
            stored_close(lg_s1) == stamped, repr(stored_close(lg_s1)))

    # (ii) closed_at EQUAL to the stored value, naive spelling.
    with SessionLocal() as db:
        c2 = CommitCounter(db)
        rep2 = close_season(lg_s1, OPERATOR, db=db, closed_at=stamped)
        c2.stop()

    _assert("S9-1 (equal, naive) succeeds as a no-op",
            rep2.closed_now is False and rep2.closed_at == stamped,
            f"closed_now={rep2.closed_now} at={rep2.closed_at!r}")
    _assert("S9-1 (equal, naive) ZERO commits occurred", c2.count == 0, str(c2.count))
    _assert("S9-1 (equal, naive) the stored timestamp is UNCHANGED",
            stored_close(lg_s1) == stamped, repr(stored_close(lg_s1)))

    # (iii) closed_at EQUAL but AWARE — the same instant, spelled the way a real
    # caller holds it. Without _normalise() this raises SeasonCloseConflictError.
    aware_equal = stamped.replace(tzinfo=timezone.utc)
    with SessionLocal() as db:
        c3 = CommitCounter(db)
        try:
            rep3 = close_season(lg_s1, OPERATOR, db=db, closed_at=aware_equal)
            aware_exc = None
        except Exception as e:            # noqa: BLE001 — recording
            rep3, aware_exc = None, e
        c3.stop()

    _assert("S9-1 (equal, AWARE) is treated as the SAME instant, not a conflict",
            aware_exc is None, f"{type(aware_exc).__name__}: {aware_exc}")
    _assert("S9-1 (equal, AWARE) succeeds as a no-op",
            rep3 is not None and rep3.closed_now is False and rep3.closed_at == stamped,
            repr(rep3))
    _assert("S9-1 (equal, AWARE) ZERO commits occurred", c3.count == 0, str(c3.count))
    _assert("S9-1 (equal, AWARE) the stored timestamp is UNCHANGED",
            stored_close(lg_s1) == stamped, repr(stored_close(lg_s1)))
    _assert("S9-1 the first call had reported closed_now=True",
            first.closed_now is True, str(first.closed_now))
    _assert("S9-1 the replay echoes the CALLER's operator, not the original",
            rep1.operator == "operator:someone-else", repr(rep1.operator))

    # ── S9-2 — conflicting timestamp ──────────────────────────────────────
    print("\nS9-2  a DIFFERENT closed_at is refused (§9.2 once-only)")
    tdb.reset()
    lg_s2 = seed_league("conflict")
    close_once(lg_s2)
    stamped2 = stored_close(lg_s2)
    different = stamped2 + timedelta(seconds=1)

    with SessionLocal() as db:
        c4 = CommitCounter(db)
        try:
            close_season(lg_s2, OPERATOR, db=db, closed_at=different)
            conflict_exc = None
        except Exception as e:            # noqa: BLE001 — recording
            conflict_exc = e
        c4.stop()

    _assert("S9-2 raises SeasonCloseConflictError (asserted by TYPE)",
            isinstance(conflict_exc, SeasonCloseConflictError),
            f"got {type(conflict_exc).__name__}: {conflict_exc}")
    _assert("S9-2 ZERO commits occurred", c4.count == 0, str(c4.count))
    _assert("S9-2 the stored timestamp is UNCHANGED",
            stored_close(lg_s2) == stamped2,
            f"db={stored_close(lg_s2)!r} expected={stamped2!r}")

    # An EARLIER differing timestamp is refused too — the refusal is not
    # "refuse to move it forward", it is "refuse to move it at all".
    with SessionLocal() as db:
        c5 = CommitCounter(db)
        try:
            close_season(lg_s2, OPERATOR, db=db,
                         closed_at=stamped2 - timedelta(days=1))
            earlier_exc = None
        except Exception as e:            # noqa: BLE001 — recording
            earlier_exc = e
        c5.stop()

    _assert("S9-2 an EARLIER differing timestamp is refused as well",
            isinstance(earlier_exc, SeasonCloseConflictError),
            f"got {type(earlier_exc).__name__}")
    _assert("S9-2 (earlier) ZERO commits, timestamp UNCHANGED",
            c5.count == 0 and stored_close(lg_s2) == stamped2,
            f"commits={c5.count} db={stored_close(lg_s2)!r}")

    # ── S9-3 — reopening unavailable ──────────────────────────────────────
    print("\nS9-3  reopening is unavailable (invariant 33)")
    # Narrow: this module only. Whether api/main.py stayed clean is a diff-gate
    # question, not a PostgreSQL one, and is deliberately not audited here.
    exported = [n for n in dir(sc) if not n.startswith("_")]
    banned = [n for n in exported
              if re.search(r"reopen|unclose|clear|reset|undo|delete", n, re.I)]
    _assert("S9-3 the module exports NO reopen/clear/reset-style name",
            banned == [], str(banned))

    src = pyinspect.getsource(sc)
    # Any assignment returning the column to NULL, in any callable, in any
    # spelling the module could plausibly use.
    null_writes = re.findall(
        r"season_closed_at\s*=\s*(?:None|null\(\))", src, re.I)
    _assert("S9-3 NO callable in the module assigns None to season_closed_at",
            null_writes == [], str(null_writes))
    # The single legitimate assignment must still be there, so the check above
    # cannot pass merely because the writer stopped writing.
    _assert("S9-3 exactly ONE assignment to the column exists (the writer's)",
            len(re.findall(r"\.season_closed_at\s*=(?!=)", src)) == 1,
            str(re.findall(r"\.season_closed_at\s*=(?!=)", src)))

    # Behavioural: hammering the writer never returns the column to NULL.
    tdb.reset()
    lg_s3 = seed_league("no reopen")
    close_once(lg_s3)
    stamped3 = stored_close(lg_s3)
    for _ in range(3):
        close_once(lg_s3)
    _assert("S9-3 repeated writer calls never return the column to NULL",
            stored_close(lg_s3) == stamped3 and stored_close(lg_s3) is not None,
            repr(stored_close(lg_s3)))

    # ── D-d — row-lock proof ──────────────────────────────────────────────
    # Direct evidence, not timing: a third connection asks PostgreSQL whether
    # the contender is blocked BY the holder. The holder takes FOR NO KEY
    # UPDATE — the mode activate_season_allocation() uses — so this also shows
    # the close serializes against an in-flight activation, per §6.4's matrix.
    print("\nD-d  close_season() BLOCKS on the League row lock (§6.4), "
          "observed via pg_blocking_pids()")
    tdb.reset()
    lg_d = seed_league("lock")

    holder_ready = threading.Event()
    release      = threading.Event()
    obs: dict = {}

    def holder():
        with SessionLocal() as dba:
            obs["holder_pid"] = dba.execute(text("SELECT pg_backend_pid()")).scalar()
            dba.execute(
                text("SELECT id FROM leagues WHERE id = :i FOR NO KEY UPDATE"),
                {"i": lg_d},
            ).fetchall()
            holder_ready.set()
            release.wait(timeout=30)
            dba.rollback()      # the holder writes nothing; it only holds the lock

    def contender():
        holder_ready.wait(timeout=30)
        with SessionLocal() as dbb:
            try:
                obs["result"] = close_season(lg_d, OPERATOR, db=dbb)
            except Exception as e:        # noqa: BLE001 — recording
                obs["exc"] = e

    th_h = threading.Thread(target=holder)
    th_c = threading.Thread(target=contender)
    th_h.start()
    th_c.start()
    holder_ready.wait(timeout=30)

    # Bounded poll on an OBSERVABLE DATABASE CONDITION, not on the clock. Each
    # iteration is a real round trip, so the loop paces itself with no sleep.
    # The deadline is a FAILURE BOUND, not evidence.
    blocked = None
    deadline = time.monotonic() + 30.0
    with SessionLocal() as probe:
        while time.monotonic() < deadline:
            row = probe.execute(text("""
                SELECT pid, wait_event_type, query
                FROM pg_stat_activity
                WHERE pid <> pg_backend_pid()
                  AND :holder = ANY(pg_blocking_pids(pid))
            """), {"holder": obs.get("holder_pid")}).fetchone()
            probe.rollback()    # end the probe's snapshot so the next read is fresh
            if row is not None:
                blocked = row
                break

    _assert("D-d the closer's backend was observed BLOCKED BY the holder's backend",
            blocked is not None,
            f"holder pid={obs.get('holder_pid')} blocked pid="
            f"{blocked[0] if blocked else 'NONE OBSERVED'}")
    if blocked is not None:
        _assert("D-d PostgreSQL reports the wait as a Lock wait",
                blocked[1] == "Lock", f"wait_event_type={blocked[1]}")
        q = (blocked[2] or "").lower()
        _assert("D-d the blocked statement is the LEAGUES row lock",
                "leagues" in q and "for update" in q, f"blocked query={blocked[2]!r}")
        # §6.4 assigns FOR UPDATE to this writer; key_share would be a downgrade.
        _assert("D-d the closer's lock mode is FOR UPDATE, not FOR NO KEY UPDATE",
                "no key" not in q, f"blocked query={blocked[2]!r}")
        _assert("D-d the season was still OPEN while the closer was blocked",
                stored_close(lg_d) is None, repr(stored_close(lg_d)))

    release.set()
    th_h.join(timeout=30)
    th_c.join(timeout=30)

    _assert("D-d once unblocked, the close completed with NO exception",
            "exc" not in obs, f"got {type(obs.get('exc')).__name__}: {obs.get('exc')}")
    _assert("D-d it then closed the season",
            obs.get("result") is not None and obs["result"].closed_now is True,
            str(obs.get("result")))
    _assert("D-d the stored timestamp matches what the unblocked call returned",
            obs.get("result") is not None
            and stored_close(lg_d) == obs["result"].closed_at,
            f"db={stored_close(lg_d)!r}")

    # ── D-e — unknown league ──────────────────────────────────────────────
    print("\nD-e  an unknown league_id is refused (§9.2)")
    tdb.reset()
    lg_e = seed_league("bystander")
    missing_id = lg_e + 10_000

    with SessionLocal() as db:
        c6 = CommitCounter(db)
        try:
            close_season(missing_id, OPERATOR, db=db)
            missing_exc = None
        except Exception as e:            # noqa: BLE001 — recording
            missing_exc = e
        c6.stop()

    _assert("D-e raises LeagueNotFoundError (asserted by TYPE)",
            isinstance(missing_exc, LeagueNotFoundError),
            f"got {type(missing_exc).__name__}: {missing_exc}")
    _assert("D-e ZERO commits occurred", c6.count == 0, str(c6.count))
    _assert("D-e no League row was created by the failed call",
            stored_close(missing_id) is None
            and _league_count(SessionLocal) == 1,
            f"leagues={_league_count(SessionLocal)}")
    _assert("D-e the bystander league is untouched (still open)",
            stored_close(lg_e) is None, repr(stored_close(lg_e)))
    # Both refusals share one base type, so a caller may catch either narrowly
    # or both together.
    _assert("D-e LeagueNotFoundError is a SeasonCloseError",
            isinstance(missing_exc, sc.SeasonCloseError), type(missing_exc).__name__)


def _raises_on_mutation(result) -> bool:
    """True when the frozen dataclass refuses attribute assignment."""
    try:
        result.closed_now = False
    except Exception:                     # noqa: BLE001 — FrozenInstanceError
        return True
    return False


def _league_count(session_factory) -> int:
    from sqlalchemy import text as _text
    with session_factory() as db:
        return db.execute(_text("SELECT COUNT(*) FROM leagues")).scalar()


try:
    main(tdb)
finally:
    tdb.teardown()

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("All assertions PASSED")