"""
test_s4_pool_legacy_rollover_pg.py — legacy Worst Beat carry migration.

Owner ruling, 2026-08-08. Covers Scope §H scenario 21 as the ruling redefines
it: the live balance is PRESERVED EXACTLY, not into `pool_instance`, but into
`championship:{league_id}`.

EACH OF THE TEN RULES IS ASSERTED SEPARATELY. They are not one property, and a
migration can satisfy most of them while failing one in a way that costs real
money — a retry that double-credits, or a zeroed column whose transfer rolled
back. So each gets its own assertion, and the two that are only observable under
failure (rules 5 and 6) get their own scenarios rather than being inferred from
a successful run.

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
    print(f"\n[HARNESS ERROR] legacy rollover suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def run_concurrent(fn_a, fn_b, timeout=30):
    """Two callables on real threads, released at one barrier."""
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

    from db.migrations.migrate_s4_pool_rollover_money import (
        DOOR_LEGACY_WORST_BEAT_MIGRATION, SOURCE_FIELD, measure,
        migration_key_for, upgrade,
    )
    from db.schema import (
        PoolInstance, PoolLegacyRolloverMigration, PoolPot, SessionLocal, engine,
    )
    from ledger.ledger import LedgerEntry, balance_of, post as ledger_post, \
        trial_balance
    from test_support_s4_pool import make_league, seed_catalog

    SEASON = 2026

    def seed_legacy_carry(name, per_week):
        """A league whose pool account really holds a legacy carry.

        The cents are put into `pool:{league_id}` through a REAL ledger posting,
        because that is where the legacy engine leaves them —
        `worst_beat_rollover_cents` is a column recording how much of the pool
        balance is spoken for, not a separate account. A fixture that set only
        the column would leave nothing for the migration to debit and the test
        would prove nothing."""
        tdb.reset()
        with SessionLocal() as db:
            seed_catalog(db)
            league, teams = make_league(db, name=name, season=SEASON)
            db.flush()
            total = sum(per_week.values())
            if total:
                ledger_post([("world", -total), (f"pool:{league.id}", total)],
                            door="buy_in_paid", session=db)
            for week, cents in per_week.items():
                db.add(PoolPot(league_id=league.id, week=week,
                               worst_beat_rollover_cents=cents,
                               entries_collected=True, total_pot_cents=0,
                               settled=True))
            db.commit()
            return league.id

    # ── rule 8: a zero balance is a verified no-op ──────────────────────────
    print("\n-- rule 8: zero legacy balance is a verified no-op --")
    league_id = seed_legacy_carry("legacy-zero", {3: 0, 4: 0})
    champ_before = balance_of(f"championship:{league_id}")
    pool_before = balance_of(f"pool:{league_id}")
    result = upgrade(engine)
    _assert("8 nothing is reported as migrated",
            result == {"leagues": 0, "migrated_cents": 0, "skipped": 0},
            str(result))
    with SessionLocal() as db:
        _assert("8 no audit row is written",
                db.query(PoolLegacyRolloverMigration).count() == 0)
        _assert("8 no posting is written",
                db.query(LedgerEntry).filter(
                    LedgerEntry.door == DOOR_LEGACY_WORST_BEAT_MIGRATION
                ).count() == 0)
        db.rollback()
    _assert("8 championship is untouched",
            balance_of(f"championship:{league_id}") == champ_before)
    _assert("8 the pool account is untouched",
            balance_of(f"pool:{league_id}") == pool_before)
    _assert("8 trial balance is zero", trial_balance() == 0)

    # ── rules 1, 2, 3, 7, 9, 10: a live carry migrates ──────────────────────
    print("\n-- rules 1/2/3/7/9/10: a live carry migrates in full --")
    PER_WEEK = {3: 1234, 4: 5, 7: 761}
    TOTAL = sum(PER_WEEK.values())          # 2000
    league_id = seed_legacy_carry("legacy-live", PER_WEEK)
    champ_before = balance_of(f"championship:{league_id}")
    pool_before = balance_of(f"pool:{league_id}")
    _assert("the fixture really holds the carry in the pool account",
            pool_before == TOTAL, str(pool_before))

    measured = measure(engine)
    _assert("measure aggregates per league across weeks",
            measured == {league_id: {"amount_cents": TOTAL,
                                     "weeks": sorted(PER_WEEK)}},
            str(measured))

    result = upgrade(engine)
    _assert("the run reports one league and the exact total",
            result["leagues"] == 1 and result["migrated_cents"] == TOTAL
            and result["skipped"] == 0, str(result))
    _assert("2 championship is credited the EXACT integer-cent amount",
            balance_of(f"championship:{league_id}") - champ_before == TOTAL,
            str(balance_of(f"championship:{league_id}") - champ_before))
    _assert("2 the legacy balance is debited from the pool account",
            balance_of(f"pool:{league_id}") == pool_before - TOTAL)
    _assert("2 the transfer balances exactly", trial_balance() == 0)

    with SessionLocal() as db:
        pots = (db.query(PoolPot).filter(PoolPot.league_id == league_id).all())
        _assert("3 every contributing week's legacy column is zeroed",
                all((p.worst_beat_rollover_cents or 0) == 0 for p in pots),
                str([p.worst_beat_rollover_cents for p in pots]))

        rows = db.query(PoolLegacyRolloverMigration).all()
        _assert("7 exactly one immutable audit row exists", len(rows) == 1,
                str(len(rows)))
        row = rows[0]
        _assert("7 the audit row identifies the league",
                row.league_id == league_id)
        _assert("7 the audit row names the source legacy field",
                row.source_field == SOURCE_FIELD, row.source_field)
        _assert("7 the audit row records the contributing weeks",
                sorted(row.source_weeks) == sorted(PER_WEEK),
                str(row.source_weeks))
        _assert("7 the audit row records the exact amount",
                row.amount_cents == TOTAL, str(row.amount_cents))
        _assert("7 the audit row names the destination account",
                row.destination_account == f"championship:{league_id}",
                row.destination_account)
        _assert("7 the audit row carries the idempotency identity",
                row.migration_key == migration_key_for(league_id),
                row.migration_key)
        _assert("7 the audit row carries the real posting id, not a placeholder",
                row.posting_id is not None
                and str(row.posting_id)
                != "00000000-0000-0000-0000-000000000000")

        entries = (db.query(LedgerEntry)
                   .filter(LedgerEntry.door
                           == DOOR_LEGACY_WORST_BEAT_MIGRATION).all())
        _assert("2 exactly one two-leg posting was written", len(entries) == 2,
                str(len(entries)))
        _assert("7 the audit row's posting id matches the ledger entries",
                {str(e.posting_id) for e in entries} == {str(row.posting_id)})
        _assert("2 the posting legs sum to zero",
                sum(e.amount_cents for e in entries) == 0)

        _assert("1/9 no pool_instance row was created — no successor Worst "
                "Beat occurrence exists",
                db.query(PoolInstance).count() == 0)
        _assert("10 no rollover lineage was written",
                db.query(PoolInstance).filter(
                    PoolInstance.origin_instance_id.isnot(None)).count() == 0)
        db.rollback()

    # ── rules 4, 5: a retry cannot double-credit ────────────────────────────
    print("\n-- rules 4/5: retry is harmless and never double-credits --")
    champ_after_first = balance_of(f"championship:{league_id}")
    pool_after_first = balance_of(f"pool:{league_id}")
    retry = upgrade(engine)
    _assert("5 the retry reports nothing migrated",
            retry["migrated_cents"] == 0, str(retry))
    _assert("5 championship is not credited a second time",
            balance_of(f"championship:{league_id}") == champ_after_first)
    _assert("5 the pool account is not debited a second time",
            balance_of(f"pool:{league_id}") == pool_after_first)
    with SessionLocal() as db:
        _assert("5 still exactly one audit row",
                db.query(PoolLegacyRolloverMigration).count() == 1)
        _assert("5 still exactly one two-leg posting",
                db.query(LedgerEntry).filter(
                    LedgerEntry.door == DOOR_LEGACY_WORST_BEAT_MIGRATION
                ).count() == 2)
        db.rollback()
    _assert("5 trial balance is still zero", trial_balance() == 0)

    print("\n-- rule 4: the idempotency key is deterministic, never a clock --")
    _assert("4 the key is a pure function of the league id",
            migration_key_for(41) == migration_key_for(41)
            and migration_key_for(41) != migration_key_for(42),
            migration_key_for(41))
    with SessionLocal() as db:
        # The constraint, not the application check, is the enforcement.
        try:
            db.execute(text("""
                INSERT INTO pool_legacy_rollover_migration
                    (migration_key, league_id, source_field, source_weeks,
                     amount_cents, destination_account, posting_id, migrated_at)
                VALUES (:key, :lid, 'x', '[]', 1, 'y',
                        '00000000-0000-0000-0000-000000000001', :now)
            """), {"key": migration_key_for(league_id), "lid": league_id,
                   "now": datetime.now(timezone.utc)})
            db.flush()
            _assert("4 a duplicate migration_key is refused by the database",
                    False, "the insert succeeded")
        except Exception as exc:  # noqa: BLE001
            _assert("4 a duplicate migration_key is refused by the database",
                    "uq_pool_legacy_rollover_migration_key" in str(exc)
                    or "unique" in str(exc).lower(), type(exc).__name__)
        db.rollback()

    # ── rule 5 under contention: the condition that actually matters ────────
    print("\n-- rule 5: two CONCURRENT runs credit championship exactly once --")
    # The sequential retry above never reaches the uniqueness constraint,
    # because the first run zeroed the legacy column and the second therefore
    # measures nothing. The real double-credit risk is two runs that BOTH
    # measure the same live carry before either commits — so that is what is
    # exercised here, and it is the only scenario in which the constraint is
    # load-bearing.
    PER_WEEK_2 = {5: 900, 6: 100}
    TOTAL_2 = sum(PER_WEEK_2.values())
    league_id = seed_legacy_carry("legacy-concurrent", PER_WEEK_2)
    champ_before = balance_of(f"championship:{league_id}")
    pool_before = balance_of(f"pool:{league_id}")

    # BOTH THREADS ARE DRIVEN PAST `measure` DELIBERATELY. Racing two
    # `upgrade()` calls does NOT reliably exercise the constraint: whichever
    # thread commits first zeroes the legacy column, so the other measures zero,
    # returns early, and never reaches the posting at all. That run asserts
    # nothing about rule 5. Calling the per-league worker directly with an
    # already-measured amount puts both threads into the posting-and-claim path,
    # which is the only condition under which the uniqueness constraint is
    # load-bearing.
    from db.migrations.migrate_s4_pool_rollover_money import _migrate_one_league

    weeks = sorted(PER_WEEK_2)
    out = run_concurrent(
        lambda: _migrate_one_league(engine, league_id, TOTAL_2, weeks),
        lambda: _migrate_one_league(engine, league_id, TOTAL_2, weeks))
    _assert("5 both concurrent runs terminate", len(out) == 2, str(out))
    performed = [v for k, v in out.values() if k == "ok" and v is True]
    losers = [v for k, v in out.values()
              if k == "error" or (k == "ok" and v is False)]
    _assert("5 exactly one run performs the migration",
            len(performed) == 1, str(out))
    # WHICH GUARD refuses the loser is timing-dependent, and asserting a
    # specific one would be asserting the thread schedule rather than the
    # behavior. TWO independent guards can fire, and both are correct:
    #   - the idempotency constraint, when both runs post before either commits;
    #   - the ledger's funded-balance guard, when the winner has already
    #     committed and drained pool:{league_id}.
    # The property that matters — and the one asserted — is that the loser
    # moves nothing. The constraint's own refusal is proved deterministically
    # by the interleave below, not by hoping this race lands the right way.
    _assert("5 the other run is refused by a guard and moves nothing",
            len(losers) == 1,
            f"refused by {type(losers[0]).__name__ if losers else 'nothing'}")
    _assert("5 championship is credited EXACTLY once",
            balance_of(f"championship:{league_id}") - champ_before == TOTAL_2,
            str(balance_of(f"championship:{league_id}") - champ_before))
    _assert("5 the pool account is debited EXACTLY once",
            pool_before - balance_of(f"pool:{league_id}") == TOTAL_2)
    with SessionLocal() as db:
        rows = (db.query(PoolLegacyRolloverMigration)
                .filter(PoolLegacyRolloverMigration.league_id == league_id)
                .all())
        _assert("5 exactly one audit row survives", len(rows) == 1,
                str(len(rows)))
        entries = (db.query(LedgerEntry)
                   .filter(LedgerEntry.door
                           == DOOR_LEGACY_WORST_BEAT_MIGRATION,
                           LedgerEntry.account == f"championship:{league_id}")
                   .all())
        _assert("5 exactly one credit leg reached championship",
                len(entries) == 1, str(len(entries)))
        pots = (db.query(PoolPot)
                .filter(PoolPot.league_id == league_id).all())
        _assert("5 the legacy columns are zeroed once",
                all((p.worst_beat_rollover_cents or 0) == 0 for p in pots))
        db.rollback()
    _assert("5 trial balance is zero after the race", trial_balance() == 0)

    # ── rule 5, deterministic: the constraint itself refuses the second ─────
    print("\n-- rule 5 (deterministic): the constraint blocks the second claim --")
    # The dangerous interleave, forced rather than raced. Session A posts and
    # claims the key WITHOUT committing; B then posts (it cannot see A's
    # uncommitted debit, so the funded-balance guard passes) and blocks on the
    # unique index. A commits, B's ON CONFLICT DO NOTHING returns no row, and B
    # discards its posting. This is the ONLY path on which the idempotency
    # constraint — not the balance guard — is what prevents the double credit.
    import time

    PER_WEEK_3 = {8: 700, 9: 300}
    TOTAL_3 = sum(PER_WEEK_3.values())
    league_id = seed_legacy_carry("legacy-interleave", PER_WEEK_3)
    champ_before = balance_of(f"championship:{league_id}")
    weeks_3 = sorted(PER_WEEK_3)

    b_result = {}

    def run_b():
        try:
            b_result["value"] = _migrate_one_league(engine, league_id, TOTAL_3,
                                                    weeks_3)
        except Exception as exc:  # noqa: BLE001
            b_result["error"] = exc

    from ledger.ledger import post as ledger_post_fn

    thread_b = threading.Thread(target=run_b)
    with SessionLocal() as a:
        a.execute(text("SET LOCAL lock_timeout = '30s'"))
        ledger_post_fn(
            [(f"pool:{league_id}", -TOTAL_3),
             (f"championship:{league_id}", TOTAL_3)],
            door=DOOR_LEGACY_WORST_BEAT_MIGRATION, session=a)
        a.execute(text("""
            INSERT INTO pool_legacy_rollover_migration
                (migration_key, league_id, source_field, source_weeks,
                 amount_cents, destination_account, posting_id, migrated_at)
            VALUES (:key, :lid, :sf, '[]', :amt, :dest,
                    '00000000-0000-0000-0000-000000000009', :now)
        """), {"key": migration_key_for(league_id), "lid": league_id,
               "sf": SOURCE_FIELD, "amt": TOTAL_3,
               "dest": f"championship:{league_id}",
               "now": datetime.now(timezone.utc)})
        a.flush()
        thread_b.start()
        time.sleep(1.5)          # let B post and reach the blocking insert
        a.commit()               # B now resolves against a committed conflict
    thread_b.join(30)

    _assert("5 the blocked run resolves rather than hanging",
            "value" in b_result or "error" in b_result, str(b_result))
    _assert("5 the blocked run is refused at the idempotency constraint",
            b_result.get("value") is False,
            str(b_result.get("error") or b_result.get("value")))
    _assert("5 championship is credited exactly once across the interleave",
            balance_of(f"championship:{league_id}") - champ_before == TOTAL_3,
            str(balance_of(f"championship:{league_id}") - champ_before))
    with SessionLocal() as db:
        _assert("5 exactly one audit row for the interleaved league",
                db.query(PoolLegacyRolloverMigration).filter(
                    PoolLegacyRolloverMigration.league_id == league_id
                ).count() == 1)
        _assert("5 exactly one credit leg reached championship",
                db.query(LedgerEntry).filter(
                    LedgerEntry.door == DOOR_LEGACY_WORST_BEAT_MIGRATION,
                    LedgerEntry.account == f"championship:{league_id}"
                ).count() == 1)
        db.rollback()
    _assert("5 trial balance is zero after the interleave", trial_balance() == 0)

    # ── rule 6: failure before commit changes neither side ──────────────────
    print("\n-- rule 6: a failure before commit leaves BOTH sides unchanged --")
    # The pool account is deliberately short of the recorded legacy column, so
    # the ledger's funded-balance guard refuses the posting. This is the honest
    # shape of the failure: a legacy column that overstates what the account
    # holds.
    tdb.reset()
    with SessionLocal() as db:
        seed_catalog(db)
        league, teams = make_league(db, name="legacy-short", season=SEASON)
        db.flush()
        short_league = league.id
        ledger_post([("world", -100), (f"pool:{short_league}", 100)],
                    door="buy_in_paid", session=db)
        db.add(PoolPot(league_id=short_league, week=3,
                       worst_beat_rollover_cents=5000,   # overstates the account
                       entries_collected=True, total_pot_cents=0, settled=True))
        db.commit()

    champ_before = balance_of(f"championship:{short_league}")
    pool_before = balance_of(f"pool:{short_league}")
    raised = None
    try:
        upgrade(engine)
    except Exception as exc:  # noqa: BLE001
        raised = exc
    _assert("6 the migration refuses rather than moving a partial amount",
            raised is not None,
            f"raised {type(raised).__name__}" if raised else "DID NOT RAISE")
    _assert("6 championship is unchanged",
            balance_of(f"championship:{short_league}") == champ_before)
    _assert("6 the pool account is unchanged",
            balance_of(f"pool:{short_league}") == pool_before)
    with SessionLocal() as db:
        pot = (db.query(PoolPot)
               .filter(PoolPot.league_id == short_league).first())
        _assert("6 the legacy column is NOT zeroed when the transfer failed",
                pot.worst_beat_rollover_cents == 5000,
                str(pot.worst_beat_rollover_cents))
        _assert("6 no audit row survives",
                db.query(PoolLegacyRolloverMigration).count() == 0)
        _assert("6 no posting survives",
                db.query(LedgerEntry).filter(
                    LedgerEntry.door == DOOR_LEGACY_WORST_BEAT_MIGRATION
                ).count() == 0)
        db.rollback()
    _assert("6 trial balance is zero", trial_balance() == 0)


if __name__ == "__main__":
    print("\n=== S4-P1 legacy Worst Beat rollover migration (PostgreSQL) ===")
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