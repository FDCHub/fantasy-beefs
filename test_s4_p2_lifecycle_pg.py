"""
test_s4_p2_lifecycle_pg.py — S4-P2 hardening on real PostgreSQL.

Covers S4-P2-1 through S4-P2-5 and the §3 concurrency/idempotency additions.

WHY SAVEPOINTS ARE TESTED AS A BEHAVIOUR, NOT AS AN IMPLEMENTATION DETAIL. The
S4-P2-2 scenario does not check that `begin_nested()` was called; it checks that
after one instance refuses, its three siblings STILL HOLD their ledger postings
and their settled flags. An implementation without savepoint isolation loses
those postings when the refusal propagates, so the assertion discriminates on
outcome rather than on mechanism.

Requires TEST_DATABASE_URL -> a local, disposable, empty, _test-named database.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_support_postgres import setup_postgres_test_db  # noqa: E402

try:
    tdb = setup_postgres_test_db()
except RuntimeError as e:
    print(f"\n[HARNESS ERROR] S4-P2 lifecycle suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def main(tdb) -> None:
    from sqlalchemy import text

    from betting.pool_claims import PoolClaimError, submit_claim
    from betting.pool_funding import (
        PoolFundingError, collect_weekly_entries, configure_pool_weekly_entry,
    )
    from betting.pool_legacy_guard import LegacyPoolPathRefused
    from betting.pool_settlement import (
        assert_pool_conservation, settle_pool_instance,
    )
    from db.schema import (
        PoolClaim, PoolConfig, PoolEconomicEvent, PoolInstance, PoolPot,
        SessionLocal, Wallet,
    )
    from ledger.ledger import LedgerEntry, balance_of, trial_balance
    from test_support_s4_pool import (
        FOUR_TEAM_KEYS, PROVIDER, REQUIRED_STAT, DefinitionStatSource,
        add_week_matchups, add_week_schedule, make_league, mark_ready,
        seed_catalog, settle_each_isolated, team_subjects,
    )

    SEASON = 2026

    def fresh(name, n_teams=4, weeks=(4, 5)):
        tdb.reset()
        with SessionLocal() as db:
            seed_catalog(db)
            league, teams = make_league(db, name=name, season=SEASON,
                                        n_teams=n_teams)
            mark_ready(db, league_id=league.id, keys=FOUR_TEAM_KEYS)
            for week in weeks:
                add_week_schedule(db, season=SEASON, week=week, name=name)
                add_week_matchups(db, league_id=league.id, week=week,
                                  teams=teams)
            db.commit()
            return league.id, [t.id for t in teams]

    def instances(db, league_id, week=3):
        return (db.query(PoolInstance)
                .filter(PoolInstance.league_id == league_id,
                        PoolInstance.week == week)
                .order_by(PoolInstance.slot).all())

    def sources(db, league_id, week, team_ids, *, incomplete_slot=None):
        """One recorded source for the week.

        `incomplete_slot` omits one team's facts from that slot's definition,
        which makes exactly one subject unevaluable and drives that instance to
        INCOMPLETE_FIELD while its siblings stay fully evaluable."""
        from db.schema import Team
        teams = (db.query(Team).filter(Team.league_id == league_id)
                 .order_by(Team.id).all())
        by_definition = {}
        for idx, inst in enumerate(instances(db, league_id, week)):
            stat = REQUIRED_STAT[inst.definition_key]
            values = {t.id: float(10 + i) for i, t in enumerate(teams)}
            values[team_ids[0]] = 99.0          # deterministic winner
            if incomplete_slot is not None and idx == incomplete_slot:
                values.pop(team_ids[-1])        # one subject unevaluable
            by_definition[inst.definition_key] = team_subjects(
                teams, stat=stat, values=values)
        return DefinitionStatSource(by_definition)

    def legs(db, instance_id):
        event = (db.query(PoolEconomicEvent)
                 .filter(PoolEconomicEvent.pool_instance_id == instance_id,
                         PoolEconomicEvent.event_type == "WINNER_DISTRIBUTION")
                 .one_or_none())
        if event is None:
            return {}
        rows = (db.query(LedgerEntry)
                .filter(LedgerEntry.posting_id == event.posting_id).all())
        return {int(r.account.split(":", 1)[1]): int(r.amount_cents)
                for r in rows if r.account.startswith("wallet:")}

    # ════ S4-P2-1 — legacy economic path ════════════════════════════════════
    print("\n== S4-P2-1: legacy Pool economic path is refused ==")
    league_id, team_ids = fresh("legacy-guard")
    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=league_id, week=3,
                               provider=PROVIDER)
        db.commit()

    from betting.pool_engine import (
        collect_weekly_entries as legacy_collect, settle_pool as legacy_settle,
        setup_pool_config,
    )

    with SessionLocal() as db:
        setup_pool_config(league_id=league_id, weekly_entry_cents=1000,
                          worst_beat_rollover=True, db=db)
        db.commit()

    def snapshot():
        with SessionLocal() as db:
            pots = {(p.league_id, p.week): (p.entries_collected, p.settled,
                                            p.total_pot_cents,
                                            p.worst_beat_rollover_cents)
                    for p in db.query(PoolPot).all()}
            insts = {i.id: (i.pot_cents, i.rollover_cents, i.settled,
                            i.distributed_cents)
                     for i in db.query(PoolInstance).all()}
            events = db.query(PoolEconomicEvent).count()
            entries = db.query(LedgerEntry).count()
            db.rollback()
        return pots, insts, events, entries, balance_of(f"pool:{league_id}")

    before = snapshot()
    for label, fn in (("collect", lambda db: legacy_collect(league_id, 3, db)),
                      ("settle", lambda db: legacy_settle(league_id, 3, db))):
        refused = None
        with SessionLocal() as db:
            try:
                fn(db)
            except LegacyPoolPathRefused as exc:
                refused = exc
            except Exception as exc:  # noqa: BLE001
                refused = exc
            db.rollback()
        _assert(f"S4-P2-1 legacy {label} is refused for a Rev1.3 league",
                isinstance(refused, LegacyPoolPathRefused),
                type(refused).__name__ if refused else "did not raise")

    after = snapshot()
    _assert("S4-P2-1 no PoolPot was altered", before[0] == after[0])
    _assert("S4-P2-1 no PoolInstance was altered", before[1] == after[1])
    _assert("S4-P2-1 no PoolEconomicEvent was created",
            before[2] == after[2], f"{before[2]} -> {after[2]}")
    _assert("S4-P2-1 no Ledger entry was posted",
            before[3] == after[3], f"{before[3]} -> {after[3]}")
    _assert("S4-P2-1 the pool account is unchanged", before[4] == after[4])
    _assert("S4-P2-1 trial balance is zero", trial_balance() == 0)

    print("  -- the guard is inert for a league that never crossed over --")
    tdb.reset()
    with SessionLocal() as db:
        seed_catalog(db)
        legacy_league, legacy_teams = make_league(db, name="legacy-only",
                                                  season=SEASON)
        db.commit()
        legacy_id = legacy_league.id
    with SessionLocal() as db:
        setup_pool_config(league_id=legacy_id, weekly_entry_cents=1000,
                          worst_beat_rollover=True, db=db)
        db.commit()
    with SessionLocal() as db:
        ok = True
        try:
            legacy_collect(legacy_id, 3, db)
            db.commit()
        except LegacyPoolPathRefused:
            ok = False
        except Exception:  # noqa: BLE001
            pass          # other legacy failures are not this guard's business
        db.rollback()
    _assert("S4-P2-1 a legacy-only league is NOT blocked by the guard", ok)

    # ════ S4-P2-2 — per-instance isolation ══════════════════════════════════
    print("\n== S4-P2-2: one refusal must not erase settled siblings ==")
    league_id, team_ids = fresh("isolation")
    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=league_id, week=3,
                               provider=PROVIDER)
        db.commit()
    with SessionLocal() as db:
        rows = instances(db, league_id, 3)
        for inst in rows:
            submit_claim(db, pool_instance_id=inst.id, team_id=team_ids[1],
                         subject_id=team_ids[0])
        db.commit()
        pot_cents = rows[0].pot_cents

    with SessionLocal() as db:
        source = sources(db, league_id, 3, team_ids, incomplete_slot=2)
        settled, refused, container = settle_each_isolated(
            db, league_id=league_id, week=3, source=source)
        db.commit()

    _assert("S4-P2-2 three instances settle", len(settled) == 3,
            str(len(settled)))
    _assert("S4-P2-2 exactly one instance refuses", len(refused) == 1,
            str([r.classification for r in refused]))
    _assert("S4-P2-2 the refusal is the governed INCOMPLETE_FIELD",
            refused and refused[0].classification == "INCOMPLETE_FIELD",
            refused[0].classification if refused else "none")
    _assert("S4-P2-2 the week container remains UNSETTLED", container is False)

    with SessionLocal() as db:
        rows = instances(db, league_id, 3)
        settled_rows = [r for r in rows if r.settled]
        unsettled_rows = [r for r in rows if not r.settled]
        _assert("S4-P2-2 three instances are marked settled",
                len(settled_rows) == 3)
        _assert("S4-P2-2 the refused instance is NOT settled",
                len(unsettled_rows) == 1
                and unsettled_rows[0].distributed_cents == 0)
        _assert("S4-P2-2 the refused instance posted NOTHING",
                db.query(PoolEconomicEvent).filter(
                    PoolEconomicEvent.pool_instance_id
                    == unsettled_rows[0].id).count() == 0)
        _assert("S4-P2-2 each settled sibling RETAINS its posting",
                all(sum(legs(db, r.id).values()) == pot_cents
                    for r in settled_rows),
                str([sum(legs(db, r.id).values()) for r in settled_rows]))
        _assert("S4-P2-2 the refused instance's pot is intact",
                unsettled_rows[0].pot_cents == pot_cents)
        pot = (db.query(PoolPot).filter(PoolPot.league_id == league_id,
                                        PoolPot.week == 3).one())
        _assert("S4-P2-2 PoolPot remains unsettled", pot.settled is False)
        _assert("S4-P2-2 conservation: only the refused pot is unresolved",
                assert_pool_conservation(db, league_id=league_id,
                                         season=SEASON) == pot_cents)
        db.rollback()
    _assert("S4-P2-2 trial balance is zero", trial_balance() == 0)

    # ════ S4-P2-3 — recovery, and the next week releases ════════════════════
    print("\n== S4-P2-3: refused instance recovers; week N+1 unblocks ==")
    with SessionLocal() as db:
        try:
            collect_weekly_entries(db, league_id=league_id, week=4,
                                   provider=PROVIDER)
            _assert("S4-P2-3 week N+1 collection is refused while week N is "
                    "incomplete", False, "it was allowed")
        except PoolFundingError as exc:
            _assert("S4-P2-3 week N+1 collection is refused while week N is "
                    "incomplete", exc.reason == "PRIOR_WEEK_UNSETTLED",
                    exc.reason)
        db.rollback()

    sibling_legs_before = {}
    with SessionLocal() as db:
        for row in instances(db, league_id, 3):
            if row.settled:
                sibling_legs_before[row.id] = legs(db, row.id)
        db.rollback()

    # Data arrives. Retry the week with a COMPLETE field.
    with SessionLocal() as db:
        source = sources(db, league_id, 3, team_ids)   # no omission now
        settled, refused, container = settle_each_isolated(
            db, league_id=league_id, week=3, source=source)
        db.commit()

    _assert("S4-P2-3 the retry settles exactly one new instance",
            len([r for r in settled if not r.replayed]) == 1,
            str([(r.pool_instance_id, r.replayed) for r in settled]))
    _assert("S4-P2-3 the already-settled siblings resolve as replays",
            len([r for r in settled if r.replayed]) == 3)
    _assert("S4-P2-3 nothing refuses on the retry", len(refused) == 0)
    _assert("S4-P2-3 the week container is NOW settled", container is True)

    with SessionLocal() as db:
        _assert("S4-P2-3 no duplicate sibling payout on retry",
                all(legs(db, iid) == before_legs
                    for iid, before_legs in sibling_legs_before.items()),
                str({iid: legs(db, iid) for iid in sibling_legs_before}))
        _assert("S4-P2-3 every instance has exactly one economic event",
                all(db.query(PoolEconomicEvent).filter(
                    PoolEconomicEvent.pool_instance_id == r.id).count() == 1
                    for r in instances(db, league_id, 3)))
        _assert("S4-P2-3 no stranded Pool balance",
                assert_pool_conservation(db, league_id=league_id,
                                         season=SEASON) == 0)
        db.rollback()
    _assert("S4-P2-3 trial balance is zero", trial_balance() == 0)

    with SessionLocal() as db:
        result = collect_weekly_entries(db, league_id=league_id, week=4,
                                        provider=PROVIDER)
        db.commit()
        _assert("S4-P2-3 week N+1 collection now succeeds",
                len(result.instance_ids) == 4)
    with SessionLocal() as db:
        try:
            collect_weekly_entries(db, league_id=league_id, week=4,
                                   provider=PROVIDER)
            _assert("S4-P2-3 week N+1 collects exactly once", False,
                    "a second collection was allowed")
        except PoolFundingError as exc:
            _assert("S4-P2-3 week N+1 collects exactly once",
                    exc.reason == "ALREADY_COLLECTED", exc.reason)
        db.rollback()
    _assert("S4-P2-3 trial balance is zero after the release",
            trial_balance() == 0)

    # ════ S4-P2-4 — claim against a settled instance ════════════════════════
    print("\n== S4-P2-4: a settled occurrence accepts no further claims ==")
    with SessionLocal() as db:
        settled_instance = [r for r in instances(db, league_id, 3)
                            if r.settled][0]
        instance_id = settled_instance.id
        claims_before = db.query(PoolClaim).filter(
            PoolClaim.pool_instance_id == instance_id).count()
        entries_before = db.query(LedgerEntry).count()
        db.rollback()
    pool_before = balance_of(f"pool:{league_id}")

    with SessionLocal() as db:
        try:
            submit_claim(db, pool_instance_id=instance_id,
                         team_id=team_ids[2], subject_id=team_ids[0])
            _assert("S4-P2-4 a claim on a settled occurrence is refused",
                    False, "it was accepted")
        except PoolClaimError as exc:
            _assert("S4-P2-4 a claim on a settled occurrence is refused",
                    exc.reason == "INSTANCE_SETTLED", exc.reason)
        db.rollback()

    with SessionLocal() as db:
        _assert("S4-P2-4 no new claim row was created",
                db.query(PoolClaim).filter(
                    PoolClaim.pool_instance_id == instance_id).count()
                == claims_before)
        _assert("S4-P2-4 zero Ledger movement",
                db.query(LedgerEntry).count() == entries_before
                and balance_of(f"pool:{league_id}") == pool_before)
        db.rollback()

    # ════ S4-P2-5 — weekly entry freeze ═════════════════════════════════════
    print("\n== S4-P2-5: the weekly contribution freezes at first collection ==")
    league_id, team_ids = fresh("freeze")
    with SessionLocal() as db:
        configure_pool_weekly_entry(db, league_id=league_id, cents=250)
        db.commit()
    with SessionLocal() as db:
        cfg = db.query(PoolConfig).filter(
            PoolConfig.league_id == league_id).one()
        _assert("S4-P2-5 configuration is not frozen before any collection",
                cfg.pool_weekly_entry_frozen_at is None
                and cfg.pool_weekly_entry_cents == 250)
        db.rollback()

    print("  -- a FAILED collection must not freeze --")
    # Drain one wallet so the collection's single posting is refused.
    with SessionLocal() as db:
        from ledger.ledger import post as ledger_post
        drained = team_ids[-1]
        balance = balance_of(f"wallet:{drained}")
        ledger_post([(f"wallet:{drained}", -balance), ("world", balance)],
                    door="buy_in_paid", session=db)
        db.commit()
    with SessionLocal() as db:
        failed = None
        try:
            collect_weekly_entries(db, league_id=league_id, week=3,
                                   provider=PROVIDER)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            failed = exc
            db.rollback()
    _assert("S4-P2-5 the underfunded collection failed",
            failed is not None, type(failed).__name__ if failed else "none")
    with SessionLocal() as db:
        cfg = db.query(PoolConfig).filter(
            PoolConfig.league_id == league_id).one()
        _assert("S4-P2-5 a rolled-back collection does NOT freeze",
                cfg.pool_weekly_entry_frozen_at is None)
        _assert("S4-P2-5 the configured value survives the failure",
                cfg.pool_weekly_entry_cents == 250)
        _assert("S4-P2-5 no instances survive the failed collection",
                db.query(PoolInstance).filter(
                    PoolInstance.league_id == league_id).count() == 0)
        db.rollback()
    _assert("S4-P2-5 trial balance is zero after the failure",
            trial_balance() == 0)

    print("  -- a SUCCESSFUL collection freezes, once --")
    with SessionLocal() as db:
        from ledger.ledger import post as ledger_post
        ledger_post([("world", -100_000), (f"wallet:{team_ids[-1]}", 100_000)],
                    door="buy_in_paid", session=db)
        db.commit()
    with SessionLocal() as db:
        result = collect_weekly_entries(db, league_id=league_id, week=3,
                                        provider=PROVIDER)
        db.commit()
        _assert("S4-P2-5 the collection used the configured 250 cents",
                result.weekly_entry_cents == 250)
    with SessionLocal() as db:
        cfg = db.query(PoolConfig).filter(
            PoolConfig.league_id == league_id).one()
        frozen_at, frozen_cents = (cfg.pool_weekly_entry_frozen_at,
                                   cfg.pool_weekly_entry_cents)
        _assert("S4-P2-5 the first successful collection stamps the freeze",
                frozen_at is not None and frozen_cents == 250)
        db.rollback()

    with SessionLocal() as db:
        try:
            configure_pool_weekly_entry(db, league_id=league_id, cents=300)
            _assert("S4-P2-5 a post-freeze configuration change is refused",
                    False, "it was accepted")
        except PoolFundingError as exc:
            _assert("S4-P2-5 a post-freeze configuration change is refused",
                    exc.reason == "ENTRY_FROZEN", exc.reason)
        db.rollback()

    with SessionLocal() as db:
        try:
            collect_weekly_entries(db, league_id=league_id, week=3,
                                   provider=PROVIDER)
        except PoolFundingError:
            pass
        db.rollback()
    with SessionLocal() as db:
        cfg = db.query(PoolConfig).filter(
            PoolConfig.league_id == league_id).one()
        _assert("S4-P2-5 a retried collection does not restamp the freeze",
                cfg.pool_weekly_entry_frozen_at == frozen_at
                and cfg.pool_weekly_entry_cents == frozen_cents,
                f"{cfg.pool_weekly_entry_frozen_at} / "
                f"{cfg.pool_weekly_entry_cents}")
        db.rollback()

    # ════ §3A — concurrent settle_week ══════════════════════════════════════
    print("\n== §3A: two concurrent settle_week calls ==")
    league_id, team_ids = fresh("concurrent-week")
    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=league_id, week=3,
                               provider=PROVIDER)
        db.commit()
    with SessionLocal() as db:
        for inst in instances(db, league_id, 3):
            submit_claim(db, pool_instance_id=inst.id, team_id=team_ids[1],
                         subject_id=team_ids[0])
        db.commit()
        pot_cents = instances(db, league_id, 3)[0].pot_cents

    wallet_before = balance_of(f"wallet:{team_ids[1]}")
    barrier = threading.Barrier(2, timeout=60)
    outcomes = {}

    def settle_all(tag):
        def run():
            try:
                with SessionLocal() as db:
                    db.execute(text("SET LOCAL lock_timeout = '30s'"))
                    source = sources(db, league_id, 3, team_ids)
                    barrier.wait()
                    settled, refused, container = settle_each_isolated(
                        db, league_id=league_id, week=3, source=source)
                    db.commit()
                    outcomes[tag] = ("ok", len(settled), len(refused))
            except Exception as exc:  # noqa: BLE001
                outcomes[tag] = ("error", type(exc).__name__, str(exc)[:80])
        return run

    threads = [threading.Thread(target=settle_all("a")),
               threading.Thread(target=settle_all("b"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(90)

    _assert("§3A both settle_week calls terminate", len(outcomes) == 2,
            str(outcomes))
    with SessionLocal() as db:
        rows = instances(db, league_id, 3)
        _assert("§3A every instance settled exactly once",
                all(r.settled for r in rows)
                and all(db.query(PoolEconomicEvent).filter(
                    PoolEconomicEvent.pool_instance_id == r.id).count() == 1
                    for r in rows), str(outcomes))
        _assert("§3A no duplicate posting: one WINNER_DISTRIBUTION per instance",
                all(len(legs(db, r.id)) == 1 for r in rows))
        _assert("§3A no duplicate GM credit",
                balance_of(f"wallet:{team_ids[1]}") - wallet_before
                == pot_cents * 4,
                str(balance_of(f"wallet:{team_ids[1]}") - wallet_before))
        pot = (db.query(PoolPot).filter(PoolPot.league_id == league_id,
                                        PoolPot.week == 3).one())
        _assert("§3A the week container is settled exactly once",
                pot.settled is True)
        _assert("§3A final state is consistent",
                assert_pool_conservation(db, league_id=league_id,
                                         season=SEASON) == 0)
        db.rollback()
    _assert("§3A trial balance is zero", trial_balance() == 0)

    print("  -- deterministic interleave on one instance --")
    league_id, team_ids = fresh("interleave")
    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=league_id, week=3,
                               provider=PROVIDER)
        db.commit()
    with SessionLocal() as db:
        target = instances(db, league_id, 3)[0]
        target_id = target.id
        submit_claim(db, pool_instance_id=target_id, team_id=team_ids[1],
                     subject_id=team_ids[0])
        db.commit()
    wallet_before = balance_of(f"wallet:{team_ids[1]}")

    b_out = {}

    def run_b():
        try:
            with SessionLocal() as db:
                db.execute(text("SET LOCAL lock_timeout = '30s'"))
                source = sources(db, league_id, 3, team_ids)
                result = settle_pool_instance(
                    db, pool_instance_id=target_id,
                    stat_source=source.for_definition(
                        db.query(PoolInstance).filter(
                            PoolInstance.id == target_id).one().definition_key))
                db.commit()
                b_out["value"] = result
        except Exception as exc:  # noqa: BLE001
            b_out["error"] = exc

    thread_b = threading.Thread(target=run_b)
    with SessionLocal() as a:
        a.execute(text("SET LOCAL lock_timeout = '30s'"))
        source = sources(a, league_id, 3, team_ids)
        key = a.query(PoolInstance).filter(
            PoolInstance.id == target_id).one().definition_key
        settle_pool_instance(a, pool_instance_id=target_id,
                             stat_source=source.for_definition(key))
        thread_b.start()
        time.sleep(1.5)      # B reaches the row lock / the event insert
        a.commit()
    thread_b.join(60)

    _assert("§3A the interleaved second attempt resolves",
            "value" in b_out or "error" in b_out, str(b_out))
    _assert("§3A it neither double-pays nor double-posts",
            balance_of(f"wallet:{team_ids[1]}") - wallet_before
            == pot_cents,
            str(balance_of(f"wallet:{team_ids[1]}") - wallet_before))
    with SessionLocal() as db:
        _assert("§3A exactly one economic event for the contested instance",
                db.query(PoolEconomicEvent).filter(
                    PoolEconomicEvent.pool_instance_id == target_id
                ).count() == 1)
        db.rollback()
    _assert("§3A trial balance is zero after the interleave",
            trial_balance() == 0)

    # ════ §3B — retry after committed economics ═════════════════════════════
    print("\n== §3B: retry after a committed settlement, response lost ==")
    league_id, team_ids = fresh("lost-ack")
    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=league_id, week=3,
                               provider=PROVIDER)
        db.commit()
    with SessionLocal() as db:
        rows = instances(db, league_id, 3)
        for inst in rows:
            for gm in team_ids[:3]:
                submit_claim(db, pool_instance_id=inst.id, team_id=gm,
                             subject_id=team_ids[0])
        db.commit()

    with SessionLocal() as db:
        source = sources(db, league_id, 3, team_ids)
        settle_each_isolated(db, league_id=league_id, week=3, source=source)
        db.commit()
        # The caller never retains the result — simulate the lost response.

    with SessionLocal() as db:
        allocation_before = {r.id: legs(db, r.id)
                             for r in instances(db, league_id, 3)}
        entries_before = db.query(LedgerEntry).count()
        db.rollback()
    wallets_before = {t: balance_of(f"wallet:{t}") for t in team_ids}

    with SessionLocal() as db:
        source = sources(db, league_id, 3, team_ids)
        settled, refused, _ = settle_each_isolated(
            db, league_id=league_id, week=3, source=source)
        db.commit()

    _assert("§3B every instance reports a replay, not a new settlement",
            len(settled) == 4 and all(r.replayed for r in settled),
            str([(r.pool_instance_id, r.replayed) for r in settled]))
    _assert("§3B nothing refuses", len(refused) == 0)
    with SessionLocal() as db:
        allocation_after = {r.id: legs(db, r.id)
                            for r in instances(db, league_id, 3)}
        _assert("§3B the per-GM allocation is identical cent-for-cent",
                allocation_after == allocation_before,
                f"{allocation_before} -> {allocation_after}")
        _assert("§3B no reposting occurred",
                db.query(LedgerEntry).count() == entries_before)
        db.rollback()
    _assert("§3B no wallet moved on the retry",
            all(balance_of(f"wallet:{t}") == wallets_before[t]
                for t in team_ids))
    _assert("§3B trial balance is zero", trial_balance() == 0)


if __name__ == "__main__":
    print("\n=== S4-P2 lifecycle / hardening suite (PostgreSQL) ===")
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