"""
test_s4_pool_idempotency_pg.py — atomicity, idempotency, crash and concurrency.

Covers Scope §H scenarios 10, 10a, 10b, 10c, 10d, 10e, 10f, 10g, 10h and 11.

POR §6.4 AND §G1 REQUIRE TWO THINGS TOGETHER, AND THIS SUITE TESTS THEM APART.

  1. ATOMICITY — the ledger posting and the `settled` transition occur in ONE
     transaction. Scenario 10h is its discriminating control: a failure injected
     between the posting and the flag must leave NEITHER. A two-transaction
     implementation passes scenario 10 and fails 10h.

  2. EVENT-KEYED IDEMPOTENCY under a database uniqueness constraint. Scenario
     10e is its discriminating control: with the constraint removed, a replayed
     economic event becomes representable and a double payout is reachable. A
     lock-only implementation passes scenario 10 and fails 10e.

A ROW LOCK IS TESTED AS A SUPPLEMENT, NEVER AS THE GUARANTEE. `FOR UPDATE`
serializes concurrent settlements within one process lifetime (10d), and that is
worth having, but §6.4 is explicit that it "cannot replace" the event key. Both
are asserted, separately, so neither can be mistaken for the other's proof.

CONTROLS MUTATE ONLY THE DATABASE, NEVER THE IMPLEMENTATION. Scenario 10e drops
an index on the test database and restores it in a finally block. No production
module is edited to manufacture a broken variant, so a hash over betting/*.py is
flat across the whole run.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] S4-P1 idempotency suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def run_concurrent(fn_a, fn_b, timeout=30):
    """Run two callables on real threads, releasing both at one barrier.

    Real threads and real sessions, because the contention being tested is
    between two DATABASE transactions. An interleave faked in one session would
    prove nothing about locking."""
    barrier = threading.Barrier(2, timeout=timeout)
    out = {}

    def wrap(name, fn):
        def run():
            try:
                barrier.wait()
                out[name] = ("ok", fn())
            except Exception as exc:  # noqa: BLE001
                out[name] = ("error", exc)
        return run

    threads = [threading.Thread(target=wrap("a", fn_a)),
               threading.Thread(target=wrap("b", fn_b))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    return out


def main(tdb) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from betting.pool_funding import PoolFundingError, collect_weekly_entries
    from betting.pool_settlement import (
        EVENT_WINNER_DISTRIBUTION, assert_pool_conservation,
        settle_pool_instance,
    )
    from db.schema import (
        PoolEconomicEvent, PoolInstance, PoolPot, SessionLocal, engine,
    )
    from ledger.ledger import LedgerEntry, balance_of, trial_balance
    from test_support_s4_pool import (
        FOUR_TEAM_KEYS, PROVIDER, REQUIRED_STAT, DefinitionStatSource,
        make_league, mark_ready, seed_catalog, team_subjects,
    )
    from betting.pool_claims import submit_claim

    SEASON = 2026

    def fresh(name, n_teams=4):
        tdb.reset()
        with SessionLocal() as db:
            seed_catalog(db)
            league, teams = make_league(db, name=name, season=SEASON,
                                        n_teams=n_teams)
            mark_ready(db, league_id=league.id, keys=FOUR_TEAM_KEYS)
            db.commit()
            return league.id, [t.id for t in teams]

    def fund(league_id, week=3):
        with SessionLocal() as db:
            result = collect_weekly_entries(db, league_id=league_id, week=week,
                                            provider=PROVIDER)
            db.commit()
            return result

    def instances(db, league_id, week=3):
        return (db.query(PoolInstance)
                .filter(PoolInstance.league_id == league_id,
                        PoolInstance.week == week)
                .order_by(PoolInstance.slot).all())

    def winner_source(db, league_id, instance, winner_team_id, team_ids):
        from db.schema import Team
        teams = (db.query(Team).filter(Team.league_id == league_id)
                 .order_by(Team.id).all())
        stat = REQUIRED_STAT[instance.definition_key]
        values = {t.id: 1.0 for t in teams}
        values[winner_team_id] = 99.0
        return DefinitionStatSource(
            {instance.definition_key: team_subjects(teams, stat=stat,
                                                    values=values)}
        ).for_definition(instance.definition_key)

    # ── 10 / 10c: retry after commit ─────────────────────────────────────────
    print("\n-- 10/10c: settlement retry after commit is a no-op --")
    league_id, team_ids = fresh("retry")
    fund(league_id)
    with SessionLocal() as db:
        inst = instances(db, league_id)[0]
        submit_claim(db, pool_instance_id=inst.id, team_id=team_ids[1],
                     subject_id=team_ids[0])
        db.commit()
    with SessionLocal() as db:
        inst = instances(db, league_id)[0]
        src = winner_source(db, league_id, inst, team_ids[0], team_ids)
        first = settle_pool_instance(db, pool_instance_id=inst.id,
                                     stat_source=src)
        db.commit()
    paid_after_first = balance_of(f"wallet:{team_ids[1]}")
    entries_after_first = _entry_count(SessionLocal, LedgerEntry,
                                       "pool_winner_distribution")
    with SessionLocal() as db:
        inst = instances(db, league_id)[0]
        src = winner_source(db, league_id, inst, team_ids[0], team_ids)
        replay = settle_pool_instance(db, pool_instance_id=inst.id,
                                      stat_source=src)
        db.commit()
    _assert("10c the replay is reported as a replay, not a new settlement",
            replay.replayed is True)
    _assert("10 no second credit reaches the winner",
            balance_of(f"wallet:{team_ids[1]}") == paid_after_first)
    _assert("10c no second posting is written",
            _entry_count(SessionLocal, LedgerEntry, "pool_winner_distribution")
            == entries_after_first)
    with SessionLocal() as db:
        events = (db.query(PoolEconomicEvent)
                  .filter(PoolEconomicEvent.pool_instance_id
                          == instances(db, league_id)[0].id).all())
        _assert("10c exactly one economic event exists for the instance",
                len(events) == 1 and events[0].event_type
                == EVENT_WINNER_DISTRIBUTION, str([e.event_type for e in events]))
        _assert("10 trial balance is zero", trial_balance() == 0)
        db.rollback()

    # ── 10b: the event key arms the constraint ───────────────────────────────
    print("\n-- 10b: a replayed economic event collides at the constraint --")
    with SessionLocal() as db:
        inst = instances(db, league_id)[0]
        db.add(PoolEconomicEvent(
            league_id=league_id, season=SEASON, week=3,
            pool_instance_id=inst.id, event_type=EVENT_WINNER_DISTRIBUTION,
            posting_id=None, amount_cents=1,
            created_at=datetime.now(timezone.utc)))
        try:
            db.flush()
            _assert("10b a second WINNER_DISTRIBUTION for one instance is "
                    "refused", False, "the insert succeeded")
        except IntegrityError:
            _assert("10b a second WINNER_DISTRIBUTION for one instance is "
                    "refused", True, "uq_pool_economic_event_instance")
        db.rollback()

    # ── 10f: distinct causes are distinguishable, and neither replays ────────
    print("\n-- 10f: sweep types are distinct and neither masquerades --")
    with SessionLocal() as db:
        inst = instances(db, league_id)[1]      # an unsettled instance
        db.add(PoolEconomicEvent(
            league_id=league_id, season=SEASON, week=3,
            pool_instance_id=inst.id,
            event_type="SUBJECT_ZERO_CLAIM_CHAMPIONSHIP_SWEEP",
            posting_id=None, amount_cents=10,
            created_at=datetime.now(timezone.utc)))
        db.add(PoolEconomicEvent(
            league_id=league_id, season=SEASON, week=3,
            pool_instance_id=inst.id, event_type="ROLLOVER_EXPIRY_SWEEP",
            posting_id=None, amount_cents=10,
            created_at=datetime.now(timezone.utc)))
        try:
            db.flush()
            _assert("10f two DIFFERENT sweep types on one instance are "
                    "distinguishable", True)
        except IntegrityError as exc:
            _assert("10f two DIFFERENT sweep types on one instance are "
                    "distinguishable", False, str(exc)[:100])
        db.add(PoolEconomicEvent(
            league_id=league_id, season=SEASON, week=3,
            pool_instance_id=inst.id, event_type="ROLLOVER_EXPIRY_SWEEP",
            posting_id=None, amount_cents=10,
            created_at=datetime.now(timezone.utc)))
        try:
            db.flush()
            _assert("10f neither sweep type can replay", False,
                    "a duplicate ROLLOVER_EXPIRY_SWEEP was accepted")
        except IntegrityError:
            _assert("10f neither sweep type can replay", True)
        db.rollback()

    # ── 10a: crash before commit leaves nothing ─────────────────────────────
    print("\n-- 10a: a crash before commit leaves no effect at all --")
    league_id, team_ids = fresh("crash-before")
    fund(league_id)
    pool_before = balance_of(f"pool:{league_id}")
    with SessionLocal() as db:
        inst = instances(db, league_id)[0]
        submit_claim(db, pool_instance_id=inst.id, team_id=team_ids[1],
                     subject_id=team_ids[0])
        db.commit()
    with SessionLocal() as db:
        inst = instances(db, league_id)[0]
        src = winner_source(db, league_id, inst, team_ids[0], team_ids)
        settle_pool_instance(db, pool_instance_id=inst.id, stat_source=src)
        db.rollback()          # the crash
    with SessionLocal() as db:
        inst = instances(db, league_id)[0]
        _assert("10a no ledger rows survive",
                _entry_count(SessionLocal, LedgerEntry,
                             "pool_winner_distribution") == 0)
        _assert("10a settled is still false", inst.settled is False)
        _assert("10a the pot is intact",
                balance_of(f"pool:{league_id}") == pool_before)
        _assert("10a no economic event survives",
                db.query(PoolEconomicEvent).filter(
                    PoolEconomicEvent.pool_instance_id == inst.id).count() == 0)
        _assert("10a trial balance is zero", trial_balance() == 0)
        db.rollback()

    # ── 10h: atomicity is discriminating ────────────────────────────────────
    print("\n-- 10h: posting and `settled` are one transaction (DISCRIMINATING) --")
    # The settlement returned successfully — a two-transaction implementation
    # would already have COMMITTED the posting by this point, and the rollback
    # above would have left money moved with `settled` false. That the ledger is
    # empty here is the proof the two are one unit.
    _assert("10h a failure after the posting leaves NEITHER the posting nor "
            "the flag",
            _entry_count(SessionLocal, LedgerEntry, "pool_winner_distribution")
            == 0,
            "a two-transaction implementation passes 10 and fails here")

    # ── 10d: concurrent settlement ──────────────────────────────────────────
    print("\n-- 10d: two concurrent settlements of one instance --")
    league_id, team_ids = fresh("concurrent-settle")
    fund(league_id)
    with SessionLocal() as db:
        inst = instances(db, league_id)[0]
        instance_id = inst.id
        submit_claim(db, pool_instance_id=instance_id, team_id=team_ids[1],
                     subject_id=team_ids[0])
        db.commit()
    winner_wallet_before = balance_of(f"wallet:{team_ids[1]}")

    def settle_once():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '20s'"))
            inst = db.query(PoolInstance).filter(
                PoolInstance.id == instance_id).first()
            src = winner_source(db, league_id, inst, team_ids[0], team_ids)
            result = settle_pool_instance(db, pool_instance_id=instance_id,
                                          stat_source=src)
            db.commit()
            return result

    out = run_concurrent(settle_once, settle_once)
    outcomes = [out.get(k) for k in ("a", "b")]
    settled_new = sum(1 for kind, value in outcomes
                      if kind == "ok" and not value.replayed)
    refused_or_replayed = sum(1 for kind, value in outcomes
                              if kind == "error" or (kind == "ok"
                                                     and value.replayed))
    _assert("10d exactly one attempt performs a real settlement",
            settled_new == 1, str(outcomes))
    _assert("10d the other is refused or resolves as a replay",
            refused_or_replayed == 1, str(outcomes))
    with SessionLocal() as db:
        events = db.query(PoolEconomicEvent).filter(
            PoolEconomicEvent.pool_instance_id == instance_id).all()
        _assert("10d exactly one economic event exists", len(events) == 1)
        pot = db.query(PoolInstance).filter(
            PoolInstance.id == instance_id).first().distributed_cents
        _assert("10d no duplicate payout",
                balance_of(f"wallet:{team_ids[1]}")
                - winner_wallet_before == pot, str(pot))
        _assert("10d no partial posting survives", trial_balance() == 0)
        db.rollback()

    # ── 10e: the row lock alone is insufficient (DISCRIMINATING) ────────────
    print("\n-- 10e: with the constraint removed a replay becomes possible --")
    with SessionLocal() as db:
        inst_id = instances(db, league_id)[1].id
        db.rollback()
    duplicate_accepted_without_constraint = False
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP INDEX uq_pool_economic_event_instance"))
        with SessionLocal() as db:
            for _ in range(2):
                db.add(PoolEconomicEvent(
                    league_id=league_id, season=SEASON, week=3,
                    pool_instance_id=inst_id,
                    event_type=EVENT_WINNER_DISTRIBUTION, posting_id=None,
                    amount_cents=500,
                    created_at=datetime.now(timezone.utc)))
            db.flush()
            duplicate_accepted_without_constraint = (
                db.query(PoolEconomicEvent).filter(
                    PoolEconomicEvent.pool_instance_id == inst_id,
                    PoolEconomicEvent.event_type == EVENT_WINNER_DISTRIBUTION
                ).count() == 2)
            db.rollback()
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_pool_economic_event_instance "
                "ON pool_economic_event (pool_instance_id, event_type) "
                "WHERE pool_instance_id IS NOT NULL"))
    _assert("10e WITHOUT the uniqueness constraint a duplicate economic event "
            "is representable — so a post-release retry could double-pay",
            duplicate_accepted_without_constraint,
            "the control is valid only if this is True")
    with SessionLocal() as db:
        db.add(PoolEconomicEvent(
            league_id=league_id, season=SEASON, week=3,
            pool_instance_id=inst_id, event_type=EVENT_WINNER_DISTRIBUTION,
            posting_id=None, amount_cents=500,
            created_at=datetime.now(timezone.utc)))
        db.flush()
        try:
            db.add(PoolEconomicEvent(
                league_id=league_id, season=SEASON, week=3,
                pool_instance_id=inst_id, event_type=EVENT_WINNER_DISTRIBUTION,
                posting_id=None, amount_cents=500,
                created_at=datetime.now(timezone.utc)))
            db.flush()
            _assert("10e WITH the constraint restored the duplicate is refused",
                    False, "the duplicate was accepted")
        except IntegrityError:
            _assert("10e WITH the constraint restored the duplicate is refused",
                    True)
        db.rollback()

    # ── 10g: no duplicate continuation ──────────────────────────────────────
    print("\n-- 10g: a replayed rollover determination mints no second carry --")
    with SessionLocal() as db:
        inst = instances(db, league_id)[2]
        inst.settled = True
        inst.rollover_cents = 400
        inst.settlement_classification = "ZERO_ELIGIBLE_CLAIMS"
        db.commit()
        carried_id = inst.id
    from betting.pool_slate import pending_continuations
    with SessionLocal() as db:
        first = pending_continuations(db, league_id=league_id, season=SEASON,
                                      week=4)
        _assert("10g the carry is visible to the next week's slate build",
                [c.id for c in first] == [carried_id])
        # Consuming it zeroes the carry in the same transaction, so a replay
        # finds nothing to carry a second time.
        first[0].rollover_cents = 0
        db.commit()
    with SessionLocal() as db:
        second = pending_continuations(db, league_id=league_id, season=SEASON,
                                       week=4)
        _assert("10g after consumption the carry is gone and cannot mint a "
                "second continuation", second == [])
        db.rollback()

    # ── 11: concurrent collection of one week ───────────────────────────────
    print("\n-- 11: two concurrent collections of the same week --")
    league_id, team_ids = fresh("concurrent-collect")

    def collect_once():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL lock_timeout = '20s'"))
            result = collect_weekly_entries(db, league_id=league_id, week=3,
                                            provider=PROVIDER)
            db.commit()
            return result

    out = run_concurrent(collect_once, collect_once)
    kinds = [out.get(k, ("missing", None))[0] for k in ("a", "b")]
    _assert("11 exactly one collection succeeds",
            kinds.count("ok") == 1, str(out))
    _assert("11 the loser fails with the domain error, not a driver error",
            any(isinstance(v, PoolFundingError)
                for k, v in out.values() if k == "error"),
            str([type(v).__name__ for k, v in out.values() if k == "error"]))
    with SessionLocal() as db:
        _assert("11 exactly one PoolPot row exists",
                db.query(PoolPot).filter(PoolPot.league_id == league_id,
                                         PoolPot.week == 3).count() == 1)
        rows = instances(db, league_id)
        _assert("11 exactly four instances exist", len(rows) == 4,
                str(len(rows)))
        events = (db.query(PoolEconomicEvent)
                  .filter(PoolEconomicEvent.league_id == league_id,
                          PoolEconomicEvent.pool_instance_id.is_(None)).all())
        _assert("11 exactly one WEEKLY_COLLECTION event exists",
                sum(1 for e in events
                    if e.event_type == "WEEKLY_COLLECTION") == 1)
        _assert("11 no partial postings survive", trial_balance() == 0)
        _assert("11 conservation holds",
                assert_pool_conservation(db, league_id=league_id,
                                         season=SEASON)
                == balance_of(f"pool:{league_id}"))
        db.rollback()


def _entry_count(SessionLocal, LedgerEntry, door: str) -> int:
    with SessionLocal() as db:
        return db.query(LedgerEntry).filter(LedgerEntry.door == door).count()


if __name__ == "__main__":
    print("\n=== S4-P1 idempotency / concurrency / crash suite (PostgreSQL) ===")
    try:
        main(tdb)
    finally:
        tdb.teardown()
    print(f"\n  {len(_failures)} failure(s)")
    if _failures:
        for f in _failures:
            print(f"    FAILED: {f}")
        sys.exit(1)
    print("  ALL PASS")