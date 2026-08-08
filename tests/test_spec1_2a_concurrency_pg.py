"""
test_spec1_2a_concurrency_pg.py — Sprint 2 Package 2A: first-valid-commit
serialization (PostgreSQL).

    C1  two concurrent counters — only one mints version 2
    C2  accept vs decline
    C3  accept vs cancel
    C4  expiry vs acceptance
    C5  UNIQUE(challenge_id, version_number) is a live structural backstop

THE RACES BUILD THEMSELVES, and that is a consequence of the design rather than
a convenience. Because the service NEVER COMMITS, a caller that invokes a
transition is left holding the challenge row lock with its work uncommitted —
which is exactly the state a real Package 2B transaction is in while it posts
escrow. A second session calling the same transition blocks on that row for real.
No cursor-event pause is needed to manufacture the overlap; the transaction
boundary the spec requires produces it.

EVIDENCE IS DIRECT, NEVER TIMED. Every blocking claim is PostgreSQL's own answer
read from a third pinned connection:

    SELECT ... FROM pg_stat_activity
    WHERE pid = :blocked AND :holder = ANY(pg_blocking_pids(pid))

No sleep is used as proof. The bounded polls wait for an observable database
condition and fail loudly if it never appears; the deadline is a failure bound.

EVERY OBSERVED SESSION IS PINNED to a Connection the test checked out, so a
backend pid read at construction is the pid that later executes the statement —
the lesson B6 Group D paid for.

§9 is what is under test: "First valid commit governs. Later callers reload the
committed result and return deterministically." So the loser of each race must
come back with an already-X answer, not an exception and not a second write.
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
    print(f"\n[HARNESS ERROR] Package 2A concurrency suite cannot run:\n  {e}")
    sys.exit(2)

_DEADLINE = 20.0
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
    from datetime import datetime, timedelta

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from db.schema import (
        SessionLocal, BeefChallenge, BeefProposal, League, Player, Roster, Team,
    )
    from beefs.proposal_lifecycle import (
        issue_proposal_challenge, counter_challenge_proposal,
        accept_locked_proposal, decline_challenge, cancel_challenge,
        expire_challenge, ProposalTerms,
        OFFERED, COUNTERED, ACCEPTED, DECLINED, CANCELLED, EXPIRED,
        MODE_LOCKED,
    )

    # ── seed ──────────────────────────────────────────────────────────────

    def _mk_league(name: str) -> int:
        with SessionLocal() as db:
            lg = League(season=2025, name=name, projection_source="fantasypros")
            db.add(lg); db.commit(); return lg.id

    def _mk_team(league_id: int, name: str) -> int:
        with SessionLocal() as db:
            t = Team(league_id=league_id, team_name=name, owner=name,
                     email=f"{name}@gg.test")
            db.add(t); db.commit(); return t.id

    def _mk_roster(team_id: int, n: int = 2) -> None:
        with SessionLocal() as db:
            for _ in range(n):
                p = Player(name=_uniq("P"), position="RB", nfl_team="SF")
                db.add(p); db.flush()
                db.add(Roster(team_id=team_id, player_id=p.id))
            db.commit()

    def _terms(cents: int = 2500) -> ProposalTerms:
        return ProposalTerms(
            anchor_stake_cents=cents, quoted_derived_stake_cents=cents,
            quoted_funded_pot_cents=cents * 2,
            anchor_odds=1.91, derived_odds=1.91,
            anchor_moneyline=-110, derived_moneyline=-110,
            pricing_model_id="mc-v1", pricing_input_hash=_uniq("h"),
        )

    class Fixture:
        def __init__(self, tag: str):
            self.league_id = _mk_league(_uniq(f"{tag}-lg"))
            self.a = _mk_team(self.league_id, _uniq(f"{tag}A"))
            self.b = _mk_team(self.league_id, _uniq(f"{tag}B"))
            _mk_roster(self.a); _mk_roster(self.b)

    class Session_:
        """One transaction owner, pinned to a Connection so its backend pid is
        stable — the stand-in for a Package 2B transaction."""

        def __init__(self):
            self.conn = tdb.engine.connect()
            self.pid = self.conn.execute(text("SELECT pg_backend_pid()")).scalar()
            self.conn.rollback()
            self.db = SessionLocal(bind=self.conn)

        def commit(self):
            self.db.commit()

        def rollback(self):
            self.db.rollback()

        def close(self):
            self.db.close()
            self.conn.close()

    # ── the observing connection ──────────────────────────────────────────
    probe = tdb.engine.connect()
    probe_pid = probe.execute(text("SELECT pg_backend_pid()")).scalar()
    probe.rollback()

    def _blocked_by(blocked_pid: int, holder_pid: int):
        end = time.monotonic() + _DEADLINE
        while time.monotonic() < end:
            row = probe.execute(text("""
                SELECT pid, wait_event_type, state, query
                FROM pg_stat_activity
                WHERE pid = :blocked AND :holder = ANY(pg_blocking_pids(pid))
            """), {"blocked": blocked_pid, "holder": holder_pid}).fetchone()
            probe.rollback()
            if row is not None:
                return row
        return None

    def _evidence_line(tag: str, holder_pid, row) -> None:
        if row is None:
            _note(f"{tag}: holder pid={holder_pid} blocked pid=NONE OBSERVED")
            return
        _note(f"{tag}: holder pid={holder_pid} blocked pid={row[0]} "
              f"wait={row[1]} state={row[2]!r}")
        _note(f"{tag}: blocked statement = {' '.join((row[3] or '').split())[:100]}")

    def _issue(fx, *, lock_at=None, now=None) -> int:
        s = Session_()
        try:
            res = issue_proposal_challenge(
                league_id=fx.league_id, week=1,
                challenger_team_id=fx.a, challenged_team_id=fx.b,
                challenge_mode=MODE_LOCKED, wager_type="straight",
                terms=_terms(), db=s.db, proposal_lock_at=lock_at,
                schedule_source_ref="sched", now=now)
            s.commit()
            return res.challenge_id
        finally:
            s.close()

    def _thread(fn, out: dict, key: str):
        def _runner():
            try:
                out[key] = fn()
            except Exception as exc:              # noqa: BLE001 — recording
                out[f"{key}_exc"] = exc
        return threading.Thread(target=_runner, daemon=True)

    def _status(cid: int) -> str:
        with SessionLocal() as db:
            return db.query(BeefChallenge).filter(
                BeefChallenge.id == cid).one().response_status

    def _versions(cid: int) -> list:
        with SessionLocal() as db:
            return [p.version_number for p in
                    db.query(BeefProposal).filter(
                        BeefProposal.challenge_id == cid)
                    .order_by(BeefProposal.version_number).all()]

    def _race(tag, cid, a_call, b_call, a_session, b_session):
        """A holds the challenge row uncommitted; B blocks on it; A commits; B
        resolves. Returns (result_a, result_b_or_exc)."""
        out: dict = {}
        res_a = a_call(a_session.db)              # takes FOR UPDATE, no commit
        th_b = _thread(lambda: b_call(b_session.db), out, "b")
        th_b.start()
        blocked = _blocked_by(b_session.pid, a_session.pid)
        _evidence_line(tag, a_session.pid, blocked)
        _assert(f"{tag} the second caller is BLOCKED BY the first",
                blocked is not None,
                f"A pid={a_session.pid} B pid={b_session.pid}")
        _assert(f"{tag} the wait is a Lock wait on beef_challenges",
                blocked is not None and blocked[1] == "Lock"
                and "beef_challenges" in (blocked[3] or "").lower(),
                f"{None if blocked is None else blocked[3]}")
        a_session.commit()                        # first valid commit governs
        th_b.join(timeout=_DEADLINE)
        b_session.commit()
        return res_a, out.get("b"), out.get("b_exc")

    # ══════════════════════════════════════════════════════════════════════
    # C1 — two concurrent counters
    # ══════════════════════════════════════════════════════════════════════
    print("\nC1   two concurrent counters — only one mints version 2 (§9)")
    tdb.reset()
    fx = Fixture("c1")
    cid = _issue(fx)
    a, b = Session_(), Session_()
    res_a, res_b, exc_b = _race(
        "C1", cid,
        lambda db: counter_challenge_proposal(
            challenge_id=cid, actor_team_id=fx.b, terms=_terms(4000), db=db),
        lambda db: counter_challenge_proposal(
            challenge_id=cid, actor_team_id=fx.b, terms=_terms(9000), db=db),
        a, b)

    _assert("C1 the winner created version 2",
            res_a.changed is True and res_a.version_number == 2,
            str(res_a))
    _assert("C1 the loser did not raise", exc_b is None,
            f"{type(exc_b).__name__}: {exc_b}")
    _assert("C1 the loser returns deterministically 'already countered'",
            res_b is not None and res_b.changed is False
            and res_b.replayed is True and res_b.detail == "already countered",
            str(getattr(res_b, "detail", None)))
    _assert("C1 exactly TWO proposals exist — no second version 2",
            _versions(cid) == [1, 2], str(_versions(cid)))
    _assert("C1 the challenge is countered once", _status(cid) == COUNTERED)
    with SessionLocal() as db:
        v2 = db.query(BeefProposal).filter(
            BeefProposal.challenge_id == cid,
            BeefProposal.version_number == 2).one()
    _assert("C1 the surviving version 2 carries the WINNER's terms, not the "
            "loser's", v2.anchor_stake_cents == 4000,
            str(v2.anchor_stake_cents))
    a.close(); b.close()

    # ══════════════════════════════════════════════════════════════════════
    # C2 — accept vs decline
    # ══════════════════════════════════════════════════════════════════════
    print("\nC2   accept vs decline — first valid commit governs")
    tdb.reset()
    fx = Fixture("c2")
    cid = _issue(fx)
    a, b = Session_(), Session_()
    res_a, res_b, exc_b = _race(
        "C2", cid,
        lambda db: accept_locked_proposal(
            challenge_id=cid, actor_team_id=fx.b, db=db),
        lambda db: decline_challenge(
            challenge_id=cid, actor_team_id=fx.b, db=db),
        a, b)

    _assert("C2 the acceptance won", res_a.response_status == ACCEPTED)
    _assert("C2 the decline did not raise", exc_b is None,
            f"{type(exc_b).__name__}: {exc_b}")
    _assert("C2 the decline returns 'already accepted' and writes nothing",
            res_b is not None and res_b.changed is False
            and res_b.detail == "already accepted",
            str(getattr(res_b, "detail", None)))
    _assert("C2 the committed state is accepted, not declined",
            _status(cid) == ACCEPTED, _status(cid))
    a.close(); b.close()

    # The other ordering: decline first, acceptance second.
    cid = _issue(fx)
    a, b = Session_(), Session_()
    res_a, res_b, exc_b = _race(
        "C2b", cid,
        lambda db: decline_challenge(
            challenge_id=cid, actor_team_id=fx.b, db=db),
        lambda db: accept_locked_proposal(
            challenge_id=cid, actor_team_id=fx.b, db=db),
        a, b)
    _assert("C2b with the decline first, the acceptance yields 'already "
            "declined'",
            exc_b is None and res_b.changed is False
            and res_b.detail == "already declined",
            str(getattr(res_b, "detail", None)))
    with SessionLocal() as db:
        acc_b = db.query(BeefChallenge).filter(
            BeefChallenge.id == cid).one().accepted_proposal_id
    _assert("C2b the committed state is declined and nothing was accepted",
            _status(cid) == DECLINED and acc_b is None,
            f"{_status(cid)} / accepted={acc_b}")
    a.close(); b.close()

    # ══════════════════════════════════════════════════════════════════════
    # C3 — accept vs cancel
    # ══════════════════════════════════════════════════════════════════════
    print("\nC3   accept vs cancel — first valid commit governs")
    tdb.reset()
    fx = Fixture("c3")
    cid = _issue(fx)
    a, b = Session_(), Session_()
    res_a, res_b, exc_b = _race(
        "C3", cid,
        lambda db: cancel_challenge(
            challenge_id=cid, actor_team_id=fx.a, db=db),
        lambda db: accept_locked_proposal(
            challenge_id=cid, actor_team_id=fx.b, db=db),
        a, b)

    _assert("C3 the cancel won", res_a.response_status == CANCELLED)
    _assert("C3 the acceptance returns 'already cancelled', not an exception",
            exc_b is None and res_b is not None and res_b.changed is False
            and res_b.detail == "already cancelled",
            f"{type(exc_b).__name__}: {getattr(res_b, 'detail', None)}")
    _assert("C3 the committed state is cancelled and nothing was accepted",
            _status(cid) == CANCELLED)
    with SessionLocal() as db:
        acc = db.query(BeefChallenge).filter(
            BeefChallenge.id == cid).one().accepted_proposal_id
    _assert("C3 accepted_proposal_id was never set", acc is None, str(acc))
    a.close(); b.close()

    # ══════════════════════════════════════════════════════════════════════
    # C4 — expiry vs acceptance
    # ══════════════════════════════════════════════════════════════════════
    print("\nC4   expiry vs acceptance — never both")
    tdb.reset()
    fx = Fixture("c4")
    base = datetime(2026, 9, 13, 12, 0, 0)
    past = base + timedelta(minutes=90)          # after the 60-minute TTL

    # Expiry wins: the acceptance that follows must be refused deterministically.
    cid = _issue(fx, now=base)
    a, b = Session_(), Session_()
    res_a, res_b, exc_b = _race(
        "C4", cid,
        lambda db: expire_challenge(challenge_id=cid, db=db, now=past),
        lambda db: accept_locked_proposal(
            challenge_id=cid, actor_team_id=fx.b, db=db, now=past),
        a, b)
    _assert("C4 the expiry won", res_a.response_status == EXPIRED)
    _assert("C4 the acceptance returns 'already expired'",
            exc_b is None and res_b is not None and res_b.changed is False
            and res_b.detail == "already expired",
            f"{type(exc_b).__name__}: {getattr(res_b, 'detail', None)}")
    _assert("C4 the committed state is expired", _status(cid) == EXPIRED)
    a.close(); b.close()

    # Acceptance wins: the expiry that follows must NOT expire an accepted
    # wager — §4 keeps `accepted` out of the negotiation-terminal set precisely
    # so settlement is never blocked by it.
    cid = _issue(fx, now=base)
    a, b = Session_(), Session_()
    res_a, res_b, exc_b = _race(
        "C4b", cid,
        lambda db: accept_locked_proposal(
            challenge_id=cid, actor_team_id=fx.b, db=db, now=base),
        lambda db: expire_challenge(challenge_id=cid, db=db, now=past),
        a, b)
    _assert("C4b the acceptance won", res_a.response_status == ACCEPTED)
    _assert("C4b the expiry returns 'already accepted' and does NOT expire it",
            exc_b is None and res_b is not None and res_b.changed is False
            and res_b.detail == "already accepted",
            f"{type(exc_b).__name__}: {getattr(res_b, 'detail', None)}")
    _assert("C4b the accepted wager survives the expiry attempt",
            _status(cid) == ACCEPTED, _status(cid))
    a.close(); b.close()

    # ══════════════════════════════════════════════════════════════════════
    # C5 — the UNIQUE version backstop is live
    # ══════════════════════════════════════════════════════════════════════
    print("\nC5   UNIQUE(challenge_id, version_number) is a live structural "
          "backstop (§3.4, §9)")
    tdb.reset()
    fx = Fixture("c5")
    cid = _issue(fx)

    # A writer that BYPASSES the challenge row lock — corruption, not a lawful
    # concurrent counter — plants version 2 directly. The service must then fail
    # loudly on the index rather than silently producing a duplicate version.
    with SessionLocal() as db:
        db.add(BeefProposal(
            challenge_id=cid, version_number=2, version_kind="counter",
            proposing_team_id=fx.b,
            created_at=datetime(2026, 9, 13, 12, 0, 0)))
        db.commit()
    _assert("C5 a raw version-2 row was planted, bypassing the lock",
            _versions(cid) == [1, 2], str(_versions(cid)))

    s = Session_()
    try:
        counter_challenge_proposal(challenge_id=cid, actor_team_id=fx.b,
                                   terms=_terms(4000), db=s.db)
        exc = None
    except Exception as e:                        # noqa: BLE001 — recording
        exc = e
    finally:
        s.rollback()

    _assert("C5 the service did NOT swallow the integrity failure",
            isinstance(exc, IntegrityError), f"got {type(exc).__name__}: {exc}")
    _assert("C5 it was the version uniqueness guard that fired",
            exc is not None and "uq_beef_proposal_version" in str(exc),
            str(exc)[:120])
    s.close()
    _assert("C5 no third proposal survives the failed attempt",
            _versions(cid) == [1, 2], str(_versions(cid)))
    _assert("C5 the challenge is untouched by the failed attempt",
            _status(cid) == OFFERED, _status(cid))

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
