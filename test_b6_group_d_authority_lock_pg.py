"""
test_b6_group_d_authority_lock_pg.py — B6 Package 3 Group D, §15 items 14-16:
the authority-writer League row lock (PostgreSQL).

SCOPE FENCE. This suite proves items 14-16 ONLY:

    14. commissioner GENESIS (scripts/bootstrap_league_commissioner.py) takes
        the League row FOR UPDATE before it touches league_commissioners. The
        writer is UNCHANGED by this package — the claim is proved against the
        code that was already there.
    15. the commissioner GRANT route (POST /league/{league_id}/commissioners)
        takes the same League row FOR UPDATE as the first database statement of
        its handler body, releases it on every refusal, and commits exactly once
        on success.
    16. NO production commissioner revoke/remove writer exists, and none is
        introduced here. The requirement is prospective; what is testable today
        is the absence, and G-j states plainly how narrowly it is established.

It does NOT exercise, approximate or stub:
    - item 17 approval-step-14 League locking          (Group E item 18)
    - AR1-AR4, SA3, P5, approval-vs-close,
      approval-vs-authority                            (Group E item 18)
    - creation/rejection/cancellation after close      (Group E/F)
    - migrations, or any money engine behaviour beyond the narrow
      no-side-effects check in G-k.
Nothing here imports economy/top_off.py, which does not exist.

Postgres only, and not incidentally: the claim under test is a row-lock mode
that SQLite cannot parse, and every blocking proof reads pg_blocking_pids()
from a third connection.

CONCURRENCY EVIDENCE IS DIRECT, NOT TIMED, following the accepted Group B/D
technique (test_b6_group_b_topoff_snapshot_pg.py l1, test_b6_group_d_season_
close_pg.py D-d): a third connection asks PostgreSQL whether the contender's
backend is blocked BY the holder's backend. No sleep is used as proof. The only
bounded polls wait for an observable database condition to appear and fail
loudly if it never does — the deadline is a FAILURE BOUND, never evidence.

LOCK RELEASE IS PROVED DIRECTLY, NOT INFERRED FROM SESSION CLOSE. The route's
Session is supplied by the test through a get_db override that is a PLAIN
CALLABLE, not a generator — so FastAPI never tears it down, and after a refusal
the session is still open while an INDEPENDENT backend takes the same League row
with FOR UPDATE NOWAIT. NOWAIT errors instead of waiting, so "the lock is free"
is a statement PostgreSQL makes, not one a timeout implies.

EVERY OBSERVED SESSION IS PINNED TO ONE BACKEND. A pooled Session hands its
connection back on rollback, so a backend pid read at construction time can
belong to somebody else by the time the statement under test runs. Each session
this suite observes — the probe, the route's, the closer's — is therefore bound
to a Connection the test checked out itself and holds until it closes. The pid
in every assertion below is the pid that actually executed the statement.

A REAL WRITER CAN BE MADE TO HOLD THE LOCK, WITHOUT EDITING IT. LeagueLockPause
freezes one backend immediately AFTER it has executed its own `leagues … FOR
UPDATE`, using a SQLAlchemy cursor event on the test engine. The lock being held
is therefore the one the production writer took itself, in its own transaction.
No production module is modified, monkey-patched or re-implemented. The filter
is the BACKEND PID, not the calling thread: FastAPI runs a sync endpoint in a
worker thread, so the handler does not execute on the thread that called it.

SCENARIOS:
    G-a  grant blocks on a conflicting League lock, then completes correctly
    G-b  genesis blocks on a conflicting League lock, then completes correctly
    G-c  genesis and grant serialize against each other on one League row
    G-d  a grant on another League is not blocked at all — cross-League
         independence, confirmed by an EMPTY pg_blocking_pids()
    G-e  grant vs season-close, BOTH interleavings, no deadlock
    G-f  concurrent duplicate grants still yield one 201, one 409, one row
    G-g  concurrent grants of DIFFERENT targets serialize, both succeed
    G-h  every refusal path releases the League row and writes nothing
    G-i  commit discipline measured on the exact session the route used
    G-j  item 16: no production revoke/remove/demote authority writer
    G-k  a grant touches no money surface
    G-l  the mode is FOR UPDATE, not FOR NO KEY UPDATE — proved by PostgreSQL's
         own conflict matrix, not by reading the Python source

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
    print(f"\n[HARNESS ERROR] B6 Group D authority-lock suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

# Failure bounds. They bound the run; they never stand in for evidence — each
# scenario asserts an OBSERVED database condition. _HOLD_DEADLINE is deliberately
# the larger of the two, so a holder can never self-release while an observation
# is still being attempted and rescue a scenario that should have failed.
_DEADLINE      = 20.0
_HOLD_DEADLINE = 90.0

_failures: list[str] = []
_evidence: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _note(line: str) -> None:
    """Record a piece of PostgreSQL evidence for the end-of-run summary."""
    _evidence.append(line)
    print(f"       · {line}")


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection begins
    the instant setup succeeds."""
    import re
    from pathlib import Path

    from fastapi import HTTPException
    from fastapi.testclient import TestClient
    from sqlalchemy import event, text
    from sqlalchemy.exc import OperationalError

    from db.deps import get_db
    from db.schema import (
        SessionLocal, FaabTransaction, League, LeagueCommissioner, Team,
        TopOffDisclosure, User, Wallet,
    )
    from ledger.ledger import LedgerEntry
    from auth.jwt_auth import get_current_user, hash_password
    from api.main import app
    from economy.season_close import close_season
    from scripts.bootstrap_league_commissioner import (
        bootstrap_first_commissioner, GenesisRefused,
    )

    OPERATOR = "operator:fraser"
    REPO = Path(os.path.dirname(os.path.abspath(__file__)))

    client = TestClient(app)
    _current = {"id": None}

    # ── auth override ─────────────────────────────────────────────────────
    # Faithful to production get_current_user, which filters is_active == 1 and
    # raises 401 otherwise (copied from the accepted genesis/grant suite). It
    # uses its OWN session, so the session handed to the route stays clean and
    # the only pre-handler statement on it is the authorization dependency's
    # unlocked league_commissioners read — exactly the production shape.
    def _as_user(user_id: int) -> None:
        _current["id"] = user_id

        def _override():
            with SessionLocal() as db:
                u = (db.query(User)
                     .filter(User.id == _current["id"], User.is_active == 1)
                     .first())
                if u is None:
                    raise HTTPException(status_code=401,
                                        detail="User not found or inactive")
                return u

        app.dependency_overrides[get_current_user] = _override

    # ── seed helpers ──────────────────────────────────────────────────────

    def _mk_league(name: str) -> int:
        with SessionLocal() as db:
            lg = League(season=2025, name=name, projection_source="fantasypros")
            db.add(lg); db.commit(); return lg.id

    def _mk_team(league_id: int, name: str) -> int:
        with SessionLocal() as db:
            t = Team(league_id=league_id, team_name=name, owner=name,
                     email=f"{name}@gg.test")
            db.add(t); db.commit(); return t.id

    def _mk_user(email: str, role: str = "gm", active: int = 1) -> int:
        with SessionLocal() as db:
            u = User(email=email, hashed_password=hash_password("x"),
                     team_id=None, role=role, is_active=active)
            db.add(u); db.commit(); return u.id

    def _rows(league_id: int):
        with SessionLocal() as db:
            return (db.query(LeagueCommissioner)
                    .filter(LeagueCommissioner.league_id == league_id)
                    .order_by(LeagueCommissioner.id).all())

    def _stored_close(league_id: int):
        with SessionLocal() as db:
            return db.execute(
                text("SELECT season_closed_at FROM leagues WHERE id = :i"),
                {"i": league_id},
            ).scalar()

    # ── the observing connection (C in every scenario) ────────────────────
    # ONE Connection, checked out for the whole run. A Connection keeps its
    # backend across rollback (a pooled Session does not), so the probe can
    # never be handed the connection a writer just released — which would make
    # every "independent session" observation circular. Main thread only.
    probe = tdb.engine.connect()
    probe_pid = probe.execute(text("SELECT pg_backend_pid()")).scalar()
    probe.rollback()

    _BLOCK_SQL = """
        SELECT pid, wait_event_type, state, query
        FROM pg_stat_activity
        WHERE pid = :blocked AND :holder = ANY(pg_blocking_pids(pid))
    """
    _ANY_BLOCK_SQL = """
        SELECT pid, wait_event_type, state, query
        FROM pg_stat_activity
        WHERE pid <> pg_backend_pid()
          AND :holder = ANY(pg_blocking_pids(pid))
    """

    def _poll(sql: str, params: dict):
        """Bounded poll on an OBSERVABLE DATABASE CONDITION. Each iteration is a
        real round trip, so the loop paces itself with no sleep; the rollback
        ends the probe's transaction so the next read sees fresh statistics."""
        end = time.monotonic() + _DEADLINE
        while time.monotonic() < end:
            row = probe.execute(text(sql), params).fetchone()
            probe.rollback()
            if row is not None:
                return row
        return None

    def _blocked_by(blocked_pid: int, holder_pid: int):
        """PostgreSQL's own answer to 'is backend X waiting on a lock held by
        backend Y', for a contender whose pid is known up front."""
        return _poll(_BLOCK_SQL, {"blocked": blocked_pid, "holder": holder_pid})

    def _any_blocked_by(holder_pid: int):
        """Same question, when the contender opens its own session internally
        (genesis) and its pid cannot be known in advance."""
        return _poll(_ANY_BLOCK_SQL, {"holder": holder_pid})

    def _blockers_of(pid: int) -> list:
        got = probe.execute(text("SELECT pg_blocking_pids(:p)"), {"p": pid}).scalar()
        probe.rollback()
        return list(got or [])

    def _can_lock_now(league_id: int, mode: str = "FOR UPDATE") -> bool:
        """True when this INDEPENDENT probe backend can take the League row in
        `mode` right now. NOWAIT raises rather than waiting, so the answer is a
        direct statement about lock availability at this instant — never a
        timeout standing in for one. `mode` is a test-owned literal."""
        try:
            probe.execute(
                text(f"SELECT id FROM leagues WHERE id = :i {mode} NOWAIT"),
                {"i": league_id},
            ).fetchall()
            return True
        except OperationalError:
            return False
        finally:
            probe.rollback()

    def _lock_evidence(tag: str, holder_pid, blocked_row) -> None:
        if blocked_row is None:
            _note(f"{tag}: holder pid={holder_pid} blocked pid=NONE OBSERVED")
            return
        _note(f"{tag}: holder pid={holder_pid} blocked pid={blocked_row[0]} "
              f"wait={blocked_row[1]} state={blocked_row[2]!r}")
        _note(f"{tag}: blocked statement = {' '.join((blocked_row[3] or '').split())[:120]}")

    def _assert_league_row_wait(tag: str, row) -> None:
        """The three claims every blocking scenario makes about the wait."""
        _assert(f"{tag} PostgreSQL reports the wait as a Lock wait",
                row is not None and row[1] == "Lock",
                f"wait_event_type={None if row is None else row[1]}")
        q = (row[3] or "").lower() if row is not None else ""
        _assert(f"{tag} the blocked statement is the LEAGUES row lock",
                "leagues" in q and "for update" in q, f"blocked query={q[:120]!r}")

    # ── connection A: holds one League row, writes nothing ────────────────

    class RowLockHolder:
        """Connection A. Takes one League row in a chosen mode and holds it,
        uncommitted, until released. It writes nothing — it exists only to
        contend, so anything that blocks on it blocks on the League row and on
        nothing else."""

        def __init__(self, league_id: int, mode: str = "FOR UPDATE"):
            self.league_id = league_id
            self.mode = mode
            self.pid = None
            self.error = None
            self.ready = threading.Event()
            self.release = threading.Event()
            self.thread = threading.Thread(target=self._run, daemon=True)

        def _run(self):
            try:
                # A Connection, not a pooled Session: the transaction stays on
                # one backend for the whole hold, so self.pid remains the pid
                # that actually holds the row.
                with tdb.engine.connect() as conn:
                    self.pid = conn.execute(text("SELECT pg_backend_pid()")).scalar()
                    conn.execute(
                        text(f"SELECT id FROM leagues WHERE id = :i {self.mode}"),
                        {"i": self.league_id},
                    ).fetchall()
                    self.ready.set()
                    self.release.wait(timeout=_HOLD_DEADLINE)
                    conn.rollback()
            except Exception as exc:              # noqa: BLE001 — recording
                self.error = exc
                self.ready.set()

        def start(self):
            self.thread.start()
            self.ready.wait(timeout=_DEADLINE)
            return self

        def stop(self):
            self.release.set()
            self.thread.join(timeout=_DEADLINE)

    # ── freezing a REAL writer while it holds its own lock ────────────────

    class LeagueLockPause:
        """Freezes ONE backend the instant it has executed a `leagues … FOR
        UPDATE`, so a production writer can be observed HOLDING the row lock it
        took itself.

        The pause is a SQLAlchemy cursor event on the TEST engine, firing AFTER
        the statement completed — the lock is genuinely held, inside the
        writer's own transaction, for exactly as long as the scenario needs. No
        production module is edited or patched.

        SELECTION IS BY BACKEND PID when `match_pid` is given, because FastAPI
        runs a sync endpoint in a worker thread: the handler does NOT execute on
        the thread that called the client, so a thread filter would never match
        a route. arm() is the thread-based alternative, used only for writers
        this suite calls directly (genesis, close_season).
        """

        def __init__(self, match_pid: int | None = None):
            self.match_pid = match_pid
            self.thread_ident = None
            self.pid = None
            self.held = threading.Event()
            self.release = threading.Event()

        def arm(self) -> None:
            """Call from INSIDE the thread whose lock should be frozen. Only for
            writers invoked directly, never for a route."""
            self.thread_ident = threading.get_ident()

        def install(self):
            event.listen(tdb.engine, "after_cursor_execute", self._hook)
            return self

        def uninstall(self) -> None:
            event.remove(tdb.engine, "after_cursor_execute", self._hook)

        def _hook(self, conn, cursor, statement, parameters, context, executemany):
            if self.held.is_set():
                return
            s = statement.lower()
            # "league_commissioners" does not contain "leagues", so the
            # authorization dependency's read cannot trip this.
            if "leagues" not in s or "for update" not in s:
                return
            raw = getattr(conn.connection, "dbapi_connection", conn.connection)
            pid = raw.get_backend_pid()
            if self.match_pid is not None:
                if pid != self.match_pid:
                    return
            elif self.thread_ident != threading.get_ident():
                return
            self.pid = pid
            self.held.set()
            self.release.wait(timeout=_HOLD_DEADLINE)

    # ── the session the route actually used ───────────────────────────────

    class RouteSession:
        """One Session the TEST owns, handed to the route through a get_db
        override that is a PLAIN CALLABLE rather than a generator.

        Two things follow, and both are load-bearing:

          * FastAPI caches one value per dependency per request, so the
            authorization dependency and the handler share exactly this
            session — the production shape;
          * FastAPI never runs a teardown for it, so after the response the
            session is STILL OPEN. Lock release and commit count can therefore
            be read off the very session the handler used, instead of being
            inferred from the session having been closed.

        The session is bound to a Connection the test checked out, so it keeps
        ONE backend for its whole life and `pid` is always the backend that ran
        the handler's statements. The pg_backend_pid() read is the TEST's, taken
        before the route runs and rolled back immediately, so the route is
        handed an idle session.
        """

        def __init__(self):
            self.conn = tdb.engine.connect()
            self.pid = self.conn.execute(text("SELECT pg_backend_pid()")).scalar()
            self.conn.rollback()
            self.db = SessionLocal(bind=self.conn)
            self.commits = 0
            event.listen(self.db, "after_commit", self._bump)

        def _bump(self, session):
            self.commits += 1

        def install(self):
            app.dependency_overrides[get_db] = lambda: self.db
            return self

        def uninstall(self):
            app.dependency_overrides.pop(get_db, None)

        def post(self, league_id: int, target_id: int, keep: bool = False):
            """`keep=True` leaves the override installed after the call starts,
            for scenarios that must uninstall it from the main thread once this
            request has already been handed its session — otherwise a second,
            overlapping request would be handed the same session."""
            self.install()
            try:
                return client.post(f"/league/{league_id}/commissioners",
                                   json={"user_id": target_id})
            finally:
                if not keep:
                    self.uninstall()

        def close(self):
            event.remove(self.db, "after_commit", self._bump)
            self.db.close()
            self.conn.close()

    def _plain_grant(league_id: int, target_id: int):
        """A grant through the ordinary request path — its own get_db session,
        no instrumentation. Used wherever two route calls overlap, since the
        override that RouteSession installs is process-global."""
        return client.post(f"/league/{league_id}/commissioners",
                           json={"user_id": target_id})

    # ══════════════════════════════════════════════════════════════════════
    # G-a — the grant takes the League row FOR UPDATE
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-a  the grant route BLOCKS on a conflicting League row lock "
          "(§6.4, item 15)")
    tdb.reset()
    lg_a     = _mk_league("G-a league")
    caller_a = _mk_user("ga_caller@gg.test")
    target_a = _mk_user("ga_target@gg.test")
    bootstrap_first_commissioner(lg_a, caller_a)
    _as_user(caller_a)

    holder_a = RowLockHolder(lg_a).start()
    _assert("G-a connection A holds the League row uncommitted",
            holder_a.error is None and holder_a.pid is not None,
            f"error={holder_a.error}")

    rs_a  = RouteSession()
    out_a: dict = {}

    def _grant_a():
        try:
            out_a["resp"] = rs_a.post(lg_a, target_a)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_a["exc"] = exc

    th_a = threading.Thread(target=_grant_a, daemon=True)
    th_a.start()

    blocked_a = _blocked_by(rs_a.pid, holder_a.pid)
    _lock_evidence("G-a", holder_a.pid, blocked_a)

    _assert("G-a the grant's backend is BLOCKED BY connection A's backend",
            blocked_a is not None,
            f"holder pid={holder_a.pid} grant pid={rs_a.pid}")
    _assert_league_row_wait("G-a", blocked_a)
    _assert("G-a the blocked backend is the grant's own session",
            blocked_a is not None and blocked_a[0] == rs_a.pid,
            f"observed={None if blocked_a is None else blocked_a[0]} expected={rs_a.pid}")
    _assert("G-a NOTHING was inserted while the grant was blocked",
            len(_rows(lg_a)) == 1, f"{len(_rows(lg_a))} authority row(s)")

    holder_a.stop()
    th_a.join(timeout=_DEADLINE)

    _assert("G-a once A released, the grant completed with no exception",
            "exc" not in out_a, f"{type(out_a.get('exc')).__name__}: {out_a.get('exc')}")
    _assert("G-a the grant returned 201",
            out_a.get("resp") is not None and out_a["resp"].status_code == 201,
            f"got {getattr(out_a.get('resp'), 'status_code', None)}: "
            f"{getattr(out_a.get('resp'), 'text', '')[:90]}")
    rows_a = _rows(lg_a)
    _assert("G-a the final state is exactly the intended commissioner set",
            [(r.user_id, r.source) for r in rows_a]
            == [(caller_a, "bootstrap"), (target_a, "local_grant")],
            str([(r.user_id, r.source) for r in rows_a]))
    _assert("G-a provenance names the granting caller",
            len(rows_a) == 2 and rows_a[1].assigned_by_user_id == caller_a,
            str([r.assigned_by_user_id for r in rows_a]))
    _assert("G-a the grant committed EXACTLY ONCE on its own session",
            rs_a.commits == 1, str(rs_a.commits))
    rs_a.close()

    # ══════════════════════════════════════════════════════════════════════
    # G-l — the mode is FOR UPDATE, not FOR NO KEY UPDATE
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-l  the lock mode is FOR UPDATE, proved by PostgreSQL's conflict "
          "matrix (item 15.1)")
    tdb.reset()
    lg_l     = _mk_league("G-l league")
    caller_l = _mk_user("gl_caller@gg.test")
    target_l = _mk_user("gl_target@gg.test")
    bootstrap_first_commissioner(lg_l, caller_l)
    _as_user(caller_l)

    # FOR KEY SHARE is the discriminating holder: in PostgreSQL's row-lock
    # matrix it conflicts with FOR UPDATE and with NOTHING weaker. So a writer
    # that blocks against it is taking FOR UPDATE, and one taking FOR NO KEY
    # UPDATE (what with_for_update(key_share=True) would render) would sail past.
    holder_l = RowLockHolder(lg_l, mode="FOR KEY SHARE").start()
    _assert("G-l connection A holds the League row FOR KEY SHARE",
            holder_l.error is None, f"error={holder_l.error}")

    ks_vs_nokey = _can_lock_now(lg_l, "FOR NO KEY UPDATE")
    ks_vs_update = _can_lock_now(lg_l, "FOR UPDATE")
    _note(f"G-l control: FOR KEY SHARE held by pid={holder_l.pid}; "
          f"FOR NO KEY UPDATE acquirable={ks_vs_nokey}, FOR UPDATE acquirable={ks_vs_update}")
    _assert("G-l CONTROL: FOR NO KEY UPDATE does NOT conflict with the held "
            "FOR KEY SHARE", ks_vs_nokey is True, str(ks_vs_nokey))
    _assert("G-l CONTROL: FOR UPDATE DOES conflict with the held FOR KEY SHARE",
            ks_vs_update is False, str(ks_vs_update))

    rs_l  = RouteSession()
    out_l: dict = {}

    def _grant_l():
        try:
            out_l["resp"] = rs_l.post(lg_l, target_l)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_l["exc"] = exc

    th_l = threading.Thread(target=_grant_l, daemon=True)
    th_l.start()

    blocked_l = _blocked_by(rs_l.pid, holder_l.pid)
    _lock_evidence("G-l", holder_l.pid, blocked_l)

    _assert("G-l the grant BLOCKS against FOR KEY SHARE — so its mode is "
            "FOR UPDATE, not FOR NO KEY UPDATE",
            blocked_l is not None,
            f"holder pid={holder_l.pid} grant pid={rs_l.pid}")
    _assert_league_row_wait("G-l", blocked_l)
    q_l = (blocked_l[3] or "").lower() if blocked_l is not None else ""
    _assert("G-l the blocked statement itself carries no 'no key' downgrade",
            blocked_l is not None and "no key" not in q_l, f"blocked query={q_l[:120]!r}")

    holder_l.stop()
    th_l.join(timeout=_DEADLINE)
    _assert("G-l the grant then completed (201)",
            out_l.get("resp") is not None and out_l["resp"].status_code == 201,
            f"got {getattr(out_l.get('resp'), 'status_code', None)}")
    rs_l.close()

    # ══════════════════════════════════════════════════════════════════════
    # G-b — genesis lock evidence (item 14, writer UNCHANGED)
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-b  commissioner GENESIS blocks on the League row lock (item 14) "
          "— its writer is not edited by this package")
    tdb.reset()
    lg_b = _mk_league("G-b league")
    u_b  = _mk_user("gb_first@gg.test")

    holder_b = RowLockHolder(lg_b).start()
    out_b: dict = {}

    def _genesis_b():
        try:
            out_b["rec"] = bootstrap_first_commissioner(lg_b, u_b)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_b["exc"] = exc

    th_b = threading.Thread(target=_genesis_b, daemon=True)
    th_b.start()

    blocked_b = _any_blocked_by(holder_b.pid)
    _lock_evidence("G-b", holder_b.pid, blocked_b)

    _assert("G-b genesis's backend is BLOCKED BY connection A's backend",
            blocked_b is not None, f"holder pid={holder_b.pid}")
    _assert_league_row_wait("G-b", blocked_b)
    _assert("G-b no authority row exists while genesis is blocked",
            len(_rows(lg_b)) == 0, f"{len(_rows(lg_b))} row(s)")

    holder_b.stop()
    th_b.join(timeout=_DEADLINE)

    _assert("G-b once A released, genesis succeeded",
            "exc" not in out_b and out_b.get("rec") is not None,
            f"{type(out_b.get('exc')).__name__}: {out_b.get('exc')}")
    rec_b = out_b.get("rec") or {}
    _assert("G-b genesis provenance: source='bootstrap'",
            rec_b.get("source") == "bootstrap", str(rec_b.get("source")))
    _assert("G-b genesis provenance: assigned_by_user_id is NULL",
            rec_b.get("assigned_by_user_id") is None,
            str(rec_b.get("assigned_by_user_id")))
    _assert("G-b exactly one authority row, for the intended user",
            [(r.user_id, r.source) for r in _rows(lg_b)] == [(u_b, "bootstrap")],
            str([(r.user_id, r.source) for r in _rows(lg_b)]))

    # ══════════════════════════════════════════════════════════════════════
    # G-c — genesis vs grant serialization
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-c  genesis and grant SERIALIZE on the same League row")
    tdb.reset()
    lg_c      = _mk_league("G-c league")
    caller_c  = _mk_user("gc_caller@gg.test")
    target_c  = _mk_user("gc_target@gg.test")
    second_c  = _mk_user("gc_second@gg.test")
    bootstrap_first_commissioner(lg_c, caller_c)     # league already has authority
    _as_user(caller_c)

    # Genesis is the holder here. It takes the League lock BEFORE it discovers
    # the league already has authority rows, so it holds a real lock and then
    # refuses — which also exercises a refusing authority writer releasing it.
    pause_c = LeagueLockPause().install()
    out_c: dict = {}

    def _genesis_c():
        pause_c.arm()
        try:
            out_c["rec"] = bootstrap_first_commissioner(lg_c, second_c)
        except GenesisRefused as exc:
            out_c["refused"] = exc
        except Exception as exc:                  # noqa: BLE001 — recording
            out_c["exc"] = exc

    th_c1 = threading.Thread(target=_genesis_c, daemon=True)
    th_c1.start()
    pause_c.held.wait(timeout=_DEADLINE)
    _assert("G-c genesis is holding the League row it locked itself",
            pause_c.held.is_set() and pause_c.pid is not None, str(pause_c.pid))

    rs_c = RouteSession()

    def _grant_c():
        try:
            out_c["resp"] = rs_c.post(lg_c, target_c)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_c["grant_exc"] = exc

    th_c2 = threading.Thread(target=_grant_c, daemon=True)
    th_c2.start()

    blocked_c = _blocked_by(rs_c.pid, pause_c.pid)
    _lock_evidence("G-c", pause_c.pid, blocked_c)

    _assert("G-c the grant is BLOCKED BY the in-flight genesis",
            blocked_c is not None,
            f"genesis pid={pause_c.pid} grant pid={rs_c.pid}")
    _assert_league_row_wait("G-c", blocked_c)
    _assert("G-c no new authority row while the grant waits",
            len(_rows(lg_c)) == 1, f"{len(_rows(lg_c))} row(s)")

    pause_c.release.set()
    th_c1.join(timeout=_DEADLINE)
    th_c2.join(timeout=_DEADLINE)
    pause_c.uninstall()

    _assert("G-c genesis REFUSED (the league already had authority) and "
            "released the row", "refused" in out_c and "exc" not in out_c,
            f"refused={'refused' in out_c} exc={out_c.get('exc')}")
    _assert("G-c the grant then proceeded and returned 201",
            out_c.get("resp") is not None and out_c["resp"].status_code == 201,
            f"got {getattr(out_c.get('resp'), 'status_code', None)}")
    _assert("G-c the final authority state is deterministic and valid",
            [(r.user_id, r.source) for r in _rows(lg_c)]
            == [(caller_c, "bootstrap"), (target_c, "local_grant")],
            str([(r.user_id, r.source) for r in _rows(lg_c)]))
    _assert("G-c the refused genesis wrote nothing for its own target",
            all(r.user_id != second_c for r in _rows(lg_c)),
            str([r.user_id for r in _rows(lg_c)]))
    rs_c.close()

    # ══════════════════════════════════════════════════════════════════════
    # G-d — cross-League independence
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-d  a lock on League X does NOT block a grant in League Y")
    tdb.reset()
    lg_x     = _mk_league("G-d league X")
    lg_y     = _mk_league("G-d league Y")
    caller_y = _mk_user("gd_caller@gg.test")
    target_y = _mk_user("gd_target@gg.test")
    bootstrap_first_commissioner(lg_y, caller_y)
    _as_user(caller_y)

    holder_x = RowLockHolder(lg_x).start()
    rs_d     = RouteSession()
    pause_d  = LeagueLockPause(match_pid=rs_d.pid).install()
    out_d: dict = {}

    def _grant_d():
        try:
            out_d["resp"] = rs_d.post(lg_y, target_y)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_d["exc"] = exc

    th_d = threading.Thread(target=_grant_d, daemon=True)
    th_d.start()
    pause_d.held.wait(timeout=_DEADLINE)

    blockers_d = _blockers_of(rs_d.pid)
    x_locked_during = _can_lock_now(lg_x)
    _note(f"G-d: holder pid={holder_x.pid} on League X; grant pid={rs_d.pid} on "
          f"League Y; pg_blocking_pids(grant)={blockers_d}")

    _assert("G-d the grant REACHED and TOOK League Y's row lock",
            pause_d.held.is_set() and pause_d.pid == rs_d.pid,
            f"paused pid={pause_d.pid} route pid={rs_d.pid}")
    _assert("G-d pg_blocking_pids() for the grant is EMPTY — it is blocked by "
            "nobody", blockers_d == [], str(blockers_d))
    _assert("G-d meanwhile League X really is still locked by A",
            x_locked_during is False, str(x_locked_during))

    pause_d.release.set()
    th_d.join(timeout=_DEADLINE)
    pause_d.uninstall()

    _assert("G-d the grant COMPLETED while League X remained locked",
            out_d.get("resp") is not None and out_d["resp"].status_code == 201,
            f"got {getattr(out_d.get('resp'), 'status_code', None)}")
    _assert("G-d League X was STILL held at that moment",
            _can_lock_now(lg_x) is False)
    _assert("G-d League Y holds exactly the two intended rows",
            [(r.user_id, r.source) for r in _rows(lg_y)]
            == [(caller_y, "bootstrap"), (target_y, "local_grant")],
            str([(r.user_id, r.source) for r in _rows(lg_y)]))
    _assert("G-d League X gained no authority row", len(_rows(lg_x)) == 0,
            f"{len(_rows(lg_x))} row(s)")

    holder_x.stop()
    _assert("G-d once A releases, League X is lockable again",
            _can_lock_now(lg_x) is True)
    rs_d.close()

    # ══════════════════════════════════════════════════════════════════════
    # G-e — grant vs season-close, BOTH interleavings
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-e (i)  GRANT holds the League row, season-close contends")
    tdb.reset()
    lg_e1     = _mk_league("G-e grant-holds")
    caller_e1 = _mk_user("ge1_caller@gg.test")
    target_e1 = _mk_user("ge1_target@gg.test")
    bootstrap_first_commissioner(lg_e1, caller_e1)
    _as_user(caller_e1)

    rs_e1    = RouteSession()
    pause_e1 = LeagueLockPause(match_pid=rs_e1.pid).install()
    out_e1: dict = {}

    def _grant_e1():
        try:
            out_e1["resp"] = rs_e1.post(lg_e1, target_e1)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_e1["grant_exc"] = exc

    th_e1g = threading.Thread(target=_grant_e1, daemon=True)
    th_e1g.start()
    pause_e1.held.wait(timeout=_DEADLINE)
    _assert("G-e(i) the grant is holding the League row",
            pause_e1.held.is_set(), str(pause_e1.pid))

    # The closer's session is built here, bound to a Connection the test holds,
    # so its backend pid is known exactly and cannot change under it.
    # close_season() then runs on it from the contending thread — one thread at
    # a time touches it, which is all a Session requires.
    close_conn1 = tdb.engine.connect()
    close_pid1  = close_conn1.execute(text("SELECT pg_backend_pid()")).scalar()
    close_conn1.rollback()
    close_db1   = SessionLocal(bind=close_conn1)

    def _close_e1():
        try:
            out_e1["close"] = close_season(lg_e1, OPERATOR, db=close_db1)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_e1["close_exc"] = exc

    th_e1c = threading.Thread(target=_close_e1, daemon=True)
    th_e1c.start()

    blocked_e1 = _blocked_by(close_pid1, pause_e1.pid)
    _lock_evidence("G-e(i)", pause_e1.pid, blocked_e1)

    _assert("G-e(i) season-close is BLOCKED BY the in-flight grant",
            blocked_e1 is not None,
            f"grant pid={pause_e1.pid} close pid={close_pid1}")
    _assert_league_row_wait("G-e(i)", blocked_e1)
    _assert("G-e(i) the season is still OPEN while the closer waits",
            _stored_close(lg_e1) is None, repr(_stored_close(lg_e1)))

    pause_e1.release.set()
    th_e1g.join(timeout=_DEADLINE)
    th_e1c.join(timeout=_DEADLINE)
    pause_e1.uninstall()

    _assert("G-e(i) NO deadlock — both writers finished without error",
            "grant_exc" not in out_e1 and "close_exc" not in out_e1,
            f"grant={out_e1.get('grant_exc')} close={out_e1.get('close_exc')}")
    _assert("G-e(i) the grant returned 201",
            out_e1.get("resp") is not None and out_e1["resp"].status_code == 201,
            f"got {getattr(out_e1.get('resp'), 'status_code', None)}")
    _assert("G-e(i) the grant committed exactly once", rs_e1.commits == 1,
            str(rs_e1.commits))
    _assert("G-e(i) the close then closed the season",
            out_e1.get("close") is not None and out_e1["close"].closed_now is True,
            str(out_e1.get("close")))
    _assert("G-e(i) authority state is complete, not partial",
            [(r.user_id, r.source) for r in _rows(lg_e1)]
            == [(caller_e1, "bootstrap"), (target_e1, "local_grant")],
            str([(r.user_id, r.source) for r in _rows(lg_e1)]))
    close_db1.close(); close_conn1.close(); rs_e1.close()

    print("\nG-e (ii) SEASON-CLOSE holds the League row, grant contends")
    tdb.reset()
    lg_e2     = _mk_league("G-e close-holds")
    caller_e2 = _mk_user("ge2_caller@gg.test")
    target_e2 = _mk_user("ge2_target@gg.test")
    bootstrap_first_commissioner(lg_e2, caller_e2)
    _as_user(caller_e2)

    close_conn2 = tdb.engine.connect()
    close_pid2  = close_conn2.execute(text("SELECT pg_backend_pid()")).scalar()
    close_conn2.rollback()
    close_db2   = SessionLocal(bind=close_conn2)
    pause_e2    = LeagueLockPause(match_pid=close_pid2).install()
    out_e2: dict = {}

    def _close_e2():
        try:
            out_e2["close"] = close_season(lg_e2, OPERATOR, db=close_db2)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_e2["close_exc"] = exc

    th_e2c = threading.Thread(target=_close_e2, daemon=True)
    th_e2c.start()
    pause_e2.held.wait(timeout=_DEADLINE)
    _assert("G-e(ii) season-close is holding the League row",
            pause_e2.held.is_set(), str(pause_e2.pid))

    rs_e2 = RouteSession()

    def _grant_e2():
        try:
            out_e2["resp"] = rs_e2.post(lg_e2, target_e2)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_e2["grant_exc"] = exc

    th_e2g = threading.Thread(target=_grant_e2, daemon=True)
    th_e2g.start()

    blocked_e2 = _blocked_by(rs_e2.pid, pause_e2.pid)
    _lock_evidence("G-e(ii)", pause_e2.pid, blocked_e2)

    _assert("G-e(ii) the grant is BLOCKED BY the in-flight season-close",
            blocked_e2 is not None,
            f"close pid={pause_e2.pid} grant pid={rs_e2.pid}")
    _assert_league_row_wait("G-e(ii)", blocked_e2)
    _assert("G-e(ii) no authority row was written while the grant waits",
            len(_rows(lg_e2)) == 1, f"{len(_rows(lg_e2))} row(s)")

    pause_e2.release.set()
    th_e2c.join(timeout=_DEADLINE)
    th_e2g.join(timeout=_DEADLINE)
    pause_e2.uninstall()

    _assert("G-e(ii) NO deadlock — both writers finished without error",
            "grant_exc" not in out_e2 and "close_exc" not in out_e2,
            f"grant={out_e2.get('grant_exc')} close={out_e2.get('close_exc')}")
    _assert("G-e(ii) the close committed the season close",
            out_e2.get("close") is not None and out_e2["close"].closed_now is True,
            str(out_e2.get("close")))
    _assert("G-e(ii) the grant then returned 201",
            out_e2.get("resp") is not None and out_e2["resp"].status_code == 201,
            f"got {getattr(out_e2.get('resp'), 'status_code', None)}")
    _assert("G-e(ii) the grant committed exactly once", rs_e2.commits == 1,
            str(rs_e2.commits))
    _assert("G-e(ii) authority state is complete, not partial",
            [(r.user_id, r.source) for r in _rows(lg_e2)]
            == [(caller_e2, "bootstrap"), (target_e2, "local_grant")],
            str([(r.user_id, r.source) for r in _rows(lg_e2)]))
    _assert("G-e(ii) the season is recorded closed",
            _stored_close(lg_e2) is not None, repr(_stored_close(lg_e2)))
    close_db2.close(); close_conn2.close(); rs_e2.close()

    # ══════════════════════════════════════════════════════════════════════
    # G-f — duplicate grant outcome preserved
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-f  concurrent duplicate grants still give one 201, one 409, "
          "one row")
    tdb.reset()
    lg_f     = _mk_league("G-f league")
    caller_f = _mk_user("gf_caller@gg.test")
    target_f = _mk_user("gf_target@gg.test")
    bootstrap_first_commissioner(lg_f, caller_f)
    _as_user(caller_f)

    codes_f: list[int] = []
    errs_f:  list[str] = []
    bar_f  = threading.Barrier(2)
    lock_f = threading.Lock()

    def _race_f():
        bar_f.wait(timeout=_DEADLINE)
        try:
            c = TestClient(app)
            r = c.post(f"/league/{lg_f}/commissioners", json={"user_id": target_f})
            with lock_f:
                codes_f.append(r.status_code)
        except Exception as exc:                  # noqa: BLE001 — recording
            with lock_f:
                errs_f.append(f"{type(exc).__name__}: {exc}")

    th_f = [threading.Thread(target=_race_f, daemon=True) for _ in range(2)]
    for t in th_f: t.start()
    for t in th_f: t.join(timeout=_DEADLINE)

    _assert("G-f both concurrent grants returned", len(codes_f) == 2 and not errs_f,
            f"codes={codes_f} errors={errs_f}")
    _assert("G-f exactly ONE 201 and ONE 409 — status semantics unchanged",
            sorted(codes_f) == [201, 409], f"got {sorted(codes_f)}")
    _assert("G-f exactly ONE row for that league/user pair",
            len([r for r in _rows(lg_f) if r.user_id == target_f]) == 1,
            str([r.user_id for r in _rows(lg_f)]))
    _assert("G-f the league holds exactly two authority rows in total",
            len(_rows(lg_f)) == 2, f"{len(_rows(lg_f))} row(s)")

    # ══════════════════════════════════════════════════════════════════════
    # G-g — same league, different targets
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-g  two grants of DIFFERENT targets serialize on the League row "
          "and both succeed")
    tdb.reset()
    lg_g     = _mk_league("G-g league")
    caller_g = _mk_user("gg_caller@gg.test")
    t1_g     = _mk_user("gg_target1@gg.test")
    t2_g     = _mk_user("gg_target2@gg.test")
    bootstrap_first_commissioner(lg_g, caller_g)
    _as_user(caller_g)

    # Two route calls overlap here. The get_db override is process-global, so
    # the first grant keeps it only until it has been handed its session
    # (keep=True, then uninstalled from here once the lock is held); the second
    # then runs on an ordinary get_db session and cannot be handed the first's.
    rs_g1   = RouteSession()
    pause_g = LeagueLockPause(match_pid=rs_g1.pid).install()
    out_g: dict = {}

    def _grant_g1():
        try:
            out_g["r1"] = rs_g1.post(lg_g, t1_g, keep=True)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_g["e1"] = exc

    def _grant_g2():
        try:
            out_g["r2"] = _plain_grant(lg_g, t2_g)
        except Exception as exc:                  # noqa: BLE001 — recording
            out_g["e2"] = exc

    th_g1 = threading.Thread(target=_grant_g1, daemon=True)
    th_g1.start()
    pause_g.held.wait(timeout=_DEADLINE)
    _assert("G-g the first grant is holding the League row",
            pause_g.held.is_set(), str(pause_g.pid))
    rs_g1.uninstall()          # request one already holds its session

    th_g2 = threading.Thread(target=_grant_g2, daemon=True)
    th_g2.start()

    blocked_g = _any_blocked_by(pause_g.pid)
    _lock_evidence("G-g", pause_g.pid, blocked_g)

    _assert("G-g the second grant is BLOCKED BY the first",
            blocked_g is not None, f"first pid={pause_g.pid}")
    _assert_league_row_wait("G-g", blocked_g)
    _assert("G-g neither target has a row while the second waits",
            len(_rows(lg_g)) == 1, f"{len(_rows(lg_g))} row(s)")

    pause_g.release.set()
    th_g1.join(timeout=_DEADLINE)
    th_g2.join(timeout=_DEADLINE)
    pause_g.uninstall()

    _assert("G-g both grants finished without error",
            "e1" not in out_g and "e2" not in out_g,
            f"{out_g.get('e1')} / {out_g.get('e2')}")
    _assert("G-g BOTH grants succeeded with 201",
            getattr(out_g.get("r1"), "status_code", None) == 201
            and getattr(out_g.get("r2"), "status_code", None) == 201,
            f"{getattr(out_g.get('r1'), 'status_code', None)} / "
            f"{getattr(out_g.get('r2'), 'status_code', None)}")
    rows_g = _rows(lg_g)
    _assert("G-g exactly two granted rows, one per target",
            sorted(r.user_id for r in rows_g if r.source == "local_grant")
            == sorted([t1_g, t2_g]),
            str([(r.user_id, r.source) for r in rows_g]))
    _assert("G-g provenance is correct on both granted rows",
            all(r.assigned_by_user_id == caller_g
                for r in rows_g if r.source == "local_grant"),
            str([(r.user_id, r.assigned_by_user_id) for r in rows_g]))
    _assert("G-g three authority rows in total (genesis + two grants)",
            len(rows_g) == 3, f"{len(rows_g)} row(s)")
    rs_g1.close()

    # ══════════════════════════════════════════════════════════════════════
    # G-h — refusal paths release the lock and write nothing
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-h  every refusal releases the League row and writes nothing "
          "(item 15.4)")
    tdb.reset()
    lg_h       = _mk_league("G-h league")
    caller_h   = _mk_user("gh_caller@gg.test")
    dup_h      = _mk_user("gh_dup@gg.test")
    inactive_h = _mk_user("gh_inactive@gg.test", active=0)
    bootstrap_first_commissioner(lg_h, caller_h)
    _as_user(caller_h)

    _assert("G-h setup: the duplicate target is granted once first",
            _plain_grant(lg_h, dup_h).status_code == 201)

    refusal_commits: dict[str, int] = {}
    baseline_h = len(_rows(lg_h))

    for label, target_id, expected in (
        ("unknown target user",   999_999,    404),
        ("inactive target user",  inactive_h, 400),
        ("duplicate commissioner", dup_h,     409),
    ):
        rs_h = RouteSession()
        resp_h = rs_h.post(lg_h, target_id)

        _assert(f"G-h [{label}] status is unchanged at {expected}",
                resp_h.status_code == expected,
                f"got {resp_h.status_code}: {resp_h.text[:90]}")
        _assert(f"G-h [{label}] ZERO commits on the route's own session",
                rs_h.commits == 0, str(rs_h.commits))
        _assert(f"G-h [{label}] ZERO new authority rows",
                len(_rows(lg_h)) == baseline_h,
                f"{len(_rows(lg_h))} vs {baseline_h}")
        # DIRECT release evidence, in two independent forms. The route's session
        # is still open (FastAPI ran no teardown for it), so the transaction
        # state is the handler's own, and the probe backend is a different one.
        _assert(f"G-h [{label}] the route's session has NO open transaction",
                rs_h.db.in_transaction() is False, str(rs_h.db.in_transaction()))
        _assert(f"G-h [{label}] the probe is a different backend",
                rs_h.pid != probe_pid, f"route={rs_h.pid} probe={probe_pid}")
        _assert(f"G-h [{label}] an INDEPENDENT session takes the same League "
                f"row immediately (FOR UPDATE NOWAIT)",
                _can_lock_now(lg_h) is True)
        _assert(f"G-h [{label}] that session is still open, not closed",
                rs_h.db.execute(text("SELECT 1")).scalar() == 1)
        rs_h.db.rollback()
        refusal_commits[label] = rs_h.commits
        rs_h.close()

    _assert("G-h the refusals left the authority set exactly as it was",
            [(r.user_id, r.source) for r in _rows(lg_h)]
            == [(caller_h, "bootstrap"), (dup_h, "local_grant")],
            str([(r.user_id, r.source) for r in _rows(lg_h)]))

    # ══════════════════════════════════════════════════════════════════════
    # G-i — commit discipline
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-i  commit discipline, measured on the exact session the route "
          "used")
    tdb.reset()
    lg_i     = _mk_league("G-i league")
    caller_i = _mk_user("gi_caller@gg.test")
    target_i = _mk_user("gi_target@gg.test")
    bootstrap_first_commissioner(lg_i, caller_i)
    _as_user(caller_i)

    rs_i = RouteSession()
    resp_i = rs_i.post(lg_i, target_i)
    _assert("G-i the successful grant returned 201", resp_i.status_code == 201,
            f"got {resp_i.status_code}: {resp_i.text[:90]}")
    _assert("G-i a successful grant commits EXACTLY ONCE", rs_i.commits == 1,
            str(rs_i.commits))
    # The handler's pre-existing db.refresh() runs AFTER that commit, so the
    # session does legitimately carry a fresh READ transaction on return. What
    # matters is that it carries no League lock: the commit released it, and an
    # independent backend proves so.
    _assert("G-i the League row is free immediately after the successful commit",
            _can_lock_now(lg_i) is True)
    rs_i.close()

    _assert("G-i every refusal path measured ZERO commits",
            set(refusal_commits.values()) == {0}, str(refusal_commits))
    _assert("G-i all three refusal paths were actually measured",
            len(refusal_commits) == 3, str(sorted(refusal_commits)))

    # ══════════════════════════════════════════════════════════════════════
    # G-j — item 16: the absence of a revoke/remove writer
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-j  item 16: NO production commissioner revoke/remove writer "
          "exists")
    # HONEST ABOUT ITS OWN LIMITS. Static searching cannot prove arbitrary
    # semantic absence, and this scenario does not claim it does. It makes three
    # narrow, checkable claims:
    #   1. RUNTIME: the registered FastAPI application exposes exactly one
    #      commissioner-authority route, POST /league/{league_id}/commissioners.
    #      That is evidence about the app as actually assembled, not about text.
    #   2. TEXT, NAMED SURFACES ONLY: across api/, auth/, economy/ and
    #      scripts/, no source line performs a DELETE or authority-stripping
    #      UPDATE against LeagueCommissioner / league_commissioners.
    #   3. TEXT, NAMED SURFACES ONLY: no callable in those directories is named
    #      as a commissioner revoke/remove/demote operation.
    # A positive control proves the scan really read production source rather
    # than silently matching nothing.
    prod_dirs = ["api", "auth", "economy", "scripts"]
    sources: dict[str, str] = {}
    for d in prod_dirs:
        for path in sorted((REPO / d).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            sources[str(path.relative_to(REPO)).replace("\\", "/")] = \
                path.read_text(encoding="utf-8", errors="replace")

    _assert("G-j the scan actually read production source",
            len(sources) >= 8, f"{len(sources)} file(s): {sorted(sources)}")
    _assert("G-j POSITIVE CONTROL: the scan finds the known authority INSERT "
            "sites, so it is reading real content",
            "LeagueCommissioner(" in sources.get("api/main.py", "")
            and "LeagueCommissioner(" in sources.get(
                "scripts/bootstrap_league_commissioner.py", ""),
            str(sorted(sources)))

    mutation_patterns = [
        (r"delete\s+from\s+league_commissioners",
         "raw DELETE against league_commissioners"),
        (r"update\s+league_commissioners",
         "raw UPDATE against league_commissioners"),
        (r"query\s*\(\s*LeagueCommissioner\s*\)(?:(?!\bquery\b).){0,400}?"
         r"\.\s*delete\s*\(",
         "ORM bulk delete of LeagueCommissioner"),
        (r"query\s*\(\s*LeagueCommissioner\s*\)(?:(?!\bquery\b).){0,400}?"
         r"\.\s*update\s*\(",
         "ORM bulk update of LeagueCommissioner"),
        (r"\.\s*delete\s*\(\s*[A-Za-z_][A-Za-z_0-9]*"
         r"(?:commissioner|authority)[A-Za-z_0-9]*\s*\)",
         "session delete of a commissioner/authority instance"),
    ]
    mutations: list[str] = []
    for name, src in sources.items():
        for pattern, why in mutation_patterns:
            for m in re.finditer(pattern, src, re.I | re.S):
                line = src[:m.start()].count("\n") + 1
                mutations.append(f"{name}:{line} {why}")
    _assert("G-j NO production source deletes or strips a LeagueCommissioner",
            mutations == [], str(mutations))

    revoke_names: list[str] = []
    for name, src in sources.items():
        for m in re.finditer(r"def\s+([A-Za-z_][A-Za-z_0-9]*)\s*\(", src):
            fn = m.group(1).lower()
            names_a_removal = any(w in fn for w in
                                  ("revoke", "demote", "unassign", "deauthorize"))
            removes_authority = (
                any(w in fn for w in ("remove", "delete", "drop", "strip"))
                and any(w in fn for w in ("commissioner", "authority"))
            )
            if names_a_removal or removes_authority:
                revoke_names.append(f"{name}:{m.group(1)}")
    _assert("G-j NO production callable is named as a commissioner "
            "revoke/remove/demote operation", revoke_names == [],
            str(revoke_names))

    comm_routes = sorted(
        (r.path, tuple(sorted(getattr(r, "methods", None) or ())))
        for r in app.routes
        if "commissioner" in getattr(r, "path", "")
    )
    _note(f"G-j: registered commissioner routes = {comm_routes}")
    _assert("G-j RUNTIME: the app exposes exactly ONE commissioner-authority "
            "route, the POST grant",
            comm_routes == [("/league/{league_id}/commissioners", ("POST",))],
            str(comm_routes))
    _assert("G-j RUNTIME: no registered route removes commissioner authority",
            not any("DELETE" in methods for _, methods in comm_routes),
            str(comm_routes))
    _assert("G-j economy/top_off.py remains ABSENT",
            not (REPO / "economy" / "top_off.py").exists())

    # ══════════════════════════════════════════════════════════════════════
    # G-k — no money-path side effects
    # ══════════════════════════════════════════════════════════════════════
    print("\nG-k  a grant touches no money surface")
    tdb.reset()
    lg_k     = _mk_league("G-k league")
    team_k   = _mk_team(lg_k, "GKTeam")
    caller_k = _mk_user("gk_caller@gg.test")
    target_k = _mk_user("gk_target@gg.test")
    bootstrap_first_commissioner(lg_k, caller_k)
    _as_user(caller_k)
    with SessionLocal() as db:
        db.add(Wallet(team_id=team_k, balance=250.0)); db.commit()

    def _money_snapshot():
        """Only the surfaces §15 item 15 names — this is not a money-engine
        regression suite."""
        with SessionLocal() as db:
            return {
                "ledger_entries":  db.query(LedgerEntry).count(),
                "faab_tx":         db.query(FaabTransaction).count(),
                "disclosures":     db.query(TopOffDisclosure).count(),
                "wallets":         {w.id: w.balance for w in db.query(Wallet).all()},
                "season_closed":   _stored_close(lg_k),
            }

    before_k = _money_snapshot()
    resp_k = _plain_grant(lg_k, target_k)
    after_k = _money_snapshot()

    _assert("G-k the grant succeeded (201)", resp_k.status_code == 201,
            f"got {resp_k.status_code}: {resp_k.text[:90]}")
    _assert("G-k NO Ledger entry was created",
            after_k["ledger_entries"] == before_k["ledger_entries"] == 0,
            f"{before_k['ledger_entries']} -> {after_k['ledger_entries']}")
    _assert("G-k NO Wallet balance changed",
            after_k["wallets"] == before_k["wallets"],
            f"{before_k['wallets']} -> {after_k['wallets']}")
    _assert("G-k NO FaabTransaction was created",
            after_k["faab_tx"] == before_k["faab_tx"] == 0,
            f"{before_k['faab_tx']} -> {after_k['faab_tx']}")
    _assert("G-k NO TopOffDisclosure was created",
            after_k["disclosures"] == before_k["disclosures"] == 0,
            f"{before_k['disclosures']} -> {after_k['disclosures']}")
    _assert("G-k season_closed_at was NOT modified",
            after_k["season_closed"] is None and before_k["season_closed"] is None,
            f"{before_k['season_closed']!r} -> {after_k['season_closed']!r}")
    _assert("G-k the authority row itself WAS written (the control)",
            len(_rows(lg_k)) == 2, f"{len(_rows(lg_k))} row(s)")

    # ── cleanup ───────────────────────────────────────────────────────────
    app.dependency_overrides.clear()
    probe.close()


try:
    main(tdb)
finally:
    tdb.teardown()

if _evidence:
    print("\nPostgreSQL lock evidence collected:")
    for line in _evidence:
        print(f"  {line}")

print("\n" + "=" * 60)
if _failures:
    print(f"FAILED: {len(_failures)} assertion(s)")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1)
print("All assertions PASSED")
