"""
test_p1_l7_wallet_lock_discipline_pg.py — P1-L7 targeted suite.

CONTROLLING RULE (Foundation Correction Plan, Section 4):

    "Row-lock the money-path reads that precede a posting, on ascending team_id.
     Do not rely on the isolation level."

    "The mutex is the Wallet row's existence, not its value. The row is
     team-keyed (12 rows); the funding scope is team-season. Confirm the row
     grain is at least as coarse as the funding scope ... Guarantee the row's
     presence by constraint, not by seeding." (Obligation 4, OPR-5)

    Test obligation: "Two racing issues by one team cannot both pass the funds
    check. Two concurrent accepts by overlapping teams serialize by ascending
    team_id with no deadlock. The test passes on the explicit lock, not on the
    isolation set — a REPEATABLE-READ-non-reliance assertion."

WHY REAL THREADS AND REAL POSTGRES. P1-L7 is a concurrency primitive. A
single-threaded test can prove the SQL says FOR UPDATE, but it cannot prove two
transactions actually serialize — and SQLite renders no FOR UPDATE clause at all,
so on SQLite every assertion below would pass vacuously against a no-op. Every
concurrency scenario here runs two real threads on two real Postgres connections.

WHAT IS AND IS NOT PROVEN HERE. P1-L7 is the concurrency substrate only. This
suite asserts the mutex exists, is ordered, is transaction-local, and fails
closed. L7-11/L7-12 are scope fences asserting P1-L4 has NOT begun: no
issue-time challenge escrow, no escrow:challenge: account, no _challenge_reserved
retirement, no proposal-to-Bet migration.

    $env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5433/fantasy_test"
    python test_p1_l7_wallet_lock_discipline_pg.py
"""

from __future__ import annotations

import ast
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST — db.schema binds its engine at import time.
from test_support_postgres import setup_postgres_test_db

tdb = setup_postgres_test_db()

# Teardown even on an unhandled exception. Without this, a crash mid-suite leaves
# the harness-created tables behind, and setup's empty-database guard then
# refuses every subsequent run until the schema is dropped by hand. drop_all
# defaults to checkfirst=True, so the explicit teardown at the end and this one
# are safe together.
import atexit
atexit.register(lambda: tdb.teardown())

from sqlalchemy import inspect, text

from db.schema import Base, League, Matchup, Team, Wallet
from ledger.ledger import (
    WalletMutexMissingError,
    _balance_of_in_session,
    balance_of,
    lock_funding_scopes,
    post as ledger_post,
    trial_balance,
)

REPO = Path(__file__).resolve().parent

_passes = 0
_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global _passes
    if condition:
        _passes += 1
        print(f"  [PASS] {label}" + (f" — {detail}" if detail else ""))
    else:
        _failures.append(label)
        print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{title}")


# ──────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

def seed_league(team_specs: list[tuple[str, int]]) -> dict[str, int]:
    """Create a league + teams + wallets. team_specs is [(name, ledger_cents)].

    The float Wallet.balance mirror is seeded DELIBERATELY WRONG (a large value
    that would authorize anything) on every wallet, so that any assertion below
    which passes could not have passed by consulting the float. P1-L7 must not
    reintroduce float authority that P1-L3B removed.
    """
    ids: dict[str, int] = {}
    with tdb.SessionLocal() as db:
        league = League(season=2025, name="P1-L7 League")
        db.add(league)
        db.flush()
        for name, cents in team_specs:
            team = Team(
                league_id=league.id,
                team_name=name,
                owner=f"owner-{name}",
                email=f"{name}@p1l7.test",
            )
            db.add(team)
            db.flush()
            db.add(Wallet(team_id=team.id, balance=99_999.0))   # wrong on purpose
            if cents:
                ledger_post(
                    [("world", -cents), (f"wallet:{team.id}", cents)],
                    door="buy_in_paid",
                    session=db,
                )
            ids[name] = team.id
        ids["_league"] = league.id
        db.commit()
    return ids


def spend(team_id: int, cents: int, escrow_tag: str, barrier: threading.Barrier,
          results: dict, key: str, hold: float = 0.35) -> None:
    """One worker: take the P1-L7 mutex, read the authoritative balance under it,
    decide, and post — all in ONE transaction, exactly the shape the production
    money paths now use.

    The two workers meet at `barrier` immediately BEFORE the lock so they contend
    for real. `hold` keeps the winner's transaction open past the loser's lock
    attempt, so a missing lock would let the loser read a stale balance — that is
    what makes C1 a real test rather than an accidental serialization.
    """
    try:
        with tdb.SessionLocal() as db:
            barrier.wait(timeout=20)
            lock_funding_scopes(db, team_id)
            available = _balance_of_in_session(db, f"wallet:{team_id}")
            results[f"{key}_saw"] = available
            if available < cents:
                results[key] = "refused"
                db.rollback()
                return
            time.sleep(hold)
            ledger_post(
                [(f"wallet:{team_id}", -cents), (f"escrow:{escrow_tag}", cents)],
                door="wager_placed",
                session=db,
            )
            db.commit()
            results[key] = "committed"
    except Exception as exc:                       # noqa: BLE001 — recorded, asserted on
        results[key] = f"error:{type(exc).__name__}"
        results[f"{key}_exc"] = str(exc)


def run_pair(target, a_kwargs: dict, b_kwargs: dict) -> dict:
    results: dict = {}
    barrier = threading.Barrier(2)
    ta = threading.Thread(target=target, kwargs={**a_kwargs, "barrier": barrier,
                                                 "results": results, "key": "a"})
    tb = threading.Thread(target=target, kwargs={**b_kwargs, "barrier": barrier,
                                                 "results": results, "key": "b"})
    ta.start(); tb.start()
    ta.join(timeout=60); tb.join(timeout=60)
    results["_alive"] = ta.is_alive() or tb.is_alive()
    return results


def source_of(func) -> str:
    import inspect as _inspect
    return _inspect.getsource(func)


# ──────────────────────────────────────────────────────────────────────────────
# L7-1 — the mutex is a real row-level update lock on the Wallet ROW
# ──────────────────────────────────────────────────────────────────────────────
section("L7-1: the mutex query requests a row-level update lock on the Wallet row")

tdb.reset()
ids = seed_league([("alpha", 10_000)])

compiled_sql: list[str] = []
with tdb.SessionLocal() as db:
    q = db.query(Wallet).filter(Wallet.team_id == ids["alpha"]).with_for_update()
    compiled_sql.append(str(q.statement.compile(tdb.engine)))

sql = compiled_sql[0].upper()
check("L7-1: the locking query compiles to SQL containing FOR UPDATE on Postgres",
      "FOR UPDATE" in sql, sql.replace("\n", " ")[-60:])
check("L7-1: the lock targets the wallets ROW, not a balance column",
      "FROM WALLETS" in sql and "BALANCE" not in sql.split("FROM WALLETS")[1],
      "no balance column in the locked selection's predicate/lock clause")

src = source_of(lock_funding_scopes)
check("L7-1: lock_funding_scopes uses with_for_update()",
      "with_for_update()" in src)
check("L7-1: lock_funding_scopes uses populate_existing() (no pre-lock snapshot)",
      "populate_existing()" in src)
# AST, not string matching: the docstring legitimately NAMES Wallet.balance to
# record that it is not authoritative. What must be absent is an actual attribute
# access in executable code.
_ledger_text = (REPO / "ledger" / "ledger.py").read_text(encoding="utf-8")
_lock_node = next(n for n in ast.walk(ast.parse(_ledger_text))
                  if isinstance(n, ast.FunctionDef) and n.name == "lock_funding_scopes")
_balance_attrs = [n for n in ast.walk(_lock_node)
                  if isinstance(n, ast.Attribute) and n.attr == "balance"]
check("L7-1: lock_funding_scopes makes zero .balance attribute accesses — the "
      "mutex is the row's existence, never its value",
      not _balance_attrs, f"found {len(_balance_attrs)}")
check("L7-1: lock_funding_scopes never commits, flushes or rolls back "
      "(transaction-local, caller-owned)",
      not any(t in src for t in ("db.commit(", "db.flush(", "db.rollback(")))

# The AST proof that the primitive's ONLY lock target is Wallet.
tree = ast.parse((REPO / "ledger" / "ledger.py").read_text(encoding="utf-8"))
lock_fn = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "lock_funding_scopes")
queried = {n.args[0].id for n in ast.walk(lock_fn)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "query" and n.args and isinstance(n.args[0], ast.Name)}
check("L7-1: the primitive locks exactly one model, and it is Wallet",
      queried == {"Wallet"}, str(sorted(queried)))


# ──────────────────────────────────────────────────────────────────────────────
# L7-2 — Wallet uniqueness / existence
# ──────────────────────────────────────────────────────────────────────────────
section("L7-2: Wallet uniqueness is schema-enforced; existence fails closed")

insp = inspect(tdb.engine)
uniques = insp.get_unique_constraints("wallets")
indexes = insp.get_indexes("wallets")
unique_on_team = (
    any(u["column_names"] == ["team_id"] for u in uniques)
    or any(i["column_names"] == ["team_id"] and i.get("unique") for i in indexes)
)
check("L7-2: wallets.team_id carries a database UNIQUE constraint — at most one "
      "Wallet row per team, enforced by the schema, not by convention",
      unique_on_team, f"uniques={uniques} unique_indexes="
                      f"{[i['name'] for i in indexes if i.get('unique')]}")

team_id_col = next(c for c in insp.get_columns("wallets") if c["name"] == "team_id")
check("L7-2: wallets.team_id is NOT NULL — no wallet floats free of a team",
      not team_id_col["nullable"])

with tdb.SessionLocal() as db:
    dupe_refused = False
    try:
        db.add(Wallet(team_id=ids["alpha"], balance=1.0))
        db.commit()
    except Exception:
        dupe_refused = True
        db.rollback()
check("L7-2: a SECOND Wallet row for the same team is refused by the database",
      dupe_refused, "the 'at most one' half of the grain is structural")

# The 'at least one' half has no constraint — so the lock must fail closed.
with tdb.SessionLocal() as db:
    orphan = Team(league_id=ids["_league"], team_name="walletless",
                  owner="nobody", email="walletless@p1l7.test")
    db.add(orphan)
    db.commit()
    orphan_id = orphan.id

with tdb.SessionLocal() as db:
    raised = None
    try:
        lock_funding_scopes(db, orphan_id)
    except WalletMutexMissingError as exc:
        raised = exc
check("L7-2: a team with NO Wallet row raises WalletMutexMissingError rather than "
      "silently locking nothing", raised is not None, str(raised)[:90])
check("L7-2: WalletMutexMissingError is a ValueError subclass (exception family "
      "preserved — no route turns 4xx into 5xx)",
      issubclass(WalletMutexMissingError, ValueError))

# Positive control: the same call succeeds for a team that HAS a wallet, so the
# assertion above is about the missing row and not a broken primitive.
with tdb.SessionLocal() as db:
    ok = lock_funding_scopes(db, ids["alpha"])
check("L7-2 positive control: the identical call succeeds for a seeded team",
      ok == [ids["alpha"]], str(ok))

# Grain: team_id already encodes team-season, so the row is not finer than scope.
with tdb.SessionLocal() as db:
    n_leagues = db.execute(text(
        "SELECT COUNT(DISTINCT league_id) FROM teams WHERE id = :t"), {"t": ids["alpha"]}
    ).scalar()
    n_seasons = db.execute(text(
        "SELECT COUNT(DISTINCT l.season) FROM leagues l JOIN teams t ON t.league_id = l.id "
        "WHERE t.id = :t"), {"t": ids["alpha"]}
    ).scalar()
    n_wallets = db.execute(text(
        "SELECT COUNT(*) FROM wallets WHERE team_id = :t"), {"t": ids["alpha"]}
    ).scalar()
check("L7-2: one team maps to exactly one league and one season — team_id already "
      "encodes the team-season funding scope",
      n_leagues == 1 and n_seasons == 1, f"leagues={n_leagues} seasons={n_seasons}")
check("L7-2: that team-season scope maps to exactly one Wallet row — row grain "
      "equals funding scope, never finer",
      n_wallets == 1, f"wallets={n_wallets}")


# ──────────────────────────────────────────────────────────────────────────────
# C1 — same Wallet, two distinct events, combined amount exceeds balance
# ──────────────────────────────────────────────────────────────────────────────
section("C1: same funding scope, two distinct concurrent events, both individually "
        "valid, combined over balance")

tdb.reset()
ids = seed_league([("solo", 10_000)])          # $100.00
res = run_pair(
    spend,
    {"team_id": ids["solo"], "cents": 7_000, "escrow_tag": "c1a"},
    {"team_id": ids["solo"], "cents": 7_000, "escrow_tag": "c1b"},
)
outcomes = [res.get("a"), res.get("b")]
committed = [o for o in outcomes if o == "committed"]

check("C1: neither worker hung (no deadlock, no lock-wait timeout)",
      not res["_alive"], str(outcomes))
check("C1: BOTH did not commit — at most one funding operation succeeded",
      len(committed) <= 1, str(outcomes))
check("C1: exactly one committed and the other was refused/rejected",
      len(committed) == 1 and len(outcomes) == 2, str(outcomes))

with tdb.SessionLocal() as db:
    final = _balance_of_in_session(db, f"wallet:{ids['solo']}")
    n_post = db.execute(text(
        "SELECT COUNT(*) FROM ledger_entries WHERE account = :a"),
        {"a": f"wallet:{ids['solo']}"}).scalar()
check("C1: final ledger balance never went negative", final >= 0, f"got {final}")
check("C1: final balance is exactly one 7000c debit against 10000c",
      final == 3_000, f"got {final}")
check("C1: the loser left NO partial posting behind",
      n_post == 2, f"wallet legs = {n_post} (1 funding credit + 1 debit)")
check("C1: trial balance still closes to zero", trial_balance() == 0,
      f"got {trial_balance()}")
check("C1: the loser observed the WINNER's committed balance, not the stale "
      "pre-debit one — this is the lock working, not luck",
      sorted([res.get("a_saw"), res.get("b_saw")]) == [3_000, 10_000],
      f"observed {sorted([res.get('a_saw'), res.get('b_saw')])}")


# ──────────────────────────────────────────────────────────────────────────────
# C2 — same Wallet, enough funds for both
# ──────────────────────────────────────────────────────────────────────────────
section("C2: same funding scope, two distinct concurrent events, balance covers both")

tdb.reset()
ids = seed_league([("plenty", 10_000)])        # $100.00
res = run_pair(
    spend,
    {"team_id": ids["plenty"], "cents": 3_000, "escrow_tag": "c2a"},
    {"team_id": ids["plenty"], "cents": 4_000, "escrow_tag": "c2b"},
)
outcomes = [res.get("a"), res.get("b")]

check("C2: neither worker hung", not res["_alive"], str(outcomes))
check("C2: BOTH committed — sufficient funds means serialization, not refusal",
      outcomes == ["committed", "committed"], str(outcomes))

seen = sorted([res.get("a_saw"), res.get("b_saw")])
check("C2: they serialized rather than both reading the opening balance — the "
      "second observed a balance consistent with the first's commit",
      seen in ([3_000, 10_000], [6_000, 10_000], [7_000, 10_000]),
      f"observed {seen}")
check("C2: neither observed a balance that ignored the other's committed debit",
      seen[0] != 10_000, f"observed {seen}")

with tdb.SessionLocal() as db:
    final = _balance_of_in_session(db, f"wallet:{ids['plenty']}")
check("C2: final balance == initial − both commitments (10000 − 3000 − 4000)",
      final == 3_000, f"got {final}")
check("C2: trial balance still closes to zero", trial_balance() == 0,
      f"got {trial_balance()}")


# ──────────────────────────────────────────────────────────────────────────────
# C3 — opposite participant ordering, two-Wallet operation
# ──────────────────────────────────────────────────────────────────────────────
section("C3: two-Wallet operation from opposite logical directions — deterministic "
        "order prevents inversion")

tdb.reset()
ids = seed_league([("home", 10_000), ("away", 10_000)])
low, high = sorted([ids["home"], ids["away"]])


def two_scope(first: int, second: int, barrier: threading.Barrier,
              results: dict, key: str) -> None:
    """Lock two scopes, passing them in the caller's own (opposite) order. If the
    primitive honored argument order instead of imposing ascending team_id, these
    two workers would hold one lock each and wait forever on the other."""
    try:
        with tdb.SessionLocal() as db:
            barrier.wait(timeout=20)
            acquired = lock_funding_scopes(db, first, second)
            results[f"{key}_order"] = acquired
            time.sleep(0.30)                       # hold both, overlap the peer
            _balance_of_in_session(db, f"wallet:{first}")
            db.commit()
            results[key] = "committed"
    except Exception as exc:                       # noqa: BLE001
        results[key] = f"error:{type(exc).__name__}"
        results[f"{key}_exc"] = str(exc)


res = run_pair(
    two_scope,
    {"first": ids["home"], "second": ids["away"]},   # challenger-first
    {"first": ids["away"], "second": ids["home"]},   # challenged-first (inverted)
)
outcomes = [res.get("a"), res.get("b")]

check("C3: neither worker hung — no deadlock between opposite-direction callers",
      not res["_alive"], str(outcomes))
check("C3: both two-Wallet operations completed", outcomes == ["committed", "committed"],
      str(outcomes))
check("C3: worker A acquired in ascending team_id despite descending arguments",
      res.get("a_order") == [low, high], str(res.get("a_order")))
check("C3: worker B acquired in the SAME ascending order despite the opposite "
      "argument order — role never reaches the ordering",
      res.get("b_order") == [low, high], str(res.get("b_order")))
check("C3: both workers agree on the acquisition order",
      res.get("a_order") == res.get("b_order"))

with tdb.SessionLocal() as db:
    dupe = lock_funding_scopes(db, high, low, high, low)
check("C3: duplicate scopes de-duplicate — one lock per scope, still ascending",
      dupe == [low, high], str(dupe))
check("C3: trial balance still closes to zero", trial_balance() == 0)


# ──────────────────────────────────────────────────────────────────────────────
# L7-3 — the lock is transaction-local and released only by commit/rollback
# ──────────────────────────────────────────────────────────────────────────────
section("L7-3: the mutex is transaction-local — released by commit/rollback, and "
        "by nothing else")

tdb.reset()
ids = seed_league([("txn", 5_000)])

holder_ready = threading.Event()
holder_release = threading.Event()
timing: dict = {}


def holder() -> None:
    with tdb.SessionLocal() as db:
        lock_funding_scopes(db, ids["txn"])
        holder_ready.set()
        holder_release.wait(timeout=20)
        db.commit()
    timing["holder_done"] = time.monotonic()


def waiter() -> None:
    holder_ready.wait(timeout=20)
    with tdb.SessionLocal() as db:
        t0 = time.monotonic()
        lock_funding_scopes(db, ids["txn"])
        timing["waiter_acquired"] = time.monotonic()
        timing["waited"] = timing["waiter_acquired"] - t0
        db.commit()


th, tw = threading.Thread(target=holder), threading.Thread(target=waiter)
th.start(); tw.start()
holder_ready.wait(timeout=20)
time.sleep(0.40)                       # waiter is now blocked on the held lock
blocked_during_hold = "waiter_acquired" not in timing
holder_release.set()
th.join(timeout=30); tw.join(timeout=30)

check("L7-3: a second transaction BLOCKS while the first holds the mutex",
      blocked_during_hold, "waiter had not acquired after 0.40s of contention")
check("L7-3: the waiter acquires once the holder commits",
      "waiter_acquired" in timing, f"waited {timing.get('waited', -1):.2f}s")
check("L7-3: the waiter's wait is attributable to the holder, not to a timeout",
      timing.get("waited", 0) >= 0.30, f"waited {timing.get('waited', -1):.2f}s")

# Rollback must release it too — otherwise a refused funding attempt would wedge
# the scope for every later caller.
with tdb.SessionLocal() as db_a:
    lock_funding_scopes(db_a, ids["txn"])
    db_a.rollback()
    with tdb.SessionLocal() as db_b:
        released = lock_funding_scopes(db_b, ids["txn"])
        db_b.rollback()
check("L7-3: rollback releases the mutex — a refused attempt does not wedge the scope",
      released == [ids["txn"]])


# ──────────────────────────────────────────────────────────────────────────────
# L7-4 — the proof rests on the lock, not on REPEATABLE READ
# ──────────────────────────────────────────────────────────────────────────────
section("L7-4: REPEATABLE-READ non-reliance — the control is the explicit lock")

tdb.reset()
ids = seed_league([("iso", 10_000)])


def spend_unlocked(team_id: int, cents: int, escrow_tag: str,
                   barrier: threading.Barrier, results: dict, key: str) -> None:
    """The SAME shape as spend(), with the lock removed and REPEATABLE READ set
    instead. This is the pre-P1-L7 world. If it also produced exactly one commit,
    C1 would prove nothing about the lock."""
    try:
        with tdb.SessionLocal() as db:
            db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            barrier.wait(timeout=20)
            available = _balance_of_in_session(db, f"wallet:{team_id}")
            results[f"{key}_saw"] = available
            if available < cents:
                results[key] = "refused"
                db.rollback()
                return
            time.sleep(0.35)
            ledger_post(
                [(f"wallet:{team_id}", -cents), (f"escrow:{escrow_tag}", cents)],
                door="wager_placed", session=db,
            )
            db.commit()
            results[key] = "committed"
    except Exception as exc:                       # noqa: BLE001
        results[key] = f"error:{type(exc).__name__}"


res_iso = run_pair(
    spend_unlocked,
    {"team_id": ids["iso"], "cents": 7_000, "escrow_tag": "isoa"},
    {"team_id": ids["iso"], "cents": 7_000, "escrow_tag": "isob"},
)
iso_saw = sorted([res_iso.get("a_saw"), res_iso.get("b_saw")])
check("L7-4: WITHOUT the lock, both racers read the same stale opening balance — "
      "REPEATABLE READ alone does not serialize this decision",
      iso_saw == [10_000, 10_000], f"observed {iso_saw}")

# The unlocked run is diagnostic, not a licence to leave the ledger dirty.
tdb.reset()
ids = seed_league([("iso2", 10_000)])
res_locked = run_pair(
    spend,
    {"team_id": ids["iso2"], "cents": 7_000, "escrow_tag": "loka"},
    {"team_id": ids["iso2"], "cents": 7_000, "escrow_tag": "lokb"},
)
lok_saw = sorted([res_locked.get("a_saw"), res_locked.get("b_saw")])
check("L7-4: WITH the lock, the same race produces two DIFFERENT observed "
      "balances — the divergence between these two runs is the lock's whole "
      "contribution",
      lok_saw == [3_000, 10_000] and iso_saw != lok_saw,
      f"unlocked {iso_saw} vs locked {lok_saw}")
check("L7-4: and only one of the locked pair committed",
      [res_locked.get("a"), res_locked.get("b")].count("committed") == 1)

src_beef = (REPO / "beefs" / "beef_engine.py").read_text(encoding="utf-8")
check("L7-4: the accept path takes the mutex, and does not merely set an "
      "isolation level",
      "lock_funding_scopes(db, challenge.challenger_team_id, "
      "challenge.challenged_team_id)" in src_beef)


# ──────────────────────────────────────────────────────────────────────────────
# C4 — P1-L6 event idempotency is not weakened or bypassed
# ──────────────────────────────────────────────────────────────────────────────
section("C4: the new lock discipline does not weaken P1-L6 event identity")

tdb.reset()
ids = seed_league([("evt", 10_000)])

import uuid as _uuid

from db.schema import LedgerPostingBatch, ProtocolEvent

C4_EVENT = _uuid.UUID("00000000-0000-4000-8000-0000000010e7")   # ProtocolEvent.event_id is Uuid

with tdb.SessionLocal() as db:
    lock_funding_scopes(db, ids["evt"])
    ev = ProtocolEvent(event_id=C4_EVENT, event_type="challenge_issue",
                       actor_identity=str(ids["evt"]))
    db.add(ev)
    db.flush()
    ledger_post(
        [(f"wallet:{ids['evt']}", -1_000), ("escrow:c4", 1_000)],
        door="wager_placed", session=db, protocol_event_id=ev.id,
    )
    db.commit()
    first_event_pk = ev.id

with tdb.SessionLocal() as db:
    dupe_refused = False
    try:
        lock_funding_scopes(db, ids["evt"])
        db.add(ProtocolEvent(event_id=C4_EVENT, event_type="challenge_issue",
                             actor_identity=str(ids["evt"])))
        db.commit()
    except Exception:
        dupe_refused = True
        db.rollback()

check("C4: UNIQUE(event_id) still refuses a duplicate ProtocolEvent — holding the "
      "P1-L7 mutex does not let a repeated event through",
      dupe_refused)

with tdb.SessionLocal() as db:
    n_events = db.execute(text(
        "SELECT COUNT(*) FROM protocol_events WHERE event_id = :e"),
        {"e": str(C4_EVENT)}).scalar()
    n_batches = db.execute(text(
        "SELECT COUNT(*) FROM ledger_posting_batches WHERE protocol_event_id = :e"),
        {"e": first_event_pk}).scalar()
    bal = _balance_of_in_session(db, f"wallet:{ids['evt']}")
check("C4: exactly one event row survives", n_events == 1, f"got {n_events}")
check("C4: exactly one posting batch is linked to it", n_batches == 1, f"got {n_batches}")
check("C4: the money posted exactly once (10000 − 1000)", bal == 9_000, f"got {bal}")
check("C4: trial balance still closes to zero", trial_balance() == 0)
check("C4: idempotency and locking remain DIFFERENT mechanisms — the lock "
      "primitive contains no event-identity logic",
      "event" not in source_of(lock_funding_scopes).lower())


# ──────────────────────────────────────────────────────────────────────────────
# L7-5 — the live production paths take the mutex before their capacity read
# ──────────────────────────────────────────────────────────────────────────────
section("L7-5: every live money path locks BEFORE it reads, in one transaction")

src_bet = (REPO / "betting" / "bet_engine.py").read_text(encoding="utf-8")


def func_node(path: Path, name: str) -> ast.FunctionDef:
    mod = ast.parse(path.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(mod)
                if isinstance(n, ast.FunctionDef) and n.name == name)


def func_source(path: Path, name: str) -> str:
    return ast.get_source_segment(
        path.read_text(encoding="utf-8"), func_node(path, name)) or ""


def call_lines(node: ast.FunctionDef, name: str) -> list[int]:
    """Line numbers of real calls to `name` in executable code. AST, not string
    search: these functions document their own locking in prose, and a comment
    that NAMES db.commit() or lock_funding_scopes() must not be mistaken for one."""
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        called = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        if called == name:
            out.append(n.lineno)
    return sorted(out)


# The authoritative capacity read is direct in three of these and indirect in
# respond_to_challenge, which reads through _verify_wallet_available(). Both
# spellings count as "the balance read the lock must precede".
READ_FNS = ("_balance_of_in_session", "_verify_wallet_available")

for path, fn, scopes in (
    (REPO / "betting" / "bet_engine.py", "_place_bet", 1),
    (REPO / "beefs" / "beef_engine.py", "issue_challenge", 1),
    (REPO / "beefs" / "beef_engine.py", "counter_challenge", 1),
    (REPO / "beefs" / "beef_engine.py", "respond_to_challenge", 2),
):
    node = func_node(path, fn)
    locks = call_lines(node, "lock_funding_scopes")
    reads = sorted(l for r in READ_FNS for l in call_lines(node, r))
    check(f"L7-5: {fn}() acquires the Wallet-row mutex", bool(locks), f"line {locks}")
    check(f"L7-5: {fn}() locks BEFORE its authoritative capacity read",
          bool(locks) and bool(reads) and locks[0] < reads[0],
          f"lock@{locks} read@{reads}")
    check(f"L7-5: {fn}() takes the mutex exactly once (single acquisition point)",
          len(locks) == 1, f"found {len(locks)}")

accept_node = func_node(REPO / "beefs" / "beef_engine.py", "respond_to_challenge")
accept_body = func_source(REPO / "beefs" / "beef_engine.py", "respond_to_challenge")
accept_lock = call_lines(accept_node, "lock_funding_scopes")[0]
commits_after = [l for l in call_lines(accept_node, "commit") if l > accept_lock]
check("L7-5: respond_to_challenge() holds the mutex to a SINGLE commit — no "
      "lock / commit / re-read / post pattern",
      len(commits_after) == 1, f"commits after the lock: {commits_after}")
check("L7-5: respond_to_challenge() locks both participants in one call",
      "challenge.challenger_team_id, challenge.challenged_team_id" in accept_body)

# The expire / kickoff / decline branches each commit and return. A lock taken
# before them would be released by their commit, so the mutex must sit after the
# LAST of them.
early_commits = [l for l in call_lines(accept_node, "commit") if l < accept_lock]
check("L7-5: the accept lock sits AFTER every early-return branch that commits "
      "(expire / kickoff / decline), so it is never released before the capacity read",
      len(early_commits) == 3, f"early commits before the lock: {early_commits}")

place_bet_node = func_node(REPO / "betting" / "bet_engine.py", "_place_bet")
pb_lock = call_lines(place_bet_node, "lock_funding_scopes")[0]
pb_commits = [l for l in call_lines(place_bet_node, "commit") if l > pb_lock]
check("L7-5: _place_bet() holds the mutex through its own single commit",
      len(pb_commits) == 1, f"commits after the lock: {pb_commits}")
check("L7-5: _place_bet() has no commit BEFORE the mutex either — the whole "
      "function is one transaction",
      not [l for l in call_lines(place_bet_node, "commit") if l < pb_lock])

check("L7-5: no money path acquires the mutex through an ad hoc with_for_update() "
      "on Wallet — one shared primitive, not duplicated locking",
      "Wallet" not in src_bet.split("with_for_update")[0][-200:]
      if "with_for_update" in src_bet else True)
for label, body in (("bet_engine", src_bet), ("beef_engine", src_beef)):
    check(f"L7-5: {label} contains no direct with_for_update() call — it goes "
          f"through lock_funding_scopes()",
          "with_for_update" not in body)


# ──────────────────────────────────────────────────────────────────────────────
# L7-6 — end-to-end: two concurrent real bets on one wallet
# ──────────────────────────────────────────────────────────────────────────────
section("L7-6: end-to-end through the real _place_bet() production path")

tdb.reset()
ids = seed_league([("live", 10_000), ("opp", 10_000)])

with tdb.SessionLocal() as db:
    db.add(Matchup(league_id=ids["_league"], week=1,
                   home_team_id=ids["live"], away_team_id=ids["opp"],
                   home_score=0.0, away_score=0.0))
    db.commit()
    matchup_id = db.execute(text("SELECT id FROM matchups LIMIT 1")).scalar()
    wallet_pk = db.execute(text("SELECT id FROM wallets WHERE team_id = :t"),
                           {"t": ids["live"]}).scalar()

from betting.bet_engine import _place_bet


def real_bet(cents: int, barrier: threading.Barrier, results: dict, key: str) -> None:
    try:
        with tdb.SessionLocal() as db:
            wallet = db.query(Wallet).filter(Wallet.id == wallet_pk).one()
            barrier.wait(timeout=20)
            bet = _place_bet(
                db, wallet, cents / 100.0, "straight", matchup_id,
                ids["live"], None, None, None, f"P1-L7 {key}", 1.909,
            )
            results[key] = f"placed:{bet.id}"
    except Exception as exc:                       # noqa: BLE001
        results[key] = f"error:{type(exc).__name__}"
        results[f"{key}_exc"] = str(exc)


# 20% MAX_BET_PCT cap on a $100 balance is $20 — two $18 stakes are each valid
# alone, and the second must see the first's committed debit (cap then $16.40).
res = run_pair(real_bet, {"cents": 1_800}, {"cents": 1_800})
outcomes = [res.get("a"), res.get("b")]
placed = [o for o in outcomes if str(o).startswith("placed")]

check("L7-6: neither real bet worker hung", not res["_alive"], str(outcomes))
check("L7-6: exactly one concurrent stake was accepted — the second is refused "
      "against the FIRST's committed balance, not the stale opening one",
      len(placed) == 1, str(outcomes))
check("L7-6: the refusal came from the capacity gate, not a database error",
      any("BetValidationError" in str(o) for o in outcomes), str(outcomes))

with tdb.SessionLocal() as db:
    bal = _balance_of_in_session(db, f"wallet:{ids['live']}")
    n_bets = db.execute(text("SELECT COUNT(*) FROM bets")).scalar()
check("L7-6: exactly one Bet row exists", n_bets == 1, f"got {n_bets}")
check("L7-6: ledger balance reflects exactly one debit", bal == 8_200, f"got {bal}")
check("L7-6: trial balance still closes to zero", trial_balance() == 0)


# ──────────────────────────────────────────────────────────────────────────────
# L7-7 — no float mirror participates in capacity authorization
# ──────────────────────────────────────────────────────────────────────────────
section("L7-7: no float Wallet.balance participates in any locked capacity decision")

with tdb.SessionLocal() as db:
    mirror = db.query(Wallet).filter(Wallet.team_id == ids["live"]).one().balance
check("L7-7: the fixture's float mirror was deliberately wrong throughout "
      "(would have authorized everything) and every result above still held",
      mirror == 99_999.0, f"mirror ${mirror:,.2f} vs ledger ${8_200/100:.2f}")

for fn, path in (("_place_bet", REPO / "betting" / "bet_engine.py"),
                 ("issue_challenge", REPO / "beefs" / "beef_engine.py"),
                 ("counter_challenge", REPO / "beefs" / "beef_engine.py"),
                 ("respond_to_challenge", REPO / "beefs" / "beef_engine.py")):
    mod = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(mod)
                if isinstance(n, ast.FunctionDef) and n.name == fn)
    hits = [n for n in ast.walk(node)
            if isinstance(n, ast.Attribute) and n.attr == "balance"]
    check(f"L7-7: {fn}() makes zero .balance attribute accesses",
          not hits, f"found {len(hits)}")


# ──────────────────────────────────────────────────────────────────────────────
# L7-8 — deterministic lock ORDER is a property of the primitive
# ──────────────────────────────────────────────────────────────────────────────
section("L7-8: the ordering is imposed by the primitive, not by callers")

lock_src = source_of(lock_funding_scopes)
check("L7-8: the primitive sorts its scopes", "sorted(" in lock_src)
check("L7-8: the primitive de-duplicates its scopes",
      "{int(team_id) for team_id in team_ids}" in lock_src)

tdb.reset()
ids = seed_league([("t1", 100), ("t2", 100), ("t3", 100)])
a, b, c = ids["t1"], ids["t2"], ids["t3"]
with tdb.SessionLocal() as db:
    orders = [
        lock_funding_scopes(db, a, b, c),
        lock_funding_scopes(db, c, b, a),
        lock_funding_scopes(db, b, a, c),
        lock_funding_scopes(db, c, a, b, a, c),
    ]
    db.rollback()
check("L7-8: every argument permutation yields the identical ascending order",
      all(o == sorted([a, b, c]) for o in orders), str(orders))
check("L7-8: the returned order is the acquisition order, ascending by team_id",
      orders[0] == sorted(orders[0]))


# ──────────────────────────────────────────────────────────────────────────────
# L7-9 — no lock-order inversion against the existing challenge-row lock
# ──────────────────────────────────────────────────────────────────────────────
section("L7-9: no inversion against pre-existing locks in the tree")

prop_src = (REPO / "beefs" / "proposal_lifecycle.py").read_text(encoding="utf-8")
check("L7-9: proposal_lifecycle still locks the BeefChallenge row (P3-S3-style "
      "discipline preserved, not regressed)",
      "with_for_update()" in prop_src)
check("L7-9: proposal_lifecycle takes NO Wallet lock, so it cannot invert against "
      "a Wallet-then-Challenge caller",
      "lock_funding_scopes" not in prop_src)

# A cycle needs one path taking Challenge→Wallet and another Wallet→Challenge.
for label, body in (("beef_engine", src_beef), ("bet_engine", src_bet)):
    lock_pos = body.find("lock_funding_scopes(")
    chal_lock = body.find("with_for_update")
    check(f"L7-9: {label} never takes a challenge row lock before a Wallet lock "
          f"(it takes no row lock other than the Wallet mutex)",
          chal_lock == -1, f"with_for_update at {chal_lock}")

settle_src = (REPO / "betting" / "settlement_engine.py").read_text(encoding="utf-8")
check("L7-9: the P3-S3 week_settlements lock is preserved untouched",
      "FOR UPDATE" in settle_src)
check("L7-9: settlement takes no Wallet mutex, so P1-L7 introduces no new edge "
      "into the settlement lock graph",
      "lock_funding_scopes" not in settle_src)


# ──────────────────────────────────────────────────────────────────────────────
# L7-10 — the primitive is genuinely shared, defined once
# ──────────────────────────────────────────────────────────────────────────────
section("L7-10: one shared primitive, defined once")

ledger_src = (REPO / "ledger" / "ledger.py").read_text(encoding="utf-8")
defs = [n for n in ast.walk(ast.parse(ledger_src))
        if isinstance(n, ast.FunctionDef) and n.name == "lock_funding_scopes"]
check("L7-10: lock_funding_scopes is defined exactly once, in ledger/ledger.py",
      len(defs) == 1, f"found {len(defs)}")

importers = []
for py in REPO.rglob("*.py"):
    if py.name.startswith("test_") or "lock_funding_scopes" not in py.read_text(
            encoding="utf-8", errors="ignore"):
        continue
    importers.append(py.relative_to(REPO).as_posix())
# P1-L4 UPDATE. economy/challenge_funding.py joined this list when P1-L4 landed:
# the Spec 2 money layer is a legitimate FOURTH consumer of the mutex, and its
# use of it is exactly what P1-L7 was built to serve.
#
# P3-D2 UPDATE. economy/dynamic_challenge.py is the FIFTH, and is legitimate for
# the same reason: the Dynamic Handshake funds two sides and the Final-Lock
# Phase 2 refunds one, so both take the funding-scope mutex, and both take it
# AFTER the challenge row lock — the rank L7-9 pins. It is enumerated here rather
# than allowed by pattern, so a sixth unreviewed consumer is still a failure.
# S8-P5 UPDATE — TWO POOL CONSUMERS, ENUMERATED AFTER REVIEW.
#
# `betting/pool_funding.py` and `betting/pool_settlement.py` are the SIXTH and
# SEVENTH consumers. They are not new: both held the mutex at the accepted P4
# baseline. What is new is that this assertion RAN — it needs PostgreSQL, which
# was deliberately unavailable through P1-P4, so a list written before the Pool
# money paths existed was never checked against them.
#
# Each was reviewed against the L7 discipline before being added here, because
# enumerating a consumer without reading it would defeat the point of the list:
#
#   pool_funding.collect_weekly_entries  takes EVERY participating wallet FOR
#       UPDATE in ASCENDING team order before any balance read. Ascending order
#       is precisely the rule that stops two concurrent collections deadlocking
#       against each other, and it is the same rule L7 pins elsewhere.
#
#   pool_settlement.settle_pool_instance takes the PoolInstance row lock FIRST
#       and the winners' funding scopes SECOND. That is the same RANK L7-9 pins
#       for challenges — the governing row before the money rows — so the two
#       subsystems cannot form a cycle against each other.
#
# Still enumerated rather than allowed by pattern, so an EIGHTH unreviewed
# consumer remains a failure.
check("L7-10: the production surface is exactly the primitive plus its known "
      "consumer modules",
      sorted(importers) == ["beefs/beef_engine.py", "betting/bet_engine.py",
                            "betting/pool_funding.py",
                            "betting/pool_settlement.py",
                            "economy/challenge_funding.py",
                            "economy/dynamic_challenge.py",
                            "ledger/ledger.py"], str(sorted(importers)))


# ──────────────────────────────────────────────────────────────────────────────
# L7-11 / L7-12 — scope fences: P1-L4 has NOT begun
# ──────────────────────────────────────────────────────────────────────────────
section("L7-11: no P1-L4 issue-time challenge escrow introduced")

import re

# Substring tokens — these contain non-word characters, so a plain `in` test is
# already unambiguous.
P1L4_LITERALS = ("escrow:challenge:", "min:{team_id}", "min:{team}")
# Identifier tokens — matched on WORD BOUNDARIES. A bare substring test would
# flag `log_challenge_issued`, the pre-existing FeedEvent logger imported from
# feed.league_feed since long before this package, which is presentation logging
# and not the SPEC 2 §9 `challenge_issued` ledger door. `\b` does not match
# inside `log_challenge_issued` because `_` is a word character.
P1L4_IDENTS = ("ChallengeFundingLeg", "challenge_funding_leg", "required_top_up",
               "anchor_stake_cents", "quoted_derived_stake_cents",
               "reconciliation_error", "challenge_issued", "challenge_refunded",
               "insufficient_acceptance_capacity")

for label, path in (("ledger/ledger.py", REPO / "ledger" / "ledger.py"),
                    ("beefs/beef_engine.py", REPO / "beefs" / "beef_engine.py"),
                    ("betting/bet_engine.py", REPO / "betting" / "bet_engine.py")):
    body = path.read_text(encoding="utf-8")
    # Comment/docstring prose legitimately names P1-L4 to record what is NOT
    # being built; only executable code counts.
    code_only = "\n".join(
        line.split("#")[0] for line in body.splitlines()
        if not line.strip().startswith("#")
    )
    hits = [t for t in P1L4_LITERALS if t in code_only]
    hits += [t for t in P1L4_IDENTS if re.search(rf"\b{t}\b", code_only)]
    check(f"L7-11: {label} introduces no P1-L4 escrow identifier in code",
          not hits, str(hits))

# Positive control — the boundary matcher must still catch a genuine door.
check("L7-11 positive control: the identifier scanner DOES flag a real "
      'door="challenge_issued" if one appears',
      bool(re.search(r"\bchallenge_issued\b", 'ledger_post([], door="challenge_issued")')))
check("L7-11 negative control: the scanner does NOT flag the pre-existing "
      "log_challenge_issued feed logger",
      not re.search(r"\bchallenge_issued\b", "log_challenge_issued(challenge, db)"))

with tdb.SessionLocal() as db:
    n_chal_escrow = db.execute(text(
        "SELECT COUNT(*) FROM ledger_entries WHERE account LIKE 'escrow:challenge:%'"
    )).scalar()
check("L7-11: no escrow:challenge: account was posted to anywhere in this suite",
      n_chal_escrow == 0, f"got {n_chal_escrow}")
# P1-L4 UPDATE — THE "HAS NOT BEGUN" HALF OF THIS FENCE IS RETIRED, DELIBERATELY.
# It asserted `economy/challenge_funding.py` did not exist, which was correct
# while P1-L7 was the frontier and is now false BY AUTHORIZATION: P1-L4 was the
# next package in the locked sequence and it lives in exactly that file.
#
# What the fence was actually protecting survives above and still passes: no
# P1-L4 escrow identifier has leaked into ledger/ledger.py, beefs/beef_engine.py
# or betting/bet_engine.py, and this suite's own fixtures still post to no
# escrow:challenge: account. The containment claim is the durable one; "the file
# does not exist" was only ever a proxy for it while the file was unwritten.
check("L7-11: P1-L4 is CONTAINED — the challenge escrow lifecycle lives in its "
      "own module and has not leaked into the P1-L7 surface",
      (REPO / "economy" / "challenge_funding.py").exists()
      and "escrow:challenge:" not in (REPO / "ledger" / "ledger.py").read_text(encoding="utf-8")
      and "escrow:challenge:" not in (REPO / "betting" / "bet_engine.py").read_text(encoding="utf-8"))

section("L7-12: the soft reservation's retirement was not P1-L7's doing")

# REVISED BY S8-P4C-1. This assertion used to read "_challenge_reserved is still
# the issue-stage reservation mechanism", and its purpose was SCOPE CONTAINMENT:
# P1-L7 added a wallet-row mutex, and the point was that it had not quietly
# taken the reservation's retirement with it. The retirement has since happened
# — in S8-P4C-1, where the application was cut over to the funded lifecycle and
# the gate was removed because real escrow replaced it.
#
# So the assertion is inverted rather than deleted, and it still guards the same
# thing: the gate is gone, and P1-L7's own surface is why we can say it went
# somewhere else. Deleting it would have retired the containment claim along
# with the mechanism it was about.
# EXECUTABLE CODE, NOT A SUBSTRING SCAN. beef_engine.py still explains in prose
# where the gate went, and a raw `in src_beef` test would match that comment and
# report the retirement as incomplete.
import ast as _ast

_beef_tree = _ast.parse(src_beef)
_beef_refs = ({n.id for n in _ast.walk(_beef_tree) if isinstance(n, _ast.Name)}
              | {n.attr for n in _ast.walk(_beef_tree)
                 if isinstance(n, _ast.Attribute)}
              | {a.name for n in _ast.walk(_beef_tree)
                 if isinstance(n, _ast.ImportFrom) for a in n.names})
check("L7-12: the issue-stage soft-reservation gate is retired",
      "_challenge_reserved" not in _beef_refs)

issue_body = func_source(REPO / "beefs" / "beef_engine.py", "issue_challenge")
check("L7-12: issue_challenge() still makes ZERO ledger postings — P1-L7 added a "
      "lock, not money movement",
      "ledger_post(" not in issue_body)

tdb.reset()
ids = seed_league([("fence", 10_000)])
before = trial_balance()
with tdb.SessionLocal() as db:
    lock_funding_scopes(db, ids["fence"])
    db.commit()
check("L7-12: acquiring the mutex posts nothing — trial balance unchanged and "
      "no ledger entry created",
      trial_balance() == before == 0, f"before={before} after={trial_balance()}")

with tdb.SessionLocal() as db:
    n_entries = db.execute(text("SELECT COUNT(*) FROM ledger_entries")).scalar()
check("L7-12: the lock created no ledger entries of its own",
      n_entries == 2, f"got {n_entries} (the fixture's own funding posting only)")


# ──────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
tdb.teardown()
if _failures:
    print(f"{len(_failures)} FAILED assertion(s):")
    for f in _failures:
        print(f"  - {f}")
    print(f"\n{_passes} passed, {len(_failures)} FAILED")
    sys.exit(1)
print(f"All {_passes} assertions PASSED")
