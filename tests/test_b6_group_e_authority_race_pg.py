"""
test_b6_group_e_authority_race_pg.py — B6 Package 3 Group E, §15 item 18 plus
the deferred Group D item 17: genuine PostgreSQL overlap (PostgreSQL only).

WHY THIS FILE EXISTS SEPARATELY. Every scenario here needs the same machinery —
sessions pinned to a known backend, a statement pause that freezes a real writer
mid-transaction while it holds a real lock, and a third connection asking
PostgreSQL who is blocking whom. That machinery is about a third of the file.
Keeping it out of test_b6_group_e_issuance_pg.py means the single-session
semantics there can be read without it, and the blocking proofs here can be read
without wading through cap arithmetic.

    this file    P1, P2, P3, P7, P11, S2, SA3, AR1-AR4, and item 17
    issuance     A4-A11, P5, P6, P8, P9, P10, S3, S4, S10, S12, S15, SA1-SA5

CONCURRENCY EVIDENCE IS DIRECT, NEVER TIMED. Every blocking claim is
PostgreSQL's own answer, read from a third connection:

    SELECT ... FROM pg_stat_activity
    WHERE pid = :blocked AND :holder = ANY(pg_blocking_pids(pid))

No sleep is ever used as proof. The only bounded polls wait for that observable
condition to appear and fail loudly if it never does; the deadline is a FAILURE
BOUND, not evidence.

A REAL WRITER IS MADE TO HOLD ITS OWN LOCK, WITHOUT EDITING IT. StatementPause
freezes one backend immediately AFTER it has executed a chosen statement — its
own `leagues ... FOR UPDATE`, its own allocation lock, its own INSERT — using a
SQLAlchemy cursor event on the test engine, filtered by backend pid. The lock
being held is therefore the one economy/top_off.py took itself, inside its own
transaction. No production module is modified, monkey-patched or re-implemented.
Selection is by PID rather than by thread because a service call may execute on
any thread; pid is what identifies the transaction.

EVERY OBSERVED SESSION IS PINNED TO ONE BACKEND. A pooled Session hands its
connection back on rollback, so a pid read at construction can belong to somebody
else by the time the statement under test runs. Each session this suite observes
is bound to a Connection the test checked out and holds until it closes.

NO PRODUCTION REVOKE WRITER IS CREATED, HERE OR ANYWHERE. §15 item 16 keeps that
absence, and Group D proved it. AR1-AR3 need a revocation that behaves the way
§6.4 REQUIRES the first real one to behave — League row FOR UPDATE before
touching league_commissioners — so this file models exactly those two statements,
in the test, as _compliant_revoke(). Worth stating plainly: a NON-compliant
revocation (a bare DELETE) would take no lock on the leagues row at all and would
not serialize against approval. That is the whole reason §6.4 makes the lock
mandatory, and it is why AR2 is a real test rather than a tautology.

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] B6 Group E authority-race suite cannot run:\n  {e}")
    sys.exit(2)

# Failure bounds. _HOLD_DEADLINE is deliberately the larger, so a holder can
# never self-release while an observation is still being attempted and rescue a
# scenario that should have failed.
_DEADLINE      = 20.0
_HOLD_DEADLINE = 90.0

_failures: list[str] = []
_evidence: list[str] = []
_seq = {"n": 0}


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def _note(line: str) -> None:
    _evidence.append(line)
    print(f"       · {line}")


def _uniq(prefix: str) -> str:
    _seq["n"] += 1
    return f"{prefix}{_seq['n']}"


def main(tdb) -> None:
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import event, text
    from sqlalchemy.exc import IntegrityError, OperationalError

    import config
    from db.schema import (
        SessionLocal, FaabTransaction, League, LeagueCommissioner, SeasonAllocation,
        Team, TopOffDisclosure, User, Wallet,
    )
    from ledger.ledger import _balance_of_in_session, trial_balance
    from auth.jwt_auth import hash_password
    from economy.season_allocation import activate_season_allocation
    from economy.season_close import close_season
    from scripts.bootstrap_league_commissioner import bootstrap_first_commissioner

    import economy.top_off as topoff
    from economy.top_off import (
        approve_top_off, create_top_off_request,
        AuthorizationAttemptAbort, CreationRefused, SeasonClosedAbort,
        REASON_OPEN_REQUEST,
    )

    SEASON = config.ALLOCATION_SEASON

    # ── seed helpers ──────────────────────────────────────────────────────

    def _mk_league(name: str, multiplier_bps: int = 10000) -> int:
        with SessionLocal() as db:
            lg = League(season=2025, name=name, projection_source="fantasypros",
                        topoff_cap_multiplier_bps=multiplier_bps)
            db.add(lg); db.commit(); return lg.id

    def _mk_team(league_id: int, name: str) -> int:
        with SessionLocal() as db:
            t = Team(league_id=league_id, team_name=name, owner=name,
                     email=f"{name}@gg.test")
            db.add(t); db.commit(); return t.id

    def _mk_user(email: str) -> int:
        with SessionLocal() as db:
            u = User(email=email, hashed_password=hash_password("x"),
                     team_id=None, role="gm", is_active=1)
            db.add(u); db.commit(); return u.id

    class Fixture:
        """One activated league with wallets, a genesis commissioner, frozen
        allocation rows and a frozen multiplier."""

        def __init__(self, tag: str, n_teams: int = 1, multiplier_bps: int = 10000):
            self.league_id = _mk_league(_uniq(f"{tag}-lg"), multiplier_bps)
            self.team_ids = [_mk_team(self.league_id, _uniq(f"{tag}T"))
                             for _ in range(n_teams)]
            for t in self.team_ids:
                with SessionLocal() as db:
                    db.add(Wallet(team_id=t, balance=1000.0)); db.commit()
            self.commissioner_id = _mk_user(f"{_uniq(tag + '_comm')}@gg.test")
            self.gm_ids = [_mk_user(f"{_uniq(tag + '_gm')}@gg.test")
                           for _ in range(n_teams)]
            bootstrap_first_commissioner(self.league_id, self.commissioner_id)
            with SessionLocal() as db:
                activate_season_allocation(self.league_id, db)

        @property
        def team_id(self) -> int:
            return self.team_ids[0]

        @property
        def gm_id(self) -> int:
            return self.gm_ids[0]

    def _open_request(fx, dollars: float, team_index: int = 0):
        with SessionLocal() as db:
            return create_top_off_request(fx.league_id, fx.team_ids[team_index],
                                          fx.gm_ids[team_index], dollars, db=db)

    def _row(request_id: int):
        with SessionLocal() as db:
            return db.query(FaabTransaction).filter(
                FaabTransaction.id == request_id).one_or_none()

    def _entry_count() -> int:
        with SessionLocal() as db:
            return db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()

    def _disclosure_count() -> int:
        with SessionLocal() as db:
            return db.query(TopOffDisclosure).count()

    def _wallet_balance(team_id: int) -> float:
        with SessionLocal() as db:
            return db.query(Wallet).filter(Wallet.team_id == team_id).one().balance

    def _legs(posting_id):
        with SessionLocal() as db:
            rows = db.execute(text(
                "SELECT account, amount_cents FROM ledger_entries "
                "WHERE posting_id = :p"), {"p": posting_id}).fetchall()
        return [(a, int(c)) for a, c in rows]

    def _authority_rows(league_id: int) -> list:
        with SessionLocal() as db:
            return [r.user_id for r in db.query(LeagueCommissioner).filter(
                LeagueCommissioner.league_id == league_id).all()]

    # ── the observing connection (C in every scenario) ────────────────────
    probe = tdb.engine.connect()
    probe_pid = probe.execute(text("SELECT pg_backend_pid()")).scalar()
    probe.rollback()

    _BLOCK_SQL = """
        SELECT pid, wait_event_type, state, query
        FROM pg_stat_activity
        WHERE pid = :blocked AND :holder = ANY(pg_blocking_pids(pid))
    """

    def _blocked_by(blocked_pid: int, holder_pid: int):
        """PostgreSQL's own answer to 'is backend X waiting on a lock held by
        backend Y'. Bounded poll on an OBSERVABLE condition; each iteration is a
        real round trip, so it paces itself with no sleep."""
        end = time.monotonic() + _DEADLINE
        while time.monotonic() < end:
            row = probe.execute(text(_BLOCK_SQL),
                                {"blocked": blocked_pid, "holder": holder_pid}).fetchone()
            probe.rollback()
            if row is not None:
                return row
        return None

    def _blockers_of(pid: int) -> list:
        got = probe.execute(text("SELECT pg_blocking_pids(:p)"), {"p": pid}).scalar()
        probe.rollback()
        return list(got or [])

    def _can_lock_league(league_id: int, mode: str = "FOR UPDATE") -> bool:
        """Whether this independent backend can take the League row right now.
        NOWAIT errors instead of waiting, so the answer is a direct statement
        about lock availability, never a timeout standing in for one."""
        try:
            probe.execute(text(f"SELECT id FROM leagues WHERE id = :i {mode} NOWAIT"),
                          {"i": league_id}).fetchall()
            return True
        except OperationalError:
            return False
        finally:
            probe.rollback()

    def _evidence_line(tag: str, holder_pid, row) -> None:
        if row is None:
            _note(f"{tag}: holder pid={holder_pid} blocked pid=NONE OBSERVED")
            return
        _note(f"{tag}: holder pid={holder_pid} blocked pid={row[0]} "
              f"wait={row[1]} state={row[2]!r}")
        _note(f"{tag}: blocked statement = {' '.join((row[3] or '').split())[:110]}")

    # ── a session the test owns, pinned to one backend, commits counted ───

    class Svc:
        """A Session for a service call, bound to a Connection the test holds so
        its backend pid is stable, with its commits counted on that very
        session."""

        def __init__(self):
            self.conn = tdb.engine.connect()
            self.pid = self.conn.execute(text("SELECT pg_backend_pid()")).scalar()
            self.conn.rollback()
            self.db = SessionLocal(bind=self.conn)
            self.commits = 0
            event.listen(self.db, "after_commit", self._bump)

        def _bump(self, session):
            self.commits += 1

        def close(self):
            event.remove(self.db, "after_commit", self._bump)
            self.db.close()
            self.conn.close()

    # ── freezing a real writer mid-transaction ────────────────────────────

    MATCH_REQUEST_LOCK    = ("faab_transactions", "for update")
    MATCH_ALLOCATION_LOCK = ("season_allocation", "for update")
    MATCH_CONFIG_READ     = ("league_season_topoff_config",)
    MATCH_LEAGUE_LOCK     = ("leagues", "for update")
    MATCH_REQUEST_INSERT  = ("insert into faab_transactions",)

    class StatementPause:
        """Freezes ONE backend the instant it has executed a matching statement,
        so a production writer can be observed HOLDING the lock it took itself.

        Fires AFTER the statement completed, so the lock is genuinely held inside
        the writer's own transaction for exactly as long as the scenario needs.
        Matching is `all(fragment in statement.lower())` plus the backend pid.
        """

        def __init__(self, match_pid: int, fragments: tuple):
            self.match_pid = match_pid
            self.fragments = fragments
            self.held = threading.Event()
            self.release = threading.Event()
            self.statement = None

        def install(self):
            event.listen(tdb.engine, "after_cursor_execute", self._hook)
            return self

        def uninstall(self) -> None:
            event.remove(tdb.engine, "after_cursor_execute", self._hook)

        def _hook(self, conn, cursor, statement, parameters, context, executemany):
            if self.held.is_set():
                return
            raw = getattr(conn.connection, "dbapi_connection", conn.connection)
            if raw.get_backend_pid() != self.match_pid:
                return
            s = statement.lower()
            if not all(f in s for f in self.fragments):
                return
            self.statement = " ".join(statement.split())
            self.held.set()
            self.release.wait(timeout=_HOLD_DEADLINE)

    class StatementRecorder:
        """Every statement one backend executed, in order. Used to prove an
        abort happened BEFORE a particular statement was ever issued — which is
        what AR4 claims and what a status assertion alone cannot show."""

        def __init__(self, match_pid: int):
            self.match_pid = match_pid
            self.statements: list[str] = []

        def install(self):
            event.listen(tdb.engine, "after_cursor_execute", self._hook)
            return self

        def uninstall(self) -> None:
            event.remove(tdb.engine, "after_cursor_execute", self._hook)

        def _hook(self, conn, cursor, statement, parameters, context, executemany):
            raw = getattr(conn.connection, "dbapi_connection", conn.connection)
            if raw.get_backend_pid() == self.match_pid:
                self.statements.append(" ".join(statement.split()).lower())

        def matching(self, *fragments) -> list:
            return [s for s in self.statements if all(f in s for f in fragments)]

    # ── modelled authority writers (test-side; no production writer added) ──

    def _compliant_revoke(db, league_id: int, user_id: int) -> None:
        """A revocation that behaves the way §6.4 requires the first real revoke
        writer to behave: League row FOR UPDATE FIRST, then the delete. Two
        statements, in a test, so AR1-AR3 can prove the contract. No production
        revoke writer is created by this suite or by Group E."""
        db.execute(text("SELECT id FROM leagues WHERE id = :i FOR UPDATE"),
                   {"i": league_id}).fetchall()
        db.execute(text("DELETE FROM league_commissioners "
                        "WHERE league_id = :l AND user_id = :u"),
                   {"l": league_id, "u": user_id})

    def _compliant_grant(db, league_id: int, user_id: int, by_user_id: int) -> None:
        """A grant with the same discipline — the production route's own lock is
        Group D's and is proven there; this models it so SA3 stays service-level
        and imports no API surface."""
        db.execute(text("SELECT id FROM leagues WHERE id = :i FOR UPDATE"),
                   {"i": league_id}).fetchall()
        db.execute(text(
            "INSERT INTO league_commissioners "
            "(league_id, user_id, source, assigned_by_user_id, created_at) "
            "VALUES (:l, :u, 'local_grant', :b, NOW())"),
            {"l": league_id, "u": user_id, "b": by_user_id})

    def _thread(fn, out: dict, key: str):
        def _runner():
            try:
                out[key] = fn()
            except Exception as exc:              # noqa: BLE001 — recording
                out[f"{key}_exc"] = exc
        return threading.Thread(target=_runner, daemon=True)

    # ══════════════════════════════════════════════════════════════════════
    # P1 — two concurrent approvals of the SAME request
    # ══════════════════════════════════════════════════════════════════════
    print("\nP1   two concurrent approvals of one request → one posting, one "
          "no-op (lock 1)")
    tdb.reset()
    fx = Fixture("p1")
    req = _open_request(fx, 20.00)

    a = Svc(); b = Svc()
    pause = StatementPause(a.pid, MATCH_REQUEST_LOCK).install()
    out: dict = {}
    th_a = _thread(lambda: approve_top_off(fx.league_id, req.request_id,
                                           fx.commissioner_id, db=a.db), out, "a")
    th_a.start()
    pause.held.wait(timeout=_DEADLINE)
    _assert("P1 approval A is holding the request row it locked itself",
            pause.held.is_set(), str(pause.statement))

    th_b = _thread(lambda: approve_top_off(fx.league_id, req.request_id,
                                           fx.commissioner_id, db=b.db), out, "b")
    th_b.start()
    blocked = _blocked_by(b.pid, a.pid)
    _evidence_line("P1", a.pid, blocked)
    _assert("P1 approval B is BLOCKED BY approval A", blocked is not None,
            f"A pid={a.pid} B pid={b.pid}")
    _assert("P1 the wait is a Lock wait on the request row",
            blocked is not None and blocked[1] == "Lock"
            and "faab_transactions" in (blocked[3] or "").lower(),
            f"{None if blocked is None else blocked[3]}")

    pause.release.set()
    th_a.join(timeout=_DEADLINE); th_b.join(timeout=_DEADLINE)
    pause.uninstall()

    _assert("P1 neither call raised", "a_exc" not in out and "b_exc" not in out,
            f"{out.get('a_exc')} / {out.get('b_exc')}")
    _assert("P1 A posted", out.get("a") is not None and out["a"].posted is True)
    _assert("P1 B is the terminal-state no-op, returning the ORIGINAL posting",
            out.get("b") is not None and out["b"].replayed is True
            and out["b"].posted is False
            and out["b"].ledger_posting_id == out["a"].ledger_posting_id,
            f"replayed={getattr(out.get('b'), 'replayed', None)}")
    _assert("P1 exactly ONE commit (A) and ZERO (B)",
            a.commits == 1 and b.commits == 0, f"A={a.commits} B={b.commits}")
    _assert("P1 exactly one posting — two ledger entries in total",
            _entry_count() == 5, f"{_entry_count()} (3 allocation legs + 2)")
    _assert("P1 exactly one disclosure", _disclosure_count() == 1,
            str(_disclosure_count()))
    _assert("P1 trial_balance() is 0", trial_balance() == 0)
    a.close(); b.close()

    # ══════════════════════════════════════════════════════════════════════
    # P2 — lock 2 serializes approvals against ONE team-season cap
    # ══════════════════════════════════════════════════════════════════════
    print("\nP2   the allocation row lock serializes cap consumption, and the "
          "loser rejects in full")
    # CONSTRUCTIBILITY NOTE, stated rather than papered over. P2's literal
    # wording is "two concurrent approvals, DIFFERENT requests, same team". That
    # precondition is unreachable through the supported path: §8.5's partial
    # unique index permits at most ONE pending request per
    # (league_id, team_id, season), so two open requests for one team-season
    # cannot coexist — by construction, in the database. The claim P2 actually
    # makes about the system is proved here in its two halves: (a) a contender
    # for the same allocation row genuinely blocks while an approval holds it,
    # and (b) an approval that no longer fits recomputes under that lock and
    # rejects in full. See the findings note.
    tdb.reset()
    fx2 = Fixture("p2")
    req2 = _open_request(fx2, 100.00)          # cap is $140

    a2 = Svc()
    pause2 = StatementPause(a2.pid, MATCH_ALLOCATION_LOCK).install()
    out2: dict = {}
    th_a2 = _thread(lambda: approve_top_off(fx2.league_id, req2.request_id,
                                            fx2.commissioner_id, db=a2.db), out2, "a")
    th_a2.start()
    pause2.held.wait(timeout=_DEADLINE)
    _assert("P2 the approval is holding the SeasonAllocation row",
            pause2.held.is_set(), str(pause2.statement))

    # A contender for that exact row — the shape any second approval against
    # this team-season cap would take at step 2.
    cont = Svc()
    out2c: dict = {}
    th_c2 = _thread(lambda: cont.db.execute(text(
        "SELECT id FROM season_allocation WHERE league_id = :l AND team_id = :t "
        "AND season = :s FOR UPDATE"),
        {"l": fx2.league_id, "t": fx2.team_id, "s": SEASON}).fetchall(),
        out2c, "c")
    th_c2.start()
    blocked2 = _blocked_by(cont.pid, a2.pid)
    _evidence_line("P2", a2.pid, blocked2)
    _assert("P2 the contender for the same allocation row is BLOCKED",
            blocked2 is not None, f"holder pid={a2.pid} contender pid={cont.pid}")
    _assert("P2 the wait is a Lock wait on season_allocation",
            blocked2 is not None and blocked2[1] == "Lock"
            and "season_allocation" in (blocked2[3] or "").lower(),
            f"{None if blocked2 is None else blocked2[3]}")

    pause2.release.set()
    th_a2.join(timeout=_DEADLINE); th_c2.join(timeout=_DEADLINE)
    pause2.uninstall()
    cont.db.rollback(); cont.close()

    _assert("P2 the first approval consumed the headroom",
            out2.get("a") is not None and out2["a"].posted is True
            and out2["a"].remaining_capacity_cents == 4000,
            f"remaining={getattr(out2.get('a'), 'remaining_capacity_cents', None)}")
    _assert("P2 it committed exactly once", a2.commits == 1, str(a2.commits))
    a2.close()

    # (b) the loser's half — an approval that no longer fits. The request is
    # planted directly because creation would now refuse it, which is the point:
    # the cap re-check at approval is mandatory and independent of creation.
    with SessionLocal() as db:
        planted = FaabTransaction(
            league_id=fx2.league_id, team_id=fx2.team_id, type="topup_bet",
            amount=80.0, amount_cents=8000, season=SEASON, status="pending",
            decision="pending", requester_user_id=fx2.gm_id)
        db.add(planted); db.commit(); planted_id = planted.id
    entries_before = _entry_count()
    b2 = Svc()
    try:
        res_b2 = approve_top_off(fx2.league_id, planted_id, fx2.commissioner_id,
                                 db=b2.db)
        exc_b2 = None
    except Exception as exc:                      # noqa: BLE001 — recording
        res_b2, exc_b2 = None, exc
    _assert("P2 the second approval REJECTS IN FULL — no partial approval, no "
            "auto-reduction",
            exc_b2 is None and res_b2 is not None and res_b2.decision == "rejected"
            and res_b2.posted is False,
            f"{type(exc_b2).__name__}: {exc_b2}")
    _assert("P2 the rejection committed exactly once", b2.commits == 1, str(b2.commits))
    _assert("P2 no ledger entry was written by the rejection",
            _entry_count() == entries_before,
            f"{entries_before} -> {_entry_count()}")
    with SessionLocal() as db:
        issued = -_balance_of_in_session(db, f"bab_issuance:{fx2.league_id}:{SEASON}")
    _assert("P2 cumulative issuance stayed within the frozen cap",
            issued == 10000 and issued <= 14000, f"issued={issued} cap=14000")
    b2.close()

    # ══════════════════════════════════════════════════════════════════════
    # P3 — different teams do not block
    # ══════════════════════════════════════════════════════════════════════
    print("\nP3   approvals for DIFFERENT teams lock different allocation rows "
          "and never block")
    tdb.reset()
    fx3 = Fixture("p3", n_teams=2)
    r3a = _open_request(fx3, 10.00, team_index=0)
    r3b = _open_request(fx3, 10.00, team_index=1)

    a3 = Svc(); b3 = Svc()
    # BOTH pauses are installed BEFORE either thread starts, and that ordering is
    # load-bearing rather than stylistic. A paused thread is blocked INSIDE
    # SQLAlchemy's event dispatch, still iterating the engine's listener
    # collection; calling event.listen() from another thread at that moment
    # mutates the deque mid-iteration and kills the paused writer with a
    # RuntimeError. Each pause is pid-filtered, so installing both up front
    # changes nothing about which backend either one freezes.
    pause3  = StatementPause(a3.pid, MATCH_ALLOCATION_LOCK).install()
    pause3b = StatementPause(b3.pid, MATCH_LEAGUE_LOCK).install()
    out3: dict = {}
    th_a3 = _thread(lambda: approve_top_off(fx3.league_id, r3a.request_id,
                                            fx3.commissioner_id, db=a3.db), out3, "a")
    th_a3.start()
    pause3.held.wait(timeout=_DEADLINE)

    th_b3 = _thread(lambda: approve_top_off(fx3.league_id, r3b.request_id,
                                            fx3.commissioner_id, db=b3.db), out3, "b")
    th_b3.start()
    pause3b.held.wait(timeout=_DEADLINE)
    blockers3 = _blockers_of(b3.pid)
    _note(f"P3: team-A approval pid={a3.pid} holds its allocation row; team-B "
          f"approval pid={b3.pid} pg_blocking_pids={blockers3}")
    _assert("P3 the second approval reached its own League lock while the first "
            "still holds team A's allocation row", pause3b.held.is_set())
    _assert("P3 pg_blocking_pids() for the second approval is EMPTY — it is "
            "blocked by nobody", blockers3 == [], str(blockers3))

    pause3b.release.set(); pause3.release.set()
    th_a3.join(timeout=_DEADLINE); th_b3.join(timeout=_DEADLINE)
    pause3.uninstall(); pause3b.uninstall()
    _assert("P3 both approvals succeeded",
            out3.get("a") is not None and out3["a"].posted
            and out3.get("b") is not None and out3["b"].posted,
            f"{out3.get('a_exc')} / {out3.get('b_exc')}")
    _assert("P3 both committed exactly once",
            a3.commits == 1 and b3.commits == 1, f"{a3.commits} / {b3.commits}")
    _assert("P3 trial_balance() is 0", trial_balance() == 0)
    a3.close(); b3.close()

    # ══════════════════════════════════════════════════════════════════════
    # P7 / P11 — duplicate creation and narrow IntegrityError classification
    # ══════════════════════════════════════════════════════════════════════
    print("\nP7   concurrent duplicate creation → the partial unique index "
          "rejects the second (§8.5)")
    tdb.reset()
    fx7 = Fixture("p7")
    a7 = Svc(); b7 = Svc()
    pause7 = StatementPause(a7.pid, MATCH_REQUEST_INSERT).install()
    out7: dict = {}
    th_a7 = _thread(lambda: create_top_off_request(fx7.league_id, fx7.team_id,
                                                   fx7.gm_id, 10.00, db=a7.db),
                    out7, "a")
    th_a7.start()
    pause7.held.wait(timeout=_DEADLINE)
    _assert("P7 creation A has inserted its pending row, uncommitted",
            pause7.held.is_set(), str(pause7.statement))

    th_b7 = _thread(lambda: create_top_off_request(fx7.league_id, fx7.team_id,
                                                   fx7.gm_id, 10.00, db=b7.db),
                    out7, "b")
    th_b7.start()
    blocked7 = _blocked_by(b7.pid, a7.pid)
    _evidence_line("P7", a7.pid, blocked7)
    _assert("P7 creation B BLOCKS on the index entry A holds",
            blocked7 is not None, f"A pid={a7.pid} B pid={b7.pid}")

    pause7.release.set()
    th_a7.join(timeout=_DEADLINE); th_b7.join(timeout=_DEADLINE)
    pause7.uninstall()

    _assert("P7 creation A succeeded", out7.get("a") is not None,
            str(out7.get("a_exc")))
    _assert("P7 creation B was refused with 'open_request_exists'",
            isinstance(out7.get("b_exc"), CreationRefused)
            and out7["b_exc"].reason_code == REASON_OPEN_REQUEST,
            f"got {type(out7.get('b_exc')).__name__}: "
            f"{getattr(out7.get('b_exc'), 'reason_code', None)}")
    with SessionLocal() as db:
        n_pending = db.query(FaabTransaction).filter(
            FaabTransaction.league_id == fx7.league_id,
            FaabTransaction.status == "pending").count()
    _assert("P7 exactly ONE pending request survives", n_pending == 1, str(n_pending))
    _assert("P7 B committed nothing", b7.commits == 0, str(b7.commits))
    a7.close(); b7.close()

    print("\nP11  an UNRELATED IntegrityError propagates rather than being "
          "swallowed as a duplicate refusal")
    tdb.reset()
    fx11 = Fixture("p11")
    a11 = Svc(); b11 = Svc()
    pause11 = StatementPause(a11.pid, MATCH_REQUEST_INSERT).install()
    out11: dict = {}
    # Point the service's constraint-name constant at a name the database will
    # never report. The SAME duplicate-index violation now looks, to the narrow
    # classifier, like any other integrity failure — and must therefore be
    # re-raised rather than converted into a benign refusal.
    real_index_name = topoff.PENDING_REQUEST_INDEX
    topoff.PENDING_REQUEST_INDEX = "uq_some_other_constraint_entirely"
    try:
        th_a11 = _thread(lambda: create_top_off_request(fx11.league_id, fx11.team_id,
                                                        fx11.gm_id, 10.00, db=a11.db),
                         out11, "a")
        th_a11.start()
        pause11.held.wait(timeout=_DEADLINE)
        th_b11 = _thread(lambda: create_top_off_request(fx11.league_id, fx11.team_id,
                                                        fx11.gm_id, 10.00, db=b11.db),
                         out11, "b")
        th_b11.start()
        _blocked_by(b11.pid, a11.pid)
        pause11.release.set()
        th_a11.join(timeout=_DEADLINE); th_b11.join(timeout=_DEADLINE)
    finally:
        topoff.PENDING_REQUEST_INDEX = real_index_name
        pause11.uninstall()

    _assert("P11 the unrelated-looking IntegrityError PROPAGATED",
            isinstance(out11.get("b_exc"), IntegrityError),
            f"got {type(out11.get('b_exc')).__name__}")
    _assert("P11 it was NOT converted into a CreationRefused",
            not isinstance(out11.get("b_exc"), CreationRefused),
            f"got {type(out11.get('b_exc')).__name__}")
    _assert("P11 CONTROL: the constant is restored and names the real index",
            topoff.PENDING_REQUEST_INDEX == "uq_faab_tx_one_open_topoff",
            topoff.PENDING_REQUEST_INDEX)
    a11.close(); b11.close()

    # ══════════════════════════════════════════════════════════════════════
    # item 17 — the League lock at step 14, held through the commit at 19
    # ══════════════════════════════════════════════════════════════════════
    print("\nITEM 17  approval takes the League row FOR UPDATE at step 14 and "
          "HOLDS IT THROUGH the commit at step 19")
    tdb.reset()
    fx17 = Fixture("i17")
    req17 = _open_request(fx17, 10.00)
    a17 = Svc()
    pause17 = StatementPause(a17.pid, MATCH_LEAGUE_LOCK).install()
    out17: dict = {}
    th_a17 = _thread(lambda: approve_top_off(fx17.league_id, req17.request_id,
                                             fx17.commissioner_id, db=a17.db),
                     out17, "a")
    th_a17.start()
    pause17.held.wait(timeout=_DEADLINE)
    _assert("item 17 the approval took a leagues row lock at step 14",
            pause17.held.is_set(), str(pause17.statement))
    _assert("item 17 the statement is a PLAIN FOR UPDATE, carrying no "
            "'no key' downgrade",
            pause17.statement is not None
            and "for update" in pause17.statement.lower()
            and "no key" not in pause17.statement.lower(),
            str(pause17.statement))
    _assert("item 17 nothing was posted before the League lock was taken",
            _entry_count() == 3, f"{_entry_count()} (the 3 allocation legs only)")

    # A contender that reads the request's committed state at the moment it
    # finally acquires the League row. If the lock were released before the
    # commit, the contender would get in and still see `pending`.
    cont17 = Svc()
    out_c17: dict = {}

    def _contend17():
        cont17.db.execute(text("SELECT id FROM leagues WHERE id = :i FOR UPDATE"),
                          {"i": fx17.league_id}).fetchall()
        seen = cont17.db.execute(text(
            "SELECT status FROM faab_transactions WHERE id = :r"),
            {"r": req17.request_id}).scalar()
        cont17.db.rollback()
        return seen

    th_c17 = _thread(_contend17, out_c17, "seen")
    th_c17.start()
    blocked17 = _blocked_by(cont17.pid, a17.pid)
    _evidence_line("item 17", a17.pid, blocked17)
    _assert("item 17 a League-row contender is BLOCKED BY the approval",
            blocked17 is not None,
            f"approval pid={a17.pid} contender pid={cont17.pid}")
    _assert("item 17 the League row is genuinely unavailable to anyone else",
            _can_lock_league(fx17.league_id) is False)

    pause17.release.set()
    th_a17.join(timeout=_DEADLINE); th_c17.join(timeout=_DEADLINE)
    pause17.uninstall()

    _assert("item 17 the approval committed", out17.get("a") is not None
            and out17["a"].posted is True, str(out17.get("a_exc")))
    _assert("item 17 THE PROOF: the contender acquired the League row only "
            "AFTER the commit — it saw status 'applied', never 'pending'",
            out_c17.get("seen") == "applied", f"saw {out_c17.get('seen')!r}")
    _assert("item 17 the lock released with the commit, not before",
            _can_lock_league(fx17.league_id) is True)
    a17.close(); cont17.close()

    # The mode itself: FOR KEY SHARE conflicts with FOR UPDATE and with nothing
    # weaker, so an approval that blocks against it is taking FOR UPDATE and not
    # the FOR NO KEY UPDATE that key_share=True would emit.
    tdb.reset()
    fx17b = Fixture("i17b")
    req17b = _open_request(fx17b, 10.00)
    ks = Svc()
    ks.db.execute(text("SELECT id FROM leagues WHERE id = :i FOR KEY SHARE"),
                  {"i": fx17b.league_id}).fetchall()
    _assert("item 17 CONTROL: FOR NO KEY UPDATE does NOT conflict with the held "
            "FOR KEY SHARE", _can_lock_league(fx17b.league_id, "FOR NO KEY UPDATE") is True)
    _assert("item 17 CONTROL: FOR UPDATE DOES conflict with it",
            _can_lock_league(fx17b.league_id, "FOR UPDATE") is False)
    a17b = Svc()
    out17b: dict = {}
    th_a17b = _thread(lambda: approve_top_off(fx17b.league_id, req17b.request_id,
                                              fx17b.commissioner_id, db=a17b.db),
                      out17b, "a")
    th_a17b.start()
    blocked17b = _blocked_by(a17b.pid, ks.pid)
    _evidence_line("item 17 mode", ks.pid, blocked17b)
    _assert("item 17 the approval BLOCKS against FOR KEY SHARE — its mode is "
            "FOR UPDATE, not FOR NO KEY UPDATE", blocked17b is not None,
            f"holder pid={ks.pid} approval pid={a17b.pid}")
    ks.db.rollback(); ks.close()
    th_a17b.join(timeout=_DEADLINE)
    _assert("item 17 the approval then completed", out17b.get("a") is not None
            and out17b["a"].posted is True, str(out17b.get("a_exc")))
    a17b.close()

    # ══════════════════════════════════════════════════════════════════════
    # AR1 — revocation wins BEFORE the final revalidation
    # ══════════════════════════════════════════════════════════════════════
    print("\nAR1  revocation commits before step 14 → authorization abort, "
          "nothing written")
    tdb.reset()
    fxr1 = Fixture("ar1")
    rq1 = _open_request(fxr1, 10.00)
    a_r1 = Svc()
    # Pause AFTER step 9's snapshot read: past the step-6 preliminary authority
    # check and before the step-14 League lock. That window is exactly where a
    # revocation must be able to land, and it is what makes step 14 load-bearing
    # rather than decorative — without it this approval would post.
    pause_r1 = StatementPause(a_r1.pid, MATCH_CONFIG_READ).install()
    out_r1: dict = {}
    th_r1 = _thread(lambda: approve_top_off(fxr1.league_id, rq1.request_id,
                                            fxr1.commissioner_id, db=a_r1.db),
                    out_r1, "a")
    th_r1.start()
    pause_r1.held.wait(timeout=_DEADLINE)
    _assert("AR1 the approval is past its preliminary authority check",
            pause_r1.held.is_set(), str(pause_r1.statement))

    with SessionLocal() as rv:
        _compliant_revoke(rv, fxr1.league_id, fxr1.commissioner_id)
        rv.commit()
    _assert("AR1 the revocation committed while the approval was in flight",
            _authority_rows(fxr1.league_id) == [], str(_authority_rows(fxr1.league_id)))

    entries_before_r1 = _entry_count()
    wallet_before_r1  = _wallet_balance(fxr1.team_id)
    pause_r1.release.set()
    th_r1.join(timeout=_DEADLINE)
    pause_r1.uninstall()

    _assert("AR1 the approval raised AuthorizationAttemptAbort (by TYPE)",
            isinstance(out_r1.get("a_exc"), AuthorizationAttemptAbort),
            f"got {type(out_r1.get('a_exc')).__name__}: {out_r1.get('a_exc')}")
    _assert("AR1 the abort names the step-14 revalidation",
            "step 14" in str(out_r1.get("a_exc")), str(out_r1.get("a_exc"))[:90])
    r1row = _row(rq1.request_id)
    _assert("AR1 status is still pending",
            (r1row.decision, r1row.status) == ("pending", "pending"),
            f"{r1row.decision}/{r1row.status}")
    _assert("AR1 both linkage fields are NULL",
            r1row.ledger_posting_id is None and r1row.disclosure_event_id is None)
    _assert("AR1 ledger_entries count unchanged", _entry_count() == entries_before_r1,
            f"{entries_before_r1} -> {_entry_count()}")
    _assert("AR1 top_off_disclosure count unchanged", _disclosure_count() == 0,
            str(_disclosure_count()))
    _assert("AR1 Wallet.balance unchanged",
            _wallet_balance(fxr1.team_id) == wallet_before_r1,
            f"{wallet_before_r1} -> {_wallet_balance(fxr1.team_id)}")
    _assert("AR1 commit count 0", a_r1.commits == 0, str(a_r1.commits))
    _assert("AR1 trial_balance() is 0", trial_balance() == 0)
    a_r1.close()

    # ══════════════════════════════════════════════════════════════════════
    # AR2 — approval wins the League lock first
    # ══════════════════════════════════════════════════════════════════════
    print("\nAR2  approval holds the League lock; the revocation BLOCKS and "
          "lands only after the issuance is final")
    tdb.reset()
    fxr2 = Fixture("ar2")
    rq2 = _open_request(fxr2, 30.00)
    a_r2 = Svc()
    pause_r2 = StatementPause(a_r2.pid, MATCH_LEAGUE_LOCK).install()
    out_r2: dict = {}
    th_r2 = _thread(lambda: approve_top_off(fxr2.league_id, rq2.request_id,
                                            fxr2.commissioner_id, db=a_r2.db),
                    out_r2, "a")
    th_r2.start()
    pause_r2.held.wait(timeout=_DEADLINE)
    _assert("AR2 the approval is holding the League row at step 14",
            pause_r2.held.is_set(), str(pause_r2.statement))

    rev = Svc()
    out_rev: dict = {}
    th_rev = _thread(lambda: (_compliant_revoke(rev.db, fxr2.league_id,
                                                fxr2.commissioner_id),
                              rev.db.commit()), out_rev, "rev")
    th_rev.start()
    blocked_r2 = _blocked_by(rev.pid, a_r2.pid)
    _evidence_line("AR2", a_r2.pid, blocked_r2)
    _assert("AR2 the revocation is GENUINELY BLOCKED (observed, not timed)",
            blocked_r2 is not None,
            f"approval pid={a_r2.pid} revocation pid={rev.pid}")
    _assert("AR2 it is waiting on the leagues row",
            blocked_r2 is not None and blocked_r2[1] == "Lock"
            and "leagues" in (blocked_r2[3] or "").lower(),
            f"{None if blocked_r2 is None else blocked_r2[3]}")
    _assert("AR2 the approver still holds authority while the approval runs",
            fxr2.commissioner_id in _authority_rows(fxr2.league_id))

    pause_r2.release.set()
    th_r2.join(timeout=_DEADLINE); th_rev.join(timeout=_DEADLINE)
    pause_r2.uninstall()

    _assert("AR2 the approval committed", out_r2.get("a") is not None
            and out_r2["a"].posted is True, str(out_r2.get("a_exc")))
    r2row = _row(rq2.request_id)
    _assert("AR2 both linkage fields are non-NULL",
            r2row.ledger_posting_id is not None
            and r2row.disclosure_event_id is not None)
    legs_r2 = _legs(r2row.ledger_posting_id)
    _assert("AR2 exactly one posting of two legs summing to zero",
            len(legs_r2) == 2 and sum(c for _, c in legs_r2) == 0, str(legs_r2))
    _assert("AR2 exactly one disclosure row", _disclosure_count() == 1,
            str(_disclosure_count()))
    with SessionLocal() as db:
        cents_r2 = _balance_of_in_session(db, f"wallet:{fxr2.team_id}")
    _assert("AR2 the mirror equals the ledger balance, converted once",
            _wallet_balance(fxr2.team_id) == cents_r2 / 100.0,
            f"mirror={_wallet_balance(fxr2.team_id)} cents={cents_r2}")
    _assert("AR2 the revocation then succeeded",
            "rev_exc" not in out_rev and _authority_rows(fxr2.league_id) == [],
            f"{out_rev.get('rev_exc')} rows={_authority_rows(fxr2.league_id)}")
    _assert("AR2 THE INVARIANT: the committed issuance's approver was authorized "
            "at commit time", r2row.decided_by_user_id == fxr2.commissioner_id
            and r2row.status == "applied")
    _assert("AR2 the approval committed exactly once", a_r2.commits == 1,
            str(a_r2.commits))
    _assert("AR2 trial_balance() is 0", trial_balance() == 0)
    a_r2.close(); rev.close()

    # ══════════════════════════════════════════════════════════════════════
    # AR3 — genuine overlap, both interleavings, no deadlock
    # ══════════════════════════════════════════════════════════════════════
    print("\nAR3  two leagues, both interleavings, repeated — no deadlock, "
          "cross-league never blocks, trial balance always 0")
    deadlocks: list[str] = []
    outcomes:  list[str] = []

    # ── run 0: APPROVAL wins the League row; the revocation contends. ──
    tdb.reset()
    lg_x = Fixture("ar3x0"); lg_y = Fixture("ar3y0")
    rq_x = _open_request(lg_x, 10.00); rq_y = _open_request(lg_y, 10.00)
    ax = Svc(); ay = Svc(); rx = Svc()
    px = StatementPause(ax.pid, MATCH_LEAGUE_LOCK).install()
    o0: dict = {}
    th_ax = _thread(lambda: approve_top_off(lg_x.league_id, rq_x.request_id,
                                            lg_x.commissioner_id, db=ax.db), o0, "ax")
    th_ax.start()
    px.held.wait(timeout=_DEADLINE)

    th_ay = _thread(lambda: approve_top_off(lg_y.league_id, rq_y.request_id,
                                            lg_y.commissioner_id, db=ay.db), o0, "ay")
    th_ay.start()
    th_ay.join(timeout=_DEADLINE)
    _assert("AR3 run 0: the CROSS-LEAGUE approval completed while league X's row "
            "was held", o0.get("ay") is not None and o0["ay"].posted is True,
            str(o0.get("ay_exc")))
    _assert("AR3 run 0: it was never blocked by the league-X approval",
            ax.pid not in _blockers_of(ay.pid), str(_blockers_of(ay.pid)))

    th_rx = _thread(lambda: (_compliant_revoke(rx.db, lg_x.league_id,
                                               lg_x.commissioner_id),
                             rx.db.commit()), o0, "rx")
    th_rx.start()
    _assert("AR3 run 0: the same-league revocation BLOCKS on league X's row",
            _blocked_by(rx.pid, ax.pid) is not None,
            f"approval={ax.pid} revoke={rx.pid}")
    px.release.set()
    th_ax.join(timeout=_DEADLINE); th_rx.join(timeout=_DEADLINE)
    px.uninstall()
    deadlocks += [f"run 0 {k}: {o0[k]}" for k in ("ax_exc", "ay_exc", "rx_exc")
                  if "deadlock" in str(o0.get(k, "")).lower()]
    row_x0 = _row(rq_x.request_id)
    outcomes.append("AR2" if row_x0.status == "applied" else "AR1")
    _assert("AR3 run 0: resolved to a clean AR2 outcome (approval first), no "
            "partial state",
            row_x0.status == "applied" and row_x0.ledger_posting_id is not None
            and row_x0.disclosure_event_id is not None,
            f"status={row_x0.status}")
    _assert("AR3 run 0: trial_balance() is exactly 0", trial_balance() == 0)
    ax.close(); ay.close(); rx.close()

    # ── run 1: the REVOCATION wins the League row; the approval contends. ──
    tdb.reset()
    lg_x1 = Fixture("ar3x1"); lg_y1 = Fixture("ar3y1")
    rq_x1 = _open_request(lg_x1, 10.00); rq_y1 = _open_request(lg_y1, 10.00)
    ax1 = Svc(); ay1 = Svc(); rx1 = Svc()
    # The revocation takes and HOLDS the League row, uncommitted.
    _compliant_revoke(rx1.db, lg_x1.league_id, lg_x1.commissioner_id)
    o1: dict = {}
    th_ax1 = _thread(lambda: approve_top_off(lg_x1.league_id, rq_x1.request_id,
                                             lg_x1.commissioner_id, db=ax1.db),
                     o1, "ax")
    th_ax1.start()
    _assert("AR3 run 1: the approval BLOCKS at step 14 on the revocation's row",
            _blocked_by(ax1.pid, rx1.pid) is not None,
            f"revoke={rx1.pid} approval={ax1.pid}")

    th_ay1 = _thread(lambda: approve_top_off(lg_y1.league_id, rq_y1.request_id,
                                             lg_y1.commissioner_id, db=ay1.db),
                     o1, "ay")
    th_ay1.start()
    th_ay1.join(timeout=_DEADLINE)
    _assert("AR3 run 1: the CROSS-LEAGUE approval completed unaffected",
            o1.get("ay") is not None and o1["ay"].posted is True,
            str(o1.get("ay_exc")))
    _assert("AR3 run 1: it was never blocked by the league-X revocation",
            rx1.pid not in _blockers_of(ay1.pid), str(_blockers_of(ay1.pid)))

    rx1.db.commit()            # the revocation wins
    th_ax1.join(timeout=_DEADLINE)
    deadlocks += [f"run 1 {k}: {o1[k]}" for k in ("ax_exc", "ay_exc")
                  if "deadlock" in str(o1.get(k, "")).lower()]
    _assert("AR3 run 1: the approval aborted on authority (AR1 shape)",
            isinstance(o1.get("ax_exc"), AuthorizationAttemptAbort),
            f"got {type(o1.get('ax_exc')).__name__}: {o1.get('ax_exc')}")
    row_x1 = _row(rq_x1.request_id)
    outcomes.append("AR1" if row_x1.status == "pending" else "AR2")
    _assert("AR3 run 1: resolved to a clean AR1 outcome, no partial state",
            row_x1.status == "pending" and row_x1.ledger_posting_id is None
            and row_x1.disclosure_event_id is None, f"status={row_x1.status}")
    _assert("AR3 run 1: the approval committed nothing", ax1.commits == 0,
            str(ax1.commits))
    _assert("AR3 run 1: trial_balance() is exactly 0", trial_balance() == 0)
    ax1.close(); ay1.close(); rx1.close()

    _assert("AR3 NO DeadlockDetected in either interleaving", deadlocks == [],
            str(deadlocks))
    _assert("AR3 both interleavings ran, resolving to AR2 then AR1 — every run "
            "is exactly one of the two, never a partial",
            outcomes == ["AR2", "AR1"], str(outcomes))

    # ══════════════════════════════════════════════════════════════════════
    # AR4 — authority removed BEFORE approval begins
    # ══════════════════════════════════════════════════════════════════════
    print("\nAR4  authority removed before approval begins → abort at step 6, "
          "before any League lock and before any cap computation")
    tdb.reset()
    fxr4 = Fixture("ar4")
    rq4 = _open_request(fxr4, 10.00)
    with SessionLocal() as rv:
        _compliant_revoke(rv, fxr4.league_id, fxr4.commissioner_id)
        rv.commit()

    a_r4 = Svc()
    rec = StatementRecorder(a_r4.pid).install()
    entries_before_r4 = _entry_count()
    wallet_before_r4  = _wallet_balance(fxr4.team_id)
    try:
        approve_top_off(fxr4.league_id, rq4.request_id, fxr4.commissioner_id,
                        db=a_r4.db)
        exc_r4 = None
    except Exception as exc:                      # noqa: BLE001 — recording
        exc_r4 = exc
    finally:
        rec.uninstall()

    _assert("AR4 raises AuthorizationAttemptAbort (by TYPE)",
            isinstance(exc_r4, AuthorizationAttemptAbort),
            f"got {type(exc_r4).__name__}: {exc_r4}")
    _note(f"AR4: the approval's backend issued {len(rec.statements)} statements; "
          f"leagues-FOR-UPDATE={len(rec.matching('leagues', 'for update'))}, "
          f"snapshot-reads={len(rec.matching('league_season_topoff_config'))}")
    _assert("AR4 NO League row lock was ever acquired",
            rec.matching("leagues", "for update") == [],
            str(rec.matching("leagues", "for update")))
    _assert("AR4 NO cap computation ran — the frozen snapshot was never read",
            rec.matching("league_season_topoff_config") == [],
            str(rec.matching("league_season_topoff_config")))
    _assert("AR4 CONTROL: the recorder did see the locks taken before step 6",
            rec.matching("faab_transactions", "for update") != []
            and rec.matching("season_allocation", "for update") != [],
            f"{len(rec.statements)} statements recorded")
    r4row = _row(rq4.request_id)
    _assert("AR4 the request remains pending",
            (r4row.decision, r4row.status) == ("pending", "pending"))
    _assert("AR4 zero economic writes",
            _entry_count() == entries_before_r4
            and _wallet_balance(fxr4.team_id) == wallet_before_r4
            and _disclosure_count() == 0)
    _assert("AR4 commit count 0", a_r4.commits == 0, str(a_r4.commits))
    a_r4.close()

    # ══════════════════════════════════════════════════════════════════════
    # SA3 — a concurrent grant never invalidates a lawful self-approval
    # ══════════════════════════════════════════════════════════════════════
    print("\nSA3  a concurrent grant does NOT invalidate or abort a lawful "
          "self-approval (invariant 24)")
    tdb.reset()
    fxs3 = Fixture("sa3")
    # The commissioner requests for his own team and will approve himself.
    with SessionLocal() as db:
        rq_s3 = create_top_off_request(fxs3.league_id, fxs3.team_id,
                                       fxs3.commissioner_id, 10.00, db=db)
    newcomer = _mk_user(f"{_uniq('sa3_new')}@gg.test")

    grant = Svc()
    grant.db.execute(text("SELECT id FROM leagues WHERE id = :i FOR UPDATE"),
                     {"i": fxs3.league_id}).fetchall()
    grant.db.execute(text(
        "INSERT INTO league_commissioners "
        "(league_id, user_id, source, assigned_by_user_id, created_at) "
        "VALUES (:l, :u, 'local_grant', :b, NOW())"),
        {"l": fxs3.league_id, "u": newcomer, "b": fxs3.commissioner_id})

    a_s3 = Svc()
    out_s3: dict = {}
    th_s3 = _thread(lambda: approve_top_off(fxs3.league_id, rq_s3.request_id,
                                            fxs3.commissioner_id,
                                            "self-approved under a racing grant",
                                            db=a_s3.db), out_s3, "a")
    th_s3.start()
    blocked_s3 = _blocked_by(a_s3.pid, grant.pid)
    _evidence_line("SA3", grant.pid, blocked_s3)
    _assert("SA3 the self-approval reached its step-14 revalidation and blocked "
            "on the uncommitted grant", blocked_s3 is not None,
            f"grant pid={grant.pid} approval pid={a_s3.pid}")
    _assert("SA3 nothing was posted while it waited", _entry_count() == 3,
            str(_entry_count()))

    grant.db.commit()          # the other commissioner now exists
    th_s3.join(timeout=_DEADLINE)

    _assert("SA3 the self-approval COMMITTED NORMALLY",
            out_s3.get("a") is not None and out_s3["a"].posted is True,
            f"{type(out_s3.get('a_exc')).__name__}: {out_s3.get('a_exc')}")
    _assert("SA3 it is still classified self_approved",
            out_s3.get("a") is not None and out_s3["a"].self_approved is True)
    _assert("SA3 exactly one commit", a_s3.commits == 1, str(a_s3.commits))
    _assert("SA3 the newcomer's authority row is present — and changed nothing",
            sorted(_authority_rows(fxs3.league_id))
            == sorted([fxs3.commissioner_id, newcomer]),
            str(_authority_rows(fxs3.league_id)))
    _assert("SA3 exactly one disclosure and a balanced posting",
            _disclosure_count() == 1
            and sum(c for _, c in _legs(out_s3["a"].ledger_posting_id)) == 0)
    _assert("SA3 trial_balance() is 0", trial_balance() == 0)
    a_s3.close(); grant.close()

    # ══════════════════════════════════════════════════════════════════════
    # S2 — approval racing season close, both interleavings
    # ══════════════════════════════════════════════════════════════════════
    print("\nS2 (i)  approval holds the League row; the season close CONTENDS")
    tdb.reset()
    fxc1 = Fixture("s2a")
    rqc1 = _open_request(fxc1, 10.00)
    a_c1 = Svc()
    pause_c1 = StatementPause(a_c1.pid, MATCH_LEAGUE_LOCK).install()
    out_c1: dict = {}
    th_ac1 = _thread(lambda: approve_top_off(fxc1.league_id, rqc1.request_id,
                                             fxc1.commissioner_id, db=a_c1.db),
                     out_c1, "a")
    th_ac1.start()
    pause_c1.held.wait(timeout=_DEADLINE)

    close1 = Svc()
    th_cc1 = _thread(lambda: close_season(fxc1.league_id, "operator:test",
                                          db=close1.db), out_c1, "close")
    th_cc1.start()
    blocked_c1 = _blocked_by(close1.pid, a_c1.pid)
    _evidence_line("S2(i)", a_c1.pid, blocked_c1)
    _assert("S2(i) the season close is BLOCKED BY the in-flight approval",
            blocked_c1 is not None,
            f"approval pid={a_c1.pid} close pid={close1.pid}")

    pause_c1.release.set()
    th_ac1.join(timeout=_DEADLINE); th_cc1.join(timeout=_DEADLINE)
    pause_c1.uninstall()

    _assert("S2(i) NO deadlock — both finished without error",
            "a_exc" not in out_c1 and "close_exc" not in out_c1,
            f"{out_c1.get('a_exc')} / {out_c1.get('close_exc')}")
    _assert("S2(i) the approval committed BEFORE the close",
            out_c1.get("a") is not None and out_c1["a"].posted is True)
    _assert("S2(i) the close then closed the season",
            out_c1.get("close") is not None and out_c1["close"].closed_now is True)
    _assert("S2(i) nothing partial — one posting, one disclosure, both linkage "
            "fields",
            _disclosure_count() == 1
            and _row(rqc1.request_id).ledger_posting_id is not None
            and _row(rqc1.request_id).disclosure_event_id is not None)
    _assert("S2(i) trial_balance() is 0", trial_balance() == 0)
    a_c1.close(); close1.close()

    print("\nS2 (ii) the season close holds the League row; the approval "
          "CONTENDS and then aborts")
    tdb.reset()
    fxc2 = Fixture("s2b")
    rqc2 = _open_request(fxc2, 10.00)
    close2 = Svc()
    pause_c2 = StatementPause(close2.pid, MATCH_LEAGUE_LOCK).install()
    out_c2: dict = {}
    th_cc2 = _thread(lambda: close_season(fxc2.league_id, "operator:test",
                                          db=close2.db), out_c2, "close")
    th_cc2.start()
    pause_c2.held.wait(timeout=_DEADLINE)

    a_c2 = Svc()
    entries_before_c2 = _entry_count()
    th_ac2 = _thread(lambda: approve_top_off(fxc2.league_id, rqc2.request_id,
                                             fxc2.commissioner_id, db=a_c2.db),
                     out_c2, "a")
    th_ac2.start()
    blocked_c2 = _blocked_by(a_c2.pid, close2.pid)
    _evidence_line("S2(ii)", close2.pid, blocked_c2)
    _assert("S2(ii) the approval is BLOCKED BY the in-flight close at step 14",
            blocked_c2 is not None,
            f"close pid={close2.pid} approval pid={a_c2.pid}")

    pause_c2.release.set()
    th_cc2.join(timeout=_DEADLINE); th_ac2.join(timeout=_DEADLINE)
    pause_c2.uninstall()

    _assert("S2(ii) the close committed", out_c2.get("close") is not None
            and out_c2["close"].closed_now is True, str(out_c2.get("close_exc")))
    _assert("S2(ii) THE PROOF that step 14 re-reads under the lock: the approval "
            "raised SeasonClosedAbort",
            isinstance(out_c2.get("a_exc"), SeasonClosedAbort),
            f"got {type(out_c2.get('a_exc')).__name__}: {out_c2.get('a_exc')}")
    _assert("S2(ii) the abort names the step-14 revalidation",
            "step 14" in str(out_c2.get("a_exc")), str(out_c2.get("a_exc"))[:90])
    c2row = _row(rqc2.request_id)
    _assert("S2(ii) the request remains pending, never rejected",
            (c2row.decision, c2row.status) == ("pending", "pending"),
            f"{c2row.decision}/{c2row.status}")
    _assert("S2(ii) nothing partial — no posting, no disclosure, no linkage",
            _entry_count() == entries_before_c2 and _disclosure_count() == 0
            and c2row.ledger_posting_id is None
            and c2row.disclosure_event_id is None)
    _assert("S2(ii) zero commits on the aborted approval", a_c2.commits == 0,
            str(a_c2.commits))
    _assert("S2(ii) trial_balance() is 0", trial_balance() == 0)
    a_c2.close(); close2.close()

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