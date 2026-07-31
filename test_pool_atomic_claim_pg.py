"""
test_pool_atomic_claim_pg.py -- atomic week claim + bench_burn retirement (PostgreSQL).

Product authority: spec/SPEC_Pool_Catalog_Rotation_POR_Rev1_0.md
Implementation scope: spec/SPEC_Pool_Rotation_Implementation_Scope_Rev1_0.md, steps 1 and 13.

WHAT WAS WRONG. collect_weekly_entries guarded against double collection with a
read-then-write check: SELECT the PoolPot row, raise if entries_collected. Two
concurrent POST /pool/collect calls for one league/week both read no row, both
ran the entire debit loop, and one lost at commit on uq_pool_pot_league_week.
The unique constraint did prevent two rows -- it did not prevent the loser from
executing its wallet debits and ledger postings first, and the failure surfaced
as IntegrityError rather than the domain ValueError the function documents.

THE CLAIM, AND WHY IT DOES NOT COMMIT. INSERT ... ON CONFLICT DO UPDATE ... WHERE
entries_collected = FALSE ... RETURNING id, run before any economic work. Zero
rows returned means another caller holds the claim.

WeekSettlement's equivalent claim commits immediately (settlement_engine.py:362).
This one must not, and that is a money-path property rather than a style choice.
entries_collected is read OUTSIDE the collecting transaction as proof that every
team was actually charged -- settle_pool at pool_engine.py:538, and
shortfall_sweep._compute_wagered_cents at :90, which credits each team a weekly
entry toward its wagering minimum on the strength of that flag alone. A
separately committed claim would publish that proof before a cent moved, and
would strand the flag TRUE so no later attempt could re-claim the week.

Because the claim stays uncommitted, a losing caller BLOCKS on the conflicting
row rather than racing it, then resolves correctly either way: the winner commits
and the loser's WHERE finds entries_collected already TRUE (zero rows -> domain
ValueError), or the winner rolls back and the loser claims the week. Assertion 9
exercises the rollback direction.

WHY REAL THREADS AND NOT A SEQUENTIAL SIMULATION. Calling collect twice in
sequence passes under the OLD code too -- the read-then-write guard catches a
fully committed prior collection perfectly well. It only fails under overlap. So
the two attempts run on two threads with two independent sessions (two
connections), released simultaneously by a threading.Barrier, and assertion 0
proves the call windows actually overlapped in wall-clock time rather than
assuming the scheduler cooperated. A test that cannot tell serial from
concurrent cannot tell fixed from broken.

NO PAYOUT MAGNITUDES ARE ASSERTED. Assertions 5, 6 and 7 count ledger rows and
distinct posting_ids. Exactly-once is a count property; an amount cannot
distinguish one correct posting from two that happen to net out.

bench_burn RETIREMENT (POR §1.1, §11.5). Removed from POOL_BET_TYPES, so
_VALID_BET_TYPES no longer accepts it and submit_pool_pick rejects it at its
first statement. PoolBetPick.bet_type is a plain String with no CHECK constraint
(db/schema.py:1114), so historical rows remain readable -- verified in this file
by inserting one directly and reading it back, reported below assertion 11 rather
than asserted, so the 0..11 label contract is not disturbed.

ASSERTIONS (12, labelled 0-11):

    0-8   concurrent collection: one winner, one domain refusal, once-only money
    9     retry after a genuinely failed collection
    10    bench_burn rejected
    11    the three surviving legacy types keep their validation behavior

Requires TEST_DATABASE_URL exported to a dedicated, empty, _test-named,
non-Railway PostgreSQL database (see test_support_postgres guards).
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Harness FIRST -- setup_postgres_test_db() applies its guards, sets DATABASE_URL
# to the disposable test DB, and imports+binds db.schema INTERNALLY. No project
# module may be imported before this call.
from test_support_postgres import setup_postgres_test_db

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] Pool atomic-claim suite cannot run:\n  {e}")
    sys.exit(2)   # 2 = harness/config error; distinct from an assertion failure

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    """Post-setup work. Project imports live here so teardown protection begins
    the instant setup succeeds."""
    from datetime import datetime

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from db.schema import (
        SessionLocal,
        League, Team, Wallet, Transaction, NflSchedule,
        PoolConfig, PoolPot, PoolBetPick,
    )
    from ledger.ledger import post as ledger_post, trial_balance, LedgerEntry
    from betting.pool_engine import (
        POOL_BET_TYPES,
        collect_weekly_entries,
        setup_pool_config,
        submit_pool_pick,
    )
    from config import CURRENT_SEASON as SEASON

    _WEEK = 1
    ENTRY_CENTS = 1000
    FUND_CENTS = 100_000
    WALLET_BALANCE_SEED = 500.00
    FUTURE_KO = datetime(2026, 9, 14, 18, 0, 0)

    COLLECT_DOOR = "pool_entry_collected"

    # ------------------------------------------------------------------
    # Fixture. Teams are funded through the real ledger doors so the debit
    # loop has something to move.
    # ------------------------------------------------------------------
    def _build_league(name: str, num_teams: int, fund_all: bool = True) -> dict:
        with SessionLocal() as _db:
            league = League(season=SEASON, name=name, projection_source="fantasypros")
            _db.add(league)
            _db.commit()
            league_id = league.id

        team_ids = []
        with SessionLocal() as _db:
            for i in range(num_teams):
                t = Team(league_id=league_id, team_name=f"{name} T{i}",
                         owner=f"owner-{i}", email=f"t{i}@{league_id}.claim.test")
                _db.add(t)
            _db.commit()
            team_ids = [
                t.id for t in
                _db.query(Team).filter(Team.league_id == league_id).order_by(Team.id).all()
            ]

        with SessionLocal() as _db:
            for tid in (team_ids if fund_all else team_ids[:-1]):
                _db.add(Wallet(team_id=tid, balance=WALLET_BALANCE_SEED))
            _db.commit()

        for tid in (team_ids if fund_all else team_ids[:-1]):
            ledger_post([("world", -FUND_CENTS), (f"wallet:{tid}", FUND_CENTS)],
                        door="buy_in_paid")

        with SessionLocal() as _db:
            setup_pool_config(league_id, weekly_entry_cents=ENTRY_CENTS,
                              worst_beat_rollover=True, db=_db)

        return {"league_id": league_id, "team_ids": team_ids}

    # _nfl_lock_time is called as _nfl_lock_time(league.season, week), so the
    # schedule row must carry the LEAGUE's season, not LOCK_SEASON.
    with SessionLocal() as _db:
        _db.add(NflSchedule(season=SEASON, week=_WEEK,
                            home_team="KC", away_team="PHI", kickoff_utc=FUTURE_KO))
        _db.commit()

    fixture = _build_league("claim-primary", num_teams=3)
    LEAGUE_ID = fixture["league_id"]
    TEAM_IDS = fixture["team_ids"]
    NUM_TEAMS = len(TEAM_IDS)

    # Derived from the code path, NOT from an observed run: the debit loop makes
    # one ledger_post per team and each posting has exactly two legs
    # (wallet:{team} debit, pool:{league} credit).
    EXPECTED_LEGS = 2 * NUM_TEAMS
    EXPECTED_POSTINGS = NUM_TEAMS
    EXPECTED_TX = NUM_TEAMS

    # ==================================================================
    # CONCURRENT COLLECTION -- two threads, two sessions, one barrier.
    # ==================================================================
    print("\n-- CONCURRENT COLLECTION: two attempts, same league/week --")

    barrier = threading.Barrier(2)
    outcomes: dict[int, dict] = {}
    outcomes_lock = threading.Lock()

    def _attempt(idx: int) -> None:
        db = SessionLocal()
        try:
            # Warm the connection so the barrier releases both threads into the
            # claim itself, not into connection setup.
            db.query(PoolConfig).filter(PoolConfig.league_id == LEAGUE_ID).first()
            barrier.wait(timeout=30)
            entered = time.monotonic()
            try:
                result = collect_weekly_entries(LEAGUE_ID, _WEEK, db)
                rec = {"ok": True, "error": None, "result": result}
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                rec = {"ok": False, "error": exc, "result": None}
            rec["entered"] = entered
            rec["exited"] = time.monotonic()
        finally:
            db.close()
        with outcomes_lock:
            outcomes[idx] = rec

    threads = [threading.Thread(target=_attempt, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    both_ran = len(outcomes) == 2
    overlapped = False
    if both_ran:
        a, b = outcomes[0], outcomes[1]
        overlapped = (max(a["entered"], b["entered"]) < min(a["exited"], b["exited"]))

    winners = [i for i, o in outcomes.items() if o["ok"]]
    losers = [i for i, o in outcomes.items() if not o["ok"]]
    loser_err = outcomes[losers[0]]["error"] if losers else None

    _assert(
        "0: two collection attempts ran genuinely concurrently (call windows overlap)",
        both_ran and overlapped,
        detail=(f"both_ran={both_ran} overlapped={overlapped}"
                + (f" windows={[(round(o['entered'], 4), round(o['exited'], 4)) for o in outcomes.values()]}"
                   if both_ran else "")),
    )
    _assert(
        "1: exactly one attempt succeeded",
        len(winners) == 1,
        detail=f"winners={len(winners)} losers={len(losers)}",
    )
    _assert(
        "2: the loser raised the domain ValueError, not IntegrityError",
        isinstance(loser_err, ValueError)
        and not isinstance(loser_err, IntegrityError)
        and "already collected" in str(loser_err),
        detail=(f"{type(loser_err).__name__}: {loser_err}" if loser_err is not None
                else "no losing attempt recorded"),
    )

    with SessionLocal() as db:
        pot_rows = db.query(PoolPot).filter(
            PoolPot.league_id == LEAGUE_ID, PoolPot.week == _WEEK,
        ).all()
        pot_count = len(pot_rows)
        pot_collected = pot_rows[0].entries_collected if pot_rows else None
        pot_total = pot_rows[0].total_pot_cents if pot_rows else None

        collect_legs = (
            db.query(LedgerEntry).filter(LedgerEntry.door == COLLECT_DOOR).count()
        )
        per_wallet_legs = {
            tid: db.query(LedgerEntry).filter(
                LedgerEntry.door == COLLECT_DOOR,
                LedgerEntry.account == f"wallet:{tid}",
            ).count()
            for tid in TEAM_IDS
        }
        distinct_postings = (
            db.query(LedgerEntry.posting_id)
            .filter(LedgerEntry.door == COLLECT_DOOR)
            .distinct().count()
        )
        pool_legs = db.query(LedgerEntry).filter(
            LedgerEntry.door == COLLECT_DOOR,
            LedgerEntry.account == f"pool:{LEAGUE_ID}",
        ).count()
        tx_count = db.query(Transaction).filter(Transaction.type == "pool_entry").count()

    _assert(
        "3: exactly one PoolPot row exists for the league/week",
        pot_count == 1,
        detail=f"PoolPot rows={pot_count}",
    )
    _assert(
        "4: entries_collected is True on the surviving row",
        pot_collected is True,
        detail=f"entries_collected={pot_collected!r} total_pot_cents={pot_total!r}",
    )
    _assert(
        "5: each wallet was debited exactly once (posting count, not amount)",
        all(n == 1 for n in per_wallet_legs.values()),
        detail=f"per-wallet {COLLECT_DOOR} legs={per_wallet_legs} (each must be 1)",
    )
    _assert(
        "6: collection-door ledger entries are exactly the once-only set",
        collect_legs == EXPECTED_LEGS,
        detail=f"{COLLECT_DOOR} legs={collect_legs} expected={EXPECTED_LEGS} "
               f"(2 legs x {NUM_TEAMS} teams; {2 * EXPECTED_LEGS} would mean both "
               f"attempts posted)",
    )
    _assert(
        "7: the losing attempt left zero partial postings",
        distinct_postings == EXPECTED_POSTINGS
        and pool_legs == NUM_TEAMS
        and tx_count == EXPECTED_TX,
        detail=f"distinct posting_ids={distinct_postings} (expected {EXPECTED_POSTINGS}) "
               f"pool-side legs={pool_legs} (expected {NUM_TEAMS}) "
               f"pool_entry Transaction rows={tx_count} (expected {EXPECTED_TX})",
    )
    _assert(
        "8: trial balance is exactly zero",
        trial_balance() == 0,
        detail=f"trial_balance={trial_balance()}c",
    )

    # ==================================================================
    # RETRY AFTER A GENUINELY FAILED COLLECTION.
    # The last team has no wallet, so the debit loop raises partway through
    # (pool_engine.py:282) after earlier teams were already staged. Nothing
    # commits, so the claim rolls back with everything else and the week must
    # remain claimable.
    # ==================================================================
    print("\n-- RETRY: a failed collection must leave the week claimable --")

    retry_fx = _build_league("claim-retry", num_teams=3, fund_all=False)
    R_LEAGUE_ID = retry_fx["league_id"]
    R_TEAM_IDS = retry_fx["team_ids"]

    first_error = None
    db = SessionLocal()
    try:
        collect_weekly_entries(R_LEAGUE_ID, _WEEK, db)
    except Exception as exc:  # noqa: BLE001
        first_error = exc
        db.rollback()
    finally:
        db.close()

    with SessionLocal() as _db:
        rows_after_fail = _db.query(PoolPot).filter(
            PoolPot.league_id == R_LEAGUE_ID, PoolPot.week == _WEEK,
        ).count()

    # Repair the fixture, then retry.
    with SessionLocal() as _db:
        _db.add(Wallet(team_id=R_TEAM_IDS[-1], balance=WALLET_BALANCE_SEED))
        _db.commit()
    ledger_post([("world", -FUND_CENTS), (f"wallet:{R_TEAM_IDS[-1]}", FUND_CENTS)],
                door="buy_in_paid")

    retry_error = None
    retry_result = None
    db = SessionLocal()
    try:
        retry_result = collect_weekly_entries(R_LEAGUE_ID, _WEEK, db)
    except Exception as exc:  # noqa: BLE001
        retry_error = exc
        db.rollback()
    finally:
        db.close()

    with SessionLocal() as _db:
        r_pot = _db.query(PoolPot).filter(
            PoolPot.league_id == R_LEAGUE_ID, PoolPot.week == _WEEK,
        ).one_or_none()
        r_collected = getattr(r_pot, "entries_collected", None)
        r_legs = _db.query(LedgerEntry).filter(
            LedgerEntry.door == COLLECT_DOOR,
            LedgerEntry.account == f"pool:{R_LEAGUE_ID}",
        ).count()

    _assert(
        "9: a retry after a genuinely failed collection still succeeds",
        first_error is not None
        and rows_after_fail == 0
        and retry_error is None
        and retry_result is not None
        and r_collected is True
        and r_legs == len(R_TEAM_IDS),
        detail=(f"first attempt raised {type(first_error).__name__}; "
                f"PoolPot rows after failure={rows_after_fail} (claim rolled back); "
                f"retry {'succeeded' if retry_error is None else f'raised {retry_error}'}; "
                f"entries_collected={r_collected!r}; "
                f"pool-side legs={r_legs} (expected {len(R_TEAM_IDS)})"),
    )

    # ==================================================================
    # NULL RETRY. entries_collected is nullable, and the guard this claim
    # replaced tested Python truthiness, under which None fell through and the
    # week stayed collectable. `WHERE ... = FALSE` would evaluate to NULL
    # against a NULL column and refuse — silently narrowing that path and
    # stranding any legacy row carrying NULL. The predicate is IS NOT TRUE.
    #
    # The row MUST be seeded with raw SQL. SQLAlchemy's Column(default=False) is
    # client-side and fills False on flush, so an ORM-seeded row would exercise
    # the FALSE path while claiming to test NULL — and that variant passes under
    # the old `= FALSE` predicate too, proving nothing.
    # ==================================================================
    print("\n-- NULL RETRY: a NULL entries_collected row must remain claimable --")

    null_fx = _build_league("claim-null", num_teams=3)
    N_LEAGUE_ID = null_fx["league_id"]
    N_TEAM_IDS = null_fx["team_ids"]

    with SessionLocal() as db:
        db.execute(
            text("""
                INSERT INTO pool_pots
                    (league_id, week, entries_collected, worst_beat_rollover_cents, settled)
                VALUES (:league_id, :week, NULL, 0, FALSE)
            """),
            {"league_id": N_LEAGUE_ID, "week": _WEEK},
        )
        db.commit()

    # Read the stored value back through raw SQL too — an ORM read would coerce
    # nothing here, but the point is to prove the DATABASE holds NULL.
    with SessionLocal() as db:
        n_is_null = db.execute(
            text("""
                SELECT entries_collected IS NULL FROM pool_pots
                WHERE league_id = :league_id AND week = :week
            """),
            {"league_id": N_LEAGUE_ID, "week": _WEEK},
        ).scalar()

    null_error = None
    null_result = None
    db = SessionLocal()
    try:
        null_result = collect_weekly_entries(N_LEAGUE_ID, _WEEK, db)
    except Exception as exc:  # noqa: BLE001
        null_error = exc
        db.rollback()
    finally:
        db.close()

    with SessionLocal() as db:
        n_pot = db.query(PoolPot).filter(
            PoolPot.league_id == N_LEAGUE_ID, PoolPot.week == _WEEK,
        ).one_or_none()
        n_collected = getattr(n_pot, "entries_collected", None)
        n_pot_rows = db.query(PoolPot).filter(
            PoolPot.league_id == N_LEAGUE_ID, PoolPot.week == _WEEK,
        ).count()
        n_per_wallet = {
            tid: db.query(LedgerEntry).filter(
                LedgerEntry.door == COLLECT_DOOR,
                LedgerEntry.account == f"wallet:{tid}",
            ).count()
            for tid in N_TEAM_IDS
        }
        n_pool_legs = db.query(LedgerEntry).filter(
            LedgerEntry.door == COLLECT_DOOR,
            LedgerEntry.account == f"pool:{N_LEAGUE_ID}",
        ).count()

    _assert(
        "12: a NULL entries_collected row is still claimable and collects exactly once",
        bool(n_is_null)
        and null_error is None
        and null_result is not None
        and n_collected is True
        and n_pot_rows == 1
        and all(c == 1 for c in n_per_wallet.values())
        and n_pool_legs == len(N_TEAM_IDS)
        and trial_balance() == 0,
        detail=(f"stored value was NULL before the claim={bool(n_is_null)}; "
                f"collect {'succeeded' if null_error is None else f'raised {null_error}'}; "
                f"entries_collected now={n_collected!r}; PoolPot rows={n_pot_rows}; "
                f"per-wallet {COLLECT_DOOR} legs={n_per_wallet} (each must be 1); "
                f"pool-side legs={n_pool_legs} (expected {len(N_TEAM_IDS)}); "
                f"trial_balance={trial_balance()}c"),
    )

    # ==================================================================
    # bench_burn RETIREMENT.
    # ==================================================================
    print("\n-- RETIREMENT: bench_burn is unreachable as a Pool --")

    bench_error = None
    with SessionLocal() as db:
        try:
            submit_pool_pick(LEAGUE_ID, TEAM_IDS[0], "bench_burn", None, _WEEK, db)
        except Exception as exc:  # noqa: BLE001
            bench_error = exc

    _assert(
        "10: submit_pool_pick rejects bench_burn with a named error",
        isinstance(bench_error, ValueError)
        and "bench_burn" in str(bench_error)
        and "Invalid bet_type" in str(bench_error)
        and "bench_burn" not in {b["key"] for b in POOL_BET_TYPES},
        detail=(f"{type(bench_error).__name__}: {bench_error}" if bench_error is not None
                else "submit_pool_pick ACCEPTED bench_burn"),
    )

    # The three surviving legacy types must behave exactly as before: accepted as
    # valid bet_types, self-pick allowed only for biggest_winner.
    survivor_results: dict[str, str] = {}
    for key in ("biggest_winner", "worst_beat", "special_teams"):
        with SessionLocal() as db:
            try:
                submit_pool_pick(LEAGUE_ID, TEAM_IDS[0], key, TEAM_IDS[0], _WEEK, db)
                survivor_results[key] = "accepted"
            except ValueError as exc:
                msg = str(exc)
                if "Invalid bet_type" in msg:
                    survivor_results[key] = "REJECTED_AS_INVALID_TYPE"
                elif "Self-pick not allowed" in msg:
                    survivor_results[key] = "self_pick_blocked"
                else:
                    survivor_results[key] = f"other: {msg}"

    _assert(
        "11: the three surviving legacy types keep their pre-change validation",
        survivor_results.get("biggest_winner") == "accepted"
        and survivor_results.get("worst_beat") == "self_pick_blocked"
        and survivor_results.get("special_teams") == "self_pick_blocked"
        and {b["key"] for b in POOL_BET_TYPES} == {
            "biggest_winner", "worst_beat", "special_teams"
        },
        detail=f"{survivor_results}; catalog keys="
               f"{sorted(b['key'] for b in POOL_BET_TYPES)}",
    )

    # Retiring the catalog key must not make existing history unreadable.
    # PoolBetPick.bet_type is a plain String with no CHECK constraint
    # (db/schema.py:1114), so a row written before the retirement still selects.
    with SessionLocal() as db:
        db.add(PoolBetPick(
            league_id=LEAGUE_ID, team_id=TEAM_IDS[1], bet_type="bench_burn",
            picked_team_id=TEAM_IDS[2], week=_WEEK,
        ))
        db.commit()
    with SessionLocal() as db:
        historical = db.query(PoolBetPick).filter(
            PoolBetPick.league_id == LEAGUE_ID,
            PoolBetPick.bet_type == "bench_burn",
        ).all()

    _assert(
        "13: a historical bench_burn PoolBetPick row remains readable",
        len(historical) == 1 and historical[0].bet_type == "bench_burn",
        detail=(f"rows returned={len(historical)} (expected 1) "
                f"bet_type={historical[0].bet_type!r} "
                f"picked_team_id={historical[0].picked_team_id!r}"
                if historical else "no rows returned — history is NOT readable"),
    )

    print()
    print(f"  VERIFIED (reported, alongside assertion 13): a bench_burn PoolBetPick "
          f"row was written directly and read back -- {len(historical)} row(s), "
          f"bet_type={historical[0].bet_type!r} picked_team_id="
          f"{historical[0].picked_team_id!r}. PoolBetPick.bet_type carries no CHECK "
          f"constraint, so retiring the catalog key leaves history readable.")


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
    print("RESULT: all pool atomic-claim assertions PASSED")
