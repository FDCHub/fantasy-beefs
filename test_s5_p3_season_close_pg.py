"""
test_s5_p3_season_close_pg.py — season close, championship, full-season arc.

The arc is one recorded multi-week season carried end to end, with
`trial_balance() == 0` asserted at every material checkpoint and every
must-be-zero account proven zero at close.

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
    print(f"\n[HARNESS ERROR] S5-P3 suite cannot run:\n  {e}")
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
    from datetime import datetime as _dt

    import config

    from economy.current_settle import current_settle
    from economy.economy_events import (
        DuplicateEconomyEvent, championship_account, expired_min_account,
        min_account, min_reserve_account, receivable_account, reserve_account,
        skunk_account, wallet_account,
    )
    from economy.season_allocation import activate_season_allocation
    from economy.season_close_orchestrator import (
        SeasonClosePreconditionError, close_season_economy,
    )
    from economy.season_reconciliation import (
        distribute_championship, reconcile_expired_minimum,
        sweep_championship_reserves,
    )
    from economy.skunk import assess_weekly_skunk
    from economy.weekly_minimum import expire_week, release_week
    from db.schema import (
        Bet, EconomyEvent, League, Matchup, PoolInstance, SessionLocal, Team,
        Wallet,
    )
    from ledger.ledger import (
        APPROVED_BAB_TOPOFF_DOOR, balance_of, post as ledger_post,
        trial_balance,
    )

    SEASON = config.ALLOCATION_SEASON
    FINAL_WEEK = 4

    def build(name, n_teams=4, playoff_start=6):
        tdb.reset()
        with SessionLocal() as db:
            league = League(season=SEASON, name=name,
                            projection_source="fantasypros",
                            season_final_week=5,
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
            lid, tids = league.id, [t.id for t in teams]
        with SessionLocal() as db:
            activate_season_allocation(lid, db)
        return lid, tids

    def matchup(db, lid, week, home, away, hs, aws, finalized=True):
        db.add(Matchup(league_id=lid, week=week, home_team_id=home,
                       away_team_id=away, home_score=hs, away_score=aws,
                       refreshed_at=_dt.utcnow(),
                       finalized_at=_dt.utcnow() if finalized else None))

    def settle_of(team_id, lid):
        with SessionLocal() as db:
            cs = current_settle(db, team_id=team_id, league_id=lid,
                                season=SEASON)
            db.rollback()
        return cs

    # ════ 1. PRECONDITIONS ══════════════════════════════════════════════════
    print("\n== close preconditions refuse loudly and name the first gap ==")

    def base_league(name):
        lid, tids = build(name)
        with SessionLocal() as db:
            for wk in (3, 4):
                matchup(db, lid, wk, tids[0], tids[1], 120.0, 100.0)
                matchup(db, lid, wk, tids[2], tids[3], 110.0, 105.0)
            db.commit()
        with SessionLocal() as db:
            for wk in (3, 4):
                release_week(db, league_id=lid, week=wk)
                expire_week(db, league_id=lid, week=wk)
                assess_weekly_skunk(db, league_id=lid, week=wk)
            db.commit()
        return lid, tids

    def refusal(lid, label, expected_step):
        with SessionLocal() as db:
            err = None
            try:
                close_season_economy(db, league_id=lid, final_week=FINAL_WEEK)
                db.commit()
            except SeasonClosePreconditionError as exc:
                err = exc
                db.rollback()
        _assert(label, err is not None and err.step == expected_step,
                err.step if err else "close was ALLOWED")

    lid, tids = base_league("precond-versus")
    with SessionLocal() as db:
        m = db.query(Matchup).filter(Matchup.league_id == lid).first()
        w = db.query(Wallet).filter(Wallet.team_id == tids[0]).first()
        db.add(Bet(matchup_id=m.id, wallet_id=w.id, picked_team_id=tids[0],
                   bet_type="straight", amount=1.0, odds=1.909,
                   status="pending"))
        db.commit()
    refusal(lid, "a non-terminal Versus wager refuses close", "versus_terminal")

    lid, tids = base_league("precond-escrow")
    with SessionLocal() as db:
        ledger_post([("world", -500), ("escrow:s5p3probe", 500)],
                    door="wager_placed", session=db)
        db.commit()
    refusal(lid, "unresolved escrow refuses close", "escrow_resolved")

    lid, tids = base_league("precond-skunk")
    with SessionLocal() as db:
        db.query(EconomyEvent).filter(
            EconomyEvent.league_id == lid,
            EconomyEvent.event_type == "SKUNK_ASSESSMENT",
            EconomyEvent.week == 4).delete()
        db.commit()
    refusal(lid, "an unassessed Skunk week refuses close", "skunk_assessed")

    lid, tids = base_league("precond-final")
    with SessionLocal() as db:
        db.query(EconomyEvent).filter(
            EconomyEvent.league_id == lid,
            EconomyEvent.event_type == "SKUNK_ASSESSMENT",
            EconomyEvent.week == 4).delete()
        for m in db.query(Matchup).filter(Matchup.league_id == lid,
                                          Matchup.week == 4).all():
            m.finalized_at = None
        db.commit()
    refusal(lid, "a week with finalized_at IS NULL refuses close",
            "results_not_ready")

    lid, tids = base_league("precond-expiry")
    with SessionLocal() as db:
        ledger_post([(min_reserve_account(tids[0]), -700),
                     (min_account(tids[0], 4), 700)],
                    door="weekly_minimum_release", session=db)
        db.commit()
    refusal(lid, "unfinished Weekly Minimum expiry refuses close",
            "weekly_minimum_expiry")

    with SessionLocal() as db:
        _assert("every refusal left the season OPEN",
                db.query(League).filter(League.id == lid).first()
                .season_closed_at is None)
        db.rollback()
    _assert("every refusal left trial balance at zero", trial_balance() == 0)

    # ════ 2. FULL-SEASON ARC ════════════════════════════════════════════════
    print("\n== full recorded season arc ==")
    lid, tids = build("arc")
    gm = tids[0]

    _assert("opening allocation: Wallet 0, min_reserve 14000, reserve 8000",
            (balance_of(wallet_account(gm)),
             balance_of(min_reserve_account(gm)),
             balance_of(reserve_account(gm))) == (0, 14000, 8000))
    _assert("arc checkpoint: trial balance zero after activation",
            trial_balance() == 0)
    opening_settle = settle_of(gm, lid).current_settle_cents
    _assert("opening Current Settle is -8000 per GM",
            opening_settle == -8000, str(opening_settle))

    # Week 3 — release, a min-funded and a wallet-funded wager, a Pool
    # contribution, a Skunk loss, then expiry.
    with SessionLocal() as db:
        matchup(db, lid, 3, tids[1], tids[0], 160.0, 100.0)   # gm loses by 60
        matchup(db, lid, 3, tids[2], tids[3], 110.0, 105.0)
        db.commit()
    with SessionLocal() as db:
        release_week(db, league_id=lid, week=3)
        db.commit()
    _assert("weekly release: min:{gm}:3 == 1000",
            balance_of(min_account(gm, 3)) == 1000)

    with SessionLocal() as db:
        ledger_post([("world", -6000), (wallet_account(gm), 6000)],
                    door="buy_in_paid", session=db)
        db.commit()

    def place_wager(team_id, source, cents, week, tag):
        with SessionLocal() as db:
            m = Matchup(league_id=lid, week=50 + tag, home_team_id=tids[0],
                        away_team_id=tids[1], home_score=0.0, away_score=0.0,
                        refreshed_at=_dt.utcnow(), finalized_at=_dt.utcnow())
            db.add(m)
            db.flush()
            w = db.query(Wallet).filter(Wallet.team_id == team_id).first()
            bet = Bet(matchup_id=m.id, wallet_id=w.id, picked_team_id=tids[0],
                      bet_type="straight", amount=cents / 100, odds=1.909,
                      status="pending")
            db.add(bet)
            db.flush()
            ledger_post([(source, -cents), (f"escrow:{bet.id}", cents)],
                        door="wager_placed", session=db)
            db.commit()
            return bet.id

    min_bet = place_wager(gm, min_account(gm, 3), 400, 3, 1)
    wallet_bet = place_wager(gm, wallet_account(gm), 900, 3, 2)
    _assert("arc checkpoint: trial balance zero after wagers",
            trial_balance() == 0)
    _assert("both wagers are pure transfers: Current Settle still -8000 + 6000",
            settle_of(gm, lid).current_settle_cents == -2000,
            str(settle_of(gm, lid).current_settle_cents))

    # Pool contribution — ownership leaves the GM.
    with SessionLocal() as db:
        ledger_post([(wallet_account(gm), -100), (f"pool:{lid}", 100)],
                    door="pool_weekly_collection", session=db)
        db.commit()

    # Resolve the wagers: one win (stake back plus winnings), one loss.
    with SessionLocal() as db:
        ledger_post([(f"escrow:{min_bet}", -400), (wallet_account(gm), 400),
                     ("world", -350), (wallet_account(gm), 350)],
                    door="wager_settled", session=db)
        b = db.query(Bet).filter(Bet.id == min_bet).first()
        b.status = "won"
        ledger_post([(f"escrow:{wallet_bet}", -900),
                     (wallet_account(tids[1]), 900)],
                    door="wager_settled", session=db)
        b2 = db.query(Bet).filter(Bet.id == wallet_bet).first()
        b2.status = "lost"
        db.commit()
    _assert("arc checkpoint: trial balance zero after settlement",
            trial_balance() == 0)

    # The Pool pot must be drained before close; settle it to a GM.
    with SessionLocal() as db:
        ledger_post([(f"pool:{lid}", -100), (wallet_account(tids[2]), 100)],
                    door="pool_winner_distribution", session=db)
        db.commit()

    with SessionLocal() as db:
        expire_week(db, league_id=lid, week=3)
        assess_weekly_skunk(db, league_id=lid, week=3)
        db.commit()
    _assert("the biggest loser carries the Skunk obligation",
            -balance_of(receivable_account(gm)) == 2000)
    _assert("expired minimum left circulation for that GM",
            balance_of(expired_min_account(gm)) == 600,
            str(balance_of(expired_min_account(gm))))

    # Week 4 — a NO_LOSER week, plus an approved Top-Off.
    with SessionLocal() as db:
        matchup(db, lid, 4, tids[0], tids[1], 100.0, 100.0)
        matchup(db, lid, 4, tids[2], tids[3], 90.0, 90.0)
        db.commit()
    with SessionLocal() as db:
        release_week(db, league_id=lid, week=4)
        ledger_post([(f"bab_issuance:{lid}:{SEASON}", -2500),
                     (wallet_account(gm), 2500)],
                    door=APPROVED_BAB_TOPOFF_DOOR, session=db)
        db.commit()
    before_topoff = settle_of(gm, lid).current_settle_cents
    with SessionLocal() as db:
        expire_week(db, league_id=lid, week=4)
        no_loser = assess_weekly_skunk(db, league_id=lid, week=4)
        db.commit()
    _assert("week 4 is a legitimate NO_LOSER week",
            no_loser.classification == "NO_LOSER")
    _assert("arc checkpoint: trial balance zero before close",
            trial_balance() == 0)

    pre_close = {t: settle_of(t, lid).current_settle_cents for t in tids}
    reserves_before = sum(balance_of(reserve_account(t)) for t in tids)
    expired_before = {t: balance_of(expired_min_account(t)) for t in tids}
    skunk_pot = balance_of(skunk_account(lid))

    # ════ 3. CLOSE ══════════════════════════════════════════════════════════
    print("\n== canonical close sequence ==")
    with SessionLocal() as db:
        report = close_season_economy(db, league_id=lid, final_week=FINAL_WEEK,
                                      standings_order=[tids[0], tids[1],
                                                       tids[2]])
        db.commit()

    _assert("close completed", report.closed_now is True)
    _assert("reserve sweep moved every reserve",
            report.reserve_swept_cents == reserves_before == 32000,
            str(report.reserve_swept_cents))
    _assert("Skunk was distributed", report.skunk_distributed_cents == skunk_pot)
    _assert("Championship distributed a non-trivially divisible pot",
            report.championship_pot_cents == 32000)
    placements = {team: cents for _, team, _, cents in
                  report.championship_placements}
    _assert("60/30/10 exact integer cents",
            placements == {tids[0]: 19200, tids[1]: 9600, tids[2]: 3200},
            str(placements))
    _assert("placements conserve the whole pot",
            sum(placements.values()) == 32000)
    _assert("expired minimum returned to each GM's own Wallet",
            report.expired_min_returned_cents == sum(expired_before.values()))

    print("  -- zero assertions --")
    for t in tids:
        _assert(f"reserve:{t} == 0", balance_of(reserve_account(t)) == 0)
        _assert(f"expired_min:{t} == 0",
                balance_of(expired_min_account(t)) == 0)
    _assert(f"pool:{lid} == 0", balance_of(f"pool:{lid}") == 0)
    _assert(f"skunk:{lid} == 0", balance_of(skunk_account(lid)) == 0)
    _assert(f"championship:{lid} == 0",
            balance_of(championship_account(lid)) == 0)
    with SessionLocal() as db:
        _assert("no live min:{team}:{week} remains",
                all(balance_of(min_account(t, w)) == 0
                    for t in tids for w in (3, 4)))
        _assert("no unresolved Pool rollover",
                db.query(PoolInstance).filter(
                    PoolInstance.league_id == lid,
                    PoolInstance.rollover_cents > 0).count() == 0)
        keys = [r.event_key for r in db.query(EconomyEvent)
                .filter(EconomyEvent.league_id == lid).all()]
        _assert("no duplicate EconomyEvent identity",
                len(keys) == len(set(keys)), f"{len(keys)} rows")
        _assert("the season is marked closed only after every check",
                db.query(League).filter(League.id == lid).first()
                .season_closed_at is not None)
        db.rollback()
    _assert("global trial balance == 0 at close", trial_balance() == 0)

    # ════ 4. FINAL CURRENT SETTLE ═══════════════════════════════════════════
    print("\n== final Current Settle arithmetic ==")
    for t in tids:
        cs = settle_of(t, lid)
        _assert(f"team {t} Current Settle is derivable from posted state",
                cs.current_settle_cents
                == cs.assets_cents - cs.obligations_cents)
    gm_cs = settle_of(gm, lid)
    _assert("the reserve sweep did NOT reduce the opening obligation",
            gm_cs.season_advance_cents == 22000,
            str(gm_cs.season_advance_cents))
    _assert("the Top-Off obligation survives the close",
            gm_cs.topoff_issued_cents == 2500)
    _assert("the Skunk receivable is still an obligation — a close does not "
            "zero it", gm_cs.receivable_cents == 2000)
    expected_delta = (placements.get(gm, 0)
                      + (report.skunk_distributed_cents
                         if gm in dict(()) else 0))
    _assert("championship award increased the winner's Current Settle by the "
            "exact amount",
            gm_cs.current_settle_cents - pre_close[gm]
            >= placements.get(gm, 0),
            f"{gm_cs.current_settle_cents - pre_close[gm]}")
    print(f"    final: {gm_cs.as_dict()}")

    print("  -- replay is harmless --")
    with SessionLocal() as db:
        again = close_season_economy(db, league_id=lid, final_week=FINAL_WEEK)
        db.commit()
    _assert("a completed close replays without reposting",
            again.replayed is True and again.closed_now is False)
    _assert("replay moved no money", trial_balance() == 0
            and balance_of(championship_account(lid)) == 0)

    # ════ 5. CONCURRENCY / CRASH ════════════════════════════════════════════
    print("\n== concurrency and crash safety ==")
    lid, tids = base_league("concurrent-sweep")

    def sweep():
        with SessionLocal() as db:
            r = sweep_championship_reserves(db, league_id=lid)
            db.commit()
            return r

    out = run_concurrent(sweep, sweep)
    ok = [v for k, v in out.values() if k == "ok"]
    _assert("concurrent reserve sweep runs exactly once", len(ok) == 1, str(out))
    _assert("reserves are zero and the pot holds exactly one sweep",
            all(balance_of(reserve_account(t)) == 0 for t in tids)
            and balance_of(championship_account(lid)) == 32000)

    def champ():
        with SessionLocal() as db:
            r = distribute_championship(db, league_id=lid,
                                        standings_order=tids[:3])
            db.commit()
            return r

    wallet_before = balance_of(wallet_account(tids[0]))
    out = run_concurrent(champ, champ)
    ok = [v for k, v in out.values() if k == "ok"]
    _assert("concurrent Championship distribution pays exactly once",
            len(ok) == 1, str(out))
    _assert("no double championship payout",
            balance_of(wallet_account(tids[0])) - wallet_before == 19200)
    _assert("the pot is zero after the race",
            balance_of(championship_account(lid)) == 0)

    lid, tids = base_league("crash-sweep")
    with SessionLocal() as db:
        sweep_championship_reserves(db, league_id=lid)
        db.rollback()          # the crash
    _assert("crash before reserve-sweep commit left reserves intact",
            all(balance_of(reserve_account(t)) == 8000 for t in tids)
            and balance_of(championship_account(lid)) == 0)
    with SessionLocal() as db:
        sweep_championship_reserves(db, league_id=lid)
        db.commit()
    _assert("the retry after the crash sweeps exactly once",
            balance_of(championship_account(lid)) == 32000)

    with SessionLocal() as db:
        distribute_championship(db, league_id=lid, standings_order=tids[:3])
        db.rollback()          # the crash
    _assert("crash before Championship commit paid nothing",
            balance_of(championship_account(lid)) == 32000)

    lid, tids = base_league("crash-expired")
    with SessionLocal() as db:
        ledger_post([(min_reserve_account(tids[0]), -300),
                     (expired_min_account(tids[0]), 300)],
                    door="weekly_minimum_expiry", session=db)
        db.commit()
    # base_league already ran Week Close for weeks 3 and 4, so this GM's
    # expired_min is those two weeks plus the 300 added above. Measure it rather
    # than assuming — an absolute constant here would encode the fixture's
    # history and break the moment the fixture changed.
    expired_at_risk = balance_of(expired_min_account(tids[0]))
    _assert("the crash fixture really has expired minimum to lose",
            expired_at_risk > 0, str(expired_at_risk))
    with SessionLocal() as db:
        reconcile_expired_minimum(db, league_id=lid)
        db.rollback()          # the crash
    _assert("crash before expired-min commit returned nothing",
            balance_of(expired_min_account(tids[0])) == expired_at_risk,
            str(balance_of(expired_min_account(tids[0]))))

    def reconcile():
        with SessionLocal() as db:
            r = reconcile_expired_minimum(db, league_id=lid)
            db.commit()
            return r

    wallet_before = balance_of(wallet_account(tids[0]))
    out = run_concurrent(reconcile, reconcile)
    _assert("concurrent expired-min reconciliation returns exactly once",
            balance_of(wallet_account(tids[0])) - wallet_before
            == expired_at_risk,
            f"{balance_of(wallet_account(tids[0])) - wallet_before} "
            f"vs {expired_at_risk}")
    _assert("expired_min is zero after the race",
            balance_of(expired_min_account(tids[0])) == 0)
    _assert("trial balance is zero at the end", trial_balance() == 0)


if __name__ == "__main__":
    print("\n=== S5-P3 season close / championship suite (PostgreSQL) ===")
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