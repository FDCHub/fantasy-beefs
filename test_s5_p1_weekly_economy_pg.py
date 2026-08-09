"""
test_s5_p1_weekly_economy_pg.py — S5-P1 money path on real PostgreSQL.

Opening allocation, the two door-bound issuance exemptions, Weekly Minimum
release and expiry, and the ONE shared min-first spend splitter used by both
Versus and Pool.

EVERY SOURCING CLAIM IS MEASURED FROM ACTUAL LEDGER LEGS, never from a returned
label. A function can report "min first" and post whatever it likes; the legs
are the only evidence that survives.

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
    print(f"\n[HARNESS ERROR] S5-P1 suite cannot run:\n  {e}")
    sys.exit(2)

_failures: list[str] = []


def _assert(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {label}{suffix}")
    if not condition:
        _failures.append(label)


def run_concurrent(fn_a, fn_b, timeout=60):
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
    import config

    from economy.economy_events import (
        expired_min_account, min_account,
        min_reserve_account, reserve_account, season_issuance_account,
        wallet_account,
    )
    from economy.season_allocation import activate_season_allocation
    from economy.spend_sourcing import plan_spend_split
    from economy.weekly_minimum import (
        WeeklyMinimumError, expire_week, expire_weekly_minimum, release_week,
        release_weekly_minimum,
    )
    from economy.economy_events import DuplicateEconomyEvent
    from db.schema import EconomyEvent, SessionLocal, Team, Wallet, League
    from ledger.ledger import (
        APPROVED_BAB_TOPOFF_DOOR, InsufficientFundsError,
        SEASON_ALLOCATION_DOOR, LedgerEntry, balance_of, post as ledger_post,
        trial_balance,
    )
    from payments.economy_config import DEFAULT_STOP

    SEASON = config.ALLOCATION_SEASON

    def make_league(name, n_teams=4, playoff_start=15):
        tdb.reset()
        with SessionLocal() as db:
            league = League(season=SEASON, name=name,
                            projection_source="fantasypros",
                            season_final_week=17,
                            playoff_start_week=playoff_start)
            db.add(league)
            db.flush()
            teams = []
            for i in range(n_teams):
                t = Team(league_id=league.id, team_name=f"{name}-{i}",
                         owner=f"o{i}", email=f"{name}-{i}@x.test")
                db.add(t)
                db.flush()
                db.add(Wallet(team_id=t.id, balance=0.0))
                teams.append(t)
            db.commit()
            return league.id, [t.id for t in teams]

    def legs_of(door):
        with SessionLocal() as db:
            rows = (db.query(LedgerEntry)
                    .filter(LedgerEntry.door == door)
                    .order_by(LedgerEntry.id).all())
            out = [(r.account, int(r.amount_cents)) for r in rows]
            db.rollback()
        return out

    # ════ 1. OPENING ALLOCATION ═════════════════════════════════════════════
    print("\n== opening allocation: Wallet 0 / min_reserve 140 / reserve 80 ==")
    league_id, team_ids = make_league("alloc")
    with SessionLocal() as db:
        result = activate_season_allocation(league_id, db)
    _assert("allocation created", result.created is True)
    _assert("the stop is the governed 220 default",
            (DEFAULT_STOP.buyin_cents, DEFAULT_STOP.min_reserve_cents,
             DEFAULT_STOP.reserve_cents) == (22000, 14000, 8000),
            str((DEFAULT_STOP.buyin_cents, DEFAULT_STOP.min_reserve_cents,
                 DEFAULT_STOP.reserve_cents)))

    issuance = season_issuance_account(league_id, SEASON)
    for team_id in team_ids:
        _assert(f"team {team_id}: Wallet receives 0",
                balance_of(wallet_account(team_id)) == 0,
                str(balance_of(wallet_account(team_id))))
        _assert(f"team {team_id}: min_reserve = 14000",
                balance_of(min_reserve_account(team_id)) == 14000,
                str(balance_of(min_reserve_account(team_id))))
        _assert(f"team {team_id}: reserve = 8000",
                balance_of(reserve_account(team_id)) == 8000,
                str(balance_of(reserve_account(team_id))))
    _assert("issuance source is season_issuance, debited 22000 per GM",
            balance_of(issuance) == -22000 * len(team_ids),
            str(balance_of(issuance)))
    _assert("bab_issuance was NOT used for the opening allocation",
            balance_of(f"bab_issuance:{league_id}:{SEASON}") == 0)
    _assert("no allocation leg touched a wallet",
            not any(a.startswith("wallet:")
                    for a, _ in legs_of(SEASON_ALLOCATION_DOOR)),
            str(legs_of(SEASON_ALLOCATION_DOOR))[:120])
    _assert("140 + 80 == 220 per GM, exact zero-sum posting",
            sum(amount for _, amount in legs_of(SEASON_ALLOCATION_DOOR)) == 0)
    _assert("trial balance is zero", trial_balance() == 0)
    with SessionLocal() as db:
        _assert("one OPENING_ALLOCATION event per GM",
                db.query(EconomyEvent).filter(
                    EconomyEvent.event_type == "OPENING_ALLOCATION").count()
                == len(team_ids))
        db.rollback()

    print("  -- retry and concurrency cannot double issue --")
    with SessionLocal() as db:
        replay = activate_season_allocation(league_id, db)
    _assert("retry is a replay, not a second issuance",
            replay.created is False)
    _assert("retry issued nothing further",
            balance_of(issuance) == -22000 * len(team_ids))

    league_id2, team_ids2 = make_league("alloc-concurrent")

    def activate():
        with SessionLocal() as db:
            return activate_season_allocation(league_id2, db)

    out = run_concurrent(activate, activate)
    created = [v for k, v in out.values() if k == "ok" and v.created]
    _assert("concurrent activation issues exactly once",
            len(created) == 1, str(out))
    _assert("concurrent activation left the exact single allocation",
            balance_of(season_issuance_account(league_id2, SEASON))
            == -22000 * len(team_ids2),
            str(balance_of(season_issuance_account(league_id2, SEASON))))
    _assert("trial balance is zero after the race", trial_balance() == 0)

    # ════ 2. THE TWO DOOR-BOUND ISSUANCE EXEMPTIONS ═════════════════════════
    print("\n== ledger guard: door-bound, never prefix-bound ==")
    probe_issuance = season_issuance_account(9901, SEASON)
    probe_bab = f"bab_issuance:9901:{SEASON}"

    def try_post(entries, door):
        try:
            ledger_post(entries, door=door)
            return None
        except InsufficientFundsError as exc:
            return exc

    _assert("(1) season_issuance:* may debit from zero under season_allocation",
            try_post([(probe_issuance, -100),
                      (min_reserve_account(team_ids[0]), 100)],
                     SEASON_ALLOCATION_DOOR) is None)
    _assert("(2) the exact opening allocation shape balances",
            balance_of(probe_issuance) == -100)
    for bad_door in ("wager_placed", "approved_bab_topoff",
                     "season_allocation_v2", "pool_payout"):
        _assert(f"(3) season_issuance:* refused under {bad_door!r}",
                try_post([(probe_issuance, -100),
                          (wallet_account(team_ids[0]), 100)],
                         bad_door) is not None)
    _assert("(4) bab_issuance:* remains refused under season_allocation",
            try_post([(probe_bab, -100),
                      (wallet_account(team_ids[0]), 100)],
                     SEASON_ALLOCATION_DOOR) is not None)
    _assert("(5) bab_issuance:* still succeeds under its canonical door",
            try_post([(probe_bab, -100),
                      (wallet_account(team_ids[0]), 100)],
                     APPROVED_BAB_TOPOFF_DOOR) is None)
    _assert("(6) no generic prefix exemption: 'issuance:' is not a namespace",
            try_post([("issuance:9901", -100),
                      (wallet_account(team_ids[0]), 100)],
                     SEASON_ALLOCATION_DOOR) is not None)
    _assert("(6) and the colon is required: 'season_issuance' stays guarded",
            try_post([("season_issuance", -100),
                      (wallet_account(team_ids[0]), 100)],
                     SEASON_ALLOCATION_DOOR) is not None)
    _assert("trial balance is zero after the guard probes",
            trial_balance() == 0)

    # ════ 3. WEEKLY RELEASE ═════════════════════════════════════════════════
    print("\n== weekly minimum release ==")
    league_id, team_ids = make_league("release")
    with SessionLocal() as db:
        activate_season_allocation(league_id, db)
    team = team_ids[0]

    with SessionLocal() as db:
        r = release_weekly_minimum(db, league_id=league_id, team_id=team, week=3)
        db.commit()
    _assert("exactly 1000 released", r.released_cents == 1000)
    _assert("min:{team}:3 holds 1000",
            balance_of(min_account(team, 3)) == 1000)
    _assert("min_reserve reduced by exactly 1000",
            balance_of(min_reserve_account(team)) == 13000)
    _assert("Wallet is untouched by release",
            balance_of(wallet_account(team)) == 0)
    _assert("trial balance is zero", trial_balance() == 0)

    with SessionLocal() as db:
        dup = None
        try:
            release_weekly_minimum(db, league_id=league_id, team_id=team, week=3)
            db.commit()
        except DuplicateEconomyEvent as exc:
            dup = exc
            db.rollback()
    _assert("duplicate release is refused at the event key", dup is not None,
            type(dup).__name__ if dup else "it succeeded")
    _assert("retry released nothing further",
            balance_of(min_account(team, 3)) == 1000
            and balance_of(min_reserve_account(team)) == 13000)

    def release_once():
        with SessionLocal() as db:
            r = release_weekly_minimum(db, league_id=league_id,
                                       team_id=team_ids[1], week=4)
            db.commit()
            return r

    out = run_concurrent(release_once, release_once)
    ok = [v for k, v in out.values() if k == "ok"]
    _assert("concurrent release produces exactly one release",
            len(ok) == 1, str(out))
    _assert("concurrent release moved exactly 1000",
            balance_of(min_account(team_ids[1], 4)) == 1000)

    print("  -- no over-release, no playoff release --")
    with SessionLocal() as db:
        # Drain the reserve to just under one week's amount.
        ledger_post([(min_reserve_account(team_ids[2]), -13_500),
                     (expired_min_account(team_ids[2]), 13_500)],
                    door="test_drain", session=db)
        db.commit()
    with SessionLocal() as db:
        err = None
        try:
            release_weekly_minimum(db, league_id=league_id,
                                   team_id=team_ids[2], week=5)
        except WeeklyMinimumError as exc:
            err = exc
        db.rollback()
    _assert("release cannot exceed the remaining reserve",
            err is not None and err.reason == "INSUFFICIENT_RESERVE",
            err.reason if err else "it released")
    _assert("the short reserve is untouched",
            balance_of(min_reserve_account(team_ids[2])) == 500)

    with SessionLocal() as db:
        err = None
        try:
            release_weekly_minimum(db, league_id=league_id,
                                   team_id=team_ids[3], week=15)
        except WeeklyMinimumError as exc:
            err = exc
        db.rollback()
    _assert("a playoff week releases nothing",
            err is not None and err.reason == "NOT_APPLICABLE_WEEK",
            err.reason if err else "it released")
    _assert("no min account was created for the playoff week",
            balance_of(min_account(team_ids[3], 15)) == 0)

    # ════ 4. SHARED MIN-FIRST SOURCING ══════════════════════════════════════
    print("\n== shared min-first sourcing: Versus and Pool, one implementation ==")
    from economy import challenge_funding
    _assert("challenge_funding delegates to the shared splitter",
            "plan_spend_split" in
            __import__("inspect").getsource(challenge_funding.plan_source_split))
    import betting.pool_funding as pool_funding
    _assert("pool_funding imports the same shared splitter",
            pool_funding.plan_spend_split is plan_spend_split)

    # A team with 1000 released min and 5000 wallet, spending 2500.
    spender = team_ids[0]
    with SessionLocal() as db:
        ledger_post([("world", -5000), (wallet_account(spender), 5000)],
                    door="buy_in_paid", session=db)
        db.commit()
    with SessionLocal() as db:
        split = plan_spend_split(db, spender, 3, 2500)
        db.rollback()
    _assert("the splitter drains min first, then wallet",
            split == [(min_account(spender, 3), 1000),
                      (wallet_account(spender), 1500)], str(split))

    # Versus entry point: the real funding splitter used by challenge funding.
    with SessionLocal() as db:
        versus_split = challenge_funding.plan_source_split(db, spender, 3, 2500)
        db.rollback()
    _assert("the Versus entry point returns the identical ordered legs",
            versus_split == split, str(versus_split))

    print("  -- Pool weekly contribution, measured from real ledger legs --")
    from betting.pool_funding import collect_weekly_entries
    from test_support_s4_pool import (
        FOUR_TEAM_KEYS, PROVIDER, mark_ready, seed_catalog,
    )
    from db.schema import NflSchedule
    from datetime import datetime, timedelta, timezone as _tz

    pool_league, pool_teams = make_league("pool-source")
    with SessionLocal() as db:
        activate_season_allocation(pool_league, db)
    with SessionLocal() as db:
        seed_catalog(db)
        mark_ready(db, league_id=pool_league, keys=FOUR_TEAM_KEYS)
        kickoff = (datetime.now(_tz.utc) + timedelta(days=2)).replace(
            hour=17, minute=0, second=0, microsecond=0, tzinfo=None)
        db.add(NflSchedule(season=SEASON, week=3, home_team="HS5",
                           away_team="AS5", kickoff_utc=kickoff))
        db.commit()
    # Release 60 cents of min for one team only; the Pool entry is 100 cents,
    # so that team must source 60 from min and 40 from wallet while the others
    # source entirely from wallet.
    partial_team = pool_teams[0]
    with SessionLocal() as db:
        ledger_post([(min_reserve_account(partial_team), -60),
                     (min_account(partial_team, 3), 60)],
                    door="weekly_minimum_release", session=db)
        for t in pool_teams:
            ledger_post([("world", -10_000), (wallet_account(t), 10_000)],
                        door="buy_in_paid", session=db)
        db.commit()

    with SessionLocal() as db:
        collect_weekly_entries(db, league_id=pool_league, week=3,
                               provider=PROVIDER)
        db.commit()

    pool_legs = legs_of("pool_weekly_collection")
    partial_min = [(a, v) for a, v in pool_legs
                   if a == min_account(partial_team, 3)]
    partial_wallet = [(a, v) for a, v in pool_legs
                      if a == wallet_account(partial_team)]
    _assert("Pool sourced 60 cents from min: first",
            partial_min == [(min_account(partial_team, 3), -60)],
            str(partial_min))
    _assert("Pool sourced the remaining 40 cents from wallet",
            partial_wallet == [(wallet_account(partial_team), -40)],
            str(partial_wallet))
    _assert("the fully-funded teams sourced entirely from wallet",
            all(any(a == wallet_account(t) and v == -100 for a, v in pool_legs)
                for t in pool_teams[1:]))
    _assert("the Pool collection posting still balances",
            sum(v for _, v in pool_legs) == 0)
    _assert("that team's min is now empty",
            balance_of(min_account(partial_team, 3)) == 0)
    _assert("trial balance is zero", trial_balance() == 0)

    # ════ 5. WEEKLY EXPIRY ══════════════════════════════════════════════════
    print("\n== weekly minimum expiry at Week Close ==")
    league_id, team_ids = make_league("expiry")
    with SessionLocal() as db:
        activate_season_allocation(league_id, db)
        db.commit()
    with SessionLocal() as db:
        release_week(db, league_id=league_id, week=3)
        db.commit()
    committed_team = team_ids[0]
    with SessionLocal() as db:
        # Spend 400 of one team's min into escrow — committed money that must be
        # structurally unreachable by expiry.
        ledger_post([(min_account(committed_team, 3), -400),
                     ("escrow:s5probe", 400)],
                    door="wager_placed", session=db)
        ledger_post([("world", -2_500), (wallet_account(committed_team), 2_500)],
                    door="buy_in_paid", session=db)
        db.commit()
    wallet_before = balance_of(wallet_account(committed_team))
    escrow_before = balance_of("escrow:s5probe")

    with SessionLocal() as db:
        results = expire_week(db, league_id=league_id, week=3)
        db.commit()
    _assert("every team expired exactly once",
            len(results) == len(team_ids)
            and all(not r.replayed for r in results))
    _assert("the committed team expired only its UNSPENT 600",
            balance_of(expired_min_account(committed_team)) == 600,
            str(balance_of(expired_min_account(committed_team))))
    _assert("its min account is now empty",
            balance_of(min_account(committed_team, 3)) == 0)
    _assert("escrow-committed cents were untouched",
            balance_of("escrow:s5probe") == escrow_before)
    _assert("Wallet is unchanged by expiry",
            balance_of(wallet_account(committed_team)) == wallet_before)
    _assert("an untouched team expired its full 1000",
            balance_of(expired_min_account(team_ids[1])) == 1000)
    _assert("trial balance is zero", trial_balance() == 0)

    with SessionLocal() as db:
        again = expire_week(db, league_id=league_id, week=3)
        db.commit()
    _assert("retrying Week Close is a no-op",
            all(r.replayed for r in again), str([r.replayed for r in again]))
    _assert("no second expiry moved anything",
            balance_of(expired_min_account(team_ids[1])) == 1000)

    with SessionLocal() as db:
        release_weekly_minimum(db, league_id=league_id, team_id=team_ids[2],
                               week=4)
        db.commit()
    # This team already expired week 3's 1000 in expire_week above, so the
    # concurrency claim is about the DELTA this race produces, not the absolute
    # balance. Measuring the absolute would silently pass or fail on unrelated
    # earlier history.
    expired_before_race = balance_of(expired_min_account(team_ids[2]))

    def expire_once():
        with SessionLocal() as db:
            r = expire_weekly_minimum(db, league_id=league_id,
                                      team_id=team_ids[2], week=4)
            db.commit()
            return r

    out = run_concurrent(expire_once, expire_once)
    ok = [v for k, v in out.values() if k == "ok"]
    _assert("concurrent expiry produces exactly one expiry",
            len(ok) == 1, str(out))
    _assert("concurrent expiry moved exactly 1000 once",
            balance_of(expired_min_account(team_ids[2]))
            - expired_before_race == 1000,
            f"delta {balance_of(expired_min_account(team_ids[2])) - expired_before_race}")
    _assert("concurrent expiry drained the week-4 min exactly once",
            balance_of(min_account(team_ids[2], 4)) == 0)
    _assert("trial balance is zero", trial_balance() == 0)

    # ════ 6. CRASH / RETRY ══════════════════════════════════════════════════
    print("\n== crash before commit leaves no durable effect ==")
    league_id, team_ids = make_league("crash")
    with SessionLocal() as db:
        activate_season_allocation(league_id, db)
        db.commit()
    crash_team = team_ids[0]

    reserve_before = balance_of(min_reserve_account(crash_team))
    with SessionLocal() as db:
        release_weekly_minimum(db, league_id=league_id, team_id=crash_team,
                               week=6)
        db.rollback()          # the crash
    _assert("release: a crash before commit released nothing",
            balance_of(min_account(crash_team, 6)) == 0
            and balance_of(min_reserve_account(crash_team)) == reserve_before)
    with SessionLocal() as db:
        _assert("release: no event row survives the crash",
                db.query(EconomyEvent).filter(
                    EconomyEvent.event_type == "WEEKLY_MINIMUM_RELEASE",
                    EconomyEvent.week == 6).count() == 0)
        db.rollback()

    with SessionLocal() as db:
        release_weekly_minimum(db, league_id=league_id, team_id=crash_team,
                               week=6)
        db.commit()
    _assert("release: the retry after the crash succeeds exactly once",
            balance_of(min_account(crash_team, 6)) == 1000)

    with SessionLocal() as db:
        expire_weekly_minimum(db, league_id=league_id, team_id=crash_team,
                              week=6)
        db.rollback()          # the crash
    _assert("expiry: a crash before commit expired nothing",
            balance_of(min_account(crash_team, 6)) == 1000
            and balance_of(expired_min_account(crash_team)) == 0)
    with SessionLocal() as db:
        expire_weekly_minimum(db, league_id=league_id, team_id=crash_team,
                              week=6)
        db.commit()
    _assert("expiry: the retry after the crash expires exactly once",
            balance_of(expired_min_account(crash_team)) == 1000
            and balance_of(min_account(crash_team, 6)) == 0)

    league_id, team_ids = make_league("crash-alloc")
    with SessionLocal() as db:
        try:
            activate_season_allocation(league_id, db)
        finally:
            db.rollback()
    # activate_season_allocation owns its transaction and commits internally, so
    # the rollback above is a no-op on the committed rows. The meaningful crash
    # proof is that a REPLAY after it issues nothing further.
    issued_after = balance_of(season_issuance_account(league_id, SEASON))
    with SessionLocal() as db:
        activate_season_allocation(league_id, db)
    _assert("allocation: a retry after commit issues nothing further",
            balance_of(season_issuance_account(league_id, SEASON)) == issued_after,
            str(balance_of(season_issuance_account(league_id, SEASON))))
    _assert("trial balance is zero at the end", trial_balance() == 0)


if __name__ == "__main__":
    print("\n=== S5-P1 weekly economy suite (PostgreSQL) ===")
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
